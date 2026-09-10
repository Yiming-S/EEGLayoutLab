/** Explicit local end-to-end acceptance. May run one native FEM on a cache miss. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve, dirname, sep } from 'node:path';
const [record, output] = process.argv.slice(2);
if (!/^[a-f0-9]{64}$/.test(record ?? '') || !output)
  throw new Error(
    'Usage: node scripts/verify-source-upgrade.mjs RECORD_ID OUTPUT_JSON',
  );
const root = resolve(import.meta.dirname, '../..'),
  path = resolve(root, output);
if (
  !path.startsWith(resolve(root, 'results/v2/upgrade_regression_tests') + sep)
)
  throw new Error('Output must be a new upgrade_regression_tests file');
const base = 'http://localhost:3000';
const health = await (
  await fetch(base + '/api/source-reception/health')
).json();
if (health.active_job) throw new Error('Another source calculation is active');
const headers = {
  'Content-Type': 'application/json',
  Origin: base,
  'X-EEG-Compute-Token': health.token,
};
async function post(endpoint, body) {
  const r = await fetch(base + endpoint, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  const value = await r.json();
  if (!r.ok) throw new Error(JSON.stringify(value));
  return value;
}
async function scenario(request) {
  let { job } = await post('/api/source-reception/jobs', request);
  const deadline = Date.now() + 620000;
  let message = '';
  while (['running', 'cancelling'].includes(job.status)) {
    if (job.message !== message) {
      message = job.message;
      console.log(
        JSON.stringify({ status: job.status, message, progress: job.progress }),
      );
    }
    if (Date.now() > deadline)
      throw new Error('Acceptance timeout; inspect local job ' + job.id);
    await new Promise((r) => setTimeout(r, 1000));
    const response = await fetch(base + '/api/source-reception/jobs/' + job.id);
    ({ job } = await response.json());
  }
  assert.equal(job.status, 'completed', job.message);
  assert.equal(job.result.schema_version, 'source-reception/2');
  const hit = await post('/api/source-reception/lookup', request);
  assert.equal(hit.hit, true);
  assert.equal(hit.job.cached, true);
  assert.deepEqual(hit.job.result, job.result);
  return job;
}
const common = {
  record_id: record,
  waveform: 'burst',
  artifact_scale: 1,
  seed: 2026,
};
const single = await scenario({
  ...common,
  mode: 'single_source',
  source_index: 2,
});
const multi = await scenario({
  ...common,
  mode: 'multi_source',
  brain_region: 'frontal',
});
assert.equal(single.result.source.patch_count, 1);
assert.equal(multi.result.source.patch_count, 6);
assert.deepEqual(single.result.layout, multi.result.layout);
assert.equal(
  single.result.provenance.provider_id,
  multi.result.provenance.provider_id,
);
assert.equal(multi.result.provenance.fem_recomputed, false);
assert.equal(multi.result.provenance.forward_mode, 'native_fem_cache');
const summary = (j) => ({
  job_id: j.id,
  key: j.key,
  cached: j.cached,
  elapsed_seconds: j.result.elapsed_seconds,
  version: j.result.schema_version,
  source_count: j.result.source.patch_count,
  forward_mode: j.result.provenance.forward_mode,
  provider_id: j.result.provenance.provider_id,
  fem_recomputed: j.result.provenance.fem_recomputed,
  result_cache: 'results/v2/source_reception_v2_jobs/' + j.key + '/cache.json',
});
const report = {
  schema: 'source-upgrade-acceptance/1',
  completed_at: new Date().toISOString(),
  record_id: record,
  checks: {
    native_coordinates_preserved_between_scenarios: true,
    shared_forward_provider: true,
    repeated_request_exact_cache_hit: true,
    multi_source_no_fem_recompute: true,
  },
  single: summary(single),
  multi: summary(multi),
  visual_interaction: 'pending_manual_unlock',
};
await mkdir(dirname(path), { recursive: true });
await writeFile(path, JSON.stringify(report, null, 2), { flag: 'wx' });
console.log(JSON.stringify(report));
