/** Display-only checks. No browser, model loading, or scientific computation. */
import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { createDemandRenderer } from '../lib/demand-renderer.ts';

function frameQueue() {
  let next = 0;
  const callbacks = new Map();
  return {
    request(callback) { const id = next++; callbacks.set(id, callback); return id; },
    cancel(id) { callbacks.delete(id); },
    get pending() { return callbacks.size; },
    flush() {
      const batch = [...callbacks.entries()];
      callbacks.clear();
      batch.forEach(([, callback]) => callback(0));
    },
    settle() {
      let count = 0;
      while (callbacks.size && count < 200) { this.flush(); count++; }
      assert.equal(callbacks.size, 0, 'rendering must stop when the camera settles');
      return count;
    },
  };
}

await test('display changes coalesce into one frame and idle scenes stop drawing', () => {
  const frames = frameQueue();
  let draws = 0;
  const renderer = createDemandRenderer(() => { draws++; return false; }, frames);
  renderer.invalidate(); renderer.invalidate(); renderer.invalidate();
  assert.equal(frames.pending, 1);
  frames.flush();
  assert.equal(draws, 1);
  assert.equal(frames.pending, 0);
  frames.flush();
  assert.equal(draws, 1);
  renderer.dispose();
});

await test('installed OrbitControls damping continues through rotation and stops at rest', () => {
  const frames = frameQueue();
  const camera = new THREE.PerspectiveCamera();
  camera.position.set(0, 0, 6);
  const controls = new OrbitControls(camera, null);
  controls.enableDamping = true;
  controls.dampingFactor = .09;
  let draws = 0;
  const renderer = createDemandRenderer(() => { draws++; return controls.update(); }, frames);
  controls.addEventListener('change', renderer.invalidate);
  const before = camera.position.clone();
  controls.rotateLeft(.5);
  assert.equal(frames.pending, 1);
  const count = frames.settle();
  assert.ok(count > 1, 'the initial pointer update must retain its damping frames');
  assert.ok(before.distanceTo(camera.position) > 2, 'rotation reaches the damped target');
  const settled = draws;
  frames.flush();
  assert.equal(draws, settled, 'there is no persistent idle animation');
  controls.removeEventListener('change', renderer.invalidate);
  renderer.dispose();
});

await test('hidden scenes cancel queued frames and show the latest changes on return', () => {
  const frames = frameQueue();
  let value = 'original', displayed, draws = 0;
  const renderer = createDemandRenderer(() => { displayed = value; draws++; return false; }, frames);
  renderer.invalidate();
  renderer.setEnabled(false);
  assert.equal(frames.pending, 0, 'a queued frame with ID zero is also cancelled');
  value = 'updated while hidden';
  renderer.invalidate(); renderer.renderNow(); frames.flush();
  assert.equal(draws, 0);
  renderer.setEnabled(true);
  assert.equal(frames.pending, 1);
  frames.flush();
  assert.equal(displayed, value);
  assert.equal(draws, 1);
  assert.equal(frames.pending, 0);
  renderer.dispose();
});

await test('resizing repaints immediately without a duplicate queued frame', () => {
  const frames = frameQueue();
  let draws = 0;
  const renderer = createDemandRenderer(() => { draws++; return false; }, frames);
  renderer.invalidate();
  renderer.renderNow();
  assert.equal(draws, 1);
  assert.equal(frames.pending, 0);
  frames.flush();
  assert.equal(draws, 1);
  renderer.dispose();
});

await test('changes requested during a draw are retained and disposal releases queued work', () => {
  const frames = frameQueue();
  let draws = 0;
  const renderer = createDemandRenderer(() => {
    draws++;
    if (draws === 1) renderer.invalidate();
    return false;
  }, frames);
  renderer.invalidate(); frames.flush();
  assert.equal(frames.pending, 1);
  renderer.dispose();
  assert.equal(frames.pending, 0);
  renderer.invalidate(); renderer.renderNow(); renderer.setEnabled(true); frames.flush();
  assert.equal(draws, 1);
});
