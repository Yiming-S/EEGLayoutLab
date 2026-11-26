"""Signal reception's run path: Node's ``SourceReceptionService`` (``webapp/server/source-reception-server.mjs``)
with ``assertIndependentNoiseParent``, ``receptionV2Context`` and ``sourceCatalog`` of ``reception-v2-support.mjs`` and
the result validators of ``webapp/contracts/source-reception.mjs``, statement by statement (phase 2 slice 7).

One request format in two versions (``schemas.source_reception``): a request without ``mode`` is v1, one with
``mode`` is v2. Each has its own identity, worker and record tree:

- v1: ``{version: 'source-reception-cache/1', record_id, layout, digests, threads: 2}``, the digests of the reception
  workflow, the bank pointer and its bank, candidates and report, and the two v1 scripts. The worker is
  ``scripts/run_source_reception.py`` under the radius search's interpreter (``RuntimeConfig.python``, Node's
  ``queue.python``) with two threads and the service's timeout (120 s). Records: ``R/results/v2/
  source_reception_jobs/<key>/``, ``cache.json`` ``{key, result, result_sha256, finished_at}``.
- v2: ``{version: 'source-reception-cache/2', forward, code, layout, record_provenance, layout_scope,
  numerical_runtime_sha256, threads: 1}``: ``forward`` is the design-evaluation identity of ``{}`` (slice 1),
  ``code`` the digests of the v2 workflow and scripts (with the atlas files for a ``region_definition``), and
  ``numerical_runtime_sha256`` the inspector's digest (``jobs.runtime_digest``, one memo per service). The worker is
  ``scripts/run_source_reception_v2.py`` under the native interpreter with one thread and at least 600 s. Records:
  ``R/results/v2/source_reception_v2_jobs/<key>/``, ``cache.json`` ``{key, identity, result, result_sha256,
  finished_at}``.

The layout comes from the library record (``Library.get``, or a saved coordinate evaluation for v2), whose bytes
enter the key (B13). Every batch holds ``request.json`` (``{request, record}``, before the spawn), the worker's
``result.json`` (read after its close, at most 24 MiB, checked with the validators and the context computed again)
and ``job.json`` (the view without the result, with ``stderr``).

Differences from Node, all deliberate:

- ``cache.json`` is published once (``RecordStore.publish_cache``, B16): a valid one already there (the lookup's
  checks) stays, and the job completes with its own result in its view; Node replaces it.
- The slot defaults to one with the installation lock (``R/results/v2/.eeglayoutlab-execution.lock``).
- Node spawns synchronously; ``run`` returns the task that spawns the worker, a ``cancel`` meanwhile is applied as
  soon as it exists, and ``submit`` awaits that task shielded (as ``jobs.design``).
- File reads, hashes and validation run in worker threads, identity work under the identity lock of
  ``jobs.kinds``. The memo of verified caches is keyed by ``(inode, size, mtime in ns)`` where Node's is
  ``ino:size:mtimeMs`` (a double of milliseconds: only mtimes within about 0.25 µs can share it).
- ``result.json`` that is not JSON fails with Python's ``SyntaxError`` text after ``结果校验失败：``, not V8's.
- Python hooks: ``finish_callbacks`` (called once a job is terminal and durable), ``aclose()``, ``active_pid()``
  and ``stored_finish()`` (the queue's startup promotion).
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Mapping
import hashlib
import logging
import threading
from typing import Any, Awaitable, Callable, Optional
import uuid

from ..schemas import jsjson
from ..schemas.source_reception import normalize_reception_request, normalize_source_request
from . import nodefs, nodepath
from .design import DesignJobError, _defined, _get, _get_member, _now_ms, _unreadable
from .design_result import _set_size, same
from .editor_records import _finite, _length, _method, _nullish, _opt, _required_length
from .identity import (RECEPTION_V2_WORKFLOW, RECEPTION_WORKFLOW, UNDEFINED, JSTypeError, _js_string, _member,
                       _path, _read_json, _same, design_context, js_truthy, request_key, to_number)
from .integrity import BANK_POINTER, InputIntegrity
from .radius import iso_time
from .reception_records import _hash_json, design_reception_record
from .records import KEY, RecordStore, error_code, node_message, read_file, stat
from .runtime import installed_environment
from .runtime_digest import ProcessRegistry, RuntimeIdentityCache, exec_file, process_env
from .slot import ExecutionSlot, InstallationLock
from .worker import STDERR_LIMIT, WorkerError, _tail, _utf8, start_worker

__all__ = ['ReceptionJobs', 'ReceptionJob', 'ReceptionError', 'ReceptionResultError', 'validate_source_result',
           'validate_reception_result', 'assert_independent_noise_parent', 'V1_SCRIPT', 'V2_SCRIPT', 'TIMEOUT_MS',
           'V2_TIMEOUT_MS', 'MAX_OUTPUT_BYTES', 'RESULT_LIMIT', 'CACHE_LIMIT', 'JOB_LIMIT', 'RUNNING',
           'V1_CACHE_SCHEMA', 'V2_CACHE_SCHEMA', 'V1_CODE', 'V2_CODE', 'ATLAS_CODE']

V1_SCRIPT = 'scripts/run_source_reception.py'
V2_SCRIPT = 'scripts/run_source_reception_v2.py'
V1_CACHE_SCHEMA = 'source-reception-cache/1'
V2_CACHE_SCHEMA = 'source-reception-cache/2'
# The files of each identity beside the workflow lists (source-reception-server.mjs:66, reception-v2-support.mjs:155).
V1_CODE = ('scripts/source_reception.py', 'scripts/run_source_reception.py')
V2_CODE = ('scripts/source_reception.py', 'scripts/run_source_reception.py', 'scripts/source_reception_v2.py',
           'scripts/run_source_reception_v2.py', 'scripts/reception_forward_provider.py',
           'scripts/inspect_reception_runtime.py')
ATLAS_CODE = ('src/compact_eeg/workflows/source_roi.py', 'webapp/public/models/ernie/source-roi.json',
              'webapp/public/models/ernie/source-roi-definition.json')
TIMEOUT_MS = 120000
V2_TIMEOUT_MS = 600000
MAX_OUTPUT_BYTES = 1024 * 1024
RESULT_LIMIT = 24 * 1024 * 1024
CACHE_LIMIT = 32 * 1024 * 1024
JOB_LIMIT = 10
MEMO_LIMIT = 2
RUNNING = ('running', 'cancelling')
CATALOG_TIMEOUT_SECONDS = 30.0
CATALOG_MAX_BUFFER = 1024 * 1024
CATALOG_SCHEMA = 'source-catalog/1'
_THREAD_NAMES = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')
_log = logging.getLogger(__name__)

# Node's messages, verbatim.
V1_LAYOUT = '源实验需要已有完整64点布局；不会将几何预览或历史相交方案当作计算布局'
V2_LAYOUT = '需要完整的已保存布局或已评价坐标'
NOISE = '信号仿真只接受独立噪声协议下的布局'
LEGACY_MULTI = '已有前向库布局使用原多源协议'
BANK_MISMATCH = '前向矩阵校验失败'
CANDIDATE_MISMATCH = '候选坐标校验失败'
RESTARTING = '计算服务正在重启'
CACHE_TOO_LARGE = '结果记录过大'
CACHE_MISMATCH = '结果记录校验失败'
INVALID_SAVED_KEY = 'Invalid saved signal record'
SAVED_MISSING = '计算记录无法读取，请重新提交'
SAVED_LAYOUT = '保存的信号布局坐标或区域标签无效'
RESULT_TOO_LARGE = '结果超过安全大小限制'
IDENTITY_CHANGED = '计算期间模型、源代码或原始布局已变化'
CATALOG_INVALID = '源目录格式无效'
NOT_ITERABLE = 'object is not iterable (cannot read property Symbol(Symbol.iterator))'


class ReceptionError(DesignJobError):
    """A refusal Node throws as a plain ``Error`` in the service (``计算服务正在重启``, ``结果记录校验失败``, the
    contexts' refusals); the message is Node's, verbatim. A ``RadiusJobError``, so the queue and the routes treat it
    as the other run paths' refusals."""


class ReceptionResultError(ValueError):
    """A result the contract's validators refuse; the message is Node's, verbatim."""


# --- Values as V8 reads them --------------------------------------------------------------------------------------

_HUGE = 2 ** 1023  # Python ints below this convert to a finite double


def _all_finite(values: list) -> bool:
    """``values.every(Number.isFinite)`` for a list, with a fast path for plain numbers (8 MB results)."""
    for value in values:
        kind = type(value)
        if kind is float:
            if value - value != 0.0:  # infinite or NaN
                return False
        elif kind is not int or not -_HUGE < value < _HUGE:
            if not _finite(value):
                return False
    return True


def _number(value: Any) -> float:
    return jsjson.to_number(value)


def _scale(value: Any) -> bool:
    """``[0, 0.5, 1, 2, 4].includes(value)`` (SameValueZero)."""
    return jsjson.is_number(value) and _number(value) in (0, 0.5, 1, 2, 4)


def _one_of(value: Any, allowed: tuple) -> bool:
    """``allowed.includes(value)`` for a list of strings."""
    return isinstance(value, str) and value in allowed


def _index(value: Any, index: int) -> Any:
    """``value?.[index]`` of a parsed JSON value."""
    if isinstance(value, list):
        return value[index] if index < len(value) else UNDEFINED
    if isinstance(value, str):
        units = value.encode('utf-16-le', errors='surrogatepass')
        if 2 * index + 2 > len(units):
            return UNDEFINED
        return units[2 * index:2 * index + 2].decode('utf-16-le', errors='surrogatepass')
    if isinstance(value, dict):
        return value.get(str(index), UNDEFINED)
    return UNDEFINED


def _iterated_size(value: Any) -> int:
    """``new Set(value).size`` of a value with a ``length``: an array's items, a string's code points; an object is
    not iterable."""
    if isinstance(value, list):
        return _set_size(value)
    if isinstance(value, str):
        return len(set(value))
    raise JSTypeError(NOT_ITERABLE)


def _hash(value: Any) -> str:
    """``hash(x)`` of source-reception-server.mjs: a string is hashed as it is (UTF-8, a lone surrogate as U+FFFD),
    anything else as ``JSON.stringify`` writes it (``undefined`` cannot be hashed)."""
    if isinstance(value, str):
        return hashlib.sha256(_utf8(value)).hexdigest()
    return _hash_json(value)


# --- webapp/contracts/source-reception.mjs ------------------------------------------------------------------------

_TRACES = ('brain_uv', 'ecg_uv', 'eog_uv', 'noise_uv', 'reconstructed_brain_uv', 'reconstructed_ecg_uv',
           'reconstructed_eog_uv', 'reconstructed_noise_uv')
_TYPES = ('clean', 'ecg', 'eog', 'mixed')
_COMBINATIONS = sorted(['clean:0', *(f'{c}:{_js_string(s)}' for c in ('ecg', 'eog', 'mixed')
                                     for s in (0, 0.5, 1, 2, 4))])


def validate_source_result(result: Any, request: Any, record: Any) -> None:
    """``validateSourceResult(result, request, record)``: raises ``ReceptionResultError`` with Node's message,
    the normalizer's ``ValueError``, or ``JSTypeError`` where V8 throws a ``TypeError``."""
    if (not _same(_opt(result, 'status'), 'completed')
            or not _same(_member(result, 'schema_version'), 'source-reception/1')
            or not same(normalize_source_request(_member(result, 'request')), request)):
        raise ReceptionResultError('源实验结果身份不一致')
    layout = _member(result, 'layout')
    for name in ('xyzMm', 'regionIndices', 'referenceXyzMm'):
        if not same(_opt(layout, name), _member(_member(record, 'layout'), name)):
            raise ReceptionResultError('源实验替换了冻结点位')
    wave = _member(result, 'waveforms')
    n = _length(_opt(wave, 'time_s'))
    if not _same(n, 400):
        raise ReceptionResultError('时间轴无效')
    times = _method(wave['time_s'], 'wave.time_s', 'every')
    if not _all_finite(times) or any(_number(times[i]) <= _number(times[i - 1]) for i in range(1, len(times))):
        raise ReceptionResultError('时间轴无效')
    for side in ('baseline', 'candidate'):
        for key in _TRACES:
            a = _opt(_member(wave, side), key)
            if (not isinstance(a, list) or len(a) != 64
                    or any(not isinstance(row, list) or len(row) != 400 or not _all_finite(row) for row in a)):
                raise ReceptionResultError('64通道波形无效')
    conditions, curve = _member(result, 'conditions'), _member(result, 'strength_curve')
    if (not isinstance(conditions, list) or len(conditions) != 4
            or _set_size([_member(c, 'condition') for c in conditions]) != 4
            or not isinstance(curve, list) or len(curve) != 16):
        raise ReceptionResultError('缺少对照条件')
    points = [f"{_js_string(_member(c, 'condition'))}:{_js_string(_member(c, 'artifact_scale'))}" for c in curve]
    if sorted(points) != _COMBINATIONS:
        raise ReceptionResultError('干扰曲线点重复或缺失')
    scale = _member(request, 'artifact_scale')
    if any(not _same(_member(c, 'artifact_scale'), 0 if _same(_member(c, 'condition'), 'clean') else scale)
           for c in conditions):
        raise ReceptionResultError('条件强度与请求不符')
    for c in [*conditions, *curve]:
        if not _one_of(_member(c, 'condition'), _TYPES) or not _scale(_member(c, 'artifact_scale')):
            raise ReceptionResultError('干扰条件无效')
        for side in ('baseline', 'candidate'):
            m = _member(c, side)
            if not js_truthy(m):
                raise ReceptionResultError('重建指标无效')
            nmse, energy = _member(m, 'nmse'), _member(m, 'explained_energy')
            ratio = _member(m, 'brain_artifact_ratio_db')
            if (not _finite(nmse) or _number(nmse) < 0 or not _finite(energy)
                    or abs(_number(energy) - (1 - _number(nmse))) > 1e-8 or (ratio is not None and not _finite(ratio))):
                raise ReceptionResultError('重建指标无效')
        baseline = _number(_member(_member(c, 'baseline'), 'explained_energy'))
        expected = _number(_member(_member(c, 'candidate'), 'explained_energy')) / baseline if baseline > 1e-8 else None
        retention = _member(c, 'field_retention')
        if (retention is not None if expected is None else
                not _finite(retention) or abs(expected - _number(retention)) > 1e-8 * max(1, abs(expected))):
            raise ReceptionResultError('AR相对保留率无效')
    xyz = _opt(_opt(result, 'source'), 'xyz_mm')
    if not js_truthy(_length(xyz)):
        raise ReceptionResultError('缺少实际源坐标')
    for x in _method(xyz, 'result.source.xyz_mm', 'some'):
        if not _same(_required_length(x), 3) or not _all_finite(_method(x, 'x', 'every')):
            raise ReceptionResultError('缺少实际源坐标')


def validate_reception_result(result: Any, request: Any, record: Any) -> None:
    """``validateReceptionResult(result, request, record)``: a v1 request's result as ``validate_source_result``
    checks it; a v2 result's identity, then its display data as v1's, then the fixed sources of its mode and, with
    a ``region_definition``, their atlas membership."""
    mode = _member(request, 'mode')
    if not js_truthy(mode):
        validate_source_result(result, request, record)
        return
    if (not _same(_opt(result, 'schema_version'), 'source-reception/2')
            or jsjson.stringify(normalize_reception_request(_member(result, 'request'))) != jsjson.stringify(request)):
        raise ReceptionResultError('新源协议结果身份不一致')
    region = _member(request, 'brain_region')
    legacy = normalize_source_request({
        'record_id': _member(request, 'record_id'), 'brain_region': 'frontal' if _nullish(region) else region,
        'waveform': _member(request, 'waveform'), 'artifact_scale': _member(request, 'artifact_scale'),
        'seed': _member(request, 'seed'),
    })
    validate_source_result({**result, 'schema_version': 'source-reception/1', 'request': legacy}, legacy, record)
    single, cross = _same(mode, 'single_source'), _same(mode, 'cross_region')
    n = 1 if single else _required_length(_member(request, 'brain_regions')) if cross else 6
    source, waves = result['source'], result['waveforms']
    normals, nam = _opt(source, 'normals_mri'), _opt(waves, 'source_nam')
    if (not _same(_member(source, 'mode'), mode) or not _same(_length(source['xyz_mm']), n)
            or not _same(_length(normals), n) or not _same(_length(nam), n)
            or any(not isinstance(v, list) or len(v) != 3 or not _all_finite(v) or abs(jsjson.hypot(*v) - 1) > 1e-5
                   for v in _method(normals, 'result.source.normals_mri', 'some'))
            or any(not _same(_required_length(row), 400) or not _all_finite(_method(row, 'row', 'every'))
                   for row in _method(nam, 'result.waveforms.source_nam', 'some'))):
        raise ReceptionResultError('固定源方向或波形记录不完整')
    if single and not _same(_index(_opt(source, 'generation_source_indices'), 0), _member(request, 'source_index')):
        raise ReceptionResultError('返回源与选择源不符')
    if cross:
        generated, bank = _member(source, 'generation_source_indices'), _member(source, 'bank_source_indices')
        if (not same(_member(source, 'source_regions'), _member(request, 'brain_regions'))
                or not _same(_member(source, 'patch_count'), n) or not _same(_length(generated), n)
                or _iterated_size(generated) != n
                or any(not jsjson.is_integer(i) or _number(i) < 0 or _number(i) > 255
                       for i in _method(generated, 'result.source.generation_source_indices', 'some'))
                or not _same(_length(bank), n)
                or any(not _same(i, 4096 + _number(generated[index]))
                       for index, i in enumerate(_method(bank, 'result.source.bank_source_indices', 'some')))):
            raise ReceptionResultError('跨区域源位置记录与选择不一致')
    definition = _member(request, 'region_definition')
    if js_truthy(definition):
        atlas = _member(source, 'atlas_sha256')
        if (not _same(_member(source, 'region_definition'), definition)
                or not _same(_member(_member(result, 'protocol'), 'region_definition'), definition)
                or not KEY.fullmatch(_js_string('' if _nullish(atlas) else atlas))
                or not _same(_length(_opt(source, 'source_regions')), n)
                or not _same(_length(_opt(source, 'source_parcels')), n)
                or (_same(mode, 'multi_source')
                    and any(not _same(r, _member(request, 'brain_region'))
                            for r in _method(source['source_regions'], 'result.source.source_regions', 'some')))):
            raise ReceptionResultError('Atlas source membership is inconsistent')


def assert_independent_noise_parent(record: Any) -> None:
    """``assertIndependentNoiseParent(record)``: signal simulation keeps independent noise; layouts searched under
    another noise model or data prior, and evaluations under another condition, are refused."""
    request = _opt(record, 'request')
    if (js_truthy(_opt(request, 'noise_model')) or js_truthy(_opt(request, 'data_prior'))
            or js_truthy(_opt(record, 'evaluation_condition'))):
        raise ReceptionError(NOISE)


def _valid_xyz(value: Any) -> bool:
    """``validXYZ(coordinates)`` of ``savedResult``: 64 distinct points of three finite numbers."""
    return (isinstance(value, list) and len(value) == 64
            and all(isinstance(point, list) and len(point) == 3 and _all_finite(point) for point in value)
            and len({','.join(_js_string(v) for v in point) for point in value}) == 64)


# --- The service --------------------------------------------------------------------------------------------------

class ReceptionJob:
    """One job of ``SourceReceptionService``: Node's plain object, with its members as attributes.

    A lookup's job has the view's members (``cached`` and the record's ``finished_at``); a computed job also has
    ``ctx``, ``batch``, ``directory`` and the worker's state. ``pending_stop`` (a stop asked for while the worker was
    being spawned) and ``done`` (resolved once ``finish`` has written the records and released the permit) are
    Python's."""

    def __init__(self, id: str, key: Any, request: Any, status: str, progress: Any, message: Any,
                 result: Any = None, *, cached: Any = None, finished_at: Any = None, ctx: Any = None):
        self.id = id
        self.key = key
        self.request = request
        self.ctx = ctx
        self.status = status
        self.progress = progress
        self.message = message
        self.result = result
        self.cached = cached
        self.finished_at = finished_at
        self.release_execution: Optional[Callable[[], None]] = None
        self.batch: Optional[str] = None
        self.directory: Optional[str] = None
        self.stderr = ''
        self.cancel_reason: Optional[str] = None
        self.worker: Any = None
        self.child: Any = None
        self.pending_stop: Optional[str] = None
        self.done: Optional[asyncio.Future] = None

    @property
    def pid(self) -> Optional[int]:
        """``job.child?.pid``."""
        return self.worker.pid if self.worker is not None else None


def _v2(request: Any) -> bool:
    """``request.mode`` of a canonical request."""
    return js_truthy(_get(request, 'mode'))


def _kind(request: Any) -> str:
    return 'sourceV2' if _v2(request) else 'source'


class ReceptionJobs:
    """Node's ``SourceReceptionService`` on one root: lookups of saved reception results, their original downloads
    and one worker run at a time.

    ``root`` is the configured root (``RuntimeConfig.repository_root``), ``python`` the native interpreter
    (``RuntimeConfig.native_python``: v2's worker, inspector, catalog and design identity) and ``compute_python`` the
    radius search's (``RuntimeConfig.python``, Node's ``queue.python``: v1's worker; default ``python``).
    ``library`` has Node's ``get(id)`` (``jobs.library.Library``; plain or a coroutine function). The members follow
    Node's in snake case: ``await context(request)``, ``view(job)``, ``await lookup(raw, context)``, ``await
    saved_result(key, raw)``, ``await verified_cache(path, key)``, ``remember(job)``, ``await submit(raw)``,
    ``run(job)``, ``close(job, code)``, ``finish(job, status, message)``, ``cancel(id, reason)``, ``dispose()`` and
    ``await catalog()`` (``sourceCatalog``, one run at a time as the route shares it), with ``jobs`` (at most 10,
    never dropping the active one), ``active`` and ``submitting``. ``context`` is Node's ``getContext`` (it replaces
    both contexts), ``native_context`` Node's ``nativeContext`` (v2's ``forward``; default slice 1's design context
    of ``{}``) and ``runtime`` the digest memo (``RuntimeIdentityCache``; closed by ``aclose`` when the service made
    it). ``clock`` (``Date.now()``), ``random_uuid`` and ``spawn`` (``jobs.worker``'s hook) replace the time, job
    identifiers and processes for tests.
    """

    def __init__(self, root: str, python: str, library: Any, *, compute_python: Optional[str] = None,
                 spawn: Optional[Callable] = None, timeout_ms: float = TIMEOUT_MS,
                 context: Optional[Callable[[Any], Any]] = None, native_context: Optional[Callable[[Any], Any]] = None,
                 store: Optional[RecordStore] = None, execution_slot: Optional[ExecutionSlot] = None,
                 inputs: Optional[InputIntegrity] = None, runtime: Optional[Callable[..., Awaitable[dict]]] = None,
                 clock: Optional[Callable[[], float]] = None, random_uuid: Optional[Callable[[], str]] = None):
        self.root = nodepath.resolve(root)
        self.python = python
        self.compute_python = compute_python if compute_python is not None else python
        self.library = library
        self.store = store if store is not None else RecordStore(self.root)
        self.execution_slot = execution_slot if execution_slot is not None else ExecutionSlot(
            InstallationLock(self.root))
        self.spawn = spawn
        self.timeout_ms = timeout_ms
        self.context_override = context
        self.native_context = native_context if native_context is not None else self._design_context
        self.inputs = inputs if inputs is not None else InputIntegrity(self.root, installed_environment(self.root))
        self._own_runtime = runtime is None
        self.runtime = runtime if runtime is not None else RuntimeIdentityCache()
        self.jobs: dict[str, ReceptionJob] = {}
        self.active: Optional[ReceptionJob] = None
        self.submitting = False
        self.disposed = False
        self.verified: OrderedDict[str, tuple] = OrderedDict()
        self._verified_lock = threading.Lock()
        self.clock = clock or _now_ms
        self.random_uuid = random_uuid or (lambda: str(uuid.uuid4()))
        self.finish_callbacks: list[Callable[[ReceptionJob], Any]] = []
        self._tasks: set[asyncio.Future] = set()
        self._catalog: Optional[asyncio.Future] = None
        self._processes = ProcessRegistry()

    # --- Contexts -------------------------------------------------------------------------------------------------

    def normalize(self, raw: Any) -> dict:
        """``normalizeReceptionRequest(raw)``: raises ``ValueError`` with Node's message."""
        return normalize_reception_request(raw)

    def _design_context(self, request: Any) -> Any:
        return design_context(self.root, self.python, self.inputs, request)

    async def context(self, request: Any) -> Any:
        """``await context(request)``: ``{record, identity, key}`` (v1 or v2 by ``request.mode``), or what the
        ``context`` override returns. Raises ``ReceptionError`` for Node's refusals, and what reading the record,
        the pointers, the inputs or the runtime digest raises."""
        if self.context_override is not None:
            value = self.context_override(request)
            if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
                value = await value
            return value
        if js_truthy(_member(request, 'mode')):
            return await self._v2_context(request)
        return await self._v1_context(request)

    async def _record(self, id: Any) -> Any:
        """``await queue.library.get(id)``."""
        from .kinds import call  # here: jobs.kinds builds the adapters of the run paths
        return await call(self.library.get, id)

    async def _v1_context(self, request: Any) -> dict:
        from .kinds import call
        record = await self._record(_member(request, 'record_id'))
        if (not js_truthy(_opt(record, 'layout')) or not _same(_member(record, 'status'), 'completed')
                or not _one_of(_member(record, 'dataset_id'), ('cache', 'strict_area'))):
            raise ReceptionError(V1_LAYOUT)
        assert_independent_noise_parent(record)
        return await call(self._v1_identity, request, record)

    def _v1_identity(self, request: Any, record: Any) -> dict:
        pointer = _read_json(self.root, BANK_POINTER)
        paths = [*RECEPTION_WORKFLOW, BANK_POINTER, _member(pointer, 'path'), _member(pointer, 'candidates'),
                 _member(pointer, 'report'), *V1_CODE]
        digests = self.inputs.digest_all([_path(path) for path in paths])
        if not _same(digests[_member(pointer, 'path')], _member(pointer, 'sha256')):
            raise ReceptionError(BANK_MISMATCH)
        report = _read_json(self.root, _member(pointer, 'report'))
        if not _same(_member(report, 'candidate_sha256'), digests[_member(pointer, 'candidates')]):
            raise ReceptionError(CANDIDATE_MISMATCH)
        identity = _defined(('version', V1_CACHE_SCHEMA), ('record_id', _member(record, 'id')),
                            ('layout', _member(record, 'layout')), ('digests', digests), ('threads', 2))
        return {'record': record, 'identity': identity, 'key': request_key(request, identity)}

    async def _v2_context(self, request: Any) -> dict:
        """``receptionV2Context(service, request)``."""
        from .kinds import call
        id = _member(request, 'record_id')
        record = await self._record(id)
        if _nullish(record):
            record = await call(design_reception_record, self.root, id, self.store)
        if (not js_truthy(record) or not _same(_member(record, 'status'), 'completed')
                or not _one_of(_member(record, 'dataset_id'), ('cache', 'strict_area', 'design_evaluation'))):
            raise ReceptionError(V2_LAYOUT)
        assert_independent_noise_parent(record)
        if (_same(_member(request, 'mode'), 'multi_source') and not js_truthy(_member(request, 'region_definition'))
                and not _same(record['dataset_id'], 'design_evaluation')):
            raise ReceptionError(LEGACY_MULTI)
        forward = await call(self.native_context, {})
        if _nullish(forward):
            _member(forward, 'identity')  # V8's TypeError
        names = [*RECEPTION_V2_WORKFLOW, *V2_CODE,
                 *(ATLAS_CODE if js_truthy(_member(request, 'region_definition')) else ())]
        code = await call(self.inputs.digest_all, names)
        # Source-result hits keep the original numerical digest; every call checks the inspector's observations.
        runtime = await self.runtime(self.python, self.root)
        historical = _same(record['dataset_id'], 'cache') and not js_truthy(_member(record, 'compatible'))
        identity = _defined(
            ('version', V2_CACHE_SCHEMA), ('forward', _get(forward, 'identity')), ('code', code),
            ('layout', _member(record, 'layout')), ('record_provenance', _member(record, 'provenance')),
            ('layout_scope', 'historical_frozen_coordinates_not_requalified' if historical
             else 'saved_coordinates_no_new_layout_optimization'),
            ('numerical_runtime_sha256', _get(runtime, 'sha256')), ('threads', 1))
        return {'record': record, 'identity': identity, 'key': request_key(request, identity)}

    # --- Views and stored results ---------------------------------------------------------------------------------

    def view(self, job: ReceptionJob) -> dict:
        """``view(job)``."""
        result, finished = job.result, job.finished_at
        return {'id': job.id, 'key': job.key, 'request': job.request, 'status': job.status,
                'progress': job.progress, 'message': job.message,
                'result': None if _nullish(result) else result, 'cached': js_truthy(job.cached),
                'finished_at': None if _nullish(finished) else finished}

    def remember(self, job: ReceptionJob) -> None:
        """``remember(job)``: keeps at most 10 jobs, dropping the oldest that is not the active one."""
        self.jobs[job.id] = job
        while len(self.jobs) > JOB_LIMIT:
            active = self.active.id if self.active is not None else UNDEFINED
            oldest = next((id for id in self.jobs if id != active), None)
            if oldest is None:
                break
            del self.jobs[oldest]

    def active_pid(self) -> Optional[int]:
        """``active?.child?.pid``: the process-group leader of the running worker."""
        return self.active.pid if self.active is not None else None

    def _verified(self, path: str, key: Any) -> Any:
        """``verifiedCache(path, key)`` (synchronous, for worker threads)."""
        info = stat(path)
        if info.st_size > CACHE_LIMIT:
            raise ReceptionError(CACHE_TOO_LARGE)
        stamp = (info.st_ino, info.st_size, info.st_mtime_ns)
        with self._verified_lock:
            memo = self.verified.get(path)
            if memo is not None and memo[0] == stamp:
                self.verified.move_to_end(path)
                return memo[1]
        cache = self.store.read(path)
        if (not _same(_get_member(cache, 'key'), key)
                or not _same(_get_member(cache, 'result_sha256'), _hash(_get_member(cache, 'result')))):
            raise ReceptionError(CACHE_MISMATCH)
        with self._verified_lock:
            self.verified[path] = (stamp, cache)  # an existing path keeps its place, as Map.set does
            while len(self.verified) > MEMO_LIMIT:
                self.verified.popitem(last=False)
        return cache

    async def verified_cache(self, path: str, key: Any) -> Any:
        """``await verifiedCache(path, key)``: the parsed ``cache.json`` at ``path`` (at most 32 MiB) whose key and
        checksum hold; the last two verified files are kept by their file state, so repeated reads of an 8 MB
        result neither parse nor hash it again. Raises ``ReceptionError`` (``结果记录过大``, ``结果记录校验失败``)
        and what ``stat`` and the read raise."""
        return await asyncio.to_thread(self._verified, path, key)

    def _hit(self, path: str, key: Any, request: Any, record: Any) -> Any:
        cache = self._verified(path, key)
        validate_reception_result(_get_member(cache, 'result'), request, record)
        return cache

    async def lookup(self, raw: Any, context: Any = None) -> dict:
        """``await lookup(raw, context)``: ``{'hit': True, 'job': view}`` of a new cached job (remembered) when the
        key's ``cache.json`` verifies and its result passes the validator for the request and the context's record,
        else ``{'hit': False}``. Never takes the permit. Raises the normalizer's ``ValueError``, a context failure,
        and ``EACCES`` or ``EPERM`` reading the record."""
        request = self.normalize(raw)
        ctx = context if not _nullish(context) else await self.context(request)
        try:
            key = _get(ctx, 'key')
            path = self.store.path(_kind(request), key, 'cache.json')
            cache = await asyncio.to_thread(self._hit, path, key, request, _get(ctx, 'record'))
            job = ReceptionJob(self.random_uuid(), key, request, 'completed', 1, '已读取同一源、布局和干扰条件的已有结果',
                               cache['result'], cached=True, finished_at=cache.get('finished_at', UNDEFINED))
            self.remember(job)
            return {'hit': True, 'job': self.view(job)}
        except Exception as error:  # noqa: BLE001 - Node's catch
            if _unreadable(error):
                raise
            return {'hit': False}

    def _saved(self, key: str, request: dict, cache: Any) -> Any:
        result = _get_member(cache, 'result')
        identity = cache.get('identity', UNDEFINED) if isinstance(cache, dict) else UNDEFINED
        if (not _same(_get_member(cache, 'key'), key)
                or not same(normalize_reception_request(_opt(result, 'request')), request)
                or (_v2(request) and (not js_truthy(_opt(identity, 'layout'))
                                      or request_key(request, identity) != key))):
            raise ReceptionError(CACHE_MISMATCH)
        layout = _member(result, 'layout')
        regions = _opt(layout, 'regionIndices')
        if (not _valid_xyz(_opt(layout, 'xyzMm')) or not _valid_xyz(_opt(layout, 'referenceXyzMm'))
                or not isinstance(regions, list) or len(regions) != 64
                or _set_size(regions) not in (1, 2, 3, 4, 6)
                or any(not jsjson.is_integer(region) or _number(region) < 0 or _number(region) >= _set_size(regions)
                       for region in regions)):
            raise ReceptionError(SAVED_LAYOUT)
        frozen = _opt(identity, 'layout')
        validate_reception_result(result, request, {'layout': layout if _nullish(frozen) else frozen})
        return result

    async def saved_result(self, key: Any, raw: Any) -> Any:
        """``await savedResult(key, raw)``: the stored result of ``key`` for its original download, checked against
        the saved protocol, not today's model identity: the record verifies, its request is ``raw``'s, a v2 record
        re-derives ``key`` from its stored identity (which must hold a layout), its layout is 64 distinct points with
        region labels, and the validator accepts it against the frozen layout. Raises ``ReceptionError`` with Node's
        messages, the normalizer's and validator's errors, and what reading the record raises."""
        if not KEY.fullmatch(_js_string(key)):
            raise ReceptionError(INVALID_SAVED_KEY)
        request = self.normalize(raw)
        path = self.store.path(_kind(request), key, 'cache.json')
        try:
            cache = await self.verified_cache(path, key)
        except Exception as error:  # noqa: BLE001 - Node's catch
            if error_code(error) == 'ENOENT':
                raise ReceptionError(SAVED_MISSING) from None
            raise
        return await asyncio.to_thread(self._saved, key, request, cache)

    async def stored_finish(self, key: Any, request: Any, identity: Any, result: Any) -> Any:
        """Python's startup ``recover()``: the ``finished_at`` of the ``cache.json`` of ``key`` when it passes the
        record checks of Node's ``inspectReceipt`` (scripts/inspect_service_reconciliation.mjs:44-51) for a
        source-reception receipt: it verifies, holds ``result``, the ``identity`` (v2) and ``request`` it names, if
        any, are these, and ``saved_result`` reproduces it; else ``None``. Raises ``EACCES`` and ``EPERM`` reading
        it."""
        try:
            request = self.normalize(request)
            cache = await self.verified_cache(self.store.path(_kind(request), key, 'cache.json'), key)
            stored = cache['result']

            def matches() -> bool:
                return ((stored is result or same(stored, result))
                        and all(name not in cache or same(cache[name], value)
                                for name, value in (('identity', identity), ('request', request))))
            if not await asyncio.to_thread(matches):
                return None
            saved = await self.saved_result(key, request)
            if saved is not stored and not await asyncio.to_thread(same, saved, stored):
                return None
        except Exception as error:  # noqa: BLE001 - any other failure keeps the receipt
            if _unreadable(error):
                raise
            return None
        return cache.get('finished_at')

    # --- Submits and the worker -----------------------------------------------------------------------------------

    def _date(self) -> str:
        """``new Date().toISOString()``."""
        return iso_time(self.clock())

    def _track(self, awaitable: Awaitable[Any]) -> asyncio.Future:
        task = asyncio.ensure_future(awaitable)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def submit(self, raw: Any) -> dict:
        """``await submit(raw)``: ``{'job': view}`` (a hit, the running job of this key, or the new job, spawned),
        ``{'busy': True}`` while another submit is in progress, or ``{'busy': True, 'maintenance': paused}`` when
        the permit is held (another run, or another workspace of this installation) or paused. Raises
        ``ReceptionError('计算服务正在重启')`` after ``dispose``, the normalizer's ``ValueError``, a context failure,
        a failed record write, or what the installation lock raises. Takes the queue's prepared ``{request, key,
        ctx}`` as well, whose request it normalizes again and whose context it computes again."""
        if self.disposed:
            raise ReceptionError(RESTARTING)
        if isinstance(raw, Mapping) and {'request', 'key', 'ctx'} <= raw.keys():
            raw = raw['request']
        request = self.normalize(raw)
        if self.submitting:
            return {'busy': True}
        self.submitting = True
        release: Optional[Callable[[], None]] = None
        try:
            ctx = await self.context(request)
            cached = await self.lookup(request, ctx)
            if cached['hit']:
                return {'job': cached['job']}
            if self.disposed:
                raise ReceptionError(RESTARTING)
            key = _get(ctx, 'key')
            if self.active is not None and _same(self.active.key, key):
                return {'job': self.view(self.active)}
            release = self.execution_slot.acquire(self)
            if release is None:
                return {'busy': True, 'maintenance': self.execution_slot.paused}
            id, kind = self.random_uuid(), _kind(request)
            directory = self.store.path(kind, key)
            batch = await asyncio.to_thread(self.store.create_batch, kind, key, id)
            await asyncio.to_thread(self.store.write, nodepath.join(batch, 'request.json'),
                                    _defined(('request', request), ('record', _get(ctx, 'record'))))
            if self.disposed:
                raise ReceptionError(RESTARTING)
            if self.execution_slot.paused:
                return {'busy': True, 'maintenance': True}
            job = ReceptionJob(id, key, request, 'running', 0, '加载冻结布局与前向矩阵', None, ctx=ctx)
            job.release_execution, job.batch, job.directory = release, batch, directory
            job.done = asyncio.get_running_loop().create_future()
            self.active = job
            release = None
            self.remember(job)
        finally:
            if release is not None:
                release()
            self.submitting = False
        # The spawn goes on if the caller is cancelled meanwhile: the job is active and holds the permit.
        await asyncio.shield(self.run(job))
        return {'job': self.view(job)}

    def run(self, job: ReceptionJob) -> Awaitable[None]:
        """``run(job)``: the returned task spawns the worker and settles once it is spawned or the spawn failed
        (``无法启动计算：<message>``)."""
        if self.disposed:
            self.finish(job, 'cancelled', '服务重启，任务未启动')
            settled = asyncio.get_running_loop().create_future()
            settled.set_result(None)
            return settled
        return self._track(self._start(job))

    async def _start(self, job: ReceptionJob) -> None:
        v2 = _v2(job.request)
        threads = '1' if v2 else '2'
        # Node's {...process.env}: bytes that are not UTF-8 reach the worker as U+FFFD, as the inspector gets them.
        env = {**process_env(), **{name: threads for name in _THREAD_NAMES}, 'PYTHONDONTWRITEBYTECODE': '1'}
        args = ['-u', nodepath.join(self.root, V2_SCRIPT if v2 else V1_SCRIPT), '--repository-root', self.root,
                '--request', nodepath.join(job.batch, 'request.json'),
                '--output', nodepath.join(job.batch, 'result.json')]
        timeout = max(self.timeout_ms, V2_TIMEOUT_MS) if v2 else self.timeout_ms

        def on_event(event: dict, diagnostic: Callable[[str], None]) -> None:
            kind = event.get('type', UNDEFINED)
            if _same(kind, 'progress') and not job.cancel_reason:
                number = to_number(event.get('progress', UNDEFINED))
                job.progress = max(job.progress, min(0.99, number if js_truthy(number) else 0))
                message = event.get('message', UNDEFINED)
                job.message = _js_string('正在计算源—接收对照' if _nullish(message) else message)
            if _same(kind, 'error'):
                message = event.get('message', UNDEFINED)
                diagnostic(_js_string('worker error' if _nullish(message) else message))

        def on_stderr(text: str) -> None:
            job.stderr = text

        def on_error(error: WorkerError) -> None:
            job.stderr = _tail(job.stderr + error.message, STDERR_LIMIT)

        def on_stop(reason: str) -> None:
            job.cancel_reason, job.status, job.message = reason, 'cancelling', '正在停止源实验'

        try:
            worker = await start_worker(
                self.python if v2 else self.compute_python, args, cwd=self.root, env=env, stdin='ignore',
                timeout=timeout / 1000, max_output_bytes=MAX_OUTPUT_BYTES, on_event=on_event, on_stderr=on_stderr,
                on_error=on_error, on_stop=on_stop, on_close=lambda code, signal: self.close(job, code),
                spawn=self.spawn)
        except Exception as error:  # noqa: BLE001 - Node's catch: any spawn failure fails the job
            self.finish(job, 'failed', f'无法启动计算：{node_message(error)}')
            return
        job.worker, job.child = worker, worker.child
        if job.pending_stop is not None:
            worker.stop(job.pending_stop)

    def close(self, job: ReceptionJob, code: Optional[int]) -> Awaitable[None]:
        """``close(job, code)``: the worker and its process group have exited. A stop (``timeout``; ``failed`` after
        an input error; else ``cancelled``) or a non-zero exit decides at once; otherwise the returned task reads
        ``result.json``, validates it, computes the context again and finishes the job."""
        if job.cancel_reason:
            status = ('timeout' if job.cancel_reason == 'timeout' else
                      'failed' if job.cancel_reason == 'input_error' else 'cancelled')
            return self.finish(job, status, '计算已停止；没有缓存未完成结果')
        if code != 0:
            return self.finish(job, 'failed', '源实验未完成；错误记录已保存，没有替换为旧分数')
        return self._track(self._collect(job))

    def _read_result(self, job: ReceptionJob) -> Any:
        path = nodepath.join(job.batch, 'result.json')
        if stat(path).st_size > RESULT_LIMIT:
            raise ReceptionError(RESULT_TOO_LARGE)
        result = jsjson.parse(nodefs.decode(read_file(path)))
        validate_reception_result(result, job.request, _get(job.ctx, 'record'))
        return result

    async def _collect(self, job: ReceptionJob) -> None:
        try:
            result = await asyncio.to_thread(self._read_result, job)
            if not _same(_get(await self.context(job.request), 'key'), job.key):
                raise ReceptionError(IDENTITY_CHANGED)
        except Exception as error:  # noqa: BLE001 - Node's catch
            await self.finish(job, 'failed', f'结果校验失败：{node_message(error)}')
            return
        job.result = result
        await self.finish(job, 'completed', '源—接收对照已计算并保存')

    def finish(self, job: ReceptionJob, status: str, message: str) -> Awaitable[None]:
        """``finish(job, status, message)``: status, message and ``finished_at`` now (``result`` cleared unless
        completed); the returned task publishes ``cache.json`` for a result (progress 1 once it is there), writes
        ``job.json``, clears ``active``, releases the permit and calls the ``finish_callbacks``. A failed write makes
        the job ``failed`` with ``保存失败：<Node's message>``."""
        job.status, job.message, job.finished_at = status, message, self._date()
        if status != 'completed':
            job.result = None
        return self._track(self._store(job, status == 'completed'))

    def _cache(self, job: ReceptionJob) -> dict:
        identity = _get(job.ctx, 'identity') if _v2(job.request) else UNDEFINED
        return _defined(('key', job.key), ('identity', identity), ('result', job.result),
                        ('result_sha256', _hash(job.result)), ('finished_at', job.finished_at))

    def _stored(self, job: ReceptionJob) -> Any:
        """The ``cache.json`` already there when Node's lookup would take it for this job, else ``None``."""
        try:
            return self._hit(self.store.path(_kind(job.request), job.key, 'cache.json'), job.key, job.request,
                             _get(job.ctx, 'record'))
        except Exception as error:  # noqa: BLE001 - as Node's lookup: anything else is not a hit
            if _unreadable(error):
                raise
            return None

    async def _store(self, job: ReceptionJob, completed: bool) -> None:
        try:
            try:
                if completed:
                    cache = await asyncio.to_thread(self._cache, job)
                    # A valid cache.json another workspace published first stays; this job keeps its own result.
                    await asyncio.to_thread(self.store.publish_cache, _kind(job.request), job.key, cache,
                                            lambda: self._stored(job))
                    job.progress = 1
                value = {name: item for name, item in self.view(job).items() if name != 'result'}
                value['stderr'] = job.stderr
                await asyncio.to_thread(self.store.write, nodepath.join(job.batch, 'job.json'), value)
            except Exception as error:  # noqa: BLE001 - Node's catch
                job.status, job.result, job.message = 'failed', None, f'保存失败：{node_message(error)}'
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
                    _log.exception('reception finish callback failed')
        finally:
            if job.done is not None and not job.done.done():
                job.done.set_result(None)

    # --- Stops ----------------------------------------------------------------------------------------------------

    def cancel(self, id: Any, reason: str = 'user') -> bool:
        """``cancel(id, reason)``: ``False`` for an unknown or finished job; else ``True``, and the worker of a
        running job that is not stopping yet gets ``SIGTERM`` (the job is ``cancelling`` until its close)."""
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
            job.cancel_reason, job.status, job.message = reason, 'cancelling', '正在停止源实验'
        return True

    def dispose(self) -> None:
        """``dispose()``: refuses new submits and stops the running worker (``restart``)."""
        self.disposed = True
        if self.active is not None:
            self.cancel(self.active.id, 'restart')

    async def aclose(self) -> None:
        """``dispose()``, then waits until the active job has finished and written its records, and stops the
        runtime inspectors and catalog runs still going, and any spawned after it (Python: the service's shutdown)."""
        self.dispose()
        job = self.active
        if job is not None and job.done is not None:
            await asyncio.shield(job.done)
        self._processes.close()
        if self._own_runtime and isinstance(self.runtime, RuntimeIdentityCache):
            self.runtime.close()

    # --- The catalog ----------------------------------------------------------------------------------------------

    def _source_catalog(self) -> Any:
        """``sourceCatalog(service)``: the v2 worker's ``--catalog`` under the native interpreter (30 s, 1 MiB)."""
        stdout = exec_file(self.python, ['-u', nodepath.join(self.root, V2_SCRIPT), '--repository-root', self.root,
                                         '--catalog'],
                           cwd=self.root, env={**process_env(), 'PYTHONDONTWRITEBYTECODE': '1',
                                               **{name: '1' for name in _THREAD_NAMES}},
                           timeout=CATALOG_TIMEOUT_SECONDS, max_buffer=CATALOG_MAX_BUFFER, processes=self._processes)
        catalog = jsjson.parse(stdout)
        if (not _same(_member(catalog, 'schema_version'), CATALOG_SCHEMA)
                or not _same(_length(_opt(catalog, 'sources')), 256)):
            raise ReceptionError(CATALOG_INVALID)
        return catalog

    async def catalog(self) -> Any:
        """``await sourceCatalog(service)``, one run at a time: callers while it runs share it (the route's
        ``catalogPromise``). Raises ``ReceptionError('源目录格式无效')``, ``runtime_digest.InspectorError``
        (``Command failed: ...``), ``MaxBufferError``, ``WorkerError`` (spawn) or ``jsjson.JSONSyntaxError``."""
        if self._catalog is None:
            task = asyncio.ensure_future(asyncio.to_thread(self._source_catalog))

            def clear(done: asyncio.Future) -> None:
                if self._catalog is done:
                    self._catalog = None
            task.add_done_callback(clear)
            self._catalog = task
        return await asyncio.shield(self._catalog)
