"""BIDS electrode pairs and 10-05 label lists (``webapp/lib/bids-electrodes.ts``, U12, U13)."""
from __future__ import annotations

import math
import re
from typing import Any, Optional

from ..schemas import jsjson
from . import jsmath
from .coordinate_source import (
    LABEL_CAP, MNI_COORDINATE_SYSTEMS, MNI_IMPORT_LIMIT_MM, validate_coordinate_source,
)
from .design_file import validate_design
from .ernie_mni import ErnieMniSurface, ernie_to_mni, load_mapping, mni_to_ernie
from .head_registration import UNIT_MM, imported_regions, place_on_ernie

__all__ = [
    'POSITION_PROVENANCE', 'bids_needs_mni_surface', 'parse_bids_electrodes',
    'export_bids_electrodes', 'export_mni_bids_electrodes', 'parse_electrode_labels',
]

REGION_DESCRIPTION = (
    'EEGLayoutLab balanced region index, numbered continuously from zero. Supported region counts: 1, 2, 3, 4, or 6.'
)
COORDINATE_DESCRIPTION = 'Ernie native coordinate frame used by EEGLayoutLab, in millimetres.'
POSITION_PROVENANCE = (
    'Electrode positions of an EEGLayoutLab layout on the Ernie template head (SimNIBS example dataset v4.1). '
    'They are design or template positions, not positions digitized on a participant.'
)
MNI_DESCRIPTION = (
    'FSL MNI152 nonlinear 6th-generation template space (SimNIBS MNI152_T1_1mm), in millimetres. '
    'Mapped from Ernie native coordinates with the SimNIBS nonlinear Ernie-to-MNI warp sampled on the Ernie scalp.'
)
PAIR_ERROR = '请成对选择electrodes.tsv和coordsystem.json，每个文件不超过64 KB。'
HEAD_COLUMNS = ('type', 'material', 'impedance', 'group', 'hemisphere')
_NUMBER_TEXT = re.compile(r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$')
_ELECTRODES_TSV_RE = re.compile(r'(?:^|_)electrodes\.tsv$')
_COORDSYSTEM_JSON_RE = re.compile(r'(?:^|_)coordsystem\.json$')
_ELECTRODES_JSON_RE = re.compile(r'(?:^|_)electrodes\.json$')
_EEG_TYPE_RE = re.compile(r'^eeg$', re.IGNORECASE)
_LABEL_EXT_RE = re.compile(r'\.(?:tsv|csv|txt)$', re.IGNORECASE)


def _utf8_bytes_len(text: str) -> int:
    # TextEncoder().encode(str): lone surrogates become U+FFFD (3 bytes in UTF-8).
    return len(text.encode('utf-16-le', errors='surrogatepass').decode('utf-16-le', errors='replace').encode('utf-8'))


def _landmarks_block(frame: str, mapping: dict[str, Any]) -> dict[str, Any]:
    points = mapping['landmarks']['native_mm' if frame == 'native' else 'mni_mm']
    mni_sys = mapping['mni']['coordinate_system']
    return {
        'AnatomicalLandmarkCoordinates': {'NAS': points['Nz'], 'LPA': points['LPA'], 'RPA': points['RPA']},
        'AnatomicalLandmarkCoordinateSystem': 'Other' if frame == 'native' else mni_sys,
        'AnatomicalLandmarkCoordinateUnits': 'mm',
        'AnatomicalLandmarkCoordinateSystemDescription': (
            'SimNIBS template landmarks mapped to Ernie by charm (eeg_positions/Fiducials.csv), '
            'in the Ernie native frame. Not digitized.'
            if frame == 'native'
            else 'SimNIBS MNI template landmarks (resources/ElectrodeCaps_MNI/Fiducials.csv). Not digitized.'
        ),
    }


def _coordinate_pair(files: list[dict[str, str]]) -> dict[str, Any]:
    if len(files) < 2 or len(files) > 3 or any(_utf8_bytes_len(f['text']) > 65536 for f in files):
        raise ValueError(PAIR_ERROR)
    electrodes = next((f for f in files if _ELECTRODES_TSV_RE.search(f['name'])), None)
    coordsystem = next((f for f in files if _COORDSYSTEM_JSON_RE.search(f['name'])), None)
    metadata = next((f for f in files if _ELECTRODES_JSON_RE.search(f['name'])), None)
    if (
        electrodes is None
        or coordsystem is None
        or len({f['name'] for f in files}) != len(files)
        or any(f is not electrodes and f is not coordsystem and f is not metadata for f in files)
    ):
        raise ValueError(PAIR_ERROR)
    prefix = electrodes['name'][:-len('electrodes.tsv')]
    if coordsystem['name'] != prefix + 'coordsystem.json' or (
        metadata is not None and metadata['name'] != prefix + 'electrodes.json'
    ):
        raise ValueError('BIDS坐标文件的名称前缀必须一致。')
    system = jsjson.parse(coordsystem['text'])
    if not isinstance(system, dict):
        raise ValueError('coordsystem.json须是JSON对象。')
    return {'electrodes': electrodes, 'coordsystem': coordsystem, 'metadata': metadata, 'system': system}


def bids_needs_mni_surface(files: list[dict[str, str]]) -> bool:
    try:
        system = _coordinate_pair(files)['system']
        eeg_sys = system.get('EEGCoordinateSystem')
        return (
            (isinstance(eeg_sys, str) and eeg_sys in MNI_COORDINATE_SYSTEMS)
            or (
                'EEGLayoutLabCoordinateSystem' not in system
                and eeg_sys != 'Other'
                and isinstance(system.get('AnatomicalLandmarkCoordinates'), dict)
            )
        )
    except Exception:  # noqa: BLE001
        return False


def _head_landmarks(system: dict[str, Any]) -> Optional[dict[str, list[float]]]:
    coordinates = system.get('AnatomicalLandmarkCoordinates')
    if not isinstance(coordinates, dict):
        return None

    def read(keys: tuple[str, ...]) -> Optional[list[float]]:
        val = next((coordinates[k] for k in keys if k in coordinates), None)
        if isinstance(val, list) and len(val) == 3 and all(jsjson.is_number(v) and math.isfinite(float(v)) for v in val):
            return [float(v) for v in val]
        return None

    nas = read(('NAS', 'Nasion', 'NZ', 'Nz'))
    lpa = read(('LPA',))
    rpa = read(('RPA',))
    if nas is None or lpa is None or rpa is None:
        return None
    if ('AnatomicalLandmarkCoordinateSystem' in system
            and system['AnatomicalLandmarkCoordinateSystem'] != system.get('EEGCoordinateSystem')):
        raise ValueError('基准点坐标系须与电极坐标系一致。')
    if ('AnatomicalLandmarkCoordinateUnits' in system
            and system['AnatomicalLandmarkCoordinateUnits'] != system.get('EEGCoordinateUnits')):
        raise ValueError('基准点单位须与电极坐标单位一致。')
    return {'NAS': nas, 'LPA': lpa, 'RPA': rpa}


def parse_bids_electrodes(
    files: list[dict[str, str]],
    surface: Optional[ErnieMniSurface] = None,
    *,
    region_count: Optional[int] = None,
    root: Optional[str] = None,
) -> dict[str, Any]:
    """``parseBIDSElectrodes`` from ``webapp/lib/bids-electrodes.ts``."""
    pair = _coordinate_pair(files)
    electrodes, coordsystem, metadata, system = (
        pair['electrodes'], pair['coordsystem'], pair['metadata'], pair['system']
    )
    eeg_sys = system.get('EEGCoordinateSystem')
    lab_sys = system.get('EEGLayoutLabCoordinateSystem')
    sys_desc = system.get('EEGCoordinateSystemDescription')
    native = (
        eeg_sys == 'Other'
        and lab_sys == 'ernie_native_mm'
        and isinstance(sys_desc, str)
        and bool(jsjson.js_trim(sys_desc))
    )
    mni = isinstance(eeg_sys, str) and eeg_sys in MNI_COORDINATE_SYSTEMS and 'EEGLayoutLabCoordinateSystem' not in system
    head = (
        _head_landmarks(system)
        if (not native and not mni and 'EEGLayoutLabCoordinateSystem' not in system
            and isinstance(eeg_sys, str) and bool(jsjson.js_trim(eeg_sys)))
        else None
    )
    if not native and not mni and head is None:
        raise ValueError(
            '仅接受显式声明Ernie原生坐标系、MNI模板空间（如MNI152NLin6Asym），或带NAS/LPA/RPA基准点的头坐标系（如CapTrak）的文件。'
        )
    if mni and surface is None:
        raise ValueError('MNI坐标需要先读取Ernie–MNI映射数据。')
    if head is not None and surface is None:
        raise ValueError('头坐标配准需要先读取Ernie头皮数据。')
    eeg_units = system.get('EEGCoordinateUnits')
    if (eeg_units not in ('mm', 'cm', 'm')) if head is not None else (eeg_units != 'mm'):
        raise ValueError(
            '头坐标的EEGCoordinateUnits须为mm、cm或m。'
            if head is not None
            else 'BIDS坐标接口目前只接受明确的mm单位，不执行单位推断或换算。'
        )
    raw_tsv = electrodes['text'].replace('\r\n', '\n').rstrip('\n')
    lines = raw_tsv.split('\n') if raw_tsv or electrodes['text'] == '' else ['']
    header = lines.pop(0).split('\t') if lines else None
    has_region = bool(header and 'region' in header)
    if not header or ','.join(header[:4]) != 'name,x,y,z' or (not has_region and not region_count):
        raise ValueError(
            'electrodes.tsv须包含name、x、y、z和明确分配的region列；没有region列时请选择区域数，由软件按空间位置均衡分区。'
        )
    allowed = {'name', 'x', 'y', 'z', 'region', *(HEAD_COLUMNS if head is not None else ())}
    base_val = system.get('EEGLayoutLabRegionIndexBase')
    base_zero = jsjson.is_number(base_val) and float(base_val) == 0.0
    if len(set(header)) != len(header) or any(col not in allowed for col in header) or (has_region and not base_zero):
        raise ValueError('region列须使用本软件的零基区域扩展，并声明EEGLayoutLabRegionIndexBase为0。')
    description = system.get('EEGLayoutLabRegionDescription')
    if has_region:
        if metadata is not None:
            cols = jsjson.parse(metadata['text'])
            if (not isinstance(cols, dict) or not isinstance(cols.get('region'), dict)
                    or not isinstance(cols['region'].get('Description'), str)):
                raise ValueError('electrodes.json须说明region列的含义。')
            description = cols['region']['Description']
        if not isinstance(description, str) or not jsjson.js_trim(description):
            raise ValueError('请在electrodes.json或EEGLayoutLabRegionDescription中说明region列。')
    rows = [line.split('\t') for line in lines]
    if head is not None:
        type_idx = header.index('type') if 'type' in header else -1
        filtered = []
        for row in rows:
            has_non_eeg_type = (
                type_idx >= 0 and type_idx < len(row) and row[type_idx]
                and not _EEG_TYPE_RE.match(jsjson.js_trim(row[type_idx]))
            )
            all_na = row[1:4] == ['n/a', 'n/a', 'n/a']
            if not has_non_eeg_type and not all_na:
                filtered.append(row)
        rows = filtered
    region_idx = header.index('region') if has_region else -1
    if (
        len(rows) != 64
        or any(
            len(row) != len(header)
            or not jsjson.js_trim(row[0])
            or any(not _NUMBER_TEXT.match(v) for v in row[1:4])
            or (region_idx >= 0 and not _NUMBER_TEXT.match(row[region_idx]))
            for row in rows
        )
    ):
        raise ValueError(
            f'本软件的布局固定为64个电极；文件中有{len(rows)}个带坐标的EEG电极，且不接受n/a坐标。'
            if head is not None
            else 'BIDS坐标文件需要64个命名电极和完整数值；不接受n/a坐标。'
        )
    names = [row[0] for row in rows]
    inp_xyz = [[jsmath.js_number(v) for v in row[1:4]] for row in rows]
    file_regions = [int(jsmath.js_number(row[region_idx])) for row in rows] if has_region else None
    raw_design_name = system.get('EEGLayoutLabDesignName')
    design_name = raw_design_name if isinstance(raw_design_name, str) else electrodes['name']
    base_design = {
        'schema': 'eeg-electrode-design/1',
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'name': design_name,
        'electrode_names': names,
    }
    if head is not None:
        if len({n.lower() for n in names}) != 64:
            raise ValueError('电极名称不能重复。')
        scale = UNIT_MM[eeg_units]
        to_mm = lambda p: [p[0] * scale, p[1] * scale, p[2] * scale]  # noqa: E731
        placed = place_on_ernie(
            [to_mm(p) for p in inp_xyz],
            {'NAS': to_mm(head['NAS']), 'LPA': to_mm(head['LPA']), 'RPA': to_mm(head['RPA'])},
            surface,
            {'coordinate_system': eeg_sys, 'unit': eeg_units, 'landmark_source': 'coordsystem', 'names': names},
            root=root,
        )
        regs = imported_regions(placed['xyz'], file_regions, region_count, description)
        source = {
            'schema': 'electrode-coordinate-source/3',
            'format': 'bids-electrodes/1',
            'electrodes_file': electrodes['name'],
            'coordsystem_file': coordsystem['name'],
            'coordinate_system': 'ernie_native_mm',
            'unit': 'mm',
            'coordinate_system_description': placed['description'],
            'region_index_base': 0,
            'region_description': regs['region_description'],
            'conversion': placed['conversion'],
            'region_assignment': regs['region_assignment'],
        }
        return validate_design({
            **base_design,
            'xyz_mm': placed['xyz'],
            'region_indices': regs['region_indices'],
            'source_metadata': source,
        })

    xyz = inp_xyz
    conversion = None
    frame_description = sys_desc
    if mni:
        assert surface is not None
        mapping = surface.mapping
        mni_export_sys = mapping['mni']['coordinate_system']
        mapped = mni_to_ernie(inp_xyz, surface)
        dists = mapped['distances_mm']
        maximum = max(dists)
        worst = dists.index(maximum)
        if maximum > MNI_IMPORT_LIMIT_MM:
            raise ValueError(
                f'电极{names[worst]}距Ernie头皮的MNI映射面{jsmath.to_fixed(maximum, 1)} mm，'
                f'超过{MNI_IMPORT_LIMIT_MM} mm。请检查坐标系和单位。'
            )
        xyz = mapped['points']
        diff_note = (
            '' if eeg_sys == mni_export_sys
            else f' (the warp targets {mni_export_sys}; differences between MNI templates are not modelled)'
        )
        frame_description = (
            f'{eeg_sys} coordinates mapped to the Ernie native frame (mm) on the scalp with the SimNIBS nonlinear '
            f'Ernie-MNI warp{diff_note}. Largest distance from the warped Ernie scalp: '
            f'{jsmath.to_fixed(maximum, 2)} mm.'
        )
        conversion = {
            'method': 'ernie-mni-scalp/1',
            'mapping_id': mapping['mapping_id'],
            'input_coordinate_system': eeg_sys,
            'input_unit': 'mm',
            'max_surface_distance_mm': maximum,
        }
    if file_regions is None:
        regs = imported_regions(xyz, None, region_count)
        source = {
            'schema': 'electrode-coordinate-source/3',
            'format': 'bids-electrodes/1',
            'electrodes_file': electrodes['name'],
            'coordsystem_file': coordsystem['name'],
            'coordinate_system': 'ernie_native_mm',
            'unit': 'mm',
            'coordinate_system_description': frame_description,
            'region_index_base': 0,
            'region_description': regs['region_description'],
            'conversion': conversion,
            'region_assignment': regs['region_assignment'],
        }
        return validate_design({
            **base_design,
            'xyz_mm': xyz,
            'region_indices': regs['region_indices'],
            'source_metadata': source,
        })
    if mni:
        source = {
            'schema': 'electrode-coordinate-source/2',
            'format': 'bids-electrodes/1',
            'electrodes_file': electrodes['name'],
            'coordsystem_file': coordsystem['name'],
            'coordinate_system': 'ernie_native_mm',
            'unit': 'mm',
            'coordinate_system_description': frame_description,
            'region_index_base': 0,
            'region_description': description,
            'conversion': conversion,
        }
        return validate_design({
            **base_design,
            'xyz_mm': xyz,
            'region_indices': file_regions,
            'source_metadata': source,
        })
    source = {
        'schema': 'electrode-coordinate-source/1',
        'format': 'bids-electrodes/1',
        'electrodes_file': electrodes['name'],
        'coordsystem_file': coordsystem['name'],
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'coordinate_system_description': frame_description,
        'region_index_base': 0,
        'region_description': description,
    }
    preserved = (
        source
        if 'EEGLayoutLabSourceMetadata' not in system
        else validate_coordinate_source(system['EEGLayoutLabSourceMetadata'])
    )
    if (
        (preserved['schema'] == 'electrode-coordinate-source/1'
         and preserved['coordinate_system_description'] != source['coordinate_system_description'])
        or preserved['region_description'] != source['region_description']
    ):
        raise ValueError('坐标来源说明与当前文件声明不一致。')
    return validate_design({
        **base_design,
        'xyz_mm': inp_xyz,
        'region_indices': file_regions,
        'source_metadata': preserved,
    })


def _tsv(design: dict[str, Any], points: list[list[float]]) -> str:
    names = design.get('electrode_names')
    lines = ['name\tx\ty\tz\tregion']
    for idx, pt in enumerate(points):
        nm = names[idx] if names else f'E{idx + 1}'
        coords = '\t'.join(jsjson.number_to_string(float(v)) for v in pt)
        lines.append(f"{nm}\t{coords}\t{design['region_indices'][idx]}")
    return '\n'.join(lines) + '\n'


def export_bids_electrodes(inp: dict[str, Any], *, root: Optional[str] = None) -> list[dict[str, str]]:
    """``exportBIDSElectrodes`` from ``webapp/lib/bids-electrodes.ts``."""
    design = validate_design(inp)
    mapping = load_mapping(root)
    source = design.get('source_metadata')
    regions = source['region_description'] if source else REGION_DESCRIPTION
    description = (
        source['coordinate_system_description']
        if source and source.get('schema') == 'electrode-coordinate-source/1'
        else COORDINATE_DESCRIPTION
    )
    system: dict[str, Any] = {
        'EEGCoordinateSystem': 'Other',
        'EEGCoordinateUnits': 'mm',
        'EEGCoordinateSystemDescription': description,
        **_landmarks_block('native', mapping),
        'EEGLayoutLabCoordinateSystem': 'ernie_native_mm',
        'EEGLayoutLabPositionProvenance': POSITION_PROVENANCE,
        'EEGLayoutLabRegionIndexBase': 0,
        'EEGLayoutLabRegionDescription': regions,
        'EEGLayoutLabDesignName': design['name'],
    }
    if source is not None:
        system['EEGLayoutLabSourceMetadata'] = source
    return [
        {'name': 'electrodes.tsv', 'text': _tsv(design, design['xyz_mm'])},
        {'name': 'coordsystem.json', 'text': jsjson.stringify(system, indent=2) + '\n'},
        {'name': 'electrodes.json', 'text': jsjson.stringify({'region': {'Description': regions}}, indent=2) + '\n'},
    ]


def export_mni_bids_electrodes(inp: dict[str, Any], surface: ErnieMniSurface) -> list[dict[str, str]]:
    """``exportMniBIDSElectrodes`` from ``webapp/lib/bids-electrodes.ts``."""
    design = validate_design(inp)
    mapping = surface.mapping
    native_limit = float(mapping['method']['native_export_limit_mm'])
    mni_export_sys = mapping['mni']['coordinate_system']
    source = design.get('source_metadata')
    regions = source['region_description'] if source else REGION_DESCRIPTION
    mapped = ernie_to_mni(design['xyz_mm'], surface)
    dists = mapped['distances_mm']
    maximum = max(dists)
    worst = dists.index(maximum)
    if maximum > native_limit:
        names = design.get('electrode_names')
        label = names[worst] if names else f'E{worst + 1}'
        raise ValueError(
            f'电极{label}距可换算的Ernie头皮{jsmath.to_fixed(maximum, 1)} mm，'
            f'超过{jsjson.number_to_string(native_limit)} mm（下颌、耳部和颈部不在MNI换算范围内）。'
        )
    prefix = f'space-{mni_export_sys}_'
    system = {
        'EEGCoordinateSystem': mni_export_sys,
        'EEGCoordinateUnits': 'mm',
        'EEGCoordinateSystemDescription': MNI_DESCRIPTION,
        **_landmarks_block('mni', mapping),
        'EEGLayoutLabPositionProvenance': POSITION_PROVENANCE,
        'EEGLayoutLabMapping': {
            'method': 'ernie-mni-scalp/1',
            'mapping_id': mapping['mapping_id'],
            'max_native_scalp_distance_mm': maximum,
        },
        'EEGLayoutLabRegionIndexBase': 0,
        'EEGLayoutLabRegionDescription': regions,
        'EEGLayoutLabDesignName': design['name'],
    }
    return [
        {'name': prefix + 'electrodes.tsv', 'text': _tsv(design, mapped['points'])},
        {'name': prefix + 'coordsystem.json', 'text': jsjson.stringify(system, indent=2) + '\n'},
        {
            'name': prefix + 'electrodes.json',
            'text': jsjson.stringify({'region': {'Description': regions}}, indent=2) + '\n',
        },
    ]


def parse_electrode_labels(
    file: dict[str, str],
    *,
    region_count: Optional[int] = None,
    root: Optional[str] = None,
) -> dict[str, Any]:
    """``parseElectrodeLabels`` from ``webapp/lib/bids-electrodes.ts``."""
    name = file['name']
    if _utf8_bytes_len(file['text']) > 65536 or not _LABEL_EXT_RE.search(name) or '/' in name or '\\' in name:
        raise ValueError('请选择不超过64 KB的.tsv、.csv或.txt电极名称文件。')
    mapping = load_mapping(root)
    cap_positions = {
        str(lbl).lower(): {'label': str(lbl), 'xyz': [float(x), float(y), float(z)]}
        for lbl, x, y, z in mapping['labels']['positions_mm']
    }
    aliases: dict[str, str] = mapping['labels']['aliases']

    txt = file['text']
    if txt.startswith('\ufeff'):
        txt = txt[1:]
    txt = txt.replace('\r\n', '\n').rstrip('\n')
    lines = txt.split('\n') if txt or file['text'] == '' else ['']
    sep = '\t' if '\t' in lines[0] else ','
    header = [jsjson.js_trim(cell) for cell in lines.pop(0).split(sep)]
    names_only = (','.join(header) == 'name') and bool(region_count)
    if ','.join(header) != 'name,region' and not names_only:
        raise ValueError('电极名称文件的表头须为name和region两列；只有name列时请选择区域数，由软件按空间位置均衡分区。')
    rows = [[jsjson.js_trim(cell) for cell in line.split(sep)] for line in lines]
    if (
        len(rows) != 64
        or any(
            len(row) != len(header)
            or not row[0]
            or (not names_only and not jsmath.ASCII_DIGITS_RE.match(row[1]))
            for row in rows
        )
    ):
        raise ValueError(
            '电极名称文件需要64行，每行一个电极名称。'
            if names_only
            else '电极名称文件需要64行，每行一个电极名称和一个整数区域。'
        )
    unknown: list[str] = []
    positions: list[Optional[dict[str, Any]]] = []
    for row in rows:
        raw_lbl = row[0]
        mapped_lbl = aliases.get(raw_lbl.upper(), raw_lbl)
        found = cap_positions.get(mapped_lbl.lower())
        if found is None:
            unknown.append(raw_lbl)
        positions.append(found)
    if unknown:
        suffix = f' 等{len(unknown)}个' if len(unknown) > 5 else ''
        raise ValueError(f"10-05电极名称中没有：{', '.join(unknown[:5])}{suffix}。")
    labels = [pos['label'] for pos in positions if pos is not None]
    if len(set(labels)) != 64:
        raise ValueError('电极名称（含T3/T4/T5/T6的现名）不能重复。')
    xyz = [list(pos['xyz']) for pos in positions if pos is not None]
    conversion = {
        'method': 'cap-labels/1',
        'mapping_id': mapping['mapping_id'],
        'input_coordinate_system': LABEL_CAP,
        'input_unit': None,
        'max_surface_distance_mm': None,
    }
    description = (
        f"Positions of the named electrodes in the SimNIBS {LABEL_CAP} 10-05 cap, placed on Ernie's skin by charm "
        '(eeg_positions), in the Ernie native frame (mm). Template positions, not digitized.'
    )
    common = {
        'format': 'electrode-labels/1',
        'electrodes_file': name,
        'coordsystem_file': None,
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'coordinate_system_description': description,
        'region_index_base': 0,
    }
    regs = imported_regions(xyz, None, region_count) if names_only else None
    if regs is not None:
        source = {
            'schema': 'electrode-coordinate-source/3',
            **common,
            'region_description': regs['region_description'],
            'conversion': conversion,
            'region_assignment': regs['region_assignment'],
        }
        reg_indices = regs['region_indices']
    else:
        source = {
            'schema': 'electrode-coordinate-source/2',
            **common,
            'region_description': REGION_DESCRIPTION,
            'conversion': conversion,
        }
        reg_indices = [int(jsmath.js_number(row[1])) for row in rows]
    stem = re.sub(r'\.[^.]+$', '', name)
    return validate_design({
        'schema': 'eeg-electrode-design/1',
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'name': stem,
        'electrode_names': labels,
        'xyz_mm': xyz,
        'region_indices': reg_indices,
        'source_metadata': source,
    })
