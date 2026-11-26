"""Bounded NDJSON worker transport, process-group reaping, and ExecutionSlot lifecycle (phase 2 slice 4).

Ports the 12 worker and execution-slot sites from ``check-local-compute.mjs`` and ``check-worker-lifecycle.mjs``.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable, Optional

import pytest

from eeglayoutlab.jobs.radius import RadiusService
from eeglayoutlab.jobs.records import RecordStore
from eeglayoutlab.jobs.worker import ExecutionSlot, execution_slot_for, start_python_worker
from eeglayoutlab.schemas import jsjson

from .library_support import code_tree, forward_inputs
from .test_radius import REQUEST, result_for


class FakeChild:
    """Deterministic fake worker process matching check-worker-lifecycle.mjs's EventEmitter child."""

    def __init__(self, pid: int = 4242, *, fail_stdin: Optional[BaseException] = None):
        self.pid = pid
        self.signals: list[str] = []
        self.stdin_payloads: list[str] = []
        self._fail_stdin = fail_stdin
        self._on_stdout: Callable[[bytes | str], None] = lambda _: None
        self._on_stderr: Callable[[bytes | str], None] = lambda _: None
        self._on_error: Callable[[BaseException], None] = lambda _: None
        self._on_stdin_error: Callable[[BaseException], None] = lambda _: None
        self._on_close: Callable[[Optional[int], Optional[str]], None] = lambda *_: None

    def _attach_handlers(self, *, on_stdout, on_stderr, on_error, on_stdin_error, on_close) -> None:
        self._on_stdout = on_stdout
        self._on_stderr = on_stderr
        self._on_error = on_error
        self._on_stdin_error = on_stdin_error
        self._on_close = on_close

    def write_stdin(self, text: str) -> None:
        if self._fail_stdin is not None:
            raise self._fail_stdin
        self.stdin_payloads.append(text)

    def kill_signal(self, sig_name: str) -> None:
        self.signals.append(sig_name)

    def emit_stdout(self, chunk: bytes | str) -> None:
        self._on_stdout(chunk)

    def emit_stderr(self, chunk: bytes | str) -> None:
        self._on_stderr(chunk)

    def emit_error(self, err: BaseException) -> None:
        self._on_error(err)

    def emit_stdin_error(self, err: BaseException) -> None:
        self._on_stdin_error(err)

    def close(self, code: Optional[int] = 0, sig: Optional[str] = None) -> None:
        self._on_close(code, sig)


def _radius_root(tmp_path: Path) -> Path:
    root = tmp_path / 'root'
    root.mkdir()
    code_tree(root)
    forward_inputs(root)
    return root


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def test_execution_permit_is_exclusive_and_idempotent():
    """check-worker-lifecycle.mjs::execution permit is exclusive, idempotent, and maintenance blocks new owners only."""
    holder = type('Holder', (), {})()
    slot = execution_slot_for(holder)
    assert execution_slot_for(holder) is slot
    assert not slot.busy
    with pytest.raises(TypeError):
        slot.acquire(None)

    release_first = slot.acquire('radius')
    assert release_first is not None and slot.busy
    assert slot.acquire('design') is None

    release_first()
    assert not slot.busy

    release_second = slot.acquire('design')
    assert release_second is not None and slot.busy
    # Releasing the first permit again is a no-op and never drops the new owner's permit.
    release_first()
    assert slot.busy
    release_second()
    assert not slot.busy


def test_worker_decodes_split_utf8_and_final_unterminated_event_without_treating_diagnostics_as_data():
    """check-worker-lifecycle.mjs::worker decodes split UTF-8 and the final unterminated event without treating
    diagnostics as data."""
    child = FakeChild()
    events: list[dict] = []
    logs: list[str] = []
    stderr_snapshots: list[str] = []
    closed_with: list[tuple[Optional[int], Optional[str]]] = []

    start_python_worker(
        executable='python3',
        args=['-u', 'worker.py'],
        spawn_process=lambda exe, args, opts: child,
        on_event=lambda ev: events.append(ev),
        on_log=lambda line: logs.append(line),
        on_stderr=lambda text: stderr_snapshots.append(text),
        on_close=lambda code, sig: closed_with.append((code, sig)),
    )

    first_line = jsjson.stringify({'type': 'progress', 'message': '头模加载中', 'progress': 0.4}) + '\n'
    raw = first_line.encode('utf-8')
    # Split right inside the multibyte UTF-8 sequence for '头'.
    split_at = raw.index('头'.encode('utf-8')) + 1
    child.emit_stdout(raw[:split_at])
    assert events == []
    child.emit_stdout(raw[split_at:])
    assert events == [{'type': 'progress', 'message': '头模加载中', 'progress': 0.4}]

    # Plain log lines and non-dict JSON values go to on_log, never on_event; stderr stays out of events.
    child.emit_stdout('plain diagnostic line\n[1,2,3]\n')
    child.emit_stderr('{"type":"result","result":{"fake":true}}\n')
    assert len(events) == 1
    assert logs == ['plain diagnostic line', '[1,2,3]']
    assert 'fake' in stderr_snapshots[-1]

    # Final unterminated event without trailing newline is flushed on close.
    child.emit_stdout(jsjson.stringify({'type': 'result', 'result': {'ok': True}}))
    assert len(events) == 1
    child.close(0, None)
    assert events[-1] == {'type': 'result', 'result': {'ok': True}}
    assert closed_with == [(0, None)]


def test_stderr_is_bounded_and_spawn_errors_wait_for_actual_close():
    """check-worker-lifecycle.mjs::stderr is bounded and spawn errors wait for actual close."""
    child = FakeChild()
    diagnostics: list[str] = []
    errors: list[str] = []
    closed = False

    handle = start_python_worker(
        executable='python3',
        args=['worker.py'],
        spawn_process=lambda exe, args, opts: child,
        on_stderr=lambda text: diagnostics.append(text),
        on_error=lambda err: errors.append(str(err)),
        on_close=lambda *_: None,
    )
    child.emit_stderr('a' * 10000)
    child.emit_stderr('b' * 10000)
    assert len(diagnostics[-1]) == 16000
    assert diagnostics[-1] == ('a' * 6000) + ('b' * 10000)

    child2 = FakeChild()

    def mark_closed(*_: Any) -> None:
        nonlocal closed
        closed = True

    handle2 = start_python_worker(
        executable='missing-python',
        args=['worker.py'],
        spawn_process=lambda exe, args, opts: child2,
        on_stderr=lambda text: diagnostics.append(text),
        on_error=lambda err: errors.append(str(err)),
        on_close=mark_closed,
    )
    child2.emit_error(FileNotFoundError('ENOENT missing-python'))
    assert errors == ['ENOENT missing-python']
    assert not closed and not handle2.closed
    child2.close(127, None)
    assert closed and handle2.closed
    child.close(0, None)
    assert handle.closed


def test_timeout_escalates_termination_and_never_closes_transport_before_the_child_closes():
    """check-worker-lifecycle.mjs::timeout escalates termination and never closes transport before the child closes."""
    child = FakeChild()
    stops: list[str] = []
    closed: list[tuple[Optional[int], Optional[str]]] = []

    handle = start_python_worker(
        executable='python3',
        args=['worker.py'],
        timeout_ms=30,
        kill_after_ms=40,
        spawn_process=lambda exe, args, opts: child,
        on_stop=lambda reason: stops.append(reason),
        on_close=lambda code, sig: closed.append((code, sig)),
    )
    _wait_until(lambda: 'SIGTERM' in child.signals, timeout=2.0)
    assert stops == ['timeout']
    assert not handle.closed and closed == []

    _wait_until(lambda: 'SIGKILL' in child.signals, timeout=2.0)
    assert child.signals == ['SIGTERM', 'SIGKILL']
    assert not handle.closed and closed == []

    child.close(None, 'SIGKILL')
    assert handle.closed and closed == [(None, 'SIGKILL')]


def test_output_overflow_and_failed_stdin_stop_once_retaining_capacity_until_close():
    """check-worker-lifecycle.mjs::output overflow and failed stdin stop once, retaining capacity until close."""
    slot = ExecutionSlot()
    permit = slot.acquire('overflow')
    assert permit is not None
    child = FakeChild()
    stops: list[str] = []
    events: list[dict] = []

    def on_close(*_: Any) -> None:
        permit()

    handle = start_python_worker(
        executable='python3',
        args=['worker.py'],
        max_output_bytes=64,
        kill_after_ms=5000,
        spawn_process=lambda exe, args, opts: child,
        on_event=lambda ev: events.append(ev),
        on_stop=lambda reason: stops.append(reason),
        on_close=on_close,
    )
    child.emit_stdout(('{"type":"result","pad":"' + 'x' * 120 + '"}\n').encode('utf-8'))
    assert stops == ['output_limit']
    assert events == []
    assert not handle.stop('user')
    assert slot.busy
    child.close(None, 'SIGTERM')
    assert not slot.busy

    # Failed stdin stops once with 'input_error' and keeps permit until close.
    permit2 = slot.acquire('stdin')
    assert permit2 is not None
    broken_child = FakeChild(fail_stdin=BrokenPipeError('EPIPE'))
    stops2: list[str] = []
    start_python_worker(
        executable='python3',
        args=['worker.py'],
        input={'hello': 'world'},
        has_input=True,
        kill_after_ms=5000,
        spawn_process=lambda exe, args, opts: broken_child,
        on_stop=lambda reason: stops2.append(reason),
        on_close=lambda *_: permit2(),
    )
    assert stops2 == ['input_error']
    assert broken_child.signals == ['SIGTERM']
    assert slot.busy
    broken_child.close(1, None)
    assert not slot.busy


def test_cancellation_does_not_release_capacity_until_child_closes_and_no_result_is_cached(tmp_path: Path):
    """check-local-compute.mjs::cancellation does not release capacity until child closes; no result is cached."""
    root = _radius_root(tmp_path)
    children: list[FakeChild] = []

    def spawn(exe: str, args: list[str], opts: dict) -> FakeChild:
        c = FakeChild(pid=5000 + len(children))
        children.append(c)
        return c

    service = RadiusService(str(root), python='python3', spawn_process=spawn, get_identity=lambda: {},
                            verify_inputs=lambda _: None)
    submitted = service.submit(REQUEST)
    job_id = submitted['job']['id']
    key = submitted['job']['key']
    assert service.cancel(job_id)
    assert service.get(job_id)['status'] == 'cancelling'
    assert service.busy and service.execution_slot.busy

    other = {**REQUEST, 'radius_mm': 40}
    busy_reply = service.submit(other)
    assert busy_reply.get('busy') is True

    # Even if the worker emits a valid result before exiting, cancellation prevents caching it.
    children[0].emit_stdout(jsjson.stringify({'type': 'result', 'result': result_for(REQUEST)}) + '\n')
    children[0].close(0, 'SIGTERM')

    final = service.get(job_id)
    assert final['status'] == 'cancelled'
    assert not service.busy and not service.execution_slot.busy
    assert service.read_cache(key, REQUEST) is None
    assert service.lookup(REQUEST) == {'hit': False}


def test_wall_clock_timeout_terminates_the_worker_and_returns_a_non_numeric_failure(tmp_path: Path):
    """check-local-compute.mjs::wall-clock timeout terminates the worker and returns a non-numeric failure."""
    root = _radius_root(tmp_path)
    children: list[FakeChild] = []

    def spawn(exe: str, args: list[str], opts: dict) -> FakeChild:
        c = FakeChild(pid=6100)
        children.append(c)
        return c

    service = RadiusService(str(root), python='python3', timeout_ms=30, spawn_process=spawn,
                            get_identity=lambda: {}, verify_inputs=lambda _: None)
    job_id = service.submit(REQUEST)['job']['id']
    _wait_until(lambda: bool(children and 'SIGTERM' in children[0].signals), timeout=2.0)
    children[0].close(None, 'SIGTERM')

    final = service.get(job_id)
    assert final['status'] == 'timeout'
    assert final['result'] is None
    assert '未把缺失结果写成0' in final['message']
    assert service.lookup(REQUEST) == {'hit': False}


def test_malformed_or_mismatched_worker_output_fails_without_crashing_the_server(tmp_path: Path):
    """check-local-compute.mjs::malformed or mismatched worker output fails without crashing the server."""
    root = _radius_root(tmp_path)
    children: list[FakeChild] = []

    def spawn(exe: str, args: list[str], opts: dict) -> FakeChild:
        c = FakeChild(pid=7000 + len(children))
        children.append(c)
        return c

    service = RadiusService(str(root), python='python3', spawn_process=spawn, get_identity=lambda: {},
                            verify_inputs=lambda _: None)

    # 1. Malformed non-JSON output + non-zero exit
    first_id = service.submit(REQUEST)['job']['id']
    children[0].emit_stdout('not valid json\n')
    children[0].close(1, None)
    first = service.get(first_id)
    assert first['status'] == 'failed' and first['result'] is None

    # 2. Mismatched request in worker result + zero exit
    second_id = service.submit(REQUEST)['job']['id']
    wrong = result_for({**REQUEST, 'radius_mm': 45})
    children[1].emit_stdout(jsjson.stringify({'type': 'result', 'result': wrong}) + '\n')
    children[1].close(0, None)
    second = service.get(second_id)
    assert second['status'] == 'failed' and '结果配置不一致' in second['message']
    assert second['result'] is None

    # 3. Subsequent valid job still succeeds cleanly
    third_id = service.submit(REQUEST)['job']['id']
    children[2].emit_stdout(jsjson.stringify({'type': 'result', 'result': result_for(REQUEST)}) + '\n')
    children[2].close(0, None)
    third = service.get(third_id)
    assert third['status'] == 'completed' and third['result'] is not None


def test_competing_services_share_one_permit_and_result_validation_retains_it_after_process_close(tmp_path: Path):
    """check-worker-lifecycle.mjs::competing services share one permit and result validation retains it after process
    close."""
    root = _radius_root(tmp_path)
    slot = ExecutionSlot()
    store = RecordStore(str(root))
    child = FakeChild(pid=8001)

    entered_write = threading.Event()
    allow_write = threading.Event()
    competing_attempt: list[Optional[Callable[[], None]]] = []

    class SlowCacheStore(RecordStore):
        def write(self, path: str, value: Any) -> None:
            if path.endswith('/cache.json'):
                entered_write.set()
                competing_attempt.append(slot.acquire('competing-service'))
                allow_write.wait(timeout=3.0)
            super().write(path, value)

    slow_store = SlowCacheStore(str(root))
    service_a = RadiusService(str(root), python='python3', store=slow_store, execution_slot=slot,
                              spawn_process=lambda *_: child, get_identity=lambda: {}, verify_inputs=lambda _: None)
    service_b = RadiusService(str(root), python='python3', store=store, execution_slot=slot,
                              spawn_process=lambda *_: FakeChild(pid=8002), get_identity=lambda: {},
                              verify_inputs=lambda _: None)

    job_id = service_a.submit(REQUEST)['job']['id']
    # Competing service cannot start while service_a holds the shared slot.
    assert service_b.submit({**REQUEST, 'radius_mm': 45}).get('busy') is True

    child.emit_stdout(jsjson.stringify({'type': 'result', 'result': result_for(REQUEST)}) + '\n')
    closer = threading.Thread(target=lambda: child.close(0, None))
    closer.start()
    assert entered_write.wait(timeout=3.0)
    # Process has closed, yet cache validation/storage still holds the shared permit!
    assert competing_attempt == [None]
    assert slot.busy
    allow_write.set()
    closer.join(timeout=3.0)

    assert not slot.busy
    assert service_a.get(job_id)['status'] == 'completed'


def test_spawn_and_durable_write_failures_release_the_permit_without_a_success_result(tmp_path: Path):
    """check-worker-lifecycle.mjs::spawn and durable-write failures release the permit without a success result."""
    root = _radius_root(tmp_path)
    slot = ExecutionSlot()

    def broken_spawn(*_: Any) -> Any:
        raise OSError('spawn failed immediately')

    service_spawn_fail = RadiusService(str(root), python='python3', execution_slot=slot,
                                       spawn_process=broken_spawn, get_identity=lambda: {},
                                       verify_inputs=lambda _: None)
    failed_spawn = service_spawn_fail.submit(REQUEST)['job']
    assert failed_spawn['status'] == 'failed'
    assert '无法启动Python' in failed_spawn['message']
    assert not slot.busy

    class BrokenCacheStore(RecordStore):
        def write(self, path: str, value: Any) -> None:
            if path.endswith('/cache.json'):
                raise OSError('ENOSPC simulated disk full')
            super().write(path, value)

    child = FakeChild(pid=8200)
    service_write_fail = RadiusService(str(root), python='python3', store=BrokenCacheStore(str(root)),
                                       execution_slot=slot, spawn_process=lambda *_: child,
                                       get_identity=lambda: {}, verify_inputs=lambda _: None)
    job_id = service_write_fail.submit(REQUEST)['job']['id']
    child.emit_stdout(jsjson.stringify({'type': 'result', 'result': result_for(REQUEST)}) + '\n')
    child.close(0, None)

    after = service_write_fail.get(job_id)
    assert after['status'] == 'failed'
    assert after['result'] is None
    assert '计算记录保存失败' in after['message']
    assert not slot.busy


def test_real_process_transport_completes_after_collecting_its_final_event():
    """check-worker-lifecycle.mjs::real process transport completes after collecting its final event."""
    events: list[dict] = []
    done = threading.Event()
    exit_codes: list[Optional[int]] = []

    script = (
        'import json, sys\n'
        'data = json.loads(sys.stdin.read())\n'
        'sys.stdout.write(json.dumps({"type": "progress", "progress": 0.5, "echo": data["n"]}) + "\\n")\n'
        'sys.stdout.flush()\n'
        'sys.stdout.write(json.dumps({"type": "result", "result": {"sum": data["n"] + 1}}))\n'
    )
    handle = start_python_worker(
        executable=sys.executable,
        args=['-c', script],
        input={'n': 41},
        has_input=True,
        on_event=lambda ev: events.append(ev),
        on_close=lambda code, _sig: (exit_codes.append(code), done.set()),
    )
    assert done.wait(timeout=10.0)
    assert handle.closed
    assert exit_codes == [0]
    assert events == [
        {'type': 'progress', 'progress': 0.5, 'echo': 41},
        {'type': 'result', 'result': {'sum': 42}},
    ]


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX process groups only')
def test_worker_completion_waits_for_a_surviving_native_descendant_to_exit(tmp_path: Path):
    """check-worker-lifecycle.mjs::worker completion waits for a surviving native descendant to exit."""
    marker = tmp_path / 'descendant.pid'
    done = threading.Event()
    script = (
        'import os, subprocess, sys, time\n'
        f'p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"], close_fds=True)\n'
        f'open({str(marker)!r}, "w").write(str(p.pid))\n'
        'sys.stdout.write(\'{"type":"result","ok":true}\\n\')\n'
        'sys.stdout.flush()\n'
    )
    start_python_worker(
        executable=sys.executable,
        args=['-c', script],
        kill_after_ms=150,
        on_close=lambda *_: done.set(),
    )
    assert done.wait(timeout=10.0)
    descendant_pid = int(marker.read_text(encoding='utf-8').strip())
    with pytest.raises(ProcessLookupError):
        os.kill(descendant_pid, 0)
