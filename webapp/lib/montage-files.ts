import { validateDesign, type ElectrodeDesign } from './design-decision.ts';
import { ERNIE_MNI_MAPPING } from './ernie-mni.ts';
import type { CoordinateFile } from './bids-electrodes.ts';

/**
 * Montage files for MNE-Python (ASA `.elc`) and EEGLAB (BESA/EGI `.sfp`).
 *
 * Both carry the Ernie native coordinates (x right, y anterior, z superior, millimetres) and the
 * template landmarks NAS, LPA and RPA, so either tool can place the layout in its fiducial head frame.
 * MNE reads the unit from `.elc`; `.sfp` has no unit field, which is why it is offered for EEGLAB only.
 */

// Labels EEGLAB's readlocs marks as fiducials, plus the ASA landmark labels MNE removes from `.elc`.
const RESERVED = new Set(['nz', 'lpa', 'rpa', 'nasion', 'left', 'right', 'nazion', 'fidnz', 'fidt9', 'fidt10', 'cms', 'drl', 'nas', 'lht', 'rht', 'lhj', 'rhj', 'headshape']);

function montageDesign(input: ElectrodeDesign) {
  const design = validateDesign(input), names = design.electrode_names ?? design.xyz_mm.map((_, index) => `E${index + 1}`);
  const spaced = names.find(name => /\s/.test(name));
  if (spaced !== undefined) throw new Error(`电极名称“${spaced}”含空格，MNE和EEGLAB坐标文件按空白分列；请改名后导出。`);
  const reserved = names.find(name => RESERVED.has(name.toLowerCase()));
  if (reserved !== undefined) throw new Error(`电极名称“${reserved}”与基准点标签冲突，MNE或EEGLAB会把它当作基准点；请改名后导出。`);
  return { design, names };
}

const landmarks = () => {
  const points = ERNIE_MNI_MAPPING.landmarks.native_mm;
  return { nasion: points.Nz, lpa: points.LPA, rpa: points.RPA };
};
const row = (point: readonly number[]) => point.map(String).join('\t');

/** ASA electrode file. Read it with `mne.channels.read_custom_montage(path, head_size=None)`. */
export function exportMneElc(input: ElectrodeDesign): CoordinateFile {
  const { design, names } = montageDesign(input), { nasion, lpa, rpa } = landmarks();
  const points = [...design.xyz_mm, nasion, lpa, rpa], labels = [...names, 'Nz', 'LPA', 'RPA'];
  return { name: 'electrodes.elc', text: [
    '# EEGLayoutLab layout on the Ernie template head (SimNIBS example dataset v4.1): design or template coordinates, not digitized.',
    '# Ernie native frame: x right, y anterior, z superior. Nz, LPA and RPA are template landmarks.',
    'ReferenceLabel\tavg',
    'UnitPosition\tmm',
    `NumberPositions=\t${points.length}`,
    'Positions',
    ...points.map(row),
    'Labels',
    ...labels,
    '',
  ].join('\n') };
}

/** BESA/EGI coordinate file (x right, y nose, z up). EEGLAB turns it to its nose-along-+X convention on import. */
export function exportEeglabSfp(input: ElectrodeDesign): CoordinateFile {
  const { design, names } = montageDesign(input), { nasion, lpa, rpa } = landmarks();
  // readlocs reads .sfp without a header line, so the file holds coordinate rows only.
  const rows: [string, readonly number[]][] = [['FidNz', nasion], ['FidT9', lpa], ['FidT10', rpa],
    ...design.xyz_mm.map((point, index): [string, readonly number[]] => [names[index], point])];
  return { name: 'electrodes.sfp', text: rows.map(([label, point]) => label + '\t' + row(point)).join('\n') + '\n' };
}

export type MontageUnit = 'mm' | 'cm' | 'm';
export type MontageLandmarks = { NAS?: [number, number, number]; LPA?: [number, number, number]; RPA?: [number, number, number] };
export type MontageRead = { format: 'mne-elc/1' | 'eeglab-sfp/1'; names: string[]; points: [number, number, number][]; landmarks: MontageLandmarks; unit: MontageUnit | null };

// Landmark labels as MNE (`.elc`) and EEGLAB (`.sfp`) name them.
const LANDMARK_LABELS: Record<string, keyof MontageLandmarks> = { nz: 'NAS', nas: 'NAS', nasion: 'NAS', nazion: 'NAS', fidnz: 'NAS',
  lpa: 'LPA', left: 'LPA', fidt9: 'LPA', rpa: 'RPA', right: 'RPA', fidt10: 'RPA' };
// Other non-electrode labels: reference/ground, head-shape points and HPI coils are skipped on import.
const SKIPPED = new Set(['cms', 'drl', 'lht', 'rht', 'lhj', 'rhj', 'headshape', 'gnd', 'ground']);
const number = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const coordinates = (cells: string[]) => {
  if (cells.length !== 3 || !cells.every(cell => number.test(cell))) throw new Error('坐标行须包含3个数值。');
  return cells.map(Number) as [number, number, number];
};

function collect(format: MontageRead['format'], labels: string[], points: [number, number, number][], unit: MontageUnit | null): MontageRead {
  if (labels.length !== points.length) throw new Error('电极名称数与坐标数不一致。');
  const result: MontageRead = { format, names: [], points: [], landmarks: {}, unit };
  labels.forEach((label, index) => {
    const key = label.toLowerCase(), landmark = LANDMARK_LABELS[key];
    if (landmark) {
      if (result.landmarks[landmark]) throw new Error(`基准点${landmark}重复。`);
      result.landmarks[landmark] = points[index];
    } else if (!SKIPPED.has(key) && !key.startsWith('hpi')) { result.names.push(label); result.points.push(points[index]); }
  });
  return result;
}

/** ASA `.elc` as MNE writes and reads it: `UnitPosition`, `Positions` (optionally `label: x y z`) and `Labels`. */
export function readMneElc(file: CoordinateFile): MontageRead {
  const lines = file.text.replace(/^﻿/, '').replace(/\r\n?/g, '\n').split('\n').map(line => line.replace(/#.*$/, '').trim()).filter(Boolean);
  let unit: MontageUnit | null = null, count: number | null = null, section = '';
  const points: [number, number, number][] = [], labels: string[] = [], inline: string[] = [];
  for (const line of lines) {
    const field = /^(\w+)\s*=?\s*(.*)$/.exec(line);
    if (field && field[1] === 'UnitPosition') {
      if (!['mm', 'cm', 'm'].includes(field[2])) throw new Error('.elc的UnitPosition须为mm、cm或m。');
      unit = field[2] as MontageUnit; continue;
    }
    if (field && field[1] === 'NumberPositions') { count = Number(field[2]); continue; }
    if (/^(Positions|Labels|NumberPolygons|TypePolygons|Polygons|ReferenceLabel)\b/.test(line)) { section = line.split(/\s/)[0]; continue; }
    if (section === 'Positions') {
      const labelled = /^([^:]+):\s*(.*)$/.exec(line);
      if (labelled) inline.push(labelled[1].trim());
      points.push(coordinates((labelled ? labelled[2] : line).split(/\s+/)));
    } else if (section === 'Labels') labels.push(...line.split(/\s+/));
  }
  if (!unit) throw new Error('.elc文件缺少UnitPosition，无法确定单位。');
  if (count === null || points.length !== count) throw new Error('.elc的NumberPositions与坐标行数不一致。');
  return collect('mne-elc/1', labels.length ? labels : inline, points, unit);
}

/** BESA/EGI `.sfp`: one `label x y z` row per point. The format has no unit field. */
export function readEeglabSfp(file: CoordinateFile): MontageRead {
  const rows = file.text.replace(/^﻿/, '').replace(/\r\n?/g, '\n').split('\n').map(line => line.trim()).filter(Boolean).map(line => line.split(/\s+/));
  if (rows.some(row => row.length !== 4)) throw new Error('.sfp每行须为名称和x、y、z三个数值。');
  return collect('eeglab-sfp/1', rows.map(row => row[0]), rows.map(row => coordinates(row.slice(1))), null);
}

export function readMontageFile(file: CoordinateFile): MontageRead {
  if (new TextEncoder().encode(file.text).length > 65536 || /[\\/]/.test(file.name)) throw new Error('电极坐标文件不超过64 KB。');
  if (/\.elc$/i.test(file.name)) return readMneElc(file);
  if (/\.sfp$/i.test(file.name)) return readEeglabSfp(file);
  throw new Error('请选择.elc或.sfp电极坐标文件。');
}
