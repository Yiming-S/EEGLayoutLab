"""The job routes of every task kind and the compute services behind them (phase 2 slice 4): Node's
``communityMiddleware`` (community-queue.mjs:489-551) for one local user.

- ``POST /api/{kind}/lookup``: 200 with ``WorkspaceQueue.submit(kind, body, lookup_only=True)``: ``{hit: false}``,
  or ``{hit: true, job}`` for a stored result (its cached receipt) or a pending task of the same key. A lookup never
  writes a record or queues a task.
- ``POST /api/{kind}/jobs``: 202 with ``submit(kind, body)``: ``{job}`` for a new queued receipt, or Node's
  ``{hit: true, job}`` for a stored result or a pending task of the same key.
- ``GET /api/{kind}/jobs/<id>[?annotation_id=<64 hex>]``: 200 ``{job}``, the receipt's view with its result.
- ``POST /api/{kind}/jobs/<id>/cancel``: 202 ``{job}``; no body is read.

As in Node, a body must be JSON (415 ``JSON required``) of at most the kind's limit as received (``BODY_LIMITS``,
413 ``配置过大``) and parse with JavaScript's rules (400 ``请求内容不是有效的JSON``); the view takes only one
``annotation_id`` (else 400 ``Unsupported task query.``) of 64 lowercase hex digits (else 400 ``Invalid electrode
name annotation.``); an unknown receipt is 404 ``任务不存在或不属于当前浏览器``. Failures follow Node's
``publicFailure``: a refusal with a status keeps it (``QueueError``: 503 unavailable or cache-only, 429 queue full,
409, 404, 413), a request the kind refuses (a ``ValueError`` of its normalizer or identity, or the radius search's
``RadiusJobError``) is a 400 with its message, and anything else a 500 with the generic message, logged. The CSRF
token of a write is checked before routing (``server.access``).

``ComputeHost`` holds the services of one process: the radius search (``jobs.radius.RadiusJobs``), the workspace
queue (``jobs.queue.WorkspaceQueue`` in ``W/.eeglayoutlab``) over the kinds wired so far (``jobs.kinds``) and the
execution slot both share, with the installation lock on ``R/results/v2``. The application's lifespan starts it (the
queue's restart rules, ``recover()`` and its dispatcher) and closes it (Node's ``dispose``: no new dispatch, the
running worker stopped with ``server_restart`` and awaited, the queue written once more). A kind without an adapter
(the design evaluation, the editor and the signal simulation until slices 5 to 7), and every kind of an application
whose lifespan never ran, is an unknown endpoint: 404 ``Unknown queue endpoint``, before any body is read.

The modules of ``eeglayoutlab.jobs`` are imported when the services start, not when the application is built.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any, Callable, Optional
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request, Response

from ...jobs import nodepath
from ..app import BODY_LIMITS, INTERNAL_MESSAGE, NOT_JSON, error_response, json_response, node_fallback, raw_path, \
    read_json_body
from ..workspace import STATE
from .health import KINDS

if TYPE_CHECKING:
    from ...jobs.queue import WorkspaceQueue
    from ...jobs.radius import RadiusJobs
    from ...jobs.runtime import RuntimeConfig
    from ...jobs.slot import ExecutionSlot
    from ..app import ServiceConfig

LOG = logging.getLogger('eeglayoutlab.server')

UNKNOWN_ENDPOINT = 'Unknown queue endpoint'
# Node's messages (community-queue.mjs), which the interface may show.
UNSUPPORTED_QUERY = 'Unsupported task query.'
INVALID_ANNOTATION = 'Invalid electrode name annotation.'
ANNOTATION_QUERY = 'annotation_id'
# The receipt identifier of Node's route pattern, and an annotation identifier.
JOB_ID = re.compile('[a-f0-9-]{36}')
ANNOTATION_ID = re.compile('[a-f0-9]{64}')


class Refusal(Exception):
    """A refused request with Node's status and message (Node's ``error(message, status)``)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class ComputeHost:
    """The compute services of one service process, built and started by ``start`` and stopped by ``close``.

    ``runtime`` gives the root and interpreters (the library routes' ``RuntimeConfig``, so both read one
    ``EEG_COMPUTE_PYTHON``). ``radius_options`` and ``queue_options`` are passed to ``RadiusJobs`` and
    ``WorkspaceQueue`` (tests set a timeout, a clock or a bound there before the lifespan starts). ``failure`` is the
    message of a start that failed, or of the queue's last write at shutdown when it failed; the command line reports
    it and exits 1, as Node's host does when its ``dispose`` throws (start.mjs)."""

    def __init__(self, config: 'ServiceConfig', runtime: Optional[Callable[[], 'RuntimeConfig']] = None):
        self.config = config
        self.runtime = runtime
        self.radius_options: dict[str, Any] = {}
        self.queue_options: dict[str, Any] = {}
        self.slot: Optional[ExecutionSlot] = None
        self.radius: Optional[RadiusJobs] = None
        self.queue: Optional[WorkspaceQueue] = None
        self.failure: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_requested = False

    @property
    def directory(self) -> str:
        """The queue's directory, ``W/.eeglayoutlab``."""
        return nodepath.join(nodepath.resolve(self.config.user.workspace), STATE)

    def _build(self) -> tuple['ExecutionSlot', 'RadiusJobs', 'WorkspaceQueue']:
        from ...jobs.kinds import community_adapters
        from ...jobs.queue import WorkspaceQueue
        from ...jobs.radius import RadiusJobs
        from ...jobs.runtime import runtime_config
        from ...jobs.slot import ExecutionSlot, InstallationLock

        runtime = self.runtime() if self.runtime is not None else runtime_config(self.config.root)
        slot = ExecutionSlot(InstallationLock(runtime.repository_root))
        radius = RadiusJobs(runtime.repository_root, runtime.python, execution_slot=slot,
                            token=self.config.tokens.csrf, **self.radius_options)
        queue = WorkspaceQueue(self.directory, community_adapters(radius), slot=slot,
                               cache_only=self.config.cache_only, clear_interrupted=self.config.clear_interrupted,
                               **self.queue_options)
        return slot, radius, queue

    async def start(self) -> None:
        """Builds the services (``queue.json`` is loaded or created and the restart rules applied, in a worker
        thread), then starts the queue: ``recover()`` and its dispatcher. A stop requested before the services exist
        (``stop_soon``) stops them as soon as they are built, so nothing is recovered or dispatched. Raises
        ``QueueStateError`` for a queue file that cannot be used, which stays as it was; ``failure`` then holds the
        message."""
        from ...jobs.queue import QueueStateError

        if self.queue is not None:
            return
        self._loop = asyncio.get_running_loop()
        try:
            self.slot, self.radius, self.queue = await asyncio.to_thread(self._build)
            if self._stop_requested:
                self._stop_now()
                return
            await self.queue.start()
        except QueueStateError as error:
            self.failure = str(error)
            raise
        except Exception as error:
            LOG.exception('the job services did not start')
            self.failure = f'the job services cannot start: {error}'
            raise
        queue = self.queue
        if queue.blocked_pids or queue.unconfirmed:
            waiting = (f'a worker of an earlier run (PID {", ".join(map(str, queue.blocked_pids))})'
                       if queue.blocked_pids else 'a worker start of an earlier run whose outcome is unknown')
            LOG.warning('New computations wait for %s. Once no worker of that run is computing, start again with '
                        '--clear-interrupted.', waiting)

    def stop_soon(self) -> None:
        """Node's synchronous ``dispose`` from a signal handler: on the services' event loop, the queue stops
        scheduling, the radius search refuses new work and stops its running worker (``server_restart``), and the queue
        is written (a launch still in flight goes back to ``queued``). ``close`` then waits for the worker's records.
        Before the services exist the request is kept, and ``start`` applies it; once the loop is closed it does
        nothing."""
        self._stop_requested = True
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._stop_now)
        except RuntimeError:
            pass  # the loop is closed: the services have stopped

    def _stop_now(self) -> None:
        queue, radius = self.queue, self.radius
        if queue is None:
            return
        queue.stop_scheduling()
        if radius is not None:
            radius.dispose()
        queue.dispose()

    async def close(self) -> None:
        """Node's ``dispose`` of the composed service: the queue stops scheduling, the radius search refuses new work
        and stops its running worker (``server_restart``); once that job's records are written, the queue is written a
        last time (unless ``stop_soon`` wrote it already) and its dispatcher has left. A receipt that was running stays
        ``running`` on disk; the next start fails it with ``服务重启中断了计算，可重新提交`` (or promotes it when its
        result was stored). When that last write failed, ``failure`` says so."""
        queue, radius = self.queue, self.radius
        if queue is None:
            return
        queue.stop_scheduling()
        if radius is not None:
            await radius.aclose()
        await queue.close()
        if queue.unsaved is not None and self.failure is None:
            reason = getattr(queue.unsaved, 'strerror', None) or str(queue.unsaved)
            self.failure = (f'Cannot write the workspace queue {queue.path} at shutdown: {reason}. The next start '
                            'applies its restart rules to the file as it was.')

    def wired(self, kind: str) -> Optional['WorkspaceQueue']:
        """The started queue when it has an adapter for ``kind``, else ``None``."""
        queue = self.queue
        return queue if queue is not None and kind in queue.adapters else None


# --- Answers -------------------------------------------------------------------------------------------------------

def public_failure(error: BaseException) -> tuple[int, str]:
    """Node's ``publicFailure(error)``: the status and message a failed request answers with."""
    message = getattr(error, 'message', None)
    if not isinstance(message, str):
        message = str(error)
    status = getattr(error, 'status', None)
    if isinstance(status, int) and not isinstance(status, bool) and 400 <= status < 600:
        return status, message
    from ...schemas import jsjson

    if isinstance(error, jsjson.JSONSyntaxError):
        return 400, NOT_JSON
    if _refusal(error):
        return 400, message
    LOG.error('job request failed', exc_info=error)
    return 500, INTERNAL_MESSAGE


def _refusal(error: BaseException) -> bool:
    """A request the kind refuses (Node's plain ``Error``), rather than a fault of the service (Node's system and
    programming errors, ``internalFault``)."""
    if isinstance(error, ValueError) and not isinstance(error, UnicodeError):
        return True
    from ...jobs.radius import RadiusJobError

    return isinstance(error, RadiusJobError)


def failure_response(error: BaseException) -> Response:
    status, message = public_failure(error)
    return error_response(status, message)


def task_query(query: bytes) -> Optional[str]:
    """The view's query, parsed as ``URLSearchParams`` parses it: the ``annotation_id`` or ``None``; ``Refusal`` 400
    for another name, a repeated one or a value that is not 64 lowercase hex digits."""
    pairs = parse_qsl(query.decode('latin-1'), keep_blank_values=True)
    names = [name for name, _ in pairs]
    if any(name != ANNOTATION_QUERY for name in names) or names.count(ANNOTATION_QUERY) > 1:
        raise Refusal(UNSUPPORTED_QUERY)
    value = pairs[0][1] if pairs else None
    if value is not None and not ANNOTATION_ID.fullmatch(value):
        raise Refusal(INVALID_ANNOTATION)
    return value


def _unknown(request: Request) -> Response:
    return error_response(404, node_fallback(raw_path(request.scope)) or 'Not Found')


def add_routes(app: FastAPI, config: 'ServiceConfig', compute: ComputeHost) -> None:
    def submit(kind: str, lookup: bool) -> Callable[[Request], Any]:
        async def endpoint(request: Request) -> Response:
            queue = compute.wired(kind)
            if queue is None:
                return error_response(404, UNKNOWN_ENDPOINT)
            raw = await read_json_body(request, BODY_LIMITS[kind])
            try:
                value = await queue.submit(kind, raw, lookup_only=lookup)
            except Exception as error:  # noqa: BLE001 - Node's catch block
                return failure_response(error)
            return json_response(200 if lookup else 202, value)
        return endpoint

    def view(kind: str) -> Callable[[Request], Any]:
        async def endpoint(request: Request) -> Response:
            id = request.path_params['id']
            if not JOB_ID.fullmatch(id):
                return _unknown(request)
            queue = compute.wired(kind)
            if queue is None:
                return error_response(404, UNKNOWN_ENDPOINT)
            try:
                annotation_id = task_query(request.scope.get('query_string', b''))
                job = await queue.view(queue.own(id, kind), True, annotation_id)
            except Exception as error:  # noqa: BLE001 - Node's catch block
                return failure_response(error)
            return json_response(200, {'job': job})
        return endpoint

    def cancel(kind: str) -> Callable[[Request], Any]:
        async def endpoint(request: Request) -> Response:
            id = request.path_params['id']
            if not JOB_ID.fullmatch(id):
                return _unknown(request)
            queue = compute.wired(kind)
            if queue is None:
                return error_response(404, UNKNOWN_ENDPOINT)
            try:
                job = await queue.cancel(id, kind)
            except Exception as error:  # noqa: BLE001 - Node's catch block
                return failure_response(error)
            return json_response(202, {'job': job})
        return endpoint

    # The identifier is read from the path parameters rather than declared as a parameter (routes.library).
    for kind in KINDS:
        name = kind.replace('-', '_')
        app.add_api_route(f'/api/{kind}/lookup', submit(kind, True), methods=['POST'], include_in_schema=False,
                          name=f'lookup_{name}')
        app.add_api_route(f'/api/{kind}/jobs', submit(kind, False), methods=['POST'], include_in_schema=False,
                          name=f'submit_{name}')
        app.add_api_route(f'/api/{kind}/jobs/{{id}}', view(kind), methods=['GET'], include_in_schema=False,
                          name=f'job_{name}')
        app.add_api_route(f'/api/{kind}/jobs/{{id}}/cancel', cancel(kind), methods=['POST'],
                          include_in_schema=False, name=f'cancel_{name}')
