import * as THREE from 'three';
import { SOURCE_ROI_DEFINITION } from '../lib/source-regions.ts';
import { createModelByteCache, type AssetCacheOptions } from './asset-cache.ts';

type Attribute = {
  type: string;
  byteOffset: number;
  count: number;
  itemSize: number;
  normalized: boolean;
};
type MeshDescriptor = {
  id: string;
  file: string;
  attributes: { position: Attribute; normal: Attribute };
  index: Attribute;
  sha256?: string;
  groups?: { start: number; count: number; materialIndex: number }[];
};
type Manifest = { meshes: MeshDescriptor[] };
function createGeometry(descriptor: MeshDescriptor, buffer: ArrayBuffer) {
  const geometry = new THREE.BufferGeometry();
  try {
    const { position, normal } = descriptor.attributes;
    geometry.setAttribute(
      'position',
      new THREE.BufferAttribute(
        new Float32Array(buffer, position.byteOffset, position.count).slice(),
        3,
      ),
    );
    geometry.setAttribute(
      'normal',
      new THREE.BufferAttribute(
        new Int8Array(buffer, normal.byteOffset, normal.count).slice(),
        3,
        true,
      ),
    );
    const index = descriptor.index;
    geometry.setIndex(
      new THREE.BufferAttribute(
        index.type === 'Uint16Array'
          ? new Uint16Array(buffer, index.byteOffset, index.count).slice()
          : new Uint32Array(buffer, index.byteOffset, index.count).slice(),
        1,
      ),
    );
    if (descriptor.groups) applySourceRoiGroups(geometry, descriptor.groups);
    // Source XYZ remain right / anterior / superior. One display unit = 100 mm.
    // Transform positions only; geometry.scale would quantize packed Int8 normals.
    const xyz = geometry.getAttribute('position');
    for (let i = 0; i < xyz.count; i++)
      xyz.setXYZ(i, xyz.getX(i) * 10, xyz.getY(i) * 10, xyz.getZ(i) * 10);
    geometry.computeBoundingBox();
    geometry.computeBoundingSphere();
    return geometry;
  } catch (error) {
    geometry.dispose();
    throw error;
  }
}
export function createHeadAssetLoader(options: AssetCacheOptions = {}) {
  const fetchAsset = options.fetch ?? ((url, init) => fetch(url, init));
  const readBytes = createModelByteCache(options);
  return async function loadHeadAssets(signal: AbortSignal) {
    signal.throwIfAborted();
    // Revalidate small indexes on each mount so a deployment can replace files at
    // the same URL. Only bytes pinned to the indexes' checksums persist in memory.
    const response = await fetchAsset('/models/ernie/manifest.json', {
      signal,
      cache: 'no-cache',
    });
    if (!response.ok) throw new Error('解剖模型索引加载失败');
    const manifest = (await response.json()) as Manifest;
    const roiResponse = await fetchAsset('/models/ernie/source-roi.json', {
      signal,
      cache: 'no-cache',
    });
    if (!roiResponse.ok) throw new Error('Atlas surface index unavailable');
    const atlas = (await roiResponse.json()) as {
      definition_id: string;
      mesh: MeshDescriptor;
    };
    if (
      atlas.definition_id !== SOURCE_ROI_DEFINITION ||
      !atlas.mesh.groups ||
      !atlas.mesh.sha256
    )
      throw new Error('Atlas surface definition mismatch');
    const scalpDescriptor = manifest.meshes.find((mesh) => mesh.id === 'scalp');
    if (!scalpDescriptor) throw new Error('解剖模型缺少头皮或脑表面');
    const descriptors = [scalpDescriptor, atlas.mesh];
    const results = await Promise.allSettled(
      descriptors.map(async (descriptor) => {
        const buffer = await readBytes(
          {
            url: `/models/ernie/${descriptor.file}`,
            sha256: descriptor.sha256,
          },
          signal,
        );
        signal.throwIfAborted();
        return createGeometry(descriptor, buffer);
      }),
    );
    const failure = results.find((result) => result.status === 'rejected');
    if (failure || signal.aborted) {
      results.forEach((result) => {
        if (result.status === 'fulfilled') result.value.dispose();
      });
      throw failure?.status === 'rejected' ? failure.reason : signal.reason;
    }
    return (results as PromiseFulfilledResult<THREE.BufferGeometry>[]).map(
      (result) => result.value,
    );
  };
}
export const loadHeadAssets = createHeadAssetLoader();
export function applySourceRoiGroups(
  geometry: THREE.BufferGeometry,
  groups: { start: number; count: number; materialIndex: number }[],
) {
  // Whole native triangles have atlas-defined labels. No coordinate partition,
  // vertex color interpolation, smoothing, or mutation of source positions.
  let end = 0;
  if (groups.length !== 7)
    throw new Error('Atlas requires six ROIs plus unassigned cortex');
  for (const [index, group] of groups.entries()) {
    if (
      group.materialIndex !== index ||
      group.start !== end ||
      !Number.isInteger(group.count) ||
      group.count < 0 ||
      group.count % 3
    )
      throw new Error('Invalid atlas mesh groups');
    end += group.count;
  }
  if (end !== geometry.index?.count)
    throw new Error('Atlas groups do not cover the native mesh');
  geometry.clearGroups();
  for (const group of groups)
    geometry.addGroup(group.start, group.count, group.materialIndex);
}
