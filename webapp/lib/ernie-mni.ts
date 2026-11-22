import mapping from '../public/data/ernie-mni-mapping.json' with { type: 'json' };

/**
 * Ernie native <-> MNI on the Ernie scalp.
 *
 * `public/data/ernie-scalp-mni.bin` holds SimNIBS's nonlinear Ernie-to-MNI warp
 * evaluated at every vertex of `public/models/ernie/scalp.bin`, which is the forward
 * bank's scalp surface, and marks the triangles where that warp is usable (not the
 * lower face, ears and neck). A point is projected onto the usable scalp in its own
 * frame; the barycentric weights of that triangle give the point in the other frame. See
 * `scripts/build_ernie_mni_mapping.py` for the generation and its verification.
 */
export type Point = [number, number, number];
export type ErnieMniSurface = { native: Float64Array; mni: Float64Array; faces: Uint16Array; usable: Uint8Array; onUsable: Uint8Array; nativeEdge: number; mniEdge: number };
export type SurfaceMapping = { points: Point[]; distances_mm: number[] };

export const ERNIE_MNI_MAPPING = mapping;
export const MNI_EXPORT_SYSTEM = mapping.mni.coordinate_system as 'MNI152NLin6Asym';
export const MAPPING_ID = mapping.mapping_id;
export const MNI_IMPORT_LIMIT_MM = mapping.method.mni_import_limit_mm;
export const NATIVE_EXPORT_LIMIT_MM = mapping.method.native_export_limit_mm;

const VERTICES = mapping.scalp_buffer.vertices, TRIANGLES = mapping.scalp_buffer.triangles;

function longestEdge(vertices: Float64Array, faces: Uint16Array, usable: Uint8Array) {
  let longest = 0;
  for (let f = 0; f < faces.length; f += 3) if (usable[f / 3])
    for (const [a, b] of [[faces[f], faces[f + 1]], [faces[f + 1], faces[f + 2]], [faces[f + 2], faces[f]]]) {
      const dx = vertices[3 * a] - vertices[3 * b], dy = vertices[3 * a + 1] - vertices[3 * b + 1], dz = vertices[3 * a + 2] - vertices[3 * b + 2];
      longest = Math.max(longest, dx * dx + dy * dy + dz * dz);
    }
  return Math.sqrt(longest);
}

/** Reads the two buffers without checking their hashes; `verifiedSurface` checks them first. */
export function surfaceFromBuffers(scalp: ArrayBuffer, mniBuffer: ArrayBuffer): ErnieMniSurface {
  const { position_byte_offset: positionOffset, index_byte_offset: indexOffset } = mapping.scalp_buffer;
  if (scalp.byteLength < indexOffset + TRIANGLES * 6 || mniBuffer.byteLength !== mapping.mni_buffer.byte_length)
    throw new Error('Ernie–MNI映射数据长度不符。');
  const position = new DataView(scalp, positionOffset, VERTICES * 12), mniView = new DataView(mniBuffer, 0, VERTICES * 12);
  const native = new Float64Array(VERTICES * 3), mni = new Float64Array(VERTICES * 3);
  for (let i = 0; i < VERTICES * 3; i++) {
    native[i] = position.getFloat32(4 * i, true) * 1000;
    mni[i] = mniView.getFloat32(4 * i, true);
  }
  const indexView = new DataView(scalp, indexOffset, TRIANGLES * 6), faces = new Uint16Array(TRIANGLES * 3);
  for (let i = 0; i < faces.length; i++) faces[i] = indexView.getUint16(2 * i, true);
  const usable = new Uint8Array(mniBuffer.slice(VERTICES * 12)), onUsable = new Uint8Array(VERTICES);
  if (usable.length !== TRIANGLES || usable.some(flag => flag > 1)) throw new Error('Ernie–MNI映射数据格式不符。');
  for (let face = 0; face < TRIANGLES; face++) if (usable[face]) for (let k = 0; k < 3; k++) onUsable[faces[3 * face + k]] = 1;
  return { native, mni, faces, usable, onUsable, nativeEdge: longestEdge(native, faces, usable), mniEdge: longestEdge(mni, faces, usable) };
}

const hex = (buffer: ArrayBuffer) => Array.from(new Uint8Array(buffer), byte => byte.toString(16).padStart(2, '0')).join('');

export async function verifiedSurface(scalp: ArrayBuffer, mniBuffer: ArrayBuffer): Promise<ErnieMniSurface> {
  const [scalpHash, mniHash] = await Promise.all([scalp, mniBuffer].map(async buffer => hex(await crypto.subtle.digest('SHA-256', buffer))));
  if (scalpHash !== mapping.scalp_buffer.sha256 || mniHash !== mapping.mni_buffer.sha256) throw new Error('Ernie–MNI映射数据校验失败。');
  return surfaceFromBuffers(scalp, mniBuffer);
}

let loading: Promise<ErnieMniSurface> | null = null;
/** Fetches and verifies both buffers once per page. */
export function loadErnieMniSurface(fetcher: typeof fetch = fetch): Promise<ErnieMniSurface> {
  loading ??= (async () => {
    const buffers = await Promise.all([mapping.scalp_buffer.file, mapping.mni_buffer.file].map(async path => {
      const response = await fetcher(path);
      if (!response.ok) throw new Error('无法读取Ernie–MNI映射数据。');
      return response.arrayBuffer();
    }));
    return verifiedSurface(buffers[0], buffers[1]);
  })().catch(error => { loading = null; throw error; });
  return loading;
}

/** Closest point of triangle abc to p (Ericson, Real-Time Collision Detection 5.1.5), as barycentric weights. */
function closest(p: Point, v: Float64Array, a: number, b: number, c: number): [number, number, number] {
  const ax = v[3 * a], ay = v[3 * a + 1], az = v[3 * a + 2];
  const abx = v[3 * b] - ax, aby = v[3 * b + 1] - ay, abz = v[3 * b + 2] - az;
  const acx = v[3 * c] - ax, acy = v[3 * c + 1] - ay, acz = v[3 * c + 2] - az;
  const apx = p[0] - ax, apy = p[1] - ay, apz = p[2] - az;
  const d1 = abx * apx + aby * apy + abz * apz, d2 = acx * apx + acy * apy + acz * apz;
  if (d1 <= 0 && d2 <= 0) return [1, 0, 0];
  const bpx = p[0] - v[3 * b], bpy = p[1] - v[3 * b + 1], bpz = p[2] - v[3 * b + 2];
  const d3 = abx * bpx + aby * bpy + abz * bpz, d4 = acx * bpx + acy * bpy + acz * bpz;
  if (d3 >= 0 && d4 <= d3) return [0, 1, 0];
  const vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) { const t = d1 / (d1 - d3); return [1 - t, t, 0]; }
  const cpx = p[0] - v[3 * c], cpy = p[1] - v[3 * c + 1], cpz = p[2] - v[3 * c + 2];
  const d5 = abx * cpx + aby * cpy + abz * cpz, d6 = acx * cpx + acy * cpy + acz * cpz;
  if (d6 >= 0 && d5 <= d6) return [0, 0, 1];
  const vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) { const t = d2 / (d2 - d6); return [1 - t, 0, t]; }
  const va = d3 * d6 - d5 * d4;
  if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) { const t = (d4 - d3) / ((d4 - d3) + (d5 - d6)); return [0, 1 - t, t]; }
  const denominator = 1 / (va + vb + vc), t = vb * denominator, s = vc * denominator;
  return [1 - t - s, t, s];
}

const at = (v: Float64Array, f: Uint16Array, face: number, w: [number, number, number]): Point =>
  [0, 1, 2].map(axis => w[0] * v[3 * f[3 * face] + axis] + w[1] * v[3 * f[3 * face + 1] + axis] + w[2] * v[3 * f[3 * face + 2] + axis]) as Point;

/**
 * Projects each point onto the usable triangles of `from` and returns the same barycentric point on `to`.
 * Only triangles with a vertex within (nearest usable-vertex distance + longest usable edge) can hold the closest point.
 */
function transfer(points: Point[], from: Float64Array, to: Float64Array, surface: ErnieMniSurface, edge: number): SurfaceMapping {
  const { faces, usable, onUsable } = surface;
  const near = new Uint8Array(VERTICES), squared = new Float64Array(VERTICES), result: SurfaceMapping = { points: [], distances_mm: [] };
  for (const point of points) {
    if (point.length !== 3 || !point.every(Number.isFinite)) throw new Error('坐标必须是有限的三维数值。');
    let nearest = Infinity;
    for (let i = 0; i < VERTICES; i++) {
      if (!onUsable[i]) { squared[i] = Infinity; continue; }
      const dx = from[3 * i] - point[0], dy = from[3 * i + 1] - point[1], dz = from[3 * i + 2] - point[2];
      squared[i] = dx * dx + dy * dy + dz * dz; nearest = Math.min(nearest, squared[i]);
    }
    const radius = (Math.sqrt(nearest) + edge) ** 2;
    for (let i = 0; i < VERTICES; i++) near[i] = squared[i] <= radius ? 1 : 0;
    let best = Infinity, bestFace = -1, bestWeights: [number, number, number] = [1, 0, 0];
    for (let face = 0; face < TRIANGLES; face++) {
      const a = faces[3 * face], b = faces[3 * face + 1], c = faces[3 * face + 2];
      if (!usable[face] || (!near[a] && !near[b] && !near[c])) continue;
      const weights = closest(point, from, a, b, c), q = at(from, faces, face, weights);
      const distance = (q[0] - point[0]) ** 2 + (q[1] - point[1]) ** 2 + (q[2] - point[2]) ** 2;
      if (distance < best) { best = distance; bestFace = face; bestWeights = weights; }
    }
    result.points.push(at(to, faces, bestFace, bestWeights));
    result.distances_mm.push(Math.sqrt(best));
  }
  return result;
}

/** Ernie native mm -> MNI152NLin6Asym mm, through the point's projection on Ernie's scalp. */
export const ernieToMni = (points: Point[], surface: ErnieMniSurface) => transfer(points, surface.native, surface.mni, surface, surface.nativeEdge);
/** MNI mm -> Ernie native mm, through the point's projection on Ernie's scalp warped to MNI. */
export const mniToErnie = (points: Point[], surface: ErnieMniSurface) => transfer(points, surface.mni, surface.native, surface, surface.mniEdge);
