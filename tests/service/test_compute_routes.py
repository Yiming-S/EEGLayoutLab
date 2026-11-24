"""The job routes (``eeglayoutlab.server.routes.compute`` and ``.community``, phase 2 slices 4 and 5) end to end:
the application with its lifespan, the workspace queue, the radius search and the coordinate evaluation on synthetic
roots whose workers are fakes (tests/service/compute_support.py), over HTTP.

- A submission is queued (202), dispatched, run by the worker and polled to its result; asked again it is the
  stored result's receipt (Node's ``{hit: true, job}``), and the library lists the new record.
- Identical requests join one task; a lookup sees it; a queued task is cancelled at once, a running one stops and
  its capacity passes to the next task; failures and invalid results keep Node's messages.
- Two workspaces of one installation: while one computes, the other's task stays queued and its queue file is
  not written (no spawn intent), then runs.
- ``ComputeHost.stop_soon`` (serve's first signal) stops the running worker while the service still answers; one
  that comes before the services exist stops them once built, so a task left queued stays queued.
- A lookup never writes a record, takes the execution lock or queues a task (check-local-data-library.mjs:121).
- ``--cache-only`` serves stored results and refuses new work; the global bound answers 429 ``queue_limited``.
- Restart: a second application on the same workspace fails the interrupted receipt, runs the queued one, promotes
  a receipt whose result was stored, and an unconfirmed spawn blocks dispatch until ``--clear-interrupted``.
- Node's body limits per kind, media type and JSON checks, the CSRF token of writes, the view's query rules,
  unknown receipts and the 404 of unwired kinds.
- Parity: the same steps against Node's composed service (``createLocalComputeService``) on the same root, with the
  same fake worker, give the same statuses and bodies (ids, times and the token masked, Node's ``online_visitors``
  dropped) and the same record tree under ``R/results/v2/local_app_jobs``; on a root whose ``results`` is a link
  out of it, the same refusal; and on one whose ``results`` link spells the root in upper case, the same result.
- The coordinate evaluation (``/api/design-evaluation``): a submission with names runs to its record and the names
  are an annotation under W that the receipt references; job views, library records and bundles show it for
  ``?annotation_id``, and the library reads Node's annotations under R too. A lookup miss writes nothing, the
  stored evaluation is one cached receipt with or without names, identical submissions join, cancellation stores
  nothing, ``stop_soon`` and a restart stop the worker (the interrupted receipt fails and keeps its annotations),
  and a code change after close turns the receipt's view failed; a receipt whose result was stored is promoted at
  restart with the stored finish time (not when the record names another identity), and the health of a receipt
  whose annotation is gone answers as its view. Node's 100 variants per receipt (its per-owner bound of 20 is
  dropped), the 65,536-byte envelope, CSRF and a body sent one byte per chunk. Parity: ``DESIGN_STEPS`` on Node's
  composed service and here give the same answers, design records and annotation bytes (Node's under R, ours under
  W), and a configured path with a NUL byte answers Node's 500.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys
import time
from typing import Any

import pytest

from .key_parity_support import needs_node, require

require('fastapi')
require('httpx')
require('pydantic')

from eeglayoutlab.jobs.queue import INTERRUPTED_MESSAGE, MAINTENANCE, NOT_FOUND, QUEUE_FULL  # noqa: E402
from eeglayoutlab.jobs.radius import WORKER_SCRIPT  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402

from .compute_support import (  # noqa: E402
    CHANGED_INPUT, DESIGN_JOBS, DESIGN_REQUESTS, DESIGN_STEPS, NODE_ANNOTATIONS, REQUESTS, SOURCE, TERMINAL,
    WORKSPACE_ANNOTATIONS, annotation_tree, cache_digests, chunked, compute_root, design_compute_root, design_key,
    design_tree, design_view, envelope, json_body, jobs_tree, key_of, masked, masked_tree, names, padded, poll, post,
    queue_file, run_node, run_python, serving, wait_for, write_queue,
)
from .library_support import radius_result, write, write_cache  # noqa: E402

LOOKUP = '/api/local-compute/lookup'
JOBS = '/api/local-compute/jobs'
UNKNOWN_ID = '00000000-0000-4000-8000-000000000000'
LOCK = 'results/v2/.eeglayoutlab-execution.lock'
CSRF_REFUSAL = '会话已更新，请刷新页面后重新计算'


@pytest.fixture
def site(tmp_path):
    """A fresh root (with its provenance) and workspace."""
    root = tmp_path / 'root'
    provenance = compute_root(root)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    return root, workspace, provenance


def error(response) -> tuple[int, str, str]:
    body = json_body(response)
    return response.status_code, body['error'], body['code']


# --- Submit, poll, cached hit ---------------------------------------------------------------------------------------

def test_a_submission_runs_to_its_result_and_is_then_the_stored_receipt(site):
    root, workspace, _ = site
    key = key_of(root, REQUESTS['done'])
    with serving(root, workspace) as (app, client):
        submitted = post(client, JOBS, REQUESTS['done'])
        assert submitted.status_code == 202, submitted.text
        receipt = json_body(submitted)['job']
        assert (receipt['status'], receipt['key'], receipt['message'], receipt['queue_position']) == (
            'queued', key, '已加入计算队列', 1)
        assert receipt['result'] is None and receipt['cached'] is False
        job = poll(client, receipt['id'])
        assert (job['status'], job['stage'], job['progress'], job['message']) == (
            'completed', 'completed', 1, '当前配置已计算')
        assert (job['cached'], job['source'], job['queue_position']) == (False, 'local_compute', 0)
        assert job['result']['status'] == 'completed' and job['result']['request'] == job['request']

        again = post(client, JOBS, REQUESTS['done'])
        assert again.status_code == 202
        hit = json_body(again)
        assert hit['hit'] is True and hit['job']['id'] == receipt['id'] and hit['job']['cached'] is True
        assert hit['job']['result'] == job['result']
        lookup = post(client, LOOKUP, REQUESTS['done'])
        assert lookup.status_code == 200 and json_body(lookup)['hit'] is True

        # One receipt: the stored result reuses the computed one; the record tree is Node's.
        assert [task['id'] for task in queue_file(workspace)['tasks']] == [receipt['id']]
        tree = jobs_tree(root)
        assert f'{key}/cache.json' in tree
        batch = next(path.split('/')[1] for path in tree if path.endswith('/job.json'))
        record = jsjson.parse(tree[f'{key}/{batch}/job.json'])
        assert record['status'] == 'completed' and record['stderr'] == 'warning: 中文\n'
        assert {'type': 'log', 'text': 'plain log line'} in record['events']
        cache = jsjson.parse(tree[f'{key}/cache.json'])
        assert cache['result'] == job['result']

        health = json_body(client.get('/api/local-compute/health'))
        assert health['active_job'] is None and (health['maintenance'], health['drained']) == (False, False)
        status = json_body(client.get('/api/community/status'))
        assert (status['queued_tasks'], status['running_tasks'], status['available']) == (0, 0, True)
        assert [entry['id'] for entry in status['jobs']] == [receipt['id']]
        assert 'result' not in status['jobs'][0] and 'online_visitors' not in status

        # The library sees the new record through the same radius search.
        listing = json_body(client.get('/api/local-compute/library'))
        row = next(row for row in listing['records'] if row['id'] == key)
        assert (row['dataset_id'], row['status'], row['compatible']) == ('cache', 'completed', True)
        record = json_body(client.get(f'/api/local-compute/library/{key}'))['record']
        assert record['compatible'] is True and record['request'] == job['request']


def test_no_layout_a_crash_and_an_invalid_result_keep_their_messages(site):
    root, workspace, _ = site
    with serving(root, workspace) as (app, client):
        ids = [json_body(post(client, JOBS, REQUESTS[name]))['job']['id'] for name in ('none', 'crash', 'stale')]
        none, crash, stale = (poll(client, id) for id in ids)
    assert (none['status'], none['message'], none['result']['status']) == (
        'no_layout', '本次搜索预算内未构造出64点布局', 'no_layout')
    assert (crash['status'], crash['message'], crash['result']) == (
        'failed', '计算未成功完成；错误记录已保存，可重新计算', None)
    assert stale['status'] == 'failed' and stale['message'].startswith('计算结果校验失败：')
    tree = jobs_tree(root)
    for name, cached in (('none', True), ('crash', False), ('stale', False)):
        key = key_of(root, REQUESTS[name])
        assert (f'{key}/cache.json' in tree) is cached
        assert any(path.startswith(f'{key}/') and path.endswith('/job.json') for path in tree)
    crashed = next(text for path, text in tree.items()
                   if path.startswith(key_of(root, REQUESTS['crash'])) and path.endswith('/job.json'))
    assert jsjson.parse(crashed)['stderr'] == 'Traceback: boom\n'


# --- Deduplication and cancellation ---------------------------------------------------------------------------------

def test_identical_requests_join_one_task_and_cancellation_passes_the_slot_on(site):
    root, workspace, _ = site
    with serving(root, workspace) as (app, client):
        held = json_body(post(client, JOBS, REQUESTS['hold']))['job']
        views: list = []
        # Until the spawn returns, the receipt is running without a job, so its message is Node's 'running' (the
        # longer under load); the worker's progress line then sets its own.
        wait_for(lambda: views.append(poll(client, held['id'], ('running',))) or views[-1]['progress'] == 0.25)
        assert all(view['message'] in ('running', '正在加载本地头模与前向矩阵', '构建候选区域') for view in views)
        assert views[-1]['message'] == '构建候选区域'
        joined = json_body(post(client, JOBS, REQUESTS['hold']))
        assert joined['hit'] is True and joined['job']['id'] == held['id'] and joined['job']['status'] == 'running'
        seen = json_body(post(client, LOOKUP, REQUESTS['hold']))
        assert seen['hit'] is True and seen['job']['id'] == held['id']

        queued = json_body(post(client, JOBS, REQUESTS['none']))['job']
        assert (queued['status'], queued['queue_position']) == ('queued', 1)
        later = json_body(post(client, JOBS, REQUESTS['second-hold']))['job']
        assert later['queue_position'] == 2
        health = json_body(client.get('/api/local-compute/health'))
        assert health['active_job']['id'] == held['id'] and 'result' not in health['active_job']
        status = json_body(client.get('/api/community/status'))
        assert (status['queued_tasks'], status['running_tasks']) == (2, 1)
        assert [entry['id'] for entry in status['jobs']] == [later['id'], queued['id'], held['id']]

        cancelled = client.post(f'{JOBS}/{later["id"]}/cancel')
        assert cancelled.status_code == 202
        assert json_body(cancelled)['job']['status'] == 'cancelled'
        stopping = json_body(client.post(f'{JOBS}/{held["id"]}/cancel'))['job']
        assert (stopping['status'], stopping['message']) == ('cancelling', '正在停止计算')
        stopped = poll(client, held['id'])
        assert (stopped['status'], stopped['message'], stopped['result']) == ('cancelled', '任务已停止', None)
        assert poll(client, queued['id'])['status'] == 'no_layout'
        # Cancelling a finished receipt answers its view and changes nothing.
        again = client.post(f'{JOBS}/{held["id"]}/cancel')
        assert again.status_code == 202 and json_body(again)['job']['status'] == 'cancelled'
    tree = jobs_tree(root)
    assert f'{key_of(root, REQUESTS["hold"])}/cache.json' not in tree
    assert not any(path.startswith(key_of(root, REQUESTS['second-hold'])) for path in tree)


def test_a_task_waiting_for_another_workspace_stays_queued_and_its_queue_file_unwritten(tmp_path):
    """Two workspaces of one installation compute one at a time (the installation lock). While A computes, B's
    receipt stays queued with Node's queued view and B writes nothing: no spawn intent that a crash could leave behind
    (B would then fail the task and block dispatch at its next start). Once A's worker stops, B's task runs."""
    root = tmp_path / 'root'
    compute_root(root)
    first, second = tmp_path / 'a', tmp_path / 'b'
    first.mkdir()
    second.mkdir()
    with serving(root, first) as (_, a), serving(root, second, queue_options={'retry_seconds': 0.05}) as (app, b):
        held = json_body(post(a, JOBS, REQUESTS['hold']))['job']
        wait_for(lambda: poll(a, held['id'], ('running',))['progress'] == 0.25)
        waiting = json_body(post(b, JOBS, REQUESTS['none']))['job']
        path = second / '.eeglayoutlab/queue.json'
        before, inode = path.read_bytes(), path.stat().st_ino
        deadline = time.monotonic() + 1.0  # 20 retry periods
        while time.monotonic() < deadline:
            assert path.stat().st_ino == inode and path.read_bytes() == before
            view = poll(b, waiting['id'], ('queued',))
            assert (view['message'], view['queue_position']) == ('已加入计算队列', 1)
            status = json_body(b.get('/api/community/status'))
            assert (status['queued_tasks'], status['running_tasks'], status['recovery_blocked']) == (1, 0, False)
            time.sleep(0.01)
        assert app.compute.slot.contended and app.compute.radius.jobs == {}
        assert a.post(f'{JOBS}/{held["id"]}/cancel').status_code == 202
        assert poll(a, held['id'])['status'] == 'cancelled'
        assert poll(b, waiting['id'])['status'] == 'no_layout'
    assert f'{key_of(root, REQUESTS["none"])}/cache.json' in jobs_tree(root)


# --- Lookups ---------------------------------------------------------------------------------------------------------

def test_the_lookup_endpoint_answers_without_a_task_and_rejects_extra_fields(site):
    """check-local-data-library.mjs:121 over HTTP: the stored request is a hit, another radius a miss, an extra
    field a 400; no task is queued, nothing is written under R and the execution lock is never taken."""
    root, workspace, provenance = site
    request = REQUESTS['none']
    key = key_of(root, request)
    write_cache(root, key, request, radius_result(request, provenance, status='no_layout'),
                '2026-09-08T12:00:00Z')
    before = snapshot(root)
    with serving(root, workspace) as (app, client):
        for body, status, hit in ((request, 200, True), ({**request, 'radius_mm': 20}, 200, False),
                                  ({**request, 'AR': 0.9}, 400, None)):
            response = post(client, LOOKUP, body)
            assert response.status_code == status, response.text
            if hit is not None:
                assert json_body(response)['hit'] is hit
        hit = json_body(post(client, LOOKUP, request))['job']
        assert (hit['status'], hit['cached'], hit['finished_at']) == ('no_layout', True, '2026-09-08T12:00:00Z')
        assert json_body(post(client, LOOKUP, REQUESTS['done'])) == {'hit': False}
        status = json_body(client.get('/api/community/status'))
        assert (status['queued_tasks'], status['running_tasks']) == (0, 0)
        assert app.compute.radius.active is None
        assert json_body(client.get('/api/local-compute/health'))['active_job'] is None
    assert snapshot(root) == before
    assert not (root / LOCK).exists()
    # The hit is a cached receipt in the workspace, as Node keeps one; a repeated lookup reuses it.
    tasks = queue_file(workspace)['tasks']
    assert [(task['key'], task['status'], task['cached']) for task in tasks] == [(key, 'no_layout', True)]


def snapshot(root: Path) -> dict:
    state = {}
    for directory, folders, files in os.walk(root):
        for name in folders + files:
            info = os.lstat(os.path.join(directory, name))
            state[os.path.join(directory, name)] = (info.st_mode, info.st_size, info.st_mtime_ns)
    return state


# --- Cache-only and the bound ---------------------------------------------------------------------------------------

def test_cache_only_serves_stored_results_and_refuses_new_work(site):
    root, workspace, provenance = site
    request = REQUESTS['none']
    key = key_of(root, request)
    write_cache(root, key, request, radius_result(request, provenance, status='no_layout'), '2026-09-08T12:00:00Z')
    with serving(root, workspace, cache_only=True) as (app, client):
        health = json_body(client.get('/api/local-compute/health'))
        assert (health['maintenance'], health['drained'], health['active_job']) == (True, True, None)
        assert error(post(client, JOBS, REQUESTS['done'])) == (503, MAINTENANCE, 'service_unavailable')
        assert json_body(post(client, LOOKUP, REQUESTS['done'])) == {'hit': False}
        served = post(client, JOBS, request)
        assert served.status_code == 202 and json_body(served)['hit'] is True
        status = json_body(client.get('/api/community/status'))
        assert (status['maintenance'], status['drained'], status['queued_tasks']) == (True, True, 0)
    assert not (root / LOCK).exists()
    assert not any(path.startswith(key_of(root, REQUESTS['done'])) for path in jobs_tree(root))


def test_the_pending_bound_answers_queue_limited(site):
    """50 pending tasks (one running, 49 queued): the 51st is 429 with Node's message; stored results and joins of
    a pending key are still served."""
    root, workspace, _ = site
    others = [{'region_count': regions, 'radius_mm': radius, 'mode': mode}
              for mode in ('whole_surface', 'low_hair') for regions in (1, 2, 3, 4, 6) for radius in range(15, 85, 5)]
    others = [request for request in others if request not in REQUESTS.values()]
    with serving(root, workspace) as (app, client):
        held = json_body(post(client, JOBS, REQUESTS['hold']))['job']
        poll(client, held['id'], ('running',))
        for request in others[:49]:
            response = post(client, JOBS, request)
            assert response.status_code == 202, response.text
        assert error(post(client, JOBS, others[49])) == (429, QUEUE_FULL, 'queue_limited')
        joined = post(client, JOBS, others[0])
        assert joined.status_code == 202 and json_body(joined)['hit'] is True
        assert json_body(client.get('/api/community/status'))['queued_tasks'] == 49
    # Shutdown stopped the held worker; the queued receipts stay queued for the next start.
    tasks = queue_file(workspace)['tasks']
    assert sum(task['status'] == 'queued' for task in tasks) == 49


def test_the_services_share_one_record_store_and_one_execution_slot(site):
    """check-service-storage.mjs:12 with the queue: the workspace queue (in ``W/.eeglayoutlab``), the radius search
    and the library share one execution slot, with the installation lock, and one record store; ``--cache-only``
    pauses that slot, so a new submit is refused with Node's maintenance answer and the queue file is still written.
    Node's custom queue directory is dropped (R6)."""
    root, workspace, _ = site
    with serving(root, workspace, cache_only=True) as (app, client):
        compute = app.compute
        assert Path(compute.queue.path) == workspace / '.eeglayoutlab/queue.json'
        assert compute.queue.slot is compute.slot and compute.radius.execution_slot is compute.slot
        assert Path(compute.slot.lock.path) == root / LOCK
        # The library routes' runtime is what the services were built with (app._api); its library reads the
        # records through the radius search's store.
        library = compute.runtime.__self__.library()
        assert library.radius is compute.radius and library.store is compute.radius.store
        # The coordinate evaluation runs under the same slot into the same store; its names go to W.
        assert compute.design.execution_slot is compute.slot and compute.design.store is compute.radius.store
        assert compute.queue.annotations is compute.annotations
        assert compute.slot.paused and not compute.slot.busy
        assert error(post(client, JOBS, REQUESTS['done'])) == (503, MAINTENANCE, 'service_unavailable')
        assert queue_file(workspace)['schema'] == 'eeglayoutlab-queue/1'
    assert not (root / LOCK).exists()


def test_stop_soon_stops_the_running_worker_while_the_service_still_answers(site):
    """``serve``'s first signal (``ComputeHost.stop_soon``, from another thread than the services' loop) is Node's
    synchronous dispose: the services refuse new work and the running worker is stopped and its records written at
    once, not after uvicorn's graceful wait."""
    from eeglayoutlab.jobs.queue import group_alive

    root, workspace, _ = site
    with serving(root, workspace) as (app, client):
        held = json_body(post(client, JOBS, REQUESTS['hold']))['job']
        wait_for(lambda: poll(client, held['id'], ('running',))['progress'] == 0.25)
        task = queue_file(workspace)['tasks'][-1]
        pid = int(task['worker_pid'])
        assert group_alive(pid)
        app.compute.stop_soon()
        wait_for(lambda: not group_alive(pid))
        wait_for(lambda: any(path.endswith('/job.json') for path in jobs_tree(root)))
        [record] = [text for path, text in jobs_tree(root).items() if path.endswith('/job.json')]
        stored = jsjson.parse(record)
        assert (stored['id'], stored['status'], stored['message']) == (task['backend_id'], 'cancelled', '任务已停止')
        assert json_body(client.get('/api/community/status'))['available'] is False


@pytest.mark.parametrize('when', ['before the services start', 'while they are built'])
def test_a_stop_while_the_services_start_launches_nothing_and_keeps_the_queued_task(site, monkeypatch, when):
    """``serve``'s first signal can come before the compute services exist: before the lifespan starts them, or while
    they are built in a worker thread. The request is kept and they stop once built, as Node's ``dispose`` before its
    first tick: nothing is recovered or dispatched, so the task an earlier run left queued stays queued, without a
    spawn intent and without records."""
    from eeglayoutlab.server.routes.compute import ComputeHost

    root, workspace, _ = site
    (workspace / '.eeglayoutlab').mkdir(mode=0o700)
    task = {'id': '11111111-1111-4111-8111-111111111111', 'sequence': 1, 'kind': 'local-compute',
            'key': key_of(root, REQUESTS['hold']), 'request': REQUESTS['hold'], 'status': 'queued',
            'created_at': '2026-11-23T08:00:00.000Z', 'progress': 0, 'cached': False, 'catalog': {}}
    write_queue(workspace, {'schema': 'eeglayoutlab-queue/1', 'sequence': 1, 'tasks': [task]})
    if when == 'before the services start':
        start = ComputeHost.start

        async def stopped_first(self: ComputeHost) -> None:
            self.stop_soon()
            await start(self)
        monkeypatch.setattr(ComputeHost, 'start', stopped_first)
    else:
        build = ComputeHost._build

        def stopped_while_built(self: ComputeHost) -> Any:
            self.stop_soon()  # from the worker thread, while the loop runs
            return build(self)
        monkeypatch.setattr(ComputeHost, '_build', stopped_while_built)
    with serving(root, workspace) as (app, client):
        status = json_body(client.get('/api/community/status'))
        assert (status['queued_tasks'], status['running_tasks'], status['available']) == (1, 0, False)
        time.sleep(0.3)  # far longer than a dispatch takes to write its spawn intent and request.json
        assert jobs_tree(root) == {} and app.compute.queue._dispatcher is None
    [stored] = queue_file(workspace)['tasks']
    assert stored == task
    assert jobs_tree(root) == {} and not (root / LOCK).exists()


# --- Restart --------------------------------------------------------------------------------------------------------

def test_a_second_instance_fails_the_interrupted_task_runs_the_queued_one_and_promotes_a_stored_result(site):
    root, workspace, _ = site
    with serving(root, workspace) as (app, client):
        done = json_body(post(client, JOBS, REQUESTS['done']))['job']
        poll(client, done['id'])
        held = json_body(post(client, JOBS, REQUESTS['hold']))['job']
        poll(client, held['id'], ('running',))
        queued = json_body(post(client, JOBS, REQUESTS['none']))['job']
    state = queue_file(workspace)
    statuses = {task['id']: task['status'] for task in state['tasks']}
    assert statuses == {done['id']: 'completed', held['id']: 'running', queued['id']: 'queued'}
    assert [path for path in jobs_tree(root) if path.startswith(key_of(root, REQUESTS['hold']))
            and path.endswith('/job.json')]
    # A crash after the records were written but before the receipt was final.
    for task in state['tasks']:
        if task['id'] == done['id']:
            task['status'] = 'running'
            task.pop('finished_at', None)
    write_queue(workspace, state)

    with serving(root, workspace) as (app, client):
        interrupted = poll(client, held['id'])
        assert (interrupted['status'], interrupted['message']) == ('failed', INTERRUPTED_MESSAGE)
        promoted = poll(client, done['id'])
        assert (promoted['status'], promoted['cached'], promoted['progress']) == ('completed', True, 1)
        assert promoted['result']['status'] == 'completed'
        assert poll(client, queued['id'])['status'] == 'no_layout'
        assert json_body(client.get('/api/community/status'))['recovery_blocked'] is False
        resubmitted = json_body(post(client, JOBS, REQUESTS['hold']))['job']
        assert resubmitted['id'] != held['id'] and resubmitted['status'] in ('queued', 'running')


def test_an_unconfirmed_spawn_blocks_dispatch_until_clear_interrupted(site, caplog):
    root, workspace, _ = site
    with serving(root, workspace) as (app, client):
        queued = json_body(post(client, JOBS, REQUESTS['none']))['job']
        poll(client, queued['id'])
        waiting = json_body(post(client, JOBS, REQUESTS['done']))['job']
        poll(client, waiting['id'])
    state = queue_file(workspace)
    # A spawn intent that no pid confirmed, written just now: the machine has not restarted since.
    for task in state['tasks']:
        if task['id'] == waiting['id']:
            task.update(status='queued', starting=True, progress=0)
            task.pop('finished_at', None)
            task.pop('message', None)
    write_queue(workspace, state)
    shutil.rmtree(root / 'results/v2/local_app_jobs' / key_of(root, REQUESTS['done']))

    with serving(root, workspace) as (app, client):
        status = json_body(client.get('/api/community/status'))
        assert (status['recovery_blocked'], status['queued_tasks']) == (True, 1)
        # The service log says what waits, and how to release it.
        assert ('New computations wait for a worker start of an earlier run whose outcome is unknown. Once no worker '
                'of that run is computing, start again with --clear-interrupted.') in caplog.messages
        time.sleep(0.5)
        assert poll(client, waiting['id'], ('queued',))['status'] == 'queued'
        health = json_body(client.get('/api/local-compute/health'))
        assert health['active_job']['id'] == waiting['id']
    with serving(root, workspace, clear_interrupted=True) as (app, client):
        assert json_body(client.get('/api/community/status'))['recovery_blocked'] is False
        assert poll(client, waiting['id'])['status'] == 'completed'


# --- Requests --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('kind, limit', [('local-compute', 4096), ('source-reception', 4096),
                                         ('electrode-editor', 32768), ('design-evaluation', 65536)])
def test_bodies_are_limited_per_kind_as_received(site, kind, limit):
    """Node's limits, applied before the kind's adapter is asked (the kinds of later slices reach the queue's 404
    here only because the test wires them)."""
    root, workspace, _ = site
    with serving(root, workspace) as (app, client):
        app.compute.wired = lambda name: app.compute.queue
        path = f'/api/{kind}/lookup'
        fits = '{}' + ' ' * (limit - 2)
        answer = post(client, path, fits)
        assert answer.status_code in (400, 404) and json_body(answer)['error'] != '配置过大'
        assert error(post(client, path, fits + ' ')) == (413, '配置过大', 'request_too_large')
        assert error(post(client, f'/api/{kind}/jobs', fits + ' ')) == (413, '配置过大', 'request_too_large')


def test_bodies_must_be_json_and_follow_the_request_format(site):
    root, workspace, _ = site
    padded = jsjson.stringify(REQUESTS['none'])
    padded += ' ' * (4096 - len(padded))
    with serving(root, workspace) as (app, client):
        assert error(post(client, LOOKUP, '{}', **{'content-type': 'text/plain'})) == (
            415, 'JSON required', 'unsupported_media_type')
        assert error(post(client, LOOKUP, '{"region_count":')) == (400, '请求内容不是有效的JSON', 'invalid_request')
        assert error(post(client, LOOKUP, '{"region_count":1,"region_count":2}'))[0] == 400
        assert error(post(client, JOBS, {**REQUESTS['none'], 'AR': 0.9}))[0] == 400
        assert error(post(client, JOBS, [1]))[0] == 400
        # Exactly the limit is accepted.
        assert post(client, LOOKUP, padded).status_code == 200
    assert not (root / LOCK).exists() and jobs_tree(root) == {}


def test_writes_need_the_csrf_token(site):
    root, workspace, _ = site
    with serving(root, workspace, csrf=False) as (app, client):
        for path in (LOOKUP, JOBS, f'{JOBS}/{UNKNOWN_ID}/cancel'):
            assert error(post(client, path, REQUESTS['none'])) == (403, CSRF_REFUSAL, 'request_forbidden')
        assert error(post(client, JOBS, REQUESTS['none'], **{'x-eeg-compute-token': 'f' * 64}))[0] == 403
        assert client.get('/api/community/status').status_code == 200
        assert error(client.get(f'{JOBS}/{UNKNOWN_ID}')) == (404, NOT_FOUND, 'not_found')
    assert queue_file(workspace)['tasks'] == []


def test_unknown_receipts_queries_and_unwired_kinds(site):
    root, workspace, _ = site
    with serving(root, workspace) as (app, client):
        id = json_body(post(client, JOBS, REQUESTS['none']))['job']['id']
        poll(client, id)
        assert error(client.get(f'{JOBS}/{UNKNOWN_ID}')) == (404, NOT_FOUND, 'not_found')
        assert error(client.post(f'{JOBS}/{UNKNOWN_ID}/cancel')) == (404, NOT_FOUND, 'not_found')
        assert error(client.get(f'{JOBS}/{id}?other=1')) == (400, 'Unsupported task query.', 'invalid_request')
        assert error(client.get(f'{JOBS}/{id}?annotation_id=a&annotation_id=b'))[1] == 'Unsupported task query.'
        assert error(client.get(f'{JOBS}/{id}?annotation_id=ABC'))[1] == 'Invalid electrode name annotation.'
        assert error(client.get(f'{JOBS}/{id}?annotation_id=' + 'a' * 64)) == (
            404, 'Electrode name annotation not found.', 'not_found')
        assert client.get(f'{JOBS}/{id}?annotation_id=').status_code == 400
        # The route pattern: ids of 36 hex digits and hyphens; anything else is the prefix's 404.
        assert error(client.get(f'{JOBS}/not-an-id'))[1:] == ('未知计算接口', 'not_found')
        assert error(client.get(JOBS))[1] == 'Unknown queue endpoint'
        assert error(client.post(f'{JOBS}/{id}'))[1] == 'Unknown queue endpoint'
        # Kinds without an adapter (slices 6 and 7) are unknown endpoints before any body is read.
        for kind in ('electrode-editor', 'source-reception'):
            assert error(post(client, f'/api/{kind}/jobs', 'x' * 100000)) == (404, 'Unknown queue endpoint', 'not_found')
            assert error(client.get(f'/api/{kind}/jobs/{id}'))[1] == 'Unknown queue endpoint'
        # The coordinate evaluation reads its body (65,536 bytes at most) and sees only its own receipts.
        assert error(post(client, '/api/design-evaluation/jobs', 'x' * 100000)) == (
            413, '配置过大', 'request_too_large')
        assert error(client.get(f'/api/design-evaluation/jobs/{id}')) == (404, NOT_FOUND, 'not_found')
        assert error(post(client, f'/api/design-evaluation/jobs/{id}/cancel')) == (404, NOT_FOUND, 'not_found')
        assert error(client.get('/api/community/heartbeat'))[1] == 'Unknown community endpoint'
        assert error(post(client, '/api/community/heartbeat', {}))[1] == 'Unknown community endpoint'


def test_a_corrupt_queue_file_stops_the_start_and_is_kept(site):
    root, workspace, _ = site
    (workspace / '.eeglayoutlab').mkdir()
    (workspace / '.eeglayoutlab/queue.json').write_bytes(b'{broken')
    with pytest.raises(Exception):
        with serving(root, workspace):
            pass
    assert (workspace / '.eeglayoutlab/queue.json').read_bytes() == b'{broken'


def test_the_worker_script_is_the_fake(site):
    """The fixture's own check: the root's worker is the fake, so nothing scientific runs."""
    root, *_ = site
    assert 'fake-radius-plan.json' in (root / WORKER_SCRIPT).read_text(encoding='utf-8')


# --- Parity with Node's composed service ----------------------------------------------------------------------------

@needs_node
def test_the_routes_answer_and_write_as_node_does(tmp_path):
    """The steps of compute_support.STEPS against Node's ``createLocalComputeService`` and the Python application on
    the same root (built again at the same path for Python), with the same fake worker and interpreter."""
    root = tmp_path / 'root'
    compute_root(root)
    scratch = tmp_path / 'node'
    scratch.mkdir()
    theirs = run_node(root, scratch)
    node_tree = jobs_tree(root)
    # Three files for each stored result (done, none), two for each other run (crash, stale, hold).
    assert len(node_tree) == 12, sorted(node_tree)
    root.rename(tmp_path / 'root.node')
    compute_root(root)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    ours = run_python(root, workspace)
    expected, actual = masked(theirs['answers'], theirs['token']), masked(ours['answers'], ours['token'])
    for step, (node, python) in enumerate(zip(expected, actual)):
        assert python == node, f'step {step}: {python} != {node}'
    assert len(actual) == len(expected)
    assert masked_tree(ours['tree']) == masked_tree(node_tree)


# A root whose results are kept elsewhere through a link: neither host computes there.
LINKED_STEPS = [
    {'method': 'POST', 'path': '/api/local-compute/lookup', 'body': REQUESTS['done']},
    {'method': 'POST', 'path': '/api/local-compute/jobs', 'body': REQUESTS['done']},
    {'method': 'GET', 'path': '/api/local-compute/jobs/{0}', 'until': TERMINAL},
    {'method': 'GET', 'path': '/api/community/status'},
]


@needs_node
def test_a_results_tree_linked_out_of_the_root_fails_the_task_as_node_does(tmp_path):
    """``R/results`` a link to a directory outside the root: Node's run path refuses at ``createBatch`` with
    ``Record directory leaves the repository.``, which the receipt keeps; the Python service's installation lock
    meets that directory first and gives the same refusal, so the view and the status are Node's within one run
    (after a restart they differ: Python's receipt has no spawn intent, test_queue). Nothing is written through the
    link."""
    root = tmp_path / 'root'
    compute_root(root)
    outside = tmp_path / 'outside'
    (root / 'results').rename(outside)
    (root / 'results').symlink_to(outside, target_is_directory=True)
    before = sorted(str(path.relative_to(outside)) for path in outside.rglob('*'))
    scratch = tmp_path / 'node'
    scratch.mkdir()
    theirs = run_node(root, scratch, LINKED_STEPS)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    ours = run_python(root, workspace, LINKED_STEPS)
    expected, actual = masked(theirs['answers'], theirs['token']), masked(ours['answers'], ours['token'])
    assert actual == expected
    job = jsjson.parse(actual[2]['body'])['job']
    assert (job['status'], job['message']) == ('failed', 'Record directory leaves the repository.')
    assert sorted(str(path.relative_to(outside)) for path in outside.rglob('*')) == before


def respelled_root(root: Path) -> None:
    """``compute_root(root)`` with ``R/results`` moved to ``R/store/results`` and linked there by an absolute path
    that spells the root in upper case; skips on a volume that does not ignore case."""
    compute_root(root)
    spelled = root.with_name(root.name.upper()) / 'store/results'
    (root / 'store').mkdir()
    (root / 'results').rename(root / 'store/results')
    if not spelled.exists():
        pytest.skip('the volume distinguishes case')
    (root / 'results').symlink_to(spelled, target_is_directory=True)


@needs_node
def test_a_results_link_that_spells_the_root_another_way_computes_as_node_does(tmp_path):
    """On a volume that ignores case (macOS), ``createBatch`` resolves each directory with ``realpath(3)``, which
    returns the on-disk spelling, so Node computes on a root whose ``results`` link spells the root in another case
    and stores the result; the installation lock resolves the directories the same way, so the answers, the status
    and the record tree are Node's."""
    root = tmp_path / 'root'
    respelled_root(root)
    scratch = tmp_path / 'node'
    scratch.mkdir()
    theirs = run_node(root, scratch, LINKED_STEPS)
    node_tree = jobs_tree(root)
    assert len(node_tree) == 3, sorted(node_tree)
    shutil.rmtree(root)
    respelled_root(root)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    ours = run_python(root, workspace, LINKED_STEPS)
    expected, actual = masked(theirs['answers'], theirs['token']), masked(ours['answers'], ours['token'])
    assert actual == expected
    assert jsjson.parse(actual[2]['body'])['job']['status'] == 'completed'
    assert masked_tree(ours['tree']) == masked_tree(node_tree)


# --- The coordinate evaluation ----------------------------------------------------------------------------------------

DESIGN_JOBS_PATH = '/api/design-evaluation/jobs'
DESIGN_LOOKUP = '/api/design-evaluation/lookup'


@pytest.fixture
def design_site(tmp_path):
    """A design root (``design_compute_root``: the stand-in worker, a stored evaluation, the library inputs) and a
    workspace."""
    root = design_compute_root(tmp_path / 'design')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    return root, workspace


def submit_design(client: Any, body: Any) -> dict:
    answer = post(client, DESIGN_JOBS_PATH, body)
    assert answer.status_code == 202, answer.text
    return json_body(answer)


def test_an_evaluation_runs_and_its_names_are_an_annotation_of_the_workspace(design_site):
    """check-design-evaluation-live.mjs's flow on the stand-in worker: submitted with names and source metadata, the
    evaluation runs to its stored record; the names are an annotation under W (never under R) referenced by the
    receipt, and the job view, the library record and its bundle show it for ``?annotation_id``
    (check-electrode-annotations.mjs:147, HTTP half). An annotation Node wrote under R is read by the library too,
    but a receipt shows only the variants it references."""
    from .library_support import annotation, write_annotation

    root, workspace = design_site
    key = design_key(root, DESIGN_REQUESTS['done'])
    with serving(root, workspace) as (app, client):
        job = submit_design(client, envelope(DESIGN_REQUESTS['done'], 'A', SOURCE))['job']
        assert (job['status'], job['message'], job['key']) == ('queued', '已加入计算队列', key)
        id, own = job['id'], job['annotation_id']
        assert job['electrode_annotation']['electrode_names'] == names('A')
        done = poll(client, id, kind='design-evaluation')
        assert (done['status'], done['message'], done['progress']) == ('completed', '设计评价已完成并保存', 1)
        assert 'annotation_id' not in done
        [task] = queue_file(workspace)['tasks']
        assert (task['kind'], task['annotation_refs']) == ('design-evaluation', [own])
        stored = annotation_tree(workspace / WORKSPACE_ANNOTATIONS)
        assert list(stored) == [f'{own}.json'] and stored[f'{own}.json'][1] == 0o600
        assert not (root / NODE_ANNOTATIONS).exists()
        record = jsjson.parse(stored[f'{own}.json'][0])
        assert (record['record_id'], record['electrode_names'], record['source_metadata']) == (key, names('A'), SOURCE)

        view = json_body(design_view(client, id, own))['job']
        assert (view['annotation_id'], view['electrode_annotation']['id']) == (own, own)
        assert error(design_view(client, id, 'b' * 64)) == (404, 'Electrode name annotation not found.', 'not_found')
        library = f'/api/local-compute/library/{key}'
        for path in (f'{library}?annotation_id={own}', f'{library}/bundle?annotation_id={own}'):
            answer = client.get(path)
            assert answer.status_code == 200, answer.text
            body = json_body(answer)
            shown = body['record'] if 'record' in body and 'schema' not in body else body
            assert shown['electrode_annotation']['electrode_names'] == names('A')
        assert error(client.get(f'{library}?annotation_id={own}&other=1')) == (
            400, 'Invalid electrode name annotation query.', 'invalid_request')

        theirs = annotation('browser-a', key)
        write_annotation(root / NODE_ANNOTATIONS, theirs)
        answer = client.get(f'{library}?annotation_id={theirs["id"]}')
        assert answer.status_code == 200, answer.text
        assert json_body(answer)['record']['electrode_annotation']['id'] == theirs['id']
        assert error(design_view(client, id, theirs['id']))[0] == 404
    assert (root / DESIGN_JOBS / key / 'cache.json').is_file()


def test_a_lookup_miss_writes_nothing_and_a_stored_evaluation_is_one_receipt(design_site):
    """A lookup never writes a record, an annotation or a receipt for a miss; the stored evaluation is a hit, the
    one cached receipt (Node's ``{hit: true, job}``) whether or not names come with it, and names given to it are
    kept as its annotation."""
    root, workspace = design_site
    before = snapshot(root)
    with serving(root, workspace) as (app, client):
        for body in (DESIGN_REQUESTS['done'], envelope(DESIGN_REQUESTS['done'], 'A')):
            assert json_body(post(client, DESIGN_LOOKUP, body)) == {'hit': False}
        assert queue_file(workspace)['tasks'] == []
        assert not (workspace / WORKSPACE_ANNOTATIONS).exists()
        assert json_body(client.get('/api/design-evaluation/health'))['active_job'] is None

        plain = submit_design(client, DESIGN_REQUESTS['cached'])
        assert plain['hit'] is True and 'annotation_id' not in plain['job']
        cached = plain['job']
        # Node's design lookup gives no finish time, so the receipt's is the time of the hit.
        assert (cached['status'], cached['message'], cached['cached']) == ('completed', '设计评价已完成', True)
        named = submit_design(client, envelope(DESIGN_REQUESTS['cached'], 'A'))
        assert named['hit'] is True and named['job']['id'] == cached['id']
        again = json_body(post(client, DESIGN_LOOKUP, envelope(DESIGN_REQUESTS['cached'], 'A')))
        assert again['job']['id'] == cached['id']
        assert again['job']['annotation_id'] == named['job']['annotation_id']
        [task] = queue_file(workspace)['tasks']
        assert (task['id'], task['cached'], task['annotation_refs']) == (
            cached['id'], True, [named['job']['annotation_id']])
    assert snapshot(root) == before
    assert not (root / LOCK).exists()


def test_identical_evaluations_join_and_a_cancelled_one_stores_nothing(design_site):
    """Identical submissions join one receipt while it runs (the health names it as the active job); its
    cancellation stops the worker (Node's ``计算已停止``) and writes no record, and the next task runs."""
    from eeglayoutlab.jobs.queue import group_alive

    root, workspace = design_site
    with serving(root, workspace) as (app, client):
        held = submit_design(client, envelope(DESIGN_REQUESTS['hold'], 'A'))['job']
        wait_for(lambda: poll(client, held['id'], ('running',), kind='design-evaluation')['progress'] == 0.25)
        joined = submit_design(client, envelope(DESIGN_REQUESTS['hold'], 'B'))
        assert joined['hit'] is True and joined['job']['id'] == held['id']
        assert json_body(client.get('/api/design-evaluation/health'))['active_job']['id'] == held['id']
        waiting = submit_design(client, DESIGN_REQUESTS['done'])['job']
        pid = app.compute.design.active_pid()
        assert pid and group_alive(pid)
        cancelled = json_body(post(client, f'{DESIGN_JOBS_PATH}/{held["id"]}/cancel'))['job']
        assert cancelled['status'] in ('cancelling', 'cancelled')
        stopped = poll(client, held['id'], ('cancelled',), kind='design-evaluation')
        assert stopped['message'] == '计算已停止'
        wait_for(lambda: not group_alive(pid))
        assert poll(client, waiting['id'], kind='design-evaluation')['status'] == 'completed'
        [task] = [task for task in queue_file(workspace)['tasks'] if task['id'] == held['id']]
        assert len(task['annotation_refs']) == 2
        assert json_body(design_view(client, held['id'], task['annotation_refs'][1]))['job']['status'] == 'cancelled'
    assert not (root / DESIGN_JOBS / design_key(root, DESIGN_REQUESTS['hold']) / 'cache.json').exists()


def test_a_restart_fails_the_interrupted_evaluation_and_keeps_its_annotations(design_site):
    """Closing the service stops the running worker; the next instance fails that receipt with the interrupted
    message, and its annotation views survive in the workspace."""
    from eeglayoutlab.jobs.queue import group_alive

    root, workspace = design_site
    with serving(root, workspace) as (app, client):
        held = submit_design(client, envelope(DESIGN_REQUESTS['hold'], 'A'))['job']
        wait_for(lambda: poll(client, held['id'], ('running',), kind='design-evaluation')['progress'] == 0.25)
        pid = app.compute.design.active_pid()
        assert pid and group_alive(pid)
    wait_for(lambda: not group_alive(pid))
    [task] = queue_file(workspace)['tasks']
    assert task['status'] == 'running' and task['annotation_refs'] == [held['annotation_id']]
    with serving(root, workspace) as (app, client):
        failed = poll(client, held['id'], kind='design-evaluation')
        assert (failed['status'], failed['message']) == ('failed', INTERRUPTED_MESSAGE)
        view = json_body(design_view(client, held['id'], held['annotation_id']))['job']
        assert view['electrode_annotation']['electrode_names'] == names('A')
        again = submit_design(client, envelope(DESIGN_REQUESTS['hold'], 'A'))['job']
        assert again['id'] != held['id'] and again['annotation_id'] == held['annotation_id']


def test_a_restart_promotes_an_interrupted_evaluation_whose_result_was_stored(design_site):
    """A receipt left running although its record was published (a crash after ``cache.json``, or a shutdown while
    the context was computed again) comes back completed and cached, with the finish time Node's reconciliation
    takes from ``cache.json`` (a hit's view has none); one whose result was never stored stays failed, and so does
    one whose record is a lookup hit but names another identity than its key's, which Node's reconciliation retains
    (``Cache request, identity or result checksum mismatch.``)."""
    from eeglayoutlab.jobs.design_result import normalize_design_request
    from eeglayoutlab.jobs.identity import design_context
    from eeglayoutlab.jobs.integrity import InputIntegrity

    from .design_support import run_result

    root, workspace = design_site
    (workspace / '.eeglayoutlab').mkdir(mode=0o700)
    held = normalize_design_request(DESIGN_REQUESTS['hold'])
    context = design_context(str(root), sys.executable, InputIntegrity(str(root)), held)
    result = run_result(held)
    write(root, f'{DESIGN_JOBS}/{context.key}/cache.json', {
        'key': context.key, 'identity': {**context.identity, 'threads': 2}, 'result': result,
        'result_sha256': jsjson.sha256_hex(result), 'finished_at': '2026-01-01T00:00:00.000Z'})

    def running(id: str, name: str, sequence: int) -> dict:
        return {'id': id, 'sequence': sequence, 'kind': 'design-evaluation',
                'key': design_key(root, DESIGN_REQUESTS[name]),
                'request': normalize_design_request(DESIGN_REQUESTS[name]), 'status': 'running',
                'created_at': '2026-11-23T08:00:00.000Z', 'progress': 0.75, 'cached': False, 'catalog': {},
                'backend_id': f'{sequence}' * 8 + '-0000-4000-8000-000000000000'}

    stored, lost = running('11111111-1111-4111-8111-111111111111', 'cached', 1), \
        running('33333333-3333-4333-8333-333333333333', 'done', 2)
    altered = running('22222222-2222-4222-8222-222222222222', 'hold', 3)
    write_queue(workspace, {'schema': 'eeglayoutlab-queue/1', 'sequence': 3, 'tasks': [stored, lost, altered]})
    with serving(root, workspace) as (app, client):
        promoted = poll(client, stored['id'], kind='design-evaluation')
        assert (promoted['status'], promoted['cached'], promoted['progress'], promoted['finished_at']) == (
            'completed', True, 1, '2026-01-01T00:00:00.000Z')
        assert promoted['result']['request'] == stored['request']
        assert json_body(post(client, DESIGN_LOOKUP, DESIGN_REQUESTS['hold']))['hit'] is True
        for task in (lost, altered):
            failed = poll(client, task['id'], kind='design-evaluation')
            assert (failed['status'], failed['message']) == ('failed', INTERRUPTED_MESSAGE)
    tasks = {task['id']: task for task in queue_file(workspace)['tasks']}
    assert 'backend_id' not in tasks[stored['id']] and tasks[stored['id']]['status'] == 'completed'


def test_the_health_of_a_receipt_whose_annotation_is_gone_answers_as_its_view(design_site):
    """Health views the active receipt with its last annotation; once that file is removed or fails its checks,
    health answers as Node's middleware does (404 or 409 with the annotation's message), not 500."""
    from eeglayoutlab.jobs.annotations import INTEGRITY, NOT_FOUND

    root, workspace = design_site
    with serving(root, workspace) as (app, client):
        held = submit_design(client, envelope(DESIGN_REQUESTS['hold'], 'A'))['job']
        wait_for(lambda: poll(client, held['id'], ('running',), kind='design-evaluation')['progress'] == 0.25)
        health = '/api/design-evaluation/health'
        assert json_body(client.get(health))['active_job']['annotation_id'] == held['annotation_id']
        path = workspace / WORKSPACE_ANNOTATIONS / f'{held["annotation_id"]}.json'
        data = path.read_bytes()
        path.unlink()
        assert error(client.get(health)) == (404, NOT_FOUND, 'not_found')
        assert error(client.get('/api/community/status')) == (404, NOT_FOUND, 'not_found')
        path.write_bytes(data.replace(b'"A-Channel05"', b'"Z-Channel05"'))
        path.chmod(0o600)
        assert error(client.get(health)) == (409, INTEGRITY, 'compute_busy')
        post(client, f'{DESIGN_JOBS_PATH}/{held["id"]}/cancel')
        poll(client, held['id'], ('cancelled',), kind='design-evaluation')


def test_stop_soon_and_cache_only_reach_the_coordinate_evaluation(design_site):
    """``ComputeHost.stop_soon`` stops a running evaluation's worker while the service answers, and nothing is
    stored for it; under ``--cache-only`` the stored evaluation is served and new work refused."""
    from eeglayoutlab.jobs.queue import group_alive

    root, workspace = design_site
    with serving(root, workspace) as (app, client):
        held = submit_design(client, DESIGN_REQUESTS['hold'])['job']
        wait_for(lambda: poll(client, held['id'], ('running',), kind='design-evaluation')['progress'] == 0.25)
        pid = app.compute.design.active_pid()
        assert pid and group_alive(pid)
        app.compute.stop_soon()
        wait_for(lambda: not group_alive(pid))
        assert json_body(client.get('/api/community/status'))['available'] is False
    assert not (root / DESIGN_JOBS / design_key(root, DESIGN_REQUESTS['hold']) / 'cache.json').exists()
    with serving(root, workspace, cache_only=True) as (app, client):
        assert submit_design(client, DESIGN_REQUESTS['cached'])['hit'] is True
        assert error(post(client, DESIGN_JOBS_PATH, DESIGN_REQUESTS['done'])) == (
            503, MAINTENANCE, 'service_unavailable')


def test_a_receipt_whose_identity_changed_after_close_is_not_served(design_site):
    """A stored evaluation's receipt is prepared again when the next instance views it: once a code input of the
    identity changed, the view asks for a new submission and the lookup misses."""
    from eeglayoutlab.jobs.queue import VIEW_KEY_CHANGED

    root, workspace = design_site
    with serving(root, workspace) as (app, client):
        done = submit_design(client, envelope(DESIGN_REQUESTS['done'], 'A'))['job']
        poll(client, done['id'], kind='design-evaluation')
    with open(root / CHANGED_INPUT, 'a', encoding='utf-8') as handle:
        handle.write('# changed after the run\n')
    with serving(root, workspace) as (app, client):
        view = json_body(client.get(f'{DESIGN_JOBS_PATH}/{done["id"]}'))['job']
        assert (view['status'], view['message'], view['result']) == ('failed', VIEW_KEY_CHANGED, None)
        assert json_body(post(client, DESIGN_LOOKUP, DESIGN_REQUESTS['done'])) == {'hit': False}


def test_a_receipt_takes_one_hundred_name_variants_over_http(design_site):
    """check-electrode-annotations.mjs:142-143 over HTTP: Node's bound of 100 variants per receipt, 413 with its
    message; a known variant is still reused."""
    from eeglayoutlab.jobs.queue import TASK_VARIANTS

    root, workspace = design_site
    with serving(root, workspace) as (app, client):
        first = submit_design(client, envelope(DESIGN_REQUESTS['done'], 'V0'))['job']
        # Settled first: while the receipt still runs, a submission that finds the record just written is a
        # receipt of its own, in Node as here (its status is the receipt's, not the job's).
        poll(client, first['id'], kind='design-evaluation')
        for index in range(1, 100):
            assert submit_design(client, envelope(DESIGN_REQUESTS['done'], f'V{index}'))['job']['id'] == first['id']
        assert error(post(client, DESIGN_JOBS_PATH, envelope(DESIGN_REQUESTS['done'], 'V100'))) == (
            413, TASK_VARIANTS, 'request_too_large')
        reused = submit_design(client, envelope(DESIGN_REQUESTS['done'], 'V7'))['job']
        assert reused['id'] == first['id']
    assert len(queue_file(workspace)['tasks'][0]['annotation_refs']) == 100


def test_design_writes_need_the_csrf_token_and_fit_the_kind_limit(design_site):
    """The design kind's writes carry the CSRF token, and its envelope may take 65,536 bytes, not one more; the
    multibyte names of a body that arrives one byte per chunk are kept intact."""
    root, workspace = design_site
    body = envelope(DESIGN_REQUESTS['done'], 'A')
    with serving(root, workspace, csrf=False) as (app, client):
        for path in (DESIGN_LOOKUP, DESIGN_JOBS_PATH, f'{DESIGN_JOBS_PATH}/{UNKNOWN_ID}/cancel'):
            assert error(post(client, path, body)) == (403, CSRF_REFUSAL, 'request_forbidden')
    assert queue_file(workspace)['tasks'] == []
    with serving(root, workspace) as (app, client):
        assert json_body(post(client, DESIGN_LOOKUP, padded(body, 65536))) == {'hit': False}
        assert error(post(client, DESIGN_LOOKUP, padded(body, 65537)))[0] == 413
        token = json_body(client.get('/api/design-evaluation/health'))['token']
        data = jsjson.stringify(envelope(DESIGN_REQUESTS['done'], 'B')).encode('utf-8')
        status, headers, text = chunked(app, client, 'POST', DESIGN_JOBS_PATH, data,
                                        {'content-type': 'application/json', 'x-eeg-compute-token': token})
        assert status == 202, text
        own = jsjson.parse(text)['job']['annotation_id']
        stored = annotation_tree(workspace / WORKSPACE_ANNOTATIONS)[f'{own}.json'][0]
        assert jsjson.parse(stored)['electrode_names'] == names('B')



@needs_node
def test_the_design_routes_answer_and_write_as_node_does(tmp_path):
    """compute_support.DESIGN_STEPS against Node's composed service and the Python application on the same design
    root (built again at the same path for Python), with the same stand-in worker: the answers, the design records and
    the annotation files. Node's session is the local owner, so its annotations have the Python service's ids and
    bytes; Node writes them under R, the Python service under W."""
    from eeglayoutlab.jobs.annotations import LOCAL_OWNER

    directory = tmp_path / 'design'
    root = design_compute_root(directory)
    scratch = tmp_path / 'node'
    scratch.mkdir()
    theirs = run_node(root, scratch, DESIGN_STEPS, owner=LOCAL_OWNER)
    node_tree = design_tree(root)
    node_annotations = annotation_tree(root / NODE_ANNOTATIONS)
    directory.rename(tmp_path / 'design.node')
    root = design_compute_root(directory)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    ours = run_python(root, workspace, DESIGN_STEPS)
    expected = masked(cache_digests(theirs['answers'], node_tree), theirs['token'])
    actual = masked(cache_digests(ours['answers'], ours['design_tree']), ours['token'])
    for step, (node, python) in enumerate(zip(expected, actual)):
        assert python == node, f'step {step}: {python} != {node}'
    assert len(actual) == len(expected)
    assert masked_tree(ours['design_tree']) == masked_tree(node_tree)
    assert ours['annotations'] == node_annotations and len(node_annotations) == 6
    assert not (root / NODE_ANNOTATIONS).exists()


NUL_STEPS = [
    {'method': 'POST', 'path': DESIGN_LOOKUP, 'body': DESIGN_REQUESTS['done']},
    {'method': 'POST', 'path': DESIGN_JOBS_PATH, 'body': envelope(DESIGN_REQUESTS['done'], 'A')},
    {'method': 'GET', 'path': '/api/community/status'},
]


@needs_node
def test_a_context_path_with_a_nul_byte_is_an_internal_fault_as_in_node(tmp_path):
    """A configured input path with a NUL byte: Node's ``ERR_INVALID_ARG_VALUE`` is a ``TypeError``, so
    ``publicFailure`` answers 500 with the generic message, not the error's text with the installation's path, and a
    receipt that meets it at dispatch shows the generic message (``publicMessage``). Nothing is written."""
    from eeglayoutlab.jobs import nodefs
    from eeglayoutlab.jobs.annotations import LOCAL_OWNER
    from eeglayoutlab.jobs.queue import INTERNAL_MESSAGE, public_message

    root = design_compute_root(tmp_path / 'design')
    config = root / 'configs/ernie_fem_point_pilot.json'
    config.write_text(config.read_text(encoding='utf-8').replace('"data/head.msh"', '"data/head.msh\\u0000"'),
                      encoding='utf-8')
    records = design_tree(root)
    scratch = tmp_path / 'node'
    scratch.mkdir()
    theirs = run_node(root, scratch, NUL_STEPS, owner=LOCAL_OWNER)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    ours = run_python(root, workspace, NUL_STEPS)
    actual = masked(ours['answers'], ours['token'])
    assert actual == masked(theirs['answers'], theirs['token'])
    internal = {'error': INTERNAL_MESSAGE, 'code': 'internal_error'}
    assert [(answer['status'], jsjson.parse(answer['body'])) for answer in actual[:2]] == [(500, internal)] * 2
    assert design_tree(root) == records and ours['annotations'] == {} and ours['queue']['tasks'] == []
    with pytest.raises(nodefs.InvalidArgValueError) as raised:
        nodefs.check_path(str(root / 'data/head.msh\0'))
    assert isinstance(raised.value, TypeError) and public_message(raised.value) == INTERNAL_MESSAGE
