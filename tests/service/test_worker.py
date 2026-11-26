"""Worker transport and computation permit (``eeglayoutlab.jobs.worker``, ``eeglayoutlab.jobs.slot``).

Ports of check-worker-lifecycle.mjs (the maintenance test is retired, R6) and the transport half of
check-local-compute.mjs: where Node drives fake children (an EventEmitter with PassThrough streams), ``FakeChild``
drives the worker the same way through the ``spawn`` hook; the service-level tests run ``Runner``, which takes the
permit and runs the worker as ``LocalComputeQueue`` and ``DesignEvaluationService`` do (permit after the lookup,
released in ``finish``'s ``finally``). Then the installation lock (another holder refuses, the kernel releases a dead
holder's lock, a worker does not inherit it), the bound on completion for workers that escape their group, and
parity with Node's own ``startPythonWorker`` (``parity/worker.mjs``) on scripted fake children and real processes:
every callback, message, diagnostic and close, compared as JSON text.
"""
from __future__ import annotations

import asyncio
import base64
import errno
import fcntl
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time
from typing import Any, Callable, Optional
import uuid

import pytest

from eeglayoutlab.jobs.identity import UNDEFINED
from eeglayoutlab.jobs.records import RecordError, RecordStore
from eeglayoutlab.jobs.slot import LOCK_NAME, ExecutionSlot, InstallationLock, execution_lock_path
from eeglayoutlab.jobs.worker import STDERR_LIMIT, SpawnError, Worker, WorkerError, start_worker
from eeglayoutlab.schemas import jsjson

from schema_parity_support import require

from .key_parity_support import NODE_ENV, needs_node

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/worker.mjs'
PY = sys.executable
SETTLE = 20.0  # seconds any wait may take under load before the test fails


async def until(check: Callable[[], bool], limit: float = SETTLE) -> None:
    deadline = time.monotonic() + limit
    while not check():
        if time.monotonic() > deadline:
            pytest.fail('worker lifecycle did not settle')
        await asyncio.sleep(0.005)


def run(coroutine) -> Any:
    return asyncio.run(coroutine)


def gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def kill(pid: Optional[int]) -> None:
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


# --- fake children ----------------------------------------------------------------------------------------------

class FakeChild:
    """check-worker-lifecycle.mjs's ``fakeChild()``: no pid, kills recorded, streams written by the test."""

    pid = None

    def __init__(self, calls: Optional[list] = None):
        self.signals: list[str] = []
        self.inputs: list[bytes] = []
        self.calls = calls
        self.args: tuple = ()
        self.worker: Optional[Worker] = None

    def spawn(self, worker: Worker, executable: str, args: list, options: dict) -> 'FakeChild':
        self.worker, self.args = worker, (executable, args, options)
        return self

    def kill(self, name: str) -> None:
        self.signals.append(name)
        if self.calls is not None:
            self.calls.append(['kill', name])

    def end_input(self, data: bytes) -> None:
        self.inputs.append(data)

    def resume(self) -> None:
        pass

    # child.stdout.write, child.stderr.write, child.emit('error'), child.stdin.emit('error'), child.emit('close')
    def stdout(self, data: bytes | str) -> None:
        self.worker.feed_stdout(data.encode() if isinstance(data, str) else data)

    def stderr(self, data: bytes | str) -> None:
        self.worker.feed_stderr(data.encode() if isinstance(data, str) else data)

    def error(self, message: str) -> None:
        self.worker.feed_error(WorkerError(message))

    def stdin_error(self, message: str, code: Optional[str] = None) -> None:
        self.worker.feed_stdin_error(WorkerError(message, code))

    def close(self, code: Optional[int] = None, signal_name: Optional[str] = None) -> None:
        self.worker.feed_close(code, signal_name)


class Fake:
    """check-worker-lifecycle.mjs's ``worker(t, override)``."""

    def __init__(self):
        self.child = FakeChild()
        self.events: list = []
        self.logs: list = []
        self.stops: list = []
        self.errors: list = []
        self.diagnostic = ''
        self.closes = 0
        self.instance: Optional[Worker] = None

    async def start(self, **override: Any) -> 'Fake':
        options = dict(timeout=1.0, max_output_bytes=1024, kill_after=0.015, spawn=self.child.spawn,
                       on_event=lambda value, _: self.events.append(value), on_log=self.logs.append,
                       on_stop=self.stops.append, on_error=self.errors.append, on_stderr=self._stderr,
                       on_close=self._close)
        options.update(override)
        self.instance = await start_worker('python', [], **options)
        return self

    def _stderr(self, text: str) -> None:
        self.diagnostic = text

    def _close(self, code: Any, signal_name: Any) -> None:
        self.closes += 1

    def dispose(self) -> None:
        if not self.instance.closed:
            self.child.close(None)


# --- check-worker-lifecycle.mjs --------------------------------------------------------------------------------

def test_execution_permit_is_exclusive_and_idempotent():
    # The pause steps stay: the slot keeps pause/resume for the service's cache-only mode.
    slot = ExecutionSlot()
    release = slot.acquire('first')
    assert slot.busy is True and slot.acquire('second') is None
    slot.pause(); release()
    assert slot.busy is False and slot.acquire('second') is None
    slot.resume()
    second = slot.acquire('second')
    release()
    assert slot.busy is True
    second()
    assert slot.busy is False
    with pytest.raises(TypeError, match='Execution permit requires an owner.'):
        slot.acquire(None)


def test_worker_decodes_split_utf8_and_the_final_unterminated_event():
    async def scenario():
        f = await Fake().start()
        line = (jsjson.stringify({'type': 'progress', 'message': '计算'}) + '\n').encode()
        offset = line.index('计'.encode()) + 1
        f.child.stdout(line[:offset]); f.child.stdout(line[offset:])
        f.child.stdout('native diagnostic\nnull\n' + jsjson.stringify({'type': 'result', 'result': {'value': 2}}))
        f.child.close(0); f.child.close(0)
        assert f.events == [{'type': 'progress', 'message': '计算'}, {'type': 'result', 'result': {'value': 2}}]
        assert f.logs == ['native diagnostic', 'null'] and f.closes == 1
        outcome = await f.instance.wait()
        assert outcome.code == 0 and outcome.result == {'value': 2} and outcome.reason is None
    run(scenario())


def test_stderr_is_bounded_and_spawn_errors_wait_for_actual_close():
    async def scenario():
        f = await Fake().start()
        f.child.stderr('x' * 18000); f.child.error('spawn failed')
        assert len(f.diagnostic) == STDERR_LIMIT == 16000 and f.diagnostic.endswith('spawn failed')
        assert len(f.errors) == 1 and f.instance.closed is False
        f.child.close(-2)
        assert f.closes == 1
        outcome = await f.instance.wait()
        assert (outcome.code, outcome.error, outcome.stderr) == (-2, 'spawn failed', f.diagnostic)
    run(scenario())


def test_timeout_escalates_termination_and_never_closes_before_the_child_closes():
    async def scenario():
        f = await Fake().start(timeout=0.01)
        await until(lambda: len(f.child.signals) == 2)
        assert f.stops == ['timeout'] and f.child.signals == ['SIGTERM', 'SIGKILL']
        assert f.instance.closed is False and f.instance.stop('user') is False
        f.child.close(None)
        assert f.closes == 1
        assert (await f.instance.wait()).reason == 'timeout'
    run(scenario())


def test_output_overflow_and_failed_stdin_stop_once_retaining_capacity_until_close():
    async def scenario():
        overflow = await Fake().start(max_output_bytes=10)
        overflow.child.stdout('x' * 11); overflow.child.stdout('x' * 11)
        assert overflow.stops == ['output_limit'] and overflow.closes == 0
        failed = await Fake().start()
        failed.child.stdin_error('broken pipe', 'EPIPE')
        assert failed.stops == ['input_error'] and failed.child.signals == ['SIGTERM'] and failed.closes == 0
        overflow.dispose(); failed.dispose()
    run(scenario())


# --- run paths over one permit ------------------------------------------------------------------------------------

RADIUS = {'region_count': 2, 'radius_mm': 35, 'mode': 'whole_surface'}
REQUEST = {'region_count': 2, 'radius_mm': 35, 'mode': 'preset', 'mask_codes': ['PL', 'PR']}


class Spawner:
    """``fakeSpawner()``: one fake child per spawn."""

    def __init__(self):
        self.children: list[FakeChild] = []

    def __call__(self, worker: Worker, executable: str, args: list, options: dict) -> FakeChild:
        child = FakeChild()
        self.children.append(child)
        return child.spawn(worker, executable, args, options)


async def _maybe(value: Any) -> Any:
    return await value if asyncio.iscoroutine(value) else value


class Runner:
    """A run path as ``LocalComputeQueue`` (and ``DesignEvaluationService``) uses the permit and the transport:
    ``submit`` takes the permit after the lookup and hands it to the job, ``run`` starts the worker, the close
    decides the status as ``LocalComputeQueue``'s ``onClose`` does, and ``finish`` writes ``job.json`` into the
    job's batch and releases the permit in its ``finally``."""

    def __init__(self, slot: ExecutionSlot, spawn: Callable, root: Path, *, timeout: float = 3.0,
                 validate: Optional[Callable] = None):
        self.slot, self.spawn, self.root, self.timeout = slot, spawn, root, timeout
        self.validate = validate or validate_radius
        self.jobs: dict[str, dict] = {}
        self.active: Optional[dict] = None
        self.submitting = False

    async def submit(self, request: Any) -> dict:
        if self.submitting:
            return {'busy': True}
        self.submitting = True
        release = None
        try:
            if self.active is not None:
                return {'job': self.active} if self.active['request'] == request else {'busy': True}
            release = self.slot.acquire(self)
            if release is None:
                return {'busy': True}
            job = {'id': str(uuid.uuid4()), 'request': request, 'status': 'queued', 'message': None, 'result': None,
                   'release': release, 'cancel_reason': None, 'spawn_error': None, 'worker': None}
            job['batch'] = self.root / job['id']
            job['batch'].mkdir(parents=True)
            self.jobs[job['id']] = job
            self.active = job
            release = None
            await self.run(job)
            return {'job': job}
        finally:
            if release is not None:
                release()
            self.submitting = False

    async def run(self, job: dict) -> None:
        terminal: dict = {'result': None}
        job['status'] = 'running'

        def on_event(event: dict, _: Any) -> None:
            if event.get('type') == 'result':
                terminal['result'] = event.get('result')

        def on_stop(reason: str) -> None:
            job['cancel_reason'], job['status'] = reason, 'cancelling'

        def on_close(code: Any, _: Any) -> None:
            asyncio.ensure_future(self.close(job, code, terminal['result']))
        try:
            job['worker'] = await start_worker(
                PY, ['-u', 'worker.py'], input=job['request'], timeout=self.timeout, max_output_bytes=8 << 20,
                on_event=on_event, on_error=lambda error: job.update(spawn_error=error.message), on_stop=on_stop,
                on_close=on_close, spawn=self.spawn)
        except Exception as error:
            await self.finish(job, 'failed', f'无法启动Python：{error}')

    async def close(self, job: dict, code: Any, result: Any) -> None:
        if job['cancel_reason']:
            timed = job['cancel_reason'] == 'timeout'
            status = 'timeout' if timed else 'failed' if job['cancel_reason'] == 'input_error' else 'cancelled'
            await self.finish(job, status, '达到计算时限，任务已停止；未把缺失结果写成0' if timed else '任务已停止')
        elif code == 0 and isinstance(result, dict) and result.get('status') in ('completed', 'no_layout'):
            try:
                await _maybe(self.validate(result, job['request']))
            except Exception as error:
                await self.finish(job, 'failed', f'计算结果校验失败：{error}')
                return
            job['result'] = result
            await self.finish(job, result['status'], '当前配置已计算')
        else:
            await self.finish(job, 'failed', f"Python启动失败：{job['spawn_error']}" if job['spawn_error']
                              else '计算未成功完成；错误记录已保存，可重新计算')

    async def finish(self, job: dict, status: str, message: str) -> None:
        job['status'], job['message'] = status, message
        try:
            view = {'id': job['id'], 'status': status, 'message': message, 'result': job['result']}
            (job['batch'] / 'job.json').write_text(jsjson.stringify(view), encoding='utf-8')
        except Exception as error:
            job['status'], job['message'], job['result'] = 'failed', f'计算记录保存失败：{error}', None
        finally:
            if self.active is job:
                self.active = None
            release, job['release'] = job['release'], None
            if release is not None:
                release()

    def cancel(self, id: str, reason: str = 'user') -> bool:
        job = self.jobs.get(id)
        if not job or job['status'] not in ('queued', 'running', 'cancelling'):
            return False
        if job['cancel_reason']:
            return True
        if job['worker'] is not None:
            job['worker'].stop(reason)
        return True


def validate_radius(result: Any, request: Any) -> None:
    # jobs.radius needs the service extra (Pydantic); the native runtime suite runs without it.
    from eeglayoutlab.jobs.radius import validate_worker_result
    validate_worker_result(result, request)


def accept(result: Any, request: Any) -> None:
    pass


def complete(child: FakeChild, result: Any) -> None:
    child.stdout(jsjson.stringify({'type': 'result', 'result': result}) + '\n')
    child.close(0)


def test_competing_services_share_one_permit_and_validation_retains_it_after_close(tmp_path):
    async def scenario():
        slot, spawn = ExecutionSlot(), Spawner()
        queue = Runner(slot, spawn, tmp_path / 'radius')
        gate = asyncio.Event()

        async def validate(result: Any, request: Any) -> None:
            await gate.wait()
        design = Runner(slot, spawn, tmp_path / 'design', validate=validate)
        outcomes = await asyncio.gather(queue.submit(RADIUS), design.submit({'n': 1}))
        assert len([value for value in outcomes if value.get('busy')]) == 1 and len(spawn.children) == 1
        owner = queue if queue.active else design
        owner.cancel(owner.active['id'])
        assert slot.busy is True
        spawn.children[0].close(None)
        await until(lambda: not owner.active)
        assert slot.busy is False
        await design.submit({'n': 2})
        spawn.children[1].stdout('{"type":"result","result":{"status":"completed","valid":true}}\n')
        spawn.children[1].close(0)
        await asyncio.sleep(0.01)
        assert slot.busy is True and (await queue.submit(RADIUS))['busy'] is True
        gate.set()
        await until(lambda: not design.active)
        assert slot.busy is False
        assert [job['status'] for job in design.jobs.values()][-1] == 'completed'
    run(scenario())


def test_spawn_and_durable_write_failures_release_the_permit_without_a_success_result(tmp_path):
    async def scenario():
        def broken(*args: Any) -> None:
            raise RuntimeError('executable missing')
        slot = ExecutionSlot()
        queue = Runner(slot, broken, tmp_path / 'broken')
        result = await queue.submit(RADIUS)
        await until(lambda: not queue.active)
        assert queue.jobs[result['job']['id']]['status'] == 'failed' and slot.busy is False
        assert queue.jobs[result['job']['id']]['message'] == '无法启动Python：executable missing'
        spawn = Spawner()
        design = Runner(slot, spawn, tmp_path / 'design')
        job = (await design.submit({'n': 1}))['job']
        for item in job['batch'].iterdir():
            item.unlink()
        job['batch'].rmdir()
        design.cancel(job['id'])
        spawn.children[0].close(None)
        await until(lambda: not design.active)
        assert design.jobs[job['id']]['status'] == 'failed' and slot.busy is False
        assert design.jobs[job['id']]['message'].startswith('计算记录保存失败：')
    run(scenario())


def test_real_process_transport_completes_after_collecting_its_final_event():
    async def scenario():
        events: list = []
        worker = await start_worker(
            PY, ['-c', 'import json, sys; sys.stdout.write(json.dumps({"type": "result", "result": {"ok": True}}))'],
            stdin='ignore', timeout=30.0, max_output_bytes=1024, on_event=lambda event, _: events.append(event))
        outcome = await worker.wait()
        assert outcome.code == 0, outcome.stderr
        assert events == [{'type': 'result', 'result': {'ok': True}}]
    run(scenario())


DESCENDANT = ('import signal, sys, time; signal.signal(signal.SIGTERM, lambda *_: None); '
              'sys.stdout.write("ready"); sys.stdout.flush(); time.sleep(120)')
PARENT = ('import json, subprocess, sys; '
          f'child = subprocess.Popen([sys.executable, "-c", {DESCENDANT!r}], stdin=subprocess.DEVNULL, '
          'stdout=subprocess.PIPE, stderr=subprocess.DEVNULL); child.stdout.read(5); '
          'sys.stdout.write(json.dumps({"type": "progress", "pid": child.pid}) + "\\n"); sys.stdout.flush()')


def test_worker_completion_waits_for_a_surviving_native_descendant_to_exit():
    descendant: list = []

    async def scenario():
        worker = await start_worker(PY, ['-c', PARENT], stdin='ignore', timeout=60.0, kill_after=0.025,
                                    max_output_bytes=1024, on_event=lambda event, _: descendant.append(int(event['pid'])))
        try:
            outcome = await worker.wait()
        finally:
            kill(worker.pid)
        assert outcome.code == 0, outcome.stderr
        assert descendant and gone(descendant[0])
        assert not outcome.escaped
    try:
        run(scenario())
    finally:
        for pid in descendant:
            kill(pid)


# --- check-local-compute.mjs -----------------------------------------------------------------------------------

def test_cancellation_does_not_release_capacity_until_the_child_closes(tmp_path):
    async def scenario():
        spawn = Spawner()
        queue = Runner(ExecutionSlot(), spawn, tmp_path, validate=accept)
        first = await queue.submit(REQUEST)
        assert queue.cancel(first['job']['id']) is True and spawn.children[0].signals == ['SIGTERM']
        assert (await queue.submit({**REQUEST, 'radius_mm': 40}))['busy'] is True
        spawn.children[0].close(None)
        await until(lambda: not queue.active)
        assert queue.jobs[first['job']['id']]['status'] == 'cancelled'
        assert queue.jobs[first['job']['id']]['result'] is None
        await queue.submit(REQUEST)
        assert len(spawn.children) == 2
        complete(spawn.children[1], {'status': 'no_layout', 'request': REQUEST})
        await until(lambda: not queue.active)
    run(scenario())


def test_wall_clock_timeout_terminates_the_worker_with_a_non_numeric_failure(tmp_path):
    async def scenario():
        spawn = Spawner()
        queue = Runner(ExecutionSlot(), spawn, tmp_path, timeout=0.02)
        first = await queue.submit(REQUEST)
        await until(lambda: len(spawn.children[0].signals) > 0)
        spawn.children[0].close(None)
        await until(lambda: not queue.active)
        job = queue.jobs[first['job']['id']]
        assert job['status'] == 'timeout' and job['result'] is None
        assert job['message'] == '达到计算时限，任务已停止；未把缺失结果写成0'
    run(scenario())


def test_malformed_or_mismatched_worker_output_fails_without_crashing(tmp_path):
    require('pydantic')

    async def scenario():
        spawn = Spawner()
        queue = Runner(ExecutionSlot(), spawn, tmp_path)
        first = await queue.submit(REQUEST)
        spawn.children[0].stdout(b'\xff not json\n[1]\n')
        complete(spawn.children[0], {'status': 'completed', 'request': {'command': 'bad'}})
        await until(lambda: not queue.active)
        job = queue.jobs[first['job']['id']]
        assert job['status'] == 'failed' and job['message'].startswith('计算结果校验失败：')
    run(scenario())


# --- the transport's own rules ----------------------------------------------------------------------------------

def test_spawn_errors_follow_nodes_two_paths(tmp_path):
    async def scenario():
        calls: list = []
        worker = await start_worker('/nonexistent/eeg-python', ['-u'], input={'a': 1}, timeout=30.0,
                                    max_output_bytes=1024, on_error=lambda error: calls.append(('error', error.code)),
                                    on_close=lambda code, name: calls.append(('close', code, name)))
        assert calls == [] and worker.pid is None
        outcome = await worker.wait()
        assert calls == [('error', 'ENOENT'), ('close', -2, None)]
        assert outcome.stderr == outcome.error == 'spawn /nonexistent/eeg-python ENOENT'
        with pytest.raises(SpawnError) as raised:
            await start_worker(str(tmp_path / 'file' / 'python'), [], timeout=30.0, max_output_bytes=1024)
        assert str(raised.value) == 'spawn ENOTDIR' and raised.value.code == 'ENOTDIR'
    (tmp_path / 'file').write_text('')
    run(scenario())


def test_input_is_written_as_node_writes_it():
    async def scenario():
        echoes = []
        for value in ({'2': 1, '1': [0.5, -0.0, 1e21], 'a': '文\u2028'}, 'plain \ud800 文', ''):
            worker = await start_worker(
                PY, ['-c', 'import sys; sys.stdout.write(\'{"type":"result","result":"\' + sys.stdin.buffer.read().hex() + \'"}\')'],
                input=value, timeout=30.0, max_output_bytes=1 << 20)
            outcome = await worker.wait()
            echoes.append(bytes.fromhex(outcome.result))
        assert echoes == [b'{"1":[0.5,0,1e+21],"2":1,"a":"\xe6\x96\x87\xe2\x80\xa8"}',
                          'plain \ufffd 文'.encode(), b'']
    run(scenario())


def test_callbacks_that_raise_do_not_break_the_transport(caplog):
    async def scenario():
        def broken(*args: Any) -> None:
            raise RuntimeError('caller bug')
        f = await Fake().start(on_event=broken, on_stderr=broken)
        f.child.stdout('{"type":"progress"}\n'); f.child.stderr('x'); f.child.close(0)
        assert f.closes == 1 and (await f.instance.wait()).code == 0
    run(scenario())
    assert 'caller bug' in caplog.text


ESCAPED = ('import json, subprocess, sys; '
           'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True, '
           'stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL); '
           'sys.stdout.write(json.dumps({"type": "progress", "pid": child.pid}) + "\\n"); sys.stdout.flush()')


def test_an_output_held_outside_the_group_is_bounded():
    # The leader exits 0, but a process that left the group (setsid) keeps stdout open: Node never sees 'close'.
    # Here the timeout stops the worker and completion is forced one grace period after its SIGKILL.
    escaped: list = []

    async def scenario():
        started = time.monotonic()
        worker = await start_worker(PY, ['-c', ESCAPED], stdin='ignore', timeout=2.0, kill_after=0.25,
                                    max_output_bytes=1024, on_event=lambda event, _: escaped.append(int(event['pid'])))
        outcome = await asyncio.wait_for(worker.wait(), SETTLE)
        elapsed = time.monotonic() - started
        assert escaped and not gone(escaped[0])
        assert (outcome.escaped, outcome.reason, outcome.code, outcome.signal) == (True, 'timeout', 0, None)
        assert elapsed >= 2.0 + 2 * 0.25 - 0.05 and worker.closed
    try:
        run(scenario())
    finally:
        for pid in escaped:
            kill(pid)


UNREAPED = r'''
import json, os, time
devnull = os.open(os.devnull, os.O_RDWR)
read, write = os.pipe()
holder = os.fork()
if holder == 0:
    os.dup2(devnull, 0); os.dup2(devnull, 1); os.dup2(devnull, 2)
    member = os.fork()
    if member == 0:
        os._exit(0)
    os.setsid()
    os.write(write, json.dumps({"type": "progress", "pid": os.getpid()}).encode() + b"\n")
    time.sleep(120)
    os._exit(0)
os.close(write)
print(os.read(read, 200).decode().strip(), flush=True)
'''


def test_a_group_that_cannot_empty_is_bounded():
    # A member of the group exits while its parent, which left the group, never reaps it: the group never empties
    # (on macOS killpg then fails with EPERM, which counts as alive, as in Node). Completion is forced at the bound.
    holder: list = []

    async def scenario():
        worker = await start_worker(PY, ['-c', UNREAPED], stdin='ignore', timeout=2.0, kill_after=0.25,
                                    max_output_bytes=1024, on_event=lambda event, _: holder.append(int(event['pid'])))
        outcome = await asyncio.wait_for(worker.wait(), SETTLE)
        assert holder
        assert (outcome.escaped, outcome.code, outcome.reason) == (True, 0, None)
    try:
        run(scenario())
    finally:
        for pid in holder:
            kill(pid)


# --- the installation lock ----------------------------------------------------------------------------------------

HOLDER = ('import fcntl, os, sys; fd = os.open(sys.argv[1], os.O_RDONLY | os.O_CREAT, 0o644); '
          'fcntl.flock(fd, fcntl.LOCK_EX); print("locked", flush=True); sys.stdin.read()')
PROBE = ('import fcntl, os, sys\nfd = os.open(sys.argv[1], os.O_RDONLY)\n'
         'try:\n    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\nexcept BlockingIOError:\n    print("refused")\n'
         'else:\n    print("taken")')


def probe(path: str) -> str:
    return subprocess.run([PY, '-c', PROBE, path], check=True, capture_output=True, text=True, timeout=60).stdout.strip()


def test_lock_lives_beside_the_record_trees(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    path = execution_lock_path(str(root))
    assert path == f'{root}/results/v2/{LOCK_NAME}' and '_jobs' not in path
    slot = ExecutionSlot(InstallationLock(str(root)))
    release = slot.acquire('job')
    assert release is not None and Path(path).is_file()
    for kind in ('radius', 'design', 'editor', 'source', 'sourceV2'):
        assert RecordStore(str(root)).keys(kind) == []
    assert probe(path) == 'refused'
    release()
    release()
    assert probe(path) == 'taken' and not slot.busy


def test_a_second_holder_in_another_process_is_refused_until_it_dies(tmp_path):
    root = tmp_path / 'root'
    (root / 'results/v2').mkdir(parents=True)
    path = execution_lock_path(str(root))
    with subprocess.Popen([PY, '-c', HOLDER, path], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as holder:
        try:
            assert holder.stdout.readline() == b'locked\n'
            slot = ExecutionSlot(InstallationLock(str(root)))
            assert slot.acquire('job') is None and slot.contended is True and slot.busy is False
            holder.kill()
            holder.wait(timeout=60)
            release = slot.acquire('job')
            assert release is not None and slot.contended is False and slot.busy is True
        finally:
            holder.kill()
    other = ExecutionSlot(InstallationLock(str(root)))  # a second workspace in this process
    assert other.acquire('job') is None and other.contended is True
    assert probe(path) == 'refused'
    release()
    assert probe(path) == 'taken'
    assert other.acquire('job') is not None


def test_available_asks_for_the_permit_and_the_lock_without_taking_either(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    path = execution_lock_path(str(root))
    slot = ExecutionSlot(InstallationLock(str(root)))
    assert slot.available() is True and not slot.busy and not slot.lock.held and probe(path) == 'taken'
    other = InstallationLock(str(root))
    assert other.try_acquire()
    assert slot.available() is False and slot.contended is True and not slot.lock.held
    other.release()
    assert slot.available() is True and slot.contended is False
    release = slot.acquire('job')
    assert slot.available() is False and slot.contended is False and slot.lock.held
    release()
    slot.pause()
    assert slot.available() is False
    slot.resume()
    assert slot.available() is True and ExecutionSlot().available() is True


def test_the_lock_is_opened_for_writing_or_read_only_when_this_user_may_not_write_it(tmp_path):
    # flock(2) on Linux NFS is a byte-range lock, and an exclusive one needs a descriptor open for writing.
    root = tmp_path / 'root'
    root.mkdir()
    lock = InstallationLock(str(root))
    assert lock.try_acquire()
    assert fcntl.fcntl(lock._fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDWR
    lock.release()
    if os.geteuid() != 0:
        os.chmod(execution_lock_path(str(root)), 0o444)  # another user's 0644 file, for this user
        assert lock.try_acquire()
        assert fcntl.fcntl(lock._fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
        assert probe(execution_lock_path(str(root))) == 'refused'
        lock.release()


LOCKED_WORKER = r'''
import fcntl, json, os, sys, time
path, sentinel = sys.argv[1], sys.argv[2]
lock = os.stat(path)
inherited = False
for fd in range(3, 256):
    try:
        status = os.fstat(fd)
    except OSError:
        continue
    inherited = inherited or (status.st_dev, status.st_ino) == (lock.st_dev, lock.st_ino)
fd = os.open(path, os.O_RDONLY)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    refused = False
except BlockingIOError:
    refused = True
print(json.dumps({"type": "progress", "inherited": inherited, "refused": refused}), flush=True)
deadline = time.monotonic() + 60
while not os.path.exists(sentinel) and time.monotonic() < deadline:
    time.sleep(0.01)
'''


def test_the_lock_is_held_while_a_worker_runs_and_released_after_it_exits(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    path, sentinel = execution_lock_path(str(root)), tmp_path / 'sentinel'

    async def scenario():
        slot = ExecutionSlot(InstallationLock(str(root)))
        release = slot.acquire('job')
        seen: list = []
        running, closed = asyncio.Event(), asyncio.Event()

        def on_close(code: Any, _: Any) -> None:
            release()
            closed.set()
        worker = await start_worker(PY, ['-c', LOCKED_WORKER, path, str(sentinel)], stdin='ignore', timeout=60.0,
                                    max_output_bytes=1024, on_close=on_close,
                                    on_event=lambda event, _: (seen.append(event), running.set()))
        await asyncio.wait_for(running.wait(), SETTLE)
        assert seen == [{'type': 'progress', 'inherited': False, 'refused': True}]
        assert await asyncio.to_thread(probe, path) == 'refused'
        sentinel.write_text('')
        await asyncio.wait_for(closed.wait(), SETTLE)
        assert (await worker.wait()).code == 0
        assert await asyncio.to_thread(probe, path) == 'taken'
    run(scenario())


def open_descriptors() -> int:
    return len(os.listdir('/dev/fd'))


@pytest.mark.parametrize('call', ['stat', 'fstat'])
def test_an_error_after_the_lock_is_taken_closes_its_descriptor(tmp_path, monkeypatch, call):
    """An error of the check that follows ``flock`` (a permission change, EIO or ESTALE on a network mount) must not
    leave the locked descriptor open with nothing referring to it: the lock would stay taken until the process
    exits, and every later probe, in every workspace of the installation, would find it held."""
    root = tmp_path / 'root'
    root.mkdir()
    path = execution_lock_path(str(root))
    slot = ExecutionSlot(InstallationLock(str(root)))
    assert slot.available() is True
    original = getattr(os, call)
    seen: list = []

    def failing(target: Any, *args: Any, **kwargs: Any) -> Any:
        if call == 'stat':
            mine = target == path
        else:  # the second fstat of the lock's descriptor; the first checks its type before the flock
            mine = isinstance(target, int) and os.path.samestat(original(target), os.stat(path))
        if mine:
            seen.append(target)
            if len(seen) == (1 if call == 'stat' else 2):
                raise OSError(errno.EIO, 'Input/output error', path)
        return original(target, *args, **kwargs)
    before = open_descriptors()
    monkeypatch.setattr(os, call, failing)
    with pytest.raises(OSError) as raised:
        slot.available()
    monkeypatch.undo()
    assert raised.value.errno == errno.EIO
    assert not slot.lock.held and open_descriptors() == before
    assert probe(path) == 'taken'
    assert slot.available() is True and slot.contended is False
    release = slot.acquire('job')
    assert release is not None and probe(path) == 'refused'
    release()


def test_the_lock_refuses_links_and_directories_out_of_the_root(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    linked = tmp_path / 'linked'
    linked.mkdir()
    (linked / 'results').symlink_to(outside, target_is_directory=True)
    # createBatch's refusal (records.mjs:70), which the Node host's run path gives on such a root.
    with pytest.raises(RecordError, match=r'^Record directory leaves the repository\.$'):
        InstallationLock(str(linked)).try_acquire()
    with pytest.raises(RecordError, match=r'^Record directory leaves the repository\.$'):
        ExecutionSlot(InstallationLock(str(linked))).available()
    assert list(outside.iterdir()) == []
    (linked / 'results').unlink()
    (linked / 'results').mkdir()
    (linked / 'results/v2').symlink_to(outside, target_is_directory=True)
    with pytest.raises(RecordError, match=r'^Record directory leaves the repository\.$'):
        ExecutionSlot(InstallationLock(str(linked))).acquire('job')
    assert list(outside.iterdir()) == []
    root = tmp_path / 'root'
    (root / 'results/v2').mkdir(parents=True)
    target = tmp_path / 'target'
    Path(execution_lock_path(str(root))).symlink_to(target)
    with pytest.raises(OSError):
        InstallationLock(str(root)).try_acquire()
    assert not target.exists()
    other = tmp_path / 'other'
    Path(execution_lock_path(str(other))).mkdir(parents=True)
    with pytest.raises(OSError):
        ExecutionSlot(InstallationLock(str(other))).acquire('job')


def outcome(call: Callable[[], Any]) -> Any:
    try:
        call()
        return 'ok'
    except RecordError as error:
        return str(error)
    except OSError as error:
        return errno.errorcode.get(error.errno)


def test_the_lock_resolves_the_root_as_create_batch_does(tmp_path):
    """The lock's directory check is ``createBatch``'s (``realpath(3)``, records.mjs:63-70): on macOS a ``results``
    link whose absolute target spells the root in another case or Unicode normalization resolves inside the root,
    where Node and ``RecordStore.create_batch`` create the batch, so the lock is taken there too; a dangling link
    raises ``ENOENT`` on both."""
    def link(name: str, target: Callable[[Path], Path]) -> Optional[Path]:
        root = tmp_path / name
        (root / 'store/results').mkdir(parents=True)
        spelled = target(root)
        if not spelled.exists():  # a case- or normalization-sensitive volume: the spelling names nothing
            return None
        (root / 'results').symlink_to(spelled, target_is_directory=True)
        return root
    roots = [
        link('root', lambda root: root.with_name('ROOT') / 'store/results'),
        link('caf\u00e9', lambda root: root.with_name('cafe\u0301') / 'store/results'),  # NFC root, NFD link
    ]
    dangling = tmp_path / 'dangling'
    dangling.mkdir()
    (dangling / 'results').symlink_to(tmp_path / 'missing', target_is_directory=True)
    for root, expected in [(root, 'ok') for root in roots if root is not None] + [(dangling, 'ENOENT')]:
        lock = InstallationLock(str(root))
        assert outcome(lock.try_acquire) == expected, root
        lock.release()
        store = RecordStore(str(root))
        assert outcome(lambda: store.create_batch('radius', 'a' * 64, str(uuid.uuid4()))) == expected, root
    assert not (tmp_path / 'missing').exists()


# --- parity with Node ---------------------------------------------------------------------------------------------

def b64(data: bytes | str) -> str:
    return base64.b64encode(data.encode() if isinstance(data, str) else data).decode()


SPLIT = b'a\xe4\xbd\xa0b\xf0\x9f\x98\x80c\xed\xa0\x80d\xf4\x90\x80\x80e\xc0\xaff\xe4\xbdg\xf0\x9f\x98h\xe2\x82i\xff\xfej'
LINES = '\n'.join([
    '{"type":"progress","progress":0.5,"stage":"geometry","message":"真实检查"}\r', '', '   \t', '\ufeff', '\u2028',
    '\xa0{"a":1}', 'true', '0', '""', '{}', '[1]', '1e400', '{"type":"result"}', '{"__proto__":{"x":1},"type":"p"}',
    '{"2":1,"1":2,"b":{"10":0,"9":1},"type":"x"}', '{"type":"result","result":null}', '{"a":1}{"b":2}',
    '{"x":-0,"y":1e21,"z":0.1}', '{"deep":' + '[' * 3000 + ']' * 3000 + '}', '{"type":"result","result":{"v":[1,2]}}',
])


def fake_cases() -> list[dict]:
    base = {'mode': 'fake', 'timeoutMs': 60000, 'maxOutputBytes': 1 << 20}
    line = (jsjson.stringify({'type': 'progress', 'message': '计算'}) + '\n').encode()
    offset = line.index('计'.encode()) + 1
    cases = [
        {'id': 'split_utf8', 'steps': [['stdout', b64(line[:offset])], ['stdout', b64(line[offset:])],
                                        ['stdout', b64('native diagnostic\nnull\n{"type":"result","result":{"value":2}}')],
                                        ['close', 0, None], ['close', 0, None]]},
        {'id': 'stderr_bound', 'steps': [['stderr', b64('x' * 18000)], ['error', 'spawn failed'], ['closed'],
                                          ['close', -2, None]]},
        {'id': 'overflow', 'maxOutputBytes': 10, 'steps': [['stdout', b64('x' * 11)], ['stdout', b64('x' * 11)],
                                                            ['closed'], ['close', None, 'SIGTERM']]},
        {'id': 'overflow_partial', 'maxOutputBytes': 20, 'steps': [['stdout', b64('{"type":"a"}\n{"b"')],
                                                                    ['stdout', b64('z' * 20)], ['stdout', b64('}\n')],
                                                                    ['close', None, 'SIGTERM']]},
        {'id': 'user_then_overflow', 'maxOutputBytes': 20, 'steps': [['stdout', b64('{"type":"partial"')],
                                                                      ['stop', 'user'], ['stdout', b64('y' * 30)],
                                                                      ['stdout', b64('}\n')], ['close', None, 'SIGTERM']]},
        {'id': 'stdin_error', 'steps': [['stdin_error', 'broken pipe', 'EPIPE'], ['closed'], ['stop', 'user'],
                                         ['close', None, 'SIGTERM']]},
        {'id': 'stop_twice', 'steps': [['stop', 'user'], ['stop', 'timeout'], ['stdout', b64('{"type":"progress"}\n')],
                                        ['stdout', b64('{"type":"result","result":1}')], ['close', None, 'SIGTERM'],
                                        ['stop', 'user'], ['closed']]},
        {'id': 'after_close', 'steps': [['stdout', b64('{"a":1}')], ['close', 0, None], ['stdout', b64('{"b":2}\n')],
                                         ['stderr', b64('late')], ['error', 'late error'], ['stop', 'user']]},
        {'id': 'lines', 'steps': [['stdout', b64(LINES + '\n')], ['close', 0, None]]},
        {'id': 'long_log', 'steps': [['stdout', b64('a' * 1999 + '😀' + 'b' * 600 + '\n' + 'é' * 2500 + '\n'
                                                     + '😀' * 1500)], ['close', 0, None]]},
        {'id': 'stderr_surrogates', 'steps': [['stderr', b64('😀' * 9000)], ['stderr', b64('x')],
                                               ['stderr', b64('\xe4'.encode('latin-1') + '文'.encode())],
                                               ['close', 1, None]]},
        {'id': 'append', 'steps': [['stdout', b64('{"type":"progress","append":"E1"}\n')], ['stderr', b64('abc')],
                                    ['stdout', b64('{"append":"E2😀"}')], ['close', 0, None]]},
        {'id': 'input_object', 'input': {'2': 1, '1': [0.5, -0.0], 'a': '文\u2028'}, 'steps': [['close', 0, None]]},
        {'id': 'input_string', 'input': 'plain \ud800 文', 'steps': [['close', 0, None]]},
        {'id': 'input_empty', 'input': '', 'steps': [['close', 0, None]]},
        {'id': 'truncated_at_close', 'steps': [['stdout', b64(b'{"t":"\xe4\xbd')], ['stderr', b64(b'abc\xf0\x9f')],
                                                ['close', 0, None]]},
    ]
    for i in range(len(SPLIT) + 1):
        out = b'{"type":"progress","message":"' + SPLIT + b'"}\nlog ' + SPLIT + b'\n'
        cut = out.index(SPLIT) + i
        cases.append({'id': f'decode_stdout_{i}', 'steps': [['stdout', b64(out[:cut])], ['stdout', b64(out[cut:])],
                                                            ['close', 0, None]]})
        cases.append({'id': f'decode_stderr_{i}', 'steps': [['stderr', b64(SPLIT[:i])], ['stderr', b64(SPLIT[i:])],
                                                            ['close', 0, None]]})
    cases.append({'id': 'decode_bytes', 'steps': [['stderr', b64(bytes([byte]))] for byte in SPLIT]
                  + [['stdout', b64(bytes([byte]))] for byte in b'{"m":"' + SPLIT + b'"}\n'] + [['close', 0, None]]})
    # Random bytes, mostly lead and continuation bytes, in random chunks, through both decoders.
    pieces = [bytes([b]) for b in range(0x80, 0x100)] + [b'a', b'\n', b'"', '文'.encode(), '😀'.encode(), b'{"m":"']
    rng = random.Random(20261123)
    for n in range(80):
        steps = [[rng.choice(('stdout', 'stderr')), b64(b''.join(rng.choice(pieces) for _ in range(rng.randrange(1, 9))))]
                 for _ in range(rng.randrange(1, 7))]
        cases.append({'id': f'decode_random_{n}', 'steps': steps + [['close', 0, None]]})
    return [{**base, **case} for case in cases]


async def python_fake(spec: dict) -> dict:
    calls: list = []
    child = FakeChild(calls)
    mask = spec.get('mask', [])

    def on_event(event: dict, diagnostic: Callable) -> None:
        calls.append(['event', masked(event, mask)])
        if isinstance(event.get('append'), str):
            diagnostic(event['append'])
    instance = await start_worker(
        'python', [], input=spec.get('input', UNDEFINED), timeout=spec['timeoutMs'] / 1000,
        max_output_bytes=spec['maxOutputBytes'], kill_after=spec.get('killAfterMs', 2000) / 1000, spawn=child.spawn,
        on_event=on_event, on_log=lambda text: calls.append(['log', text]),
        on_stderr=lambda text: calls.append(['stderr', text]), on_error=lambda error: calls.append(['error', error.message]),
        on_stop=lambda reason: calls.append(['stop', reason]),
        on_close=lambda code, name: calls.append(['close', code, name]))
    for kind, *args in spec['steps']:
        if kind == 'stdout':
            child.stdout(base64.b64decode(args[0]))
        elif kind == 'stderr':
            child.stderr(base64.b64decode(args[0]))
        elif kind == 'error':
            child.error(args[0])
        elif kind == 'stdin_error':
            child.stdin_error(args[0], args[1])
        elif kind == 'close':
            child.close(args[0], args[1])
        elif kind == 'stop':
            calls.append(['stopped', instance.stop(args[0])])
        elif kind == 'closed':
            calls.append(['closed', instance.closed])
    if not instance.closed:
        child.close(None, None)
    calls.append(['input', b64(b''.join(child.inputs))])
    return {'calls': calls}


def masked(event: dict, mask: list) -> dict:
    return {key: (None if key in mask else value) for key, value in event.items()}


def real_cases(tmp_path: Path) -> list[dict]:
    script = tmp_path / 'noexec'
    script.write_text('echo \'{"type":"result","result":"sh"}\'\n')
    script.chmod(0o755)
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'eeg-worker-probe').write_text('#!/bin/sh\necho \'{"type":"result","result":"found"}\'\n')
    (bin_dir / 'eeg-worker-probe').chmod(0o755)
    env = {'PATH': os.environ.get('PATH', os.defpath), 'EEG_PROBE': 'v文'}
    echo = 'import sys; sys.stdout.write(\'{"type":"result","result":"\' + sys.stdin.buffer.read().hex() + \'"}\')'
    base = {'mode': 'real', 'executable': PY, 'timeoutMs': 60000, 'maxOutputBytes': 1 << 20}
    cases = [
        {'id': 'events', 'stdin': 'ignore', 'args': ['-c', 'import sys; sys.stdout.write(sys.argv[1])', LINES]},
        {'id': 'exit_code', 'args': ['-c', 'import sys; sys.stderr.write("boom 文"); sys.exit(3)']},
        {'id': 'self_kill', 'args': ['-c', 'import os, signal; os.kill(os.getpid(), signal.SIGKILL)']},
        {'id': 'output_limit', 'maxOutputBytes': 1000,
         'args': ['-c', 'import sys, time; sys.stdout.write("x" * 5000); sys.stdout.flush(); time.sleep(60)']},
        {'id': 'timeout', 'timeoutMs': 500, 'args': ['-c', 'import time; time.sleep(60)']},
        # The shell ignores SIGTERM at once, and the interpreter it becomes inherits that.
        {'id': 'timeout_kill', 'executable': '/bin/sh', 'timeoutMs': 2000, 'killAfterMs': 300,
         'args': ['-c', f"trap '' TERM; exec '{PY}' -c 'import time; time.sleep(60)'"]},
        {'id': 'descendant', 'stdin': 'ignore', 'killAfterMs': 100, 'mask': ['pid'], 'args': ['-c', PARENT]},
        {'id': 'input_object', 'input': {'2': 1, '1': [0.5, -0.0, 1e21], 'a': '文\u2028'}, 'args': ['-c', echo]},
        {'id': 'input_string', 'input': 'plain \ud800 文', 'args': ['-c', echo]},
        {'id': 'stdin_closed', 'input': 'x' * 1_000_000,
         'args': ['-c', 'import os, time; os.close(0); time.sleep(60)']},
        {'id': 'stdin_ignore', 'stdin': 'ignore',
         'args': ['-c', 'import sys; print(\'{"type":"result","result":%d}\' % len(sys.stdin.read()))']},
        {'id': 'stdin_open', 'args': ['-c', 'import select, sys; ready = select.select([sys.stdin], [], [], 0.3)[0]; '
                                            'print(\'{"type":"result","result":%s}\' % ("true" if ready else "false"))']},
        {'id': 'spawn_enoent', 'executable': '/nonexistent/eeg-python', 'input': {'a': 1}, 'args': ['-u']},
        {'id': 'spawn_eacces', 'executable': str(tmp_path), 'args': []},
        {'id': 'cwd_missing', 'cwd': str(tmp_path / 'missing'), 'args': ['-c', 'print(1)']},
        {'id': 'spawn_enotdir', 'executable': str(script / 'python'), 'args': []},
        {'id': 'no_shebang', 'executable': str(script), 'args': []},
        {'id': 'bare_name', 'executable': 'eeg-worker-probe', 'env': {**env, 'PATH': f'{bin_dir}:{env["PATH"]}'},
         'args': []},
        {'id': 'env_cwd', 'env': env, 'cwd': str(tmp_path), 'args': ['-c', (
            'import json, os; print(json.dumps({"type": "result", "result": [os.getcwd(), os.environ.get("EEG_PROBE"), '
            '"HOME" in os.environ, os.getpgrp() == os.getpid(), os.getsid(0) == os.getpid()]}))')]},
        {'id': 'stop_user', 'stopOnEvent': 'user',
         'args': ['-c', 'import time; print(\'{"type":"progress"}\', flush=True); time.sleep(60)']},
        {'id': 'invalid_utf8', 'args': ['-c', (
            'import os; os.write(1, b\'{"type":"progress","message":"a\\xff\\xfeb\\xe4\\xbd"}\\nbad \\xed\\xa0\\x80 line\\n'
            '{"type":"result","result":"\\xf0\\x9f\\x98"}\'); '
            'os.write(2, b"err \\xc3\\x28 \\xe2\\x82 \\xf4\\x90\\x80\\x80 end \\xe4")')]},
        {'id': 'stderr_tail', 'args': ['-c', 'import sys; sys.stderr.write("a" + "😀" * 10000); sys.stderr.flush(); sys.exit(1)']},
        {'id': 'many_events', 'args': ['-c', (
            'import json, sys\nfor i in range(3000):\n    sys.stdout.write(json.dumps({"type": "progress", "progress": i / 3000, '
            '"message": "步" * (i % 7)}) + "\\n")\nsys.stdout.write(json.dumps({"type": "result", "result": {"n": 3000}}))')]},
    ]
    return [{**base, **case} for case in cases]


async def python_real(spec: dict) -> dict:
    record: dict = {'events': [], 'logs': [], 'stderr': None, 'errors': [], 'stops': [], 'stopped': [],
                    'close': None, 'closes': 0}
    holder: dict = {}
    mask = spec.get('mask', [])

    def on_event(event: dict, diagnostic: Callable) -> None:
        record['events'].append(masked(event, mask))
        if isinstance(event.get('append'), str):
            diagnostic(event['append'])
        if spec.get('stopOnEvent') and not record['stopped']:
            record['stopped'] += [holder['worker'].stop(spec['stopOnEvent']), holder['worker'].stop('again')]

    def on_close(code: Any, name: Any) -> None:
        record['closes'] += 1
        record['close'] = [code, name]
    try:
        worker = await start_worker(
            spec['executable'], spec['args'], cwd=spec.get('cwd'), env=spec.get('env'), stdin=spec.get('stdin', 'pipe'),
            input=spec.get('input', UNDEFINED), timeout=spec['timeoutMs'] / 1000, max_output_bytes=spec['maxOutputBytes'],
            kill_after=spec.get('killAfterMs', 2000) / 1000, on_event=on_event,
            on_log=record['logs'].append, on_stderr=lambda text: record.__setitem__('stderr', text),
            on_error=lambda error: record['errors'].append(error.message), on_stop=record['stops'].append,
            on_close=on_close)
    except SpawnError as error:
        return {'thrown': error.message, 'code': error.code}
    holder['worker'] = worker
    await worker.wait()
    await asyncio.sleep(0.1)
    return record


def run_driver(cases: list[dict], scratch: Path) -> dict[str, str]:
    spec_path, out_path = scratch / 'worker-spec.json', scratch / 'worker-node.json'
    spec_path.write_text(jsjson.stringify({'cases': cases}), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV,
                   timeout=600)
    output = jsjson.parse(out_path.read_text(encoding='utf-8'))
    return {case['id']: case['text'] for case in output['cases']}


@needs_node
def test_fake_children_match_node(tmp_path):
    cases = fake_cases()
    node = run_driver(cases, tmp_path)

    async def python() -> dict[str, str]:
        return {case['id']: jsjson.stringify(await python_fake(case)) for case in cases}
    ours = run(python())
    assert set(node) == set(ours)
    assert {key: (ours[key], node[key]) for key in node if ours[key] != node[key]} == {}


@needs_node
def test_real_processes_match_node(tmp_path):
    cases = real_cases(tmp_path)
    node = run_driver(cases, tmp_path)

    async def python() -> dict[str, str]:
        return {case['id']: jsjson.stringify(await python_real(case)) for case in cases}
    ours = run(python())
    assert set(node) == set(ours)
    assert {key: (ours[key], node[key]) for key in node if ours[key] != node[key]} == {}
    record = jsjson.parse(ours['env_cwd'])
    assert record['events'][0]['result'][1:] == ['v文', False, True, True]
