import test from 'node:test';
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { DesignEvaluationService, normalizeDesignRequest, validRobustness, validateDesignResult } from '../server/design-evaluation-server.mjs';
import { robustnessSummary } from '../contracts/scientific-options.mjs';
import { designSubmission, restoreDesignEvaluation } from '../lib/design-decision.ts';
import { criticalElectrodes, robustnessRows } from '../lib/design-robustness.ts';
import { designContextRoot, robustnessBlock, stats } from './helpers/robustness-fixture.mjs';

const design = { schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm', name: 'test',
  xyz_mm: Array.from({ length: 64 }, (_, i) => [(i % 8) * 6, Math.floor(i / 8) * 6, 0]), region_indices: Array.from({ length: 64 }, (_, i) => Number(i >= 32)) };
const request = { action: 'evaluate', design, radius_mm: 6, seed: 42 };
const robustRequest = { ...request, robustness: 'standard/1' };
const nominal = { field_relative: 0.9, field_absolute: 0.81, reference_field_absolute: 0.9, sensitivity_tail: 0.8, localization_relative: 0.7,
  median_mm: 5, p90_mm: 12, reference_median_mm: 4, reference_p90_mm: 10 };
const result = (req, robustness) => ({ schema: 'design-evaluation/1', status: 'completed', request: req, forward_mode: 'scalp_node_table', nominal,
  projection_max_mm: 0, evaluated_xyz_mm: design.xyz_mm, trials: [], provenance: { candidate_count: 100 }, ...(robustness ? { robustness } : {}) });

void test('robustness is an evaluate-only option on the nominal Ernie head and leaves default requests unchanged', () => {
  assert.deepEqual(Object.keys(normalizeDesignRequest(request)).sort(), ['action', 'design', 'radius_mm', 'seed']);
  assert.equal(normalizeDesignRequest(robustRequest).robustness, 'standard/1');
  for (const value of [null, false, ''] ) assert.equal('robustness' in normalizeDesignRequest({ ...request, robustness: value }), false);
  assert.throws(() => normalizeDesignRequest({ ...request, robustness: 'standard/2' }), /稳健性协议/);
  assert.throws(() => normalizeDesignRequest({ ...robustRequest, action: 'perturb' }), /网格偏移/);
  assert.throws(() => normalizeDesignRequest({ ...robustRequest, conductivity_scenario: 'skull_x2' }), /电导率情景/);
  assert.throws(() => normalizeDesignRequest({ ...robustRequest, head_id: 'ixi002' }), /其他头模/);
  // The browser builds the same request, and never adds robustness to a perturbation or a scenario.
  assert.equal(designSubmission(design, 'evaluate', 6, 42, undefined, undefined, true).robustness, 'standard/1');
  assert.equal('robustness' in designSubmission(design, 'perturb', 6, 42, undefined, undefined, true), false);
  assert.equal('robustness' in designSubmission(design, 'evaluate', 6, 42, undefined, 'skull_x2', true), false);
  assert.equal('robustness' in designSubmission(design, 'evaluate', 6, 42), false);
});

void test('the result validator requires the block exactly when requested and checks its structure', () => {
  validateDesignResult(result(robustRequest, robustnessBlock()), robustRequest);
  validateDesignResult(result(robustRequest, robustnessBlock({ table: false })), robustRequest);
  validateDesignResult(result(request), request);
  assert.throws(() => validateDesignResult(result(robustRequest), robustRequest), /稳健性/);
  assert.throws(() => validateDesignResult(result(request, robustnessBlock()), request), /稳健性/);
  const broken = [
    b => { b.dropout.single.candidate.pop(); },
    b => { b.dropout.random[1].candidate.p10 = b.dropout.random[1].candidate.median + .01; },
    b => { b.impedance[0].log_sd = 2; },
    b => { b.replacement.levels[0].candidate.rejected = 0; },
    b => { b.replacement.levels[1].reference.fixed_estimator = stats(.9, 16); },
    b => { b.replacement.levels[0].candidate.fixed_estimator.count = 16; },
    b => { b.dropout.random[0].reference.median = Number.NaN; },
    b => { b.replacement = { status: 'unavailable' }; },
  ];
  for (const corrupt of broken) {
    const block = robustnessBlock(); corrupt(block);
    assert.equal(validRobustness(block), false, corrupt.toString());
  }
});

void test('the library summary, the table rows and the critical electrodes come from the same block', () => {
  const block = robustnessBlock(), summary = robustnessSummary(block);
  assert.deepEqual(summary.dropout, { removed: [2, 4, 8], candidate: [.999, .998, .997], reference: [.9993, .9993 - 1e-3, .9993 - 2e-3] });
  assert.deepEqual(summary.replacement.rms_mm, [5, 10]);
  assert.deepEqual(summary.replacement.fixed.reference, [.99, null]);
  assert.equal(robustnessSummary(robustnessBlock({ table: false })).replacement, null);
  const rows = robustnessRows(block);
  assert.equal(rows.length, 3 + 2 + 4);
  assert.match(rows[5].note, /当前布局1次、标准64 0次/);
  assert.equal(rows[7].reference, null);
  const names = Array.from({ length: 64 }, (_, i) => `N${i}`);
  assert.deepEqual(criticalElectrodes(block, names, 3).map(item => item.name), ['N63', 'N62', 'N61']);
});

void test('a saved robustness evaluation restores its option with the inputs', () => {
  const record = { id: 'r'.repeat(64), layout: { xyzMm: design.xyz_mm } };
  const bundle = { schema: 'eeg-reproducibility-bundle/1', record_id: record.id, reproduction: { request: robustRequest },
    original_record: { result: result(robustRequest, robustnessBlock()) } };
  assert.equal(restoreDesignEvaluation(bundle, record).robustness, true);
  const other = { ...bundle, reproduction: { request: { ...robustRequest, robustness: 'standard/9' } }, original_record: { result: result({ ...robustRequest, robustness: 'standard/9' }) } };
  assert.throws(() => restoreDesignEvaluation(other, record), /评价条件/);
});

void test('the robustness module enters the context identity only for requests that use it', async () => {
  const root = await designContextRoot('eeg-robustness-identity-');
  const service = new DesignEvaluationService({ root, python: 'python3' });
  const plain = await service.context(request), robust = await service.context(robustRequest);
  assert.equal('src/compact_eeg/workflows/design_robustness.py' in plain.identity.digests, false);
  assert.equal('src/compact_eeg/workflows/design_robustness.py' in robust.identity.digests, true);
  await writeFile(join(root, 'src/compact_eeg/workflows/design_robustness.py'), 'changed');
  assert.equal((await service.context(request)).key, plain.key);
  assert.notEqual((await service.context(robustRequest)).key, robust.key);
});
