/** One explicitly bounded real experiment, then read-only cache replay. No new layout search. */
import assert from 'node:assert/strict';
import { readFile, readdir, mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, join } from 'node:path';
import { validateSourceResult } from './source-reception-server.mjs';
const root = resolve('..'),
  base = 'http://localhost:3000';
const json = async (path, options) => {
  const r = await fetch(base + path, options);
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
for (
  let attempt = 0;
  ['running', 'cancelling'].includes(job.status) && attempt < 100;
  attempt++
) {
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
assert.deepEqual(await oldJobs(), beforeJobs);
assert.deepEqual(await digests(), beforeHashes);
const unauthed = await fetch(base + '/api/source-reception/jobs', {
  ...options,
  headers: { 'Content-Type': 'application/json' },
});
assert.equal(unauthed.status, 403);
for (const route of [
  '/',
  '/design',
  '/library',
  '/reception?record=' + row.id + '&ar=90',
])
  assert.equal((await fetch(base + route)).status, 200);
const report = {
  status: 'passed',
  completed_utc: new Date().toISOString(),
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
