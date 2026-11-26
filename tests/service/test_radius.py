"""The radius search (``eeglayoutlab.jobs.radius``): its identity and stored results (phase 2 slice 3) and its run
path (slice 4).

Ports check-local-compute.mjs's result validation test and checks ``validate_worker_result`` against Node's
``validateWorkerResult`` message by message; ``code_identity``, ``radius_identity`` and ``RadiusCache`` are checked
here on their own (their parity with Node's ``identityFor`` on synthetic and linked roots is in test_library.py).

The run path, ``RadiusJobs``: the queue tests of check-local-compute.mjs (:72, :86, and :97, :106 and :111 on the
service itself), driven through ``FakeChild`` as Node drives its fake children; the permit, the installation lock,
the publish-once rule, the completion callbacks and a real worker process; the byte parity of every record the run
path writes with Node's own ``LocalComputeQueue`` (``parity/radius_run.mjs``); and, with ``EEG_KEY_PARITY_ROOT``,
check-lab-workflow.mjs:25 on that installation, read only.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from schema_parity_support import require

require('pydantic')

from eeglayoutlab.jobs import radius as radius_module  # noqa: E402
from eeglayoutlab.jobs.identity import DATA_PRIOR_FILES, request_key  # noqa: E402
from eeglayoutlab.jobs.library import Library  # noqa: E402
from eeglayoutlab.jobs.radius import (  # noqa: E402
    CODE_FILES, RADIUS_IDENTITY_VERSION, WORKER_ENV, WORKER_SCRIPT, RadiusCache, RadiusJobError, RadiusJobs,
    RadiusResultError, code_identity, radius_identity, validate_worker_result,
)
from eeglayoutlab.jobs.records import error_code  # noqa: E402
from eeglayoutlab.jobs.runtime import runtime_config  # noqa: E402
from eeglayoutlab.jobs.slot import InstallationLock, execution_lock_path  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402

from .key_parity_support import NODE_ENV, PRIOR, needs_node  # noqa: E402
from .library_support import (  # noqa: E402
    CODE_NAMES, WEBAPP, code_tree, forward_inputs, radius_result, sha, write, write_cache,
)
from .radius_support import (  # noqa: E402
    OTHER, TIMEOUT_CASE_MS, FakeChild, Spawner, build, make_jobs, parity_cases, record_tree, result_for as run_result,
    run_node, run_python, until,
)

REQUEST = {'region_count': 2, 'radius_mm': 35, 'mode': 'preset', 'mask_codes': ['PL', 'PR']}


def result_for(config: dict = REQUEST) -> dict:
    """``resultFor(config)`` of check-local-compute.mjs (the reference coordinates are the same list)."""
    xyz = [[i * 5.0, 0.0, 0.0] for i in range(64)]
    regions = config['region_count']
    labels = [min(regions - 1, i * regions // 64) for i in range(64)]
    return {'status': 'completed', 'request': config,
            'layout': {'id': 'fixture', 'xyzMm': xyz, 'referenceXyzMm': xyz, 'regionIndices': labels},
            'geometry': {'union_connected_component_count': regions, 'common_graph_radius_mm': config['radius_mm'],
                         'union_area_cm2': 30},
            'metrics': {'field_relative': 0.8, 'sensitivity_tail': 0.3, 'localization_relative': 0.5,
                        'conditional_global': 0.3}}


def test_result_validation_rejects_stale_request_duplicated_points_wrong_components_and_false_g():
    """check-local-compute.mjs:61."""
    validate_worker_result(result_for(), REQUEST)
    with pytest.raises(RadiusResultError, match='^结果配置不一致$'):
        validate_worker_result(result_for({**REQUEST, 'radius_mm': 40}), REQUEST)
    duplicate = result_for()
    duplicate['layout']['xyzMm'][1] = duplicate['layout']['xyzMm'][0]
    with pytest.raises(RadiusResultError, match='^无效64点坐标$'):
        validate_worker_result(duplicate, REQUEST)
    merged = result_for()
    merged['geometry']['union_connected_component_count'] = 1
    with pytest.raises(RadiusResultError, match='^区域几何无效$'):
        validate_worker_result(merged, REQUEST)
    wrong = result_for()
    wrong['metrics']['conditional_global'] = 0.9
    with pytest.raises(RadiusResultError, match='^综合约束计算不一致$'):
        validate_worker_result(wrong, REQUEST)
    validate_worker_result({'status': 'no_layout', 'request': REQUEST, 'layout': None, 'metrics': None}, REQUEST)


def test_adaptive_cross_region_allocation_mode_normalizes_and_enforces_floor():
    """check-local-compute.mjs::adaptive cross-region allocation mode normalizes cleanly and enforces >= 4 per region."""
    from eeglayoutlab.schemas.radius_search import normalize_request
    adaptive_req = normalize_request({**REQUEST, 'allocation_mode': 'adaptive'})
    assert adaptive_req == {**REQUEST, 'allocation_mode': 'adaptive'}
    assert normalize_request({**REQUEST, 'allocation_mode': 'balanced'}) == REQUEST
    assert normalize_request({**REQUEST, 'allocation_mode': None}) == REQUEST
    with pytest.raises(ValueError, match='单区域'):
        normalize_request({'region_count': 1, 'radius_mm': 30, 'mode': 'whole_surface', 'allocation_mode': 'adaptive'})
    with pytest.raises(ValueError, match='配额模式无效'):
        normalize_request({**REQUEST, 'allocation_mode': 'invalid'})
    asymmetric = result_for(adaptive_req)
    asymmetric['layout']['regionIndices'] = [0 if i < 12 else 1 for i in range(64)]
    validate_worker_result(asymmetric, adaptive_req)
    with pytest.raises(RadiusResultError, match='^区域分配错误$'):
        validate_worker_result({**asymmetric, 'request': REQUEST}, REQUEST)
    below_floor = result_for(adaptive_req)
    below_floor['layout']['regionIndices'] = [0 if i < 3 else 1 for i in range(64)]
    with pytest.raises(RadiusResultError, match='^区域分配错误$'):
        validate_worker_result(below_floor, adaptive_req)
    comp_req = normalize_request({**adaptive_req, 'objective_mode': 'composite'})
    assert comp_req == {**adaptive_req, 'objective_mode': 'composite'}
    assert normalize_request({**REQUEST, 'objective_mode': 'min'}) == REQUEST
    assert normalize_request({**REQUEST, 'objective_mode': None}) == REQUEST
    with pytest.raises(ValueError, match='优化目标模式无效'):
        normalize_request({**REQUEST, 'objective_mode': 'invalid'})
    validate_worker_result({**asymmetric, 'request': comp_req}, comp_req)

    k16_req = normalize_request({**comp_req, 'electrode_count': 16})
    assert k16_req == {**comp_req, 'electrode_count': 16}
    assert normalize_request({**REQUEST, 'electrode_count': 64}) == REQUEST
    assert normalize_request({**REQUEST, 'electrode_count': None}) == REQUEST
    with pytest.raises(ValueError, match='电极总数只支持'):
        normalize_request({**REQUEST, 'electrode_count': 20})
    with pytest.raises(ValueError, match='至少为每区4导'):
        normalize_request({'region_count': 4, 'radius_mm': 30, 'mode': 'whole_surface', 'allocation_mode': 'adaptive', 'electrode_count': 12})
    with pytest.raises(ValueError, match='每区至少2导'):
        normalize_request({'region_count': 6, 'radius_mm': 30, 'mode': 'whole_surface', 'electrode_count': 8})
    k16_res = result_for(k16_req)
    k16_res['layout']['xyzMm'] = k16_res['layout']['xyzMm'][:16]
    k16_res['layout']['regionIndices'] = [0 if i < 6 else 1 for i in range(16)]
    validate_worker_result(k16_res, k16_req)
    with pytest.raises(RadiusResultError, match='^无效16点坐标$'):
        validate_worker_result({**k16_res, 'layout': {**k16_res['layout'], 'xyzMm': k16_res['layout']['xyzMm'][:15]}}, k16_req)


def _variant(change) -> dict:
    result = copy.deepcopy(result_for())
    change(result)
    return result


def _set(path: str, value):
    def change(result):
        *parents, last = path.split('.')
        target = result
        for part in parents:
            target = target[int(part)] if isinstance(target, list) else target[part]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value
    return change


VALIDATOR_CASES = {
    'accepted': result_for(),
    'no-layout': {'status': 'no_layout', 'request': REQUEST, 'layout': None, 'metrics': None},
    'no-layout-scores': {'status': 'no_layout', 'request': REQUEST, 'layout': None, 'metrics': {}},
    'no-layout-undefined': {'status': 'no_layout', 'request': REQUEST},
    'failed': _variant(_set('status', 'failed')),
    'null': None,
    'request-unnormalized': _variant(_set('request', {**REQUEST, 'radius_mm': 35.0, 'mask_codes': ['PL', 'PR']})),
    'request-refused': _variant(_set('request', {**REQUEST, 'AR': 0.9})),
    'request-missing': _variant(lambda r: r.pop('request')),
    'layout-null': _variant(_set('layout', None)),
    'xyz-short': _variant(lambda r: r['layout'].update(xyzMm=r['layout']['xyzMm'][:63])),
    'xyz-string': _variant(_set('layout.xyzMm.3.0', '15')),
    'xyz-boolean': _variant(_set('layout.xyzMm.3.1', True)),
    'xyz-negative-zero': _variant(_set('layout.xyzMm.0.1', -0.0)),
    'reference-null': _variant(_set('layout.referenceXyzMm', None)),
    'labels-float': _variant(_set('layout.regionIndices.0', 0.5)),
    'labels-range': _variant(_set('layout.regionIndices.63', 2)),
    'labels-unbalanced': _variant(_set('layout.regionIndices.31', 1)),
    'geometry-null': _variant(_set('geometry', None)),
    'geometry-count-string': _variant(_set('geometry.union_connected_component_count', '2')),
    'radius-limit': _variant(_set('geometry.common_graph_radius_mm', 35 + 1e-7)),
    'radius-over': _variant(_set('geometry.common_graph_radius_mm', 35 + 2e-7)),
    'radius-zero': _variant(_set('geometry.common_graph_radius_mm', 0)),
    'area-negative': _variant(_set('geometry.union_area_cm2', -1)),
    'spacing': _variant(_set('layout.xyzMm.1', [3.99, 0.0, 0.0])),
    'spacing-limit': _variant(_set('layout.xyzMm.1', [4 - 1e-7, 0.0, 0.0])),
    'metrics-null': _variant(_set('metrics', None)),
    'metrics-string': _variant(_set('metrics.field_relative', '0.8')),
    'metrics-null-score': _variant(lambda r: r['metrics'].update(sensitivity_tail=None, conditional_global=None)),
    'metrics-null-score-g': _variant(_set('metrics.sensitivity_tail', None)),
    'metrics-missing-score': _variant(lambda r: r['metrics'].pop('localization_relative')),
    'g-tolerance': _variant(_set('metrics.conditional_global', 0.3 + 5e-11)),
    'g-outside': _variant(_set('metrics.conditional_global', 0.3 + 2e-10)),
}

VALIDATOR_DRIVER = r"""
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const [specPath, outPath] = process.argv.slice(2);
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const { validateWorkerResult } = await import(pathToFileURL(`${spec.webapp}/server/local-compute-server.mjs`).href);
const out = {};
for (const [name, result] of Object.entries(spec.cases)) {
  try { validateWorkerResult(result, spec.request); out[name] = null; } catch (error) { out[name] = error.message; }
}
writeFileSync(outPath, JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_validator_messages_equal_node(tmp_path):
    driver, spec, out = tmp_path / 'validator.mjs', tmp_path / 'spec.json', tmp_path / 'out.json'
    driver.write_text(VALIDATOR_DRIVER, encoding='utf-8')
    spec.write_text(jsjson.stringify({'webapp': str(WEBAPP), 'request': REQUEST, 'cases': VALIDATOR_CASES}),
                    encoding='utf-8')
    subprocess.run(['node', str(driver), str(spec), str(out)], check=True, env=NODE_ENV)
    node = json.loads(out.read_text(encoding='utf-8'))
    python = {}
    for name, result in VALIDATOR_CASES.items():
        # Through the JSON text, as the worker's output and the stored records reach the validator.
        try:
            validate_worker_result(jsjson.parse(jsjson.stringify(result)), REQUEST)
            python[name] = None
        except ValueError as error:
            python[name] = str(error)
    assert python == node
    assert node['accepted'] is None and node['radius-limit'] is None and node['g-outside'] is not None


# --- Identity -----------------------------------------------------------------------------------------------------

def _code_root(tmp_path: Path) -> Path:
    root = tmp_path / 'root'
    root.mkdir()
    code_tree(root)
    forward_inputs(root)
    return root


def test_code_identity_lists_top_level_python_files_in_code_unit_order(tmp_path):
    root = _code_root(tmp_path)
    identity = code_identity(str(root))
    names = ['Z.py', 'a.py', 'b.py', 'ä.py', '\U0001F600.py', 'ｚ.py']
    assert list(identity) == [*CODE_FILES, *(f'src/compact_eeg/{name}' for name in names)]
    assert identity['src/compact_eeg/a.py'] == sha('a.py')
    assert identity['scripts/run_local_radius_compute.py'] == sha('worker')
    assert 'src/compact_eeg/notes.txt' not in identity and set(CODE_NAMES) - set(names) == {'notes.txt', 'cache.pyc'}


def test_code_identity_follows_links_and_fails_like_node(tmp_path):
    root = _code_root(tmp_path)
    outside = tmp_path / 'outside.py'
    outside.write_text('outside', encoding='utf-8')
    (root / 'src/compact_eeg/linked.py').symlink_to(outside)
    assert code_identity(str(root))['src/compact_eeg/linked.py'] == sha('outside')
    (root / 'src/compact_eeg/package.py').mkdir()
    with pytest.raises(OSError) as caught:
        code_identity(str(root))
    assert error_code(caught.value) == 'EISDIR'
    with pytest.raises(OSError) as caught:
        code_identity(str(tmp_path / 'missing'))
    assert error_code(caught.value) == 'ENOENT'


def test_radius_identity_adds_prior_files_and_runtime_only_when_present(tmp_path):
    root = _code_root(tmp_path)
    code = {'src/compact_eeg/a.py': sha('a.py')}
    plain = radius_identity(str(root), REQUEST, code, None)
    assert jsjson.stringify(plain) == jsjson.stringify(
        {'version': RADIUS_IDENTITY_VERSION, 'code': code, 'threads': 2})
    prior = radius_identity(str(root), {**REQUEST, 'data_prior': PRIOR}, code, {'python': 'x'})
    assert list(prior['code']) == [*code, *DATA_PRIOR_FILES]
    assert prior['code'][DATA_PRIOR_FILES[0]] == sha(DATA_PRIOR_FILES[0]) and prior['runtime'] == {'python': 'x'}
    assert 'runtime' not in radius_identity(str(root), REQUEST, code, '')
    cache = RadiusCache(str(root), 'python3', get_identity=lambda: code)
    identity, key = cache.identity_for(REQUEST)
    assert key == request_key(REQUEST, identity) == jsjson.sha256_hex({'request': REQUEST, 'identity': plain})


def test_read_cache_returns_the_canonical_request_or_a_miss(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    cache = RadiusCache(str(root), 'python3', get_identity=lambda: {})
    raw = {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface', 'mask_codes': []}
    canonical = {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'}
    key = cache.identity_for(canonical)[1]
    result = radius_result(canonical, status='no_layout')
    write_cache(root, key, raw, result, '2026-01-01T00:00:00Z')
    stored = cache.read_cache(key)
    assert jsjson.stringify(stored['request']) == jsjson.stringify(canonical)
    assert stored['finished_at'] == '2026-01-01T00:00:00Z' and cache.read_cache(key, canonical) is not None
    assert cache.read_cache(key, {**canonical, 'radius_mm': 20}) is None
    write_cache(root, key, raw, {**result, 'metrics': {}}, None)
    assert cache.read_cache(key) is None  # no_layout with scores
    write(root, f'results/v2/local_app_jobs/{key}/cache.json', {'key': key, 'request': raw, 'result_sha256': sha('x')})
    assert cache.read_cache(key) is None  # no result
    write_cache(root, sha('other'), raw, result)
    other = root / f'results/v2/local_app_jobs/{sha("other")}'
    other.rename(root / f'results/v2/local_app_jobs/{sha("moved")}')
    assert cache.read_cache(sha('moved')) is None  # key mismatch
    if os.geteuid() != 0:
        path = root / f'results/v2/local_app_jobs/{key}/cache.json'
        path.chmod(0)
        with pytest.raises(PermissionError):
            cache.read_cache(key)


# --- The run path ---------------------------------------------------------------------------------------------------

def run(coroutine):
    return asyncio.run(coroutine)


def _cache_file(root: Path, key: str) -> Path:
    return root / f'results/v2/local_app_jobs/{key}/cache.json'


def test_queue_has_one_child_deduplicates_identical_in_flight_requests_and_records_progress(tmp_path):
    """check-local-compute.mjs:72: one child, the same job for the same request, busy for another, the worker run
    with the shell off and two BLAS threads (B10), progress recorded, then a cached hit without a spawn."""
    async def scenario():
        spawner = Spawner()
        jobs = make_jobs(tmp_path, spawner)
        first, same = await jobs.submit(REQUEST), await jobs.submit(REQUEST)
        assert first['job']['id'] == same['job']['id'] and len(spawner.children) == 1
        assert (await jobs.submit(OTHER))['busy'] is True
        child = spawner.children[0]
        assert child.options['shell'] is False
        assert child.options['env']['OPENBLAS_NUM_THREADS'] == '2'
        assert {name: child.options['env'][name] for name in WORKER_ENV} == WORKER_ENV
        assert child.executable == 'python3' and child.args == ['-u', str(tmp_path / WORKER_SCRIPT)]
        assert child.options['cwd'] == str(tmp_path) and child.inputs == [jsjson.stringify(REQUEST).encode()]
        child.stdout(jsjson.stringify({'type': 'progress', 'progress': .5, 'stage': 'geometry',
                                       'message': '真实检查'}) + '\n')
        assert jobs.active.progress == .5
        child.complete(run_result())
        await until(lambda: jobs.active is None)
        assert jobs.jobs[first['job']['id']].status == 'completed'
        cached = await jobs.submit(REQUEST)
        assert cached['job']['cached'] is True and len(spawner.children) == 1
        jobs.dispose()
    run(scenario())


def test_disk_cache_survives_queue_restart_and_source_identity_invalidates_it(tmp_path):
    """check-local-compute.mjs:86."""
    async def scenario():
        spawner = Spawner()
        jobs = make_jobs(tmp_path, spawner)
        await jobs.submit(REQUEST)
        spawner.children[0].complete(run_result())
        await until(lambda: jobs.active is None)
        job = next(iter(jobs.jobs.values()))
        assert jsjson.parse((Path(job.batch) / 'job.json').read_text(encoding='utf-8'))['status'] == 'completed'
        again = make_jobs(tmp_path, Spawner('cache must not spawn'))
        assert (await again.submit(REQUEST))['job']['cached'] is True
        changed = make_jobs(tmp_path, Spawner('expected new calculation'), get_identity=lambda: {'version': 'changed'})
        new_job = await changed.submit(REQUEST)
        assert new_job['job']['key'] != job.key
        await until(lambda: changed.active is None)
        assert changed.jobs[new_job['job']['id']].status == 'failed'
        for each in (jobs, again, changed):
            each.dispose()
    run(scenario())


def test_cancellation_does_not_release_capacity_until_child_closes_no_result_is_cached(tmp_path):
    """check-local-compute.mjs:97, on the run path itself (test_worker.py ports it on a stand-in)."""
    async def scenario():
        spawner = Spawner()
        jobs = make_jobs(tmp_path, spawner)
        first = await jobs.submit(REQUEST)
        assert jobs.cancel(first['job']['id']) is True and spawner.children[0].kills == ['SIGTERM']
        assert (await jobs.submit(OTHER))['busy'] is True
        assert jobs.execution_slot.busy
        spawner.children[0].close(None)
        await until(lambda: jobs.active is None)
        assert jobs.jobs[first['job']['id']].status == 'cancelled' and not jobs.execution_slot.busy
        assert not _cache_file(tmp_path, first['job']['key']).exists()
        await jobs.submit(REQUEST)
        assert len(spawner.children) == 2
        spawner.children[1].complete({'status': 'no_layout', 'request': REQUEST})
        await until(lambda: jobs.active is None)
        assert _cache_file(tmp_path, first['job']['key']).exists()
        jobs.dispose()
    run(scenario())


def test_wall_clock_timeout_terminates_the_worker_and_returns_a_non_numeric_failure(tmp_path):
    """check-local-compute.mjs:106."""
    async def scenario():
        spawner = Spawner()
        jobs = make_jobs(tmp_path, spawner, timeout_ms=20)
        first = await jobs.submit(REQUEST)
        await until(lambda: bool(spawner.children[0].kills))
        spawner.children[0].close(None)
        await until(lambda: jobs.active is None)
        job = jobs.jobs[first['job']['id']]
        assert job.status == 'timeout' and jobs.view(job)['result'] is None
        assert job.message == '达到计算时限，任务已停止；未把缺失结果写成0'
        jobs.dispose()
    run(scenario())


def test_malformed_or_mismatched_worker_output_fails_without_crashing_the_server(tmp_path):
    """check-local-compute.mjs:111."""
    async def scenario():
        spawner = Spawner()
        jobs = make_jobs(tmp_path, spawner)
        first = await jobs.submit(REQUEST)
        spawner.children[0].complete({'status': 'completed', 'request': {'command': 'bad'}})
        await until(lambda: jobs.active is None)
        job = jobs.jobs[first['job']['id']]
        assert job.status == 'failed' and job.message == '计算结果校验失败：配置含未支持字段'
        jobs.dispose()
    run(scenario())


def test_the_permit_and_the_installation_lock_are_held_until_the_records_are_written(tmp_path):
    """The slot is released in finish's ``finally``, after job.json and cache.json; the completion callbacks come
    after that, once, with the job terminal; another workspace's lock on the installation is refused meanwhile."""
    async def scenario():
        spawner = Spawner()
        jobs = make_jobs(tmp_path, spawner)
        seen = []

        def finished(job):
            seen.append((job.id, job.status, jobs.active, jobs.execution_slot.busy,
                         jobs.execution_slot.lock.held, (Path(job.batch) / 'job.json').is_file(),
                         _cache_file(tmp_path, job.key).is_file()))
        jobs.finish_callbacks.append(finished)
        first = await jobs.submit(REQUEST)
        assert jobs.execution_slot.busy and jobs.execution_slot.lock.held
        other = InstallationLock(str(tmp_path))
        assert other.try_acquire() is False
        spawner.children[0].complete(run_result())
        assert jobs.jobs[first['job']['id']].status == 'completed' and jobs.execution_slot.busy  # writes pending
        await jobs.jobs[first['job']['id']].done
        assert seen == [(first['job']['id'], 'completed', None, False, False, True, True)]
        assert other.try_acquire() is True
        other.release()
        assert not any((tmp_path / 'results/v2/local_app_jobs').glob('*/.eeglayoutlab-execution.lock'))
        assert Path(execution_lock_path(str(tmp_path))).is_file()
        assert jobs.store.keys('radius') == [first['job']['key']]
        jobs.dispose()
    run(scenario())


def test_another_workspace_computing_makes_a_submit_busy_without_writing(tmp_path):
    """The installation lock: while another process holds it, the permit is refused (``contended``), nothing is
    written, and the same submit succeeds once it is released; a lookup takes neither."""
    async def scenario():
        holder = InstallationLock(str(tmp_path))
        assert holder.try_acquire()
        spawner = Spawner()
        jobs = make_jobs(tmp_path, spawner)
        assert await jobs.submit(REQUEST) == {'busy': True, 'maintenance': False}
        assert jobs.execution_slot.contended and not jobs.submitting and not spawner.children
        assert not (tmp_path / 'results/v2/local_app_jobs').exists()
        assert await jobs.lookup(REQUEST) == {'hit': False}
        holder.release()
        assert (await jobs.submit(REQUEST))['job']['status'] == 'running'
        assert not jobs.execution_slot.contended
        jobs.dispose()
        spawner.children[0].close(None)
        await until(lambda: jobs.active is None)
    run(scenario())


def test_a_paused_slot_and_a_broken_lock_refuse_before_any_write(tmp_path):
    async def scenario():
        jobs = make_jobs(tmp_path, Spawner())
        jobs.execution_slot.pause()
        assert await jobs.submit(REQUEST) == {'busy': True, 'maintenance': True}
        jobs.execution_slot.resume()
        lock = Path(execution_lock_path(str(tmp_path)))
        lock.parent.mkdir(parents=True)
        lock.symlink_to(tmp_path / 'elsewhere')
        with pytest.raises(OSError):
            await jobs.submit(REQUEST)
        assert not jobs.submitting and jobs.active is None and not jobs.execution_slot.busy
        assert not (tmp_path / 'results/v2/local_app_jobs').exists() and not (tmp_path / 'elsewhere').exists()
    run(scenario())


def test_a_cancel_while_the_worker_is_spawned_stops_it_as_soon_as_it_exists(tmp_path):
    """Node spawns synchronously; here a cancel during the spawn makes the job ``cancelling`` at once and the
    child gets SIGTERM when it exists."""
    async def scenario():
        release = asyncio.Event()
        spawner = Spawner()

        async def slow(worker, executable, args, options):
            await release.wait()
            return spawner(worker, executable, args, options)
        jobs = make_jobs(tmp_path, slow)
        submitted = asyncio.ensure_future(jobs.submit(REQUEST))
        await until(lambda: jobs.active is not None and jobs.active.status == 'running')
        assert not jobs.submitting
        assert await jobs.submit(REQUEST) == {'job': jobs.view(jobs.active)}  # the same key while it spawns
        id = jobs.active.id
        assert jobs.cancel(id) is True and jobs.active.status == 'cancelling' and jobs.cancel(id) is True
        release.set()
        assert (await submitted)['job']['status'] == 'cancelling'
        assert spawner.children[0].kills == ['SIGTERM']
        spawner.children[0].close(None, 'SIGTERM')
        await until(lambda: jobs.active is None)
        assert (jobs.jobs[id].status, jobs.jobs[id].message) == ('cancelled', '任务已停止')
    run(scenario())


def test_a_cancelled_submit_caller_does_not_strand_the_active_job(tmp_path):
    """The spawn goes on when the task awaiting submit is cancelled (a dropped request): the worker starts, its
    close finishes the job, and the permit is released."""
    async def scenario():
        release = asyncio.Event()
        spawner = Spawner()

        async def slow(worker, executable, args, options):
            await release.wait()
            return spawner(worker, executable, args, options)
        jobs = make_jobs(tmp_path, slow)
        submitted = asyncio.ensure_future(jobs.submit(REQUEST))
        await until(lambda: jobs.active is not None and jobs.active.status == 'running')
        submitted.cancel()
        with pytest.raises(asyncio.CancelledError):
            await submitted
        release.set()
        await until(lambda: len(spawner.children) == 1)
        id = jobs.active.id
        spawner.children[0].complete(run_result())
        await until(lambda: jobs.active is None)
        assert jobs.jobs[id].status == 'completed'
        assert not jobs.execution_slot.busy and not jobs.execution_slot.lock.held
        assert (await jobs.submit(REQUEST))['job']['source'] == 'local_cache'
    run(scenario())


def test_a_valid_cache_published_first_by_another_workspace_is_kept(tmp_path):
    """B16: cache.json is published once. A valid one written meanwhile (another workspace) stays byte for byte;
    the job completes with its own result in job.json. A file that is not valid is replaced."""
    async def scenario():
        spawner = Spawner()
        jobs = make_jobs(tmp_path, spawner)
        first = await jobs.submit(REQUEST)
        key = first['job']['key']
        theirs = write_cache(tmp_path, key, REQUEST, run_result(), '2026-01-01T00:00:00.000Z')
        before = theirs.read_bytes()
        spawner.children[0].complete(run_result())
        await until(lambda: jobs.active is None)
        job = jobs.jobs[first['job']['id']]
        assert (job.status, theirs.read_bytes()) == ('completed', before)
        record = jsjson.parse((Path(job.batch) / 'job.json').read_text(encoding='utf-8'))
        assert (record['status'], record['finished_at']) == ('completed', job.finished_at)
        # Not a valid record: a new service computes again and replaces it.
        theirs.write_text('not json', encoding='utf-8')
        second = make_jobs(tmp_path, spawner)
        assert (await second.submit(REQUEST))['job']['status'] == 'running'
        spawner.children[1].complete(run_result())
        await until(lambda: second.active is None)
        job = second.jobs[next(reversed(second.jobs))]
        expected = {'key': key, 'request': REQUEST, 'result': run_result(),
                    'result_sha256': jsjson.sha256_hex(run_result()), 'finished_at': job.finished_at}
        assert theirs.read_bytes() == jsjson.stringify(expected).encode('utf-8')
        assert not [name for name in os.listdir(theirs.parent) if name.endswith('.tmp')]
    run(scenario())


def test_aclose_stops_the_worker_and_waits_for_its_records(tmp_path):
    async def scenario():
        spawner = Spawner()
        jobs = make_jobs(tmp_path, spawner)
        first = await jobs.submit(REQUEST)
        closing = asyncio.ensure_future(jobs.aclose())
        await until(lambda: bool(spawner.children[0].kills))
        assert jobs.active.cancel_reason == 'server_restart' and not closing.done()
        spawner.children[0].close(None, 'SIGTERM')
        await closing
        record = jsjson.parse((Path(jobs.jobs[first['job']['id']].batch) / 'job.json').read_text(encoding='utf-8'))
        assert (record['status'], record['message']) == ('cancelled', '任务已停止')
        with pytest.raises(RadiusJobError, match='^计算服务正在重启$'):
            await jobs.submit(REQUEST)
    run(scenario())


def test_the_queue_starts_jobs_with_its_prepared_request_and_reads_their_state(tmp_path):
    """What ``jobs.kinds``'s adapter calls: the context of ``identity_for``, ``lookup(request, ctx)``,
    ``submit(prepared)`` (the request is normalized again, as Node's submit does), ``jobs``, ``view``,
    ``active``, ``submitting`` and ``active_pid()``."""
    async def scenario():
        spawner = Spawner()
        jobs = make_jobs(tmp_path, spawner)
        identity, key = jobs.identity_for(REQUEST)
        ctx = {'identity': identity, 'key': key}
        assert await jobs.lookup(REQUEST, ctx) == {'hit': False}
        assert await jobs.lookup(REQUEST, (identity, key)) == {'hit': False}
        started = await jobs.submit({'request': {**REQUEST, 'mask_codes': ['PL', 'PR']}, 'key': key, 'ctx': ctx})
        assert started['job']['key'] == key and jobs.active.id == started['job']['id'] and not jobs.submitting
        assert jobs.active_pid() is None  # a fake child has no pid
        assert jobs.view(jobs.jobs[started['job']['id']]) == started['job']
        spawner.children[0].complete(run_result())
        await until(lambda: jobs.active is None)
        hit = await jobs.lookup(REQUEST, ctx)
        assert hit['hit'] is True and hit['job']['source'] == 'local_cache' and hit['job']['id'] == started['job']['id']
        assert jobs.view(jobs.jobs[started['job']['id']])['source'] == 'local_compute'
    run(scenario())


def test_the_job_map_keeps_the_newest_100(tmp_path, monkeypatch):
    """Lookups add a cached job each and drop the oldest that is not active; finish drops the oldest."""
    monkeypatch.setattr(radius_module, 'JOB_LIMIT', 2)

    async def scenario():
        spawner = Spawner()
        jobs = make_jobs(tmp_path, spawner)
        requests = [{**REQUEST, 'radius_mm': radius} for radius in (20, 25, 30)]
        for request in requests:
            write_cache(tmp_path, jobs.identity_for(request)[1], request, run_result(request))
        active = (await jobs.submit(REQUEST))['job']['id']
        ids = [(await jobs.lookup(request))['job']['id'] for request in requests]
        assert list(jobs.jobs) == [active, ids[-1]]  # the active job stays
        cached = await jobs.lookup(requests[0])
        assert list(jobs.jobs) == [active, cached['job']['id']] and cached['job']['id'] not in ids
        spawner.children[0].complete(run_result())
        await until(lambda: jobs.active is None)
        assert list(jobs.jobs) == [active, cached['job']['id']]
        assert (await jobs.lookup(REQUEST))['job']['id'] == active
    run(scenario())


WORKER = r'''
import json, os, sys
request = sys.stdin.read()
print(json.dumps({'type': 'progress', 'progress': 0.5, 'stage': 'env', 'message': json.dumps({
    'cwd': os.getcwd(), 'argv': sys.orig_argv[1:], 'request': request,
    'env': {name: os.environ.get(name) for name in %(names)r}})}))
sys.stderr.write('worker stderr\n')
print(json.dumps({'type': 'result', 'result': %(result)s}))
'''


def test_a_real_worker_process_completes_through_the_transport(tmp_path):
    """The worker as Node runs it: ``python -u R/scripts/run_local_radius_compute.py`` in R, the request on
    stdin, ``WORKER_ENV`` added to the service's environment; the records written and the group gone."""
    root = tmp_path / 'root'
    result = run_result()
    write(root, WORKER_SCRIPT, WORKER % {'names': list(WORKER_ENV), 'result': jsjson.stringify(result)})

    async def scenario():
        jobs = RadiusJobs(str(root), sys.executable, get_identity=lambda: {}, timeout_ms=60000)
        first = await jobs.submit(REQUEST)
        assert isinstance(jobs.active_pid(), int)
        pid = jobs.active_pid()
        await until(lambda: jobs.active is None, 60)
        job = jobs.jobs[first['job']['id']]
        assert (job.status, job.message, job.stderr) == ('completed', '当前配置已计算', 'worker stderr\n')
        report = json.loads(job.events[0]['message'])
        assert report == {'cwd': os.path.realpath(root), 'argv': ['-u', str(root / WORKER_SCRIPT)],
                          'request': jsjson.stringify(REQUEST), 'env': WORKER_ENV}
        with pytest.raises(ProcessLookupError):
            os.killpg(pid, 0)
        assert jsjson.parse(_cache_file(root, job.key).read_text(encoding='utf-8'))['result'] == result
        assert not jobs.execution_slot.busy and not jobs.execution_slot.lock.held
    run(scenario())


# --- Parity with Node's run path -------------------------------------------------------------------------------------

_TEMPORARY = re.compile(r'\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.tmp')
PARITY_IDS = [case['id'] for case in parity_cases(Path('/parity'))]


@pytest.fixture(scope='module')
def node_run(tmp_path_factory):
    """Node's ``LocalComputeQueue`` over every case once; each root is then moved to ``root.node``."""
    base = tmp_path_factory.mktemp('radius-run')
    cases = parity_cases(base)
    for case in cases:
        build(case)
    output = run_node(cases, base)
    for case in cases:
        Path(case['root']).rename(Path(case['root']).with_name('root.node'))
    return {case['id']: (case, theirs) for case, theirs in zip(cases, output['cases'])}


def _masked(records: list) -> list:
    """The records with the random part of temporary names masked (a failed rename names its temporary)."""
    return [[kind, _TEMPORARY.sub('.<uuid>.tmp', text)] for kind, text in records]


@needs_node
@pytest.mark.parametrize('id', PARITY_IDS)
def test_run_path_writes_the_bytes_and_reports_the_states_of_node(node_run, id):
    """Parity 1 of slice 4: given the same worker output, clock and job identifiers, the run path returns Node's
    views, refusals and errors (as JSON text), spawns the worker as Node does (executable, arguments, cwd, stdio,
    shell, thread settings, inherited environment, stdin bytes, signals) and leaves the same record tree:
    request.json, job.json and cache.json byte for byte, no temporaries."""
    case, theirs = node_run[id]
    build(case)  # the same root, at the same path, again
    ours = run_python(case)
    assert _masked(ours['records']) == _masked(theirs['records'])
    assert (ours['clock'], ours['ids']) == (theirs['clock'], theirs['ids'])
    assert ours['children'] == theirs['children']
    node_root = Path(case['root']).with_name('root.node')
    assert record_tree(Path(case['root'])) == record_tree(node_root)
    assert not [name for name in record_tree(node_root) if name.endswith('.tmp')]


def test_the_timeout_case_records_its_progress_when_the_loop_stalls_well_below_its_timer(tmp_path, monkeypatch):
    """The timeout case feeds a progress line, then waits for the timer. A loop held up right after the timer is
    armed (``FakeChild.resume`` ends ``Worker._begin``), as on a loaded machine, for less than the timer
    (``TIMEOUT_CASE_MS``) must not let it fire first: the progress would be dropped, where Node records it. A longer
    stall would still drop it, since Python arms the timer a few loop iterations before ``submit`` returns (``await
    asyncio.shield(self.run(job))``) and Node in the same turn; hence a timer far above any stall under load."""
    case = next(case for case in parity_cases(tmp_path) if case['id'] == 'timeout')
    build(case)
    plain = run_python(case)
    monkeypatch.setattr(FakeChild, 'resume', lambda self: time.sleep(0.1))
    build(case)
    stalled = run_python(case)
    assert stalled['records'] == plain['records']
    view = jsjson.parse(plain['records'][1][1])
    assert (view['status'], view['progress'], view['stage']) == ('cancelling', 0.4, 'geometry')
    # Far above any stall a loaded machine gives.
    assert TIMEOUT_CASE_MS >= 1000


@needs_node
def test_the_parity_cases_reach_every_outcome_of_the_run_path(node_run):
    texts = ''.join(text for _, theirs in node_run.values() for _, text in theirs['records'])
    statuses = set(re.findall(r'"status":"([a-z_]+)"', texts))
    assert {'running', 'cancelling', 'completed', 'no_layout', 'failed', 'timeout', 'cancelled'} <= statuses
    for message in ('正在加载本地头模与前向矩阵', '正在停止计算', '达到计算时限，任务已停止；未把缺失结果写成0',
                    '任务已停止', '计算结果校验失败：结果配置不一致', '计算结果校验失败：任务排队后科学代码已变化',
                    '当前配置已计算', '本次搜索预算内未构造出64点布局', 'Python启动失败：spawn python3 ENOENT',
                    '计算未成功完成；错误记录已保存，可重新计算', '无法启动Python：', '计算记录保存失败：ENOENT',
                    '计算记录保存失败：EISDIR', '已读取相同模型与配置的已有计算记录', '计算服务正在重启',
                    '缓存前向模型身份不一致', '"busy":true,"active_job"', '"local_cache"'):
        assert message in texts, message


# --- The real installation (EEG_KEY_PARITY_ROOT) ---------------------------------------------------------------------

REAL_ROOT = os.environ.get('EEG_KEY_PARITY_ROOT')
real_root = pytest.mark.skipif(not REAL_ROOT, reason='set EEG_KEY_PARITY_ROOT to a checkout with results/v2')

LAB_DRIVER = r"""
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const [specPath, outPath] = process.argv.slice(2);
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const lab = await import(pathToFileURL(`${spec.webapp}/lib/lab-workflow.ts`).href);
const out = { AREA_CAPS: lab.AREA_CAPS, REGION_COUNTS: lab.REGION_COUNTS, areas: [] };
for (const domain of ['whole_scalp_free', 'low_hair_free']) for (const area of lab.AREA_CAPS) {
  out.areas.push({ domain, area, rows: lab.areaRows(spec.records, domain, area).map(row => row === undefined ? null :
    { id: row.id, comparison: lab.comparisonLink(row, 50), design: lab.radiusDesignLink(row, 50) }) });
}
writeFileSync(outPath, JSON.stringify(out));
"""


@pytest.mark.data_bundle
@real_root
@needs_node
def test_all_30_actual_strict_area_records_have_exactly_one_entry_per_domain_area_r_and_preserved_metrics(tmp_path):
    """check-lab-workflow.mjs:25: the library of a run path that cannot compute (its spawn fails the test) lists
    the 30 strict-area records, one per domain, area cap and region count, with their geometry and minimum score;
    ``areaRows`` and the links stay in Node (lib/lab-workflow.ts) on the records Python lists. Read only: no
    lookup, no submit, so nothing takes the installation lock or writes."""
    def refuse(*_):
        pytest.fail('comparison cannot compute')
    config = runtime_config(REAL_ROOT)
    jobs = RadiusJobs(config.repository_root, config.python, spawn=refuse)
    records = Library(config.repository_root, config, radius=jobs).list()['records']
    driver, spec, out = tmp_path / 'lab.mjs', tmp_path / 'spec.json', tmp_path / 'out.json'
    driver.write_text(LAB_DRIVER, encoding='utf-8')
    spec.write_text(jsjson.stringify({'webapp': str(WEBAPP), 'records': records}), encoding='utf-8')
    subprocess.run(['node', str(driver), str(spec), str(out)], check=True, env=NODE_ENV, timeout=120)
    node = json.loads(out.read_text(encoding='utf-8'))
    by_id = {record['id']: record for record in records}
    ids = set()
    assert len(node['areas']) == 2 * len(node['AREA_CAPS'])
    for entry in node['areas']:
        rows = [by_id[row['id']] if row else None for row in entry['rows']]
        assert [row and row['region_count'] for row in rows] == node['REGION_COUNTS']
        for row, links in zip(rows, entry['rows']):
            ids.add(row['id'])
            assert row['dataset_id'] == 'strict_area' and row['area_cap_cm2'] == entry['area']
            assert row['geometry']['union_connected_component_count'] == row['region_count']
            metrics = row['metrics']
            assert metrics['conditional_global'] == min(metrics['field_relative'], metrics['sensitivity_tail'],
                                                        metrics['localization_relative'])
            query = parse_qs(urlsplit(links['comparison']).query)
            assert float(query['ar'][0]) == 50 and float(query['r'][0]) == row['region_count']
            assert float(query['area'][0]) == row['area_cap_cm2']
            assert links['design'] == f"/design?from={row['id']}&ar=50"
            assert row['request'] is None  # never silently translate area into a radius request
    assert len(ids) == 30 and jobs.jobs == {}
    jobs.dispose()
