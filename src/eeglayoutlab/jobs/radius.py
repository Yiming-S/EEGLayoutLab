"""The radius search's identity, stored results and execution service (``local-compute-server.mjs``, slices 3–4).

- ``validate_worker_result`` is ``validateWorkerResult`` (line 65): a result is accepted only for the request it
  was computed for, with ``expected_count`` distinct points at least 4 mm apart, balanced or adaptive regions, the
  geometry of the request and a consistent minimum of the three retention scores.
- ``code_identity`` is ``codeIdentity`` (99-109): the raw bytes of the radius worker, its configuration, the bank and
  surface-mask pointers and every top-level ``src/compact_eeg/*.py`` (sorted by UTF-16 code units), read at
  ``nodepath.join(root, path)`` without a containment check, links followed (plan B8: unlike the design inputs).
- ``RadiusCache`` is the read side of ``LocalComputeQueue``: ``identity_for``, ``read_cache`` and the input check of
  a cache hit (``InputIntegrity.verify``).
- ``RadiusService`` adds the job execution side of ``LocalComputeQueue`` (slice 4): ``health``, ``view``, ``lookup``,
  ``submit``, ``cancel`` and ``dispose``, sharing ``RecordStore`` and ``ExecutionSlot``, spawning the radius worker
  with ``shell=False`` and 2 BLAS/OMP threads (plan B10), and publishing ``cache.json`` once without replacing an
  already valid cache file (rule 2).
"""
from __future__ import annotations

import errno
import hashlib
import math
import os
import secrets
import threading
from typing import Any, Callable, Optional
import uuid

from ..schemas import jsjson
from ..schemas.radius_search import MASK_CODES, normalize_request
from ..server.workspace import iso_now
from . import nodepath
from .fingerprint import runtime_identity
from .identity import DATA_PRIOR_FILES, UNDEFINED, _member, _same, js_truthy, request_key
from .integrity import ADMISSION_POINTER, BANK_POINTER, InputIntegrity
from .records import RecordStore, node_message, read_file, scandir
from .runtime import runtime_config
from .worker import ExecutionSlot, WorkerHandle, execution_slot_for, start_python_worker

__all__ = [
    'MASK_CODES', 'RADIUS_IDENTITY_VERSION', 'RADIUS_THREADS', 'RadiusResultError', 'validate_worker_result',
    'code_identity', 'radius_identity', 'RadiusCache', 'RadiusService', 'normalize_request',
]

RADIUS_IDENTITY_VERSION = 'local-radius-queue/1'
RADIUS_THREADS = 2
MIN_ADAPTIVE_REGION_ELECTRODES = 4
CODE_FILES = ('scripts/run_local_radius_compute.py', 'configs/single_head_optimization.json', BANK_POINTER,
              ADMISSION_POINTER)
_SCORES = ('field_relative', 'sensitivity_tail', 'localization_relative')
_RUNNING = frozenset({'queued', 'running', 'cancelling'})


class RadiusResultError(ValueError):
    """A worker result ``validateWorkerResult`` refuses; the message is Node's, verbatim."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _finite(value: Any) -> bool:
    """``Number.isFinite(value)``."""
    return jsjson.is_number(value) and math.isfinite(jsjson.to_number(value))


def _coordinates(rows: Any, expected_len: int = 64) -> bool:
    return (isinstance(rows, list) and len(rows) == expected_len
            and all(isinstance(row, list) and len(row) == 3 and all(_finite(v) for v in row) for row in rows))


def _joined(point: list) -> str:
    """``point.join(',')`` of finite numbers (``-0`` is written ``0``)."""
    return ','.join(jsjson.number_to_string(jsjson.to_number(v)) for v in point)


def balanced_count(region: int, regions: int, total: int = 64) -> int:
    """``Math.floor(total / regions) + Number(region < total % regions)``."""
    return total // regions + int(region < total % regions)


def validate_worker_result(result: Any, request: dict) -> None:
    """``validateWorkerResult(result, request)``; ``request`` is a canonical radius request. Raises
    ``RadiusResultError`` (or the format's ``ValueError`` for a result request Node's normalizer refuses)."""
    if (not js_truthy(result) or _member(result, 'status') not in ('completed', 'no_layout')
            or jsjson.stringify(normalize_request(_member(result, 'request'))) != jsjson.stringify(request)):
        raise RadiusResultError('结果配置不一致')
    if result['status'] == 'no_layout':
        if _member(result, 'layout') not in (None, UNDEFINED) or _member(result, 'metrics') not in (None, UNDEFINED):
            raise RadiusResultError('无布局任务不能附带分数')
        return
    layout, geometry, metrics = _member(result, 'layout'), _member(result, 'geometry'), _member(result, 'metrics')
    regions = int(request['region_count'])
    raw_ec = _member(request, 'electrode_count')
    expected_count = 64 if raw_ec in (None, UNDEFINED) else int(raw_ec)
    if (not js_truthy(layout) or not _coordinates(_member(layout, 'xyzMm'), expected_count)
            or not _coordinates(_member(layout, 'referenceXyzMm'), 64)
            or len({_joined(row) for row in layout['xyzMm']}) != expected_count
            or not isinstance(_member(layout, 'regionIndices'), list) or len(layout['regionIndices']) != expected_count
            or not all(jsjson.is_integer(r) and 0 <= r < regions for r in layout['regionIndices'])):
        raise RadiusResultError(f'无效{expected_count}点坐标')
    labels = layout['regionIndices']
    if _same(_member(request, 'allocation_mode'), 'adaptive'):
        if any(sum(1 for v in labels if v == r) < MIN_ADAPTIVE_REGION_ELECTRODES for r in range(regions)):
            raise RadiusResultError('区域分配错误')
    elif any(sum(1 for v in labels if v == r) != balanced_count(r, regions, expected_count) for r in range(regions)):
        raise RadiusResultError('区域分配错误')
    if not js_truthy(geometry) or not _same(_member(geometry, 'union_connected_component_count'), request['region_count']):
        raise RadiusResultError('区域几何无效')
    radius = _member(geometry, 'common_graph_radius_mm')
    area = _member(geometry, 'union_area_cm2')
    if (not _finite(radius) or radius <= 0 or radius > request['radius_mm'] + 1e-7
            or not _finite(area) or area <= 0):
        raise RadiusResultError('区域几何无效')
    xyz = layout['xyzMm']
    for i in range(expected_count):
        for j in range(i + 1, expected_count):
            if jsjson.hypot(*(a - b for a, b in zip(xyz[i], xyz[j]))) < 4 - 1e-7:
                raise RadiusResultError('电极间距不足')
    if not js_truthy(metrics):
        raise RadiusResultError('指标无效')
    scores = [_member(metrics, name) for name in _SCORES]
    if any(score is not None and not _finite(score) for score in scores):
        raise RadiusResultError('指标无效')
    expected = None if any(score is None for score in scores) else min(scores)
    conditional = _member(metrics, 'conditional_global')
    if (conditional is not None if expected is None
            else not (_finite(conditional) and abs(conditional - expected) <= 1e-10)):
        raise RadiusResultError('综合约束计算不一致')


# --- Identity ----------------------------------------------------------------------------------------------------

def code_identity(root: str) -> dict[str, str]:
    """``codeIdentity(repositoryRoot)``: SHA-256 of the raw bytes of each code file, in Node's order."""
    names = [name for name, _ in scandir(nodepath.join(root, 'src/compact_eeg')) if name.endswith('.py')]
    paths = [*CODE_FILES, *(f'src/compact_eeg/{name}' for name in nodepath.js_sort(names))]
    return {path: _sha256(read_file(nodepath.join(root, path))) for path in paths}


def radius_identity(root: str, request: Any, code: dict, runtime: Any) -> dict:
    """``identityFor(request, code).identity``: ``{version, code: {...code, ...prior}, threads, runtime?}``."""
    prior = ({path: _sha256(read_file(nodepath.join(root, path))) for path in DATA_PRIOR_FILES}
             if js_truthy(_member(request, 'data_prior')) else {})
    identity: dict[str, Any] = {'version': RADIUS_IDENTITY_VERSION, 'code': {**code, **prior},
                                'threads': RADIUS_THREADS}
    if js_truthy(runtime):
        identity['runtime'] = runtime
    return identity


class RadiusCache:
    """The read side of Node's ``LocalComputeQueue`` on one root."""

    def __init__(self, root: str, python: str, *, store: Optional[RecordStore] = None,
                 get_identity: Optional[Callable[[], dict]] = None,
                 get_runtime: Optional[Callable[[], Any]] = None,
                 verify_inputs: Optional[Callable[[Any], None]] = None):
        self.root = nodepath.resolve(root)
        self.python = python
        self.store = store or RecordStore(self.root)
        self.get_identity = get_identity or (lambda: code_identity(self.root))
        if get_runtime is None:
            get_runtime = (lambda: None) if get_identity else (lambda: runtime_identity(self.python))
        self.get_runtime = get_runtime
        inputs = InputIntegrity(self.root)
        if verify_inputs is None:
            verify_inputs = ((lambda result: None) if get_identity
                             else (lambda result: inputs.verify(_member(result, 'provenance'))))
        self.verify_inputs = verify_inputs

    def identity_for(self, request: Any, code: Optional[dict] = None) -> tuple[dict, str]:
        """``identityFor(request, code = this.getIdentity())``: the identity and its key."""
        if code is None:
            code = self.get_identity()
        runtime = self.get_runtime()
        identity = radius_identity(self.root, request, code, runtime)
        return identity, request_key(request, identity)

    def read_cache(self, key: str, request: Optional[dict] = None) -> Optional[dict]:
        """``await readCache(key, request)``: the stored ``{key, request, result, result_sha256, finished_at}`` with
        the canonical request, or ``None`` for a record that is missing, corrupt or not this request's."""
        try:
            cache = self.store.read(self.store.path('radius', key, 'cache.json'))
            result = _member(cache, 'result')
            if not _same(_member(cache, 'key'), key) or result is UNDEFINED:
                return None
            if not _same(_member(cache, 'result_sha256'), jsjson.sha256_hex(result)):
                return None
            normalized = normalize_request(_member(cache, 'request'))
            if request is not None and jsjson.stringify(normalized) != jsjson.stringify(request):
                return None
            validate_worker_result(result, normalized)
            return {**cache, 'request': normalized}
        except Exception as error:
            if isinstance(error, OSError) and error.errno in (errno.EACCES, errno.EPERM):
                raise
            return None


# --- RadiusService (slice 4) -------------------------------------------------------------------------------------

class _RadiusJob:
    def __init__(
        self,
        *,
        id: str,
        key: str,
        request: dict,
        status: str,
        stage: str,
        progress: float,
        message: str,
        created_at: str,
        finished_at: Optional[str] = None,
        cached: bool = False,
        result: Any = None,
        batch: Optional[str] = None,
        cache_path: Optional[str] = None,
        identity: Optional[dict] = None,
        release_execution: Optional[Callable[[], None]] = None,
    ):
        self.id = id
        self.key = key
        self.request = request
        self.status = status
        self.stage = stage
        self.progress = progress
        self.message = message
        self.created_at = created_at
        self.finished_at = finished_at
        self.cached = cached
        self.result = result
        self.batch = batch
        self.cache_path = cache_path
        self.identity = identity or {}
        self.release_execution = release_execution
        self.events: list[Any] = []
        self.stderr = ''
        self.cancel_reason: Optional[str] = None
        self.spawn_error: Optional[str] = None
        self.worker: Optional[WorkerHandle] = None
        self.child: Any = None


class RadiusService(RadiusCache):
    """Port of ``LocalComputeQueue`` (``webapp/server/local-compute-server.mjs``, slice 4)."""

    def __init__(
        self,
        repository_root: Optional[str] = None,
        *,
        python: Optional[str] = None,
        timeout_ms: float = 180000,
        spawn_process: Optional[Callable[..., Any]] = None,
        store: Optional[RecordStore] = None,
        execution_slot: Optional[ExecutionSlot] = None,
        get_identity: Optional[Callable[[], dict]] = None,
        get_runtime: Optional[Callable[[], Any]] = None,
        verify_inputs: Optional[Callable[[Any], None]] = None,
    ):
        self.runtime = runtime_config(repository_root, python=python)
        super().__init__(
            self.runtime.repository_root,
            self.runtime.python,
            store=store,
            get_identity=get_identity,
            get_runtime=get_runtime,
            verify_inputs=verify_inputs,
        )
        self.execution_slot = execution_slot or execution_slot_for(self)
        self.timeout_ms = timeout_ms
        self.spawn_process = spawn_process
        self._lock = threading.RLock()
        self.jobs: dict[str, _RadiusJob] = {}
        self.active: Optional[_RadiusJob] = None
        self.submitting = False
        self.disposed = False
        self.local_only = True
        self.token = secrets.token_hex(32)

    def health(self) -> dict[str, Any]:
        available = (os.path.exists(nodepath.join(self.root, 'scripts/run_local_radius_compute.py'))
                     and os.path.exists(nodepath.join(self.root, 'results/v2/current_multiregion_bank.json')))
        with self._lock:
            active_view = self.view(self.active) if self.active is not None else None
        return {
            'available': available, 'local_only': self.local_only, 'token': self.token,
            'max_concurrent_jobs': 1, 'threads': RADIUS_THREADS,
            'timeout_seconds': self.timeout_ms / 1000, 'supported_masks': list(MASK_CODES),
            'active_job': active_view,
        }

    @staticmethod
    def view(job: _RadiusJob) -> dict[str, Any]:
        return {
            'id': job.id,
            'key': job.key,
            'request': job.request,
            'status': job.status,
            'stage': job.stage,
            'progress': job.progress,
            'message': job.message,
            'result': job.result if job.result is not None else None,
            'created_at': job.created_at,
            'finished_at': job.finished_at if job.finished_at is not None else None,
            'cached': bool(job.cached),
            'source': 'local_cache' if job.cached else 'local_compute',
        }

    def lookup(self, raw: Any, identity_key: Optional[tuple[dict, str]] = None) -> dict[str, Any]:
        request = normalize_request(raw)
        _, key = identity_key if identity_key is not None else self.identity_for(request)
        with self._lock:
            same = next((j for j in self.jobs.values()
                         if j.key == key and j.status in ('completed', 'no_layout')), None)
        if same is not None:
            self.verify_inputs(same.result)
            return {'hit': True, 'job': {**self.view(same), 'cached': True, 'source': 'local_cache'}}
        cache = self.read_cache(key, request)
        if cache is None:
            return {'hit': False}
        self.verify_inputs(cache['result'])
        job = _RadiusJob(
            id=str(uuid.uuid4()),
            key=key,
            request=request,
            status=cache['result']['status'],
            stage='cached',
            progress=1,
            message='已读取相同模型与配置的已有计算记录',
            result=cache['result'],
            created_at=iso_now(),
            finished_at=cache.get('finished_at'),
            cached=True,
        )
        with self._lock:
            self.jobs[job.id] = job
            while len(self.jobs) > 100:
                oldest = next((entry for entry in self.jobs.values() if entry is not self.active), None)
                if oldest is None:
                    break
                self.jobs.pop(oldest.id, None)
            return {'hit': True, 'job': self.view(job)}

    def submit(self, raw: Any) -> dict[str, Any]:
        if self.disposed:
            raise RuntimeError('计算服务正在重启')
        request = normalize_request(raw)
        with self._lock:
            if self.submitting:
                return {'busy': True}
            self.submitting = True
        release: Optional[Callable[[], None]] = None
        try:
            identity, key = self.identity_for(request)
            stored = self.lookup(request, (identity, key))
            if stored.get('hit'):
                return {'job': stored['job']}
            if self.disposed:
                raise RuntimeError('计算服务正在重启')
            with self._lock:
                if self.active is not None:
                    if self.active.key == key:
                        return {'job': self.view(self.active)}
                    return {'busy': True, 'active_job': self.view(self.active)}
            release = self.execution_slot.acquire(self)
            if release is None:
                return {'busy': True}
            cache_path = self.store.path('radius', key, 'cache.json')
            job_id = str(uuid.uuid4())
            batch = self.store.create_batch('radius', key, job_id)
            self.store.write(nodepath.join(batch, 'request.json'),
                             {'request': request, 'identity': identity, 'key': key})
            if self.disposed:
                raise RuntimeError('计算服务正在重启')
            job = _RadiusJob(
                id=job_id,
                key=key,
                request=request,
                status='queued',
                stage='queued',
                progress=0,
                message='等待计算进程启动',
                created_at=iso_now(),
                batch=batch,
                cache_path=cache_path,
                identity=identity,
                release_execution=release,
            )
            with self._lock:
                self.jobs[job_id] = job
                self.active = job
            release = None
            self._run(job)
            with self._lock:
                return {'job': self.view(job)}
        finally:
            if release is not None:
                release()
            with self._lock:
                self.submitting = False

    def _run(self, job: _RadiusJob) -> None:
        if self.disposed:
            self._finish(job, 'cancelled', '服务重启，任务未启动')
            return
        terminal: list[Any] = [None]
        with self._lock:
            job.status = 'running'
            job.stage = 'starting'
            job.message = '正在加载本地头模与前向矩阵'

        def on_event(event: dict, *_: Any) -> None:
            with self._lock:
                if event.get('type') == 'progress' and not job.cancel_reason:
                    raw_prog = event.get('progress')
                    prog = float(raw_prog) if jsjson.is_number(raw_prog) and math.isfinite(float(raw_prog)) else 0.0
                    job.progress = max(job.progress, min(0.99, prog))
                    job.stage = str(event.get('stage') or 'computing')
                    job.message = str(event.get('message') or '正在计算')
                elif event.get('type') == 'result':
                    terminal[0] = event.get('result')
                job.events.append(event)

        def on_log(text: str) -> None:
            with self._lock:
                job.events.append({'type': 'log', 'text': text})

        def on_stderr(text: str) -> None:
            with self._lock:
                job.stderr = text

        def on_error(err: BaseException) -> None:
            with self._lock:
                job.spawn_error = str(err)

        def on_stop(stop_reason: str) -> None:
            with self._lock:
                job.cancel_reason = stop_reason
                job.status = 'cancelling'
                job.message = '正在停止计算'

        def on_close(code: Optional[int], _sig: Optional[str] = None) -> None:
            res = terminal[0]
            if job.cancel_reason:
                timed = job.cancel_reason == 'timeout'
                status = 'timeout' if timed else ('failed' if job.cancel_reason == 'input_error' else 'cancelled')
                msg = '达到计算时限，任务已停止；未把缺失结果写成0' if timed else '任务已停止'
                self._finish(job, status, msg)
                return
            if code == 0 and isinstance(res, dict) and res.get('status') in ('completed', 'no_layout'):
                try:
                    validate_worker_result(res, job.request)
                    sources = (_member(_member(res, 'provenance'), 'code_sha256')
                               if isinstance(_member(res, 'provenance'), dict) else {})
                    if isinstance(sources, dict):
                        for path, digest in sources.items():
                            if job.identity.get('code', {}).get(path) != digest:
                                raise ValueError('任务排队后科学代码已变化')
                except Exception as err:  # noqa: BLE001
                    self._finish(job, 'failed', f'计算结果校验失败：{err}')
                    return
                with self._lock:
                    job.result = res
                count = job.request.get('electrode_count') or 64
                msg = '当前配置已计算' if res['status'] == 'completed' else f'本次搜索预算内未构造出{count}点布局'
                self._finish(job, res['status'], msg)
            else:
                msg = (f'Python启动失败：{job.spawn_error}' if job.spawn_error
                       else '计算未成功完成；错误记录已保存，可重新计算')
                self._finish(job, 'failed', msg)

        env = {
            **os.environ,
            'OMP_NUM_THREADS': '2',
            'OPENBLAS_NUM_THREADS': '2',
            'MKL_NUM_THREADS': '2',
            'VECLIB_MAXIMUM_THREADS': '2',
            'PYTHONUNBUFFERED': '1',
        }
        try:
            handle = start_python_worker(
                spawn_process=self.spawn_process,
                executable=self.python,
                args=['-u', nodepath.join(self.root, 'scripts/run_local_radius_compute.py')],
                options={'cwd': self.root, 'stdio': ['pipe', 'pipe', 'pipe'], 'env': env},
                input=job.request,
                has_input=True,
                timeout_ms=self.timeout_ms,
                max_output_bytes=8 * 1024 * 1024,
                on_event=on_event,
                on_log=on_log,
                on_stderr=on_stderr,
                on_error=on_error,
                on_stop=on_stop,
                on_close=on_close,
            )
            with self._lock:
                job.worker = handle
                job.child = handle.child
        except Exception as err:  # noqa: BLE001
            self._finish(job, 'failed', f'无法启动Python：{err}')

    def _finish(self, job: _RadiusJob, status: str, message: str) -> None:
        with self._lock:
            job.status = status
            job.stage = status
            job.message = message
            job.finished_at = iso_now()
            if status in ('completed', 'no_layout'):
                job.progress = 1
        try:
            if job.batch is not None:
                self.store.write(
                    nodepath.join(job.batch, 'job.json'),
                    {**self.view(job), 'events': list(job.events), 'stderr': job.stderr},
                )
            if status in ('completed', 'no_layout') and job.cache_path is not None:
                # Rule 2: Python publishes a cache.json once and never replaces a valid one.
                if self.read_cache(job.key, job.request) is None:
                    self.store.write(job.cache_path, {
                        'key': job.key,
                        'request': job.request,
                        'result': job.result,
                        'result_sha256': jsjson.sha256_hex(job.result),
                        'finished_at': job.finished_at,
                    })
        except Exception as err:  # noqa: BLE001
            with self._lock:
                job.status = 'failed'
                job.stage = 'failed'
                job.message = f'计算记录保存失败：{node_message(err)}'
                job.result = None
        finally:
            with self._lock:
                if self.active is job:
                    self.active = None
                rel = job.release_execution
                job.release_execution = None
                while len(self.jobs) > 100:
                    first_key = next(iter(self.jobs))
                    self.jobs.pop(first_key, None)
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
            if job is None or job.status not in _RUNNING:
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
            self.cancel(active_id, 'server_restart')
