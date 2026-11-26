"""Shared execution slot and bounded NDJSON Python worker transport (phase 2 slice 4).

Ports ``webapp/server/jobs/execution-slot.mjs`` and ``webapp/server/jobs/python-worker.mjs``:

- ``ExecutionSlot``: one exclusive process permit per workspace/application, held through result verification and
  durable storage; releasing a permit is idempotent and affects only its own token.
- ``start_python_worker``: spawns a child process without a shell (in its own POSIX process group when using the
  real ``subprocess.Popen``), decodes split UTF-8 chunks incrementally, enforces ``max_output_bytes`` on raw
  stdout bytes, bounds ``stderr`` diagnostics to 16,000 characters, escalates ``SIGTERM`` to ``SIGKILL`` after
  ``kill_after_ms``, and waits for any surviving native descendant in the worker's process group to exit before
  completing ``on_close``.
"""
from __future__ import annotations

import codecs
import errno
import inspect
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Optional

from ..schemas import jsjson

__all__ = ['ExecutionSlot', 'execution_slot_for', 'WorkerHandle', 'start_python_worker']


class ExecutionSlot:
    """One process permit per application; held through result verification and storage."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: Optional[object] = None

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._owner is not None

    def acquire(self, owner: Any) -> Optional[Callable[[], None]]:
        if owner is None:
            raise TypeError('Execution permit requires an owner.')
        with self._lock:
            if self._owner is not None:
                return None
            token = object()
            self._owner = token

        def release() -> None:
            with self._lock:
                if self._owner is token:
                    self._owner = None

        return release


def execution_slot_for(holder: Any) -> ExecutionSlot:
    slot = getattr(holder, 'execution_slot', None)
    if slot is None:
        slot = ExecutionSlot()
        holder.execution_slot = slot
    return slot


class WorkerHandle:
    """Returned by ``start_python_worker``."""

    def __init__(self, child: Any, stop_fn: Callable[[str], bool], is_closed: Callable[[], bool]):
        self.child = child
        self._stop = stop_fn
        self._is_closed = is_closed

    def stop(self, reason: str = 'user') -> bool:
        return self._stop(reason)

    @property
    def closed(self) -> bool:
        return self._is_closed()


def _accepts_two_args(fn: Callable[..., Any]) -> bool:
    try:
        params = list(inspect.signature(fn).parameters.values())
    except (TypeError, ValueError):
        return False
    if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
        return True
    positional = [p for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                                  inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    return len(positional) >= 2


def _default_spawn(executable: str, args: list[str], options: dict[str, Any]) -> subprocess.Popen[bytes]:
    stdio = options.get('stdio', ('pipe', 'pipe', 'pipe'))
    stdin_opt = subprocess.PIPE if stdio[0] == 'pipe' else subprocess.DEVNULL
    stdout_opt = subprocess.PIPE if len(stdio) < 2 or stdio[1] == 'pipe' else subprocess.DEVNULL
    stderr_opt = subprocess.PIPE if len(stdio) < 3 or stdio[2] == 'pipe' else subprocess.DEVNULL
    return subprocess.Popen(
        [executable, *args],
        cwd=options.get('cwd'),
        env=options.get('env'),
        stdin=stdin_opt,
        stdout=stdout_opt,
        stderr=stderr_opt,
        shell=False,
        start_new_session=bool(options.get('detached', os.name != 'nt')),
    )


def start_python_worker(
    *,
    executable: str,
    args: list[str],
    options: Optional[dict[str, Any]] = None,
    input: Any = None,
    has_input: bool = False,
    timeout_ms: float = 180000,
    max_output_bytes: int = 8 * 1024 * 1024,
    kill_after_ms: float = 2000,
    spawn_process: Optional[Callable[..., Any]] = None,
    on_event: Callable[..., None] = lambda event, *_: None,
    on_log: Callable[[str], None] = lambda text: None,
    on_stderr: Callable[[str], None] = lambda text: None,
    on_error: Callable[[BaseException], None] = lambda err: None,
    on_stop: Callable[[str], None] = lambda reason: None,
    on_close: Callable[[Optional[int], Optional[str]], None] = lambda code, sig: None,
) -> WorkerHandle:
    opts = dict(options or {})
    real_spawn = spawn_process is None
    process_group = sys.platform != 'win32' and real_spawn
    spawner = spawn_process or _default_spawn
    child = spawner(executable, list(args), {**opts, 'detached': process_group, 'shell': False})

    lock = threading.RLock()
    stdout_decoder = codecs.getincrementaldecoder('utf-8')('replace')
    stderr_decoder = codecs.getincrementaldecoder('utf-8')('replace')
    buffer = ''
    bytes_seen = 0
    diagnostic = ''
    reason: Optional[str] = None
    closed = False
    close_seen = False
    kill_timer: Optional[threading.Timer] = None
    event_two_args = _accepts_two_args(on_event)

    def append_diagnostic(text: str) -> None:
        nonlocal diagnostic
        with lock:
            diagnostic = (diagnostic + text)[-16000:]
            current = diagnostic
        on_stderr(current)

    def report_error(err: BaseException) -> None:
        append_diagnostic(str(err))
        on_error(err)

    def group_alive() -> bool:
        pid = getattr(child, 'pid', None)
        if not process_group or type(pid) is not int or pid <= 0:
            return False
        try:
            os.kill(-pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as err:
            return err.errno != errno.ESRCH

    def send_signal(sig_name: str) -> None:
        sig_num = getattr(signal, sig_name, signal.SIGTERM)
        pid = getattr(child, 'pid', None)
        try:
            if process_group and type(pid) is not int:
                return
            if process_group and type(pid) is int and pid > 0:
                os.kill(-pid, sig_num)
            elif hasattr(child, 'kill_signal'):
                child.kill_signal(sig_name)
            elif real_spawn and hasattr(child, 'send_signal'):
                child.send_signal(sig_num)
            elif hasattr(child, 'kill'):
                child.kill(sig_name)
        except ProcessLookupError:
            pass
        except OSError as err:
            if err.errno != errno.ESRCH:
                report_error(err)
        except BaseException as err:  # noqa: BLE001
            report_error(err)

    def schedule_kill() -> threading.Timer:
        timer = threading.Timer(max(0.001, kill_after_ms / 1000.0), lambda: send_signal('SIGKILL'))
        timer.daemon = True
        timer.start()
        return timer

    def stop(stop_reason: str) -> bool:
        nonlocal reason, kill_timer
        with lock:
            if closed or reason is not None:
                return False
            reason = stop_reason
        on_stop(stop_reason)
        send_signal('SIGTERM')
        with lock:
            if not closed:
                kill_timer = schedule_kill()
        return True

    def parse_line(line: str) -> None:
        if not jsjson.js_trim(line):
            return
        try:
            event = jsjson.parse(line)
        except ValueError:
            on_log(line[:2000])
            return
        if not isinstance(event, dict):
            on_log(line[:2000])
            return
        if event_two_args:
            on_event(event, append_diagnostic)
        else:
            on_event(event)

    timeout_timer = threading.Timer(max(0.001, timeout_ms / 1000.0), lambda: stop('timeout'))
    timeout_timer.daemon = True
    timeout_timer.start()

    def handle_stdout_chunk(chunk: bytes | str) -> None:
        nonlocal buffer, bytes_seen
        raw = chunk.encode('utf-8') if isinstance(chunk, str) else bytes(chunk)
        with lock:
            if close_seen or reason == 'output_limit':
                return
            bytes_seen += len(raw)
            if bytes_seen > max_output_bytes:
                over = True
            else:
                over = False
                decoded = stdout_decoder.decode(raw, final=False)
                combined = buffer + decoded
                lines = combined.split('\n')
                buffer = lines.pop()
        if over:
            stop('output_limit')
            return
        for line in lines:
            parse_line(line)

    def handle_stderr_chunk(chunk: bytes | str) -> None:
        raw = chunk.encode('utf-8') if isinstance(chunk, str) else bytes(chunk)
        with lock:
            if close_seen:
                return
            decoded = stderr_decoder.decode(raw, final=False)
        if decoded:
            append_diagnostic(decoded)

    def finalize_close(code: Optional[int], exit_signal: Optional[str] = None) -> None:
        nonlocal close_seen, closed, kill_timer
        with lock:
            if close_seen:
                return
            close_seen = True
            stop_reason = reason
            tail_out = '' if stop_reason == 'output_limit' else buffer + stdout_decoder.decode(b'', final=True)
            tail_err = stderr_decoder.decode(b'', final=True)
        timeout_timer.cancel()
        if stop_reason != 'output_limit' and tail_out:
            for part in tail_out.split('\n'):
                parse_line(part)
        if tail_err:
            append_diagnostic(tail_err)

        def complete() -> None:
            nonlocal closed
            with lock:
                if closed:
                    return
                closed = True
                kt = kill_timer
            if kt is not None:
                kt.cancel()
            on_close(code, exit_signal)

        if group_alive():
            send_signal('SIGTERM')
            with lock:
                if kill_timer is None:
                    kill_timer = schedule_kill()

            def wait_descendants() -> None:
                while group_alive():
                    time.sleep(0.025)
                complete()

            threading.Thread(target=wait_descendants, name='worker-group-reap', daemon=True).start()
        else:
            complete()

    if real_spawn:
        def pump_stream(stream: Any, handler: Callable[[bytes], None]) -> None:
            if stream is None:
                return
            try:
                while True:
                    chunk = os.read(stream.fileno(), 65536)
                    if not chunk:
                        break
                    handler(chunk)
            except OSError:
                pass
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        out_thread = threading.Thread(target=pump_stream, args=(child.stdout, handle_stdout_chunk),
                                      name='worker-stdout', daemon=True)
        err_thread = threading.Thread(target=pump_stream, args=(child.stderr, handle_stderr_chunk),
                                      name='worker-stderr', daemon=True)
        out_thread.start()
        err_thread.start()

        if has_input or input is not None:
            payload = (input if isinstance(input, str) else jsjson.stringify(input)).encode('utf-8')
            if child.stdin is not None:
                try:
                    child.stdin.write(payload)
                    child.stdin.close()
                except BaseException as err:  # noqa: BLE001
                    try:
                        child.stdin.close()
                    except OSError:
                        pass
                    report_error(err)
                    stop('input_error')
        elif child.stdin is not None:
            try:
                child.stdin.close()
            except OSError:
                pass

        def wait_process() -> None:
            rc = child.wait()
            out_thread.join(timeout=2.0)
            err_thread.join(timeout=2.0)
            sig_name: Optional[str] = None
            if rc < 0:
                try:
                    sig_name = signal.Signals(-rc).name
                except ValueError:
                    sig_name = str(-rc)
            finalize_close(rc, sig_name)

        threading.Thread(target=wait_process, name='worker-wait', daemon=True).start()
    else:
        # Driven fake child for deterministic unit tests (mirrors Node EventEmitter/PassThrough child).
        child._attach_handlers(
            on_stdout=handle_stdout_chunk,
            on_stderr=handle_stderr_chunk,
            on_error=report_error,
            on_stdin_error=lambda err: (report_error(err), stop('input_error')),
            on_close=finalize_close,
        )
        if has_input or input is not None:
            payload_str = input if isinstance(input, str) else jsjson.stringify(input)
            try:
                child.write_stdin(payload_str)
            except BaseException as err:  # noqa: BLE001
                report_error(err)
                stop('input_error')

    return WorkerHandle(child, stop, lambda: closed)
