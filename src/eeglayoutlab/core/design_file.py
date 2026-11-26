"""Electrode design validation and CSV/JSON parsing (``webapp/lib/design-decision.ts``, U12)."""
from __future__ import annotations

import math
import re
from typing import Any

from ..schemas import jsjson
from . import jsmath
from .coordinate_source import validate_coordinate_source

__all__ = ['validate_design', 'scientific_design', 'design_csv', 'parse_design']

_CSV_QUOTE_RE = re.compile(r'[",\r\n]')


def _finite(n: Any) -> bool:
    return jsjson.is_number(n) and math.isfinite(float(n))


def _utf16_codes(value: str) -> list[int]:
    data = value.encode('utf-16-le', errors='surrogatepass')
    return [data[i] | (data[i + 1] << 8) for i in range(0, len(data), 2)]


def _has_name_control(value: str) -> bool:
    return any(code < 32 or code == 127 for code in _utf16_codes(value))


def _point_key(p: list[float]) -> str:
    return ','.join(jsjson.number_to_string(float(v)) for v in p)


def validate_design(inp: Any) -> dict[str, Any]:
    """``validateDesign(input)`` from ``webapp/lib/design-decision.ts``."""
    if (
        not isinstance(inp, dict)
        or inp.get('schema') != 'eeg-electrode-design/1'
        or inp.get('coordinate_system') != 'ernie_native_mm'
        or inp.get('unit') != 'mm'
    ):
        raise ValueError('坐标须为本App的Ernie原生毫米坐标；请使用导出模板。其他头模或坐标系需先完成配准。')
    xyz = inp.get('xyz_mm')
    if (
        not isinstance(xyz, list)
        or len(xyz) != 64
        or any(not isinstance(p, list) or len(p) != 3 or not all(_finite(v) for v in p) for p in xyz)
    ):
        raise ValueError('需要64行有限数值坐标，每行包含x、y、z。')
    if len({_point_key(p) for p in xyz}) != 64:
        raise ValueError('64个电极坐标必须互不重复。')
    if any(abs(float(v)) > 500.0 for p in xyz for v in p):
        raise ValueError('坐标超出Ernie毫米坐标输入范围，请检查单位和配准。')
    regions = inp.get('region_indices')
    if not isinstance(regions, list):
        raise ValueError('需要区域标签数组。')
    distinct = {int(float(v)) if jsjson.is_integer(v) else repr(v) for v in regions}
    r = len(distinct)
    if (
        r not in (1, 2, 3, 4, 6)
        or len(regions) != 64
        or any(not jsjson.is_integer(v) or float(v) < 0 or float(v) >= r for v in regions)
    ):
        raise ValueError('区域标签须从0连续编号，区域数量为1、2、3、4或6。')
    int_regions = [int(float(v)) for v in regions]
    counts = sorted((sum(1 for n in int_regions if n == i) for i in range(r)), reverse=True)
    if any(counts[i] != (64 // r + (1 if i < 64 % r else 0)) for i in range(r)):
        raise ValueError('每区电极数须均衡分配，总数64。')
    has_names = 'electrode_names' in inp and inp['electrode_names'] is not None
    if 'electrode_names' in inp and inp['electrode_names'] is None:
        # JSON null is not undefined: Array.isArray(null) is false in JS!
        raise ValueError('需要64个不重复的电极名称，每个名称最多128个字符且不含控制字符。')
    if has_names:
        names = inp['electrode_names']
        if (
            not isinstance(names, list)
            or len(names) != 64
            or len({n for n in names if isinstance(n, str)}) != 64
            or any(
                not isinstance(n, str)
                or not jsjson.js_trim(n)
                or len(_utf16_codes(n)) > 128
                or _has_name_control(n)
                for n in names
            )
        ):
            raise ValueError('需要64个不重复的电极名称，每个名称最多128个字符且不含控制字符。')
    raw_name = inp.get('name')
    name = jsjson.slice_utf16(raw_name, 100) if isinstance(raw_name, str) else '导入布局'
    out: dict[str, Any] = {
        'schema': 'eeg-electrode-design/1',
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'name': name,
        'xyz_mm': [[float(v) for v in p] for p in xyz],
        'region_indices': int_regions,
    }
    if has_names:
        out['electrode_names'] = list(inp['electrode_names'])
    if 'source_metadata' in inp:
        out['source_metadata'] = validate_coordinate_source(inp['source_metadata'])
    return out


def scientific_design(design: dict[str, Any]) -> dict[str, Any]:
    validated = validate_design(design)
    validated.pop('electrode_names', None)
    validated.pop('source_metadata', None)
    return validated


def _js_str(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return jsjson.number_to_string(value)
    return str(value)


def design_csv(design: dict[str, Any]) -> str:
    """``designCSV`` from ``webapp/lib/design-decision.ts``."""
    names = design.get('electrode_names')
    lines = [
        '# coordinate_system=ernie_native_mm; unit=mm; region=zero_based',
        'electrode,region,x_mm,y_mm,z_mm',
    ]
    for i, p in enumerate(design['xyz_mm']):
        el_name = names[i] if names else f'E{i + 1}'
        cells = []
        for val in (el_name, design['region_indices'][i], p[0], p[1], p[2]):
            cell = _js_str(val)
            if _CSV_QUOTE_RE.search(cell) or jsjson.js_trim(cell) != cell:
                cell = '"' + cell.replace('"', '""') + '"'
            cells.append(cell)
        lines.append(','.join(cells))
    return '\n'.join(lines)


def _trim_start(text: str) -> str:
    i = 0
    while i < len(text) and text[i] in jsjson.JS_TRIM:
        i += 1
    return text[i:]


def parse_design(text: str, name: str = '导入布局') -> dict[str, Any]:
    """``parseDesign(text, name)`` from ``webapp/lib/design-decision.ts``."""
    if _trim_start(text).startswith('{'):
        return validate_design(jsjson.parse(text))
    normalized = text.replace('\r\n', '\n').rstrip('\n')
    rows = normalized.split('\n') if normalized or text == '' else ['']
    first = rows.pop(0) if rows else None
    second = rows.pop(0) if rows else None
    if (
        first is None
        or jsjson.js_trim(first) != '# coordinate_system=ernie_native_mm; unit=mm; region=zero_based'
        or second is None
        or jsjson.js_trim(second) != 'electrode,region,x_mm,y_mm,z_mm'
    ):
        raise ValueError('CSV须包含模板的坐标系声明和表头。')
    parsed_cells: list[list[str]] = []
    for row in rows:
        cells: list[str] = []
        value = ''
        quoted = False
        closed = False
        i = 0
        while i < len(row):
            c = row[i]
            if quoted:
                if c == '"' and i + 1 < len(row) and row[i + 1] == '"':
                    value += '"'
                    i += 1
                elif c == '"':
                    quoted = False
                    closed = True
                else:
                    value += c
            elif c == ',':
                cells.append(value)
                value = ''
                closed = False
            elif c == '"' and not value and not closed:
                quoted = True
            else:
                if closed or c == '"':
                    raise ValueError('CSV引号格式无效。')
                value += c
            i += 1
        if quoted:
            raise ValueError('CSV引号格式无效。')
        cells.append(value)
        parsed_cells.append(cells)
    if (
        any(len(p) != 5 or any(not jsjson.js_trim(x) for x in p) for p in parsed_cells)
        or len({p[0] for p in parsed_cells}) != 64
    ):
        raise ValueError('CSV需要64行不重复的电极名称和完整数值。')
    return validate_design({
        'schema': 'eeg-electrode-design/1',
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'name': name,
        'xyz_mm': [[jsmath.js_number(x) for x in p[2:]] for p in parsed_cells],
        'region_indices': [jsmath.js_number(p[1]) for p in parsed_cells],
        'electrode_names': [p[0] for p in parsed_cells],
    })
