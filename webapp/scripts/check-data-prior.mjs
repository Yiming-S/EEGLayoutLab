import test from 'node:test';
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { DATA_PRIOR_FILES, dataPriorFromFile, dataPriorLabel, normalizeDataPrior } from '../contracts/scientific-options.mjs';
import { DesignEvaluationService, normalizeDesignRequest } from '../server/design-evaluation-server.mjs';
import { LocalComputeQueue, normalizeRequest } from '../server/local-compute-server.mjs';
import { assertIndependentNoiseParent } from '../server/reception-v2-support.mjs';
import { designSubmission, restoreDesignEvaluation } from '../lib/design-decision.ts';
import { dataPriorParam, parseDataPriorParam, readDataPriorFile } from '../lib/data-prior.ts';
import { canSimulateRecord } from '../lib/local-library.ts';
import { requestKey } from '../lib/local-compute.ts';
import { comparisonGroup } from '../lib/pareto.ts';
import { localizedRecordTitle } from '../lib/i18n/records.ts';
import { designContextRoot } from './helpers/robustness-fixture.mjs';

const prior = { region_gain: [1.037, 2.829, 0.09946, 1.344, 0.4122, 1.072, 0.09946], rho: 0.2, length_mm: 20 };
const independent = { ...prior, rho: 0, length_mm: null };
const design = { schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm', name: 'test',
  xyz_mm: Array.from({ length: 64 }, (_, i) => [(i % 8) * 6, Math.floor(i / 8) * 6, 0]), region_indices: Array.from({ length: 64 }, (_, i) => Number(i >= 32)) };
const request = { action: 'evaluate', design, radius_mm: 6, seed: 42 };
const spatial = { kind: 'spatial', rho: 0.5, length_mm: 20 };

/** An eeg-data-prior/1 file with the fields the page reads (src/compact_eeg/workflows/data_prior.py). */
const priorFile = (overrides = {}) => ({
  schema: 'eeg-data-prior/1', id: 'a'.repeat(16), request: prior,
  regions: ['frontal', 'central', 'parietal', 'occipital', 'temporal_left', 'temporal_right', 'other'],
  fit: { relative_residual: 0.58, uniform_relative_residual: 0.62, data_snr_db: 4.8, fitted_region_gain: prior.region_gain, shrinkage: 1,
    held_out: { summaries: 28, prior_better_count: 28, prior_relative_residual_median: 0.6, uniform_relative_residual_median: 0.63, selected_shrinkage: 1 } },
  channels: ['Fz', 'Cz', 'Pz'], inputs: [{ label: 'a' }, { label: 'b' }, { label: 'c' }], summaries_excluded: [], band_hz: [1, 40], ...overrides,
});

void test('a data prior request value is canonical and replaces the noise model on the Ernie head', () => {
  assert.deepEqual(normalizeDataPrior(prior), prior);
  assert.deepEqual(normalizeDataPrior(independent), independent);
  for (const value of [undefined, null]) assert.equal(normalizeDataPrior(value), undefined);
  for (const change of [{ region_gain: prior.region_gain.slice(1) }, { region_gain: [1.23456, ...prior.region_gain.slice(1)] }, { region_gain: [0, ...prior.region_gain.slice(1)] },
    { rho: 0.255 }, { rho: 0.99 }, { rho: 0, length_mm: 20 }, { length_mm: 25 }, { length_mm: null }, { extra: 1 }])
    assert.throws(() => normalizeDataPrior({ ...prior, ...change }), /数据先验/);
  assert.throws(() => normalizeDataPrior(prior, { noiseModel: spatial }), /噪声模型/);
  assert.throws(() => normalizeDataPrior(prior, { head: 'ixi002' }), /Ernie/);
  assert.equal(dataPriorLabel(prior), '数据先验（噪声ρ=0.2，L=20 mm）');
  assert.equal(dataPriorLabel(independent), '数据先验（噪声独立）');
  assert.equal(dataPriorLabel(undefined), '');
});

void test('prior files are read with their fit, and a prior survives the draft URL', () => {
  assert.deepEqual(dataPriorFromFile(priorFile()), prior);
  assert.throws(() => dataPriorFromFile({ ...priorFile(), schema: 'eeg-covariance-summary/1' }), /eeg-data-prior/);
  assert.throws(() => dataPriorFromFile({ ...priorFile(), regions: ['frontal'] }), /eeg-data-prior/);
  const { value, details } = readDataPriorFile(JSON.stringify(priorFile()));
  assert.deepEqual(value, prior);
  assert.deepEqual([details.summaries, details.channels, details.held_out.better, details.shrinkage], [3, 3, 28, 1]);
  assert.equal(readDataPriorFile(JSON.stringify(priorFile({ fit: { ...priorFile().fit, held_out: null } }))).details.held_out, null);
  assert.throws(() => readDataPriorFile('{'), /JSON/);
  assert.throws(() => readDataPriorFile(JSON.stringify(priorFile({ fit: { ...priorFile().fit, relative_residual: 'x' } }))), /拟合记录/);
  for (const value of [prior, independent]) assert.deepEqual(parseDataPriorParam(dataPriorParam(value)), value);
  assert.equal(dataPriorParam(independent).endsWith(',0,0'), true);
  assert.throws(() => parseDataPriorParam('1,2,3'), /参数/);
  assert.throws(() => parseDataPriorParam(dataPriorParam(prior).replace(',20', ',25')), /长度/);
});

void test('the services accept a prior only without a noise model, and default requests are unchanged', () => {
  assert.deepEqual(normalizeDesignRequest({ ...request, data_prior: prior }).data_prior, prior);
  assert.equal('data_prior' in normalizeDesignRequest(request), false);
  assert.throws(() => normalizeDesignRequest({ ...request, data_prior: prior, noise_model: spatial }), /噪声模型/);
  assert.throws(() => normalizeDesignRequest({ ...request, data_prior: prior, head_id: 'ixi002' }), /Ernie/);
  const search = { region_count: 2, radius_mm: 30, mode: 'whole_surface' };
  assert.deepEqual(normalizeRequest({ ...search, data_prior: prior }), { ...search, data_prior: prior });
  assert.deepEqual(normalizeRequest(search), search);
  assert.throws(() => normalizeRequest({ ...search, data_prior: prior, noise_model: spatial }), /噪声模型/);
  assert.notEqual(requestKey({ ...search, data_prior: prior }), requestKey(search));
  // The decision page sends the prior instead of its noise choice.
  const submitted = designSubmission(design, 'evaluate', 6, 42, spatial, undefined, false, prior);
  assert.deepEqual(submitted.data_prior, prior);
  assert.equal('noise_model' in submitted, false);
  assert.equal('data_prior' in designSubmission(design, 'evaluate', 6, 42), false);
});

void test('saved prior evaluations restore their prior and stay out of signal simulation and grouping with area-prior records', () => {
  const record = { id: 'r'.repeat(64), layout: { xyzMm: design.xyz_mm } };
  const withPrior = { ...request, data_prior: prior };
  const result = { schema: 'design-evaluation/1', status: 'completed', request: withPrior, forward_mode: 'scalp_node_table', projection_max_mm: 0,
    nominal: { field_relative: 0.9, field_absolute: 0.81, reference_field_absolute: 0.9, sensitivity_tail: 0.8, localization_relative: 0.7, median_mm: 5, p90_mm: 12, reference_median_mm: 4, reference_p90_mm: 10 },
    evaluated_xyz_mm: design.xyz_mm, trials: [], provenance: { candidate_count: 100 } };
  const bundle = { schema: 'eeg-reproducibility-bundle/1', record_id: record.id, reproduction: { request: withPrior }, original_record: { result } };
  assert.deepEqual(restoreDesignEvaluation(bundle, record).data_prior, prior);
  const invalid = { ...withPrior, data_prior: { ...prior, rho: 2 } };
  assert.throws(() => restoreDesignEvaluation({ ...bundle, reproduction: { request: invalid }, original_record: { result: { ...result, request: invalid } } }, record), /评价条件/);
  const saved = { status: 'completed', dataset_id: 'cache', compatible: true, layout: { xyzMm: design.xyz_mm }, request: { region_count: 2, radius_mm: 30, mode: 'whole_surface' } };
  assert.equal(canSimulateRecord(saved), true);
  assert.equal(canSimulateRecord({ ...saved, request: { ...saved.request, data_prior: prior } }), false);
  assert.throws(() => assertIndependentNoiseParent({ request: { data_prior: prior } }), /独立噪声/);
  assert.notEqual(comparisonGroup({ ...saved, request: { ...saved.request, data_prior: prior } }), comparisonGroup(saved));
  assert.notEqual(comparisonGroup({ ...saved, request: { ...saved.request, data_prior: prior } }), comparisonGroup({ ...saved, request: { ...saved.request, data_prior: independent } }));
});

void test('the prior modules and atlas enter the computation identity only for requests with a prior', async () => {
  const root = await designContextRoot('eeg-data-prior-identity-');
  const service = new DesignEvaluationService({ root, python: 'python3' });
  const plain = await service.context(request), withPrior = await service.context({ ...request, data_prior: prior });
  for (const path of DATA_PRIOR_FILES) {
    assert.equal(path in plain.identity.digests, false);
    assert.equal(path in withPrior.identity.digests, true);
  }
  await writeFile(join(root, 'src/compact_eeg/workflows/data_prior.py'), 'changed');
  assert.equal((await service.context(request)).key, plain.key);
  assert.notEqual((await service.context({ ...request, data_prior: prior })).key, withPrior.key);
  // The search queue adds the same files to its code identity.
  const queue = { root, getRuntime: () => null, getIdentity: () => ({ 'src/compact_eeg/metrics.py': 'm' }) };
  const search = { region_count: 2, radius_mm: 30, mode: 'whole_surface' };
  const code = (value) => Object.keys(LocalComputeQueue.prototype.identityFor.call(queue, value).identity.code);
  assert.deepEqual(code(search), ['src/compact_eeg/metrics.py']);
  assert.deepEqual(code({ ...search, data_prior: prior }), ['src/compact_eeg/metrics.py', ...DATA_PRIOR_FILES]);
});

void test('record titles name the data prior in both languages', () => {
  const search = { id: 's'.repeat(64), dataset_id: 'cache', status: 'completed', compatible: true, region_count: 2, mode: 'whole_surface', radius_cap_mm: 30,
    request: { region_count: 2, radius_mm: 30, mode: 'whole_surface', data_prior: prior } };
  assert.match(localizedRecordTitle(search, 'zh-CN'), /数据先验（噪声ρ=0.2，L=20 mm）$/);
  assert.match(localizedRecordTitle(search, 'en'), /Data prior \(noise ρ=0.2, L=20 mm\)$/);
  const evaluation = { id: 'e'.repeat(64), dataset_id: 'design_evaluation', status: 'completed', region_count: 2, mode: 'imported_coordinates', label: 'cap',
    evaluation_condition: { data_prior: independent } };
  assert.match(localizedRecordTitle(evaluation, 'en'), /evaluated coordinates · Data prior \(independent noise\)$/);
});
