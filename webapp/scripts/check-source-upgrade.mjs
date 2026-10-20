import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { stripTypeScriptTypes } from 'node:module';
import {
  normalizeReceptionRequest,
  validateReceptionResult,
  designReceptionRecord,
} from './reception-v2-support.mjs';
import { describeSearch, experimentBundle } from './experiment-bundle.mjs';
import { areaRecords, radiusRecords } from './local-data-library.mjs';
import { createHash } from 'node:crypto';
import { normalizeDesignRequest } from '../server/design-evaluation-server.mjs';
import { sourceKey } from '../lib/source-reception.ts';
const root = new URL('../../', import.meta.url).pathname;
const fieldSource = stripTypeScriptTypes(
  await readFile(new URL('../lib/source-field.ts', import.meta.url), 'utf8'),
).replace(
  "'./source-reception'",
  JSON.stringify(new URL('../lib/source-reception.ts', import.meta.url).href),
);
const { fieldFrames } = await import(
  'data:text/javascript;base64,' + Buffer.from(fieldSource).toString('base64')
);
const request = {
  record_id: 'a'.repeat(64),
  mode: 'single_source',
  source_index: 2,
  waveform: 'burst',
  artifact_scale: 1,
  seed: 2026,
};
void test('v2 identities separate source modes, preserve v1 keys and exclude AR', () => {
  const r = normalizeReceptionRequest(request);
  assert.equal(sourceKey(r), JSON.stringify(r));
  for (const x of [
    { ...request, ar: 90 },
    { ...request, source_index: 256 },
    { ...request, source_index: -1 },
    { ...request, brain_region: 'frontal' },
    { ...request, mode: 'other' },
  ])
    assert.throws(() => normalizeReceptionRequest(x));
  const v1 = {
    record_id: request.record_id,
    brain_region: 'frontal',
    waveform: 'burst',
    artifact_scale: 1,
    seed: 2026,
  };
  assert.equal(sourceKey(v1), JSON.stringify(v1));
  assert.notEqual(sourceKey(r), sourceKey({ ...r, source_index: 3 }));
});
void test('field display uses both complete previews for a common scale, and common-target residuals', () => {
  const components = (brain, recon) =>
    Object.fromEntries(
      [
        'brain_uv',
        'ecg_uv',
        'eog_uv',
        'noise_uv',
        'reconstructed_brain_uv',
        'reconstructed_ecg_uv',
        'reconstructed_eog_uv',
        'reconstructed_noise_uv',
      ].map((k) => [
        k,
        Array.from({ length: 64 }, () =>
          Array(400).fill(
            k === 'brain_uv'
              ? brain
              : k === 'reconstructed_brain_uv'
                ? recon
                : 0,
          ),
        ),
      ]),
    );
  const result = {
    waveforms: { baseline: components(2, 1), candidate: components(-4, 3) },
  };
  result.waveforms.candidate.brain_uv[63][399] = 9;
  const brain = fieldFrames(result, 'clean', 'brain');
  assert.equal(brain.limit, 9);
  assert.equal(brain.sides[1][0][0], -4);
  assert.equal(brain.target, false);
  const residual = fieldFrames(result, 'clean', 'residual');
  assert.equal(residual.target, true);
  assert.equal(residual.sides[0][0][0], -1);
  assert.equal(residual.sides[1][0][0], 1);
  assert.equal(result.waveforms.candidate.brain_uv[63][399], 9);
});
void test('real area bundle preserves original bytes identity, all coordinates and stored accepted trace', async () => {
  const p = JSON.parse(
    await readFile(root + 'results/v2/current_strict_area_budget_study.json'),
  );
  const bytes = await readFile(root + p.report),
    raw = JSON.parse(bytes);
  const r = areaRecords(raw, { file: p.report, sha256: p.sha256 }).find(
    (r) =>
      r.status === 'completed' && r.region_count === 2 && r.area_cap_cm2 === 60,
  );
  const bundle = await experimentBundle(root, r);
  assert.equal(
    bundle.source.sha256,
    createHash('sha256').update(bytes).digest('hex'),
  );
  assert.deepEqual(bundle.record.layout.xyzMm, r.layout.xyzMm);
  assert.ok(bundle.search.initial);
  assert.ok(bundle.search.final);
  assert.ok(bundle.search.curve.length);
  assert.deepEqual(bundle.original_record, raw);
  assert.equal(
    bundle.search.curve.at(-1).value,
    Math.min(bundle.search.final.field20, bundle.search.final.sensitivity_tail),
  );
});
void test('missing history is explicit and never fabricates zero-score initial state', () => {
  const s = describeSearch(
    { dataset_id: 'offline_radius', provenance: {}, request: null },
    {},
  );
  assert.equal(s.history_status, 'not_available_in_loaded_record');
  assert.equal(s.initial, null);
  assert.deepEqual(s.curve, []);
});
void test('historical field objective keeps its saved trajectory and is not replaced with the tail minimum', async () => {
  const file = 'webapp/public/data/single_head_optimization.json';
  const raw = JSON.parse(await readFile(root + file));
  const record = radiusRecords(raw, { file })[0];
  const b = await experimentBundle(root, record);
  assert.ok(b.search.trace.length > 0);
  assert.equal(b.search.curve[0].value, b.search.initial.objective_score);
  assert.equal(b.search.curve.at(-1).value, b.search.final.objective_score);
  assert.notEqual(
    b.search.curve[0].value,
    Math.min(b.search.initial.field20, b.search.initial.sensitivity_tail),
  );
});
void test('synthetic completed native record resolves evaluated coordinates, not unprojected inputs', async () => {
  // A serialization fixture, not a simulated head or scientific result.
  const fixtureRoot = await mkdtemp(join(tmpdir(), 'eeg-reception-record-'));
  const id = 'a'.repeat(64);
  const digest = (bytes) => createHash('sha256').update(bytes).digest('hex');
  const xyz = Array.from({ length: 64 }, (_, i) => [(i % 8) * 6, Math.floor(i / 8) * 6, 0]);
  const result = {
    schema: 'design-evaluation/1', status: 'completed', forward_mode: 'direct_fem',
    request: { action: 'evaluate', radius_mm: 6, seed: 42, design: {
      schema: 'eeg-electrode-design/1', name: 'synthetic-test', coordinate_system: 'ernie_native_mm', unit: 'mm',
      xyz_mm: xyz, region_indices: xyz.map((_, i) => Number(i >= 32)),
    } },
    nominal: { field_relative: 1, field_absolute: .9, reference_field_absolute: .9, sensitivity_tail: 1,
      localization_relative: 1, median_mm: 10, p90_mm: 20, reference_median_mm: 10, reference_p90_mm: 20 },
    projection_max_mm: 1, evaluated_xyz_mm: xyz.map(([x, y]) => [x, y, 1]),
    provenance: { candidate_count: 64 }, trials: [],
  };
  result.request = normalizeDesignRequest(result.request);
  const report = JSON.stringify({ baseline: { reference_xyz_mm: xyz } });
  try {
    await mkdir(join(fixtureRoot, 'results/v2/design_evaluation_jobs', id), { recursive: true });
    await writeFile(join(fixtureRoot, 'results/v2/reference.json'), report);
    await writeFile(join(fixtureRoot, 'results/v2/current_strict_area_budget_study.json'), JSON.stringify({ report: 'results/v2/reference.json', sha256: digest(report) }));
    await writeFile(join(fixtureRoot, 'results/v2/design_evaluation_jobs', id, 'cache.json'), JSON.stringify({ key: id, result, result_sha256: digest(JSON.stringify(result)) }));
    const r = await designReceptionRecord(fixtureRoot, id);
    assert.deepEqual(r.layout.xyzMm, result.evaluated_xyz_mm);
    assert.notDeepEqual(r.layout.xyzMm, xyz);
    assert.equal(r.layout.xyzMm.length, 64);
    assert.equal(r.provenance.forward_mode, 'direct_fem');
    const invalid = structuredClone(result);
    invalid.request.design.region_indices = Array(64).fill(99);
    await writeFile(join(fixtureRoot, 'results/v2/design_evaluation_jobs', id, 'cache.json'), JSON.stringify({ key: id, result: invalid, result_sha256: digest(JSON.stringify(invalid)) }));
    await assert.rejects(designReceptionRecord(fixtureRoot, id), /区域编号错误/);
  } finally {
    await rm(fixtureRoot, { recursive: true });
  }
});
void test('v2 validator rejects wrong source identity before accepting display data', () => {
  assert.throws(() =>
    validateReceptionResult(
      { schema_version: 'source-reception/1', request },
      normalizeReceptionRequest(request),
      {},
    ),
  );
});
