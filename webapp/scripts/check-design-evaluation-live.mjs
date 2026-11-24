/** Explicit local integration experiment. Writes only through the app job cache. */
import assert from 'node:assert/strict';
import { exportDesign } from '../lib/design-decision.ts';
import { validateDesignResult } from './design-evaluation-server.mjs';
import { openServiceSession } from './helpers/service-session.mjs';

// The Node host at EEG_TEST_URL (default http://127.0.0.1:3000), or the Python service (eeglayoutlab serve): with
// EEG_SERVICE_RUNTIME (its <workspace>/.eeglayoutlab/runtime.json) or EEG_SERVICE_TOKEN and EEG_TEST_URL, sign in
// as its launched browser and send the session cookie.
const service = process.env.EEG_SERVICE_RUNTIME || process.env.EEG_SERVICE_TOKEN
  ? await openServiceSession({ base: process.env.EEG_TEST_URL }) : null;
const base = service?.base || process.env.EEG_TEST_URL || 'http://127.0.0.1:3000';
// Node's host knows a browser by the visitor cookie it issues; without it every poll would be another visitor's.
let visitorCookie = '';
async function json(path, options = {}) {
  const headers = new Headers(options.headers);
  const cookie = [service?.cookie, visitorCookie].filter(Boolean).join('; ');
  if (cookie) headers.set('Cookie', cookie);
  const response = await fetch(base + path, { ...options, headers });
  const issued = response.headers.get('set-cookie');
  if (issued) visitorCookie = issued.split(';')[0];
  const body = await response.json();
  if (!response.ok) throw new Error(`${response.status}: ${body.error}`);
  return body;
}
const health = await json('/api/local-compute/health');
assert.equal(
  health.active_job,
  null,
  'An existing user job is active; do not start test',
);
const library = await json('/api/local-compute/library');
const row = library.records.find(
  (r) =>
    r.dataset_id === 'strict_area' &&
    r.area_cap_cm2 === 60 &&
    r.region_count === 2 &&
    r.mode.includes('whole'),
);
assert.ok(row);
const { record } = await json('/api/local-compute/library/' + row.id);
const candidate = exportDesign(record);
async function run(request) {
  let { job } = await json('/api/design-evaluation/jobs', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-EEG-Compute-Token': health.token,
    },
    body: JSON.stringify(request),
  });
  const stop = Date.now() + 620000;
  let last = '';
  // Both hosts queue a new evaluation first.
  while (['queued', 'running', 'cancelling'].includes(job.status) && Date.now() < stop) {
    if (job.message !== last) {
      last = job.message;
      console.log(last);
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
    ({ job } = await json('/api/design-evaluation/jobs/' + job.id));
  }
  assert.equal(job.status, 'completed', job.message);
  validateDesignResult(job.result, request);
  console.log(
    JSON.stringify({
      key: job.key,
      cached: job.cached,
      forward: job.result.forward_mode,
      elapsed_seconds: job.result.elapsed_seconds,
      nominal: job.result.nominal,
      trials: job.result.trials.map(
        ({
          index,
          status,
          actual_max_mm,
          target_error_max_mm,
          unchanged_fraction,
          field_relative,
          fixed_estimator_field_relative,
        }) => ({
          index,
          status,
          actual_max_mm,
          target_error_max_mm,
          unchanged_fraction,
          field_relative,
          fixed_estimator_field_relative,
        }),
      ),
    }),
  );
  return job;
}
const common = { radius_mm: 6, seed: 42 };
if (process.argv.includes('--native')) {
  const design = {
    ...candidate,
    name: '新坐标FEM验证 · 标准64的首点偏移0.2mm',
    xyz_mm: record.layout.referenceXyzMm.map((p, i) => [
      p[0] + (i === 0 ? 0.2 : 0),
      p[1],
      p[2],
    ]),
  };
  const job = await run({ action: 'evaluate', design, ...common });
  assert.equal(job.result.forward_mode, 'direct_fem');
  assert.ok(job.result.native_qa.reference_relative_difference <= 1e-8);
  assert.equal((await run({ action: 'evaluate', design, ...common })).cached, true);
} else {
  const reference = {
    ...candidate,
    name: '标准全头64恒等检查',
    xyz_mm: record.layout.referenceXyzMm,
  };
  const result = (
    await run({ action: 'evaluate', design: reference, ...common })
  ).result;
  for (const key of [
    'field_relative',
    'sensitivity_tail',
    'localization_relative',
  ])
    assert.ok(Math.abs(result.nominal[key] - 1) < 1e-9, key);
  const request = { action: 'perturb', design: candidate, ...common };
  await run(request);
  assert.equal((await run(request)).cached, true);
}
