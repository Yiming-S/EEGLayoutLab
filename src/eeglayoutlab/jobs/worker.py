"""Bounded NDJSON worker transport: Node's ``jobs/python-worker.mjs`` (``startPythonWorker``) for asyncio, statement
by statement. Scientific event and result rules belong to callers.

``await start_worker(executable, args, ...)`` spawns the worker with the shell off, in a new session, so it leads a
process group as Node's ``detached`` child does, and returns a ``Worker`` once the child exists (Node's call
returns synchronously; nothing is delivered to the callbacks before it returns). Then, as in Node:

- stdin gets ``input`` when it is given: a string as it is, any other value as ``JSON.stringify`` writes it, UTF-8,
  then end of file; a failed write is reported and stops the worker (``input_error``);
- stdout is decoded as a stream (a character split across reads is joined) and split on ``\\n``; each line that is
  not blank (``trim``) is parsed with ``JSON.parse``, an object goes to ``on_event(event, append_diagnostic)`` and
  anything else, as its first 2,000 UTF-16 units, to ``on_log``; the last line counts at close even without
  ``\\n``. Past ``max_output_bytes`` bytes the read that passes is dropped with everything after it, and the worker
  stops (``output_limit``);
- stderr, spawn and signal errors are appended to a diagnostic kept as its last 16,000 UTF-16 units, which
  ``on_stderr`` gets after each append;
- ``stop(reason)`` (first reason wins; ``False`` when already stopping or closed) calls ``on_stop``, sends
  ``SIGTERM`` to the group and ``SIGKILL`` ``kill_after`` seconds later; the timeout stops with ``timeout``;
- ``on_close(code, signal)`` comes once, when the child has exited and closed stdout and stderr, and the whole
  process group has exited: a surviving descendant gets ``SIGTERM``, then ``SIGKILL``, and the group is polled every
  25 ms. So a computation permit is not released while a native descendant still runs.

Spawn errors keep Node's two paths: ``ENOENT``, ``EACCES``, ``EAGAIN``, ``EMFILE`` and ``ENFILE`` (also for a
missing working directory) are reported as ``spawn <executable> <CODE>`` and followed by a close with the negative
error number, as libuv reports them; any other error raises ``SpawnError`` (``spawn <CODE>``) from
``start_worker``, as Node's ``spawn`` throws. Executables are found as libuv finds them: Python's own search on
macOS (``posix_spawn``), glibc's ``execvp`` elsewhere (``jobs.fingerprint``).

``spawn`` replaces the process for tests, as Node's ``spawnProcess`` does: it gets ``(worker, executable, args,
options)`` and returns a child with ``pid``, ``kill(signal_name)``, ``end_input(data)`` and ``resume()``, and drives
the worker through ``feed_stdout``, ``feed_stderr``, ``feed_error``, ``feed_stdin_error`` and ``feed_close``. Such a
child is signalled through ``kill`` and there is no group to wait for, as in Node.

Deliberate difference: an escaped worker cannot hang the service. Node waits for stdout and stderr to close and
for the group to exit without a bound, so a process that leaves the group (``setsid``) while holding an output, or a
member that cannot be killed, keeps the permit forever. Here completion is forced ``timeout + 2 * kill_after``
after the spawn (one grace period after the ``SIGKILL`` the timeout schedules): the outputs are closed, the group
gets ``SIGKILL`` again, and ``on_close`` reports the leader's status (``None`` while it still runs) with
``Outcome.escaped`` set. Known difference: Node's outputs are socket pairs, these are pipes (the child sees a FIFO,
and a write that fills the smaller buffer blocks at another size).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import errno
import inspect
import logging
import os
import signal as signals
import subprocess
import sys
from typing import Any, Callable, Optional, Sequence

from ..schemas import jsjson
from .fingerprint import _EXECVP_SKIP
from .identity import UNDEFINED

__all__ = ['KILL_AFTER_SECONDS', 'STDERR_LIMIT', 'LOG_LIMIT', 'GROUP_POLL_SECONDS', 'WorkerError', 'SpawnError',
           'Outcome', 'Worker', 'start_worker']

KILL_AFTER_SECONDS = 2.0
STDERR_LIMIT = 16000  # UTF-16 units
LOG_LIMIT = 2000  # UTF-16 units
GROUP_POLL_SECONDS = 0.025
# libuv reports these spawn errors as an 'error' event and a close; Node's spawn throws any other.
_REPORTED = frozenset({errno.EACCES, errno.EAGAIN, errno.EMFILE, errno.ENFILE, errno.ENOENT})
_log = logging.getLogger(__name__)


def _code(number: Optional[int]) -> str:
    """libuv's name for an error number."""
    if number == errno.EAGAIN:
        return 'EAGAIN'
    return errno.errorcode.get(number, f'Unknown system error -{number}') if number is not None else 'UNKNOWN'


class WorkerError(Exception):
    """A transport error as Node's ``onError`` sees it: ``message`` is Node's (``spawn python ENOENT``,
    ``write EPIPE``, ``kill EPERM``), ``code`` its error code."""

    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.code = code


class SpawnError(WorkerError):
    """A spawn error Node's ``spawn`` throws (``spawn ENOTDIR``, ``spawn ENOEXEC``)."""


@dataclass(frozen=True)
class Outcome:
    """What ``on_close`` concluded, for callers that await ``Worker.wait()``."""

    code: Optional[int]
    """The exit status; ``None`` after a signal; the negative error number after a reported spawn error."""
    signal: Optional[str]
    """The signal that ended the child (``'SIGTERM'``), or ``None``."""
    reason: Optional[str]
    """The first stop reason: ``timeout``, ``output_limit``, ``input_error`` or the caller's (``user``)."""
    stderr: str
    """The diagnostic: the last 16,000 UTF-16 units of stderr and transport errors."""
    result: Any
    """The ``result`` member of the last event of type ``result``; ``UNDEFINED`` when there was none."""
    error: Optional[str]
    """The message of the last transport error (spawn, stdin, signal), or ``None``."""
    escaped: bool = False
    """Completion was forced at the bound (a process outside the group held an output, or one could not be killed)."""


def _tail(text: str, limit: int) -> str:
    """``text.slice(-limit)`` in UTF-16 units; may leave a lone low surrogate first."""
    if 2 * len(text) <= limit:
        return text
    units = text.encode('utf-16-le', errors='surrogatepass')
    if len(units) <= 2 * limit:
        return text
    return units[-2 * limit:].decode('utf-16-le', errors='surrogatepass')


def _utf8(text: str) -> bytes:
    """A string as Node writes it to a stream: UTF-8 of its UTF-16 units, a lone surrogate as U+FFFD."""
    units = text.encode('utf-16-le', errors='surrogatepass')
    return units.decode('utf-16-le', errors='replace').encode('utf-8')


class _StringDecoder:
    """Node's ``new StringDecoder('utf8')`` (``src/string_decoder.cc``). A character cut at the end of a chunk is
    held back for as many bytes as its lead byte announces (``C0``-``DF`` two, ``E0``-``EF`` three, ``F0``-``F7``
    four, whether or not the sequence can be valid) and decoded alone once they arrive, or as soon as a byte that is
    not a continuation byte comes; everything else is decoded at once (invalid bytes as U+FFFD, as V8 decodes).
    Python's incremental decoder gives the same text in total, but emits a replacement it can already tell
    (``F4 90``, ``C0``) one chunk earlier, which ``on_stderr`` would see."""

    def __init__(self):
        self._missing = 0
        self._buffered = b''

    def write(self, data: bytes) -> str:
        prepend = ''
        if self._missing > 0:
            for i in range(min(len(data), self._missing)):
                if data[i] & 0xC0 != 0x80:
                    # Not the continuation byte it should be: decode what is held, the byte starts a new character.
                    self._missing = 0
                    self._buffered += data[:i]
                    data = data[i:]
                    break
            found = min(len(data), self._missing)
            self._buffered += data[:found]
            data = data[found:]
            self._missing -= found
            if self._missing == 0:
                prepend = self._buffered.decode('utf-8', errors='replace')
                self._buffered = b''
        if not data:
            return prepend
        buffered = 0
        if data[-1] & 0x80:
            # Find where the last character begins and how long its lead byte says it is.
            i = len(data) - 1
            while True:
                buffered += 1
                if data[i] & 0xC0 == 0x80:
                    if buffered >= 4 or i == 0:
                        buffered = 0
                        break
                    i -= 1
                    continue
                if data[i] & 0xE0 == 0xC0:
                    self._missing = 2
                elif data[i] & 0xF0 == 0xE0:
                    self._missing = 3
                elif data[i] & 0xF8 == 0xF0:
                    self._missing = 4
                else:
                    buffered = 0
                    break
                if buffered >= self._missing:
                    self._missing = buffered = 0
                self._missing -= buffered
                break
        if buffered:
            self._buffered = data[len(data) - buffered:]
            data = data[:len(data) - buffered]
        return prepend + data.decode('utf-8', errors='replace')

    def end(self) -> str:
        text = self._buffered.decode('utf-8', errors='replace')
        self._missing, self._buffered = 0, b''
        return text


class Worker:
    """``startPythonWorker``'s state and its return value ``{child, stop, closed}``."""

    def __init__(self, loop: asyncio.AbstractEventLoop, *, timeout: float, max_output_bytes: int,
                 kill_after: float, process_group: bool, on_event: Optional[Callable] = None,
                 on_log: Optional[Callable] = None, on_stderr: Optional[Callable] = None,
                 on_error: Optional[Callable] = None, on_stop: Optional[Callable] = None,
                 on_close: Optional[Callable] = None):
        self._loop = loop
        self._timeout = timeout
        self._max_output_bytes = max_output_bytes
        self._kill_after = kill_after
        self.process_group = process_group
        self._callbacks = {'event': on_event, 'log': on_log, 'stderr': on_stderr, 'error': on_error,
                           'stop': on_stop, 'close': on_close}
        self.child: Any = None
        self._stdout = _StringDecoder()
        self._stderr = _StringDecoder()
        self._buffer = ''
        self._bytes = 0
        self._diagnostic = ''
        self._reason: Optional[str] = None
        self._closed = False
        self._close_seen = False
        self._timer: Optional[asyncio.TimerHandle] = None
        self._bound: Optional[asyncio.TimerHandle] = None
        self._kill_timers: list[asyncio.TimerHandle] = []
        self._group_timer: Optional[asyncio.TimerHandle] = None
        self._status: tuple[Optional[int], Optional[str]] = (None, None)
        self._result: Any = UNDEFINED
        self._error: Optional[str] = None
        self._escaped = False
        self._done: asyncio.Future = loop.create_future()

    # --- the returned object ---------------------------------------------------------------------------------

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pid(self) -> Optional[int]:
        """``child.pid``: ``None`` when the spawn failed."""
        pid = getattr(self.child, 'pid', None)
        return pid if isinstance(pid, int) and not isinstance(pid, bool) else None

    @property
    def reason(self) -> Optional[str]:
        return self._reason

    @property
    def stderr(self) -> str:
        return self._diagnostic

    def stop(self, reason: str) -> bool:
        """``stop(reason)``: ``False`` when closed or already stopping; else ``SIGTERM``, ``SIGKILL`` later."""
        if self._closed or self._reason:
            return False
        self._reason = reason
        self._call('stop', reason)
        self._signal('SIGTERM')
        self._kill_timers.append(self._loop.call_later(self._kill_after, self._signal, 'SIGKILL'))
        return True

    async def wait(self) -> Outcome:
        """The outcome, once ``on_close`` has been called."""
        return await asyncio.shield(self._done)

    # --- Node's closures ---------------------------------------------------------------------------------------

    def _call(self, name: str, *args: Any) -> None:
        # Node's callbacks run inside its event handlers; one that throws must not break the transport here.
        callback = self._callbacks[name]
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            _log.exception('worker %s callback failed', name)

    def append_diagnostic(self, text: str) -> None:
        """``appendDiagnostic(text)``, which ``on_event`` also gets."""
        self._diagnostic = _tail(self._diagnostic + text, STDERR_LIMIT)
        self._call('stderr', self._diagnostic)

    def _report_error(self, error: WorkerError) -> None:
        self._error = error.message
        self.append_diagnostic(error.message)
        self._call('error', error)

    def _group_alive(self) -> bool:
        pid = self.pid
        if not self.process_group or pid is None:
            return False
        try:
            os.killpg(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            return True  # EPERM: a member this user cannot signal is alive

    def _signal(self, name: str) -> None:
        try:
            pid = self.pid
            if self.process_group and pid is not None:
                os.killpg(pid, getattr(signals, name))
            else:
                self.child.kill(name)
        except ProcessLookupError:
            pass
        except OSError as error:
            self._report_error(WorkerError(f'kill {_code(error.errno)}', _code(error.errno)))

    def _parse(self, line: str) -> None:
        if not jsjson.js_trim(line):
            return
        try:
            event = jsjson.parse(line)
        except Exception:
            self._call('log', jsjson.slice_utf16(line, LOG_LIMIT))
            return
        if not isinstance(event, dict):
            self._call('log', jsjson.slice_utf16(line, LOG_LIMIT))
            return
        if event.get('type') == 'result':
            self._result = event.get('result', UNDEFINED)
        self._call('event', event, self.append_diagnostic)

    # --- the child's events --------------------------------------------------------------------------------------

    def feed_stdout(self, chunk: bytes) -> None:
        """``child.stdout`` 'data' (a stream emits no empty chunk)."""
        if not chunk or self._close_seen or self._reason == 'output_limit':
            return
        self._bytes += len(chunk)
        if self._bytes > self._max_output_bytes:
            self.stop('output_limit')
            return
        text = self._stdout.write(bytes(chunk))
        self._buffer += text
        if '\n' in text:
            lines = self._buffer.split('\n')
            self._buffer = lines.pop()
            for line in lines:
                self._parse(line)

    def feed_stderr(self, chunk: bytes) -> None:
        """``child.stderr`` 'data'."""
        if chunk and not self._close_seen:
            self.append_diagnostic(self._stderr.write(bytes(chunk)))

    def feed_error(self, error: BaseException) -> None:
        """``child`` 'error' (a spawn error); the close follows."""
        self._report_error(error if isinstance(error, WorkerError) else WorkerError(str(error)))

    def feed_stdin_error(self, error: BaseException) -> None:
        """``child.stdin`` 'error': a failed input pipe is not evidence that the process has exited."""
        self._report_error(error if isinstance(error, WorkerError) else WorkerError(str(error)))
        self.stop('input_error')

    def feed_close(self, code: Optional[int], signal: Optional[str]) -> None:
        """``child`` 'close' (exited, stdout and stderr closed); later ones are ignored, as ``once`` does."""
        if self._close_seen:
            return
        self._close_seen = True
        self._status = (code, signal)
        if self._timer is not None:
            self._timer.cancel()
        if self._reason != 'output_limit':
            self._parse(self._buffer + self._stdout.end())
        self.append_diagnostic(self._stderr.end())
        # Native subprocesses inherit the worker's process group. Do not release the computation permit while a
        # descendant is still running after its parent exits.
        if self._group_alive():
            self._signal('SIGTERM')
            if not self._kill_timers:
                self._kill_timers.append(self._loop.call_later(self._kill_after, self._signal, 'SIGKILL'))
            self._group_timer = self._loop.call_later(GROUP_POLL_SECONDS, self._poll_group)
        else:
            self._complete()

    def _poll_group(self) -> None:
        if self._closed:
            return
        if not self._group_alive():
            self._complete()
        else:
            self._group_timer = self._loop.call_later(GROUP_POLL_SECONDS, self._poll_group)

    def _complete(self) -> None:
        if self._closed:
            return
        self._closed = True
        for timer in (*self._kill_timers, self._group_timer, self._bound, self._timer):
            if timer is not None:
                timer.cancel()
        code, signal = self._status
        self._call('close', code, signal)
        if not self._done.done():
            self._done.set_result(Outcome(code=code, signal=signal, reason=self._reason, stderr=self._diagnostic,
                                          result=self._result, error=self._error, escaped=self._escaped))

    def _give_up(self) -> None:
        """The bound: stop waiting for outputs held outside the group and for members that cannot be killed."""
        if self._closed:
            return
        self._escaped = True
        self._signal('SIGKILL')
        if not self._close_seen:
            status = self.child.abandon()
            self._close_seen = True
            self._status = status
            if self._reason != 'output_limit':
                self._parse(self._buffer + self._stdout.end())
            self.append_diagnostic(self._stderr.end())
        self._complete()

    def _begin(self, child: Any, input: Any) -> None:
        self.child = child
        self._timer = self._loop.call_later(self._timeout, self.stop, 'timeout')
        if self.process_group:
            self._bound = self._loop.call_later(self._timeout + 2 * self._kill_after, self._give_up)
        if input is not UNDEFINED:
            try:
                child.end_input(_utf8(input if isinstance(input, str) else jsjson.stringify(input)))
            except Exception as error:
                self._report_error(error if isinstance(error, WorkerError) else WorkerError(str(error)))
                self.stop('input_error')
        child.resume()


# --- the process ----------------------------------------------------------------------------------------------

def _status(returncode: Optional[int]) -> tuple[Optional[int], Optional[str]]:
    """Node's ``(code, signal)`` for a return code."""
    if returncode is None:
        return None, None
    if returncode < 0:
        try:
            return None, signals.Signals(-returncode).name
        except ValueError:
            return None, f'SIG{-returncode}'
    return returncode, None


def _write_error(error: BaseException) -> WorkerError:
    """Node's stdin error: ``write EPIPE``."""
    number = getattr(error, 'errno', None)
    if number is None and isinstance(error, BrokenPipeError):
        number = errno.EPIPE
    elif number is None and isinstance(error, ConnectionResetError):
        number = errno.ECONNRESET
    return WorkerError(f'write {_code(number)}', _code(number))


class _Process(asyncio.SubprocessProtocol):
    """A real child: forwards the subprocess transport's events to the worker as Node's streams emit them. Events
    wait until ``resume`` (Node's handlers are attached before anything is read) and are then delivered in order."""

    def __init__(self, worker: Worker):
        self._worker = worker
        self._transport: Optional[asyncio.SubprocessTransport] = None
        self._pending: list[tuple[Callable, tuple]] = []
        self._live = False
        self._open = {1, 2}
        self._exited = False
        self._closing = False
        self.pid: Optional[int] = None

    def _deliver(self, handler: Callable, *args: Any) -> None:
        if self._live and not self._pending:
            handler(*args)
        else:
            self._pending.append((handler, args))

    def _flush(self) -> None:
        while self._pending:
            handler, args = self._pending.pop(0)
            handler(*args)

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]
        self.pid = transport.get_pid()  # type: ignore[attr-defined]

    def pipe_data_received(self, fd: int, data: bytes) -> None:
        if fd == 1:
            self._deliver(self._worker.feed_stdout, data)
        elif fd == 2:
            self._deliver(self._worker.feed_stderr, data)

    def pipe_connection_lost(self, fd: int, exc: Optional[BaseException]) -> None:
        if fd == 0:
            if exc is not None:
                self._deliver(self._worker.feed_stdin_error, _write_error(exc))
            return
        self._open.discard(fd)
        self._maybe_close()

    def process_exited(self) -> None:
        self._exited = True
        self._maybe_close()

    def _maybe_close(self) -> None:
        if self._exited and not self._open and not self._closing:
            self._closing = True
            self._deliver(self._close)

    def _close(self) -> None:
        status = _status(self._transport.get_returncode())
        self._transport.close()  # done with it (closes stdin if still open), as asyncio's own protocol does
        self._worker.feed_close(*status)

    def kill(self, name: str) -> None:
        if self._transport is not None:
            self._transport.send_signal(getattr(signals, name))

    def end_input(self, data: bytes) -> None:
        """``child.stdin.end(data)``. Node writes before the child runs, into the pipe's buffer; a child that has
        already exited here (its exit was seen while the pipes were being connected) gets nothing, without an
        error, as it would have left Node's bytes unread."""
        if self._exited:
            return
        pipe = self._transport.get_pipe_transport(0) if self._transport is not None else None
        if pipe is None:
            raise WorkerError("Cannot read properties of null (reading 'end')")
        pipe.write(data)  # type: ignore[attr-defined]
        pipe.write_eof()  # type: ignore[attr-defined]

    def resume(self) -> None:
        self._live = True
        if self._pending:
            asyncio.get_running_loop().call_soon(self._flush)

    def abandon(self) -> tuple[Optional[int], Optional[str]]:
        """Closes the outputs (and kills the leader if it still runs); the leader's status, if it has exited."""
        self._live = False
        self._pending.clear()
        if self._transport is None:
            return None, None
        status = _status(self._transport.get_returncode())
        self._transport.close()
        return status


class _FailedSpawn:
    """A child libuv could not start: Node emits 'error' and then 'close' with the negative error number."""

    pid = None

    def __init__(self, worker: Worker, executable: str, number: int):
        self._worker = worker
        self._error = WorkerError(f'spawn {executable} {_code(number)}', _code(number))
        self._number = number

    def kill(self, name: str) -> None:
        pass

    def end_input(self, data: bytes) -> None:
        pass

    def resume(self) -> None:
        asyncio.get_running_loop().call_soon(self._emit)

    def _emit(self) -> None:
        self._worker.feed_error(self._error)
        self._worker.feed_close(-self._number, None)

    def abandon(self) -> tuple[Optional[int], Optional[str]]:
        return -self._number, None


async def _exec(process: _Process, candidate: Optional[str], argv: list[str], options: dict) -> None:
    """One spawn; a file without a ``#!`` line is run again with ``/bin/sh`` off macOS (glibc's ``execvp``)."""
    loop = asyncio.get_running_loop()
    try:
        transport, _ = await loop.subprocess_exec(lambda: process, *argv, executable=candidate, **options)
    except OSError as error:
        if error.errno != errno.ENOEXEC or sys.platform == 'darwin':
            raise
        transport, _ = await loop.subprocess_exec(lambda: process, '/bin/sh', candidate or argv[0], *argv[1:],
                                                  **options)
    process.pid = transport.get_pid()


async def _spawn(worker: Worker, executable: str, args: list[str], options: dict) -> Any:
    """libuv's spawn of ``[executable, *args]`` in a new session, with the three streams ``options['stdio']``."""
    stdin = subprocess.DEVNULL if options['stdio'][0] == 'ignore' else subprocess.PIPE
    popen = {'stdin': stdin, 'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE, 'cwd': options.get('cwd'),
             'env': options.get('env'), 'start_new_session': options['detached']}
    argv = [executable, *args]
    process = _Process(worker)
    try:
        if sys.platform == 'darwin' or '/' in executable:
            await _exec(process, None, argv, popen)
            return process
        if not executable:
            raise OSError(errno.ENOENT, os.strerror(errno.ENOENT), executable)
        denied = False
        env = popen['env'] if popen['env'] is not None else os.environ
        for directory in env.get('PATH', os.defpath).split(':'):
            try:
                await _exec(process, f'{directory}/{executable}' if directory else f'./{executable}', argv, popen)
                return process
            except OSError as error:
                if error.errno not in _EXECVP_SKIP:
                    raise
                denied = denied or error.errno == errno.EACCES
        number = errno.EACCES if denied else errno.ENOENT
        raise OSError(number, os.strerror(number), executable)
    except OSError as error:
        if error.errno in _REPORTED:
            return _FailedSpawn(worker, executable, error.errno)
        raise SpawnError(f'spawn {_code(error.errno)}', _code(error.errno)) from error


async def start_worker(executable: str, args: Sequence[str], *, cwd: Optional[str] = None,
                       env: Optional[dict] = None, stdin: str = 'pipe', input: Any = UNDEFINED, timeout: float,
                       max_output_bytes: int, kill_after: float = KILL_AFTER_SECONDS,
                       on_event: Optional[Callable[[dict, Callable[[str], None]], None]] = None,
                       on_log: Optional[Callable[[str], None]] = None,
                       on_stderr: Optional[Callable[[str], None]] = None,
                       on_error: Optional[Callable[[WorkerError], None]] = None,
                       on_stop: Optional[Callable[[str], None]] = None,
                       on_close: Optional[Callable[[Optional[int], Optional[str]], None]] = None,
                       spawn: Optional[Callable] = None) -> Worker:
    """``startPythonWorker({executable, args, options: {cwd, env, stdio: [stdin, 'pipe', 'pipe']}, input,
    timeoutMs: timeout * 1000, maxOutputBytes, killAfterMs: kill_after * 1000, on...})``.

    ``timeout`` and ``kill_after`` are in seconds. ``stdin`` is ``'pipe'`` or ``'ignore'``; ``input`` (left out:
    nothing is written and stdin stays open) needs ``'pipe'``. Raises ``SpawnError`` where Node's ``spawn`` throws.
    """
    if stdin not in ('pipe', 'ignore'):
        raise ValueError("stdin must be 'pipe' or 'ignore'")
    if stdin == 'ignore' and input is not UNDEFINED:
        raise ValueError("input needs stdin 'pipe'")
    loop = asyncio.get_running_loop()
    worker = Worker(loop, timeout=timeout, max_output_bytes=max_output_bytes, kill_after=kill_after,
                    process_group=spawn is None and os.name == 'posix', on_event=on_event, on_log=on_log,
                    on_stderr=on_stderr, on_error=on_error, on_stop=on_stop, on_close=on_close)
    options = {'cwd': cwd, 'env': env, 'stdio': [stdin, 'pipe', 'pipe'], 'detached': worker.process_group,
               'shell': False}
    if spawn is None:
        child = await _spawn(worker, executable, list(args), options)
    else:
        child = spawn(worker, executable, list(args), options)
        if inspect.isawaitable(child):
            child = await child
    worker._begin(child, input)
    return worker
