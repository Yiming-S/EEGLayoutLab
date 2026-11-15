import { validateCoordinateSource } from '../contracts/coordinate-source.mjs';
import type { CoordinateSourceMetadata } from '../contracts/coordinate-source';
import { validateDesign, type ElectrodeDesign } from './design-decision.ts';

export type CoordinateFile = { name: string; text: string };
const regionDescription = 'EEGLayoutLab balanced region index, numbered continuously from zero. Supported region counts: 1, 2, 3, 4, or 6.';
const coordinateDescription = 'Ernie native coordinate frame used by EEGLayoutLab, in millimetres.';
const plain = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value));
const numberText = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

/** A coordinate-file adapter with an explicit EEGLayoutLab region extension. No registration or unit inference. */
export function parseBIDSElectrodes(files: CoordinateFile[]): ElectrodeDesign {
  if (files.length < 2 || files.length > 3 || files.some(file => new TextEncoder().encode(file.text).length > 65536))
    throw new Error('请成对选择electrodes.tsv和coordsystem.json，每个文件不超过64 KB。');
  const electrodes = files.find(file => /(?:^|_)electrodes\.tsv$/.test(file.name));
  const coordsystem = files.find(file => /(?:^|_)coordsystem\.json$/.test(file.name));
  const metadata = files.find(file => /(?:^|_)electrodes\.json$/.test(file.name));
  if (!electrodes || !coordsystem || new Set(files.map(file => file.name)).size !== files.length ||
      files.some(file => ![electrodes, coordsystem, metadata].includes(file)))
    throw new Error('请成对选择electrodes.tsv和coordsystem.json，每个文件不超过64 KB。');
  const prefix = electrodes.name.slice(0, -'electrodes.tsv'.length);
  if (coordsystem.name !== prefix + 'coordsystem.json' || metadata && metadata.name !== prefix + 'electrodes.json') throw new Error('BIDS坐标文件的名称前缀必须一致。');
  const system: unknown = JSON.parse(coordsystem.text);
  if (!plain(system) || system.EEGCoordinateSystem !== 'Other' || system.EEGLayoutLabCoordinateSystem !== 'ernie_native_mm' ||
      typeof system.EEGCoordinateSystemDescription !== 'string' || !system.EEGCoordinateSystemDescription.trim())
    throw new Error('仅接受显式声明Ernie原生坐标系的文件；MNI、head及其他坐标须先在外部配准。');
  if (system.EEGCoordinateUnits !== 'mm') throw new Error('BIDS坐标接口目前只接受明确的mm单位，不执行单位推断或换算。');
  const lines = electrodes.text.replace(/\r\n/g, '\n').replace(/\n+$/, '').split('\n'), header = lines.shift()?.split('\t');
  if (!header || header.slice(0, 4).join(',') !== 'name,x,y,z' || !header.includes('region'))
    throw new Error('electrodes.tsv须包含name、x、y、z和明确分配的region列；不能自动分配区域。');
  if (new Set(header).size !== header.length || header.some(column => !['name', 'x', 'y', 'z', 'region'].includes(column)) || system.EEGLayoutLabRegionIndexBase !== 0)
    throw new Error('region列须使用本软件的零基区域扩展，并声明EEGLayoutLabRegionIndexBase为0。');
  let description = system.EEGLayoutLabRegionDescription;
  if (metadata) {
    const columns: unknown = JSON.parse(metadata.text);
    if (!plain(columns) || !plain(columns.region) || typeof columns.region.Description !== 'string') throw new Error('electrodes.json须说明region列的含义。');
    description = columns.region.Description;
  }
  if (typeof description !== 'string' || !description.trim()) throw new Error('请在electrodes.json或EEGLayoutLabRegionDescription中说明region列。');
  const rows = lines.map(line => line.split('\t')), region = header.indexOf('region');
  if (rows.length !== 64 || rows.some(row => row.length !== header.length || !row[0].trim() || row.slice(1).some(value => !numberText.test(value))))
    throw new Error('BIDS坐标文件需要64个命名电极和完整数值；不接受n/a坐标。');
  const source: CoordinateSourceMetadata = { schema: 'electrode-coordinate-source/1', format: 'bids-electrodes/1',
    electrodes_file: electrodes.name, coordsystem_file: coordsystem.name, coordinate_system: 'ernie_native_mm', unit: 'mm',
    coordinate_system_description: system.EEGCoordinateSystemDescription, region_index_base: 0, region_description: description };
  const preserved = system.EEGLayoutLabSourceMetadata === undefined ? source : validateCoordinateSource(system.EEGLayoutLabSourceMetadata) as CoordinateSourceMetadata;
  if (preserved.coordinate_system_description !== source.coordinate_system_description || preserved.region_description !== source.region_description) throw new Error('坐标来源说明与当前文件声明不一致。');
  return validateDesign({ schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm',
    name: typeof system.EEGLayoutLabDesignName === 'string' ? system.EEGLayoutLabDesignName : electrodes.name,
    electrode_names: rows.map(row => row[0]), xyz_mm: rows.map(row => row.slice(1, 4).map(Number)), region_indices: rows.map(row => Number(row[region])), source_metadata: preserved });
}

/** Raw coordinate numbers retain their JSON/JavaScript round-trip precision in TSV. */
export function exportBIDSElectrodes(input: ElectrodeDesign): CoordinateFile[] {
  const design = validateDesign(input), source = design.source_metadata, description = source?.coordinate_system_description ?? coordinateDescription,
    regions = source?.region_description ?? regionDescription;
  const system = { EEGCoordinateSystem: 'Other', EEGCoordinateUnits: 'mm', EEGCoordinateSystemDescription: description,
    EEGLayoutLabCoordinateSystem: 'ernie_native_mm', EEGLayoutLabRegionIndexBase: 0, EEGLayoutLabRegionDescription: regions,
    EEGLayoutLabDesignName: design.name, ...(source ? { EEGLayoutLabSourceMetadata: source } : {}) };
  return [
    { name: 'electrodes.tsv', text: ['name\tx\ty\tz\tregion', ...design.xyz_mm.map((point, index) => [design.electrode_names?.[index] ?? `E${index + 1}`, ...point, design.region_indices[index]].join('\t'))].join('\n') + '\n' },
    { name: 'coordsystem.json', text: JSON.stringify(system, null, 2) + '\n' },
    { name: 'electrodes.json', text: JSON.stringify({ region: { Description: regions } }, null, 2) + '\n' },
  ];
}
