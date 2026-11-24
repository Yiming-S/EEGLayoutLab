"""The durable workspace queue (``eeglayoutlab.jobs.queue``) and its job kinds (``eeglayoutlab.jobs.kinds``).

Ports, with the stub adapters of check-community-queue.mjs:11-38 (``queue_support.Stubs``): check-community-queue.mjs
(the scheduler; owners, visitors and networks are dropped, R1), the queue tests of check-abuse-limits.mjs,
check-queue-maintenance.mjs (the invariants that hold without operator maintenance, R6),
check-product-operations-integration.mjs:131 and check-cross-region-contract.mjs:124; the receipt rules of
check-reconciliation.mjs as the queue's startup recovery. Then what Python adds: crash consistency of
``queue.json``, a corrupt file kept as it is, the reboot and ``clear_interrupted`` rules for an unconfirmed spawn,
finalization from the completion callback, retention, the cache-only mode, and the local-compute adapter over the
radius service surface. Last, the views and status of scripted scenarios against Node's own ``CommunityQueue``
(``parity/queue_views.mjs``).
"""
from __future__ import annotations

import asyncio
import errno
import os
from pathlib import Path
import re
import stat
import time
from typing import Any, Callable, Optional
import uuid

import pytest

from eeglayoutlab.jobs import records
from eeglayoutlab.jobs.kinds import ServiceAdapter, call
from eeglayoutlab.jobs.queue import (
    DISPATCH_KEY_CHANGED, INTERRUPTED_MESSAGE, QUEUE_SCHEMA, RECEIPT_LIMITS, STATUSES, TASK_VARIANTS, QueueError,
    QueueStateError, WorkspaceQueue, boot_id, group_alive, iso, receipt_catalog, retain_receipts,
)
from eeglayoutlab.jobs.slot import ExecutionSlot, InstallationLock, execution_lock_path
from eeglayoutlab.schemas import jsjson

from .key_parity_support import needs_node, require
from .queue_support import Stubs, StubAdapter, comparable, node_scenarios, run_scenario, task_json

ROOT = Path(__file__).resolve().parents[2]
SETTLE = 20.0
KEY = 'v1-1'


def run(coroutine) -> Any:
    return asyncio.run(coroutine)


async def until(check: Callable[[], bool], limit: float = SETTLE) -> None:
    deadline = time.monotonic() + limit
    while not check():
        if time.monotonic() > deadline:
            pytest.fail('the queue did not settle')
        await asyncio.sleep(0.005)


def make(directory: Path, stubs: Optional[Stubs] = None, **options: Any) -> tuple[WorkspaceQueue, Stubs]:
    stubs = stubs or Stubs()
    return WorkspaceQueue(str(directory), stubs.adapters, **options), stubs


def held() -> tuple[asyncio.Event, asyncio.Event]:
    """(entered, release): an operation the test holds at an await, as Node's ``deferred()`` pairs."""
    return asyncio.Event(), asyncio.Event()


class SlotAdapter(StubAdapter):
    """check-queue-maintenance.mjs's adapter: ``start`` takes the execution permit and the finish releases it."""

    def __init__(self, stubs: Stubs, slot: ExecutionSlot):
        super().__init__(stubs, 'local-compute')
        self.slot = slot
        self.numbers: list = []
        self.releases: dict[str, Callable[[], None]] = {}

    async def start(self, prepared: dict) -> dict:
        request = prepared['request']
        release = self.slot.acquire(request['n'])
        if release is None:
            return {'busy': True, 'maintenance': self.slot.paused}
        self.numbers.append(request['n'])
        job = {'id': str(uuid.uuid4()), 'key': self.key(request['n']), 'request': request, 'status': 'running',
               'result': None}
        self.workers[job['id']] = job
        self.releases[job['id']] = release
        return {'job': job}

    def finish(self, status: Optional[str] = None, **members: Any) -> dict:
        job = self.running()
        release = self.releases.pop(job['id'])
        finished = super().finish(status, **members)
        release()
        return finished


def slot_fixture(directory: Path, slot: Optional[ExecutionSlot] = None, **options: Any):
    slot = slot or ExecutionSlot()
    stubs = Stubs(kinds=())
    adapter = SlotAdapter(stubs, slot)
    stubs.adapters['local-compute'] = adapter
    queue = WorkspaceQueue(str(directory), stubs.adapters, slot=slot, **options)
    return queue, adapter, slot


def state_file(directory: Path, tasks: list[dict], sequence: Optional[int] = None,
               boot: Optional[str] = None) -> Path:
    """``queue.json`` with ``tasks``; with ``boot``, as last written in that boot."""
    path = directory / 'queue.json'
    directory.mkdir(parents=True, exist_ok=True)
    state = {'schema': QUEUE_SCHEMA, 'sequence': len(tasks) if sequence is None else sequence, 'tasks': tasks}
    if boot is not None:
        state = {'schema': state['schema'], 'sequence': state['sequence'], 'boot_id': boot, 'tasks': tasks}
    path.write_text(jsjson.stringify(state), encoding='utf-8')
    return path


def receipt(n: int, status: str, kind: str = 'local-compute', **members: Any) -> dict:
    return {'id': str(uuid.uuid4()), 'sequence': n, 'kind': kind, 'key': f'v1-{n}', 'request': {'n': n},
            'status': status, 'created_at': '2026-11-20T00:00:00.000Z', 'progress': 0, 'cached': False,
            'catalog': {}, **members}


# --- check-community-queue.mjs ----------------------------------------------------------------------------------

def test_all_four_services_share_one_persistent_fifo_slot(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        for i, kind in enumerate(f.adapters):
            await q.submit(kind, {'n': i})
        assert f.starts == []
        assert len(task_json(tmp_path)['tasks']) == 4
        await q.tick()
        assert f.starts == ['local-compute:0']
        await q.tick()
        assert len(f.starts) == 1
        for kind in f.adapters:
            f.finish(kind)
            await q.tick()
        assert f.starts == ['local-compute:0', 'source-reception:1', 'design-evaluation:2', 'electrode-editor:3']
        assert (await q.stats())['running_tasks'] == 0
        q.dispose()
    run(main())


def test_exact_pending_keys_share_work_and_cancel_always_cancels(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        first = await q.submit('local-compute', {'n': 1})
        second = await q.submit('local-compute', {'n': 1})
        assert first['job']['id'] == second['job']['id'] and second['hit'] is True
        assert len(q.tasks) == 1
        # One local user: a cancel stops the shared task (the multi-owner subscription is dropped, R1).
        cancelled = await q.cancel(first['job']['id'], 'local-compute')
        assert cancelled['status'] == 'cancelled' and q.own(first['job']['id'])['status'] == 'cancelled'
        third = await q.submit('local-compute', {'n': 1})
        assert third['job']['id'] != first['job']['id']
        await q.tick()
        assert len(f.starts) == 1
        q.dispose()
    run(main())


def test_completed_cache_bypasses_a_busy_worker_and_repeated_lookup_reuses_a_receipt(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        f.adapters['source-reception'].caches['v1-2'] = {'key': 'v1-2', 'status': 'completed', 'result': {'cached': 1},
                                                         'cached': True}
        await q.submit('local-compute', {'n': 1})
        await q.tick()
        a = await q.submit('source-reception', {'n': 2}, True)
        b = await q.submit('source-reception', {'n': 2}, True)
        assert a['job']['id'] == b['job']['id'] and a['job']['result'] == {'cached': 1}
        assert len(f.starts) == 1
        q.dispose()
    run(main())


def test_queued_cancellation_advances_running_cancellation_waits_for_close(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        a = await q.submit('local-compute', {'n': 1})
        b = await q.submit('source-reception', {'n': 2})
        await q.cancel(a['job']['id'])
        await q.tick()
        assert f.starts == ['source-reception:2']
        await q.cancel(b['job']['id'])
        assert q.own(b['job']['id'])['status'] == 'cancelling'
        # A cancelling task is not shared: the same key queues anew.
        c = await q.submit('source-reception', {'n': 2})
        assert c['job']['id'] != b['job']['id']
        await q.tick()
        assert len(f.starts) == 1
        f.finish('source-reception')
        await q.tick()
        assert len(f.starts) == 2 and q.own(b['job']['id'])['status'] == 'cancelled'
        q.dispose()
    run(main())


def test_queued_receipt_survives_restart_and_changed_identity_fails_without_starting(tmp_path):
    async def main() -> None:
        q, _ = make(tmp_path)
        job = (await q.submit('electrode-editor', {'n': 1}))['job']
        q.dispose()
        g, h = make(tmp_path)
        assert g.own(job['id'])['status'] == 'queued'
        h.change()
        await g.tick()
        task = g.own(job['id'])
        assert task['status'] == 'failed' and task['message'] == '排队后模型或代码已更新，请重新提交'
        assert h.starts == []
        g.dispose()
    run(main())


def test_queued_receipt_executes_after_clean_restart_and_same_key_lookup_restores_it(tmp_path):
    async def main() -> None:
        q, _ = make(tmp_path)
        job = (await q.submit('design-evaluation', {'n': 4}))['job']
        q.dispose()
        g, h = make(tmp_path)
        found = await g.submit('design-evaluation', {'n': 4}, True)
        assert found['job']['id'] == job['id'] and found['job']['status'] == 'queued'
        await g.tick()
        assert h.starts == ['design-evaluation:4']
        g.dispose()
    run(main())


def test_worker_pid_blocks_consecutive_restarts_and_an_unconfirmed_spawn_fails_closed(tmp_path):
    async def main() -> None:
        q, _ = make(tmp_path)
        await q.submit('local-compute', {'n': 1})
        q.tasks[0].update(status='running', worker_pid=os.getpid())
        q.dispose()
        g, h = make(tmp_path)
        await g.tick()
        assert (await g.stats())['recovery_blocked'] is True
        g.dispose()
        k, s = make(tmp_path)
        await k.tick()
        stats = await k.stats()
        assert stats['recovery_blocked'] is True and stats['running_tasks'] == 1 and s.starts == []
        k.dispose()
        disk = task_json(tmp_path)
        assert disk['tasks'][0]['worker_pid'] == os.getpid()
        del disk['tasks'][0]['worker_pid']
        disk['tasks'][0]['starting'] = True
        (tmp_path / 'queue.json').write_text(jsjson.stringify(disk), encoding='utf-8')
        m, _ = make(tmp_path)
        assert (await m.stats())['recovery_blocked'] is True
        m.dispose()
    run(main())


def test_one_live_owner_prevents_a_second_service_and_invalid_queue_json_is_not_overwritten(tmp_path):
    from eeglayoutlab.server.workspace import Workspace, WorkspaceInUse

    workspace = Workspace.open(str(tmp_path / 'w'))
    try:
        with pytest.raises(WorkspaceInUse):
            Workspace.open(str(tmp_path / 'w'), wait=0)
        state = Path(workspace.state)
        q, _ = make(state)
        q.dispose()
        (state / 'queue.json').write_text('corrupt', encoding='utf-8')
        with pytest.raises(QueueStateError, match='kept unchanged'):
            make(state)
        assert (state / 'queue.json').read_text(encoding='utf-8') == 'corrupt'
    finally:
        workspace.close()


def test_the_global_queue_bound_invalid_inputs_and_unknown_receipts(tmp_path):
    async def main() -> None:
        q, _ = make(tmp_path, max_queued=4)
        for n in range(4):
            await q.submit('local-compute', {'n': n})
        with pytest.raises(QueueError) as refused:
            await q.submit('local-compute', {'n': 5})
        assert (refused.value.status, refused.value.message) == (429, '队列已满，请稍后提交；已有结果仍可读取')
        # A pending key still joins its task at the bound, and a lookup still answers.
        assert (await q.submit('local-compute', {'n': 1}))['hit'] is True
        assert await q.submit('local-compute', {'n': 6}, True) == {'hit': False}
        with pytest.raises(ValueError, match='invalid'):
            await q.submit('local-compute', {'n': 'bad'})
        with pytest.raises(QueueError) as unknown:
            q.own(str(uuid.uuid4()))
        assert (unknown.value.status, unknown.value.message) == (404, '任务不存在或不属于当前浏览器')
        with pytest.raises(QueueError) as other_kind:
            q.own(q.tasks[0]['id'], 'source-reception')
        assert other_kind.value.status == 404
        q.dispose()
    run(main())


def test_the_queue_bound_maps_to_nodes_http_code():
    require('fastapi')
    from eeglayoutlab.server.app import ERROR_CODES

    assert ERROR_CODES[429] == 'queue_limited' and ERROR_CODES[503] == 'service_unavailable'


def test_backend_key_mismatch_is_cancelled_and_never_presented_as_an_old_key_result(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        adapter = f.adapters['local-compute']
        start = adapter.start

        async def changed(prepared: dict) -> dict:
            out = await start(prepared)
            out['job']['key'] = 'changed'
            return out
        adapter.start = changed
        job = (await q.submit('local-compute', {'n': 1}))['job']
        await q.tick()
        task = q.own(job['id'])
        assert task['status'] == 'failed' and task['message'] == '排队后模型或代码已更新，请重新提交'
        assert next(iter(adapter.workers.values()))['status'] == 'cancelling'
        assert q.active_id is None and (await q.view(task))['result'] is None
        q.dispose()
    run(main())


def test_dispose_during_identity_preparation_cannot_enqueue_or_launch_a_late_task(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        entered, release = held()

        async def prepare(request: Any) -> dict:
            entered.set()
            await release.wait()
            return {'request': request, 'key': KEY}
        f.adapters['local-compute'].prepare = prepare
        request = asyncio.ensure_future(q.submit('local-compute', {'n': 1}))
        await entered.wait()
        q.dispose()
        release.set()
        with pytest.raises(QueueError) as refused:
            await request
        assert refused.value.status == 503 and refused.value.message == '计算队列不可用，请稍后重试'
        assert f.starts == [] and q.tasks == [] and task_json(tmp_path)['tasks'] == []
    run(main())


# --- check-abuse-limits.mjs -------------------------------------------------------------------------------------

def test_a_lookup_of_a_computed_result_keeps_the_computed_receipt_and_writes_nothing_new(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        adapter = f.adapters['local-compute']
        job = (await q.submit('local-compute', {'n': 1}))['job']
        await q.tick()
        backend = adapter.get(q.own(job['id'])['backend_id'])
        backend.update(status='completed', result={'ok': True})
        adapter.caches[KEY] = {**backend, 'cached': True, 'finished_at': '2026-11-20T00:00:00.000Z'}
        await q.tick()
        assert q.own(job['id'])['cached'] is False
        before = (tmp_path / 'queue.json').read_bytes()
        hit = await q.submit('local-compute', {'n': 1}, True)
        assert hit['hit'] is True and hit['job']['id'] == job['id']
        # The reply says it replayed the saved result; the receipt stays in the computed pool.
        assert hit['job']['cached'] is True and q.own(job['id'])['cached'] is False
        assert (tmp_path / 'queue.json').read_bytes() == before
        q.dispose()
    run(main())


def test_a_shutdown_during_a_launch_keeps_the_task_queued_instead_of_blocking_restart(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path, Stubs(kinds=('local-compute',)))
        entered, release = held()

        async def start(prepared: dict) -> dict:
            entered.set()
            await release.wait()
            raise RuntimeError('本地服务正在重启')
        f.adapters['local-compute'].start = start
        job = (await q.submit('local-compute', {'n': 1}))['job']
        dispatch = asyncio.ensure_future(q.tick())
        await entered.wait()
        q.stop_scheduling()
        q.dispose()
        release.set()
        await dispatch
        g, h = make(tmp_path, Stubs(kinds=('local-compute',)))
        task = g.own(job['id'])
        assert task['status'] == 'queued' and 'starting' not in task and 'backend_id' not in task
        assert (await g.stats())['recovery_blocked'] is False
        await g.tick()
        assert h.starts == ['local-compute:1']
        g.dispose()
    run(main())


@pytest.mark.skipif(os.geteuid() == 0, reason='root writes into a read-only directory')
def test_a_failed_queue_write_stops_new_work_until_the_disk_accepts_writes_again(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        tmp_path.chmod(0o500)
        try:
            with pytest.raises(PermissionError):
                await q.submit('local-compute', {'n': 1})
            assert q.failure
            assert not any(name.endswith('.tmp') for name in os.listdir(tmp_path))
            # The refused submission is taken back, so it never runs later.
            assert q.tasks == [] and q.sequence == 0
            with pytest.raises(QueueError) as refused:
                await q.submit('local-compute', {'n': 2})
            assert refused.value.status == 503
            await q.tick()
            assert q.failure and (await q.stats())['available'] is False
        finally:
            tmp_path.chmod(0o700)
        await q.tick()
        assert q.failure is None
        await q.submit('local-compute', {'n': 2})
        await q.tick()
        assert f.starts == ['local-compute:2']
        q.dispose()
    run(main())


# --- check-queue-maintenance.mjs (without operator maintenance, R6) ---------------------------------------------

def test_an_external_worker_acquiring_the_slot_during_dispatch_preparation_keeps_the_task_queued(tmp_path):
    async def main() -> None:
        q, adapter, slot = slot_fixture(tmp_path)
        entered, release = held()
        job = (await q.submit('local-compute', {'n': 1}))['job']
        original = adapter.prepare

        async def prepare(request: Any) -> dict:
            entered.set()
            await release.wait()
            return await original(request)
        adapter.prepare = prepare
        dispatch = asyncio.ensure_future(q.tick())
        await entered.wait()
        permit = slot.acquire('external service')
        release.set()
        await dispatch
        task = q.own(job['id'])
        assert task['status'] == 'queued' and 'starting' not in task and adapter.numbers == []
        permit()
        q.dispose()
    run(main())


def test_confirmed_busy_contention_clears_spawn_intent_and_preserves_fifo_through_restart(tmp_path):
    async def main() -> None:
        q, adapter, slot = slot_fixture(tmp_path)
        entered, release = held()
        first = (await q.submit('local-compute', {'n': 1}))['job']
        second = (await q.submit('local-compute', {'n': 2}))['job']

        async def start(prepared: dict) -> dict:
            entered.set()
            await release.wait()
            assert slot.busy
            return {'busy': True, 'maintenance': False}
        adapter.start = start
        dispatch = asyncio.ensure_future(q.tick())
        await entered.wait()
        assert q.own(first['id'])['starting'] is True and task_json(tmp_path)['tasks'][0]['starting'] is True
        permit = slot.acquire('competing direct submission')
        assert callable(permit)
        release.set()
        await dispatch
        task = q.own(first['id'])
        assert task['status'] == 'queued'
        assert not {'starting', 'worker_pid', 'backend_id'} & task.keys()
        assert (await q.view(task))['queue_position'] == 1
        permit()
        q.dispose()
        g, h, _ = slot_fixture(tmp_path)
        assert (await g.stats())['recovery_blocked'] is False
        assert [task['id'] for task in g.tasks] == [first['id'], second['id']]
        await g.tick()
        assert h.numbers == [1]
        h.finish()
        await g.tick()
        assert h.numbers == [1, 2]
        g.dispose()
    run(main())


def test_an_ambiguous_thrown_start_keeps_its_recovery_guard_through_restart(tmp_path):
    async def main() -> None:
        q, adapter, _ = slot_fixture(tmp_path)
        await q.submit('local-compute', {'n': 1})

        async def start(prepared: dict) -> dict:
            raise RuntimeError('Launch outcome unknown')
        adapter.start = start
        await q.tick()
        task = q.tasks[0]
        assert task['starting'] is True and task['status'] == 'failed'
        assert task['message'] == '服务器内部错误，已记录；请稍后重试'
        q.dispose()
        g, h, _ = slot_fixture(tmp_path)
        assert (await g.stats())['recovery_blocked'] is True
        assert g.maintenance_status() == {'maintenance': False, 'drained': False}
        await g.submit('local-compute', {'n': 2})
        await g.tick()
        assert h.numbers == []
        g.dispose()
    run(main())


def test_a_worker_launched_while_the_service_stops_stays_tracked(tmp_path):
    async def main() -> None:
        q, adapter, _ = slot_fixture(tmp_path)
        entered, release = held()
        job = (await q.submit('local-compute', {'n': 1}))['job']
        original = adapter.start
        adapter.pid = lambda: os.getpid()

        async def start(prepared: dict) -> dict:
            value = await original(prepared)
            entered.set()
            await release.wait()
            return value
        adapter.start = start
        dispatch = asyncio.ensure_future(q.tick())
        await entered.wait()
        q.stop_scheduling()
        release.set()
        await dispatch
        task = q.own(job['id'])
        assert task['status'] == 'running' and task['starting'] is False and task['worker_pid'] == os.getpid()
        saved = task_json(tmp_path)['tasks'][0]
        assert saved['backend_id'] == task['backend_id'] and saved['worker_pid'] == os.getpid()
        q.dispose()
        # The restart knows the launched worker: it is interrupted, and its live group blocks dispatch.
        g, _, _ = slot_fixture(tmp_path)
        assert g.own(job['id'])['message'] == INTERRUPTED_MESSAGE
        assert (await g.stats())['recovery_blocked'] is True
        g.dispose()
    run(main())


# --- check-product-operations-integration.mjs, check-cross-region-contract.mjs ----------------------------------

def test_shutdown_during_asynchronous_admission_cannot_persist_a_late_queued_task(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        entered, release = held()
        lookup = f.adapters['local-compute'].lookup

        async def held_lookup(prepared: dict) -> dict:
            entered.set()
            await release.wait()
            return await lookup(prepared)
        f.adapters['local-compute'].lookup = held_lookup
        submitting = asyncio.ensure_future(q.submit('local-compute', {'n': 1}))
        await entered.wait()
        q.dispose()
        stopped = (tmp_path / 'queue.json').read_bytes()
        release.set()
        with pytest.raises(QueueError) as refused:
            await submitting
        assert refused.value.status == 503
        assert q.tasks == [] and (tmp_path / 'queue.json').read_bytes() == stopped and f.starts == []
    run(main())


CROSS_REGIONS = ('frontal', 'central', 'parietal', 'occipital', 'temporal_left', 'temporal_right')


def test_a_source_adapter_deduplicates_permuted_selections_and_restores_a_pending_canonical_request(tmp_path):
    """The real adapter shape (``ServiceAdapter``) over check-cross-region-contract.mjs's stub service, with the
    cross-region canonical order of normalizeReceptionRequest (the full normalizer comes with slice 7)."""
    class Service:
        def __init__(self):
            self.jobs: dict = {}
            self.active = None
            self.submitting = False
            self.finish_callbacks: list = []

        @staticmethod
        async def context(request: dict) -> dict:
            return {'key': jsjson.sha256_hex(request)}

        @staticmethod
        async def lookup(request: dict, ctx: dict) -> dict:
            return {'hit': False}

        @staticmethod
        def submit(prepared: dict) -> dict:
            raise AssertionError('this test must not launch a worker')

        @staticmethod
        def view(job: Any) -> Any:
            return job

        @staticmethod
        def cancel(id: Any) -> None:
            pass

    def normalize(raw: dict) -> dict:
        return {**{key: value for key, value in raw.items() if key != 'brain_regions'},
                'brain_regions': [name for name in CROSS_REGIONS if name in raw['brain_regions']]}

    def cross(regions: list[str]) -> dict:
        return {'record_id': 'a' * 64, 'waveform': 'burst', 'artifact_scale': 1, 'seed': 2026, 'mode': 'cross_region',
                'brain_regions': regions}

    async def main() -> None:
        adapters = {'source-reception': ServiceAdapter(Service(), normalize, Service.context)}
        q = WorkspaceQueue(str(tmp_path), adapters)
        first = await q.submit('source-reception', cross(['occipital', 'frontal']))
        duplicate = await q.submit('source-reception', cross(['frontal', 'occipital']))
        assert first['job']['id'] == duplicate['job']['id']
        assert q.tasks[0]['request']['brain_regions'] == ['frontal', 'occipital']
        q.dispose()
        q = WorkspaceQueue(str(tmp_path), adapters)
        restored = await q.submit('source-reception', cross(['occipital', 'frontal']), True)
        assert restored['job']['id'] == first['job']['id'] and restored['job']['status'] == 'queued'
        q.dispose()
    run(main())


# --- check-reconciliation.mjs: startup recovery ------------------------------------------------------------------

def stored(stubs: Stubs, n: int, status: str = 'completed', kind: str = 'local-compute', **members: Any) -> None:
    key = f'v1-{n}'
    stubs.adapters[kind].caches[key] = {'key': key, 'status': status, 'result': {'status': status, 'n': n},
                                        'message': '已读取相同模型与配置的已有计算记录',
                                        'finished_at': '2026-11-14T12:00:00.000Z', 'cached': True, **members}


def test_only_running_and_exact_restart_interrupted_failed_receipts_are_recoverable(tmp_path):
    statuses = ['running', 'queued', 'cancelling', 'cancelled', 'completed', 'no_layout', 'failed', 'failed',
                'timeout']
    tasks = [receipt(n, status) for n, status in enumerate(statuses, 1)]
    tasks[7]['message'] = INTERRUPTED_MESSAGE
    tasks[6]['message'] = 'something else'
    state_file(tmp_path, tasks)

    async def main() -> None:
        stubs = Stubs()
        for n in range(1, len(statuses) + 1):
            stored(stubs, n)
        q, _ = make(tmp_path, stubs)
        promoted = await q.recover()
        assert promoted == [tasks[0]['id'], tasks[7]['id']]
        assert [task['status'] for task in q.tasks] == [
            'completed', 'queued', 'failed', 'cancelled', 'completed', 'no_layout', 'failed', 'completed', 'timeout']
        restored = q.tasks[0]
        assert restored['cached'] is True and restored['progress'] == 1
        assert restored['finished_at'] == '2026-11-14T12:00:00.000Z'
        assert restored['message'] == '已读取相同模型与配置的已有计算记录'
        assert q.tasks[2]['message'] == INTERRUPTED_MESSAGE and q.tasks[6]['message'] == 'something else'
        assert task_json(tmp_path)['tasks'][0]['status'] == 'completed'
        view = await q.view(restored)
        assert view['status'] == 'completed' and view['result'] == {'status': 'completed', 'n': 1}
        q.dispose()
    run(main())


def test_no_layout_is_valid_only_for_the_radius_search_and_cancellations_never_revive(tmp_path):
    tasks = [receipt(1, 'running'), receipt(2, 'running', 'source-reception'), receipt(3, 'cancelling'),
             receipt(4, 'cancelled')]
    state_file(tmp_path, tasks)

    async def main() -> None:
        stubs = Stubs()
        stored(stubs, 1, 'no_layout')
        stored(stubs, 2, 'no_layout', 'source-reception')
        stored(stubs, 3)
        stored(stubs, 4)
        q, _ = make(tmp_path, stubs)
        assert await q.recover() == [tasks[0]['id']]
        assert [task['status'] for task in q.tasks] == ['no_layout', 'failed', 'failed', 'cancelled']
        q.dispose()
    run(main())


def test_missing_invalid_stale_and_duplicate_observations_cannot_change_receipts(tmp_path):
    tasks = [receipt(n, 'running') for n in range(1, 9)]
    state_file(tmp_path, tasks)

    async def main() -> None:
        stubs = Stubs()
        adapter = stubs.adapters['local-compute']
        # 1: no stored result. 2: a record of another key. 3: a result that is not finished. 4: no valid date.
        stored(stubs, 2, key='v1-other')
        stored(stubs, 3, 'failed')
        stored(stubs, 4, finished_at='yesterday')
        for n in (5, 6, 7, 8):
            stored(stubs, n)
        prepare, lookup = adapter.prepare, adapter.lookup

        async def changed(raw: Any) -> dict:
            prepared = await prepare(raw)
            if raw['n'] == 5:  # the identity changed since the run
                return {**prepared, 'key': 'v2-5'}
            if raw['n'] == 6:  # the canonical request changed
                return {**prepared, 'request': {**raw, 'canonical': True}}
            return prepared

        async def unreadable(prepared: dict) -> dict:
            if prepared['key'] == 'v1-7':
                raise PermissionError(13, 'Permission denied')
            return await lookup(prepared)
        adapter.prepare, adapter.lookup = changed, unreadable
        q, _ = make(tmp_path, stubs)
        q.tasks[7]['worker_pid'] = os.getpid()  # 8: its worker may still run
        assert await q.recover() == []
        assert all(task['status'] == 'failed' and task['message'] == INTERRUPTED_MESSAGE for task in q.tasks)
        q.dispose()
        # Two receipts with one id cannot both be observed: the file is refused before any recovery.
        duplicate = state_file(tmp_path / 'duplicate', [tasks[0], {**receipt(2, 'failed'), 'id': tasks[0]['id']}])
        before = duplicate.read_bytes()
        with pytest.raises(QueueStateError, match='repeats the id'):
            make(tmp_path / 'duplicate')
        assert duplicate.read_bytes() == before
    run(main())


def test_a_radius_cache_without_identity_uses_the_key_definition_and_the_production_validator(tmp_path):
    require('pydantic')
    from eeglayoutlab.jobs.kinds import local_compute_adapter
    from eeglayoutlab.jobs.radius import RadiusCache
    from .library_support import radius_result, write_cache

    root = tmp_path / 'root'
    root.mkdir()
    from eeglayoutlab.schemas.radius_search import normalize_request

    request = normalize_request({'region_count': 2, 'radius_mm': 35, 'mode': 'preset', 'mask_codes': ['PL', 'PR']})
    service = RadiusSurface(RadiusCache(str(root), 'python3', get_identity=lambda: {'scripts/x.py': 'a' * 64}))
    key = service.cache.identity_for(request)[1]
    result = radius_result(request)
    # Radius records never stored their identity: the key is re-derived and the result validated in full.
    path = write_cache(root, key, request, result, '2026-11-14T12:00:00.000Z')
    assert 'identity' not in jsjson.parse(path.read_text())
    tasks = [receipt(1, 'running', key=key, request=request), receipt(2, 'running', key=key, request=request)]
    state_file(tmp_path / 'w', tasks)

    async def main() -> None:
        adapters = {'local-compute': local_compute_adapter(service)}
        q = WorkspaceQueue(str(tmp_path / 'w'), adapters)
        before = path.read_bytes()
        assert await q.recover() == [tasks[0]['id'], tasks[1]['id']]
        assert q.tasks[0]['status'] == 'completed' and q.tasks[0]['finished_at'] == '2026-11-14T12:00:00.000Z'
        assert path.read_bytes() == before and service.lookups == 2
        q.dispose()
        # A record the production validator refuses (here: fewer than 64 points) is not a result.
        state_file(tmp_path / 'w', tasks)
        broken = {**result, 'layout': {**result['layout'], 'xyzMm': result['layout']['xyzMm'][:63]}}
        write_cache(root, key, request, broken, '2026-11-14T12:00:00.000Z')
        q = WorkspaceQueue(str(tmp_path / 'w'), adapters)
        assert await q.recover() == []
        assert q.tasks[0]['status'] == 'failed'
        q.dispose()
    run(main())


class RadiusSurface:
    """The radius job service surface the local-compute adapter uses (``jobs.radius.RadiusJobs``), over slice 3's
    ``RadiusCache``: lookups only."""

    def __init__(self, cache: Any):
        self.cache = cache
        self.jobs: dict[str, dict] = {}
        self.active = None
        self.submitting = False
        self.finish_callbacks: list = []
        self.lookups = 0
        self.submitted: list = []

    def identity_for(self, request: Any) -> tuple:
        return self.cache.identity_for(request)

    async def lookup(self, request: Any, ctx: dict) -> dict:
        self.lookups += 1
        stored = self.cache.read_cache(ctx['key'], request)
        if stored is None:
            return {'hit': False}
        job = {'id': str(uuid.uuid4()), 'key': ctx['key'], 'request': request, 'status': stored['result']['status'],
               'stage': 'cached', 'progress': 1, 'message': '已读取相同模型与配置的已有计算记录',
               'result': stored['result'], 'created_at': iso(0), 'finished_at': stored.get('finished_at'),
               'cached': True, 'source': 'local_cache'}
        self.jobs[job['id']] = job
        return {'hit': True, 'job': job}

    async def submit(self, prepared: Any) -> dict:
        self.submitted.append(prepared)
        job = {'id': str(uuid.uuid4()), 'key': prepared['key'], 'request': prepared['request'], 'status': 'running',
               'progress': 0, 'message': '正在加载本地头模与前向矩阵', 'result': None, 'worker': PidHolder(4242)}
        self.jobs[job['id']] = job
        self.active = job
        return {'job': self.view(job)}

    def view(self, job: dict) -> dict:
        return {name: value for name, value in job.items() if name != 'worker'}

    def cancel(self, id: Any, reason: str = 'user') -> bool:
        job = self.jobs.get(id)
        if job is None or job['status'] not in ('queued', 'running', 'cancelling'):
            return False
        job['status'] = 'cancelling'
        return True

    def end(self, status: str, message: str, result: Any = None) -> None:
        job, self.active = self.active, None
        job.update(status=status, message=message, result=result, progress=1)
        for callback in list(self.finish_callbacks):
            callback(job)


class PidHolder:
    def __init__(self, pid: int):
        self.pid = pid


# --- Python: crash consistency, corrupt files, boot time ---------------------------------------------------------

def test_queue_json_is_replaced_atomically_with_the_bytes_node_writes(tmp_path):
    async def main() -> None:
        q, _ = make(tmp_path, now=lambda: 1763856000000, boot_id=lambda: 'boot-1')
        path = tmp_path / 'queue.json'
        first = path.stat()
        await q.submit('local-compute', {'n': 1})
        second = path.stat()
        assert second.st_ino != first.st_ino  # a new file renamed into place, never rewritten in place
        assert stat.S_IMODE(second.st_mode) == 0o600 and stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
        expected = jsjson.stringify({'schema': QUEUE_SCHEMA, 'sequence': 1, 'boot_id': 'boot-1', 'tasks': q.tasks})
        assert path.read_bytes() == expected.encode('utf-8')
        assert sorted(os.listdir(tmp_path)) == ['queue.json']
        task = task_json(tmp_path)['tasks'][0]
        assert list(task) == ['id', 'sequence', 'kind', 'key', 'request', 'status', 'created_at', 'progress',
                              'cached', 'catalog']
        assert task['created_at'] == '2025-11-23T00:00:00.000Z'
        q.dispose()
    run(main())


def test_a_crash_before_the_rename_keeps_the_previous_file_and_a_torn_temporary_is_ignored(tmp_path, monkeypatch):
    async def main() -> None:
        q, _ = make(tmp_path)
        await q.submit('local-compute', {'n': 1})
        before = (tmp_path / 'queue.json').read_bytes()

        def crash(source: str, target: str) -> None:
            raise OSError(5, 'Input/output error')
        monkeypatch.setattr(records, '_rename', crash)
        with pytest.raises(OSError):
            await q.submit('local-compute', {'n': 2})
        monkeypatch.undo()
        assert (tmp_path / 'queue.json').read_bytes() == before
        assert os.listdir(tmp_path) == ['queue.json']
        q.dispose()
        # A crash between the temporary's write and the rename leaves a torn temporary next to the last file.
        torn = tmp_path / f'queue.json.{uuid.uuid4()}.tmp'
        torn.write_bytes(before[: len(before) // 2])
        g, _ = make(tmp_path)
        assert [task['request'] for task in g.tasks] == [{'n': 1}]
        assert not torn.exists()
        g.dispose()
    run(main())


@pytest.mark.parametrize('content, reason', [
    (b'corrupt', 'not valid JSON'),
    (b'\xff\xfe{}', 'not UTF-8'),
    (b'{"version":1,"sequence":0,"tasks":[]}', 'not an eeglayoutlab-queue/1 file'),
    (b'{"schema":"eeglayoutlab-queue/1","sequence":-1,"tasks":[]}', 'sequence is invalid'),
    (b'{"schema":"eeglayoutlab-queue/1","sequence":0,"tasks":{}}', 'tasks are not a list'),
    (b'{"schema":"eeglayoutlab-queue/1","sequence":0,"boot_id":7,"tasks":[]}', 'boot_id is invalid'),
    (b'{"schema":"eeglayoutlab-queue/1","sequence":0,"boot_id":"","tasks":[]}', 'boot_id is invalid'),
    (b'{"schema":"eeglayoutlab-queue/1","sequence":1,"tasks":[1]}', 'task 1 is not an object'),
    (b'{"schema":"eeglayoutlab-queue/1","sequence":1,"tasks":[{"id":"a","sequence":1,"kind":"local-compute",'
     b'"key":"k","request":{},"status":"lost","created_at":"x","progress":0,"cached":false,"catalog":{}}]}',
     'unknown status'),
    (b'{"schema":"eeglayoutlab-queue/1","sequence":1,"tasks":[{"id":"a","sequence":1,"kind":"local-compute",'
     b'"key":"k","request":{},"status":"queued","created_at":"x","progress":0,"cached":false,"catalog":{},'
     b'"worker_pid":"12"}]}', 'invalid worker_pid'),
    (b'{"schema":"eeglayoutlab-queue/1","sequence":0,"tasks":[{"id":"a","sequence":1,"kind":"local-compute",'
     b'"key":"k","request":{},"status":"queued","created_at":"x","progress":0,"cached":false,"catalog":{}}]}',
     'invalid sequence'),
])
def test_a_corrupt_queue_file_is_kept_byte_for_byte_and_startup_refuses(tmp_path, content, reason):
    (tmp_path / 'queue.json').write_bytes(content)
    with pytest.raises(QueueStateError) as refused:
        make(tmp_path)
    assert reason in str(refused.value) and str(tmp_path / 'queue.json') in str(refused.value)
    assert (tmp_path / 'queue.json').read_bytes() == content
    assert os.listdir(tmp_path) == ['queue.json']


def test_a_link_or_directory_in_place_of_queue_json_is_refused(tmp_path):
    (tmp_path / 'elsewhere.json').write_text('{}')
    (tmp_path / 'queue.json').symlink_to(tmp_path / 'elsewhere.json')
    with pytest.raises(QueueStateError):
        make(tmp_path)
    assert (tmp_path / 'queue.json').is_symlink()
    (tmp_path / 'queue.json').unlink()
    (tmp_path / 'queue.json').mkdir()
    with pytest.raises(QueueStateError, match='not a regular file'):
        make(tmp_path)


def test_a_failed_last_write_at_dispose_is_kept_for_the_service_to_report(tmp_path):
    """Node's ``dispose`` throws when its last ``persist`` fails, and its host exits 1; the queue keeps that error
    (``unsaved``) for the service, which reports it (``ComputeHost.close``, ``serve``'s exit status)."""
    q, _ = make(tmp_path)
    q.dispose()
    assert q.unsaved is None
    g, _ = make(tmp_path)

    def full() -> None:
        raise OSError(errno.ENOSPC, 'No space left on device')
    g._save = full
    g.dispose()
    assert isinstance(g.unsaved, OSError) and g.unsaved.errno == errno.ENOSPC and g.failure


def test_boot_id_is_the_kernels():
    booted = boot_id()
    if os.path.exists('/proc/sys/kernel/random/boot_id'):
        assert booted == Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    else:
        import subprocess
        text = subprocess.run(['sysctl', '-n', 'kern.bootsessionuuid'], capture_output=True, text=True, check=True)
        assert booted == text.stdout.strip()
    assert re.fullmatch('[0-9A-Fa-f-]{36}', booted) and boot_id() == booted


def unconfirmed_state(directory: Path, task: Optional[dict] = None, boot: Optional[str] = None) -> dict:
    """A queue file whose one receipt recorded a spawn intent but no worker (created a minute ago), last written in
    the boot ``boot``."""
    task = task or receipt(1, 'running', starting=True, created_at=iso(time.time() * 1000 - 60000))
    state_file(directory, [task], boot=boot)
    return task


def test_an_unconfirmed_spawn_is_resolved_by_a_reboot_after_its_intent(tmp_path):
    async def main() -> None:
        task = unconfirmed_state(tmp_path, boot='boot-1')
        # Written in this boot, or the boot of the write or of this start unknown: still blocked.
        for written, now in (('boot-1', 'boot-1'), (None, 'boot-1'), ('boot-1', None)):
            unconfirmed_state(tmp_path, task, written)
            q, f = make(tmp_path, boot_id=lambda now=now: now)
            assert q.unconfirmed and (await q.stats())['recovery_blocked'] is True
            await q.submit('local-compute', {'n': 2})
            await q.tick()
            assert f.starts == []
            q.dispose()
        assert task_json(tmp_path)['tasks'][0]['starting'] is True and 'boot_id' not in task_json(tmp_path)
        unconfirmed_state(tmp_path, task, 'boot-1')
        q, f = make(tmp_path, boot_id=lambda: 'boot-2')
        assert task_json(tmp_path)['boot_id'] == 'boot-2'
        assert not q.unconfirmed and (await q.stats())['recovery_blocked'] is False
        restored = q.own(task['id'])
        assert 'starting' not in restored and restored['status'] == 'failed'
        assert restored['message'] == INTERRUPTED_MESSAGE
        await q.submit('local-compute', {'n': 2})
        await q.tick()
        assert f.starts == ['local-compute:2']
        q.dispose()
    run(main())


def test_clear_interrupted_resolves_an_unconfirmed_spawn(tmp_path):
    async def main() -> None:
        task = unconfirmed_state(tmp_path)
        q, f = make(tmp_path, clear_interrupted=True)
        assert (await q.stats())['recovery_blocked'] is False and 'starting' not in q.own(task['id'])
        assert 'starting' not in task_json(tmp_path)['tasks'][0]
        q.dispose()
        unconfirmed_state(tmp_path)
        g, h = make(tmp_path)
        assert (await g.stats())['recovery_blocked'] is True
        assert g.clear_interrupted() == 1
        assert (await g.stats())['recovery_blocked'] is False
        await g.submit('local-compute', {'n': 2})
        await g.tick()
        assert h.starts == ['local-compute:2']
        g.dispose()
    run(main())


def test_a_worker_group_that_is_gone_unblocks_and_leaves_its_receipt(tmp_path):
    async def main() -> None:
        child = await asyncio.create_subprocess_exec('sleep', '60', start_new_session=True)
        try:
            state_file(tmp_path, [receipt(1, 'running', worker_pid=child.pid, backend_id=str(uuid.uuid4()))])
            q, f = make(tmp_path)
            assert q.blocked_pids == [child.pid] and (await q.stats())['recovery_blocked'] is True
            await q.submit('local-compute', {'n': 2})
            await q.tick()
            assert f.starts == []
        finally:
            child.kill()
            await child.wait()
        assert not group_alive(child.pid)
        await q.tick()
        assert f.starts == ['local-compute:2'] and 'worker_pid' not in q.tasks[0]
        assert 'worker_pid' not in task_json(tmp_path)['tasks'][0]
        q.dispose()
        # A dead pid is dropped at startup as well, so a reused pid cannot block a later restart.
        state_file(tmp_path, [receipt(1, 'failed', worker_pid=child.pid, message=INTERRUPTED_MESSAGE)])
        g, _ = make(tmp_path)
        assert g.blocked_pids == [] and 'worker_pid' not in task_json(tmp_path)['tasks'][0]
        g.dispose()
    run(main())


def test_group_alive_covers_descendants_of_a_dead_leader():
    import subprocess
    import sys

    script = ('import os, subprocess; p = subprocess.Popen(["sleep", "60"], stdin=subprocess.DEVNULL, '
              'stdout=subprocess.DEVNULL); print(p.pid, flush=True); os._exit(0)')
    leader = subprocess.Popen([sys.executable, '-c', script], start_new_session=True, stdout=subprocess.PIPE)
    try:
        descendant = int(leader.stdout.readline())
        leader.wait()
        leader.stdout.close()
        assert group_alive(leader.pid)  # the leader is gone, its group is not
    finally:
        try:
            os.killpg(leader.pid, 9)
        except ProcessLookupError:
            pass
    run(until(lambda: not group_alive(leader.pid)))
    with pytest.raises(ProcessLookupError):
        os.kill(descendant, 0)
    assert not group_alive(0) and not group_alive(-1) and not group_alive(True) and not group_alive('1')


# --- Python: completion callbacks, retention, cache-only, views ---------------------------------------------------

def test_finalization_runs_from_the_completion_callback_even_after_the_service_forgets_the_job(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path, retry_seconds=3600)
        adapter = f.adapters['local-compute']
        await q.start()
        first = (await q.submit('local-compute', {'n': 1}))['job']
        second = (await q.submit('local-compute', {'n': 2}))['job']
        await until(lambda: f.starts == ['local-compute:1'])
        assert q.own(first['id'])['status'] == 'running'
        job = adapter.finish('completed', message='计算完成', progress=1, result={'scientific': True})
        # Node's pitfall: the service's bounded map evicts the finished job before the next poll.
        adapter.workers.clear()
        await until(lambda: f.starts == ['local-compute:1', 'local-compute:2'])
        task = q.own(first['id'])
        assert (task['status'], task['message'], task['progress']) == ('completed', '计算完成', 1)
        assert job['id'] == task['backend_id'] and q.own(second['id'])['status'] == 'running'
        await q.close()
        assert q._dispatcher is None
    run(main())


def test_the_dispatcher_starts_queued_work_after_recovery_and_retries_a_held_permit(tmp_path):
    async def main() -> None:
        state_file(tmp_path, [receipt(1, 'queued')])
        q, adapter, slot = slot_fixture(tmp_path, retry_seconds=0.05)
        permit = slot.acquire('another holder')
        await q.start()
        await asyncio.sleep(0.2)
        assert adapter.numbers == []
        permit()
        await until(lambda: adapter.numbers == [1])
        adapter.finish()
        await until(lambda: q.tasks[0]['status'] == 'completed')
        await q.close()
    run(main())


def test_another_workspace_holding_the_installation_lock_keeps_the_task_queued_and_writes_nothing(tmp_path):
    """As Node's tick reads ``executionSlot.busy`` before it writes a spawn intent, a permit held by another
    workspace of the installation (its lock) gates dispatch before the task is prepared: the receipt stays queued,
    ``queue.json`` is never written, so no crash can leave an unconfirmed spawn, and the task runs once the lock is
    free."""
    async def main() -> None:
        root = tmp_path / 'root'
        root.mkdir()
        other = InstallationLock(str(root))  # another workspace of the installation, computing
        assert other.try_acquire()
        directory = tmp_path / 'workspace'
        q, adapter, slot = slot_fixture(directory, ExecutionSlot(InstallationLock(str(root))), retry_seconds=0.02)
        job = (await q.submit('local-compute', {'n': 1}))['job']
        prepared: list = []
        original = adapter.prepare

        async def prepare(raw: Any) -> dict:
            prepared.append(raw)
            return await original(raw)
        adapter.prepare = prepare
        path = directory / 'queue.json'
        before, inode = path.read_bytes(), path.stat().st_ino
        await q.start()
        try:
            deadline = time.monotonic() + 0.5  # 25 retry periods
            while time.monotonic() < deadline:
                assert path.stat().st_ino == inode and path.read_bytes() == before
                view = await q.view(q.own(job['id']))
                assert (view['status'], view['message'], view['queue_position']) == ('queued', '已加入计算队列', 1)
                assert (await q.stats())['running_tasks'] == 0 and q.active_id is None
                await asyncio.sleep(0.005)
            assert slot.contended and not slot.busy and prepared == [] and adapter.numbers == []
        finally:
            other.release()
        await until(lambda: adapter.numbers == [1])
        assert not slot.contended and slot.lock.held
        adapter.finish()
        await until(lambda: q.tasks[0]['status'] == 'completed')
        await q.close()
    run(main())


def test_an_installation_lock_that_cannot_be_used_fails_the_task_before_its_spawn_intent(tmp_path):
    async def main() -> None:
        root = tmp_path / 'root'
        Path(execution_lock_path(str(root))).mkdir(parents=True)  # a directory in place of the lock file
        directory = tmp_path / 'workspace'
        q, adapter, _ = slot_fixture(directory, ExecutionSlot(InstallationLock(str(root))))
        job = (await q.submit('local-compute', {'n': 1}))['job']
        assert await q.tick() is True
        task = q.own(job['id'])
        assert (task['status'], task['message']) == ('failed', '服务器内部错误，已记录；请稍后重试')
        assert 'starting' not in task and 'starting' not in task_json(directory)['tasks'][0]
        assert adapter.numbers == [] and q.active_id is None
        q.dispose()
        g, _, _ = slot_fixture(directory)
        assert (await g.stats())['recovery_blocked'] is False
        g.dispose()
    run(main())


def test_another_workspace_taking_the_installation_lock_while_a_task_is_prepared_keeps_it_queued(tmp_path):
    """The second probe, after ``prepare`` and before the spawn intent, as Node's tick reads its busy slot again: a
    lock that another workspace takes while the task's identity is prepared leaves the task queued and
    ``queue.json`` unwritten, so no crash in between can leave an unconfirmed spawn."""
    async def main() -> None:
        root = tmp_path / 'root'
        root.mkdir()
        directory = tmp_path / 'workspace'
        q, adapter, slot = slot_fixture(directory, ExecutionSlot(InstallationLock(str(root))))
        job = (await q.submit('local-compute', {'n': 1}))['job']
        entered, release = held()
        original = adapter.prepare

        async def prepare(raw: Any) -> dict:
            entered.set()
            await release.wait()
            return await original(raw)
        adapter.prepare = prepare
        path = directory / 'queue.json'
        before, inode = path.read_bytes(), path.stat().st_ino
        dispatch = asyncio.ensure_future(q.tick())
        await entered.wait()
        other = InstallationLock(str(root))  # another workspace of the installation starts computing
        assert other.try_acquire()
        try:
            release.set()
            assert await dispatch is False
            task = q.own(job['id'])
            assert task['status'] == 'queued' and 'starting' not in task and adapter.numbers == []
            assert path.stat().st_ino == inode and path.read_bytes() == before
            assert slot.contended and not slot.busy and q.active_id is None
        finally:
            other.release()
        assert await q.tick() is True and adapter.numbers == [1]
        adapter.finish()
        q.dispose()
    run(main())


def test_a_record_tree_out_of_the_root_fails_the_task_with_nodes_message_after_its_identity(tmp_path):
    """With ``R/results`` linked out of the root, Node's run path fails the task at ``createBatch`` with ``Record
    directory leaves the repository.``, a refusal the receipt shows (records.mjs:70), after the dispatch prepared the
    identity, so a key changed since the submit is reported first. The lock's directory check gives that message, in
    that order; nothing is created outside the root.

    The check comes before the spawn intent, where Node's comes inside ``adapter.start``, after it: Node's failed
    receipt keeps ``starting: true``, so after a restart Node reports ``recovery_blocked`` and dispatches nothing
    until the receipt is repaired. This receipt has no intent, so a restart dispatches, and each task fails again
    with the same message (a deliberate difference, design 0001 slice 4)."""
    async def main() -> None:
        root = tmp_path / 'root'
        root.mkdir()
        outside = tmp_path / 'outside'
        outside.mkdir()
        (root / 'results').symlink_to(outside, target_is_directory=True)
        directory = tmp_path / 'workspace'
        q, adapter, _ = slot_fixture(directory, ExecutionSlot(InstallationLock(str(root))))
        first = (await q.submit('local-compute', {'n': 1}))['job']
        assert await q.tick() is True
        task = q.own(first['id'])
        assert (task['status'], task['message']) == ('failed', 'Record directory leaves the repository.')
        second = (await q.submit('local-compute', {'n': 2}))['job']
        adapter.stubs.change()
        assert await q.tick() is True
        task = q.own(second['id'])
        assert (task['status'], task['message']) == ('failed', DISPATCH_KEY_CHANGED)
        assert all('starting' not in task for task in task_json(directory)['tasks']) and adapter.numbers == []
        assert list(outside.iterdir()) == []
        q.dispose()
        q, adapter, _ = slot_fixture(directory, ExecutionSlot(InstallationLock(str(root))))  # a restart
        assert (await q.stats())['recovery_blocked'] is False
        third = (await q.submit('local-compute', {'n': 3}))['job']
        assert await q.tick() is True
        task = q.own(third['id'])
        assert (task['status'], task['message']) == ('failed', 'Record directory leaves the repository.')
        assert adapter.numbers == [] and list(outside.iterdir()) == []
        q.dispose()
    run(main())


def test_a_worker_pid_from_before_a_reboot_is_dropped_and_clear_interrupted_forgets_a_live_one(tmp_path):
    """A pid recorded before the last boot belongs to no process of that run: a live process with the same pid is
    another one, so it neither blocks dispatch nor stays in the receipt. Without a reboot a live group blocks, as in
    Node, until it is gone or the person clears it (``--clear-interrupted``, or the method once started)."""
    async def main() -> None:
        child = await asyncio.create_subprocess_exec('sleep', '60', start_new_session=True)
        try:
            pid = child.pid
            task = receipt(1, 'running', worker_pid=pid, backend_id=str(uuid.uuid4()),
                           created_at=iso(time.time() * 1000 - 60000))
            state_file(tmp_path, [task], boot='boot-1')
            q, f = make(tmp_path, boot_id=lambda: 'boot-2')  # rebooted since the last write
            assert q.blocked_pids == [] and (await q.stats())['recovery_blocked'] is False
            restored = q.own(task['id'])
            assert 'worker_pid' not in restored and 'worker_pid' not in task_json(tmp_path)['tasks'][0]
            assert (restored['status'], restored['message']) == ('failed', INTERRUPTED_MESSAGE)
            await q.submit('local-compute', {'n': 2})
            await q.tick()
            assert f.starts == ['local-compute:2']
            q.dispose()
            for written, now in (('boot-1', 'boot-1'), (None, 'boot-1'), ('boot-1', None)):
                state_file(tmp_path, [task], boot=written)
                g, h = make(tmp_path, boot_id=lambda now=now: now)
                assert g.blocked_pids == [pid] and (await g.stats())['recovery_blocked'] is True
                g.dispose()
            state_file(tmp_path, [task])
            g, h = make(tmp_path, clear_interrupted=True)
            assert g.blocked_pids == [] and 'worker_pid' not in task_json(tmp_path)['tasks'][0]
            await g.submit('local-compute', {'n': 2})
            await g.tick()
            assert h.starts == ['local-compute:2']
            g.dispose()
            state_file(tmp_path, [task])
            k, s = make(tmp_path)
            assert k.blocked_pids == [pid] and (await k.stats())['recovery_blocked'] is True
            assert k.clear_interrupted() == 1
            assert k.blocked_pids == [] and (await k.stats())['recovery_blocked'] is False
            assert 'worker_pid' not in k.tasks[0] and 'worker_pid' not in task_json(tmp_path)['tasks'][0]
            await k.submit('local-compute', {'n': 2})
            await k.tick()
            assert s.starts == ['local-compute:2'] and group_alive(pid)
            k.dispose()
        finally:
            child.kill()
            await child.wait()
    run(main())


def test_a_clock_set_forward_is_not_taken_for_a_reboot(tmp_path):
    """Both kernels derive the boot time they report from the wall clock, so a clock set forward since the last write
    (NTP after a long pause, a restored virtual machine) moves it past that write without a reboot. The boot id does
    not move: a file last written in this boot, however long ago its times say, keeps a live worker group and an
    unconfirmed spawn blocking dispatch."""
    async def main() -> None:
        child = await asyncio.create_subprocess_exec('sleep', '60', start_new_session=True)
        try:
            long_ago = '2001-01-01T00:00:00.000Z'
            tasks = [receipt(1, 'running', worker_pid=child.pid, backend_id=str(uuid.uuid4()), created_at=long_ago),
                     receipt(2, 'running', starting=True, created_at=long_ago)]
            path = state_file(tmp_path, tasks, boot=boot_id())
            os.utime(path, (978307200, 978307200))
            q, f = make(tmp_path)
            assert q.blocked_pids == [child.pid] and q.unconfirmed
            assert (await q.stats())['recovery_blocked'] is True
            await q.submit('local-compute', {'n': 3})
            await q.tick()
            assert f.starts == []
            disk = task_json(tmp_path)['tasks']
            assert disk[0]['worker_pid'] == child.pid and disk[1]['starting'] is True
            q.dispose()
        finally:
            child.kill()
            await child.wait()
    run(main())


def test_a_hit_whose_stored_finished_at_is_not_a_string_keeps_it_and_the_queue_loads_again(tmp_path):
    """Node copies a hit's ``finished_at`` from the stored record unchecked (``ready.job.finished_at || now``), and
    never checks receipts when it loads. A record restored or written by hand with a number there gives the same
    receipt and reply, and the next start reads the file the queue wrote."""
    async def main() -> None:
        for n, finished in enumerate((1763856000000, {'t': 1}, True), 1):
            q, f = make(tmp_path)
            stored(f, n, finished_at=finished)
            hit = await q.submit('local-compute', {'n': n}, True)
            assert hit['hit'] is True and hit['job']['finished_at'] == finished
            assert task_json(tmp_path)['tasks'][-1]['finished_at'] == finished
            q.dispose()
            g, _ = make(tmp_path)
            assert g.tasks[-1]['finished_at'] == finished
            assert (await g.view(g.tasks[-1], False))['finished_at'] == finished
            g.dispose()
    run(main())


def test_retention_keeps_pending_and_guarded_tasks_and_the_newest_receipts_of_each_pool():
    assert RECEIPT_LIMITS == {'computed': 1000, 'cached': 300}
    limits = {'computed': 3, 'cached': 2}
    tasks = [receipt(n, 'completed', cached=n % 2 == 0) for n in range(1, 11)]
    tasks += [receipt(11, 'queued'), receipt(12, 'failed', worker_pid=os.getpid()), receipt(13, 'failed', starting=True),
              receipt(14, 'running')]
    kept = retain_receipts(tasks, limits)
    assert [task['sequence'] for task in kept] == [5, 7, 8, 9, 10, 11, 12, 13, 14]
    # JavaScript's slice(-0) keeps everything: a computed limit of 0 keeps every computed receipt.
    assert len(retain_receipts(tasks, {'computed': 0, 'cached': 0})) == 5 + 4


def test_retention_is_applied_on_every_write(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path, Stubs(kinds=('local-compute',)), receipt_limits={'computed': 2, 'cached': 1})
        ids = []
        for n in range(4):
            ids.append((await q.submit('local-compute', {'n': n}))['job']['id'])
            await q.tick()
            f.finish('local-compute')
            await q.tick()
        hit = (await q.submit('local-compute', {'n': 9}, True))
        assert hit == {'hit': False}
        f.adapters['local-compute'].caches['v1-9'] = {'key': 'v1-9', 'status': 'completed', 'result': {}}
        f.adapters['local-compute'].caches['v1-8'] = {'key': 'v1-8', 'status': 'completed', 'result': {}}
        nine = (await q.submit('local-compute', {'n': 9}, True))['job']['id']
        eight = (await q.submit('local-compute', {'n': 8}, True))['job']['id']
        assert [task['id'] for task in task_json(tmp_path)['tasks']] == [ids[2], ids[3], eight]
        with pytest.raises(QueueError):
            q.own(nine)
        q.dispose()
    run(main())


def test_cache_only_serves_hits_refuses_misses_and_reports_drained(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        job = (await q.submit('local-compute', {'n': 1}))['job']
        await q.tick()
        q.dispose()
        state = task_json(tmp_path)
        state['tasks'][0]['status'] = 'running'
        state['tasks'].append({**state['tasks'][0], 'id': str(uuid.uuid4()), 'sequence': 2, 'status': 'queued',
                               'key': 'v1-2', 'request': {'n': 2}})
        state['sequence'] = 2
        state.get('tasks')[0].pop('backend_id')
        (tmp_path / 'queue.json').write_text(jsjson.stringify(state))
        slot = ExecutionSlot()
        stubs = Stubs()
        stubs.adapters['local-compute'].caches['v1-3'] = {'key': 'v1-3', 'status': 'completed', 'result': {'r': 3}}
        g = WorkspaceQueue(str(tmp_path), stubs.adapters, slot=slot, cache_only=True)
        assert slot.paused and g.maintenance_status() == {'maintenance': True, 'drained': True}
        hit = await g.submit('local-compute', {'n': 3})
        assert hit['hit'] is True and hit['job']['result'] == {'r': 3}
        assert await g.submit('local-compute', {'n': 4}, True) == {'hit': False}
        with pytest.raises(QueueError) as refused:
            await g.submit('local-compute', {'n': 4})
        assert (refused.value.status, refused.value.message) == (503, '服务维护中，已有结果仍可读取；请稍后提交新计算')
        assert refused.value.admission_rejected
        await g.tick()
        assert stubs.starts == [] and g.own(state['tasks'][1]['id'])['status'] == 'queued'
        stats = await g.stats()
        assert stats['maintenance'] is True and stats['drained'] is True and 'online_visitors' not in stats
        assert g.own(job['id'])['status'] == 'failed'
        g.dispose()
        assert g.maintenance_status()['drained'] is False
    run(main())


def test_cache_only_is_not_drained_while_a_job_or_permit_is_active(tmp_path):
    async def main() -> None:
        q, adapter, slot = slot_fixture(tmp_path)
        await q.submit('local-compute', {'n': 1})
        await q.tick()
        q.cache_only = True
        assert q.maintenance_status() == {'maintenance': True, 'drained': False}
        adapter.finish()
        assert q.maintenance_status()['drained'] is False  # its receipt is not final yet
        await q.tick()
        assert q.maintenance_status()['drained'] is True
        permit = slot.acquire('direct')
        assert q.maintenance_status()['drained'] is False
        permit()
        q.dispose()
    run(main())


def test_views_use_exactly_the_eight_task_client_statuses():
    text = (ROOT / 'webapp/client/task-client.ts').read_text(encoding='utf-8')
    declared = re.search(r'const taskStatuses = \[([^\]]*)\]', text).group(1)
    assert tuple(re.findall(r"'([a-z_]+)'", declared)) == STATUSES


def test_stats_lists_the_last_twelve_receipts_newest_first_and_active_restores_a_pending_task(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        ids = [(await q.submit('local-compute', {'n': n}))['job']['id'] for n in range(14)]
        await q.tick()
        stats = await q.stats()
        assert list(stats) == ['queued_tasks', 'running_tasks', 'available', 'resource_blocked', 'recovery_blocked',
                               'maintenance', 'drained', 'jobs']
        assert [job['id'] for job in stats['jobs']] == ids[:1:-1][:12]
        assert stats['queued_tasks'] == 13 and stats['running_tasks'] == 1
        assert all('result' not in job for job in stats['jobs'])
        active = await q.active('local-compute')
        assert active['id'] == ids[0] and active['status'] == 'running' and 'result' not in active
        assert await q.active('source-reception') is None
        queued = await q.view(q.own(ids[3]))
        assert queued['queue_position'] == 3 and queued['message'] == '已加入计算队列' and queued['result'] is None
        q.dispose()
    run(main())


def test_a_finished_view_reads_the_stored_result_through_the_current_identity(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        job = (await q.submit('local-compute', {'n': 1}))['job']
        await q.tick()
        f.finish('local-compute')
        await q.tick()
        q.dispose()
        g, h = make(tmp_path)  # a new service: its job map is empty
        h.adapters['local-compute'].caches[KEY] = {'key': KEY, 'status': 'completed', 'result': {'scientific': True}}
        view = await g.view(g.own(job['id']))
        assert view['status'] == 'completed' and view['result'] == {'scientific': True}
        h.change()
        assert (await g.view(g.own(job['id'])))['message'] == '模型或代码已更新，请重新提交'
        h.revision = 'v1'
        h.adapters['local-compute'].caches.clear()
        missing = await g.view(g.own(job['id']))
        assert (missing['status'], missing['message'], missing['result']) == ('failed', '计算记录无法读取，请重新提交',
                                                                              None)
        assert (await g.view(g.own(job['id']), False))['status'] == 'completed'
        g.dispose()
    run(main())


def test_identity_and_study_admission_checks_refuse_with_409(tmp_path):
    async def main() -> None:
        q, _ = make(tmp_path)
        with pytest.raises(QueueError) as changed:
            await q.submit('local-compute', {'n': 1}, expected_key='v1-2')
        assert (changed.value.status, changed.value.message) == (
            409, 'Scientific identity changed before task acceptance.')
        with pytest.raises(QueueError) as study:
            await q.submit('local-compute', {'n': 1}, can_accept=lambda: False)
        assert study.value.status == 409 and study.value.study_admission_cancelled
        with pytest.raises(TypeError, match='Task admission guard must be a function.'):
            await q.submit('local-compute', {'n': 1}, can_accept=True)
        with pytest.raises(QueueError) as unknown:
            await q.submit('nonexistent', {'n': 1})
        assert unknown.value.status == 404
        assert q.tasks == []
        q.dispose()
    run(main())


class Annotations:
    """Electrode-name variants for the local user: one per name list."""

    def __init__(self):
        self.created: list[str] = []

    def identity(self, prepared: dict) -> dict:
        return {'id': jsjson.sha256_hex(prepared['electrode_names'])}

    def read(self, id: str, key: str) -> dict:
        return {'id': id, 'record_id': key}

    async def create(self, prepared: dict) -> dict:
        value = self.identity(prepared)
        self.created.append(value['id'])
        return value


def test_annotation_references_are_a_list_per_receipt(tmp_path):
    async def main() -> None:
        stubs = Stubs()
        adapter = stubs.adapters['design-evaluation']
        prepare = adapter.prepare

        async def with_names(raw: dict) -> dict:
            prepared = await prepare({'n': raw['n']})
            return {**prepared, 'electrode_names': raw.get('names')} if raw.get('names') else prepared
        adapter.prepare = with_names
        annotations = Annotations()
        q = WorkspaceQueue(str(tmp_path), stubs.adapters, annotations=annotations)
        first = await q.submit('design-evaluation', {'n': 1, 'names': ['a']})
        named = jsjson.sha256_hex(['a'])
        assert first['job']['annotation_id'] == named and first['job']['electrode_annotation']['record_id'] == 'v1-1'
        again = await q.submit('design-evaluation', {'n': 1, 'names': ['a']})
        other = await q.submit('design-evaluation', {'n': 1, 'names': ['b']})
        assert again['job']['id'] == other['job']['id'] == first['job']['id']
        assert annotations.created == [named, jsjson.sha256_hex(['b'])]
        task = q.own(first['job']['id'])
        assert task['annotation_refs'] == [named, jsjson.sha256_hex(['b'])]
        assert task_json(tmp_path)['tasks'][0]['annotation_refs'] == task['annotation_refs']
        stats = await q.stats()
        assert stats['jobs'][0]['annotation_id'] == jsjson.sha256_hex(['b'])
        with pytest.raises(QueueError) as missing:
            await q.view(task, True, 'f' * 64)
        assert (missing.value.status, missing.value.message) == (404, 'Electrode name annotation not found.')
        task['annotation_refs'] = [f'{n:064x}' for n in range(100)]  # Node's per-owner 20 is dropped (R1)
        with pytest.raises(QueueError) as limited:
            await q.submit('design-evaluation', {'n': 1, 'names': ['c']})
        assert (limited.value.status, limited.value.message) == (413, TASK_VARIANTS)
        no_store = WorkspaceQueue(str(tmp_path / 'other'), stubs.adapters)
        with pytest.raises(QueueError) as unavailable:
            await no_store.submit('design-evaluation', {'n': 2, 'names': ['a']})
        assert unavailable.value.status == 503
        q.dispose()
        no_store.dispose()
    run(main())


def test_submit_cancel_and_dispatch_are_serialized(tmp_path):
    async def main() -> None:
        q, f = make(tmp_path)
        adapter = f.adapters['local-compute']
        prepare = adapter.prepare
        inside = [0]
        peak = [0]

        async def slow(raw: Any) -> dict:
            inside[0] += 1
            peak[0] = max(peak[0], inside[0])
            await asyncio.sleep(0.01)
            inside[0] -= 1
            return await prepare(raw)
        adapter.prepare = slow
        results = await asyncio.gather(*(q.submit('local-compute', {'n': n % 3}) for n in range(9)),
                                       q.tick(), q.tick())
        assert peak[0] == 1
        assert len(q.tasks) == 3 and {result['job']['id'] for result in results[:9]} == {t['id'] for t in q.tasks}
        q.dispose()
    run(main())


def test_receipt_catalogs_follow_node():
    record = {'label': 'AL + AR', 'region_count': 2, 'mode': 'preset', 'request': {'mask_codes': ['AL', 'AR']},
              'layout': {'xyzMm': [[0, 0, 0]] * 64}}
    request = {'record_id': 'a' * 64, 'mode': 'multi_source'}
    result = {'schema_version': 'source-reception/2', 'layout': record['layout'],
              'conditions': [{'condition': 'mixed', 'field_retention': None, 'baseline': {'explained_energy': -1},
                              'candidate': {'explained_energy': -2}}], 'waveforms': {'brain_uv': ['large'] * 10}}
    catalog = receipt_catalog('source-reception', {'request': request, 'ctx': {'record': record}}, result)
    assert catalog == {'parent_label': 'AL + AR', 'region_count': 2, 'mask_codes': ['AL', 'AR'],
                       'location_mode': 'preset', 'electrode_count': 64, 'parent_id': 'a' * 64,
                       'protocol': 'source-reception/2',
                       'conditions': [{'condition': 'mixed', 'field_retention': None, 'baseline_explained_energy': -1,
                                       'candidate_explained_energy': -2}]}
    assert receipt_catalog('local-compute', {'request': {}, 'ctx': {'identity': {}, 'key': 'k'}}) == {}
    editor = {'parent_id': 'p', 'action': 'evaluate', 'slots': [{'enabled': True}, {'enabled': False}, {}]}
    assert receipt_catalog('electrode-editor', {'request': editor}) == {
        'parent_id': 'p', 'protocol': 'electrode-editor/1', 'electrode_count': 1}
    assert receipt_catalog('source-reception', {'request': {}}) == {'protocol': 'source-reception/1'}


# --- The local-compute adapter -----------------------------------------------------------------------------------

def test_the_local_compute_adapter_drives_the_radius_service_surface(tmp_path):
    require('pydantic')
    from eeglayoutlab.jobs.kinds import local_compute_adapter
    from eeglayoutlab.jobs.radius import RadiusCache

    root = tmp_path / 'root'
    root.mkdir()
    service = RadiusSurface(RadiusCache(str(root), 'python3', get_identity=lambda: {'scripts/x.py': 'b' * 64}))
    adapter = local_compute_adapter(service)
    raw = {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface', 'mask_codes': []}

    async def main() -> None:
        with pytest.raises(ValueError, match='区域数只支持1、2、3、4、6'):
            await adapter.prepare({**raw, 'region_count': 5})
        prepared = await adapter.prepare(raw)
        canonical = {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'}
        identity, key = service.cache.identity_for(canonical)
        assert prepared == {'request': canonical, 'key': key, 'ctx': {'identity': identity, 'key': key}}
        q = WorkspaceQueue(str(tmp_path / 'w'), {'local-compute': adapter}, retry_seconds=3600)
        await q.start()
        job = (await q.submit('local-compute', raw))['job']
        assert job['request'] == canonical and job['key'] == key and job['catalog'] == {}
        await until(lambda: q.own(job['id'])['status'] == 'running' and 'worker_pid' in q.own(job['id']))
        task = q.own(job['id'])
        assert task['worker_pid'] == 4242 and service.submitted[0]['key'] == key
        assert (await q.view(task))['message'] == '正在加载本地头模与前向矩阵'
        assert adapter.busy() and adapter.pid() == 4242
        await q.cancel(job['id'])
        assert service.jobs[task['backend_id']]['status'] == 'cancelling'
        service.end('cancelled', '任务已停止')
        await until(lambda: q.own(job['id'])['status'] == 'cancelled')
        assert q.own(job['id'])['message'] == '任务已停止' and 'worker_pid' not in q.own(job['id'])
        await q.close()
    run(main())


def test_the_adapter_runs_synchronous_identity_work_in_a_thread_one_at_a_time():
    import threading

    active = [0]
    peak = [0]
    threads = set()

    def identity(request: Any) -> tuple:
        threads.add(threading.get_ident())
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        active[0] -= 1
        return {'r': request}, f'key-{request}'

    async def main() -> None:
        loop_thread = threading.get_ident()
        values = await asyncio.gather(*(call(identity, n) for n in range(4)))
        assert [value[1] for value in values] == ['key-0', 'key-1', 'key-2', 'key-3']
        assert loop_thread not in threads and peak[0] == 1
    run(main())


def test_the_adapter_works_with_the_radius_job_service(tmp_path):
    """``jobs.radius.RadiusJobs`` (the run path) has the surface the adapter expects."""
    require('pydantic')
    from eeglayoutlab.jobs import radius
    from eeglayoutlab.jobs.kinds import local_compute_adapter
    from .library_support import radius_result, write_cache

    if not hasattr(radius, 'RadiusJobs'):
        pytest.skip('the radius run path is not there yet')
    root = tmp_path / 'root'
    root.mkdir()
    service = radius.RadiusJobs(str(root), 'python3', get_identity=lambda: {'scripts/x.py': 'c' * 64},
                                execution_slot=ExecutionSlot())
    adapter = local_compute_adapter(service)
    request = {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'}

    async def main() -> None:
        prepared = await adapter.prepare(request)
        assert prepared['key'] == service.identity_for(request)[1]
        assert await adapter.lookup(prepared) == {'hit': False}
        write_cache(root, prepared['key'], request, radius_result(request, status='no_layout'),
                    '2026-11-14T12:00:00.000Z')
        found = await adapter.lookup(prepared)
        assert found['hit'] is True and found['job']['status'] == 'no_layout'
        assert adapter.get(found['job']['id'])['id'] == found['job']['id']
        assert adapter.busy() is False and adapter.pid() is None and adapter.cancel('x') is False
        seen: list = []
        adapter.on_finish(lambda id, view: seen.append(id))
        assert len(service.finish_callbacks) == 1
        q = WorkspaceQueue(str(tmp_path / 'w'), {'local-compute': adapter})
        hit = await q.submit('local-compute', request, True)
        assert hit['hit'] is True and hit['job']['status'] == 'no_layout' and hit['job']['cached'] is True
        q.dispose()
    run(main())


# --- Parity with Node's CommunityQueue ----------------------------------------------------------------------------

CLOCK = 1763856000000
SCENARIOS = [
    {'id': 'fifo', 'clock': CLOCK, 'steps': [
        ['submit', 'local-compute', 0], ['submit', 'source-reception', 1], ['submit', 'design-evaluation', 2],
        ['submit', 'electrode-editor', 3], ['stats'], ['tick'], ['tick'], ['view', 0], ['view', 1],
        ['active', 'local-compute'], ['active', 'source-reception'],
        ['progress', 'local-compute', 0.25, 'optimize', '正在计算'], ['view', 0], ['view', 0, False],
        ['clock', CLOCK + 1500], ['finish', 'local-compute'], ['tick'], ['view', 0], ['own', 0], ['view', 1],
        ['finish', 'source-reception'], ['tick'], ['own', 1], ['view', 1], ['finish', 'design-evaluation'], ['tick'],
        ['finish', 'electrode-editor'], ['tick'], ['view', 3], ['own', 3], ['stats'], ['status']]},
    {'id': 'dedupe', 'clock': CLOCK, 'steps': [
        ['submit', 'local-compute', 1], ['submit', 'local-compute', 1], ['submit', 'local-compute', 1, True],
        ['submit', 'local-compute', 2], ['tick'], ['submit', 'local-compute', 1], ['submit', 'local-compute', 1, True],
        ['cancel', 0], ['submit', 'local-compute', 1], ['view', 0], ['tick'], ['finish', 'local-compute'], ['tick'],
        ['own', 0], ['view', 0], ['view', 1], ['stats']]},
    {'id': 'hit-receipt', 'clock': CLOCK, 'steps': [
        ['cache', 'source-reception', 2, 'completed', {'cached': 1}],
        ['cache', 'local-compute', 3, 'no_layout', {'layout': None}, '2026-11-01T08:00:00.000Z'],
        ['submit', 'local-compute', 1], ['tick'],
        ['submit', 'source-reception', 2, True], ['submit', 'source-reception', 2, True],
        ['submit', 'source-reception', 2], ['submit', 'local-compute', 3, True], ['submit', 'local-compute', 3],
        ['view', 1], ['view', 2], ['own', 1], ['own', 2], ['stats'], ['restart'], ['view', 1],
        ['restart', {'keep': True}], ['stats']]},
    {'id': 'failure', 'clock': CLOCK, 'steps': [
        ['submit', 'local-compute', 1], ['submit', 'local-compute', 2], ['tick'],
        ['fail', 'local-compute', '计算未成功完成；错误记录已保存，可重新计算'], ['tick'], ['own', 0], ['view', 0],
        ['view', 1], ['submit', 'local-compute', 1], ['submit', 'local-compute', {'n': 'bad'}],
        ['submit', 'local-compute', [1]], ['cancel', 0], ['cancel', 1], ['finish', 'local-compute'], ['tick'],
        ['own', 1], ['view', 1], ['cancel', 1], ['stats']]},
    {'id': 'restart', 'clock': CLOCK, 'steps': [
        ['submit', 'local-compute', 1], ['submit', 'design-evaluation', 2], ['submit', 'local-compute', 3],
        ['tick'], ['progress', 'local-compute', 0.5, 'metrics', '正在计算'], ['clock', CLOCK + 60000], ['restart'],
        ['own', 0], ['view', 0], ['view', 1], ['stats'], ['tick'], ['view', 1], ['restart', {'keep': True}],
        ['view', 1], ['own', 1], ['change'], ['finish', 'design-evaluation'], ['tick'], ['own', 1], ['view', 1],
        ['view', 2], ['own', 2], ['stats']]},
    {'id': 'identity', 'clock': CLOCK, 'steps': [
        ['submit', 'electrode-editor', 1], ['submit', 'local-compute', 2], ['restart'], ['change'], ['tick'],
        ['own', 0], ['view', 0], ['tick'], ['own', 1], ['submit', 'local-compute', 2, True],
        ['submit', 'local-compute', 2], ['stats']]},
    {'id': 'retention', 'clock': CLOCK, 'options': {'receiptLimits': {'computed': 2, 'cached': 1}}, 'steps': [
        ['submit', 'local-compute', 1], ['tick'], ['finish', 'local-compute'], ['tick'],
        ['submit', 'local-compute', 2], ['tick'], ['finish', 'local-compute'], ['tick'],
        ['submit', 'local-compute', 3], ['tick'], ['finish', 'local-compute'], ['tick'],
        ['cache', 'local-compute', 7, 'completed', {'seven': True}],
        ['cache', 'local-compute', 8, 'completed', {'eight': True}],
        ['submit', 'local-compute', 7, True], ['submit', 'local-compute', 8, True], ['submit', 'local-compute', 4],
        ['own', 0], ['own', 1], ['own', 2], ['own', 3], ['own', 4], ['own', 5], ['stats']]},
    {'id': 'bound', 'clock': CLOCK, 'options': {'maxQueued': 2}, 'steps': [
        ['submit', 'local-compute', 1], ['submit', 'local-compute', 2], ['submit', 'local-compute', 3],
        ['submit', 'local-compute', 2], ['submit', 'local-compute', 3, True], ['tick'], ['submit', 'local-compute', 3],
        ['cancel', 1], ['submit', 'local-compute', 3], ['stats']]},
    {'id': 'cache-only', 'clock': CLOCK, 'steps': [
        ['submit', 'local-compute', 1], ['submit', 'local-compute', 2], ['tick'],
        ['cache', 'local-compute', 5, 'completed', {'five': True}],
        ['restart', {'keep': True, 'cacheOnly': True}], ['status'], ['stats'],
        ['submit', 'local-compute', 5], ['submit', 'local-compute', 6, True], ['submit', 'local-compute', 6],
        ['submit', 'local-compute', 2], ['tick'], ['view', 1], ['finish', 'local-compute'], ['tick'], ['status'],
        ['own', 0], ['restart', {'keep': True}], ['status'], ['tick'], ['stats']]},
]


@needs_node
def test_views_and_status_equal_nodes_community_queue(tmp_path):
    node = node_scenarios(SCENARIOS, tmp_path)
    for scenario in SCENARIOS:
        python = run_scenario(scenario, tmp_path / scenario['id'])
        assert comparable(python) == comparable(node[scenario['id']]), scenario['id']
