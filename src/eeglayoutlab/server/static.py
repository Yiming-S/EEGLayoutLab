"""The static interface: the export that ``npm run build`` writes to ``webapp/dist/client`` (``output: 'export'``).

Rules (endpoints.md section 9.4):

- ``/`` serves ``index.html`` and ``/<name>`` serves ``<name>.html`` for each page of the export; ``/<name>/``
  redirects (308, relative) to ``/<name>``; any other path that is not a file of the export gets ``404.html`` with
  status 404. Pages are HTML with ``Cache-Control: no-store``, so a new build is picked up at once.
- Files: ``/_next/static/**`` (hashed names) is ``public, max-age=31536000, immutable``, the others
  ``public, max-age=3600``; ETag and Last-Modified; ``HEAD``. Other methods get 405 with ``Allow: GET, HEAD``.
- Conditional and range requests as vinext evaluates them (the Node host's static files): its preconditions
  (``If-Match`` and ``If-Unmodified-Since`` → 412, ``If-None-Match`` and ``If-Modified-Since`` → 304, a request
  ``Cache-Control: no-cache`` → no 304), its HTTP-date parser (the three formats of RFC 9110, all in GMT), its
  ``If-Range`` and its single byte range (206, or 416 when it cannot be satisfied). Repeated request headers are
  joined with ``', '``, as in Node's ``req.headers``, except the dates, of which the first counts.
- The original bytes only: the ``.br``/``.gz`` sidecars of the build are never served, and over loopback no
  compression is needed. The ``<name>.txt`` files beside the pages are the pages' RSC payloads.
- A file is found by its exact name, as in vinext's table of the export, also on a file system that ignores case
  (APFS, NTFS): ``/Favicon.svg`` or ``/design.HTML`` is not a file of the export.
- Never served: a percent-encoded spelling of a path, ``.`` and ``..`` segments, dotfiles, ``.html`` files by
  name (Node answers 404 too) and anything whose real path leaves the export.

Until the export is built (its ``index.html`` is there), every page answers 503 with how to build it; the API is not
affected. The export and its pages are looked up at every request, so a build made while the service runs, which
writes the pages last, is served without a restart.
"""
from __future__ import annotations

from email.utils import formatdate
import os
import re
import stat
import time
from typing import Any, Optional

import anyio

from .app import raw_path

__all__ = ['StaticExport', 'DocsSite', 'CONTENT_TYPES', 'page_names', 'content_type', 'export_root']

# vinext's CONTENT_TYPES (static-file-cache.js), which the Node host uses, plus binary glTF.
CONTENT_TYPES = {
    '.avif': 'image/avif', '.bmp': 'image/bmp', '.csv': 'text/csv; charset=utf-8',
    '.eot': 'application/vnd.ms-fontobject', '.gif': 'image/gif', '.heic': 'image/heic',
    '.js': 'application/javascript; charset=utf-8', '.mjs': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.html': 'text/html; charset=utf-8', '.ico': 'image/x-icon',
    '.jpeg': 'image/jpeg', '.jpg': 'image/jpeg', '.json': 'application/json; charset=utf-8',
    '.map': 'application/json; charset=utf-8', '.mp3': 'audio/mpeg', '.mp4': 'video/mp4', '.ogg': 'audio/ogg',
    '.ogv': 'video/ogg', '.pdf': 'application/pdf', '.png': 'image/png', '.rsc': 'text/x-component',
    '.svg': 'image/svg+xml', '.ttf': 'font/ttf', '.txt': 'text/plain; charset=utf-8', '.wasm': 'application/wasm',
    '.webm': 'video/webm', '.webmanifest': 'application/manifest+json', '.webp': 'image/webp',
    '.woff': 'font/woff', '.woff2': 'font/woff2', '.xml': 'application/xml', '.glb': 'model/gltf-binary',
}
DEFAULT_TYPE = 'application/octet-stream'
HTML = 'text/html; charset=utf-8'
IMMUTABLE = 'public, max-age=31536000, immutable'
PUBLIC = 'public, max-age=3600'
SIDECARS = ('.br', '.gz', '.zst')
CHUNK = 64 * 1024
_PAGE = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width, initial-scale=1"><title>EEG Layout Lab</title></head>'
         '<body><main><h1>{title}</h1><p lang="en">{english}</p></main></body></html>')
NOT_BUILT_PAGE = _PAGE.format(
    title='界面尚未构建：请在 webapp 目录运行 <code>npm run build</code>，然后重新运行 eeglayoutlab。',
    english='The interface has not been built. Run <code>npm run build</code> in the webapp directory '
            '(or pass <code>--static</code>), then run eeglayoutlab again.').encode('utf-8')
NOT_FOUND_PAGE = _PAGE.format(title='页面不存在', english='Page not found.').encode('utf-8')
DOCS_NOT_BUILT_PAGE = _PAGE.format(
    title='本地离线文档未包含在当前安装中：请打开在线文档，传入已构建站点的 <code>--docs</code>，或在源码检出目录运行 <code>mkdocs build</code>。',
    english='Local documentation is not included in this installation. Open the online documentation, pass '
            '<code>--docs</code> to a built site, or in a source checkout run <code>mkdocs build</code> and reload '
            'this page.').encode('utf-8')
_COMMON = [(b'x-content-type-options', b'nosniff')]


def content_type(name: str) -> str:
    return CONTENT_TYPES.get(os.path.splitext(name)[1].lower(), DEFAULT_TYPE)


def _lookup(root: str, segments: list[str], suffix: str = '') -> Optional[tuple[str, os.stat_result]]:
    """The real path and status of a regular file of the export ``root``, or ``None``."""
    names = [*segments[:-1], segments[-1] + suffix]
    if any(not part or part.startswith('.') or '\\' in part or '\0' in part for part in names):
        return None
    # Each name as it is spelled in its directory: a file system that ignores case would also find
    # /Favicon.svg or /favicon.svg.BR, which are not files of the export (vinext looks names up exactly).
    candidate = root
    for part in names:
        try:
            if part not in os.listdir(candidate):
                return None
        except (OSError, ValueError):
            return None
        candidate = os.path.join(candidate, part)
    real = os.path.realpath(candidate)
    if not real.startswith(root + os.sep):
        return None
    try:
        status = os.stat(real)
    except (OSError, ValueError):
        return None
    return (real, status) if stat.S_ISREG(status.st_mode) else None


def export_root(directory: Optional[str]) -> Optional[str]:
    """The real path of the export in ``directory``, or ``None`` until it is built: a directory without
    ``index.html`` (an older build that was not an export, or one that ``npm run build`` is still writing) is not."""
    if not directory:
        return None
    root = os.path.realpath(directory)
    return root if _lookup(root, ['index'], '.html') is not None else None


def _is_page(root: str, name: str) -> bool:
    """Whether ``/<name>`` is a page: ``<name>.html`` at the top of the export, except ``index`` and ``404``."""
    return '/' not in name and name not in ('index', '404') and _lookup(root, [name], '.html') is not None


def page_names(directory: str) -> frozenset[str]:
    """The pages of an export: its top-level ``<name>.html`` files except ``404.html``; ``index`` is ``/``."""
    with os.scandir(directory) as entries:
        return frozenset(entry.name[:-5] for entry in entries
                         if entry.name.endswith('.html') and entry.name != '404.html' and not entry.name.startswith('.')
                         and entry.is_file())


# --- vinext's request evaluation (webapp/node_modules/vinext/dist/server/http-{range,conditional,date}.js) -------

_MAX_SAFE_INTEGER = 2**53 - 1
# JavaScript's \d is ASCII-only, its \s within Latin-1 (which header values are read as) is _JS_SPACE, and
# ^...$ without the m flag is fullmatch.
_RANGE_SPEC = re.compile(r'([0-9]*)-([0-9]*)')
_NO_CACHE = re.compile(r'(?:^|,)[ \t\n\v\f\r\xa0]*no-cache[ \t\n\v\f\r\xa0]*(?:,|\Z)', re.IGNORECASE)
_WEEKDAYS = {'Sun': 0, 'Mon': 1, 'Tue': 2, 'Wed': 3, 'Thu': 4, 'Fri': 5, 'Sat': 6}
_MONTHS = {name: number for number, name in enumerate(
    ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'), 1)}
_WEEKDAY = '(Mon|Tue|Wed|Thu|Fri|Sat|Sun)'
_LONG_WEEKDAY = '(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
_MONTH = '(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
_TIME = r'([0-9]{2}):([0-9]{2}):([0-9]{2})'
_IMF_FIXDATE = re.compile(_WEEKDAY + r', ([0-9]{2}) ' + _MONTH + r' ([0-9]{4}) ' + _TIME + ' GMT')
_RFC850_DATE = re.compile(_LONG_WEEKDAY + r', ([0-9]{2})-' + _MONTH + r'-([0-9]{2}) ' + _TIME + ' GMT')
_ASCTIME_DATE = re.compile(_WEEKDAY + ' ' + _MONTH + r' (?: ([0-9])|([0-9]{2})) ' + _TIME + r' ([0-9]{4})')
_JS_SPACE = ' \t\n\v\f\r\xa0'


def _decimal(digits: str) -> Optional[int]:
    """``parseDecimalInteger``: the value of ASCII digits, or ``None`` (overflow) beyond ``Number.MAX_SAFE_INTEGER``.
    The length is checked before ``int``, which refuses more than 4300 digits."""
    digits = digits.lstrip('0') or '0'
    if len(digits) > 16:
        return None
    value = int(digits)
    return value if value <= _MAX_SAFE_INTEGER else None


def _byte_range(header: Optional[str], size: int) -> Optional[tuple[int, int]] | str:
    """``parseByteRange``: a single ``bytes=`` range as ``(first, last)``; ``'unsatisfiable'``; or ``None`` to send
    the whole file (no header, another unit, several ranges or an invalid value)."""
    if not header or header[:6].lower() != 'bytes=':
        return None
    spec = header[6:].strip(_JS_SPACE)
    match = _RANGE_SPEC.fullmatch(spec)
    if ',' in spec or not match or not (match[1] or match[2]):
        return None
    if not match[1]:
        suffix = _decimal(match[2])
        if suffix is None:
            return 'unsatisfiable' if size == 0 else (0, size - 1)
        if suffix == 0 or size == 0:
            return 'unsatisfiable'
        return max(size - suffix, 0), size - 1
    start = _decimal(match[1])
    end = _decimal(match[2]) if match[2] else size - 1
    if start is None:
        return 'unsatisfiable'
    if end is None:
        return 'unsatisfiable' if start >= size else (start, size - 1)
    if start >= size or end < start:
        return 'unsatisfiable'
    return start, min(end, size - 1)


def _days(year: int, month: int, day: int) -> int:
    """Days from 1970-01-01 in the proleptic Gregorian calendar, for any ``day`` (JavaScript's MakeDay)."""
    year -= month <= 2
    era = year // 400
    of_era = year - era * 400
    of_year = (153 * ((month + 9) % 12) + 2) // 5 + day - 1
    return era * 146097 + of_era * 365 + of_era // 4 - of_era // 100 + of_year - 719468


def _month_days(year: int, month: int) -> int:
    if month == 2:
        return 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def _timestamp(weekday: str, day: str, month: str, year: str, hour: str, minute: str, second: str) -> Optional[int]:
    """``timestampFromHttpDateParts`` in seconds: ``None`` unless the date exists and falls on ``weekday``."""
    days = _days(int(year), _MONTHS[month], int(day))
    if not (1 <= int(day) <= _month_days(int(year), _MONTHS[month]) and int(hour) < 24 and int(minute) < 60
            and int(second) < 60 and (days + 4) % 7 == _WEEKDAYS[weekday[:3]]):
        return None
    return days * 86400 + int(hour) * 3600 + int(minute) * 60 + int(second)


def parse_http_date(value: str) -> Optional[int]:
    """``parseHttpDate`` in seconds: IMF-fixdate, RFC 850 or asctime, all in GMT; ``None`` for anything else. An
    RFC 850 two-digit year is in this century unless that is more than 50 years from now."""
    if imf := _IMF_FIXDATE.fullmatch(value):
        return _timestamp(*imf.groups())
    if rfc850 := _RFC850_DATE.fullmatch(value):
        weekday, day, month, short_year, hour, minute, second = rfc850.groups()
        now = time.time()
        today = time.gmtime(now)
        year = today.tm_year - today.tm_year % 100 + int(short_year)
        # Milliseconds, as JavaScript's Date: the date as written (overflowing days carry over) against the same
        # day and time 50 years from now.
        candidate = ((_days(year, _MONTHS[month], 1) + int(day) - 1) * 86_400_000 + int(hour) * 3_600_000
                     + int(minute) * 60_000 + int(second) * 1000)
        limit = (_days(today.tm_year + 50, today.tm_mon, 1) + today.tm_mday - 1) * 86_400_000 \
            + int(now * 1000) % 86_400_000
        if candidate > limit:
            year -= 100
        return _timestamp(weekday, day, month, str(year), hour, minute, second)
    if asctime := _ASCTIME_DATE.fullmatch(value):
        weekday, month, one_digit, two_digits, hour, minute, second, year = asctime.groups()
        return _timestamp(weekday, one_digit or two_digits, month, year, hour, minute, second)
    return None


def _skip_space(value: str, index: int) -> int:
    while index < len(value) and value[index] in ' \t':
        index += 1
    return index


def _entity_tag(value: str, start: int) -> Optional[tuple[int, int, int]]:
    """``parseEntityTag``: ``(opaque start, opaque end, end)`` of the tag at ``start``, or ``None``."""
    index = start + 2 if value.startswith('W/', start) else start
    if index >= len(value) or value[index] != '"':
        return None
    opaque = index = index + 1
    while index < len(value) and value[index] != '"':
        code = ord(value[index])
        if not (code == 33 or 35 <= code <= 126 or 128 <= code <= 255):
            return None
        index += 1
    if index >= len(value):
        return None
    return opaque, index, index + 1


def _tags_match(header: str, etag: str) -> bool:
    """``matchesIfNoneMatch`` and ``matchesIfMatch``: ``*``, or a list of entity tags one of which has the opaque
    tag of ``etag`` (weak comparison); a malformed list matches nothing."""
    index = _skip_space(header, 0)
    if header[index:index + 1] == '*':
        return _skip_space(header, index + 1) == len(header)
    current = _entity_tag(etag, 0)
    if current is None or current[2] != len(etag):
        return False
    opaque = etag[current[0]:current[1]]
    matched = seen = False
    while index < len(header):
        if header[index] == ',':
            index = _skip_space(header, index + 1)
            continue
        candidate = _entity_tag(header, index)
        if candidate is None:
            return False
        seen = True
        matched = matched or header[candidate[0]:candidate[1]] == opaque
        index = _skip_space(header, candidate[2])
        if index == len(header):
            break
        if header[index] != ',':
            return False
        index = _skip_space(header, index + 1)
    return seen and matched


def _preconditions(scope: Any, etag: str, mtime: int) -> str:
    """``evaluateRequestPreconditions`` for GET and HEAD (``mtime`` in whole seconds): ``'proceed'``,
    ``'not-modified'`` or ``'precondition-failed'``."""
    match, unmodified = _header(scope, b'if-match'), _header(scope, b'if-unmodified-since', first=True)
    none_match, modified = _header(scope, b'if-none-match'), _header(scope, b'if-modified-since', first=True)
    if match is None and unmodified is None and none_match is None and modified is None:
        return 'proceed'
    if match is not None:
        if not _tags_match(match, etag):
            return 'precondition-failed'
    elif unmodified:
        since = parse_http_date(unmodified)
        if since is not None and mtime > since:
            return 'precondition-failed'
    cache_control = _header(scope, b'cache-control')
    no_cache = bool(cache_control) and _NO_CACHE.search(cache_control) is not None
    if none_match is not None:
        if not (none_match.strip(_JS_SPACE) == '*' or _tags_match(none_match, etag)):
            return 'proceed'
        return 'proceed' if no_cache else 'not-modified'
    if no_cache or not modified:
        return 'proceed'
    since = parse_http_date(modified)
    return 'not-modified' if since is not None and mtime <= since else 'proceed'


def _range_allowed(condition: Optional[str], etag: str, mtime: int) -> bool:
    """``ifRangeAllowsRange``: an entity tag must be strong and equal; a date must not precede the file."""
    if not condition:
        return True
    condition = condition.strip(_JS_SPACE)
    if condition.startswith(('"', 'W/')):
        return not condition.startswith('W/') and not etag.startswith('W/') and condition == etag
    since = parse_http_date(condition)
    return since is not None and mtime <= since


def _header(scope: Any, name: bytes, first: bool = False) -> Optional[str]:
    """A request header as Node's ``req.headers`` has it: repeated values joined with ``', '``, or the first one
    (Node drops the repeats of the date headers); ``None`` when absent."""
    values = [value.decode('latin-1') for key, value in scope['headers'] if key.lower() == name]
    if not values:
        return None
    return values[0] if first else ', '.join(values)


async def _respond(send: Any, status: int, headers: list[tuple[bytes, bytes]], body: bytes, head: bool) -> None:
    headers = [*headers, *_COMMON, (b'content-length', str(len(body)).encode('ascii'))]
    await send({'type': 'http.response.start', 'status': status, 'headers': headers})
    await send({'type': 'http.response.body', 'body': b'' if head else body})


class StaticExport:
    """ASGI application for every path outside ``/api/``."""

    def __init__(self, directory: Optional[str]):
        self.directory = directory

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        method = scope['method']
        head = method == 'HEAD'
        if method not in ('GET', 'HEAD'):
            await _respond(send, 405, [(b'allow', b'GET, HEAD'), (b'content-type', b'text/plain; charset=utf-8')],
                           b'Method Not Allowed', False)
            return
        root = export_root(self.directory)
        if root is None:
            await _respond(send, 503, [(b'content-type', HTML.encode()), (b'cache-control', b'no-store')],
                           NOT_BUILT_PAGE, head)
            return
        path = scope['path']
        if raw_path(scope) != path:
            await self._not_found(root, send, head)
            return
        name = path[1:]
        if path == '/' or _is_page(root, name):
            await self._file(root, scope, send, _lookup(root, [name or 'index'], '.html'), HTML, 'no-store')
            return
        if path.endswith('/') and _is_page(root, name[:-1]):
            location = path[:-1].encode('latin-1')
            query = scope.get('query_string', b'')
            await _respond(send, 308, [(b'location', location + (b'?' + query if query else b''))], b'', head)
            return
        segments = name.split('/')
        if segments[-1].endswith(('.html', *SIDECARS)):
            await self._not_found(root, send, head)
            return
        cache = IMMUTABLE if path.startswith('/_next/static/') else PUBLIC
        await self._file(root, scope, send, _lookup(root, segments), content_type(segments[-1]), cache)

    async def _not_found(self, root: str, send: Any, head: bool) -> None:
        found = _lookup(root, ['404.html'])
        body = NOT_FOUND_PAGE
        if found is not None:
            try:
                body = await anyio.Path(found[0]).read_bytes()
            except OSError:
                pass
        await _respond(send, 404, [(b'content-type', HTML.encode()), (b'cache-control', b'no-store')], body, head)

    async def _file(self, root: str, scope: Any, send: Any, found: Optional[tuple[str, os.stat_result]],
                    kind: str, cache: str) -> None:
        head = scope['method'] == 'HEAD'
        if found is None:
            await self._not_found(root, send, head)
            return
        path, status = found
        size = status.st_size
        etag = f'"{status.st_mtime_ns:x}-{size:x}"'
        # Whole seconds, as Node has them (new Date(mtimeMs).toUTCString(), Math.floor(mtimeMs / 1e3)): the
        # header names the second the preconditions compare, never the next one (formatdate rounds a float mtime).
        seconds = status.st_mtime_ns // 1_000_000_000
        modified = formatdate(seconds, usegmt=True)
        headers = [(b'cache-control', cache.encode()), (b'etag', etag.encode()),
                   (b'last-modified', modified.encode())]
        outcome = _preconditions(scope, etag, seconds)
        if outcome == 'not-modified':
            await send({'type': 'http.response.start', 'status': 304, 'headers': [*headers, *_COMMON]})
            await send({'type': 'http.response.body', 'body': b''})
            return
        headers += [(b'content-type', kind.encode()), (b'accept-ranges', b'bytes')]
        if outcome == 'precondition-failed':
            await _respond(send, 412, headers, b'', head)
            return
        span = None
        if _range_allowed(_header(scope, b'if-range'), etag, seconds):
            span = _byte_range(_header(scope, b'range'), size)
        if span == 'unsatisfiable':
            await _respond(send, 416, [*headers, (b'content-range', f'bytes */{size}'.encode())], b'', head)
            return
        first, last = span if isinstance(span, tuple) else (0, size - 1)
        length = last - first + 1 if size else 0
        if isinstance(span, tuple):
            headers.append((b'content-range', f'bytes {first}-{last}/{size}'.encode()))
        headers += [*_COMMON, (b'content-length', str(length).encode())]
        await send({'type': 'http.response.start', 'status': 206 if isinstance(span, tuple) else 200,
                    'headers': headers})
        if head or length == 0:
            await send({'type': 'http.response.body', 'body': b''})
            return
        async with await anyio.open_file(path, 'rb') as handle:
            await handle.seek(first)
            remaining = length
            while remaining > 0:
                chunk = await handle.read(min(CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                await send({'type': 'http.response.body', 'body': chunk, 'more_body': remaining > 0})
            if remaining > 0:
                # The file shrank while it was sent; end the response short rather than hang.
                await send({'type': 'http.response.body', 'body': b''})


class DocsSite(StaticExport):
    """ASGI application for ``/docs`` and ``/docs/...``: the documentation site that ``mkdocs build`` writes
    (``use_directory_urls``, so a chapter is ``<name>/index.html``).

    ``/docs`` redirects (308) to ``/docs/``; a path ending in ``/`` serves that directory's ``index.html``; a
    directory named without the slash redirects to it; any other path is a file of the site. Pages are
    ``no-store`` and files ``public, max-age=3600``, with the same conditional and range handling, exact names and
    refusals as the interface. A path that is not in the site gets the site's ``404.html``. Until the site is built
    (its ``index.html`` is there) every path answers 503 with how to build it, so the interface can tell whether to
    link here or to the Markdown on GitHub.
    """

    PREFIX = '/docs/'

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        method = scope['method']
        head = method == 'HEAD'
        if method not in ('GET', 'HEAD'):
            await _respond(send, 405, [(b'allow', b'GET, HEAD'), (b'content-type', b'text/plain; charset=utf-8')],
                           b'Method Not Allowed', False)
            return
        root = export_root(self.directory)
        if root is None:
            await _respond(send, 503, [(b'content-type', HTML.encode()), (b'cache-control', b'no-store')],
                           DOCS_NOT_BUILT_PAGE, head)
            return
        path = scope['path']
        if raw_path(scope) != path:
            await self._not_found(root, send, head)
            return
        query = scope.get('query_string', b'')
        if path == self.PREFIX[:-1]:
            await _respond(send, 308, [(b'location', self.PREFIX.encode() + (b'?' + query if query else b''))],
                           b'', head)
            return
        segments = path[len(self.PREFIX):].split('/')
        if segments[-1] == '':
            await self._file(root, scope, send, _lookup(root, [*segments[:-1], 'index.html']), HTML, 'no-store')
            return
        found = _lookup(root, segments)
        if found is None and _lookup(root, [*segments, 'index.html']) is not None:
            location = path.encode('latin-1') + b'/'
            await _respond(send, 308, [(b'location', location + (b'?' + query if query else b''))], b'', head)
            return
        kind = content_type(segments[-1])
        await self._file(root, scope, send, found, kind, 'no-store' if kind == HTML else PUBLIC)
