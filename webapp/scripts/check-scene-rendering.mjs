/** Exercise display events with the actual scene and layers, without WebGL. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { sceneFixture } from './helpers/viewer-fixture.mjs';

await test('signal color and selection changes repaint a stationary scene once', t => {
  const f = sceneFixture(t);
  try {
    f.scene.setLayout({ regionCount: 1, allocation: [64], domainMode: 'whole_surface', radiusCm: 1,
      recordedLayout: { id: 'display-test', xyzMm: Array.from({ length: 64 }, () => [100, 0, 0]),
        regionIndices: Array(64).fill(0), referenceXyzMm: Array.from({ length: 64 }, () => [100, 0, 0]) } });
    f.settle();
    const count = Number(f.canvas.dataset.renderCount);
    const position = f.draws.at(-2).position.clone();
    f.scene.setSignals({ electrodeValues: Array(64).fill(.5), potentialLimit: 1, selectedElectrode: 7 });
    assert.equal(f.queue.size, 1);
    f.settle();
    assert.equal(Number(f.canvas.dataset.renderCount), count + 1);
    assert.equal(f.canvas.dataset.potentialCount, '64');
    assert.equal(f.canvas.dataset.selectedElectrode, '7');
    assert.ok(f.draws.at(-2).position.distanceTo(position) < 1e-12, 'signal updates do not move the camera');
  } finally { f.scene.dispose(); }
});

await test('offscreen and hidden-tab resizes pause rendering, then restore both viewports after focus', t => {
  const f = sceneFixture(t);
  try {
    f.scene.setLayout({ regionCount: 1, allocation: [3], domainMode: 'whole_surface', radiusCm: 1 });
    f.settle();
    f.intersections[0].callback([{ isIntersecting: false, intersectionRatio: 0 }]);
    const count = Number(f.canvas.dataset.renderCount);
    f.host.clientWidth = 1200; f.host.clientHeight = 800;
    f.resizes[0].callback(); f.scene.focusRegion(0); f.scene.setRearView(false); f.scene.setRearView(true);
    f.settle();
    assert.equal(Number(f.canvas.dataset.renderCount), count);
    assert.equal(f.canvas.dataset.renderPaused, 'true');
    f.document.hidden = true;
    f.intersections[0].callback([{ isIntersecting: true, intersectionRatio: 1 }]);
    f.resizes[0].callback(); f.settle();
    assert.equal(Number(f.canvas.dataset.renderCount), count, 'visible bounds do not override a hidden tab');
    f.document.hidden = false;
    f.document.dispatchEvent(new Event('visibilitychange'));
    f.settle();
    assert.equal(f.canvas.dataset.renderPaused, 'false');
    assert.equal(f.canvas.dataset.rearView, 'visible');
    assert.ok(Number(f.canvas.dataset.renderCount) > count);
    assert.deepEqual(f.viewports.at(-2), [1028, 608, 160, 180]);
    assert.deepEqual(f.viewports.at(-1), [0, 0, 1200, 800]);
    assert.equal(f.draws.at(-2).camera.aspect, 1.5);
    assert.equal(f.draws.at(-1).camera.aspect, 160 / 180);
    // Returning from a fullscreen-sized viewport retains a valid rear inset.
    f.host.clientWidth = 800; f.host.clientHeight = 400; f.resizes[0].callback(); f.settle();
    assert.deepEqual(f.viewports.at(-2), [628, 208, 160, 180]);
    assert.deepEqual(f.viewports.at(-1), [0, 0, 800, 400]);
  } finally { f.scene.dispose(); }
  assert.equal(f.queue.size, 0);
  assert.equal(f.resizes[0].disconnected, true);
  assert.equal(f.intersections[0].disconnected, true);
  assert.equal(f.canvas.removed, true);
});
