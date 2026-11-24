"""``GET /api/{local-compute,design-evaluation,source-reception,electrode-editor}/health``.

Node serves the four from ``communityMiddleware`` (community-queue.mjs) with the same body,
``{...queue.health(), ...scheduler.maintenanceStatus(), active_job}``, so the members keep that order:
``LocalComputeQueue.health()`` (local-compute-server.mjs) first, then ``maintenance`` and ``drained``, with
``active_job`` keeping its first position. ``token`` is the CSRF token every write sends back as
``X-EEG-Compute-Token``; health is reachable only with the session cookie. A failure while the active receipt is
viewed (its electrode-name annotation missing or failing its checks) is answered as the job routes answer it
(``compute.failure_response``: 404 or 409 with the annotation's message), as Node's middleware catches it.

With the workspace queue started (the application's lifespan, ``routes.compute.ComputeHost``), ``active_job`` is
the first pending receipt of the kind viewed without its result (``WorkspaceQueue.active``), and ``maintenance`` and
``drained`` are the queue's: ``maintenance`` is ``eeglayoutlab serve --cache-only`` (Node's operator maintenance
mode is not carried over), ``drained`` that nothing runs or may still run. Without a queue they are ``null``,
``false`` and ``false``.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional

from fastapi import FastAPI, Response

from ...jobs import nodepath
from ..app import json_response

if TYPE_CHECKING:
    from ..app import ServiceConfig
    from .compute import ComputeHost

KINDS = ('local-compute', 'design-evaluation', 'source-reception', 'electrode-editor')
MASK_CODES = ['PL', 'PR', 'AL', 'AR', 'FL', 'FM', 'FR', 'OL', 'OR']
# LocalComputeQueue's radius timeout, reported for every kind.
TIMEOUT_SECONDS = 180


def available(root: str) -> bool:
    """Whether the radius worker and its bank are present, checked per request as Node does (``existsSync``
    follows links)."""
    return (os.path.exists(nodepath.join(root, 'scripts/run_local_radius_compute.py'))
            and os.path.exists(nodepath.join(root, 'results/v2/current_multiregion_bank.json')))


def health(config: 'ServiceConfig') -> dict[str, Any]:
    return {
        'available': available(config.root), 'local_only': True, 'token': config.tokens.csrf,
        'max_concurrent_jobs': 1, 'threads': 2, 'timeout_seconds': TIMEOUT_SECONDS,
        'supported_masks': MASK_CODES, 'active_job': None, 'maintenance': False, 'drained': False,
    }


def add_routes(app: FastAPI, config: 'ServiceConfig', compute: Optional['ComputeHost'] = None) -> None:
    from .compute import failure_response  # compute imports KINDS from this module

    def route(kind: str) -> Callable[[], Awaitable[Response]]:
        async def endpoint() -> Response:
            body = health(config)
            queue = compute.queue if compute is not None else None
            if queue is not None:
                try:
                    # Assigned in place: active_job keeps its position, as Node's spread keeps it.
                    body['active_job'] = await queue.active(kind)
                    body.update(queue.maintenance_status())
                except Exception as error:  # noqa: BLE001 - Node's catch block (an unreadable annotation: 404, 409)
                    return failure_response(error)
            return json_response(200, body)
        return endpoint

    for kind in KINDS:
        app.add_api_route(f'/api/{kind}/health', route(kind), methods=['GET'], include_in_schema=False,
                          name=f'health_{kind.replace("-", "_")}')
