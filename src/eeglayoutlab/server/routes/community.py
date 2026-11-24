"""``GET /api/community/status`` (phase 2 slice 4): the task menu of the interface (components/community-status.tsx).

Node serves it from ``communityMiddleware`` (community-queue.mjs:505) as ``scheduler.stats(visitor)``. Here it is
``WorkspaceQueue.stats()``: ``{queued_tasks, running_tasks, available, resource_blocked, recovery_blocked,
maintenance, drained, jobs}``, with ``jobs`` the last 12 receipts of the workspace, newest first, viewed without
their results. There is no ``online_visitors`` and no ``POST /api/community/heartbeat``: visitors are not carried
over, and the interface reads this route on both hosts. Other paths under ``/api/community/`` (the signal records
of slice 7 among them) are 404 ``Unknown community endpoint``, and so is this one while no queue is started.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response

from ..app import error_response, json_response
from .compute import failure_response

if TYPE_CHECKING:
    from ..app import ServiceConfig
    from .compute import ComputeHost

UNKNOWN_ENDPOINT = 'Unknown community endpoint'


def add_routes(app: FastAPI, config: 'ServiceConfig', compute: 'ComputeHost') -> None:
    async def status(request: Request) -> Response:
        queue = compute.queue
        if queue is None:
            return error_response(404, UNKNOWN_ENDPOINT)
        try:
            return json_response(200, await queue.stats())
        except Exception as error:  # noqa: BLE001 - Node's catch block
            return failure_response(error)

    app.add_api_route('/api/community/status', status, methods=['GET'], include_in_schema=False,
                      name='community_status')
