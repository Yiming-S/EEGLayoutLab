"""The robustness-study routes (``eeglayoutlab.server.routes.studies``, phase 2 slice 8) end to end: the application
with its lifespan and the study service of ``routes.compute.ComputeHost`` over the workspace queue, on the synthetic
design roots of tests/service/compute_support.py (their design worker is a stand-in), over HTTP.

- A study is a draft until it is started (nothing is queued or written under R); its cases then run one at a time as
  coordinate evaluations of the workspace queue, and its export holds each completed case's original ``cache.json``
  text, also once the record is removed. Its records are in ``W/studies``, never in ``R/results/web-service``.
- Node's middleware before the other API routes: queries, methods, paths, bodies and operations answer with Node's
  statuses, messages, codes and headers; a resource refusal carries ``Retry-After``, any other failure is not
  described; until the lifespan has started, every study path is 404 ``Study not found.``.
- The route half of check-robustness-studies.mjs "HTTP study writes require origin/token and reads isolate signed
  browser sessions": a write needs the CSRF token, every request a loopback origin and the session (Python's 401);
  signed browser sessions are dropped (R1).
- Restart: a running study is paused (``paused_recovery``) and its interrupted receipt failed; reads submit nothing;
  an explicit resume looks for the interrupted case's cache (as Node, a missing one fails the case) and runs the
  next case.
- ``--cache-only``: a study whose cases are stored completes from them; a case that would compute is deferred
  (``paused_resource``) and reads do not retry it.
- Shutdown in Node's dispose order: the studies stop before the queue's scheduling and the job services, a study
  write or pump in progress is awaited before the queue is written a last time (after ``stop_soon`` too), and later
  writes are refused.
- Parity: ``STUDY_STEPS`` against Node's composed service (``createLocalComputeService``) and the Python application
  on the same root give the same statuses, content types and bodies (ids, times, revisions, cache digests and the
  token masked; the members of start and cancel answers that race with the pump dropped), the same design records
  and the same study trees (Node's ``Q/studies``, ours ``W/studies``).
- check-robustness-browser.mjs's inputs: ``tests/service/fixtures/robustness`` holds the stage-5 study inputs (two
  noise seeds and six grid displacements of one design) and ``case-requests.json``, the canonical request of each
  case, which the script proves cached instead of importing Node's ``normalizeDesignRequest``. The file must be what
  ``robustness_requests()`` writes (``PYTHONPATH=src:tests python -m tests.service.test_study_routes`` writes it
  again), the study protocol must give the same requests, and Node's ``normalizeDesignRequest`` the same text.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Iterator

import pytest

from .key_parity_support import NODE_ENV, needs_node, require

require('fastapi')
require('httpx')
require('pydantic')

from eeglayoutlab.jobs.annotations import LOCAL_OWNER  # noqa: E402
from eeglayoutlab.jobs.queue import INTERRUPTED_MESSAGE  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402
from eeglayoutlab.server.app import ERROR_CODES, Service  # noqa: E402

from .compute_support import (  # noqa: E402
    DESIGN_JOBS, SETTLE, STUDY_DONE, STUDY_NETWORK, STUDY_STEPS, design_compute_root, design_tree, json_body,
    masked_tree, padded, post, queue_file, run_node, run_python, serving, study_body, study_compute_root,
    study_digests, study_ids, study_masked, study_tree, study_tree_masked, wait_for,
)
from .service_support import TOKENS  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/service/fixtures/robustness'
PROTOCOLS = ('noise_seeds', 'grid_displacements')
S = '/api/robustness-studies'
POLL = 0.05  # the study poll interval of these tests (Node's is 500 ms)
API_HEADERS = {'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store',
               'x-content-type-options': 'nosniff', 'cross-origin-resource-policy': 'same-origin',
               'x-eeg-api-version': '1'}
UNAVAILABLE = 'Study storage or scientific input is unavailable.'
CACHE_INVALID = 'Completed case failed scientific cache integrity checks.'
# A read whose lstat meets study.json while a write renames the next revision over it sees the replaced file's link
# count 0 (APFS does this) and is refused, in Node as here (ProjectStore's file check); polls read again.
RACED = 'Project file failed integrity checks.'
DEFERRED = 'The original queue deferred this case. Resume explicitly when resources are available.'


@pytest.fixture
def site(tmp_path):
    """A fresh design root and workspace."""
    root = design_compute_root(tmp_path / 'root')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    return root, workspace


@contextlib.contextmanager
def studies(root: Path, workspace: Path, **options: Any) -> Iterator[tuple[Service, Any]]:
    """``serving`` with the study poll at ``POLL``."""
    with serving(root, workspace, lifespan=False, **options) as (app, client):
        app.compute.study_options['poll_seconds'] = POLL
        with client:
            yield app, client


def create(client: Any, body: Any) -> dict:
    response = post(client, S, body)
    assert response.status_code == 201, response.text
    return json_body(response)['study']


def control(client: Any, id: str, action: str) -> dict:
    response = post(client, f'{S}/{id}/{action}', {})
    assert response.status_code == 200, response.text
    return json_body(response)['study']


def study(client: Any, id: str) -> dict:
    response = client.get(f'{S}/{id}')
    assert response.status_code == 200, response.text
    return json_body(response)['study']


def until(client: Any, id: str, check: Any) -> dict:
    """The study once ``check(study)`` holds."""
    deadline = time.monotonic() + SETTLE
    while True:
        response = client.get(f'{S}/{id}')
        if not (response.status_code == 409 and json_body(response)['error'] == RACED):
            assert response.status_code == 200, response.text
            value = json_body(response)['study']
            if check(value):
                return value
        if time.monotonic() > deadline:
            raise AssertionError(f'the study did not settle: {response.text}')
        time.sleep(0.02)


def settle(client: Any, id: str) -> dict:
    return until(client, id, lambda value: value['status'] in STUDY_DONE)


def refusal(response: Any, status: int, message: str) -> None:
    assert response.status_code == status, response.text
    assert json_body(response) == {'error': message, 'code': ERROR_CODES[status]}
    assert {name: response.headers.get(name) for name in API_HEADERS} == API_HEADERS


def tasks(workspace: Path) -> list[dict]:
    return queue_file(workspace)['tasks']


# --- Draft, start, cases, export -------------------------------------------------------------------------------------

def test_a_study_is_a_draft_until_started_and_its_cases_run_as_coordinate_evaluations(site):
    root, workspace = site
    records = design_tree(root)
    with studies(root, workspace) as (app, client):
        listed = client.get(S)
        assert listed.status_code == 200 and json_body(listed) == {'studies': []}
        assert {name: listed.headers.get(name) for name in API_HEADERS} == API_HEADERS
        draft = create(client, study_body('noise_seeds', 'done', [(42, 6), (43, 6)], True, title='  Noise  '))
        id = draft['id']
        assert (draft['status'], draft['title']) == ('draft', 'Noise')
        assert [(case['status'], case['receipt_id']) for case in draft['cases']] == [('pending', None)] * 2
        assert design_tree(root) == records and tasks(workspace) == []
        assert study(client, id) == draft

        started = control(client, id, 'start')
        assert started['status'] == 'running'
        done = settle(client, id)
        assert done['status'] == 'completed' and done['aggregation']['completed_cases'] == 2
        for case in done['cases']:
            target = f'/api/design-evaluation/jobs/{case["receipt_id"]}?annotation_id={case["annotation_id"]}'
            job = json_body(client.get(target))['job']
            assert (job['status'], job['key'], job['annotation_id']) == ('completed', case['key'],
                                                                         case['annotation_id'])
        assert [task['kind'] for task in tasks(workspace)] == ['design-evaluation'] * 2

        exported = client.get(f'{S}/{id}/export')
        assert exported.status_code == 200
        assert {name: exported.headers.get(name) for name in API_HEADERS} == API_HEADERS
        value = json_body(exported)
        assert value['schema'] == 'eeg-robustness-study-export/1' and value['study']['id'] == id
        for entry, case in zip(value['cases'], done['cases']):
            text = (root / DESIGN_JOBS / case['key'] / 'cache.json').read_text(encoding='utf-8')
            digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
            assert (entry['cache_json'], entry['source_sha256'], entry['cache']) == (text, digest, jsjson.parse(text))
            snapshot = workspace / 'studies' / id / 'snapshots' / f'{digest}.json'
            assert snapshot.read_text(encoding='utf-8') == text

        # The study keeps its results when the records are removed.
        for case in done['cases']:
            (root / DESIGN_JOBS / case['key'] / 'cache.json').unlink()
        assert client.get(f'{S}/{id}/export').text == exported.text
        [row] = json_body(client.get(S))['studies']
        assert (row['id'], row['status'], row['case_count'], row['completed_cases']) == (id, 'completed', 2, 2)
    assert sorted(path.name for path in (workspace / 'studies' / id).iterdir()) == ['snapshots', 'study.json']
    assert not (root / 'results/web-service').exists()


# --- The middleware --------------------------------------------------------------------------------------------------

def test_the_study_paths_keep_nodes_order_statuses_messages_and_headers(site):
    root, workspace = site
    with studies(root, workspace) as (app, client):
        id = create(client, study_body('noise_seeds', 'done', [(42, 6)]))['id']
        base = f'{S}/{id}'
        json_type = {'content-type': 'application/json'}
        for method, path, content, status, message in [
            ('GET', S + '?view=1', None, 400, 'Study API queries are not supported.'),
            ('POST', base + '/start?x', b'{}', 400, 'Study API queries are not supported.'),
            ('PUT', S, b'{}', 405, 'Unsupported study method.'),
            ('PATCH', base, b'{}', 405, 'Unsupported study method.'),
            ('DELETE', base, None, 405, 'Unsupported study method.'),
            ('GET', f'{S}/', None, 404, 'Study not found.'),
            ('GET', base.upper().replace('/API/ROBUSTNESS-STUDIES', S), None, 404, 'Study not found.'),
            ('GET', base + '/', None, 404, 'Study not found.'),
            ('GET', base + '/other', None, 404, 'Study not found.'),
            ('POST', f'{S}/00000000-0000-4000-8000-000000000000/cancel', b'{}', 404, 'Study not found.'),
            ('GET', base + '/start', None, 405, 'Unsupported study operation.'),
            ('POST', base + '/export', b'{}', 405, 'Unsupported study operation.'),
            ('POST', base, b'{}', 405, 'Unsupported study operation.'),
            ('POST', base + '/start', b'[]', 400, 'Study control requests require an empty JSON object.'),
            ('POST', base + '/start', b'{"a":1}', 400, 'Study control requests require an empty JSON object.'),
            ('POST', S, b'{"protocol":', 400, 'Invalid study JSON.'),
            ('POST', S, padded({}, 65537).encode('utf-8'), 413, 'Study request is too large.'),
        ]:
            response = client.request(method, path, content=content, headers=json_type)
            refusal(response, status, message)
        refusal(client.post(S, content=b'{}', headers={'content-type': 'text/plain'}), 415, 'JSON is required.')
        # A body at the limit is read; the study format then refuses it.
        response = client.post(S, content=padded({}, 65536).encode('utf-8'), headers=json_type)
        assert response.status_code == 400 and json_body(response)['code'] == 'invalid_request'
        assert study(client, id)['status'] == 'draft' and tasks(workspace) == []

        # A resource refusal names its wait; any other failure is not described.
        store = app.compute.studies.store
        from eeglayoutlab.server.workspace_studies import ResourceError

        def busy() -> None:
            raise ResourceError('Study storage capacity reached.', 503, retry_after=30)
        store.before_write = busy
        response = post(client, S, study_body('noise_seeds', 'done', [(43, 6)]))
        refusal(response, 503, 'Study storage capacity reached.')
        assert response.headers['retry-after'] == '30'

        def broken() -> None:
            raise RuntimeError(f'{root}/private detail')
        store.before_write = broken
        response = post(client, S, study_body('noise_seeds', 'done', [(43, 6)]))
        refusal(response, 500, UNAVAILABLE)
        assert 'retry-after' not in response.headers
        assert [row['id'] for row in json_body(client.get(S))['studies']] == [id]


def test_until_the_lifespan_has_started_every_study_path_is_not_found(site):
    root, workspace = site
    with serving(root, workspace, lifespan=False) as (app, client):
        assert app.compute.studies is None
        refusal(client.get(S), 404, 'Study not found.')
        refusal(post(client, S, study_body('noise_seeds', 'done', [(42, 6)])), 404, 'Study not found.')
        refusal(client.get(f'{S}/00000000-0000-4000-8000-000000000000/export'), 404, 'Study not found.')
    assert not (workspace / 'studies').exists()


def test_study_writes_need_the_token_every_request_a_loopback_origin_and_the_session(site):
    """The route half of "HTTP study writes require origin/token and reads isolate signed browser sessions": the
    origin and the token are checked before the study middleware (``server.access``); the per-browser sessions are
    dropped (R1), the one local session is the service's cookie."""
    root, workspace = site
    body = study_body('noise_seeds', 'done', [(42, 6)])
    with studies(root, workspace) as (app, client):
        refusal(post(client, S, body, **{'x-eeg-compute-token': '0' * 64}), 403,
                'Refresh the page before changing a study.')
        refusal(post(client, S, body, origin='http://evil.example'), 403, 'Request rejected by access policy.')
        refusal(client.get(S, headers={'origin': 'http://evil.example'}), 403, 'Request rejected by access policy.')
        assert not (workspace / 'studies').exists()
        id = create(client, body)['id']
        refusal(post(client, f'{S}/{id}/start', {}, **{'x-eeg-compute-token': '0' * 64}), 403,
                'Refresh the page before changing a study.')
        refusal(post(client, f'{S}/{id}/cancel', {}, origin='http://evil.example'), 403,
                'Request rejected by access policy.')
        client.cookies.clear()
        response = client.get(f'{S}/{id}')
        assert response.status_code == 401 and json_body(response)['code'] == 'authentication_required'
        assert client.get(f'/open?token={TOKENS.launch}').status_code == 303
        assert study(client, id)['status'] == 'draft' and tasks(workspace) == []


# --- Restart, cache-only, shutdown -----------------------------------------------------------------------------------

def test_a_restart_pauses_a_running_study_and_only_an_explicit_resume_runs_it_on(site):
    root, workspace = site
    with studies(root, workspace) as (app, client):
        id = create(client, study_body('noise_seeds', 'hold', [(1, 6), (2, 6)]))['id']
        control(client, id, 'start')
        running = until(client, id, lambda value: value['cases'][0]['status'] == 'running')
        receipt = running['cases'][0]['receipt_id']
    stored = jsjson.parse((workspace / 'studies' / id / 'study.json').read_text(encoding='utf-8'))
    assert stored['status'] == 'running'

    with studies(root, workspace) as (app, client):
        paused = study(client, id)
        assert paused['status'] == 'paused_recovery' and paused['cases'][0]['receipt_id'] == receipt
        job = json_body(client.get(f'/api/design-evaluation/jobs/{receipt}'))['job']
        assert (job['status'], job['message']) == ('failed', INTERRUPTED_MESSAGE)
        count = len(tasks(workspace))
        time.sleep(10 * POLL)  # reads and the poll never submit a paused study's cases
        assert study(client, id)['status'] == 'paused_recovery' and len(tasks(workspace)) == count
        assert [row['status'] for row in json_body(client.get(S))['studies']] == ['paused_recovery']

        assert control(client, id, 'resume')['status'] == 'running'
        resumed = until(client, id, lambda value: value['cases'][1]['status'] == 'running')
        # The worker may have stored its cache before the receipt's final state reached disk; this one did not.
        assert resumed['cases'][0]['status'] == 'failed'
        assert resumed['cases'][0]['error'] == {'code': 'scientific_cache_invalid', 'message': CACHE_INVALID}
        assert len(tasks(workspace)) == count + 1
        control(client, id, 'cancel')
        cancelled = settle(client, id)
        assert cancelled['status'] == 'cancelled'
        assert [case['status'] for case in cancelled['cases']] == ['failed', 'cancelled']


def test_a_cache_only_service_completes_studies_from_stored_results_and_defers_new_cases(site):
    root, workspace = site
    with studies(root, workspace) as (app, client):
        first = create(client, study_body('noise_seeds', 'done', [(42, 6), (43, 6)]))['id']
        control(client, first, 'start')
        assert settle(client, first)['status'] == 'completed'

    with studies(root, workspace, cache_only=True) as (app, client):
        health = json_body(client.get('/api/local-compute/health'))
        assert (health['maintenance'], health['drained']) == (True, True)
        cached = create(client, study_body('noise_seeds', 'done', [(42, 6), (43, 6)], title='Cached'))['id']
        control(client, cached, 'start')
        done = settle(client, cached)
        assert done['status'] == 'completed'
        for case in done['cases']:
            assert json_body(client.get(f'/api/design-evaluation/jobs/{case["receipt_id"]}'))['job']['cached']

        mixed = create(client, study_body('noise_seeds', 'done', [(42, 6), (44, 6)], title='Mixed'))['id']
        control(client, mixed, 'start')
        deferred = until(client, mixed, lambda value: value['status'] == 'paused_resource')
        assert [case['status'] for case in deferred['cases']] == ['completed', 'pending']
        assert deferred['last_error'] == deferred['cases'][1]['error'] == {'code': 'submission_deferred',
                                                                            'message': DEFERRED}
        time.sleep(10 * POLL)
        assert study(client, mixed) == deferred
        assert not any(task['status'] in ('queued', 'running') for task in tasks(workspace))
        control(client, mixed, 'cancel')
        assert [case['status'] for case in settle(client, mixed)['cases']] == ['completed', 'cancelled']


def recorder(calls: list[str], name: str, method: Any) -> Any:
    if asyncio.iscoroutinefunction(method):
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return await method(*args, **kwargs)
    else:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return method(*args, **kwargs)
    return wrapped


def record_dispose(monkeypatch: Any, app: Service) -> list[str]:
    host, calls = app.compute, []
    for name, owner in (('studies', host.studies), ('queue', host.queue), ('design', host.design)):
        for method in ('stop', 'aclose', 'stop_scheduling', 'dispose', 'close'):
            if hasattr(owner, method) and not (owner is host.studies and method in ('dispose', 'close')):
                monkeypatch.setattr(owner, method, recorder(calls, f'{name}.{method}', getattr(owner, method)))
    return calls


def hold(host: Any, calls: list[str], busy: str) -> Any:
    """Holds a study write (an admission that takes a while, as Node's resource gate may) or a study's pump until the
    shutdown awaits the studies (``studies.aclose``), then records ``study <busy> done``; bounded, so a shutdown that
    never awaits them fails it. Returns the write's future (``None`` for the pump)."""
    service, entered, written = host.studies, threading.Event(), None

    async def held(*args: Any) -> None:
        entered.set()
        await asyncio.to_thread(wait_for, lambda: 'studies.aclose' in calls)
        calls.append(f'study {busy} done')
    if busy == 'write':
        service.store.before_write = held
        written = asyncio.run_coroutine_threadsafe(
            service.create(study_body('noise_seeds', 'done', [(42, 6)])), host._loop)
    else:
        service.pump = held
        host._loop.call_soon_threadsafe(service.run, '5d5d0000-0000-4000-8000-000000000001')
    assert entered.wait(SETTLE)
    return written


def test_shutdown_stops_the_studies_first_and_awaits_their_writes_before_the_queues_last_write(site, monkeypatch):
    """Node's dispose: ``studies.stop()`` before the scheduler and the job services; ``studies.flush()`` (a study write
    in progress) and ``close()`` before the scheduler's last write; later study writes are refused."""
    from eeglayoutlab.server.workspace_studies import ResourceError

    root, workspace = site
    with studies(root, workspace) as (app, client):
        host, service = app.compute, app.compute.studies
        assert service.store.before_write == host._admit and service.store.directory == host.study_directory
        calls = record_dispose(monkeypatch, app)
        written = hold(host, calls, 'write')
    assert written.result(0)['study']['status'] == 'draft'
    assert calls[:3] == ['studies.stop', 'queue.stop_scheduling', 'design.dispose']
    assert calls.index('studies.aclose') < calls.index('study write done') < calls.index('design.aclose')
    assert calls.index('design.aclose') < calls.index('queue.close') < calls.index('queue.dispose')
    assert service.store.closed and service.closed
    with pytest.raises(ResourceError, match=r'^The service is stopping\.$'):
        host._admit()
    [id] = [path.name for path in (workspace / 'studies').iterdir()]
    assert jsjson.parse((workspace / 'studies' / id / 'study.json').read_text(encoding='utf-8'))['status'] == 'draft'


def test_stop_soon_stops_the_studies_before_the_queue_and_reads_still_answer(site, monkeypatch):
    root, workspace = site
    with studies(root, workspace) as (app, client):
        id = create(client, study_body('noise_seeds', 'done', [(42, 6)]))['id']
        calls = record_dispose(monkeypatch, app)
        app.compute.stop_soon()
        wait_for(lambda: 'queue.dispose' in calls)  # nothing of the studies in progress: written at once
        assert calls[:4] == ['studies.stop', 'queue.stop_scheduling', 'design.dispose', 'queue.dispose']
        refusal(post(client, S, study_body('noise_seeds', 'done', [(43, 6)])), 503, 'Study service is stopping.')
        assert study(client, id)['status'] == 'draft'
        assert [row['id'] for row in json_body(client.get(S))['studies']] == [id]
    assert tasks(workspace) == []


@pytest.mark.parametrize('busy', ['write', 'pump'])
def test_stop_soon_leaves_the_queues_last_write_until_the_studies_are_done(site, monkeypatch, busy):
    """Node's dispose defers ``scheduler.dispose()`` while a study is written or pumped: after ``serve``'s signal
    (``stop_soon``) the queue is written by ``close``, once the studies are done."""
    root, workspace = site
    with studies(root, workspace) as (app, client):
        host = app.compute
        calls = record_dispose(monkeypatch, app)
        written = hold(host, calls, busy)
        host.stop_soon()
        wait_for(lambda: 'design.dispose' in calls)
    assert written is None or written.result(0)['study']['status'] == 'draft'
    assert calls[:3] == ['studies.stop', 'queue.stop_scheduling', 'design.dispose']
    assert calls.index(f'study {busy} done') < calls.index('queue.dispose')
    assert calls.count('queue.dispose') == 1


# --- Parity ----------------------------------------------------------------------------------------------------------

@needs_node
def test_the_study_routes_answer_and_write_as_node_does(tmp_path):
    """compute_support.STUDY_STEPS against Node's composed service and the Python application on the same root (a
    design root with two head packages, built again at the same path for Python), with the same stand-in worker:
    the answers, the design records and the study trees. Node's session is the local owner on a network whose name
    is a SHA-256, as its study records require."""
    directory = tmp_path / 'design'
    root = study_compute_root(directory)
    scratch = tmp_path / 'node'
    scratch.mkdir()
    theirs = run_node(root, scratch, STUDY_STEPS, owner=LOCAL_OWNER, network=STUDY_NETWORK)
    node_tree = design_tree(root)
    node_studies = study_tree(scratch / 'queue' / 'studies')
    directory.rename(tmp_path / 'design.node')
    root = study_compute_root(directory)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    ours = run_python(root, workspace, STUDY_STEPS)
    node_digests = study_digests(node_tree, node_studies)
    our_digests = study_digests(ours['design_tree'], ours['studies'])
    expected = study_masked(theirs['answers'], theirs['token'], node_digests, STUDY_STEPS)
    actual = study_masked(ours['answers'], ours['token'], our_digests, STUDY_STEPS)
    for step, (node, python) in enumerate(zip(expected, actual)):
        assert python == node, f'step {step}: {python} != {node}'
    assert len(actual) == len(expected) == len(STUDY_STEPS)
    assert masked_tree(ours['design_tree']) == masked_tree(node_tree)
    node_masked = study_tree_masked(node_studies, node_digests, study_ids(theirs['answers'], STUDY_STEPS))
    our_masked = study_tree_masked(ours['studies'], our_digests, study_ids(ours['answers'], STUDY_STEPS))
    assert our_masked == node_masked
    assert sum(path.endswith('/study.json') for path in our_masked) == 9  # the studies the steps create
    assert not (root / 'results/web-service').exists()


# --- check-robustness-browser.mjs's fixture --------------------------------------------------------------------------

def stage5_input(protocol: str) -> dict:
    return jsjson.parse((FIXTURE / f'{protocol}-input.json').read_text(encoding='utf-8'))


def robustness_requests() -> str:
    """``case-requests.json``: for each protocol of the stage-5 inputs, the canonical request of each case,
    ``normalize_design_request({action, design, ...case})`` (Node's ``normalizeDesignRequest``; ``evaluate`` for noise
    seeds, ``perturb`` for grid displacements), as ``JSON.stringify`` text, one per line, in the cases' order."""
    from eeglayoutlab.jobs.design_result import normalize_design_request

    members = []
    for protocol in PROTOCOLS:
        study = stage5_input(protocol)
        action = 'evaluate' if study['protocol'] == 'noise_seeds' else 'perturb'
        requests = [jsjson.stringify(normalize_design_request({'action': action, 'design': study['design'], **case}))
                    for case in study['cases']]
        members.append(f'{jsjson.quote(protocol)}:[\n' + ',\n'.join(requests) + '\n]')
    return '{' + ',\n'.join(members) + '}\n'


def test_the_robustness_fixture_holds_the_canonical_requests_of_its_inputs():
    """The script proves each case cached by these requests, then compares each study case's request with them."""
    from eeglayoutlab.jobs.studies import normalize_study_input

    text = (FIXTURE / 'case-requests.json').read_text(encoding='utf-8')
    assert text == robustness_requests(), 'PYTHONPATH=src:tests python -m tests.service.test_study_routes writes it'
    fixture = jsjson.parse(text)
    noise, grid = (stage5_input(protocol) for protocol in PROTOCOLS)
    assert (noise['protocol'], grid['protocol']) == PROTOCOLS and noise['design'] == grid['design']
    assert [len(fixture[protocol]) for protocol in PROTOCOLS] == [2, 6]
    assert sorted({request['radius_mm'] for request in fixture['grid_displacements']}) == [3, 6, 10]
    for protocol, study in zip(PROTOCOLS, (noise, grid)):
        assert normalize_study_input(study)['requests'] == fixture[protocol]


@needs_node
def test_the_robustness_fixture_is_nodes_canonical_requests(tmp_path):
    out = tmp_path / 'node.json'
    subprocess.run(['node', str(ROOT / 'tests/service/parity/robustness_requests.mjs'), str(out)], check=True, cwd=ROOT,
                   env=NODE_ENV)
    node = jsjson.parse(out.read_text(encoding='utf-8'))
    fixture = jsjson.parse((FIXTURE / 'case-requests.json').read_text(encoding='utf-8'))
    for protocol in PROTOCOLS:
        assert [jsjson.stringify(request) for request in fixture[protocol]] == node[protocol]


if __name__ == '__main__':
    (FIXTURE / 'case-requests.json').write_bytes(robustness_requests().encode('utf-8'))
