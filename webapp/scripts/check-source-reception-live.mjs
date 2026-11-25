/** One explicitly bounded real experiment, then read-only cache replay. No new layout search. */
import assert from 'node:assert/strict';
import { readFile, readdir, mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, join } from 'node:path';
import { validateSourceResult } from './source-reception-server.mjs';
import { openServiceSession } from './helpers/service-session.mjs';

// The Node host at EEG_TEST_URL (default http://127.0.0.1:3000), or the Python service (eeglayoutlab serve): with
// EEG_SERVICE_RUNTIME (its <workspace>/.eeglayoutlab/runtime.json) or EEG_SERVICE_TOKEN and EEG_TEST_URL, sign in
// as its launched browser and send the session cookie. EEG_REPOSITORY_ROOT is the root the service serves (default
// this checkout); the report is written below it, so run the script on a copy of the installation.
const root = resolve(process.env.EEG_REPOSITORY_ROOT || '..');
const service =
  process.env.EEG_SERVICE_RUNTIME || process.env.EEG_SERVICE_TOKEN
    ? await openServiceSession({ base: process.env.EEG_TEST_URL })
    : null;
const base =
  service?.base || process.env.EEG_TEST_URL || 'http://127.0.0.1:3000';
// Node's host knows a browser by the visitor cookie it issues; without it every poll would be another visitor's,
// and its records list only that browser's receipts.
let visitorCookie = '';
const cookies = (...extra) =>
  [service?.cookie, visitorCookie, ...extra].filter(Boolean).join('; ');
const call = async (path, options = {}) => {
  const headers = new Headers(options.headers);
  const cookie = cookies();
  if (cookie) headers.set('Cookie', cookie);
  const r = await fetch(base + path, { ...options, headers });
  const issued = r.headers.get('set-cookie');
  if (issued) visitorCookie = issued.split(';')[0];
  return r;
};
const json = async (path, options) => {
  const r = await call(path, options);
  const data = await r.json();
  assert.ok(r.ok, `${path}: ${r.status} ${data.error ?? ''}`);
  return data;
};
const originalPaths = [
  'webapp/public/data/single_head_optimization.json',
  'results/v2/current_strict_area_budget_study.json',
  'results/v2/current_multiregion_bank.json',
];
const digests = async () =>
  Promise.all(
    originalPaths.map(async (p) =>
      createHash('sha256')
        .update(await readFile(join(root, p)))
        .digest('hex'),
    ),
  );
const oldJobs = async () =>
  (await readdir(join(root, 'results/v2/local_app_jobs'), { recursive: true }))
    .filter((p) => p.endsWith('request.json'))
    .sort();
const beforeHashes = await digests(),
  beforeJobs = await oldJobs();
const h = await json('/api/source-reception/health');
assert.equal(
  h.active_job,
  null,
  'Do not interrupt an existing source computation',
);
assert.equal(
  (await json('/api/local-compute/health')).active_job,
  null,
  'Do not interrupt an existing layout computation',
);
const library = await json('/api/local-compute/library');
const row = library.records.find(
  (r) =>
    r.status === 'completed' &&
    r.dataset_id === 'cache' &&
    r.request?.region_count === 2 &&
    r.request.radius_mm === 35 &&
    JSON.stringify(r.request.mask_codes) === JSON.stringify(['AL', 'AR']),
);
assert.ok(
  row,
  'Saved bilateral expanded-ear 32+32 layout must exist; never silently substitute',
);
const { record } = await json('/api/local-compute/library/' + row.id);
const request = {
  record_id: row.id,
  brain_region: 'frontal',
  waveform: 'burst',
  artifact_scale: 1,
  seed: 2026,
};
const options = {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-EEG-Compute-Token': h.token,
  },
  body: JSON.stringify(request),
};
const start = performance.now(),
  submitted = await json('/api/source-reception/jobs', options);
let job = submitted.job;
// Both hosts queue a new experiment first; v1's worker stops itself after 120 s.
while (['queued', 'running', 'cancelling'].includes(job.status)) {
  if (performance.now() - start > 240000)
    throw new Error('Integration test polling timed out');
  await new Promise((r) => setTimeout(r, 500));
  job = (await json('/api/source-reception/jobs/' + job.id)).job;
}
assert.equal(job.status, 'completed', job.message);
validateSourceResult(job.result, request, record);
assert.equal(job.result.protocol.sample_rate_hz, 200);
assert.equal(job.result.protocol.duration_s, 20);
const elapsed = performance.now() - start,
  lookupStart = performance.now(),
  stored = await json('/api/source-reception/lookup', options);
const cacheRoundtripMs = performance.now() - lookupStart;
assert.equal(stored.hit, true);
assert.equal(stored.job.cached, true);
assert.deepEqual(stored.job.result, job.result);
// The records list names the receipt without its waveforms; its original download is the same result.
const records = await json('/api/community/records');
assert.equal(records.schema, 'browser-experiment-records/1');
const listed = records.records.find((r) => r.id === job.id);
assert.ok(listed, 'The completed experiment is a record of this browser or workspace');
assert.equal(listed.catalog.parent_id, row.id);
assert.ok(!JSON.stringify(records).includes('waveforms'));
const saved = await json(`/api/community/records/${job.id}/result`);
assert.deepEqual(saved.result, job.result);
assert.deepEqual(await oldJobs(), beforeJobs);
assert.deepEqual(await digests(), beforeHashes);
const unauthed = await call('/api/source-reception/jobs', {
  ...options,
  headers: { 'Content-Type': 'application/json' },
});
await unauthed.arrayBuffer();
assert.equal(unauthed.status, 403);
for (const route of [
  '/',
  '/design',
  '/library',
  '/reception?record=' + row.id + '&ar=90',
]) {
  // The Python service serves its pages to the session only.
  const page = await call(route);
  await page.arrayBuffer();
  assert.equal(page.status, 200, route);
}
const report = {
  status: 'passed',
  completed_utc: new Date().toISOString(),
  host: service ? 'python' : 'node',
  layout_label: row.label,
  record_id: row.id,
  request,
  result_key: job.key,
  computed_or_reused: job.cached ? 'reused' : 'computed',
  submit_to_result_ms: elapsed,
  cache_roundtrip_ms: cacheRoundtripMs,
  old_layout_jobs_unchanged: true,
  original_data_unchanged: true,
  conditions: job.result.conditions,
  brain_amplitude_ratio: job.result.metrics.pure_brain_amplitude_ratio,
  source_xyz_mm: job.result.source.xyz_mm,
  preview_points: job.result.waveforms.time_s.length,
  result_bytes: Buffer.byteLength(JSON.stringify(job.result)),
  browser_testing_performed: false,
};
const directory = join(
  root,
  'webapp/outputs/source-reception',
  new Date().toISOString().replaceAll(':', '-'),
);
await mkdir(directory, { recursive: true });
await writeFile(
  join(directory, 'integration.json'),
  JSON.stringify(report, null, 2),
);
console.log(
  JSON.stringify(
    { ...report, report_path: join(directory, 'integration.json') },
    null,
    2,
  ),
);
