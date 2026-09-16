/** Display-only regressions: no browser server, worker, model load, or result write. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import * as THREE from 'three';

const sceneText = readFileSync(new URL('../lib/anatomical-head-scene.ts', import.meta.url), 'utf8');
const component = readFileSync(new URL('../components/cluster-head-viewer.tsx', import.meta.url), 'utf8');
const source = ts.createSourceFile('scene.ts', sceneText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
function extracted(name, context) {
  let declaration;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === name) declaration = node;
    ts.forEachChild(node, visit);
  }
  visit(source);
  assert.ok(declaration, `${name} must exist`);
  const js = ts.transpileModule(`const ${declaration.getText(source)}; globalThis.subject = ${name};`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const sandbox = { ...context };
  vm.runInNewContext(js, sandbox);
  return sandbox.subject;
}

await test('standard contacts use square geometry; layout contacts remain circular without altering coordinates', () => {
  const attach = extracted('attachContact', { THREE });
  for (const reference of [false, true]) {
    const parent = new THREE.Group();
    const position = new THREE.Vector3(.1, .2, .3), original = position.clone();
    const normal = new THREE.Vector3(0, 0, 1);
    attach(parent, { position, normal, direction: normal }, '#128a80', 'contact', reference);
    const contact = parent.children[0];
    assert.equal(contact.children[0].geometry.type, reference ? 'BoxGeometry' : 'CylinderGeometry');
    assert.equal(contact.userData.rim.geometry.type, reference ? 'BoxGeometry' : 'TorusGeometry');
    assert.equal(contact.userData.center.geometry.type, reference ? 'BoxGeometry' : 'CylinderGeometry');
    assert.ok(position.equals(original), 'recorded position input is never mutated');
    assert.ok(contact.position.distanceTo(original.clone().addScaledVector(normal, .012)) < 1e-12);
    parent.traverse(object => {
      if (object instanceof THREE.Mesh) { object.geometry.dispose(); object.material.dispose(); }
    });
  }
});

await test('rear overview reuses the same scene and renderer and restores the main viewport', () => {
  for (const showRearView of [false, true]) {
    const calls = [];
    const renderer = Object.fromEntries(['setScissorTest', 'setViewport', 'setClearColor', 'setScissor', 'clear', 'render']
      .map(name => [name, (...args) => calls.push([name, ...args])]));
    const scene = {}, camera = {}, rearCamera = {};
    const render = extracted('render', { renderer, scene, camera, rearCamera, showRearView,
      viewportWidth: 800, viewportHeight: 400, rearViewport: { x: 628, y: 208, width: 160, height: 180 } });
    render();
    const draws = calls.filter(call => call[0] === 'render');
    assert.equal(draws.length, showRearView ? 2 : 1);
    assert.equal(draws[0][1], scene); assert.equal(draws[0][2], camera);
    if (showRearView) {
      assert.equal(draws[1][1], scene); assert.equal(draws[1][2], rearCamera);
      assert.deepEqual(calls.at(-1), ['setViewport', 0, 0, 800, 400]);
      assert.deepEqual(calls.at(-2), ['setScissorTest', false]);
    }
  }
  assert.equal((sceneText.match(/new THREE\.WebGLRenderer\(/g) || []).length, 1);
  assert.equal((sceneText.match(/new OrbitControls\(/g) || []).length, 1);
});

await test('rear overview bounds do not ray-pick or edit hidden main-view contacts', () => {
  const canvas = { getBoundingClientRect: () => ({ left: 10, top: 20, width: 800, height: 400 }) };
  const hit = extracted('overRearView', { showRearView: true, canvas, rearViewport: { x: 628, y: 208, width: 160, height: 180 } });
  assert.equal(hit({ clientX: 700, clientY: 60 }), true);
  assert.equal(hit({ clientX: 410, clientY: 220 }), false);
  assert.match(sceneText, /if \(overRearView\(e\)\) \{ pointerStart = null; return; \}/);
  assert.match(component, /data-rear-overview className="pointer-events-none/);
});

await test('compact mode preserves full-screen, region data, shape legend, and coordinate documentation', () => {
  assert.match(component, /compact\?: boolean/);
  assert.match(component, /regionAreasCm2\[index\]\.toFixed\(2\)/);
  assert.match(component, /focusRegion\(index\)/);
  assert.match(component, /props\.compact \? <details/);
  assert.match(component, /Boolean\(props\.editor\?\.enabled\)/);
  assert.match(component, /event\.key === 'Escape'/);
  assert.match(component, /方形：标准64导/);
  assert.match(component, /圆形：当前布局/);
  assert.match(sceneText, /cancelAnimationFrame\(frame\)/);
  assert.match(sceneText, /observer\.disconnect\(\)/);
  assert.match(sceneText, /renderer\.dispose\(\)/);
});
