import { ERNIE_MNI_MAPPING, projectOntoScalp, type ErnieMniSurface, type Point } from './ernie-mni.ts';

/**
 * Registration of digitized head-frame coordinates onto the Ernie template scalp.
 *
 * 1. The nasion and the two preauricular points define a fiducial frame in each space
 *    (origin on the LPA–RPA line closest to the nasion, x towards RPA, y towards the nasion).
 *    Aligning the two frames, with one isotropic scale from the inter-preauricular width and
 *    the nasion depth, gives the initial similarity transform.
 * 2. That similarity transform is refined by iterated closest points: each electrode is paired
 *    with its closest point on Ernie's scalp, and the three landmarks are kept as weighted pairs
 *    with Ernie's template landmarks (Horn's closed-form weighted similarity solution).
 * 3. Each transformed electrode is projected onto the scalp. A point more than
 *    HEAD_REGISTRATION_LIMIT_MM (contracts/coordinate-source.mjs) from the scalp after registration is rejected.
 *
 * This places a measured montage on a template head. It does not model the participant's anatomy,
 * and the landmarks are compared with SimNIBS template landmarks, not with landmarks digitized on Ernie.
 */
/** Each landmark counts as this many electrodes in the surface fit. */
export const LANDMARK_WEIGHT = 8;
const MAX_ITERATIONS = 500;
const TOLERANCE_MM = 1e-4;

export type Landmarks = { NAS: Point; LPA: Point; RPA: Point };
export type HeadRegistration = {
  points: Point[];
  distances_mm: number[];
  scale: number;
  rotation_deg: number;
  translation_mm: Point;
  landmark_residuals_mm: { NAS: number; LPA: number; RPA: number };
  iterations: number;
};

export const ERNIE_LANDMARKS: Landmarks = (() => {
  const native = ERNIE_MNI_MAPPING.landmarks.native_mm;
  return { NAS: native.Nz as Point, LPA: native.LPA as Point, RPA: native.RPA as Point };
})();

type Matrix = number[][];
const sub = (a: Point, b: Point): Point => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: Point, b: Point) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const norm = (a: Point) => Math.sqrt(dot(a, a));
const scaled = (a: Point, s: number): Point => [a[0] * s, a[1] * s, a[2] * s];
const cross = (a: Point, b: Point): Point => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = (a: Point) => scaled(a, 1 / norm(a));
const apply = (rotation: Matrix, point: Point): Point =>
  [0, 1, 2].map(row => rotation[row][0] * point[0] + rotation[row][1] * point[1] + rotation[row][2] * point[2]) as Point;

/** Fiducial frame: origin and rows x, y, z (Neuromag convention). */
function fiducialFrame({ NAS, LPA, RPA }: Landmarks) {
  const across = sub(RPA, LPA), width = norm(across);
  if (!(width > 1)) throw new Error('左右耳前点重合或距离过近，无法建立基准坐标系。');
  const x = scaled(across, 1 / width), t = dot(sub(NAS, LPA), x), origin: Point = [LPA[0] + t * x[0], LPA[1] + t * x[1], LPA[2] + t * x[2]];
  const forward = sub(NAS, origin), depth = norm(forward);
  if (!(depth > 1)) throw new Error('鼻根点位于左右耳前点连线上，无法建立基准坐标系。');
  const y = scaled(forward, 1 / depth), z = unit(cross(x, y));
  return { origin, axes: [x, y, z] as Matrix, width, depth };
}

/** Largest eigenvector of a symmetric 4x4 matrix (cyclic Jacobi). */
function largestEigenvector(input: Matrix): number[] {
  const a = input.map(row => [...row]), v: number[][] = [0, 1, 2, 3].map(i => [0, 1, 2, 3].map(j => (i === j ? 1 : 0)));
  for (let sweep = 0; sweep < 100; sweep++) {
    let off = 0;
    for (let p = 0; p < 4; p++) for (let q = p + 1; q < 4; q++) off += a[p][q] * a[p][q];
    if (off < 1e-30) break;
    for (let p = 0; p < 4; p++) for (let q = p + 1; q < 4; q++) {
      if (Math.abs(a[p][q]) < 1e-300) continue;
      const theta = (a[q][q] - a[p][p]) / (2 * a[p][q]);
      const t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1)), c = 1 / Math.sqrt(t * t + 1), s = t * c;
      for (let k = 0; k < 4; k++) {
        const akp = a[k][p], akq = a[k][q];
        a[k][p] = c * akp - s * akq; a[k][q] = s * akp + c * akq;
      }
      for (let k = 0; k < 4; k++) {
        const apk = a[p][k], aqk = a[q][k];
        a[p][k] = c * apk - s * aqk; a[q][k] = s * apk + c * aqk;
      }
      for (let k = 0; k < 4; k++) {
        const vkp = v[k][p], vkq = v[k][q];
        v[k][p] = c * vkp - s * vkq; v[k][q] = s * vkp + c * vkq;
      }
    }
  }
  let best = 0;
  for (let i = 1; i < 4; i++) if (a[i][i] > a[best][best]) best = i;
  return v.map(row => row[best]);
}

/** Weighted similarity q ≈ s R p + t (Horn 1987, unit quaternions). */
export function similarityFit(source: Point[], target: Point[], weights: number[]) {
  const total = weights.reduce((sum, w) => sum + w, 0);
  const mean = (points: Point[]) => [0, 1, 2].map(axis => points.reduce((sum, p, i) => sum + weights[i] * p[axis], 0) / total) as Point;
  const ms = mean(source), mt = mean(target);
  const m = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  let spread = 0;
  source.forEach((p, i) => {
    const a = sub(p, ms), b = sub(target[i], mt);
    spread += weights[i] * dot(a, a);
    for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) m[r][c] += weights[i] * a[r] * b[c];
  });
  const [[sxx, sxy, sxz], [syx, syy, syz], [szx, szy, szz]] = m;
  const [w, x, y, z] = largestEigenvector([
    [sxx + syy + szz, syz - szy, szx - sxz, sxy - syx],
    [syz - szy, sxx - syy - szz, sxy + syx, szx + sxz],
    [szx - sxz, sxy + syx, -sxx + syy - szz, syz + szy],
    [sxy - syx, szx + sxz, syz + szy, -sxx - syy + szz],
  ]);
  const rotation: Matrix = [
    [w * w + x * x - y * y - z * z, 2 * (x * y - w * z), 2 * (x * z + w * y)],
    [2 * (x * y + w * z), w * w - x * x + y * y - z * z, 2 * (y * z - w * x)],
    [2 * (x * z - w * y), 2 * (y * z + w * x), w * w - x * x - y * y + z * z],
  ];
  let aligned = 0;
  source.forEach((p, i) => { aligned += weights[i] * dot(sub(target[i], mt), apply(rotation, sub(p, ms))); });
  const scale = aligned / spread, rotated = apply(rotation, ms);
  return { scale, rotation, translation: [mt[0] - scale * rotated[0], mt[1] - scale * rotated[1], mt[2] - scale * rotated[2]] as Point };
}

type Similarity = { scale: number; rotation: Matrix; translation: Point };
const transform = ({ scale, rotation, translation }: Similarity, p: Point): Point => {
  const r = apply(rotation, p);
  return [scale * r[0] + translation[0], scale * r[1] + translation[1], scale * r[2] + translation[2]];
};

/** Initial transform from the two fiducial frames. */
export function landmarkSimilarity(from: Landmarks, to: Landmarks = ERNIE_LANDMARKS): Similarity {
  const a = fiducialFrame(from), b = fiducialFrame(to);
  const scale = Math.sqrt((b.width / a.width) * (b.depth / a.depth));
  // R = B^T A maps subject axes onto Ernie axes.
  const rotation = [0, 1, 2].map(r => [0, 1, 2].map(c => b.axes[0][r] * a.axes[0][c] + b.axes[1][r] * a.axes[1][c] + b.axes[2][r] * a.axes[2][c]));
  const moved = apply(rotation, a.origin);
  return { scale, rotation, translation: [b.origin[0] - scale * moved[0], b.origin[1] - scale * moved[1], b.origin[2] - scale * moved[2]] };
}

export function registerHeadPoints(points: Point[], landmarks: Landmarks, surface: ErnieMniSurface): HeadRegistration {
  if (points.some(p => p.length !== 3 || !p.every(Number.isFinite))) throw new Error('坐标必须是有限的三维数值。');
  const names = ['NAS', 'LPA', 'RPA'] as const;
  const sourceLandmarks = names.map(name => landmarks[name]), targetLandmarks = names.map(name => ERNIE_LANDMARKS[name]);
  const weights = [...points.map(() => 1), ...names.map(() => LANDMARK_WEIGHT)];
  let current = landmarkSimilarity(landmarks), iterations = 0, previous: Point[] | null = null;
  for (; iterations < MAX_ITERATIONS; iterations++) {
    const moved = points.map(p => transform(current, p));
    if (previous && Math.max(...moved.map((p, i) => norm(sub(p, previous![i])))) < TOLERANCE_MM) break;
    previous = moved;
    const closest = projectOntoScalp(moved, surface).points;
    current = similarityFit([...points, ...sourceLandmarks], [...closest, ...targetLandmarks], weights);
  }
  const moved = points.map(p => transform(current, p)), projected = projectOntoScalp(moved, surface);
  const residual = (name: typeof names[number]) => norm(sub(transform(current, landmarks[name]), ERNIE_LANDMARKS[name]));
  const trace = current.rotation[0][0] + current.rotation[1][1] + current.rotation[2][2];
  return {
    points: projected.points, distances_mm: projected.distances_mm, scale: current.scale,
    rotation_deg: Math.acos(Math.max(-1, Math.min(1, (trace - 1) / 2))) * 180 / Math.PI, translation_mm: current.translation,
    landmark_residuals_mm: { NAS: residual('NAS'), LPA: residual('LPA'), RPA: residual('RPA') }, iterations,
  };
}

/** Region sizes the evaluator accepts for `count` regions, largest first. */
export const regionSizes = (count: number) => Array.from({ length: count }, (_, i) => Math.floor(64 / count) + (i < 64 % count ? 1 : 0));
export const REGION_ASSIGNMENT_METHOD = 'balanced-spatial/1';

/** Minimum-cost assignment of rows to columns for a square matrix (Kuhn–Munkres with potentials). */
function assignment(cost: number[][]) {
  const n = cost.length, u = new Float64Array(n + 1), v = new Float64Array(n + 1), p = new Int32Array(n + 1), way = new Int32Array(n + 1);
  for (let i = 1; i <= n; i++) {
    p[0] = i;
    let j0 = 0;
    const minv = new Float64Array(n + 1).fill(Infinity), used = new Uint8Array(n + 1);
    do {
      used[j0] = 1;
      const i0 = p[j0];
      let delta = Infinity, j1 = 0;
      for (let j = 1; j <= n; j++) if (!used[j]) {
        const current = cost[i0 - 1][j - 1] - u[i0] - v[j];
        if (current < minv[j]) { minv[j] = current; way[j] = j0; }
        if (minv[j] < delta) { delta = minv[j]; j1 = j; }
      }
      for (let j = 0; j <= n; j++) if (used[j]) { u[p[j]] += delta; v[j] -= delta; } else minv[j] -= delta;
      j0 = j1;
    } while (p[j0] !== 0);
    do { const j1 = way[j0]; p[j0] = p[j1]; j0 = j1; } while (j0);
  }
  const rows = new Int32Array(n);
  for (let j = 1; j <= n; j++) rows[p[j] - 1] = j - 1;
  return rows;
}

/**
 * Balanced spatial regions: k-means with each region's size fixed to the evaluator's balanced allocation,
 * solved exactly at every step as an assignment problem. Deterministic: farthest-point initialization from the
 * point farthest from the centroid, and regions numbered from anterior to posterior (then left to right).
 */
export function assignBalancedRegions(points: Point[], count: number): number[] {
  if (points.length !== 64) throw new Error('需要64个电极。');
  if (![1, 2, 3, 4, 6].includes(count)) throw new Error('区域数须为1、2、3、4或6。');
  if (count === 1) return points.map(() => 0);
  const sizes = regionSizes(count), slots = sizes.flatMap((size, region) => Array.from({ length: size }, () => region));
  const squared = (a: Point, b: Point) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2;
  const centroid = [0, 1, 2].map(axis => points.reduce((sum, p) => sum + p[axis], 0) / 64) as Point;
  const farthest = (from: (p: Point) => number) => points.reduce((best, p, i) => (from(p) > from(points[best]) ? i : best), 0);
  const centers: Point[] = [points[farthest(p => squared(p, centroid))]];
  while (centers.length < count) centers.push(points[farthest(p => Math.min(...centers.map(c => squared(p, c))))]);
  let labels: number[] = [];
  for (let step = 0; step < 100; step++) {
    const rows = assignment(points.map(p => slots.map(region => squared(p, centers[region]))));
    const next = Array.from(rows, slot => slots[slot]);
    if (next.every((label, i) => label === labels[i])) break;
    labels = next;
    for (let region = 0; region < count; region++) {
      const members = points.filter((_, i) => labels[i] === region);
      centers[region] = [0, 1, 2].map(axis => members.reduce((sum, p) => sum + p[axis], 0) / members.length) as Point;
    }
  }
  // Number regions anterior to posterior, ties left to right. The evaluator checks the multiset of sizes, not their order.
  const order = centers.map((c, region) => ({ c, region })).sort((a, b) => b.c[1] - a.c[1] || a.c[0] - b.c[0] || a.region - b.region);
  const renamed = new Map(order.map((item, index) => [item.region, index]));
  return labels.map(label => renamed.get(label)!);
}
