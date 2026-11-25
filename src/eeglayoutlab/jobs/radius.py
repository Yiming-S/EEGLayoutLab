"""The radius search's identity and stored results: Node's ``local-compute-server.mjs``, statement by statement.

- ``validate_worker_result`` is ``validateWorkerResult`` (line 65): a result is accepted only for the request it
  was computed for, with 64 distinct points at least 4 mm apart, balanced regions, the geometry of the request and
  a consistent minimum of the three retention scores.
- ``code_identity`` is ``codeIdentity`` (99-109): the raw bytes of the radius worker, its configuration, the bank and
  surface-mask pointers and every top-level ``src/compact_eeg/*.py`` (sorted by UTF-16 code units), read at
  ``nodepath.join(root, path)`` without a containment check, links followed (plan B8: unlike the design inputs).
- ``RadiusCache`` is the read side of ``LocalComputeQueue``: ``identity_for`` (148-155, the key format of every
  radius record), ``read_cache`` (157-170) and the input check of a cache hit (``InputIntegrity.verify``).

The request format itself is ``eeglayoutlab.schemas.radius_search.normalize_request`` (``normalizeRequest``).
The runtime member comes from ``runtime_identity`` of the compute interpreter (``RuntimeConfig.python``, Node's
``computePython``), never from the native one; it is ``None`` on macOS, so identities there have no ``runtime``.
"""
from __future__ import annotations

import errno
import hashlib
import math
from typing import Any, Callable, Optional

from ..schemas import jsjson
from ..schemas.radius_search import MASK_CODES, normalize_request
from . import nodepath
from .fingerprint import runtime_identity
from .identity import DATA_PRIOR_FILES, UNDEFINED, _member, _same, js_truthy, request_key
from .integrity import ADMISSION_POINTER, BANK_POINTER, InputIntegrity
from .records import RecordStore, read_file, scandir

__all__ = ['MASK_CODES', 'RADIUS_IDENTITY_VERSION', 'RADIUS_THREADS', 'RadiusResultError', 'validate_worker_result',
           'code_identity', 'radius_identity', 'RadiusCache', 'normalize_request']

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
