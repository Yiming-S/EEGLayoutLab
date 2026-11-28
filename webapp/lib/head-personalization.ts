import mapping from '../public/data/ernie-mni-mapping.json' with { type: 'json' };
import type { Point } from './ernie-mni.ts';

export type CephalicClass = 'dolichocephalic' | 'mesocephalic' | 'brachycephalic';

export type SubjectHeadProfile = {
  id: string;
  label: string;
  /** Horizontal head circumference around glabella–opisthocranion (mm), typically 510–630 mm. */
  circumferenceMm: number;
  /** Cephalic index = 100 * bitragion/biparietal breadth / anteroposterior length, typically 70–88. */
  cephalicIndex: number;
  /** Superior crown height above the inter-auricular (LPA–RPA) axis (mm), typically 112–150 mm. */
  vertexHeightMm: number;
};

export type PhotoLandmark2D = [number, number];

export type FrontPhotoLandmarks = {
  leftTragus: PhotoLandmark2D;
  rightTragus: PhotoLandmark2D;
  vertexTop: PhotoLandmark2D;
};

export type SidePhotoLandmarks = {
  nasion: PhotoLandmark2D;
  inion: PhotoLandmark2D;
  tragus: PhotoLandmark2D;
  vertexTop: PhotoLandmark2D;
};

export type PersonalizedElectrodeRow = {
  index: number;
  name: string;
  region: number;
  templateMm: Point;
  subjectMm: Point;
  deltaMm: Point;
  shiftMm: number;
};

export type PersonalizedMontageResult = {
  profile: SubjectHeadProfile;
  cephalicClass: CephalicClass;
  dimensionsMm: {
    breadthMm: number;
    lengthMm: number;
    vertexHeightMm: number;
    circumferenceMm: number;
  };
  scaleFactors: {
    sx: number;
    sy: number;
    sz: number;
  };
  rows: PersonalizedElectrodeRow[];
  meanShiftMm: number;
  maxShiftMm: number;
  subjectMinSpacingMm: number;
  templateMinSpacingMm: number;
  spacingSafe: boolean;
};

const sub = (a: Point, b: Point): Point => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a: Point, b: Point): Point => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const dot = (a: Point, b: Point) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const norm = (a: Point) => Math.sqrt(dot(a, a));
const scaleVec = (a: Point, s: number): Point => [a[0] * s, a[1] * s, a[2] * s];
const cross = (a: Point, b: Point): Point => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];

/** Ramanujan's second approximation to ellipse perimeter for semi-axes a = L/2, b = W/2. */
export function ellipseCircumferenceMm(lengthMm: number, breadthMm: number): number {
  const a = lengthMm / 2;
  const b = breadthMm / 2;
  const h = (a - b) ** 2 / ((a + b) ** 2 || 1);
  return Math.PI * (a + b) * (1 + (3 * h) / (10 + Math.sqrt(Math.max(0, 4 - 3 * h))));
}

/** Solves exact cranial length L and breadth W (mm) from head circumference C (mm) and cephalic index CI = 100*W/L. */
export function dimensionsFromCircumferenceAndCi(circumferenceMm: number, cephalicIndex: number): {
  lengthMm: number;
  breadthMm: number;
} {
  if (!(circumferenceMm >= 460 && circumferenceMm <= 680)) {
    throw new Error('头围须在 460–680 mm（46–68 cm）合理生理范围内');
  }
  if (!(cephalicIndex >= 65 && cephalicIndex <= 95)) {
    throw new Error('头长宽指数（CI）须在 65–95 合理解剖范围内');
  }
  const ratio = cephalicIndex / 100;
  const unitPerim = ellipseCircumferenceMm(1, ratio);
  const lengthMm = circumferenceMm / unitPerim;
  const breadthMm = lengthMm * ratio;
  return { lengthMm, breadthMm };
}

/** Ernie template fiducial frame & baseline anthropometric dimensions. */
export const ERNIE_CRANIAL_FRAME = (() => {
  const Nz = mapping.landmarks.native_mm.Nz as Point;
  const LPA = mapping.landmarks.native_mm.LPA as Point;
  const RPA = mapping.landmarks.native_mm.RPA as Point;
  const Iz = mapping.landmarks.native_mm.Iz as Point;
  const czRow = mapping.labels.positions_mm.find((r) => r[0] === 'Cz');
  const Cz: Point = czRow ? [Number(czRow[1]), Number(czRow[2]), Number(czRow[3])] : [4.62, -2.29, 99.87];

  const across = sub(RPA, LPA);
  const breadthMm = norm(across);
  const ex = scaleVec(across, 1 / breadthMm);
  const t = dot(sub(Nz, LPA), ex);
  const origin = add(LPA, scaleVec(ex, t));
  const apVec = sub(Nz, Iz);
  const forwardRaw = sub(apVec, scaleVec(ex, dot(apVec, ex)));
  const lengthMm = norm(forwardRaw);
  const ey = scaleVec(forwardRaw, 1 / lengthMm);
  const ezRaw = cross(ex, ey);
  const ez = scaleVec(ezRaw, 1 / norm(ezRaw));
  const vertexHeightMm = Math.abs(dot(sub(Cz, origin), ez));
  const circumferenceMm = ellipseCircumferenceMm(lengthMm, breadthMm);
  const cephalicIndex = (100 * breadthMm) / lengthMm;

  return {
    origin,
    ex,
    ey,
    ez,
    breadthMm,
    lengthMm,
    vertexHeightMm,
    circumferenceMm,
    cephalicIndex,
  };
})();

export function classifyCephalicIndex(ci: number): CephalicClass {
  if (ci < 75.0) return 'dolichocephalic';
  if (ci <= 80.0) return 'mesocephalic';
  return 'brachycephalic';
}

export function cephalicClassLabel(kind: CephalicClass): string {
  switch (kind) {
    case 'dolichocephalic':
      return '长头型（CI < 75）';
    case 'mesocephalic':
      return '中头型（75 ≤ CI ≤ 80）';
    case 'brachycephalic':
      return '圆阔头型（CI > 80）';
  }
}

export const SUBJECT_HEAD_PRESETS: readonly SubjectHeadProfile[] = [
  {
    id: 'compact_brachy',
    label: '紧凑圆阔头型（头围 53.8 cm · CI 82.5）',
    circumferenceMm: 538,
    cephalicIndex: 82.5,
    vertexHeightMm: 123.5,
  },
  {
    id: 'ernie_reference',
    label: '标准中头型基准（头围 56.5 cm · CI 77.6）',
    circumferenceMm: Number(ERNIE_CRANIAL_FRAME.circumferenceMm.toFixed(1)),
    cephalicIndex: Number(ERNIE_CRANIAL_FRAME.cephalicIndex.toFixed(1)),
    vertexHeightMm: Number(ERNIE_CRANIAL_FRAME.vertexHeightMm.toFixed(1)),
  },
  {
    id: 'large_dolicho',
    label: '大头围长头型（头围 60.6 cm · CI 73.2）',
    circumferenceMm: 606,
    cephalicIndex: 73.2,
    vertexHeightMm: 136.5,
  },
  {
    id: 'broad_high_crown',
    label: '宽颅高顶头型（头围 59.0 cm · CI 84.0）',
    circumferenceMm: 590,
    cephalicIndex: 84.0,
    vertexHeightMm: 138.0,
  },
];

const dist2D = (a: PhotoLandmark2D, b: PhotoLandmark2D) => Math.hypot(a[0] - b[0], a[1] - b[1]);

/**
 * Calibrates a subject's 3D cranial anthropometric profile from front + lateral photo landmarks
 * normalized to each photo's aspect-preserved metric plane, anchored by measured head circumference (mm).
 */
export function calibrateFromPhotoLandmarks(
  front: FrontPhotoLandmarks,
  side: SidePhotoLandmarks,
  circumferenceMm: number,
  label = '头型照片标定个体',
): SubjectHeadProfile {
  const frontWidthPx = dist2D(front.leftTragus, front.rightTragus);
  const tragusMidFront: PhotoLandmark2D = [
    (front.leftTragus[0] + front.rightTragus[0]) / 2,
    (front.leftTragus[1] + front.rightTragus[1]) / 2,
  ];
  const frontHeightPx = dist2D(tragusMidFront, front.vertexTop);

  const sideLengthPx = dist2D(side.nasion, side.inion);
  const sideHeightPx = Math.abs(side.tragus[1] - side.vertexTop[1]) || dist2D(side.tragus, side.vertexTop);

  if (frontWidthPx < 0.05 || frontHeightPx < 0.04 || sideLengthPx < 0.05 || sideHeightPx < 0.04) {
    throw new Error('照片标志点间距过小，请分别点选左右耳屏、鼻根、枕外隆凸与颅顶最高点');
  }

  // Use crown height present in BOTH views to cancel camera distance / zoom difference between front and side photos!
  const widthToHeight = frontWidthPx / frontHeightPx;
  const lengthToHeight = sideLengthPx / sideHeightPx;
  const rawCi = Math.min(92, Math.max(67, (100 * widthToHeight) / lengthToHeight));
  const { lengthMm } = dimensionsFromCircumferenceAndCi(circumferenceMm, rawCi);
  const rawHeightMm = Math.min(152, Math.max(112, lengthMm / lengthToHeight));

  return {
    id: 'photo_calibrated',
    label,
    circumferenceMm: Number(circumferenceMm.toFixed(1)),
    cephalicIndex: Number(rawCi.toFixed(1)),
    vertexHeightMm: Number(rawHeightMm.toFixed(1)),
  };
}

function minPairwiseDistance(points: readonly Point[]): number {
  if (points.length < 2) return Infinity;
  let minD2 = Infinity;
  for (let i = 0; i < points.length; i++) {
    for (let j = i + 1; j < points.length; j++) {
      const d2 =
        (points[i][0] - points[j][0]) ** 2 +
        (points[i][1] - points[j][1]) ** 2 +
        (points[i][2] - points[j][2]) ** 2;
      if (d2 < minD2) minD2 = d2;
    }
  }
  return Math.sqrt(minD2);
}

/**
 * Maps a layout's Ernie native scalp coordinates onto an individual subject's 3D cranial geometry
 * using fiducial-pinned anisotropic cranial shell deformation in the Neuromag anatomical frame.
 */
export function morphLayoutToSubject(
  templateXyzMm: readonly Point[],
  regionIndices: readonly number[],
  profile: SubjectHeadProfile,
  electrodeNames?: readonly string[],
): PersonalizedMontageResult {
  if (!templateXyzMm.length) {
    throw new Error('请先选择或导入至少一套电极布局');
  }
  const { breadthMm, lengthMm } = dimensionsFromCircumferenceAndCi(
    profile.circumferenceMm,
    profile.cephalicIndex,
  );
  const sx = breadthMm / ERNIE_CRANIAL_FRAME.breadthMm;
  const sy = lengthMm / ERNIE_CRANIAL_FRAME.lengthMm;
  const sz = profile.vertexHeightMm / ERNIE_CRANIAL_FRAME.vertexHeightMm;

  const { origin, ex, ey, ez } = ERNIE_CRANIAL_FRAME;
  const rows: PersonalizedElectrodeRow[] = [];
  const subjectPoints: Point[] = [];
  let sumShift = 0;
  let maxShift = 0;

  for (let i = 0; i < templateXyzMm.length; i++) {
    const p = templateXyzMm[i];
    const rel = sub(p, origin);
    const lx = dot(rel, ex);
    const ly = dot(rel, ey);
    const lz = dot(rel, ez);

    // Smooth dome-preserving anisotropic transform: above the auricular plane z scales by sz;
    // below the auricular plane (mastoid / lower ear-EEG), vertical offset scales gently by sqrt(sy*sz) so ear anatomy stays proportional.
    const scaledX = lx * sx;
    const scaledY = ly * sy;
    const scaledZ = lz >= 0 ? lz * sz : lz * Math.sqrt(sy * sz);

    const subjectMm: Point = add(
      origin,
      add(add(scaleVec(ex, scaledX), scaleVec(ey, scaledY)), scaleVec(ez, scaledZ)),
    ).map((v) => Number(v.toFixed(4))) as Point;

    const deltaMm: Point = [
      Number((subjectMm[0] - p[0]).toFixed(4)),
      Number((subjectMm[1] - p[1]).toFixed(4)),
      Number((subjectMm[2] - p[2]).toFixed(4)),
    ];
    const shiftMm = norm(sub(subjectMm, p));
    sumShift += shiftMm;
    if (shiftMm > maxShift) maxShift = shiftMm;
    subjectPoints.push(subjectMm);

    rows.push({
      index: i,
      name: electrodeNames?.[i] ?? `E${i + 1}`,
      region: regionIndices[i] ?? 0,
      templateMm: p,
      subjectMm,
      deltaMm,
      shiftMm,
    });
  }

  const templateMinSpacingMm = minPairwiseDistance(templateXyzMm);
  const subjectMinSpacingMm = minPairwiseDistance(subjectPoints);

  return {
    profile,
    cephalicClass: classifyCephalicIndex(profile.cephalicIndex),
    dimensionsMm: {
      breadthMm,
      lengthMm,
      vertexHeightMm: profile.vertexHeightMm,
      circumferenceMm: profile.circumferenceMm,
    },
    scaleFactors: { sx, sy, sz },
    rows,
    meanShiftMm: sumShift / rows.length,
    maxShiftMm: maxShift,
    subjectMinSpacingMm,
    templateMinSpacingMm,
    spacingSafe: subjectMinSpacingMm >= 4.0 - 1e-6,
  };
}

export function exportPersonalizedMontageCsv(result: PersonalizedMontageResult): string {
  const header = `# schema=eeg-personalized-montage/1; subject=${result.profile.id}; circumference_mm=${result.profile.circumferenceMm.toFixed(1)}; cephalic_index=${result.profile.cephalicIndex.toFixed(1)}; vertex_height_mm=${result.profile.vertexHeightMm.toFixed(1)}; unit=mm`;
  const cols = 'electrode,region,x_mm,y_mm,z_mm,template_x_mm,template_y_mm,template_z_mm,shift_mm';
  const lines = result.rows.map(
    (r) =>
      `${r.name},${r.region},${r.subjectMm[0].toFixed(3)},${r.subjectMm[1].toFixed(3)},${r.subjectMm[2].toFixed(3)},${r.templateMm[0].toFixed(3)},${r.templateMm[1].toFixed(3)},${r.templateMm[2].toFixed(3)},${r.shiftMm.toFixed(3)}`,
  );
  return [header, cols, ...lines].join('\n');
}

export function exportPersonalizedMontageJson(
  result: PersonalizedMontageResult,
  baseName = 'personalized-layout',
): string {
  return JSON.stringify(
    {
      schema: 'eeg-personalized-montage/1',
      name: `${baseName} (${result.profile.label})`,
      coordinate_system: 'subject_anatomical_mm',
      unit: 'mm',
      subject_profile: {
        id: result.profile.id,
        label: result.profile.label,
        cephalic_class: result.cephalicClass,
        circumference_mm: Number(result.dimensionsMm.circumferenceMm.toFixed(2)),
        cephalic_index: Number(result.profile.cephalicIndex.toFixed(2)),
        breadth_mm: Number(result.dimensionsMm.breadthMm.toFixed(2)),
        length_mm: Number(result.dimensionsMm.lengthMm.toFixed(2)),
        vertex_height_mm: Number(result.dimensionsMm.vertexHeightMm.toFixed(2)),
        scale_factors: {
          sx: Number(result.scaleFactors.sx.toFixed(4)),
          sy: Number(result.scaleFactors.sy.toFixed(4)),
          sz: Number(result.scaleFactors.sz.toFixed(4)),
        },
      },
      summary: {
        electrode_count: result.rows.length,
        mean_shift_mm: Number(result.meanShiftMm.toFixed(3)),
        max_shift_mm: Number(result.maxShiftMm.toFixed(3)),
        subject_min_spacing_mm: Number(result.subjectMinSpacingMm.toFixed(3)),
        spacing_safe_4mm: result.spacingSafe,
      },
      electrode_names: result.rows.map((r) => r.name),
      region_indices: result.rows.map((r) => r.region),
      xyz_mm: result.rows.map((r) => r.subjectMm),
      template_ernie_xyz_mm: result.rows.map((r) => r.templateMm),
    },
    null,
    2,
  );
}
