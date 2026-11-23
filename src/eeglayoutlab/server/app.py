"""The local HTTP service (design 0001, decision 6).

``create_app(config)`` builds the service of one process. Every request passes the access checks of
``server.access`` first (guard, session cookie, CSRF token for writes); then paths under ``/api/`` go to the JSON
API and every other path to the static interface (``server.static``). The API has, so far, the health routes of
the four task kinds (``routes.health``), the read-only library and catalogs (``routes.library``) and, for every
request format, a diagnostic endpoint that returns the canonical request.

The transport follows the route that serves the Node host's job submissions (``communityMiddleware`` in
webapp/server/community-queue.mjs), so the interface sees the same answers:

- a request body must be JSON: ``Content-Type`` must start with ``application/json`` (case-sensitive, as in
  Node), else 415;
- at most the route's limit as received (``BODY_LIMITS``), else 413;
- the whole body is decoded as UTF-8 with replacement and parsed with JavaScript's rules (``schemas.jsjson``),
  else 400;
- JSON responses are written with ``JSON.stringify`` semantics and carry ``X-EEG-API-Version: 1``,
  ``Cache-Control: no-store``, ``X-Content-Type-Options: nosniff`` and
  ``Cross-Origin-Resource-Policy: same-origin``; errors are ``{"error": ..., "code": ...}``;
- an unknown path or method under one of Node's API prefixes gets Node's 404 message (``node_fallback``), and
  an unexpected exception a generic 500 (the library routes answer Node's own 500 instead: ``routes.library``).
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from fastapi import FastAPI, Request, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from .. import API_VERSION
from ..schemas import jsjson
from ..schemas.registry import REQUEST_FORMATS, RequestFormat

if TYPE_CHECKING:
    from ..jobs.runtime import RuntimeConfig
    from .access import Tokens
    from .workspace import UserContext

LOG = logging.getLogger('eeglayoutlab.server')

# Node's limit for design evaluation, the largest request kind; the diagnostic endpoints share it.
MAX_BODY_BYTES = 65536
# Node's limit per task kind (communityMiddleware, community-queue.mjs), as received.
BODY_LIMITS = {'design-evaluation': 65536, 'electrode-editor': 32768, 'local-compute': 4096, 'source-reception': 4096}
ERROR_CODES = {
    400: 'invalid_request', 401: 'authentication_required', 403: 'request_forbidden', 404: 'not_found',
    405: 'method_not_allowed', 409: 'compute_busy', 413: 'request_too_large', 415: 'unsupported_media_type',
    429: 'queue_limited', 500: 'internal_error', 503: 'service_unavailable',
}
HEADERS = {
    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    'Cross-Origin-Resource-Policy': 'same-origin', 'X-EEG-API-Version': API_VERSION,
}
# The Node host's messages (community-queue.mjs and http/public-errors.mjs), which the interface may show.
NOT_JSON_MEDIA = 'JSON required'
TOO_LARGE = '配置过大'
NOT_JSON = '请求内容不是有效的JSON'
INTERNAL_MESSAGE = '服务器内部错误，已记录；请稍后重试'
NOT_FOUND = 'Not Found'
_QUEUE_ENDPOINT = re.compile(
    r'/api/(?:local-compute|source-reception|design-evaluation|electrode-editor)/(?:jobs|lookup|health)'
    r'(?:/[a-f0-9-]{36}(?:/cancel)?)?')


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class ServiceConfig:
    """What one service process serves."""

    root: str
    """R, the scientific root, spelled as ``jobs.runtime.repository_root`` gives it (the string Node uses)."""
    port: int
    """The bound port; it names the session cookie."""
    tokens: 'Tokens'
    user: 'UserContext'
    static_dir: Optional[str] = None
    """The static export (``webapp/dist/client``); until it is built (its ``index.html`` is there), pages answer
    503."""
    runtime: Optional['RuntimeConfig'] = None
    """The root and interpreters (``jobs.runtime.runtime_config``); by default ``runtime_config(root)`` on first
    use, with ``EEG_COMPUTE_PYTHON`` as Node reads it."""


def json_response(status: int, value: Any) -> Response:
    return Response(jsjson.stringify(value).encode('utf-8'), status_code=status,
                    media_type='application/json; charset=utf-8', headers=HEADERS)


def error_response(status: int, message: str) -> Response:
    return json_response(status, {'error': message, 'code': ERROR_CODES.get(status, 'request_failed')})


async def read_json_body(request: Request, limit: int = MAX_BODY_BYTES) -> Any:
    """The parsed body, or ``ApiError`` with Node's status: 415, then 413 (more than ``limit`` bytes as
    received), then 400."""
    if not request.headers.get('content-type', '').startswith('application/json'):
        raise ApiError(415, NOT_JSON_MEDIA)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise ApiError(413, TOO_LARGE)
    try:
        return jsjson.parse(jsjson.decode_body(bytes(body)))
    except ValueError as error:
        raise ApiError(400, NOT_JSON) from error


def raw_path(scope: Any) -> str:
    """The path as received (Node's ``req.url`` without its query): not percent-decoded."""
    raw = scope.get('raw_path')
    return raw.decode('latin-1') if raw is not None else scope['path']


def node_fallback(path: str) -> Optional[str]:
    """Node's 404 message for an unknown path or method under one of its API prefixes, taken in the order its
    middleware layers claim a path (endpoints.md sections 1.3 and 3); ``None`` outside them."""
    if path == '/api/robustness-studies' or path.startswith('/api/robustness-studies/'):
        return 'Study not found.'
    if path == '/api/projects' or path.startswith('/api/projects/'):
        return 'Project endpoint not found.'
    if _QUEUE_ENDPOINT.fullmatch(path):
        return 'Unknown queue endpoint'
    if path.startswith('/api/community/'):
        return 'Unknown community endpoint'
    # computeMiddleware matches these prefixes without a trailing slash.
    if path.startswith('/api/source-reception'):
        return '未知源实验接口'
    if path.startswith('/api/design-evaluation'):
        return '未知设计评价接口'
    if path.startswith('/api/electrode-editor'):
        return 'Unknown editor endpoint'
    if path.startswith('/api/local-compute'):
        return '未知计算接口'
    return None


def validation_message(error: ValueError) -> str:
    if isinstance(error, ValidationError):
        parts = [f"{'.'.join(str(part) for part in item['loc']) or 'body'}: {item['msg']}" for item in error.errors()]
        return '; '.join(parts)[:500]
    return str(error)[:500]


def normalize_endpoint(format: RequestFormat) -> Callable[[Request], Awaitable[Response]]:
    async def normalize(request: Request) -> Response:
        value = await read_json_body(request)
        try:
            canonical = format.normalize(value)
        except ValueError as error:
            raise ApiError(400, validation_message(error)) from error
        return json_response(200, {'canonical': canonical, 'canonical_sha256': jsjson.sha256_hex(canonical)})

    normalize.__name__ = 'normalize_' + format.name.replace('-', '_')
    return normalize


class RawPathRouting:
    """Routes match the path as received, as the Node host matches ``req.url``: a percent-encoded spelling of a
    route (``/api/normalize/coordinate%2Dsource``) is not that route."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope['type'] == 'http' and raw_path(scope) != scope['path']:
            await error_response(404, node_fallback(raw_path(scope)) or NOT_FOUND)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _api(config: ServiceConfig) -> FastAPI:
    from .openapi import openapi_text
    from .routes import health, library

    # The interactive documentation pages load scripts from a CDN, which a local-first service does not do.
    # A trailing slash is an unknown path (404), as in Node, not a redirect built from the Host header.
    app = FastAPI(title='EEGLayoutLab', version=API_VERSION, docs_url=None, redoc_url=None, openapi_url=None,
                  redirect_slashes=False)
    app.add_middleware(RawPathRouting)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, error: ApiError) -> Response:
        return error_response(error.status, error.message)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> Response:
        # Node answers a wrong method on its routes as an unknown path.
        if error.status_code in (404, 405):
            fallback = node_fallback(raw_path(request.scope))
            if fallback is not None:
                return error_response(404, fallback)
        return error_response(error.status_code, str(error.detail))

    @app.exception_handler(Exception)
    async def internal_error(_: Request, error: Exception) -> Response:
        return error_response(500, INTERNAL_MESSAGE)

    health.add_routes(app, config)
    library.add_routes(app, config)
    for format in REQUEST_FORMATS.values():
        app.add_api_route(f'/api/normalize/{format.name}', normalize_endpoint(format), methods=['POST'],
                          include_in_schema=False)

    @app.get('/api/openapi.json', include_in_schema=False)
    async def openapi() -> Response:
        # The document has integer-like keys (the response statuses), which JSON.stringify would reorder, so it
        # is served as written by openapi_text(), byte-identical to contracts/generated/openapi.json.
        return Response(openapi_text().encode('utf-8'), status_code=200,
                        media_type='application/json; charset=utf-8', headers=HEADERS)

    return app


class Service:
    """The ASGI application: access control, then the API (``/api/...``) or the static interface."""

    def __init__(self, config: ServiceConfig):
        from .access import AccessControl
        from .static import StaticExport

        self.config = config
        self.api = _api(config)
        self.static = StaticExport(config.static_dir)
        self.access = AccessControl(self._route, config.tokens, config.port)

    async def _route(self, scope: Any, receive: Any, send: Any) -> None:
        if raw_path(scope).startswith('/api/'):
            await self.api(scope, receive, send)
        else:
            await self.static(scope, receive, send)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope['type'] == 'lifespan':
            await self.api(scope, receive, send)
            return
        if scope['type'] != 'http':
            raise RuntimeError(f'unsupported ASGI scope {scope["type"]!r}')
        started = False

        async def watched(message: Any) -> None:
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)

        try:
            await self.access(scope, receive, watched)
        except Exception:
            # The API's handler has answered already; anything else gets the same generic answer. The details
            # stay in the service log.
            LOG.exception('internal error on %s %s', scope.get('method'), raw_path(scope))
            if not started:
                await error_response(500, INTERNAL_MESSAGE)(scope, receive, send)


def create_app(config: ServiceConfig) -> Service:
    return Service(config)
