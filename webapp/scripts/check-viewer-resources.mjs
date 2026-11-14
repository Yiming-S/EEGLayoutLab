import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { createHash } from 'node:crypto';
import {
  loadHeadAssets,
  createHeadAssetLoader,
  applySourceRoiGroups,
} from '../viewer/assets.ts';
import { createHeadScene } from '../viewer/head-scene.ts';
import { REGION_COLORS } from '../viewer/contacts.ts';
import * as compatibility from '../lib/anatomical-head-scene.ts';
import { createSceneLifetime, releaseGroup } from '../viewer/resources.ts';
import { SOURCE_ROI_DEFINITION } from '../lib/source-regions.ts';
import { sceneFixture } from './helpers/viewer-fixture.mjs';

function assetFixture(t, mode = 'valid') {
  const bytes = new ArrayBuffer(52);
  new Float32Array(bytes, 0, 9).set([0, 0, 0, 0.1, 0, 0, 0, 0.1, 0]);
  new Int8Array(bytes, 36, 9).set([0, 0, 127, 0, 0, 127, 0, 0, 127]);
  new Uint16Array(bytes, 46, 3).set([0, 1, 2]);
  const descriptor = {
    id: 'scalp',
    file: 'scalp.bin',
    attributes: {
      position: {
        type: 'Float32Array',
        byteOffset: 0,
        count: 9,
        itemSize: 3,
        normalized: false,
      },
      normal: {
        type: 'Int8Array',
        byteOffset: 36,
        count: 9,
        itemSize: 3,
        normalized: true,
      },
    },
    index: {
      type: 'Uint16Array',
      byteOffset: 46,
      count: 3,
      itemSize: 1,
      normalized: false,
    },
  };
  const groups = Array.from({ length: 7 }, (_, materialIndex) => ({
    materialIndex,
    start: materialIndex <= 1 ? 0 : 3,
    count: materialIndex === 1 ? 3 : 0,
  }));
  const atlas = {
    definition_id: SOURCE_ROI_DEFINITION,
    mesh: {
      ...structuredClone(descriptor),
      id: 'cortex',
      file: 'cortex.bin',
      groups,
      sha256: createHash('sha256').update(new Uint8Array(bytes)).digest('hex'),
    },
  };
  if (mode === 'bad checksum') atlas.mesh.sha256 = '0'.repeat(64);
  if (mode === 'bad groups') atlas.mesh.groups = groups.slice(1);
  if (mode === 'bad buffer') atlas.mesh.attributes.position.count = 10000;
  const controller = new AbortController(),
    disposed = [];
  // oxlint-disable-next-line typescript/unbound-method -- wrapper calls the original with its geometry receiver
  const originalDispose = THREE.BufferGeometry.prototype.dispose;
  t.mock.method(THREE.BufferGeometry.prototype, 'dispose', function () {
    disposed.push(this);
    return originalDispose.call(this);
  });
  const fetchAsset = async (requestedUrl, { signal }) => {
    const url = requestedUrl.split('?')[0];
    if (url.endsWith('.json')) assert.equal(signal, controller.signal);
    else assert.notEqual(signal, controller.signal);
    if (url.endsWith('manifest.json'))
      return { ok: true, json: async () => ({ meshes: [descriptor] }) };
    if (url.endsWith('source-roi.json'))
      return { ok: true, json: async () => atlas };
    if (url.endsWith('cortex.bin') && mode === 'network failure')
      throw new Error('Network failed');
    return {
      ok: true,
      arrayBuffer: async () => {
        if (url.endsWith('cortex.bin') && mode === 'abort') controller.abort();
        return bytes;
      },
    };
  };
  return {
    controller,
    disposed,
    groups,
    load: createHeadAssetLoader({ fetch: fetchAsset }),
  };
}

void test('legacy viewer entry point exports the actual renderer, asset loader and palette', () => {
  assert.equal(compatibility.createHeadScene, createHeadScene);
  assert.equal(compatibility.loadHeadAssets, loadHeadAssets);
  assert.equal(compatibility.applySourceRoiGroups, applySourceRoiGroups);
  assert.equal(compatibility.REGION_COLORS, REGION_COLORS);
});

void test('asset loading preserves recorded units, packed normals and native atlas groups', async (t) => {
  const f = assetFixture(t);
  const geometries = await f.load(f.controller.signal);
  assert.equal(f.disposed.length, 0);
  assert.ok(
    Math.abs(geometries[0].getAttribute('position').getX(1) - 1) < 1e-7,
  );
  assert.equal(geometries[0].getAttribute('normal').getZ(0), 1);
  assert.ok(geometries[0].getAttribute('normal').array instanceof Int8Array);
  assert.deepEqual(geometries[1].groups, f.groups);
  for (const geometry of geometries) geometry.dispose();
  assert.equal(f.disposed.length, 2);
});

for (const [mode, disposals, message] of [
  ['network failure', 1, /Network failed/],
  ['bad checksum', 1, /checksum/],
  ['bad groups', 2, /Atlas requires/],
  ['bad buffer', 2, /length/],
  ['abort', 0, /aborted/i],
]) {
  void test(`asset ${mode} releases every allocated geometry exactly once`, async (t) => {
    const f = assetFixture(t, mode);
    await assert.rejects(f.load(f.controller.signal), message);
    assert.equal(f.disposed.length, disposals);
    assert.equal(new Set(f.disposed).size, disposals);
  });
}

void test('group cleanup deduplicates shared geometry, material and label texture ownership', () => {
  const group = new THREE.Group(),
    geometry = new THREE.BoxGeometry(),
    material = new THREE.MeshBasicMaterial();
  const texture = new THREE.Texture(),
    label = new THREE.SpriteMaterial({ map: texture });
  const counts = { geometry: 0, material: 0, texture: 0, label: 0 };
  for (const [name, value] of Object.entries({
    geometry,
    material,
    texture,
    label,
  }))
    value.addEventListener('dispose', () => counts[name]++);
  group.add(
    new THREE.Mesh(geometry, material),
    new THREE.Mesh(geometry, material),
    new THREE.Sprite(label),
    new THREE.Sprite(label),
  );
  releaseGroup(group);
  releaseGroup(group);
  assert.deepEqual(counts, { geometry: 1, material: 1, texture: 1, label: 1 });
  assert.equal(group.children.length, 0);
});

void test('scene lifetime runs every cleanup once even when one cleanup fails', () => {
  const lifetime = createSceneLifetime(),
    calls = [];
  lifetime.defer(() => calls.push('first'));
  lifetime.defer(() => {
    calls.push('failed');
    throw new Error('Cleanup failed');
  });
  lifetime.defer(() => calls.push('last'));
  assert.throws(() => lifetime.dispose(), AggregateError);
  lifetime.dispose();
  assert.deepEqual(calls, ['last', 'failed', 'first']);
});

void test('partial scene initialization removes listeners, observers, canvas and renderer; caller retains assets', (t) => {
  const f = sceneFixture(t, { initialize: false, failObserve: true });
  let scalp = 0,
    cortex = 0;
  f.scalp.addEventListener('dispose', () => scalp++);
  f.cortex.addEventListener('dispose', () => cortex++);
  assert.throws(() => f.create(), /Observer initialization failed/);
  assert.equal(f.renderer.disposed, 1);
  assert.equal(f.renderer.contextLosses, 1);
  assert.equal(f.canvas.removed, true);
  assert.equal(f.canvas.listenerCount, 0);
  assert.equal(f.document.listenerCount, 0);
  assert.equal(f.resizes[0].disconnected, true);
  assert.equal(f.queue.size, 0);
  assert.equal(scalp, 0);
  assert.equal(cortex, 0);
});

void test('successful scene cleanup is idempotent and releases both assets and browser subscriptions', (t) => {
  const f = sceneFixture(t);
  let scalp = 0,
    cortex = 0;
  f.scalp.addEventListener('dispose', () => scalp++);
  f.cortex.addEventListener('dispose', () => cortex++);
  f.scene.dispose();
  f.scene.dispose();
  assert.equal(f.renderer.disposed, 1);
  assert.equal(f.renderer.contextLosses, 1);
  assert.equal(scalp, 1);
  assert.equal(cortex, 1);
  assert.equal(f.canvas.listenerCount, 0);
  assert.equal(f.document.listenerCount, 0);
  assert.equal(f.resizes[0].disconnected, true);
  assert.equal(f.intersections[0].disconnected, true);
  assert.equal(f.queue.size, 0);
});

void test('renderer disposal failure still releases the WebGL context and all browser subscriptions', (t) => {
  const f = sceneFixture(t);
  f.renderer.dispose = () => {
    throw new Error('Renderer cleanup failed');
  };
  assert.throws(() => f.scene.dispose(), AggregateError);
  assert.equal(f.renderer.contextLosses, 1);
  assert.equal(f.canvas.removed, true);
  assert.equal(f.canvas.listenerCount, 0);
  assert.equal(f.document.listenerCount, 0);
  assert.equal(f.queue.size, 0);
  f.scene.dispose();
  assert.equal(f.renderer.contextLosses, 1);
});
