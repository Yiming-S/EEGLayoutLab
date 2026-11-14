/** Display-only regressions against the actual viewer modules. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as THREE from 'three';
import { attachContact } from '../viewer/contacts.ts';
import { releaseGroup } from '../viewer/resources.ts';
import { sceneFixture } from './helpers/viewer-fixture.mjs';

const component = readFileSync(new URL('../components/cluster-head-viewer.tsx', import.meta.url), 'utf8');

await test('standard contacts use square geometry; layout contacts remain circular without altering coordinates', () => {
  for (const reference of [false, true]) {
    const parent = new THREE.Group();
    const position = new THREE.Vector3(.1, .2, .3), original = position.clone();
    const normal = new THREE.Vector3(0, 0, 1);
    attachContact(parent, { position, normal, direction: normal }, '#128a80', 'contact', reference);
    const contact = parent.children[0];
    assert.equal(contact.children[0].geometry.type, reference ? 'BoxGeometry' : 'CylinderGeometry');
    assert.equal(contact.userData.rim.geometry.type, reference ? 'BoxGeometry' : 'TorusGeometry');
    assert.equal(contact.userData.center.geometry.type, reference ? 'BoxGeometry' : 'CylinderGeometry');
    assert.ok(position.equals(original));
    assert.ok(contact.position.distanceTo(original.clone().addScaledVector(normal, .012)) < 1e-12);
    releaseGroup(parent);
  }
});

await test('rear overview reuses the scene and renderer and restores the main viewport', t => {
  const f = sceneFixture(t); f.settle();
  f.scene.setRearView(false); f.settle();
  const before = f.draws.length;
  f.scene.setRearView(true); f.settle();
  assert.equal(f.draws.length, before + 2);
  assert.equal(f.draws.at(-1).scene, f.draws.at(-2).scene);
  assert.notEqual(f.draws.at(-1).camera, f.draws.at(-2).camera);
  assert.deepEqual(f.viewports.at(-1), [0, 0, 800, 400]);
  assert.equal(f.canvas.dataset.rearView, 'visible');
});

await test('rear overview does not start an editor selection or change a scientific coordinate', t => {
  const f = sceneFixture(t);
  const points = Array.from({ length: 64 }, () => [100, 0, 0]);
  const recordedLayout = { id: 'recorded', xyzMm: points, referenceXyzMm: points, regionIndices: Array(64).fill(0) };
  f.scene.setLayout({ regionCount: 1, allocation: [64], domainMode: 'whole_surface', radiusCm: 1, recordedLayout });
  let selections = 0, moves = 0;
  f.scene.setEditor({ enabled: true, active: Array(64).fill(true), selection: [], candidates: [{ bank_indices: [0], xyz_mm: [[100, 0, 0]] }],
    onSelect: () => selections++, onMove: () => moves++, onInvalid() {} });
  const before = structuredClone(points);
  const pointer = name => Object.assign(new Event(name), { clientX: 700, clientY: 60, button: 0, pointerId: 1, pointerType: 'mouse' });
  f.canvas.dispatchEvent(pointer('pointerdown')); f.canvas.dispatchEvent(pointer('pointerup'));
  assert.equal(selections, 0); assert.equal(moves, 0);
  assert.deepEqual(recordedLayout.xyzMm, before);
  assert.match(component, /data-rear-overview className="pointer-events-none/);
});

await test('compact mode preserves full-screen, region data, shape legend, and coordinate documentation', () => {
  for (const pattern of [/compact\?: boolean/, /regionAreasCm2\[index\]\.toFixed\(2\)/, /focusRegion\(index\)/,
    /props\.compact \? <details/, /Boolean\(props\.editor\?\.enabled\)/, /event\.key === 'Escape'/,
    /方形：标准64导/, /圆形：当前布局/]) assert.match(component, pattern);
});
