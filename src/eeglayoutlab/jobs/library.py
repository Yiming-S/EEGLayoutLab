"""The local data library (``local-data-library/1``): Node's ``webapp/server/local-data-library.mjs``, statement by
statement.

The library reads, never writes: the frozen offline experiments (``webapp/public/data/single_head_optimization.json``
and the two strict-area reports the pointers under ``results/v2`` name), the radius cache records under
``results/v2/local_app_jobs`` and the saved coordinate evaluations under ``results/v2/design_evaluation_jobs``.

Record bytes enter keys built on them (the editor's parent digest, the reception identities: plan B13), so every
record is built member by member in Node's order, with Node's labels (numbers written by
``jsjson.number_to_string``, the Chinese text verbatim) and ``provenance.file`` as the literal
``results/v2/local_app_jobs/<key>/cache.json`` (B20). A radius record is ``compatible`` when the current radius
identity (code, threads, runtime) gives its key again and its forward inputs still have the recorded digests.

Known differences from Node, none of which reaches a key:

- ``list()`` sorts with V8's algorithm as Node 26 runs it (``jssort``) and Node's comparator, but the comparator
  compares texts in UTF-16 code-unit order where Node's ``localeCompare`` uses ICU collation, which depends on the
  locale. Records without ``finished_at`` (the offline experiments) can therefore come out in another order, and,
  since each answer decides which records V8 compares next, a record whose ``finished_at`` is truthy but not a
  string fails the listing exactly when Node's sort throws only where ICU orders the compared texts as code units
  do (for the author's installation, without ``LANG`` or under ``en_US``, not under ``zh_CN``, which puts Han
  before Latin), and only on Node 26: Node 22 and 24 sort 3 to 7 records differently (``jssort``).
- Memo stamps are ``st_mtime_ns`` and size where Node uses ``mtimeMs``; they never leave the process.
- Warning texts carry Node's messages for Node's own errors, V8's for member reads of ``null`` and ``undefined``,
  and libuv's for system errors (``node_message``); a ``SyntaxError`` from a file that is not JSON carries Python's
  message.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
from typing import Any, Callable, Optional

from ..schemas import jsjson
from ..schemas.layout_key import layout_key as _key_of
from . import jssort, nodefs, nodepath
from .annotations import ElectrodeAnnotations
from .design_result import _distinct
from .identity import UNDEFINED, JSTypeError, _js_string, _member, _same, js_truthy
from .radius import RadiusCache
from .reception_records import _spread, design_reception_record, received, summary
from .records import KEY, RecordStore, error_code, node_message, read_file, realpath, stat

__all__ = ['LIBRARY_SCHEMA', 'DATASETS', 'RETENTION', 'INPUT_WARNING', 'LibraryError', 'PathArgumentError',
           'domain_label', 'noise_model_label', 'data_prior_label', 'allocation_mode_label', 'objective_mode_label',
           'electrode_count_label', 'validate_saved_record', 'radius_records', 'area_records', 'summary', 'Library']

LIBRARY_SCHEMA = 'local-data-library/1'
DATASETS = (
    {'id': 'design_evaluation', 'label': '已评价坐标布局', 'note': '已保存的固定64点坐标评价；保留原坐标与评价协议。'},
    {'id': 'cache', 'label': '按需计算缓存', 'note': '严格半径上限快速搜索；完整配置和科学代码身份一致时自动复用。'},
    {'id': 'strict_area', 'label': '外部曝光筛选 · 30面积布局',
     'note': '4096字典／256源、20 dB；固定 min(field,sensitivity) 分支。所有中心、电极和区域面片使用同一外部曝光筛选。'},
    {'id': 'historical_area', 'label': '历史面积实验 · 原坐标范围',
     'note': '未使用外部曝光筛选；原坐标和分数保留，不属于当前候选表面协议。'},
    {'id': 'offline_radius', 'label': '早期半径实验 · 原始记录',
     'note': '区域允许相交，不保证R个分离区域；不同搜索预算。只能按原实验口径查看，不能替代当前设计结果。'},
)
RETENTION = ('Files on this computer; original experiments are read-only. No browser storage, automatic expiry or '
             'background batch computation.')
FAMILY_NAMES = {
    'bilateral_near_ear': '双侧耳后代理', 'left_ear_forehead': '左耳后＋前额', 'right_ear_forehead': '右耳后＋前额',
    'bilateral_expanded_ear': '双侧扩展耳周', 'bilateral_ear_forehead': '双耳后＋前额',
    'bilateral_ear_split_forehead': '双耳后＋双侧前额', 'bilateral_ear_forehead_orbital': '双耳后＋双侧前额＋眶周',
}
OFFLINE_RADIUS = 'webapp/public/data/single_head_optimization.json'
STRICT_AREA_POINTER = 'results/v2/current_strict_area_budget_study.json'
HISTORICAL_AREA_POINTER = 'results/v2/historical_strict_area_budget_study.json'
AREA_V3 = 'compact-eeg-area-budget-study/3-strict-merge-limited'
AREA_V4 = 'compact-eeg-area-budget-study/4-external-exposure'
INPUT_WARNING = '前向输入文件与部分缓存的原模型不符；这些历史记录仍可查看，但不能作为当前配置命中。'
PATCH_VERTICES = 52410
MIN_ADAPTIVE_REGION_ELECTRODES = 4
# What ``familyNames[key]`` finds on Object.prototype for an identifier that is not a family: its members, as a
# template literal writes them (``Function.prototype.toString`` of a built-in, ``String(Object.prototype)``).
_OBJECT_PROTOTYPE = {
    '__proto__': '[object Object]',
    **{name: f'function {name}() {{ [native code] }}' for name in (
        'constructor', '__defineGetter__', '__defineSetter__', 'hasOwnProperty', '__lookupGetter__',
        '__lookupSetter__', 'isPrototypeOf', 'propertyIsEnumerable', 'toString', 'valueOf', 'toLocaleString')},
}
_OBJECT_PROTOTYPE['constructor'] = 'function Object() { [native code] }'
_SCORES = ('field_relative', 'sensitivity_tail', 'localization_relative')
_SHA256 = re.compile('[a-f0-9]{64}')



def _layout_key(layout: Any) -> Optional[str]:
    """``layoutKey(layout)``: the key of a search layout, or ``None`` without coordinates and region indices."""
    if not isinstance(layout, dict) or not js_truthy(layout.get('xyzMm')) or not js_truthy(layout.get('regionIndices')):
        return None
    return _key_of(layout['xyzMm'], layout['regionIndices'])

class LibraryError(ValueError):
    """A library record or report Node refuses; the message is Node's, verbatim."""


# --- JavaScript values ------------------------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _id_for(dataset: str, id: str) -> str:
    """``idFor(dataset, id)``: SHA-256 of the plain string ``<dataset>:<id>``, encoded as ``hash.update`` encodes
    a string (UTF-8, a lone surrogate as U+FFFD)."""
    text = f'{dataset}:{id}'.encode('utf-16-le', errors='surrogatepass').decode('utf-16-le', errors='replace')
    return _sha256(text.encode('utf-8'))


def _opt(value: Any, key: str) -> Any:
    """``value?.key``."""
    return UNDEFINED if value is None or value is UNDEFINED else _member(value, key)


def _nullish(value: Any) -> bool:
    return value is None or value is UNDEFINED


def _finite(value: Any) -> bool:
    return jsjson.is_number(value) and math.isfinite(jsjson.to_number(value))


def _units(text: str) -> bytes:
    """A sort key in UTF-16 code-unit order."""
    return text.encode('utf-16-be', errors='surrogatepass')


def _slice_units(text: str, start: int) -> str:
    """``text.slice(start)`` in UTF-16 code units."""
    data = text.encode('utf-16-le', errors='surrogatepass')[2 * start:]
    return data.decode('utf-16-le', errors='surrogatepass')


def _length(value: Any) -> Any:
    """``value.length`` of a parsed JSON value (an object's ``length`` member)."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        return len(_units(value)) // 2
    return _opt(value, 'length') if isinstance(value, dict) else UNDEFINED


def _method(value: Any, expression: str, method: str) -> list:
    """The array whose ``method`` Node calls; V8's ``TypeError`` for anything else."""
    if _nullish(value):
        raise JSTypeError(f"Cannot read properties of {'null' if value is None else 'undefined'} (reading '{method}')")
    if not isinstance(value, list):
        raise JSTypeError(f'{expression}.{method} is not a function')
    return value


def _find(items: Any, expression: str, test: Callable[[Any], bool]) -> Any:
    """``items.find(test)``."""
    for item in _method(items, expression, 'find'):
        if test(item):
            return item
    return UNDEFINED


def _defined(record: dict) -> dict:
    """The members ``JSON.stringify`` writes: ``undefined`` ones are left out."""
    return {key: value for key, value in record.items() if value is not UNDEFINED}


def _number_in(value: Any, allowed: tuple) -> bool:
    """``allowed.includes(value)`` for numbers (``true`` is not 1)."""
    return jsjson.is_number(value) and jsjson.to_number(value) in allowed


def _joined(point: list) -> str:
    return ','.join(jsjson.number_to_string(jsjson.to_number(v)) for v in point)


class PathArgumentError(TypeError):
    """``path.resolve`` of a value that is not a string: Node's ``ERR_INVALID_ARG_TYPE``."""

    code = 'ERR_INVALID_ARG_TYPE'


def _path_argument(value: Any, index: int) -> str:
    """``path.resolve``'s check of its argument ``paths[index]``."""
    if not isinstance(value, str):
        raise PathArgumentError(f'The "paths[{index}]" argument must be of type string. Received {received(value)}')
    return value


def _index(value: Any, index: int) -> Any:
    """``value[index]`` of a parsed JSON value: a string gives its code unit there."""
    if isinstance(value, list):
        return value[index] if index < len(value) else UNDEFINED
    if isinstance(value, str):
        data = value.encode('utf-16-le', errors='surrogatepass')[2 * index:2 * index + 2]
        return data.decode('utf-16-le', errors='surrogatepass') if data else UNDEFINED
    return _member(value, str(index))


def _family_name(family_id: Any) -> Any:
    """``familyNames[familyId]``: the object literal's own names, then what Object.prototype holds."""
    key = _js_string(family_id)
    name = FAMILY_NAMES.get(key)
    return name if name is not None else _OBJECT_PROTOTYPE.get(key)


def _compare_units(x: str, y: str) -> int:
    """``x.localeCompare(y)`` by UTF-16 code units."""
    x_units, y_units = _units(x), _units(y)
    return (x_units > y_units) - (x_units < y_units)


def _newest_first(a: dict, b: dict) -> int:
    """``(a, b) => (b.finished_at || '').localeCompare(a.finished_at || '') || a.label.localeCompare(b.label)``:
    V8's ``TypeError`` when ``b.finished_at`` is truthy but not a string, or ``a.label`` is not a string."""
    mine, theirs = _member(b, 'finished_at'), _member(a, 'finished_at')
    mine = mine if js_truthy(mine) else ''
    if not isinstance(mine, str):
        raise JSTypeError('(b.finished_at || "").localeCompare is not a function')
    order = _compare_units(mine, _js_string(theirs) if js_truthy(theirs) else '')
    if order:
        return order
    label = _member(a, 'label')
    if _nullish(label):
        raise JSTypeError(f"Cannot read properties of {'null' if label is None else 'undefined'} "
                          "(reading 'localeCompare')")
    if not isinstance(label, str):
        raise JSTypeError('a.label.localeCompare is not a function')
    return _compare_units(label, _js_string(_member(b, 'label')))


def domain_label(mode: Any) -> str:
    """``domainLabel(mode)``: whole head, the low-hair proxy, or a named anatomical combination."""
    if isinstance(mode, (str, list)):
        return '全头' if 'whole' in mode else '低毛发代理' if 'low_hair' in mode else '指定解剖组合'
    if _nullish(mode):
        raise JSTypeError(f"Cannot read properties of {'null' if mode is None else 'undefined'} (reading 'includes')")
    raise JSTypeError('mode.includes is not a function')


def noise_model_label(value: dict) -> str:
    """``noiseModelLabel(value)`` (scientific-options.mjs) of a canonical noise model."""
    kind = value.get('kind')
    if kind == 'spatial':
        return f"空间相关噪声 ρ=0.5，L={_js_string(value['length_mm'])} mm"
    if kind == 'brain_background':
        return '脑背景活动噪声（仅定位，50%）'
    return '独立噪声（默认）'


def data_prior_label(value: dict) -> str:
    """``dataPriorLabel(value)`` (scientific-options.mjs) of a canonical data prior."""
    rho = value['rho']
    noise = f"ρ={_js_string(rho)}，L={_js_string(value['length_mm'])} mm" if js_truthy(rho) else '独立'
    return f'数据先验（噪声{noise}）'


def allocation_mode_label(value: Any) -> str:
    """``allocationModeLabel(value)`` (scientific-options.mjs)."""
    return '跨区自适应配额' if _same(value, 'adaptive') else ''


def objective_mode_label(value: Any) -> str:
    """``objectiveModeLabel(value)`` (scientific-options.mjs)."""
    return '子空间信息复合目标' if _same(value, 'composite') else ''


def electrode_count_label(value: Any) -> str:
    """``electrodeCountLabel(value)`` (scientific-options.mjs)."""
    return f'{_js_string(value)}导' if jsjson.is_number(value) and not _same(value, 64) else ''


# --- Records ----------------------------------------------------------------------------------------------------

def _xyz(value: Any, expected_len: int = 64) -> bool:
    return (isinstance(value, list) and len(value) == expected_len
            and all(isinstance(p, list) and len(p) == 3 and all(_finite(v) for v in p) for p in value))


def validate_saved_record(record: Any) -> Any:
    """``validateSavedRecord(record)``: distinct points, valid regional counts, a consistent minimum retention,
    and valid region patches. Returns the record; raises ``LibraryError`` with Node's message."""
    if not js_truthy(record) or _member(record, 'status') not in ('completed', 'no_layout'):
        raise LibraryError('无效记录状态')
    if record['status'] == 'no_layout':
        if not _nullish(_member(record, 'layout')) or not _nullish(_member(record, 'metrics')):
            raise LibraryError('缺失布局带有分数')
        return record
    layout, r, m = _member(record, 'layout'), _member(record, 'region_count'), _member(record, 'metrics')
    req = _member(record, 'request')
    adaptive = _same(_opt(req, 'allocation_mode'), 'adaptive')
    raw_ec = _opt(req, 'electrode_count')
    expected_count = 64 if raw_ec in (None, UNDEFINED) else int(jsjson.to_number(raw_ec))
    if (not _number_in(r, (1, 2, 3, 4, 6)) or not _xyz(_opt(layout, 'xyzMm'), expected_count)
            or not _xyz(_opt(layout, 'referenceXyzMm'), 64)
            or len({_joined(p) for p in layout['xyzMm']}) != expected_count
            or not isinstance(_member(layout, 'regionIndices'), list) or len(layout['regionIndices']) != expected_count
            or any(not jsjson.is_integer(n) or n < 0 or n >= r for n in layout['regionIndices'])
            or (any(sum(1 for i in layout['regionIndices'] if i == n) < MIN_ADAPTIVE_REGION_ELECTRODES
                    for n in range(int(r)))
                if adaptive
                else any(sum(1 for i in layout['regionIndices'] if i == n)
                         != expected_count // int(r) + int(n < expected_count % int(r))
                         for n in range(int(r))))):
        raise LibraryError('记录坐标与区域标签无效')
    scores = [_opt(m, key) for key in _SCORES]
    if not js_truthy(m) or any(v is not None and not _finite(v) for v in scores):
        raise LibraryError('无效保留率')
    g = None if any(v is None for v in scores) else min(scores)
    conditional = _member(m, 'conditional_global')
    if (conditional is not None if g is None
            else not (_finite(conditional) and not abs(g - conditional) > 1e-9)):
        raise LibraryError('保留率最小值不一致')
    if (_same(_member(record, 'dataset_id'), 'strict_area')
            and not _same(_opt(_member(record, 'geometry'), 'union_connected_component_count'), r)):
        raise LibraryError('面积实验连通数不符')
    patches = _member(layout, 'regionPatchVertexIndices')
    if js_truthy(patches):
        areas = _member(layout, 'regionAreasCm2')
        if (not _same(_length(patches), r) or not _same(_length(areas), r)
                or any(not _finite(a) or a <= 0 for a in _method(areas, 'layout.regionAreasCm2', 'some'))
                or any(not isinstance(ids, list) or not ids or not _distinct(ids)
                       or any(not jsjson.is_integer(i) or i < 0 or i >= PATCH_VERTICES for i in ids)
                       for ids in _method(patches, 'layout.regionPatchVertexIndices', 'some'))):
            raise LibraryError('保存的区域面片或面积无效')
    if (_same(_opt(_member(record, 'provenance'), 'surface_status'), 'external_exposure_screened')
            and not js_truthy(_member(layout, 'regionPatchVertexIndices'))):
        raise LibraryError('新版面积记录缺少原生区域面片')
    return record


def radius_records(data: Any, provenance: dict) -> list[dict]:
    """``radiusRecords(data, provenance)``: the early radius experiments, one record per condition and objective, at
    20 dB, read-only (``compatible`` is false)."""
    if (not _same(_member(data, 'schema'), 'single-head-app/1')
            or not _same(_opt(_member(data, 'scope'), 'head_count'), 1)
            or not _same(_opt(_member(data, 'scope'), 'physical_electrode_count'), 64)):
        raise LibraryError('半径实验格式错误')
    baseline = _find(_member(_member(data, 'baseline'), 'conditions'), 'data.baseline.conditions',
                     lambda row: _same(_member(row, 'snr_db'), 20))
    rows = []
    for c in _method(_member(data, 'conditions'), 'data.conditions', 'flatMap'):
        for v in _method(_member(c, 'variants'), 'c.variants', 'map'):
            m = _find(_member(v, 'conditions'), 'v.conditions', lambda row: _same(_member(row, 'snr_db'), 20))
            id = _id_for('offline_radius', f"{_js_string(_member(c, 'id'))}:{_js_string(_member(v, 'id'))}")
            region_count = _js_string(_member(c, 'R'))
            family = _family_name(_member(c, 'family_id'))
            family = family if family is not None else domain_label(_member(c, 'mode'))
            radius = _js_string(_member(c, 'radius_mm'))
            spacing = _js_string(_member(c, 'spacing_mm'))
            objective = '场重建优化' if _same(_member(v, 'objective'), 'field_20db') else '场与敏感度优化'
            label = f'{region_count}区 · {family} · 半径≤{radius} mm · 点距{spacing} mm · {objective}'
            record = {'id': id, 'dataset_id': 'offline_radius', 'label': label, 'region_count': _member(c, 'R'),
                      'mode': _member(c, 'mode'), 'radius_cap_mm': _member(c, 'radius_mm'),
                      'spacing_mm': _member(c, 'spacing_mm'), 'status': 'completed', 'compatible': False,
                      'request': None, 'geometry': None}
            record['layout'] = _defined({'id': _member(v, 'id'), 'xyzMm': _member(v, 'xyz_mm'),
                                         'regionIndices': _member(v, 'region_indices'),
                                         'referenceXyzMm': _member(_member(data, 'baseline'), 'xyz_mm')})
            metrics = _spread(m)
            metrics['reference_field_absolute'] = _member(baseline, 'field_absolute')
            metrics['reference_median_mm'] = _member(baseline, 'median_mm')
            record['metrics'] = _defined(metrics)
            record['provenance'] = _defined({**provenance, 'original': _member(data, 'provenance'),
                                             'condition_id': _member(c, 'id'), 'objective': _member(v, 'objective'),
                                             'snr_db': 20, 'overlapping_regions_allowed': True,
                                             'formal_population_ar': False})
            rows.append(validate_saved_record(_defined(record)))
    return rows


def _source_model(localization: Any) -> bool:
    """The frozen source model of a strict-area score: 4096 dictionary and 256 generating sources."""
    return (_same(_member(localization, 'dictionary_source_count'), 4096)
            and _same(_member(localization, 'generation_source_count'), 256))


def area_records(data: Any, provenance: dict, historical: bool = False) -> list[dict]:
    """``areaRecords(data, provenance, {historical})``: the 30 strict-area layouts of an area-budget report (the
    frozen ``min_field_sensitivity20`` finalist of each condition, or a ``no_layout`` record), read-only.

    ``final.xyz_mm`` is in region order and ``evaluation.xyz_mm`` in bank-index order; the record never mixes them.
    """
    schema_version = _member(data, 'schema_version')
    exterior = _same(schema_version, AREA_V4)
    config = _member(data, 'config')
    if ((not exterior and not _same(schema_version, AREA_V3))
            or not _same(_opt(config, 'physical_electrode_count'), 64) or not _same(_opt(config, 'spacing_mm'), 4)
            or not _same(_opt(_opt(config, 'evaluation'), 'snr_db'), 20)
            or not _same(_opt(config, 'require_disconnected_regions'), True)
            or not _same(_member(data, 'formal_population_ar'), False)
            or not _same(_length(_opt(data, 'conditions')), 30)):
        raise LibraryError('严格面积报告协议与本导入器不符')
    baseline = _member(data, 'baseline')
    identity = _member(data, 'identity')
    if exterior and not _SHA256.fullmatch(_js_string(_opt(identity, 'surface_admissibility_sha256'))):
        raise LibraryError('缺少外部表面筛选身份')
    rows = []
    for entry in _method(_member(data, 'conditions'), 'data.conditions', 'map'):
        c = _member(entry, 'condition')
        f = _find(_member(entry, 'finalists'), 'entry.finalists',
                  lambda v: _same(_member(v, 'objective'), 'min_field_sensitivity20'))
        condition_id = (f"{_js_string(_member(data, 'run_id'))}:{_js_string(_member(provenance, 'sha256'))}:"
                        f"{_js_string(_member(c, 'id'))}" if exterior else _js_string(_member(c, 'id')))
        id = _id_for('strict_area', condition_id)
        label = (f"{_js_string(_member(c, 'region_count'))}区 · {domain_label(_member(c, 'domain'))} · "
                 f"总面积≤{_js_string(_member(c, 'area_cap_cm2'))} cm²")
        sha = _opt(identity, 'surface_admissibility_sha256')
        version = _opt(identity, 'surface_admissibility_version')
        base = {
            'id': id, 'dataset_id': 'historical_area' if historical else 'strict_area', 'label': label,
            'region_count': _member(c, 'region_count'), 'mode': _member(c, 'domain'),
            'area_cap_cm2': _member(c, 'area_cap_cm2'), 'spacing_mm': 4, 'compatible': False, 'request': None,
            'provenance': _defined({
                **provenance, 'run_id': _member(data, 'run_id'), 'batch_id': _member(data, 'batch_id'),
                'condition_id': _member(c, 'id'),
                'surface_admissibility_sha256': None if _nullish(sha) else sha,
                'surface_admissibility_version': 'legacy_coordinate_roi' if _nullish(version) else version,
                'surface_status': 'external_exposure_screened' if exterior else 'historical_unqualified',
                'objective': _opt(f, 'objective'), 'snr_db': 20, 'dictionary_sources': 4096,
                'generation_sources': 256, 'formal_population_ar': False, 'reevaluation_512_sources': False,
            }),
        }
        if _nullish(f):
            if _same(_member(entry, 'status'), 'completed_best_found'):
                raise LibraryError('缺少冻结主分支')
            rows.append(validate_saved_record(_defined({**base, 'status': 'no_layout', 'layout': None,
                                                        'metrics': None, 'geometry': None})))
            continue
        e = _member(f, 'evaluation')
        field = _find(_member(_member(e, 'field_metrics'), 'conditions'), 'e.field_metrics.conditions',
                      lambda row: _same(_member(row, 'nominal_reference_snr_db'), 20))
        if (not js_truthy(field) or not _source_model(_member(e, 'localization'))
                or not _source_model(_member(baseline, 'localization'))):
            raise LibraryError('严格面积原始评分的源模型不符')
        final = _member(f, 'final')
        record = {**base, 'status': 'completed', 'compatible': False, 'request': None,
                  'geometry': _member(final, 'geometry')}
        layout = {'id': _member(e, 'id'), 'xyzMm': _member(final, 'xyz_mm'),
                  'regionIndices': _member(final, 'region_indices'),
                  'referenceXyzMm': _member(baseline, 'reference_xyz_mm')}
        if exterior:
            layout['regionPatchVertexIndices'] = _member(final, 'surface_patch_vertex_indices')
            layout['regionAreasCm2'] = _member(_member(final, 'geometry'), 'region_areas_cm2')
        record['layout'] = _defined(layout)
        first = _index(_member(_member(baseline, 'field_metrics'), 'conditions'), 0)
        record['metrics'] = _defined({
            'field_relative': _member(e, 'field20'),
            'field_absolute': _member(field, 'candidate_field_explained_energy'),
            'reference_field_absolute': _member(first, 'candidate_field_explained_energy'),
            'sensitivity_tail': _member(e, 'sensitivity_tail'),
            'localization_relative': _member(e, 'localization_relative20'),
            'conditional_global': _member(e, 'conditional_global20'),
            'median_mm': _member(_member(e, 'localization'), 'median_error_mm'),
            'p90_mm': _member(_member(e, 'localization'), 'p90_error_mm'),
            'reference_median_mm': _member(_member(baseline, 'localization'), 'median_error_mm'),
        })
        rows.append(validate_saved_record(_defined(record)))
    return rows


# --- The library ------------------------------------------------------------------------------------------------

class Library:
    """``LocalDataLibrary`` of one root: ``list()`` and ``get(id)`` return values whose ``jsjson.stringify`` is
    Node's text, and ``annotations`` reads the electrode-name annotations (``ElectrodeAnnotations.local``).

    ``config`` is the ``RuntimeConfig``: its ``python`` (Node's ``computePython``) identifies the radius runtime.
    ``radius`` replaces the radius cache reader (Node's queue), for tests that fix its identity. The library is
    safe to call from several threads; calls run one at a time, as Node's single thread runs them.
    """

    def __init__(self, root: str, config: Any, workspace_annotations_dir: Optional[str] = None, *,
                 radius: Optional[RadiusCache] = None):
        self.root = nodepath.resolve(root)
        self.radius = radius if radius is not None else RadiusCache(self.root, config.python)
        self.store: RecordStore = self.radius.store
        self.records: dict[str, dict] = {}
        self.loaded: dict[str, Any] = {}
        self.warnings: list[str] = []
        self.annotations = ElectrodeAnnotations.local(workspace_annotations_dir, self.root)
        self._lock = threading.RLock()
        # Layout keys of resident full records, by id: (the layout they were computed from, the key).
        self._layout_keys: dict[str, tuple] = {}

    # Node: offline(datasetId, file, convert, digest)
    def _offline(self, dataset_id: str, file: str, convert: Callable[[Any, dict], list], digest: Any = None) -> None:
        info = stat(file)
        fingerprint = (info.st_mtime_ns, info.st_size, digest or '')
        if self.loaded.get(dataset_id) == fingerprint:
            return
        data = read_file(file)
        sha256 = _sha256(data)
        if digest and sha256 != digest:
            raise LibraryError('报告SHA256校验失败')
        rows = convert(jsjson.parse(nodefs.decode(data)),
                       {'file': _slice_units(file, len(_units(self.root)) // 2 + 1), 'sha256': sha256})
        for id, row in list(self.records.items()):
            if row.get('dataset_id') == dataset_id:
                del self.records[id]
        for row in rows:
            self.records[row['id']] = row
        self.loaded[dataset_id] = fingerprint

    def refresh(self) -> None:
        """``await refresh()``: reloads what changed and recomputes every radius record's ``compatible``."""
        self.warnings = []
        for dataset in ('offline_radius', 'historical_area', 'strict_area'):
            try:
                if dataset == 'offline_radius':
                    self._offline(dataset, nodepath.join(self.root, OFFLINE_RADIUS), radius_records)
                else:
                    pointer_path = HISTORICAL_AREA_POINTER if dataset == 'historical_area' else STRICT_AREA_POINTER
                    pointer = jsjson.parse(nodefs.decode(read_file(nodepath.join(self.root, pointer_path))))
                    file = realpath(nodepath.resolve(self.root, _path_argument(_member(pointer, 'report'), 1)))
                    if (not file.startswith(nodepath.join(self.root, 'results/v2/campaigns') + '/')
                            or not _SHA256.fullmatch(_js_string(_member(pointer, 'sha256')))):
                        raise LibraryError('报告路径或身份无效')
                    historical = dataset == 'historical_area'
                    self._offline(dataset, file, lambda data, source: area_records(data, source, historical),
                                  pointer['sha256'])
            except Exception as error:  # noqa: BLE001 - every failure is a warning in Node
                for id, row in list(self.records.items()):
                    if row.get('dataset_id') == dataset:
                        del self.records[id]
                self.loaded.pop(dataset, None)
                label = next(d['label'] for d in DATASETS if d['id'] == dataset)
                self.warnings.append(f"{label}：{'数据未提供' if error_code(error) == 'ENOENT' else node_message(error)}")
        directory = self.store.directory('radius')
        keys = self.store.keys('radius')
        known = set(keys)
        # Only summary metadata remains resident for the cache; full arrays load on demand.
        for id, row in list(self.records.items()):
            if row.get('dataset_id') == 'cache' and id not in known:
                del self.records[id]
        code = self.radius.get_identity()
        for key in keys:
            path = nodepath.join(directory, key, 'cache.json')
            try:
                info = stat(path)
                stamp = (info.st_mtime_ns, info.st_size)
                row = self.records.get(key)
                if self.loaded.get(key) != stamp or row is None:
                    cache = self.radius.read_cache(key)
                    if not cache:
                        raise LibraryError('缓存完整性校验未通过')
                    row = self.cache_record(cache, False)
                    keyed = summary(row)
                    key_of_layout = _layout_key(row.get('layout'))
                    if key_of_layout:
                        keyed['layout_key'] = key_of_layout
                    self.records[key] = keyed
                    self.loaded[key] = stamp
                row = self.records[key]
                # The radius cache owns the key formula (code identity, threads and, off macOS, the runtime).
                row['compatible'] = self.radius.identity_for(_member(row, 'request'), code)[1] == key
                if row['compatible']:
                    cache = self.radius.read_cache(key)
                    try:
                        self.radius.verify_inputs(_member(cache, 'result'))
                    except Exception:  # noqa: BLE001
                        row['compatible'] = False
                        self.warnings.append(INPUT_WARNING)
            except Exception as error:  # noqa: BLE001
                self.records.pop(key, None)
                self.loaded.pop(key, None)
                if error_code(error) != 'ENOENT':
                    self.warnings.append(f'一条计算缓存未载入：{node_message(error)}')
        coordinate_directory = self.store.directory('design')
        coordinate_keys = self.store.keys('design')
        known = set(coordinate_keys)
        for id, row in list(self.records.items()):
            if row.get('dataset_id') == 'design_evaluation' and id not in known:
                del self.records[id]
        for key in coordinate_keys:
            try:
                info = stat(nodepath.join(coordinate_directory, key, 'cache.json'))
                stamp = (info.st_mtime_ns, info.st_size)
                if self.loaded.get('coordinates:' + key) == stamp and key in self.records:
                    continue
                record = design_reception_record(self.root, key, self.store, conditions=True, with_layout_key=True)
                if record:
                    self.records[key] = summary(record)
                else:
                    self.records.pop(key, None)
                self.loaded['coordinates:' + key] = stamp
            except Exception as error:  # noqa: BLE001
                self.records.pop(key, None)
                self.loaded.pop('coordinates:' + key, None)
                if error_code(error) != 'ENOENT':
                    self.warnings.append(f'一条坐标评价记录未载入：{node_message(error)}')

    def cache_record(self, cache: dict, compatible: bool) -> dict:
        """``cacheRecord(cache, compatible)``: a radius cache record (``read_cache``'s value) as a library record."""
        r, request = cache['result'], cache['request']
        mode = request['mode']
        sites = ' + '.join(request['mask_codes']) if mode == 'preset' else domain_label(mode)
        label = f"{_js_string(request['region_count'])}区 · {sites} · 半径≤{_js_string(request['radius_mm'])} mm"
        if js_truthy(request.get('noise_model')):
            label += ' · ' + noise_model_label(request['noise_model'])
        if js_truthy(request.get('data_prior')):
            label += ' · ' + data_prior_label(request['data_prior'])
        if js_truthy(request.get('allocation_mode')):
            label += ' · ' + allocation_mode_label(request['allocation_mode'])
        if js_truthy(request.get('objective_mode')):
            label += ' · ' + objective_mode_label(request['objective_mode'])
        if js_truthy(request.get('electrode_count')):
            label += ' · ' + electrode_count_label(request['electrode_count'])
        record: dict[str, Any] = {
            'id': cache['key'], 'dataset_id': 'cache', 'status': r['status'], 'label': label,
            'region_count': request['region_count'], 'radius_cap_mm': request['radius_mm'], 'mode': mode,
            'spacing_mm': 4, 'compatible': compatible, 'request': request,
        }
        if cache.get('finished_at', UNDEFINED) is not UNDEFINED:
            record['finished_at'] = cache['finished_at']
        for name in ('metrics', 'geometry', 'layout'):
            value = r.get(name)
            record[name] = None if value is None else value
        record['provenance'] = {**_spread(r.get('provenance')), 'result_sha256': cache['result_sha256'],
                                'file': f"results/v2/local_app_jobs/{cache['key']}/cache.json"}
        return validate_saved_record(record)

    def _listed(self, row: dict) -> dict:
        """``listed(row)``: the summary with the layout key last; a resident full record is keyed once."""
        layout = row.get('layout')
        if 'layout_key' in row or layout is None:
            return summary(row)
        cached = self._layout_keys.get(row['id'])
        if cached is None or cached[0] is not layout:
            cached = (layout, _layout_key(layout))
            self._layout_keys[row['id']] = cached
        listed = summary(row)
        if cached[1]:
            listed['layout_key'] = cached[1]
        return listed

    def list(self) -> dict:
        """``await list()``: ``{schema, local_only, records, warnings, datasets, retention}``, records without
        their layout and provenance, newest first (``finished_at``, then the label in code-unit order), sorted by
        V8's algorithm (``jssort``) with Node's comparator (``_newest_first``), whose ``TypeError`` fails the
        listing."""
        with self._lock:
            self.refresh()
            records = jssort.array_sort([self._listed(row) for row in self.records.values()], _newest_first)
            return {
                'schema': LIBRARY_SCHEMA, 'local_only': True, 'records': records,
                'warnings': list(dict.fromkeys(self.warnings)),
                'datasets': [{**dataset, 'count': sum(1 for row in records if row.get('dataset_id') == dataset['id'])}
                             for dataset in DATASETS],
                'retention': RETENTION,
            }

    def get(self, id: Any) -> Optional[dict]:
        """``await get(id)``: the full record (with layout and provenance), or ``None``; only 64 lowercase hex
        digits are looked up, never a path."""
        if not (isinstance(id, str) and KEY.fullmatch(id)):
            return None
        with self._lock:
            self.refresh()
            row = self.records.get(id)
            if row is not None and row.get('dataset_id') == 'design_evaluation':
                return design_reception_record(self.root, id, self.store, conditions=True)
            if row is None or row.get('dataset_id') != 'cache':
                return dict(row) if row is not None else None
            cache = self.radius.read_cache(id)
            return self.cache_record(cache, row['compatible']) if cache else None
