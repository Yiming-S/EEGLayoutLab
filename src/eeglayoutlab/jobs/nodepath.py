"""Node's ``path.posix`` (``lib/path.js``), for every path string that enters a request key.

Raw pointer strings are digest keys verbatim, and the paths Node builds with ``join``, ``dirname`` and
``relative`` are normalized its way. Python's ``os.path`` differs: ``dirname('a')`` is ``''`` (Node ``'.'``),
``dirname('a/b/')`` is ``'a/b'`` (Node ``'a'``), ``join('a', '/b')`` drops ``'a'`` (Node ``'a/b'``) and
``normpath('//a')`` keeps the leading ``//`` (Node ``'/a'``). So key strings are never built with ``os.path``.
"""
from __future__ import annotations

import os

__all__ = ['InvalidArgTypeError', 'normalize', 'join', 'dirname', 'resolve', 'relative', 'is_absolute', 'js_sort']


class InvalidArgTypeError(TypeError):
    """Node's ``ERR_INVALID_ARG_TYPE``: a path argument that is not a string (``undefined`` from an absent
    pointer member, ``null``, a number ...)."""

    code = 'ERR_INVALID_ARG_TYPE'


def _normalize_string(path: str, allow_above_root: bool) -> str:
    """``normalizeString(path, allowAboveRoot, '/', isPosixPathSeparator)``: resolves ``.`` and ``..`` segments."""
    res = ''
    last_segment_length = 0
    last_slash = -1
    dots = 0
    code = ''
    for i in range(len(path) + 1):
        if i < len(path):
            code = path[i]
        elif code == '/':
            break
        else:
            code = '/'
        if code == '/':
            if last_slash == i - 1 or dots == 1:
                pass
            elif dots == 2:
                if len(res) < 2 or last_segment_length != 2 or res[-1] != '.' or res[-2] != '.':
                    if len(res) > 2:
                        last_slash_index = res.rfind('/')
                        if last_slash_index == -1:
                            res = ''
                            last_segment_length = 0
                        else:
                            res = res[:last_slash_index]
                            last_segment_length = len(res) - 1 - res.rfind('/')
                        last_slash = i
                        dots = 0
                        continue
                    elif len(res) != 0:
                        res = ''
                        last_segment_length = 0
                        last_slash = i
                        dots = 0
                        continue
                if allow_above_root:
                    res += '/..' if len(res) > 0 else '..'
                    last_segment_length = 2
            else:
                if len(res) > 0:
                    res += '/' + path[last_slash + 1:i]
                else:
                    res = path[last_slash + 1:i]
                last_segment_length = i - last_slash - 1
            last_slash = i
            dots = 0
        elif code == '.' and dots != -1:
            dots += 1
        else:
            dots = -1
    return res


def _check(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise InvalidArgTypeError(f'The "{name}" argument must be of type string.')
    return value


def is_absolute(path: str) -> bool:
    """``path.posix.isAbsolute``."""
    return _check(path, 'path').startswith('/')


def normalize(path: str) -> str:
    """``path.posix.normalize``: ``//a//b/../c/`` gives ``/a/c/``; an empty path gives ``.``."""
    _check(path, 'path')
    if not path:
        return '.'
    absolute = path[0] == '/'
    trailing_separator = path[-1] == '/'
    path = _normalize_string(path, not absolute)
    if not path:
        if absolute:
            return '/'
        return './' if trailing_separator else '.'
    if trailing_separator:
        path += '/'
    return '/' + path if absolute else path


def join(*parts: str) -> str:
    """``path.posix.join``: the non-empty parts joined with ``/``, then normalized; an absolute part is kept."""
    for part in parts:
        _check(part, 'path')
    joined = [part for part in parts if part]
    if not joined:
        return '.'
    return normalize('/'.join(joined))


def dirname(path: str) -> str:
    """``path.posix.dirname``: ``'a'`` gives ``'.'`` and ``'a/b/'`` gives ``'a'``."""
    _check(path, 'path')
    if not path:
        return '.'
    has_root = path[0] == '/'
    end = -1
    matched_slash = True
    for i in range(len(path) - 1, 0, -1):
        if path[i] == '/':
            if not matched_slash:
                end = i
                break
        else:
            matched_slash = False
    if end == -1:
        return '/' if has_root else '.'
    if has_root and end == 1:
        return '//'
    return path[:end]


def resolve(*parts: str, cwd: str | None = None) -> str:
    """``path.posix.resolve``, with ``process.cwd()`` replaced by ``cwd`` (default ``os.getcwd()``).

    Symbolic links are never followed: the result is a normalized string, not a real path.
    """
    resolved = ''
    resolved_absolute = False
    for part in reversed(parts):
        _check(part, 'path')
        if not part:
            continue
        resolved = f'{part}/{resolved}'
        resolved_absolute = part[0] == '/'
        if resolved_absolute:
            break
    if not resolved_absolute:
        current = os.getcwd() if cwd is None else cwd
        resolved = f'{current}/{resolved}'
        resolved_absolute = current.startswith('/')
    resolved = _normalize_string(resolved, not resolved_absolute)
    if resolved_absolute:
        return '/' + resolved
    return resolved or '.'


def relative(from_: str, to: str, cwd: str | None = None) -> str:
    """``path.posix.relative(from, to)``; relative arguments are resolved against ``cwd``."""
    _check(from_, 'from')
    _check(to, 'to')
    if from_ == to:
        return ''
    from_ = resolve(from_, cwd=cwd)
    to = resolve(to, cwd=cwd)
    if from_ == to:
        return ''
    from_start, from_end = 1, len(from_)
    from_len = from_end - from_start
    to_start = 1
    to_len = len(to) - to_start
    length = min(from_len, to_len)
    last_common_sep = -1
    i = 0
    while i < length:
        from_code = from_[from_start + i]
        if from_code != to[to_start + i]:
            break
        if from_code == '/':
            last_common_sep = i
        i += 1
    if i == length:
        if to_len > length:
            if to[to_start + i] == '/':
                return to[to_start + i + 1:]
            if i == 0:
                return to[to_start + i:]
        elif from_len > length:
            if from_[from_start + i] == '/':
                last_common_sep = i
            elif i == 0:
                last_common_sep = 0
    out = ''
    for j in range(from_start + last_common_sep + 1, from_end + 1):
        if j == from_end or from_[j] == '/':
            out += '..' if not out else '/..'
    return out + to[to_start + last_common_sep:]


def js_sort(names):
    """``Array.prototype.sort()`` of strings: UTF-16 code-unit order (Python's ``sorted`` uses code points)."""
    return sorted(names, key=lambda name: name.encode('utf-16-be', errors='surrogatepass'))
