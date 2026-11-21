import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { createHash } from 'node:crypto';
import { SourceReceptionService } from '../server/source-reception-server.mjs';
import {
  comparisonNotes,
  parseDesign,
  designCSV,
  qualification,
  decisionMarkdown,
  validateDesign,
  decisionHref,
  parseDecisionThresholds,
  jointDecisionThresholds,
  decisionCriteriaSummary,
} from '../lib/design-decision.ts';
import { assessment } from '../lib/lab-workflow.ts';
import {
  DesignEvaluationService,
  normalizeDesignRequest,
  validateDesignResult,
} from './design-evaluation-server.mjs';
const design = {
  schema: 'eeg-electrode-design/1',
  coordinate_system: 'ernie_native_mm',
  unit: 'mm',
  name: 'test',
  xyz_mm: Array.from({ length: 64 }, (_, i) => [
    (i % 8) * 6,
    Math.floor(i / 8) * 6,
    0,
  ]),
  region_indices: Array.from({ length: 64 }, (_, i) => Number(i >= 32)),
};
const request = { action: 'evaluate', design, radius_mm: 6, seed: 42 };
const baselineResult = () => ({
  schema: 'design-evaluation/1',
  status: 'completed',
  request,
  forward_mode: 'cached_fem',
  nominal: {
    field_relative: 1,
    field_absolute: 0.9,
    reference_field_absolute: 0.9,
    sensitivity_tail: 1,
    localization_relative: 1,
    median_mm: 10,
    p90_mm: 20,
    reference_median_mm: 10,
    reference_p90_mm: 20,
  },
  projection_max_mm: 0,
  evaluated_xyz_mm: design.xyz_mm,
  provenance: { candidate_count: 64 },
  trials: [],
});

void test('coordinate round trip preserves all coordinates, order, frame and labels', () => {
  assert.deepEqual(parseDesign(JSON.stringify(design)), design);
  assert.deepEqual(parseDesign(designCSV(design), 'test'), { ...design, electrode_names: Array.from({ length: 64 }, (_, i) => `E${i + 1}`) });
  assert.deepEqual(normalizeDesignRequest(request), request);
});

void test('method round trip preserves all independent decision thresholds and both records', () => {
  const t = { mode: 'custom', field: 68, sensitivity: 30, localization: null, p90_mm: 20 };
  const href = decisionHref(['a', 'b'], t),
    q = new URL(href, 'http://localhost').searchParams;
  assert.deepEqual(parseDecisionThresholds(q), t);
  assert.equal(q.get('a'), 'a');
  assert.equal(q.get('b'), 'b');
  assert.deepEqual(
    parseDecisionThresholds(new URLSearchParams('ar=0&sensitivity=NaN&p90=-1')),
    { mode: 'custom', field: 90, sensitivity: null, localization: null, p90_mm: null },
  );
});

void test('plain comparison links use the same three-metric decision as the overview', () => {
  const record = { metrics: { field_relative: 0.9231, sensitivity_tail: 0.4666, localization_relative: 0.7405, p90_mm: 20 } };
  const thresholds = parseDecisionThresholds(new URLSearchParams('ar=90'));
  assert.deepEqual(thresholds, jointDecisionThresholds(90));
  assert.equal(assessment(record.metrics, 90).state, 'fail');
  assert.equal(qualification(record, thresholds).state, 'fail');
  assert.equal(qualification(record, thresholds).failed.length, 2);
  assert.equal(qualification(record, { ...thresholds, sensitivity: null, localization: null }).failed.length, 2);
  assert.match(decisionCriteriaSummary(thresholds), /均不低于90%/);
  assert.deepEqual(parseDecisionThresholds(new URL(decisionHref(['a'], thresholds), 'http://localhost').searchParams), thresholds);
  assert.deepEqual(parseDecisionThresholds(new URLSearchParams('ar=1')), jointDecisionThresholds(90));
  assert.equal(parseDecisionThresholds(new URLSearchParams('ar=1&thresholdMode=custom')).field, 1);
});

void test('custom reconstruction-only requirements and legacy independent limits survive reload', () => {
  const thresholds = { mode: 'custom', field: 90, sensitivity: null, localization: null, p90_mm: null };
  const q = new URL(decisionHref(['a'], thresholds), 'http://localhost').searchParams;
  assert.deepEqual(parseDecisionThresholds(q), thresholds);
  assert.match(decisionCriteriaSummary(thresholds), /^仅检查/);
  assert.equal(qualification({ metrics: { field_relative: 0.95, sensitivity_tail: 0.1, localization_relative: 0.2 } }, thresholds).state, 'pass');
  assert.deepEqual(parseDecisionThresholds(new URLSearchParams('ar=68&sensitivity=30&p90=20')), { mode: 'custom', field: 68, sensitivity: 30, localization: null, p90_mm: 20 });
});
void test('input rejects unknown frames, blank CSV numbers, duplicates and invalid labels', () => {
  assert.throws(() => validateDesign({ ...design, unit: 'm' }));
  assert.throws(() =>
    parseDesign(designCSV(design).replace('E1,0,0,0,0', 'E1,0,,0,0')),
  );
  assert.throws(() =>
    normalizeDesignRequest({
      ...request,
      design: { ...design, xyz_mm: Array(64).fill([0, 0, 0]) },
    }),
  );
  assert.throws(() =>
    normalizeDesignRequest({
      ...request,
      design: { ...design, region_indices: Array(64).fill(9) },
    }),
  );
  assert.throws(() => normalizeDesignRequest({ ...request, seed: -1 }));
});
void test('thresholds preserve missing and negative values, and support independent physical units', () => {
  const record = {
    metrics: {
      field_relative: 0.8,
      sensitivity_tail: 0.2,
      localization_relative: 0.3,
      p90_mm: 25,
    },
  };
  assert.equal(
    qualification(record, {
      field: 80,
      sensitivity: null,
      localization: null,
      p90_mm: 30,
    }).state,
    'pass',
  );
  assert.equal(
    qualification(record, {
      field: 80,
      sensitivity: 50,
      localization: null,
      p90_mm: 20,
    }).failed.length,
    2,
  );
  assert.equal(
    qualification({ metrics: { field_relative: null } }, { field: 1 }).state,
    'missing',
  );
  assert.equal(
    qualification(
      { metrics: { field_relative: -0.1 } },
      { field: 1, sensitivity: null, localization: null, p90_mm: null },
    ).state,
    'fail',
  );
});
void test('comparison blocks protocol mixing and reports unmatched actual area', () => {
  const a = {
    dataset_id: 'strict_area',
    area_cap_cm2: 60,
    spacing_mm: 4,
    geometry: { union_area_cm2: 60 },
    provenance: { sha256: 'a' },
  };
  assert.deepEqual(comparisonNotes([a, a]), []);
  assert.ok(
    comparisonNotes([a, { ...a, dataset_id: 'cache' }]).some((s) =>
      s.includes('协议不同'),
    ),
  );
  assert.ok(
    comparisonNotes([a, { ...a, geometry: { union_area_cm2: 50 } }]).some((s) =>
      s.includes('99%'),
    ),
  );
});
void test('report retains negative scores, original provenance and independent stage scope', () => {
  const r = {
    id: 'x',
    label: 'layout',
    dataset_id: 'strict_area',
    region_count: 2,
    provenance: { sha256: 'a' },
    metrics: { field_relative: -0.1 },
  };
  const report = decisionMarkdown([r], {
    field: 90,
    sensitivity: null,
    localization: null,
    p90_mm: null,
  });
  assert.ok(report.includes('-10.00%'));
  assert.ok(report.includes('512独立源复评'));
  assert.ok(report.includes('"sha256": "a"'));
});
void test('result validator rejects a switched request or displaced nominal coordinates', () => {
  validateDesignResult(baselineResult(), request);
  assert.throws(() =>
    validateDesignResult(
      { ...baselineResult(), request: { ...request, seed: 9 } },
      request,
    ),
  );
  assert.throws(() =>
    validateDesignResult(
      {
        ...baselineResult(),
        evaluated_xyz_mm: design.xyz_mm.map((p) => [p[0] + 3, p[1], p[2]]),
      },
      request,
    ),
  );
  const headRequest = { ...request, head_id: 'ixi002' };
  validateDesignResult({ ...baselineResult(), request: headRequest, forward_mode: 'head_scalp_node_table' }, headRequest);
  for (const forward_mode of ['cached_fem', 'direct_fem', 'scalp_node_table'])
    assert.throws(() => validateDesignResult({ ...baselineResult(), request: headRequest, forward_mode }, headRequest), /身份错误/);
  assert.throws(() => validateDesignResult({ ...baselineResult(), forward_mode: 'head_scalp_node_table' }, request), /身份错误/);
  assert.throws(() => validateDesignResult({ ...baselineResult(), forward_mode: 'unknown' }, request), /身份错误/);
});

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'eeg-design-tests-'));
  const queue = {
    root,
    python: 'python3',
    active: null,
    submitting: false,
    sources: {},
  };
  const children = [];
  let version = 1;
  const service = new DesignEvaluationService(queue, {
    timeoutMs: 3000,
    context: async (request) => ({
      identity: { version },
      key: createHash('sha256')
        .update(JSON.stringify({ request, version }))
        .digest('hex'),
    }),
    spawnProcess: () => {
      const child = new EventEmitter();
      child.stdin = new PassThrough();
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      child.kill = () => true;
      children.push(child);
      return child;
    },
  });
  queue.designTests = service;
  return { queue, service, children, change: () => version++ };
}
async function done(service) {
  for (let i = 0; i < 100; i++) {
    if (!service.active) return;
    await new Promise((r) => setTimeout(r, 10));
  }
  assert.fail('job did not finish');
}
void test('worker results cache by exact inputs and do not consume another worker slot on hit', async () => {
  const { service, children, queue, change } = await fixture();
  let release;
  try {
    const first = await service.submit(request);
    assert.equal(first.job.status, 'running');
    children[0].stdout.write(
      JSON.stringify({ type: 'result', result: baselineResult() }) + '\n',
    );
    children[0].emit('close', 0);
    await done(service);
    release = queue.executionSlot.acquire('other');
    const cached = await service.submit(request);
    assert.equal(cached.job.cached, true);
    assert.equal(children.length, 1);
    change();
    const busy = await service.submit(request);
    assert.equal(busy.busy, true);
  } finally {
    release?.();
    service.dispose();
  }
});
void test('cancel keeps shared slot until process close and never creates a success cache', async () => {
  const { service, children } = await fixture();
  try {
    const first = await service.submit(request);
    service.cancel(first.job.id);
    assert.equal(service.active.status, 'cancelling');
    assert.equal((await service.submit({ ...request, seed: 43 })).busy, true);
    children[0].emit('close', 0);
    await done(service);
    assert.equal(service.jobs.get(first.job.id).result, null);
  } finally {
    service.dispose();
  }
});

void test('shutdown during input validation cannot start a late worker', async () => {
  const { service, children } = await fixture();
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  service.contextOverride = async () => {
    await pending;
    return { identity: {}, key: 'a'.repeat(64) };
  };
  const submission = service.submit(request);
  service.dispose();
  release();
  await assert.rejects(submission, /服务正在重启/);
  assert.equal(children.length, 0);
  assert.equal(service.active, null);
  assert.equal(service.submitting, false);
});

void test('missing cache identities and different anatomical domains are never silent matches', () => {
  const a = { dataset_id: 'cache', provenance: {}, mode: 'whole_surface' };
  assert.ok(comparisonNotes([a, a]).some((s) => s.includes('身份未匹配')));
  assert.ok(
    comparisonNotes([a, { ...a, mode: 'low_hair' }]).some((s) =>
      s.includes('位置范围不同'),
    ),
  );
});

void test('corrupt perturbation coordinates, labels or derived spacing are rejected', () => {
  const req = { ...request, action: 'perturb' };
  const result = {
    ...baselineResult(),
    request: req,
    trials: Array.from({ length: 4 }, (_, index) => ({
      index,
      status: 'completed',
      xyz_mm: design.xyz_mm,
      requested_xyz_mm: design.xyz_mm,
      region_indices: design.region_indices,
      actual_max_mm: 0,
      actual_mean_mm: 0,
      candidate_bank_indices: Array.from({ length: 64 }, (_, i) => i),
      unchanged_fraction: 1,
      minimum_chord_distance_mm: 6,
      target_error_max_mm: 0,
      field_relative: 1,
      fixed_estimator_field_relative: 1,
    })),
  };
  validateDesignResult(result, req);
  for (const change of [
    { xyz_mm: [] },
    { region_indices: Array(64).fill(0) },
    { minimum_chord_distance_mm: undefined },
    { actual_max_mm: 5 },
    { actual_mean_mm: 5 },
    { candidate_bank_indices: Array(64).fill(0) },
    { candidate_bank_indices: Array.from({ length: 64 }, (_, i) => i + 1) },
  ]) {
    const bad = structuredClone(result);
    Object.assign(bad.trials[0], change);
    assert.throws(() => validateDesignResult(bad, req));
  }
});

void test('source, scalp and manifest bytes all invalidate the real context identity', async () => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-design-identity-'));
  const digest = (x) => createHash('sha256').update(x).digest('hex');
  const pointer = {
    path: 'results/v2/bank/runs/r/batches/b/bank.npz',
    candidates: 'data/candidates.npz',
    report: 'data/report.json',
    sha256: digest('bank'),
  };
  const files = {
    'results/v2/current_multiregion_bank.json': JSON.stringify(pointer),
    'results/v2/current_surface_admissibility.json': JSON.stringify({ path: 'data/admission.npz', sha256: digest('mask'), geometry_sha256: digest('candidates'), schema_version: 'native-external-exposure/1' }),
    'data/admission.npz': 'mask',
    [pointer.path]: 'bank',
    [pointer.candidates]: 'candidates',
    [pointer.report]: JSON.stringify({
      candidate_sha256: digest('candidates'),
    }),
    'results/v2/bank/runs/r/run_manifest.json': JSON.stringify({
      source_inputs: 'data/sources.npz',
    }),
    'configs/ernie_fem_point_pilot.json': JSON.stringify({
      mesh_path: 'data/head.msh',
      external_node_mapping_path: 'data/scalp/mapping.npy',
    }),
    'data/head.msh': 'mesh',
    'data/scalp/mapping.npy': 'mapping',
    'data/scalp/external_scalp_vertices_m.npy': 'vertices',
    'data/scalp/external_scalp_triangles.npy': 'triangles',
    'data/sources.npz': 'sources',
  };
  for (const file of [
    'src/compact_eeg/workflows/__init__.py',
    'src/compact_eeg/workflows/paths.py',
    'src/compact_eeg/workflows/design_evaluation.py',
    'src/compact_eeg/workflows/head_model.py',
    'src/compact_eeg/workflows/reception_forward_provider.py',
    'src/compact_eeg/workflows/shared_native_forward.py',
    'src/compact_eeg/workflows/scalp_node_table.py',
    'scripts/design_evaluation.py',
    'scripts/inspect_ernie_cortical_forward.py',
    'src/compact_eeg/cortical_fem.py',
    'src/compact_eeg/surface_admissibility.py',
    'src/compact_eeg/layout_search_metrics.py',
    'src/compact_eeg/noise_models.py',
    'src/compact_eeg/workflows/head_package.py',
    'src/compact_eeg/metrics.py',
    'src/compact_eeg/prototype_localization.py',
    'src/compact_eeg/inverse_pilot.py',
  ])
    files[file] = 'code';
  for (const [path, body] of Object.entries(files)) {
    await mkdir(dirname(join(root, path)), { recursive: true });
    await writeFile(join(root, path), body);
  }
  const service = new DesignEvaluationService({ root, python: 'python3' });
  const source = new SourceReceptionService({ root, python: 'python3' });
  assert.deepEqual(await source.nativeContext(request), await service.context(request));
  source.dispose();
  let previous = (await service.context(request)).key;
  for (const path of [
    'src/compact_eeg/workflows/design_evaluation.py',
    'src/compact_eeg/workflows/head_model.py',
    'src/compact_eeg/workflows/reception_forward_provider.py',
    'src/compact_eeg/workflows/shared_native_forward.py',
    'src/compact_eeg/workflows/scalp_node_table.py',
    'src/compact_eeg/noise_models.py',
    'src/compact_eeg/workflows/head_package.py',
    'data/sources.npz',
    'data/scalp/external_scalp_vertices_m.npy',
    'data/scalp/external_scalp_triangles.npy',
  ]) {
    await writeFile(join(root, path), 'changed');
    const current = (await service.context(request)).key;
    assert.notEqual(current, previous);
    previous = current;
  }
  await writeFile(join(root, 'data/admission.npz'), 'changed mask');
  await assert.rejects(() => service.context(request), /筛选/);
  await writeFile(join(root, 'results/v2/current_surface_admissibility.json'), JSON.stringify({ path: 'data/admission.npz', sha256: digest('changed mask'), geometry_sha256: digest('candidates'), schema_version: 'native-external-exposure/2' }));
  previous = (await service.context(request)).key;
  // A published scalp-node table enters the identity: pointer, manifest, index and row bytes.
  const tableDir = 'results/v2/scalp_node_table/' + 't'.repeat(64);
  const tablePointer = (manifest) => JSON.stringify({ schema: 'scalp-node-superposition/1', table_id: 't'.repeat(64), manifest_path: tableDir + '/manifest.json', manifest_sha256: digest(manifest) });
  for (const [name, body] of [['manifest.json', 'manifest'], ['index.npz', 'index'], ['rows.npy', 'rows']]) {
    await mkdir(join(root, tableDir), { recursive: true });
    await writeFile(join(root, tableDir, name), body);
  }
  await writeFile(join(root, 'results/v2/current_scalp_node_table.json'), tablePointer('manifest'));
  let current = (await service.context(request)).key;
  assert.notEqual(current, previous);
  previous = current;
  await writeFile(join(root, tableDir, 'rows.npy'), 'changed rows');
  current = (await service.context(request)).key;
  assert.notEqual(current, previous);
  // A conductivity scenario adds its definition and its own table only when requested.
  await writeFile(join(root, tableDir, 'manifest.json'), 'manifest');
  await writeFile(join(root, tableDir, 'rows.npy'), 'rows');
  const nominalKey = (await service.context(request)).key;
  const scenarioRequest = { ...request, conductivity_scenario: 'skull_x2' };
  await assert.rejects(() => service.context(scenarioRequest), /尚未预计算/);
  // Without the nominal table the worker would solve FEM before rejecting a scenario.
  await rm(join(root, 'results/v2/current_scalp_node_table.json'));
  await assert.rejects(() => service.context(scenarioRequest), /名义头皮节点表/);
  await writeFile(join(root, 'results/v2/current_scalp_node_table.json'), tablePointer('manifest'));
  const scenarioDir = 'results/v2/scalp_node_table_scenarios/skull_x2/' + 's'.repeat(64);
  await mkdir(join(root, scenarioDir), { recursive: true });
  for (const [name, body] of [['manifest.json', 'scenario manifest'], ['index.npz', 'scenario index'], ['rows.npy', 'scenario rows']])
    await writeFile(join(root, scenarioDir, name), body);
  await writeFile(join(root, 'configs/conductivity_scenarios.json'), 'scenarios');
  await writeFile(join(root, 'results/v2/scalp_node_table_scenarios/skull_x2/current.json'), JSON.stringify({ schema: 'scalp-node-superposition/1', table_id: 's'.repeat(64), manifest_path: scenarioDir + '/manifest.json', manifest_sha256: digest('scenario manifest') }));
  assert.equal((await service.context(request)).key, nominalKey);
  previous = (await service.context(scenarioRequest)).key;
  for (const path of ['configs/conductivity_scenarios.json', scenarioDir + '/rows.npy', scenarioDir + '/index.npz']) {
    await writeFile(join(root, path), 'changed');
    current = (await service.context(scenarioRequest)).key;
    assert.notEqual(current, previous);
    previous = current;
  }
  assert.equal((await service.context(request)).key, nominalKey);
  await writeFile(join(root, scenarioDir, 'manifest.json'), 'changed scenario manifest');
  await assert.rejects(() => service.context(scenarioRequest), /电导率情景头皮节点表/);
  await writeFile(join(root, scenarioDir, 'manifest.json'), 'scenario manifest');
  // A head package adds its package files and its own table only when requested.
  const headRequest = { ...request, head_id: 'ixi002' };
  await assert.rejects(() => service.context(headRequest), /尚未预计算/);
  const head = 'results/v2/heads/ixi002', headTable = head + '/table/' + 'h'.repeat(64);
  await mkdir(join(root, headTable), { recursive: true });
  const headFiles = ['package.json', 'scalp.npz', 'admissibility.npz', 'sources.npz', 'mapping.npz'];
  for (const name of headFiles) await writeFile(join(root, head, name), name);
  for (const [name, body] of [['manifest.json', 'head manifest'], ['index.npz', 'head index'], ['rows.npy', 'head rows']])
    await writeFile(join(root, headTable, name), body);
  await writeFile(join(root, head, 'table.json'), JSON.stringify({ schema: 'scalp-node-superposition/1', table_id: 'h'.repeat(64), manifest_path: headTable + '/manifest.json', manifest_sha256: digest('head manifest') }));
  assert.equal((await service.context(request)).key, nominalKey);
  previous = (await service.context(headRequest)).key;
  for (const path of [...headFiles.map((name) => head + '/' + name), headTable + '/rows.npy', headTable + '/index.npz']) {
    await writeFile(join(root, path), 'changed');
    current = (await service.context(headRequest)).key;
    assert.notEqual(current, previous);
    previous = current;
  }
  assert.equal((await service.context(request)).key, nominalKey);
  await writeFile(join(root, headTable, 'manifest.json'), 'changed head manifest');
  await assert.rejects(() => service.context(headRequest), /头模头皮节点表/);
  await writeFile(join(root, tableDir, 'manifest.json'), 'changed manifest');
  await assert.rejects(() => service.context(request), /头皮节点表/);
  service.dispose();
});

void test('head listing offers only complete plain package directories contained in the project', async () => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-design-heads-')),
    outside = await mkdtemp(join(tmpdir(), 'eeg-design-heads-outside-'));
  const digest = (x) => createHash('sha256').update(x).digest('hex');
  const write = async (path, body) => {
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, body);
  };
  const headPackage = async (base, head_id, { manifest = 'manifest', skip = [] } = {}) => {
    const table = `results/v2/heads/${head_id}/table/${'h'.repeat(64)}`;
    const files = {
      'package.json': JSON.stringify({ head_id, dataset: { name: 'IXI', subject: head_id } }),
      'scalp.npz': 'scalp', 'admissibility.npz': 'mask', 'sources.npz': 'sources', 'mapping.npz': 'mapping',
      'table.json': JSON.stringify({ manifest_path: table + '/manifest.json', manifest_sha256: digest('manifest') }),
    };
    for (const [name, body] of Object.entries(files)) if (!skip.includes(name)) await write(join(base, name), body);
    for (const [name, body] of [['manifest.json', manifest], ['index.npz', 'index'], ['rows.npy', 'rows']])
      if (!skip.includes(name)) await write(join(base, 'table', 'h'.repeat(64), name), body);
  };
  const heads = join(root, 'results/v2/heads');
  const service = new DesignEvaluationService({ root, python: 'python3' });
  assert.deepEqual(await service.heads(), []);
  await headPackage(join(heads, 'ixi002'), 'ixi002');
  await headPackage(join(heads, 'ixi012'), 'ixi012', { skip: ['mapping.npz'] });
  await headPackage(join(heads, 'ixi013'), 'ixi013', { skip: ['rows.npy'] });
  await headPackage(join(heads, 'ixi014'), 'ixi014', { manifest: 'changed manifest' });
  await headPackage(join(outside, 'ext1'), 'ext1');
  await symlink(join(outside, 'ext1'), join(heads, 'ext1'));
  await headPackage(join(heads, 'ext2'), 'ext2');
  await rm(join(heads, 'ext2', 'scalp.npz'));
  await write(join(outside, 'scalp.npz'), 'scalp');
  await symlink(join(outside, 'scalp.npz'), join(heads, 'ext2', 'scalp.npz'));
  await write(join(heads, 'notes'), 'not a package');
  assert.deepEqual(await service.heads(), [{ head_id: 'ixi002', dataset: 'IXI', subject: 'ixi002' }]);
  service.dispose();
  await rm(root, { recursive: true, force: true });
  await rm(outside, { recursive: true, force: true });
});
