"""The robustness-study routes (phase 2 slice 8): Node's study middleware (``RobustnessStudyService.middleware``,
webapp/server/studies/service.mjs:601-657) for the one local user.

As in Node's composed service (local-compute-server.mjs:460), the study middleware comes before every other API
route: each request whose path (as received, without its query) is ``/api/robustness-studies`` or starts with
``/api/robustness-studies/`` is served here, whatever its method. ``server.access`` has checked it first: the guard
(403 ``Request rejected by access policy.``), the session and, for a write, the token (403 ``Refresh the page before
changing a study.``). Then ``workspace_studies.RobustnessStudyService.handle`` answers:

- ``GET /api/robustness-studies``: 200 ``{studies}``, every study of the workspace;
- ``POST /api/robustness-studies``: 201 ``{study}``, a new draft (its cases are prepared, none is submitted);
- ``GET /api/robustness-studies/<id>``: 200 ``{study}``; ``GET /api/robustness-studies/<id>/export``: 200, the
  ``eeg-robustness-study-export/1`` envelope with each completed case's archived ``cache.json`` and its exact text;
- ``POST /api/robustness-studies/<id>/start``, ``/resume`` and ``/cancel`` with a body that is exactly ``{}``: 200
  ``{study}``.

Its refusals are Node's, in Node's order: a query (any ``?``) 400 ``Study API queries are not supported.``, a method
other than GET and POST 405 ``Unsupported study method.``, a path that names no study 404 ``Study not found.``, a body
that is not JSON 415 ``JSON is required.``, more than 65,536 bytes as received 413 ``Study request is too large.``,
text that does not parse 400 ``Invalid study JSON.``, a control body other than ``{}`` 400, another operation 405
``Unsupported study operation.``; a refusal of the protocol, the store or the service keeps its status and message,
and any other failure is 500 ``Study storage or scientific input is unavailable.`` (logged).

Answers are written as Node's ``sendJson`` writes them: ``JSON.stringify`` bytes (in a worker thread: an export holds
up to 64 MiB of caches), an error with ``code`` added for its status, the API headers, and ``Retry-After`` for a
resource refusal that names one. The export is this JSON too; the interface makes the download from it.

Until the application's lifespan has started the study service (``ComputeHost.studies``), every such path is 404
``Study not found.``. The module imports no job module, so building the application loads none.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastapi import Request, Response

from ...schemas import jsjson
from ..app import ERROR_CODES, HEADERS, error_response, raw_path

if TYPE_CHECKING:
    from .compute import ComputeHost

__all__ = ['PREFIX', 'NOT_FOUND', 'StudyRoutes', 'study_path', 'study_response']

PREFIX = '/api/robustness-studies'
NOT_FOUND = 'Study not found.'


def study_path(path: str) -> bool:
    """Whether the study middleware claims ``path`` (the request target's path as received)."""
    return path == PREFIX or path.startswith(PREFIX + '/')


def study_response(status: int, value: Any, headers: dict[str, str]) -> Response:
    """Node's ``sendJson(res, status, value)``: an error object gets ``code`` (``codes[status]`` or
    ``request_failed``), and the body is ``JSON.stringify(value)`` with the API headers and ``headers``."""
    if status >= 400 and isinstance(value, dict) and isinstance(value.get('error'), str):
        value = {**value, 'code': value.get('code') or ERROR_CODES.get(status, 'request_failed')}
    return Response(jsjson.stringify(value).encode('utf-8'), status_code=status,
                    media_type='application/json; charset=utf-8', headers={**HEADERS, **headers})


class StudyRoutes:
    """The ASGI handler of the study paths over ``compute``'s study service."""

    def __init__(self, compute: 'ComputeHost'):
        self.compute = compute

    @staticmethod
    def claims(path: str) -> bool:
        return study_path(path)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        service = self.compute.studies
        if service is None:
            await error_response(404, NOT_FOUND)(scope, receive, send)
            return
        request = Request(scope, receive)
        # Node tests req.url for '?'; a request target whose query is empty reaches an ASGI application without it.
        status, value, headers = await service.handle(
            scope['method'], raw_path(scope), query=bool(scope.get('query_string')),
            content_type=request.headers.get('content-type'), body=request.stream())
        response = await asyncio.to_thread(study_response, status, value, headers)
        await response(scope, receive, send)
