"""The job routes of every task kind and the compute services behind them (phase 2 slices 4 to 7): Node's
``communityMiddleware`` (community-queue.mjs:489-551) for one local user.

- ``POST /api/{kind}/lookup``: 200 with ``WorkspaceQueue.submit(kind, body, lookup_only=True)``: ``{hit: false}``,
  or ``{hit: true, job}`` for a stored result (its cached receipt) or a pending task of the same key. A lookup never
  writes a record or queues a task.
- ``POST /api/{kind}/jobs``: 202 with ``submit(kind, body)``: ``{job}`` for a new queued receipt, or Node's
  ``{hit: true, job}`` for a stored result or a pending task of the same key.
- ``GET /api/{kind}/jobs/<id>[?annotation_id=<64 hex>]``: 200 ``{job}``, the receipt's view with its result.
- ``POST /api/{kind}/jobs/<id>/cancel``: 202 ``{job}``; no body is read.

A coordinate evaluation (``design-evaluation``) may come as a ``design-submission/1`` envelope with 64 electrode
names and source metadata: its request is the evaluated one, and the names become the receipt's electrode-name
annotation (``W/annotations/electrode-names/<id>.json``, created once and referenced by the receipt's
``annotation_refs``), which the answer carries as ``annotation_id`` and ``electrode_annotation``. A lookup miss
creates none. ``?annotation_id=`` selects a variant the receipt references (else 404 ``Electrode name annotation
not found.``).

As in Node, a body must be JSON (415 ``JSON required``) of at most the kind's limit as received (``BODY_LIMITS``,
413 ``配置过大``) and parse with JavaScript's rules (400 ``请求内容不是有效的JSON``); the view takes only one
``annotation_id`` (else 400 ``Unsupported task query.``) of 64 lowercase hex digits (else 400 ``Invalid electrode
name annotation.``); an unknown receipt is 404 ``任务不存在或不属于当前浏览器``. Failures follow Node's
``publicFailure``: a refusal with a status keeps it (``QueueError``: 503 unavailable or cache-only, 429 queue full,
409, 404, 413), a request the kind refuses (a ``ValueError`` of its normalizer or identity, or the radius search's
``RadiusJobError``, which the coordinate evaluation's and the editor's refusals are) is a 400 with its message, and
anything else (a system error, or a ``TypeError`` such as Node's refusal of a path argument) a 500 with the generic
message, logged. The CSRF token of a write is checked before routing (``server.access``).

An electrode-editor request (``electrode-editor``, at most 32,768 bytes) is a ``prepare`` of a library layout or an
``evaluate`` of its 64 stable slots (``schemas.electrode_editor``); a parent the editor refuses is a 400 with Node's
message (``jobs.editor.EditorContextError``: no saved region boundaries, a noise model, a changed parent digest, a
changed report, another region geometry or surface admission). A receipt's view of a stored evaluation prepares its
request again, so once its parent has changed the view answers that refusal, as Node's does. Node's own editor
routes behind these (``ElectrodeEditorService.handle``: ``Editor request too large``, ``Job expired; submit again to
read the saved result``) never answer in its composed service, whose queue routes come first; other paths under
``/api/electrode-editor`` are 404 ``Unknown editor endpoint`` (``app.node_fallback``).

A signal-reception request (``source-reception``, at most 4,096 bytes) is v1 without ``mode`` and v2 with it
(``schemas.source_reception``); a layout the service refuses (not a saved 64-point layout, one searched under
another noise model, the legacy multi-source protocol) and a context that cannot be formed (the forward bank or the
candidates changed, the runtime inspector failed) are a 400 with Node's message. A completed receipt's view reads
its stored result through the identity of today (``模型或代码已更新，请重新提交`` once that changed); its original
download is ``GET /api/community/records/<id>/result`` (``routes.community``). ``GET
/api/source-reception/catalog`` is Node's ``sourceCatalog``: the v2 worker's ``--catalog`` under the native
interpreter, one run shared by the requests that arrive while it runs; a failure is Node's 500 ``计算记录无法读取``
(``computeMiddleware``'s catch). Other paths under ``/api/source-reception`` are 404 ``未知源实验接口``.

``ComputeHost`` holds the services of one process: the radius search (``jobs.radius.RadiusJobs``), the coordinate
evaluation (``jobs.design.DesignJobs``), the electrode editor (``jobs.editor.EditorJobs``, which reads its parents
from the library) and signal reception (``jobs.reception.ReceptionJobs``, which reads its layouts from the library
too), all on the radius search's record store, as Node's ``DesignEvaluationService``, ``ElectrodeEditorService`` and
``SourceReceptionService`` use their queue's; the workspace queue (``jobs.queue.WorkspaceQueue`` in
``W/.eeglayoutlab``) over the four kinds (``jobs.kinds``) with the workspace's electrode-name annotations
(``jobs.annotations.ElectrodeAnnotations.local``: written to ``W/annotations/electrode-names``, read from there, then
from Node's ``R/results/v2/design_evaluation_jobs/electrode_annotations``); and the execution slot the services
share, with the installation lock on ``R/results/v2``, so one worker of any kind runs at a time. The application's
lifespan starts it (the queue's restart rules, ``recover()`` and its dispatcher) and closes it (Node's ``dispose``:
no new dispatch, the running worker stopped with ``server_restart`` or ``restart`` and awaited, the queue written
once more, the runtime inspectors and catalog runs stopped). Every kind of an application whose lifespan never ran
is an unknown endpoint: 404 ``Unknown queue endpoint``, before any body is read (the catalog: ``未知源实验接口``).

The host also holds the workspace's robustness studies (slice 8, ``routes.studies``): a
``workspace_studies.RobustnessStudyService`` over the queue (its cases are coordinate evaluations of the queue's
``design-evaluation`` kind) with its ``StudyStore`` in ``W/studies``, built once the queue has started; its restart
recovery (running studies become ``paused_recovery``) runs as it starts. The store's ``before_write`` is Node's
``admit`` without the resource gate (R2): once the services stop, a study write that is not a cancellation is refused
with 503 ``The service is stopping.``. The services stop in Node's ``dispose`` order: the studies stop first (no new
pump or submission), then the queue's scheduling and the job services; the pumps and study writes still running are
awaited (``RobustnessStudyService.flush``) before the queue is written a last time.

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
    from ...jobs.annotations import ElectrodeAnnotations
    from ...jobs.design import DesignJobs
    from ...jobs.editor import EditorJobs
    from ...jobs.library import Library
    from ...jobs.queue import WorkspaceQueue
    from ...jobs.radius import RadiusJobs
    from ...jobs.reception import ReceptionJobs
    from ...jobs.runtime import RuntimeConfig
    from ...jobs.slot import ExecutionSlot
    from ..app import ServiceConfig
    from ..workspace_studies import RobustnessStudyService

LOG = logging.getLogger('eeglayoutlab.server')

UNKNOWN_ENDPOINT = 'Unknown queue endpoint'
# Node's answer to a failure of computeMiddleware's own routes (the signal catalog among them).
UNREADABLE = '计算记录无法读取'
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


class _Library:
    """The library a factory gives, built on first use: ``get(id)`` for signal reception, which reads its layouts
    through it as Node's ``SourceReceptionService`` reads ``queue.library``."""

    def __init__(self, factory: Callable[[], 'Library']):
        self.factory = factory

    def get(self, id: Any) -> Any:
        return self.factory().get(id)


class ComputeHost:
    """The compute services of one service process, built and started by ``start`` and stopped by ``close``.

    ``runtime`` gives the root and interpreters (the library routes' ``RuntimeConfig``, so both read one
    ``EEG_COMPUTE_PYTHON``). ``library`` gives the ``jobs.library.Library`` the editor and signal reception read their
    layouts from (the library routes' ``library``, as Node's editor, reception and library routes share
    ``queue.library``); a host without it builds one on first use, on the same root, interpreters, annotations and
    radius search. ``radius_options``, ``design_options``, ``editor_options``, ``reception_options`` and
    ``queue_options`` are passed to ``RadiusJobs``, ``DesignJobs``, ``EditorJobs``, ``ReceptionJobs`` and
    ``WorkspaceQueue`` (tests set a timeout, a clock or a bound there before the lifespan starts); ``study_options``
    to ``RobustnessStudyService`` (its poll interval, clock or identifiers), except ``store``, which holds options of
    its ``StudyStore``.
    ``failure`` is the message of a start that failed, or of the queue's last write at shutdown when it failed; the
    command line reports it and exits 1, as Node's host does when its ``dispose`` throws (start.mjs)."""

    def __init__(self, config: 'ServiceConfig', runtime: Optional[Callable[[], 'RuntimeConfig']] = None):
        self.config = config
        self.runtime = runtime
        self.library: Optional[Callable[[], 'Library']] = None
        self.radius_options: dict[str, Any] = {}
        self.design_options: dict[str, Any] = {}
        self.editor_options: dict[str, Any] = {}
        self.reception_options: dict[str, Any] = {}
        self.queue_options: dict[str, Any] = {}
        self.study_options: dict[str, Any] = {}
        self.slot: Optional[ExecutionSlot] = None
        self.radius: Optional[RadiusJobs] = None
        self.design: Optional[DesignJobs] = None
        self.editor: Optional[EditorJobs] = None
        self.reception: Optional[ReceptionJobs] = None
        self.annotations: Optional[ElectrodeAnnotations] = None
        self.queue: Optional[WorkspaceQueue] = None
        self.studies: Optional[RobustnessStudyService] = None
        self.failure: Optional[str] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_requested = False
        self._disposing = False

    @property
    def directory(self) -> str:
        """The queue's directory, ``W/.eeglayoutlab``."""
        return nodepath.join(nodepath.resolve(self.config.user.workspace), STATE)

    @property
    def study_directory(self) -> str:
        """The studies' directory, ``W/studies``."""
        from ..workspace_studies import STUDIES

        return nodepath.join(nodepath.resolve(self.config.user.workspace), STUDIES)

    def _build(self) -> tuple['ExecutionSlot', 'RadiusJobs', 'DesignJobs', 'EditorJobs', 'ReceptionJobs',
                              'ElectrodeAnnotations', 'WorkspaceQueue']:
        from ...jobs.annotations import WORKSPACE_ANNOTATIONS, ElectrodeAnnotations
        from ...jobs.design import DesignJobs
        from ...jobs.editor import EditorJobs
        from ...jobs.kinds import community_adapters
        from ...jobs.library import Library
        from ...jobs.queue import WorkspaceQueue
        from ...jobs.radius import RadiusJobs
        from ...jobs.reception import ReceptionJobs
        from ...jobs.runtime import runtime_config
        from ...jobs.slot import ExecutionSlot, InstallationLock

        runtime = self.runtime() if self.runtime is not None else runtime_config(self.config.root)
        slot = ExecutionSlot(InstallationLock(runtime.repository_root))
        radius = RadiusJobs(runtime.repository_root, runtime.python, execution_slot=slot,
                            token=self.config.tokens.csrf, **self.radius_options)
        # Node's DesignEvaluationService and ElectrodeEditorService: the queue's root, record store and slot, and the
        # native interpreter.
        design = DesignJobs(runtime.repository_root, runtime.native_python, execution_slot=slot, store=radius.store,
                            **self.design_options)
        # The library reads the same two directories (routes.library).
        workspace_annotations = nodepath.join(self.config.user.workspace, *WORKSPACE_ANNOTATIONS)
        # The library routes' library (create_app), else one of its own; either is built when first needed.
        library = self.library if self.library is not None else (
            lambda: Library(runtime.repository_root, runtime, workspace_annotations, radius=radius))
        editor = EditorJobs(runtime.repository_root, runtime.native_python, library, execution_slot=slot,
                            store=radius.store, **self.editor_options)
        # Node's SourceReceptionService: v2 runs under the native interpreter, v1 under the radius search's
        # (queue.python); one runtime-digest memo per service.
        reception = ReceptionJobs(runtime.repository_root, runtime.native_python, _Library(library),
                                  compute_python=runtime.python, execution_slot=slot, store=radius.store,
                                  **self.reception_options)
        annotations = ElectrodeAnnotations.local(workspace_annotations, runtime.repository_root)
        queue = WorkspaceQueue(self.directory, community_adapters(radius, design, editor, reception), slot=slot,
                               annotations=annotations, cache_only=self.config.cache_only,
                               clear_interrupted=self.config.clear_interrupted, **self.queue_options)
        return slot, radius, design, editor, reception, annotations, queue

    async def start(self) -> None:
        """Builds the services (``queue.json`` is loaded or created and the restart rules applied, in a worker
        thread), then starts the queue: ``recover()`` and its dispatcher, and then the study service, whose restart
        recovery runs in the background (a failed one refuses the study requests, not the start). A stop requested
        before the services exist (``stop_soon``) stops them as soon as they are built, so nothing is recovered or
        dispatched. Raises ``QueueStateError`` for a queue file that cannot be used, which stays as it was;
        ``failure`` then holds the message."""
        from ...jobs.queue import QueueStateError

        if self.queue is not None:
            return
        self._loop = asyncio.get_running_loop()
        try:
            (self.slot, self.radius, self.design, self.editor, self.reception, self.annotations,
             self.queue) = await asyncio.to_thread(self._build)
            if self._stop_requested:
                self._stop_now()
                return
            await self.queue.start()
            self.studies = self._study_service(self.queue, self.design.root)
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

    def _study_service(self, queue: 'WorkspaceQueue', root: str) -> 'RobustnessStudyService':
        """Node's ``RobustnessStudyService({queue, scheduler, beforeWrite: admit})`` for the workspace, on the running
        loop (its recovery and poll start at once)."""
        from ..workspace_studies import RobustnessStudyService, StudyStore

        options = dict(self.study_options)
        store = StudyStore(self.study_directory, before_write=self._admit, **options.pop('store', {}))
        return RobustnessStudyService(queue, root, store=store, **options)

    def _admit(self) -> None:
        """Node's ``admit`` (local-compute-server.mjs:445-449) without the resource gate (R2): a study write that
        is not a cancellation is refused once the services stop."""
        if self._disposing:
            from ..workspace_studies import ResourceError

            raise ResourceError('The service is stopping.', 503)

    def stop_soon(self) -> None:
        """Node's synchronous ``dispose`` from a signal handler: on the services' event loop, the studies stop, the
        queue stops scheduling, the services refuse new work and stop their running worker (the radius search's with
        ``server_restart``, the other kinds' with ``restart``), and the queue is written (a launch still in flight goes
        back to ``queued``), unless a study is still pumped or written: as Node defers ``scheduler.dispose()``,
        ``close`` then writes it after them. ``close`` then waits for the worker's records.
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

    def _services(self) -> list[Any]:
        # createLocalComputeService's dispose order: signal reception, the coordinate evaluation, the editor, then the
        # radius search.
        return [service for service in (self.reception, self.design, self.editor, self.radius) if service is not None]

    def _stop_now(self) -> None:
        queue = self.queue
        if queue is None:
            return
        # Node's dispose: the studies stop before the scheduler (no new pump, submission or study write).
        self._disposing = True
        studies = self.studies
        if studies is not None:
            studies.stop()
        queue.stop_scheduling()
        for service in self._services():
            service.dispose()
        # The scheduler is written last: while a study is pumped or written, close() writes it once they are done.
        if studies is None or not (studies.inflight or studies.store.pending_writes):
            queue.dispose()

    async def close(self) -> None:
        """Node's ``dispose`` of the composed service: the studies stop, the queue stops scheduling, the services
        refuse new work and stop their running worker; once the studies' pumps and writes have finished (the store
        is then closed) and that job's records are written, the queue is written a last time (unless ``stop_soon``
        wrote it already) and its dispatcher has left. A receipt that was running stays ``running`` on disk; the next
        start fails it with ``服务重启中断了计算，可重新提交`` (or promotes it when its result was stored), and a
        running study becomes ``paused_recovery``. When the queue's last write failed, ``failure`` says so."""
        queue = self.queue
        if queue is None:
            return
        self._disposing = True
        studies = self.studies
        if studies is not None:
            studies.stop()
        queue.stop_scheduling()
        services = self._services()
        # Every service refuses new work before any is awaited, as Node disposes them one after another.
        for service in services:
            service.dispose()
        if studies is not None:
            # Node's studies.flush() and studies.close() before scheduler.dispose(); a failed recovery is logged.
            await studies.aclose()
        for service in services:
            await service.aclose()
        await queue.close()
        if queue.unsaved is not None and self.failure is None:
            reason = getattr(queue.unsaved, 'strerror', None) or str(queue.unsaved)
            self.failure = (f'Cannot write the workspace queue {queue.path} at shutdown: {reason}. The next start '
                            'applies its restart rules to the file as it was.')

    async def catalog(self) -> Any:
        """``sourceCatalog``: the 256 frozen generation sources of signal reception (``ReceptionJobs.catalog``)."""
        assert self.reception is not None
        return await self.reception.catalog()

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

    # The coordinate evaluation's plain Errors (jobs.design.DesignJobError) are RadiusJobErrors.
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


async def json_answer(status: int, value: Any) -> Response:
    """``json_response`` written in a worker thread: a signal result is about 1 to 8 MB of JSON, whose text the
    port of ``JSON.stringify`` takes a second or more to write, so health and polling keep answering meanwhile."""
    return await asyncio.to_thread(json_response, status, value)


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
            return await json_answer(200 if lookup else 202, value)
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
            return await json_answer(200, {'job': job})
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
            return await json_answer(202, {'job': job})  # a finished receipt's view carries its result
        return endpoint

    async def catalog(request: Request) -> Response:
        if compute.reception is None:
            return _unknown(request)
        try:
            value = await compute.catalog()
        except Exception:  # noqa: BLE001 - computeMiddleware's catch block
            LOG.exception('the signal catalog failed')
            return error_response(500, UNREADABLE)
        return json_response(200, value)

    app.add_api_route('/api/source-reception/catalog', catalog, methods=['GET'], include_in_schema=False,
                      name='reception_catalog')
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
