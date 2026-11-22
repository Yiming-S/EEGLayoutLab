import { LABEL_CAP, MNI_COORDINATE_SYSTEMS, validateCoordinateSource } from '../contracts/coordinate-source.mjs';
import type { CoordinateConversion, CoordinateSourceMetadata } from '../contracts/coordinate-source';
import { validateDesign, type ElectrodeDesign } from './design-decision.ts';
import { ERNIE_MNI_MAPPING, MAPPING_ID, MNI_EXPORT_SYSTEM, MNI_IMPORT_LIMIT_MM, NATIVE_EXPORT_LIMIT_MM, ernieToMni, mniToErnie,
  type ErnieMniSurface, type Point } from './ernie-mni.ts';
import type { Landmarks } from './head-registration.ts';
import { UNIT_MM, importedRegions, placeOnErnie, type RegionCount } from './head-frame-import.ts';
import type { MontageUnit } from './montage-files.ts';

export type CoordinateFile = { name: string; text: string };
const regionDescription = 'EEGLayoutLab balanced region index, numbered continuously from zero. Supported region counts: 1, 2, 3, 4, or 6.';
const coordinateDescription = 'Ernie native coordinate frame used by EEGLayoutLab, in millimetres.';
/** Written into every exported coordinate system file: these are not measured positions. */
export const POSITION_PROVENANCE = 'Electrode positions of an EEGLayoutLab layout on the Ernie template head (SimNIBS example dataset v4.1). ' +
  'They are design or template positions, not positions digitized on a participant.';
const mniDescription = 'FSL MNI152 nonlinear 6th-generation template space (SimNIBS MNI152_T1_1mm), in millimetres. ' +
  'Mapped from Ernie native coordinates with the SimNIBS nonlinear Ernie-to-MNI warp sampled on the Ernie scalp.';
const plain = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value));
const numberText = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const pairError = '请成对选择electrodes.tsv和coordsystem.json，每个文件不超过64 KB。';
const isMni = (system: unknown) => typeof system === 'string' && (MNI_COORDINATE_SYSTEMS as readonly string[]).includes(system);

/** Template landmarks (nasion, left and right preauricular points) in the file's own frame. Not digitized. */
function landmarks(frame: 'native' | 'mni') {
  const points = ERNIE_MNI_MAPPING.landmarks[frame === 'native' ? 'native_mm' : 'mni_mm'];
  return {
    AnatomicalLandmarkCoordinates: { NAS: points.Nz, LPA: points.LPA, RPA: points.RPA },
    AnatomicalLandmarkCoordinateSystem: frame === 'native' ? 'Other' : MNI_EXPORT_SYSTEM,
    AnatomicalLandmarkCoordinateUnits: 'mm',
    AnatomicalLandmarkCoordinateSystemDescription: frame === 'native'
      ? 'SimNIBS template landmarks mapped to Ernie by charm (eeg_positions/Fiducials.csv), in the Ernie native frame. Not digitized.'
      : 'SimNIBS MNI template landmarks (resources/ElectrodeCaps_MNI/Fiducials.csv). Not digitized.',
  };
}

function coordinatePair(files: CoordinateFile[]) {
  if (files.length < 2 || files.length > 3 || files.some(file => new TextEncoder().encode(file.text).length > 65536)) throw new Error(pairError);
  const electrodes = files.find(file => /(?:^|_)electrodes\.tsv$/.test(file.name));
  const coordsystem = files.find(file => /(?:^|_)coordsystem\.json$/.test(file.name));
  const metadata = files.find(file => /(?:^|_)electrodes\.json$/.test(file.name));
  if (!electrodes || !coordsystem || new Set(files.map(file => file.name)).size !== files.length ||
      files.some(file => ![electrodes, coordsystem, metadata].includes(file)))
    throw new Error(pairError);
  const prefix = electrodes.name.slice(0, -'electrodes.tsv'.length);
  if (coordsystem.name !== prefix + 'coordsystem.json' || metadata && metadata.name !== prefix + 'electrodes.json') throw new Error('BIDS坐标文件的名称前缀必须一致。');
  const system: unknown = JSON.parse(coordsystem.text);
  if (!plain(system)) throw new Error('coordsystem.json须是JSON对象。');
  return { electrodes, coordsystem, metadata, system };
}

/**
 * True when the coordinate system file needs the Ernie scalp surface: an MNI template space, or a head frame
 * with landmarks, which is registered onto the scalp.
 */
export function bidsNeedsMniSurface(files: CoordinateFile[]) {
  try {
    const { system } = coordinatePair(files);
    return isMni(system.EEGCoordinateSystem) || (system.EEGLayoutLabCoordinateSystem === undefined && system.EEGCoordinateSystem !== 'Other' && plain(system.AnatomicalLandmarkCoordinates));
  } catch { return false; }
}

/** Head frames: any declared system other than Ernie-native or MNI, used together with NAS/LPA/RPA landmarks in the same frame and unit. */
function headLandmarks(system: Record<string, unknown>): Landmarks | null {
  const coordinates = system.AnatomicalLandmarkCoordinates;
  if (!plain(coordinates)) return null;
  const read = (keys: string[]) => {
    const value = keys.map(key => coordinates[key]).find(entry => entry !== undefined);
    return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite) ? value as Point : null;
  };
  const NAS = read(['NAS', 'Nasion', 'NZ', 'Nz']), LPA = read(['LPA']), RPA = read(['RPA']);
  if (!NAS || !LPA || !RPA) return null;
  if (system.AnatomicalLandmarkCoordinateSystem !== undefined && system.AnatomicalLandmarkCoordinateSystem !== system.EEGCoordinateSystem)
    throw new Error('基准点坐标系须与电极坐标系一致。');
  if (system.AnatomicalLandmarkCoordinateUnits !== undefined && system.AnatomicalLandmarkCoordinateUnits !== system.EEGCoordinateUnits)
    throw new Error('基准点单位须与电极坐标单位一致。');
  return { NAS, LPA, RPA };
}
const HEAD_COLUMNS = ['type', 'material', 'impedance', 'group', 'hemisphere'];

/**
 * A coordinate-file adapter with an explicit EEGLayoutLab region extension. No unit inference.
 * Ernie-native files are read as they are. MNI files are mapped onto Ernie's scalp with `surface`.
 * Head-frame files (CapTrak, ElektaNeuromag and others) need NAS/LPA/RPA landmarks in the coordinate-system file;
 * they are registered onto Ernie's scalp (`head-frame-import.ts`). Without a region column, `options.regionCount`
 * assigns balanced spatial regions.
 */
export function parseBIDSElectrodes(files: CoordinateFile[], surface?: ErnieMniSurface, options: { regionCount?: RegionCount } = {}): ElectrodeDesign {
  const { electrodes, coordsystem, metadata, system } = coordinatePair(files);
  const native = system.EEGCoordinateSystem === 'Other' && system.EEGLayoutLabCoordinateSystem === 'ernie_native_mm' &&
    typeof system.EEGCoordinateSystemDescription === 'string' && Boolean(system.EEGCoordinateSystemDescription.trim());
  const mni = isMni(system.EEGCoordinateSystem) && system.EEGLayoutLabCoordinateSystem === undefined;
  const head = !native && !mni && system.EEGLayoutLabCoordinateSystem === undefined && typeof system.EEGCoordinateSystem === 'string' &&
    Boolean(system.EEGCoordinateSystem.trim()) ? headLandmarks(system) : null;
  if (!native && !mni && !head) throw new Error('仅接受显式声明Ernie原生坐标系、MNI模板空间（如MNI152NLin6Asym），或带NAS/LPA/RPA基准点的头坐标系（如CapTrak）的文件。');
  if (mni && !surface) throw new Error('MNI坐标需要先读取Ernie–MNI映射数据。');
  if (head && !surface) throw new Error('头坐标配准需要先读取Ernie头皮数据。');
  if (head ? !['mm', 'cm', 'm'].includes(system.EEGCoordinateUnits as string) : system.EEGCoordinateUnits !== 'mm')
    throw new Error(head ? '头坐标的EEGCoordinateUnits须为mm、cm或m。' : 'BIDS坐标接口目前只接受明确的mm单位，不执行单位推断或换算。');
  const lines = electrodes.text.replace(/\r\n/g, '\n').replace(/\n+$/, '').split('\n'), header = lines.shift()?.split('\t');
  const hasRegion = Boolean(header?.includes('region'));
  if (!header || header.slice(0, 4).join(',') !== 'name,x,y,z' || (!hasRegion && !options.regionCount))
    throw new Error('electrodes.tsv须包含name、x、y、z和明确分配的region列；没有region列时请选择区域数，由软件按空间位置均衡分区。');
  const allowed = ['name', 'x', 'y', 'z', 'region', ...(head ? HEAD_COLUMNS : [])];
  if (new Set(header).size !== header.length || header.some(column => !allowed.includes(column)) || (hasRegion && system.EEGLayoutLabRegionIndexBase !== 0))
    throw new Error('region列须使用本软件的零基区域扩展，并声明EEGLayoutLabRegionIndexBase为0。');
  let description = system.EEGLayoutLabRegionDescription;
  if (hasRegion) {
    if (metadata) {
      const columns: unknown = JSON.parse(metadata.text);
      if (!plain(columns) || !plain(columns.region) || typeof columns.region.Description !== 'string') throw new Error('electrodes.json须说明region列的含义。');
      description = columns.region.Description;
    }
    if (typeof description !== 'string' || !description.trim()) throw new Error('请在electrodes.json或EEGLayoutLabRegionDescription中说明region列。');
  }
  let rows = lines.map(line => line.split('\t'));
  if (head) {
    // Digitized files may list reference, ground and EOG channels: keep EEG rows with coordinates.
    const type = header.indexOf('type');
    rows = rows.filter(row => !(type >= 0 && row[type] && !/^eeg$/i.test(row[type].trim())) && !row.slice(1, 4).every(value => value === 'n/a'));
  }
  const region = header.indexOf('region');
  if (rows.length !== 64 || rows.some(row => row.length !== header.length || !row[0].trim() || row.slice(1, 4).some(value => !numberText.test(value)) ||
      (region >= 0 && !numberText.test(row[region]))))
    throw new Error(head ? `本软件的布局固定为64个电极；文件中有${rows.length}个带坐标的EEG电极，且不接受n/a坐标。` : 'BIDS坐标文件需要64个命名电极和完整数值；不接受n/a坐标。');
  const names = rows.map(row => row[0]), input = rows.map(row => row.slice(1, 4).map(Number) as Point);
  const fileRegions = hasRegion ? rows.map(row => Number(row[region])) : null;
  const name = typeof system.EEGLayoutLabDesignName === 'string' ? system.EEGLayoutLabDesignName : electrodes.name;
  const design = { schema: 'eeg-electrode-design/1' as const, coordinate_system: 'ernie_native_mm' as const, unit: 'mm' as const, name, electrode_names: names };
  if (head) {
    if (new Set(names.map(n => n.toLowerCase())).size !== 64) throw new Error('电极名称不能重复。');
    const unit = system.EEGCoordinateUnits as MontageUnit, scale = UNIT_MM[unit], mm = (p: Point): Point => [p[0] * scale, p[1] * scale, p[2] * scale];
    const placed = placeOnErnie(input.map(mm), { NAS: mm(head.NAS), LPA: mm(head.LPA), RPA: mm(head.RPA) }, surface,
      { coordinate_system: system.EEGCoordinateSystem as string, unit, landmark_source: 'coordsystem', names });
    const regions = importedRegions(placed.xyz, fileRegions, options.regionCount, description as string);
    const source: CoordinateSourceMetadata = { schema: 'electrode-coordinate-source/3', format: 'bids-electrodes/1', electrodes_file: electrodes.name,
      coordsystem_file: coordsystem.name, coordinate_system: 'ernie_native_mm', unit: 'mm', coordinate_system_description: placed.description,
      region_index_base: 0, region_description: regions.region_description, conversion: placed.conversion, region_assignment: regions.region_assignment };
    return validateDesign({ ...design, xyz_mm: placed.xyz, region_indices: regions.region_indices, source_metadata: source });
  }
  let xyz = input, conversion: CoordinateConversion | null = null, frameDescription = system.EEGCoordinateSystemDescription as string;
  if (mni) {
    const mapped = mniToErnie(input, surface!), worst = mapped.distances_mm.indexOf(Math.max(...mapped.distances_mm));
    if (mapped.distances_mm[worst] > MNI_IMPORT_LIMIT_MM)
      throw new Error(`电极${names[worst]}距Ernie头皮的MNI映射面${mapped.distances_mm[worst].toFixed(1)} mm，超过${MNI_IMPORT_LIMIT_MM} mm。请检查坐标系和单位。`);
    const maximum = Math.max(...mapped.distances_mm), declared = system.EEGCoordinateSystem as string;
    xyz = mapped.points;
    frameDescription = `${declared} coordinates mapped to the Ernie native frame (mm) on the scalp with the SimNIBS nonlinear Ernie-MNI warp` +
      `${declared === MNI_EXPORT_SYSTEM ? '' : ` (the warp targets ${MNI_EXPORT_SYSTEM}; differences between MNI templates are not modelled)`}. ` +
      `Largest distance from the warped Ernie scalp: ${maximum.toFixed(2)} mm.`;
    conversion = { method: 'ernie-mni-scalp/1', mapping_id: MAPPING_ID, input_coordinate_system: declared, input_unit: 'mm', max_surface_distance_mm: maximum };
  }
  if (!fileRegions) {
    const regions = importedRegions(xyz, null, options.regionCount);
    const source: CoordinateSourceMetadata = { schema: 'electrode-coordinate-source/3', format: 'bids-electrodes/1', electrodes_file: electrodes.name,
      coordsystem_file: coordsystem.name, coordinate_system: 'ernie_native_mm', unit: 'mm', coordinate_system_description: frameDescription,
      region_index_base: 0, region_description: regions.region_description, conversion, region_assignment: regions.region_assignment };
    return validateDesign({ ...design, xyz_mm: xyz, region_indices: regions.region_indices, source_metadata: source });
  }
  if (mni) {
    const source: CoordinateSourceMetadata = { schema: 'electrode-coordinate-source/2', format: 'bids-electrodes/1',
      electrodes_file: electrodes.name, coordsystem_file: coordsystem.name, coordinate_system: 'ernie_native_mm', unit: 'mm',
      coordinate_system_description: frameDescription, region_index_base: 0, region_description: description as string, conversion: conversion! };
    return validateDesign({ ...design, xyz_mm: xyz, region_indices: fileRegions, source_metadata: source });
  }
  const source: CoordinateSourceMetadata = { schema: 'electrode-coordinate-source/1', format: 'bids-electrodes/1',
    electrodes_file: electrodes.name, coordsystem_file: coordsystem.name, coordinate_system: 'ernie_native_mm', unit: 'mm',
    coordinate_system_description: frameDescription, region_index_base: 0, region_description: description as string };
  const preserved = system.EEGLayoutLabSourceMetadata === undefined ? source : validateCoordinateSource(system.EEGLayoutLabSourceMetadata) as CoordinateSourceMetadata;
  // A converted source keeps its own description; its Ernie-native export states the native frame instead.
  if ((preserved.schema === 'electrode-coordinate-source/1' && preserved.coordinate_system_description !== source.coordinate_system_description) ||
      preserved.region_description !== source.region_description) throw new Error('坐标来源说明与当前文件声明不一致。');
  return validateDesign({ ...design, xyz_mm: input, region_indices: fileRegions, source_metadata: preserved });
}

const tsv = (design: ElectrodeDesign, points: number[][]) =>
  ['name\tx\ty\tz\tregion', ...points.map((point, index) => [design.electrode_names?.[index] ?? `E${index + 1}`, ...point, design.region_indices[index]].join('\t'))].join('\n') + '\n';

/** Raw coordinate numbers retain their JSON/JavaScript round-trip precision in TSV. */
export function exportBIDSElectrodes(input: ElectrodeDesign): CoordinateFile[] {
  const design = validateDesign(input), source = design.source_metadata, regions = source?.region_description ?? regionDescription;
  const description = source?.schema === 'electrode-coordinate-source/1' ? source.coordinate_system_description : coordinateDescription;
  const system = { EEGCoordinateSystem: 'Other', EEGCoordinateUnits: 'mm', EEGCoordinateSystemDescription: description, ...landmarks('native'),
    EEGLayoutLabCoordinateSystem: 'ernie_native_mm', EEGLayoutLabPositionProvenance: POSITION_PROVENANCE,
    EEGLayoutLabRegionIndexBase: 0, EEGLayoutLabRegionDescription: regions,
    EEGLayoutLabDesignName: design.name, ...(source ? { EEGLayoutLabSourceMetadata: source } : {}) };
  return [
    { name: 'electrodes.tsv', text: tsv(design, design.xyz_mm) },
    { name: 'coordsystem.json', text: JSON.stringify(system, null, 2) + '\n' },
    { name: 'electrodes.json', text: JSON.stringify({ region: { Description: regions } }, null, 2) + '\n' },
  ];
}

/** The same layout in MNI152NLin6Asym. Refuses coordinates the evaluator would not accept on Ernie's scalp. */
export function exportMniBIDSElectrodes(input: ElectrodeDesign, surface: ErnieMniSurface): CoordinateFile[] {
  const design = validateDesign(input), regions = design.source_metadata?.region_description ?? regionDescription;
  const mapped = ernieToMni(design.xyz_mm, surface), worst = mapped.distances_mm.indexOf(Math.max(...mapped.distances_mm));
  if (mapped.distances_mm[worst] > NATIVE_EXPORT_LIMIT_MM) {
    const label = design.electrode_names?.[worst] ?? `E${worst + 1}`;
    throw new Error(`电极${label}距可换算的Ernie头皮${mapped.distances_mm[worst].toFixed(1)} mm，超过${NATIVE_EXPORT_LIMIT_MM} mm（下颌、耳部和颈部不在MNI换算范围内）。`);
  }
  const prefix = `space-${MNI_EXPORT_SYSTEM}_`;
  const system = { EEGCoordinateSystem: MNI_EXPORT_SYSTEM, EEGCoordinateUnits: 'mm', EEGCoordinateSystemDescription: mniDescription, ...landmarks('mni'),
    EEGLayoutLabPositionProvenance: POSITION_PROVENANCE,
    EEGLayoutLabMapping: { method: 'ernie-mni-scalp/1', mapping_id: MAPPING_ID, max_native_scalp_distance_mm: Math.max(...mapped.distances_mm) },
    EEGLayoutLabRegionIndexBase: 0, EEGLayoutLabRegionDescription: regions, EEGLayoutLabDesignName: design.name };
  return [
    { name: prefix + 'electrodes.tsv', text: tsv(design, mapped.points) },
    { name: prefix + 'coordsystem.json', text: JSON.stringify(system, null, 2) + '\n' },
    { name: prefix + 'electrodes.json', text: JSON.stringify({ region: { Description: regions } }, null, 2) + '\n' },
  ];
}

const capPositions = new Map(ERNIE_MNI_MAPPING.labels.positions_mm.map(([label, x, y, z]) => [String(label).toLowerCase(), { label: String(label), xyz: [x, y, z] as Point }]));
const aliases: Record<string, string> = ERNIE_MNI_MAPPING.labels.aliases;

/**
 * 64 electrode names with regions (`name` and `region` columns, tab- or comma-separated).
 * Positions are the SimNIBS 10-05 cap placed on Ernie's skin, the source of the standard64 reference.
 */
export function parseElectrodeLabels(file: CoordinateFile, options: { regionCount?: RegionCount } = {}): ElectrodeDesign {
  if (new TextEncoder().encode(file.text).length > 65536 || !/\.(?:tsv|csv|txt)$/i.test(file.name) || /[\\/]/.test(file.name))
    throw new Error('请选择不超过64 KB的.tsv、.csv或.txt电极名称文件。');
  const lines = file.text.replace(/^﻿/, '').replace(/\r\n/g, '\n').replace(/\n+$/, '').split('\n');
  const separator = lines[0]?.includes('\t') ? '\t' : ',', header = lines.shift()?.split(separator).map(cell => cell.trim());
  const namesOnly = header?.join(',') === 'name' && Boolean(options.regionCount);
  if (!header || (header.join(',') !== 'name,region' && !namesOnly))
    throw new Error('电极名称文件的表头须为name和region两列；只有name列时请选择区域数，由软件按空间位置均衡分区。');
  const rows = lines.map(line => line.split(separator).map(cell => cell.trim()));
  if (rows.length !== 64 || rows.some(row => row.length !== header.length || !row[0] || (!namesOnly && !/^\d+$/.test(row[1]))))
    throw new Error(namesOnly ? '电极名称文件需要64行，每行一个电极名称。' : '电极名称文件需要64行，每行一个电极名称和一个整数区域。');
  const unknown: string[] = [], positions = rows.map(([name]) => {
    const found = capPositions.get((aliases[name.toUpperCase()] ?? name).toLowerCase());
    if (!found) unknown.push(name);
    return found;
  });
  if (unknown.length) throw new Error(`10-05电极名称中没有：${unknown.slice(0, 5).join(', ')}${unknown.length > 5 ? ` 等${unknown.length}个` : ''}。`);
  const labels = positions.map(position => position!.label);
  if (new Set(labels).size !== 64) throw new Error('电极名称（含T3/T4/T5/T6的现名）不能重复。');
  const xyz = positions.map(position => [...position!.xyz] as Point);
  const conversion = { method: 'cap-labels/1' as const, mapping_id: MAPPING_ID, input_coordinate_system: LABEL_CAP as 'EEG10-20_extended_SPM12', input_unit: null, max_surface_distance_mm: null };
  const description = `Positions of the named electrodes in the SimNIBS ${LABEL_CAP} 10-05 cap, placed on Ernie's skin by charm ` +
    '(eeg_positions), in the Ernie native frame (mm). Template positions, not digitized.';
  const common = { format: 'electrode-labels/1' as const, electrodes_file: file.name, coordsystem_file: null, coordinate_system: 'ernie_native_mm' as const,
    unit: 'mm' as const, coordinate_system_description: description, region_index_base: 0 as const };
  const regions = namesOnly ? importedRegions(xyz, null, options.regionCount) : null;
  const source: CoordinateSourceMetadata = regions
    ? { schema: 'electrode-coordinate-source/3', ...common, region_description: regions.region_description, conversion, region_assignment: regions.region_assignment }
    : { schema: 'electrode-coordinate-source/2', ...common, region_description: regionDescription, conversion };
  return validateDesign({ schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm', name: file.name.replace(/\.[^.]+$/, ''),
    electrode_names: labels, xyz_mm: xyz, region_indices: regions ? regions.region_indices : rows.map(row => Number(row[1])), source_metadata: source });
}
