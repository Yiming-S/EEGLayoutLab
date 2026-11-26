"""The job routes under test (test_compute_routes.py, tests/service/README.md): a synthetic root whose radius worker
is a fake, the service started with its lifespan, and Node's composed service over the same root.

``FAKE_WORKER`` replaces ``scripts/run_local_radius_compute.py``. It reads the request on stdin, as the real worker
does, and plays the step of ``R/fake-radius-plan.json`` for it (keyed ``<region_count>/<radius_mm>/<mode>``):
stdout lines, a stderr text, a wait (``hold`` seconds, until it is stopped), then a result line and an exit status.
A result echoes the request it was given unless the step is ``stale``. Both hosts run the same script with the
same interpreter, so the records they write can be compared.

``compute_root`` builds the root: the radius code (``library_support.code_tree``), the fake worker, the forward
inputs and the plan; the results it plans carry a provenance that ``InputIntegrity.verify`` accepts and whose
``code_sha256`` is the root's code identity. ``serving`` starts ``create_app`` with its lifespan on a workspace (a
TestClient used as a context manager runs the ASGI lifespan, so the queue starts and recovers; leaving it stops the
running worker and writes the queue once more).

``run_node`` runs ``parity/compute_routes.mjs`` (its header documents the steps) over a root; ``run_python`` runs the
same steps through the Python application; ``masked`` puts both answers in the compared form.

The coordinate evaluation (slice 5): ``design_compute_root`` builds a design root (``key_parity_support.design_root``,
so the scientific context is the real one on both hosts) whose ``scripts/design_evaluation.py`` is ``DESIGN_WORKER``,
design_support's stand-in with one more behaviour, picked by the design's ``name``: ``change`` alters a code file of
the identity before it answers, so the context computed again after the close has another key. The root also holds a
stored evaluation of ``DESIGN_REQUESTS['cached']`` that neither host computed, whose hits are cached receipts, and
the library's inputs (the radius code tree and the offline datasets), so that the library reads its records and
bundles. ``cache_digests`` names each ``cache.json`` digest in an answer by its path: the file holds a finish time.
``names``, ``SOURCE`` and ``envelope`` build ``design-submission/1`` bodies, ``DESIGN_STEPS`` are the HTTP steps both
hosts run, and ``design_tree`` / ``annotation_tree`` read what they wrote.

The electrode editor (slice 6): ``editor_compute_root`` builds an editor root (``editor_support.editor_root``: parents
of every kind on a design root) whose ``scripts/electrode_editor.py`` is ``EDITOR_WORKER`` and whose
``scripts/design_evaluation.py`` is ``DESIGN_WORKER``, so that both kinds share one queue and one slot.
``EDITOR_WORKER`` is editor_support's stand-in, which plays the behaviour ``R/editor-plan.json`` names for a request
(keyed ``<action>/<parent_id>/<disabled slots>``, ``editor_plan_key``): ``hold``, ``fail``, ``stale``, ``change`` (it
alters the editor's workflow file, an input of every editor identity, before it answers) or ``reparent`` (it rewrites
the finish time of its parent's radius record, so the parent's digest changes). The root also holds two stored edits
neither host computed (``stored_edit``), whose hits are cached receipts. ``editor_steps`` gives the HTTP steps both
hosts run on it, and ``editor_tree`` reads the records they wrote.

Signal reception (slice 7): ``reception_compute_root`` builds a reception root (``reception_support.reception_root``:
an editor root with the reception workflow files and stub runtime inspectors) whose two reception workers are
``RECEPTION_WORKER`` and whose ``scripts/design_evaluation.py`` is ``DESIGN_WORKER``, so that the kinds share one
queue and one slot. ``RECEPTION_WORKER`` is reception_support's stand-in, which plays the behaviour
``R/reception-plan.json`` names for a request's seed (``RECEPTION_MODES``): ``hold``, ``fail``, ``stale`` (it writes
the result of the next seed) or ``change`` (it alters ``scripts/source_reception.py``, an input of every reception
identity, before it answers). The root also holds a stored v1 result neither host computed (``stored_reception``),
whose hit is a cached receipt. ``reception_steps`` gives the HTTP steps both hosts run on it (a ``FILE`` step writes
or removes a file of the root between two requests), ``reception_tree`` reads the records they wrote, and
``reception_masked`` puts the answers in the compared form: each saved result longer than ``BRIEF`` bytes by the
SHA-256 of its text, and Node's records scope ``current_browser`` as the workspace's.

Robustness studies (slice 8): ``study_compute_root`` is a design root with the head packages ``STUDY_HEADS``;
``STUDY_STEPS`` are the HTTP steps both hosts run on it (``study_body`` builds a study of the stand-in's design, whose
name picks the worker's behaviour; a step with ``field`` waits for a member of the study, and a ``brief`` start or
cancel answer is compared without the members that race with the pump). ``study_tree`` reads a studies directory
(Node's ``Q/studies``, ours ``W/studies``); ``study_digests`` names each ``cache.json`` digest by its key (also a
snapshot's whose record was removed), and ``study_masked`` / ``study_tree_masked`` put the answers and the trees in
the compared form (ids numbered as the answers show them, times, revisions and Node's session ``network`` masked, a
directory's rows in id order).

Research projects (slice 9): ``project_compute_root`` is a reception root (as above) that also holds a stored
coordinate evaluation of ``DESIGN_REQUESTS['cached']`` (a named evaluation's record), a stored electrode edit
(``stored-evaluate`` of ``editor_requests``) and the data manifest and runtime lock a delivery names. ``project_steps``
are the HTTP steps both hosts run on it (``capture`` keeps a project's and its entries' ids, and Node's project key is
sent and ignored); a step marked ``differs`` is a deliberate difference (the list, sharing), which
``project_differences`` checks apart. ``project_masked`` puts the answers in the compared form (``masked``, a
create's ``access_key`` and a delivery's Node or Python ``source_files`` and ``manifest_sha256`` masked once each
side's delivery passed its host's checks) and ``project_tree_masked`` the project trees (Node's ``Q/projects``, ours
``W/projects``: ids numbered, times, the ``owner_key_hash`` of a key nobody holds and Node's ``creator_network``
masked).
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Iterator, Optional

from eeglayoutlab.jobs.identity import UNDEFINED
from eeglayoutlab.jobs.radius import WORKER_SCRIPT, RadiusCache, code_identity
from eeglayoutlab.jobs.runtime import runtime_config
from eeglayoutlab.schemas import jsjson
from eeglayoutlab.server.app import Service, create_app

from .design_support import ADMISSION_POINTER, DESIGN, FAKE_WORKER as DESIGN_FAKE_WORKER, run_result
from .editor_support import (
    EDITOR_CODE, EDITOR_JOBS, FAKE_WORKER as EDITOR_FAKE_WORKER, MISSING, REGIONS, STALE, editor_root, evaluate,
    evaluate_result, parent_digests, prepare, prepare_result,
)
from .key_parity_support import NODE_ENV, design_root
from .library_support import code_tree, forward_inputs, offline_datasets, radius_result, write
from .reception_support import (
    BRIEF, CATALOG, FAKE_WORKER as RECEPTION_FAKE_WORKER, SOURCE_JOBS, SOURCE_V2_JOBS, brief, cross, fixture,
    multi, reception_root, single, v1,
)
from .service_support import TOKENS, loopback_client, service_config

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/compute_routes.mjs'
PLAN = 'fake-radius-plan.json'
SETTLE = 30.0  # seconds a job may take to settle under load before a test fails
HOLD = 120  # seconds a held worker waits; it is always stopped before that

FAKE_WORKER = r'''import json
import os
import sys
import time

request = json.loads(sys.stdin.read())
with open(os.path.join(os.getcwd(), 'fake-radius-plan.json'), encoding='utf-8') as handle:
    plan = json.load(handle)
step = plan['%s/%s/%s' % (request['region_count'], request['radius_mm'], request['mode'])]
for line in step.get('stdout', []):
    sys.stdout.write(line + '\n')
    sys.stdout.flush()
if step.get('stderr'):
    sys.stderr.write(step['stderr'])
    sys.stderr.flush()
if step.get('hold'):
    time.sleep(step['hold'])
if 'result' in step:
    result = step['result']
    if not step.get('stale'):
        result['request'] = request
    sys.stdout.write(json.dumps({'type': 'result', 'result': result}, ensure_ascii=False) + '\n')
    sys.stdout.flush()
sys.exit(step.get('exit', 0))
'''

# The planned requests: a completed layout with progress, no layout, a crash, a held worker, a result for another
# request.
REQUESTS = {
    'done': {'region_count': 2, 'radius_mm': 35, 'mode': 'preset', 'mask_codes': ['PL', 'PR']},
    'none': {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'},
    'crash': {'region_count': 3, 'radius_mm': 50, 'mode': 'whole_surface'},
    'hold': {'region_count': 4, 'radius_mm': 50, 'mode': 'whole_surface'},
    'stale': {'region_count': 2, 'radius_mm': 40, 'mode': 'preset', 'mask_codes': ['PL', 'PR']},
    'second-hold': {'region_count': 6, 'radius_mm': 50, 'mode': 'whole_surface'},
}
TERMINAL = ('completed', 'no_layout', 'failed', 'cancelled', 'timeout')


def plan_key(request: dict) -> str:
    return f"{request['region_count']}/{request['radius_mm']}/{request['mode']}"


def progress(value: float, stage: str, message: str) -> str:
    return jsjson.stringify({'type': 'progress', 'progress': value, 'stage': stage, 'message': message})


def compute_root(root: Path) -> dict:
    """Builds the root; returns the provenance of its planned results."""
    code_tree(root)
    write(root, WORKER_SCRIPT, FAKE_WORKER)
    provenance = {**forward_inputs(root), 'code_sha256': code_identity(str(root))}
    hold = {'stdout': [progress(0.25, 'geometry', '构建候选区域')], 'hold': HOLD}
    steps = {
        'done': {'stdout': [progress(0.25, 'geometry', '构建候选区域'), 'plain log line',
                            progress(0.75, 'optimize', '优化布局')],
                 'stderr': 'warning: 中文\n', 'result': radius_result(REQUESTS['done'], provenance)},
        'none': {'result': radius_result(REQUESTS['none'], provenance, status='no_layout')},
        'crash': {'stderr': 'Traceback: boom\n', 'exit': 1},
        'hold': hold,
        'second-hold': hold,
        'stale': {'result': radius_result(REQUESTS['done'], provenance), 'stale': True},
    }
    write(root, PLAN, {plan_key(REQUESTS[name]): step for name, step in steps.items()})
    return provenance


def key_of(root: Path, request: dict) -> str:
    """The radius key of ``request`` on ``root`` (the service's identity: code files, threads, runtime)."""
    from eeglayoutlab.jobs.radius import normalize_request

    return RadiusCache(str(root), sys.executable).identity_for(normalize_request(request))[1]


def json_body(response: Any) -> Any:
    return jsjson.parse(response.text)


@contextlib.contextmanager
def serving(root: Path, workspace: Path, *, cache_only: bool = False, clear_interrupted: bool = False,
            radius_options: Optional[dict] = None, queue_options: Optional[dict] = None,
            csrf: bool = True, lifespan: bool = True) -> Iterator[tuple[Service, Any]]:
    """The application on ``root`` and ``workspace`` with its lifespan running (not with ``lifespan`` false: no
    compute service is started), and a loopback client that holds the session cookie (and sends the CSRF token
    unless ``csrf`` is false)."""
    config = dataclasses.replace(service_config(root, None, workspace),
                                 runtime=runtime_config(str(root), sys.executable, env={}),
                                 cache_only=cache_only, clear_interrupted=clear_interrupted)
    app = create_app(config)
    app.compute.radius_options.update(radius_options or {})
    app.compute.queue_options.update(queue_options or {})
    client = loopback_client(app, csrf=csrf)
    if not lifespan:
        yield app, client
        return
    with client:
        yield app, client


def post(client: Any, path: str, body: Any = None, **headers: str) -> Any:
    data = body if isinstance(body, (bytes, str)) or body is None else jsjson.stringify(body)
    return client.post(path, content=data, headers={'content-type': 'application/json', **headers})


def poll(client: Any, id: str, statuses: tuple[str, ...] = TERMINAL, limit: float = SETTLE,
         kind: str = 'local-compute') -> dict:
    """The receipt's view once its status is one of ``statuses``."""
    deadline = time.monotonic() + limit
    while True:
        response = client.get(f'/api/{kind}/jobs/{id}')
        assert response.status_code == 200, response.text
        job = json_body(response)['job']
        if job['status'] in statuses:
            return job
        if time.monotonic() > deadline:
            raise AssertionError(f'the job did not reach {statuses}: {job}')
        time.sleep(0.02)


def wait_for(check: Any, limit: float = SETTLE) -> None:
    deadline = time.monotonic() + limit
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError('the service did not settle')
        time.sleep(0.02)


def queue_file(workspace: Path) -> dict:
    return jsjson.parse((workspace / '.eeglayoutlab/queue.json').read_text(encoding='utf-8'))


def write_queue(workspace: Path, state: dict) -> None:
    (workspace / '.eeglayoutlab/queue.json').write_text(jsjson.stringify(state), encoding='utf-8')


def jobs_tree(root: Path) -> dict[str, str]:
    """``R/results/v2/local_app_jobs`` as ``{relative path: text}``."""
    base = root / 'results/v2/local_app_jobs'
    if not base.exists():
        return {}
    return {str(path.relative_to(base)): path.read_text(encoding='utf-8')
            for path in sorted(base.rglob('*')) if path.is_file()}


# --- The coordinate evaluation ---------------------------------------------------------------------------------------

DESIGN_JOBS = 'results/v2/design_evaluation_jobs'
NODE_ANNOTATIONS = DESIGN_JOBS + '/electrode_annotations'
WORKSPACE_ANNOTATIONS = 'annotations/electrode-names'
# A code file of the design identity, which the ``change`` worker alters.
CHANGED_INPUT = 'src/compact_eeg/metrics.py'
_ANCHOR = "xyz = design['xyz_mm']\n"
assert DESIGN_FAKE_WORKER.count(_ANCHOR) == 1
DESIGN_WORKER = DESIGN_FAKE_WORKER.replace(_ANCHOR, (
    "if mode == 'change':\n"
    f"    with open(os.path.join(os.getcwd(), {CHANGED_INPUT!r}), 'a', encoding='utf-8') as handle:\n"
    "        handle.write('# changed during the run\\n')\n") + _ANCHOR)


def design_request(name: str, **extra: Any) -> dict:
    """check-design-decision.mjs's request, with the design named ``name`` (the stand-in worker's behaviour)."""
    return {'action': 'evaluate', 'design': {**DESIGN, 'name': name}, 'radius_mm': 6, 'seed': 42, **extra}


DESIGN_REQUESTS = {name: design_request(name) for name in ('done', 'cached', 'hold', 'fail', 'stale', 'change')}
SOURCE = {'schema': 'electrode-coordinate-source/1', 'format': 'bids-electrodes/1', 'electrodes_file': 'electrodes.tsv',
          'coordsystem_file': 'coordsystem.json', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm',
          'coordinate_system_description': 'Ernie native space, mm', 'region_index_base': 0,
          'region_description': 'Two regions, from the file'}


def names(version: str) -> list[str]:
    """64 distinct names with multibyte characters (two, three and four UTF-8 bytes), as the interface imports them."""
    return [f'{version}-Fp1, left' if i == 0 else f'{version}-Cz "midline"' if i == 1 else f'{version}-电极03' if i == 2
            else f'{version}-É\U0001F600{i:02d}' if i == 3 else f'{version}-Channel{i + 1:02d}' for i in range(64)]


def envelope(request: Any, version: Optional[str] = None, source: Optional[dict] = None, **extra: Any) -> dict:
    """A ``design-submission/1`` body: ``request`` with the names of ``version`` and, given, the source metadata."""
    body = {'schema': 'design-submission/1', 'request': request, 'electrode_names': names(version or 'E')}
    if source is not None:
        body['source_metadata'] = source
    return {**body, **extra}


def padded(value: Any, size: int) -> str:
    """``value`` as JSON text padded with spaces to ``size`` UTF-8 bytes."""
    text = jsjson.stringify(value)
    return text + ' ' * (size - len(text.encode('utf-8')))


def design_key(root: Path, raw: Any) -> str:
    """The key of ``raw`` on ``root`` (the scientific context of the service's interpreter)."""
    from eeglayoutlab.jobs.design_result import normalize_design_request
    from eeglayoutlab.jobs.identity import design_context
    from eeglayoutlab.jobs.integrity import InputIntegrity

    return design_context(str(root), sys.executable, InputIntegrity(str(root)), normalize_design_request(raw)).key


def design_compute_root(directory: Path, heads: tuple[str, ...] = ()) -> Path:
    """A design root with ``DESIGN_WORKER``, a stored evaluation of ``DESIGN_REQUESTS['cached']`` and the inputs
    of the library (the radius code tree and the offline datasets), so that its records and bundles can be read;
    ``heads`` adds those head packages (and the nominal table), as ``design_root`` builds them."""
    from eeglayoutlab.jobs.identity import DATA_PRIOR_FILES

    root = Path(design_root(directory, heads=heads))
    kept = {path: (root / path).read_bytes() for path in DATA_PRIOR_FILES}
    code_tree(root)
    forward_inputs(root)
    offline_datasets(root)
    for path, data in kept.items():  # code_tree writes them too; the design root's bytes stay
        write(root, path, data)
    write(root, 'scripts/design_evaluation.py', DESIGN_WORKER)
    stored_design(root, DESIGN_REQUESTS['cached'])
    assert (root / ADMISSION_POINTER).is_file()
    return root


def stored_design(root: Path, raw: Any) -> str:
    """Writes the ``cache.json`` a coordinate evaluation of ``raw`` would publish on ``root`` (its context computed
    here, as both hosts compute it) with a fixed finish time; returns the key."""
    from eeglayoutlab.jobs.design_result import normalize_design_request
    from eeglayoutlab.jobs.identity import design_context
    from eeglayoutlab.jobs.integrity import InputIntegrity

    request = normalize_design_request(raw)
    context = design_context(str(root), sys.executable, InputIntegrity(str(root)), request)
    result = run_result(request)
    write(root, f'{DESIGN_JOBS}/{context.key}/cache.json', {
        'key': context.key, 'identity': context.identity, 'result': result,
        'result_sha256': jsjson.sha256_hex(result), 'finished_at': '2026-01-01T00:00:00.000Z'})
    return context.key


def tree(base: Path, skip: tuple[str, ...] = ()) -> dict[str, str]:
    """The files below ``base`` as ``{relative path: text}``, without those below a ``skip`` directory."""
    if not base.exists():
        return {}
    return {str(path.relative_to(base)): path.read_text(encoding='utf-8') for path in sorted(base.rglob('*'))
            if path.is_file() and not any(str(path.relative_to(base)).startswith(name + '/') for name in skip)}


def design_tree(root: Path) -> dict[str, str]:
    """``R/results/v2/design_evaluation_jobs`` without Node's annotation directory."""
    return tree(root / DESIGN_JOBS, ('electrode_annotations',))


def annotation_tree(directory: Path) -> dict[str, tuple[str, int]]:
    """The annotation files of ``directory``: ``{name: (text, mode)}``."""
    if not directory.exists():
        return {}
    return {path.name: (path.read_text(encoding='utf-8'), path.stat().st_mode & 0o777)
            for path in sorted(directory.iterdir())}


def cache_digests(answers: list[dict], records: dict[str, str]) -> list[dict]:
    """``answers`` with the digest of each ``cache.json`` of ``records`` (a ``design_tree``) named by its path:
    the file holds its finish time, so its digest differs between hosts while the path does not."""
    names = {hashlib.sha256(text.encode('utf-8')).hexdigest(): f'<sha256 of {path}>' for path, text in records.items()
             if path.endswith('/cache.json')}
    out = []
    for answer in answers:
        body = answer['body']
        for digest, name in names.items():
            body = body.replace(digest, name)
        out.append({**answer, 'body': body})
    return out


def design_view(client: Any, id: str, annotation: Optional[str] = None) -> Any:
    query = f'?annotation_id={annotation}' if annotation else ''
    return client.get(f'/api/design-evaluation/jobs/{id}{query}')


# --- The electrode editor ---------------------------------------------------------------------------------------------

EDITOR_PLAN = 'editor-plan.json'
_PROGRESS = "print(json.dumps({'type': 'progress', 'progress': 0.25, 'message': '读取父布局'}), flush=True)\n"
assert EDITOR_FAKE_WORKER.count(_PROGRESS) == 1
EDITOR_WORKER = EDITOR_FAKE_WORKER.replace(_PROGRESS, (
    f"if os.path.exists({EDITOR_PLAN!r}):\n"
    f"    with open({EDITOR_PLAN!r}, encoding='utf-8') as handle:\n"
    "        plan = json.load(handle)\n"
    "    disabled = ','.join(str(i) for i, slot in enumerate(request.get('slots', [])) if not slot['enabled'])\n"
    "    mode = plan.get('%s/%s/%s' % (request['action'], request['parent_id'], disabled), mode)\n"
    "if mode == 'change':\n"
    f"    with open({EDITOR_CODE!r}, 'a', encoding='utf-8') as handle:\n"
    "        handle.write('# changed during the run\\n')\n"
    "if mode == 'reparent':\n"
    "    path = parent['provenance']['file']\n"
    "    with open(path, encoding='utf-8') as handle:\n"
    "        text = handle.read()\n"
    "    with open(path + '.tmp', 'w', encoding='utf-8') as handle:\n"
    "        handle.write(text.replace('T08:00:00Z\"', 'T08:00:00.000Z\"'))\n"
    "    os.replace(path + '.tmp', path)\n") + _PROGRESS)
# The slot an evaluation switches off to pick a behaviour of the plan (``editor_compute_root``).
EDITOR_MODES = {'hold': 63, 'fail': 62, 'stale': 61, 'change': 60}
# The finish time of the stored edits.
STORED_AT = '2026-01-01T00:00:00.000Z'


def editor_plan_key(request: dict) -> str:
    """The plan's key of an editor request: ``<action>/<parent_id>/<the disabled slots, comma-separated>``."""
    disabled = ','.join(str(i) for i, slot in enumerate(request.get('slots', [])) if not slot['enabled'])
    return f"{request['action']}/{request['parent_id']}/{disabled}"


def editor_requests(ids: dict[str, str], digests: dict[str, Optional[str]]) -> dict[str, dict]:
    """The editor requests of the routes' tests, by name: the ``cache`` parent prepared (``prepare``) and evaluated
    with slot 5 switched off (``done``), slots 5 and 6 (``pair``) or the slot of a behaviour (``EDITOR_MODES``); a
    strict-area parent prepared (``strict``); the two stored edits (``stored-prepare``, ``stored-evaluate``) and an
    evaluation of the latter's parent that rewrites that parent (``reparent``)."""
    cache = (ids['cache'], digests['cache'])
    return {
        'prepare': prepare(ids['cache']), 'done': evaluate(*cache, (5,)), 'pair': evaluate(*cache, (5, 6)),
        **{mode: evaluate(*cache, (slot,)) for mode, slot in EDITOR_MODES.items()},
        'strict': prepare(ids['strict']), 'stored-prepare': prepare(ids['strict-2']),
        'stored-evaluate': evaluate(ids['cache-prior'], digests['cache-prior'], (11,)),
        'reparent': evaluate(ids['cache-prior'], digests['cache-prior'], (9,)),
    }


def editor_context(root: Any, request: dict) -> dict:
    """The editor's context of ``request`` on ``root`` as the service computes it (``sys.executable``, no
    ``EEG_COMPUTE_PYTHON``): ``{identity, admission, key, parent, parent_digest}``."""
    import asyncio

    from eeglayoutlab.jobs.editor import EditorJobs
    from eeglayoutlab.jobs.library import Library

    runtime = runtime_config(str(root), sys.executable, env={})
    jobs = EditorJobs(runtime.repository_root, runtime.native_python, Library(runtime.repository_root, runtime))
    return asyncio.run(jobs.context(request))


def editor_key(root: Any, request: dict) -> str:
    return editor_context(root, request)['key']


def stored_edit(root: Any, request: dict, result: dict, identity: Optional[dict] = None) -> str:
    """Writes the ``cache.json`` an editor run would publish for ``request`` (its context computed here, as both
    hosts compute it; ``identity`` replaces the context's) with a fixed finish time; returns the key."""
    context = editor_context(root, request)
    write(Path(root), f"{EDITOR_JOBS}/{context['key']}/cache.json", {
        'key': context['key'], 'identity': context['identity'] if identity is None else identity, 'result': result,
        'result_sha256': jsjson.sha256_hex(result), 'finished_at': STORED_AT})
    return context['key']


def editor_compute_root(directory: Path) -> dict:
    """An editor root (``editor_support.editor_root``) with ``EDITOR_WORKER``, ``DESIGN_WORKER``, the plan of
    ``editor_requests`` and the two stored edits. Returns ``{root, ids, digests, requests, stored}``: the root string
    (its real path), the parents' ids and digests (as the service's library gives them to ``sys.executable``), the
    requests by name and the stored edits' keys by name."""
    from eeglayoutlab.jobs.editor import WORKER_SCRIPT as EDITOR_SCRIPT

    built = editor_root(directory)
    root, ids = built['tree'], built['ids']
    write(Path(root), EDITOR_SCRIPT, EDITOR_WORKER)
    write(Path(root), 'scripts/design_evaluation.py', DESIGN_WORKER)
    digests = parent_digests(root, ids, sys.executable, {})
    requests = editor_requests(ids, digests)
    plan = {editor_plan_key(requests[mode]): mode for mode in EDITOR_MODES}
    plan[editor_plan_key(requests['reparent'])] = 'reparent'
    write(Path(root), EDITOR_PLAN, plan)
    stored = {
        'stored-prepare': stored_edit(root, requests['stored-prepare'],
                                      prepare_result(requests['stored-prepare'], REGIONS['strict-2'])),
        'stored-evaluate': stored_edit(root, requests['stored-evaluate'], evaluate_result(requests['stored-evaluate'])),
    }
    assert parent_digests(root, ids, sys.executable, {}) == digests  # the stored edits are no library records
    return {'root': root, 'ids': ids, 'digests': digests, 'requests': requests, 'stored': stored}


def editor_tree(root: Path) -> dict[str, str]:
    """``R/results/v2/electrode_editor_jobs``."""
    return tree(Path(root) / EDITOR_JOBS)


# --- Signal reception -------------------------------------------------------------------------------------------------

RECEPTION_PLAN = 'reception-plan.json'
# A code file of every reception identity (v1's and v2's), which the ``change`` worker alters.
RECEPTION_CHANGED = 'scripts/source_reception.py'
RECEPTION_WORKERS = ('scripts/run_source_reception.py', 'scripts/run_source_reception_v2.py')
# The seed of a v1 request of the ``cache`` parent that picks a behaviour of the plan.
RECEPTION_MODES = {'hold': 1, 'fail': 2, 'stale': 3, 'change': 4}
_REQUEST = "    data = json.load(handle)\n"
assert RECEPTION_FAKE_WORKER.count(_REQUEST) == 1
RECEPTION_WORKER = RECEPTION_FAKE_WORKER.replace(_REQUEST, _REQUEST + (
    f"if os.path.exists(os.path.join(root, {RECEPTION_PLAN!r})):\n"
    f"    with open(os.path.join(root, {RECEPTION_PLAN!r}), encoding='utf-8') as handle:\n"
    "        mode = json.load(handle).get(str(data['request']['seed']), mode)\n"
    "if mode == 'change':\n"
    f"    with open(os.path.join(root, {RECEPTION_CHANGED!r}), 'a', encoding='utf-8') as handle:\n"
    "        handle.write('# changed during the run\\n')\n"
    "if mode == 'stale':\n"
    "    data['request'] = dict(data['request'], seed=data['request']['seed'] + 1)\n"))


def reception_requests(ids: dict[str, str]) -> dict[str, dict]:
    """The reception requests of the routes' tests, by name: v1 of the ``cache`` parent (``v1``) and with the seed
    of a behaviour (``RECEPTION_MODES``), v2's three modes (``single`` of the strict-area parent, ``multi`` of the
    ``cache`` parent, ``cross`` of the saved coordinate evaluation) and the stored result's request (``stored``, v1 of
    the strict-area parent)."""
    return {'v1': v1(ids['cache']), 'single': single(ids['strict']), 'multi': multi(ids['cache']),
            'cross': cross(ids['design'], ['occipital', 'frontal']), 'stored': v1(ids['strict']),
            **{mode: v1(ids['cache'], seed=seed) for mode, seed in RECEPTION_MODES.items()}}


def reception_context(root: Any, request: dict) -> dict:
    """The reception context of ``request`` on ``root`` as the service computes it (``sys.executable``, no
    ``EEG_COMPUTE_PYTHON``): ``{record, identity, key}``."""
    import asyncio

    from eeglayoutlab.jobs.library import Library
    from eeglayoutlab.jobs.reception import ReceptionJobs

    runtime = runtime_config(str(root), sys.executable, env={})
    jobs = ReceptionJobs(runtime.repository_root, runtime.native_python, Library(runtime.repository_root, runtime),
                         compute_python=runtime.python)

    async def run() -> dict:
        try:
            return await jobs.context(jobs.normalize(request))
        finally:
            await jobs.aclose()
    return asyncio.run(run())


def reception_key(root: Any, request: dict) -> str:
    return reception_context(root, request)['key']


def stored_reception(root: Any, request: dict, identity: Optional[dict] = None, *,
                     finished_at: str = STORED_AT) -> str:
    """Writes the ``cache.json`` a reception run would publish for ``request`` (its context computed here, as both
    hosts compute it; a v2 record holds the context's identity, or ``identity``) with a fixed finish time; returns
    the key."""
    from eeglayoutlab.jobs.reception import _hash
    from eeglayoutlab.schemas.source_reception import normalize_reception_request

    context = reception_context(root, request)
    value = fixture(normalize_reception_request(request), context['record']['layout'])
    key = context['key']
    if 'mode' in request:
        path = f'{SOURCE_V2_JOBS}/{key}/cache.json'
        record = {'key': key, 'identity': context['identity'] if identity is None else identity, 'result': value}
    else:
        assert identity is None
        path = f'{SOURCE_JOBS}/{key}/cache.json'
        record = {'key': key, 'result': value}
    write(Path(root), path, {**record, 'result_sha256': _hash(value), 'finished_at': finished_at})
    return key


def reception_compute_root(directory: Path) -> dict:
    """A reception root (``reception_support.reception_root``) with ``RECEPTION_WORKER`` as both workers,
    ``DESIGN_WORKER``, the plan and the stored result of ``requests['stored']``. Returns ``{root, ids, requests,
    stored}``: the root string (its real path), the parents' ids, the requests by name and the stored result's key."""
    built = reception_root(directory)
    root, ids = built['tree'], built['ids']
    for script in RECEPTION_WORKERS:
        write(Path(root), script, RECEPTION_WORKER)
    write(Path(root), 'scripts/design_evaluation.py', DESIGN_WORKER)
    write(Path(root), RECEPTION_PLAN, {str(seed): mode for mode, seed in RECEPTION_MODES.items()})
    requests = reception_requests(ids)
    return {'root': root, 'ids': ids, 'requests': requests, 'stored': stored_reception(root, requests['stored'])}


def reception_tree(root: Path) -> dict[str, str]:
    """``R/results/v2/source_reception_jobs`` and ``source_reception_v2_jobs``, by path below ``R/results/v2``."""
    return {**{f'source_reception_jobs/{path}': text for path, text in tree(Path(root) / SOURCE_JOBS).items()},
            **{f'source_reception_v2_jobs/{path}': text for path, text in tree(Path(root) / SOURCE_V2_JOBS).items()}}


def briefed_tree(records: dict[str, str]) -> dict[str, str]:
    """``masked_tree`` of a reception tree, each text longer than ``BRIEF`` bytes by its SHA-256."""
    return {path: brief(text) for path, text in masked_tree(records).items()}


_SR = '/api/source-reception'
_CR = '/api/community/records'
# The text of a cache.json whose checksum fails: ``{k0}`` is the key of the first receipt.
_TAMPERED = '{"key":"{k0}","result":{"a":1},"result_sha256":"' + '0' * 64 + '"}'


def reception_steps(built: dict) -> list[dict]:
    """Signal reception on ``reception_compute_root``'s root ``built``. Receipts: {0} v1 (computed, key {k0}), {1}
    the stored result (cached), {2} single, {3} multi, {4} cross, {5} hold (cancelled), {6} a coordinate evaluation
    queued behind it, {7} fail (cancelled while queued), {8} fail, {9} stale, {10} change."""
    ids, r = built['ids'], built['requests']
    a = r['v1']
    return [
        {'method': 'GET', 'path': f'{_SR}/health'},
        {'method': 'GET', 'path': _CR},
        {'method': 'GET', 'path': f'{_SR}/catalog'},
        # A lookup miss creates no receipt; a v1 request runs, then is the stored receipt.
        {'method': 'POST', 'path': f'{_SR}/lookup', 'body': a},
        {'method': 'GET', 'path': _CR},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': a},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{0}}', 'until': TERMINAL},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': a},
        {'method': 'POST', 'path': f'{_SR}/lookup', 'body': a},
        # A stored result neither host computed: its lookup is one cached receipt, which the submit reuses.
        {'method': 'POST', 'path': f'{_SR}/lookup', 'body': r['stored']},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': r['stored']},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{1}}'},
        # The three modes of v2.
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': r['single']},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{2}}', 'until': TERMINAL},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': r['multi']},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{3}}', 'until': TERMINAL},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': r['cross']},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{4}}', 'until': TERMINAL},
        # The records list and the original downloads.
        {'method': 'GET', 'path': _CR},
        {'method': 'GET', 'path': f'{_CR}/{{0}}/result'},
        {'method': 'GET', 'path': f'{_CR}/{{1}}/result'},
        {'method': 'GET', 'path': f'{_CR}/{{4}}/result'},
        # A running worker: joins, the health's active job, a coordinate evaluation and a reception queued behind
        # it, cancellations; the evaluation runs once the slot is free.
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': r['hold']},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{5}}', 'until': ('running',), 'progress': True},
        {'method': 'GET', 'path': f'{_SR}/health'},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': r['hold']},
        {'method': 'POST', 'path': f'{_SR}/lookup', 'body': r['hold']},
        {'method': 'POST', 'path': '/api/design-evaluation/jobs', 'body': DESIGN_REQUESTS['done']},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': r['fail']},
        {'method': 'GET', 'path': '/api/community/status'},
        {'method': 'GET', 'path': '/api/design-evaluation/health'},
        {'method': 'GET', 'path': f'{_CR}/{{5}}/result'},
        {'method': 'POST', 'path': f'{_SR}/jobs/{{7}}/cancel'},
        {'method': 'POST', 'path': f'{_SR}/jobs/{{5}}/cancel'},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{5}}', 'until': TERMINAL},
        {'method': 'POST', 'path': f'{_SR}/jobs/{{5}}/cancel'},
        {'method': 'GET', 'path': '/api/design-evaluation/jobs/{6}', 'until': TERMINAL},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': r['fail']},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{8}}', 'until': TERMINAL},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': r['stale']},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{9}}', 'until': TERMINAL},
        # Receipts without a saved result, of another kind or unknown, and the community routes' 404s.
        {'method': 'GET', 'path': f'{_CR}/{{8}}/result'},
        {'method': 'GET', 'path': f'{_CR}/{{7}}/result'},
        {'method': 'GET', 'path': f'{_CR}/{{5}}/result'},
        {'method': 'GET', 'path': f'{_CR}/{{6}}/result'},
        {'method': 'GET', 'path': f'{_CR}/{_UNKNOWN}/result'},
        {'method': 'GET', 'path': f'{_CR}/not-a-receipt/result'},
        {'method': 'GET', 'path': f'{_CR}/{{0}}'},
        {'method': 'POST', 'path': _CR},
        {'method': 'POST', 'path': f'{_CR}/{{0}}/result'},
        {'method': 'GET', 'path': _CR},
        # Refusals: the parent's checks, the request format, the body rules, the token, the routes.
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': v1(ids['missing'])},
        {'method': 'POST', 'path': f'{_SR}/lookup', 'body': v1(ids['historical'])},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': v1(ids['design'])},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': v1(ids['cache-prior'])},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': single(ids['missing'])},
        {'method': 'POST', 'path': f'{_SR}/lookup', 'body': single(ids['cache-spatial'])},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': multi(ids['cache'], definition=False)},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': {**a, 'ar': 90}},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': {**r['single'], 'source_index': 256}},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': None},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'raw': padded(a, 4096)},
        {'method': 'POST', 'path': f'{_SR}/lookup', 'raw': padded(a, 4097)},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'raw': '{}', 'type': 'text/plain'},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'raw': '{"record_id":'},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': a, 'token': False},
        {'method': 'POST', 'path': f'{_SR}/jobs/{{0}}/cancel', 'token': False},
        {'method': 'POST', 'path': f'{_SR}/jobs/{{0}}/cancel'},
        {'method': 'GET', 'path': f'{_SR}/jobs/{_UNKNOWN}'},
        {'method': 'POST', 'path': f'{_SR}/jobs/{_UNKNOWN}/cancel'},
        {'method': 'GET', 'path': f'{_SR}/jobs/not-a-receipt'},
        {'method': 'GET', 'path': f'{_SR}/other'},
        {'method': 'GET', 'path': f'{_SR}/jobs'},
        {'method': 'POST', 'path': f'{_SR}/jobs/{{0}}'},
        {'method': 'POST', 'path': f'{_SR}/catalog'},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{6}}'},
        {'method': 'GET', 'path': '/api/design-evaluation/jobs/{0}'},
        # The catalog worker fails: computeMiddleware's 500.
        {'method': 'FILE', 'path': 'stub/catalog.txt', 'text': 'exit:3'},
        {'method': 'GET', 'path': f'{_SR}/catalog'},
        {'method': 'FILE', 'path': 'stub/catalog.txt', 'text': jsjson.stringify({**CATALOG, 'sources': []})},
        {'method': 'GET', 'path': f'{_SR}/catalog'},
        {'method': 'FILE', 'path': 'stub/catalog.txt', 'text': jsjson.stringify(CATALOG)},
        {'method': 'GET', 'path': f'{_SR}/catalog'},
        # The saved result of {0} fails its checks, then is gone; the receipt's view keeps the result it holds.
        {'method': 'FILE', 'path': f'{SOURCE_JOBS}/{{k0}}/cache.json', 'text': 'not json'},
        {'method': 'GET', 'path': f'{_CR}/{{0}}/result'},
        {'method': 'POST', 'path': f'{_SR}/lookup', 'body': a},
        {'method': 'FILE', 'path': f'{SOURCE_JOBS}/{{k0}}/cache.json', 'text': _TAMPERED},
        {'method': 'GET', 'path': f'{_CR}/{{0}}/result'},
        {'method': 'FILE', 'path': f'{SOURCE_JOBS}/{{k0}}/cache.json', 'text': None},
        {'method': 'GET', 'path': f'{_CR}/{{0}}/result'},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{0}}'},
        {'method': 'GET', 'path': _CR},
        # The worker changes the reception code: the run fails, the cached receipt's view is stale, and its
        # original download is still served.
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': r['change']},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{10}}', 'until': TERMINAL},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{1}}'},
        {'method': 'GET', 'path': f'{_CR}/{{1}}/result'},
        {'method': 'POST', 'path': f'{_SR}/lookup', 'body': r['stored']},
        {'method': 'GET', 'path': f'{_SR}/health'},
        {'method': 'GET', 'path': '/api/community/status'},
    ]


# --- Parity with Node's composed service --------------------------------------------------------------------------

# The steps both hosts run (parity/compute_routes.mjs documents them). {N} in a path is the id of the N-th receipt
# (by first appearance) of the answers so far, {aN} the N-th annotation id and {kN} the N-th key.
STEPS: list[dict] = [
    {'method': 'GET', 'path': '/api/local-compute/health'},
    {'method': 'GET', 'path': '/api/community/status'},
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'body': REQUESTS['done']},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['done']},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{0}', 'until': TERMINAL},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['done']},
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'body': REQUESTS['done']},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['none']},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{1}', 'until': TERMINAL},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['crash']},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{2}', 'until': TERMINAL},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['stale']},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{3}', 'until': TERMINAL},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['hold']},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{4}', 'until': ('running',), 'progress': True},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['hold']},
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'body': REQUESTS['hold']},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['second-hold']},
    {'method': 'GET', 'path': '/api/local-compute/health'},
    {'method': 'POST', 'path': '/api/local-compute/jobs/{5}/cancel'},
    {'method': 'POST', 'path': '/api/local-compute/jobs/{4}/cancel'},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{4}', 'until': TERMINAL},
    {'method': 'POST', 'path': '/api/local-compute/jobs/{4}/cancel'},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{0}'},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{0}?annotation_id=' + 'a' * 64},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{0}?other=1'},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{0}?annotation_id=ABC'},
    {'method': 'GET', 'path': '/api/local-compute/jobs/00000000-0000-4000-8000-000000000000'},
    {'method': 'POST', 'path': '/api/local-compute/jobs/00000000-0000-4000-8000-000000000000/cancel'},
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'body': {**REQUESTS['none'], 'AR': 0.9}},
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'raw': '{"region_count":'},
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'raw': '{}', 'type': 'text/plain'},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'raw': ' ' * 4097},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['none'], 'token': False},
    {'method': 'POST', 'path': '/api/local-compute/jobs/{0}/cancel', 'token': False},
    {'method': 'GET', 'path': '/api/local-compute/library'},
    {'method': 'GET', 'path': '/api/community/status'},
]

_D = '/api/design-evaluation'
_R = DESIGN_REQUESTS
_UNKNOWN = '00000000-0000-4000-8000-000000000000'
# The coordinate evaluation on design_compute_root. Receipts: {0} done (computed), {1} cached (the stored evaluation),
# {2} hold (cancelled), {3} fail (cancelled while queued), {4} fail, {5} stale, {6} change. Annotations: {a0} A, {a1}
# B (its body sent one byte per chunk), {a2} C with source metadata on {0}; {a3} A on {1}; {a4} A on {2}; {a5} D, in a
# body of exactly the limit, on {0}.
DESIGN_STEPS: list[dict] = [
    {'method': 'GET', 'path': f'{_D}/health'},
    {'method': 'GET', 'path': '/api/community/status'},
    # A lookup miss creates neither a receipt nor an annotation.
    {'method': 'POST', 'path': f'{_D}/lookup', 'body': _R['done']},
    {'method': 'POST', 'path': f'{_D}/lookup', 'body': envelope(_R['done'], 'A')},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': envelope(_R['done'], 'A')},
    {'method': 'GET', 'path': f'{_D}/jobs/{{0}}', 'until': TERMINAL},
    {'method': 'GET', 'path': f'{_D}/jobs/{{0}}?annotation_id={{a0}}'},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': envelope(_R['done'], 'A')},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': envelope(_R['done'], 'B'), 'chunks': True},
    {'method': 'POST', 'path': f'{_D}/lookup', 'body': envelope(_R['done'], 'B')},
    {'method': 'POST', 'path': f'{_D}/lookup', 'body': _R['done']},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': envelope(_R['done'], 'C', SOURCE)},
    {'method': 'GET', 'path': f'{_D}/jobs/{{0}}?annotation_id={{a1}}'},
    {'method': 'GET', 'path': f'{_D}/jobs/{{0}}?annotation_id=' + 'b' * 64},
    {'method': 'GET', 'path': f'{_D}/jobs/{{0}}?annotation_id={{a0}}&annotation_id={{a1}}'},
    # A stored evaluation neither host computed: one cached receipt, reused with and without names.
    {'method': 'POST', 'path': f'{_D}/lookup', 'body': _R['cached']},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': envelope(_R['cached'], 'A')},
    {'method': 'POST', 'path': f'{_D}/lookup', 'body': envelope(_R['cached'], 'A')},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': _R['cached']},
    {'method': 'GET', 'path': f'{_D}/jobs/{{1}}?annotation_id={{a3}}'},
    {'method': 'GET', 'path': f'{_D}/jobs/{{1}}?annotation_id={{a0}}'},
    # A running worker: joins, the health's active job, a queued task behind it, cancellations.
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': _R['hold']},
    {'method': 'GET', 'path': f'{_D}/jobs/{{2}}', 'until': ('running',), 'progress': True},
    {'method': 'GET', 'path': f'{_D}/health'},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': envelope(_R['hold'], 'A')},
    {'method': 'POST', 'path': f'{_D}/lookup', 'body': _R['hold']},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': _R['fail']},
    {'method': 'GET', 'path': '/api/community/status'},
    {'method': 'POST', 'path': f'{_D}/jobs/{{3}}/cancel'},
    {'method': 'POST', 'path': f'{_D}/jobs/{{2}}/cancel'},
    {'method': 'GET', 'path': f'{_D}/jobs/{{2}}?annotation_id={{a4}}', 'until': TERMINAL},
    {'method': 'POST', 'path': f'{_D}/jobs/{{2}}/cancel'},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': _R['fail']},
    {'method': 'GET', 'path': f'{_D}/jobs/{{4}}', 'until': TERMINAL},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': _R['stale']},
    {'method': 'GET', 'path': f'{_D}/jobs/{{5}}', 'until': TERMINAL},
    # The library's record and bundle with an annotation the Python service wrote to W (Node: to R).
    {'method': 'GET', 'path': '/api/local-compute/library/{k0}?annotation_id={a0}'},
    {'method': 'GET', 'path': '/api/local-compute/library/{k0}/bundle?annotation_id={a2}'},
    {'method': 'GET', 'path': '/api/local-compute/library/{k0}?annotation_id={a0}&other=1'},
    {'method': 'GET', 'path': '/api/local-compute/library/{k0}?annotation_id={a3}'},
    {'method': 'GET', 'path': '/api/local-compute/library/{k1}?annotation_id={a3}'},
    {'method': 'GET', 'path': '/api/local-compute/library/{k0}?annotation_id=' + 'c' * 64},
    # Refusals: the envelope's checks in Node's order, the request format, the body rules, the token.
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': {**envelope(_R['done'], 'A'), 'electrode_names': names('A')[:63]}},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': envelope(_R['done'], 'A', note='x')},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': envelope(_R['done'], 'A', {**SOURCE, 'unit': 'cm'})},
    {'method': 'POST', 'path': f'{_D}/lookup', 'body': {**envelope(_R['done'], 'A'), 'source_metadata': None}},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': envelope({}, 'A')},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': envelope(None, 'A')},
    {'method': 'POST', 'path': f'{_D}/lookup', 'body': {**_R['done'], 'design': {**DESIGN, 'unit': 'cm'}}},
    {'method': 'POST', 'path': f'{_D}/jobs', 'raw': padded(envelope(_R['done'], 'D'), 65536)},
    {'method': 'POST', 'path': f'{_D}/lookup', 'raw': padded(envelope(_R['done'], 'D'), 65537)},
    {'method': 'POST', 'path': f'{_D}/jobs', 'raw': '{}', 'type': 'text/plain'},
    {'method': 'POST', 'path': f'{_D}/jobs', 'raw': '{"schema":'},
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': envelope(_R['done'], 'A'), 'token': False},
    {'method': 'POST', 'path': f'{_D}/jobs/{{0}}/cancel', 'token': False},
    {'method': 'GET', 'path': f'{_D}/jobs/{_UNKNOWN}'},
    {'method': 'POST', 'path': f'{_D}/jobs/{_UNKNOWN}/cancel'},
    # The worker changes a code file of the identity: the run fails, and the stored receipt's key is stale.
    {'method': 'POST', 'path': f'{_D}/jobs', 'body': _R['change']},
    {'method': 'GET', 'path': f'{_D}/jobs/{{6}}', 'until': TERMINAL},
    {'method': 'GET', 'path': f'{_D}/jobs/{{1}}'},
    {'method': 'GET', 'path': f'{_D}/jobs/{{0}}?annotation_id={{a0}}'},
    {'method': 'POST', 'path': f'{_D}/lookup', 'body': _R['done']},
    {'method': 'GET', 'path': '/api/community/status'},
]
_E = '/api/electrode-editor'


def editor_steps(built: dict) -> list[dict]:
    """The electrode editor on ``editor_compute_root``'s root ``built``. Receipts: {0} the ``cache`` parent prepared,
    {1} evaluated, {2} the pair (its body sent one byte per chunk), {3} the strict parent prepared, {4} and {5} the
    stored preparation and evaluation (cached), {6} hold (cancelled), {7} a coordinate evaluation queued behind it,
    {8} fail (cancelled while queued), {9} fail, {10} stale, {11} reparent, {12} change."""
    ids, r = built['ids'], built['requests']
    p, done = r['prepare'], r['done']
    stale_digest = evaluate(ids['cache'], STALE, (5,))
    return [
        {'method': 'GET', 'path': f'{_E}/health'},
        {'method': 'GET', 'path': f'{_E}/parents'},
        {'method': 'GET', 'path': f'{_E}/records'},
        # A lookup miss creates no receipt; a preparation runs, then is the stored receipt.
        {'method': 'POST', 'path': f'{_E}/lookup', 'body': p},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': p},
        {'method': 'GET', 'path': f'{_E}/jobs/{{0}}', 'until': TERMINAL},
        {'method': 'GET', 'path': f'{_E}/jobs/{{0}}?annotation_id=' + 'a' * 64},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': p},
        {'method': 'POST', 'path': f'{_E}/lookup', 'body': p},
        # Evaluations with the parent's digest; the pair's body arrives one byte per chunk.
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': done},
        {'method': 'GET', 'path': f'{_E}/jobs/{{1}}', 'until': TERMINAL},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': done},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': r['pair'], 'chunks': True},
        {'method': 'GET', 'path': f'{_E}/jobs/{{2}}', 'until': TERMINAL},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': r['strict']},
        {'method': 'GET', 'path': f'{_E}/jobs/{{3}}', 'until': TERMINAL},
        # Stored edits neither host computed: one cached receipt each.
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': r['stored-prepare']},
        {'method': 'POST', 'path': f'{_E}/lookup', 'body': r['stored-prepare']},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': r['stored-evaluate']},
        {'method': 'GET', 'path': f'{_E}/records'},
        # A running worker: joins, the health's active job, a coordinate evaluation and an edit queued behind it,
        # cancellations; the evaluation runs once the slot is free.
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': r['hold']},
        {'method': 'GET', 'path': f'{_E}/jobs/{{6}}', 'until': ('running',), 'progress': True},
        {'method': 'GET', 'path': f'{_E}/health'},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': r['hold']},
        {'method': 'POST', 'path': f'{_E}/lookup', 'body': r['hold']},
        {'method': 'POST', 'path': '/api/design-evaluation/jobs', 'body': DESIGN_REQUESTS['done']},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': r['fail']},
        {'method': 'GET', 'path': '/api/community/status'},
        {'method': 'GET', 'path': '/api/design-evaluation/health'},
        {'method': 'POST', 'path': f'{_E}/jobs/{{8}}/cancel'},
        {'method': 'POST', 'path': f'{_E}/jobs/{{6}}/cancel'},
        {'method': 'GET', 'path': f'{_E}/jobs/{{6}}', 'until': TERMINAL},
        {'method': 'POST', 'path': f'{_E}/jobs/{{6}}/cancel'},
        {'method': 'GET', 'path': '/api/design-evaluation/jobs/{7}', 'until': TERMINAL},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': r['fail']},
        {'method': 'GET', 'path': f'{_E}/jobs/{{9}}', 'until': TERMINAL},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': r['stale']},
        {'method': 'GET', 'path': f'{_E}/jobs/{{10}}', 'until': TERMINAL},
        # Refusals: the parent's checks in Node's order, the request format, the body rules, the token, the routes.
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': stale_digest},
        {'method': 'POST', 'path': f'{_E}/lookup', 'body': stale_digest},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': prepare(ids['cache-spatial'])},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': evaluate(ids['cache-spatial'], STALE)},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': prepare(MISSING)},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': prepare(ids['design'])},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': prepare(ids['cache-unpatched'])},
        {'method': 'POST', 'path': f'{_E}/lookup', 'body': prepare(ids['cache-geometry'])},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': {'action': 'prepare'}},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': {**p, 'seed': 2026}},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': {**done, 'seed': 2027}},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': {**done, 'slots': done['slots'][1:]}},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': evaluate(ids['cache'], built['digests']['cache'],
                                                                   tuple(range(63)))},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': None},
        {'method': 'POST', 'path': f'{_E}/jobs', 'raw': padded(p, 32768)},
        {'method': 'POST', 'path': f'{_E}/lookup', 'raw': padded(p, 32769)},
        {'method': 'POST', 'path': f'{_E}/jobs', 'raw': '{}', 'type': 'text/plain'},
        {'method': 'POST', 'path': f'{_E}/jobs', 'raw': '{"action":'},
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': p, 'token': False},
        {'method': 'POST', 'path': f'{_E}/jobs/{{0}}/cancel', 'token': False},
        {'method': 'POST', 'path': f'{_E}/jobs/{{0}}/cancel'},
        {'method': 'GET', 'path': f'{_E}/jobs/{_UNKNOWN}'},
        {'method': 'POST', 'path': f'{_E}/jobs/{_UNKNOWN}/cancel'},
        {'method': 'GET', 'path': f'{_E}/jobs/not-a-receipt'},
        {'method': 'GET', 'path': f'{_E}/other'},
        {'method': 'GET', 'path': f'{_E}/jobs'},
        {'method': 'POST', 'path': f'{_E}/jobs/{{0}}'},
        {'method': 'GET', 'path': '/api/design-evaluation/jobs/{0}'},
        {'method': 'GET', 'path': f'{_E}/jobs/{{7}}'},
        # The worker rewrites its parent: the run fails, and the stored evaluation of that parent is refused.
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': r['reparent']},
        {'method': 'GET', 'path': f'{_E}/jobs/{{11}}', 'until': TERMINAL},
        {'method': 'GET', 'path': f'{_E}/jobs/{{5}}'},
        {'method': 'GET', 'path': f'{_E}/jobs/{{4}}'},
        {'method': 'GET', 'path': f'{_E}/parents'},
        # The worker changes the editor's code: the run fails, and the stored receipts' keys are stale.
        {'method': 'POST', 'path': f'{_E}/jobs', 'body': r['change']},
        {'method': 'GET', 'path': f'{_E}/jobs/{{12}}', 'until': TERMINAL},
        {'method': 'GET', 'path': f'{_E}/jobs/{{4}}'},
        {'method': 'GET', 'path': f'{_E}/jobs/{{0}}'},
        {'method': 'POST', 'path': f'{_E}/lookup', 'body': p},
        {'method': 'GET', 'path': f'{_E}/records'},
        {'method': 'GET', 'path': '/api/community/status'},
    ]


_ID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
_TIME = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z')
# The members only Node has, its public-service machinery: the visitor count of the status, and the public library's
# ``visibility`` (on rows) and ``library_scope`` (test_library_parity.py removes them the same way).
_NODE_ONLY = ('online_visitors', 'visibility', 'library_scope')


# A path's ``{N}`` is a UUID that is a whole JSON string (a receipt), not one inside a path such as the interpreter's.
_RECEIPT = re.compile(r'"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"')
_ANNOTATION_ID = re.compile(r'"annotation_id":"([a-f0-9]{64})"')
_KEY = re.compile(r'"key":"([a-f0-9]{64})"')


def _ids(text: str, ids: list[str]) -> None:
    for id in _ID.findall(text):
        if id not in ids:
            ids.append(id)


def _seen(text: str, seen: dict[str, list[str]]) -> None:
    """Collects the receipt ids (``''``), annotation ids (``'a'``) and keys (``'k'``) of a body in order."""
    for kind, pattern in (('', _RECEIPT), ('a', _ANNOTATION_ID), ('k', _KEY)):
        for value in pattern.findall(text):
            if value not in seen[kind]:
                seen[kind].append(value)


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {name: _strip(member) for name, member in value.items() if name not in _NODE_ONLY}
    if isinstance(value, list):
        return [_strip(member) for member in value]
    return value


def masked(answers: list[dict], token: str) -> list[dict]:
    """Receipt and job ids numbered by first appearance, times and the CSRF token masked, Node's visitor count
    dropped; bodies re-serialized with ``JSON.stringify`` so that member order still counts."""
    ids: list[str] = []
    for answer in answers:
        _ids(answer['body'], ids)
    out = []
    for answer in answers:
        text = answer['body'].replace(token, '<token>')
        try:
            text = jsjson.stringify(_strip(jsjson.parse(text)))
        except Exception:  # noqa: BLE001 - a body that is not JSON is compared as it is
            pass
        text = _ID.sub(lambda match: f'<id{ids.index(match.group(0))}>', text)
        text = _TIME.sub('<time>', text)
        out.append({**answer, 'body': text})
    return out


_RESULT = '"result":'


def _briefed(text: str) -> str:
    """``text`` with each ``"result"`` member whose value is an object or array longer than ``BRIEF`` characters
    replaced by ``"sha256:<hex of its exact text>"``: a signal result is about 1 MB, which the port of
    ``JSON.stringify`` takes about a second to write again, and it holds no id or time to mask."""
    if len(text) <= BRIEF:
        return text
    decoder = json.JSONDecoder()
    out: list[str] = []
    at = 0
    while True:
        index = text.find(_RESULT, at)
        if index < 0:
            break
        start = index + len(_RESULT)
        out.append(text[at:start])
        at = start
        if text[start:start + 1] not in ('{', '['):
            continue
        end = decoder.raw_decode(text, start)[1]
        span = text[start:end]
        out.append('"sha256:' + hashlib.sha256(span.encode('utf-8')).hexdigest() + '"' if len(span) > BRIEF
                   else span)
        at = end
    out.append(text[at:])
    return ''.join(out)


def reception_masked(answers: list[dict], token: str, node: bool = False) -> list[dict]:
    """``masked`` of answers that may carry signal results (``_briefed``); ``node`` reads Node's records scope,
    one browser's (``current_browser``), as the workspace's."""
    out = []
    for answer in answers:
        body = answer['body']
        if node:
            body = body.replace('"scope":"current_browser"', '"scope":"workspace"', 1)
        out.append({**answer, 'body': _briefed(body)})
    return masked(out, token)


def masked_tree(tree: dict[str, str]) -> dict[str, str]:
    """A record tree with batch and job ids and times masked; keys are kept."""
    ids: list[str] = []
    for path in tree:
        _ids(path, ids)
    out = {}
    for path, text in tree.items():
        name = _ID.sub(lambda match: f'<id{ids.index(match.group(0))}>', path)
        out[name] = _TIME.sub('<time>', _ID.sub('<job>', text))
    return out


def run_node(root: Path, scratch: Path, steps: list[dict] = STEPS, owner: str = 'parity-owner',
             network: Optional[str] = None) -> dict:
    """Node's composed service (``createLocalComputeService``) over ``root`` with its state in ``scratch``, its
    session pinned to ``owner`` (``LOCAL_OWNER`` gives Node's annotations the Python service's ids and bytes) and
    ``network`` (``'loopback'`` by default; Node's study records require a SHA-256, ``STUDY_NETWORK``)."""
    spec = scratch / 'spec.json'
    out = scratch / 'out.json'
    spec.write_text(json.dumps({'root': str(root), 'queueDirectory': str(scratch / 'queue'),
                                'python': sys.executable, 'owner': owner, 'steps': steps,
                                'terminal': list(TERMINAL), 'settle_ms': SETTLE * 1000,
                                **({'network': network} if network is not None else {})}), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec), str(out)], check=True, env=NODE_ENV, timeout=300)
    return json.loads(out.read_text(encoding='utf-8'))


def _target(path: str, seen: dict[str, list[str]], captured: Optional[dict[str, Any]] = None) -> str:
    """The driver's ``substitute``: ``{N}``, ``{aN}`` and ``{kN}`` from ``seen``, ``{$name}`` from ``captured`` (as
    JavaScript's ``String`` writes it)."""
    text = re.sub(r'\{([ak]?)(\d+)\}', lambda match: seen[match.group(1)][int(match.group(2))], path)
    return re.sub(r'\{\$(\w+)\}', lambda match: _js_text((captured or {}).get(match.group(1), UNDEFINED)), text)


def _js_text(value: Any) -> str:
    if value is UNDEFINED:
        return 'undefined'
    if isinstance(value, str):
        return value
    return jsjson.stringify(value)


_PROJECT_PATH = re.compile(r'/api/projects/([0-9a-f-]{36})(?:[/?]|$)')


def chunked(app: Service, client: Any, method: str, target: str, data: bytes, headers: dict[str, str]) -> Any:
    """One request whose body reaches the application one byte per ASGI message, on the event loop of ``client``'s
    lifespan (the test client hands an application the whole body at once). Returns ``(status, headers, text)``."""
    from .service_support import HOST, PORT, session_cookie

    path, _, query = target.partition('?')
    sent = [(b'host', HOST.encode()), (b'cookie', session_cookie().encode())]
    sent += [(name.lower().encode('latin-1'), value.encode('latin-1')) for name, value in headers.items()]
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'http',
             'path': path, 'raw_path': path.encode('latin-1'), 'query_string': query.encode('latin-1'),
             'root_path': '', 'headers': sent, 'client': ('127.0.0.1', 50000), 'server': ('127.0.0.1', PORT)}
    pieces = [data[index:index + 1] for index in range(len(data))]
    messages: list[dict] = []

    async def run() -> None:
        async def receive() -> dict:
            if pieces:
                return {'type': 'http.request', 'body': pieces.pop(0), 'more_body': bool(pieces)}
            return {'type': 'http.request', 'body': b'', 'more_body': False}

        async def send(message: dict) -> None:
            messages.append(message)

        await app(scope, receive, send)

    client.portal.call(run)
    start = next(message for message in messages if message['type'] == 'http.response.start')
    received = {name.decode('latin-1').lower(): value.decode('latin-1') for name, value in start['headers']}
    body = b''.join(message.get('body', b'') for message in messages if message['type'] == 'http.response.body')
    return start['status'], received, body.decode('utf-8')


def _member(value: Any, field: str, missing: Any = None) -> Any:
    """The driver's ``field.split('.').reduce((member, name) => member?.[name], value)``; ``missing`` stands for
    ``undefined``."""
    for name in field.split('.'):
        if isinstance(value, dict) and name in value:
            value = value[name]
        elif isinstance(value, list) and name.isdigit() and int(name) < len(value):
            value = value[int(name)]
        else:
            return missing
    return value


def run_python(root: Path, workspace: Path, steps: list[dict] = STEPS, **options: Any) -> dict:
    """The same steps through the Python application, as the driver sends them: ``{N}`` is the N-th distinct id
    in the bodies so far (``{aN}`` the N-th annotation id, ``{kN}`` the N-th key; a ``brief`` step's are not
    collected) and ``{$name}`` a member an earlier step's ``capture`` kept; a step other than GET carries the CSRF
    token unless it says ``token: false``, and its ``headers``; a step under ``/api/projects/<id>`` carries the access
    key of that project's create answer (ignored, as Node's credential); a step with ``chunks`` sends its body one byte
    at a time, a step with ``until`` is repeated until its job (or the member ``field`` names) reaches one of those
    statuses (with ``progress``, a progress above 0), and a ``FILE`` step writes ``text`` to its path below the root
    (removes the file when ``text`` is ``None``). ``options`` go to ``serving``."""
    answers: list[dict] = []
    seen: dict[str, list[str]] = {'': [], 'a': [], 'k': []}
    captured: dict[str, Any] = {}
    keys: dict[str, str] = {}
    with serving(root, workspace, csrf=False, **options) as (app, client):
        for step in steps:
            target = _target(step['path'], seen, captured)
            if step['method'] == 'FILE':
                path = Path(root) / target
                if step['text'] is None:
                    path.unlink()
                else:
                    path.write_bytes(_target(step['text'], seen, captured).encode('utf-8'))
                answers.append({'method': 'FILE', 'path': step['path'], 'status': 0, 'type': None, 'disposition': None,
                                'body': ''})
                continue
            headers = {}
            data = None
            if step['method'] != 'GET':
                headers['content-type'] = step.get('type', 'application/json')
                if step.get('token', True):
                    headers['x-eeg-compute-token'] = TOKENS.csrf
                data = (_target(step['raw'], seen, captured) if 'raw' in step
                        else _target(jsjson.stringify(step['body']), seen, captured) if 'body' in step else None)
            project = _PROJECT_PATH.match(target)
            if project and project.group(1) in keys and step.get('key', True):
                headers['x-eeg-project-key'] = keys[project.group(1)]
            for name, value in step.get('headers', {}).items():
                headers[name.lower()] = _target(value, seen, captured)
            deadline = time.monotonic() + SETTLE
            while True:
                if step.get('chunks'):
                    status, received, body = chunked(app, client, step['method'], target,
                                                     (data or '').encode('utf-8'), headers)
                    kind, disposition = received.get('content-type'), received.get('content-disposition')
                else:
                    response = client.request(step['method'], target, content=data, headers=headers)
                    status, kind, body = response.status_code, response.headers.get('content-type'), response.text
                    disposition = response.headers.get('content-disposition')
                until = step.get('until')
                if until is None:
                    break
                if 'field' in step:
                    if _member(jsjson.parse(body), step['field']) in until:
                        break
                else:
                    job = jsjson.parse(body)['job']
                    if job['status'] in until and (not step.get('progress') or job['progress'] > 0):
                        break
                if time.monotonic() > deadline:
                    raise AssertionError(f'{target} did not settle: {body}')
                time.sleep(0.02)
            if step['method'] == 'POST' and target == '/api/projects' and status == 201:
                created = jsjson.parse(body)
                keys[created['project']['id']] = created['access_key']
            for name, field in step.get('capture', {}).items():
                captured[name] = _member(jsjson.parse(body), field, UNDEFINED)
            if not step.get('brief'):
                _seen(body, seen)
            answers.append({'method': step['method'], 'path': step['path'], 'status': status, 'type': kind,
                            'disposition': disposition, 'body': body})
    return {'answers': answers, 'token': TOKENS.csrf, 'tree': jobs_tree(root), 'queue': queue_file(workspace),
            'design_tree': design_tree(root), 'editor_tree': editor_tree(root), 'reception_tree': reception_tree(root),
            'annotations': annotation_tree(workspace / WORKSPACE_ANNOTATIONS),
            'studies': study_tree(workspace / 'studies'), 'projects': study_tree(workspace / 'projects')}


# --- Robustness studies -----------------------------------------------------------------------------------------------

_S = '/api/robustness-studies'
STUDY_HEADS = ('ixi002', 'a')
# Node's session network for the study parity: its study records hold one, which must be a SHA-256.
STUDY_NETWORK = hashlib.sha256(b'parity-network').hexdigest()
STUDY_DONE = ('completed', 'completed_with_failures', 'cancelled')


def study_body(protocol: str, name: str, cases: list[tuple], annotated: bool = False, **extra: Any) -> dict:
    """A study of ``DESIGN`` named ``name`` (the stand-in worker's behaviour), with names and the source declaration
    when ``annotated``; ``cases`` are ``(seed, radius_mm)`` or, for ``heads``, ``(head_id, seed, radius_mm)``."""
    design = {**DESIGN, 'name': name}
    if annotated:
        design.update(electrode_names=names('S'), source_metadata=SOURCE)
    rows = [{'head_id': case[0], 'seed': case[1], 'radius_mm': case[2]} if len(case) == 3
            else {'seed': case[0], 'radius_mm': case[1]} for case in cases]
    return {'protocol': protocol, 'design': design, 'cases': rows, **extra}


def _settle(id: str) -> dict:
    return {'method': 'GET', 'path': f'{_S}/{id}', 'until': STUDY_DONE, 'field': 'study.status'}


def _control(id: str, action: str, **extra: Any) -> dict:
    return {'method': 'POST', 'path': f'{_S}/{id}/{action}', 'body': {}, **extra}


# The studies on study_compute_root (a design root with STUDY_HEADS). Ids: {0} the evaluation of
# DESIGN_REQUESTS['done']; {1} the annotated noise study, whose first case is that receipt (a stored result) and whose
# second ({3}) is computed; {5} a grid study; {12} a cross-head study; {17} a study whose worker fails; {22} a study
# whose first case holds its worker until it is cancelled ({24}); {23} a draft that is cancelled; {26} and {27} drafts
# sent at the body limit and one byte per chunk; {28} a study whose worker changes the identity. Keys: {k1} the noise
# study's computed case, whose record is removed before the study is read again from its snapshots.
STUDY_STEPS: list[dict] = [
    {'method': 'GET', 'path': _S},
    {'method': 'POST', 'path': '/api/design-evaluation/jobs', 'body': DESIGN_REQUESTS['done']},
    {'method': 'GET', 'path': '/api/design-evaluation/jobs/{0}', 'until': TERMINAL},
    {'method': 'POST', 'path': _S, 'body': study_body('noise_seeds', 'done', [(42, 6), (43, 6)], True,
                                                       title='  Noise study  ', notes='Plain <b>text</b>')},
    {'method': 'GET', 'path': _S},
    {'method': 'GET', 'path': f'{_S}/{{1}}'},
    {'method': 'GET', 'path': f'{_S}/{{1}}/export'},
    _control('{1}', 'start', brief=True),
    _settle('{1}'),
    {'method': 'GET', 'path': f'{_S}/{{1}}/export'},
    {'method': 'GET', 'path': '/api/design-evaluation/jobs/{3}'},
    _control('{1}', 'resume'),
    _control('{1}', 'start'),
    _control('{1}', 'cancel'),
    # Grid displacements (perturbations with four trials each) and one head per case.
    {'method': 'POST', 'path': _S, 'body': study_body('grid_displacements', 'done', [(11, 3), (12, 6), (11, 10)])},
    _control('{5}', 'start', brief=True),
    _settle('{5}'),
    {'method': 'GET', 'path': f'{_S}/{{5}}/export'},
    {'method': 'POST', 'path': _S, 'body': study_body('heads', 'done', [(head, 7, 6) for head in STUDY_HEADS])},
    _control('{12}', 'start', brief=True),
    _settle('{12}'),
    {'method': 'GET', 'path': f'{_S}/{{12}}/export'},
    # Failed children, then a running one: one study at a time, and cancellation stops its worker.
    {'method': 'POST', 'path': _S, 'body': study_body('noise_seeds', 'fail', [(1, 6), (2, 6)])},
    _control('{17}', 'start', brief=True),
    _settle('{17}'),
    {'method': 'POST', 'path': _S, 'body': study_body('noise_seeds', 'hold', [(1, 6), (2, 6)])},
    {'method': 'POST', 'path': _S, 'body': study_body('noise_seeds', 'done', [(5, 6), (6, 6)])},
    _control('{22}', 'start', brief=True),
    {'method': 'GET', 'path': f'{_S}/{{22}}', 'until': ('running',), 'field': 'study.cases.0.status'},
    _control('{23}', 'start'),
    _control('{22}', 'cancel', brief=True),
    _settle('{22}'),
    {'method': 'GET', 'path': '/api/design-evaluation/jobs/{24}'},
    _control('{23}', 'cancel', brief=True),
    _settle('{23}'),
    {'method': 'GET', 'path': f'{_S}/{{23}}/export'},
    _control('{23}', 'resume'),
    _control('{23}', 'start'),
    # The body and path rules.
    {'method': 'POST', 'path': _S, 'raw': padded(study_body('noise_seeds', 'done', [(8, 6)]), 65536)},
    {'method': 'POST', 'path': _S, 'body': study_body('noise_seeds', 'done', [(9, 6)], True), 'chunks': True},
    {'method': 'POST', 'path': _S, 'raw': padded(study_body('noise_seeds', 'done', [(8, 6)]), 65537)},
    {'method': 'POST', 'path': _S, 'body': study_body('noise_seeds', 'done', [(8, 6)], design={**DESIGN, 'unit': 'm'})},
    {'method': 'POST', 'path': _S, 'body': study_body('noise_seeds', 'done', [])},
    {'method': 'POST', 'path': _S, 'body': study_body('noise_seeds', 'done', [(8, 6), (8, 6)])},
    {'method': 'POST', 'path': _S, 'body': study_body('noise_seeds', 'done', [(8, 6), (9, 3)])},
    {'method': 'POST', 'path': _S, 'body': study_body('heads', 'done', [('ixi002', 7, 6), ('ixi002', 7, 6)])},
    {'method': 'POST', 'path': _S, 'body': study_body('heads', 'done', [('missing', 7, 6)])},
    {'method': 'POST', 'path': _S, 'raw': 'null'},
    {'method': 'POST', 'path': _S, 'raw': '{"protocol":'},
    {'method': 'POST', 'path': _S, 'raw': '{}', 'type': 'text/plain'},
    {'method': 'POST', 'path': _S, 'body': study_body('noise_seeds', 'done', [(8, 6)]), 'token': False},
    {'method': 'GET', 'path': _S + '?view=1'},
    {'method': 'GET', 'path': f'{_S}/{{1}}?view=1'},
    {'method': 'POST', 'path': f'{_S}/{{1}}', 'body': {}},
    {'method': 'POST', 'path': f'{_S}/{{1}}/export', 'body': {}},
    {'method': 'GET', 'path': f'{_S}/{{1}}/start'},
    {'method': 'GET', 'path': f'{_S}/{{1}}/'},
    {'method': 'GET', 'path': f'{_S}/{{1}}/other'},
    {'method': 'GET', 'path': f'{_S}/'},
    {'method': 'GET', 'path': f'{_S}/x'},
    {'method': 'GET', 'path': f'{_S}/%7B1%7D'},
    {'method': 'GET', 'path': f'{_S}/00000000-0000-4000-8000-000000000000'},
    {'method': 'GET', 'path': f'{_S}/00000000-0000-4000-8000-000000000000/export'},
    _control('00000000-0000-4000-8000-000000000000', 'cancel'),
    _control('{26}', 'start', body={'extra': True}),
    _control('{26}', 'start', body=[]),
    _control('{26}', 'start', raw=''),
    _control('{26}', 'start', raw='{}', type='text/plain'),
    _control('{26}', 'start', token=False),
    _control('{26}', 'cancel', token=False),
    # A worker that changes the scientific identity: the pending case fails without a receipt.
    {'method': 'POST', 'path': _S, 'body': study_body('noise_seeds', 'change', [(1, 6), (2, 6)])},
    _control('{28}', 'start', brief=True),
    _settle('{28}'),
    # Completed studies keep their results after the code changed and after a record is removed.
    {'method': 'FILE', 'path': DESIGN_JOBS + '/{k1}/cache.json', 'text': None},
    {'method': 'GET', 'path': f'{_S}/{{1}}'},
    {'method': 'GET', 'path': f'{_S}/{{1}}/export'},
    {'method': 'GET', 'path': _S},
]


def study_compute_root(directory: Path) -> Path:
    """``design_compute_root`` with the head packages ``STUDY_HEADS``."""
    return design_compute_root(directory, heads=STUDY_HEADS)


def study_tree(directory: Path) -> dict[str, tuple[Optional[str], int]]:
    """The studies' directory (``W/studies``, Node's ``Q/studies``): ``{relative path: (text or None for a
    directory, mode)}``."""
    if not directory.exists():
        return {}
    return {str(path.relative_to(directory)): (None if path.is_dir() else path.read_text(encoding='utf-8'),
                                                path.stat().st_mode & 0o7777)
            for path in sorted(directory.rglob('*'))}


# Members of a study answer that depend on when the pump ran: the case statuses and the counts (start and cancel
# answer while it works), the number of writes and the last write's time.
_BRIEF = ('cases', 'aggregation', 'revision', 'updated_at', 'status', 'last_error')
_REVISION = re.compile(r'"revision":\d+')
_UUID_TEXT = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def _brief(body: str) -> str:
    try:
        value = jsjson.parse(body)
    except ValueError:
        return body
    if isinstance(value, dict) and isinstance(value.get('study'), dict):
        value = {'study': {name: member for name, member in value['study'].items() if name not in _BRIEF}}
    return jsjson.stringify(value)


def _sorted_directory(body: str) -> str:
    """A directory answer with its rows in id order: both hosts list the study directories in the file system's
    order, which depends on the (masked) identifiers."""
    try:
        value = jsjson.parse(body)
    except ValueError:
        return body
    if isinstance(value, dict) and isinstance(value.get('studies'), list):
        value = {**value, 'studies': sorted(value['studies'], key=lambda row: str(row.get('id')))}
        return jsjson.stringify(value)
    return body


def _study_answers(answers: list[dict], steps: list[dict]) -> list[dict]:
    out = []
    for step, answer in zip(steps, answers):
        body = _brief(answer['body']) if step.get('brief') else answer['body']
        out.append({**answer, 'body': _REVISION.sub('"revision":"<n>"', body)})
    return out


def study_ids(answers: list[dict], steps: list[dict]) -> list[str]:
    """The ids of the answers in the order ``study_masked`` numbers them."""
    ids: list[str] = []
    for answer in _study_answers(answers, steps):
        _ids(answer['body'], ids)
    return ids


def study_digests(records: dict[str, str], tree: dict[str, tuple[Optional[str], int]]) -> dict[str, str]:
    """The name of each ``cache.json`` digest, ``<cache of KEY>``: of the files of ``records`` (a ``design_tree``)
    and of the snapshots of ``tree`` (a ``study_tree``; a snapshot whose record was removed is still named). A
    ``cache.json`` holds its finish time, so its digest differs between hosts while its key does not."""
    names = {}
    for path, text in records.items():
        if path.endswith('/cache.json'):
            names[hashlib.sha256(text.encode('utf-8')).hexdigest()] = f'<cache of {path.split("/")[0]}>'
    for path, (text, _) in tree.items():
        if text is not None and '/snapshots/' in path:
            names[hashlib.sha256(text.encode('utf-8')).hexdigest()] = f'<cache of {jsjson.parse(text)["key"]}>'
    return names


def _named(text: str, digests: dict[str, str]) -> str:
    for digest, name in digests.items():
        text = text.replace(digest, name)
    return text


def study_masked(answers: list[dict], token: str, digests: dict[str, str], steps: list[dict]) -> list[dict]:
    """``masked`` of the answers to ``steps``: a ``brief`` answer without the members that depend on when the pump
    ran, each ``cache.json`` digest named (``study_digests``), ``revision`` masked and a directory's rows in id
    order."""
    assert len(answers) == len(steps)
    named = [{**answer, 'body': _named(answer['body'], digests)} for answer in _study_answers(answers, steps)]
    return [{**answer, 'body': _sorted_directory(answer['body'])} for answer in masked(named, token)]


def study_tree_masked(tree: dict[str, tuple[Optional[str], int]], digests: dict[str, str], ids: list[str]) -> dict:
    """A ``study_tree`` with the study, receipt and operation ids numbered as in the answers (``study_ids``), times
    and revisions masked, each snapshot named by the ``cache.json`` it copies (``study_digests``), and Node's
    ``network`` member (the pinned session's) removed. An id no answer showed fails."""
    for path, (text, _) in tree.items():
        for id in _UUID_TEXT.findall(path + (text or '')):
            assert id in ids, f'{id} of {path} is in no answer'

    def mask(text: str) -> str:
        text = _UUID_TEXT.sub(lambda match: f'<id{ids.index(match.group(0))}>', text)
        text = _REVISION.sub('"revision":"<n>"', _TIME.sub('<time>', _named(text, digests)))
        return text.replace(f',"network":"{STUDY_NETWORK}"', '')

    return {mask(path): (None if text is None else mask(text), mode) for path, (text, mode) in tree.items()}


# --- Research projects ------------------------------------------------------------------------------------------------

_P = '/api/projects'
DATA_MANIFEST = {'schema_version': 'eeglayoutlab-data-bundle/1', 'bundle_id': 'fixture-data'}
RUNTIME_LOCK = {'schema': 'eeglayoutlab-runtime-lock/1'}
# Node's source files a delivery's host names (project-delivery.mjs hostFiles).
NODE_HOST_FILES = ('webapp/package.json', 'webapp/package-lock.json', 'webapp/server/projects/store.mjs',
                   'webapp/server/projects/service.mjs', 'webapp/server/delivery/research-bundle.mjs',
                   'webapp/server/delivery/project-delivery.mjs')


def project_compute_root(directory: Path) -> dict:
    """``reception_compute_root`` plus a stored coordinate evaluation of ``DESIGN_REQUESTS['cached']``, a stored
    electrode edit and the data manifest and runtime lock a delivery reads. Returns ``reception_compute_root``'s
    ``{root, ids, requests, stored}`` with ``design`` and ``edit``, the two stored records' keys."""
    built = reception_compute_root(directory)
    root, ids = Path(built['root']), built['ids']
    design = stored_design(root, DESIGN_REQUESTS['cached'])
    request = editor_requests(ids, parent_digests(str(root), ids, sys.executable, {}))['stored-evaluate']
    edit = stored_edit(str(root), request, evaluate_result(request))
    write(root, 'data/manifest.json', DATA_MANIFEST)
    write(root, 'configs/runtime/manifest.json', RUNTIME_LOCK)
    return {**built, 'design': design, 'edit': edit}


def _entry(revision: int, **members: Any) -> dict:
    return {'revision': revision, **members}


def project_steps(built: dict) -> list[dict]:
    """The research projects on ``project_compute_root``'s root ``built``: a project ({$p}) renamed, its entries (two
    library layouts {$reference} and {$candidate}, a named coordinate evaluation {$named} with the annotation
    {$annotation}, an electrode edit {$edit}, a signal receipt {$receipt} saved as {$signal}), its comparison settings,
    its delivery, its detaches; the refusals of attachments (one whose bundle fails: the generic 500), revisions,
    methods, queries, paths, bodies and the token; the list and sharing (``differs``). Each comment names the revision
    a write leaves."""
    ids, r = built['ids'], built['requests']
    P = _P + '/{$p}'
    href = (f'/decision?a={ids["cache"]}&b={ids["strict"]}&ar=87&thresholdMode=custom&sensitivity=63'
            '&localization=52&p90=28.5')
    workflow = {'reference_entry_id': '{$reference}', 'candidate_entry_id': '{$candidate}', 'comparison_href': href}
    return [
        {'method': 'GET', 'path': _P, 'differs': True},
        {'method': 'POST', 'path': _P, 'capture': {'p': 'project.id'},
         'body': {'title': '  Study A  ', 'owner_name': 'Researcher', 'notes': 'Plain <b>text</b>, 中文'}},  # 1
        {'method': 'GET', 'path': P},
        {'method': 'PATCH', 'path': P, 'body': _entry(1, title='Renamed study')},  # 2
        {'method': 'PATCH', 'path': P, 'body': _entry(1, title='Stale')},
        {'method': 'PATCH', 'path': P, 'body': _entry(2, identity={'fake': True})},
        {'method': 'PATCH', 'path': P, 'body': _entry(2)},
        # Two library layouts, a named coordinate evaluation, an electrode edit and a signal receipt.
        {'method': 'POST', 'path': P + '/entries', 'capture': {'reference': 'entry.id'},
         'body': _entry(2, kind='layout', record_id=ids['cache'], title='Reference')},  # 3
        {'method': 'POST', 'path': P + '/entries', 'capture': {'candidate': 'entry.id'},
         'body': _entry(3, kind='layout', record_id=ids['strict'], notes='Candidate')},  # 4
        {'method': 'POST', 'path': P + '/entries', 'body': _entry(4, kind='layout', record_id=ids['cache'])},
        {'method': 'POST', 'path': '/api/design-evaluation/jobs', 'capture': {'annotation': 'job.annotation_id'},
         'body': envelope(DESIGN_REQUESTS['cached'], 'A', SOURCE)},
        {'method': 'POST', 'path': P + '/entries', 'capture': {'named': 'entry.id'},
         'body': _entry(4, kind='layout', record_id=built['design'], annotation_id='{$annotation}')},  # 5
        {'method': 'POST', 'path': P + '/entries', 'capture': {'edit': 'entry.id'},
         'body': _entry(5, kind='editor', record_id=built['edit'])},  # 6
        {'method': 'POST', 'path': f'{_SR}/lookup', 'body': r['stored'], 'capture': {'receipt': 'job.id'}},
        {'method': 'POST', 'path': P + '/entries', 'capture': {'signal': 'entry.id'},
         'body': _entry(6, kind='source', receipt_id='{$receipt}', title='Signal case')},  # 7
        {'method': 'GET', 'path': P + '/entries/{$reference}'},
        {'method': 'GET', 'path': P + '/entries/{$named}'},
        {'method': 'GET', 'path': P + '/entries/{$edit}'},
        {'method': 'GET', 'path': P + '/entries/{$signal}'},
        {'method': 'PATCH', 'path': P + '/entries/{$signal}',
         'body': _entry(7, title='Renamed case', notes='Original values retained')},  # 8
        {'method': 'PATCH', 'path': P + '/entries/{$signal}', 'body': _entry(8)},
        {'method': 'PATCH', 'path': P, 'body': _entry(8, workflow=workflow)},  # 9
        {'method': 'PATCH', 'path': P, 'body': _entry(9, workflow={**workflow, 'comparison_href': 'https://x.test/'})},
        {'method': 'GET', 'path': P},
        {'method': 'GET', 'path': P + '/export'},
        # Attachments refused: no such layout, edit or receipt, client data, a stale revision, another record's names,
        # a receipt that has not completed.
        {'method': 'POST', 'path': P + '/entries', 'body': _entry(9, kind='layout', record_id='d' * 64)},
        {'method': 'POST', 'path': P + '/entries', 'body': _entry(9, kind='editor', record_id='d' * 64)},
        {'method': 'POST', 'path': P + '/entries', 'body': _entry(9, kind='source', receipt_id=_UNKNOWN)},
        {'method': 'POST', 'path': P + '/entries', 'body': _entry(9, kind='source', receipt_id='{$receipt}',
                                                                   payload={'schema_version': 'source-reception/2'})},
        {'method': 'POST', 'path': P + '/entries', 'body': _entry(8, kind='layout', record_id=ids['strict-2'])},
        {'method': 'POST', 'path': P + '/entries',
         'body': _entry(9, kind='layout', record_id=ids['cache'], annotation_id='{$annotation}')},
        # A layout whose source cannot be read (the offline radius report the root's pointer names is missing).
        {'method': 'POST', 'path': P + '/entries', 'body': _entry(9, kind='layout', record_id=ids['offline'])},
        {'method': 'POST', 'path': f'{_SR}/jobs', 'body': r['hold'], 'capture': {'held': 'job.id'}},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{$held}}', 'until': ('running',), 'progress': True},
        {'method': 'POST', 'path': P + '/entries', 'body': _entry(9, kind='source', receipt_id='{$held}')},
        {'method': 'POST', 'path': f'{_SR}/jobs/{{$held}}/cancel'},
        {'method': 'GET', 'path': f'{_SR}/jobs/{{$held}}', 'until': TERMINAL},
        # Detaches: by If-Match and by body, a stale revision, an entry already removed.
        {'method': 'DELETE', 'path': P + '/entries/{$candidate}', 'headers': {'If-Match': '"8"'}},
        {'method': 'DELETE', 'path': P + '/entries/{$candidate}', 'headers': {'If-Match': '"9"'}},  # 10
        {'method': 'DELETE', 'path': P + '/entries/{$edit}', 'body': _entry(10)},  # 11
        {'method': 'DELETE', 'path': P + '/entries/{$edit}', 'body': _entry(11)},
        {'method': 'GET', 'path': P + '/entries/{$edit}'},
        {'method': 'GET', 'path': P + '/export'},
        # A second project, and the list; sharing (Node: a stale revision, so its record stays as Python's).
        {'method': 'POST', 'path': _P, 'body': {'title': 'Study B', 'owner_name': '研究者'}},  # 1
        {'method': 'GET', 'path': _P, 'differs': True},
        {'method': 'POST', 'path': P + '/share', 'body': _entry(1), 'differs': True},
        {'method': 'POST', 'path': P + '/revoke-share', 'body': _entry(1), 'differs': True},
        # Methods, queries, paths, bodies and the token.
        {'method': 'PUT', 'path': P, 'body': {}},
        {'method': 'HEAD', 'path': P},
        {'method': 'GET', 'path': P + '?key=x'},
        {'method': 'PATCH', 'path': P + '?x', 'body': _entry(11, title='Query')},
        {'method': 'GET', 'path': f'{_P}/{_UNKNOWN}'},
        {'method': 'GET', 'path': f'{_P}/not-a-project'},
        {'method': 'GET', 'path': f'{_P}/'},
        {'method': 'GET', 'path': P + '/other'},
        {'method': 'GET', 'path': P + '/entries'},
        {'method': 'GET', 'path': P + '/entries/not-an-entry'},
        {'method': 'POST', 'path': P + '/export', 'body': {}},
        {'method': 'POST', 'path': P, 'body': {}},
        {'method': 'PATCH', 'path': f'{P}/entries/{_UNKNOWN}', 'body': _entry(11, title='Nobody')},
        {'method': 'POST', 'path': _P, 'raw': '{"title":'},
        {'method': 'POST', 'path': _P, 'raw': '[]'},
        {'method': 'POST', 'path': _P, 'raw': '{}', 'type': 'text/plain'},
        {'method': 'POST', 'path': _P, 'raw': padded({'title': 'Too large', 'owner_name': 'R'}, 65537)},
        {'method': 'POST', 'path': _P, 'raw': padded({'title': 'At the limit', 'owner_name': 'R'}, 65536)},  # 1
        {'method': 'POST', 'path': _P, 'body': {'title': 'Chunked 研究', 'owner_name': 'R'}, 'chunks': True},  # 1
        {'method': 'POST', 'path': _P, 'body': {'title': '', 'owner_name': 'R'}},
        {'method': 'POST', 'path': _P, 'body': {'title': 'No token', 'owner_name': 'R'}, 'token': False},
        {'method': 'PATCH', 'path': P, 'body': _entry(11, title='No token'), 'token': False},
        {'method': 'DELETE', 'path': P + '/entries/{$reference}', 'body': _entry(11), 'token': False},
        {'method': 'GET', 'path': P},
    ]


def project_differences(steps: list[dict], node: list[dict], python: list[dict]) -> None:
    """The deliberate differences of the ``differs`` steps: Node's ``GET /api/projects`` is 405 and the service lists
    the workspace's projects; Node's ``share`` and ``revoke-share`` refuse a stale revision (409) and are not the
    service's endpoints (404)."""
    for step, theirs, ours in zip(steps, node, python):
        if not step.get('differs'):
            continue
        if step['path'] == _P:
            assert (theirs['status'], jsjson.parse(theirs['body'])['error']) == (
                405, 'Projects are opened with their identifier and credential.'), theirs
            listed = jsjson.parse(ours['body'])
            assert ours['status'] == 200 and list(listed) == ['projects'], ours
        else:
            assert (theirs['status'], jsjson.parse(theirs['body'])['error']) == (
                409, 'Project changed. Reload it before saving.'), theirs
            assert (ours['status'], jsjson.parse(ours['body'])) == (
                404, {'error': 'Project endpoint not found.', 'code': 'not_found'}), ours


_ACCESS_KEY = re.compile(r'"access_key":"[a-f0-9]{64}"')


def _delivery(body: str, files: tuple[str, ...]) -> str:
    """A delivery answer with its host's ``source_files``, its ``manifest_sha256`` and the digest of its README (which
    names the project's id) masked, once they are checked: the files are ``files`` (Node's or the Python service's),
    the manifest is the delivery's own and each file's digest is its content's."""
    from eeglayoutlab.server.delivery import validate_research_delivery

    try:
        value = jsjson.parse(body)
    except ValueError:
        return body
    if not (isinstance(value, dict) and value.get('schema') == 'eeg-research-delivery/1'):
        return body
    assert validate_research_delivery(value) is True
    assert tuple(row['path'] for row in value['host']['source_files']) == files
    for file in value['files']:
        assert file['sha256'] == hashlib.sha256(file['content'].encode('utf-8')).hexdigest()
    assert value['files'][0]['path'] == 'README.md'
    value['files'][0]['sha256'] = '<readme>'
    value['host']['source_files'] = '<source files>'
    value['manifest_sha256'] = '<manifest>'
    return jsjson.stringify(value)


def project_masked(answers: list[dict], token: str, steps: list[dict], node: bool) -> list[dict]:
    """``masked`` of the answers to the steps that are not ``differs``, each create's ``access_key`` and each
    delivery's ``source_files`` (Node's or ``delivery.HOST_FILES``), ``manifest_sha256`` and README digest masked;
    the project id of a ``Content-Disposition`` is numbered as in the bodies."""
    from eeglayoutlab.server.delivery import HOST_FILES

    files = NODE_HOST_FILES if node else HOST_FILES
    kept = [{**answer, 'body': _delivery(_ACCESS_KEY.sub('"access_key":"<key>"', answer['body']), files)}
            for step, answer in zip(steps, answers) if not step.get('differs')]
    ids: list[str] = []
    for answer in kept:
        _ids(answer['body'], ids)
    return [{**answer, 'disposition': answer['disposition'] and _ID.sub(
                lambda match: f'<id{ids.index(match.group(0))}>', answer['disposition'])}
            for answer in masked(kept, token)]


_KEY_HASH = re.compile(r'"owner_key_hash":"[a-f0-9]{64}"')


def project_tree_masked(tree: dict[str, tuple[Optional[str], int]], ids: list[str]) -> dict:
    """A projects directory (``study_tree``) with ids numbered as in the answers (an id no answer showed fails),
    times masked, the ``owner_key_hash`` masked and Node's ``creator_network`` (the pinned session's) removed."""
    for path, (text, _) in tree.items():
        for id in _UUID_TEXT.findall(path + (text or '')):
            assert id in ids, f'{id} of {path} is in no answer'

    def mask(text: str) -> str:
        text = _UUID_TEXT.sub(lambda match: f'<id{ids.index(match.group(0))}>', text)
        text = _KEY_HASH.sub('"owner_key_hash":"<hash>"', _TIME.sub('<time>', text))
        return text.replace(f',"creator_network":"{STUDY_NETWORK}"', '')

    return {mask(path): (None if text is None else mask(text), mode) for path, (text, mode) in tree.items()}


def project_ids(answers: list[dict], steps: list[dict]) -> list[str]:
    """The ids of the compared answers in the order ``masked`` numbers them."""
    ids: list[str] = []
    for step, answer in zip(steps, answers):
        if not step.get('differs'):
            _ids(answer['body'], ids)
    return ids
