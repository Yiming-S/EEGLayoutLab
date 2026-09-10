/** Real local HTTP checks. Read-only reuse only; no new numerical simulations. */
import assert from 'node:assert/strict';
import { mkdir, readdir, writeFile, readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, join } from 'node:path';
import { validateSavedRecord } from './local-data-library.mjs';

const base = 'http://localhost:3000', root = resolve('..');
const json = async (url, options) => { const response = await fetch(base + url, options); assert.ok(response.ok, `${url}: ${response.status}`); return response.json(); };
const files = async () => (await readdir(join(root, 'results/v2/local_app_jobs'), { recursive: true })).filter((p) => p.endsWith('request.json')).sort();
const unchangedSources = ['webapp/public/data/single_head_optimization.json', 'results/v2/current_strict_area_budget_study.json'];
const hashes = async () => Promise.all(unchangedSources.map(async (p) => createHash('sha256').update(await readFile(join(root, p))).digest('hex')));
const before = await files(), originalHashes = await hashes();
const health = await json('/api/local-compute/health');
assert.equal(health.available, true);
const headers = { 'Content-Type': 'application/json', 'X-EEG-Compute-Token': health.token };
const library = await json('/api/local-compute/library');
assert.equal(library.schema, 'local-data-library/1'); assert.deepEqual(library.warnings, []);
assert.equal(library.datasets.find((d) => d.id === 'offline_radius').count, 342);
assert.equal(library.datasets.find((d) => d.id === 'strict_area').count, 30);
const selected = library.datasets.map((d) => library.records.find((r) => r.dataset_id === d.id));
for (const row of selected) {
  assert.ok(row);
  const { record } = await json(`/api/local-compute/library/${row.id}`);
  validateSavedRecord(record);
  assert.equal(record.id, row.id);
  if (row.dataset_id !== 'cache') assert.equal(record.compatible, false);
}
const timings = [];
for (const row of library.records.filter((r) => r.dataset_id === 'cache' && r.compatible)) {
  const start = performance.now();
  const lookup = await json('/api/local-compute/lookup', { method: 'POST', headers, body: JSON.stringify(row.request) });
  assert.equal(lookup.hit, true); assert.equal(lookup.job.cached, true); assert.equal(lookup.job.source, 'local_cache');
  assert.deepEqual(lookup.job.result.metrics ?? null, row.metrics);
  const submitted = await json('/api/local-compute/jobs', { method: 'POST', headers, body: JSON.stringify(row.request) });
  assert.equal(submitted.job.cached, true); assert.equal(submitted.job.key, row.id);
  timings.push({ label: row.label, status: row.status, read_and_resubmit_ms: performance.now() - start });
}
const missRequest = { region_count: 1, radius_mm: 20, mode: 'whole_surface' };
const miss = await json('/api/local-compute/lookup', { method: 'POST', headers, body: JSON.stringify(missRequest) });
assert.equal(miss.hit, false);
assert.deepEqual(await files(), before); assert.deepEqual(await hashes(), originalHashes);
assert.equal((await json('/api/local-compute/health')).active_job?.id, health.active_job?.id);
const areaRecord = selected.find((row) => row.dataset_id === 'strict_area');
const routes = ['/', '/?domain=whole_scalp_free&area=120&r=3&ar=50', '/design', `/design?from=${areaRecord.id}&ar=50`, '/library', `/library?record=${areaRecord.id}&ar=50`, '/method?ar=50&returnTo=%2Fdesign%3Far%3D50', '/results'];
for (const route of routes) {
  const response = await fetch(base + route); assert.equal(response.status, 200);
}
const report = { status: 'passed', completed_utc: new Date().toISOString(), datasets: library.datasets,
  cached_requests_checked: timings.length, no_new_task_files: true, original_data_unchanged: true,
  lookup_miss_did_not_compute: true, source_separation_verified: true, routes_checked: routes, timings, browser_testing_performed: false };
const directory = resolve('outputs/local-library', new Date().toISOString().replaceAll(':', '-'));
await mkdir(directory, { recursive: true }); await writeFile(join(directory, 'integration.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ ...report, report_path: join(directory, 'integration.json') }, null, 2));
