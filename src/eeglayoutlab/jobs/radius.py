"""The radius search's identity and stored results: Node's ``local-compute-server.mjs``, statement by statement.

- ``validate_worker_result`` is ``validateWorkerResult`` (line 65): a result is accepted only for the request it
  was computed for, with 64 distinct points at least 4 mm apart, balanced regions, the geometry of the request and
  a consistent minimum of the three retention scores.
- ``code_identity`` is ``codeIdentity`` (99-109): the raw bytes of the radius worker, its configuration, the bank and
  surface-mask pointers and every top-level ``src/compact_eeg/*.py`` (sorted by UTF-16 code units), read at
  ``nodepath.join(root, path)`` without a containment check, links followed (plan B8: unlike the design inputs).
- ``RadiusCache`` is the read side of ``LocalComputeQueue``: ``identity_for`` (148-155, the key format of every
  radius record), ``read_cache`` (157-170) and the input check of a cache hit (``InputIntegrity.verify``).
- ``RadiusJobs`` adds the run path (111-303): ``health``, ``view``, ``lookup``, ``submit``, ``run``, ``finish``,
  ``cancel`` and ``dispose``, with Node's messages, statuses and record bytes (see its docstring).

The request format itself is ``eeglayoutlab.schemas.radius_search.normalize_request`` (``normalizeRequest``).
The runtime member comes from ``runtime_identity`` of the compute interpreter (``RuntimeConfig.python``, Node's
``computePython``), never from the native one; it is ``None`` on macOS, so identities there have no ``runtime``.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import logging
import math
import os
import secrets
import time
from typing import Any, Awaitable, Callable, Optional
import uuid

from ..schemas import jsjson
from ..schemas.radius_search import MASK_CODES, normalize_request
from . import nodepath
from .bundle import to_number as js_number
from .fingerprint import runtime_identity
from .identity import DATA_PRIOR_FILES, UNDEFINED, _js_string, _member, _same, js_truthy, request_key
from .integrity import ADMISSION_POINTER, BANK_POINTER, InputIntegrity
from .records import RecordStore, node_message, read_file, scandir
from .slot import ExecutionSlot, InstallationLock
from .worker import WorkerError, start_worker

__all__ = ['MASK_CODES', 'RADIUS_IDENTITY_VERSION', 'RADIUS_THREADS', 'RadiusResultError', 'validate_worker_result',
           'code_identity', 'radius_identity', 'RadiusCache', 'normalize_request', 'RadiusJobs', 'RadiusJob',
           'RadiusJobError', 'WORKER_SCRIPT', 'WORKER_ENV', 'MAX_OUTPUT_BYTES', 'TIMEOUT_MS', 'iso_time']

RADIUS_IDENTITY_VERSION = 'local-radius-queue/1'
RADIUS_THREADS = 2
MIN_ADAPTIVE_REGION_ELECTRODES = 4
CODE_FILES = ('scripts/run_local_radius_compute.py', 'configs/single_head_optimization.json', BANK_POINTER,
              ADMISSION_POINTER)
_SCORES = ('field_relative', 'sensitivity_tail', 'localization_relative')


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
    """``codeIdentity(repositoryRoot)``: SHA-256 of the raw bytes of each code file, in Node's order.

    ``readdirSync`` lists ``src/compact_eeg`` (a missing directory raises ``ENOENT``, as in Node); names ending in
    ``.py`` are kept (a directory so named fails to read with ``EISDIR``) and sorted by UTF-16 code units.
    """
    names = [name for name, _ in scandir(nodepath.join(root, 'src/compact_eeg')) if name.endswith('.py')]
    paths = [*CODE_FILES, *(f'src/compact_eeg/{name}' for name in nodepath.js_sort(names))]
    return {path: _sha256(read_file(nodepath.join(root, path))) for path in paths}


def radius_identity(root: str, request: Any, code: dict, runtime: Any) -> dict:
    """``identityFor(request, code).identity``: ``{version, code: {...code, ...prior}, threads, runtime?}``.

    The data-prior files (``DATA_PRIOR_FILES``, raw bytes) are added only for a request with a ``data_prior``, so
    the keys of other requests are unchanged; ``runtime`` only when it is truthy (off macOS).
    """
    prior = ({path: _sha256(read_file(nodepath.join(root, path))) for path in DATA_PRIOR_FILES}
             if js_truthy(_member(request, 'data_prior')) else {})
    identity: dict[str, Any] = {'version': RADIUS_IDENTITY_VERSION, 'code': {**code, **prior},
                                'threads': RADIUS_THREADS}
    if js_truthy(runtime):
        identity['runtime'] = runtime
    return identity


class RadiusCache:
    """The read side of Node's ``LocalComputeQueue`` on one root.

    ``python`` is the compute interpreter (``RuntimeConfig.python``), whose fingerprint is the identity's runtime
    off macOS. As in Node, a ``get_identity`` override (a test fixture) also turns the runtime off and makes the
    input check a no-op unless those are given too.
    """

    def __init__(self, root: str, python: str, *, get_identity: Optional[Callable[[], dict]] = None,
                 get_runtime: Optional[Callable[[], Any]] = None,
                 verify_inputs: Optional[Callable[[Any], None]] = None):
        self.root = nodepath.resolve(root)
        self.python = python
        self.store = RecordStore(self.root)
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
        the canonical request, or ``None`` for a record that is missing, corrupt or not this request's. Only
        ``EACCES`` and ``EPERM`` raise: an unreadable record is not a miss."""
        try:
            cache = self.store.read(self.store.path('radius', key, 'cache.json'))
            result = _member(cache, 'result')
            if not _same(_member(cache, 'key'), key) or result is UNDEFINED:
                # JSON.stringify(undefined) cannot be hashed: Node throws, which is a miss here too.
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


# --- The run path ------------------------------------------------------------------------------------------------

WORKER_SCRIPT = 'scripts/run_local_radius_compute.py'
# The worker's threads (B10): Node's environment overrides, added to the service's own environment.
WORKER_ENV = {'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2',
              'VECLIB_MAXIMUM_THREADS': '2', 'PYTHONUNBUFFERED': '1'}
TIMEOUT_MS = 180000
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
JOB_LIMIT = 100
RUNNING = ('queued', 'running', 'cancelling')
DONE = ('completed', 'no_layout')
_log = logging.getLogger(__name__)


class RadiusJobError(RuntimeError):
    """A refusal Node throws as a plain ``Error`` (``计算服务正在重启``); the message is Node's, verbatim."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def iso_time(milliseconds: float) -> str:
    """``new Date(milliseconds).toISOString()`` for years 0 to 9999: UTC, milliseconds and ``Z``."""
    moment = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=int(milliseconds))
    return moment.strftime('%Y-%m-%dT%H:%M:%S.') + f'{moment.microsecond // 1000:03d}Z'


def _now_ms() -> int:
    """``Date.now()``."""
    return time.time_ns() // 1_000_000


def _message(error: BaseException) -> str:
    """``error.message``."""
    message = getattr(error, 'message', None)
    return message if isinstance(message, str) else str(error)


def _entries(value: Any) -> list[tuple[str, Any]]:
    """``Object.entries(value)`` of parsed JSON: an object's members (V8's key order), an array's or a string's
    indices (a string by UTF-16 unit); numbers and booleans have none."""
    if isinstance(value, dict):
        return [(key, value[key]) for key in jsjson._own_keys(value)]
    if isinstance(value, list):
        return [(str(i), item) for i, item in enumerate(value)]
    if isinstance(value, str):
        data = value.encode('utf-16-le', errors='surrogatepass')
        return [(str(i // 2), data[i:i + 2].decode('utf-16-le', errors='surrogatepass'))
                for i in range(0, len(data), 2)]
    return []


def _key_of(identity_key: Any) -> Any:
    """``(identityKey || ...).key``: the pair ``identity_for`` returns, or a mapping with ``key`` (Node's ``{key}``
    and the queue's ``ctx``)."""
    if isinstance(identity_key, tuple):
        return identity_key[1]
    if isinstance(identity_key, Mapping):
        return identity_key.get('key', UNDEFINED)
    return identity_key


class RadiusJob:
    """One job of ``LocalComputeQueue``: Node's plain object, with its members as attributes.

    A submitted job has them all; a cached job made by ``lookup`` has the eleven ``view`` reads. ``result`` and
    ``finished_at`` are ``UNDEFINED`` until set (``view`` writes ``null`` for them), ``cached`` is ``None`` for a
    computed job (Node: absent). ``done`` (Python) resolves once ``finish`` has written the records and released
    the permit."""

    def __init__(self, id: str, key: str, request: dict, status: str, stage: str, progress: Any, message: str,
                 created_at: str, *, result: Any = UNDEFINED, finished_at: Any = UNDEFINED, cached: Any = None):
        self.id = id
        self.key = key
        self.request = request
        self.status = status
        self.stage = stage
        self.progress = progress
        self.message = message
        self.result = result
        self.created_at = created_at
        self.finished_at = finished_at
        self.cached = cached
        # A computed job's members (submit and run).
        self.release_execution: Optional[Callable[[], None]] = None
        self.batch: Optional[str] = None
        self.cache_path: Optional[str] = None
        self.events: list = []
        self.stderr = ''
        self.child: Any = None
        self.worker: Any = None
        self.identity: Any = None
        self.cancel_reason: Optional[str] = None
        self.spawn_error: Optional[str] = None
        # Python: a stop asked for while the worker was being spawned (Node spawns synchronously).
        self.pending_stop: Optional[str] = None
        self.done: Optional[asyncio.Future] = None

    @property
    def pid(self) -> Optional[int]:
        """``job.child?.pid``."""
        return self.worker.pid if self.worker is not None else None


class RadiusJobs(RadiusCache):
    """Node's ``LocalComputeQueue`` on one root: the radius search's lookups and its one computation at a time.

    The members follow Node's in snake case: ``health()``, ``view(job)``, ``identity_for``, ``read_cache``,
    ``await lookup(raw, identity_key)``, ``await submit(raw)``, ``run(job)``, ``finish(job, status,
    message)``, ``cancel(id, reason)`` and ``dispose()``, with the state the queue's adapter reads (``jobs``, an
    insertion-ordered map of at most 100 jobs, ``active``, ``submitting`` and ``active_pid()``).

    The worker is ``python -u R/scripts/run_local_radius_compute.py`` (``python`` is ``RuntimeConfig.python``,
    Node's ``computePython``) with the request as ``JSON.stringify`` on stdin, ``cwd`` R, the shell off, the
    service's environment plus ``WORKER_ENV`` (two threads, B10), a 180 s timeout and 8 MiB of output. A batch is
    ``local_app_jobs/<key>/<uuid>/`` with ``request.json`` (``{request, identity, key}``, written before the
    spawn) and ``job.json`` (the view with ``events`` and ``stderr``, written when the job ends); a completed or
    ``no_layout`` result, validated and still made by the code of its identity, then becomes the key's
    ``cache.json`` (``{key, request, result, result_sha256, finished_at}``). Bytes, statuses and messages are
    Node's, and the permit of ``execution_slot`` is held from the spawn until the records are written.

    Differences from Node, all deliberate:

    - ``cache.json`` is published once (``RecordStore.publish_cache``, B16): when another workspace has already
      published a valid one for the key, it stays, and this job keeps its own result (its ``job.json`` has it).
    - The slot defaults to one with the installation lock (``R/results/v2/.eeglayoutlab-execution.lock``).
    - Node spawns synchronously; here ``run`` marks the job ``running`` and returns the task that spawns it, so a
      ``cancel`` that comes meanwhile is applied as soon as the worker exists (the job is ``cancelling`` at once,
      as in Node). ``submit`` awaits that task shielded: a cancelled caller never strands an active job.
    - ``finish`` does Node's synchronous part at once and returns the task that writes the records; files are
      written and read in worker threads, as Node's ``fs.promises`` does, so the event loop keeps serving.
    - ``finish_callbacks``: each ``callback(job)`` is called once the job is terminal, its records are written,
      ``active`` is cleared and the permit released. The queue finalizes from it, where Node's polls ``busy()``.
    - ``clock`` (``Date.now()`` in milliseconds), ``random_uuid`` and ``spawn`` (``jobs.worker``'s hook) replace
      the time, the job identifiers and the process for tests, as Node's ``spawnProcess`` does.
    """

    def __init__(self, root: str, python: str, *, timeout_ms: float = TIMEOUT_MS, spawn: Optional[Callable] = None,
                 get_identity: Optional[Callable[[], dict]] = None, get_runtime: Optional[Callable[[], Any]] = None,
                 verify_inputs: Optional[Callable[[Any], None]] = None,
                 execution_slot: Optional[ExecutionSlot] = None, clock: Optional[Callable[[], float]] = None,
                 random_uuid: Optional[Callable[[], str]] = None, token: Optional[str] = None):
        super().__init__(root, python, get_identity=get_identity, get_runtime=get_runtime,
                         verify_inputs=verify_inputs)
        self.execution_slot = execution_slot if execution_slot is not None else ExecutionSlot(
            InstallationLock(self.root))
        self.timeout_ms = timeout_ms
        self.spawn = spawn
        self.clock = clock or _now_ms
        self.random_uuid = random_uuid or (lambda: str(uuid.uuid4()))
        self.jobs: dict[str, RadiusJob] = {}
        self.active: Optional[RadiusJob] = None
        self.submitting = False
        self.disposed = False
        self.token = token if token is not None else secrets.token_hex(32)
        self.local_only: Optional[bool] = None
        self.finish_callbacks: list[Callable[[RadiusJob], Any]] = []

    def _date(self) -> str:
        """``new Date().toISOString()``."""
        return iso_time(self.clock())

    def health(self) -> dict:
        """``health()``: the service part of the four health routes."""
        available = (os.path.exists(nodepath.join(self.root, WORKER_SCRIPT))
                     and os.path.exists(nodepath.join(self.root, BANK_POINTER)))
        return {'available': available, 'local_only': True if self.local_only is None else self.local_only,
                'token': self.token, 'max_concurrent_jobs': 1, 'threads': RADIUS_THREADS,
                'timeout_seconds': self.timeout_ms / 1000, 'supported_masks': list(MASK_CODES),
                'active_job': self.view(self.active) if self.active is not None else None}

    def view(self, job: RadiusJob) -> dict:
        """``view(job)``."""
        result = job.result
        finished = job.finished_at
        return {'id': job.id, 'key': job.key, 'request': job.request, 'status': job.status, 'stage': job.stage,
                'progress': job.progress, 'message': job.message,
                'result': None if result is UNDEFINED else result, 'created_at': job.created_at,
                'finished_at': None if finished is UNDEFINED else finished,
                'cached': False if job.cached is None else job.cached,
                'source': 'local_cache' if job.cached else 'local_compute'}

    def active_pid(self) -> Optional[int]:
        """``active?.child?.pid``: the process-group leader of the running worker."""
        return self.active.pid if self.active is not None else None

    async def _verify(self, result: Any) -> None:
        """``await this.verifyInputs(result)``: hashing the forward inputs runs in a worker thread."""
        await asyncio.to_thread(self.verify_inputs, result)

    async def lookup(self, raw: Any, identity_key: Any = None) -> dict:
        """``await lookup(raw, identityKey)``: ``{'hit': False}``, or ``{'hit': True, 'job': view}`` from a finished
        job of this key or from its ``cache.json`` (a new cached job, as in Node). Never takes the permit. Raises the
        normalizer's ``ValueError``, ``IdentityError`` when the forward inputs of a hit changed, and ``EACCES`` or
        ``EPERM`` reading the record."""
        request = normalize_request(raw)
        key = _key_of(identity_key) if identity_key is not None else self.identity_for(request)[1]
        same = next((job for job in self.jobs.values() if _same(job.key, key) and job.status in DONE), None)
        if same is not None:
            await self._verify(same.result)
            return {'hit': True, 'job': {**self.view(same), 'cached': True, 'source': 'local_cache'}}
        cache = await asyncio.to_thread(self.read_cache, key, request)
        if cache is None:
            return {'hit': False}
        await self._verify(cache['result'])
        job = RadiusJob(self.random_uuid(), key, request, cache['result']['status'], 'cached', 1,
                        '已读取相同模型与配置的已有计算记录', self._date(), result=cache['result'],
                        finished_at=cache.get('finished_at', UNDEFINED), cached=True)
        self.jobs[job.id] = job
        while len(self.jobs) > JOB_LIMIT:
            oldest = next((entry for entry in self.jobs.values() if entry is not self.active), None)
            if oldest is None:
                break
            del self.jobs[oldest.id]
        return {'hit': True, 'job': self.view(job)}

    async def submit(self, raw: Any) -> dict:
        """``await submit(raw)``: ``{'job': view}`` (a hit, the running job of this key, or the new job, spawned),
        ``{'busy': True, 'active_job': view}`` while another key runs, ``{'busy': True, 'maintenance': paused}``
        when the permit is held elsewhere or paused (``execution_slot.contended``: another workspace of this
        installation computes), or ``{'busy': True}`` while another submit is in progress. ``raw`` may also be the
        queue's prepared ``{'request', 'key', 'ctx'}``, whose request is normalized again (Node's adapter passes
        the request). Raises ``RadiusJobError('计算服务正在重启')`` after ``dispose``, the normalizer's
        ``ValueError``, a failed record write, or what the installation lock raises (an ``OSError``, or
        ``createBatch``'s ``RecordError`` for a record tree out of the root)."""
        if self.disposed:
            raise RadiusJobError('计算服务正在重启')
        if isinstance(raw, dict) and {'request', 'key', 'ctx'} <= raw.keys():
            raw = raw['request']
        request = normalize_request(raw)
        if self.submitting:
            return {'busy': True}
        self.submitting = True
        release: Optional[Callable[[], None]] = None
        job: Optional[RadiusJob] = None
        try:
            identity, key = self.identity_for(request)
            # Reading a ready result does not consume compute capacity, even while another job runs.
            stored = await self.lookup(request, {'key': key})
            if stored['hit']:
                return {'job': stored['job']}
            if self.disposed:
                raise RadiusJobError('计算服务正在重启')
            if self.active is not None:
                if _same(self.active.key, key):
                    return {'job': self.view(self.active)}
                return {'busy': True, 'active_job': self.view(self.active)}
            release = self.execution_slot.acquire(self)
            if release is None:
                return {'busy': True, 'maintenance': self.execution_slot.paused}
            cache_path = self.store.path('radius', key, 'cache.json')
            id = self.random_uuid()
            batch = await asyncio.to_thread(self.store.create_batch, 'radius', key, id)
            await asyncio.to_thread(self.store.write, nodepath.join(batch, 'request.json'),
                                    {'request': request, 'identity': identity, 'key': key})
            if self.disposed:
                raise RadiusJobError('计算服务正在重启')
            if self.execution_slot.paused:
                return {'busy': True, 'maintenance': True}
            job = RadiusJob(id, key, request, 'queued', 'queued', 0, '等待计算进程启动', self._date(), result=None)
            job.release_execution, job.batch, job.cache_path, job.identity = release, batch, cache_path, identity
            job.done = asyncio.get_running_loop().create_future()
            self.jobs[id] = job
            self.active = job
            release = None
        finally:
            if release is not None:
                release()
            self.submitting = False
        # Spawn only after the previous process has emitted close, never on cancel request. The spawn goes on if
        # the caller is cancelled meanwhile: the job is active and holds the permit, so it must reach its close.
        await asyncio.shield(self.run(job))
        return {'job': self.view(job)}

    def run(self, job: RadiusJob) -> Awaitable[None]:
        """``run(job)``: the job is ``running`` at once; the returned task spawns the worker and settles once it
        is spawned or the spawn failed (a failed spawn finishes the job: ``无法启动Python：<message>``). The close
        decides the status: the stop reason first (``timeout``; ``failed`` after an input error; ``cancelled``),
        then a validated ``completed``/``no_layout`` result of exit status 0, else ``failed``."""
        if self.disposed:
            self.finish(job, 'cancelled', '服务重启，任务未启动')
            settled = asyncio.get_running_loop().create_future()
            settled.set_result(None)
            return settled
        job.status, job.stage, job.message = 'running', 'starting', '正在加载本地头模与前向矩阵'
        return asyncio.ensure_future(self._start(job))

    async def _start(self, job: RadiusJob) -> None:
        terminal: list[Any] = [None]  # terminalResult

        def on_event(event: dict, _append: Any) -> None:
            kind = event.get('type', UNDEFINED)
            if _same(kind, 'progress') and not job.cancel_reason:
                number = js_number(event.get('progress', UNDEFINED))
                job.progress = max(job.progress, min(0.99, number if js_truthy(number) else 0))
                stage = event.get('stage', UNDEFINED)
                job.stage = _js_string(stage if js_truthy(stage) else 'computing')
                message = event.get('message', UNDEFINED)
                job.message = _js_string(message if js_truthy(message) else '正在计算')
            elif _same(kind, 'result'):
                terminal[0] = event.get('result', UNDEFINED)
            job.events.append(event)

        def on_stop(reason: str) -> None:
            job.cancel_reason, job.status, job.message = reason, 'cancelling', '正在停止计算'

        def on_error(error: WorkerError) -> None:
            job.spawn_error = error.message

        def on_stderr(text: str) -> None:
            job.stderr = text

        try:
            worker = await start_worker(
                self.python, ['-u', nodepath.join(self.root, WORKER_SCRIPT)], cwd=self.root,
                env={**os.environ, **WORKER_ENV}, input=job.request, timeout=self.timeout_ms / 1000,
                max_output_bytes=MAX_OUTPUT_BYTES, on_event=on_event,
                on_log=lambda text: job.events.append({'type': 'log', 'text': text}), on_stderr=on_stderr,
                on_error=on_error, on_stop=on_stop,
                on_close=lambda code, signal: self._closed(job, code, terminal[0]), spawn=self.spawn)
        except Exception as error:  # noqa: BLE001 - Node's catch: any spawn failure fails the job
            self.finish(job, 'failed', f'无法启动Python：{_message(error)}')
            return
        job.worker, job.child = worker, worker.child
        if job.pending_stop is not None:
            worker.stop(job.pending_stop)

    def _closed(self, job: RadiusJob, code: Optional[int], terminal: Any) -> None:
        """``onClose(code)``: the worker and its whole process group have exited."""
        if job.cancel_reason:
            timed = job.cancel_reason == 'timeout'
            status = 'timeout' if timed else 'failed' if job.cancel_reason == 'input_error' else 'cancelled'
            self.finish(job, status, '达到计算时限，任务已停止；未把缺失结果写成0' if timed else '任务已停止')
        elif (code == 0 and js_truthy(terminal)
              and _same_status(_member(terminal, 'status'))):
            try:
                validate_worker_result(terminal, job.request)
                provenance = _member(terminal, 'provenance')
                sources = (UNDEFINED if provenance is None or provenance is UNDEFINED
                           else _member(provenance, 'code_sha256'))
                code_digests = job.identity['code']
                for path, digest in _entries({} if sources is None or sources is UNDEFINED else sources):
                    if not _same(code_digests.get(path, UNDEFINED), digest):
                        raise RadiusResultError('任务排队后科学代码已变化')
            except Exception as error:  # noqa: BLE001 - Node's catch
                self.finish(job, 'failed', f'计算结果校验失败：{_message(error)}')
                return
            job.result = terminal
            status = terminal['status']
            self.finish(job, status, '当前配置已计算' if status == 'completed' else '本次搜索预算内未构造出64点布局')
        else:
            self.finish(job, 'failed', f'Python启动失败：{job.spawn_error}' if job.spawn_error
                        else '计算未成功完成；错误记录已保存，可重新计算')

    def finish(self, job: RadiusJob, status: str, message: str) -> Awaitable[None]:
        """``finish(job, status, message)``: Node's synchronous part (status, stage, message, ``finished_at``,
        progress 1 for a result) happens now; the returned task writes ``job.json`` and, for a result, publishes
        ``cache.json``, then clears ``active``, releases the permit, trims ``jobs`` to 100 and calls the
        ``finish_callbacks``. A failed write makes the job ``failed`` with ``计算记录保存失败：<Node's message>``."""
        job.status, job.stage, job.message = status, status, message
        job.finished_at = self._date()
        job.progress = 1 if status in DONE else job.progress
        # Node builds job.json's value here, before its first await.
        value = {**self.view(job), 'events': job.events, 'stderr': job.stderr}
        return asyncio.ensure_future(self._store(job, status, value))

    def _publish(self, job: RadiusJob) -> Any:
        cache = {'key': job.key, 'request': job.request, 'result': job.result,
                 'result_sha256': jsjson.sha256_hex(job.result), 'finished_at': job.finished_at}
        return self.store.publish_cache('radius', job.key, cache, lambda: self.read_cache(job.key, job.request))

    async def _store(self, job: RadiusJob, status: str, value: dict) -> None:
        try:
            try:
                await asyncio.to_thread(self.store.write, nodepath.join(job.batch, 'job.json'), value)
                if status in DONE:
                    # A valid cache.json another workspace published first stays; this job keeps its own result.
                    await asyncio.to_thread(self._publish, job)
            except Exception as error:  # noqa: BLE001 - Node's catch
                job.status, job.message, job.result = 'failed', f'计算记录保存失败：{node_message(error)}', None
            finally:
                if self.active is job:
                    self.active = None
                release, job.release_execution = job.release_execution, None
                if release is not None:
                    release()
                # Retain a bounded number of job summaries; durable results stay on disk.
                while len(self.jobs) > JOB_LIMIT:
                    del self.jobs[next(iter(self.jobs))]
            for callback in list(self.finish_callbacks):
                try:
                    callback(job)
                except Exception:  # noqa: BLE001 - a callback never breaks the run path
                    _log.exception('radius finish callback failed')
        finally:
            if job.done is not None and not job.done.done():
                job.done.set_result(None)

    def cancel(self, id: Any, reason: str = 'user') -> bool:
        """``cancel(id, reason)``: ``False`` for an unknown or finished job; else the worker gets ``SIGTERM`` (the
        job is ``cancelling`` until its close) and ``True``."""
        job = self.jobs.get(id) if isinstance(id, str) else None
        if job is None or job.status not in RUNNING:
            return False
        if job.cancel_reason:
            return True
        if job.worker is not None:
            job.worker.stop(reason)
        elif job.status == 'running' and job.batch is not None:
            # Still spawning: stopped as soon as the worker exists, cancelling from now on as in Node.
            job.pending_stop = reason
            job.cancel_reason, job.status, job.message = reason, 'cancelling', '正在停止计算'
        return True

    def dispose(self) -> None:
        """``dispose()``: refuses new submits and stops the running worker (``server_restart``)."""
        self.disposed = True
        if self.active is not None:
            self.cancel(self.active.id, 'server_restart')

    async def aclose(self) -> None:
        """``dispose()``, then waits until the active job has finished and written its records (Python: the
        service's shutdown, so no worker outlives it)."""
        self.dispose()
        job = self.active
        if job is not None and job.done is not None:
            await asyncio.shield(job.done)


def _same_status(status: Any) -> bool:
    """``['completed', 'no_layout'].includes(status)``."""
    return isinstance(status, str) and status in DONE
