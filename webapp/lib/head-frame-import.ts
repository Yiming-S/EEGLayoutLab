import type { CoordinateConversion, CoordinateSourceMetadata, RegionAssignment } from '../contracts/coordinate-source';
import { HEAD_REGISTRATION_LIMIT_MM, HEAD_REGISTRATION_METHOD } from '../contracts/coordinate-source.mjs';
import { validateDesign, type ElectrodeDesign } from './design-decision.ts';
import { MAPPING_ID, type ErnieMniSurface, type Point } from './ernie-mni.ts';
import { ERNIE_LANDMARKS, REGION_ASSIGNMENT_METHOD, assignBalancedRegions, registerHeadPoints, type Landmarks } from './head-registration.ts';
import { readMontageFile, type MontageUnit } from './montage-files.ts';
import type { CoordinateFile } from './bids-electrodes.ts';

export const UNIT_MM: Record<MontageUnit, number> = { mm: 1, cm: 10, m: 1000 };
export const BALANCED_REGION_DESCRIPTION = (count: number) =>
  `EEGLayoutLab balanced region index assigned on import: ${count} spatial region${count === 1 ? '' : 's'} of balanced size ` +
  '(size-constrained k-means on the Ernie coordinates, solved exactly as an assignment problem), numbered from anterior to posterior.';
export type RegionCount = 1 | 2 | 3 | 4 | 6;

const sameLandmarks = (a: Landmarks) =>
  (['NAS', 'LPA', 'RPA'] as const).every(name => a[name].every((value, axis) => Math.abs(value - ERNIE_LANDMARKS[name][axis]) <= 1e-6));

export type Placement = { xyz: Point[]; conversion: Extract<CoordinateConversion, { method: 'head-landmarks-surface/1' }> | null; description: string };

/**
 * Places millimetre head-frame coordinates on Ernie. Files carrying Ernie's own template landmarks (EEGLayoutLab exports)
 * are already Ernie-native and are read unchanged; any other landmarks are registered onto Ernie's scalp.
 */
export function placeOnErnie(points: Point[], landmarks: Landmarks, surface: ErnieMniSurface | undefined,
  input: { coordinate_system: string; unit: MontageUnit; landmark_source: 'coordsystem' | 'file'; names: string[] }): Placement {
  if (input.unit === 'mm' && sameLandmarks(landmarks))
    return { xyz: points, conversion: null, description: 'Ernie native coordinate frame used by EEGLayoutLab, in millimetres (the file carries Ernie\'s template landmarks).' };
  if (!surface) throw new Error('头坐标配准需要先读取Ernie头皮数据。');
  const registration = registerHeadPoints(points, landmarks, surface);
  const worst = registration.distances_mm.indexOf(Math.max(...registration.distances_mm));
  if (registration.distances_mm[worst] > HEAD_REGISTRATION_LIMIT_MM)
    throw new Error(`配准后电极${input.names[worst]}距Ernie头皮${registration.distances_mm[worst].toFixed(1)} mm，超过${HEAD_REGISTRATION_LIMIT_MM} mm。请检查坐标系、单位和基准点。球面模板（非实测坐标）请改用电极名称列表导入。`);
  if (!(registration.scale >= 0.5 && registration.scale <= 2)) throw new Error(`配准缩放系数${registration.scale.toFixed(2)}超出0.5–2，请检查单位。`);
  const residual = Math.max(...Object.values(registration.landmark_residuals_mm)), maximum = Math.max(...registration.distances_mm);
  const conversion = { method: HEAD_REGISTRATION_METHOD as 'head-landmarks-surface/1', mapping_id: MAPPING_ID, input_coordinate_system: input.coordinate_system,
    input_unit: input.unit, landmark_source: input.landmark_source, scale: registration.scale, rotation_deg: registration.rotation_deg,
    max_landmark_residual_mm: residual, max_surface_distance_mm: maximum, iterations: registration.iterations };
  return { xyz: registration.points, conversion, description:
    `${input.coordinate_system} head-frame coordinates registered onto the Ernie template scalp: NAS/LPA/RPA landmark alignment refined by an ` +
    `isotropic similarity fit to the scalp surface (scale ${registration.scale.toFixed(3)}, rotation ${registration.rotation_deg.toFixed(1)}°), ` +
    `then projected onto the scalp. Largest distance from the scalp before projection: ${maximum.toFixed(2)} mm; largest landmark residual against ` +
    `SimNIBS template landmarks: ${residual.toFixed(1)} mm. Template-head placement, not an individual anatomical registration.` };
}

/** Regions from the file, or assigned on import when the user chose a region count. */
export function importedRegions(xyz: Point[], fromFile: number[] | null, regionCount: RegionCount | undefined, fileDescription?: string) {
  if (fromFile) return { region_indices: fromFile, region_assignment: { method: 'file' } as RegionAssignment, region_description: fileDescription! };
  if (!regionCount) throw new Error('文件没有region列，请选择区域数（1、2、3、4或6），由软件按空间位置均衡分区。');
  return { region_indices: assignBalancedRegions(xyz, regionCount), region_assignment: { method: REGION_ASSIGNMENT_METHOD, region_count: regionCount } as RegionAssignment,
    region_description: BALANCED_REGION_DESCRIPTION(regionCount) };
}

/** MNE `.elc` or EEGLAB `.sfp`. `.sfp` has no unit field, so its unit must be chosen; regions are assigned on import. */
export function parseMontageFile(file: CoordinateFile, surface: ErnieMniSurface | undefined,
  options: { unit?: MontageUnit; regionCount?: RegionCount } = {}): ElectrodeDesign {
  const read = readMontageFile(file);
  const unit = read.unit ?? options.unit;
  if (!unit) throw new Error('.sfp文件没有单位字段，请选择坐标单位（mm、cm或m）。');
  if (read.unit && options.unit && options.unit !== read.unit) throw new Error(`文件声明的单位是${read.unit}，与所选单位不一致。`);
  if (read.points.length !== 64)
    throw new Error(`本软件的布局固定为64个电极；文件中有${read.points.length}个电极（不含基准点、参考和地线）。`);
  if (new Set(read.names.map(name => name.toLowerCase())).size !== 64) throw new Error('电极名称不能重复。');
  const missing = (['NAS', 'LPA', 'RPA'] as const).filter(name => !read.landmarks[name]);
  if (missing.length) throw new Error(`文件缺少基准点${missing.join('、')}（如Nz/LPA/RPA或FidNz/FidT9/FidT10），无法放到Ernie头上。`);
  const scale = UNIT_MM[unit], mm = (p: [number, number, number]): Point => [p[0] * scale, p[1] * scale, p[2] * scale];
  const landmarks = { NAS: mm(read.landmarks.NAS!), LPA: mm(read.landmarks.LPA!), RPA: mm(read.landmarks.RPA!) };
  const placed = placeOnErnie(read.points.map(mm), landmarks, surface,
    { coordinate_system: read.format === 'mne-elc/1' ? 'ASA .elc head frame' : 'BESA/EGI .sfp head frame', unit, landmark_source: 'file', names: read.names });
  const regions = importedRegions(placed.xyz, null, options.regionCount);
  const source: CoordinateSourceMetadata = { schema: 'electrode-coordinate-source/3', format: read.format, electrodes_file: file.name, coordsystem_file: null,
    coordinate_system: 'ernie_native_mm', unit: 'mm', coordinate_system_description: placed.description, region_index_base: 0,
    region_description: regions.region_description, conversion: placed.conversion, region_assignment: regions.region_assignment };
  return validateDesign({ schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm', name: file.name.replace(/\.[^.]+$/, ''),
    electrode_names: read.names, xyz_mm: placed.xyz, region_indices: regions.region_indices, source_metadata: source });
}
