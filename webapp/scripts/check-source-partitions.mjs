import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as THREE from 'three';
import { createHash } from 'node:crypto';
import { SOURCE_REGIONS, SOURCE_ROI_DEFINITION } from '../lib/source-regions.ts';
import { translateText } from '../lib/i18n/core.ts';
import copy from '../lib/i18n/catalog.json' with { type: 'json' };

import { applySourceRoiGroups } from '../viewer/assets.ts';
import { releaseGroup } from '../viewer/resources.ts';
import { createSourceLayer } from '../viewer/source-layer.ts';
import { sceneFixture } from './helpers/viewer-fixture.mjs';
const sceneText = ['head-scene.ts', 'assets.ts', 'source-layer.ts'].map(name => readFileSync(new URL('../viewer/' + name, import.meta.url), 'utf8')).join('\n');

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
  applySourceRoiGroups(geometry, mesh.groups);
  assert.deepEqual(geometry.groups, mesh.groups);
  assert.equal(geometry.getAttribute('color'), undefined, 'no interpolated vertex coloring');
  for (const source of atlas.generation_sources) {
    const start = source.display_triangle * 3;
    const group = mesh.groups.find(g => start >= g.start && start < g.start + g.count);
    assert.equal(group.materialIndex, source.material_index);
    const offset = source.hemisphere === 'lh' ? 0 : atlas.validation[0].vertices;
    assert.deepEqual(Array.from(indices.slice(start, start + 3)), source.parent_vertex_indices.map(i => i + offset));
  }
  assert.throws(() => applySourceRoiGroups(geometry, mesh.groups.slice(1)));
  assert.throws(() => applySourceRoiGroups(geometry, mesh.groups.map((g,i) => ({...g, count:g.count + (i === 0 ? 3 : 0)}))));
  [positions,normals,indices].forEach((array,i) => assert.deepEqual(array, before[i]));
  geometry.dispose();
});

await test('source label sprites and textures are disposed; source selection scales only the marker', t => {
  const group = new THREE.Group(), texture = new THREE.Texture();
  const material = new THREE.SpriteMaterial({ map: texture });
  let textures = 0, materials = 0;
  texture.addEventListener('dispose', () => textures++);
  material.addEventListener('dispose', () => materials++);
  group.add(new THREE.Sprite(material));
  releaseGroup(group);
  assert.equal(textures, 1); assert.equal(materials, 1); assert.equal(group.children.length, 0);
  sceneFixture(t);
  const scene = new THREE.Scene(), layer = createSourceLayer(scene);
  layer.setLayout({ sourceXyzMm: [[10, 20, 30]], regionCount: 1, allocation: [64], domainMode: 'whole_surface', radiusCm: 1 });
  const markerGroup = layer.group.children[0], label = markerGroup.children.find(child => child instanceof THREE.Sprite);
  const labelScale = label.scale.clone();
  layer.select(0);
  assert.deepEqual(markerGroup.position.toArray(), [.1, .2, .3]);
  assert.equal(markerGroup.userData.marker.scale.x, 1.6);
  assert.ok(label.scale.equals(labelScale));
  releaseGroup(scene);
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
