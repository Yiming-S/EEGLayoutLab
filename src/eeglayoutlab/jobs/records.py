"""The read side of Node's record store (``webapp/server/storage/records.mjs:29-83``) and the ``fs`` calls of the library.

The five record trees stay at ``R/results/v2/*_jobs`` (decision U1); a directory's name is the request key. Reads
follow Node's checks: ``path`` refuses a key that is not 64 lowercase hex digits and a suffix that leaves the key's
directory (lexically), ``contained`` resolves the root and the target with ``realpath(3)`` (``nodefs.realpath``) and
requires the target inside the root, and ``keys`` lists the directories (not links to them) named like a key.

Node's ``readdir`` returns names sorted by their bytes (libuv's ``scandir`` sorts with ``strcmp``), not in the
directory's order, so ``scandir`` here sorts the raw names before decoding them. The ``fs`` helpers raise
``OSError`` carrying Node's ``code``, ``syscall`` and path, so ``node_message`` writes the message Node's error has
(``EACCES: permission denied, open '<path>'``); the library shows such messages in its warnings.
"""
from __future__ import annotations

import errno
import os
import re
import stat as stat_module
from typing import Any, Optional

from ..schemas import jsjson
from . import nodefs, nodepath

__all__ = ['RECORD_DIRECTORIES', 'KEY', 'RecordError', 'RecordStore', 'read_file', 'stat', 'realpath', 'scandir',
           'error_code', 'node_message']

RECORD_DIRECTORIES = {
    'radius': 'results/v2/local_app_jobs',
    'design': 'results/v2/design_evaluation_jobs',
    'editor': 'results/v2/electrode_editor_jobs',
    'source': 'results/v2/source_reception_jobs',
    'sourceV2': 'results/v2/source_reception_v2_jobs',
}
KEY = re.compile('[a-f0-9]{64}')
_CHUNK = 1 << 20

# libuv's uv_strerror texts, which Node's fs errors carry (deps/uv/include/uv.h, UV_ERRNO_MAP).
_UV_TEXT = {
    'E2BIG': 'argument list too long', 'EACCES': 'permission denied', 'EAGAIN': 'resource temporarily unavailable',
    'EBADF': 'bad file descriptor', 'EBUSY': 'resource busy or locked', 'EFBIG': 'file too large',
    'EILSEQ': 'illegal byte sequence', 'EINVAL': 'invalid argument', 'EIO': 'i/o error',
    'EISDIR': 'illegal operation on a directory', 'ELOOP': 'too many symbolic links encountered',
    'EMFILE': 'too many open files', 'ENAMETOOLONG': 'name too long', 'ENFILE': 'file table overflow',
    'ENODEV': 'no such device', 'ENOENT': 'no such file or directory', 'ENOMEM': 'not enough memory',
    'ENOTDIR': 'not a directory', 'ENXIO': 'no such device or address',
    'EOVERFLOW': 'value too large for defined data type', 'EPERM': 'operation not permitted',
    'ETIMEDOUT': 'connection timed out',
}


class RecordError(ValueError):
    """A record path or file Node refuses; the message is Node's, verbatim."""


def _annotate(error: OSError, syscall: str, path: Optional[str]) -> OSError:
    error.code = errno.errorcode.get(error.errno, 'UNKNOWN')  # type: ignore[attr-defined]
    error.syscall = syscall  # type: ignore[attr-defined]
    error.node_path = path  # type: ignore[attr-defined]
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
    """``error.message`` as Node writes it: ``<code>: <text>, <syscall> '<path>'`` for a system error from these
    helpers, else the exception's own message (Node's text for the errors this package raises; a ``SyntaxError``'s
    message is Python's, not V8's)."""
    syscall = getattr(error, 'syscall', None)
    if isinstance(error, OSError) and syscall:
        code = error_code(error) or 'UNKNOWN'
        text = _UV_TEXT.get(code, os.strerror(error.errno).lower() if error.errno else 'unknown error')
        path = getattr(error, 'node_path', None)
        return f"{code}: {text}, {syscall}" + (f" '{path}'" if path is not None else '')
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


class RecordStore:
    """``new RecordStore(repositoryRoot)``, read side: the root is ``path.resolve``-d, never resolved through links."""

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
