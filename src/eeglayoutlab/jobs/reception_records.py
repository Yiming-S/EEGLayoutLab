"""Saved coordinate evaluations as library records: ``designReceptionRecord`` and ``receptionLayouts`` of Node's
``reception-v2-support.mjs`` (lines 20-126), and ``robustnessSummary`` of ``webapp/contracts/scientific-options.mjs``.

The record's bytes enter keys built on it (the editor's parent digest, reception v2's ``record_provenance``), so
it is built member by member in Node's order. ``provenance.design_result`` holds the literal path
``results/v2/design_evaluation_jobs/<id>/cache.json`` (plan B20) and the SHA-256 of the file's exact bytes.
"""
from __future__ import annotations

import errno
import hashlib
import math
from typing import Any, Optional

from ..schemas import jsjson
from ..schemas.layout_key import layout_key
from . import nodefs, nodepath
from .design_result import normalize_design_request, validate_design_result
from .identity import UNDEFINED, _js_string, _member, _same, js_truthy, request_key
from .records import KEY, RecordStore, node_message, read_file, stat

__all__ = ['DESIGN_RECORD_LIMIT', 'DesignRecordError', 'HashArgumentError', 'design_reception_record',
           'received', 'robustness_summary', 'reception_layouts', 'summary']

DESIGN_RECORD_LIMIT = 8 * 1024 * 1024
STRICT_AREA_POINTER = 'results/v2/current_strict_area_budget_study.json'


class DesignRecordError(ValueError):
    """A stored design evaluation the library refuses; the message is Node's, verbatim."""


class HashArgumentError(TypeError):
    """``createHash().update(undefined)``: Node's ``ERR_INVALID_ARG_TYPE``."""

    code = 'ERR_INVALID_ARG_TYPE'


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_json(value: Any) -> str:
    """``digest(JSON.stringify(value))``: ``JSON.stringify(undefined)`` is ``undefined``, which cannot be hashed."""
    if value is UNDEFINED:
        raise HashArgumentError('The "data" argument must be of type string or an instance of Buffer, TypedArray, '
                                'or DataView. Received undefined')
    return jsjson.sha256_hex(value)


def summary(record: dict) -> dict:
    """``({layout, provenance, ...record}) => record``."""
    return {key: value for key, value in record.items() if key not in ('layout', 'provenance')}


def _spread(value: Any) -> dict:
    """``{...value}`` of a parsed JSON value: an object's members, an array's or a string's indices."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return {str(index): item for index, item in enumerate(value)}
    if isinstance(value, str):
        units = value.encode('utf-16-le', errors='surrogatepass')
        return {str(index): units[2 * index:2 * index + 2].decode('utf-16-le', errors='surrogatepass')
                for index in range(len(units) // 2)}
    return {}


def _nullish_median(value: Any) -> Any:
    """``value?.median ?? null``."""
    median = UNDEFINED if value is None or value is UNDEFINED else _member(value, 'median')
    return None if median is None or median is UNDEFINED else median


def _median(level: Any, side: str) -> Any:
    """``level[side]?.median ?? null``."""
    return _nullish_median(_member(level, side))


def _array(value: Any) -> Any:
    """An array's items for ``.map``; JSON.stringify writes ``null`` for an ``undefined`` item."""
    return [None if item is UNDEFINED else item for item in value]


def robustness_summary(block: Any) -> dict:
    """``robustnessSummary(block)``: per level, the median retention of the layout and of standard64; replacement is
    ``None`` unless it completed. Called on a block ``validRobustness`` accepted."""
    replacement_block = _member(block, 'replacement')
    status = (UNDEFINED if replacement_block is None or replacement_block is UNDEFINED
              else _member(replacement_block, 'status'))
    replacement: Any = None
    if _same(status, 'completed'):
        levels = _member(replacement_block, 'levels')
        replacement = {
            'rms_mm': _array([_member(level, 'rms_mm') for level in levels]),
            'fixed': {
                'candidate': [_nullish_median(_member(_member(level, 'candidate'), 'fixed_estimator')) for level in levels],
                'reference': [_nullish_median(_member(_member(level, 'reference'), 'fixed_estimator')) for level in levels],
            },
            'redigitized': {
                'candidate': [_nullish_median(_member(_member(level, 'candidate'), 'redigitized')) for level in levels],
                'reference': [_nullish_median(_member(_member(level, 'reference'), 'redigitized')) for level in levels],
            },
        }
    dropout = _member(_member(block, 'dropout'), 'random')
    impedance = _member(block, 'impedance')
    out: dict[str, Any] = {}
    protocol = _member(block, 'protocol')
    if protocol is not UNDEFINED:
        out['protocol'] = protocol
    out['dropout'] = {'removed': _array([_member(level, 'removed') for level in dropout]),
                      'candidate': [_median(level, 'candidate') for level in dropout],
                      'reference': [_median(level, 'reference') for level in dropout]}
    out['impedance'] = {'log_sd': _array([_member(level, 'log_sd') for level in impedance]),
                        'candidate': [_median(level, 'candidate') for level in impedance],
                        'reference': [_median(level, 'reference') for level in impedance]}
    out['replacement'] = replacement
    return out


def _read_pointer(root: str, relative: str) -> Any:
    return jsjson.parse(nodefs.decode(read_file(nodepath.join(root, relative))))


def _js_min(*values: Any) -> float:
    """``Math.min(...values)`` of numbers: ``-0`` is smaller than ``+0``, ``NaN`` wins (Python's ``min`` keeps the
    first of two zeros)."""
    result = math.inf
    for value in values:
        number = jsjson.to_number(value)
        if math.isnan(number):
            return math.nan
        if number < result or (number == 0 and result == 0 and math.copysign(1, number) < 0):
            result = number
    return result


def received(value: Any) -> str:
    """The ``Received ...`` part of Node's ``ERR_INVALID_ARG_TYPE`` message (``determineSpecificType``) for a
    parsed JSON value that is not a string. An object is named by ``value.constructor?.name`` when that is a
    non-empty string, and is otherwise written as ``util.inspect`` writes it at depth -1 (``[Object]``).

    This is Node's hardened text (nodejs/node#65607, in Node 24.22 and later releases). Earlier releases (Node
    26.5, 24.21) name the object by any ``name`` member (``String(name)``) and, for a truthy primitive
    ``constructor``, throw V8's ``TypeError`` from their ``'name' in`` check instead."""
    if value is UNDEFINED:
        return 'undefined'
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return f"type boolean ({'true' if value else 'false'})"
    if jsjson.is_number(value):
        number = jsjson.to_number(value)
        return f"type number ({'-0' if number == 0 and math.copysign(1, number) < 0 else _js_string(number)})"
    if not isinstance(value, dict):
        return 'an instance of Array'
    constructor = value.get('constructor', UNDEFINED)
    if constructor is UNDEFINED:
        return 'an instance of Object'
    # A parsed primitive or array has no own ``name``, and none on its prototype.
    name = constructor.get('name') if isinstance(constructor, dict) else None
    return f'an instance of {name}' if isinstance(name, str) and name else '[Object]'


def design_reception_record(root: str, id: Any, store: Optional[RecordStore] = None, *,
                            conditions: bool = False, with_layout_key: bool = False) -> Optional[dict]:
    """``await designReceptionRecord(root, id, store, {conditions})``: a saved coordinate evaluation as a library
    record, or ``None`` (no such record, a perturbation trial, another action, or, without ``conditions``, an
    evaluation under another noise model, conductivity scenario, head or data prior).

    Raises ``DesignRecordError`` (Node's messages) for a record that fails its checks, and Node's system errors
    (``node_message`` writes their text) for an unreadable record or reference report.
    """
    if not (isinstance(id, str) and KEY.fullmatch(id)):
        return None
    store = store or RecordStore(root)
    path = f'results/v2/design_evaluation_jobs/{id}/cache.json'
    try:
        stored_path = store.contained(store.path('design', id, 'cache.json'))
        if stat(stored_path).st_size > DESIGN_RECORD_LIMIT:
            raise DesignRecordError('设计记录过大')
        # Provenance hashes the exact persisted bytes, including JSON whitespace.
        data = read_file(stored_path)
    except OSError as error:
        if error.errno == errno.ENOENT:
            return None
        raise
    cache = jsjson.parse(nodefs.decode(data))
    r = _member(cache, 'result')
    if not _same(_member(cache, 'key'), id) or not _same(_member(cache, 'result_sha256'), _hash_json(r)):
        raise DesignRecordError('设计记录校验失败')
    request = normalize_design_request(_member(r, 'request'))
    identity = _member(cache, 'identity')
    if js_truthy(identity) and request_key(request, identity) != id:
        raise DesignRecordError('设计记录身份校验失败')
    # Perturbation trials are not nominal coordinate designs for this workflow.
    raw_request = _member(r, 'request')
    action = UNDEFINED if raw_request is None or raw_request is UNDEFINED else _member(raw_request, 'action')
    if _same(action, 'perturb'):
        return None
    validate_design_result(r, request)
    if not _same(action, 'evaluate'):
        return None
    condition: dict[str, Any] = {}
    for name in ('noise_model', 'conductivity_scenario', 'head_id', 'data_prior'):
        if js_truthy(request.get(name)):
            condition[name] = request[name]
    variant = len(condition) > 0
    if variant and not conditions:
        return None
    pointer = _read_pointer(root, STRICT_AREA_POINTER)
    report_path = _member(pointer, 'report')
    if not isinstance(report_path, str):  # path.join's check
        raise nodepath.InvalidArgTypeError(
            f'The "path" argument must be of type string. Received {received(report_path)}')
    report = read_file(nodepath.join(root, report_path))
    if not _same(_sha256(report), _member(pointer, 'sha256')):
        raise DesignRecordError('参照坐标报告校验失败')
    baseline = _member(_member(jsjson.parse(nodefs.decode(report)), 'baseline'), 'reference_xyz_mm')
    design = raw_request['design']
    nominal = r['nominal']
    scores = [_member(nominal, key) for key in ('field_relative', 'sensitivity_tail', 'localization_relative')]
    record: dict[str, Any] = {
        'id': id,
        'dataset_id': 'design_evaluation',
        'label': design['name'],
        'status': 'completed',
        'region_count': len({jsjson.to_number(v) for v in design['region_indices']}),
        'mode': 'imported_coordinates',
        'spacing_mm': 4,
        'compatible': False,
        'request': None,
        'geometry': None,
    }
    finished_at = _member(cache, 'finished_at')
    if finished_at is not UNDEFINED:
        record['finished_at'] = finished_at
    if variant:
        record['evaluation_condition'] = condition
    # Robustness leaves the nominal protocol unchanged; it adds a summary, not a condition.
    robustness = _member(r, 'robustness')
    if js_truthy(robustness):
        record['robustness'] = robustness_summary(robustness)
    record['metrics'] = {**_spread(nominal), 'conditional_global': (
        None if any(v is None or v is UNDEFINED for v in scores) else _js_min(*scores))}
    layout: dict[str, Any] = {'id': id, 'xyzMm': r['evaluated_xyz_mm']}
    if baseline is not UNDEFINED:
        layout['referenceXyzMm'] = baseline
    layout['regionIndices'] = design['region_indices']
    record['layout'] = layout
    provenance = _spread(_member(r, 'provenance'))
    forward_mode = _member(r, 'forward_mode')
    if forward_mode is not UNDEFINED:
        provenance['forward_mode'] = forward_mode
    elif 'forward_mode' in provenance:
        del provenance['forward_mode']
    provenance['design_result'] = {'path': path, 'sha256': _sha256(data)}
    record['provenance'] = provenance
    if with_layout_key:
        # Listing only: the key of the submitted design, not of the projected points.
        record['layout_key'] = layout_key(design['xyz_mm'], design['region_indices'])
    return record


def reception_layouts(library: Any) -> dict:
    """``await receptionLayouts(queue)``: the library's completed radius and strict-area layouts under independent
    noise, then every saved coordinate evaluation under the default protocol, with their warnings (not
    deduplicated). ``library`` is a ``jobs.library.Library``."""
    listed = library.list()
    records = [record for record in listed['records']
               if record.get('dataset_id') in ('cache', 'strict_area') and _same(record.get('status'), 'completed')
               and not js_truthy(_option(record.get('request'), 'noise_model'))
               and not js_truthy(_option(record.get('request'), 'data_prior'))
               and not js_truthy(_option(record.get('request'), 'electrode_count'))]
    warnings = list(listed['warnings'])
    for key in library.store.keys('design'):
        try:
            record = design_reception_record(library.root, key, library.store)
            if record:
                records.append(summary(record))
        except Exception as error:  # noqa: BLE001 - every failure is a warning in Node
            warnings.append(f'一条坐标评价记录未载入：{node_message(error)}')
    return {**listed, 'records': records, 'warnings': warnings}


def _option(value: Any, key: str) -> Any:
    """``value?.key``."""
    if value is None or value is UNDEFINED:
        return UNDEFINED
    return _member(value, key)
