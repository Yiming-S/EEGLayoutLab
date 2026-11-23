"""Node's ``fs`` for the files that enter request keys: path strings, directory names and real paths.

Node turns a path string into bytes as UTF-8 with lone surrogates replaced by U+FFFD, refuses a path with a NUL
byte (``ERR_INVALID_ARG_VALUE``) before any I/O, and decodes the names it reads (``readdir``, ``readlink``,
``realpath``) as UTF-8 with invalid bytes replaced by U+FFFD. Python's ``os`` functions use surrogateescape, so
a name that is not UTF-8 opens again in Python but not in Node; every file access here goes through bytes made
the way Node makes them.

Node has two real-path functions, and the design identity uses both:

- ``realpath_sync`` is ``fs.realpathSync`` (lib/fs.js, JavaScript): it walks the components with ``lstat`` and
  ``readlink`` and resolves each link target *lexically* (``path.resolve(previous, target)``, so ``..`` after a
  symlinked component is collapsed in the string), keeping the spelling it was given. ``InputIntegrity``'s root
  and Node's main module path, from which its default root comes, are resolved with it.
- ``realpath`` is ``fs.promises.realpath``: libuv calls the C library's ``realpath(3)``, which resolves link
  targets physically and, on macOS, returns each component's on-disk letter case and Unicode normalization.
  ``InputIntegrity.digest`` resolves every input with it.

``os.path.realpath`` is neither: physical like ``realpath(3)`` but spelling-preserving like ``realpathSync``.
"""
from __future__ import annotations

import ctypes
import errno
import os
import re
import stat as stat_module
import sys

from . import nodepath

__all__ = ['InvalidArgValueError', 'check_path', 'inspect_string', 'encode', 'decode', 'read_file', 'open_check',
           'readdir', 'stat', 'lstat', 'realpath', 'realpath_sync']

_LONE_SURROGATE = re.compile('[\ud800-\udfff]')


class InvalidArgValueError(ValueError):
    """Node's ``ERR_INVALID_ARG_VALUE``: a path string with a NUL byte."""

    code = 'ERR_INVALID_ARG_VALUE'


def check_path(path: object) -> str:
    """``getValidatedPath(path)`` for the strings Node passes: a string without NUL bytes."""
    if not isinstance(path, str):
        raise nodepath.InvalidArgTypeError(f'The "path" argument must be of type string. Received {path!r}')
    if '\0' in path:
        inspected = inspect_string(path)
        if len(_utf16(inspected)) > 128:  # ERR_INVALID_ARG_VALUE cuts the inspected value
            inspected = _from_utf16(_utf16(inspected)[:128]) + '...'
        raise InvalidArgValueError(f"The argument 'path' must be a string, Uint8Array, or URL without null bytes. "
                                   f'Received {inspected}')
    return path


# --- util.inspect of a string (lib/internal/util/inspect.js: formatPrimitive, strEscape) --------------------------

_ESCAPES = {0x08: '\\b', 0x09: '\\t', 0x0a: '\\n', 0x0c: '\\f', 0x0d: '\\r', 0x5c: '\\\\'}
_BREAK_LENGTH = 80  # util.inspect.defaultOptions.breakLength
_MAX_STRING_LENGTH = 10000


def _utf16(text: str) -> list[int]:
    data = text.encode('utf-16-le', errors='surrogatepass')
    return [data[i] | data[i + 1] << 8 for i in range(0, len(data), 2)]


def _from_utf16(units: list[int]) -> str:
    return b''.join(unit.to_bytes(2, 'little') for unit in units).decode('utf-16-le', errors='surrogatepass')


def _str_escape(units: list[int]) -> str:
    """``strEscape``: control characters, the backslash, C1 controls and lone surrogates escaped, in the quotes the
    text needs least (single, else double, else a backtick unless it holds one or ``${``)."""
    quote = "'"
    if 0x27 in units:
        text = _from_utf16(units)
        if '"' not in text:
            quote = '"'
        elif '`' not in text and '${' not in text:
            quote = '`'
    out = []
    index = 0
    while index < len(units):
        unit = units[index]
        if (unit == 0x27 and quote == "'") or unit == 0x5c or unit < 0x20 or 0x7e < unit < 0xa0:
            out.append("\\'" if unit == 0x27 else _ESCAPES.get(unit, f'\\x{unit:02X}'))
        elif 0xd800 <= unit <= 0xdfff:
            if unit <= 0xdbff and index + 1 < len(units) and 0xdc00 <= units[index + 1] <= 0xdfff:
                out.append(_from_utf16(units[index:index + 2]))
                index += 2
                continue
            out.append(f'\\u{unit:x}')
        else:
            out.append(chr(unit))
        index += 1
    return quote + ''.join(out) + quote


def inspect_string(text: str) -> str:
    """``util.inspect(text)`` with Node's defaults: quoted and escaped; past 76 code units it is split after each
    line feed into quoted pieces joined by `` +\\n  ``, and past 10000 cut with ``... N more characters``."""
    units = _utf16(text)
    trailer = ''
    if len(units) > _MAX_STRING_LENGTH:
        remaining = len(units) - _MAX_STRING_LENGTH
        units = units[:_MAX_STRING_LENGTH]
        trailer = f"... {remaining} more character{'s' if remaining > 1 else ''}"
    if len(units) > 16 and len(units) > _BREAK_LENGTH - 4:
        lines, start = [], 0
        for index, unit in enumerate(units):
            if unit == 0x0a:
                lines.append(units[start:index + 1])
                start = index + 1
        if start < len(units):
            lines.append(units[start:])
        return ' +\n  '.join(_str_escape(line) for line in lines) + trailer
    return _str_escape(units) + trailer


def encode(path: str) -> bytes:
    """A JavaScript string as Node passes it to the system: UTF-8, a lone surrogate as U+FFFD."""
    return _LONE_SURROGATE.sub('\ufffd', check_path(path)).encode('utf-8')


def decode(raw: bytes) -> str:
    """A name as Node returns it with the default ``'utf8'`` encoding: invalid bytes become U+FFFD."""
    return raw.decode('utf-8', errors='replace')


def read_file(path: str) -> bytes:
    """``readFile(path)``: a directory raises ``EISDIR``, as Node's does."""
    with open(encode(path), 'rb') as stream:
        return stream.read()


def open_check(path: str) -> None:
    """The ``open`` of ``createReadStream(path)`` (``O_RDONLY``): an unreadable file raises ``EACCES``; a directory
    opens, and fails only when it is read."""
    os.close(os.open(encode(path), os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0)))


def readdir(path: str) -> list[str]:
    """``readdir(path)``: the names in the directory's order, decoded as Node decodes them."""
    return [decode(name) for name in os.listdir(encode(path))]


def stat(path: str) -> os.stat_result:
    return os.stat(encode(path))


def lstat(path: str) -> os.stat_result:
    return os.lstat(encode(path))


# --- fs.promises.realpath: realpath(3) ---------------------------------------------------------------------------

def _libc_realpath():
    if os.name != 'posix':
        return None
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        # macOS headers bind realpath() to realpath$DARWIN_EXTSN, which libuv calls; it allocates the result.
        function = getattr(libc, 'realpath$DARWIN_EXTSN', None) if sys.platform == 'darwin' else None
        if function is None:
            function = libc.realpath
        free = libc.free
    except (OSError, AttributeError):
        return None
    function.argtypes = (ctypes.c_char_p, ctypes.c_void_p)
    function.restype = ctypes.c_void_p
    free.argtypes = (ctypes.c_void_p,)
    free.restype = None
    return function, free


_REALPATH = _libc_realpath()


def realpath(path: str) -> str:
    """``fs.promises.realpath(path)``: ``realpath(3)`` of the bytes, decoded as Node decodes them.

    On macOS the result carries each component's on-disk letter case and Unicode normalization, whatever the
    spelling of ``path``; a missing file, a dangling link, a loop or a file used as a directory raise ``OSError``
    with the system's errno, as Node rejects with its code.
    """
    raw = encode(path)
    if _REALPATH is None:  # no C library to call (not POSIX): the closest Python equivalent
        return os.path.realpath(path, strict=True)
    function, free = _REALPATH
    result = function(raw, None)
    if not result:
        number = ctypes.get_errno() or errno.EIO
        raise OSError(number, os.strerror(number), path)
    try:
        return decode(ctypes.string_at(result))
    finally:
        free(result)


# --- fs.realpathSync: lib/fs.js -----------------------------------------------------------------------------------

# Node restarts the walk after every link and stops only when the kernel reports ELOOP. When the walk comes back
# to a path string it has already restarted from, Node's loop runs forever (link targets are cached by inode, so
# the walk repeats); this port raises ELOOP there instead, for example for ``a -> b/../a`` with ``b`` a link to a
# subdirectory, which the kernel resolves elsewhere. A walk that never repeats but keeps growing (``a ->
# b/../a/c`` with ``b`` a link into a tree that has ``a/c``) also runs forever in Node; the port stops it after
# ``_MAX_RESTARTS`` links. That bound is a deliberate difference: a path that needs more link hops than that
# (``self -> .`` repeated 4097 times) resolves in Node and raises ELOOP here. These strings are only the
# configured root and this package's own path, for which no real installation comes near it.
_MAX_RESTARTS = 4096


def _split_root(path: str) -> str:
    """``splitRoot``: the leading slashes."""
    for index, char in enumerate(path):
        if char != '/':
            return path[:index]
    return path


def realpath_sync(path: str) -> str:
    """``fs.realpathSync(path)``: link targets resolved lexically, the given spelling kept.

    Each component is ``lstat``-ed (so a missing one raises ``ENOENT``); a link is ``stat``-ed (``ENOENT`` when
    dangling, ``ELOOP`` for a loop) and read, and the walk restarts from the root on
    ``path.resolve(path.resolve(previous, target), rest)``. Node's break on a FIFO or socket, which reads a stat
    buffer shared by the whole process, is not reproduced.
    """
    p = nodepath.resolve(check_path(path))
    seen_links: dict[tuple[int, int], str] = {}
    known_hard: set[str] = set()
    current = base = _split_root(p)
    pos = len(current)
    restarted_from = {p}
    while pos < len(p):
        result = p.find('/', pos)
        previous = current
        if result == -1:
            last = p[pos:]
            current += last
            base = previous + last
            pos = len(p)
        else:
            current += p[pos:result + 1]
            base = previous + p[pos:result]
            pos = result + 1
        if base in known_hard:
            continue
        info = lstat(base)
        if not stat_module.S_ISLNK(info.st_mode):
            known_hard.add(base)
            continue
        link = (info.st_dev, info.st_ino)
        if link in seen_links:
            target = seen_links[link]
        else:
            stat(base)
            target = decode(os.readlink(encode(base)))
        seen_links[link] = target
        p = nodepath.resolve(nodepath.resolve(previous, target), p[pos:])
        current = base = _split_root(p)
        pos = len(current)
        if p in restarted_from or len(restarted_from) > _MAX_RESTARTS:
            raise OSError(errno.ELOOP, os.strerror(errno.ELOOP), path)
        restarted_from.add(p)
    return p
