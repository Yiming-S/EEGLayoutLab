/** Opt-in HTTP -> Python checks. Run only against an idle local checkout. */
import assert from 'node:assert/strict';
import { exportDesign } from '../lib/design-decision.ts';
import { validateWorkerResult } from '../server/local-compute-server.mjs';
import { validateEditorResult } from '../server/electrode-editor-server.mjs';
import { validateDesignResult } from '../server/design-evaluation-server.mjs';
import { validateSourceResult } from '../server/source-reception-server.mjs';
import { validateReceptionResult } from '../server/reception-v2-support.mjs';
import { openServiceSession } from './helpers/service-session.mjs';

// Opt-in: the Python service admits only requests with its session cookie; sign in as its launched browser.
const service = process.env.EEG_SERVICE_RUNTIME || process.env.EEG_SERVICE_TOKEN
  ? await openServiceSession({ base: process.env.EEG_TEST_URL }) : null;
const base = service?.base || process.env.EEG_TEST_URL || 'http://127.0.0.1:3000';
const url = new URL(base);
if (url.protocol !== 'http:' || !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) {
  throw new Error('The integration target must be an explicit local HTTP server.');
}
let browserCookie = '';
const sessionHeaders = service ? { Cookie: service.cookie } : {};
const cookies = () => [service?.cookie, browserCookie].filter(Boolean).join('; ');
// The server admits 20 submissions a minute per visitor. A fully cached run exceeds that, so wait out the window.
const admitted = async (send) => {
  for (let attempt = 0; ; attempt++) {
    const response = await send();
    if (response.status !== 429 || attempt === 2) return response;
    await response.arrayBuffer();
    await new Promise(resolve => setTimeout(resolve, 61000));
  }
};
const json = async (path, options) => {
  const requestHeaders = new Headers(options?.headers);
  const cookie = cookies();
  if (cookie) requestHeaders.set('Cookie', cookie);
  const response = await admitted(() => fetch(base + path, { ...options, headers: requestHeaders }));
  const issued = response.headers.get('set-cookie');
  if (issued) browserCookie = issued.split(';')[0];
  const body = await response.json();
  assert.ok(response.ok, `${path}: ${response.status} ${body.error || ''}`);
  return body;
};
const health = await json('/api/local-compute/health');
assert.equal(health.available, true);
assert.equal(health.active_job, null, 'Do not interrupt an existing job.');
assert.equal((await json('/api/source-reception/health')).active_job, null);
const headers = { 'Content-Type': 'application/json', 'X-EEG-Compute-Token': health.token, Origin: base };
const running = new Set(['running', 'queued', 'cancelling']);
async function run(endpoint, request, validate) {
  const submit = () => json(endpoint + '/jobs', { method: 'POST', headers, body: JSON.stringify(request) });
  let { job } = await submit();
  const started = Date.now(); // after admission: a rate-limit wait is not job time
  while (running.has(job.status)) {
    if (Date.now() - started > 620000) throw new Error('Integration deadline exceeded: ' + endpoint);
    await new Promise(resolve => setTimeout(resolve, 500));
    ({ job } = await json(endpoint + '/jobs/' + job.id));
  }
  assert.equal(job.status, 'completed', job.message);
  validate(job.result, request);
  // Completion can precede the atomic cache write by one event-loop turn.
  await new Promise(resolve => setTimeout(resolve, 100));
  const replay = (await submit()).job;
  assert.equal(replay.cached, true, 'Same input must replay the saved computation.');
  assert.deepEqual(replay.result, job.result);
  console.log(JSON.stringify({ check: endpoint, status: 'passed', wall_seconds: (Date.now() - started) / 1000, cached_replay: true }));
  return job;
}

for (const route of ['/', '/library', '/design', '/electrodes', '/coordinates', '/decision', '/reception', '/guide', '/method', '/results', '/pilot-results']) {
  const response = await fetch(base + route, { headers: sessionHeaders });
  assert.equal(response.status, 200, route);
  await response.arrayBuffer();
}
if (service) assert.equal((await fetch(base + '/api/local-compute/health')).status, 401, 'The service requires its session cookie.');
const library = await json('/api/local-compute/library');
assert.deepEqual(library.warnings, []);
assert.equal(library.records.filter(r => r.dataset_id === 'strict_area').length, 30);
assert.equal(library.records.filter(r => r.dataset_id === 'historical_area').length, 30);
assert.equal(library.records.filter(r => r.dataset_id === 'offline_radius').length, 342);
console.log(JSON.stringify({ check: 'routes-and-library', status: 'passed', pages: 11, supplied_records: 402 }));

const layout = await run('/api/local-compute', { region_count: 2, radius_mm: 35, mode: 'preset', mask_codes: ['AL', 'AR'] }, validateWorkerResult);
const { record } = await json('/api/local-compute/library/' + layout.key);
assert.equal(record.layout.xyzMm.length, 64);
assert.deepEqual(record.metrics, layout.result.metrics);
const bundle = await json('/api/local-compute/library/' + layout.key + '/bundle');
assert.ok(bundle);

const prepare = await run('/api/electrode-editor', { action: 'prepare', parent_id: record.id }, validateEditorResult);
const edit = { action: 'evaluate', parent_id: record.id, parent_digest: prepare.parent_digest, seed: 2026,
  slots: prepare.result.original_indices.map(bank_index => ({ bank_index, enabled: true })) };
edit.slots[0].enabled = false;
const edited = await run('/api/electrode-editor', edit, validateEditorResult);
assert.equal(edited.result.electrode_count, 63);
assert.ok(edited.result.edited_metrics.field_relative <= edited.result.parent_metrics.field_relative + 1e-10);

const design = { action: 'evaluate', design: exportDesign(record), radius_mm: 6, seed: 42 };
const evaluated = await run('/api/design-evaluation', design, validateDesignResult);
assert.deepEqual(evaluated.result.evaluated_xyz_mm, record.layout.xyzMm);

await run('/api/source-reception', { record_id: record.id, brain_region: 'frontal', waveform: 'burst', artifact_scale: 1, seed: 2026 }, (result, request) => validateSourceResult(result, request, record));
let nativeMode = null;
const optional = [];
if (process.argv.includes('--native')) {
  const nativeRequest = { ...design, design: { ...design.design, name: 'Native FEM integration fixture',
    xyz_mm: record.layout.referenceXyzMm.map((p, i) => [p[0] + (i === 0 ? .2 : 0), p[1], p[2]]) } };
  const native = await run('/api/design-evaluation', nativeRequest, validateDesignResult);
  // A published scalp-node table replaces the per-request solve; otherwise native FEM runs.
  assert.ok(['direct_fem', 'scalp_node_table'].includes(native.result.forward_mode));
  if (native.result.forward_mode === 'scalp_node_table') assert.match(native.result.native_qa.scalp_node_table.table_id, /^[a-f0-9]{64}$/);
  assert.ok(native.result.native_qa.reference_relative_difference <= 1e-8);
  nativeMode = native.result.forward_mode;
  const nativeRecord = { layout: { xyzMm: native.result.evaluated_xyz_mm,
    referenceXyzMm: record.layout.referenceXyzMm, regionIndices: nativeRequest.design.region_indices } };
  for (const scenario of [{ mode: 'single_source', source_index: 2 }, { mode: 'multi_source', brain_region: 'frontal' }]) {
    await run('/api/source-reception', { record_id: native.key, waveform: 'burst', artifact_scale: 1, seed: 2026, ...scenario },
      (result, request) => validateReceptionResult(result, request, nativeRecord));
  }
  // Optional protocols are separate cached requests whose provenance names the model; none reaches reception.
  const optionArg = (name) => { const index = process.argv.indexOf(name); return index > 0 ? process.argv[index + 1] : undefined; };
  const notReceivable = async (key) => {
    const response = await admitted(() => fetch(base + '/api/source-reception/jobs', { method: 'POST', headers: { ...headers, Cookie: cookies() },
      body: JSON.stringify({ record_id: key, mode: 'single_source', source_index: 2, waveform: 'burst', artifact_scale: 1, seed: 2026 }) }));
    // A rate-limit answer says nothing about the record.
    assert.ok(response.status >= 400 && response.status < 500 && response.status !== 429, 'reception must refuse ' + key + ': ' + response.status);
    await response.arrayBuffer();
  };
  const spatial = await run('/api/design-evaluation', { ...nativeRequest, noise_model: { kind: 'spatial', rho: 0.5, length_mm: 20 } }, validateDesignResult);
  assert.equal(spatial.result.provenance.noise_model.kind, 'spatial_gaussian_correlation');
  assert.notEqual(spatial.key, native.key);
  await notReceivable(spatial.key);
  optional.push('spatial_noise');
  const scenario = optionArg('--scenario');
  if (scenario) {
    const mismatched = await run('/api/design-evaluation', { ...nativeRequest, conductivity_scenario: scenario }, validateDesignResult);
    assert.equal(mismatched.result.provenance.model_mismatch.scenario.name, scenario);
    assert.ok(mismatched.result.provenance.model_mismatch.matched_model.field_relative > 0);
    await notReceivable(mismatched.key);
    optional.push('conductivity_scenario:' + scenario);
  }
  const head = optionArg('--head');
  if (head) {
    const { heads } = await json('/api/design-evaluation/heads');
    assert.ok(heads.some((entry) => entry.head_id === head), 'head package not listed: ' + head);
    const other = await run('/api/design-evaluation', { ...nativeRequest, head_id: head }, validateDesignResult);
    assert.equal(other.result.provenance.head.head_id, head);
    assert.ok(other.result.nominal.field_relative > 0 && other.result.nominal.localization_relative > 0);
    await notReceivable(other.key);
    optional.push('head:' + head);
  }
}
assert.equal((await fetch(base + '/api/local-compute/jobs', { method: 'POST', headers: sessionHeaders })).status, 403);
assert.equal((await fetch(base + '/api/local-compute/health', { headers: { ...sessionHeaders, Origin: 'https://example.org' } })).status, 403);
console.log(JSON.stringify({ status: 'passed', native_fem_checked: process.argv.includes('--native'), new_coordinate_forward_mode: nativeMode, optional_protocols: optional, scope: 'Local HTTP, numerical jobs, coordinate evaluation, electrode deletion, source simulation and cache replay. No browser QA; new native FEM and v2 sources only with --native.' }));
