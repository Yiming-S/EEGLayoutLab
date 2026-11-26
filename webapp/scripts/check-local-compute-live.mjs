/** HTTP-to-Python integration, not browser or visual QA. Uses real local jobs. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { validateWorkerResult } from '../server/local-compute-server.mjs';
import { scriptServer } from './helpers/service-session.mjs';

// The Python service (eeglayoutlab serve): with EEG_SERVICE_RUNTIME (its <workspace>/.eeglayoutlab/runtime.json), or
// EEG_SERVICE_TOKEN and EEG_TEST_URL, the script signs in as its launched browser and sends the session cookie
// (helpers/service-session.mjs). With EEG_TEST_URL alone, the legacy Node host there. EEG_REPOSITORY_ROOT is the
// root the server serves (default this checkout).
const { base, service } = await scriptServer();
const call = (path, options = {}) => fetch(base + path,
  { ...options, headers: { ...options.headers, ...(service ? { Cookie: service.cookie } : {}) } });
const health = await call('/api/local-compute/health').then((r) => r.json());
assert.equal(health.available, true);
const headers = { 'Content-Type': 'application/json', 'X-EEG-Compute-Token': health.token };
const observations = [];
const delay = (ms) => new Promise((done) => setTimeout(done, ms));
async function submit(request) {
  const response = await call('/api/local-compute/jobs', { method: 'POST', headers, body: JSON.stringify(request) });
  // The HTTP status last: an error body has its own `code` (the stable error code) on both hosts.
  return { ...await response.json(), code: response.status };
}
async function settled(job) {
  const start = Date.now();
  while (['queued', 'running', 'cancelling'].includes(job.status)) {
    if (Date.now() - start > 180000) throw new Error('Integration test exceeded server deadline');
    await delay(300);
    const response = await call(`/api/local-compute/jobs/${job.id}`);
    assert.equal(response.status, 200);
    job = (await response.json()).job;
  }
  return job;
}
if (health.active_job) await settled(health.active_job);
for (const request of [
  { region_count: 2, radius_mm: 35, mode: 'preset', mask_codes: ['PL', 'PR'] },
  { region_count: 2, radius_mm: 40, mode: 'preset', mask_codes: ['PL', 'PR'] },
  { region_count: 4, radius_mm: 50, mode: 'whole_surface' },
  { region_count: 1, radius_mm: 15, mode: 'whole_surface' },
  { region_count: 1, radius_mm: 80, mode: 'whole_surface' },
  { region_count: 3, radius_mm: 50, mode: 'whole_surface' },
  { region_count: 6, radius_mm: 80, mode: 'low_hair' },
]) {
  const started = Date.now(), submitted = await submit(request);
  assert.equal(submitted.code, 202, JSON.stringify(submitted));
  const job = await settled(submitted.job);
  assert.ok(['completed', 'no_layout'].includes(job.status), JSON.stringify(job));
  if (request.region_count === 1 && request.radius_mm === 15) assert.equal(job.status, 'no_layout');
  if ([2, 4].includes(request.region_count)) assert.equal(job.status, 'completed');
  validateWorkerResult(job.result, request);
  // Wait for the durable completion record before asserting cache behavior.
  await delay(100);
  const cache = await submit(request);
  assert.equal(cache.code, 202); assert.equal(cache.job.cached, true);
  const record = { request, status: job.status, wall_seconds: (Date.now() - started) / 1000,
    job_id: job.id, cache_verified: true, geometry: job.result.geometry, metrics: job.result.metrics };
  observations.push(record);
  console.log(JSON.stringify(record));
}
const bad = await submit({ region_count: 2, radius_mm: 35, mode: 'preset', mask_codes: ['PL_superior', 'PR'] });
assert.equal(bad.code, 400);
const unauthorized = await call('/api/local-compute/jobs', { method: 'POST',
  headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ region_count: 2, radius_mm: 35, mode: 'whole_surface' }) });
assert.equal(unauthorized.status, 403);
const crossOrigin = await call('/api/local-compute/health', { headers: { Origin: 'https://example.org' } });
assert.equal(crossOrigin.status, 403);
const report = { status: 'passed', scope: 'real localhost HTTP -> Python -> durable result/cache; no browser QA',
  observations, invalid_configuration_rejected: true, missing_token_rejected: true, cross_origin_rejected: true,
  formal_population_ar: false, completed_utc: new Date().toISOString() };
const directory = resolve('outputs/local-compute', new Date().toISOString().replaceAll(':', '-'));
await mkdir(directory, { recursive: true });
await writeFile(resolve(directory, 'integration.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify({ status: report.status, report: resolve(directory, 'integration.json') }));
