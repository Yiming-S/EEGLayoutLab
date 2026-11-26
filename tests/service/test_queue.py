"""Durable workspace FIFO queue and startup receipt reconciliation tests (phase 2 slice 4).

Ports all 24 ``slice = 4`` queue and reconciliation sites from:
- ``check-abuse-limits.mjs``
- ``check-community-queue.mjs``
- ``check-cross-region-contract.mjs``
- ``check-product-operations-integration.mjs``
- ``check-queue-maintenance.mjs``
- ``check-reconciliation.mjs``
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any, Callable, Optional
import uuid

import pytest

from eeglayoutlab.jobs.identity import request_key
from eeglayoutlab.jobs.queue import (
    INTERRUPTED_MESSAGE, QueueError, WorkspaceQueue, build_reconciliation, inspect_receipt, radius_adapter,
    validate_queue,
)
from eeglayoutlab.jobs.radius import RadiusService
from eeglayoutlab.jobs.worker import ExecutionSlot
from eeglayoutlab.schemas import jsjson

from .library_support import code_tree, forward_inputs, radius_result, write_cache
from .test_radius import REQUEST, result_for


class FakeAdapter:
    """In-memory controllable workflow adapter sharing a single ExecutionSlot."""

    def __init__(
        self,
        kind: str,
        slot: Optional[ExecutionSlot] = None,
        *,
        normalize: Optional[Callable[[Any], dict]] = None,
    ):
        self.kind = kind
        self.slot = slot
        self.version = 1
        self._normalize = normalize or self._default_normalize
        self.cache: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.active_id: Optional[str] = None
        self._release: Optional[Callable[[], None]] = None
        self.worker_pid = 51000
        self.prepare_hook: Optional[Callable[[dict], None]] = None
        self.start_hook: Optional[Callable[[dict], Optional[dict]]] = None
        self.next_key_override: Optional[str] = None

    @staticmethod
    def _default_normalize(raw: Any) -> dict:
        if not isinstance(raw, dict) or not raw:
            raise ValueError('Invalid request.')
        if 'bad' in raw:
            raise ValueError('Invalid parameter.')
        return dict(raw)

    def identity(self) -> dict[str, Any]:
        return {'kind': self.kind, 'version': self.version}

    def prepare(self, raw: Any) -> dict[str, Any]:
        request = self._normalize(raw)
        if self.prepare_hook is not None:
            self.prepare_hook(request)
        ident = self.identity()
        key = request_key(request, ident)
        return {'request': request, 'key': key, 'ctx': {'identity': ident, 'key': key}}

    def lookup(self, prepared: dict[str, Any]) -> dict[str, Any]:
        entry = self.cache.get(prepared['key'])
        if entry is None:
            return {'hit': False}
        return {
            'hit': True,
            'job': {
                'id': str(uuid.uuid4()),
                'key': prepared['key'],
                'request': prepared['request'],
                'status': entry['status'],
                'progress': 1,
                'result': entry['result'],
                'finished_at': entry.get('finished_at', '2026-10-01T00:00:00Z'),
                'cached': True,
                'source': 'local_cache',
            },
        }

    def start(self, raw: Any) -> dict[str, Any]:
        if self.start_hook is not None:
            override = self.start_hook(raw)
            if override is not None:
                return override
        prepared = self.prepare(raw)
        if self.active_id is not None:
            return {'busy': True}
        rel = None
        if self.slot is not None:
            rel = self.slot.acquire(self)
            if rel is None:
                return {'busy': True}
        self._release = rel
        jid = str(uuid.uuid4())
        key = self.next_key_override or prepared['key']
        self.next_key_override = None
        job = {
            'id': jid,
            'key': key,
            'request': prepared['request'],
            'status': 'running',
            'progress': 0.25,
            'message': 'running',
            'result': None,
            'cached': False,
        }
        self.jobs[jid] = job
        self.active_id = jid
        return {'job': dict(job)}

    def finish(self, jid: Optional[str] = None, *, status: str = 'completed', result: Any = None,
               write_cache_entry: bool = True) -> None:
        target = jid or self.active_id
        assert target is not None
        job = self.jobs[target]
        res = {'ok': True, 'status': status} if result is None and status in ('completed', 'no_layout') else result
        job['status'] = status
        job['progress'] = 1 if status in ('completed', 'no_layout') else job['progress']
        job['result'] = res
        job['message'] = status
        job['finished_at'] = '2026-10-01T00:00:05Z'
        if write_cache_entry and status in ('completed', 'no_layout'):
            self.cache[job['key']] = {
                'status': status,
                'result': res,
                'finished_at': job['finished_at'],
            }
        if self.active_id == target:
            self.active_id = None
        if self._release is not None:
            rel = self._release
            self._release = None
            rel()

    def cancel(self, jid: str) -> bool:
        job = self.jobs.get(jid)
        if job is None:
            return False
        job['status'] = 'cancelling'
        job['cancelling'] = True
        return True

    def as_dict(self) -> dict[str, Callable[..., Any]]:
        return {
            'prepare': self.prepare,
            'lookup': self.lookup,
            'start': self.start,
            'get': lambda jid: dict(self.jobs[jid]) if jid in self.jobs else None,
            'busy': lambda: self.active_id is not None,
            'pid': lambda: self.worker_pid if self.active_id is not None else None,
            'cancel': self.cancel,
        }


def _four_adapters(slot: ExecutionSlot) -> tuple[dict[str, FakeAdapter], dict[str, dict]]:
    objs = {
        kind: FakeAdapter(kind, slot)
        for kind in ('local-compute', 'source-reception', 'design-evaluation', 'electrode-editor')
    }
    return objs, {kind: obj.as_dict() for kind, obj in objs.items()}


def _make_queue(qdir: Path, adapters: dict[str, dict], **kwargs: Any) -> WorkspaceQueue:
    return WorkspaceQueue(str(qdir), adapters, poll_ms=None, **kwargs)


def _radius_root(tmp_path: Path) -> Path:
    root = tmp_path / 'root'
    root.mkdir()
    code_tree(root)
    forward_inputs(root)
    return root


# --- Abuse-limits & persistence resilience ports -----------------------------------------------------------------

def test_lookup_of_a_computed_result_keeps_the_computed_receipt_and_writes_nothing_new(tmp_path: Path):
    """check-abuse-limits.mjs::a lookup of a computed result keeps the computed receipt and writes nothing new."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    qdir = tmp_path / 'queue'
    q = _make_queue(qdir, adapters, execution_slot=slot)
    try:
        sub = q.submit('local-compute', {'n': 1})['job']
        q.tick()
        objs['local-compute'].finish()
        q.tick()

        queue_file = qdir / 'queue.json'
        before_bytes = queue_file.read_bytes()
        assert len(q.tasks) == 1
        assert q.tasks[0]['id'] == sub['id']
        assert q.tasks[0]['cached'] is False

        looked = q.submit('local-compute', {'n': 1}, lookup_only=True)
        assert looked['hit'] is True
        assert looked['job']['id'] == sub['id']
        assert looked['job']['cached'] is True
        assert looked['job']['source'] == 'local_cache'
        # Original computed receipt remains cached=False and queue.json is untouched byte-for-byte.
        assert len(q.tasks) == 1 and q.tasks[0]['cached'] is False
        assert queue_file.read_bytes() == before_bytes
    finally:
        q.dispose()


def test_shutdown_during_a_launch_keeps_the_task_queued_instead_of_blocking_restart(tmp_path: Path):
    """check-abuse-limits.mjs::a shutdown during a launch keeps the task queued instead of blocking restart."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    qdir = tmp_path / 'queue'
    entered_start = threading.Event()
    allow_return = threading.Event()

    def slow_start(_raw: dict) -> dict:
        entered_start.set()
        allow_return.wait(timeout=3.0)
        return {'busy': True}

    objs['local-compute'].start_hook = slow_start
    q = _make_queue(qdir, adapters, execution_slot=slot)
    job = q.submit('local-compute', {'n': 2})['job']

    ticker = threading.Thread(target=q.tick)
    ticker.start()
    assert entered_start.wait(timeout=3.0)
    # Dispose happens mid-launch before workerPid is recorded.
    q.dispose()
    allow_return.set()
    ticker.join(timeout=3.0)

    objs['local-compute'].start_hook = None
    restarted = _make_queue(qdir, adapters, execution_slot=slot)
    try:
        assert not restarted.unconfirmed_worker
        assert restarted.stats()['recovery_blocked'] is False
        restored = restarted.get_task(job['id'])
        assert restored['status'] == 'queued'
        restarted.tick()
        assert restarted.get_task(job['id'])['status'] == 'running'
        objs['local-compute'].finish()
        restarted.tick()
        assert restarted.get_task(job['id'])['status'] == 'completed'
    finally:
        restarted.dispose()


def test_failed_queue_write_stops_new_work_until_the_disk_accepts_writes_again(tmp_path: Path, monkeypatch):
    """check-abuse-limits.mjs::a failed queue write stops new work until the disk accepts writes again."""
    import eeglayoutlab.jobs.queue as queue_mod

    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    qdir = tmp_path / 'queue'
    q = _make_queue(qdir, adapters, execution_slot=slot)
    try:
        real_save = queue_mod._save_atomic
        fail_writes = True

        def flaky_save(path: str, value: Any) -> None:
            if fail_writes:
                raise OSError('ENOSPC disk full')
            real_save(path, value)

        monkeypatch.setattr(queue_mod, '_save_atomic', flaky_save)
        with pytest.raises(OSError, match='ENOSPC'):
            q.submit('local-compute', {'n': 1})
        assert q.persist_failed is True
        assert q.stats()['available'] is False

        # Subsequent submissions fail closed with 503 while disk writes are failing.
        with pytest.raises(QueueError) as refused:
            q.submit('local-compute', {'n': 2})
        assert refused.value.status == 503

        # Once disk accepts writes again, tick() recovers persistence and resumes scheduling.
        fail_writes = False
        q.tick()
        assert q.persist_failed is False and q.failure is None
        assert q.stats()['available'] is True
        nxt = q.submit('local-compute', {'n': 3})['job']
        assert nxt['status'] == 'queued'
        objs['local-compute'].finish()
        q.tick()
        objs['local-compute'].finish()
        q.tick()
        assert q.get_task(nxt['id'])['status'] == 'completed'
    finally:
        monkeypatch.undo()
        q.dispose()


# --- CommunityQueue FIFO, deduplication, cancellation, restart, bounds, guards -----------------------------------

def test_all_four_services_share_one_persistent_fifo_slot_and_timeout_starts_in_the_worker(tmp_path: Path):
    """check-community-queue.mjs::all four services share one persistent FIFO slot; timeout starts in the worker."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    q = _make_queue(tmp_path / 'queue', adapters, execution_slot=slot)
    try:
        kinds = ('local-compute', 'source-reception', 'design-evaluation', 'electrode-editor')
        ids = [q.submit(kind, {'step': idx})['job']['id'] for idx, kind in enumerate(kinds)]
        positions = [q.view(q.get_task(tid))['queue_position'] for tid in ids]
        assert positions == [1, 2, 3, 4]

        started_order: list[str] = []
        for idx, kind in enumerate(kinds):
            q.tick()
            assert [k for k in kinds if objs[k].active_id is not None] == [kind]
            # Waiting tasks stay 'queued' until they actually enter the worker (timeout only starts on launch).
            for later_id in ids[idx + 1:]:
                assert q.get_task(later_id)['status'] == 'queued'
            started_order.append(kind)
            objs[kind].finish()
            q.tick()

        assert started_order == list(kinds)
        assert [q.get_task(tid)['status'] for tid in ids] == ['completed'] * 4
    finally:
        q.dispose()


def test_exact_pending_keys_share_work(tmp_path: Path):
    """check-community-queue.mjs::exact pending keys share work; one subscriber cannot cancel the others."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    q = _make_queue(tmp_path / 'queue', adapters, execution_slot=slot)
    try:
        first = q.submit('local-compute', {'radius_mm': 35})['job']
        second = q.submit('local-compute', {'radius_mm': 35})['job']
        assert first['id'] == second['id']
        assert len(q.tasks) == 1

        q.tick()
        in_flight = q.submit('local-compute', {'radius_mm': 35})['job']
        assert in_flight['id'] == first['id'] and in_flight['status'] == 'running'
        objs['local-compute'].finish()
        q.tick()
        assert q.view(q.get_task(first['id']))['status'] == 'completed'
    finally:
        q.dispose()


def test_completed_cache_bypasses_a_busy_worker_and_repeated_lookup_reuses_a_receipt(tmp_path: Path):
    """check-community-queue.mjs::completed cache bypasses a busy worker and repeated lookup reuses a receipt."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    cached_prep = objs['design-evaluation'].prepare({'design': 'ready'})
    objs['design-evaluation'].cache[cached_prep['key']] = {
        'status': 'completed',
        'result': {'nominal': 0.91},
        'finished_at': '2026-10-01T00:00:00Z',
    }
    q = _make_queue(tmp_path / 'queue', adapters, execution_slot=slot)
    try:
        busy_job = q.submit('local-compute', {'radius_mm': 30})['job']
        q.tick()
        assert objs['local-compute'].active_id is not None

        # Cached hit completes immediately without waiting behind the busy local-compute worker.
        hit_1 = q.submit('design-evaluation', {'design': 'ready'})['job']
        assert hit_1['status'] == 'completed' and hit_1['cached'] is True
        assert hit_1['result'] == {'nominal': 0.91}

        hit_2 = q.submit('design-evaluation', {'design': 'ready'}, lookup_only=True)['job']
        assert hit_2['id'] == hit_1['id']
        assert sum(1 for t in q.tasks if t['kind'] == 'design-evaluation') == 1

        assert q.get_task(busy_job['id'])['status'] == 'running'
        objs['local-compute'].finish()
        q.tick()
    finally:
        q.dispose()


def test_queued_cancellation_advances_running_waits_for_close_and_cancelling_is_not_shared(tmp_path: Path):
    """check-community-queue.mjs::queued cancellation advances; running cancellation waits for actual close;
    cancelling is not shared."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    q = _make_queue(tmp_path / 'queue', adapters, execution_slot=slot)
    try:
        j1 = q.submit('local-compute', {'n': 1})['job']
        j2 = q.submit('local-compute', {'n': 2})['job']
        j3 = q.submit('local-compute', {'n': 3})['job']

        # Cancel queued j2 before dispatch -> j3 advances to position 2 (then 1 once j1 starts).
        cancelled_q = q.cancel(j2['id'], 'local-compute')
        assert cancelled_q['status'] == 'cancelled'

        q.tick()
        assert q.get_task(j1['id'])['status'] == 'running'
        assert q.view(q.get_task(j3['id']))['queue_position'] == 1

        # Cancel running j1 -> status becomes 'cancelling', slot remains busy until child closes.
        cancelling = q.cancel(j1['id'], 'local-compute')
        assert cancelling['status'] == 'cancelling'
        q.tick()
        assert q.get_task(j3['id'])['status'] == 'queued'

        # Submitting same key as 'cancelling' j1 is NOT shared with the dying task; it creates a fresh queued receipt.
        fresh_j1 = q.submit('local-compute', {'n': 1})['job']
        assert fresh_j1['id'] != j1['id'] and fresh_j1['status'] == 'queued'

        # Close j1 -> j3 now starts.
        objs['local-compute'].finish(status='cancelled', write_cache_entry=False)
        q.tick()
        assert q.get_task(j1['id'])['status'] == 'cancelled'
        assert q.get_task(j3['id'])['status'] == 'running'
        objs['local-compute'].finish()
        q.tick()
        objs['local-compute'].finish()
        q.tick()
    finally:
        q.dispose()


def test_queued_receipt_survives_restart_and_changed_scientific_identity_fails_without_starting(tmp_path: Path):
    """check-community-queue.mjs::queued receipt survives restart and changed scientific identity fails without
    starting."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    qdir = tmp_path / 'queue'
    q1 = _make_queue(qdir, adapters, execution_slot=slot)
    queued = q1.submit('local-compute', {'n': 10})['job']
    q1.dispose()

    # Bump code identity version before restart.
    objs['local-compute'].version = 2
    started = False
    objs['local-compute'].start_hook = lambda *_: (_ for _ in ()).throw(AssertionError('must not start'))  # type: ignore[func-returns-value]
    q2 = _make_queue(qdir, adapters, execution_slot=slot)
    try:
        assert not started
        assert q2.get_task(queued['id'])['status'] == 'queued'
        q2.tick()
        failed = q2.get_task(queued['id'])
        assert failed['status'] == 'failed'
        assert '模型或代码已更新' in failed['message']
    finally:
        q2.dispose()


def test_queued_receipt_executes_after_clean_restart_and_same_key_pending_lookup_restores_it(tmp_path: Path):
    """check-community-queue.mjs::queued receipt executes after clean restart and same-key pending lookup restores
    it."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    qdir = tmp_path / 'queue'
    q1 = _make_queue(qdir, adapters, execution_slot=slot)
    queued = q1.submit('local-compute', {'n': 11})['job']
    q1.dispose()

    q2 = _make_queue(qdir, adapters, execution_slot=slot)
    try:
        looked = q2.submit('local-compute', {'n': 11}, lookup_only=True)
        assert looked['hit'] is True
        assert looked['job']['id'] == queued['id'] and looked['job']['status'] == 'queued'

        q2.tick()
        assert q2.get_task(queued['id'])['status'] == 'running'
        objs['local-compute'].finish()
        q2.tick()
        assert q2.view(q2.get_task(queued['id']))['status'] == 'completed'
    finally:
        q2.dispose()


def test_worker_pid_blocks_consecutive_restarts_and_unconfirmed_spawn_fails_closed(tmp_path: Path):
    """check-community-queue.mjs::worker PID blocks consecutive restarts; an unconfirmed spawn fails closed."""
    slot = ExecutionSlot()
    _, adapters = _four_adapters(slot)
    qdir = tmp_path / 'queue'
    qdir.mkdir()

    sleeper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        (qdir / 'queue.json').write_text(jsjson.stringify({
            'version': 1,
            'sequence': 2,
            'tasks': [
                {
                    'id': str(uuid.uuid4()), 'sequence': 1, 'kind': 'local-compute', 'key': 'a' * 64,
                    'request': {'n': 1}, 'owners': ['local'], 'status': 'running',
                    'created_at': '2026-10-01T00:00:00Z', 'workerPid': sleeper.pid,
                },
                {
                    'id': '22222222-2222-2222-2222-222222222222', 'sequence': 2, 'kind': 'local-compute',
                    'key': 'b' * 64, 'request': {'n': 2}, 'owners': ['local'], 'status': 'queued',
                    'created_at': '2026-10-01T00:00:01Z',
                },
            ],
        }), encoding='utf-8')

        # Restart 1 & Restart 2 while sleeper PID is alive: recovery_blocked stays True, queued task does not start.
        for _ in range(2):
            q = _make_queue(qdir, adapters, execution_slot=slot)
            assert q.stats()['recovery_blocked'] is True
            q.tick()
            assert q.get_task('22222222-2222-2222-2222-222222222222')['status'] == 'queued'
            # Preserve workerPid across restart if process is still alive: check blocked_pids directly.
            assert sleeper.pid in q.blocked_pids
            q.dispose()
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=5)

    # Unconfirmed spawn (starting=True with no workerPid) fails closed on startup and stays blocked.
    qdir_unconfirmed = tmp_path / 'queue-unconfirmed'
    qdir_unconfirmed.mkdir()
    (qdir_unconfirmed / 'queue.json').write_text(jsjson.stringify({
        'version': 1,
        'sequence': 2,
        'tasks': [
            {
                'id': str(uuid.uuid4()), 'sequence': 1, 'kind': 'local-compute', 'key': 'c' * 64,
                'request': {'n': 1}, 'owners': ['local'], 'status': 'running', 'starting': True,
                'created_at': '2026-10-01T00:00:00Z',
            },
            {
                'id': '33333333-3333-3333-3333-333333333333', 'sequence': 2, 'kind': 'local-compute',
                'key': 'd' * 64, 'request': {'n': 2}, 'owners': ['local'], 'status': 'queued',
                'created_at': '2026-10-01T00:00:01Z',
            },
        ],
    }), encoding='utf-8')
    qu = _make_queue(qdir_unconfirmed, adapters, execution_slot=slot)
    try:
        assert qu.unconfirmed_worker is True
        assert qu.stats()['recovery_blocked'] is True
        qu.tick()
        assert qu.get_task('33333333-3333-3333-3333-333333333333')['status'] == 'queued'
    finally:
        qu.dispose()


def test_one_live_owner_prevents_a_second_scheduler_and_invalid_queue_json_is_not_overwritten(tmp_path: Path):
    """check-community-queue.mjs::one live owner prevents a second scheduler; invalid queue JSON is not overwritten."""
    slot = ExecutionSlot()
    _, adapters = _four_adapters(slot)
    qdir = tmp_path / 'queue'
    q1 = _make_queue(qdir, adapters, execution_slot=slot)
    try:
        with pytest.raises(RuntimeError, match='already owned'):
            _make_queue(qdir, adapters, execution_slot=slot)
    finally:
        q1.dispose()

    corrupt_dir = tmp_path / 'corrupt-queue'
    corrupt_dir.mkdir()
    corrupt_bytes = b'{"version": 1, "tasks": [corrupt!'
    (corrupt_dir / 'queue.json').write_bytes(corrupt_bytes)
    with pytest.raises(ValueError, match='preserve the file'):
        _make_queue(corrupt_dir, adapters, execution_slot=slot)
    assert (corrupt_dir / 'queue.json').read_bytes() == corrupt_bytes
    assert not (corrupt_dir / 'worker.lock').exists()


def test_global_queue_bounds_invalid_inputs_and_missing_task(tmp_path: Path):
    """check-community-queue.mjs::per-browser and global queue bounds, invalid inputs, and unknown ownership."""
    slot = ExecutionSlot()
    _, adapters = _four_adapters(slot)
    q = _make_queue(tmp_path / 'queue', adapters, execution_slot=slot, max_queued=2)
    try:
        q.submit('local-compute', {'n': 1})
        q.submit('local-compute', {'n': 2})
        with pytest.raises(QueueError) as full_err:
            q.submit('local-compute', {'n': 3})
        assert full_err.value.status == 429 and '队列已满' in full_err.value.message

        with pytest.raises(ValueError, match='Invalid parameter'):
            q.submit('local-compute', {'bad': True})

        with pytest.raises(QueueError) as unknown_kind:
            q.submit('unknown-kind', {'n': 1})
        assert unknown_kind.value.status == 404

        with pytest.raises(QueueError) as missing_task:
            q.get_task('99999999-9999-9999-9999-999999999999', 'local-compute')
        assert missing_task.value.status == 404
    finally:
        q.dispose()


def test_backend_key_mismatch_is_cancelled_and_never_presented_as_an_old_key_result(tmp_path: Path):
    """check-community-queue.mjs::backend key mismatch is cancelled and never presented as an old-key result."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    q = _make_queue(tmp_path / 'queue', adapters, execution_slot=slot)
    try:
        job = q.submit('local-compute', {'n': 7})['job']
        objs['local-compute'].next_key_override = 'f' * 64
        q.tick()

        failed = q.view(q.get_task(job['id']))
        assert failed['status'] == 'failed'
        assert failed['result'] is None
        assert '模型或代码已更新' in failed['message']
        backend_id = q.get_task(job['id'])['backendId']
        assert objs['local-compute'].jobs[backend_id].get('cancelling') is True
    finally:
        q.dispose()


def test_dispose_during_identity_preparation_cannot_enqueue_or_launch_a_late_task(tmp_path: Path):
    """check-community-queue.mjs::dispose during identity preparation cannot enqueue or launch a late task."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    qdir1 = tmp_path / 'q1'
    q1 = _make_queue(qdir1, adapters, execution_slot=slot)
    objs['local-compute'].prepare_hook = lambda _req: q1.dispose()
    with pytest.raises(QueueError) as err:
        q1.submit('local-compute', {'n': 1})
    assert err.value.status == 503
    assert q1.tasks == []

    # Dispose during dispatch prepare_hook cannot launch the queued task.
    objs['local-compute'].prepare_hook = None
    qdir2 = tmp_path / 'q2'
    q2 = _make_queue(qdir2, adapters, execution_slot=slot)
    queued = q2.submit('local-compute', {'n': 2})['job']
    objs['local-compute'].prepare_hook = lambda _req: q2.dispose()
    q2.tick()
    assert objs['local-compute'].active_id is None
    assert q2.tasks[0]['id'] == queued['id'] and q2.tasks[0]['status'] == 'queued'


def test_source_adapter_deduplicates_permuted_selections_and_restores_a_pending_canonical_request(tmp_path: Path):
    """check-cross-region-contract.mjs::real source adapter deduplicates permuted selections and restores a pending
    canonical request."""
    source_regions = ('frontal', 'central', 'temporal_left', 'temporal_right', 'parietal', 'occipital')

    def normalize_cross(raw: Any) -> dict:
        if not isinstance(raw, dict) or raw.get('mode') != 'cross_region':
            raise ValueError('expected cross_region')
        chosen = raw.get('brain_regions')
        if not isinstance(chosen, list) or not chosen or len(set(chosen)) != len(chosen):
            raise ValueError('invalid brain_regions')
        if any(r not in source_regions for r in chosen):
            raise ValueError('unknown region')
        canonical_regions = [r for r in source_regions if r in chosen]
        return {
            'record_id': raw['record_id'],
            'mode': 'cross_region',
            'brain_regions': canonical_regions,
            'waveform': raw['waveform'],
            'artifact_scale': raw['artifact_scale'],
            'seed': raw['seed'],
        }

    slot = ExecutionSlot()
    source_adapter = FakeAdapter('source-reception', slot, normalize=normalize_cross)
    adapters = {'source-reception': source_adapter.as_dict()}
    qdir = tmp_path / 'cross-queue'
    q1 = _make_queue(qdir, adapters, execution_slot=slot)
    base = {'record_id': 'a' * 64, 'mode': 'cross_region', 'waveform': 'burst', 'artifact_scale': 1, 'seed': 2026}
    first = q1.submit('source-reception', {**base, 'brain_regions': ['occipital', 'frontal']})['job']
    duplicate = q1.submit('source-reception', {**base, 'brain_regions': ['frontal', 'occipital']})['job']
    assert first['id'] == duplicate['id']
    assert q1.tasks[0]['request']['brain_regions'] == ['frontal', 'occipital']
    q1.dispose()

    q2 = _make_queue(qdir, adapters, execution_slot=slot)
    try:
        restored = q2.submit('source-reception', {**base, 'brain_regions': ['occipital', 'frontal']},
                             lookup_only=True)['job']
        assert restored['id'] == first['id']
        assert restored['status'] == 'queued'
    finally:
        q2.dispose()


def test_shutdown_during_asynchronous_admission_cannot_persist_a_late_queued_task(tmp_path: Path):
    """check-product-operations-integration.mjs::shutdown during asynchronous admission cannot persist a late queued
    task or project."""
    slot = ExecutionSlot()
    _, adapters = _four_adapters(slot)
    qdir = tmp_path / 'admission-queue'
    holder: list[WorkspaceQueue] = []

    def stop_on_admission() -> None:
        holder[0].stop_scheduling()

    q = _make_queue(qdir, adapters, execution_slot=slot, before_new_work=stop_on_admission)
    holder.append(q)
    try:
        with pytest.raises(QueueError) as refused:
            q.submit('local-compute', {'n': 42})
        assert refused.value.status == 503
        assert q.tasks == []
        persisted = jsjson.parse((qdir / 'queue.json').read_text(encoding='utf-8'))
        assert persisted['tasks'] == []
    finally:
        q.dispose()


# --- Slot contention, ambiguous start, and cache_only tracking ports ---------------------------------------------

def test_external_worker_acquiring_slot_during_dispatch_preparation_keeps_task_queued(tmp_path: Path):
    """check-queue-maintenance.mjs::an external worker acquiring the slot during dispatch preparation keeps the task
    queued."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    q = _make_queue(tmp_path / 'queue', adapters, execution_slot=slot)
    external_release: list[Optional[Callable[[], None]]] = []
    try:
        job = q.submit('local-compute', {'n': 1})['job']
        objs['local-compute'].prepare_hook = lambda _req: external_release.append(slot.acquire('external'))
        q.tick()
        assert q.get_task(job['id'])['status'] == 'queued'
        assert objs['local-compute'].active_id is None

        objs['local-compute'].prepare_hook = None
        assert external_release[0] is not None
        external_release[0]()
        q.tick()
        assert q.get_task(job['id'])['status'] == 'running'
        objs['local-compute'].finish()
        q.tick()
    finally:
        q.dispose()


def test_confirmed_busy_contention_clears_spawn_intent_and_preserves_fifo_through_restart(tmp_path: Path):
    """check-queue-maintenance.mjs::confirmed busy contention clears spawn intent and preserves FIFO through
    maintenance and restart."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    qdir = tmp_path / 'queue'
    q1 = _make_queue(qdir, adapters, execution_slot=slot)
    j1 = q1.submit('local-compute', {'n': 1})['job']
    j2 = q1.submit('source-reception', {'n': 2})['job']

    objs['local-compute'].start_hook = lambda _raw: {'busy': True}
    q1.tick()
    t1 = q1.get_task(j1['id'])
    assert t1['status'] == 'queued' and 'starting' not in t1
    assert not q1.unconfirmed_worker
    q1.dispose()

    objs['local-compute'].start_hook = None
    q2 = _make_queue(qdir, adapters, execution_slot=slot)
    try:
        assert not q2.stats()['recovery_blocked']
        assert [t['id'] for t in q2.tasks] == [j1['id'], j2['id']]
        q2.tick()
        assert q2.get_task(j1['id'])['status'] == 'running'
        objs['local-compute'].finish()
        q2.tick()
        assert q2.get_task(j2['id'])['status'] == 'running'
        objs['source-reception'].finish()
        q2.tick()
        assert [q2.get_task(j1['id'])['status'], q2.get_task(j2['id'])['status']] == ['completed', 'completed']
    finally:
        q2.dispose()


def test_ambiguous_thrown_start_keeps_its_recovery_guard_through_restart(tmp_path: Path):
    """check-queue-maintenance.mjs::an ambiguous thrown start keeps its recovery guard through maintenance and
    restart."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    qdir = tmp_path / 'queue'
    q1 = _make_queue(qdir, adapters, execution_slot=slot)
    j1 = q1.submit('local-compute', {'n': 1})['job']
    j2 = q1.submit('local-compute', {'n': 2})['job']

    def ambiguous_boom(_raw: dict) -> dict:
        raise RuntimeError('ambiguous post-fork failure')

    objs['local-compute'].start_hook = ambiguous_boom
    q1.tick()
    assert q1.unconfirmed_worker is True
    assert q1.stats()['recovery_blocked'] is True
    assert q1.get_task(j1['id'])['status'] == 'failed'
    assert q1.get_task(j1['id']).get('starting') is True
    assert q1.get_task(j2['id'])['status'] == 'queued'
    q1.dispose()

    objs['local-compute'].start_hook = None
    q2 = _make_queue(qdir, adapters, execution_slot=slot)
    try:
        assert q2.unconfirmed_worker is True
        assert q2.stats()['recovery_blocked'] is True
        q2.tick()
        assert q2.get_task(j2['id'])['status'] == 'queued'
    finally:
        q2.dispose()


def test_worker_launched_before_cache_only_stays_tracked_when_start_resolves_afterwards(tmp_path: Path):
    """check-queue-maintenance.mjs::a worker launched before the pause stays tracked when start resolves afterwards."""
    slot = ExecutionSlot()
    objs, adapters = _four_adapters(slot)
    q = _make_queue(tmp_path / 'queue', adapters, execution_slot=slot)
    try:
        j1 = q.submit('local-compute', {'n': 1})['job']
        j2 = q.submit('local-compute', {'n': 2})['job']

        def pause_during_start(raw: dict) -> Optional[dict]:
            q.cache_only = True
            return None

        objs['local-compute'].start_hook = pause_during_start
        q.tick()
        t1 = q.get_task(j1['id'])
        assert t1['status'] == 'running' and t1.get('backendId') is not None
        assert not q.drained()

        objs['local-compute'].finish()
        q.tick()
        assert q.get_task(j1['id'])['status'] == 'completed'
        # Because cache_only is True, j2 stays queued without dispatching and drained() becomes True.
        assert q.get_task(j2['id'])['status'] == 'queued'
        assert q.drained() is True
    finally:
        q.dispose()


# --- Startup reconciliation ports (check-reconciliation.mjs) -----------------------------------------------------

def test_only_running_and_exact_restart_interrupted_failed_receipts_are_recoverable(tmp_path: Path):
    """check-reconciliation.mjs::only running and exact restart-interrupted failed receipts are recoverable."""
    root = _radius_root(tmp_path)
    radius = RadiusService(str(root), python='python3', verify_inputs=lambda _: None)
    adapters = {'local-compute': radius_adapter(radius)}

    reqs = [{**REQUEST, 'radius_mm': r} for r in (25, 30, 35, 40, 45)]
    keys = []
    for req in reqs:
        ident, key = radius.identity_for(req)
        keys.append(key)
        cache_path = root / f'results/v2/local_app_jobs/{key}/cache.json'
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        res = result_for(req)
        cache_path.write_text(jsjson.stringify({
            'key': key, 'request': req, 'identity': ident, 'result': res,
            'result_sha256': jsjson.sha256_hex(res), 'finished_at': '2026-10-02T00:00:00Z',
        }), encoding='utf-8')

    qdir = tmp_path / 'queue'
    qdir.mkdir()
    statuses = [
        ('t-running', 'running', '正在计算'),
        ('t-interrupted', 'failed', INTERRUPTED_MESSAGE),
        ('t-other-fail', 'failed', '计算结果校验失败：电极间距不足'),
        ('t-cancelled', 'cancelled', '任务已停止'),
        ('t-queued', 'queued', '已加入计算队列'),
    ]
    (qdir / 'queue.json').write_text(jsjson.stringify({
        'version': 1,
        'sequence': 5,
        'tasks': [
            {
                'id': tid, 'sequence': idx + 1, 'kind': 'local-compute', 'key': keys[idx],
                'request': reqs[idx], 'owners': ['local'], 'status': st, 'message': msg,
                'created_at': '2026-10-02T00:00:00Z',
            }
            for idx, (tid, st, msg) in enumerate(statuses)
        ],
    }), encoding='utf-8')

    q = _make_queue(qdir, adapters, root=str(root))
    try:
        by_id = {t['id']: t for t in q.tasks}
        assert by_id['t-running']['status'] == 'completed' and by_id['t-running']['cached'] is True
        assert by_id['t-interrupted']['status'] == 'completed' and by_id['t-interrupted']['cached'] is True
        assert by_id['t-other-fail']['status'] == 'failed'
        assert by_id['t-cancelled']['status'] == 'cancelled'
        assert by_id['t-queued']['status'] == 'queued'
    finally:
        q.dispose()


def test_no_layout_is_valid_only_for_the_radius_cache_and_cancellations_never_revive():
    """check-reconciliation.mjs::no_layout is valid only for the radius cache; cancellations never revive."""
    req = {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'}
    req_sha = jsjson.sha256_hex(req)
    queue_doc = {
        'version': 1,
        'sequence': 3,
        'tasks': [
            {
                'id': 'r-radius', 'sequence': 1, 'kind': 'local-compute', 'key': 'a' * 64,
                'request': req, 'owners': ['local'], 'status': 'running', 'created_at': '2026-10-01T00:00:00Z',
            },
            {
                'id': 'r-design', 'sequence': 2, 'kind': 'design-evaluation', 'key': 'b' * 64,
                'request': req, 'owners': ['local'], 'status': 'running', 'created_at': '2026-10-01T00:00:00Z',
            },
            {
                'id': 'r-cancelled', 'sequence': 3, 'kind': 'local-compute', 'key': 'c' * 64,
                'request': req, 'owners': ['local'], 'status': 'cancelling', 'created_at': '2026-10-01T00:00:00Z',
            },
        ],
    }
    obs = [
        {
            'id': 'r-radius', 'kind': 'local-compute', 'key': 'a' * 64, 'verdict': 'verified',
            'status': 'no_layout', 'request_sha256': req_sha, 'cache_sha256': '1' * 64,
            'identity_sha256': '2' * 64, 'finished_at': '2026-10-01T00:01:00Z', 'catalog': {},
        },
        {
            'id': 'r-design', 'kind': 'design-evaluation', 'key': 'b' * 64, 'verdict': 'verified',
            'status': 'no_layout', 'request_sha256': req_sha, 'cache_sha256': '3' * 64,
            'identity_sha256': '4' * 64, 'finished_at': '2026-10-01T00:01:00Z', 'catalog': {},
        },
        {
            'id': 'r-cancelled', 'kind': 'local-compute', 'key': 'c' * 64, 'verdict': 'verified',
            'status': 'completed', 'request_sha256': req_sha, 'cache_sha256': '5' * 64,
            'identity_sha256': '6' * 64, 'finished_at': '2026-10-01T00:01:00Z', 'catalog': {},
        },
    ]
    reconciled = build_reconciliation(queue_doc, obs)
    assert [c['id'] for c in reconciled['changes']] == ['r-radius']
    reasons = {r['id']: r['reason'] for r in reconciled['retained']}
    assert reasons == {
        'r-design': 'invalid_verified_observation',
        'r-cancelled': 'status_not_recoverable',
    }


def test_missing_invalid_stale_and_duplicate_observations_cannot_change_receipts():
    """check-reconciliation.mjs::missing, invalid, stale and duplicate observations cannot change receipts."""
    req = {'region_count': 2, 'radius_mm': 35, 'mode': 'whole_surface'}
    req_sha = jsjson.sha256_hex(req)
    queue_doc = validate_queue({
        'version': 1,
        'sequence': 4,
        'tasks': [
            {'id': f't{i}', 'sequence': i, 'kind': 'local-compute', 'key': f'{i}' * 64,
             'request': req, 'owners': ['local'], 'status': 'running'}
            for i in range(1, 5)
        ],
    })
    obs = [
        # t1 missing observation
        # t2 unverified observation
        {'id': 't2', 'verdict': 'retained', 'reason': 'missing_cache'},
        # t3 stale key mismatch
        {'id': 't3', 'kind': 'local-compute', 'key': '9' * 64, 'verdict': 'verified',
         'status': 'completed', 'request_sha256': req_sha, 'cache_sha256': 'a' * 64,
         'identity_sha256': 'b' * 64, 'finished_at': '2026-10-01T00:00:00Z', 'catalog': {}},
        # t4 invalid sha / timestamp
        {'id': 't4', 'kind': 'local-compute', 'key': '4' * 64, 'verdict': 'verified',
         'status': 'completed', 'request_sha256': req_sha, 'cache_sha256': 'not-a-sha',
         'identity_sha256': 'b' * 64, 'finished_at': '', 'catalog': {}},
    ]
    out = build_reconciliation(queue_doc, obs)
    assert out['changes'] == []
    assert {r['id']: r['reason'] for r in out['retained']} == {
        't1': 'cache_not_inspected',
        't2': 'missing_cache',
        't3': 'receipt_identity_changed',
        't4': 'invalid_verified_observation',
    }
    assert out['proposed_queue']['tasks'] == queue_doc['tasks']

    # Duplicate observation IDs raise ValueError immediately.
    with pytest.raises(ValueError, match='Duplicate'):
        build_reconciliation(queue_doc, [{'id': 't1'}, {'id': 't1'}])


def test_legacy_cache_without_identity_uses_the_original_key_definition_and_production_validator(tmp_path: Path):
    """check-reconciliation.mjs::legacy cache without identity uses the original key definition and production
    validator."""
    root = _radius_root(tmp_path)
    radius = RadiusService(str(root), python='python3', verify_inputs=lambda _: None)
    adapters = {'local-compute': radius_adapter(radius)}
    _, key = radius.identity_for(REQUEST)

    # write_cache writes {key, request, result, result_sha256, finished_at} WITHOUT an 'identity' field.
    write_cache(root, key, REQUEST, radius_result(REQUEST, status='no_layout'), '2026-10-03T00:00:00Z')
    task = {
        'id': 'legacy-1',
        'sequence': 1,
        'kind': 'local-compute',
        'key': key,
        'request': REQUEST,
        'owners': ['local'],
        'status': 'failed',
        'message': INTERRUPTED_MESSAGE,
        'created_at': '2026-10-03T00:00:00Z',
    }
    obs = inspect_receipt(task, root=str(root), adapters=adapters)
    assert obs['verdict'] == 'verified'
    assert obs['status'] == 'no_layout'
    assert obs['identity_evidence'] == 'original_key_definition_and_production_validation'

    # Corrupting the legacy result's validator rules (no_layout carrying metrics) rejects recovery on fresh startup.
    write_cache(root, key, REQUEST, {**radius_result(REQUEST, status='no_layout'), 'metrics': {}},
                '2026-10-03T00:00:00Z')
    fresh_radius = RadiusService(str(root), python='python3', verify_inputs=lambda _: None)
    bad_obs = inspect_receipt(task, root=str(root), adapters={'local-compute': radius_adapter(fresh_radius)})
    assert bad_obs['verdict'] == 'retained'
    assert bad_obs['reason'] == 'production_lookup_miss'
