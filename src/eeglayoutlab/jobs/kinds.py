"""Job kinds of the workspace queue: Node's ``community-adapters.mjs`` (lines 4-24) for ``jobs.queue``.

An adapter connects the queue to one per-kind job service. It has Node's seven members plus the Python completion
hook:

- ``await prepare(raw)``: the canonical request and its identity, ``{'request', 'key', 'ctx'[, extra members]}``.
  Normalizer errors propagate with their own message (a 400 in the routes); nothing is written.
- ``await lookup(prepared)``: ``{'hit': False}`` or ``{'hit': True, 'job': view}`` from the stored result. It never
  takes the execution slot and never starts a worker.
- ``await start(prepared)``: the service's submit. ``{'job': view}`` (running, or already done when the service
  found a stored result), or ``{'busy': True, ...}`` when it confirms that nothing was launched (the slot is held or
  paused). Anything else it raises leaves the launch outcome unknown.
- ``get(id)``: the service's view of its job ``id``, or ``None`` once it has forgotten it.
- ``busy()``: the service has an active job or a submit in progress.
- ``pid()``: the process-group leader of the active worker, or ``None``.
- ``cancel(id)``: stop that job (SIGTERM to its group); its receipt stays ``cancelling`` until the job finishes.
- ``on_finish(callback)``: register ``callback(id, view)``, which the service calls once a job is terminal and
  durable (its records written, its active slot cleared and the permit released). The queue finalizes receipts
  from it, never from a poll of the service's bounded job map (jobs.md section 5.6, pitfall).
- ``await finished_at(prepared, job)`` (optional): the finish time of the stored result a lookup ``job`` came from,
  once the record passes the checks of Node's reconciliation (the coordinate evaluation, the electrode editor and
  signal reception: Node's reconciliation reads it from ``cache.json``). The queue's startup ``recover()`` uses it in
  place of the view's ``finished_at``.
- ``await saved_result(key, request)`` (signal reception only): the stored result of a completed receipt for its
  original download, checked against the protocol it was saved under, without preparing the identity again
  (Node's ``savedResult``; ``GET /api/community/records/<id>/result``).

``ServiceAdapter`` is Node's ``adapter(service, normalize, context)``. It expects Node's service surface in
snake_case: ``lookup(request, ctx)``, ``submit(prepared)``, ``jobs`` (id -> job), ``view(job)``, ``active``,
``submitting``, ``cancel(id)`` and ``finish_callbacks`` (a list of ``callback(job)``, called with the service's own
job once it is terminal and durable). ``context`` and ``lookup`` may be coroutine functions; synchronous ones run in
a worker thread, one identity computation at a time across all kinds (as Node's ``serial()``), so the event loop
keeps answering health and polling. ``local_compute_adapter`` builds the radius search's adapter
(``normalize_request`` and ``identity_for``), ``design_evaluation_adapter`` the coordinate evaluation's
(``DesignAdapter``: the service's own ``normalize`` and ``context``, after the ``design-submission/1`` envelope) and
``electrode_editor_adapter`` the electrode editor's (``StoredResultAdapter`` over ``jobs.editor.EditorJobs``: its
``normalize`` and ``context``, which Node's adapter calls as they are) and ``source_reception_adapter`` signal
reception's (``ReceptionAdapter`` over ``jobs.reception.ReceptionJobs``: Node's ``normalizeReceptionRequest``, which
is the service's ``normalize``, its ``context`` and its ``savedResult``).
"""
from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any, Awaitable, Callable, Optional, Protocol, Union

from .identity import UNDEFINED, js_truthy

__all__ = ['KINDS', 'Adapter', 'ServiceAdapter', 'StoredResultAdapter', 'DesignAdapter', 'ReceptionAdapter',
           'local_compute_adapter', 'design_evaluation_adapter', 'electrode_editor_adapter', 'source_reception_adapter',
           'community_adapters', 'call', 'resolve']

# The kinds the routes accept (community-queue.mjs:494); slice 4 wired 'local-compute', slice 5 'design-evaluation',
# slice 6 'electrode-editor' and slice 7 'source-reception'.
KINDS = ('local-compute', 'source-reception', 'design-evaluation', 'electrode-editor')

FinishCallback = Callable[[str, dict], None]

# Identity work hashes input files and parses records: one computation at a time, off the event loop.
_IDENTITY = threading.Lock()


class Adapter(Protocol):
    """What ``jobs.queue.WorkspaceQueue`` calls for one kind (see the module docstring)."""

    async def prepare(self, raw: Any) -> dict: ...
    async def lookup(self, prepared: dict) -> dict: ...
    async def start(self, prepared: dict) -> dict: ...
    def get(self, id: str) -> Optional[dict]: ...
    def busy(self) -> bool: ...
    def pid(self) -> Optional[int]: ...
    def cancel(self, id: str) -> Any: ...
    def on_finish(self, callback: FinishCallback) -> None: ...


async def resolve(value: Union[Any, Awaitable[Any]]) -> Any:
    """``await`` for a value that may or may not be awaitable (JavaScript's ``await`` of a plain value)."""
    if inspect.isawaitable(value):
        return await value
    return value


async def call(function: Callable[..., Any], *args: Any) -> Any:
    """Calls ``function``: a coroutine function on the loop, any other in a worker thread under the identity lock."""
    if inspect.iscoroutinefunction(function):
        return await function(*args)

    def work() -> Any:
        with _IDENTITY:
            return function(*args)
    return await resolve(await asyncio.to_thread(work))


def _context(value: Any) -> dict:
    """Node's ``ctx`` (``{identity, key}`` for the radius search); ``identity_for`` may return the pair."""
    if isinstance(value, tuple) and len(value) == 2:
        identity, key = value
        return {'identity': identity, 'key': key}
    if not isinstance(value, dict) or 'key' not in value:
        raise TypeError('A job context must have a key.')
    return value


def _member(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _pid(job: Any) -> Optional[int]:
    """``service.active?.child?.pid``: the worker (``jobs.worker.Worker``) or child of the active job."""
    for name in ('worker', 'child'):
        holder = _member(job, name)
        pid = _member(holder, 'pid') if holder is not None else None
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
            return pid
    return None


class ServiceAdapter:
    """``adapter(service, normalize, context)`` of community-adapters.mjs:5-13, plus ``on_finish``."""

    def __init__(self, service: Any, normalize: Callable[[Any], Any], context: Callable[[Any], Any]):
        self.service = service
        self.normalize = normalize
        self.context = context

    async def prepare(self, raw: Any) -> dict:
        request = self.normalize(raw)
        ctx = _context(await call(self.context, request))
        return {'request': request, 'key': ctx['key'], 'ctx': ctx}

    async def lookup(self, prepared: dict) -> dict:
        return await call(self.service.lookup, prepared['request'], prepared.get('ctx'))

    async def start(self, prepared: dict) -> dict:
        return await resolve(self.service.submit(prepared))

    def get(self, id: Any) -> Optional[dict]:
        job = self.service.jobs.get(id)
        return self.service.view(job) if job is not None else None

    def busy(self) -> bool:
        return bool(self.service.active or self.service.submitting)

    def pid(self) -> Optional[int]:
        active_pid = getattr(self.service, 'active_pid', None)
        if callable(active_pid):
            return active_pid()
        active = self.service.active
        return _pid(active) if active is not None else None

    def cancel(self, id: Any) -> Any:
        return self.service.cancel(id)

    def on_finish(self, callback: FinishCallback) -> None:
        def finished(job: Any) -> None:
            view = self.service.view(job)
            callback(view['id'], view)
        self.service.finish_callbacks.append(finished)


class StoredResultAdapter(ServiceAdapter):
    """``adapter(service, normalize, context)`` for a service with a ``stored_finish`` (the coordinate evaluation and
    the electrode editor, built on ``jobs.design.DesignJobs``, and signal reception): ``finished_at`` gives the stored
    record's finish time once the record passes the checks of Node's reconciliation
    (scripts/inspect_service_reconciliation.mjs, which reads it from ``cache.json`` for these kinds); the design
    lookup's views have none."""

    async def finished_at(self, prepared: dict, job: dict) -> Any:
        """The stored record's ``finished_at`` (the service's ``stored_finish``: the record checks of Node's
        reconciliation, then the time), or ``None``."""
        identity = prepared['ctx'].get('identity', UNDEFINED)
        return await self.service.stored_finish(prepared['key'], prepared['request'], identity,
                                                job.get('result', UNDEFINED))


class DesignAdapter(StoredResultAdapter):
    """The coordinate evaluation's adapter (community-adapters.mjs:18-21): ``prepare`` unwraps a
    ``design-submission/1`` envelope (``jobs.annotations.design_submission``: its checks and messages come first),
    normalizes the request with the service's ``normalize`` and computes its ``context``. The electrode names and
    the source metadata an envelope carries are kept beside the request, as ``electrode_names`` and
    ``source_metadata`` when present, never in it: they enter neither the key nor the worker's input, only the
    queue's annotation of the receipt. A bare request (the stored request at dispatch and in views among them)
    prepares as with the plain adapter."""

    async def prepare(self, raw: Any) -> dict:
        from .annotations import design_submission

        submitted = design_submission(raw)
        request = self.normalize(submitted['request'])
        ctx = _context(await call(self.context, request))
        prepared = {'request': request, 'key': ctx['key'], 'ctx': ctx}
        # Node spreads each member only when it is truthy.
        for name in ('electrode_names', 'source_metadata'):
            if js_truthy(submitted.get(name, UNDEFINED)):
                prepared[name] = submitted[name]
        return prepared


class ReceptionAdapter(StoredResultAdapter):
    """Signal reception's adapter (community-adapters.mjs:15-16): the plain adapter with the stored finish time, and
    Node's ``savedResult``."""

    async def saved_result(self, key: Any, request: Any) -> Any:
        """``savedResult(key, request)``: the service's ``saved_result``; the identity is not prepared again."""
        return await self.service.saved_result(key, request)


def local_compute_adapter(service: Any) -> ServiceAdapter:
    """The radius search (``'local-compute'``): ``normalize_request`` and the service's ``identity_for``."""
    # Imported here: the radius-search format needs Pydantic, which the native runtime does not have.
    from ..schemas.radius_search import normalize_request
    return ServiceAdapter(service, normalize_request, service.identity_for)


def design_evaluation_adapter(service: Any) -> DesignAdapter:
    """The coordinate evaluation (``'design-evaluation'``, ``jobs.design.DesignJobs``): the service's ``normalize``
    and ``context``, which a subclass of the service may override."""
    return DesignAdapter(service, service.normalize, service.context)


def electrode_editor_adapter(service: Any) -> StoredResultAdapter:
    """The electrode editor (``'electrode-editor'``, ``jobs.editor.EditorJobs``): the plain adapter over the service's
    ``normalize`` and ``context`` (community-adapters.mjs:22), with the stored finish time of the coordinate
    evaluation's, whose lookup the editor's is."""
    return StoredResultAdapter(service, service.normalize, service.context)


def source_reception_adapter(service: Any) -> ReceptionAdapter:
    """Signal reception (``'source-reception'``, ``jobs.reception.ReceptionJobs``): the service's ``normalize``
    (``normalizeReceptionRequest``: v1 without ``mode``, v2 with it) and ``context``, the stored finish time and the
    saved result."""
    return ReceptionAdapter(service, service.normalize, service.context)


def community_adapters(radius: Any, design: Any = None, editor: Any = None,
                       reception: Any = None) -> dict[str, Adapter]:
    """``communityAdapters(queue, normalizeRequest)``: the radius search and, when given, the coordinate evaluation,
    the electrode editor and signal reception, in Node's order."""
    adapters: dict[str, Adapter] = {'local-compute': local_compute_adapter(radius)}
    if reception is not None:
        adapters['source-reception'] = source_reception_adapter(reception)
    if design is not None:
        adapters['design-evaluation'] = design_evaluation_adapter(design)
    if editor is not None:
        adapters['electrode-editor'] = electrode_editor_adapter(editor)
    return adapters
