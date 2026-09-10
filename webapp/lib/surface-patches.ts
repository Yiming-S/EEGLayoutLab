import * as THREE from 'three';

/** Native barycentric dual cells: every selected vertex owns 1/3 of each
 * incident triangle, exactly matching Python vertex_area_weights. */
export function surfacePatchGeometry(surface: THREE.BufferGeometry, vertexIds: number[], offset = 0) {
  const positions = surface.getAttribute('position');
  const normals = surface.getAttribute('normal');
  const index = surface.getIndex();
  if (!index) throw new Error('区域显示需要索引表面网格');
  const selected = new Set(vertexIds);
  if (!selected.size || selected.size !== vertexIds.length || vertexIds.some(id => !Number.isInteger(id) || id < 0 || id >= positions.count)) throw new Error('区域顶点索引无效');
  const triangles: number[] = [], edges = new Map<string, [THREE.Vector3, THREE.Vector3]>();
  const point = (ids: number[]) => {
    const p = new THREE.Vector3(), n = new THREE.Vector3();
    for (const id of ids) {
      p.add(new THREE.Vector3().fromBufferAttribute(positions, id));
      if (normals) n.add(new THREE.Vector3().fromBufferAttribute(normals, id));
    }
    return p.divideScalar(ids.length).addScaledVector(n.normalize(), offset);
  };
  const midpointKey = (a: number, b: number) => `e${Math.min(a,b)}:${Math.max(a,b)}`;
  for (let f = 0; f < index.count; f += 3) {
    const face = [index.getX(f), index.getX(f+1), index.getX(f+2)];
    if (!face.some(v => selected.has(v))) continue;
    for (let k = 0; k < 3; k++) {
      const a = face[k], b = face[(k+1)%3], c = face[(k+2)%3];
      if (!selected.has(a)) continue;
      const polygon = [point([a]), point([a,b]), point(face), point([c,a])];
      const keys = [`v${a}`, midpointKey(a,b), `f${f/3}`, midpointKey(c,a)];
      for (const j of [0,1,2,0,2,3]) triangles.push(...polygon[j].toArray());
      for (let j = 0; j < 4; j++) {
        const next = (j+1)%4, key = [keys[j],keys[next]].sort().join('|');
        if (edges.has(key)) edges.delete(key);
        else edges.set(key, [polygon[j],polygon[next]]);
      }
    }
  }
  const fill = new THREE.BufferGeometry();
  fill.setAttribute('position', new THREE.Float32BufferAttribute(triangles, 3));
  fill.computeVertexNormals();
  const boundary = new THREE.BufferGeometry();
  boundary.setAttribute('position', new THREE.Float32BufferAttribute([...edges.values()].flatMap(pair => pair.flatMap(p => p.toArray())), 3));
  return { fill, boundary };
}
