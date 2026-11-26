import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { conditionChoices } from '../lib/evaluation-conditions.ts';
import { NOISE_MODEL_PRESETS } from '../contracts/scientific-options.mjs';

const all = { noiseModelId: 'iid', scenarioId: '', robustness: false, dataPrior: null };
const prior = { region_gain: [1, 1, 1, 1, 1, 1, 1], rho: 0, length_mm: null };
const ids = (choices) => choices.noisePresets.map(preset => preset.id);

void test('the condition form offers per action exactly what the contract accepts', () => {
  const search = conditionChoices('search', all);
  assert.deepEqual(ids(search), NOISE_MODEL_PRESETS.filter(preset => preset.search).map(preset => preset.id));
  assert.equal(search.scenarioOffered, false); assert.equal(search.robustnessOffered, false); assert.equal(search.dataPriorOffered, true);
  const evaluate = conditionChoices('evaluate', all);
  assert.deepEqual(ids(evaluate), NOISE_MODEL_PRESETS.map(preset => preset.id));
  assert.equal(evaluate.scenarioOffered, true); assert.equal(evaluate.robustnessAllowed, true); assert.equal(evaluate.dataPriorOffered, true);
  const perturb = conditionChoices('perturb', all);
  assert.deepEqual(ids(perturb), NOISE_MODEL_PRESETS.map(preset => preset.id));
  assert.equal(perturb.scenarioOffered, false); assert.equal(perturb.robustnessOffered, false); assert.equal(perturb.dataPriorOffered, true);
});

void test('combinations the service rejects are not offered together', () => {
  // Cross-session robustness is defined only under the nominal conductivity.
  const scenario = conditionChoices('evaluate', { ...all, scenarioId: 'skull_x2', robustness: true });
  assert.equal(scenario.robustnessOffered, true); assert.equal(scenario.robustnessAllowed, false);
  // A data prior carries its own noise structure.
  assert.equal(conditionChoices('evaluate', { ...all, dataPrior: prior }).noiseLocked, true);
  assert.equal(conditionChoices('search', { ...all, dataPrior: prior }).noiseLocked, true);
  assert.equal(conditionChoices('evaluate', all).noiseLocked, false);
});

void test('study protocols offer the conditions of the requests they send', () => {
  const seeds = conditionChoices('study', { noiseModelId: 'iid', scenarioId: '' }, 'noise_seeds');
  assert.equal(seeds.scenarioOffered, true); assert.equal(seeds.robustnessOffered, false); assert.equal(seeds.dataPriorOffered, false);
  // A heads study maps the design to another head, where conductivity scenarios are undefined.
  assert.equal(conditionChoices('study', { noiseModelId: 'iid', scenarioId: '' }, 'heads').scenarioOffered, false);
  // Grid displacements send the position-offset test.
  assert.equal(conditionChoices('study', { noiseModelId: 'iid', scenarioId: '' }, 'grid_displacements').scenarioOffered, false);
  assert.deepEqual(ids(conditionChoices('study', { noiseModelId: 'iid' }, 'noise_seeds')), NOISE_MODEL_PRESETS.map(preset => preset.id));
});

void test('a page offers only the conditions it manages, and builds no condition form of its own', async () => {
  assert.equal(conditionChoices('evaluate', { noiseModelId: 'iid' }).scenarioOffered, false);
  assert.equal(conditionChoices('evaluate', { noiseModelId: 'iid' }).dataPriorOffered, false);
  for (const file of ['features/design/design-workspace.tsx', 'features/decision/position-evaluation-section.tsx', 'features/robustness/study-draft-section.tsx']) {
    const source = await readFile(file, 'utf8');
    assert.match(source, /<EvaluationConditions /, file);
    assert.doesNotMatch(source, /NOISE_MODEL_PRESETS\.map|CONDUCTIVITY_SCENARIOS\.map|<DataPriorPicker /, file);
  }
  for (const orchestrator of ['features/decision/decision-workspace.tsx', 'features/robustness/robustness-workspace.tsx']) {
    const source = await readFile(orchestrator, 'utf8');
    assert.doesNotMatch(source, /NOISE_MODEL_PRESETS\.map|CONDUCTIVITY_SCENARIOS\.map|<DataPriorPicker /, orchestrator);
  }
});
