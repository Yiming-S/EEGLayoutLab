"""Stored design-evaluation results: ``validateDesignResult`` and ``validRobustness`` of Node's
``design-evaluation-server.mjs`` (lines 100-255), statement by statement.

A result is accepted only for the canonical request it was computed for (``same``: equal ``JSON.stringify`` text),
with the forward mode of its head, consistent nominal metrics, evaluated coordinates within 2 mm of the requested
ones and at least 4 mm apart, the trials of its action and, exactly when requested, a well-formed robustness
block. ``normalize_design_request`` is the phase 1 schema (``eeglayoutlab.schemas.design_evaluation``), which
decides acceptance and builds the canonical request. A request it refuses raises ``DesignResultError`` with the
message ``node_refusal`` finds: Node's checks of ``normalizeDesignRequest`` and the option normalizers of
``scientific-options.mjs`` in Node's order, so a stored record with a value Node no longer accepts (an option
retired after it was saved, or an edit with its checksum recomputed) gives Node's library warning.
"""
from __future__ import annotations

import math
import re
from typing import Any, Optional

from ..schemas import jsjson
from .identity import UNDEFINED, JSTypeError, _member, _same, js_truthy, to_number

__all__ = ['DesignResultError', 'ROBUSTNESS_LEVELS', 'FORWARD_MODES', 'normalize_design_request', 'node_refusal',
           'same', 'validate_design_result', 'valid_robustness']

# webapp/contracts/scientific-options.mjs
ROBUSTNESS_LEVELS = {'dropout': (2, 4, 8), 'impedance': (0.5, 1.0), 'replacement': (5, 10)}
FORWARD_MODES = ('cached_fem', 'direct_fem', 'scalp_node_table')
_FIELD_ERROR = '设计评价字段错误'
_REQUIRED = ('action', 'design', 'radius_mm', 'seed')
_FIELDS = (*_REQUIRED, 'noise_model', 'conductivity_scenario', 'head_id', 'robustness', 'data_prior')
_SPATIAL_LENGTHS_MM = (10, 20, 40)
_SCENARIOS = ('skull_x0.5', 'skull_x2')
_HEAD_ID = re.compile('[a-z0-9]+(?:[_-][a-z0-9]+)*')
_PRIOR_LENGTHS_MM = (5, 10, 15, 20, 30, 40)


class DesignResultError(ValueError):
    """A stored design result Node refuses; the message is Node's, verbatim."""


def normalize_design_request(raw: Any) -> dict:
    """``normalizeDesignRequest(raw)`` through the phase 1 schema; raises ``DesignResultError`` with Node's
    message."""
    from ..schemas.design_evaluation import normalize_design_request as normalize  # Pydantic: the service extra
    try:
        return normalize(raw)
    except ValueError as error:
        raise DesignResultError(node_refusal(raw) or _schema_message(error)) from None


# --- normalizeDesignRequest's refusals --------------------------------------------------------------------------

def _absent(value: Any) -> bool:
    """``value === undefined || value === null``."""
    return value is None or value is UNDEFINED


def _empty_string(value: Any) -> bool:
    return isinstance(value, str) and value == ''


def _sorted_keys(value: dict) -> str:
    """``Object.keys(value).sort().join(',')``: UTF-16 code-unit order."""
    return ','.join(sorted(value, key=lambda key: key.encode('utf-16-be', errors='surrogatepass')))


def _number_in(value: Any, allowed: tuple) -> bool:
    """``allowed.includes(value)`` for a list of numbers (``true`` is not 1)."""
    return jsjson.is_number(value) and jsjson.to_number(value) in allowed


def _units(value: str) -> int:
    return len(value.encode('utf-16-le', errors='surrogatepass')) // 2


def _four_digits(value: Any) -> bool:
    """``fourDigits``: a finite number in [1e-3, 1e3] with at most 4 significant digits."""
    if not jsjson.is_number(value):
        return False
    number = jsjson.to_number(value)
    return 1e-3 <= number <= 1e3 and jsjson.equals_to_precision(number, 4)


def _noise_model(value: Any) -> Any:
    """``normalizeNoiseModel(value)``: a truthy model, or ``None`` for independent noise."""
    if _absent(value):
        return None
    if not isinstance(value, dict):
        raise DesignResultError('噪声模型格式无效')
    # The joined key text is also 'kind,length_mm,rho' for the keys 'kind' and 'length_mm,rho': members are read
    # as Node reads them, absent ones undefined.
    keys, kind = _sorted_keys(value), value.get('kind', UNDEFINED)
    if _same(kind, 'iid') and keys == 'kind':
        return None
    if (_same(kind, 'spatial') and keys == 'kind,length_mm,rho' and _same(value.get('rho', UNDEFINED), 0.5)
            and _number_in(value.get('length_mm', UNDEFINED), _SPATIAL_LENGTHS_MM)):
        return value
    if (_same(kind, 'brain_background') and keys == 'fraction,kind'
            and _same(value.get('fraction', UNDEFINED), 0.5)):
        return value
    raise DesignResultError('不支持的噪声模型')


def _scenario(value: Any, action: Any) -> Any:
    """``normalizeConductivityScenario(value, action)``."""
    if _absent(value) or _empty_string(value):
        return None
    if not isinstance(value, str) or value not in _SCENARIOS:
        raise DesignResultError('不支持的电导率情景')
    if not _same(action, 'evaluate'):
        raise DesignResultError('电导率情景只用于坐标评价，不用于网格偏移')
    return value


def _head(value: Any, action: Any, scenario: Any) -> Any:
    """``normalizeHeadId(value, action, scenario)``."""
    if _absent(value) or _empty_string(value):
        return None
    if not isinstance(value, str) or _units(value) > 40 or not _HEAD_ID.fullmatch(value):
        raise DesignResultError('头模编号无效')
    if not _same(action, 'evaluate'):
        raise DesignResultError('其他头模只用于坐标评价，不用于网格偏移')
    if scenario:
        raise DesignResultError('电导率情景只定义在Ernie头模上')
    return value


def _robustness(value: Any, action: Any, scenario: Any, head: Any) -> None:
    """``normalizeRobustness(value, action, scenario, head)``."""
    if _absent(value) or _empty_string(value) or value is False:
        return
    if not _same(value, 'standard/1'):
        raise DesignResultError('不支持的稳健性协议')
    if not _same(action, 'evaluate'):
        raise DesignResultError('稳健性评价只用于坐标评价，不用于网格偏移')
    if scenario or head:
        raise DesignResultError('稳健性评价只定义在Ernie名义头模上，不与电导率情景或其他头模同时使用')


def _data_prior(value: Any, noise_model: Any, head: Any) -> None:
    """``normalizeDataPrior(value, {noiseModel, head})``."""
    if _absent(value):
        return
    if not isinstance(value, dict) or _sorted_keys(value) != 'length_mm,region_gain,rho':
        raise DesignResultError('数据先验格式无效')
    # The joined names also match {"length_mm,region_gain": ..., "rho": ...}, which has no region_gain.
    gains, rho, length = (value.get(key, UNDEFINED) for key in ('region_gain', 'rho', 'length_mm'))
    if not isinstance(gains, list) or len(gains) != 7 or not all(_four_digits(gain) for gain in gains):
        raise DesignResultError('数据先验的区域增益须为7个保留4位有效数字的正数')
    if not jsjson.is_number(rho):
        raise DesignResultError('数据先验的噪声相关比例无效')
    rho = jsjson.to_number(rho)
    if not 0 <= rho <= 0.95 or jsjson.round_half_up(rho * 100) / 100 != rho:
        raise DesignResultError('数据先验的噪声相关比例无效')
    if (length is not None) if rho == 0 else not _number_in(length, _PRIOR_LENGTHS_MM):
        raise DesignResultError('数据先验的噪声相关长度无效')
    if noise_model:
        raise DesignResultError('数据先验已包含噪声结构，不能同时选择噪声模型')
    if head:
        raise DesignResultError('数据先验只定义在Ernie头模上')


def _set_size(values: list) -> int:
    """``new Set(values).size`` (SameValueZero: ``-0`` is ``0``, ``NaN`` is itself, objects by identity)."""
    seen = set()
    for value in values:
        if isinstance(value, bool):
            item: Any = ('boolean', value)
        elif jsjson.is_number(value):
            number = jsjson.to_number(value)
            item = ('number', 'NaN' if math.isnan(number) else number)
        elif isinstance(value, str):
            item = ('string', value)
        elif value is None:
            item = ('null',)
        else:
            item = ('object', id(value))
        seen.add(item)
    return len(seen)


def _coordinate(value: Any) -> bool:
    """``Number.isFinite(v) && !(Math.abs(v) > 500)``."""
    return _finite(value) and not abs(jsjson.to_number(value)) > 500


def node_refusal(x: Any) -> Optional[str]:
    """The message ``normalizeDesignRequest(x)`` throws, or ``None`` when Node accepts ``x``: the field check, the
    option normalizers (noise model, conductivity scenario, head, robustness, data prior), the design, its
    coordinates, region labels, numbering, balance and spacing, then action, radius and seed, in Node's order."""
    try:
        _refuse(x)
    except DesignResultError as error:
        return str(error)
    return None


def _refuse(x: Any) -> None:
    if (not isinstance(x, dict) or any(key not in x for key in _REQUIRED)
            or any(key not in _FIELDS for key in x)):
        raise DesignResultError(_FIELD_ERROR)
    action = x['action']
    noise_model = _noise_model(x.get('noise_model', UNDEFINED))
    scenario = _scenario(x.get('conductivity_scenario', UNDEFINED), action)
    head = _head(x.get('head_id', UNDEFINED), action, scenario)
    _robustness(x.get('robustness', UNDEFINED), action, scenario, head)
    _data_prior(x.get('data_prior', UNDEFINED), noise_model, head)
    d = x['design']
    if (not isinstance(d, dict) or not _same(d.get('schema', UNDEFINED), 'eeg-electrode-design/1')
            or not _same(d.get('coordinate_system', UNDEFINED), 'ernie_native_mm')
            or not _same(d.get('unit', UNDEFINED), 'mm')):
        raise DesignResultError('需要已配准的Ernie原生毫米坐标')
    xyz = d.get('xyz_mm', UNDEFINED)
    if (not isinstance(xyz, list) or len(xyz) != 64
            or any(not isinstance(p, list) or len(p) != 3 or not all(_coordinate(v) for v in p) for p in xyz)
            or len({_joined(p) for p in xyz}) != 64):
        raise DesignResultError('需要64个互异的有限坐标')
    regions = d.get('region_indices', UNDEFINED)
    if not isinstance(regions, list) or len(regions) != 64:
        raise DesignResultError('需要64个区域标签')
    r = _set_size(regions)
    if r not in (1, 2, 3, 4, 6) or any(not jsjson.is_integer(v) or v < 0 or v >= r for v in regions):
        raise DesignResultError('区域编号错误')
    counts = sorted((sum(1 for v in regions if v == i) for i in range(r)), reverse=True)
    if any(n != 64 // r + int(i < 64 % r) for i, n in enumerate(counts)):
        raise DesignResultError('区域分配须均衡，总数64')
    points = [[jsjson.to_number(v) for v in p] for p in xyz]
    for i in range(64):
        for j in range(i + 1, 64):
            if _gap(points[i], points[j]) < 4 - 1e-7:
                raise DesignResultError('最小直线点距需达到4 mm')
    seed = x['seed']
    if (not (isinstance(action, str) and action in ('evaluate', 'perturb'))
            or not _number_in(x['radius_mm'], (3, 6, 10)) or not jsjson.is_integer(seed) or seed < 0 or seed > 9999):
        raise DesignResultError('计算动作、偏移或种子无效')


def _schema_message(error: ValueError) -> str:
    errors = getattr(error, 'errors', None)
    if callable(errors):
        for item in errors():
            cause = (item.get('ctx') or {}).get('error')
            text = str(cause) if cause is not None else ''
            # The model validators raise Node's messages; field rules have none, so they get the first check's.
            if text and not text.isascii():
                return text
    return _FIELD_ERROR


def same(a: Any, b: Any) -> bool:
    """``JSON.stringify(a) === JSON.stringify(b)``; ``undefined`` stringifies to ``undefined``."""
    if a is UNDEFINED or b is UNDEFINED:
        return a is b
    return jsjson.stringify(a) == jsjson.stringify(b)


def _finite(value: Any) -> bool:
    """``Number.isFinite(value)``."""
    return jsjson.is_number(value) and math.isfinite(jsjson.to_number(value))


def _points(value: Any) -> bool:
    return (isinstance(value, list) and len(value) == 64
            and all(isinstance(p, list) and len(p) == 3 and all(_finite(v) for v in p) for p in value))


def _gap(a: list, b: list) -> float:
    """``Math.hypot(...a.map((v, k) => v - b[k]))``."""
    return jsjson.hypot(*(v - b[k] for k, v in enumerate(a)))


def _minimum(points: list) -> float:
    """The smallest distance between two of the points (``Math.min`` of none is ``Infinity``)."""
    return min((_gap(p, q) for i, p in enumerate(points) for q in points[i + 1:]), default=math.inf)


def _joined(point: list) -> str:
    return ','.join(jsjson.number_to_string(jsjson.to_number(v)) for v in point)


def _items(value: Any, name: str) -> list:
    """``value`` as an array whose methods Node calls; V8's ``TypeError`` otherwise."""
    if not isinstance(value, list):
        raise JSTypeError(f'{name} is not a function')
    return value


def validate_design_result(r: Any, request: dict, admission: Any = UNDEFINED) -> None:
    """``validateDesignResult(r, request, admission)``; ``request`` is the canonical request. Raises
    ``DesignResultError`` with Node's message (or ``JSTypeError`` where V8 throws)."""
    provenance = UNDEFINED if r is None or r is UNDEFINED else _member(r, 'provenance')
    if js_truthy(admission):
        def recorded(key: str) -> Any:
            return UNDEFINED if provenance is None or provenance is UNDEFINED else _member(provenance, key)
        if (not _same(recorded('surface_admissibility_sha256'), _member(admission, 'sha256'))
                or not _same(recorded('surface_admissibility_version'), _member(admission, 'schema_version'))):
            raise DesignResultError('设计评价表面筛选身份不匹配')
    schema = UNDEFINED if r is None or r is UNDEFINED else _member(r, 'schema')
    if (not _same(schema, 'design-evaluation/1') or not _same(_member(r, 'status'), 'completed')
            or not same(_member(r, 'request'), request)
            # A head result always uses its own table mode; an Ernie result never may.
            or (not _same(_member(r, 'forward_mode'), 'head_scalp_node_table') if js_truthy(request.get('head_id'))
                else _member(r, 'forward_mode') not in FORWARD_MODES)):
        raise DesignResultError('设计评价结果身份错误')
    nominal = _member(r, 'nominal')
    if (not js_truthy(nominal) or not _finite(_member(nominal, 'field_relative'))
            or not _finite(_member(nominal, 'median_mm')) or not _finite(_member(nominal, 'reference_median_mm'))):
        raise DesignResultError('评价指标无效')
    for key in ('field_absolute', 'reference_field_absolute', 'p90_mm', 'reference_p90_mm'):
        if not _finite(_member(nominal, key)):
            raise DesignResultError('缺少绝对指标或误差分位数')
    for key in ('sensitivity_tail', 'localization_relative'):
        value = _member(nominal, key)
        if value is not None and not _finite(value):
            raise DesignResultError('无效相对指标')
    n = nominal
    if (n['median_mm'] < 0 or n['p90_mm'] < n['median_mm'] or n['reference_median_mm'] < 0
            or n['reference_p90_mm'] < n['reference_median_mm'] or n['reference_field_absolute'] <= 0
            or abs(n['field_relative'] - n['field_absolute'] / n['reference_field_absolute']) > 1e-8):
        raise DesignResultError('绝对指标与相对指标不一致')
    design_xyz = request['design']['xyz_mm']
    projection, evaluated = _member(r, 'projection_max_mm'), _member(r, 'evaluated_xyz_mm')
    if (not _finite(projection) or projection < 0 or projection > 2 + 1e-7 or not isinstance(evaluated, list)
            or len(evaluated) != 64
            or any(not isinstance(p, list) or len(p) != 3 or not all(_finite(v) for v in p)
                   or _gap(p, design_xyz[i]) > 2 + 1e-7 for i, p in enumerate(evaluated))):
        raise DesignResultError('结果投影坐标无效')
    if _minimum(evaluated) < 4 - 1e-7:
        raise DesignResultError('实际评价坐标点距不足')
    adjustment = max(_gap(p, design_xyz[i]) for i, p in enumerate(evaluated))
    if abs(adjustment - projection) > 1e-7:
        raise DesignResultError('投影距离与实际坐标不一致')
    trials = _member(r, 'trials')
    if not isinstance(trials, list) or len(trials) != (4 if request['action'] == 'perturb' else 0):
        raise DesignResultError('偏移试验不完整')
    for i, t in enumerate(trials):
        _check_trial(i, t, r, request)
    robustness = _member(r, 'robustness')
    if not valid_robustness(robustness) if js_truthy(request.get('robustness')) else robustness is not UNDEFINED:
        raise DesignResultError('稳健性结果无效')


def _check_trial(i: int, t: Any, r: dict, request: dict) -> None:
    design = request['design']
    provenance = _member(r, 'provenance')
    count = UNDEFINED if provenance is None or provenance is UNDEFINED else _member(provenance, 'candidate_count')
    xyz, indices = _member(t, 'xyz_mm'), None
    if (not _points(xyz) or not _points(_member(t, 'requested_xyz_mm'))
            or len({_joined(p) for p in xyz}) != 64 or not jsjson.is_integer(count)
            or not isinstance(indices := _member(t, 'candidate_bank_indices'), list) or len(indices) != 64
            or not _distinct(indices) or any(not jsjson.is_integer(v) or v < 0 or v >= count for v in indices)
            or not same(_member(t, 'region_indices'), design['region_indices'])):
        raise DesignResultError('偏移坐标或区域标签无效')
    moved = [_gap(p, design['xyz_mm'][k]) for k, p in enumerate(xyz)]
    requested = t['requested_xyz_mm']
    target_error = max(_gap(p, requested[k]) for k, p in enumerate(xyz))
    unchanged = sum(1 for v in moved if v <= 1e-7) / 64
    total = 0.0
    for v in moved:  # Array.prototype.reduce adds in order; Python 3.12's sum() compensates
        total += v
    chord, actual_max, actual_mean = (_member(t, 'minimum_chord_distance_mm'), _member(t, 'actual_max_mm'),
                                      _member(t, 'actual_mean_mm'))
    target, fraction = _member(t, 'target_error_max_mm'), _member(t, 'unchanged_fraction')
    if (not _finite(chord) or abs(_minimum(xyz) - chord) > 1e-7 or not _close(max(moved), actual_max, 1e-7)
            or not _finite(actual_mean) or abs(total / 64 - actual_mean) > 1e-7
            or not _finite(target) or abs(target_error - target) > 1e-7 or not _close(unchanged, fraction, 1e-10)):
        raise DesignResultError('偏移几何量与坐标不一致')
    if (not _same(_member(t, 'index'), i) or _member(t, 'status') not in ('completed', 'geometry_rejected')
            or not _finite(actual_max) or actual_max < 0 or actual_max > request['radius_mm'] + 1e-7
            or not _finite(fraction) or fraction < 0 or fraction > 1):
        raise DesignResultError('偏移结果无效')
    field, fixed = _member(t, 'field_relative'), _member(t, 'fixed_estimator_field_relative')
    if t['status'] == 'completed' and (not _finite(field) or not _finite(fixed) or chord < 4 - 1e-7):
        raise DesignResultError('偏移评分或点距无效')
    if t['status'] != 'completed' and (field is not None or fixed is not None):
        raise DesignResultError('几何失败不能携带评分')


def _close(a: float, b: Any, tolerance: float) -> bool:
    """``!(Math.abs(a - b) > tolerance)`` for a number ``a``: the subtraction converts ``b`` with ``ToNumber``
    (``identity.to_number``: ``null`` is 0, a string or an array goes through StringToNumber, another object is
    NaN, whose difference is never greater, or V8's ``TypeError`` with its own ``toString``)."""
    return not abs(a - to_number(b)) > tolerance


def _distinct(values: list) -> bool:
    """``new Set(values).size === values.length`` (SameValueZero: ``1`` and ``true`` differ, objects by identity)."""
    seen = set()
    for value in values:
        if isinstance(value, (dict, list)):
            item: Any = ('object', id(value))
        elif isinstance(value, bool):
            item = ('boolean', value)
        elif jsjson.is_number(value):
            item = ('number', jsjson.to_number(value))
        else:
            item = (type(value).__name__, value)
        if item in seen:
            return False
        seen.add(item)
    return True


# --- Robustness --------------------------------------------------------------------------------------------------

def _score(value: Any) -> bool:
    return _finite(value) and 0 <= value <= 2


def _summary(value: Any, count: int) -> bool:
    """``summary(value, count)``: median, p10 and minimum in order, with a count of 1..count."""
    if not isinstance(value, dict):
        return False
    if not all(_score(value.get(key, UNDEFINED)) for key in ('median', 'p10', 'minimum')):
        return False
    number = value.get('count', UNDEFINED)
    return (value['minimum'] <= value['p10'] + 1e-12 and value['p10'] <= value['median'] + 1e-12
            and jsjson.is_integer(number) and 1 <= number <= count)


def _levels(items: Any, key: str, values: tuple, count: int) -> bool:
    return (isinstance(items, list) and len(items) == len(values)
            and all(_same(_member(level, key), values[i]) and _same(_member(level, 'draws'), count)
                    and _summary(_member(level, 'candidate'), count) and _summary(_member(level, 'reference'), count)
                    for i, level in enumerate(items)))


def valid_robustness(b: Any) -> bool:
    """``validRobustness(b)``: the structure and ranges of a robustness block (the numbers come from the worker)."""
    if not js_truthy(b) or not _same(_member(b, 'protocol'), 'standard/1') or not _same(_member(b, 'snr_db'), 20):
        return False
    dropout = _member(b, 'dropout')
    if not js_truthy(dropout):
        return False
    single = _member(dropout, 'single')
    candidate = UNDEFINED if single is None or single is UNDEFINED else _member(single, 'candidate')
    if (not isinstance(candidate, list) or len(candidate) != 64 or not all(_score(v) for v in candidate)
            or not _summary(_member(single, 'reference'), 64)):
        return False
    if (not _levels(_member(dropout, 'random'), 'removed', ROBUSTNESS_LEVELS['dropout'], 32)
            or not _levels(_member(b, 'impedance'), 'log_sd', ROBUSTNESS_LEVELS['impedance'], 32)):
        return False
    p = _member(b, 'replacement')
    status = UNDEFINED if p is None or p is UNDEFINED else _member(p, 'status')
    if _same(status, 'unavailable'):
        return isinstance(_member(p, 'reason'), str) and _key_count(p) == 2
    centre, levels = (UNDEFINED, UNDEFINED) if not _same(status, 'completed') else (_member(p, 'centre_mm'),
                                                                                     _member(p, 'levels'))
    if (not _same(status, 'completed') or not isinstance(centre, list) or len(centre) != 3
            or not all(_finite(v) for v in centre) or not _same(_member(p, 'jitter_mm'), 2)
            or not isinstance(_member(p, 'table_id'), str) or not isinstance(levels, list)
            or len(levels) != len(ROBUSTNESS_LEVELS['replacement'])):
        return False
    return all(_same(_member(level, 'rms_mm'), ROBUSTNESS_LEVELS['replacement'][i])
               and _same(_member(level, 'trials'), 16) and _finite(_member(level, 'rotation_deg'))
               and all(_replacement_side(_member(level, name)) for name in ('candidate', 'reference'))
               for i, level in enumerate(levels))


def _replacement_side(o: Any) -> bool:
    if not js_truthy(o):
        return False
    completed, rejected = _member(o, 'completed'), _member(o, 'rejected')
    if not jsjson.is_integer(completed) or not jsjson.is_integer(rejected) or completed + rejected != 16:
        return False
    if completed == 0:
        return (_member(o, 'fixed_estimator') is None and _member(o, 'redigitized') is None
                and _member(o, 'displacement_rms_mm') is None)
    fixed = _member(o, 'fixed_estimator')
    return (_summary(fixed, 16) and _summary(_member(o, 'redigitized'), 16) and _same(fixed['count'], completed)
            and _finite(_member(o, 'displacement_rms_mm')))


def _key_count(value: Any) -> int:
    """``Object.keys(value).length``."""
    if isinstance(value, dict):
        return len(value)
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        return len(value.encode('utf-16-le', errors='surrogatepass')) // 2
    return 0
