import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import * as THREE from 'three';
import { createHash } from 'node:crypto';
import { SOURCE_REGIONS, SOURCE_ROI_DEFINITION } from '../lib/source-regions.ts';
import { translateText } from '../lib/i18n/core.ts';
import copy from '../lib/i18n/source-regions-catalog.json' with { type: 'json' };

const sceneText = readFileSync(new URL('../lib/anatomical-head-scene.ts', import.meta.url), 'utf8');
const ast = ts.createSourceFile('scene.ts', sceneText, ts.ScriptTarget.Latest, true);
function extract(name) {
  const node = ast.statements.find(n => ts.isFunctionDeclaration(n) && n.name?.text === name);
  assert.ok(node);
  const js = ts.transpileModule(node.getText(ast).replace(/^export /, '') + `\nglobalThis.subject = ${name};`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const sandbox = { THREE, SOURCE_REGIONS };
  vm.runInNewContext(js, sandbox);
  return sandbox.subject;
}

await test('six ROI IDs and labels match the shared DK definition; no nearest-anchor classifier remains', () => {
  const definition = JSON.parse(readFileSync(new URL('../public/models/ernie/source-roi-definition.json', import.meta.url)));
  assert.equal(definition.id, SOURCE_ROI_DEFINITION);
  assert.deepEqual(SOURCE_REGIONS.map(r => [r.id, r.label]), definition.groups.map(r => [r.id, r.label]));
  assert.doesNotMatch(sceneText, /nearestSourceRegion|applySourcePartitionColors/);
  assert.equal(new Set(SOURCE_REGIONS.map(r => r.color)).size, 6);
});

await test('native cortex and actual source parents share exact atlas material groups without mutating geometry', () => {
  const base = new URL('../public/models/ernie/', import.meta.url);
  const atlas = JSON.parse(readFileSync(new URL('source-roi.json', base)));
  const mesh = atlas.mesh;
  const bytes = readFileSync(new URL(mesh.file, base));
  assert.equal(createHash('sha256').update(bytes).digest('hex'), mesh.sha256);
  assert.equal(createHash('sha256').update(readFileSync(new URL('source-roi-definition.json', base))).digest('hex'), atlas.definition_sha256);
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  const positions = new Float32Array(buffer, mesh.attributes.position.byteOffset, mesh.attributes.position.count).slice();
  for (let i = 0; i < positions.length; i++) positions[i] *= 10;
  const normals = new Int8Array(buffer, mesh.attributes.normal.byteOffset, mesh.attributes.normal.count).slice();
  const indices = new (mesh.index.type === 'Uint16Array' ? Uint16Array : Uint32Array)(buffer, mesh.index.byteOffset, mesh.index.count).slice();
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.BufferAttribute(normals, 3, true));
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  const before = [positions.slice(), normals.slice(), indices.slice()];
  extract('applySourceRoiGroups')(geometry, mesh.groups);
  assert.deepEqual(geometry.groups, mesh.groups);
  assert.equal(geometry.getAttribute('color'), undefined, 'no interpolated vertex coloring');
  for (const source of atlas.generation_sources) {
    const start = source.display_triangle * 3;
    const group = mesh.groups.find(g => start >= g.start && start < g.start + g.count);
    assert.equal(group.materialIndex, source.material_index);
    const offset = source.hemisphere === 'lh' ? 0 : atlas.validation[0].vertices;
    assert.deepEqual(Array.from(indices.slice(start, start + 3)), source.parent_vertex_indices.map(i => i + offset));
  }
  assert.throws(() => extract('applySourceRoiGroups')(geometry, mesh.groups.slice(1)));
  assert.throws(() => extract('applySourceRoiGroups')(geometry, mesh.groups.map((g,i) => ({...g, count:g.count + (i === 0 ? 3 : 0)}))));
  [positions,normals,indices].forEach((array,i) => assert.deepEqual(array, before[i]));
  geometry.dispose();
});

await test('source label sprites and textures are disposed; source selection scales only the marker', () => {
  const group = new THREE.Group(), texture = new THREE.Texture();
  const material = new THREE.SpriteMaterial({ map: texture });
  let textures = 0, materials = 0;
  texture.addEventListener('dispose', () => textures++);
  material.addEventListener('dispose', () => materials++);
  group.add(new THREE.Sprite(material));
  extract('releaseGroup')(group);
  assert.equal(textures, 1); assert.equal(materials, 1); assert.equal(group.children.length, 0);
  assert.match(sceneText, /object\.userData\.marker\.scale\.setScalar/);
  assert.match(sceneText, /group\.position\.set\(\.\.\.mriMmToDisplay\(xyz\)\)/);
  assert.match(sceneText, /sourceIndex: i, marker/);
});

await test('new terminology is bilingual and source colors stay independent of electrode region controls', () => {
  for (const entry of Object.values(copy)) {
    assert.ok(entry.en.trim());
    assert.doesNotMatch(translateText(entry.source, 'en'), /[\u3400-\u9fff]/);
  }
  const viewer = readFileSync(new URL('../components/cluster-head-viewer.tsx', import.meta.url), 'utf8');
  assert.match(viewer, /setSourcePartitions\(showSourcePartitions\)/);
  assert.match(viewer, /setRegions\(showRegions\)/);
  assert.match(viewer, /sourceRegions\?\.includes\(item.id\)/);
});
