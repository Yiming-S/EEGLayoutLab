"""The numerical runtime digest of signal reception v2: Node's ``runtime/identity-cache.mjs``, statement by statement.

``numerical_runtime_sha256`` comes from the inspector ``R/scripts/inspect_reception_runtime_snapshot.py``, or the
legacy ``inspect_reception_runtime.py`` when the first does not exist (``ENOENT`` of ``access(R_OK)``; any other
failure is raised). It runs as a subprocess of the native interpreter (``RuntimeConfig.native_python``, Node's
``nativePython``) as Node's ``execFile`` runs it: no ``-I``, working directory R, the environment given (default
the service's, as Node reads ``process.env``) plus ``INSPECT_ENV``, 15 s, 8 MiB per output counted after UTF-8
decoding, and Node's messages (``Command failed: <python> <script>\\n<stderr>``, ``spawn <python> ENOENT``,
``stdout maxBuffer length exceeded``). Its output is parsed with ``JSON.parse``. The service never computes the
digest itself (plan B15).

``RuntimeIdentityCache`` is ``createRuntimeIdentityCache``: a memo keyed by ``sha256(JSON.stringify([python, root,
sorted env entries]))`` that holds at most four inspections in least-recently-used order. Before an entry is reused
every stamp of its ``watch`` (the inspector's own ``lstat`` observations) and of the launcher chain (each PATH
candidate of the interpreter, its symbolic links and their ancestors) is taken again; any difference runs the
inspector again, and a stamp that cannot be taken fails the call. A result without ``watch`` (the legacy inspector)
is never cached, nor is one whose interpreter is a bare name searched without ``PATH``. Calls for one key share the
inspection in flight, as Node's ``pending`` map does; failures are never cached.

``await cache(python, root, env)`` returns ``{'schema': 'reception-runtime-digest/1', 'sha256': ...}``, a new dict
for each caller. The work runs in a thread of its own (file stamps, the subprocess), so the event loop never waits
on it; ``read_sync`` is the same call for code already in a worker thread, and both share the memo and the
inspections in flight. ``inspect(python, root, env)`` replaces the inspector for tests, as Node's ``inspect`` option
does; it is called in that thread.

Errors keep Node's classes for the queue's ``internal_fault``: Node's plain ``Error`` refusals are
``RuntimeDigestError`` (a ``ValueError``; ``InspectorError`` for ``Command failed``, with Node's numeric ``code``),
system errors keep their code (``lstat``, ``readlink`` and ``access`` raise ``OSError`` that ``records.node_message``
writes as Node does; spawn failures ``jobs.worker.WorkerError``), the output bound is ``MaxBufferError`` (Node's
``RangeError``) and text that is not JSON ``jsjson.JSONSyntaxError``.

Known differences:

- the memo key sorts the environment by UTF-16 code units, not ``localeCompare``; the key never leaves the process,
  and both orders keep every entry, so only names that ``localeCompare`` ties could hit differently;
- an inspector that ignores ``SIGTERM`` after the timeout or the output bound gets ``SIGKILL`` after
  ``KILL_GRACE_SECONDS`` (Node waits for it forever); the message is the same;
- a bare interpreter name is searched as ``jobs.worker`` searches it (Python's own search on macOS, glibc's
  ``execvp`` elsewhere): on macOS, libuv stops at the first candidate that fails with an error other than
  ``EACCES``, ``ENOENT`` or ``ENOTDIR``, where Python goes on to the next;
- ``close()`` kills the inspectors still running, and any that a call spawns after it (service shutdown); Node
  leaves them to finish.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import concurrent.futures
import ctypes
from dataclasses import dataclass, field
import errno
import hashlib
import os
import re
import selectors
import signal as signals
import socket
import stat as stat_module
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping, Optional, Sequence

from ..schemas import jsjson
from . import nodefs, nodepath
from .fingerprint import _EXECVP_SKIP
from .identity import UNDEFINED, _js_string
from .worker import _REPORTED, SpawnError, WorkerError, _code, _status, _StringDecoder, _utf8

__all__ = ['DIGEST_SCHEMA', 'WATCH_SCHEMA', 'SNAPSHOT_SCRIPT', 'LEGACY_SCRIPT', 'INSPECT_ENV',
           'INSPECT_TIMEOUT_SECONDS', 'INSPECT_MAX_BUFFER', 'MAX_ENTRIES', 'KILL_GRACE_SECONDS', 'INVALID_DIGEST', 'CHANGED_DURING_INSPECTION',
           'LAUNCHER_CHAIN_TOO_LARGE', 'INVALID_LIMIT', 'RuntimeDigestError', 'InspectorError', 'MaxBufferError',
           'ProcessRegistry', 'RuntimeIdentityCache', 'run_inspector', 'exec_file', 'process_env']

DIGEST_SCHEMA = 'reception-runtime-digest/1'
WATCH_SCHEMA = 'reception-runtime-watch/1'
SNAPSHOT_SCRIPT = 'scripts/inspect_reception_runtime_snapshot.py'
LEGACY_SCRIPT = 'scripts/inspect_reception_runtime.py'
INSPECT_ENV = {'PYTHONDONTWRITEBYTECODE': '1', 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1',
               'MKL_NUM_THREADS': '1', 'VECLIB_MAXIMUM_THREADS': '1'}
INSPECT_TIMEOUT_SECONDS = 15.0
INSPECT_MAX_BUFFER = 8 * 1024 * 1024
MAX_ENTRIES = 4
KILL_GRACE_SECONDS = 2.0
WATCH_LIMIT = 100000
LAUNCHER_LIMIT = 10000

# Node's messages, verbatim.
INVALID_DIGEST = '接收数值环境身份无效'
CHANGED_DURING_INSPECTION = '数值运行环境在检查期间发生变化'
LAUNCHER_CHAIN_TOO_LARGE = 'Python launcher link chain is too large'
INVALID_LIMIT = 'Invalid runtime cache limit'

# JavaScript's \d is ASCII and its $ ends the input; Python's \d and $ are not, so the patterns spell both out.
_STAMP = re.compile('[0-9]+(?::[0-9]+){2}(?::[0-9]+:-?[0-9]+:-?[0-9]+)?')
_HEX64 = re.compile('[a-f0-9]{64}')
_MISSING = ('ENOENT', 'ENOTDIR')
_READ_SIZE = 65536
_EXIT_POLL_SECONDS = 0.05  # how soon stdin closes after the child exits


class RuntimeDigestError(ValueError):
    """Node's plain ``Error``: a refusal whose message is Node's, verbatim."""

    name = 'Error'

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InspectorError(RuntimeDigestError):
    """``execFile``'s ``Command failed: <cmd>\\n<stderr>``: a non-zero exit, a signal or the timeout. ``code`` is
    the exit status (``None`` after a signal), as Node's."""

    def __init__(self, message: str, *, code: Optional[int], killed: bool, signal: Optional[str], cmd: str):
        super().__init__(message)
        self.code = code
        self.killed = killed
        self.signal = signal
        self.cmd = cmd


class MaxBufferError(RuntimeError):
    """``ERR_CHILD_PROCESS_STDIO_MAXBUFFER``, a ``RangeError``: an internal fault for the queue."""

    name = 'RangeError'
    code = 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER'

    def __init__(self, stream: str):
        self.message = f'{stream} maxBuffer length exceeded'
        super().__init__(self.message)


# --- File observations ------------------------------------------------------------------------------------------

def _stamp(path: str, full: bool) -> Optional[str]:
    """``stamp(path, full)``: ``dev:ino:mode[:size:mtimeNs:ctimeNs]`` of ``lstat`` (Node's ``bigint`` values: ``dev``
    as an unsigned 64-bit number), ``None`` for ``ENOENT`` and ``ENOTDIR``."""
    try:
        info = nodefs.lstat(path)
    except OSError as error:
        if getattr(error, 'code', None) in _MISSING:
            return None
        raise
    values = [info.st_dev % (1 << 64), info.st_ino, info.st_mode]
    if full:
        values += [info.st_size, info.st_mtime_ns, info.st_ctime_ns]
    return ':'.join(str(value) for value in values)


def _unchanged(entries: Sequence[Sequence[Any]]) -> bool:
    """``unchanged(watch)``: every stamp is taken (none skipped after a difference), so a stamp that cannot be taken
    fails the call. Node takes them concurrently: argument errors reject before any I/O, and the file errors come in
    list order with one thread-pool worker, as here."""
    for path, _, _ in entries:
        nodefs.check_path(path)
    same = True
    for path, full, expected in entries:
        if _stamp(path, full) != expected:
            same = False
    return same


def _valid_watch(watch: Any) -> bool:
    """``validWatch(watch)``."""
    if not isinstance(watch, dict) or watch.get('schema', UNDEFINED) != WATCH_SCHEMA:
        return False
    entries = watch.get('entries', UNDEFINED)
    if not isinstance(entries, (list, tuple)) or not entries or len(entries) > WATCH_LIMIT:
        return False
    paths: set[str] = set()
    for item in entries:
        if (not isinstance(item, (list, tuple)) or len(item) != 3 or not isinstance(item[0], str)
                or not item[0].startswith('/') or item[0] in paths or not isinstance(item[1], bool)
                or not (item[2] is None or (isinstance(item[2], str) and _STAMP.fullmatch(item[2])))):
            return False
        paths.add(item[0])
    return True


def _readlink(path: str) -> str:
    """``readlink(path)``: the target decoded as Node decodes names."""
    try:
        return nodefs.decode(os.readlink(nodefs.encode(path)))
    except OSError as error:
        raise nodefs.system_error(error, 'readlink', path) from None


def _launcher_watch(python: str, root: str, env: Mapping[str, Any]) -> Optional[dict]:
    """``launcherWatch(python, root, env)``: stamps of each PATH candidate (or of the interpreter path), every
    symbolic link on the way and their ancestors (ancestors without size and times). ``None`` for a bare name
    without ``PATH``, which the operating system searches on a default path. ``..`` is never normalized before a
    directory link is traversed: the observed path is the one the system executes."""
    search = env.get('PATH', UNDEFINED)
    if not nodepath.is_absolute(python) and '/' not in python and not isinstance(search, str):
        return None

    def absolute(path: str) -> str:
        return path if nodepath.is_absolute(path) else f'{root}/{path}'

    if nodepath.is_absolute(python) or '/' in python:
        candidates = [absolute(python)]
    else:
        candidates = [f'{absolute(directory or ".")}/{python}' for directory in search.split(':')]
    paths: dict[str, bool] = {}
    expanded: set[str] = set()
    pending = [(path, True) for path in candidates]
    while pending:
        path, full = pending.pop()
        paths[path] = bool(paths.get(path) or full)
        if path in expanded:
            continue
        if len(expanded) > LAUNCHER_LIMIT:
            raise RuntimeDigestError(LAUNCHER_CHAIN_TOO_LARGE)
        expanded.add(path)
        try:
            if stat_module.S_ISLNK(nodefs.lstat(path).st_mode):
                paths[path] = True
                target = _readlink(path)
                pending.append((target if nodepath.is_absolute(target) else f'{nodepath.dirname(path)}/{target}',
                                True))
        except OSError as error:
            if getattr(error, 'code', None) not in _MISSING:
                raise
        if nodepath.dirname(path) != path:
            pending.append((nodepath.dirname(path), False))
    return {'schema': WATCH_SCHEMA, 'entries': [[path, full, _stamp(path, full)] for path, full in paths.items()]}


# --- execFile ---------------------------------------------------------------------------------------------------

def _invalid_value(name: str, value: str, reason: str) -> nodefs.InvalidArgValueError:
    """Node's ``ERR_INVALID_ARG_VALUE(name, value, reason)``: the inspected value cut at 128 UTF-16 units."""
    inspected = nodefs.inspect_string(value)
    units = inspected.encode('utf-16-le', errors='surrogatepass')
    if len(units) > 256:
        inspected = units[:256].decode('utf-16-le', errors='surrogatepass') + '...'
    kind = 'property' if '.' in name else 'argument'
    return nodefs.InvalidArgValueError(f"The {kind} '{name}' {reason}. Received {inspected}")


def _env_bytes(env: Mapping[str, Any]) -> dict[bytes, bytes]:
    """``envPairs``: each member that is not ``undefined`` as ``String(value)``, UTF-8 with a lone surrogate as
    U+FFFD; a NUL byte is refused with Node's message."""
    pairs: dict[bytes, bytes] = {}
    for key, value in env.items():
        if value is UNDEFINED:
            continue
        text = value if isinstance(value, str) else _js_string(value)
        for part in (key, text):
            if '\0' in part:
                raise _invalid_value(f"options.env['{key}']", part, 'must be a string without null bytes')
        pairs[_utf8(key)] = _utf8(text)
    return pairs


def _exec_candidate(candidate: Optional[bytes], argv: list[bytes], options: dict) -> subprocess.Popen:
    """One ``execve``; off macOS a file without a ``#!`` line (``ENOEXEC``) runs with ``/bin/sh``, as glibc's
    ``execvp`` runs it."""
    try:
        return subprocess.Popen(argv, executable=candidate, **options)
    except OSError as error:
        if error.errno != errno.ENOEXEC or sys.platform == 'darwin':
            raise
    return subprocess.Popen([b'/bin/sh', candidate or argv[0], *argv[1:]], **options)


def _spawn(argv: list[bytes], options: dict) -> subprocess.Popen:
    """libuv's spawn: Python's own search on macOS (``posix_spawn``), glibc's ``execvp`` elsewhere (PATH of the
    child's environment, ``/bin:/usr/bin`` without one, an empty entry being the working directory)."""
    name = argv[0]
    if sys.platform == 'darwin' or b'/' in name:
        return _exec_candidate(None, argv, options)
    if not name:
        raise OSError(errno.ENOENT, os.strerror(errno.ENOENT))
    denied = False
    for directory in options['env'].get(b'PATH', os.defpath.encode()).split(b':'):
        try:
            return _exec_candidate(directory + b'/' + name if directory else b'./' + name, argv, options)
        except OSError as error:
            if error.errno not in _EXECVP_SKIP:
                raise
            denied = denied or error.errno == errno.EACCES
    number = errno.EACCES if denied else errno.ENOENT
    raise OSError(number, os.strerror(number))


def _signal(process: subprocess.Popen) -> None:
    """``child.kill('SIGTERM')``, then ``SIGKILL`` after ``KILL_GRACE_SECONDS`` (Node would wait for the exit)."""
    if process.poll() is not None:
        return
    try:
        process.send_signal(signals.SIGTERM)
        process.wait(timeout=KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    except ProcessLookupError:
        process.wait()


class ProcessRegistry:
    """The children a service runs through ``exec_file`` (its ``processes``). ``close()`` kills those running, and
    a child added after it (spawned while the close ran) is killed at once, so none outlives the service."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: set = set()
        self._closed = False

    def __len__(self) -> int:
        return len(self._running)

    def add(self, process: subprocess.Popen) -> None:
        with self._lock:
            if not self._closed:
                self._running.add(process)
                return
        process.kill()

    def discard(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._running.discard(process)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            running = list(self._running)
        for process in running:
            process.kill()  # Popen.kill ignores a child already reaped


@dataclass
class _Output:
    name: str
    decoder: _StringDecoder = field(default_factory=_StringDecoder)
    size: int = 0
    parts: list = field(default_factory=list)


def exec_file(file: str, args: Sequence[str], *, cwd: str, env: Mapping[str, Any], timeout: float, max_buffer: int,
              processes: Optional[ProcessRegistry] = None) -> str:
    """``(await promisify(execFile)(file, args, {cwd, env, timeout, maxBuffer})).stdout``.

    The three streams are socket pairs, as libuv makes them; stdin stays open and unwritten until the child exits.
    Outputs are decoded as Node's ``setEncoding('utf8')`` decodes them, and the bound counts the decoded text's
    UTF-8 bytes. Past the bound, or at the timeout, both outputs are closed and the child gets ``SIGTERM``
    (execFile's ``kill()``); past the bound the call fails with ``MaxBufferError``, at the timeout the exit status
    decides (a child that still exits with 0 succeeds with the output read until then). Otherwise a non-zero exit
    or a signal fails with ``Command failed: <file> <args>\\n<stderr>``. ``processes`` holds the running child.
    """
    if not isinstance(file, str):
        raise nodepath.InvalidArgTypeError('The "file" argument must be of type string.')
    if '\0' in file:
        raise _invalid_value('file', file, 'must be a string without null bytes')
    if not file:
        raise _invalid_value('file', file, 'cannot be empty')
    for index, value in enumerate(args):
        if '\0' in value:
            raise _invalid_value(f'args[{index}]', value, 'must be a string without null bytes')
    if '\0' in cwd:
        raise _invalid_value('options.cwd', cwd, 'must be a string, Uint8Array, or URL without null bytes')
    argv = [nodefs.encode(file), *(nodefs.encode(value) for value in args)]
    cmd = f"{file} {' '.join(args)}" if args else file
    options = {'cwd': nodefs.encode(cwd), 'env': _env_bytes(env)}
    pairs = [socket.socketpair() for _ in range(3)]
    try:
        try:
            process = _spawn(argv, {**options, 'stdin': pairs[0][1].fileno(), 'stdout': pairs[1][1].fileno(),
                                    'stderr': pairs[2][1].fileno()})
        except OSError as error:
            if error.errno in _REPORTED:  # the 'error' event: spawn <file> <CODE>
                raise WorkerError(f'spawn {file} {_code(error.errno)}', _code(error.errno)) from None
            raise SpawnError(f'spawn {_code(error.errno)}', _code(error.errno)) from None  # spawn throws
        finally:
            for _, child in pairs:
                child.close()
    except BaseException:
        for ours, _ in pairs:
            ours.close()
        raise
    stdin, stdout, stderr = (pair[0] for pair in pairs)
    outputs = {stdout: _Output('stdout'), stderr: _Output('stderr')}
    if processes is not None:
        processes.add(process)
    deadline = time.monotonic() + timeout
    failure: Optional[MaxBufferError] = None
    drained = killed = False
    try:
        with selectors.DefaultSelector() as selector:
            for end in outputs:
                selector.register(end, selectors.EVENT_READ)
            while failure is None:
                if not selector.get_map():
                    drained = True
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if stdin.fileno() != -1:
                    if process.poll() is None:
                        remaining = min(remaining, _EXIT_POLL_SECONDS)
                    else:
                        stdin.close()  # Node destroys stdin at the exit
                for key, _ in selector.select(remaining):
                    output = outputs[key.fileobj]
                    try:
                        chunk = key.fileobj.recv(_READ_SIZE)
                    except ConnectionResetError:
                        chunk = b''
                    if chunk:
                        text = output.decoder.write(chunk)
                    else:
                        text = output.decoder.end()
                        selector.unregister(key.fileobj)
                    output.size += len(text.encode('utf-8'))
                    if output.size > max_buffer:
                        failure = MaxBufferError(output.name)
                        break
                    output.parts.append(text)
        if drained:
            try:
                process.wait(timeout=max(deadline - time.monotonic(), 0))
            except subprocess.TimeoutExpired:
                pass
        if failure is not None or not drained or process.poll() is None:
            killed = True  # the bound or the timeout: kill()
            for end in outputs:
                end.close()
            _signal(process)
    except BaseException:
        for end in outputs:
            end.close()
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    finally:
        for end in (stdin, stdout, stderr):
            end.close()
        if processes is not None:
            processes.discard(process)
    if failure is not None:
        raise failure
    code, signal = _status(process.returncode)
    if code == 0 and signal is None:
        return ''.join(outputs[stdout].parts)
    raise InspectorError(f"Command failed: {cmd}\n{''.join(outputs[stderr].parts)}", code=code, killed=killed,
                         signal=signal, cmd=cmd)


# --- The inspector ----------------------------------------------------------------------------------------------

def _libc_access() -> Optional[Callable[[bytes, int], int]]:
    if os.name != 'posix':
        return None
    try:
        function = ctypes.CDLL(None, use_errno=True).access
    except (OSError, AttributeError):
        return None
    function.argtypes = (ctypes.c_char_p, ctypes.c_int)
    function.restype = ctypes.c_int
    return function


_ACCESS = _libc_access()


def _access(path: str) -> None:
    """``access(path, constants.R_OK)``: libuv's ``access(2)``; a failure raises its errno with Node's message."""
    raw = nodefs.encode(path)
    if _ACCESS is not None:
        if _ACCESS(raw, os.R_OK) == 0:
            return
        number = ctypes.get_errno() or errno.EIO
    else:  # no C library to call: the closest Python equivalent
        if os.access(raw, os.R_OK):
            return
        try:
            os.stat(raw)
            number = errno.EACCES
        except OSError as error:
            number = error.errno or errno.ENOENT
    raise nodefs.system_error(OSError(number, os.strerror(number), path), 'access', path)


def run_inspector(python: str, root: str, env: Mapping[str, Any], *,
                  processes: Optional[ProcessRegistry] = None) -> Any:
    """``runInspector({python, root, env})``: ``JSON.parse`` of the inspector's output."""
    script = nodepath.join(root, SNAPSHOT_SCRIPT)
    try:
        _access(script)
    except OSError as error:
        if getattr(error, 'code', None) != 'ENOENT':
            raise
        script = nodepath.join(root, LEGACY_SCRIPT)
    stdout = exec_file(python, [script], cwd=root, env=env, timeout=INSPECT_TIMEOUT_SECONDS,
                       max_buffer=INSPECT_MAX_BUFFER, processes=processes)
    return jsjson.parse(stdout)


def process_env() -> dict[str, str]:
    """``process.env``: the environment's bytes decoded as UTF-8, invalid bytes as U+FFFD, as V8 decodes them."""
    if os.supports_bytes_environ:
        return {nodefs.decode(key): nodefs.decode(value) for key, value in os.environb.items()}
    return dict(os.environ)


# --- The memo ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Saved:
    digest: dict
    watch: dict
    launcher: dict


class RuntimeIdentityCache:
    """``createRuntimeIdentityCache({inspect, maxEntries})`` (see the module docstring). File observations are taken
    again on every call; there is no validity window."""

    def __init__(self, inspect: Optional[Callable[[str, str, dict], Any]] = None, max_entries: Any = MAX_ENTRIES):
        if isinstance(max_entries, bool) or not jsjson.is_integer(max_entries) or max_entries < 0:
            raise RuntimeDigestError(INVALID_LIMIT)
        self._processes = ProcessRegistry()
        self._inspect = inspect or (lambda python, root, env: run_inspector(python, root, env,
                                                                            processes=self._processes))
        self._max_entries = int(max_entries)
        self._cache: OrderedDict[str, _Saved] = OrderedDict()
        self._pending: dict[str, concurrent.futures.Future] = {}
        self._lock = threading.Lock()

    async def __call__(self, python: str, root: str, env: Optional[Mapping[str, Any]] = None) -> dict:
        """``await runtimeIdentity({python, root, env})``: ``{'schema', 'sha256'}``; ``env`` defaults to the
        service's environment (``process_env``)."""
        future, work = self._join(python, root, env)
        if work is not None:
            threading.Thread(target=work, name='runtime-digest', daemon=True).start()
        return dict(await asyncio.wrap_future(future))

    def read_sync(self, python: str, root: str, env: Optional[Mapping[str, Any]] = None) -> dict:
        """The same call from a worker thread: blocks until the digest is known."""
        future, work = self._join(python, root, env)
        if work is not None:
            work()
        return dict(future.result())

    def close(self) -> None:
        """Kills the inspectors still running, and any spawned later; their callers fail with ``Command failed``."""
        self._processes.close()

    def _join(self, python: str, root: str, env: Optional[Mapping[str, Any]]):
        """The inspection in flight for this key, or a new one and the work that settles it."""
        root = nodepath.resolve(root)
        env = {**(process_env() if env is None else env), **INSPECT_ENV}
        entries = [[name, value] for name, value in sorted(env.items(), key=lambda item: _units(item[0]))]
        key = hashlib.sha256(jsjson.stringify([python, root, entries]).encode('utf-8', errors='surrogatepass')
                             ).hexdigest()
        with self._lock:
            future = self._pending.get(key)
            if future is not None:
                return future, None
            future = concurrent.futures.Future()
            future.set_running_or_notify_cancel()  # a caller that stops waiting never cancels the others' result
            self._pending[key] = future

        def work() -> None:
            try:
                value = self._operation(key, python, root, env)
            except BaseException as error:
                with self._lock:
                    self._cache.pop(key, None)
                    if self._pending.get(key) is future:
                        del self._pending[key]
                future.set_exception(error)
            else:
                with self._lock:
                    if self._pending.get(key) is future:
                        del self._pending[key]
                future.set_result(value)
        return future, work

    def _operation(self, key: str, python: str, root: str, env: dict) -> dict:
        with self._lock:
            saved = self._cache.get(key)
        if saved is not None and _unchanged(saved.watch['entries']) and _unchanged(saved.launcher['entries']):
            with self._lock:
                self._cache.pop(key, None)
                self._cache[key] = saved
            return dict(saved.digest)
        with self._lock:
            self._cache.pop(key, None)
        launcher = _launcher_watch(python, root, env)
        result = self._inspect(python, root, env)
        schema = result.get('schema', UNDEFINED) if isinstance(result, dict) else UNDEFINED
        if schema != DIGEST_SCHEMA or not _HEX64.fullmatch(_js_string(result.get('sha256', UNDEFINED))):
            raise RuntimeDigestError(INVALID_DIGEST)
        digest = {'schema': result['schema'], 'sha256': result['sha256']}
        # Older scientific snapshots remain readable, but are inspected on every call.
        if 'watch' in result:
            watch = result['watch']
            if (not _valid_watch(watch) or not _unchanged(watch['entries'])
                    or (launcher is not None and not _unchanged(launcher['entries']))):
                raise RuntimeDigestError(CHANGED_DURING_INSPECTION)
            if self._max_entries and launcher is not None:
                with self._lock:
                    self._cache[key] = _Saved(digest, watch, launcher)
                    while len(self._cache) > self._max_entries:
                        self._cache.popitem(last=False)
        return digest


def _units(text: str) -> bytes:
    return text.encode('utf-16-be', errors='surrogatepass')
