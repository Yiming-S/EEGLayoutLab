/**
 * Phase 3, Slice 16: Browser-tier cache-only fixture builder.
 *
 * Connects to a running writable `eeglayoutlab serve` instance (via `EEG_SERVICE_RUNTIME` or
 * `EEG_SERVICE_TOKEN` + `EEG_TEST_URL`) on a composed root (`base` + `scalp-node-table`) and
 * populates the exact verified records required by the `serve --cache-only` browser scripts:
 *
 *   1. Golden 64-electrode native-frame design evaluation (`EEG_GOLDEN_REQUEST`)
 *   2. Compatible two-region `AL,AR` 35 mm radius search layout (`radius_record_id`)
 *   3. 63-electrode edited copy of that `AL,AR` 35 mm layout (`EEG_EDITOR_RECORD_KEY`)
 *   4. All 8 robustness study cases from `tests/service/fixtures/robustness/case-requests.json`
 *   5. v1 multi-source signal simulation on the `AL,AR` 35 mm layout (`EEG_SIGNAL_V1_FIXTURE`)
 *   6. When SimNIBS native runtime is available (`direct_fem_available === true` and not
 *      `--skip-v2`), a v2 single-source signal simulation (`EEG_SIGNAL_FIXTURE` with
 *      `region_definition: "dk40-six-roi-v1"`) plus a complete research delivery bundle
 *      (`EEG_OLDER_DELIVERY`) holding `layout`, `editor` and `source` entries.
 *
 * Writes `<out-dir>/fixtures.json` and `<out-dir>/fixtures.env` so CI or local QA can stop the
 * writable service, launch `eeglayoutlab serve <clean-workspace> --cache-only`, source
 * `fixtures.env`, and run the browser suite with zero uncached job submissions.
 */
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { isAbsolute, join, resolve } from 'node:path';
import { scriptServer } from './helpers/service-session.mjs';

const args = process.argv.slice(2);
let outDir = process.env.EEG_FIXTURE_OUTPUT || '';
let skipV2 = false;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--out-dir' && args[i + 1]) {
    outDir = args[++i];
  } else if (args[i] === '--skip-v2') {
    skipV2 = true;
  } else {
    throw new Error(`Unknown argument: ${args[i]}`);
  }
}

const root = resolve(process.env.EEG_REPOSITORY_ROOT || resolve(import.meta.dirname, '../..'));
const targetDir = resolve(outDir || join(root, 'artifacts/browser-fixtures'));
assert.ok(isAbsolute(targetDir), 'Output directory must be an absolute path.');
await mkdir(targetDir, { recursive: true, mode: 0o700 });

const { base, service } = await scriptServer({ node: false });
assert.ok(service, 'build-browser-fixtures.mjs requires a running Python service (EEG_SERVICE_RUNTIME).');

async function api(path, { method = 'GET', body } = {}) {
  const headers = { Cookie: service.cookie };
  if (method !== 'GET' && method !== 'HEAD') {
    headers.Origin = base;
    headers['X-EEG-Compute-Token'] = service.csrf;
    headers['Content-Type'] = 'application/json';
  }
  const init = { method, headers };
  if (body !== undefined) init.body = JSON.stringify(body);
  const response = await fetch(base + path, init);
  const value = await response.json();
  assert.ok(response.ok, `${method} ${path} -> ${response.status}: ${value?.error || JSON.stringify(value)}`);
  return value;
}

async function runJob(kind, requestBody, timeoutMs = 600000) {
  const submitted = await api(`/api/${kind}/jobs`, { method: 'POST', body: requestBody });
  let job = submitted.job;
  assert.ok(job && typeof job.id === 'string', `Missing job receipt for ${kind}`);
  const deadline = Date.now() + timeoutMs;
  while (['queued', 'running', 'cancelling'].includes(job.status)) {
    assert.ok(Date.now() < deadline, `${kind} job ${job.id} timed out after ${timeoutMs} ms`);
    await new Promise((done) => setTimeout(done, 350));
    job = (await api(`/api/${kind}/jobs/${job.id}`)).job;
  }
  assert.equal(job.status, 'completed', `${kind} job ${job.id} ended as ${job.status}: ${job.message}`);
  return job;
}

const health = await api('/api/local-compute/health');
assert.equal(health.available, true, 'Base model data is not available on the target service.');
assert.equal(health.maintenance, false, 'Start eeglayoutlab serve without --cache-only while building fixtures.');
const dataStatus = await api('/api/data-status');
assert.equal(
  dataStatus.coordinate_evaluation_ready,
  true,
  'Coordinate evaluation needs scalp-node-table or SimNIBS before building browser fixtures.',
);

// 1. Compatible AL + AR 35 mm radius search layout + second layout from strict_area library
console.log('[1/6] Ensuring AL,AR 35 mm radius layout...');
const radiusRequest = { region_count: 2, radius_mm: 35, mode: 'preset', mask_codes: ['AL', 'AR'] };
const radiusJob = await runJob('local-compute', radiusRequest, 240000);
const radiusRecordId = radiusJob.key;

const library = (await api('/api/local-compute/library')).records;
const secondRecord =
  library.find(
    (row) =>
      row.id !== radiusRecordId &&
      row.dataset_id === 'strict_area' &&
      row.status === 'completed' &&
      row.mode === 'whole_scalp_free' &&
      row.area_cap_cm2 === 120 &&
      row.region_count === 2,
  ) ??
  library.find((row) => row.id !== radiusRecordId && row.dataset_id === 'strict_area' && row.status === 'completed');
assert.ok(secondRecord, 'Expected at least one completed strict_area layout in library.');

// 2. 63-electrode edited copy (disabling E1 / slot 0) on AL,AR 35 mm layout
console.log('[2/6] Ensuring 63-electrode edited record...');
const preparedEditor = await runJob('electrode-editor', { action: 'prepare', parent_id: radiusRecordId }, 60000);
const slots = preparedEditor.result.slots.map((slot, index) => ({
  slot: slot.slot,
  enabled: index !== 0,
  vertex_index: slot.vertex_index,
}));
const editorJob = await runJob(
  'electrode-editor',
  { action: 'evaluate', parent_id: radiusRecordId, slots },
  240000,
);
const editorRecordKey = editorJob.key;

// 3. Golden 64-electrode coordinate evaluation request (named 'Native FEM integration fixture')
console.log('[3/6] Ensuring golden 64-electrode coordinate evaluation...');
const robustnessFixtureDir = resolve(import.meta.dirname, '../../tests/service/fixtures/robustness');
const noiseSeedsInput = JSON.parse(await readFile(join(robustnessFixtureDir, 'noise_seeds-input.json'), 'utf8'));
const goldenRequest = {
  action: 'evaluate',
  design: {
    schema: 'eeg-electrode-design/1',
    coordinate_system: 'ernie_native_mm',
    unit: 'mm',
    name: 'Native FEM integration fixture',
    xyz_mm: noiseSeedsInput.design.xyz_mm,
    region_indices: noiseSeedsInput.design.region_indices,
  },
  radius_mm: 6,
  seed: 42,
};
const goldenRequestPath = join(targetDir, 'golden-design-request.json');
await writeFile(goldenRequestPath, JSON.stringify(goldenRequest, null, 2) + '\n', { mode: 0o600 });
const goldenJob = await runJob('design-evaluation', goldenRequest, 300000);

// 4. All 8 robustness study cases (2 noise_seeds + 6 grid_displacements)
console.log('[4/6] Ensuring all 8 robustness study cases...');
const caseRequests = JSON.parse(await readFile(join(robustnessFixtureDir, 'case-requests.json'), 'utf8'));
const robustnessKeys = [];
for (const protocol of ['noise_seeds', 'grid_displacements']) {
  for (const req of caseRequests[protocol]) {
    const done = await runJob('design-evaluation', req, 300000);
    robustnessKeys.push(done.key);
  }
}

// 5. v1 multi-source signal simulation on AL,AR 35 mm layout
console.log('[5/6] Ensuring v1 signal simulation...');
const v1Request = {
  record_id: radiusRecordId,
  brain_region: 'frontal',
  waveform: 'burst',
  artifact_scale: 1,
  seed: 2026,
};
const v1Job = await runJob('source-reception', v1Request, 180000);
const v1FixturePath = join(targetDir, 'v1-signal-result.json');
await writeFile(v1FixturePath, JSON.stringify(v1Job.result, null, 2) + '\n', { mode: 0o600 });

// 6. Optional v2 single-source signal simulation & research delivery when SimNIBS runtime is present
let v2FixturePath = null;
let olderDeliveryPath = null;
if (!skipV2 && dataStatus.direct_fem_available) {
  console.log('[6/6] SimNIBS runtime detected; ensuring v2 signal simulation & delivery fixture...');
  const v2Request = {
    record_id: radiusRecordId,
    mode: 'single_source',
    source_index: 2,
    region_definition: 'dk40-six-roi-v1',
    waveform: 'burst',
    artifact_scale: 1,
    seed: 2026,
  };
  const v2Job = await runJob('source-reception', v2Request, 600000);
  v2FixturePath = join(targetDir, 'v2-signal-result.json');
  await writeFile(v2FixturePath, JSON.stringify(v2Job.result, null, 2) + '\n', { mode: 0o600 });

  const created = await api('/api/projects', {
    method: 'POST',
    body: { title: 'Browser fixture baseline delivery', owner_name: 'Fixture builder' },
  });
  let project = created.project;
  for (const entry of [
    { kind: 'layout', record_id: radiusRecordId },
    { kind: 'editor', record_id: editorRecordKey },
    { kind: 'source', receipt_id: v2Job.id },
  ]) {
    const updated = await api(`/api/projects/${project.id}/entries`, {
      method: 'POST',
      body: { revision: project.revision, ...entry },
    });
    project = updated.project;
  }
  const deliveryRes = await fetch(`${base}/api/projects/${project.id}/export`, {
    headers: { Cookie: service.cookie },
  });
  assert.ok(deliveryRes.ok, `Export delivery failed: ${deliveryRes.status}`);
  olderDeliveryPath = join(targetDir, 'baseline-research-delivery.json');
  await writeFile(olderDeliveryPath, Buffer.from(await deliveryRes.arrayBuffer()), { mode: 0o600 });
} else {
  console.log('[6/6] Skipping v2 signal simulation (table-only runtime or --skip-v2).');
}

const summary = {
  schema: 'eeglayoutlab-browser-fixtures/1',
  created_at: new Date().toISOString(),
  radius_record_id: radiusRecordId,
  second_layout_id: secondRecord.id,
  editor_record_key: editorRecordKey,
  golden_design_key: goldenJob.key,
  golden_request_path: goldenRequestPath,
  robustness_case_keys: robustnessKeys,
  v1_signal_key: v1Job.key,
  v1_signal_fixture_path: v1FixturePath,
  v2_signal_fixture_path: v2FixturePath,
  older_delivery_path: olderDeliveryPath,
};
const summaryPath = join(targetDir, 'fixtures.json');
await writeFile(summaryPath, JSON.stringify(summary, null, 2) + '\n', { mode: 0o600 });

const envLines = [
  `export EEG_LAYOUT_ID=${JSON.stringify(radiusRecordId)}`,
  `export EEG_SECOND_LAYOUT_ID=${JSON.stringify(secondRecord.id)}`,
  `export EEG_EDITOR_RECORD_KEY=${JSON.stringify(editorRecordKey)}`,
  `export EEG_GOLDEN_REQUEST=${JSON.stringify(goldenRequestPath)}`,
  `export EEG_SIGNAL_V1_FIXTURE=${JSON.stringify(v1FixturePath)}`,
];
if (v2FixturePath) envLines.push(`export EEG_SIGNAL_FIXTURE=${JSON.stringify(v2FixturePath)}`);
if (olderDeliveryPath) envLines.push(`export EEG_OLDER_DELIVERY=${JSON.stringify(olderDeliveryPath)}`);
await writeFile(join(targetDir, 'fixtures.env'), envLines.join('\n') + '\n', { mode: 0o600 });

console.log(JSON.stringify({ fixtures: summaryPath, ...summary }, null, 2));
