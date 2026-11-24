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

``ServiceAdapter`` is Node's ``adapter(service, normalize, context)``. It expects Node's service surface in
snake_case: ``lookup(request, ctx)``, ``submit(prepared)``, ``jobs`` (id -> job), ``view(job)``, ``active``,
``submitting``, ``cancel(id)`` and ``finish_callbacks`` (a list of ``callback(job)``, called with the service's own
job once it is terminal and durable). ``context`` and ``lookup`` may be coroutine functions; synchronous ones run in
a worker thread, one identity computation at a time across all kinds (as Node's ``serial()``), so the event loop
keeps answering health and polling. ``local_compute_adapter`` builds the radius search's adapter
(``normalize_request`` and ``identity_for``).
"""
from __future__ import annotations

import asyncio
import inspect
import threading
from typing import Any, Awaitable, Callable, Optional, Protocol, Union

__all__ = ['KINDS', 'Adapter', 'ServiceAdapter', 'local_compute_adapter', 'community_adapters', 'call', 'resolve']

# The kinds the routes accept (community-queue.mjs:494); slice 4 wires 'local-compute', slices 5 to 7 the others.
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


def local_compute_adapter(service: Any) -> ServiceAdapter:
    """The radius search (``'local-compute'``): ``normalize_request`` and the service's ``identity_for``."""
    # Imported here: the radius-search format needs Pydantic, which the native runtime does not have.
    from ..schemas.radius_search import normalize_request
    return ServiceAdapter(service, normalize_request, service.identity_for)


def community_adapters(radius: Any) -> dict[str, Adapter]:
    """``communityAdapters(queue, normalizeRequest)`` for the kinds this slice wires."""
    return {'local-compute': local_compute_adapter(radius)}
