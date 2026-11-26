"""Pure-Python port of ``webapp/contracts/coordinate-source.mjs`` (no Pydantic dependency).

Used by ``eeglayoutlab design`` and ``eeglayoutlab export`` so those commands run without the ``[service]`` extra.
"""
from __future__ import annotations

import math
import re
from typing import Any

from ..schemas import jsjson

__all__ = [
    'MNI_COORDINATE_SYSTEMS', 'LABEL_CAP', 'MNI_IMPORT_LIMIT_MM',
    'HEAD_REGISTRATION_METHOD', 'HEAD_REGISTRATION_LIMIT_MM', 'MONTAGE_FORMATS',
    'validate_coordinate_source', 'coordinate_source_files',
]

_COMMON = (
    'schema', 'format', 'electrodes_file', 'coordsystem_file', 'coordinate_system',
    'unit', 'coordinate_system_description', 'region_index_base', 'region_description',
)
_CONVERSION_FIELDS = ('method', 'mapping_id', 'input_coordinate_system', 'input_unit', 'max_surface_distance_mm')
MNI_COORDINATE_SYSTEMS = (
    'MNI152NLin6Asym', 'MNI152NLin6Sym', 'MNI152Lin', 'MNI152NLin2009aAsym', 'MNI152NLin2009aSym',
    'MNI152NLin2009bAsym', 'MNI152NLin2009bSym', 'MNI152NLin2009cAsym', 'MNI152NLin2009cSym',
    'MNI305', 'MNIColin27', 'IXI549Space', 'ICBM452AirSpace', 'ICBM452Warp5Space',
)
LABEL_CAP = 'EEG10-20_extended_SPM12'
MNI_IMPORT_LIMIT_MM = 10
HEAD_REGISTRATION_METHOD = 'head-landmarks-surface/1'
HEAD_REGISTRATION_LIMIT_MM = 10
MONTAGE_FORMATS = ('mne-elc/1', 'eeglab-sfp/1')
_HEAD_CONVERSION_FIELDS = (
    'method', 'mapping_id', 'input_coordinate_system', 'input_unit', 'landmark_source',
    'scale', 'rotation_deg', 'max_landmark_residual_mm', 'max_surface_distance_mm', 'iterations',
)
_HEX64 = re.compile(r'^[0-9a-f]{64}$')


def _utf16_codes(s: str) -> list[int]:
    data = s.encode('utf-16-le', errors='surrogatepass')
    return [data[i] | (data[i + 1] << 8) for i in range(0, len(data), 2)]


def _text(value: Any, max_len: int, multiline: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    codes = _utf16_codes(value)
    if len(codes) > max_len or not jsjson.js_trim(value):
        return False
    for code in codes:
        if (code < 32 and not (multiline and code in (9, 10, 13))) or code == 127:
            return False
    return True


def _file_name(name: Any) -> bool:
    return _text(name, 200) and '/' not in name and '\\' not in name and name not in ('.', '..')


def _plain(value: Any) -> bool:
    return isinstance(value, dict)


def _keys_equal(value: dict, expected: tuple[str, ...]) -> bool:
    return sorted(value.keys()) == sorted(expected)


def _finite_in(value: Any, low: float, high: float) -> bool:
    return jsjson.is_number(value) and math.isfinite(float(value)) and low <= float(value) <= high


def _conversion_valid(value: Any, fmt: str) -> bool:
    if not _plain(value) or not _keys_equal(value, _CONVERSION_FIELDS):
        return False
    mapping_id = value.get('mapping_id')
    if not isinstance(mapping_id, str) or not _HEX64.match(mapping_id):
        return False
    if fmt == 'bids-electrodes/1':
        return (
            value.get('method') == 'ernie-mni-scalp/1'
            and value.get('input_coordinate_system') in MNI_COORDINATE_SYSTEMS
            and value.get('input_unit') == 'mm'
            and _finite_in(value.get('max_surface_distance_mm'), 0, MNI_IMPORT_LIMIT_MM)
        )
    return (
        value.get('method') == 'cap-labels/1'
        and value.get('input_coordinate_system') == LABEL_CAP
        and value.get('input_unit') is None
        and value.get('max_surface_distance_mm') is None
    )


def _head_conversion_valid(value: Any) -> bool:
    if not _plain(value) or not _keys_equal(value, _HEAD_CONVERSION_FIELDS):
        return False
    mapping_id = value.get('mapping_id')
    iterations = value.get('iterations')
    return (
        value.get('method') == HEAD_REGISTRATION_METHOD
        and isinstance(mapping_id, str)
        and bool(_HEX64.match(mapping_id))
        and _text(value.get('input_coordinate_system'), 64)
        and value.get('input_unit') in ('mm', 'cm', 'm')
        and value.get('landmark_source') in ('coordsystem', 'file')
        and _finite_in(value.get('scale'), 0.5, 2)
        and _finite_in(value.get('rotation_deg'), 0, 180)
        and _finite_in(value.get('max_landmark_residual_mm'), 0, 1000)
        and _finite_in(value.get('max_surface_distance_mm'), 0, HEAD_REGISTRATION_LIMIT_MM)
        and jsjson.is_integer(iterations)
        and 0 <= int(float(iterations)) <= 1000
    )


def _region_assignment_valid(value: Any) -> bool:
    if not _plain(value):
        return False
    if value.get('method') == 'file':
        return _keys_equal(value, ('method',))
    rc = value.get('region_count')
    return (
        value.get('method') == 'balanced-spatial/1'
        and _keys_equal(value, ('method', 'region_count'))
        and jsjson.is_integer(rc)
        and int(float(rc)) in (1, 2, 3, 4, 6)
    )


def _v3_valid(value: dict) -> bool:
    if not _keys_equal(value, (*_COMMON, 'conversion', 'region_assignment')):
        return False
    if not _region_assignment_valid(value.get('region_assignment')):
        return False
    fmt = value.get('format')
    montage = fmt in MONTAGE_FORMATS
    if not (montage or fmt in ('bids-electrodes/1', 'electrode-labels/1')):
        return False
    cs_ok = (value.get('coordsystem_file') is None
             if (montage or fmt == 'electrode-labels/1')
             else _file_name(value.get('coordsystem_file')))
    if not cs_ok:
        return False
    conv = value.get('conversion')
    if conv is None:
        return fmt != 'electrode-labels/1'
    if _plain(conv) and conv.get('method') == HEAD_REGISTRATION_METHOD:
        return fmt != 'electrode-labels/1' and _head_conversion_valid(conv)
    return (not montage) and _conversion_valid(conv, fmt)


def _same_zero(value: Any) -> bool:
    return jsjson.is_number(value) and float(value) == 0.0


def validate_coordinate_source(value: Any) -> dict[str, Any]:
    """``validateCoordinateSource(value)``: raises ``ValueError('坐标来源说明格式无效')`` on invalid metadata."""
    if _plain(value) and value.get('schema') == 'electrode-coordinate-source/3':
        if (
            value.get('coordinate_system') != 'ernie_native_mm'
            or value.get('unit') != 'mm'
            or not _same_zero(value.get('region_index_base'))
            or not _text(value.get('coordinate_system_description'), 2048, True)
            or not _text(value.get('region_description'), 1024, True)
            or not _file_name(value.get('electrodes_file'))
            or not _v3_valid(value)
        ):
            raise ValueError('坐标来源说明格式无效')
        out = dict(value)
        out['region_index_base'] = 0
        out['conversion'] = dict(value['conversion']) if value['conversion'] is not None else None
        out['region_assignment'] = dict(value['region_assignment'])
        return out
    v2 = _plain(value) and value.get('schema') == 'electrode-coordinate-source/2'
    if (
        not _plain(value)
        or not (v2 or value.get('schema') == 'electrode-coordinate-source/1')
        or not _keys_equal(value, (*_COMMON, 'conversion') if v2 else _COMMON)
        or not (value.get('format') == 'bids-electrodes/1' or (v2 and value.get('format') == 'electrode-labels/1'))
        or value.get('coordinate_system') != 'ernie_native_mm'
        or value.get('unit') != 'mm'
        or not _same_zero(value.get('region_index_base'))
        or not _text(value.get('coordinate_system_description'), 2048, True)
        or not _text(value.get('region_description'), 1024, True)
        or not _file_name(value.get('electrodes_file'))
        or not (value.get('coordsystem_file') is None if value.get('format') == 'electrode-labels/1'
                else _file_name(value.get('coordsystem_file')))
        or (v2 and not _conversion_valid(value.get('conversion'), value['format']))
    ):
        raise ValueError('坐标来源说明格式无效')
    out = dict(value)
    out['region_index_base'] = 0
    if v2:
        out['conversion'] = dict(value['conversion'])
    return out


def coordinate_source_files(source: dict[str, Any]) -> str:
    files = ' + '.join(x for x in (source.get('electrodes_file'), source.get('coordsystem_file')) if x)
    conv = source.get('conversion')
    return f"{files} · {conv['input_coordinate_system']} → Ernie" if conv else files
