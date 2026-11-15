/* oxlint-disable typescript/no-implied-eval -- compile a trusted repository component for static rendering */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { coordinateReview } from '../features/decision/coordinate-review.ts';
import { exportBIDSElectrodes, parseBIDSElectrodes } from '../lib/bids-electrodes.ts';
import { designSubmission, exportDesign, scientificDesign, validateDesign } from '../lib/design-decision.ts';
import { normalizeDesignRequest } from '../server/design-evaluation-server.mjs';
import { communityAdapters } from '../server/community-adapters.mjs';
import { ElectrodeAnnotations, validateElectrodeAnnotation } from '../server/annotations/electrode-names.mjs';
import { ProjectService } from '../server/projects/service.mjs';
import { ProjectStore } from '../server/projects/store.mjs';
import { buildResearchDelivery, validateResearchDelivery } from '../server/delivery/research-bundle.mjs';
import { validateCoordinateSource } from '../contracts/coordinate-source.mjs';
import { evaluationPresentation } from '../features/decision/evaluation-presentation.ts';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const design = { schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm', name: 'Original scientific design name',
  xyz_mm: Array.from({ length: 64 }, (_, index) => [(index % 8) * 6 + 1.42e-14, Math.floor(index / 8) * 6, -112.31415926535898]),
  region_indices: Array.from({ length: 64 }, (_, index) => index % 2),
  electrode_names: Array.from({ length: 64 }, (_, index) => index === 0 ? ' Fp1, "left" ' : `电极${index + 1}`) };
const request = normalizeDesignRequest({ action: 'evaluate', design, radius_mm: 6, seed: 42 });
const fixtureFiles = () => exportBIDSElectrodes(design);

void test('reading a cached native-FEM result is labelled as a read while preserving the original scientific origin', () => {
  const original = { forward_mode: 'direct_fem' }, before = JSON.stringify(original);
  const loaded = evaluationPresentation({ cached: true }, original);
  assert.equal(loaded.heading, '已读取保存的坐标评价'); assert.equal(loaded.origin, '新位置FEM'); assert.equal(loaded.forward_mode, 'direct_fem');
  assert.equal(evaluationPresentation({ cached: false }, original).heading, '坐标评价结果');
  const bank = evaluationPresentation({ cached: true }, { forward_mode: 'cached_fem' });
  assert.equal(bank.heading, loaded.heading); assert.equal(bank.origin, '已有前向库FEM');
  assert.equal(evaluationPresentation({ cached: true }, { forward_mode: 'unknown' }).origin, '未记录');
  assert.equal(JSON.stringify(original), before);
});

void test('unevaluated coordinates have no projected positions, zero displacement or qualified status', () => {
  const before = JSON.stringify(design), review = coordinateReview(design);
  assert.equal(review.evaluated, false); assert.equal(review.coordinate_system, 'ernie_native_mm'); assert.equal(review.unit, 'mm');
  assert.equal(review.rows.length, 64);
  for (const [index, row] of review.rows.entries()) {
    assert.equal(row.status, 'not_evaluated'); assert.equal(row.evaluated_xyz_mm, null); assert.equal(row.movement_mm, null);
    assert.strictEqual(row.input_xyz_mm, design.xyz_mm[index]); assert.equal(row.name, design.electrode_names[index]); assert.equal(row.region, design.region_indices[index]);
  }
  assert.equal(JSON.stringify(design), before);
});

void test('per-electrode projection review preserves original/result arrays and full exported coordinate precision', () => {
  const evaluated_xyz_mm = design.xyz_mm.map((point, index) => [point[0], point[1], point[2] + (index === 63 ? 2.1 : 0.5)]), result = { evaluated_xyz_mm };
  const original = JSON.stringify({ design, result }), review = coordinateReview(design, result);
  assert.equal(review.evaluated, true); assert.equal(review.rows[0].movement_mm, 0.5); assert.equal(review.rows[0].status, 'within_projection_limit');
  assert.equal(review.rows[63].status, 'outside_projection_limit');
  assert.strictEqual(review.rows[0].evaluated_xyz_mm, result.evaluated_xyz_mm[0]);
  const exported = JSON.parse(JSON.stringify(review));
  assert.deepEqual(exported.rows.map(row => row.input_xyz_mm), design.xyz_mm);
  assert.deepEqual(exported.rows.map(row => row.evaluated_xyz_mm), evaluated_xyz_mm);
  assert.equal(exported.rows[0].input_xyz_mm[0], 1.42e-14); assert.equal(exported.rows[0].input_xyz_mm[2], -112.31415926535898);
  assert.equal(JSON.stringify({ design, result }), original);
  for (const invalid of [[], evaluated_xyz_mm.slice(1), evaluated_xyz_mm.map((point, index) => index ? point : [NaN, 0, 0])]) {
    const unreviewed = coordinateReview(design, { evaluated_xyz_mm: invalid });
    assert.equal(unreviewed.evaluated, false); assert.ok(unreviewed.rows.every(row => row.status === 'not_evaluated'));
  }
});

void test('coordinate review renders unassessed rows without qualification and escapes imported labels', async t => {
  let source = await readFile(new URL('../features/decision/coordinate-review-panel.tsx', import.meta.url), 'utf8');
  const tree = ts.createSourceFile('coordinate-review-panel.tsx', source, ts.ScriptTarget.Latest, true);
  for (const statement of [...tree.statements].reverse()) if (ts.isImportDeclaration(statement)) source = source.slice(0, statement.pos) + source.slice(statement.end);
  const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React } }).outputText, exports = {};
  new Function('exports', 'React', 'useLanguage', 'Button', 'coordinateReview', code)(exports, React, () => ({ tx: text => text }), props => React.createElement('button', props), coordinateReview);
  t.mock.method(globalThis, 'fetch', () => { throw new Error('Rendering a review must not contact the server.'); });
  const named = { ...design, electrode_names: design.electrode_names.map((name, index) => index ? name : '<script>alert(1)</script>') };
  const html = renderToStaticMarkup(React.createElement(exports.CoordinateReviewPanel, { design: named, result: null }));
  assert.equal([...html.matchAll(/>未评价<\/td>/g)].length, 64); assert.equal([...html.matchAll(/>合格<\/td>/g)].length, 0);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/); assert.doesNotMatch(html, /<script>/);
  assert.match(html, /1\.42e-14/); assert.match(html, /-112\.31415926535898/);
  const done = renderToStaticMarkup(React.createElement(exports.CoordinateReviewPanel, { design: named, result: { evaluated_xyz_mm: design.xyz_mm.map(point => [point[0], point[1], point[2] + 0.5]) } }));
  assert.equal([...done.matchAll(/>合格<\/td>/g)].length, 64); assert.match(done, /0\.500000/);
});

void test('the BIDS coordinate subset round-trips names, rows, regions, precise numbers and explicit source declarations', () => {
  const files = fixtureFiles(), original = JSON.stringify(files), parsed = parseBIDSElectrodes(files);
  assert.deepEqual(scientificDesign(parsed), scientificDesign(design));
  assert.deepEqual(parsed.electrode_names, design.electrode_names);
  assert.equal(parsed.source_metadata.format, 'bids-electrodes/1'); assert.equal(parsed.source_metadata.coordinate_system, 'ernie_native_mm'); assert.equal(parsed.source_metadata.unit, 'mm');
  assert.equal(parsed.source_metadata.region_index_base, 0); assert.equal(parsed.source_metadata.electrodes_file, 'electrodes.tsv');
  assert.deepEqual(parseBIDSElectrodes(exportBIDSElectrodes(parsed)), parsed);
  assert.deepEqual(parseBIDSElectrodes(files.slice(0, 2)), parsed, 'The explicit region description can accompany the frame declaration.');
  const multiline = { ...parsed, source_metadata: { ...parsed.source_metadata, coordinate_system_description: 'Ernie native frame.\nOriginal description retained.' } };
  assert.deepEqual(parseBIDSElectrodes(exportBIDSElectrodes(multiline)), multiline);
  assert.equal(JSON.stringify(files), original);
});

void test('BIDS adapters reject undeclared/head/MNI frames, other units, unknown regions, missing coordinates and unmatched pairs', () => {
  const mutateSystem = change => { const files = fixtureFiles(), system = JSON.parse(files[1].text); change(system); files[1].text = JSON.stringify(system); return files; };
  for (const files of [
    fixtureFiles().slice(0, 1),
    mutateSystem(system => { system.EEGCoordinateSystem = 'MNI152NLin6Asym'; }),
    mutateSystem(system => { system.EEGCoordinateSystem = 'head'; }),
    mutateSystem(system => { delete system.EEGLayoutLabCoordinateSystem; }),
    ...['m', 'cm', 'n/a', undefined].map(unit => mutateSystem(system => { system.EEGCoordinateUnits = unit; })),
    mutateSystem(system => { system.EEGLayoutLabRegionIndexBase = 1; }),
  ]) assert.throws(() => parseBIDSElectrodes(files));
  const replaceTSV = change => { const files = fixtureFiles(); files[0].text = change(files[0].text); return files; };
  for (const files of [
    replaceTSV(text => text.split('\n').map(row => row.split('\t').slice(0, 4).join('\t')).join('\n')),
    replaceTSV(text => text.replace('1.42e-14', 'n/a')),
    replaceTSV(text => text.split('\n').slice(0, 64).join('\n')),
    replaceTSV(text => text.replace('电极2', design.electrode_names[0])),
    replaceTSV(text => text.replace(/\t1\n/g, '\t4\n')),
    (() => { const files = fixtureFiles(); files[1].name = 'other_coordsystem.json'; return files; })(),
    (() => { const files = fixtureFiles(); files[0].name = '../electrodes.tsv'; files[1].name = '../coordsystem.json'; files[2].name = '../electrodes.json'; return files; })(),
  ]) assert.throws(() => parseBIDSElectrodes(files));
});

void test('source metadata remains bounded and cannot change scientific normalization, context identity or legacy annotation IDs', async t => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'eeg-coordinate-source-'))); t.after(() => rm(root, { recursive: true, force: true }));
  const parsed = parseBIDSElectrodes(fixtureFiles()), identity = { fixed_model: 'test' };
  const adapter = communityAdapters({ designTests: { normalize: normalizeDesignRequest, context: async request => ({ identity, key: hash({ request, identity }) }) } })['design-evaluation'];
  const bare = await adapter.prepare(request), named = await adapter.prepare(designSubmission(design, 'evaluate', 6, 42)), sourced = await adapter.prepare(designSubmission(parsed, 'evaluate', 6, 42));
  assert.deepEqual(bare.request, named.request); assert.deepEqual(bare.request, sourced.request); assert.equal(bare.key, sourced.key);
  assert.equal(JSON.stringify(sourced.request).includes('source_metadata'), false);
  const annotations = new ElectrodeAnnotations(root), owner = 'a'.repeat(64), old = annotations.create(named, owner), current = annotations.create(sourced, owner);
  assert.equal(old.source_metadata, undefined); assert.deepEqual(current.source_metadata, parsed.source_metadata); assert.notEqual(old.id, current.id);
  assert.equal(annotations.create(named, owner).id, old.id);
  assert.equal(validateElectrodeAnnotation(old, bare.key), old); assert.equal(validateElectrodeAnnotation(current, bare.key), current);
  assert.deepEqual(new ElectrodeAnnotations(root).read(current.id, owner, bare.key).source_metadata, parsed.source_metadata);
  assert.throws(() => validateDesign({ ...parsed, source_metadata: { ...parsed.source_metadata, coordinate_system: 'head' } }));
  assert.throws(() => validateCoordinateSource({ ...parsed.source_metadata, electrodes_file: '/private/input.tsv' }));
  assert.throws(() => validateCoordinateSource({ ...parsed.source_metadata, coordinate_system_description: 'x'.repeat(2049) }));
});

void test('source declarations survive trusted project snapshots and deliveries without entering or changing scientific payload', async t => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'eeg-coordinate-project-'))); t.after(() => rm(root, { recursive: true, force: true }));
  const parsed = parseBIDSElectrodes(fixtureFiles()), identity = { fixed: true }, key = hash({ request, identity }), owner = 'a'.repeat(64);
  const annotations = new ElectrodeAnnotations(root), annotation = annotations.create({ request, key, electrode_names: parsed.electrode_names, source_metadata: parsed.source_metadata }, owner);
  const record = { id: key, dataset_id: 'design_evaluation', label: design.name, status: 'completed', region_count: 2,
    layout: { xyzMm: design.xyz_mm, regionIndices: design.region_indices }, provenance: {} };
  const scientific = { schema: 'eeg-reproducibility-bundle/1', record, original_record: { request, values: [1 / 3, -1e-18, 1.0000000000000002] } }, before = JSON.stringify(scientific);
  const originalFile = join(root, 'original-scientific.json'); await writeFile(originalFile, before);
  const service = new ProjectService({ queue: { root, runtime: { queueDirectory: root }, library: { get: async () => record } }, scheduler: { annotations }, bundle: async () => scientific });
  const input = { revision: 1, kind: 'layout', record_id: key, annotation_id: annotation.id }, resolved = await service.resolveSnapshot(input, { id: owner });
  assert.strictEqual(resolved.snapshot.payload, scientific); assert.deepEqual(resolved.snapshot.electrode_annotation.source_metadata, parsed.source_metadata);
  const created = await service.store.create({ title: 'Source declarations', owner_name: 'Researcher' });
  await service.store.attach(created.project.id, created.access_key, input, resolved.snapshot, resolved.summary);
  const restored = new ProjectStore(service.store.directory), copies = await restored.readSnapshots(created.project.id, created.access_key), delivery = buildResearchDelivery(copies);
  assert.equal(validateResearchDelivery(delivery), true);
  const snapshot = JSON.parse(delivery.files[1].content);
  assert.deepEqual(snapshot.electrode_annotation.source_metadata, parsed.source_metadata); assert.equal(JSON.stringify(snapshot.payload), before);
  assert.deepEqual(exportDesign({ ...record, electrode_annotation: snapshot.electrode_annotation }).source_metadata, parsed.source_metadata);
  assert.equal(await readFile(originalFile, 'utf8'), before);
  service.close(); await service.flush();
});

void test('signal project summaries copy only verified original request fields, leave omissions absent and clone arrays', async t => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'eeg-source-summary-'))); t.after(() => rm(root, { recursive: true, force: true }));
  const receipt_id = randomUUID(), record_id = 'a'.repeat(64), key = 'b'.repeat(64);
  const requests = [
    { record_id, mode: 'single_source', source_index: 0, seed: 0 },
    { record_id, mode: 'multi_source', brain_region: 'frontal', seed: 2026 },
    { record_id, mode: 'cross_region', brain_regions: ['frontal', 'parietal'], seed: 14 },
    { record_id },
  ];
  for (const request of requests) {
    const payload = { schema_version: 'source-reception/2', request, layout: { xyzMm: design.xyz_mm }, source: { generation_source_indices: [7, 8], source_regions: ['occipital', null] } }, before = JSON.stringify(payload);
    const service = new ProjectService({ queue: { root, runtime: { queueDirectory: root } }, scheduler: { own: () => ({ key, request, status: 'completed' }), adapters: { 'source-reception': { savedResult: async () => payload } } } });
    const resolved = await service.resolveSnapshot({ kind: 'source', receipt_id }, { id: 'owner' });
    assert.strictEqual(resolved.snapshot.payload, payload); assert.equal(resolved.summary.parent_id, record_id);
    for (const field of ['brain_region', 'brain_regions', 'source_index', 'seed']) {
      assert.equal(Object.hasOwn(resolved.summary, field), Object.hasOwn(request, field));
      if (Object.hasOwn(request, field)) assert.deepEqual(resolved.summary[field], request[field]);
    }
    assert.equal(Object.hasOwn(resolved.summary, 'source_indices'), false); assert.equal(Object.hasOwn(resolved.summary, 'source_regions'), false);
    if (request.brain_regions) { assert.notStrictEqual(resolved.summary.brain_regions, request.brain_regions); resolved.summary.brain_regions.push('changed UI metadata'); }
    assert.equal(JSON.stringify(payload), before); service.close(); await service.flush();
  }
});
