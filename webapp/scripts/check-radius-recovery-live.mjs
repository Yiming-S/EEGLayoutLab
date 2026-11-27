/** Real local API regression for the previously missed PL/PR 25 mm layout. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { validateWorkerResult } from '../server/local-compute-server.mjs';
import { scriptServer } from './helpers/service-session.mjs';

// The Python service (eeglayoutlab serve): with EEG_SERVICE_RUNTIME (its <workspace>/.eeglayoutlab/runtime.json), or
// EEG_SERVICE_TOKEN and EEG_TEST_URL, the script signs in as its launched browser and sends the session cookie
// (helpers/service-session.mjs). With EEG_TEST_URL alone, the legacy Node host there. EEG_REPOSITORY_ROOT is the
// root the server serves (default this checkout).
const { base, service } = await scriptServer();
const call = (path, options = {}) => fetch(base + path,
  { ...options, headers: { ...options.headers, ...(service ? { Cookie: service.cookie } : {}) } });
const root = resolve(process.env.EEG_REPOSITORY_ROOT || '..');
const originalKey = '6135457e71e0f4bd652216d1ff75d49f8e4257582229de844063b217f044a71d';
const originalPath = join(root, 'results/v2/local_app_jobs', originalKey, 'cache.json');
const hasHistoricalRecord = existsSync(originalPath);
const originalBytes = hasHistoricalRecord ? await readFile(originalPath) : null;
const digest = (bytes) => createHash('sha256').update(bytes).digest('hex');
const request = { region_count: 2, radius_mm: 25, mode: 'preset', mask_codes: ['PL', 'PR'] };
if (originalBytes) {
  const original = JSON.parse(originalBytes.toString('utf8'));
  assert.deepEqual(original.request, request);
  assert.equal(original.result.status, 'no_layout');
}
const pointerFiles = ['results/v2/current_multiregion_bank.json', 'results/v2/current_strict_area_budget_study.json'];
const pointerBefore = await Promise.all(pointerFiles.map(async (p) => digest(await readFile(join(root, p)))));
const health = await call('/api/local-compute/health').then((r) => r.json());
assert.equal(health.available, true);
assert.equal(health.active_job, null, 'Do not interrupt another local calculation');
const headers = { 'Content-Type': 'application/json', 'X-EEG-Compute-Token': health.token };
const started = Date.now();
const submission = await call('/api/local-compute/jobs', { method: 'POST', headers, body: JSON.stringify(request) });
assert.equal(submission.status, 202);
let { job } = await submission.json();
assert.notEqual(job.key, originalKey, 'Changed search code requires a distinct cache identity');
while (['queued', 'running', 'cancelling'].includes(job.status)) {
  if (Date.now() - started > 185000) throw new Error('Local recovery exceeded its bounded deadline');
  await new Promise((done) => setTimeout(done, 500));
  const response = await call('/api/local-compute/jobs/' + job.id);
  assert.equal(response.status, 200);
  ({ job } = await response.json());
}
assert.equal(job.status, 'completed', JSON.stringify({ status: job.status, message: job.message }));
validateWorkerResult(job.result, request);
assert.ok(job.result.provenance.algorithm_version.startsWith('strict-radius-local/'));
assert.equal(job.result.geometry.union_connected_component_count, 2);
assert.deepEqual(job.result.geometry.actual_region_counts, [32, 32]);
assert.ok(job.result.geometry.minimum_chord_distance_mm >= 4 - 1e-7);
assert.ok(job.result.geometry.maximum_electrode_graph_distances_mm.every((d) => d <= 25 + 1e-7));
if (originalBytes) {
  assert.equal(digest(await readFile(originalPath)), digest(originalBytes), 'Original failed search remains unchanged');
}
assert.deepEqual(await Promise.all(pointerFiles.map(async (p) => digest(await readFile(join(root, p))))), pointerBefore);
const lookup = await call('/api/local-compute/lookup', { method: 'POST', headers, body: JSON.stringify(request) }).then((r) => r.json());
assert.equal(lookup.hit, true);
assert.equal(lookup.job.cached, true);
assert.equal(lookup.job.key, job.key);
if (hasHistoricalRecord) {
  const oldRecord = await call('/api/local-compute/library/' + originalKey).then((r) => r.json());
  assert.equal(oldRecord.record.status, 'no_layout');
  assert.equal(oldRecord.record.compatible, false);
}
const newRecord = await call('/api/local-compute/library/' + job.key).then((r) => r.json());
assert.equal(newRecord.record.status, 'completed');
assert.equal(newRecord.record.compatible, true);
assert.deepEqual(newRecord.record.layout.xyzMm, job.result.layout.xyzMm);
const page = await call('/design?ar=90&saved=' + job.key);
assert.equal(page.status, 200); // HTTP check only; no browser interaction assertion.
const report = {
  status: 'passed', scope: 'Same-constraint real API recovery; no browser interaction testing',
  request, old_cache_key: originalKey, new_cache_key: job.key,
  elapsed_seconds: (Date.now() - started) / 1000, result_cached: job.cached,
  geometry: job.result.geometry, metrics: job.result.metrics,
  center_selection: job.result.diagnostics.center_selection,
  centers: job.result.layout.centerVertexIndices,
  old_record_checked: hasHistoricalRecord, original_experiment_pointers_unchanged: true, cache_reuse_verified: true,
  formal_population_ar: false,
};
const directory = resolve('outputs/radius-recovery', new Date().toISOString().replaceAll(':', '-'));
await mkdir(directory, { recursive: true });
await writeFile(join(directory, 'integration.json'), JSON.stringify(report, null, 2), { flag: 'wx' });
console.log(JSON.stringify({ ...report, report_path: join(directory, 'integration.json') }, null, 2));
