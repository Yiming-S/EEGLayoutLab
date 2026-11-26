"""``GET /api/{local-compute,design-evaluation,source-reception,electrode-editor}/health``.

Node serves the four from ``communityMiddleware`` (community-queue.mjs) with the same body,
``{...queue.health(), ...scheduler.maintenanceStatus(), active_job}``, so the members keep that order:
``LocalComputeQueue.health()`` (local-compute-server.mjs) first, then ``maintenance`` and ``drained``, with
``active_job`` keeping its first position. ``token`` is the CSRF token every write sends back as
``X-EEG-Compute-Token``; health is reachable only with the session cookie.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Optional

from fastapi import FastAPI, Response

from ...jobs import nodepath
from ..app import json_response

if TYPE_CHECKING:
    from ..app import ServiceConfig
    from .queue import QueueRoutes

KINDS = ('local-compute', 'design-evaluation', 'source-reception', 'electrode-editor')
MASK_CODES = ['PL', 'PR', 'AL', 'AR', 'FL', 'FM', 'FR', 'OL', 'OR']
# LocalComputeQueue's radius timeout, reported for every kind.
TIMEOUT_SECONDS = 180


def available(root: str) -> bool:
    """Whether the radius worker and its bank are present, checked per request as Node does (``existsSync``
    follows links)."""
    return (os.path.exists(nodepath.join(root, 'scripts/run_local_radius_compute.py'))
            and os.path.exists(nodepath.join(root, 'results/v2/current_multiregion_bank.json')))


def health(config: 'ServiceConfig', kind: str = 'local-compute',
           queue_routes: Optional['QueueRoutes'] = None) -> dict[str, Any]:
    active_job = queue_routes.active_for_health(kind) if queue_routes is not None else None
    drained = queue_routes.drained_for_health() if queue_routes is not None else bool(config.cache_only)
    return {
        'available': available(config.root), 'local_only': True, 'token': config.tokens.csrf,
        'max_concurrent_jobs': 1, 'threads': 2, 'timeout_seconds': TIMEOUT_SECONDS,
        'supported_masks': MASK_CODES, 'active_job': active_job,
        'maintenance': bool(config.cache_only), 'drained': drained,
    }


def add_routes(app: FastAPI, config: 'ServiceConfig',
               queue_routes: Optional['QueueRoutes'] = None) -> None:
    def make_endpoint(task_kind: str):
        async def endpoint() -> Response:
            return json_response(200, health(config, task_kind, queue_routes))
        return endpoint

    for kind in KINDS:
        app.add_api_route(f'/api/{kind}/health', make_endpoint(kind), methods=['GET'], include_in_schema=False,
                          name=f'health_{kind.replace("-", "_")}')
