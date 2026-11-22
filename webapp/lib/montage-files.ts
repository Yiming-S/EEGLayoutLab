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
