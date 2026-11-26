"""The research-project routes (phase 2 slice 9): Node's project middleware (``ProjectService.middleware``,
webapp/server/projects/service.mjs:82-140) for the one local user.

As in Node's composed service (local-compute-server.mjs:460), the project middleware comes after the study middleware
and before every other API route: each request whose path (as received, without its query) is ``/api/projects`` or
starts with ``/api/projects/`` is served here, whatever its method. ``server.access`` has checked it first: the guard
(403 ``Request rejected by access policy.``), the session and, for a write (``POST``, ``PATCH``, ``DELETE``, also
``PUT``), the token (403 ``Refresh the page before saving the project.``). Then
``workspace_projects.ProjectService.handle`` answers:

- ``GET /api/projects``: 200 ``{projects}``, the workspace's projects, most recently updated first (new: Node has no
  list and answers 405);
- ``POST /api/projects``: 201 ``{project, role: 'owner', access_key}``, a new project in ``W/projects``; the access
  key is random and stored nowhere;
- ``GET`` and ``PATCH /api/projects/<id>``: 200 ``{project, role}``;
- ``POST /api/projects/<id>/entries``: 201 ``{project, role, entry}``, a snapshot of a completed layout, electrode
  edit or signal receipt of the workspace;
- ``GET``, ``PATCH`` and ``DELETE /api/projects/<id>/entries/<entry>``: 200 (``DELETE`` names the revision it
  replaces in its body, ``{revision}``, or in ``If-Match``);
- ``GET /api/projects/<id>/export``: 200, the ``eeg-research-delivery/1`` delivery
  (``server.delivery.ProjectDelivery``), with ``Content-Disposition: attachment; filename="eeg-research-<id>.json"``.

Node's refusals, in Node's order: another method 405 ``Unsupported project method.``, a query (any ``?``) 400 ``Project
API credentials and parameters must not use a query string.``, a path that names no project or names ``share`` or
``revoke-share`` (credentials are not carried over) 404 ``Project endpoint not found.``, an unknown project 404
``Project not found.``, a write once the service stops (its store is closed first) 503 ``Project store is
stopping.``, a body that is not JSON 415 ``JSON is required.``, more than 65,536 bytes as received 413 ``Project
request is too large.``, text that does not parse or is not an object 400 ``Invalid project JSON.``, another operation
405 ``Unsupported project operation.``; a refusal of the store, the request formats or the delivery keeps its status
and message, and any other failure is 500 ``Project storage or scientific record is unavailable.`` (logged). The
``X-EEG-Project-Key`` header is accepted and ignored.

Answers are written as Node's ``sendJson`` writes them (``routes.studies.study_response``): ``JSON.stringify`` bytes in
a worker thread (an entry holds up to 16 MiB of snapshot), an error with ``code`` added for its status, the API
headers, ``Retry-After`` for a resource refusal that names one; a delivery's bytes come from
``server.delivery.delivery_json`` (up to 32 MiB). Until the application's lifespan has started the project service
(``ComputeHost.projects``), every such path is 404 ``Project endpoint not found.``. The module imports no job module,
so building the application loads none.

Known differences from Node, beyond the store's (``workspace_projects``): the access policy runs before routing, so a
write without the token is 403 where Node answers 405 for ``PUT`` or 400 for a query; a lone ``?`` reaches the service
as no query (ASGI drops it), so it is served where Node answers 400; every request needs the service's session cookie
(401); Node's per-browser rate limit is not ported (R1).
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Optional

from fastapi import Request, Response

from ..app import HEADERS, error_response, raw_path
from .studies import study_response

if TYPE_CHECKING:
    from .compute import ComputeHost

__all__ = ['PREFIX', 'ENDPOINT', 'DISPOSITION', 'ProjectRoutes', 'project_path', 'project_response']

PREFIX = '/api/projects'
ENDPOINT = 'Project endpoint not found.'
DISPOSITION = 'Content-Disposition'


def project_path(path: str) -> bool:
    """Whether the project middleware claims ``path`` (the request target's path as received)."""
    return path == PREFIX or path.startswith(PREFIX + '/')


def _header(scope: Any, name: bytes) -> Optional[str]:
    """A request header as Node's ``req.headers`` has it: repeated values joined with ``', '`` (``If-Match``), read as
    Latin-1; ``None`` when absent."""
    values = [value.decode('latin-1') for key, value in scope['headers'] if key.lower() == name]
    return ', '.join(values) if values else None


def project_response(status: int, value: Any, headers: dict[str, str]) -> Response:
    """Node's ``send(status, value)`` of the project middleware. A delivery (the export's answer, the only one with a
    ``Content-Disposition``) is written by ``delivery_json``, which gives ``JSON.stringify``'s text of its file
    contents faster than ``jsjson.stringify``."""
    if status == 200 and DISPOSITION in headers:
        from ..delivery import delivery_json

        return Response(delivery_json(value).encode('utf-8'), status_code=status,
                        media_type='application/json; charset=utf-8', headers={**HEADERS, **headers})
    return study_response(status, value, headers)


class ProjectRoutes:
    """The ASGI handler of the project paths over ``compute``'s project service."""

    def __init__(self, compute: 'ComputeHost'):
        self.compute = compute

    @staticmethod
    def claims(path: str) -> bool:
        return project_path(path)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        service = self.compute.projects
        if service is None:
            await error_response(404, ENDPOINT)(scope, receive, send)
            return
        request = Request(scope, receive)
        # Node tests req.url for '?'; a request target whose query is empty reaches an ASGI application without it.
        status, value, headers = await service.handle(
            scope['method'], raw_path(scope), query=bool(scope.get('query_string')),
            content_type=request.headers.get('content-type'), body=request.stream(),
            if_match=_header(scope, b'if-match'))
        response = await asyncio.to_thread(project_response, status, value, headers)
        await response(scope, receive, send)

