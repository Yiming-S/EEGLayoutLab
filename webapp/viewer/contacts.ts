import * as THREE from 'three';
import biosemiReference from '../lib/biosemi64-reference.json' with { type: 'json' };
import { mriMmToDisplay } from '../lib/fixed64-results.ts';
import { FIGURE_REGION_COLORS } from '../lib/layout-figure.ts';
import { surfacePatchGeometry } from '../lib/surface-patches.ts';
import type { XYZ } from '../../contracts/layout';
import type { LayoutOptions, SurfacePoint } from './types.ts';
import { releaseGroup } from './resources.ts';

export const REGION_COLORS = [...FIGURE_REGION_COLORS];
const UP = new THREE.Vector3(0, 0, 1);
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

export const attachContact = (
  parent: THREE.Group,
  point: SurfacePoint,
  color: string,
  name: string,
  referencePoint: boolean,
) => {
  const contact = new THREE.Group(),
    radius = referencePoint ? 0.033 : 0.025;
  const pad = new THREE.Mesh(
    referencePoint
      ? new THREE.BoxGeometry(radius * 2.32, 0.008, radius * 2.32)
      : new THREE.CylinderGeometry(radius * 1.16, radius * 1.16, 0.008, 20),
    new THREE.MeshStandardMaterial({ color: '#eee8e1', roughness: 0.82 }),
  );
  const rim = new THREE.Mesh(
    referencePoint
      ? new THREE.BoxGeometry(radius * 1.75, 0.012, radius * 1.75)
      : new THREE.TorusGeometry(radius * 0.75, radius * 0.23, 8, 20),
    new THREE.MeshStandardMaterial({
      color,
      roughness: 0.38,
      metalness: referencePoint ? 0.28 : 0.12,
    }),
  );
  if (!referencePoint) rim.rotation.x = Math.PI / 2;
  rim.position.y = 0.01;
  const center = new THREE.Mesh(
    referencePoint
      ? new THREE.BoxGeometry(radius, 0.012, radius)
      : new THREE.CylinderGeometry(radius * 0.41, radius * 0.41, 0.012, 16),
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
  return contact;
};

export function createContactsLayer(
  scene: THREE.Scene,
  scalp: THREE.Mesh<THREE.BufferGeometry>,
  canvas: HTMLCanvasElement,
  invalidate: () => void,
) {
  const scalpGeometry = scalp.geometry;
  const reference = new THREE.Group(),
    regions = new THREE.Group();
  scene.add(reference, regions);
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
  let referenceContacts: THREE.Group[] = [];
  biosemiReference.channels.forEach((channel, i) => {
    const point = project(new THREE.Vector3(...channel.xyz_m));
    const contact = attachContact(
      reference,
      point,
      '#8c9da7',
      channel.name,
      true,
    );
    contact.userData.referenceIndex = i;
    contact.userData.channelName = channel.name;
    referenceContacts.push(contact);
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
  let schematicContacts: THREE.Group[] = [];
  let recordedOptions: LayoutOptions['recordedLayout'];
  const syncVisibility = () => {
    reference.visible = showReference;
    regions.visible = showRegions;
    canvas.dataset.referenceCount = showReference ? '64' : '0';
    canvas.dataset.visibleRegionCount = showRegions
      ? String(regionPointCount)
      : '0';
    invalidate();
  };
  const setLayout = (options: LayoutOptions) => {
    const recorded = options.recordedLayout;
    recordedOptions = recorded;
    if (
      recorded &&
      (recorded.xyzMm.length < 2 ||
        recorded.xyzMm.length > 64 ||
        recorded.regionIndices.length !== recorded.xyzMm.length ||
        recorded.referenceXyzMm.length !== 64)
    )
      throw new Error('实验布局必须含64个记录坐标');
    releaseGroup(regions);
    contacts = [];
    schematicContacts = [];
    regionFocus = Array.from({ length: options.regionCount }, () => []);
    regionPointCount = 0;
    const nextReferenceKey = recorded
      ? JSON.stringify(recorded.referenceXyzMm)
      : 'schematic';
    if (referenceKey !== nextReferenceKey) {
      releaseGroup(reference);
      referenceContacts = [];
      biosemiReference.channels.forEach((channel, i) => {
        const point = recorded
          ? recordedPoint(recorded.referenceXyzMm[i])
          : project(new THREE.Vector3(...channel.xyz_m));
        const contact = attachContact(
          reference,
          point,
          '#8c9da7',
          channel.name,
          true,
        );
        contact.userData.referenceIndex = i;
        contact.userData.channelName = channel.name;
        if (recorded) contact.userData.xyzMm = recorded.referenceXyzMm[i];
        referenceContacts.push(contact);
      });
      referenceKey = nextReferenceKey;
    }
    if (recorded) {
      if (recorded.regionPatchVertexIndices) {
        if (recorded.regionPatchVertexIndices.length !== options.regionCount)
          throw new Error('区域面片数量与布局不符');
        recorded.regionPatchVertexIndices.forEach((ids, r) => {
          const geometry = surfacePatchGeometry(scalpGeometry, ids, 0.001);
          const fill = new THREE.Mesh(
            geometry.fill,
            new THREE.MeshBasicMaterial({
              color: REGION_COLORS[r],
              transparent: true,
              opacity: 0.3,
              depthWrite: false,
              side: THREE.DoubleSide,
            }),
          );
          const boundary = new THREE.LineSegments(
            geometry.boundary,
            new THREE.LineBasicMaterial({ color: REGION_COLORS[r] }),
          );
          fill.name = `区域${r + 1}表面`;
          boundary.name = `区域${r + 1}边界`;
          regions.add(fill, boundary);
        });
      }
      recorded.xyzMm.forEach((xyz, i) => {
        const point = recordedPoint(xyz);
        const regionIndex = recorded.regionIndices[i];
        regionFocus[regionIndex].push(point);
        const label = options.electrodeNames?.[i] ?? `E${i + 1}`;
        const contact = attachContact(
          regions,
          point,
          REGION_COLORS[regionIndex],
          `实验电极 ${i + 1}`,
          false,
        );
        contact.userData.electrodeIndex = i;
        contact.userData.regionIndex = regionIndex;
        contact.userData.xyzMm = xyz;
        contact.userData.channelName = label;
        contact.userData.active = true;
        contacts.push(contact);
      });
      regionPointCount = recorded.xyzMm.length;
      canvas.dataset.electrodeCount = String(recorded.xyzMm.length);
      canvas.dataset.layoutSource = 'recorded-fem';
      canvas.dataset.layoutId = recorded.id;
      canvas.dataset.patchCount = String(
        recorded.regionPatchVertexIndices?.length ?? 0,
      );
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
        regionFocus[r].push(point);
        const contact = attachContact(
          regions,
          point,
          color,
          `区域${r + 1} · ${i + 1}`,
          false,
        );
        contact.userData.schematicIndex = schematicContacts.length;
        contact.userData.regionIndex = r;
        contact.userData.channelName = `#${i + 1}`;
        contact.userData.active = true;
        schematicContacts.push(contact);
        regionPointCount += 1;
      }
    });
    canvas.dataset.electrodeCount = String(regionPointCount);
    syncVisibility();
  };
  return {
    setLayout,
    recordedPoint,
    get contacts() {
      return contacts;
    },
    get schematicContacts() {
      return schematicContacts;
    },
    get referenceContacts() {
      return referenceContacts;
    },
    get regionFocus() {
      return regionFocus;
    },
    get recordedLayout() {
      return recordedOptions;
    },
    get visible() {
      return showRegions;
    },
    get referenceVisible() {
      return showReference;
    },
    setEditor(value: LayoutOptions['editor']) {
      if (!value) return;
      contacts.forEach((contact, i) => {
        contact.userData.active = Boolean(value.active[i]);
        contact.traverse((object) => {
          if (object instanceof THREE.Mesh) {
            object.material.transparent = !value.active[i];
            object.material.opacity = value.active[i] ? 1 : 0.22;
            object.material.depthWrite = value.active[i];
          }
        });
        (contact.userData.rim.material as THREE.MeshStandardMaterial).color.set(
          value.selection.includes(i) ? '#111827' : contact.userData.color,
        );
        contact.scale.setScalar(value.selection.includes(i) ? 1.4 : 1);
      });
      canvas.dataset.electrodeCount = String(
        value.active.filter(Boolean).length,
      );
      canvas.dataset.editorMode = value.enabled ? 'edit' : 'view';
      invalidate();
    },
    setSignals(
      options: Pick<
        LayoutOptions,
        | 'electrodeValues'
        | 'potentialLimit'
        | 'selectedElectrode'
        | 'selectedSource'
        | 'onElectrodeSelect'
        | 'onSourceSelect'
      >,
    ) {
      const values = options.electrodeValues,
        limit = options.potentialLimit;
      const valid =
        values?.length === 64 &&
        values.every(Number.isFinite) &&
        limit != null &&
        Number.isFinite(limit) &&
        limit > 0;
      contacts.forEach((contact, i) => {
        const t = valid ? THREE.MathUtils.clamp(values[i] / limit, -1, 1) : 0;
        const color = valid
          ? new THREE.Color('#f5f5f4').lerp(
              new THREE.Color(t < 0 ? '#2166ac' : '#b2182b'),
              Math.abs(t),
            )
          : new THREE.Color('#f6f9fa');
        (
          contact.userData.center.material as THREE.MeshStandardMaterial
        ).color.copy(color);
        (contact.userData.rim.material as THREE.MeshStandardMaterial).color.set(
          options.selectedElectrode === i
            ? '#111827'
            : valid
              ? color
              : contact.userData.color,
        );
        contact.scale.setScalar(options.selectedElectrode === i ? 1.35 : 1);
      });
      canvas.dataset.potentialCount = valid ? '64' : '0';
      canvas.dataset.potentialLimit = valid ? String(limit) : '';
      canvas.dataset.selectedElectrode = String(
        options.selectedElectrode ?? '',
      );
      invalidate();
    },
    setReference(value: boolean) {
      showReference = value;
      syncVisibility();
    },
    setRegions(value: boolean) {
      showRegions = value;
      syncVisibility();
    },
  };
}
