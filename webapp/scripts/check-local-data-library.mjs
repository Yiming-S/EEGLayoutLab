import test from 'node:test';
import { dataTest } from './test-tiers.mjs';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { LocalComputeQueue, computeMiddleware } from './local-compute-server.mjs';
import { InputIntegrity } from './local-input-integrity.mjs';
import { validateSavedRecord, areaRecords } from './local-data-library.mjs';
import { designLink } from '../lib/local-library.ts';

const root = resolve('..');
const digest = (value) => createHash('sha256').update(value).digest('hex');
const request = { region_count: 1, radius_mm: 15, mode: 'whole_surface' };
const noLayout = { status: 'no_layout', request, layout: null, metrics: null };
async function cachedFixture() {
  const repositoryRoot = await mkdtemp(join(tmpdir(), 'eeg-library-test-'));
  const queue = new LocalComputeQueue({ repositoryRoot, getIdentity: () => ({}),
    spawnProcess: () => assert.fail('reading must never spawn Python') });
  const { key } = queue.identityFor(request);
  const dir = join(repositoryRoot, 'results/v2/local_app_jobs', key);
  await mkdir(dir, { recursive: true });
  const file = join(dir, 'cache.json');
  await writeFile(file, JSON.stringify({ key, request, result: noLayout, result_sha256: digest(JSON.stringify(noLayout)), finished_at: '2026-09-08T12:00:00Z' }));
  return { queue, file, key };
}

void dataTest('all offline layouts load read-only with protocol separation and original metric values', async () => {
  const queue = new LocalComputeQueue({ repositoryRoot: root, spawnProcess: () => assert.fail('no computation in library') });
  const library = await queue.library.list();
  assert.equal(library.warnings.length, 0);
  assert.equal(library.datasets.find((d) => d.id === 'offline_radius').count, 342);
  assert.equal(library.datasets.find((d) => d.id === 'strict_area').count, 30);
  const radius = JSON.parse(await readFile(join(root, 'webapp/public/data/single_head_optimization.json'), 'utf8'));
  const pointer = JSON.parse(await readFile(join(root, 'results/v2/current_strict_area_budget_study.json'), 'utf8'));
  const bytes = await readFile(join(root, pointer.report)); assert.equal(digest(bytes), pointer.sha256);
  const area = JSON.parse(bytes);
  const historicalPointer = JSON.parse(await readFile(join(root, 'results/v2/historical_strict_area_budget_study.json'), 'utf8'));
  const historicalArea = JSON.parse(await readFile(join(root, historicalPointer.report), 'utf8'));
  for (const row of library.records.filter((r) => ['offline_radius', 'strict_area', 'historical_area'].includes(r.dataset_id))) {
    const record = await queue.library.get(row.id);
    validateSavedRecord(record); assert.equal(record.compatible, false); assert.equal(record.request, null);
    assert.equal(designLink(record), null);
    if (row.dataset_id === 'offline_radius') {
      const c = radius.conditions.find((v) => v.id === record.provenance.condition_id);
      const v = c.variants.find((v) => v.id === record.layout.id);
      assert.deepEqual(record.layout.xyzMm, v.xyz_mm);
      assert.deepEqual(record.layout.regionIndices, v.region_indices);
      assert.equal(record.metrics.conditional_global, v.conditions.find((m) => m.snr_db === 20).conditional_global);
    } else {
      const original = row.dataset_id === 'historical_area' ? historicalArea : area;
      const c = original.conditions.find((v) => v.condition.id === record.provenance.condition_id);
      const f = c.finalists.find((v) => v.objective === 'min_field_sensitivity20');
      assert.deepEqual(record.layout.xyzMm, f.final.xyz_mm);
      assert.deepEqual(record.layout.regionIndices, f.final.region_indices);
      assert.equal(record.metrics.field_relative, f.evaluation.field20);
      assert.equal(record.metrics.reference_median_mm, original.baseline.localization.median_error_mm);
      assert.equal(record.provenance.reevaluation_512_sources, false);
    }
  }
  assert.equal(queue.jobs.size, 0); queue.dispose();
});

void dataTest('coordinate evaluations appear in the read-only library and reopen their original evaluated coordinates', async () => {
  const queue = new LocalComputeQueue({ repositoryRoot: root, spawnProcess: () => assert.fail('record listing cannot compute') });
  const library = await queue.library.list();
  const summaries = library.records.filter(record => record.dataset_id === 'design_evaluation');
  assert.equal(library.datasets.find(dataset => dataset.id === 'design_evaluation').count, summaries.length);
  for (const summary of summaries) {
    const record = await queue.library.get(summary.id);
    const cache = JSON.parse(await readFile(join(root, 'results/v2/design_evaluation_jobs', summary.id, 'cache.json'), 'utf8'));
    assert.equal(cache.result.request.action, 'evaluate');
    assert.equal(record.label, cache.result.request.design.name);
    assert.deepEqual(record.layout.xyzMm, cache.result.evaluated_xyz_mm);
    assert.deepEqual(record.layout.regionIndices, cache.result.request.design.region_indices);
    assert.equal(record.metrics.field_relative, cache.result.nominal.field_relative);
    assert.equal(record.layout.xyzMm.length, 64);
  }
  assert.equal(queue.jobs.size, 0); queue.dispose();
});

void test('existing cache has history after restart and exact lookup does not spawn', async () => {
  const { queue, key } = await cachedFixture();
  const library = await queue.library.list(), row = library.records.find((r) => r.id === key);
  assert.equal(row.compatible, true); assert.equal(row.status, 'no_layout'); assert.equal(row.metrics, null);
  assert.equal(designLink(row), `/design?saved=${key}&ar=90`);
  assert.equal((await queue.lookup(request)).hit, true);
  assert.equal((await queue.lookup({ ...request, radius_mm: 20 })).hit, false);
  assert.equal(queue.active, null); queue.dispose();
});

void test('historical algorithm data stays readable but cannot resume as current cache', async () => {
  const { queue, key } = await cachedFixture();
  queue.getIdentity = () => ({ changed: true });
  const record = await queue.library.get(key);
  assert.equal(record.compatible, false);
  assert.equal(designLink(record), `/design?saved=${key}&ar=90`); // Parameters only; not a cache hit.
  assert.equal((await queue.lookup(request)).hit, false); queue.dispose();
});

void test('cached result is served while unrelated computation runs, without changing that job', async () => {
  const { queue } = await cachedFixture();
  const active = { id: 'fixture-active', key: 'another-key', status: 'running', request: { ...request, radius_mm: 40 } };
  queue.active = active;
  const response = await queue.submit(request);
  assert.equal(response.job.cached, true); assert.equal(queue.active, active);
  queue.active = null; queue.dispose();
});

void test('invalid checksum and malformed records are misses, not usable scores', async () => {
  const { queue, file } = await cachedFixture();
  const cache = JSON.parse(await readFile(file, 'utf8')); cache.result.status = 'completed';
  await writeFile(file, JSON.stringify(cache));
  assert.equal((await queue.lookup(request)).hit, false);
  assert.equal((await queue.library.list()).records.length, 0);
  await writeFile(file, '{broken'); assert.equal((await queue.lookup(request)).hit, false);
  queue.dispose();
});

void test('lookup HTTP endpoint returns a miss without a task, and rejects extra query fields', async () => {
  const { queue } = await cachedFixture(); const middleware = computeMiddleware(queue);
  for (const [body, code, hit] of [[request, 200, true], [{ ...request, radius_mm: 20 }, 200, false], [{ ...request, AR: .9 }, 400]]) {
    let response;
    const req = { url: '/api/local-compute/lookup', method: 'POST', socket: { remoteAddress: '127.0.0.1' },
      headers: { host: 'localhost:3000', 'content-type': 'application/json', 'x-eeg-compute-token': queue.token },
      async *[Symbol.asyncIterator]() { yield Buffer.from(JSON.stringify(body)); } };
    await middleware(req, { writeHead(value) { assert.equal(value, code); }, end(bytes) { response = JSON.parse(bytes); } }, () => assert.fail());
    if (code === 200) assert.equal(response.hit, hit);
  }
  assert.equal(queue.active, null); queue.dispose();
});

void test('input byte changes invalidate memoized SHA even when model pointer stays the same', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'eeg-input-test-'));
  const file = join(dir, 'bank.npz'); await writeFile(file, 'abc');
  const inputs = new InputIntegrity(dir);
  const first = await inputs.digest('bank.npz'); assert.equal(first, digest('abc'));
  assert.equal(await inputs.digest('bank.npz'), first);
  await writeFile(file, 'xyz'); assert.notEqual(await inputs.digest('bank.npz'), first);
  await assert.rejects(() => inputs.digest('../../etc/passwd'));
});

void test('failed input identity blocks cached reuse instead of starting replacement work', async () => {
  const { queue } = await cachedFixture();
  queue.verifyInputs = async () => { throw new Error('changed input'); };
  await assert.rejects(() => queue.submit(request), /changed input/);
  assert.equal(queue.active, null); queue.dispose();
});

void test('library only returns allowlisted opaque IDs, not filesystem paths', async () => {
  const { queue } = await cachedFixture();
  assert.equal(await queue.library.get('../cache.json'), null);
  assert.equal(await queue.library.get('/etc/passwd'), null);
  assert.equal(await queue.library.get('a'.repeat(64)), null); queue.dispose();
});

void dataTest('area importer rejects changed scientific protocols instead of applying stale labels', async () => {
  const pointer = JSON.parse(await readFile(join(root, 'results/v2/current_strict_area_budget_study.json'), 'utf8'));
  const report = JSON.parse(await readFile(join(root, pointer.report), 'utf8'));
  for (const change of [
    (r) => { r.schema_version = 'new-version'; },
    (r) => { r.config.spacing_mm = 2; },
    (r) => { r.config.evaluation.snr_db = 10; },
    (r) => { r.baseline.localization.generation_source_count = 512; },
  ]) { const copy = structuredClone(report); change(copy); assert.throws(() => areaRecords(copy, {})); }
});
