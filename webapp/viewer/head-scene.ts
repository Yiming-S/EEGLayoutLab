import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { mriMmToDisplay } from '../lib/fixed64-results.ts';
import type { XYZ } from '../../contracts/layout';
import { createDemandRenderer } from '../lib/demand-renderer.ts';
import {
  SOURCE_REGIONS,
  SOURCE_ROI_DEFINITION,
  UNASSIGNED_SOURCE_COLOR,
  sourceRegion,
} from '../lib/source-regions.ts';
import type { LayoutOptions, ViewName } from './types.ts';
import { createContactsLayer } from './contacts.ts';
import { createSourceLayer } from './source-layer.ts';
import { createSceneLifetime, releaseGroup } from './resources.ts';

const UP = new THREE.Vector3(0, 0, 1);
const DIRECTIONS: Record<ViewName, THREE.Vector3> = {
  oblique: new THREE.Vector3(-0.95, 1.7, 0.7).normalize(),
  front: new THREE.Vector3(0, 1, 0.06).normalize(),
  left: new THREE.Vector3(-1, 0, 0.06).normalize(),
  right: new THREE.Vector3(1, 0, 0.06).normalize(),
  back: new THREE.Vector3(0, -1, 0.06).normalize(),
  top: new THREE.Vector3(0, 0.001, 1).normalize(),
};
export function createHeadScene(
  host: HTMLDivElement,
  scalpGeometry: THREE.BufferGeometry,
  cortexGeometry: THREE.BufferGeometry,
  rendererFactory: () => THREE.WebGLRenderer = () =>
    new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    }),
) {
  const lifetime = createSceneLifetime();
  const scene = new THREE.Scene();
  let initializedOwnership = false;
  try {
    const camera = new THREE.PerspectiveCamera(32, 1, 0.05, 50);
    camera.up.copy(UP);
    // A fixed overview uses the same scene and renderer, not another asset load
    // or WebGL context. The main camera remains the only interactive camera.
    const rearCamera = new THREE.PerspectiveCamera(32, 1, 0.05, 50);
    rearCamera.up.copy(UP);
    const renderer = rendererFactory();
    lifetime.defer(() => renderer.forceContextLoss());
    lifetime.defer(() => renderer.dispose());
    lifetime.defer(() =>
      releaseGroup(
        scene,
        initializedOwnership
          ? undefined
          : new Set([scalpGeometry, cortexGeometry]),
      ),
    );
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.2;
    renderer.autoClear = false;
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
    lifetime.defer(() => canvas.remove());
    host.appendChild(canvas);
    canvas.dataset.referenceShape = 'square';
    canvas.dataset.layoutShape = 'circle';
    canvas.dataset.renderMode = 'on-demand';
    canvas.dataset.renderCount = '0';
    const controls = new OrbitControls(camera, canvas);
    lifetime.defer(() => controls.dispose());
    // The page keeps scrolling past the viewer until the visitor engages it: wheel and pinch
    // zoom start after a click, tap or keyboard focus, and one-finger vertical swipes scroll
    // the page (OrbitControls sets touch-action none when it connects).
    canvas.style.touchAction = 'pan-y';
    controls.enableZoom = false;
    const engage = () => { controls.enableZoom = true; };
    const release = () => { controls.enableZoom = false; };
    canvas.addEventListener('pointerdown', engage);
    canvas.addEventListener('focus', engage);
    canvas.addEventListener('blur', release);
    lifetime.defer(() => {
      canvas.removeEventListener('pointerdown', engage);
      canvas.removeEventListener('focus', engage);
      canvas.removeEventListener('blur', release);
    });
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
      [UNASSIGNED_SOURCE_COLOR, ...SOURCE_REGIONS.map((r) => r.color)].map(
        (color) =>
          new THREE.MeshStandardMaterial({
            color,
            roughness: 0.85,
            side: THREE.DoubleSide,
          }),
      ),
    );
    cortex.visible = false;
    scene.add(scalp, cortex);
    scene.updateMatrixWorld(true);
    const raycaster = new THREE.Raycaster();
    const contactsLayer = createContactsLayer(scene, scalp, canvas, () =>
      invalidate(),
    );
    const sourceLayer = createSourceLayer(scene);
    let selectElectrode: ((index: number) => void) | undefined;
    let selectSource: ((index: number) => void) | undefined;
    let editor: LayoutOptions['editor'];
    const setLayout = (options: LayoutOptions) => {
      sourceLayer.setLayout(options);
      contactsLayer.setLayout(options);
    };
    let fitDistance = 6,
      initialized = false;
    const target = controls.target.clone();
    let showRearView = true;
    let viewportWidth = 1,
      viewportHeight = 1;
    let rearViewport = { x: 0, y: 0, width: 1, height: 1 };
    let renderedFrames = 0;
    const render = () => {
      renderer.setScissorTest(false);
      renderer.setViewport(0, 0, viewportWidth, viewportHeight);
      renderer.setClearColor('#f8fafb', 0);
      renderer.clear();
      renderer.render(scene, camera);
      if (showRearView) {
        const { x, y, width, height } = rearViewport;
        renderer.setViewport(x, y, width, height);
        renderer.setScissor(x, y, width, height);
        renderer.setScissorTest(true);
        renderer.setClearColor('#eff4f6', 1);
        renderer.clear();
        renderer.render(scene, rearCamera);
        renderer.setScissorTest(false);
        renderer.setViewport(0, 0, viewportWidth, viewportHeight);
      }
      canvas.dataset.renderCount = String(++renderedFrames);
    };
    const drawing = createDemandRenderer(() => {
      const moving = controls.update();
      render();
      return moving;
    });
    lifetime.defer(() => drawing.dispose());
    const invalidate = drawing.invalidate;
    controls.addEventListener('change', invalidate);
    lifetime.defer(() => controls.removeEventListener('change', invalidate));
    const resize = () => {
      const width = Math.max(host.clientWidth, 1),
        height = Math.max(host.clientHeight, 1);
      renderer.setSize(width, height, false);
      viewportWidth = width;
      viewportHeight = height;
      const insetWidth = Math.min(160, Math.max(96, width * 0.28));
      const insetHeight = insetWidth * 1.125;
      rearViewport = {
        x: width - insetWidth - 12,
        y: height - insetHeight - 12,
        width: insetWidth,
        height: insetHeight,
      };
      rearCamera.aspect = insetWidth / insetHeight;
      const rearHalfVertical = THREE.MathUtils.degToRad(rearCamera.fov / 2);
      const rearFit = Math.max(
        1.6 / Math.tan(rearHalfVertical),
        1.16 / (Math.tan(rearHalfVertical) * rearCamera.aspect),
      );
      rearCamera.position
        .copy(target)
        .addScaledVector(DIRECTIONS.back, rearFit);
      rearCamera.lookAt(target);
      rearCamera.updateProjectionMatrix();
      canvas.dataset.rearView = showRearView ? 'visible' : 'hidden';
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
      drawing.renderNow();
    };
    const setView = (name: ViewName) => {
      controls.target.copy(target);
      camera.position
        .copy(target)
        .addScaledVector(DIRECTIONS[name], fitDistance);
      controls.update();
      invalidate();
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
      invalidate();
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
        invalidate();
      } else return;
      event.preventDefault();
    };
    canvas.addEventListener('keydown', keydown);
    lifetime.defer(() => canvas.removeEventListener('keydown', keydown));
    let pointerStart: { x: number; y: number } | null = null;
    const overRearView = (e: PointerEvent) => {
      if (!showRearView) return false;
      const box = canvas.getBoundingClientRect();
      const x = e.clientX - box.left,
        y = box.height - (e.clientY - box.top);
      return (
        x >= rearViewport.x &&
        x <= rearViewport.x + rearViewport.width &&
        y >= rearViewport.y &&
        y <= rearViewport.y + rearViewport.height
      );
    };
    const pointRay = (e: PointerEvent) => {
      const box = canvas.getBoundingClientRect();
      raycaster.setFromCamera(
        new THREE.Vector2(
          ((e.clientX - box.left) / box.width) * 2 - 1,
          (-(e.clientY - box.top) / box.height) * 2 + 1,
        ),
        camera,
      );
    };
    let drag: {
      slot: number;
      target: number | null;
      valid: boolean;
      position: THREE.Vector3;
      quaternion: THREE.Quaternion;
    } | null = null;
    const pointerDown = (e: PointerEvent) => {
      // The overview never ray-picks or edits. Dragging it can still rotate the
      // main view through the existing OrbitControls listener.
      if (overRearView(e)) {
        pointerStart = null;
        return;
      }
      pointerStart = { x: e.clientX, y: e.clientY };
      if (!editor?.enabled || !contactsLayer.visible || e.button !== 0) return;
      pointRay(e);
      const scalpDistance =
        raycaster.intersectObject(scalp, false)[0]?.distance ?? Infinity;
      const hits = raycaster
        .intersectObjects(contactsLayer.contacts, true)
        .filter((h) => h.distance <= scalpDistance + 0.06);
      let object: THREE.Object3D | null = hits[0]?.object ?? null;
      while (object && !Number.isInteger(object.userData.electrodeIndex))
        object = object.parent;
      if (!object) return;
      const slot = object.userData.electrodeIndex as number;
      e.stopImmediatePropagation();
      controls.enabled = false;
      canvas.setPointerCapture(e.pointerId);
      editor.onSelect(slot, e.shiftKey || e.metaKey || e.ctrlKey);
      drag = {
        slot,
        target: null,
        valid: true,
        position: object.position.clone(),
        quaternion: object.quaternion.clone(),
      };
    };
    const pointerMove = (e: PointerEvent) => {
      if (
        !drag ||
        !editor ||
        !contactsLayer.recordedLayout ||
        !pointerStart ||
        Math.hypot(e.clientX - pointerStart.x, e.clientY - pointerStart.y) < 5
      )
        return;
      e.stopImmediatePropagation();
      pointRay(e);
      const hit = raycaster.intersectObject(scalp, false)[0];
      if (!hit) {
        drag.valid = false;
        return;
      }
      const candidates =
        editor.candidates[
          contactsLayer.recordedLayout.regionIndices[drag.slot]
        ];
      let nearest = 0,
        best = Infinity;
      candidates.xyz_mm.forEach((p, i) => {
        const distance = hit.point.distanceToSquared(
          new THREE.Vector3(...mriMmToDisplay(p)),
        );
        if (distance < best) {
          nearest = i;
          best = distance;
        }
      });
      const xyz = candidates.xyz_mm[nearest];
      drag.target = candidates.bank_indices[nearest];
      drag.valid =
        !editor.active[drag.slot] ||
        contactsLayer.recordedLayout.xyzMm.every(
          (p, i) =>
            i === drag!.slot ||
            !editor!.active[i] ||
            Math.hypot(...p.map((v, k) => v - xyz[k])) >= 4 - 1e-7,
        );
      const contact = contactsLayer.contacts[drag.slot],
        point = contactsLayer.recordedPoint(xyz);
      contact.position
        .copy(point.position)
        .addScaledVector(point.normal, 0.012);
      contact.quaternion.setFromUnitVectors(
        new THREE.Vector3(0, 1, 0),
        point.normal,
      );
      (contact.userData.rim.material as THREE.MeshStandardMaterial).color.set(
        drag.valid ? '#111827' : '#dc2626',
      );
      canvas.style.cursor = drag.valid ? 'grabbing' : 'not-allowed';
      invalidate();
    };
    const pointerUp = (e: PointerEvent) => {
      if (drag) {
        e.stopImmediatePropagation();
        const d = drag;
        drag = null;
        controls.enabled = true;
        contactsLayer.contacts[d.slot].position.copy(d.position);
        contactsLayer.contacts[d.slot].quaternion.copy(d.quaternion);
        (
          contactsLayer.contacts[d.slot].userData.rim
            .material as THREE.MeshStandardMaterial
        ).color.set(
          editor?.selection.includes(d.slot)
            ? '#111827'
            : contactsLayer.contacts[d.slot].userData.color,
        );
        invalidate();
        if (canvas.hasPointerCapture(e.pointerId))
          canvas.releasePointerCapture(e.pointerId);
        if (d.target !== null && d.valid && e.type !== 'pointercancel')
          editor?.onMove(d.slot, d.target);
        else if (!d.valid && e.type !== 'pointercancel') editor?.onInvalid();
        pointerStart = null;
        canvas.style.cursor = 'grab';
        return;
      }
      if (
        overRearView(e) ||
        !pointerStart ||
        Math.hypot(e.clientX - pointerStart.x, e.clientY - pointerStart.y) > 5
      )
        return;
      const box = canvas.getBoundingClientRect();
      raycaster.setFromCamera(
        new THREE.Vector2(
          ((e.clientX - box.left) / box.width) * 2 - 1,
          (-(e.clientY - box.top) / box.height) * 2 + 1,
        ),
        camera,
      );
      const scalpDistance = editor
        ? (raycaster.intersectObject(scalp, false)[0]?.distance ?? Infinity)
        : Infinity;
      const hits = raycaster
        .intersectObjects(
          [
            ...contactsLayer.contacts.filter(() => contactsLayer.visible),
            ...sourceLayer.group.children,
          ],
          true,
        )
        .filter((hit) => !editor || hit.distance <= scalpDistance + 0.06);
      for (const hit of hits) {
        let object: THREE.Object3D | null = hit.object;
        while (object) {
          if (Number.isInteger(object.userData.electrodeIndex)) {
            if (editor)
              editor.onSelect(
                object.userData.electrodeIndex,
                e.shiftKey || e.metaKey || e.ctrlKey,
              );
            else selectElectrode?.(object.userData.electrodeIndex);
            return;
          }
          if (Number.isInteger(object.userData.sourceIndex)) {
            selectSource?.(object.userData.sourceIndex);
            return;
          }
          object = object.parent;
        }
      }
    };
    canvas.addEventListener('pointerdown', pointerDown, true);
    lifetime.defer(() =>
      canvas.removeEventListener('pointerdown', pointerDown, true),
    );
    canvas.addEventListener('pointermove', pointerMove, true);
    lifetime.defer(() =>
      canvas.removeEventListener('pointermove', pointerMove, true),
    );
    canvas.addEventListener('pointerup', pointerUp, true);
    lifetime.defer(() =>
      canvas.removeEventListener('pointerup', pointerUp, true),
    );
    canvas.addEventListener('pointercancel', pointerUp, true);
    lifetime.defer(() =>
      canvas.removeEventListener('pointercancel', pointerUp, true),
    );
    const start = () => {
        canvas.style.cursor = 'grabbing';
      },
      end = () => {
        canvas.style.cursor = 'grab';
      };
    controls.addEventListener('start', start);
    lifetime.defer(() => controls.removeEventListener('start', start));
    controls.addEventListener('end', end);
    lifetime.defer(() => controls.removeEventListener('end', end));
    const observer = new ResizeObserver(resize);
    lifetime.defer(() => observer.disconnect());
    observer.observe(host);
    const bounds = host.getBoundingClientRect();
    let inViewport =
      bounds.width > 0 &&
      bounds.height > 0 &&
      bounds.bottom > 0 &&
      bounds.top < window.innerHeight &&
      bounds.right > 0 &&
      bounds.left < window.innerWidth;
    const syncActivity = () => {
      const active = inViewport && !document.hidden;
      canvas.dataset.renderPaused = String(!active);
      drawing.setEnabled(active);
    };
    const viewportObserver = new IntersectionObserver(([entry]) => {
      inViewport = entry.isIntersecting && entry.intersectionRatio > 0;
      syncActivity();
    });
    lifetime.defer(() => viewportObserver.disconnect());
    viewportObserver.observe(host);
    document.addEventListener('visibilitychange', syncActivity);
    lifetime.defer(() =>
      document.removeEventListener('visibilitychange', syncActivity),
    );
    syncActivity();
    resize();
    initializedOwnership = true;
    return {
      canvas,
      setLayout,
      setEditor(value: LayoutOptions['editor']) {
        editor = value;
        contactsLayer.setEditor(value);
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
        selectElectrode = options.onElectrodeSelect;
        selectSource = options.onSourceSelect;
        contactsLayer.setSignals(options);
        sourceLayer.select(options.selectedSource);
      },
      setView,
      /** Full-screen views take every touch gesture; inline views leave vertical swipes to the page. */
      setGestureCapture(value: boolean) {
        canvas.style.touchAction = value ? 'none' : 'pan-y';
        if (value) controls.enableZoom = true;
        else if (document.activeElement !== canvas) controls.enableZoom = false;
      },
      setRearView(value: boolean) {
        showRearView = value;
        canvas.dataset.rearView = value ? 'visible' : 'hidden';
        invalidate();
      },
      focusRegion(index: number) {
        const points = contactsLayer.regionFocus[index];
        if (!points?.length) return;
        const center = new THREE.Vector3(),
          direction = new THREE.Vector3();
        for (const point of points) {
          center.add(point.position);
          direction.add(point.normal);
        }
        center.divideScalar(points.length);
        if (direction.lengthSq() < 1e-8) direction.copy(center).sub(target);
        controls.target.copy(center);
        camera.position
          .copy(center)
          .addScaledVector(direction.normalize(), fitDistance * 0.72);
        controls.update();
        canvas.dataset.focusedRegion = String(index + 1);
        invalidate();
      },
      zoom,
      setReference: (value: boolean) => contactsLayer.setReference(value),
      setRegions: (value: boolean) => contactsLayer.setRegions(value),
      setBrain(value: boolean) {
        cortex.visible = value;
        skinMaterial.transparent = value;
        skinMaterial.opacity = value ? 0.18 : 1;
        skinMaterial.depthWrite = !value;
        skinMaterial.needsUpdate = true;
        canvas.dataset.viewMode = value ? 'brain' : 'scalp';
        invalidate();
      },
      setSourcePartitions(value: boolean) {
        const palette = [
          UNASSIGNED_SOURCE_COLOR,
          ...SOURCE_REGIONS.map((r) => r.color),
        ];
        cortex.material.forEach((material, index) =>
          material.color.set(value ? palette[index] : '#c8858a'),
        );
        canvas.dataset.sourcePartitions = value ? SOURCE_ROI_DEFINITION : 'off';
        invalidate();
      },
      focusSourceRegion(id: string) {
        const region = sourceRegion(id);
        if (!region) return;
        const center = new THREE.Vector3(
          ...mriMmToDisplay([...region.anchor] as XYZ),
        );
        const direction = center.clone().sub(target).normalize();
        controls.target.copy(center);
        camera.position
          .copy(center)
          .addScaledVector(direction, fitDistance * 0.8);
        controls.update();
        invalidate();
      },
      dispose: () => lifetime.dispose(),
    };
  } catch (error) {
    // The caller retains the two input geometries until initialization succeeds.
    try {
      lifetime.dispose();
    } catch (cleanupError) {
      throw new AggregateError(
        [error, cleanupError],
        'Scene initialization and cleanup failed',
      );
    }
    throw error;
  }
}

export type HeadScene = ReturnType<typeof createHeadScene>;
