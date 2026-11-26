"""Design-evaluation execution service (``webapp/server/design-evaluation-server.mjs``, phase 2 slice 5).

Ports ``DesignEvaluationService`` for coordinate evaluation and grid-displacement perturbation:
- Uses ``RuntimeConfig.native_python`` (plan B5) with 1 thread across OMP/BLAS/MKL/vecLib (plan B10).
- Shares ``RecordStore`` and ``ExecutionSlot`` with the radius, editor and reception services.
- Validates worker outputs via ``validate_design_result`` (including ``valid_robustness`` when requested) and
  re-verifies ``context(request).key == job.key`` before publishing.
- Publishes ``cache.json`` once (rule 2, plan B16) in Node's exact field order
  ``{key, identity, result, result_sha256, finished_at}`` (plan B14, whose bytes hash into reception v2 keys),
  and writes batch ``request.json`` as ``{request, identity}`` (plan B19).
"""
from __future__ import annotations

import errno
import inspect
import math
import os
import threading
from typing import Any, Callable, Optional
import uuid

from ..schemas import jsjson
from ..server.workspace import iso_now
from . import nodepath
from .annotations import design_submission
from .design_result import UNDEFINED, normalize_design_request, validate_design_result
from .identity import DesignContext, design_context
from .integrity import InputIntegrity
from .records import RecordStore, node_message
from .runtime import runtime_config
from .worker import ExecutionSlot, WorkerHandle, execution_slot_for, start_python_worker

__all__ = ['DESIGN_THREADS', 'DesignEvaluationService', 'design_adapter']

DESIGN_THREADS = 1


def _call_maybe_async(fn: Callable[..., Any], *args: Any) -> Any:
    out = fn(*args)
    if inspect.isawaitable(out):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            return asyncio.run(out)
        box: list[Any] = []
        err: list[BaseException] = []

        def runner() -> None:
            try:
                box.append(asyncio.run(out))
            except BaseException as exc:  # noqa: BLE001
                err.append(exc)

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()
        if err:
            raise err[0]
        return box[0]
    return out


class _DesignJob:
    def __init__(
        self,
        *,
        id: str,
        key: str,
        request: dict[str, Any],
        ctx: dict[str, Any],
        status: str,
        progress: float,
        message: str,
        result: Any = None,
        cached: bool = False,
        batch: Optional[str] = None,
        directory: Optional[str] = None,
        release_execution: Optional[Callable[[], None]] = None,
    ):
        self.id = id
        self.key = key
        self.request = request
        self.ctx = ctx
        self.status = status
        self.progress = progress
        self.message = message
        self.result = result
        self.cached = cached
        self.batch = batch
        self.directory = directory
        self.release_execution = release_execution
        self.stderr = ''
        self.terminal: Any = None
        self.worker_error: Optional[str] = None
        self.cancel_reason: Optional[str] = None
        self.worker: Optional[WorkerHandle] = None
        self.child: Any = None


class DesignEvaluationService:
    """Port of ``DesignEvaluationService`` (``webapp/server/design-evaluation-server.mjs``)."""

    record_kind = 'design'
    script_name = 'scripts/design_evaluation.py'

    def __init__(
        self,
        repository_root: Optional[str] = None,
        *,
        python: Optional[str] = None,
        runtime: Any = None,
        timeout_ms: float = 600000,
        spawn_process: Optional[Callable[..., Any]] = None,
        store: Optional[RecordStore] = None,
        execution_slot: Optional[ExecutionSlot] = None,
        inputs: Optional[InputIntegrity] = None,
        context_override: Optional[Callable[[dict[str, Any]], Any]] = None,
    ):
        self.runtime = runtime or runtime_config(repository_root, python=python)
        self.root = nodepath.resolve(self.runtime.repository_root)
        self.python = self.runtime.native_python
        self.store = store or RecordStore(self.root)
        self.inputs = inputs or InputIntegrity(self.root)
        self.execution_slot = execution_slot or execution_slot_for(self)
        self.timeout_ms = timeout_ms
        self.spawn_process = spawn_process
        self.context_override = context_override

        self._lock = threading.RLock()
        self.jobs: dict[str, _DesignJob] = {}
        self.active: Optional[_DesignJob] = None
        self.submitting = False
        self.disposed = False

    def normalize(self, raw: Any) -> dict[str, Any]:
        return normalize_design_request(raw)

    def validate(self, result: Any, request: dict[str, Any], admission: Any = UNDEFINED) -> None:
        validate_design_result(result, request, admission)

    def worker_input(self, job: _DesignJob) -> Any:
        return job.request

    def context(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.context_override is not None:
            raw_ctx = _call_maybe_async(self.context_override, request)
            if isinstance(raw_ctx, DesignContext):
                return {'identity': raw_ctx.identity, 'admission': raw_ctx.admission, 'key': raw_ctx.key}
            return dict(raw_ctx)
        dc = design_context(self.root, self.python, self.inputs, request)
        return {'identity': dc.identity, 'admission': dc.admission, 'key': dc.key}

    def view(self, job: _DesignJob) -> dict[str, Any]:
        return {
            'id': job.id,
            'key': job.key,
            'status': job.status,
            'message': job.message,
            'progress': job.progress,
            'result': job.result if job.result is not None else None,
            'cached': bool(job.cached),
        }

    def _remember(self, job: _DesignJob) -> None:
        with self._lock:
            self.jobs[job.id] = job
            while len(self.jobs) > 20:
                victim = next((jid for jid in self.jobs if self.active is None or jid != self.active.id), None)
                if victim is None:
                    break
                self.jobs.pop(victim, None)

    def _read_valid_cache(self, key: str, request: dict[str, Any], admission: Any = UNDEFINED) -> Optional[dict[str, Any]]:
        cache_path = self.store.path(self.record_kind, key, 'cache.json')
        try:
            cache = self.store.read(cache_path)
            if not isinstance(cache, dict):
                return None
            if cache.get('key') != key or cache.get('result') is None:
                return None
            if jsjson.sha256_hex(cache['result']) != cache.get('result_sha256'):
                return None
            self.validate(cache['result'], request, admission)
            return cache
        except Exception as err:  # noqa: BLE001
            if isinstance(err, OSError) and err.errno in (errno.EACCES, errno.EPERM):
                raise
            return None

    def lookup(self, raw: Any, ctx: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        request = self.normalize(raw)
        resolved = ctx if ctx is not None else self.context(request)
        admission = resolved.get('admission', UNDEFINED)
        cache = self._read_valid_cache(resolved['key'], request, admission)
        if cache is None:
            return {'hit': False}
        job = _DesignJob(
            id=str(uuid.uuid4()),
            key=resolved['key'],
            request=request,
            ctx=resolved,
            status='completed',
            progress=1,
            message='设计评价已完成',
            result=cache['result'],
            cached=True,
        )
        view = self.view(job)
        if cache.get('finished_at') is not None:
            view = {**view, 'finished_at': cache['finished_at']}
        return {'hit': True, 'job': view}

    def submit(self, raw: Any) -> dict[str, Any]:
        if self.disposed:
            raise RuntimeError('计算服务正在重启')
        request = self.normalize(raw)
        with self._lock:
            if self.submitting:
                return {'busy': True, 'error': '正在处理另一项设计评价请求'}
            self.submitting = True
        release: Optional[Callable[[], None]] = None
        try:
            ctx = self.context(request)
            if self.disposed:
                raise RuntimeError('计算服务正在重启')
            key = ctx['key']
            admission = ctx.get('admission', UNDEFINED)
            directory = self.store.path(self.record_kind, key)
            cache = self._read_valid_cache(key, request, admission)
            if cache is not None:
                cached_job = _DesignJob(
                    id=str(uuid.uuid4()),
                    key=key,
                    request=request,
                    ctx=ctx,
                    status='completed',
                    progress=1,
                    message='设计评价已完成',
                    result=cache['result'],
                    cached=True,
                )
                self._remember(cached_job)
                return {'job': self.view(cached_job)}
            if self.disposed:
                raise RuntimeError('计算服务正在重启')
            with self._lock:
                if self.active is not None and self.active.key == key:
                    return {'job': self.view(self.active)}
            release = self.execution_slot.acquire(self)
            if release is None:
                return {'busy': True}
            job_id = str(uuid.uuid4())
            batch = self.store.create_batch(self.record_kind, key, job_id)
            self.store.write(
                nodepath.join(batch, 'request.json'),
                {'request': request, 'identity': ctx['identity']},
            )
            if self.disposed:
                raise RuntimeError('计算服务正在重启')
            job = _DesignJob(
                id=job_id,
                key=key,
                request=request,
                ctx=ctx,
                batch=batch,
                directory=directory,
                status='running',
                progress=0,
                message='准备本地坐标评价',
                release_execution=release,
            )
            with self._lock:
                self.active = job
            release = None
            self._remember(job)
            self._run(job)
            with self._lock:
                return {'job': self.view(job)}
        finally:
            if release is not None:
                release()
            with self._lock:
                self.submitting = False

    def _run(self, job: _DesignJob) -> None:
        if self.disposed:
            self._finish(job, 'cancelled', '服务重启，任务未启动')
            return

        def on_event(event: dict[str, Any], *_: Any) -> None:
            with self._lock:
                etype = event.get('type')
                if etype == 'progress' and not job.cancel_reason:
                    raw_prog = event.get('progress')
                    prog = float(raw_prog) if jsjson.is_number(raw_prog) and math.isfinite(float(raw_prog)) else 0.0
                    job.progress = max(job.progress, min(0.99, prog))
                    job.message = str(event.get('message', ''))
                elif etype == 'result':
                    job.terminal = event.get('result')
                elif etype == 'error':
                    job.worker_error = str(event.get('message', ''))

        def on_stderr(text: str) -> None:
            with self._lock:
                job.stderr = text

        def on_error(err: BaseException) -> None:
            with self._lock:
                job.worker_error = str(err)

        def on_stop(reason: str) -> None:
            with self._lock:
                job.cancel_reason = reason
                job.status = 'cancelling'
                job.message = '正在停止计算'

        def on_close(code: Optional[int], _sig: Optional[str] = None) -> None:
            self._close_worker(job, code)

        env = {
            **os.environ,
            'OMP_NUM_THREADS': str(DESIGN_THREADS),
            'OPENBLAS_NUM_THREADS': str(DESIGN_THREADS),
            'MKL_NUM_THREADS': str(DESIGN_THREADS),
            'VECLIB_MAXIMUM_THREADS': str(DESIGN_THREADS),
            'PYTHONDONTWRITEBYTECODE': '1',
        }
        try:
            handle = start_python_worker(
                spawn_process=self.spawn_process,
                executable=self.python,
                args=['-u', nodepath.join(self.root, self.script_name)],
                options={'cwd': self.root, 'stdio': ['pipe', 'pipe', 'pipe'], 'env': env},
                input=self.worker_input(job),
                has_input=True,
                timeout_ms=self.timeout_ms,
                max_output_bytes=4 * 1024 * 1024,
                on_event=on_event,
                on_stderr=on_stderr,
                on_error=on_error,
                on_stop=on_stop,
                on_close=on_close,
            )
            with self._lock:
                job.worker = handle
                job.child = handle.child
        except Exception as err:  # noqa: BLE001
            self._finish(job, 'failed', str(err))

    def _close_worker(self, job: _DesignJob, code: Optional[int]) -> None:
        if job.cancel_reason:
            status = (
                'timeout' if job.cancel_reason == 'timeout'
                else 'failed' if job.cancel_reason == 'input_error'
                else 'cancelled'
            )
            minutes = jsjson.round_half_up(self.timeout_ms / 60000)
            msg = (
                f'达到{int(minutes)}分钟计算时限，未保存未完成结果'
                if job.cancel_reason == 'timeout'
                else '计算已停止'
            )
            self._finish(job, status, msg)
            return
        if code != 0:
            self._finish(job, 'failed', job.worker_error or '计算未完成，错误记录已保存')
            return
        try:
            admission = job.ctx.get('admission', UNDEFINED)
            self.validate(job.terminal, job.request, admission)
            current_ctx = self.context(job.request)
            if current_ctx['key'] != job.key:
                raise ValueError('计算期间输入或代码发生变化')
            with self._lock:
                job.result = job.terminal
            self._finish(job, 'completed', '设计评价已完成并保存')
        except Exception as err:  # noqa: BLE001
            self._finish(job, 'failed', str(err))

    def _finish(self, job: _DesignJob, status: str, message: str) -> None:
        with self._lock:
            job.status = status
            job.message = message
            if status != 'completed':
                job.result = None
            else:
                job.progress = 1
        try:
            if status == 'completed' and job.directory is not None:
                admission = job.ctx.get('admission', UNDEFINED)
                # Rule 2 (plan B16): publish cache.json once, never overwrite an already valid cache.json.
                if self._read_valid_cache(job.key, job.request, admission) is None:
                    # Plan B14: exact field order key, identity, result, result_sha256, finished_at.
                    self.store.write(
                        nodepath.join(job.directory, 'cache.json'),
                        {
                            'key': job.key,
                            'identity': job.ctx['identity'],
                            'result': job.result,
                            'result_sha256': jsjson.sha256_hex(job.result),
                            'finished_at': iso_now(),
                        },
                    )
            if job.batch is not None:
                self.store.write(
                    nodepath.join(job.batch, 'job.json'),
                    {**self.view(job), 'stderr': job.stderr},
                )
        except Exception as err:  # noqa: BLE001
            with self._lock:
                job.status = 'failed'
                job.result = None
                job.message = f'结果保存失败：{node_message(err)}'
        finally:
            with self._lock:
                if self.active is job:
                    self.active = None
                rel = job.release_execution
                job.release_execution = None
            if rel is not None:
                rel()

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            job = self.jobs.get(job_id)
            return self.view(job) if job is not None else None

    @property
    def busy(self) -> bool:
        with self._lock:
            return self.active is not None or self.submitting

    def pid(self) -> Optional[int]:
        with self._lock:
            pid = getattr(self.active.child, 'pid', None) if self.active is not None else None
            return pid if type(pid) is int and pid > 0 else None

    def cancel(self, job_id: str, reason: str = 'user') -> bool:
        with self._lock:
            job = self.jobs.get(job_id)
            if job is None or job.status not in ('running', 'cancelling'):
                return False
            if job.cancel_reason:
                return True
            worker = job.worker
        if worker is not None:
            worker.stop(reason)
        return True

    def dispose(self) -> None:
        self.disposed = True
        with self._lock:
            active_id = self.active.id if self.active is not None else None
        if active_id is not None:
            self.cancel(active_id, 'restart')


def design_adapter(service: DesignEvaluationService) -> dict[str, Callable[..., Any]]:
    """Adapter binding ``DesignEvaluationService`` (and ``design-submission/1`` envelopes) into ``WorkspaceQueue``."""
    def prepare(raw: Any) -> dict[str, Any]:
        submission = design_submission(raw)
        request = service.normalize(submission['request'])
        ctx = service.context(request)
        out: dict[str, Any] = {'request': request, 'key': ctx['key'], 'ctx': ctx}
        if 'electrode_names' in submission:
            out['electrode_names'] = submission['electrode_names']
        if 'source_metadata' in submission:
            out['source_metadata'] = submission['source_metadata']
        return out

    return {
        'prepare': prepare,
        'lookup': lambda p: service.lookup(p['request'], p['ctx']),
        'start': lambda r: service.submit(r),
        'get': lambda job_id: service.get(job_id),
        'busy': lambda: bool(service.busy),
        'pid': lambda: service.pid(),
        'cancel': lambda job_id: service.cancel(job_id),
    }
