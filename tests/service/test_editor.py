"""The electrode editor's run path (``eeglayoutlab.jobs.editor``, phase 2 slice 6).

Ports check-electrode-editor.mjs's result-schema test (:48) and its service test (:68, driven through ``FakeChild``
as Node drives its fake children, with the same context stub). Then what Python adds: the context on synthetic
editor roots (each refusal in Node's order, the B17 identity, the parent's digest, the worker input), the view's
parent digest for every kind of job, the catalogs, the factory, shared capacity with the coordinate evaluation and a
real worker process; and the byte parity of every record the run path writes with Node's own
``ElectrodeEditorService`` (``parity/editor_run.mjs``) on editor roots, where the library, the design context and
the digests are the real ones on both sides.
"""
from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path
import re
import sys

import pytest

from schema_parity_support import require

require('pydantic')

from eeglayoutlab.jobs.design import DesignJob, DesignJobError  # noqa: E402
from eeglayoutlab.jobs.editor import (  # noqa: E402
    EDITOR_CACHE_SCHEMA, GEOMETRY_DIFFERS, NOT_A_PARENT, NOT_INDEPENDENT, PARENT_CHANGED, REPORT_MISMATCH,
    WORKER_SCRIPT, EditorContextError, EditorJobs, editor_jobs,
)
from eeglayoutlab.jobs.editor_records import (  # noqa: E402
    EditorResultError, parents as editor_parents, records as editor_records, validate_editor_result,
)
from eeglayoutlab.jobs.identity import design_context, request_key  # noqa: E402
from eeglayoutlab.jobs.integrity import InputIntegrity  # noqa: E402
from eeglayoutlab.jobs.library import Library  # noqa: E402
from eeglayoutlab.jobs.runtime import runtime_config  # noqa: E402
from eeglayoutlab.jobs.slot import ExecutionSlot, InstallationLock  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402

from .design_support import REQUEST as DESIGN_REQUEST, Fixture, baseline_result, done, record_tree  # noqa: E402
from .editor_support import (  # noqa: E402
    CASE_IDS, EDITOR_CODE, EDITOR_JOBS, METRICS, REPORT, STALE, build, catalog, editor_root, evaluate, parent_records,
    parity_cases, prepare, prepare_result, run_node_cases, run_python, tampered_report, worker_root,
)
from .key_parity_support import EDITOR_ACCEPTED, digest, needs_node  # noqa: E402
from .radius_support import SETTLE, Spawner, until  # noqa: E402


def run(coroutine):
    return asyncio.run(coroutine)


def _parse(path: Path) -> object:
    return jsjson.parse(Path(path).read_text(encoding='utf-8'))


# --- check-electrode-editor.mjs -------------------------------------------------------------------------------------

PARENT, DIGEST = 'a' * 64, 'b' * 64
XYZ = [[i * 5, 0, 0] for i in range(64)]
LABELS = [int(i >= 32) for i in range(64)]


def node_request() -> dict:
    """``request()``: every slot of ``initialSlots(domain)`` (the 64 original indices) enabled."""
    return {'action': 'evaluate', 'parent_id': PARENT, 'parent_digest': DIGEST, 'seed': 2026,
            'slots': [{'bank_index': i, 'enabled': True} for i in range(64)]}


def node_result(request: dict) -> dict:
    """``result(r)``."""
    return {'schema': 'electrode-editor/1', 'status': 'completed', 'request': request, 'electrode_count': 64,
            'active_slots': list(range(64)), 'evaluated_xyz_mm': XYZ, 'region_indices': LABELS,
            'minimum_distance_mm': 5, 'baseline': METRICS, 'parent_metrics': METRICS, 'edited_metrics': METRICS}


def test_result_schema_rejects_stale_requests_malformed_geometry_and_fabricated_combined_score(tmp_path):
    """check-electrode-editor.mjs:48, through ``validateEditorResult`` and the service's ``validate``."""
    service = EditorJobs(str(tmp_path), 'python')
    r = node_request()
    validate_editor_result(node_result(r), r)
    service.validate(node_result(r), r)
    for patch in ({'electrode_count': 63}, {'minimum_distance_mm': 0}, {'active_slots': [1] * 64},
                  {'edited_metrics': {**METRICS, 'conditional_global': .8}}):
        with pytest.raises(EditorResultError):
            validate_editor_result({**node_result(r), **patch}, r)
        with pytest.raises(EditorResultError):
            service.validate({**node_result(r), **patch}, r, {'sha256': 'x'})
    # A stale request: the result of another request is not this one's.
    stale = {**r, 'parent_digest': 'e' * 64}
    with pytest.raises(EditorResultError, match='^Editor result identity mismatch$'):
        service.validate(node_result(stale), r)


def test_editor_shares_capacity_caches_completed_results_and_retains_capacity_while_cancelling(tmp_path):
    """check-electrode-editor.mjs:68: the coordinate evaluation's permit is the editor's (busy, no child), a
    completed result is cached (a hit needs no permit), and a cancelled job keeps the permit until its process
    closes and saves nothing. Python also checks the permit from the coordinate evaluation's side."""
    async def scenario():
        slot = ExecutionSlot(InstallationLock(str(tmp_path)))
        children: list = []
        service = EditorJobs(str(tmp_path), 'python', {}, spawn=Spawner(children=children), execution_slot=slot)
        identity = {'schema': 'test'}

        async def context(request):
            return {'identity': identity, 'key': jsjson.sha256_hex({'request': request, 'identity': identity}),
                    'parent': {'id': PARENT}, 'parent_digest': DIGEST}
        service.context = context
        design = Fixture(tmp_path, execution_slot=slot)
        try:
            release_design = slot.acquire('existing')
            assert (await service.submit(node_request()))['busy'] is True
            assert len(children) == 0
            release_design()
            first = await service.submit(node_request())
            assert len(children) == 1
            assert (await design.service.submit(DESIGN_REQUEST))['busy'] is True  # one permit for both services
            children[0].stdout(jsjson.stringify({'type': 'result', 'result': node_result(node_request())}) + '\n')
            children[0].close(0)
            await done(service)
            assert service.jobs[first['job']['id']].status == 'completed'
            release_other = slot.acquire('other')
            assert (await service.submit(node_request()))['job']['cached'] is True
            assert len(children) == 1
            release_other()
            following = node_request()
            following['slots'][0]['enabled'] = False
            second = await service.submit(following)
            service.cancel(second['job']['id'])
            assert service.active is not None
            assert (await design.service.submit(DESIGN_REQUEST))['busy'] is True  # still held while cancelling
            children[1].close(0)
            await done(service)
            assert service.jobs[second['job']['id']].status == 'cancelled'
            assert service.jobs[second['job']['id']].result is None
            cache = _parse(Path(service.store.path(service.record_kind, first['job']['key'], 'cache.json')))
            assert cache['result']['electrode_count'] == 64
            # Python: the cancelled job saved nothing, and the permit is free again for the design evaluation.
            assert not Path(service.store.path(service.record_kind, second['job']['key'], 'cache.json')).exists()
            assert children[1].kills == ['SIGTERM']
            assert (await design.service.submit(DESIGN_REQUEST))['job']['status'] == 'running'
            design.children[0].complete(baseline_result())
            await done(design.service)
            assert not slot.busy and not slot.lock.held
        finally:
            service.dispose()
            design.service.dispose()
    run(scenario())


# --- The context on editor roots --------------------------------------------------------------------------------------

@pytest.fixture(scope='module')
def base(tmp_path_factory):
    """An editor root with its parents; nothing changes it."""
    return editor_root(tmp_path_factory.mktemp('editor-base'))


def _service(built: dict, python: str = 'python3', **options) -> EditorJobs:
    config = runtime_config(built['root'], python, env={})
    return EditorJobs(config.repository_root, config.native_python, Library(config.repository_root, config),
                      **options)


def _context(service: EditorJobs, request: dict) -> dict:
    return run(service.context(request))


def test_the_context_refuses_each_parent_in_nodes_order(base):
    service = _service(base)
    ids = base['ids']
    records = parent_records(base['root'], ids, 'python3')
    for name in ('missing', 'historical', 'offline', 'design', 'strict-no-layout', 'cache-unpatched',
                 'cache-zero-patches', 'cache-no-layout'):
        with pytest.raises(EditorContextError, match=f'^{NOT_A_PARENT}$'):
            _context(service, prepare(ids[name]))
    assert records['missing'] is None and records['cache-zero-patches'] is None  # the library refused it
    assert records['design']['dataset_id'] == 'design_evaluation' and records['offline']['status'] == 'completed'
    # The record, then the noise model, then the digest: a stale digest of a refused parent names the parent.
    with pytest.raises(EditorContextError, match=f'^{NOT_INDEPENDENT}$'):
        _context(service, evaluate(ids['cache-spatial'], STALE))
    with pytest.raises(EditorContextError, match=f'^{NOT_A_PARENT}$'):
        _context(service, evaluate(ids['missing'], STALE))
    with pytest.raises(EditorContextError, match=f'^{PARENT_CHANGED}$'):
        _context(service, evaluate(ids['cache'], STALE))
    for name in ('cache-geometry', 'cache-admission'):
        with pytest.raises(EditorContextError, match=f'^{GEOMETRY_DIFFERS}$'):
            _context(service, prepare(ids[name]))
    # A refusal is a 400 in the routes, as Node's plain Error.
    assert issubclass(EditorContextError, DesignJobError)
    for name in EDITOR_ACCEPTED:
        assert _context(service, prepare(ids[name]))['parent'] == records[name]


def test_the_context_extends_the_design_identity_with_the_parent_and_the_editors_code(base):
    """B17: the design context's identity with ``schema`` overwritten in its first position and the parent's digest
    and the editor's digests appended; the key is ``sha256({request, identity})``; the worker reads the request and
    the parent's full library record."""
    service = _service(base)
    ids = base['ids']
    parent = parent_records(base['root'], ids, 'python3')['cache']
    request = evaluate(ids['cache'], jsjson.sha256_hex(parent))
    context = _context(service, request)
    design = design_context(service.root, service.python, InputIntegrity(service.root), request)
    assert list(context) == ['identity', 'admission', 'key', 'parent', 'parent_digest']
    assert list(context['identity']) == [*design.identity, 'parent_digest', 'editor_sha256',
                                         'editor_implementation_sha256']
    assert context['identity'] == {**design.identity, 'schema': EDITOR_CACHE_SCHEMA,
                                   'parent_digest': jsjson.sha256_hex(parent),
                                   'editor_sha256': digest('editor worker'),
                                   'editor_implementation_sha256': {EDITOR_CODE: digest('editor code')}}
    assert context['admission'] == design.admission
    assert (context['parent'], context['parent_digest']) == (parent, request['parent_digest'])
    assert context['key'] == request_key(request, context['identity'])
    job = DesignJob('id', context['key'], 'running', 0, '', request=request, ctx=context)
    assert jsjson.stringify(service.worker_input(job)) == jsjson.stringify({'request': request, 'parent': parent})
    # A preparation has no digest to check; its key differs, its identity is the same.
    prepared = _context(service, prepare(ids['cache']))
    assert prepared['identity'] == context['identity'] and prepared['key'] != context['key']
    # The strict-area parent's geometry is its report's.
    strict = _context(service, prepare(ids['strict']))
    assert strict['parent']['provenance']['file'] == REPORT and 'geometry_sha256' not in strict['parent']['provenance']


def test_the_library_may_be_a_factory_or_answer_asynchronously(base):
    records = parent_records(base['root'], base['ids'], 'python3')
    made = []

    class Async:
        async def get(self, id):
            return {v['id']: v for v in records.values() if v}.get(id)

    def factory():
        made.append(1)
        return Async()

    config = runtime_config(base['root'], 'python3', env={})
    service = EditorJobs(config.repository_root, config.native_python, factory)
    assert not made
    context = _context(service, prepare(base['ids']['strict-2']))
    assert context['parent'] == records['strict-2'] and made == [1]
    _context(service, prepare(base['ids']['cache']))
    assert made == [1]


def test_a_rewritten_report_fails_the_strict_parents_identity(tmp_path):
    """A same-size rewrite with its times given back: the library keeps the layout it read, the report's digest is
    computed again (its change time differs), so the editor refuses the parent; a fresh library refuses the report
    itself."""
    built = editor_root(tmp_path)
    service = _service(built)
    request = prepare(built['ids']['strict'])
    _context(service, request)
    path = Path(built['tree'], REPORT)
    before = path.stat()
    path.write_text(tampered_report(), encoding='utf-8')
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(EditorContextError, match=f'^{REPORT_MISMATCH}$'):
        _context(service, request)
    with pytest.raises(EditorContextError, match=f'^{NOT_A_PARENT}$'):
        _context(_service(built), request)


def test_editor_jobs_builds_the_service_of_a_runtime(base):
    config = runtime_config(base['root'], 'python3', env={})
    service = editor_jobs(config)
    assert (service.root, service.python, service.record_kind, service.script_name) == (
        config.repository_root, config.native_python, 'editor', WORKER_SCRIPT)
    assert isinstance(service.library, Library) and service.library.root == config.repository_root
    given = object()
    assert editor_jobs(config, given).library is given


# --- The view, the catalogs -------------------------------------------------------------------------------------------

def test_the_view_adds_the_parent_digest_of_the_context_or_of_the_result(tmp_path):
    """``view(j)``: ``j.ctx?.parent_digest``, else ``hash(j.result.parent)`` (a preparation echoes its parent), else
    ``j.result?.request?.parent_digest``; a job with none leaves it out of the JSON."""
    service = EditorJobs(str(tmp_path), 'python3')
    request = node_request()
    running = DesignJob('a', 'k', 'running', 0, 'm', None, request=request, ctx={'parent_digest': DIGEST})
    assert service.view(running) == {'id': 'a', 'key': 'k', 'status': 'running', 'message': 'm', 'progress': 0,
                                     'result': None, 'cached': False, 'parent_digest': DIGEST}
    prepared = prepare_result(prepare(PARENT))
    cached = DesignJob('b', 'k', 'completed', 1, 'done', prepared, cached=True)
    assert service.view(cached)['parent_digest'] == jsjson.sha256_hex(prepared['parent'])
    evaluated = DesignJob('c', 'k', 'completed', 1, 'done', node_result(request), cached=True)
    assert service.view(evaluated)['parent_digest'] == DIGEST
    failed = DesignJob('d', 'k', 'failed', 0, 'x', None, request=request, ctx={'identity': {}})
    assert 'parent_digest' not in service.view(failed)
    assert service.view(DesignJob('e', 'k', 'completed', 1, 'x', {'parent': 0, 'request': None},
                                  cached=True)) == {'id': 'e', 'key': 'k', 'status': 'completed', 'message': 'x',
                                                    'progress': 1, 'result': {'parent': 0, 'request': None},
                                                    'cached': True}
    odd = DesignJob('f', 'k', 'completed', 1, 'x', {'parent': None, 'request': {'parent_digest': 1}}, cached=True)
    assert service.view(odd)['parent_digest'] == 1


def test_records_and_parents_are_the_catalogs_of_slice_3(base, tmp_path):
    service = _service(base)
    assert service.parents() == editor_parents(service.library)
    rows = service.parents()
    ids = base['ids']
    # The catalog offers what the context may still refuse: another region geometry or surface admission.
    assert {row['id'] for row in rows if row['dataset_id'] == 'cache'} == {
        ids[name] for name in ('cache', 'cache-prior', 'cache-other-code', 'cache-geometry', 'cache-admission')}
    strict = {row['id'] for row in rows if row['dataset_id'] == 'strict_area'}
    assert len(strict) == 29 and {ids['strict'], ids['strict-2'], ids['strict-null-localization']} <= strict
    assert service.records() == editor_records(service.store) == []


# --- A real worker process --------------------------------------------------------------------------------------------

def test_a_real_worker_process_prepares_evaluates_fails_and_stops_through_the_transport(tmp_path):
    """The worker as Node runs it, ``python -u R/scripts/electrode_editor.py`` in R with ``{request, parent}`` on
    stdin, on an editor root with the real library and context: a preparation and an evaluation with their records,
    a worker error, a stale result and a cancelled worker; no process group outlives its job."""
    built = worker_root(tmp_path)
    root, ids = Path(built['tree']), built['ids']

    async def scenario():
        config = runtime_config(built['root'], sys.executable, env={})
        service = EditorJobs(built['root'], sys.executable, Library(config.repository_root, config),
                             timeout_ms=60000)
        try:
            records = parent_records(built['root'], ids, sys.executable)
            first = await service.submit(prepare(ids['cache']))
            pid = service.active_pid()
            assert isinstance(pid, int)
            await done(service)
            job = service.jobs[first['job']['id']]
            assert (job.status, job.message, job.progress, job.stderr) == (
                'completed', '设计评价已完成并保存', 1, 'editor stderr\n')
            parent = records['cache']
            assert job.result['parent'] == {'id': ids['cache'], 'region_count': 2, 'label': parent['label']}
            assert [len(region['bank_indices']) for region in job.result['regions']] == [32, 32]
            with pytest.raises(ProcessLookupError):
                os.killpg(pid, 0)
            cache = _parse(root / EDITOR_JOBS / job.key / 'cache.json')
            assert list(cache) == ['key', 'identity', 'result', 'result_sha256', 'finished_at']
            assert (cache['key'], cache['result']) == (job.key, job.result)
            assert cache['identity']['parent_digest'] == jsjson.sha256_hex(parent)
            assert job.key == request_key(prepare(ids['cache']), cache['identity'])
            assert _parse(Path(job.batch) / 'request.json') == {'request': prepare(ids['cache']),
                                                                'identity': cache['identity']}
            view = service.view(job)
            assert view['parent_digest'] == jsjson.sha256_hex(parent)
            assert _parse(Path(job.batch) / 'job.json') == {**view, 'stderr': 'editor stderr\n'}
            hit = await service.lookup(prepare(ids['cache']))
            assert hit['hit'] is True and hit['job']['parent_digest'] == jsjson.sha256_hex(parent)

            request = evaluate(ids['cache'], jsjson.sha256_hex(parent), (3, 40))
            evaluated = await service.submit(request)
            await done(service)
            job = service.jobs[evaluated['job']['id']]
            assert (job.status, job.result['electrode_count'], job.result['parent_label']) == (
                'completed', 62, parent['label'])
            cached = await service.submit(request)
            assert (cached['job']['cached'], cached['job']['parent_digest']) == (True, request['parent_digest'])

            (root / 'editor-mode.txt').write_text('fail', encoding='utf-8')
            failing = await service.submit(prepare(ids['strict']))
            await done(service)
            job = service.jobs[failing['job']['id']]
            assert (job.status, job.message, job.result) == ('failed', '编辑评价失败', None)
            assert 'Traceback: boom' in job.stderr and not (root / EDITOR_JOBS / job.key / 'cache.json').exists()

            (root / 'editor-mode.txt').write_text('stale', encoding='utf-8')
            stale = await service.submit(prepare(ids['strict-2']))
            await done(service)
            job = service.jobs[stale['job']['id']]
            assert (job.status, job.message) == ('failed', 'Editor result identity mismatch')

            (root / 'editor-mode.txt').write_text('hold', encoding='utf-8')
            held = await service.submit(prepare(ids['cache-prior']))
            job = service.jobs[held['job']['id']]
            pid = service.active_pid()
            await until(lambda: job.progress == 0.25)
            assert job.message == '读取父布局'
            service.cancel(job.id)
            await done(service)
            assert (job.status, job.message) == ('cancelled', '计算已停止')
            with pytest.raises(ProcessLookupError):
                os.killpg(pid, 0)
            assert not service.execution_slot.busy and not service.execution_slot.lock.held
            assert [row['key'] for row in service.records()] == [service.jobs[evaluated['job']['id']].key]
        finally:
            # A failed step must not leave the held worker behind: dispose stops it before the loop closes.
            await asyncio.wait_for(service.aclose(), SETTLE)
    run(scenario())


# --- Parity with Node's run path -------------------------------------------------------------------------------------

_TEMPORARY = re.compile(r'\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.tmp')


@pytest.fixture(scope='module')
def node_run(tmp_path_factory):
    """Node's ``ElectrodeEditorService`` over every case once; each root is then moved to ``root.node``."""
    base = tmp_path_factory.mktemp('editor-run')
    parents = catalog(base / 'catalog')
    cases = parity_cases(base, parents)
    for case in cases:
        build(case)
    output = run_node_cases(cases, base)
    for case in cases:
        Path(case['root']).rename(Path(case['root']).with_name('root.node'))
    return {case['id']: (case, theirs) for case, theirs in zip(cases, output['cases'])}, parents


def _masked(records: list) -> list:
    """The records with the random part of temporary names masked (a failed write names its temporary)."""
    return [[kind, _TEMPORARY.sub('.<uuid>.tmp', text)] for kind, text in records]


@needs_node
@pytest.mark.parametrize('id', CASE_IDS)
def test_run_path_writes_the_bytes_and_reports_the_states_of_node(node_run, id):
    """Parity of slice 6: given the same worker output, clock and job identifiers, the editor's run path returns
    Node's views (with their parent digests), refusals and errors (as JSON text), spawns the worker as Node does
    (executable, arguments, cwd, stdio, shell, thread settings, inherited environment, stdin bytes: the request and
    the parent's record, signals) and leaves the same record tree under results/v2/electrode_editor_jobs:
    request.json, job.json and cache.json byte for byte, no temporaries. The one difference is B16's: in
    ``publish-once`` the valid cache.json another workspace wrote first stays here, where Node replaces it."""
    case, theirs = node_run[0][id]
    build(case)  # the same root, at the same path, again
    ours = run_python(case)
    assert len(ours['records']) == len(theirs['records'])
    for index, (mine, node) in enumerate(zip(_masked(ours['records']), _masked(theirs['records']))):
        assert mine == node, (index, case['steps'][min(index, len(case['steps']) - 1)][0])
    assert (ours['clock'], ours['ids']) == (theirs['clock'], theirs['ids'])
    assert ours['children'] == theirs['children']
    node_root = Path(case['root']).with_name('root.node')
    mine, node = record_tree(Path(case['root']), EDITOR_JOBS), record_tree(node_root, EDITOR_JOBS)
    if id == 'publish-once':
        key = jsjson.parse(theirs['records'][0][1])['job']['key']
        kept = jsjson.parse(mine.pop(f'{key}/cache.json').decode('utf-8'))
        replaced = jsjson.parse(node.pop(f'{key}/cache.json').decode('utf-8'))
        assert kept['finished_at'] == '2026-01-01T00:00:00.000Z' != replaced['finished_at']
        assert {**kept, 'finished_at': None} == {**replaced, 'finished_at': None}
    assert mine == node
    assert not [name for name in node if name.endswith('.tmp')]
    design = 'results/v2/design_evaluation_jobs'  # the parent evaluation's records, as built: never written
    assert record_tree(Path(case['root']), design) == record_tree(node_root, design)


@needs_node
def test_the_parity_cases_reach_every_outcome_of_the_run_path(node_run):
    cases, parents = node_run
    texts = ''.join(text for _, theirs in cases.values() for _, text in theirs['records'])
    statuses = set(re.findall(r'"status":"([a-z_]+)"', texts))
    assert {'running', 'cancelling', 'completed', 'failed', 'timeout', 'cancelled'} <= statuses
    for message in ('准备本地坐标评价', '正在停止计算', '达到0分钟计算时限，未保存未完成结果', '计算已停止',
                    '计算未完成，错误记录已保存', '设计评价已完成并保存', '设计评价已完成"', '计算期间输入或代码发生变化',
                    '"busy":true,"maintenance":false', 'spawn EINVAL', 'expected new calculation',
                    'spawn python3 ENOENT',
                    NOT_A_PARENT, NOT_INDEPENDENT, PARENT_CHANGED, REPORT_MISMATCH, GEOMETRY_DIFFERS,
                    'Editor result identity mismatch', 'Invalid editor region data', 'Invalid edited electrode count',
                    'Stable electrode identities changed', 'Invalid edited geometry', 'Missing field metric',
                    'Invalid editor metric', 'Invalid editor decision score',
                    "Cannot read properties of null (reading 'bank_indices')",
                    "Cannot read properties of null (reading 'length')", 'r.regions.some is not a function',
                    'Invalid editor request', 'Invalid preparation fields', 'Invalid editor protocol',
                    'Invalid stable electrode slots', 'At least two active electrodes are required',
                    '"cached":true', '{"hit":false}', '"hit":true', '[object Object]', 'Infinity'):
        assert message in texts, message
    if os.geteuid() != 0:
        assert 'EACCES: permission denied, open' in texts
    children = [child for _, theirs in cases.values() for child in theirs['children']]
    assert {tuple(child['kills']) for child in children} >= {(), ('SIGTERM',)}
    # The parent's record goes to the worker; a hit's view takes its parent digest from the result.
    first = jsjson.parse(base64.b64decode(children[0]['input']).decode('utf-8'))
    assert list(first) == ['request', 'parent'] and first['parent']['id'] == parents['ids']['cache']
    assert jsjson.sha256_hex(first['parent']) == parents['digests']['cache']
    views = [jsjson.parse(text) for kind, text in cases['prepare-done'][1]['records'] if kind == 'submit']
    hit = next(view['job'] for view in views if view.get('job', {}).get('cached'))
    assert hit['parent_digest'] == jsjson.sha256_hex(hit['result']['parent']) != parents['digests']['cache']
    views = [jsjson.parse(text) for kind, text in cases['evaluate-done'][1]['records'] if kind == 'submit']
    hit = next(view['job'] for view in views if view.get('job', {}).get('cached'))
    assert hit['parent_digest'] == parents['digests']['cache']
