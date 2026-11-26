"""MNE-Python ``.elc`` and EEGLAB ``.sfp`` montage exporters and readers (``webapp/lib/montage-files.ts`` &
``head-frame-import.ts``, U12).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ..schemas import jsjson
from . import jsmath
from .coordinate_source import validate_coordinate_source
from .design_file import validate_design
from .ernie_mni import ErnieMniSurface, load_mapping
from .head_registration import UNIT_MM, imported_regions, place_on_ernie

__all__ = [
    'export_mne_elc', 'export_eeglab_sfp',
    'read_mne_elc', 'read_eeglab_sfp', 'read_montage_file', 'parse_montage_file',
]

_RESERVED = frozenset({
    'nz', 'lpa', 'rpa', 'nasion', 'left', 'right', 'nazion', 'fidnz', 'fidt9', 'fidt10',
    'cms', 'drl', 'nas', 'lht', 'rht', 'lhj', 'rhj', 'headshape',
})
_LANDMARK_LABELS = {
    'nz': 'NAS', 'nas': 'NAS', 'nasion': 'NAS', 'nazion': 'NAS', 'fidnz': 'NAS',
    'lpa': 'LPA', 'left': 'LPA', 'fidt9': 'LPA',
    'rpa': 'RPA', 'right': 'RPA', 'fidt10': 'RPA',
}
_SKIPPED = frozenset({'cms', 'drl', 'lht', 'rht', 'lhj', 'rhj', 'headshape', 'gnd', 'ground'})
_NUMBER_RE = re.compile(r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$')
_JS_WS_ONE = re.compile(f'[{re.escape("".join(sorted(jsjson.JS_TRIM)))}]')
_FIELD_RE = re.compile(
    rf'^([A-Za-z0-9_]+)[{re.escape("".join(sorted(jsjson.JS_TRIM)))}]*=?[{re.escape("".join(sorted(jsjson.JS_TRIM)))}]*(.*)$'
)
_SECTION_RE = re.compile(r'^(Positions|Labels|NumberPolygons|TypePolygons|Polygons|ReferenceLabel)\b')
_INLINE_LABEL_RE = re.compile(rf'^([^:]+):[{re.escape("".join(sorted(jsjson.JS_TRIM)))}]*(.*)$')


def _ascii_lower(text: str) -> str:
    # Match JS toLowerCase on electrode/landmark names (standard Unicode lower without locale tricks).
    return text.lower()


def _montage_design(inp: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    design = validate_design(inp)
    names = design.get('electrode_names') or [f'E{i + 1}' for i in range(len(design['xyz_mm']))]
    spaced = next((n for n in names if _JS_WS_ONE.search(n)), None)
    if spaced is not None:
        raise ValueError(f'电极名称“{spaced}”含空格，MNE和EEGLAB坐标文件按空白分列；请改名后导出。')
    reserved = next((n for n in names if _ascii_lower(n) in _RESERVED), None)
    if reserved is not None:
        raise ValueError(f'电极名称“{reserved}”与基准点标签冲突，MNE或EEGLAB会把它当作基准点；请改名后导出。')
    return design, names


def _row(point: list[float]) -> str:
    return '\t'.join(jsjson.number_to_string(float(v)) for v in point)


def export_mne_elc(inp: dict[str, Any], *, root: Optional[str] = None) -> dict[str, str]:
    """``exportMneElc``: ASA ``.elc`` file."""
    design, names = _montage_design(inp)
    lm = load_mapping(root)['landmarks']['native_mm']
    points = [*design['xyz_mm'], lm['Nz'], lm['LPA'], lm['RPA']]
    labels = [*names, 'Nz', 'LPA', 'RPA']
    lines = [
        '# EEGLayoutLab layout on the Ernie template head (SimNIBS example dataset v4.1): '
        'design or template coordinates, not digitized.',
        '# Ernie native frame: x right, y anterior, z superior. Nz, LPA and RPA are template landmarks.',
        'ReferenceLabel\tavg',
        'UnitPosition\tmm',
        f'NumberPositions=\t{len(points)}',
        'Positions',
        *(_row(p) for p in points),
        'Labels',
        *labels,
        '',
    ]
    return {'name': 'electrodes.elc', 'text': '\n'.join(lines)}


def export_eeglab_sfp(inp: dict[str, Any], *, root: Optional[str] = None) -> dict[str, str]:
    """``exportEeglabSfp``: BESA/EGI ``.sfp`` file."""
    design, names = _montage_design(inp)
    lm = load_mapping(root)['landmarks']['native_mm']
    rows = [
        ('FidNz', lm['Nz']),
        ('FidT9', lm['LPA']),
        ('FidT10', lm['RPA']),
        *zip(names, design['xyz_mm']),
    ]
    return {
        'name': 'electrodes.sfp',
        'text': '\n'.join(f'{label}\t{_row(pt)}' for label, pt in rows) + '\n',
    }


def _coordinates(cells: list[str]) -> list[float]:
    if len(cells) != 3 or not all(_NUMBER_RE.match(c) for c in cells):
        raise ValueError('坐标行须包含3个数值。')
    return [jsmath.js_number(c) for c in cells]


def _collect(fmt: str, labels: list[str], points: list[list[float]], unit: Optional[str]) -> dict[str, Any]:
    if len(labels) != len(points):
        raise ValueError('电极名称数与坐标数不一致。')
    names: list[str] = []
    pts: list[list[float]] = []
    landmarks: dict[str, list[float]] = {}
    for label, pt in zip(labels, points):
        key = _ascii_lower(label)
        lm = _LANDMARK_LABELS.get(key)
        if lm:
            if lm in landmarks:
                raise ValueError(f'基准点{lm}重复。')
            landmarks[lm] = pt
        elif key not in _SKIPPED and not key.startswith('hpi'):
            names.append(label)
            pts.append(pt)
    return {'format': fmt, 'names': names, 'points': pts, 'landmarks': landmarks, 'unit': unit}


def _split_lines_crlf(text: str) -> list[str]:
    if text.startswith('\ufeff'):
        text = text[1:]
    return text.replace('\r\n', '\n').replace('\r', '\n').split('\n')


def read_mne_elc(file: dict[str, str]) -> dict[str, Any]:
    raw_lines = _split_lines_crlf(file['text'])
    lines = []
    for line in raw_lines:
        stripped = jsjson.js_trim(line.split('#', 1)[0])
        if stripped:
            lines.append(stripped)
    unit: Optional[str] = None
    count: Optional[float] = None
    section = ''
    points: list[list[float]] = []
    labels: list[str] = []
    inline: list[str] = []
    for line in lines:
        field_m = _FIELD_RE.match(line)
        if field_m and field_m.group(1) == 'UnitPosition':
            val = field_m.group(2)
            if val not in ('mm', 'cm', 'm'):
                raise ValueError('.elc的UnitPosition须为mm、cm或m。')
            unit = val
            continue
        if field_m and field_m.group(1) == 'NumberPositions':
            count = jsmath.js_number(field_m.group(2))
            continue
        if _SECTION_RE.match(line):
            section = jsmath.JS_WHITESPACE_RE.split(line)[0]
            continue
        if section == 'Positions':
            labelled = _INLINE_LABEL_RE.match(line)
            if labelled:
                inline.append(jsjson.js_trim(labelled.group(1)))
                rest = labelled.group(2)
            else:
                rest = line
            points.append(_coordinates(jsmath.JS_WHITESPACE_RE.split(rest) if rest else ['']))
        elif section == 'Labels':
            labels.extend(jsmath.JS_WHITESPACE_RE.split(line))
    if not unit:
        raise ValueError('.elc文件缺少UnitPosition，无法确定单位。')
    if count is None or math.isnan(count) or len(points) != count:
        raise ValueError('.elc的NumberPositions与坐标行数不一致。')
    return _collect('mne-elc/1', labels if labels else inline, points, unit)


def read_eeglab_sfp(file: dict[str, str]) -> dict[str, Any]:
    raw_lines = _split_lines_crlf(file['text'])
    rows = []
    for line in raw_lines:
        trimmed = jsjson.js_trim(line)
        if trimmed:
            rows.append(jsmath.JS_WHITESPACE_RE.split(trimmed))
    if any(len(r) != 4 for r in rows):
        raise ValueError('.sfp每行须为名称和x、y、z三个数值。')
    return _collect('eeglab-sfp/1', [r[0] for r in rows], [_coordinates(r[1:]) for r in rows], None)


def read_montage_file(file: dict[str, str]) -> dict[str, Any]:
    name = file['name']
    if len(file['text'].encode('utf-8', errors='surrogatepass')) > 65536 or '/' in name or '\\' in name:
        raise ValueError('电极坐标文件不超过64 KB。')
    lower = name.lower()
    if lower.endswith('.elc'):
        return read_mne_elc(file)
    if lower.endswith('.sfp'):
        return read_eeglab_sfp(file)
    raise ValueError('请选择.elc或.sfp电极坐标文件。')


def parse_montage_file(
    file: dict[str, str],
    surface: Optional[ErnieMniSurface],
    *,
    unit: Optional[str] = None,
    region_count: Optional[int] = None,
    root: Optional[str] = None,
) -> dict[str, Any]:
    """``parseMontageFile`` from ``webapp/lib/head-frame-import.ts``."""
    read = read_montage_file(file)
    chosen_unit = read['unit'] if read['unit'] is not None else unit
    if not chosen_unit:
        raise ValueError('.sfp文件没有单位字段，请选择坐标单位（mm、cm或m）。')
    if read['unit'] and unit and unit != read['unit']:
        raise ValueError(f"文件声明的单位是{read['unit']}，与所选单位不一致。")
    if len(read['points']) != 64:
        raise ValueError(f"本软件的布局固定为64个电极；文件中有{len(read['points'])}个电极（不含基准点、参考和地线）。")
    if len({_ascii_lower(n) for n in read['names']}) != 64:
        raise ValueError('电极名称不能重复。')
    missing = [n for n in ('NAS', 'LPA', 'RPA') if n not in read['landmarks']]
    if missing:
        raise ValueError(f"文件缺少基准点{'、'.join(missing)}（如Nz/LPA/RPA或FidNz/FidT9/FidT10），无法放到Ernie头上。")
    scale = UNIT_MM[chosen_unit]
    to_mm = lambda p: [p[0] * scale, p[1] * scale, p[2] * scale]  # noqa: E731
    lm = {n: to_mm(read['landmarks'][n]) for n in ('NAS', 'LPA', 'RPA')}
    placed = place_on_ernie(
        [to_mm(p) for p in read['points']],
        lm,
        surface,
        {
            'coordinate_system': 'ASA .elc head frame' if read['format'] == 'mne-elc/1' else 'BESA/EGI .sfp head frame',
            'unit': chosen_unit,
            'landmark_source': 'file',
            'names': read['names'],
        },
        root=root,
    )
    regions = imported_regions(placed['xyz'], None, region_count)
    source = validate_coordinate_source({
        'schema': 'electrode-coordinate-source/3',
        'format': read['format'],
        'electrodes_file': file['name'],
        'coordsystem_file': None,
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'coordinate_system_description': placed['description'],
        'region_index_base': 0,
        'region_description': regions['region_description'],
        'conversion': placed['conversion'],
        'region_assignment': regions['region_assignment'],
    })
    stem = re.sub(r'\.[^.]+$', '', file['name'])
    return validate_design({
        'schema': 'eeg-electrode-design/1',
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'name': stem,
        'electrode_names': read['names'],
        'xyz_mm': placed['xyz'],
        'region_indices': regions['region_indices'],
        'source_metadata': source,
    })
