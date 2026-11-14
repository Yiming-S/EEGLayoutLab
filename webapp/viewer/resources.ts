import * as THREE from 'three';

export function releaseGroup(
  root: THREE.Object3D,
  preserveGeometries: ReadonlySet<THREE.BufferGeometry> = new Set(),
) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  const textures = new Set<THREE.Texture>();
  root.traverse((object) => {
    if (object instanceof THREE.Sprite) {
      materials.add(object.material);
      if (object.material.map) textures.add(object.material.map);
    }
    if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
      geometries.add(object.geometry);
      (Array.isArray(object.material)
        ? object.material
        : [object.material]
      ).forEach((m) => materials.add(m));
    }
  });
  geometries.forEach((g) => {
    if (!preserveGeometries.has(g)) g.dispose();
  });
  textures.forEach((t) => t.dispose());
  materials.forEach((m) => m.dispose());
  root.clear();
}

/** Own every scene subscription and GPU resource, including partial initialization. */
export function createSceneLifetime() {
  let disposed = false;
  const callbacks: (() => void)[] = [];
  return {
    defer(cleanup: () => void) {
      if (disposed) throw new Error('Scene lifetime already disposed');
      callbacks.push(cleanup);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      const failures: unknown[] = [];
      for (const cleanup of callbacks.reverse()) {
        try {
          cleanup();
        } catch (error) {
          failures.push(error);
        }
      }
      callbacks.length = 0;
      if (failures.length)
        throw new AggregateError(failures, 'Scene cleanup failed');
    },
  };
}
