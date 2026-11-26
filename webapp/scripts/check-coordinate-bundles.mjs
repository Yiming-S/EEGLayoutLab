import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, writeFile, rm, symlink, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { experimentBundle } from '../server/experiment-bundle.mjs';
import { assertIndependentNoiseParent, designReceptionRecord } from '../server/reception-v2-support.mjs';
import { normalizeDesignRequest } from '../server/design-evaluation-server.mjs';
import { computeMiddleware } from '../server/local-compute-server.mjs';
import { translateText } from '../lib/i18n/core.ts';
import catalog from '../lib/i18n/exports-catalog.json' with { type: 'json' };

const digest = bytes => createHash('sha256').update(bytes).digest('hex');

async function fixture(t, extra = {}) {
  // Serialization data only; no physical head model or numerical worker runs.
  const root = await realpath(await mkdtemp(join(tmpdir(), 'eeg-coordinate-bundle-')));
  t.after(() => rm(root, { recursive: true, force: true }));
  const xyz = Array.from({ length: 64 }, (_, i) => [(i % 8) * 6, Math.floor(i / 8) * 6, 0]);
  const request = normalizeDesignRequest({ action: 'evaluate', radius_mm: 6, seed: 42, design: {
    schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm', name: 'Coordinate serialization fixture',
    xyz_mm: xyz, region_indices: xyz.map((_, i) => Number(i >= 32)),
  }, ...extra });
  const identity = { schema: 'design-evaluation-cache/1', digests: { fixture: digest('serialization fixture') }, threads: 1 };
  const id = digest(JSON.stringify({ request, identity }));
  const result = {
    schema: 'design-evaluation/1', status: 'completed', request, forward_mode: request.head_id ? 'head_scalp_node_table' : 'direct_fem',
    nominal: { field_relative: .9 / .99, field_absolute: .9, reference_field_absolute: .99,
      sensitivity_tail: .4, localization_relative: .5, median_mm: 10, p90_mm: 20,
      reference_median_mm: 9, reference_p90_mm: 18 },
    projection_max_mm: 1, evaluated_xyz_mm: xyz.map(([x, y]) => [x, y, 1]),
    provenance: { candidate_count: 64 }, trials: [],
  };
  const relative = `results/v2/design_evaluation_jobs/${id}/cache.json`;
  const file = join(root, relative);
  const cache = { key: id, identity, result, result_sha256: digest(JSON.stringify(result)), finished_at: '2026-10-14T00:00:00Z' };
  await mkdir(join(root, 'results/v2/design_evaluation_jobs', id), { recursive: true });
  const report = JSON.stringify({ baseline: { reference_xyz_mm: xyz } });
  await writeFile(join(root, 'results/v2/reference.json'), report);
  await writeFile(join(root, 'results/v2/current_strict_area_budget_study.json'), JSON.stringify({ report: 'results/v2/reference.json', sha256: digest(report) }));
  await writeFile(file, JSON.stringify(cache));
  const record = await designReceptionRecord(root, id, undefined, { conditions: true });
  // Refresh only the outer file identity to exercise inner integrity checks.
  const persist = async value => {
    const bytes = JSON.stringify(value);
    await writeFile(file, bytes);
    record.provenance.design_result.sha256 = digest(bytes);
  };
  return { root, id, record, cache, file, relative, persist };
}

void test('coordinate bundle preserves input and evaluated coordinates separately without inventing search history', async t => {
  const { root, id, record, cache, file, relative } = await fixture(t);
  const before = await readFile(file), recordBefore = structuredClone(record);
  const bundle = await experimentBundle(root, record);
  assert.equal(bundle.schema, 'eeg-reproducibility-bundle/1');
  assert.equal(bundle.record_id, id);
  assert.deepEqual(bundle.source, { path: relative, sha256: digest(before) });
  assert.deepEqual(bundle.original_record, cache);
  assert.deepEqual(bundle.record.layout.xyzMm, cache.result.evaluated_xyz_mm);
  assert.notDeepEqual(bundle.record.layout.xyzMm, cache.result.request.design.xyz_mm);
  assert.deepEqual(bundle.record.metrics, { ...cache.result.nominal, conditional_global: .4 });
  assert.deepEqual(bundle.reproduction.request, cache.result.request);
  assert.deepEqual(bundle.reproduction.identity, cache.identity);
  assert.equal(bundle.reproduction.entrypoint, 'scripts/design_evaluation.py');
  assert.equal(bundle.reproduction.metrics_recomputed, false);
  assert.equal(bundle.search.history_status, 'not_applicable_coordinate_evaluation');
  assert.equal(bundle.search.objective, null);
  assert.equal(bundle.search.initial, null);
  assert.equal(bundle.search.final, null);
  assert.deepEqual(bundle.search.trace, []);
  assert.deepEqual(bundle.search.curve, []);
  assert.deepEqual(bundle.snapshots, [null, null]);
  assert.match(bundle.coordinate_note, /输入坐标.*实际评价坐标/);
  assert.deepEqual(record, recordBefore);
  assert.deepEqual(await readFile(file), before);
});

void test('read-only coordinate bundle endpoint returns a matching export without starting a worker', async t => {
  const { root, id, record } = await fixture(t);
  const middleware = computeMiddleware({ root, library: { get: async key => key === id ? record : null } });
  let status, body;
  await middleware({ method: 'GET', url: `/api/local-compute/library/${id}/bundle`,
    socket: { remoteAddress: '127.0.0.1' }, headers: { host: 'localhost:3000' } }, {
    writeHead(value) { status = value; }, end(value) { body = JSON.parse(value); },
  }, () => assert.fail('bundle endpoint must handle the request'));
  assert.equal(status, 200);
  assert.equal(body.record_id, id);
  assert.deepEqual(body.record, record);
  assert.equal(body.original_record.key, id);
  assert.equal(body.search.history_status, 'not_applicable_coordinate_evaluation');
});

void test('coordinate exports reject missing or redirected source paths and changed source bytes', async t => {
  const { root, record, file } = await fixture(t);
  const original = structuredClone(record);
  for (const path of ['results/v2/reference.json', '../cache.json', undefined]) {
    record.provenance.design_result.path = path;
    await assert.rejects(experimentBundle(root, record), /来源路径或身份无效/);
  }
  Object.assign(record, structuredClone(original));
  record.provenance.design_result.sha256 = undefined;
  await assert.rejects(experimentBundle(root, record), /来源路径或身份无效/);
  Object.assign(record, structuredClone(original));
  await writeFile(file, JSON.stringify({ changed: true }));
  await assert.rejects(experimentBundle(root, record), /原始文件校验失败/);
});

void test('coordinate source symlinks cannot escape the experiment directory', async t => {
  const { root, record, file } = await fixture(t);
  const bytes = await readFile(file), outside = join(root, 'outside-cache.json');
  await writeFile(outside, bytes);
  await rm(file);
  await symlink(outside, file);
  await assert.rejects(experimentBundle(root, record), /来源文件不在实验目录内/);
});

void test('coordinate exports verify the cache key, result checksum and request identity after validating file bytes', async t => {
  const { root, record, cache, persist } = await fixture(t);
  for (const change of [
    value => { value.key = 'f'.repeat(64); },
    value => { value.result.nominal.field_relative = 123; },
    value => { value.identity = null; },
    value => { value.identity.threads = 2; },
    value => { value.result.request.seed = 43; value.result_sha256 = digest(JSON.stringify(value.result)); },
  ]) {
    const invalid = structuredClone(cache); change(invalid); await persist(invalid);
    await assert.rejects(experimentBundle(root, record), /缓存校验失败|记录身份不匹配/);
  }
});

void test('coordinate exports reject source results that no longer match displayed coordinates or metrics', async t => {
  const { root, record, cache, persist } = await fixture(t);
  for (const change of [
    value => { value.result.evaluated_xyz_mm = value.result.evaluated_xyz_mm.map(([x, y]) => [x, y, .5]); value.result.projection_max_mm = .5; },
    value => { value.result.nominal.field_absolute = .495; value.result.nominal.field_relative = .5; },
  ]) {
    const invalid = structuredClone(cache); change(invalid);
    invalid.result_sha256 = digest(JSON.stringify(invalid.result)); await persist(invalid);
    await assert.rejects(experimentBundle(root, record), /来源与所选记录不匹配/);
  }
  await persist(cache);
  for (const change of [
    value => { value.label = 'another record'; },
    value => { value.layout.regionIndices[0] = 1; },
    value => { value.metrics.conditional_global = .99; },
  ]) {
    const invalid = structuredClone(record); change(invalid);
    await assert.rejects(experimentBundle(root, invalid), /来源与所选记录不匹配/);
  }
});

void test('coordinate history labels have complete English and Chinese translations', () => {
  for (const key of Object.keys(catalog).filter(key => key.startsWith('exports_coordinate_'))) {
    const entry = catalog[key];
    assert.equal(translateText(entry.source, 'en'), entry.en);
    assert.equal(translateText(entry.source, 'zh-CN'), entry.source);
    assert.doesNotMatch(entry.en, /[\u3400-\u9fff]/);
  }
});

void test('evaluations under other conditions are library records with their conditions, never signal-simulation parents', async t => {
  for (const [extra, condition] of [
    [{ noise_model: { kind: 'spatial', rho: 0.5, length_mm: 20 } }, { noise_model: { kind: 'spatial', rho: 0.5, length_mm: 20 } }],
    [{ conductivity_scenario: 'skull_x2' }, { conductivity_scenario: 'skull_x2' }],
    [{ head_id: 'ixi002' }, { head_id: 'ixi002' }],
  ]) {
    const { root, id, record } = await fixture(t, extra);
    assert.deepEqual(record.evaluation_condition, condition);
    assert.equal(await designReceptionRecord(root, id), null);
    assert.throws(() => assertIndependentNoiseParent(record), /独立噪声/);
  }
  const { root, id, record } = await fixture(t);
  assert.equal(record.evaluation_condition, undefined);
  assert.deepEqual(await designReceptionRecord(root, id), record);
  assert.doesNotThrow(() => assertIndependentNoiseParent(record));
});
