"""Job queue and radius-search HTTP routes (phase 2 slice 4).

Serves:
- ``GET /api/community/status``: ``WorkspaceQueue.stats()`` (without ``online_visitors`` or client IPs);
- ``GET /api/community/records``: ``WorkspaceQueue.records()``;
- ``POST /api/local-compute/lookup``: cache/pending lookup without starting a worker;
- ``POST /api/local-compute/jobs``: enqueue or return cached/shared radius job (202);
- ``GET /api/local-compute/jobs/<uuid>``: read job view (200 or 404);
- ``POST /api/local-compute/jobs/<uuid>/cancel``: cancel queued or running job (202 or 404).
"""
from __future__ import annotations

import os
import re
import threading
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request, Response

from ..app import BODY_LIMITS, ApiError, error_response, json_response, node_fallback, raw_path, read_json_body
from ..workspace import STATE

if TYPE_CHECKING:
    from ...jobs.queue import WorkspaceQueue
    from ...jobs.radius import RadiusService
    from ...jobs.worker import ExecutionSlot
    from ..app import ServiceConfig
    from .library import LibraryRoutes

JOB_ID = re.compile('[a-f0-9-]{36}')
ANNOTATION_HEX = re.compile('[a-f0-9]{64}')


def _check_job_query(query: bytes) -> Optional[str]:
    pairs = parse_qsl(query.decode('latin-1'), keep_blank_values=True)
    names = [name for name, _ in pairs]
    if any(name != 'annotation_id' for name in names) or names.count('annotation_id') > 1:
        raise ApiError(400, 'Unsupported task query.')
    if not pairs:
        return None
    val = pairs[0][1]
    if not ANNOTATION_HEX.fullmatch(val):
        raise ApiError(400, 'Invalid electrode name annotation.')
    return val


class QueueRoutes:
    """Lazy-initialized ``ExecutionSlot``, ``RadiusService`` and ``WorkspaceQueue`` of one service process."""

    def __init__(self, config: 'ServiceConfig', library_routes: 'LibraryRoutes'):
        self.config = config
        self.library_routes = library_routes
        self._lock = threading.RLock()
        self._slot: Optional[ExecutionSlot] = None
        self._radius: Optional[RadiusService] = None
        self._queue: Optional[WorkspaceQueue] = None

    def _queue_dir(self) -> str:
        from ...jobs import nodepath
        return nodepath.join(self.config.user.workspace, STATE, 'queue')

    def has_persisted_queue(self) -> bool:
        return os.path.isfile(os.path.join(self._queue_dir(), 'queue.json'))

    def queue(self) -> 'WorkspaceQueue':
        from ...jobs.queue import WorkspaceQueue, radius_adapter
        from ...jobs.radius import RadiusService
        from ...jobs.worker import ExecutionSlot

        with self._lock:
            if self._queue is not None:
                return self._queue
            runtime = self.library_routes.runtime()
            store = self.library_routes.library().store
            self._slot = ExecutionSlot()
            self._radius = RadiusService(
                runtime.repository_root,
                python=runtime.python,
                store=store,
                execution_slot=self._slot,
            )
            self._queue = WorkspaceQueue(
                self._queue_dir(),
                {'local-compute': radius_adapter(self._radius)},
                root=runtime.repository_root,
                owner=self.config.user.owner,
                execution_slot=self._slot,
                cache_only=self.config.cache_only,
            )
            return self._queue

    def active_for_health(self, kind: str) -> Optional[dict[str, Any]]:
        with self._lock:
            q = self._queue
        if q is None and self.has_persisted_queue():
            q = self.queue()
        return q.active(kind) if q is not None else None

    def drained_for_health(self) -> bool:
        if not self.config.cache_only:
            return False
        with self._lock:
            q = self._queue
        if q is None and self.has_persisted_queue():
            q = self.queue()
        return q.drained() if q is not None else True

    def close(self) -> None:
        with self._lock:
            q, r = self._queue, self._radius
        if q is not None:
            q.stop_scheduling()
        if r is not None:
            r.dispose()
        if q is not None:
            q.dispose()


def _translate_queue_error(err: BaseException) -> ApiError:
    from ...jobs.queue import QueueError

    if isinstance(err, ApiError):
        return err
    if isinstance(err, QueueError):
        return ApiError(err.status, err.message)
    if isinstance(err, ValueError):
        return ApiError(400, str(err))
    raise err


def add_routes(app: FastAPI, config: 'ServiceConfig', library_routes: 'LibraryRoutes') -> QueueRoutes:
    routes = QueueRoutes(config, library_routes)

    def status_endpoint() -> Response:
        return json_response(200, routes.queue().stats())

    def records_endpoint() -> Response:
        return json_response(200, routes.queue().records())

    async def lookup_endpoint(request: Request) -> Response:
        raw = await read_json_body(request, BODY_LIMITS['local-compute'])
        try:
            result = routes.queue().submit('local-compute', raw, lookup_only=True)
        except Exception as err:  # noqa: BLE001
            raise _translate_queue_error(err) from err
        return json_response(200, result)

    async def submit_endpoint(request: Request) -> Response:
        raw = await read_json_body(request, BODY_LIMITS['local-compute'])
        try:
            result = routes.queue().submit('local-compute', raw, lookup_only=False)
        except Exception as err:  # noqa: BLE001
            raise _translate_queue_error(err) from err
        return json_response(202, result)

    def get_job_endpoint(request: Request) -> Response:
        job_id = request.path_params['id']
        if not JOB_ID.fullmatch(job_id):
            return error_response(404, node_fallback(raw_path(request.scope)) or 'Not Found')
        _check_job_query(request.scope.get('query_string', b''))
        try:
            q = routes.queue()
            task = q.get_task(job_id, 'local-compute')
            return json_response(200, {'job': q.view(task, include_result=True)})
        except Exception as err:  # noqa: BLE001
            raise _translate_queue_error(err) from err

    def cancel_job_endpoint(request: Request) -> Response:
        job_id = request.path_params['id']
        if not JOB_ID.fullmatch(job_id):
            return error_response(404, node_fallback(raw_path(request.scope)) or 'Not Found')
        try:
            return json_response(202, {'job': routes.queue().cancel(job_id, 'local-compute')})
        except Exception as err:  # noqa: BLE001
            raise _translate_queue_error(err) from err

    app.add_api_route('/api/community/status', status_endpoint, methods=['GET'], include_in_schema=False)
    app.add_api_route('/api/community/records', records_endpoint, methods=['GET'], include_in_schema=False)
    app.add_api_route('/api/local-compute/lookup', lookup_endpoint, methods=['POST'], include_in_schema=False)
    app.add_api_route('/api/local-compute/jobs', submit_endpoint, methods=['POST'], include_in_schema=False)
    app.add_api_route('/api/local-compute/jobs/{id}', get_job_endpoint, methods=['GET'], include_in_schema=False)
    app.add_api_route('/api/local-compute/jobs/{id}/cancel', cancel_job_endpoint, methods=['POST'],
                      include_in_schema=False)
    return routes
