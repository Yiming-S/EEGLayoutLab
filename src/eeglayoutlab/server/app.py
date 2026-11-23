"""The local HTTP service (design 0001, decision 6).

Phase 1 provides the transport rules and, for every request format, a diagnostic endpoint that returns the
canonical request. The computing endpoints, the queue and the access token follow in phase 2.

The transport follows the route that serves the Node host's job submissions (``communityMiddleware`` in
webapp/server/community-queue.mjs), so the interface sees the same answers:

- a request body must be JSON: ``Content-Type`` must start with ``application/json`` (case-sensitive, as in
  Node), else 415;
- at most 65,536 bytes as received, else 413;
- the whole body is decoded as UTF-8 with replacement and parsed with JavaScript's rules (``schemas.jsjson``),
  else 400;
- JSON responses are written with ``JSON.stringify`` semantics and carry ``X-EEG-API-Version: 1``,
  ``Cache-Control: no-store``, ``X-Content-Type-Options: nosniff`` and
  ``Cross-Origin-Resource-Policy: same-origin``; errors are ``{"error": ..., "code": ...}``.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from .. import API_VERSION
from ..schemas import jsjson
from ..schemas.registry import REQUEST_FORMATS, RequestFormat

# Node's limit for design evaluation, the largest request kind; the diagnostic endpoints share it. Phase 2 gives
# each submission endpoint Node's limit for its kind (32,768 bytes for electrode editing, 4,096 for the others).
MAX_BODY_BYTES = 65536
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


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def json_response(status: int, value: Any) -> Response:
    return Response(jsjson.stringify(value).encode('utf-8'), status_code=status,
                    media_type='application/json; charset=utf-8', headers=HEADERS)


def error_response(status: int, message: str) -> Response:
    return json_response(status, {'error': message, 'code': ERROR_CODES.get(status, 'request_failed')})


async def read_json_body(request: Request) -> Any:
    """The parsed body, or ``ApiError`` with Node's status: 415, then 413, then 400."""
    if not request.headers.get('content-type', '').startswith('application/json'):
        raise ApiError(415, NOT_JSON_MEDIA)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise ApiError(413, TOO_LARGE)
    try:
        return jsjson.parse(jsjson.decode_body(bytes(body)))
    except ValueError as error:
        raise ApiError(400, NOT_JSON) from error


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
        raw = scope.get('raw_path') if scope['type'] == 'http' else None
        if raw is not None and raw.decode('latin-1') != scope['path']:
            await error_response(404, 'Not Found')(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    from .openapi import openapi_text

    # The interactive documentation pages load scripts from a CDN, which a local-first service does not do.
    # A trailing slash is an unknown path (404), as in Node, not a redirect built from the Host header.
    app = FastAPI(title='EEGLayoutLab', version=API_VERSION, docs_url=None, redoc_url=None, openapi_url=None,
                  redirect_slashes=False)
    app.add_middleware(RawPathRouting)

    @app.exception_handler(ApiError)
    async def api_error(_: Request, error: ApiError) -> Response:
        return error_response(error.status, error.message)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException) -> Response:
        return error_response(error.status_code, str(error.detail))

    @app.exception_handler(Exception)
    async def internal_error(_: Request, error: Exception) -> Response:
        return error_response(500, INTERNAL_MESSAGE)

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
