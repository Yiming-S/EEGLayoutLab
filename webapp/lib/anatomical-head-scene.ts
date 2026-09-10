import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import biosemiReference from '@/lib/biosemi64-reference.json';
import { mriMmToDisplay, type XYZ } from '@/lib/fixed64-results';
import { surfacePatchGeometry } from '@/lib/surface-patches';

export type DomainMode = 'whole_surface' | 'low_hair' | 'preset';
export type ViewName = 'oblique' | 'front' | 'left' | 'right' | 'back' | 'top';
export type LayoutOptions = {
  editor?: {
    enabled: boolean; active: boolean[]; selection: number[];
    candidates: { bank_indices: number[]; xyz_mm: XYZ[] }[];
    onSelect: (slot: number, multiple: boolean) => void;
    onMove: (slot: number, bankIndex: number) => void;
    onInvalid: () => void;
  };
  regionCount: number;
  allocation: number[];
  domainMode: DomainMode;
  maskCodes?: string[];
  radiusCm: number;
  sourceXyzMm?: XYZ[];
  sourceNormals?: XYZ[];
  selectedSource?: number;
  onSourceSelect?: (index: number) => void;
  electrodeValues?: number[];
  potentialLimit?: number;
  selectedElectrode?: number;
  onElectrodeSelect?: (index: number) => void;
  recordedLayout?: {
    id: string;
    xyzMm: XYZ[];
    regionIndices: number[];
    referenceXyzMm: XYZ[];
    regionPatchVertexIndices?: number[][];
    regionAreasCm2?: number[];
  };
};
export const REGION_COLORS = [
  '#128a80',
  '#376ec6',
  '#c8811b',
  '#8655ac',
  '#c34f68',
  '#598d37',
];
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
};
type Manifest = { meshes: MeshDescriptor[] };
type SurfacePoint = {
  position: THREE.Vector3;
  normal: THREE.Vector3;
  direction: THREE.Vector3;
};
const UP = new THREE.Vector3(0, 0, 1);
const DIRECTIONS: Record<ViewName, THREE.Vector3> = {
  oblique: new THREE.Vector3(-0.95, 1.7, 0.7).normalize(),
  front: new THREE.Vector3(0, 1, 0.06).normalize(),
  left: new THREE.Vector3(-1, 0, 0.06).normalize(),
  right: new THREE.Vector3(1, 0, 0.06).normalize(),
  back: new THREE.Vector3(0, -1, 0.06).normalize(),
  top: new THREE.Vector3(0, 0.001, 1).normalize(),
};
const ANCHORS: Record<string, [number, number, number]> = {
  PL: [-1, -0.45, -0.22],
  PR: [1, -0.45, -0.22],
  AL: [-1, -0.18, -0.07],
  AR: [1, -0.18, -0.07],
  FL: [-0.43, 0.9, 0.36],
  FM: [0, 1, 0.4],
  FR: [0.43, 0.9, 0.36],
  OL: [-0.48, 1, -0.06],
  OR: [0.48, 1, -0.06],
  crown: [0, 0, 1],
  occipital: [0, -1, 0.2],
  temporalLeft: [-1, 0, 0.28],
  temporalRight: [1, 0, 0.28],
  posterior: [0, -1, -0.4],
};
for (const code of ['PL', 'PR', 'AL', 'AR']) {
  for (const [suffix, z] of [
    ['superior', 0.3],
    ['middle', -0.1],
    ['inferior', -0.45],
  ] as const) {
    ANCHORS[`${code}_${suffix}`] = [ANCHORS[code][0], ANCHORS[code][1], z];
  }
}
function anchors(options: LayoutOptions) {
  const keys =
    options.domainMode === 'preset' && options.maskCodes?.length
      ? options.maskCodes
      : options.domainMode === 'whole_surface'
        ? [
            'crown',
            'FM',
            'occipital',
            'temporalLeft',
            'temporalRight',
            'posterior',
          ]
        : ['PL', 'PR', 'FM', 'FL', 'FR', 'OL'];
  return keys
    .slice(0, options.regionCount)
    .map((key) =>
      new THREE.Vector3(...(ANCHORS[key] ?? ANCHORS.FM)).normalize(),
    );
}
function releaseGroup(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  root.traverse((object) => {
    if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
      geometries.add(object.geometry);
      (Array.isArray(object.material)
        ? object.material
        : [object.material]
      ).forEach((m) => materials.add(m));
    }
  });
  geometries.forEach((g) => g.dispose());
  materials.forEach((m) => m.dispose());
  root.clear();
}
async function loadGeometry(descriptor: MeshDescriptor, signal: AbortSignal) {
  const response = await fetch(`/models/ernie/${descriptor.file}`, { signal });
  if (!response.ok) throw new Error('解剖模型文件加载失败');
  const buffer = await response.arrayBuffer();
  const geometry = new THREE.BufferGeometry();
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
      new Int8Array(buffer, normal.byteOffset, normal.count),
      3,
      true,
    ),
  );
  const index = descriptor.index;
  geometry.setIndex(
    new THREE.BufferAttribute(
      index.type === 'Uint16Array'
        ? new Uint16Array(buffer, index.byteOffset, index.count)
        : new Uint32Array(buffer, index.byteOffset, index.count),
      1,
    ),
  );
  // Source XYZ remain right / anterior / superior. One display unit = 100 mm.
  // Transform positions only; geometry.scale would quantize packed Int8 normals.
  const xyz = geometry.getAttribute('position');
  for (let i = 0; i < xyz.count; i++)
    xyz.setXYZ(i, xyz.getX(i) * 10, xyz.getY(i) * 10, xyz.getZ(i) * 10);
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}
export async function loadHeadAssets(signal: AbortSignal) {
  const response = await fetch('/models/ernie/manifest.json', { signal });
  if (!response.ok) throw new Error('解剖模型索引加载失败');
  const manifest = (await response.json()) as Manifest;
  const descriptors = ['scalp', 'cortex'].map((id) => {
    const descriptor = manifest.meshes.find((mesh) => mesh.id === id);
    if (!descriptor) throw new Error('解剖模型缺少头皮或脑表面');
    return descriptor;
  });
  const results = await Promise.allSettled(
    descriptors.map((descriptor) => loadGeometry(descriptor, signal)),
  );
  const failure = results.find((result) => result.status === 'rejected');
  if (failure || signal.aborted) {
    results.forEach((result) => {
      if (result.status === 'fulfilled') result.value.dispose();
    });
    throw failure?.status === 'rejected'
      ? failure.reason
      : new Error('Aborted');
  }
  return (results as PromiseFulfilledResult<THREE.BufferGeometry>[]).map(
    (result) => result.value,
  );
}
export function createHeadScene(
  host: HTMLDivElement,
  scalpGeometry: THREE.BufferGeometry,
  cortexGeometry: THREE.BufferGeometry,
) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.05, 50);
  camera.up.copy(UP);
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance',
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.2;
  const canvas = renderer.domElement;
  canvas.setAttribute(
    'aria-label',
    '可旋转的真实头部与64电极布局，方向键旋转，加减键缩放',
  );
  canvas.setAttribute('role', 'img');
  canvas.tabIndex = 0;
  Object.assign(canvas.style, {
    display: 'block',
    width: '100%',
    height: '100%',
    cursor: 'grab',
    touchAction: 'none',
  });
  host.appendChild(canvas);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.dampingFactor = 0.09;
  controls.enablePan = true;
  controls.screenSpacePanning = true;
  controls.rotateSpeed = 0.8;
  controls.minDistance = 1.7;
  controls.maxDistance = 15;
  controls.target.set(0, 0.04, -0.12);
  scene.add(new THREE.HemisphereLight('#fff9f3', '#79818e', 2.5));
  const key = new THREE.DirectionalLight('#fff2e6', 3.0);
  key.position.set(-3, 5, 6);
  scene.add(key);
  const fill = new THREE.DirectionalLight('#e4ecff', 1.2);
  fill.position.set(4, 0, 2);
  scene.add(fill);
  const back = new THREE.DirectionalLight('#fffaf4', 1.6);
  back.position.set(0, -4, 3);
  scene.add(back);
  const skinMaterial = new THREE.MeshStandardMaterial({
    color: '#cf987a',
    roughness: 0.82,
    metalness: 0,
  });
  const scalp = new THREE.Mesh(scalpGeometry, skinMaterial);
  const cortex = new THREE.Mesh(
    cortexGeometry,
    new THREE.MeshStandardMaterial({
      color: '#c8858a',
      roughness: 0.85,
      side: THREE.DoubleSide,
    }),
  );
  cortex.visible = false;
  scene.add(scalp, cortex);
  scene.updateMatrixWorld(true);
  const reference = new THREE.Group(),
    regions = new THREE.Group();
  scene.add(reference, regions);
  const sources = new THREE.Group();
  scene.add(sources);
  const raycaster = new THREE.Raycaster();
  // Radial display projection only: no electrode registration or geodesic claim.
  const project = (direction: THREE.Vector3): SurfacePoint => {
    const unit = direction.clone().normalize();
    raycaster.set(unit.clone().multiplyScalar(4), unit.clone().negate());
    const hit = raycaster.intersectObject(scalp, false)[0];
    if (!hit?.face) throw new Error('电极示意投影失败');
    const normal = (hit.normal ?? hit.face.normal).clone().normalize();
    if (normal.dot(unit) < 0) normal.negate();
    return { position: hit.point, normal, direction: unit };
  };
  const attachContact = (
    parent: THREE.Group,
    point: SurfacePoint,
    color: string,
    name: string,
    referencePoint: boolean,
  ) => {
    const contact = new THREE.Group(),
      radius = referencePoint ? 0.033 : 0.025;
    const pad = new THREE.Mesh(
      new THREE.CylinderGeometry(radius * 1.16, radius * 1.16, 0.008, 20),
      new THREE.MeshStandardMaterial({ color: '#eee8e1', roughness: 0.82 }),
    );
    const rim = new THREE.Mesh(
      new THREE.TorusGeometry(radius * 0.75, radius * 0.23, 8, 20),
      new THREE.MeshStandardMaterial({
        color,
        roughness: 0.38,
        metalness: referencePoint ? 0.28 : 0.12,
      }),
    );
    rim.rotation.x = Math.PI / 2;
    rim.position.y = 0.01;
    const center = new THREE.Mesh(
      new THREE.CylinderGeometry(radius * 0.41, radius * 0.41, 0.012, 16),
      new THREE.MeshStandardMaterial({
        color: '#f6f9fa',
        roughness: 0.3,
        metalness: 0.12,
      }),
    );
    center.position.y = 0.009;
    const pin = new THREE.Mesh(
      new THREE.CylinderGeometry(radius * 0.14, radius * 0.14, 0.014, 8),
      new THREE.MeshStandardMaterial({
        color: '#657782',
        metalness: 0.5,
        roughness: 0.4,
      }),
    );
    pin.position.y = 0.015;
    contact.add(pad, rim, center, pin);
    contact.position.copy(point.position).addScaledVector(point.normal, 0.012);
    contact.quaternion.setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      point.normal,
    );
    contact.userData = { name, color, center, rim };
    parent.add(contact);
  };
  biosemiReference.channels.forEach((channel) => {
    const point = project(new THREE.Vector3(...channel.xyz_m));
    attachContact(reference, point, '#8c9da7', channel.name, true);
  });
  let referenceKey = 'schematic';
  const recordedPoint = (xyzMm: XYZ): SurfacePoint => {
    const position = new THREE.Vector3(...mriMmToDisplay(xyzMm));
    // Use the closest display vertex ONLY for glyph orientation. Never move
    // the recorded scientific coordinate or radially project the layout.
    const vertices = scalpGeometry.getAttribute('position');
    const normals = scalpGeometry.getAttribute('normal');
    let best = 0,
      distance = Infinity;
    for (let i = 0; i < vertices.count; i++) {
      const d =
        (vertices.getX(i) - position.x) ** 2 +
        (vertices.getY(i) - position.y) ** 2 +
        (vertices.getZ(i) - position.z) ** 2;
      if (d < distance) {
        best = i;
        distance = d;
      }
    }
    const normal = new THREE.Vector3(
      normals.getX(best),
      normals.getY(best),
      normals.getZ(best),
    ).normalize();
    return { position, normal, direction: position.clone().normalize() };
  };
  let showReference = true,
    showRegions = true,
    regionPointCount = 0;
  let regionFocus: SurfacePoint[][] = [];
  let contacts: THREE.Group[] = [];
  let selectElectrode: ((index: number) => void) | undefined;
  let selectSource: ((index: number) => void) | undefined;
  let editor: LayoutOptions['editor'];
  let recordedOptions: LayoutOptions['recordedLayout'];
  const syncVisibility = () => {
    reference.visible = showReference;
    regions.visible = showRegions;
    canvas.dataset.referenceCount = showReference ? '64' : '0';
    canvas.dataset.visibleRegionCount = showRegions
      ? String(regionPointCount)
      : '0';
  };
  const setLayout = (options: LayoutOptions) => {
    releaseGroup(sources);
    for (const [i, xyz] of (options.sourceXyzMm ?? []).entries()) {
      const marker = new THREE.Mesh(new THREE.SphereGeometry(.018, 10, 8), new THREE.MeshBasicMaterial({ color: '#ffd14a', depthTest: false, transparent: true, opacity: .9 }));
      marker.userData.sourceIndex = i;
      marker.position.set(...mriMmToDisplay(xyz)); marker.renderOrder = 10; sources.add(marker);
      const normal = options.sourceNormals?.[i];
      if (normal) {
        const origin = mriMmToDisplay(xyz), end = mriMmToDisplay(xyz.map((v, j) => v + normal[j] * 12) as XYZ);
        const direction = new THREE.Vector3(...end).sub(new THREE.Vector3(...origin)).normalize();
        const arrow = new THREE.ArrowHelper(direction, new THREE.Vector3(...origin), .12, '#b57808', .035, .018);
        sources.add(arrow);
      }
    }
    const recorded = options.recordedLayout;
    recordedOptions = recorded;
    if (
      recorded &&
      (recorded.xyzMm.length !== 64 ||
        recorded.regionIndices.length !== 64 ||
        recorded.referenceXyzMm.length !== 64)
    )
      throw new Error('实验布局必须含64个记录坐标');
    releaseGroup(regions);
    contacts = [];
    regionFocus = Array.from({ length: options.regionCount }, () => []);
    regionPointCount = 0;
    const nextReferenceKey = recorded
      ? JSON.stringify(recorded.referenceXyzMm)
      : 'schematic';
    if (referenceKey !== nextReferenceKey) {
      releaseGroup(reference);
      biosemiReference.channels.forEach((channel, i) => {
        const point = recorded
          ? recordedPoint(recorded.referenceXyzMm[i])
          : project(new THREE.Vector3(...channel.xyz_m));
        attachContact(reference, point, '#8c9da7', channel.name, true);
      });
      referenceKey = nextReferenceKey;
    }
    if (recorded) {
      if (recorded.regionPatchVertexIndices) {
        if (recorded.regionPatchVertexIndices.length !== options.regionCount) throw new Error('区域面片数量与布局不符');
        recorded.regionPatchVertexIndices.forEach((ids, r) => {
          const geometry = surfacePatchGeometry(scalpGeometry, ids, .001);
          const fill = new THREE.Mesh(geometry.fill, new THREE.MeshBasicMaterial({ color: REGION_COLORS[r], transparent: true, opacity: .30, depthWrite: false, side: THREE.DoubleSide }));
          const boundary = new THREE.LineSegments(geometry.boundary, new THREE.LineBasicMaterial({ color: REGION_COLORS[r] }));
          fill.name = `区域${r+1}表面`; boundary.name = `区域${r+1}边界`;
          regions.add(fill, boundary);
        });
      }
      recorded.xyzMm.forEach((xyz, i) => {
        const point = recordedPoint(xyz);
        regionFocus[recorded.regionIndices[i]].push(point);
        attachContact(
          regions,
          point,
          REGION_COLORS[recorded.regionIndices[i]],
          `实验电极 ${i + 1}`,
          false,
        );
        const contact = regions.children[regions.children.length - 1] as THREE.Group;
        contact.userData.electrodeIndex = i;
        contacts.push(contact);
      });
      regionPointCount = 64;
      canvas.dataset.electrodeCount = '64';
      canvas.dataset.layoutSource = 'recorded-fem';
      canvas.dataset.layoutId = recorded.id;
      canvas.dataset.patchCount = String(recorded.regionPatchVertexIndices?.length ?? 0);
      syncVisibility();
      return;
    }
    canvas.dataset.layoutSource = 'schematic';
    delete canvas.dataset.layoutId;
    canvas.dataset.patchCount = '0';
    const golden = Math.PI * (3 - Math.sqrt(5));
    anchors(options).forEach((direction, r) => {
      const color = REGION_COLORS[r],
        center = project(direction);
      const helper =
        Math.abs(direction.z) > 0.9 ? new THREE.Vector3(0, 1, 0) : UP;
      const u = new THREE.Vector3().crossVectors(direction, helper).normalize(),
        v = new THREE.Vector3().crossVectors(direction, u).normalize();
      const angularRadius = options.radiusCm / 10 / center.position.length();
      const pointAt = (angle: number, radiusFactor: number) =>
        project(
          direction
            .clone()
            .addScaledVector(u, angularRadius * radiusFactor * Math.cos(angle))
            .addScaledVector(v, angularRadius * radiusFactor * Math.sin(angle)),
        );
      const outline: THREE.Vector3[] = [];
      for (let j = 0; j <= 48; j++) {
        const p = pointAt((j * Math.PI) / 24, 1);
        outline.push(p.position.clone().addScaledVector(p.normal, 0.008));
      }
      const boundary = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(outline),
        new THREE.LineDashedMaterial({
          color,
          dashSize: 0.025,
          gapSize: 0.018,
          transparent: true,
          opacity: 0.8,
        }),
      );
      boundary.computeLineDistances();
      regions.add(boundary);
      const count = options.allocation[r] ?? 0;
      for (let i = 0; i < count; i++) {
        const point = pointAt(i * golden, 0.86 * Math.sqrt((i + 0.5) / count));
        attachContact(regions, point, color, `区域${r + 1} · ${i + 1}`, false);
        regionPointCount += 1;
      }
    });
    canvas.dataset.electrodeCount = String(regionPointCount);
    syncVisibility();
  };
  let fitDistance = 6,
    initialized = false;
  const target = controls.target.clone();
  const resize = () => {
    const width = Math.max(host.clientWidth, 1),
      height = Math.max(host.clientHeight, 1);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    const halfVertical = THREE.MathUtils.degToRad(camera.fov / 2),
      halfHorizontal = Math.atan(Math.tan(halfVertical) * camera.aspect);
    const nextFit = Math.max(
      1.45 / Math.tan(halfVertical),
      1.13 / Math.tan(halfHorizontal),
    );
    const current = initialized
      ? camera.position.clone().sub(controls.target)
      : DIRECTIONS.oblique.clone();
    const relativeZoom = initialized ? current.length() / fitDistance : 1;
    fitDistance = nextFit;
    camera.position
      .copy(controls.target)
      .addScaledVector(current.normalize(), fitDistance * relativeZoom);
    camera.updateProjectionMatrix();
    controls.update();
    initialized = true;
    // Resizing clears the drawing buffer; repaint in the same callback so
    // fullscreen transitions do not expose an empty canvas between frames.
    renderer.render(scene, camera);
  };
  const setView = (name: ViewName) => {
    controls.target.copy(target);
    camera.position.copy(target).addScaledVector(DIRECTIONS[name], fitDistance);
    controls.update();
  };
  const zoom = (factor: number) => {
    const delta = camera.position.clone().sub(controls.target),
      distance = THREE.MathUtils.clamp(
        delta.length() * factor,
        controls.minDistance,
        controls.maxDistance,
      );
    camera.position
      .copy(controls.target)
      .addScaledVector(delta.normalize(), distance);
    controls.update();
  };
  const keydown = (event: KeyboardEvent) => {
    if (event.key === '+' || event.key === '=') zoom(0.82);
    else if (event.key === '-') zoom(1.22);
    else if (event.key === 'Home') setView('oblique');
    else if (
      ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)
    ) {
      const delta = camera.position.clone().sub(controls.target),
        axis =
          event.key === 'ArrowLeft' || event.key === 'ArrowRight'
            ? UP
            : new THREE.Vector3().crossVectors(delta, UP).normalize();
      delta.applyAxisAngle(
        axis,
        ['ArrowLeft', 'ArrowUp'].includes(event.key) ? 0.16 : -0.16,
      );
      camera.position.copy(controls.target).add(delta);
      controls.update();
    } else return;
    event.preventDefault();
  };
  canvas.addEventListener('keydown', keydown);
  let pointerStart: { x: number; y: number } | null = null;
  const pointRay = (e: PointerEvent) => {
    const box = canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2((e.clientX-box.left)/box.width*2-1, -(e.clientY-box.top)/box.height*2+1), camera);
  };
  let drag: { slot: number; target: number | null; valid: boolean; position: THREE.Vector3; quaternion: THREE.Quaternion } | null = null;
  const pointerDown = (e: PointerEvent) => {
    pointerStart = { x: e.clientX, y: e.clientY };
    if (!editor?.enabled || !showRegions || e.button !== 0) return;
    pointRay(e);
    const scalpDistance = raycaster.intersectObject(scalp, false)[0]?.distance ?? Infinity;
    const hits = raycaster.intersectObjects(contacts, true).filter(h => h.distance <= scalpDistance + .06);
    let object: THREE.Object3D | null = hits[0]?.object ?? null;
    while (object && !Number.isInteger(object.userData.electrodeIndex)) object = object.parent;
    if (!object) return;
    const slot = object.userData.electrodeIndex as number;
    e.stopImmediatePropagation(); controls.enabled = false; canvas.setPointerCapture(e.pointerId);
    editor.onSelect(slot, e.shiftKey || e.metaKey || e.ctrlKey);
    drag = { slot, target: null, valid: true, position: object.position.clone(), quaternion: object.quaternion.clone() };
  };
  const pointerMove = (e: PointerEvent) => {
    if (!drag || !editor || !recordedOptions || !pointerStart || Math.hypot(e.clientX-pointerStart.x, e.clientY-pointerStart.y) < 5) return;
    e.stopImmediatePropagation(); pointRay(e);
    const hit = raycaster.intersectObject(scalp, false)[0];
    if (!hit) { drag.valid = false; return; }
    const candidates = editor.candidates[recordedOptions.regionIndices[drag.slot]];
    let nearest = 0, best = Infinity;
    candidates.xyz_mm.forEach((p, i) => { const distance = hit.point.distanceToSquared(new THREE.Vector3(...mriMmToDisplay(p))); if (distance < best) { nearest = i; best = distance; } });
    const xyz = candidates.xyz_mm[nearest];
    drag.target = candidates.bank_indices[nearest];
    drag.valid = !editor.active[drag.slot] || recordedOptions.xyzMm.every((p, i) => i === drag!.slot || !editor!.active[i] || Math.hypot(...p.map((v, k) => v-xyz[k])) >= 4-1e-7);
    const contact = contacts[drag.slot], point = recordedPoint(xyz);
    contact.position.copy(point.position).addScaledVector(point.normal, .012);
    contact.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), point.normal);
    (contact.userData.rim.material as THREE.MeshStandardMaterial).color.set(drag.valid ? '#111827' : '#dc2626');
    canvas.style.cursor = drag.valid ? 'grabbing' : 'not-allowed';
  };
  const pointerUp = (e: PointerEvent) => {
    if (drag) {
      e.stopImmediatePropagation();
      const d = drag; drag = null; controls.enabled = true;
      contacts[d.slot].position.copy(d.position); contacts[d.slot].quaternion.copy(d.quaternion);
      (contacts[d.slot].userData.rim.material as THREE.MeshStandardMaterial).color.set(editor?.selection.includes(d.slot) ? '#111827' : contacts[d.slot].userData.color);
      if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
      if (d.target !== null && d.valid && e.type !== 'pointercancel') editor?.onMove(d.slot, d.target);
      else if (!d.valid && e.type !== 'pointercancel') editor?.onInvalid();
      pointerStart = null; canvas.style.cursor = 'grab'; return;
    }
    if (!pointerStart || Math.hypot(e.clientX - pointerStart.x, e.clientY - pointerStart.y) > 5) return;
    const box = canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2((e.clientX - box.left) / box.width * 2 - 1, -(e.clientY - box.top) / box.height * 2 + 1), camera);
    const scalpDistance = editor ? raycaster.intersectObject(scalp, false)[0]?.distance ?? Infinity : Infinity;
    const hits = raycaster.intersectObjects([...contacts.filter(() => showRegions), ...sources.children], true).filter(hit => !editor || hit.distance <= scalpDistance + .06);
    for (const hit of hits) {
      let object: THREE.Object3D | null = hit.object;
      while (object) {
        if (Number.isInteger(object.userData.electrodeIndex)) {
          if (editor) editor.onSelect(object.userData.electrodeIndex, e.shiftKey || e.metaKey || e.ctrlKey);
          else selectElectrode?.(object.userData.electrodeIndex);
          return;
        }
        if (Number.isInteger(object.userData.sourceIndex)) { selectSource?.(object.userData.sourceIndex); return; }
        object = object.parent;
      }
    }
  };
  canvas.addEventListener('pointerdown', pointerDown, true);
  canvas.addEventListener('pointermove', pointerMove, true);
  canvas.addEventListener('pointerup', pointerUp, true);
  canvas.addEventListener('pointercancel', pointerUp, true);
  const start = () => {
      canvas.style.cursor = 'grabbing';
    },
    end = () => {
      canvas.style.cursor = 'grab';
    };
  controls.addEventListener('start', start);
  controls.addEventListener('end', end);
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  resize();
  let frame = 0;
  const animate = () => {
    controls.update();
    renderer.render(scene, camera);
    frame = requestAnimationFrame(animate);
  };
  animate();
  return {
    canvas,
    setLayout,
    setEditor(value: LayoutOptions['editor']) {
      editor = value;
      if (!value) return;
      contacts.forEach((contact, i) => {
        contact.traverse(object => { if (object instanceof THREE.Mesh) { object.material.transparent = !value.active[i]; object.material.opacity = value.active[i] ? 1 : .22; object.material.depthWrite = value.active[i]; } });
        (contact.userData.rim.material as THREE.MeshStandardMaterial).color.set(value.selection.includes(i) ? '#111827' : contact.userData.color);
        contact.scale.setScalar(value.selection.includes(i) ? 1.4 : 1);
      });
      canvas.dataset.electrodeCount = String(value.active.filter(Boolean).length);
      canvas.dataset.editorMode = value.enabled ? 'edit' : 'view';
    },
    setSignals(options: Pick<LayoutOptions, 'electrodeValues' | 'potentialLimit' | 'selectedElectrode' | 'selectedSource' | 'onElectrodeSelect' | 'onSourceSelect'>) {
      selectElectrode = options.onElectrodeSelect; selectSource = options.onSourceSelect;
      const values = options.electrodeValues, limit = options.potentialLimit;
      const valid = values?.length === 64 && values.every(Number.isFinite) && limit != null && Number.isFinite(limit) && limit > 0;
      contacts.forEach((contact, i) => {
        const t = valid ? THREE.MathUtils.clamp(values[i] / limit, -1, 1) : 0;
        const color = valid ? new THREE.Color('#f5f5f4').lerp(new THREE.Color(t < 0 ? '#2166ac' : '#b2182b'), Math.abs(t)) : new THREE.Color('#f6f9fa');
        (contact.userData.center.material as THREE.MeshStandardMaterial).color.copy(color);
        (contact.userData.rim.material as THREE.MeshStandardMaterial).color.set(options.selectedElectrode === i ? '#111827' : valid ? color : contact.userData.color);
        contact.scale.setScalar(options.selectedElectrode === i ? 1.35 : 1);
      });
      for (const object of sources.children) if (Number.isInteger(object.userData.sourceIndex)) object.scale.setScalar(object.userData.sourceIndex === options.selectedSource ? 1.6 : 1);
      canvas.dataset.potentialCount = valid ? '64' : '0';
      canvas.dataset.potentialLimit = valid ? String(limit) : '';
      canvas.dataset.selectedElectrode = String(options.selectedElectrode ?? '');
    },
    setView,
    focusRegion(index: number) {
      const points = regionFocus[index];
      if (!points?.length) return;
      const center = new THREE.Vector3(), direction = new THREE.Vector3();
      for (const point of points) { center.add(point.position); direction.add(point.normal); }
      center.divideScalar(points.length);
      if (direction.lengthSq() < 1e-8) direction.copy(center).sub(target);
      controls.target.copy(center);
      camera.position.copy(center).addScaledVector(direction.normalize(), fitDistance * .72);
      controls.update();
      canvas.dataset.focusedRegion = String(index + 1);
    },
    zoom,
    setReference(value: boolean) {
      showReference = value;
      syncVisibility();
    },
    setRegions(value: boolean) {
      showRegions = value;
      syncVisibility();
    },
    setBrain(value: boolean) {
      cortex.visible = value;
      skinMaterial.transparent = value;
      skinMaterial.opacity = value ? 0.18 : 1;
      skinMaterial.depthWrite = !value;
      skinMaterial.needsUpdate = true;
      canvas.dataset.viewMode = value ? 'brain' : 'scalp';
    },
    dispose() {
      cancelAnimationFrame(frame);
      observer.disconnect();
      canvas.removeEventListener('keydown', keydown);
      canvas.removeEventListener('pointerdown', pointerDown, true);
      canvas.removeEventListener('pointermove', pointerMove, true);
      canvas.removeEventListener('pointerup', pointerUp, true);
      canvas.removeEventListener('pointercancel', pointerUp, true);
      controls.removeEventListener('start', start);
      controls.removeEventListener('end', end);
      controls.dispose();
      releaseGroup(scene);
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
    },
  };
}
export type HeadScene = ReturnType<typeof createHeadScene>;
