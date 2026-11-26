"""The coordinate evaluation's run path: Node's ``DesignEvaluationService`` (``design-evaluation-server.mjs:256-472``),
statement by statement.

``DesignJobs`` is the base class of the native workflows that evaluate one request per worker run (Node's
``ElectrodeEditorService`` extends ``DesignEvaluationService`` the same way, slice 6). Its overridable members are
Node's: ``normalize(raw)``, ``validate(result, request, admission)``, ``worker_input(job)``, ``await context(request)``
and ``view(job)``, with the class attributes ``record_kind`` (``'design'``: ``R/results/v2/design_evaluation_jobs``)
and ``script_name`` (``scripts/design_evaluation.py``). An override keeps the signature: ``validate`` takes
``admission`` even where it ignores it (JavaScript drops the extra argument, Python does not), and ``context``
returns a dict with ``key`` and ``identity`` (``super().context`` first, as the editor's does).
``heads()`` is ``jobs.design_heads`` (slice 3) and
``handle()`` is HTTP (the routes). The request format is the phase 1 schema (``design_result.normalize_design_request``)
and the identity slice 1's scientific context (``identity.design_context``); the request's key enters
``R/results/v2/design_evaluation_jobs/<key>/`` with ``<uuid>/request.json`` (``{request, identity}``, before the
spawn), ``<uuid>/job.json`` (the view with ``stderr``, at the end) and, for a completed result, ``cache.json``
(``{key, identity, result, result_sha256, finished_at}``), whose bytes enter the reception v2 keys (B14).
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
import os
import time
from typing import Any, Awaitable, Callable, Optional
import uuid

from ..schemas import jsjson
from . import nodepath
from .design_result import normalize_design_request, same, validate_design_result
from .identity import UNDEFINED, _js_string, _same, design_context, js_truthy, to_number
from .integrity import InputIntegrity
from .radius import RadiusJobError, iso_time
from .records import RecordStore, error_code, node_message
from .runtime import installed_environment
from .slot import ExecutionSlot, InstallationLock
from .worker import WorkerError, start_worker

__all__ = ['DesignJobs', 'DesignJob', 'DesignJobError', 'WORKER_SCRIPT', 'WORKER_ENV', 'TIMEOUT_MS',
           'MAX_OUTPUT_BYTES', 'JOB_LIMIT', 'RUNNING']

WORKER_SCRIPT = 'scripts/design_evaluation.py'
# The worker's threads: one, as the identity says (``threads: 1``), added to the service's own environment.
WORKER_ENV = {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
              'VECLIB_MAXIMUM_THREADS': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
TIMEOUT_MS = 600000
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
JOB_LIMIT = 20
RUNNING = ('running', 'cancelling')
_UNREADABLE = ('EACCES', 'EPERM')
_log = logging.getLogger(__name__)


class DesignJobError(RadiusJobError):
    """A refusal Node throws as a plain ``Error`` (``计算服务正在重启``, ``计算期间输入或代码发生变化``); the message
    is Node's, verbatim. A ``RadiusJobError``, so the routes treat both run paths' refusals alike."""


def _now_ms() -> int:
    """``Date.now()``."""
    return time.time_ns() // 1_000_000


def _get(value: Any, key: str) -> Any:
    """``value.key`` of a context or record: ``UNDEFINED`` when absent (Node's object members)."""
    if isinstance(value, Mapping):
        return value.get(key, UNDEFINED)
    return getattr(value, key, UNDEFINED)


def _defined(*members: tuple[str, Any]) -> dict:
    """An object literal as ``JSON.stringify`` writes it: members whose value is ``undefined`` are left out."""
    return {key: value for key, value in members if value is not UNDEFINED}


def _context(value: Any) -> Any:
    """A context as Node's object: ``identity.DesignContext`` (a named tuple) becomes ``{identity, admission, key}``."""
    if isinstance(value, tuple) and hasattr(value, '_asdict'):
        return dict(value._asdict())
    return value


def _unreadable(error: BaseException) -> bool:
    """``['EACCES', 'EPERM'].includes(e.code)``: a record that cannot be read is not a miss."""
    return error_code(error) in _UNREADABLE


class DesignJob:
    """One job of ``DesignEvaluationService``: Node's plain object ``j``, with its members as attributes.

    A cached job from ``submit`` has the seven ``view`` members only (``request`` and ``ctx`` are ``None``, absent in
    Node); one from ``lookup`` also has ``request`` and ``ctx``; a computed job has them all. ``terminal`` (the
    worker's last ``result`` event) is ``UNDEFINED`` until one comes; ``worker_error`` is ``None`` until an error
    event or a transport error. ``done`` (Python) resolves once ``finish`` has written the records and released the
    permit."""

    def __init__(self, id: str, key: Any, status: str, progress: Any, message: Any, result: Any = None, *,
                 cached: Any = None, request: Any = None, ctx: Any = None):
        self.id = id
        self.key = key
        self.request = request
        self.ctx = ctx
        self.status = status
        self.progress = progress
        self.message = message
        self.result = result
        self.cached = cached
        # A computed job's members (submit and run).
        self.release_execution: Optional[Callable[[], None]] = None
        self.batch: Optional[str] = None
        self.directory: Optional[str] = None
        self.stderr = ''
        self.terminal: Any = UNDEFINED
        self.worker_error: Optional[str] = None
        self.cancel_reason: Optional[str] = None
        self.worker: Any = None
        self.child: Any = None
        # Python: a stop asked for while the worker was being spawned (Node spawns synchronously).
        self.pending_stop: Optional[str] = None
        self.done: Optional[asyncio.Future] = None

    @property
    def pid(self) -> Optional[int]:
        """``j.child?.pid``."""
        return self.worker.pid if self.worker is not None else None


class DesignJobs:
    """Node's ``DesignEvaluationService`` on one root: lookups of saved evaluations and one worker run at a time.

    ``root`` is the configured root (``RuntimeConfig.repository_root``, Node's ``queue.root``) and ``python`` the
    native interpreter (``RuntimeConfig.native_python``, Node's ``this.python``), which runs the worker and enters
    the identity. The members follow Node's in snake case: ``await context(request)``, ``view(job)``,
    ``remember(job)``, ``normalize(raw)``, ``validate(result, request, admission)``, ``worker_input(job)``, ``await
    lookup(raw, context)``, ``await submit(raw)``, ``run(job)``, ``close(job, code)``, ``finish(job, status,
    message)``, ``cancel(id, reason)`` and ``dispose()``, with the state the queue's adapter reads (``jobs``, an
    insertion-ordered map of at most 20 jobs that never drops the active one, ``active``, ``submitting`` and
    ``active_pid()``). ``context_override`` is Node's ``contextOverride`` (the ``context`` option): a function of the
    request, plain or a coroutine function, whose value replaces the scientific context.

    The worker is ``python -u R/<script_name>`` with ``worker_input(job)`` (the canonical request) as
    ``JSON.stringify`` on stdin, ``cwd`` R, the shell off, the service's environment plus ``WORKER_ENV`` (one
    thread), a 600 s timeout and 4 MiB of output. Its close decides: a stop (``timeout``; ``failed`` after an input
    error; else ``cancelled``), a non-zero exit (``failed`` with the worker's error), then ``validate`` of the last
    result and the context computed again, whose key must still be the job's (``计算期间输入或代码发生变化``), and only
    then ``completed``. Messages, statuses and record bytes are Node's, and the permit of ``execution_slot`` is held
    from before the batch is created until the records are written.

    Differences from Node, all deliberate:

    - ``cache.json`` is published once (``RecordStore.publish_cache``, B16): a valid one already there (Node's lookup
      checks: its key, checksum and ``validate`` of its result for the job's request) stays, and the job completes
      with its own result in ``job.json``; Node replaces it.
    - The slot defaults to one with the installation lock (``R/results/v2/.eeglayoutlab-execution.lock``).
    - Node spawns synchronously; here ``run`` returns the task that spawns the worker, so a ``cancel`` meanwhile is
      applied as soon as it exists (the job is ``cancelling`` at once, as in Node), and ``submit`` awaits that task
      shielded: a cancelled caller never strands an active job.
    - ``finish`` does Node's synchronous part at once and returns the task that writes the records; ``close`` does
      its synchronous part (the stop, the exit status, ``validate``) in the worker's close callback and returns the
      task that computes the context again. Records are read and written in worker threads, and the scientific
      context is computed in a worker thread under the identity lock of ``jobs.kinds`` (one identity at a time).
    - ``finish_callbacks``: each ``callback(job)`` is called once the job is terminal, its records are written,
      ``active`` is cleared and the permit released. The queue finalizes from it.
    - ``submit`` also takes the queue's prepared ``{request, key, ctx, ...}``, whose request it normalizes again and
      whose context it computes again, as Node's adapter passes the request.
    - ``clock`` (``Date.now()`` in milliseconds), ``random_uuid`` and ``spawn`` (``jobs.worker``'s hook) replace the
      time, the job identifiers and the process for tests, as Node's ``spawnProcess`` does.
    """

    record_kind = 'design'
    script_name = WORKER_SCRIPT

    def __init__(self, root: str, python: str, *, spawn: Optional[Callable] = None, timeout_ms: float = TIMEOUT_MS,
                 context: Optional[Callable[[Any], Any]] = None, store: Optional[RecordStore] = None,
                 execution_slot: Optional[ExecutionSlot] = None, inputs: Optional[InputIntegrity] = None,
                 clock: Optional[Callable[[], float]] = None, random_uuid: Optional[Callable[[], str]] = None):
        self.root = nodepath.resolve(root)
        self.store = store if store is not None else RecordStore(self.root)
        self.execution_slot = execution_slot if execution_slot is not None else ExecutionSlot(
            InstallationLock(self.root))
        self.spawn = spawn
        self.timeout_ms = timeout_ms
        self.context_override = context
        self.inputs = inputs if inputs is not None else InputIntegrity(self.root, installed_environment(self.root))
        self.jobs: dict[str, DesignJob] = {}
        self.active: Optional[DesignJob] = None
        self.submitting = False
        self.disposed = False
        self.python = python
        self.clock = clock or _now_ms
        self.random_uuid = random_uuid or (lambda: str(uuid.uuid4()))
        self.finish_callbacks: list[Callable[[DesignJob], Any]] = []
        self._tasks: set[asyncio.Future] = set()

    # --- Node's overridable members -------------------------------------------------------------------------------

    async def context(self, request: Any) -> Any:
        """``await context(request)``: ``{identity, admission, key}`` of the scientific context (slice 1), computed
        in a worker thread, or what ``context_override`` returns."""
        if self.context_override is not None:
            value = self.context_override(request)
            if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
                value = await value
            return _context(value)
        from .kinds import call  # here: jobs.kinds builds the adapters of this module
        return await call(self._scientific_context, request)

    def _scientific_context(self, request: Any) -> dict:
        context = design_context(self.root, self.python, self.inputs, request)
        return {'identity': context.identity, 'admission': context.admission, 'key': context.key}

    def view(self, job: DesignJob) -> dict:
        """``view(j)``."""
        result = job.result
        return _defined(('id', job.id), ('key', job.key), ('status', job.status), ('message', job.message),
                        ('progress', job.progress),
                        ('result', None if result is None or result is UNDEFINED else result),
                        ('cached', js_truthy(job.cached)))

    def remember(self, job: DesignJob) -> None:
        """``remember(j)``: keeps at most 20 jobs, dropping the oldest that is not the active one."""
        self.jobs[job.id] = job
        while len(self.jobs) > JOB_LIMIT:
            active = self.active.id if self.active is not None else UNDEFINED
            oldest = next((id for id in self.jobs if id != active), None)
            if oldest is None:
                break
            del self.jobs[oldest]

    def normalize(self, raw: Any) -> dict:
        """``normalizeDesignRequest(raw)``: raises ``DesignResultError`` with Node's message."""
        return normalize_design_request(raw)

    def validate(self, result: Any, request: Any, admission: Any = UNDEFINED) -> None:
        """``validateDesignResult(result, request, admission)``."""
        validate_design_result(result, request, admission)

    def worker_input(self, job: DesignJob) -> Any:
        """``workerInput(j)``: what the worker reads on stdin."""
        return job.request

    # --- Lookups and submits --------------------------------------------------------------------------------------

    def active_pid(self) -> Optional[int]:
        """``active?.child?.pid``: the process-group leader of the running worker."""
        return self.active.pid if self.active is not None else None

    def _date(self) -> str:
        """``new Date().toISOString()``."""
        return iso_time(self.clock())

    def _track(self, awaitable: Awaitable[Any]) -> asyncio.Future:
        task = asyncio.ensure_future(awaitable)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _current(self, cache: Any, key: Any) -> bool:
        """``cache.key === key && hash(cache.result) === cache.result_sha256``. A member of ``null`` throws (a miss
        in the callers' catch); a missing result cannot be hashed, where Node throws: a miss as well."""
        if not _same(_get_member(cache, 'key'), key):
            return False
        result = _get_member(cache, 'result')
        return result is not UNDEFINED and _same(jsjson.sha256_hex(result), _get_member(cache, 'result_sha256'))

    def _read(self, key: Any) -> Any:
        return self.store.read(nodepath.join(self.store.path(self.record_kind, key), 'cache.json'))

    async def lookup(self, raw: Any, context: Any = None) -> dict:
        """``await lookup(raw, context)``: ``{'hit': False}``, or ``{'hit': True, 'job': view}`` of a new cached job
        (not remembered) when ``cache.json`` of the key is current and ``validate`` accepts its result. Never takes
        the permit. Raises the normalizer's ``ValueError``, a context failure, and ``EACCES`` or ``EPERM`` reading
        the record."""
        request = self.normalize(raw)
        ctx = context if context is not None and context is not UNDEFINED else await self.context(request)
        directory = self.store.path(self.record_kind, _get(ctx, 'key'))
        try:
            cache = await asyncio.to_thread(self.store.read, nodepath.join(directory, 'cache.json'))
            if not self._current(cache, _get(ctx, 'key')):
                return {'hit': False}
            self.validate(cache['result'], request, _get(ctx, 'admission'))
            return {'hit': True, 'job': self.view(DesignJob(self.random_uuid(), _get(ctx, 'key'), 'completed', 1,
                                                            '设计评价已完成', cache['result'], cached=True,
                                                            request=request, ctx=ctx))}
        except Exception as error:  # noqa: BLE001 - Node's catch
            if _unreadable(error):
                raise
            return {'hit': False}

    async def submit(self, raw: Any) -> dict:
        """``await submit(raw)``: ``{'job': view}`` (a hit, the running job of this key, or the new job, spawned),
        ``{'busy': True, 'error': '正在处理另一项设计评价请求'}`` while another submit is in progress, or ``{'busy': True,
        'maintenance': paused}`` when the permit is held (another key runs, or another workspace of this
        installation computes: ``execution_slot.contended``) or paused. Raises ``DesignJobError('计算服务正在重启')``
        after ``dispose``, the normalizer's ``ValueError``, a context failure, a failed record write, or what the
        installation lock raises."""
        if self.disposed:
            raise DesignJobError('计算服务正在重启')
        if isinstance(raw, Mapping) and {'request', 'key', 'ctx'} <= raw.keys():
            raw = raw['request']
        request = self.normalize(raw)
        if self.submitting:
            return {'busy': True, 'error': '正在处理另一项设计评价请求'}
        self.submitting = True
        release: Optional[Callable[[], None]] = None
        job: Optional[DesignJob] = None
        try:
            ctx = await self.context(request)
            if self.disposed:
                raise DesignJobError('计算服务正在重启')
            key = _get(ctx, 'key')
            directory = self.store.path(self.record_kind, key)
            try:
                cache = await asyncio.to_thread(self.store.read, nodepath.join(directory, 'cache.json'))
                if self._current(cache, key):
                    self.validate(cache['result'], request, _get(ctx, 'admission'))
                    hit = DesignJob(self.random_uuid(), key, 'completed', 1, '设计评价已完成', cache['result'],
                                    cached=True)
                    self.remember(hit)
                    return {'job': self.view(hit)}
            except Exception as error:  # noqa: BLE001 - Node's catch: anything else computes again
                if _unreadable(error):
                    raise
            if self.disposed:
                raise DesignJobError('计算服务正在重启')
            if self.active is not None and _same(self.active.key, key):
                return {'job': self.view(self.active)}
            release = self.execution_slot.acquire(self)
            if release is None:
                return {'busy': True, 'maintenance': self.execution_slot.paused}
            id = self.random_uuid()
            batch = await asyncio.to_thread(self.store.create_batch, self.record_kind, key, id)
            await asyncio.to_thread(self.store.write, nodepath.join(batch, 'request.json'),
                                    _defined(('request', request), ('identity', _get(ctx, 'identity'))))
            if self.disposed:
                raise DesignJobError('计算服务正在重启')
            if self.execution_slot.paused:
                return {'busy': True, 'maintenance': True}
            job = DesignJob(id, key, 'running', 0, '准备本地坐标评价', None, request=request, ctx=ctx)
            job.release_execution, job.batch, job.directory = release, batch, directory
            job.done = asyncio.get_running_loop().create_future()
            self.active = job
            release = None
            self.remember(job)
        finally:
            if release is not None:
                release()
            self.submitting = False
        # The spawn goes on if the caller is cancelled meanwhile: the job is active and holds the permit, so it must
        # reach its close.
        await asyncio.shield(self.run(job))
        return {'job': self.view(job)}

    async def stored_finish(self, key: Any, request: Any, identity: Any, result: Any) -> Any:
        """Python's startup ``recover()``: the ``finished_at`` of the ``cache.json`` of ``key`` when it passes the
        record checks of Node's ``inspectReceipt`` (scripts/inspect_service_reconciliation.mjs:44-49): its key and
        checksum are current (the lookup's checks), it holds ``result``, and the ``identity`` and ``request`` it
        names, if any, are these; else ``None``. The record is read as the lookup reads it, without that tool's
        ``readStrictCache`` (links, ``nlink``, a second read; R6): B16's publish can leave ``nlink`` 2. Raises what
        reading the record raises."""
        cache = await asyncio.to_thread(self._read, key)
        if (not self._current(cache, key) or not same(cache['result'], result)
                or any(name in cache and not same(cache[name], value)
                       for name, value in (('identity', identity), ('request', request)))):
            return None
        return cache.get('finished_at')

    # --- The worker -----------------------------------------------------------------------------------------------

    def run(self, job: DesignJob) -> Awaitable[None]:
        """``run(j)``: the returned task spawns the worker and settles once it is spawned or the spawn failed (which
        finishes the job ``failed`` with the error's message)."""
        if self.disposed:
            self.finish(job, 'cancelled', '服务重启，任务未启动')
            settled = asyncio.get_running_loop().create_future()
            settled.set_result(None)
            return settled
        return self._track(self._start(job))

    async def _start(self, job: DesignJob) -> None:
        def on_event(event: dict, _append: Any) -> None:
            kind = event.get('type', UNDEFINED)
            if _same(kind, 'progress') and not job.cancel_reason:
                number = to_number(event.get('progress', UNDEFINED))
                job.progress = max(job.progress, min(0.99, number if js_truthy(number) else 0))
                job.message = _js_string(event.get('message', UNDEFINED))
            if _same(kind, 'result'):
                job.terminal = event.get('result', UNDEFINED)
            if _same(kind, 'error'):
                job.worker_error = _js_string(event.get('message', UNDEFINED))

        def on_stderr(text: str) -> None:
            job.stderr = text

        def on_error(error: WorkerError) -> None:
            job.worker_error = error.message

        def on_stop(reason: str) -> None:
            job.cancel_reason, job.status, job.message = reason, 'cancelling', '正在停止计算'

        try:
            worker = await start_worker(
                self.python, ['-u', nodepath.join(self.root, self.script_name or WORKER_SCRIPT)], cwd=self.root,
                env={**os.environ, **WORKER_ENV}, input=self.worker_input(job), timeout=self.timeout_ms / 1000,
                max_output_bytes=MAX_OUTPUT_BYTES, on_event=on_event, on_stderr=on_stderr, on_error=on_error,
                on_stop=on_stop, on_close=lambda code, signal: self.close(job, code), spawn=self.spawn)
        except Exception as error:  # noqa: BLE001 - Node's catch: any spawn failure fails the job
            self.finish(job, 'failed', node_message(error))
            return
        job.worker, job.child = worker, worker.child
        if job.pending_stop is not None:
            worker.stop(job.pending_stop)

    def close(self, job: DesignJob, code: Optional[int]) -> Awaitable[None]:
        """``close(j, code)``: the worker and its process group have exited. The stop reason and the exit status
        decide at once, then ``validate`` of the last result; the returned task computes the context again and
        finishes the job."""
        if job.cancel_reason:
            timed = job.cancel_reason == 'timeout'
            status = 'timeout' if timed else 'failed' if job.cancel_reason == 'input_error' else 'cancelled'
            minutes = jsjson.number_to_string(jsjson.round_half_up(self.timeout_ms / 60000))
            return self.finish(job, status, f'达到{minutes}分钟计算时限，未保存未完成结果' if timed else '计算已停止')
        if code != 0:
            return self.finish(job, 'failed',
                               job.worker_error if job.worker_error is not None else '计算未完成，错误记录已保存')
        try:
            self.validate(job.terminal, job.request, _get(job.ctx, 'admission'))
        except Exception as error:  # noqa: BLE001 - Node's catch
            return self.finish(job, 'failed', node_message(error))
        return self._track(self._confirm(job))

    async def _confirm(self, job: DesignJob) -> None:
        try:
            if not _same(_get(await self.context(job.request), 'key'), job.key):
                raise DesignJobError('计算期间输入或代码发生变化')
            job.result = job.terminal
            await self.finish(job, 'completed', '设计评价已完成并保存')
        except Exception as error:  # noqa: BLE001 - Node's catch
            await self.finish(job, 'failed', node_message(error))

    def finish(self, job: DesignJob, status: str, message: str) -> Awaitable[None]:
        """``finish(j, status, message)``: Node's synchronous part (status, message, ``result`` cleared unless
        completed; for a result progress 1 and the ``cache.json`` value with ``finished_at``) happens now; the
        returned task publishes ``cache.json``, then writes ``job.json``, then clears ``active``, releases the
        permit and calls the ``finish_callbacks``. A failed write makes the job ``failed`` with
        ``结果保存失败：<Node's message>`` (``job.json`` is not written when ``cache.json`` failed)."""
        job.status, job.message = status, message
        if status != 'completed':
            job.result = None
        cache = None
        if status == 'completed':
            job.progress = 1
            cache = _defined(('key', job.key), ('identity', _get(job.ctx, 'identity')), ('result', job.result),
                             ('result_sha256', jsjson.sha256_hex(job.result)), ('finished_at', self._date()))
        return self._track(self._store(job, cache))

    def _stored(self, job: DesignJob) -> Any:
        """The ``cache.json`` already there when Node's lookup would take it for this job, else ``None``."""
        try:
            cache = self._read(job.key)
            if not self._current(cache, job.key):
                return None
            self.validate(cache['result'], job.request, _get(job.ctx, 'admission'))
            return cache
        except Exception as error:  # noqa: BLE001 - as Node's lookup: anything else is not a hit
            if _unreadable(error):
                raise
            return None

    async def _store(self, job: DesignJob, cache: Optional[dict]) -> None:
        try:
            try:
                if cache is not None:
                    # A valid cache.json another workspace published first stays; this job keeps its own result.
                    await asyncio.to_thread(self.store.publish_cache, self.record_kind, job.key, cache,
                                            lambda: self._stored(job))
                value = {**self.view(job), 'stderr': job.stderr}
                await asyncio.to_thread(self.store.write, nodepath.join(job.batch, 'job.json'), value)
            except Exception as error:  # noqa: BLE001 - Node's catch
                job.status, job.result, job.message = 'failed', None, f'结果保存失败：{node_message(error)}'
            finally:
                if self.active is job:
                    self.active = None
                release, job.release_execution = job.release_execution, None
                if release is not None:
                    release()
            for callback in list(self.finish_callbacks):
                try:
                    callback(job)
                except Exception:  # noqa: BLE001 - a callback never breaks the run path
                    _log.exception('design finish callback failed')
        finally:
            if job.done is not None and not job.done.done():
                job.done.set_result(None)

    # --- Stops ----------------------------------------------------------------------------------------------------

    def cancel(self, id: Any, reason: str = 'user') -> None:
        """``cancel(id, reason)``: the worker of a running job gets ``SIGTERM`` (the job is ``cancelling`` until its
        close); an unknown, finished or already stopping job is left alone. Returns ``None``, as Node's."""
        job = self.jobs.get(id) if isinstance(id, str) else None
        if job is None or job.status not in RUNNING:
            return None
        if job.cancel_reason:
            return None
        if job.worker is not None:
            job.worker.stop(reason)
        elif job.status == 'running' and job.batch is not None:
            # Still spawning: stopped as soon as the worker exists, cancelling from now on as in Node.
            job.pending_stop = reason
            job.cancel_reason, job.status, job.message = reason, 'cancelling', '正在停止计算'
        return None

    def dispose(self) -> None:
        """``dispose()``: refuses new submits and stops the running worker (``restart``)."""
        self.disposed = True
        if self.active is not None:
            self.cancel(self.active.id, 'restart')

    async def aclose(self) -> None:
        """``dispose()``, then waits until the active job has finished and written its records (Python: the
        service's shutdown, so no worker outlives it)."""
        self.dispose()
        job = self.active
        if job is not None and job.done is not None:
            await asyncio.shield(job.done)


def _get_member(value: Any, key: str) -> Any:
    """``value.key`` on parsed JSON: ``null`` throws as V8 does (a miss in the callers' catch)."""
    if value is None:
        raise TypeError(f"Cannot read properties of null (reading '{key}')")
    if isinstance(value, dict):
        return value.get(key, UNDEFINED)
    return UNDEFINED
