/** Explicit local integration test. Saves real editor evaluations, never mocks scores. */
import assert from 'node:assert/strict';
import { scriptServer } from './helpers/service-session.mjs';

// The Python service (eeglayoutlab serve): with EEG_SERVICE_RUNTIME (its <workspace>/.eeglayoutlab/runtime.json), or
// EEG_SERVICE_TOKEN and EEG_TEST_URL, the script signs in as its launched browser and sends the session cookie
// (helpers/service-session.mjs). With EEG_TEST_URL alone, the legacy Node host there.
const { base, service } = await scriptServer();
// Node's host knows a browser by the visitor cookie it issues; without it every poll would be another visitor's.
let visitorCookie = '';
const cookies = (...extra) => [service?.cookie, visitorCookie, ...extra].filter(Boolean).join('; ');
async function json(path, options = {}) {
  const headers = new Headers(options.headers);
  const cookie = cookies();
  if (cookie) headers.set('Cookie', cookie);
  const response = await fetch(base + path, { ...options, headers });
  const issued = response.headers.get('set-cookie');
  if (issued) visitorCookie = issued.split(';')[0];
  const data = await response.json();
  if (!response.ok) throw new Error(`${response.status}: ${data.error ?? path}`);
  return data;
}
const token = (await json('/api/local-compute/health')).token;
async function submit(request) {
  let { job } = await json('/api/electrode-editor/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-EEG-Compute-Token': token },
    body: JSON.stringify(request),
  });
  const start = Date.now();
  // Both hosts queue a new edit first.
  while (['queued', 'running', 'cancelling'].includes(job.status)) {
    if (Date.now() - start > 180000) throw new Error('Integration test polling timed out');
    await new Promise((resolve) => setTimeout(resolve, 600));
    job = (await json('/api/electrode-editor/jobs/' + job.id)).job;
  }
  assert.equal(job.status, 'completed', job.message);
  return job;
}
const { records: parents } = await json('/api/electrode-editor/parents');
const parent = parents.find((p) => p.region_count === 2 && p.request?.mask_codes?.includes('PL')
  && p.request?.mask_codes?.includes('PR'));
assert.ok(parent, 'An exact two-region bilateral-ear parent is required');
const prepared = await submit({ action: 'prepare', parent_id: parent.id }), domain = prepared.result;
const full = {
  action: 'evaluate', parent_id: parent.id, parent_digest: prepared.parent_digest, seed: 2026,
  slots: domain.original_indices.map((bank_index) => ({ bank_index, enabled: true })),
};
const original = await submit(full);
assert.equal(original.result.electrode_count, 64);
assert.deepEqual(original.result.parent_metrics, original.result.edited_metrics);
console.log(JSON.stringify({ stage: 'original64', parent: parent.label, metrics: original.result.edited_metrics }));
const reduced = structuredClone(full);
reduced.slots[0].enabled = false;
const reducedJob = await submit(reduced);
assert.equal(reducedJob.result.electrode_count, 63);
assert.ok(reducedJob.result.edited_metrics.field_relative <= original.result.edited_metrics.field_relative + 1e-10);
assert.ok(reducedJob.result.edited_metrics.sensitivity_tail <= original.result.edited_metrics.sensitivity_tail + 1e-10);
console.log(JSON.stringify({ stage: 'delete_one_63', metrics: reducedJob.result.edited_metrics }));
const repeated = await submit(reduced);
assert.equal(repeated.cached, true);
assert.equal(repeated.key, reducedJob.key);
console.log(JSON.stringify({ stage: 'cache_hit', cached: repeated.cached, key: repeated.key }));
const map = new Map(domain.regions.flatMap((r) => r.bank_indices.map((b, i) => [b, r.xyz_mm[i]])));
let moved = null;
for (let slot = 1; slot < 64 && !moved; slot++) {
  const r = domain.regions[domain.parent.layout.regionIndices[slot]];
  for (const candidate of r.bank_indices) {
    if (candidate === full.slots[slot].bank_index) continue;
    const point = map.get(candidate);
    if (reduced.slots.every((s, i) => i === slot || !s.enabled
      || Math.hypot(...map.get(s.bank_index).map((v, k) => v - point[k])) >= 4 - 1e-7)) {
      moved = structuredClone(reduced);
      moved.slots[slot].bank_index = candidate;
      break;
    }
  }
}
assert.ok(moved, 'A valid within-region move exists');
const movedJob = await submit(moved);
assert.equal(movedJob.result.electrode_count, 63);
assert.notEqual(movedJob.key, reducedJob.key);
console.log(JSON.stringify({ stage: 'move_and_delete_63', metrics: movedJob.result.edited_metrics }));
const two = structuredClone(full);
two.slots.forEach((s, i) => { s.enabled = i === 0 || i === 32; });
const twoJob = await submit(two);
assert.equal(twoJob.result.electrode_count, 2);
assert.equal(twoJob.result.edited_metrics.localization_relative, null);
assert.equal(twoJob.result.edited_metrics.conditional_global, null);
console.log(JSON.stringify({ stage: 'two_electrode_edge', metrics: twoJob.result.edited_metrics }));
const saved = (await json('/api/electrode-editor/records')).records;
assert.ok(saved.some((r) => r.key === movedJob.key));
for (const locale of ['en', 'zh-CN']) {
  // The Python service serves its pages to the session only.
  const r = await fetch(base + '/electrodes?parent=' + parent.id + '&ar=32',
    { headers: { Cookie: cookies('eeg-layout-language=' + locale) } });
  await r.arrayBuffer();
  assert.equal(r.status, 200);
}
console.log(JSON.stringify({
  stage: 'passed', parent_id: parent.id, keys: [original.key, reducedJob.key, movedJob.key, twoJob.key],
}));
