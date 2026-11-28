import type { Point } from './ernie-mni.ts';
import {
  ERNIE_CRANIAL_FRAME,
  morphLayoutToSubject,
  type SubjectHeadProfile,
} from './head-personalization.ts';

export type ShellSizingMode = 'three_size_sml' | 'one_size_universal';
export type PodMountType = 'rigid_pod' | 'spring_plunger' | 'slotted_rail';

export type HardwareArchetype = SubjectHeadProfile & {
  sizeGroup: 'S' | 'M' | 'L';
};

/**
 * Five adult anthropometric cranial archetypes spanning S (P10), M (P50), L (P90),
 * plus dolichocephalic (long-narrow) and brachycephalic (broad-round) shape extremes.
 */
export const HARDWARE_SIZE_ARCHETYPES: readonly HardwareArchetype[] = [
  {
    id: 'size_S_p10',
    sizeGroup: 'S',
    label: 'S 小码（P10 · 头围 54.0 cm）',
    circumferenceMm: 540,
    cephalicIndex: 78.5,
    vertexHeightMm: 123.5,
  },
  {
    id: 'size_M_p50',
    sizeGroup: 'M',
    label: 'M 中码（P50 · 头围 57.2 cm）',
    circumferenceMm: 572,
    cephalicIndex: 77.8,
    vertexHeightMm: 130.5,
  },
  {
    id: 'size_L_p90',
    sizeGroup: 'L',
    label: 'L 大码（P90 · 头围 60.5 cm）',
    circumferenceMm: 605,
    cephalicIndex: 77.2,
    vertexHeightMm: 137.5,
  },
  {
    id: 'shape_M_dolicho',
    sizeGroup: 'M',
    label: '长头型极值（头围 57.2 cm · CI 72.8）',
    circumferenceMm: 572,
    cephalicIndex: 72.8,
    vertexHeightMm: 131.5,
  },
  {
    id: 'shape_M_brachy',
    sizeGroup: 'M',
    label: '圆阔头型极值（头围 57.2 cm · CI 84.0）',
    circumferenceMm: 572,
    cephalicIndex: 84.0,
    vertexHeightMm: 129.5,
  },
];

export type HardwareElectrodeSpec = {
  index: number;
  name: string;
  region: number;
  /** Outward unit surface normal in anatomical mm space (for spring plunger axis orientation). */
  normal: Point;
  /** Nominal coordinates for S, M, L shells (mm). */
  coordsBySizeMm: {
    S: Point;
    M: Point;
    L: Point;
    dolichoM: Point;
    brachyM: Point;
  };
  /** Peak-to-peak radial compression stroke along outward normal required under the selected shell mode (mm). */
  radialStrokeMm: number;
  /** Peak lateral/tangential arc drift perpendicular to normal under the selected shell mode (mm). */
  tangentialDriftMm: number;
  /** Full S-to-L Euclidean span if built as a single un-sized shell (mm). */
  sToLSpanMm: number;
  /** Dolicho-to-Brachy shape drift at fixed head circumference (mm). */
  cephalicDriftMm: number;
  mountType: PodMountType;
};

export type HardwareSizingReport = {
  designName: string;
  sizingMode: ShellSizingMode;
  electrodeCount: number;
  regionCount: number;
  electrodes: HardwareElectrodeSpec[];
  summary: {
    maxRadialStrokeMm: number;
    meanRadialStrokeMm: number;
    maxTangentialDriftMm: number;
    maxCephalicDriftMm: number;
    worstMinSpacingMm: number;
    mountCounts: Record<PodMountType, number>;
  };
};

const sub = (a: Point, b: Point): Point => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: Point, b: Point) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const norm = (a: Point) => Math.sqrt(dot(a, a));

function outwardNormal(p: Point): Point {
  const { origin, ex, ey, ez, breadthMm, lengthMm, vertexHeightMm } = ERNIE_CRANIAL_FRAME;
  const rel = sub(p, origin);
  const lx = dot(rel, ex);
  const ly = dot(rel, ey);
  const lz = dot(rel, ez);
  // Ellipsoidal gradient normal grad(x^2/a^2 + y^2/b^2 + z^2/c^2)
  const gx = lx / ((breadthMm / 2) ** 2 || 1);
  const gy = ly / ((lengthMm / 2) ** 2 || 1);
  const gz = lz / (vertexHeightMm ** 2 || 1);
  const wx = ex[0] * gx + ey[0] * gy + ez[0] * gz;
  const wy = ex[1] * gx + ey[1] * gy + ez[1] * gz;
  const wz = ex[2] * gx + ey[2] * gy + ez[2] * gz;
  const len = Math.hypot(wx, wy, wz) || 1;
  return [Number((wx / len).toFixed(4)), Number((wy / len).toFixed(4)), Number((wz / len).toFixed(4))];
}

/** The labels in podMountLabel state these same limits. */
export function classifyPodMount(radialStrokeMm: number, tangentialDriftMm: number): PodMountType {
  if (radialStrokeMm <= 3.5 && tangentialDriftMm <= 2.5) return 'rigid_pod';
  if (radialStrokeMm <= 9.0 && tangentialDriftMm <= 6.5) return 'spring_plunger';
  return 'slotted_rail';
}

export function podMountLabel(kind: PodMountType): string {
  switch (kind) {
    case 'rigid_pod':
      return '刚性壳体直装（行程≤3.5 mm且漂移≤2.5 mm）';
    case 'spring_plunger':
      return '弹性顶针/硅胶悬臂（行程≤9 mm且漂移≤6.5 mm）';
    case 'slotted_rail':
      return '分档滑槽/可调悬臂（行程>9 mm或漂移>6.5 mm）';
  }
}

/**
 * Computes S/M/L reference coordinates, normal axes, cephalic shape drift, and required
 * spring/slider mechanical tolerances for any 2–64 electrode layout.
 */
export function analyzeHardwareSizing(
  templateXyzMm: readonly Point[],
  regionIndices: readonly number[],
  options: {
    designName?: string;
    sizingMode?: ShellSizingMode;
    electrodeNames?: readonly string[];
  } = {},
): HardwareSizingReport {
  if (templateXyzMm.length < 2) {
    throw new Error('硬件尺码与公差分析至少需要2个电极坐标');
  }
  const sizingMode = options.sizingMode ?? 'three_size_sml';
  const morphed = HARDWARE_SIZE_ARCHETYPES.map((arch) =>
    morphLayoutToSubject(templateXyzMm, regionIndices, arch, options.electrodeNames),
  );
  const [resS, resM, resL, resDolicho, resBrachy] = morphed;

  const mountCounts: Record<PodMountType, number> = {
    rigid_pod: 0,
    spring_plunger: 0,
    slotted_rail: 0,
  };
  const electrodes: HardwareElectrodeSpec[] = [];
  let maxRadial = 0;
  let sumRadial = 0;
  let maxTangential = 0;
  let maxCephalic = 0;

  for (let i = 0; i < templateXyzMm.length; i++) {
    const n = outwardNormal(resM.rows[i].subjectMm);
    const pS = resS.rows[i].subjectMm;
    const pM = resM.rows[i].subjectMm;
    const pL = resL.rows[i].subjectMm;
    const pDol = resDolicho.rows[i].subjectMm;
    const pBra = resBrachy.rows[i].subjectMm;

    // Under `one_size_universal`, one M-centered frame must accommodate S, M, L, Dolicho, Brachy.
    // Under `three_size_sml`, each S/M/L shell covers ±1.6 cm circumference (~1/3 of S–L span) plus full Dolicho–Brachy shape variation!
    const candidates =
      sizingMode === 'one_size_universal'
        ? [pS, pM, pL, pDol, pBra]
        : [
            pM,
            pDol,
            pBra,
            [
              pM[0] + (pS[0] - pM[0]) * 0.34,
              pM[1] + (pS[1] - pM[1]) * 0.34,
              pM[2] + (pS[2] - pM[2]) * 0.34,
            ] as Point,
            [
              pM[0] + (pL[0] - pM[0]) * 0.34,
              pM[1] + (pL[1] - pM[1]) * 0.34,
              pM[2] + (pL[2] - pM[2]) * 0.34,
            ] as Point,
          ];

    let minNormalProj = Infinity;
    let maxNormalProj = -Infinity;
    let peakTangential = 0;

    for (const c of candidates) {
      const diff = sub(c, pM);
      const radialProj = dot(diff, n);
      if (radialProj < minNormalProj) minNormalProj = radialProj;
      if (radialProj > maxNormalProj) maxNormalProj = radialProj;
      const tangVec: Point = [
        diff[0] - radialProj * n[0],
        diff[1] - radialProj * n[1],
        diff[2] - radialProj * n[2],
      ];
      const tang = norm(tangVec);
      if (tang > peakTangential) peakTangential = tang;
    }

    const radialStrokeMm = maxNormalProj - minNormalProj;
    const tangentialDriftMm = peakTangential;
    const sToLSpanMm = norm(sub(pL, pS));
    const cephalicDriftMm = norm(sub(pBra, pDol));
    const mountType = classifyPodMount(radialStrokeMm, tangentialDriftMm);
    mountCounts[mountType] += 1;

    sumRadial += radialStrokeMm;
    if (radialStrokeMm > maxRadial) maxRadial = radialStrokeMm;
    if (tangentialDriftMm > maxTangential) maxTangential = tangentialDriftMm;
    if (cephalicDriftMm > maxCephalic) maxCephalic = cephalicDriftMm;

    electrodes.push({
      index: i,
      name: resM.rows[i].name,
      region: resM.rows[i].region,
      normal: n,
      coordsBySizeMm: { S: pS, M: pM, L: pL, dolichoM: pDol, brachyM: pBra },
      radialStrokeMm,
      tangentialDriftMm,
      sToLSpanMm,
      cephalicDriftMm,
      mountType,
    });
  }

  const worstMinSpacingMm = Math.min(...morphed.map((m) => m.subjectMinSpacingMm));

  return {
    designName: options.designName ?? '当前电极布局',
    sizingMode,
    electrodeCount: templateXyzMm.length,
    regionCount: new Set(regionIndices).size,
    electrodes,
    summary: {
      maxRadialStrokeMm: maxRadial,
      meanRadialStrokeMm: sumRadial / electrodes.length,
      maxTangentialDriftMm: maxTangential,
      maxCephalicDriftMm: maxCephalic,
      worstMinSpacingMm,
      mountCounts,
    },
  };
}

export function exportHardwareCadCsv(report: HardwareSizingReport): string {
  const comment = `# schema=eeg-hardware-sizing-reference/1; design=${report.designName.replace(/[\r\n;]/g, ' ')}; sizing_mode=${report.sizingMode}; unit=mm`;
  const header =
    'electrode,region,S_x_mm,S_y_mm,S_z_mm,M_x_mm,M_y_mm,M_z_mm,L_x_mm,L_y_mm,L_z_mm,normal_x,normal_y,normal_z,radial_stroke_mm,tangential_drift_mm,cephalic_drift_mm,mount_type';
  const rows = report.electrodes.map((e) => {
    const { S, M, L } = e.coordsBySizeMm;
    return [
      e.name,
      e.region,
      S[0].toFixed(2),
      S[1].toFixed(2),
      S[2].toFixed(2),
      M[0].toFixed(2),
      M[1].toFixed(2),
      M[2].toFixed(2),
      L[0].toFixed(2),
      L[1].toFixed(2),
      L[2].toFixed(2),
      e.normal[0].toFixed(4),
      e.normal[1].toFixed(4),
      e.normal[2].toFixed(4),
      e.radialStrokeMm.toFixed(2),
      e.tangentialDriftMm.toFixed(2),
      e.cephalicDriftMm.toFixed(2),
      e.mountType,
    ].join(',');
  });
  return [comment, header, ...rows].join('\n');
}

export function exportHardwareCadJson(report: HardwareSizingReport): string {
  return JSON.stringify(
    {
      schema: 'eeg-hardware-sizing-reference/1',
      design_name: report.designName,
      sizing_mode: report.sizingMode,
      electrode_count: report.electrodeCount,
      region_count: report.regionCount,
      archetypes: HARDWARE_SIZE_ARCHETYPES,
      summary: {
        max_radial_stroke_mm: Number(report.summary.maxRadialStrokeMm.toFixed(3)),
        mean_radial_stroke_mm: Number(report.summary.meanRadialStrokeMm.toFixed(3)),
        max_tangential_drift_mm: Number(report.summary.maxTangentialDriftMm.toFixed(3)),
        max_cephalic_drift_mm: Number(report.summary.maxCephalicDriftMm.toFixed(3)),
        worst_min_spacing_mm: Number(report.summary.worstMinSpacingMm.toFixed(3)),
        mount_counts: report.summary.mountCounts,
      },
      electrodes: report.electrodes.map((e) => ({
        electrode: e.name,
        region: e.region,
        normal_unit: e.normal,
        coordinates_mm: e.coordsBySizeMm,
        radial_stroke_mm: Number(e.radialStrokeMm.toFixed(3)),
        tangential_drift_mm: Number(e.tangentialDriftMm.toFixed(3)),
        s_to_l_span_mm: Number(e.sToLSpanMm.toFixed(3)),
        cephalic_drift_mm: Number(e.cephalicDriftMm.toFixed(3)),
        recommended_mount: e.mountType,
      })),
    },
    null,
    2,
  );
}
