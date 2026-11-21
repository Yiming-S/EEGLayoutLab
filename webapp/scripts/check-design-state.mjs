import test from 'node:test';
import { NOISE_MODEL_PRESETS, noiseModelId } from '../contracts/scientific-options.mjs';
import assert from 'node:assert/strict';
import { designViewState } from '../features/design/design-state.ts';
import { requestKey } from '../lib/local-compute.ts';
import { comparisonLink, parseAR, REGION_COUNTS } from '../lib/lab-workflow.ts';
import { MASK_NAMES } from '../lib/ui-language.ts';
import { placementChoices, choiceFromSlots } from '../lib/placement-options.ts';
import { createHookHarness } from './helpers/hook-harness.mjs';

const input = { ready: true, error: '', editing: true, hasLayout: false, hasChoice: true, currentStatus: null };
const stateFor = patch => designViewState({ ...input, ...patch });
const request = { region_count: 2, radius_mm: 35, mode: 'whole_surface' };
const source = {
  id: 'a'.repeat(64), dataset_id: 'strict_area', label: 'Unit-test area record', mode: 'whole_scalp_free',
  region_count: 2, area_cap_cm2: 60,
  layout: { xyzMm: Array.from({ length: 64 }, (_, i) => [i * 4, -0, 1e-12]), regionIndices: Array.from({ length: 64 }, (_, i) => i % 2) },
  metrics: { field_relative: .8765432109876543, sensitivity_tail: .75, localization_relative: null, conditional_global: null, p90_mm: 21.23456789012345 },
  geometry: { common_graph_radius_mm: 24.12345678901234, union_area_cm2: 59.87654321098765 },
};
const freeze = object => {
  for (const value of Object.values(object)) if (value && typeof value === 'object') freeze(value);
  return Object.freeze(object);
};
freeze(source);

void test('initial loading and load errors do not invite a computation', () => {
  assert.equal(stateFor({ ready: false }).phase, 'loading');
  const failure = stateFor({ ready: false, error: 'Record unavailable' });
  assert.equal(failure.phase, 'load-error');
  assert.equal(failure.action, null);
});

void test('an area record stays a read-only viewing state until an explicit radius configuration is created', () => {
  const state = stateFor({ editing: false, hasLayout: true, currentStatus: { status: 'running' } });
  assert.equal(state.phase, 'area-record');
  assert.equal(state.action, 'new-radius');
  assert.match(state.title, /面积约束/);
  assert.doesNotMatch(state.detail, /正在搜索|正在计算/);
});

void test('unsubmitted configurations distinguish a complete choice from missing region locations', () => {
  const ready = stateFor({}), incomplete = stateFor({ hasChoice: false });
  assert.equal(ready.phase, 'draft');
  assert.equal(incomplete.phase, 'draft');
  assert.match(ready.detail, /已有匹配结果会自动读取/);
  assert.match(incomplete.detail, /请先选择/);
  assert.equal(ready.action, 'configure');
});

for (const status of ['queued', 'running', 'cancelling']) void test(`${status} reports the confirmed task state without an estimated percentage`, () => {
  const job = freeze({ status, progress: .333333, message: 'Internal task message', request, result: null });
  const before = JSON.stringify(job), state = stateFor({ currentStatus: job });
  assert.equal(state.phase, status);
  assert.equal(state.action, 'task');
  assert.doesNotMatch(state.title + state.detail, /%|\d+秒|\d+分钟/);
  assert.equal(JSON.stringify(job), before);
});

for (const status of ['failed', 'timeout', 'cancelled', 'no_layout']) void test(`${status} does not present a draft as a completed result`, () => {
  const state = stateFor({ currentStatus: { status } });
  assert.equal(state.phase, status);
  assert.ok(['retry', 'configure'].includes(state.action));
  assert.doesNotMatch(state.title, /已完成|设置半径/);
});

void test('completed status without a loaded layout does not announce an available layout', () => {
  assert.equal(stateFor({ currentStatus: { status: 'completed', cached: true } }).phase, 'result-loading');
});

void test('loaded results describe known cache and compute provenance without inferring missing provenance', () => {
  const cached = stateFor({ hasLayout: true, currentStatus: { status: 'completed', cached: true } });
  const computed = stateFor({ hasLayout: true, currentStatus: { status: 'completed', cached: false } });
  const unknown = stateFor({ hasLayout: true, currentStatus: { status: 'completed' } });
  assert.equal(cached.phase, 'completed');
  assert.match(cached.detail, /未重新计算/);
  assert.match(computed.detail, /计算完成/);
  assert.doesNotMatch(unknown.detail, /计算完成|未重新计算|缓存/);
});

async function controller(t, search) {
  const calls = [], history = [];
  const harness = await createHookHarness({
    filename: new URL('../features/design/use-design-controller.ts', import.meta.url), exportName: 'useDesignController',
    imports: {
      requestKey, NOISE_MODEL_PRESETS, presetIdFor: noiseModelId, comparisonLink, parseAR, REGION_COUNTS, MASK_NAMES, placementChoices, choiceFromSlots,
      apiJson: async (url, options) => {
        calls.push({ url, options });
        if (url === '/data/experiment_protocol_v2.json') return { anatomical_preset_matrix: { 2: [{ masks: ['PL', 'PR'] }] } };
        if (url === '/api/local-compute/library/' + source.id) return { record: source };
        throw new Error('Unexpected controller request: ' + url);
      },
    },
    globals: { window: { location: { search }, matchMedia: () => ({ matches: false }), history: { replaceState: (_state, _title, href) => history.push(href) } } },
  });
  t.after(() => harness.dispose());
  await harness.waitFor(state => state.ready);
  return { harness, calls, history };
}
const view = state => designViewState({ ready: state.ready, error: state.error, editing: state.editing, hasLayout: !!state.layout, hasChoice: !!state.choice, currentStatus: state.currentStatus });

void test('real design controller restores area records and creates the same radius request only after the explicit action', async t => {
  const { harness, calls } = await controller(t, `?from=${source.id}&ar=87`);
  const before = JSON.stringify(source);
  assert.equal(view(harness.current).phase, 'area-record');
  assert.equal(harness.current.layout, source.layout);
  assert.equal(harness.current.metrics, source.metrics);
  assert.equal(harness.current.receptionId, source.id);
  await harness.act(state => state.startRadius());
  assert.equal(view(harness.current).phase, 'draft');
  assert.deepEqual(harness.current.request, request);
  assert.equal(harness.current.layout, undefined);
  assert.equal(harness.current.metrics, undefined);
  assert.equal(harness.current.receptionId, null);
  assert.equal(harness.current.source, source);
  assert.equal(JSON.stringify(source), before);
  assert.equal(calls.length, 2);
  assert.ok(calls.every(call => !call.options.method || call.options.method === 'GET'));
});

void test('real controller keeps scientific objects and URL parameters while rejecting stale task presentation after parameter edits', async t => {
  const { harness, calls } = await controller(t, `?from=${source.id}&ar=87&project=keep-context`);
  await harness.act(state => state.startRadius());
  const result = freeze({ status: 'completed', request: { ...request }, layout: source.layout, metrics: source.metrics, geometry: source.geometry });
  const job = freeze({ id: 'test-task', key: 'b'.repeat(64), request: { ...request }, status: 'completed', cached: true, result, progress: 1 });
  const before = JSON.stringify({ request: harness.current.request, result, job });
  await harness.act(state => { state.setComputed(result); state.setStatus(job); });
  assert.equal(view(harness.current).phase, 'completed');
  assert.equal(harness.current.layout, result.layout);
  assert.equal(harness.current.metrics, result.metrics);
  assert.equal(harness.current.geometry, result.geometry);
  assert.equal(Object.is(harness.current.layout.xyzMm[0][1], -0), true);
  assert.equal(harness.current.receptionId, job.key);
  await harness.act(state => state.setAR(72));
  assert.equal(JSON.stringify({ request: harness.current.request, result, job }), before);
  const sameResultURL = new URL(harness.current.here, 'http://localhost');
  assert.equal(sameResultURL.searchParams.get('project'), 'keep-context');
  assert.equal(sameResultURL.searchParams.get('from'), source.id);
  assert.equal(sameResultURL.searchParams.get('ar'), '72');
  assert.equal(sameResultURL.searchParams.get('radius'), '35');
  await harness.act(state => { state.setRadius(40); state.setDraft(true); });
  assert.equal(harness.current.currentStatus, null);
  assert.equal(harness.current.metrics, undefined);
  assert.equal(harness.current.layout, undefined);
  assert.equal(view(harness.current).phase, 'draft');
  assert.deepEqual(harness.current.request, { ...request, radius_mm: 40 });
  assert.equal(new URL(harness.current.here, 'http://localhost').searchParams.get('radius'), '40');
  assert.equal(JSON.stringify(result), JSON.stringify(job.result));
  assert.equal(calls.length, 2);
});
