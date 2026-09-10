# Ernie anatomical display buffers

This derivative contains the exterior scalp and the largest gray-matter surface
component from the same hash-verified SimNIBS Ernie mesh. It is for anatomical
visualization only. It is not qualified for EEG forward modeling, source
localization, or AR computation.

## Attribution and license

Derived from SimNIBS example dataset v4.1, Ernie head model.
© SimNIBS developers 2024. [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).
The copyright and license are stated in the
[official v4.1 release](https://github.com/simnibs/example-dataset/releases/tag/v4.1).
Keep attribution, the license link, and the description of modifications when
redistributing these buffers. The license contains a noncommercial condition.

## Geometry and provenance

| Buffer | Vertices | Triangles | Binary bytes |
| --- | ---: | ---: | ---: |
| scalp.bin | 52,410 | 104,864 | 1,415,336 |
| cortex.bin | 154,967 | 309,211 | 6,035,040 |

The scalp is tag 1005's closed manifold component with the largest absolute
signed volume. The gray-matter display is tag 1002's component with the largest
triangle count. It includes both sides of the brain within one component; no
hemisphere parcellation is claimed. The manifest inventories every component.

No smoothing, decimation, cropping, gap repair, synthetic anatomy, translation,
or rotation is applied. The inferior face/neck termination is the source mesh
boundary. Selected raw coordinates are multiplied by 0.001 to convert mm to m
and stored as float32. The maximum absolute coordinate rounding error is
7.45e-9 m for scalp and 3.73e-9 m for gray matter. Exact float64 coordinates
remain in the original .msh identified by its manifest path and SHA-256.

Native axes are +X right, +Y anterior, +Z superior. Both buffers use the same
subject coordinate frame. The optional shared view center and optional Y-up
rotation in the manifest are display instructions only; they are not baked.
For a native Z-up Three.js viewer, use `camera.up.set(0, 0, 1)` and apply the
same scene scale and root transform to both buffers.

## Loading

All offsets are bytes; `count` is a scalar typed-array element count. All arrays
start at 4-byte-aligned offsets. Buffer byte order is little-endian. Positions
are Float32Array; normals are normalized Int8Array; scalp indices are
Uint16Array and cortex indices Uint32Array.

```js
const types = { Float32Array, Int8Array, Uint16Array, Uint32Array };
const geometry = new THREE.BufferGeometry();
for (const [name, d] of Object.entries(mesh.attributes)) {
  const array = new types[d.type](arrayBuffer, d.byteOffset, d.count);
  geometry.setAttribute(name, new THREE.BufferAttribute(array, d.itemSize, d.normalized));
}
const d = mesh.index;
geometry.setIndex(new THREE.BufferAttribute(new types[d.type](arrayBuffer, d.byteOffset, d.count), 1));
geometry.computeBoundingSphere();
```

Original triangle order is preserved. The scalp winding has positive signed
volume; gray matter has negative signed volume. Use a DoubleSide material for
gray matter, or invert its triangle winding and normals together in the viewer.
The selected gray-matter source component has 1,778 boundary edges and 4
nonmanifold edges. Neither mesh contains degenerate triangles. These are
documented source topology properties, not repaired display geometry.

## Verification

The adjacent `manifest.json` records the source mesh hash, surface selection,
coordinate conversion, buffer layout, topology and original exporter identity.
The App loads these frozen display buffers directly. The original export command
in that manifest is provenance, not an installation step in this checkout.

The source mesh is included in the separately installed scientific data bundle.
Run `python3 scripts/data_bundle.py verify` from the repository root to verify that
bundle. Display buffers do not replace the original mesh used by the FEM solver;
the browser and scientific backend use separate representations.
