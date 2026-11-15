import test from 'node:test';
import assert from 'node:assert/strict';
import { projectExperimentAssociations, sourceLayoutAssociation, sourceScenarioSummary, filterProjectExperiments } from '../features/projects/project-experiment-associations.ts';

const layout = (id, key, title = id) => ({ id, record_id: key, kind: 'layout', title, summary: { protocol: 'cache', electrode_count: 64 } });
const source = (id, key, parent, scenario = {}) => ({ id, record_id: key, kind: 'source', title: id, summary: { ...(parent === undefined ? {} : { parent_id: parent }), ...scenario } });
const a = 'a'.repeat(64), b = 'b'.repeat(64), c = 'c'.repeat(64);
const entries = [layout('layout-a', a, 'Named layout A'), layout('layout-a-alias', a, 'Other names for A'), layout('layout-b', b),
  source('signal-a', 'd'.repeat(64), a, { mode: 'single_source', source_index: 0, seed: 0 }),
  source('signal-b', 'e'.repeat(64), b, { mode: 'multi_source', brain_region: 'frontal', seed: 42 }),
  source('unrecorded-parent', 'f'.repeat(64), undefined), source('external-parent', '1'.repeat(64), c),
  { id: 'editor', record_id: a, kind: 'editor', title: 'Edited layout', summary: { parent_id: a } }];
const frozen = value => {
  for (const item of Object.values(value)) if (item && typeof item === 'object') frozen(item);
  return Object.freeze(value);
};
frozen(entries);

void test('project totals distinguish saved name copies from distinct scientific layouts', () => {
  const result = projectExperimentAssociations(entries, 'layout-a');
  assert.equal(result.layoutCopies, 3); assert.equal(result.distinctLayoutCount, 2);
  assert.equal(result.signals.length, 4); assert.equal(result.candidateSignals.length, 1);
  assert.equal(result.candidateSignals[0], entries[3]);
});

void test('every name alias of one scientific key has the same associated signal records', () => {
  const first = projectExperimentAssociations(entries, 'layout-a'), alias = projectExperimentAssociations(entries, 'layout-a-alias');
  assert.equal(first.candidateRecordId, alias.candidateRecordId);
  assert.deepEqual(first.candidateSignals, alias.candidateSignals);
  const parent = sourceLayoutAssociation(entries[3], entries);
  assert.equal(parent.parentId, a);
  assert.deepEqual(parent.layouts.map(entry => entry.title), ['Named layout A', 'Other names for A']);
});

void test('candidate switching updates only the filtered view and preserves all historical entries and scientific identities', () => {
  const before = JSON.stringify(entries);
  assert.deepEqual(filterProjectExperiments(entries, 'candidate-source', 'layout-a'), [entries[3]]);
  assert.deepEqual(filterProjectExperiments(entries, 'candidate-source', 'layout-b'), [entries[4]]);
  assert.deepEqual(filterProjectExperiments(entries, 'all', 'layout-b'), entries);
  assert.equal(JSON.stringify(entries), before);
  assert.equal(filterProjectExperiments(entries, 'candidate-source', 'layout-a')[0].record_id, 'd'.repeat(64));
});

void test('absent and detached candidates never inherit the previously selected layout or an editor parent', () => {
  for (const id of [undefined, null, 'missing', 'editor']) {
    const result = projectExperimentAssociations(entries, id);
    assert.equal(result.candidateRecordId, null); assert.deepEqual(result.candidateSignals, []);
  }
  assert.deepEqual(filterProjectExperiments(entries.filter(entry => entry.id !== 'layout-a'), 'candidate-source', 'layout-a'), []);
});

void test('missing parent metadata stays unrecorded and an external scientific ID is kept without inventing a project title', () => {
  assert.deepEqual(sourceLayoutAssociation(entries[5], entries), { parentId: null, layouts: [] });
  assert.deepEqual(sourceLayoutAssociation(entries[6], entries), { parentId: c, layouts: [] });
  assert.deepEqual(sourceLayoutAssociation({ ...entries[5], summary: { parent_id: '../layout-a', mode: 'single_source', source_index: 0 } }, entries), { parentId: null, layouts: [] });
});

void test('old summaries do not infer a mode, source index, brain region or random seed', () => {
  assert.deepEqual(sourceScenarioSummary(entries[5]), { mode: null, brainRegion: null, brainRegions: null, sourceIndex: null, seed: null });
  const scene = sourceScenarioSummary(source('mode-only', a, a, { mode: 'single_source' }));
  assert.equal(scene.mode, 'single_source'); assert.equal(scene.sourceIndex, null); assert.equal(scene.seed, null);
});

void test('zero source indices and seeds are recorded values, not missing values', () => {
  assert.deepEqual(sourceScenarioSummary(entries[3]), { mode: 'single_source', brainRegion: null, brainRegions: null, sourceIndex: 0, seed: 0 });
  assert.deepEqual(sourceScenarioSummary(entries[4]), { mode: 'multi_source', brainRegion: 'frontal', brainRegions: null, sourceIndex: null, seed: 42 });
});

void test('cross-region request order is preserved and never substituted with calculated-source fields', () => {
  const value = frozen(source('cross-region', a, b, { mode: 'cross_region', brain_regions: ['occipital', 'frontal'], source_indices: [8, 12], source_regions: ['temporal'], seed: 2026 }));
  const before = JSON.stringify(value), summary = sourceScenarioSummary(value);
  assert.deepEqual(summary.brainRegions, ['occipital', 'frontal']);
  assert.equal(summary.sourceIndex, null); assert.equal(summary.brainRegion, null);
  assert.notEqual(summary.brainRegions, value.summary.brain_regions);
  assert.equal(JSON.stringify(value), before);
});

void test('malformed historical field types cannot break the project view or become default values', () => {
  const result = sourceScenarioSummary(source('malformed', a, a, { mode: '', brain_region: 0, brain_regions: [null], source_index: '0', seed: NaN }));
  assert.deepEqual(result, { mode: null, brainRegion: null, brainRegions: null, sourceIndex: null, seed: null });
  assert.equal(sourceScenarioSummary(layout('not-source', a)).mode, null);
});
