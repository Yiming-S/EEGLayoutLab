"""The research-project routes (``eeglayoutlab.server.routes.projects``, phase 2 slice 9) end to end: the application
with its lifespan and the project service of ``routes.compute.ComputeHost`` over the workspace's library, editor
records, queue and annotations, on the synthetic roots of tests/service/compute_support.py (their workers are
stand-ins), over HTTP.

- A project holds every kind of result (library layouts, a named coordinate evaluation, an electrode edit, a signal
  receipt) as snapshots in ``W/projects``, never in ``R/results/web-service``; its export is the delivery of those
  snapshot bytes, an attachment that is never cached. Two name variants of one evaluation keep their names in the
  snapshots and the delivery once the workspace's annotations are gone (the project half of
  check-electrode-annotations.mjs:148).
- The HTTP halves of check-project-api.mjs: :43 (the list, a project read without a key, a query refused), :53 (the
  export's headers and bound, read without the scientific cache), :77 (the token, the origin and the session before
  the bounded JSON and the revisions), :88 and check-project-store.mjs:87 (sharing is not an endpoint), :98 (a saved
  signal copy survives the loss of its record), :110 (a foreign, running or client-supplied signal result is refused
  before any saved result is read) and :119 (a layout snapshot is the reproducibility bundle; a detach by
  ``If-Match`` keeps the snapshot file). Credentials are dropped: ``X-EEG-Project-Key`` is accepted and ignored.
- Shutdown in Node's dispose order (check-product-operations-integration.mjs:113, without the operations log): the
  project store closes right after the studies stop; a project write accepted before is awaited before the studies'
  and the queue's last writes (``close``, and after ``stop_soon``), later writes are 503 ``Project store is
  stopping.`` while reads still answer. Projects survive a restart; until the lifespan has started every project path
  is 404 ``Project endpoint not found.``.
- Parity: ``project_steps`` against Node's composed service (``createLocalComputeService``) and the Python
  application on the same root give the same statuses, content types, ``Content-Disposition`` and bodies (ids,
  times, the token, access keys, the host's source files and the delivery manifest masked), the deliberate
  differences (``project_differences``) apart, the same job records and the same project trees (Node's
  ``Q/projects``, ours ``W/projects``; key hashes masked).
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
from pathlib import Path
import shutil
import threading
from typing import Any, Iterator

import pytest

from .key_parity_support import needs_node, require

require('fastapi')
require('httpx')
require('pydantic')

from eeglayoutlab.jobs.annotations import LOCAL_OWNER  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402
from eeglayoutlab.server.app import ERROR_CODES, Service  # noqa: E402

from .compute_support import (  # noqa: E402
    DESIGN_JOBS, DESIGN_REQUESTS, SETTLE, SOURCE, STUDY_NETWORK, TERMINAL, design_tree, envelope, json_body,
    masked_tree, names, poll, post, project_compute_root, project_differences, project_ids, project_masked,
    project_steps, project_tree_masked, reception_compute_root, reception_tree, run_node, run_python, serving,
    study_tree, wait_for,
)
from .projects_support import NOT_OWNED  # noqa: E402
from .service_support import HOST, PORT, TOKENS, session_cookie  # noqa: E402

P = '/api/projects'
UNKNOWN = '00000000-0000-4000-8000-000000000000'
API_HEADERS = {'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store',
               'x-content-type-options': 'nosniff', 'cross-origin-resource-policy': 'same-origin',
               'x-eeg-api-version': '1'}
ENDPOINT = 'Project endpoint not found.'
STOPPING = 'Project store is stopping.'
CHANGED = 'Project changed. Reload it before saving.'
WRITE_TOKEN = 'Refresh the page before saving the project.'
POLICY = 'Request rejected by access policy.'


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    """One ``project_compute_root`` for the tests that only read its records (each has its own workspace)."""
    return project_compute_root(tmp_path_factory.mktemp('projects') / 'root')


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / 'workspace'
    path.mkdir()
    return path


@contextlib.contextmanager
def projects(root: Any, workspace: Path, **options: Any) -> Iterator[tuple[Service, Any]]:
    """``serving`` with ``options`` as the host's ``project_options`` (before the lifespan starts)."""
    with serving(Path(root), workspace, lifespan=False) as (app, client):
        app.compute.project_options.update(options)
        with client:
            yield app, client


def refusal(response: Any, status: int, message: str) -> None:
    assert response.status_code == status, response.text
    assert json_body(response) == {'error': message, 'code': ERROR_CODES[status]}
    assert {name: response.headers.get(name) for name in API_HEADERS} == API_HEADERS


def answer(response: Any, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    assert {name: response.headers.get(name) for name in API_HEADERS} == API_HEADERS
    return json_body(response)


def create(client: Any, title: str = 'Study', **extra: Any) -> dict:
    created = answer(post(client, P, {'title': title, 'owner_name': 'Researcher', **extra}), 201)
    assert list(created) == ['project', 'role', 'access_key'] and created['role'] == 'owner'
    return created


def attach(client: Any, id: str, revision: int, **input: Any) -> dict:
    return answer(post(client, f'{P}/{id}/entries', {'revision': revision, **input}), 201)


def patch(client: Any, path: str, body: Any, **headers: str) -> Any:
    data = body if isinstance(body, (bytes, str)) else jsjson.stringify(body)
    return client.patch(path, content=data, headers={'content-type': 'application/json', **headers})


def snapshot_file(workspace: Path, id: str, entry: dict) -> bytes:
    return (workspace / 'projects' / id / 'snapshots' / f"{entry['snapshot_sha256']}.json").read_bytes()


# --- Entries and the delivery --------------------------------------------------------------------------------------

def test_a_project_holds_every_kind_of_result_and_exports_their_snapshot_bytes(tmp_path, workspace):
    """Every entry kind through the routes; the delivery holds each snapshot's bytes, is read without the scientific
    records (check-project-api.mjs:53) and survives their loss with every field (:98); a layout's snapshot is its
    reproducibility bundle and a detach by an unquoted ``If-Match`` keeps the snapshot (:119)."""
    from eeglayoutlab.server.delivery import validate_research_delivery

    site = project_compute_root(tmp_path / 'root')
    root, ids = Path(site['root']), site['ids']
    with projects(root, workspace) as (app, client):
        created = create(client, '  Study A  ', notes='Plain <b>text</b>, 中文')
        id = created['project']['id']
        assert (created['project']['title'], created['project']['revision']) == ('Study A', 1)
        refusal(post(client, f'{P}/{id}/entries', {'revision': 1, 'kind': 'layout', 'record_id': 'd' * 64}), 404,
                'Choose a completed layout evaluation.')
        layout = attach(client, id, 1, kind='layout', record_id=ids['cache'], title='Reference')
        assert layout['project']['revision'] == 2 and layout['role'] == 'owner'
        job = json_body(post(client, '/api/design-evaluation/jobs', envelope(DESIGN_REQUESTS['cached'], 'A', SOURCE)))
        named = attach(client, id, 2, kind='layout', record_id=site['design'],
                       annotation_id=job['job']['annotation_id'])
        edit = attach(client, id, 3, kind='editor', record_id=site['edit'])
        receipt = json_body(post(client, '/api/source-reception/lookup', site['requests']['stored']))['job']['id']
        reads: list[str] = []
        adapter = app.compute.queue.adapters['source-reception']
        saved_result = adapter.saved_result

        async def counted(*args: Any) -> Any:
            reads.append('read')
            return await saved_result(*args)
        adapter.saved_result = counted
        signal = attach(client, id, 4, kind='source', receipt_id=receipt, title='Signal case')
        assert reads == ['read']
        entries = [layout['entry'], named['entry'], edit['entry'], signal['entry']]
        assert [entry['kind'] for entry in entries] == ['layout', 'layout', 'editor', 'source']
        assert named['entry']['annotation_id'] == job['job']['annotation_id']
        assert signal['entry']['record_id'] == site['stored']

        saved = []
        for entry in entries:
            read = answer(client.get(f'{P}/{id}/entries/{entry["id"]}'))
            assert read['entry'] == entry
            data = snapshot_file(workspace, id, entry)
            assert hashlib.sha256(data).hexdigest() == entry['snapshot_sha256']
            assert jsjson.parse(data.decode('utf-8')) == read['snapshot']
            saved.append(data)
        bundle = answer(client.get(f'{P}/{id}/entries/{layout["entry"]["id"]}'))['snapshot']['payload']
        assert (bundle['schema'], bundle['record']['id']) == ('eeg-reproducibility-bundle/1', ids['cache'])

        exported = client.get(f'{P}/{id}/export')
        delivery = answer(exported)
        assert exported.headers['content-disposition'] == f'attachment; filename="eeg-research-{id}.json"'
        assert validate_research_delivery(delivery) is True
        assert [file['content'].encode('utf-8') for file in delivery['files'][1:]] == saved
        assert [record['id'] for record in delivery['records']] == [entry['id'] for entry in entries]
        assert reads == ['read'], 'Export accessed the old scientific cache again.'
        assert created['access_key'] not in exported.text

        # The receipt's record and the stored result are gone: the saved copy keeps every field.
        for path in (root / 'results/v2').glob(f'source_reception*_jobs/{site["stored"]}'):
            shutil.rmtree(path)
        kept = answer(client.get(f'{P}/{id}/entries/{signal["entry"]["id"]}'))
        assert jsjson.stringify(kept['snapshot']).encode('utf-8') == saved[3]
        renamed = answer(patch(client, f'{P}/{id}/entries/{signal["entry"]["id"]}',
                               {'revision': 5, 'title': 'Renamed case', 'notes': 'Original values retained'}))
        assert (renamed['entry']['title'], renamed['project']['revision']) == ('Renamed case', 6)
        assert snapshot_file(workspace, id, signal['entry']) == saved[3]
        again = answer(client.get(f'{P}/{id}/export'))
        assert [file['content'] for file in again['files'][1:]] == [file['content'] for file in delivery['files'][1:]]

        removed = client.delete(f'{P}/{id}/entries/{layout["entry"]["id"]}', headers={'if-match': '6'})
        assert answer(removed)['project']['revision'] == 7
        project = answer(client.get(f'{P}/{id}'))['project']
        assert [entry['id'] for entry in project['entries']] == [entry['id'] for entry in entries[1:]]
        assert snapshot_file(workspace, id, layout['entry']) == saved[0]
    assert sorted(path.name for path in workspace.iterdir()) == ['.eeglayoutlab', 'annotations', 'projects']
    assert not (root / 'results/web-service').exists()


def test_each_name_variant_survives_the_loss_of_its_annotation_in_snapshots_and_the_delivery(tmp_path, workspace):
    """The project half of check-electrode-annotations.mjs:148: two name variants of one coordinate evaluation saved
    in a project keep their names once the workspace's annotations are gone, over HTTP, in the snapshots a restarted
    store reads and in the delivery; no snapshot names an owner, and the stored result is unchanged."""
    from eeglayoutlab.server.delivery import build_research_delivery, validate_research_delivery
    from eeglayoutlab.server.workspace_projects import ProjectStore

    site = project_compute_root(tmp_path / 'root')
    cache = Path(site['root']) / DESIGN_JOBS / site['design'] / 'cache.json'
    before = cache.read_bytes()
    with projects(site['root'], workspace) as (app, client):
        jobs = [json_body(post(client, '/api/design-evaluation/jobs', envelope(DESIGN_REQUESTS['cached'], version)))['job']
                for version in 'AB']
        variants = [job['annotation_id'] for job in jobs]
        assert variants[0] != variants[1] and [job['key'] for job in jobs] == [site['design']] * 2
        id = create(client, 'Named electrodes')['project']['id']
        entries = [attach(client, id, n + 1, kind='layout', record_id=site['design'], annotation_id=variant)['entry']
                   for n, variant in enumerate(variants)]
        shutil.rmtree(workspace / 'annotations')
        for entry, version in zip(entries, 'AB'):
            snapshot = answer(client.get(f'{P}/{id}/entries/{entry["id"]}'))['snapshot']
            assert snapshot['electrode_annotation']['electrode_names'] == names(version)
        exported = answer(client.get(f'{P}/{id}/export'))
        assert validate_research_delivery(exported) is True
        assert [row['annotation_id'] for row in exported['records']] == variants
    copies = asyncio.run(ProjectStore(str(workspace / 'projects')).read_snapshots(id))
    for item, version in zip(copies['entries'], 'AB'):
        assert item['snapshot']['electrode_annotation']['electrode_names'] == names(version)
        assert '"owner"' not in item['snapshot_json']
    delivery = build_research_delivery(copies)
    assert validate_research_delivery(delivery) is True
    assert [row['annotation_id'] for row in delivery['records']] == variants
    assert jsjson.parse(delivery['files'][1]['content'])['electrode_annotation']['electrode_names'] == names('A')
    assert [file['content'] for file in delivery['files'][1:]] == [file['content'] for file in exported['files'][1:]]
    assert cache.read_bytes() == before


def test_the_export_is_an_uncached_attachment_within_the_delivery_bound(built, workspace):
    """The HTTP half of check-project-api.mjs:53."""
    with projects(built['root'], workspace) as (app, client):
        created = create(client)
        id = created['project']['id']
        attach(client, id, 1, kind='layout', record_id=built['ids']['strict'])
        exported = client.get(f'{P}/{id}/export')
        answer(exported)
        assert exported.headers['content-disposition'] == f'attachment; filename="eeg-research-{id}.json"'
        app.compute.projects.delivery.maximum_bytes = 100
        response = client.get(f'{P}/{id}/export')
        refusal(response, 413, 'Project export exceeds the size limit.')
        assert 'content-disposition' not in response.headers
        app.compute.projects.delivery.maximum_bytes = 32 * 1024 * 1024
        assert client.get(f'{P}/{id}/export').status_code == 200


# --- Access, the list, sharing ---------------------------------------------------------------------------------------

def test_the_list_names_the_projects_and_a_project_reads_without_a_key(built, workspace):
    """The HTTP half of check-project-api.mjs:43 for the one local user: ``GET /api/projects`` lists the projects
    (Node: 405), a project reads with any ``X-EEG-Project-Key`` or none, a query string is refused, and no answer
    carries a key or a key hash."""
    times = iter(f'2026-11-25T00:00:0{n}.000Z' for n in range(1, 10))
    with projects(built['root'], workspace, store={'now': lambda: next(times)}) as (app, client):
        assert answer(client.get(P)) == {'projects': []}
        a, b = create(client, 'A'), create(client, 'B', notes='n')
        listed = answer(client.get(P, headers={'x-eeg-project-key': a['access_key']}))
        assert listed == {'projects': [
            {'id': b['project']['id'], 'title': 'B', 'owner_name': 'Researcher', 'revision': 1,
             'created_at': '2026-11-25T00:00:02.000Z', 'updated_at': '2026-11-25T00:00:02.000Z', 'entry_count': 0},
            {'id': a['project']['id'], 'title': 'A', 'owner_name': 'Researcher', 'revision': 1,
             'created_at': '2026-11-25T00:00:01.000Z', 'updated_at': '2026-11-25T00:00:01.000Z', 'entry_count': 0}]}
        path = f"{P}/{a['project']['id']}"
        read = answer(client.get(path))
        assert read == {'project': a['project'], 'role': 'owner'}
        for key in (a['access_key'], b['access_key'], '0' * 64, 'not a key'):
            assert answer(client.get(path, headers={'x-eeg-project-key': key})) == read
        query = 'Project API credentials and parameters must not use a query string.'
        refusal(client.get(f"{path}?key={a['access_key']}"), 400, query)
        refusal(client.get(f'{P}?view=all'), 400, query)
        for text in (jsjson.stringify(listed), jsjson.stringify(read)):
            assert 'key_hash' not in text and a['access_key'] not in text and b['access_key'] not in text


def test_project_writes_need_the_token_every_request_a_loopback_origin_and_the_session(built, workspace):
    """The HTTP half of check-project-api.mjs:77: the token, the origin and the session are checked before the
    project middleware (``server.access``), then the bounded JSON and the revision."""
    with projects(built['root'], workspace) as (app, client):
        id = create(client)['project']['id']
        path = f'{P}/{id}'
        refusal(patch(client, path, {'revision': 1, 'title': 'Forbidden'}, **{'x-eeg-compute-token': ''}), 403,
                WRITE_TOKEN)
        refusal(post(client, P, {'title': 'Forbidden', 'owner_name': 'R'}, **{'x-eeg-compute-token': '0' * 64}), 403,
                WRITE_TOKEN)
        refusal(client.get(path, headers={'origin': 'https://attacker.invalid'}), 403, POLICY)
        refusal(patch(client, path, {'revision': 1, 'title': 'Forbidden'}, origin='https://attacker.invalid'), 403,
                POLICY)
        refusal(patch(client, path, '{broken'), 400, 'Invalid project JSON.')
        refusal(patch(client, path, {'revision': 1, 'notes': 'x' * 70000}), 413, 'Project request is too large.')
        assert answer(patch(client, path, {'revision': 1, 'title': 'Renamed'}))['project']['revision'] == 2
        refusal(patch(client, path, {'revision': 1, 'title': 'Stale'}), 409, CHANGED)
        refusal(patch(client, path, {'revision': 2, 'identity': {'fake': True}}), 400, 'Invalid project fields.')
        client.cookies.clear()
        response = client.get(path)
        assert response.status_code == 401 and json_body(response)['code'] == 'authentication_required'
        assert client.get(f'/open?token={TOKENS.launch}').status_code == 303
        project = answer(client.get(path))['project']
        assert (project['title'], project['revision']) == ('Renamed', 2)
        assert [row['id'] for row in answer(client.get(P))['projects']] == [id]


def test_sharing_is_not_an_endpoint(built, workspace):
    """The HTTP half of check-project-api.mjs:88 and check-project-store.mjs:87: ``share`` and ``revoke-share`` are
    404 ``Project endpoint not found.`` for any method and project, and change nothing."""
    with projects(built['root'], workspace) as (app, client):
        created = create(client)
        id = created['project']['id']
        for target in (id, UNKNOWN):
            for operation in ('share', 'revoke-share'):
                refusal(post(client, f'{P}/{target}/{operation}', {'revision': 1}), 404, ENDPOINT)
                refusal(client.get(f'{P}/{target}/{operation}'), 404, ENDPOINT)
        assert answer(client.get(f'{P}/{id}')) == {'project': created['project'], 'role': 'owner'}


def test_signal_attachments_refuse_foreign_running_or_client_results_before_reading_one(tmp_path, workspace):
    """The HTTP half of check-project-api.mjs:110 on the workspace queue: a receipt the queue does not give is 404,
    a running one 409, scientific data in the body 400, and no saved result is read."""
    site = reception_compute_root(tmp_path / 'root')
    with projects(site['root'], workspace) as (app, client):
        reads: list[Any] = []
        adapter = app.compute.queue.adapters['source-reception']
        adapter.saved_result = lambda *args: reads.append(args)
        id = create(client)['project']['id']
        path = f'{P}/{id}/entries'
        refusal(post(client, path, {'revision': 1, 'kind': 'source', 'receipt_id': UNKNOWN}), 404, NOT_OWNED)
        held = json_body(post(client, '/api/source-reception/jobs', site['requests']['hold']))['job']['id']
        try:
            poll(client, held, ('running',), kind='source-reception')
            refusal(post(client, path, {'revision': 1, 'kind': 'source', 'receipt_id': held}), 409,
                    'Only completed signal results can be saved.')
            refusal(post(client, path, {'revision': 1, 'kind': 'source', 'receipt_id': held,
                                        'payload': {'schema_version': 'source-reception/2'}}), 400,
                    'Invalid project attachment.')
        finally:
            post(client, f'/api/source-reception/jobs/{held}/cancel')
            poll(client, held, TERMINAL, kind='source-reception')
        assert reads == []
        assert answer(client.get(f'{P}/{id}'))['project']['revision'] == 1


def test_until_the_lifespan_has_started_every_project_path_is_not_found(built, workspace):
    with serving(Path(built['root']), workspace, lifespan=False) as (app, client):
        assert app.compute.projects is None
        refusal(client.get(P), 404, ENDPOINT)
        refusal(post(client, P, {'title': 'Study', 'owner_name': 'Researcher'}), 404, ENDPOINT)
        refusal(client.get(f'{P}/{UNKNOWN}/export'), 404, ENDPOINT)
        refusal(client.delete(f'{P}/{UNKNOWN}/entries/{UNKNOWN}', headers={'if-match': '1'}), 404, ENDPOINT)
    assert not (workspace / 'projects').exists()


def test_projects_survive_a_restart(built, workspace):
    with projects(built['root'], workspace) as (app, client):
        id = create(client)['project']['id']
        entry = attach(client, id, 1, kind='layout', record_id=built['ids']['cache'])['entry']
        before = [client.get(target).text for target in (P, f'{P}/{id}', f'{P}/{id}/entries/{entry["id"]}')]
        exported = answer(client.get(f'{P}/{id}/export'))
    with projects(built['root'], workspace) as (app, client):
        assert [client.get(target).text for target in (P, f'{P}/{id}', f'{P}/{id}/entries/{entry["id"]}')] == before
        again = answer(client.get(f'{P}/{id}/export'))
        # The manifest's digest covers the export time.
        moment = {'exported_at': None, 'manifest_sha256': None}
        assert {**again, **moment} == {**exported, **moment}
        assert answer(patch(client, f'{P}/{id}', {'revision': 2, 'title': 'Continued'}))['project']['revision'] == 3


# --- Shutdown --------------------------------------------------------------------------------------------------------

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
    for name, owner, methods in (('studies', host.studies, ('stop', 'aclose')),
                                 ('projects', host.projects, ('close', 'flush')),
                                 ('queue', host.queue, ('stop_scheduling', 'dispose', 'close')),
                                 ('design', host.design, ('dispose', 'aclose'))):
        for method in methods:
            monkeypatch.setattr(owner, method, recorder(calls, f'{name}.{method}', getattr(owner, method)))
    return calls


def held_write(monkeypatch: Any, client: Any, app: Service, id: str, calls: list[str], release: Any) -> Any:
    """A ``PATCH`` of project ``id`` (revision 1, title ``Accepted before stop``) as a task of the client's portal (whose
    shutdown waits for it, so its answer is read even when the lifespan stops meanwhile), its save held in the write's
    worker thread until ``release()`` holds (bounded), then recorded in ``calls`` as ``project write done``. Returns
    the task's future, of ``(status, text)``, once the write has been accepted (its save entered)."""
    store, entered = app.compute.projects.store, threading.Event()
    save = store.save_sync

    def held(record: dict) -> None:
        if record.get('title') == 'Accepted before stop':
            entered.set()
            wait_for(release)
            calls.append('project write done')
        return save(record)
    monkeypatch.setattr(store, 'save_sync', held)
    path = f'{P}/{id}'
    body = jsjson.stringify({'revision': 1, 'title': 'Accepted before stop'}).encode('utf-8')
    headers = [(b'host', HOST.encode()), (b'cookie', session_cookie().encode()),
               (b'content-type', b'application/json'), (b'x-eeg-compute-token', TOKENS.csrf.encode())]
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'PATCH', 'scheme': 'http',
             'path': path, 'raw_path': path.encode(), 'query_string': b'', 'root_path': '', 'headers': headers,
             'client': ('127.0.0.1', 50000), 'server': ('127.0.0.1', PORT)}

    async def send_patch() -> tuple[int, str]:
        messages: list[dict] = []
        sent = [{'type': 'http.request', 'body': body, 'more_body': False}]

        async def receive() -> dict:
            return sent.pop(0) if sent else {'type': 'http.disconnect'}

        async def send(message: dict) -> None:
            messages.append(message)
        await app(scope, receive, send)
        status = next(message['status'] for message in messages if message['type'] == 'http.response.start')
        text = b''.join(message.get('body', b'') for message in messages if message['type'] == 'http.response.body')
        return status, text.decode('utf-8')
    answer = client.portal.start_task_soon(send_patch)
    assert entered.wait(SETTLE)
    return answer


def stored_title(workspace: Path, id: str) -> str:
    return jsjson.parse((workspace / 'projects' / id / 'project.json').read_text(encoding='utf-8'))['title']


def test_shutdown_awaits_an_accepted_project_write_before_the_queues_last_write(built, workspace, monkeypatch):
    """check-product-operations-integration.mjs:113 without the operations log: a project write accepted before the
    shutdown is awaited (``projects.flush``) before the studies' and the queue's last writes; it answers 200 and its
    change is on disk. The store closes right after the studies stop, before the queue's scheduling."""
    with serving(Path(built['root']), workspace) as (app, client):
        host = app.compute
        assert Path(host.projects.store.directory) == (workspace / 'projects').resolve()
        assert host.projects.before_write == host._admit
        id = create(client, 'Flush test')['project']['id']
        calls = record_dispose(monkeypatch, app)
        answered = held_write(monkeypatch, client, app, id, calls, lambda: 'projects.flush' in calls)
    # The lifespan's shutdown (ComputeHost.close) has run.
    assert answered.result(SETTLE)[0] == 200, answered.result(0)
    assert calls[:4] == ['studies.stop', 'projects.close', 'queue.stop_scheduling', 'design.dispose']
    assert calls.index('projects.flush') < calls.index('project write done') < calls.index('studies.aclose')
    assert calls.index('studies.aclose') < calls.index('design.aclose') < calls.index('queue.close')
    assert calls.index('queue.close') < calls.index('queue.dispose') and calls.count('queue.dispose') == 1
    assert host.projects.store.closed
    assert stored_title(workspace, id) == 'Accepted before stop'


def test_stop_soon_closes_the_projects_and_reads_still_answer(built, workspace, monkeypatch):
    """After ``serve``'s signal (``stop_soon``) with no project write pending, the queue is written at once; every
    project write is then 503 ``Project store is stopping.`` and every read still answers."""
    with projects(built['root'], workspace) as (app, client):
        id = create(client)['project']['id']
        entry = attach(client, id, 1, kind='layout', record_id=built['ids']['cache'])['entry']
        calls = record_dispose(monkeypatch, app)
        app.compute.stop_soon()
        wait_for(lambda: 'queue.dispose' in calls)
        assert calls[:5] == ['studies.stop', 'projects.close', 'queue.stop_scheduling', 'design.dispose',
                             'queue.dispose']
        base = f'{P}/{id}'
        for response in (post(client, P, {'title': 'Late', 'owner_name': 'R'}),
                         patch(client, base, {'revision': 2, 'title': 'Late'}),
                         post(client, f'{base}/entries', {'revision': 2, 'kind': 'layout',
                                                          'record_id': built['ids']['strict']}),
                         patch(client, f'{base}/entries/{entry["id"]}', {'revision': 2, 'title': 'Late'}),
                         client.delete(f'{base}/entries/{entry["id"]}', headers={'if-match': '2'})):
            refusal(response, 503, STOPPING)
        for target in (P, base, f'{base}/entries/{entry["id"]}', f'{base}/export'):
            assert client.get(target).status_code == 200
        assert answer(client.get(base))['project']['revision'] == 2


def test_stop_soon_leaves_the_queues_last_write_until_a_project_write_is_done(built, workspace, monkeypatch):
    """Node's dispose defers ``scheduler.dispose()`` while a project write is pending: after ``stop_soon`` the queue
    is written by ``close``, once the write is done."""
    release = threading.Event()
    with projects(built['root'], workspace) as (app, client):
        host = app.compute
        id = create(client, 'Flush test')['project']['id']
        calls = record_dispose(monkeypatch, app)
        answered = held_write(monkeypatch, client, app, id, calls, release.is_set)
        try:
            host.stop_soon()
            # Once a coroutine scheduled after it has run, the stop has run on the loop.
            asyncio.run_coroutine_threadsafe(asyncio.sleep(0), host._loop).result(SETTLE)
            assert calls[:4] == ['studies.stop', 'projects.close', 'queue.stop_scheduling', 'design.dispose']
            assert 'queue.dispose' not in calls
            refusal(post(client, P, {'title': 'Late', 'owner_name': 'R'}), 503, STOPPING)
            assert answer(client.get(f'{P}/{id}'))['project']['title'] == 'Flush test'
        finally:
            release.set()
        assert answered.result(SETTLE)[0] == 200, answered.result(0)
        assert answer(client.get(f'{P}/{id}'))['project']['title'] == 'Accepted before stop'
    assert calls.index('project write done') < calls.index('queue.dispose')
    assert calls.count('queue.dispose') == 1
    assert stored_title(workspace, id) == 'Accepted before stop'


# --- Parity ----------------------------------------------------------------------------------------------------------

@needs_node
def test_the_project_routes_answer_and_write_as_node_does(tmp_path):
    """compute_support.project_steps against Node's composed service and the Python application on the same root
    (built again at the same path for Python), with the same stand-in workers: the answers, the job records and the
    project trees. Node's session is the local owner on a network whose name is a SHA-256, as its records require;
    the driver sends each project's Node credential, which the Python service ignores."""
    directory = tmp_path / 'root'
    site = project_compute_root(directory)
    steps = project_steps(site)
    scratch = tmp_path / 'node'
    scratch.mkdir()
    theirs = run_node(Path(site['root']), scratch, steps, owner=LOCAL_OWNER, network=STUDY_NETWORK)
    node_design, node_reception = design_tree(Path(site['root'])), reception_tree(Path(site['root']))
    node_projects = study_tree(scratch / 'queue' / 'projects')
    directory.rename(tmp_path / 'root.node')
    site = project_compute_root(directory)
    assert project_steps(site) == steps
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    ours = run_python(Path(site['root']), workspace, steps)
    assert len(ours['answers']) == len(theirs['answers']) == len(steps)
    project_differences(steps, theirs['answers'], ours['answers'])
    expected = project_masked(theirs['answers'], theirs['token'], steps, node=True)
    actual = project_masked(ours['answers'], ours['token'], steps, node=False)
    kept = [step for step in steps if not step.get('differs')]
    for index, (step, node, python) in enumerate(zip(kept, expected, actual)):
        assert python == node, f'step {index} {step["method"]} {step["path"]}: {python} != {node}'
    assert sum(answer['disposition'] is not None for answer in actual) == 2
    assert masked_tree(ours['design_tree']) == masked_tree(node_design)
    assert masked_tree(ours['reception_tree']) == masked_tree(node_reception)
    node_masked = project_tree_masked(node_projects, project_ids(theirs['answers'], steps))
    our_masked = project_tree_masked(ours['projects'], project_ids(ours['answers'], steps))
    assert our_masked == node_masked
    assert sum(path.endswith('/project.json') for path in our_masked) == 4  # the projects the steps create
    assert not (Path(site['root']) / 'results/web-service').exists()
