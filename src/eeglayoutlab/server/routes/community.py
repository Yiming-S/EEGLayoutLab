"""``GET /api/community/status`` (phase 2 slice 4) and the signal records (slice 7): Node's ``communityMiddleware``
(community-queue.mjs:504-519) for one local user.

``/api/community/status`` is the task menu of the interface (components/community-status.tsx). Node serves it as
``scheduler.stats(visitor)``. Here it is ``WorkspaceQueue.stats()``: ``{queued_tasks, running_tasks, available,
resource_blocked, recovery_blocked, maintenance, drained, jobs}``, with ``jobs`` the last 12 receipts of the
workspace, newest first, viewed without their results. There is no ``online_visitors`` and no ``POST
/api/community/heartbeat``: visitors are not carried over, and the interface reads this route on both hosts.

``/api/community/records`` is ``WorkspaceQueue.records()``: ``{schema: 'browser-experiment-records/1', scope:
'workspace', receipt_limit, records}``, the newest completed signal-reception receipt of each result in the
workspace, newest first, with its catalog metadata and no waveforms. Node's scope is ``current_browser``: its list
is one browser's.

``/api/community/records/<id>/result`` is ``{result}``, the saved result of that receipt read through the identity
it was computed under (``ReceptionJobs.saved_result``; the request is not prepared again, so a model or code change
since does not hide it). An unknown identifier, or one of another kind, is 404 ``任务不存在或不属于当前浏览器``; a
receipt that is not completed is 404 ``计算记录无法读取，请重新提交``; a result that is gone or fails its checks is
Node's answer for that failure (``routes.compute.public_failure``). There is no rate limit and no gate on
concurrent reads.

Other paths under ``/api/community/`` are 404 ``Unknown community endpoint``, and so are these while no queue is
started.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response

from ..app import error_response, json_response
from .compute import failure_response, json_answer

if TYPE_CHECKING:
    from ..app import ServiceConfig
    from .compute import ComputeHost

UNKNOWN_ENDPOINT = 'Unknown community endpoint'
# The receipt identifier of Node's route pattern.
RECORD_ID = re.compile('[a-f0-9-]{36}')


def add_routes(app: FastAPI, config: 'ServiceConfig', compute: 'ComputeHost') -> None:
    async def status(request: Request) -> Response:
        queue = compute.queue
        if queue is None:
            return error_response(404, UNKNOWN_ENDPOINT)
        try:
            return json_response(200, await queue.stats())
        except Exception as error:  # noqa: BLE001 - Node's catch block
            return failure_response(error)

    async def records(request: Request) -> Response:
        queue = compute.queue
        if queue is None:
            return error_response(404, UNKNOWN_ENDPOINT)
        try:
            return json_response(200, queue.records())
        except Exception as error:  # noqa: BLE001 - Node's catch block
            return failure_response(error)

    async def saved_result(request: Request) -> Response:
        id = request.path_params['id']
        queue = compute.queue
        if queue is None or not RECORD_ID.fullmatch(id):
            return error_response(404, UNKNOWN_ENDPOINT)
        try:
            result = await queue.saved_result(id)
        except Exception as error:  # noqa: BLE001 - Node's catch block
            return failure_response(error)
        return await json_answer(200, {'result': result})

    app.add_api_route('/api/community/status', status, methods=['GET'], include_in_schema=False,
                      name='community_status')
    app.add_api_route('/api/community/records', records, methods=['GET'], include_in_schema=False,
                      name='community_records')
    # The identifier is read from the path parameters rather than declared as a parameter (routes.library).
    app.add_api_route('/api/community/records/{id}/result', saved_result, methods=['GET'], include_in_schema=False,
                      name='community_record_result')
