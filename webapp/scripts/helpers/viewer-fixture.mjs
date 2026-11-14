import assert from 'node:assert/strict';
import * as THREE from 'three';
import { createHeadScene } from '../../viewer/head-scene.ts';

/** Real scene/layers/OrbitControls; only browser surfaces and GPU calls are replaced. */
export function sceneFixture(t, { initialize = true, failObserve = false } = {}) {
  const queue = new Map(), draws = [], viewports = [], resizes = [], intersections = [];
  let nextFrame = 0;
  class Events extends EventTarget {
    listeners = new Map();
    addEventListener(name, handler, options) {
      super.addEventListener(name, handler, options);
      const handlers = this.listeners.get(name) ?? new Set(); handlers.add(handler); this.listeners.set(name, handlers);
    }
    removeEventListener(name, handler, options) { super.removeEventListener(name, handler, options); this.listeners.get(name)?.delete(handler); }
    get listenerCount() { return [...this.listeners.values()].reduce((total, handlers) => total + handlers.size, 0); }
  }
  const document = new Events(); document.hidden = false;
  class Canvas extends Events {
    style = {}; dataset = {}; ownerDocument = document;
    setAttribute() {} getRootNode() { return document; } remove() { this.removed = true; }
    getBoundingClientRect() { return { left: 0, top: 0, width: host.clientWidth, height: host.clientHeight }; }
    getContext() { return { fillRect() {}, strokeRect() {}, fillText() {} }; }
    setPointerCapture() {} hasPointerCapture() { return false; }
  }
  document.createElement = () => new Canvas();
  class Renderer {
    domElement = new Canvas(); disposed = 0; contextLosses = 0;
    setPixelRatio() {} setSize() {} setScissorTest() {} setClearColor() {} clear() {} setScissor() {}
    setViewport(...args) { viewports.push(args); }
    render(scene, camera) { draws.push({ scene, camera, position: camera.position.clone() }); }
    dispose() { this.disposed++; } forceContextLoss() { this.contextLosses++; }
  }
  class ResizeObserver {
    constructor(callback) { this.callback = callback; resizes.push(this); }
    observe() { if (failObserve) throw new Error('Observer initialization failed'); }
    disconnect() { this.disconnected = true; }
  }
  class IntersectionObserver {
    constructor(callback) { this.callback = callback; intersections.push(this); }
    observe() {} disconnect() { this.disconnected = true; }
  }
  const host = { clientWidth: 800, clientHeight: 400, appendChild() {},
    getBoundingClientRect: () => ({ width: 800, height: 400, top: 0, bottom: 400, left: 0, right: 800 }) };
  const globals = { document, window: { devicePixelRatio: 1, innerWidth: 1000, innerHeight: 700 }, ResizeObserver, IntersectionObserver,
    requestAnimationFrame: callback => { const id = nextFrame++; queue.set(id, callback); return id; },
    cancelAnimationFrame: id => queue.delete(id) };
  const original = new Map(Object.keys(globals).map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  for (const [key, value] of Object.entries(globals)) Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
  const renderer = new Renderer(), scalp = new THREE.SphereGeometry(1, 12, 12), cortex = new THREE.SphereGeometry(.8, 8, 8);
  let scene;
  t.after(() => {
    if (scene) scene.dispose(); else { scalp.dispose(); cortex.dispose(); }
    for (const [key, descriptor] of original) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
    }
  });
  const create = () => scene = createHeadScene(host, scalp, cortex, () => renderer);
  const settle = () => {
    let count = 0;
    while (queue.size && count++ < 200) {
      const batch = [...queue.values()]; queue.clear(); batch.forEach(callback => callback(0));
    }
    assert.equal(queue.size, 0);
  };
  if (initialize) create();
  return { get scene() { return scene; }, create, canvas: renderer.domElement, renderer, scalp, cortex, host, document,
    draws, viewports, queue, resizes, intersections, settle };
}
