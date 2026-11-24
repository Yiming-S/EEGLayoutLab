"""Node's record store (``webapp/server/storage/records.mjs``) and the ``fs`` calls of the library.

The five record trees stay at ``R/results/v2/*_jobs`` (decision U1); a directory's name is the request key. Reads
follow Node's checks: ``path`` refuses a key that is not 64 lowercase hex digits and a suffix that leaves the key's
directory (lexically), ``contained`` resolves the root and the target with ``realpath(3)`` (``nodefs.realpath``) and
requires the target inside the root, and ``keys`` lists the directories (not links to them) named like a key.

Writes are Node's, call for call (``records.mjs:14-83``): ``atomic_json`` writes ``JSON.stringify(value)`` as UTF-8
to ``<path>.<uuid4>.tmp`` (``open(..., 'wx', 0o600)``), syncs it, renames it over ``path``, syncs the directory and
removes the temporary in ``finally``; ``RecordStore.write`` first requires the real parent inside the real root;
``create_batch`` creates ``<kind>/<key>/<id>`` one component at a time and resolves each one before going through
it. Syncs are libuv's (on macOS ``F_FULLFSYNC``). ``publish_cache`` is the one deliberate difference (plan B16):
``cache.json`` is published with ``link(2)``, so a valid one is never replaced. A temporary left by a crash is a
file in a key's directory: ``keys`` lists directories and readers open ``cache.json`` by name, so it is never read.

Node's ``readdir`` returns names sorted by their bytes (libuv's ``scandir`` sorts with ``strcmp``), not in the
directory's order, so ``scandir`` here sorts the raw names before decoding them. The ``fs`` helpers raise
``OSError`` carrying Node's ``code``, ``syscall``, path and destination, so ``node_message`` writes the message
Node's error has (``EACCES: permission denied, open '<path>'``, ``... rename '<from>' -> '<to>'``); the library shows
such messages in its warnings and the run paths in their failure messages.
"""
from __future__ import annotations

import errno
import os
import re
import stat as stat_module
import sys
from typing import Any, Callable, Optional
import uuid

from ..schemas import jsjson
from . import nodefs, nodepath

try:
    import fcntl
except ImportError:  # not POSIX
    fcntl = None  # type: ignore[assignment]

__all__ = ['RECORD_DIRECTORIES', 'KEY', 'BATCH', 'RecordError', 'RecordStore', 'read_file', 'stat', 'realpath',
           'scandir', 'error_code', 'node_message', 'json_bytes', 'atomic_json', 'atomic_bytes', 'fsync']

RECORD_DIRECTORIES = {
    'radius': 'results/v2/local_app_jobs',
    'design': 'results/v2/design_evaluation_jobs',
    'editor': 'results/v2/electrode_editor_jobs',
    'source': 'results/v2/source_reception_jobs',
    'sourceV2': 'results/v2/source_reception_v2_jobs',
}
KEY = re.compile('[a-f0-9]{64}')
BATCH = re.compile('[a-f0-9-]{36}')
_CHUNK = 1 << 20

# libuv's uv_strerror texts, which Node's fs errors carry (deps/uv/include/uv.h, UV_ERRNO_MAP; the system errors of
# util.getSystemErrorMap()). An errno libuv does not map is "Unknown system error -<errno>" in fs.promises.
_UV_TEXT = {
    'E2BIG': 'argument list too long', 'EACCES': 'permission denied', 'EADDRINUSE': 'address already in use',
    'EADDRNOTAVAIL': 'address not available', 'EAFNOSUPPORT': 'address family not supported',
    'EAGAIN': 'resource temporarily unavailable', 'EALREADY': 'connection already in progress',
    'EBADF': 'bad file descriptor', 'EBUSY': 'resource busy or locked', 'ECANCELED': 'operation canceled',
    'ECONNABORTED': 'software caused connection abort', 'ECONNREFUSED': 'connection refused',
    'ECONNRESET': 'connection reset by peer', 'EDESTADDRREQ': 'destination address required',
    'EEXIST': 'file already exists', 'EFAULT': 'bad address in system call argument', 'EFBIG': 'file too large',
    'EFTYPE': 'inappropriate file type or format', 'EHOSTDOWN': 'host is down',
    'EHOSTUNREACH': 'host is unreachable', 'EILSEQ': 'illegal byte sequence', 'EINTR': 'interrupted system call',
    'EINVAL': 'invalid argument', 'EIO': 'i/o error', 'EISCONN': 'socket is already connected',
    'EISDIR': 'illegal operation on a directory', 'ELOOP': 'too many symbolic links encountered',
    'EMFILE': 'too many open files', 'EMLINK': 'too many links', 'EMSGSIZE': 'message too long',
    'ENAMETOOLONG': 'name too long', 'ENETDOWN': 'network is down', 'ENETUNREACH': 'network is unreachable',
    'ENFILE': 'file table overflow', 'ENOBUFS': 'no buffer space available', 'ENODATA': 'no data available',
    'ENODEV': 'no such device', 'ENOENT': 'no such file or directory', 'ENOEXEC': 'exec format error',
    'ENOMEM': 'not enough memory', 'ENONET': 'machine is not on the network',
    'ENOPROTOOPT': 'protocol not available', 'ENOSPC': 'no space left on device',
    'ENOSYS': 'function not implemented', 'ENOTCONN': 'socket is not connected', 'ENOTDIR': 'not a directory',
    'ENOTEMPTY': 'directory not empty', 'ENOTSOCK': 'socket operation on non-socket',
    'ENOTSUP': 'operation not supported on socket', 'ENOTTY': 'inappropriate ioctl for device',
    'ENXIO': 'no such device or address', 'EOVERFLOW': 'value too large for defined data type',
    'EPERM': 'operation not permitted', 'EPIPE': 'broken pipe', 'EPROTO': 'protocol error',
    'EPROTONOSUPPORT': 'protocol not supported', 'EPROTOTYPE': 'protocol wrong type for socket',
    'ERANGE': 'result too large', 'EREMOTEIO': 'remote I/O error', 'EROFS': 'read-only file system',
    'ESHUTDOWN': 'cannot send after transport endpoint shutdown',
    'ESOCKTNOSUPPORT': 'socket type not supported', 'ESPIPE': 'invalid seek', 'ESRCH': 'no such process',
    'ETIMEDOUT': 'connection timed out', 'ETXTBSY': 'text file is busy', 'EUNATCH': 'protocol driver not attached',
    'EXDEV': 'cross-device link not permitted',
}
# This system's errno values of those names (EOPNOTSUPP, EWOULDBLOCK and other aliases are not libuv names).
_UV_CODE = {getattr(errno, name): name for name in _UV_TEXT if hasattr(errno, name)}
# link(2) on a file system without hard links (FAT, exFAT, some network file systems).
_NO_HARD_LINKS = {getattr(errno, name) for name in ('EPERM', 'ENOTSUP', 'EOPNOTSUPP', 'ENOSYS') if hasattr(errno, name)}
# Node's flag strings (lib/internal/fs/utils.js, stringToFlags); libuv opens every file with O_CLOEXEC, as os.open.
_FLAGS = {'r': os.O_RDONLY, 'wx': os.O_TRUNC | os.O_CREAT | os.O_WRONLY | os.O_EXCL}
# fcntl commands of libuv's uv_fs_fsync on macOS.
_F_FULLFSYNC = getattr(fcntl, 'F_FULLFSYNC', 51)
_F_BARRIERFSYNC = 85


class RecordError(ValueError):
    """A record path or file Node refuses; the message is Node's, verbatim."""


def _uv_code(number: Optional[int]) -> str:
    if number in _UV_CODE:
        return _UV_CODE[number]
    return f'Unknown system error -{number}'


def _annotate(error: OSError, syscall: str, path: Optional[str], dest: Optional[str] = None) -> OSError:
    error.code = _uv_code(error.errno)  # type: ignore[attr-defined]
    error.syscall = syscall  # type: ignore[attr-defined]
    error.node_path = path  # type: ignore[attr-defined]
    error.node_dest = dest  # type: ignore[attr-defined]
    return error


def error_code(error: BaseException) -> Optional[str]:
    """``error.code``: Node's code of a system error or an argument error, else ``None``."""
    code = getattr(error, 'code', None)
    if isinstance(code, str):
        return code
    if isinstance(error, OSError) and error.errno in errno.errorcode:
        return errno.errorcode[error.errno]
    return None


def node_message(error: BaseException) -> str:
    """``error.message`` as Node writes it: ``<code>: <text>, <syscall>[ '<path>'][ -> '<dest>']`` for a system
    error from these helpers, else the exception's own message (Node's text for the errors this package raises; a
    ``SyntaxError``'s message is Python's, not V8's)."""
    syscall = getattr(error, 'syscall', None)
    if isinstance(error, OSError) and syscall:
        code = error_code(error) or _uv_code(error.errno)
        text = _UV_TEXT.get(code, code)
        path, dest = getattr(error, 'node_path', None), getattr(error, 'node_dest', None)
        return (f"{code}: {text}, {syscall}" + (f" '{path}'" if path is not None else '')
                + (f" -> '{dest}'" if dest is not None else ''))
    return str(error)


def read_file(path: str) -> bytes:
    """``await readFile(path)``: ``open`` fails with the path in the message; a directory opens and fails on
    ``read`` (``EISDIR``, without a path)."""
    try:
        fd = os.open(nodefs.encode(path), os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0))
    except OSError as error:
        raise _annotate(error, 'open', path) from None
    try:
        if stat_module.S_ISDIR(os.fstat(fd).st_mode):
            raise _annotate(OSError(errno.EISDIR, os.strerror(errno.EISDIR)), 'read', None)
        chunks = []
        while True:
            try:
                chunk = os.read(fd, _CHUNK)
            except OSError as error:
                raise _annotate(error, 'read', None) from None
            if not chunk:
                return b''.join(chunks)
            chunks.append(chunk)
    finally:
        os.close(fd)


def stat(path: str) -> os.stat_result:
    """``await stat(path)`` (links followed)."""
    try:
        return os.stat(nodefs.encode(path))
    except OSError as error:
        raise _annotate(error, 'stat', path) from None


def realpath(path: str) -> str:
    """``await realpath(path)``: ``realpath(3)``, as ``nodefs.realpath``."""
    try:
        return nodefs.realpath(path)
    except OSError as error:
        raise _annotate(error, 'realpath', path) from None


def scandir(path: str) -> list[tuple[str, bool]]:
    """``await readdir(path, {withFileTypes: true})`` as ``(name, entry.isDirectory())``: names in byte order (libuv
    sorts them with ``strcmp``), decoded as Node decodes them; a link to a directory is not a directory."""
    try:
        with os.scandir(nodefs.encode(path)) as entries:
            found = [(entry.name, entry.is_dir(follow_symlinks=False)) for entry in entries]
    except OSError as error:
        raise _annotate(error, 'scandir', path) from None
    return [(nodefs.decode(name), is_dir) for name, is_dir in sorted(found)]


# --- The fs/promises calls of the writers, with Node's errors -----------------------------------------------------

def _mkdir(path: str) -> None:
    """``await mkdir(path)`` (mode 0o777 less the umask)."""
    try:
        os.mkdir(nodefs.encode(path), 0o777)
    except OSError as error:
        raise _annotate(error, 'mkdir', path) from None


def _open(path: str, flags: str, mode: Optional[int] = None) -> int:
    """``await open(path, flags, mode)`` with Node's flag strings (``'r'``, ``'wx'``); Node's default mode is
    0o666."""
    try:
        return os.open(nodefs.encode(path), _FLAGS[flags], 0o666 if mode is None else mode)
    except OSError as error:
        raise _annotate(error, 'open', path) from None


def _write(fd: int, data: bytes) -> None:
    """``filehandle.writeFile(data)``: writes until every byte is written."""
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except OSError as error:
            raise _annotate(error, 'write', None) from None
        view = view[written:]


def fsync(fd: int) -> None:
    """``filehandle.sync()``: libuv's ``uv_fs_fsync``, which on macOS asks for ``F_FULLFSYNC`` (the drive's cache too),
    then ``F_BARRIERFSYNC``, then ``fsync``; elsewhere ``fsync``."""
    if sys.platform == 'darwin' and fcntl is not None:
        for command in (_F_FULLFSYNC, _F_BARRIERFSYNC):
            try:
                fcntl.fcntl(fd, command)
                return
            except OSError:
                pass
    try:
        os.fsync(fd)
    except OSError as error:
        raise _annotate(error, 'fsync', None) from None


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError as error:
        raise _annotate(error, 'close', None) from None


def _rename(path: str, dest: str) -> None:
    """``await rename(path, dest)``: replaces ``dest`` (a link there is replaced, not followed)."""
    try:
        os.rename(nodefs.encode(path), nodefs.encode(dest))
    except OSError as error:
        raise _annotate(error, 'rename', path, dest) from None


def _link(path: str, dest: str) -> None:
    """``await link(path, dest)``: fails with ``EEXIST`` when ``dest`` exists (a dangling link included)."""
    try:
        os.link(nodefs.encode(path), nodefs.encode(dest))
    except OSError as error:
        raise _annotate(error, 'link', path, dest) from None


def _unlink(path: str) -> None:
    try:
        os.unlink(nodefs.encode(path))
    except OSError as error:
        raise _annotate(error, 'unlink', path) from None


def _temporary(path: str) -> str:
    """``${path}.${randomUUID()}.tmp`` (a lowercase UUID v4), the name Node's project and study scanners accept."""
    return f'{path}.{uuid.uuid4()}.tmp'


def _write_new(temporary: str, data: bytes) -> None:
    """``open(temporary, 'wx', 0o600)``, ``writeFile``, ``sync``, ``close`` (in ``finally``)."""
    fd = _open(temporary, 'wx', 0o600)
    try:
        _write(fd, data)
        fsync(fd)
    finally:
        _close(fd)


def _sync_directory(directory: str) -> None:
    fd = _open(directory, 'r')
    try:
        fsync(fd)
    finally:
        _close(fd)


def _discard(temporary: str) -> None:
    """``await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; })``."""
    try:
        _unlink(temporary)
    except OSError as error:
        if error_code(error) != 'ENOENT':
            raise


# --- JSON.stringify's cycle check ------------------------------------------------------------------------------------

def _members(value: Any):
    """The children of a container in ``JSON.stringify``'s order, with V8's key for the messages: an object's keys
    are names (array indices first, ascending), an array's are indices."""
    if isinstance(value, dict):
        names = [name for name in value if isinstance(name, str)]
        indices = sorted((name for name in names if jsjson.is_array_index(name)), key=int)
        for name in indices + [name for name in names if not jsjson.is_array_index(name)]:
            yield name, value[name]
    else:
        yield from enumerate(value)


def _circle(path: list, start: int, last: Any) -> str:
    """V8's message (json-stringifier.cc, ``ConstructCircularStructureErrorMessage``): the object the circle starts
    at, at most two steps after it, ``...``, the last step, and the key that closes the circle."""
    def kind(value: Any) -> str:
        return 'Object' if isinstance(value, dict) else 'Array'

    def key(name: Any) -> str:
        if isinstance(name, int):
            return f'index {name}'
        return f"property '{name}'" if name else '<anonymous>'

    def step(index: int) -> str:
        return f"\n    |     {key(path[index][0])} -> object with constructor '{kind(path[index][1])}'"

    lines = ['Converting circular structure to JSON',
             f"\n    --> starting at object with constructor '{kind(path[start][1])}'"]
    index = start + 1
    prefix_end = min(len(path), index + 2)
    while index < prefix_end:
        lines.append(step(index))
        index += 1
    if len(path) > index + 1:
        lines.append('\n    |     ...')
    index = max(index, len(path) - 1)
    while index < len(path):
        lines.append(step(index))
        index += 1
    lines.append(f'\n    --- {key(last)} closes the circle')
    return ''.join(lines)


def _check_acyclic(value: Any) -> None:
    """Raises V8's ``TypeError`` when ``value`` contains itself; ``jsjson.stringify`` would never return. A value
    reached twice on different paths is not a circle, as in V8."""
    if not isinstance(value, (dict, list, tuple)):
        return
    path: list[tuple[Any, Any]] = [('', value)]
    on_path = {id(value)}
    pending = [_members(value)]
    while pending:
        entry = next(pending[-1], None)
        if entry is None:
            pending.pop()
            on_path.discard(id(path.pop()[1]))
            continue
        name, child = entry
        if not isinstance(child, (dict, list, tuple)):
            continue
        if id(child) in on_path:
            start = next(i for i, (_, container) in enumerate(path) if container is child)
            raise TypeError(_circle(path, start, name))
        path.append((name, child))
        on_path.add(id(child))
        pending.append(_members(child))


def json_bytes(value: Any) -> bytes:
    """The bytes Node writes for ``value``: ``JSON.stringify(value)`` (``jsjson.stringify``) as UTF-8. A value that
    contains itself raises V8's ``TypeError`` before anything is written."""
    _check_acyclic(value)
    return jsjson.stringify(value).encode('utf-8')


def _replace(path: str, data: Callable[[], bytes]) -> None:
    temporary = _temporary(path)
    try:
        _write_new(temporary, data())
        _rename(temporary, path)
        _sync_directory(nodepath.dirname(path))
    finally:
        _discard(temporary)


def atomic_bytes(path: str, data: bytes) -> None:
    """``atomicBytes(path, bytes)`` (studies/store.mjs): ``data`` replaces ``path`` atomically; a failed write never
    replaces the last valid file, and the temporary is removed whatever happens."""
    _replace(path, lambda: data)


def atomic_json(path: str, value: Any) -> None:
    """``atomicJson(path, value)``: ``json_bytes(value)`` replaces ``path`` as ``atomic_bytes`` does (a value that
    cannot be written fails before the temporary is created)."""
    _replace(path, lambda: json_bytes(value))


class RecordStore:
    """``new RecordStore(repositoryRoot)``: the root is ``path.resolve``-d, never resolved through links."""

    def __init__(self, root: str):
        self.root = nodepath.resolve(root)

    def directory(self, kind: str) -> str:
        path = RECORD_DIRECTORIES.get(kind)
        if not path:
            raise RecordError(f'Unknown record kind: {kind}')
        return nodepath.join(self.root, path)

    def path(self, kind: str, key: Any, *parts: str) -> str:
        if not (isinstance(key, str) and KEY.fullmatch(key)):
            raise RecordError('Invalid scientific record key.')
        base = nodepath.join(self.directory(kind), key)
        path = nodepath.join(base, *parts)
        suffix = nodepath.relative(base, path)
        if nodepath.is_absolute(suffix) or suffix == '..' or suffix.startswith('../'):
            raise RecordError('Record path leaves its directory.')
        return path

    def contained(self, path: str) -> str:
        """The real path of ``path``, which must be inside the real root."""
        root = realpath(self.root)
        target = realpath(path)
        if not target.startswith(root + '/'):
            raise RecordError('Record path leaves the repository.')
        return target

    def read(self, path: str) -> Any:
        """``JSON.parse(await readFile(await this.contained(path), 'utf8'))``."""
        return jsjson.parse(nodefs.decode(read_file(self.contained(path))))

    def keys(self, kind: str) -> list[str]:
        """The keys of one record tree in Node's order; ``[]`` when the tree (or the root) is missing."""
        directory = self.directory(kind)
        try:
            path = self.contained(directory)
            return [name for name, is_dir in scandir(path) if is_dir and KEY.fullmatch(name)]
        except OSError as error:
            if error.errno == errno.ENOENT:
                return []
            raise

    # --- Writes ---------------------------------------------------------------------------------------------------

    def _parent_inside(self, path: str) -> None:
        root = realpath(self.root)
        parent = realpath(nodepath.dirname(path))
        if not parent.startswith(root + '/'):
            raise RecordError('Record path leaves the repository.')

    def write(self, path: str, value: Any) -> None:
        """``await write(path, value)``: the real parent directory must be inside the real root (``path`` itself
        may be a link, which is replaced); then ``atomic_json``, which replaces an existing file."""
        self._parent_inside(path)
        atomic_json(path, value)

    def create_batch(self, kind: str, key: Any, id: Any) -> str:
        """``await createBatch(kind, key, id)``: ``<kind>/<key>/<id>`` under the root, every component created
        (``EEXIST`` is fine) and then resolved inside the real root before the next one is created through it."""
        if not (isinstance(id, str) and BATCH.fullmatch(id)):
            raise RecordError('Invalid batch identifier.')
        path = self.path(kind, key, id)
        root = realpath(self.root)
        cursor = self.root
        for part in nodepath.relative(self.root, path).split('/'):
            cursor = nodepath.join(cursor, part)
            try:
                _mkdir(cursor)
            except OSError as error:
                if error_code(error) != 'EEXIST':
                    raise
            actual = realpath(cursor)
            if not actual.startswith(root + '/'):
                raise RecordError('Record directory leaves the repository.')
        return path

    def stored_cache(self, kind: str, key: Any) -> Optional[Any]:
        """``<kind>/<key>/cache.json`` when it passes the checks every kind's reader makes first (Node:
        ``cache.key === key`` and ``cache.result_sha256 === sha256(JSON.stringify(cache.result))``), else ``None``.
        As in Node's readers, a missing, unreadable-as-JSON or foreign file is not a hit, and only ``EACCES`` and
        ``EPERM`` raise."""
        try:
            cache = self.read(self.path(kind, key, 'cache.json'))
            if not isinstance(cache, dict) or cache.get('key') != key or 'result' not in cache:
                return None
            if cache.get('result_sha256') != jsjson.sha256_hex(cache['result']):
                return None
            return cache
        except Exception as error:  # noqa: BLE001 - every other failure is a miss in Node's readers
            if isinstance(error, OSError) and error.errno in (errno.EACCES, errno.EPERM):
                raise
            return None

    def publish_cache(self, kind: str, key: Any, value: Any,
                      valid: Optional[Callable[[], Optional[Any]]] = None) -> Optional[Any]:
        """Publishes ``value`` as ``<kind>/<key>/cache.json`` once (plan B16), where Node's ``write`` replaces it.

        The containment check and the temporary are ``write``'s; the temporary is then linked to ``cache.json``,
        which fails if the name exists. Then the existing file is read with ``valid`` (default ``stored_cache``;
        a kind passes its own reader, for the radius ``lambda: RadiusCache.read_cache(key, request)``): a valid
        file is a hit, which stays, and only a file that is not (corrupt, foreign, a directory's name ...) is
        replaced by renaming the temporary over it. On a file system without hard links the same check comes
        before the rename. A rename over a file that is not valid can still race with another publisher; the
        installation's execution lock (``R/results/v2/.eeglayoutlab-execution.lock``) keeps publishers apart.

        Returns ``None`` when ``value`` is now the cache, else what ``valid`` returned for the cache already there.
        Errors are Node's (``EACCES`` reading the existing file raises; ``cache.json`` is left as it was), and the
        temporary is removed whatever happens.
        """
        path = self.path(kind, key, 'cache.json')
        self._parent_inside(path)
        temporary = _temporary(path)
        try:
            _write_new(temporary, json_bytes(value))
            try:
                _link(temporary, path)
            except OSError as error:
                if error.errno != errno.EEXIST and error.errno not in _NO_HARD_LINKS:
                    raise
                existing = valid() if valid is not None else self.stored_cache(kind, key)
                if existing is not None:
                    return existing
                _rename(temporary, path)
            _sync_directory(nodepath.dirname(path))
            return None
        finally:
            _discard(temporary)
