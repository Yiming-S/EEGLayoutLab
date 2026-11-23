"""Access control for every request (design 0001, decision 6).

The checks run in this order, before any routing:

1. **Guard** (``loopback_request``), ported from ``loopbackRequest`` in webapp/server/http/access-policy.mjs: the
   peer is loopback, ``Host`` names the loopback interface, ``Origin`` (when sent) is ``http://<Host>`` and
   ``Sec-Fetch-Site`` (when sent) is ``same-origin`` or ``none``. Otherwise 403 ``request_forbidden``, as JSON for
   every path.
2. **Session cookie.** ``GET /open?token=<launch token>`` exchanges the token printed by ``eeglayoutlab serve``
   for the cookie ``eeglayoutlab-<port>`` (the port is in the name because cookies are not port-isolated). Every
   other path needs the cookie: without it, 401 ``authentication_required`` as JSON under ``/api/`` and as an
   HTML page elsewhere.

   The launcher opens the URL through a local file (``workspace.write_open_page``), and a browser marks that
   navigation ``Sec-Fetch-Site: cross-site``. So ``GET /open`` alone also passes the guard as a cross-site
   top-level navigation when its token is the launch token; it then answers 200 with a page that refreshes to ``/``,
   because the browser would not send the ``SameSite=Strict`` cookie on a redirect that a cross-site navigation
   started.
3. **CSRF token for writes.** ``POST``, ``PATCH``, ``PUT`` and ``DELETE`` also need ``X-EEG-Compute-Token`` equal to
   the token that health returns, compared as Node's ``tokenMatches``; otherwise 403 with the message of Node's
   route family (``write_refusal``).

Every comparison of a secret is constant-time.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import re
import secrets
from typing import Any, Optional
from urllib.parse import parse_qsl

from .app import error_response, raw_path

__all__ = [
    'Tokens', 'AccessControl', 'cookie_name', 'loopback_request', 'token_matches', 'write_refusal', 'FORBIDDEN',
    'SESSION_EXPIRED', 'WRITE_METHODS',
]

FORBIDDEN = 'Request rejected by access policy.'
SESSION_EXPIRED = '本地服务会话已失效，请重新运行 eeglayoutlab 打开'
WRITE_METHODS = frozenset({'POST', 'PATCH', 'PUT', 'DELETE'})
# JavaScript's \d and $ are ASCII-only and end-only; fullmatch with [0-9] keeps that.
_LOOPBACK_HOST = re.compile(r'(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?')
_LOOPBACK_PEERS = frozenset({'127.0.0.1', '::1'})
_CSRF_TOKEN = re.compile(r'[a-f0-9]{64}')
# Node's 403 messages for a write without the token, by route family (endpoints.md section 2.4); compute and queue
# routes, and every other path, use the first.
_WRITE_REFUSED = '会话已更新，请刷新页面后重新计算'
_WRITE_REFUSALS = (
    ('/api/projects', 'Refresh the page before saving the project.'),
    ('/api/robustness-studies', 'Refresh the page before changing a study.'),
)
_COMMUNITY_REFUSED = '刷新页面后重试'

_PAGE = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width, initial-scale=1"><title>EEG Layout Lab</title></head>'
         '<body><main><h1>{title}</h1><p>{body}</p><p lang="en">{english}</p></main></body></html>')
SESSION_PAGE = _PAGE.format(
    title='本地服务会话已失效',
    body='请在终端重新运行 <code>eeglayoutlab</code>，并使用它打开的 http://127.0.0.1 地址（不要改用 localhost）。',
    english='The local session has expired or this link is not valid. Run <code>eeglayoutlab</code> again and '
            'use the http://127.0.0.1 address it opens (not localhost).').encode('utf-8')
# The answer to /open from the launcher's page: a same-origin navigation to / that carries the new cookie.
LAUNCH_PAGE = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta http-equiv="refresh" '
               'content="0;url=/"><title>EEG Layout Lab</title></head><body><main><p><a href="/">打开 EEG Layout Lab'
               '</a></p><p lang="en"><a href="/">Open EEG Layout Lab</a></p></main></body></html>').encode('utf-8')
_PAGE_HEADERS = [
    (b'content-type', b'text/html; charset=utf-8'), (b'cache-control', b'no-store'),
    (b'x-content-type-options', b'nosniff'), (b'content-security-policy', b"default-src 'none'"),
    (b'referrer-policy', b'no-referrer'),
]


@dataclass(frozen=True)
class Tokens:
    """The secrets of one process; a new set at every start (decision U6)."""

    launch: str
    """In the URL that ``eeglayoutlab serve`` opens and in ``runtime.json``; valid for the life of the process."""
    session: str
    """The cookie value."""
    csrf: str
    """``X-EEG-Compute-Token``: 64 lowercase hex digits, returned by health as ``token``."""

    @classmethod
    def generate(cls) -> 'Tokens':
        return cls(launch=secrets.token_hex(32), session=secrets.token_hex(32), csrf=secrets.token_hex(32))


def cookie_name(port: int) -> str:
    return f'eeglayoutlab-{port}'


def _header(scope: Any, name: bytes, first: bool = False, separator: str = ', ') -> Optional[str]:
    """A request header as Node's ``req.headers`` has it: the first value of ``Host``, the values of ``Cookie``
    joined with ``'; '`` and of the others with ``', '``; ``None`` when absent. Values are read as Latin-1, as
    Node reads them."""
    values = [value.decode('latin-1') for key, value in scope['headers'] if key.lower() == name]
    if not values:
        return None
    return values[0] if first else separator.join(values)


def loopback_request(scope: Any, sites: tuple[str, ...] = ('same-origin', 'none')) -> bool:
    """``loopbackRequest(req)`` of webapp/server/http/access-policy.mjs; ``sites`` are the accepted values of
    ``Sec-Fetch-Site``."""
    client = scope.get('client')
    peer = client[0] if client else None
    if isinstance(peer, str) and peer.startswith('::ffff:'):
        peer = peer[7:]
    if peer not in _LOOPBACK_PEERS:
        return False
    host = _header(scope, b'host', first=True)
    if host is None or not _LOOPBACK_HOST.fullmatch(host):
        return False
    origin = _header(scope, b'origin')
    if origin and origin != f'http://{host}':
        return False
    site = _header(scope, b'sec-fetch-site')
    return not site or site in sites


def _launch_navigation(scope: Any) -> bool:
    """A top-level navigation, by what the browser says of it: ``Sec-Fetch-Mode`` and ``Sec-Fetch-Dest``, when
    sent, are ``navigate`` and ``document``."""
    mode, destination = _header(scope, b'sec-fetch-mode'), _header(scope, b'sec-fetch-dest')
    return mode in (None, 'navigate') and destination in (None, 'document')


def token_matches(value: Any, token: str) -> bool:
    """``tokenMatches`` of webapp/server/local-compute-server.mjs."""
    return (isinstance(value, str) and _CSRF_TOKEN.fullmatch(value) is not None and len(value) == len(token)
            and hmac.compare_digest(value.encode('ascii'), token.encode('ascii')))


def write_refusal(path: str) -> str:
    """Node's message for a write without a valid ``X-EEG-Compute-Token`` on ``path``."""
    for prefix, message in _WRITE_REFUSALS:
        if path == prefix or path.startswith(prefix + '/'):
            return message
    if path.startswith('/api/community/'):
        return _COMMUNITY_REFUSED
    return _WRITE_REFUSED


def _secret_equal(value: str, secret: str) -> bool:
    return hmac.compare_digest(value.encode('latin-1', 'replace'), secret.encode('ascii'))


class AccessControl:
    """ASGI middleware, outermost: the guard, the session cookie and the CSRF token, then ``app``."""

    def __init__(self, app: Any, tokens: Tokens, port: int):
        self.app = app
        self.tokens = tokens
        self.cookie = cookie_name(port)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        path = raw_path(scope)
        method = scope['method']
        if not loopback_request(scope) and not self._launched(scope, path, method):
            await error_response(403, FORBIDDEN)(scope, receive, send)
            return
        if path == '/open':
            if method in WRITE_METHODS and not token_matches(_header(scope, b'x-eeg-compute-token'), self.tokens.csrf):
                await error_response(403, write_refusal(path))(scope, receive, send)
            elif method != 'GET':
                await _send(send, 405, [(b'allow', b'GET'), (b'content-type', b'text/plain; charset=utf-8')],
                            b'Method Not Allowed', method == 'HEAD')
            else:
                await self._open(scope, send)
            return
        if not self._has_session(scope):
            if path.startswith('/api/'):
                await error_response(401, SESSION_EXPIRED)(scope, receive, send)
            else:
                await _send(send, 401, _PAGE_HEADERS, SESSION_PAGE, method == 'HEAD')
            return
        if method in WRITE_METHODS and not token_matches(_header(scope, b'x-eeg-compute-token'), self.tokens.csrf):
            await error_response(403, write_refusal(path))(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _launched(self, scope: Any, path: str, method: str) -> bool:
        """``GET /open`` with the launch token from the launcher's page: a cross-site top-level navigation."""
        return (path == '/open' and method == 'GET' and _launch_navigation(scope)
                and loopback_request(scope, ('same-origin', 'none', 'cross-site'))
                and _secret_equal(self._launch_token(scope), self.tokens.launch))

    @staticmethod
    def _launch_token(scope: Any) -> str:
        query = parse_qsl(scope.get('query_string', b'').decode('latin-1'), keep_blank_values=True)
        return query[0][1] if len(query) == 1 and query[0][0] == 'token' else ''

    def _has_session(self, scope: Any) -> bool:
        cookies = _header(scope, b'cookie', separator='; ')
        if not cookies:
            return False
        found = False
        for part in cookies.split(';'):
            name, separator, value = part.strip().partition('=')
            if separator and name == self.cookie:
                # Every candidate is compared, so the time taken does not depend on which one matched.
                found = _secret_equal(value, self.tokens.session) or found
        return found

    async def _open(self, scope: Any, send: Any) -> None:
        if not _secret_equal(self._launch_token(scope), self.tokens.launch):
            await _send(send, 401, _PAGE_HEADERS, SESSION_PAGE)
            return
        cookie = (b'set-cookie', f'{self.cookie}={self.tokens.session}; HttpOnly; SameSite=Strict; Path=/'.encode())
        if _header(scope, b'sec-fetch-site') == 'cross-site':
            await _send(send, 200, [*_PAGE_HEADERS, cookie], LAUNCH_PAGE)
            return
        # The target is relative and never built from Host.
        await _send(send, 303, [(b'location', b'/'), cookie, (b'cache-control', b'no-store'),
                                (b'referrer-policy', b'no-referrer')], b'')


async def _send(send: Any, status: int, headers: list[tuple[bytes, bytes]], body: bytes, head: bool = False) -> None:
    headers = [*headers, (b'content-length', str(len(body)).encode('ascii'))]
    await send({'type': 'http.response.start', 'status': status, 'headers': headers})
    await send({'type': 'http.response.body', 'body': b'' if head else body})
