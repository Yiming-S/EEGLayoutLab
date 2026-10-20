/** Exercise display events with real Three.js geometry and controls, without WebGL. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { createDemandRenderer } from '../lib/demand-renderer.ts';

const text = readFileSync(new URL('../lib/anatomical-head-scene.ts', import.meta.url), 'utf8');
const source = ts.createSourceFile('scene.ts', text, ts.ScriptTarget.Latest, true);
const js = ts.transpileModule(source.statements.filter(node => !ts.isImportDeclaration(node))
  .map(node => node.getText(source)).join('\n').replace(/^export /gm, '') + '\nglobalThis.createScene = createHeadScene;',
{ compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;

function sceneFixture() {
  const queue = new Map();
  let nextFrame = 0;
  const frames = {
    request(callback) { const id = nextFrame++; queue.set(id, callback); return id; },
    cancel(id) { queue.delete(id); },
  };
  const document = new EventTarget();
  document.hidden = false;
  class Canvas extends EventTarget {
    style = {}; dataset = {}; ownerDocument = document;
    setAttribute() {} getRootNode() { return document; } remove() { this.removed = true; }
  }
  const canvases = [], draws = [], viewports = [];
  class Renderer {
    constructor() { this.domElement = new Canvas(); canvases.push(this.domElement); }
    setPixelRatio() {} setSize() {} setScissorTest() {} setClearColor() {} clear() {} setScissor() {}
    setViewport(...args) { viewports.push(args); }
    render(scene, camera) { draws.push({ camera, position: camera.position.clone() }); }
    dispose() {} forceContextLoss() {}
  }
  const resizes = [], intersections = [];
  class ResizeObserver {
    constructor(callback) { this.callback = callback; resizes.push(this); }
    observe() {} disconnect() { this.disconnected = true; }
  }
  class IntersectionObserver {
    constructor(callback) { this.callback = callback; intersections.push(this); }
    observe() {} disconnect() { this.disconnected = true; }
  }
  const host = { clientWidth: 800, clientHeight: 400, appendChild() {},
    getBoundingClientRect: () => ({ width: 800, height: 400, top: 0, bottom: 400, left: 0, right: 800 }) };
  const sandbox = { THREE: { ...THREE, WebGLRenderer: Renderer }, OrbitControls, document,
    window: { devicePixelRatio: 1, innerWidth: 1000, innerHeight: 700 }, ResizeObserver, IntersectionObserver,
    createDemandRenderer: draw => createDemandRenderer(draw, frames), biosemiReference: { channels: [] },
    mriMmToDisplay: xyz => xyz.map(value => value / 100), sourceRegion: () => undefined,
    UNASSIGNED_SOURCE_COLOR: '#888888', SOURCE_REGIONS: [], SOURCE_ROI_DEFINITION: 'test' };
  vm.runInNewContext(js, sandbox);
  const scene = sandbox.createScene(host, new THREE.SphereGeometry(1, 12, 12), new THREE.SphereGeometry(.8, 8, 8));
  const settle = () => {
    let count = 0;
    while (queue.size && count++ < 200) {
      const batch = [...queue.values()]; queue.clear(); batch.forEach(callback => callback(0));
    }
    assert.equal(queue.size, 0);
  };
  return { scene, canvas: canvases[0], host, document, draws, viewports, queue, resizes, intersections, settle };
}

await test('signal color and selection changes repaint a stationary scene once', () => {
  const f = sceneFixture();
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

await test('offscreen and hidden-tab resizes pause rendering, then restore both viewports after focus', () => {
  const f = sceneFixture();
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
