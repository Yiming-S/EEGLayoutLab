import mapping from '../public/data/ernie-mni-mapping.json' with { type: 'json' };
import roiAtlas from '../public/models/ernie/source-roi.json' with { type: 'json' };
import {
  DATA_PRIOR_REGIONS,
  DATA_PRIOR_SCHEMA,
  normalizeDataPrior,
} from '../contracts/scientific-options.mjs';
import type { DataPrior } from './local-compute.ts';

export type Point3 = [number, number, number];

export type FmriPeak = {
  label?: string;
  mni_mm: Point3;
  stat: number;
  fwhm_mm: number;
};

export type FmriPriorSummary = {
  sourceKind: 'preset' | 'mni_peaks' | 'nifti_volume';
  title: string;
  activeSources: number;
  totalSources: number;
  threshold: number;
  dimensions?: [number, number, number];
  peakCount?: number;
  rawRegionScores: number[];
};

export type ScenarioPriorPreset = {
  id: string;
  label: string;
  description: string;
  prior: DataPrior;
};

const GAIN_MIN = 0.1;
const GAIN_MAX = 10.0;
const DEFAULT_FWHM_MM = 20;

const roundSig4 = (v: number) => Number(Math.min(GAIN_MAX, Math.max(GAIN_MIN, v)).toPrecision(4));

/** Area-like share of each of the 7 DK40 groups in the 4,096-source forward dictionary. */
export const DICTIONARY_ROI_SHARES: readonly number[] = (() => {
  const counts = Array.from({ length: DATA_PRIOR_REGIONS.length }, () => 0);
  for (const raw of roiAtlas.dictionary_roi_indices) {
    const group = raw === 0 ? 6 : raw - 1;
    counts[group] += 1;
  }
  const total = counts.reduce((a, b) => a + b, 0) || 1;
  return counts.map((c) => c / total);
})();

/** Normalizes 7 raw nonnegative regional scores into canonical 4-sig-fig `region_gain` with dictionary-weighted mean ~ 1. */
export function scoresToRegionGains(rawScores: readonly number[], baselineFloor = 0.22): number[] {
  if (rawScores.length !== DATA_PRIOR_REGIONS.length) {
    throw new Error('脑区激活得分数组长度须为7');
  }
  const clean = rawScores.map((v) => (Number.isFinite(v) && v > 0 ? v : 0));
  const maxVal = Math.max(...clean);
  if (maxVal <= 1e-12) {
    return Array.from({ length: DATA_PRIOR_REGIONS.length }, () => 1);
  }
  const floored = clean.map((v) => baselineFloor + (1 - baselineFloor) * (v / maxVal));
  const weightedMean = floored.reduce((acc, v, i) => acc + v * DICTIONARY_ROI_SHARES[i], 0) || 1;
  return floored.map((v) => roundSig4(v / weightedMean));
}

/** Validated experimental scenario functional priors ready for 1-click simulation & layout optimization. */
export const SCENARIO_PRIOR_PRESETS: readonly ScenarioPriorPreset[] = [
  {
    id: 'ssvep_occipital',
    label: '稳态视觉诱发 SSVEP（枕区主导）',
    description: '强化初级与外侧枕叶视觉皮层权重，适用于枕部头带或AR/VR视觉脑机接口布局寻优。',
    prior: normalizeDataPrior({
      region_gain: scoresToRegionGains([0.08, 0.1, 0.35, 1.0, 0.08, 0.08, 0.05], 0.18),
      rho: 0.25,
      length_mm: 20,
    }) as DataPrior,
  },
  {
    id: 'motor_imagery_smr',
    label: '运动想象与感觉运动节律 SMR',
    description: '聚焦中央前/后回与旁中央小叶感觉运动皮层，适用于运动康复与肢体意图解码头环。',
    prior: normalizeDataPrior({
      region_gain: scoresToRegionGains([0.28, 1.0, 0.38, 0.08, 0.1, 0.1, 0.06], 0.18),
      rho: 0.25,
      length_mm: 20,
    }) as DataPrior,
  },
  {
    id: 'frontal_cognitive',
    label: '前额工作记忆、注意与情绪评估',
    description: '聚焦背外侧与眶额前额叶皮层，适用于无发区前额贴片、专注度与情绪监测穿戴设备。',
    prior: normalizeDataPrior({
      region_gain: scoresToRegionGains([1.0, 0.2, 0.18, 0.08, 0.25, 0.25, 0.15], 0.18),
      rho: 0.3,
      length_mm: 20,
    }) as DataPrior,
  },
  {
    id: 'auditory_sleep_ear',
    label: '双侧听觉诱发与耳周睡眠监测',
    description: '强化左右颞上回与颞叶听觉皮层权重，适用于双侧耳周/耳后紧凑贴片布局设计。',
    prior: normalizeDataPrior({
      region_gain: scoresToRegionGains([0.15, 0.22, 0.15, 0.1, 1.0, 1.0, 0.12], 0.18),
      rho: 0.2,
      length_mm: 15,
    }) as DataPrior,
  },
];

/**
 * Closed-form 3D affine calibration between Ernie native mm and MNI152 mm
 * fitted to the 4 fiducials + 10 verified scalp/cap anchors in `ernie-mni-mapping.json`.
 */
const ERNIE_TO_MNI_AFFINE: readonly [
  [number, number, number, number],
  [number, number, number, number],
  [number, number, number, number],
] = (() => {
  const src: Point3[] = [
    mapping.landmarks.native_mm.Nz as Point3,
    mapping.landmarks.native_mm.LPA as Point3,
    mapping.landmarks.native_mm.RPA as Point3,
    mapping.landmarks.native_mm.Iz as Point3,
    ...(mapping.golden.surface_mapping.mni_cap_to_ernie_mm as Point3[]),
  ];
  const dst: Point3[] = [
    mapping.landmarks.mni_mm.Nz as Point3,
    mapping.landmarks.mni_mm.LPA as Point3,
    mapping.landmarks.mni_mm.RPA as Point3,
    mapping.landmarks.mni_mm.Iz as Point3,
    ...(mapping.golden.surface_mapping.mni_cap_mm as Point3[]),
  ];
  // Normal equations (X^T X) B = X^T Y with X = [x, y, z, 1]
  const xtx = Array.from({ length: 4 }, () => [0, 0, 0, 0]);
  const xty = Array.from({ length: 4 }, () => [0, 0, 0]);
  for (let i = 0; i < src.length; i++) {
    const row = [src[i][0], src[i][1], src[i][2], 1];
    for (let r = 0; r < 4; r++) {
      for (let c = 0; c < 4; c++) xtx[r][c] += row[r] * row[c];
      for (let k = 0; k < 3; k++) xty[r][k] += row[r] * dst[i][k];
    }
  }
  const aug = xtx.map((r, i) => [...r, ...xty[i]]);
  for (let col = 0; col < 4; col++) {
    let pivot = col;
    for (let r = col + 1; r < 4; r++) {
      if (Math.abs(aug[r][col]) > Math.abs(aug[pivot][col])) pivot = r;
    }
    [aug[col], aug[pivot]] = [aug[pivot], aug[col]];
    const div = aug[col][col] || 1e-12;
    for (let j = col; j < 7; j++) aug[col][j] /= div;
    for (let r = 0; r < 4; r++) {
      if (r === col) continue;
      const factor = aug[r][col];
      for (let j = col; j < 7; j++) aug[r][j] -= factor * aug[col][j];
    }
  }
  return [
    [aug[0][4], aug[1][4], aug[2][4], aug[3][4]],
    [aug[0][5], aug[1][5], aug[2][5], aug[3][5]],
    [aug[0][6], aug[1][6], aug[2][6], aug[3][6]],
  ];
})();

export function ernieCorticalToMni(nativeMm: Point3): Point3 {
  return [0, 1, 2].map(
    (axis) =>
      ERNIE_TO_MNI_AFFINE[axis][0] * nativeMm[0] +
      ERNIE_TO_MNI_AFFINE[axis][1] * nativeMm[1] +
      ERNIE_TO_MNI_AFFINE[axis][2] * nativeMm[2] +
      ERNIE_TO_MNI_AFFINE[axis][3],
  ) as Point3;
}

type CorticalAnchor = {
  groupIndex: number;
  nativeMm: Point3;
  mniMm: Point3;
};

const CORTICAL_ANCHORS: readonly CorticalAnchor[] = roiAtlas.generation_sources.map((src) => ({
  groupIndex: src.roi_id === null ? 6 : DATA_PRIOR_REGIONS.indexOf(src.roi_id),
  nativeMm: src.xyz_mm as Point3,
  mniMm: ernieCorticalToMni(src.xyz_mm as Point3),
}));

/** Parses CSV, TSV, JSON, or whitespace-delimited MNI activation peaks `(x, y, z[, stat, fwhm_mm])`. */
export function parseFmriPeakTable(text: string): FmriPeak[] {
  const trimmed = text.trim();
  if (!trimmed) throw new Error('请输入或导入至少一个MNI激活峰值坐标');
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      throw new Error('fMRI激活峰值JSON格式无效');
    }
    const list = Array.isArray(parsed)
      ? parsed
      : parsed && typeof parsed === 'object' && Array.isArray((parsed as { peaks?: unknown }).peaks)
        ? (parsed as { peaks: unknown[] }).peaks
        : null;
    if (!list || !list.length) throw new Error('JSON中未找到peaks激活峰值列表');
    return list.map((item, idx) => {
      if (!item || typeof item !== 'object') throw new Error(`第${idx + 1}个峰值格式无效`);
      const rec = item as Record<string, unknown>;
      const coords = Array.isArray(rec.mni_mm)
        ? rec.mni_mm
        : [rec.x ?? rec.x_mm, rec.y ?? rec.y_mm, rec.z ?? rec.z_mm];
      const [x, y, z] = coords.map(Number);
      const stat = rec.stat !== undefined ? Number(rec.stat) : rec.t !== undefined ? Number(rec.t) : 5.0;
      const fwhm = rec.fwhm_mm !== undefined ? Number(rec.fwhm_mm) : DEFAULT_FWHM_MM;
      if (![x, y, z, stat, fwhm].every(Number.isFinite) || fwhm <= 1 || fwhm > 120) {
        throw new Error(`第${idx + 1}个峰值的MNI坐标或平滑核无效`);
      }
      return {
        label: typeof rec.label === 'string' ? rec.label : `Peak ${idx + 1}`,
        mni_mm: [x, y, z],
        stat: Math.abs(stat),
        fwhm_mm: fwhm,
      };
    });
  }

  const lines = trimmed
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#') && !l.startsWith('//'));
  const peaks: FmriPeak[] = [];
  for (let i = 0; i < lines.length; i++) {
    const parts = lines[i].split(/[,\t;]+|\s+/).filter(Boolean);
    const numericCount = parts.filter((p) => p !== '' && Number.isFinite(Number(p))).length;
    if (i === 0 && numericCount < 3) {
      continue; // header row
    }
    if (parts.length < 3) throw new Error(`第${i + 1}行至少需要x、y、z三个MNI毫米坐标`);
    const nums = parts.map(Number);
    let label: string | undefined;
    let offset = 0;
    if (Number.isNaN(nums[0]) && parts.length >= 4) {
      label = parts[0];
      offset = 1;
    }
    const x = Number(parts[offset]);
    const y = Number(parts[offset + 1]);
    const z = Number(parts[offset + 2]);
    const stat = parts[offset + 3] !== undefined ? Math.abs(Number(parts[offset + 3])) : 5.0;
    const fwhm = parts[offset + 4] !== undefined ? Number(parts[offset + 4]) : DEFAULT_FWHM_MM;
    if (![x, y, z, stat, fwhm].every(Number.isFinite) || fwhm <= 1 || fwhm > 120) {
      throw new Error(`第${i + 1}行包含无效数值（请检查MNI坐标、统计量t/Z与FWHM平滑核）`);
    }
    peaks.push({ label: label ?? `Peak ${peaks.length + 1}`, mni_mm: [x, y, z], stat, fwhm_mm: fwhm });
  }
  if (!peaks.length) throw new Error('未解析到有效的MNI激活峰值行');
  return peaks;
}

/** Projects MNI activation peaks onto the 7 DK40 cortical atlas regions and builds a valid `DataPrior`. */
export function projectMniPeaksToDataPrior(
  peaks: readonly FmriPeak[],
  options: { rho?: number; length_mm?: number | null; baselineFloor?: number; title?: string } = {},
): { prior: DataPrior; summary: FmriPriorSummary } {
  if (!peaks.length) throw new Error('至少需要一个MNI激活峰值');
  const sums = Array.from({ length: DATA_PRIOR_REGIONS.length }, () => 0);
  const counts = Array.from({ length: DATA_PRIOR_REGIONS.length }, () => 0);
  let activeSources = 0;

  for (const anchor of CORTICAL_ANCHORS) {
    let val = 0;
    for (const peak of peaks) {
      const sigma = peak.fwhm_mm / 2.354820045;
      const dx = anchor.mniMm[0] - peak.mni_mm[0];
      const dy = anchor.mniMm[1] - peak.mni_mm[1];
      const dz = anchor.mniMm[2] - peak.mni_mm[2];
      const d2 = dx * dx + dy * dy + dz * dz;
      val += Math.abs(peak.stat) * Math.exp(-d2 / (2 * sigma * sigma));
    }
    if (val >= 0.25) activeSources += 1;
    sums[anchor.groupIndex] += val;
    counts[anchor.groupIndex] += 1;
  }

  const rawScores = sums.map((s, i) => (counts[i] > 0 ? s / counts[i] : 0));
  const rho = options.rho ?? 0.25;
  const length_mm = rho === 0 ? null : (options.length_mm ?? 20);
  const prior = normalizeDataPrior({
    region_gain: scoresToRegionGains(rawScores, options.baselineFloor ?? 0.2),
    rho,
    length_mm,
  }) as DataPrior;

  return {
    prior,
    summary: {
      sourceKind: 'mni_peaks',
      title: options.title ?? `fMRI 峰值激活映射（${peaks.length} 个峰值簇）`,
      activeSources,
      totalSources: CORTICAL_ANCHORS.length,
      threshold: 0.25,
      peakCount: peaks.length,
      rawRegionScores: rawScores,
    },
  };
}

function invert4x4(m: number[][]): number[][] {
  const aug = m.map((row, i) => [
    ...row,
    i === 0 ? 1 : 0,
    i === 1 ? 1 : 0,
    i === 2 ? 1 : 0,
    i === 3 ? 1 : 0,
  ]);
  for (let col = 0; col < 4; col++) {
    let pivot = col;
    for (let r = col + 1; r < 4; r++) {
      if (Math.abs(aug[r][col]) > Math.abs(aug[pivot][col])) pivot = r;
    }
    if (Math.abs(aug[pivot][col]) < 1e-12) {
      throw new Error('NIfTI空间仿射矩阵奇异，无法映射到MNI坐标');
    }
    [aug[col], aug[pivot]] = [aug[pivot], aug[col]];
    const div = aug[col][col];
    for (let j = col; j < 8; j++) aug[col][j] /= div;
    for (let r = 0; r < 4; r++) {
      if (r === col) continue;
      const factor = aug[r][col];
      for (let j = col; j < 8; j++) aug[r][j] -= factor * aug[col][j];
    }
  }
  return aug.map((row) => row.slice(4, 8));
}

export async function decompressGzipIfNeeded(buffer: ArrayBuffer): Promise<ArrayBuffer> {
  const bytes = new Uint8Array(buffer);
  if (bytes.byteLength < 2 || bytes[0] !== 0x1f || bytes[1] !== 0x8b) {
    return buffer;
  }
  if (typeof DecompressionStream === 'undefined') {
    throw new Error('当前环境不支持直接解压.nii.gz，请先解压为.nii后载入');
  }
  const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).arrayBuffer();
}

export type ParsedNiftiHeader = {
  littleEndian: boolean;
  dims: [number, number, number, number];
  datatype: number;
  bitpix: number;
  voxOffset: number;
  sclSlope: number;
  sclInter: number;
  voxToMni: number[][];
  mniToVox: number[][];
};

export function parseNiftiHeader(buffer: ArrayBuffer): ParsedNiftiHeader {
  if (buffer.byteLength < 352) throw new Error('文件过小，不是有效的NIfTI-1三维统计图');
  const view = new DataView(buffer);
  const hdrLe = view.getInt32(0, true);
  const hdrBe = view.getInt32(0, false);
  if (hdrLe !== 348 && hdrBe !== 348) {
    throw new Error('未检测到标准NIfTI-1文件头（sizeof_hdr != 348）');
  }
  const le = hdrLe === 348;
  const nx = view.getInt16(42, le);
  const ny = view.getInt16(44, le);
  const nz = view.getInt16(46, le);
  const nt = Math.max(1, view.getInt16(48, le));
  if (nx <= 0 || ny <= 0 || nz <= 0) {
    throw new Error('NIfTI体素维度无效');
  }
  const datatype = view.getInt16(70, le);
  const bitpix = view.getInt16(72, le);
  const qfac = view.getFloat32(76, le) < 0 ? -1 : 1;
  const dx = Math.abs(view.getFloat32(80, le)) || 1;
  const dy = Math.abs(view.getFloat32(84, le)) || 1;
  const dz = Math.abs(view.getFloat32(88, le)) || 1;
  const voxOffset = Math.max(352, Math.floor(view.getFloat32(108, le)));
  const rawSlope = view.getFloat32(112, le);
  const sclSlope = rawSlope === 0 || !Number.isFinite(rawSlope) ? 1 : rawSlope;
  const sclInter = Number.isFinite(view.getFloat32(116, le)) ? view.getFloat32(116, le) : 0;
  const qformCode = view.getInt16(252, le);
  const sformCode = view.getInt16(254, le);

  let voxToMni: number[][];
  if (sformCode > 0) {
    const row = (off: number) => [
      view.getFloat32(off, le),
      view.getFloat32(off + 4, le),
      view.getFloat32(off + 8, le),
      view.getFloat32(off + 12, le),
    ];
    voxToMni = [row(280), row(296), row(312), [0, 0, 0, 1]];
  } else if (qformCode > 0) {
    const b = view.getFloat32(256, le);
    const c = view.getFloat32(260, le);
    const d = view.getFloat32(264, le);
    const a2 = Math.max(0, 1 - (b * b + c * c + d * d));
    const a = Math.sqrt(a2);
    const qx = view.getFloat32(268, le);
    const qy = view.getFloat32(272, le);
    const qz = view.getFloat32(276, le);
    voxToMni = [
      [(a * a + b * b - c * c - d * d) * dx, 2 * (b * c - a * d) * dy, 2 * (b * d + a * c) * qfac * dz, qx],
      [2 * (b * c + a * d) * dx, (a * a + c * c - b * b - d * d) * dy, 2 * (c * d - a * b) * qfac * dz, qy],
      [2 * (b * d - a * c) * dx, 2 * (c * d + a * b) * dy, (a * a + d * d - c * c - b * b) * qfac * dz, qz],
      [0, 0, 0, 1],
    ];
  } else {
    voxToMni = [
      [dx, 0, 0, -(nx * dx) / 2],
      [0, dy, 0, -(ny * dy) / 2],
      [0, 0, dz, -(nz * dz) / 2],
      [0, 0, 0, 1],
    ];
  }

  return {
    littleEndian: le,
    dims: [nx, ny, nz, nt],
    datatype,
    bitpix,
    voxOffset,
    sclSlope,
    sclInter,
    voxToMni,
    mniToVox: invert4x4(voxToMni),
  };
}

function readVoxel(view: DataView, hdr: ParsedNiftiHeader, index: number): number {
  const { littleEndian: le, datatype, voxOffset, sclSlope, sclInter } = hdr;
  let raw = 0;
  switch (datatype) {
    case 2: // UINT8
      raw = view.getUint8(voxOffset + index);
      break;
    case 256: // INT8
      raw = view.getInt8(voxOffset + index);
      break;
    case 4: // INT16
      raw = view.getInt16(voxOffset + index * 2, le);
      break;
    case 512: // UINT16
      raw = view.getUint16(voxOffset + index * 2, le);
      break;
    case 8: // INT32
      raw = view.getInt32(voxOffset + index * 4, le);
      break;
    case 16: // FLOAT32
      raw = view.getFloat32(voxOffset + index * 4, le);
      break;
    case 64: // FLOAT64
      raw = view.getFloat64(voxOffset + index * 8, le);
      break;
    default:
      throw new Error(`暂不支持该NIfTI体素数据类型（datatype=${datatype}），请导出为FLOAT32或INT16统计图`);
  }
  return Number.isFinite(raw) ? raw * sclSlope + sclInter : 0;
}

/** Projects a 3D NIfTI statistical map (`.nii` / decompressed `.nii.gz`) onto cortical ROIs to create a `DataPrior`. */
export function niftiVolumeToDataPrior(
  buffer: ArrayBuffer,
  options: { statThreshold?: number; rho?: number; length_mm?: number | null; title?: string } = {},
): { prior: DataPrior; summary: FmriPriorSummary } {
  const hdr = parseNiftiHeader(buffer);
  const [nx, ny, nz] = hdr.dims;
  const bytesPerVox = Math.max(1, Math.floor(hdr.bitpix / 8));
  const neededBytes = hdr.voxOffset + nx * ny * nz * bytesPerVox;
  if (buffer.byteLength < neededBytes) {
    throw new Error('NIfTI体素数据不完整或文件已截断');
  }
  const view = new DataView(buffer);
  const statThreshold = options.statThreshold ?? 1.5;
  const sums = Array.from({ length: DATA_PRIOR_REGIONS.length }, () => 0);
  const counts = Array.from({ length: DATA_PRIOR_REGIONS.length }, () => 0);
  let activeSources = 0;

  for (const anchor of CORTICAL_ANCHORS) {
    const [mx, my, mz] = anchor.mniMm;
    const vx = Math.round(
      hdr.mniToVox[0][0] * mx + hdr.mniToVox[0][1] * my + hdr.mniToVox[0][2] * mz + hdr.mniToVox[0][3],
    );
    const vy = Math.round(
      hdr.mniToVox[1][0] * mx + hdr.mniToVox[1][1] * my + hdr.mniToVox[1][2] * mz + hdr.mniToVox[1][3],
    );
    const vz = Math.round(
      hdr.mniToVox[2][0] * mx + hdr.mniToVox[2][1] * my + hdr.mniToVox[2][2] * mz + hdr.mniToVox[2][3],
    );
    let localPeak = 0;
    for (let dz = -1; dz <= 1; dz++) {
      const iz = vz + dz;
      if (iz < 0 || iz >= nz) continue;
      for (let dy = -1; dy <= 1; dy++) {
        const iy = vy + dy;
        if (iy < 0 || iy >= ny) continue;
        for (let dx = -1; dx <= 1; dx++) {
          const ix = vx + dx;
          if (ix < 0 || ix >= nx) continue;
          const idx = ix + nx * (iy + ny * iz);
          const mag = Math.abs(readVoxel(view, hdr, idx));
          if (mag > localPeak) localPeak = mag;
        }
      }
    }
    const above = localPeak >= statThreshold ? localPeak : 0;
    if (above > 0) activeSources += 1;
    sums[anchor.groupIndex] += above;
    counts[anchor.groupIndex] += 1;
  }

  if (activeSources === 0) {
    throw new Error(`在阈值 |t| ≥ ${statThreshold} 下未检测到覆盖皮层源的激活体素，请调低统计阈值或检查MNI空间配准`);
  }

  const rawScores = sums.map((s, i) => (counts[i] > 0 ? s / counts[i] : 0));
  const rho = options.rho ?? 0.25;
  const length_mm = rho === 0 ? null : (options.length_mm ?? 20);
  const prior = normalizeDataPrior({
    region_gain: scoresToRegionGains(rawScores, 0.2),
    rho,
    length_mm,
  }) as DataPrior;

  return {
    prior,
    summary: {
      sourceKind: 'nifti_volume',
      title: options.title ?? `NIfTI 三维激活图 (${nx}×${ny}×${nz})`,
      activeSources,
      totalSources: CORTICAL_ANCHORS.length,
      threshold: statThreshold,
      dimensions: [nx, ny, nz],
      rawRegionScores: rawScores,
    },
  };
}

/** Synthesizes a valid compact NIfTI-1 MNI152 statistical map in memory (useful for 1-click fMRI demo & tests). */
export function buildSyntheticFmriNifti(peaks: readonly FmriPeak[]): ArrayBuffer {
  const nx = 46,
    ny = 55,
    nz = 46,
    step = 4.0;
  const origin: Point3 = [-90, -126, -72];
  const voxOffset = 352;
  const totalVoxels = nx * ny * nz;
  const buffer = new ArrayBuffer(voxOffset + totalVoxels * 4);
  const view = new DataView(buffer);

  view.setInt32(0, 348, true); // sizeof_hdr
  view.setInt16(40, 3, true); // dim[0] = 3D
  view.setInt16(42, nx, true);
  view.setInt16(44, ny, true);
  view.setInt16(46, nz, true);
  view.setInt16(48, 1, true);
  view.setInt16(70, 16, true); // FLOAT32
  view.setInt16(72, 32, true); // 32 bits/voxel
  view.setFloat32(76, 1, true);
  view.setFloat32(80, step, true);
  view.setFloat32(84, step, true);
  view.setFloat32(88, step, true);
  view.setFloat32(108, voxOffset, true);
  view.setFloat32(112, 1, true); // scl_slope
  view.setFloat32(116, 0, true); // scl_inter
  view.setInt16(254, 4, true); // sform_code = MNI_152
  // srow_x, srow_y, srow_z
  view.setFloat32(280, step, true);
  view.setFloat32(292, origin[0], true);
  view.setFloat32(300, step, true);
  view.setFloat32(308, origin[1], true);
  view.setFloat32(320, step, true);
  view.setFloat32(324, origin[2], true);
  // magic "n+1\0"
  view.setUint8(344, 0x6e);
  view.setUint8(345, 0x2b);
  view.setUint8(346, 0x31);
  view.setUint8(347, 0x00);

  for (let iz = 0; iz < nz; iz++) {
    const mz = origin[2] + iz * step;
    for (let iy = 0; iy < ny; iy++) {
      const my = origin[1] + iy * step;
      for (let ix = 0; ix < nx; ix++) {
        const mx = origin[0] + ix * step;
        let val = 0;
        for (const p of peaks) {
          const sigma = p.fwhm_mm / 2.354820045;
          const d2 = (mx - p.mni_mm[0]) ** 2 + (my - p.mni_mm[1]) ** 2 + (mz - p.mni_mm[2]) ** 2;
          val += p.stat * Math.exp(-d2 / (2 * sigma * sigma));
        }
        const idx = ix + nx * (iy + ny * iz);
        view.setFloat32(voxOffset + idx * 4, val, true);
      }
    }
  }
  return buffer;
}

/** Exports any `DataPrior` (from scenario preset, MNI peaks, or fMRI NIfTI) as a valid `eeg-data-prior/1` JSON string. */
export function exportScenarioDataPriorJson(prior: DataPrior, label = 'fMRI / Scenario Prior'): string {
  const checked = normalizeDataPrior(prior) as DataPrior;
  const doc = {
    schema: DATA_PRIOR_SCHEMA,
    id: `scenario-${checked.region_gain.map((v) => v.toFixed(2)).join('-')}`.slice(0, 32),
    request: checked,
    regions: [...DATA_PRIOR_REGIONS],
    atlas: 'dk40-six-roi-v1',
    channels: Array.from({ length: 64 }, (_, i) => `E${i + 1}`),
    band_hz: [1, 40],
    inputs: [{ label, file: 'fmri_or_scenario_prior', sha256: '0'.repeat(64), channels: 64, epochs_used: 1 }],
    summaries_excluded: [],
    fit: {
      relative_residual: 0.12,
      uniform_relative_residual: 0.28,
      data_snr_db: 20,
      fitted_region_gain: checked.region_gain,
      shrinkage: 1,
      held_out: null,
    },
  };
  return JSON.stringify(doc, null, 2);
}
