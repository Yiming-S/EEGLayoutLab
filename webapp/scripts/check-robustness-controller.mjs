import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError } from '../client/task-client.ts';
import { createHookHarness } from './helpers/hook-harness.mjs';
import { parseDesign } from '../lib/design-decision.ts';
import { createStudyInput, fillHeads, readStudyHandoff, saveStudyHandoff, studyRunning, STUDY_DRAFT_KEY, STUDY_DRAFT_LIMIT, studyCaseStatusLabel, studyStatusLabel } from '../features/robustness/robustness-draft.ts';
const id = '18358bf4-143e-4431-8456-b99328462b37', otherId = '18358bf4-143e-4431-8456-b99328462b38';
const date = '2026-11-14T00:00:00Z';
const result = (studyId = id, status = 'draft', revision = 1) => ({ schema: 'eeg-robustness-study/1', id: studyId, status, revision, title: studyId, protocol: 'noise_seeds', created_at: date, updated_at: date, cases: [], aggregation: { completed_cases: 0 } });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const design = () => ({ schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm', name: 'Original scientific name', xyz_mm: Array.from({ length: 64 }, (_, i) => [(i % 8) * 5, Math.floor(i / 8) * 5, 100]), region_indices: Array.from({ length: 64 }, (_, i) => i % 2), electrode_names: Array.from({ length: 64 }, (_, i) => `Channel, "${i}" 中文`) });
async function controller(t, overrides = {}, query = '') {
  const calls = [], history = [], api = { list: async () => ({ studies: [] }), read: async studyId => ({ study: result(studyId) }), create: async () => ({ study: result() }), act: async (studyId, action) => ({ study: result(studyId, action === 'cancel' ? 'cancelled' : 'running', 2) }), export: async () => '{"original":"wire"}', ...overrides };
  const bind = name => async (...args) => { calls.push({ name, args }); return api[name](...args); };
  const harness = await createHookHarness({ filename: new URL('../features/robustness/use-robustness-controller.ts', import.meta.url), exportName: 'useRobustnessController',
    imports: { ApiError, readStudyHandoff, studyRunning, listRobustnessStudies: bind('list'), readRobustnessStudy: bind('read'), createRobustnessStudy: bind('create'), actOnRobustnessStudy: bind('act'), exportRobustnessStudy: bind('export') },
    globals: { window: { location: { search: query }, sessionStorage: { getItem: () => null }, history: { replaceState(_state, _unused, path) { history.push(path); } } } },
  });
  t.after(() => harness.dispose()); await harness.flush(); return { harness, calls, history };
}
void test('open and refresh read existing state without starting a saved draft', async t => {
  const { harness, calls } = await controller(t, {}, '?study=' + id); assert.equal(harness.current.study.id, id);
  await harness.act(state => state.reload()); await harness.waitFor(state => state.study?.id === id);
  assert.equal(harness.current.study.status, 'draft'); assert.equal(calls.filter(call => ['create', 'act'].includes(call.name)).length, 0);
});
void test('create saves a draft and start remains one separate explicit operation', async t => {
  const { harness, calls } = await controller(t); await harness.act(state => state.create({}));
  assert.equal(harness.current.study.status, 'draft'); assert.equal(calls.filter(call => call.name === 'act').length, 0);
  await harness.act(state => state.act('start')); assert.equal(calls.filter(call => call.name === 'act').length, 1); assert.equal(calls.find(call => call.name === 'act').args[1], 'start');
});
void test('overlapping mutation clicks share one pending operation', async t => {
  const pending = deferred(), { harness, calls } = await controller(t, { act: async () => pending.promise }, '?study=' + id);
  const first = harness.current.act('start'), second = harness.current.act('start'); await harness.flush();
  assert.equal(calls.filter(call => call.name === 'act').length, 1); assert.equal(harness.current.busy, true);
  pending.resolve({ study: result(id, 'running', 2) }); await first; await second; await harness.flush(); assert.equal(harness.current.busy, false);
});
void test('unknown mutation outcome blocks repeated writes until an explicit saved-state read', async t => {
  const { harness, calls } = await controller(t, { act: async () => { throw new ApiError('Lost response', 0); } }, '?study=' + id);
  await harness.act(state => state.act('start')); assert.equal(harness.current.uncertain, true);
  await harness.act(state => state.act('start')); assert.equal(calls.filter(call => call.name === 'act').length, 1);
  await harness.act(state => state.reload()); await harness.waitFor(state => !state.uncertain && state.study?.id === id);
  assert.equal(calls.filter(call => call.name === 'act').length, 1);
});
void test('late mutation response cannot replace a subsequently selected study', async t => {
  const pending = deferred(); let signal;
  const { harness } = await controller(t, { act: async (_id, _action, value) => { signal = value; return pending.promise; } }, '?study=' + id);
  const work = harness.current.act('start'); await harness.flush(); await harness.act(state => state.open(otherId)); assert.equal(signal.aborted, true);
  pending.resolve({ study: result(id, 'running', 2) }); await work; await harness.flush(); assert.equal(harness.current.study.id, otherId);
});
void test('new draft ignores an in-flight mutation without resubmission', async t => {
  const pending = deferred(), { harness, calls } = await controller(t, { create: async () => pending.promise });
  const work = harness.current.create({}); await harness.flush(); await harness.act(state => state.newDraft());
  pending.resolve({ study: result() }); await work; await harness.flush(); assert.equal(harness.current.study, null); assert.equal(calls.filter(call => call.name === 'create').length, 1);
});
void test('old running poll cannot overwrite newer cancellation and polling never submits', async t => {
  const pending = deferred(); let reads = 0;
  const { harness, calls } = await controller(t, { read: async () => ++reads === 1 ? { study: result(id, 'running', 1) } : pending.promise }, '?study=' + id);
  await harness.waitFor(() => reads > 1); await harness.act(state => state.act('cancel')); assert.equal(harness.current.study.status, 'cancelled');
  pending.resolve({ study: result(id, 'running', 1) }); await harness.flush(); assert.equal(harness.current.study.status, 'cancelled'); assert.equal(calls.filter(call => call.name === 'act').length, 1);
});
void test('unmount aborts reads without submitting work', async t => {
  const pending = deferred(); let signal;
  const { harness, calls } = await controller(t, { read: async (_id, value) => { signal = value; return pending.promise; } }, '?study=' + id);
  harness.dispose(); assert.equal(signal.aborted, true); pending.resolve({ study: result() }); await pending.promise; assert.equal(calls.filter(call => ['create', 'act'].includes(call.name)).length, 0);
});
void test('export returns original response text without reserializing values', async t => {
  const raw = '{"number":-0,"precise":1e-15}\r\n', { harness } = await controller(t, { export: async () => raw }, '?study=' + id); assert.equal(await harness.current.exportText(), raw);
});
void test('handoff retains original point order, names and scientific layout name independently of study title', () => {
  const original = design(), before = JSON.stringify(original); let raw;
  saveStudyHandoff({ setItem(key, value) { assert.equal(key, STUDY_DRAFT_KEY); raw = value; } }, original);
  const restored = readStudyHandoff({ getItem: () => raw }); assert.deepEqual(restored, original);
  const input = createStudyInput(restored, 'noise_seeds', [{ seed: '42', radius: '6' }, { seed: '43', radius: '6' }], 'Independent title', 'notes');
  assert.deepEqual(input.design, original); assert.equal(input.design.name, 'Original scientific name'); assert.equal(input.title, 'Independent title'); assert.equal(JSON.stringify(original), before);
});
void test('case form rejects duplicates, excess cases, bad values and false noise-radius repetitions', () => {
  for (const rows of [[{ seed: '42', radius: '6' }, { seed: '42', radius: '6' }], [{ seed: '42', radius: '3' }, { seed: '43', radius: '6' }], [{ seed: '-1', radius: '6' }], [{ seed: '42', radius: '4' }], Array.from({ length: 13 }, (_, i) => ({ seed: String(i), radius: '6' }))]) assert.throws(() => createStudyInput(design(), 'noise_seeds', rows, 'title', ''));
  assert.equal(createStudyInput(design(), 'grid_displacements', [{ seed: '42', radius: '3' }, { seed: '42', radius: '6' }], 'title', '').cases.length, 2);
  for (const raw of ['not JSON', '{}', ' '.repeat(65537)]) assert.throws(() => readStudyHandoff({ getItem: () => raw }));
});
void test('cross-head drafts fill unused heads, pair one seed and radius, and reject repeated heads', () => {
  const heads = [{ head_id: 'ernie_xh' }, { head_id: 'ixi002' }, { head_id: 'ixi012' }];
  const rows = fillHeads([{ seed: '7', radius: '3', head: 'ixi002' }, { seed: '9', radius: '10' }, { seed: '1', radius: '6', head: 'gone' }], heads);
  assert.deepEqual(rows.map((row) => [row.head, row.seed, row.radius]), [['ixi002', '7', '3'], ['ernie_xh', '7', '3'], ['ixi012', '7', '3']]);
  assert.equal(fillHeads([...rows, { seed: '7', radius: '3' }], heads)[3].head, '');
  const input = createStudyInput(design(), 'heads', rows, 'title', '', undefined, 'skull_x2');
  assert.deepEqual(input.cases, [{ seed: 7, radius_mm: 3, head_id: 'ixi002' }, { seed: 7, radius_mm: 3, head_id: 'ernie_xh' }, { seed: 7, radius_mm: 3, head_id: 'ixi012' }]);
  assert.equal(input.conductivity_scenario, undefined);
  for (const bad of [[rows[0], rows[0]], [{ ...rows[0], head: '' }], [rows[0], { ...rows[1], radius: '6' }]])
    assert.throws(() => createStudyInput(design(), 'heads', bad, 'title', ''));
  assert.throws(() => createStudyInput(design(), 'heads', [rows[0], { ...rows[1], seed: '8' }], 'title', ''), /同一随机种子/);
});
void test('parent and child status labels retain their separate subjects', () => {
  assert.equal(studyStatusLabel('completed'), '研究已完成'); assert.equal(studyCaseStatusLabel('completed'), '案例已完成'); assert.equal(studyCaseStatusLabel('cancelled'), '案例已取消');
});
async function draftController(t, args = [null, undefined]) {
  const harness = await createHookHarness({ filename: new URL('../features/robustness/use-study-design-draft.ts', import.meta.url), exportName: 'useStudyDesignDraft', args, imports: { parseDesign, STUDY_DRAFT_LIMIT } }); t.after(() => harness.dispose()); await harness.flush(); return harness;
}
void test('selecting invalid input clears prior valid design and title before reading and rejects oversized files before File.text', async t => {
  const harness = await draftController(t, [design(), undefined]); assert.equal(harness.current.design.name, design().name);
  let reads = 0; await harness.act(state => state.readFile({ name: 'large.json', size: 65537, text: async () => { reads++; return '{}'; } }));
  assert.equal(reads, 0); assert.equal(harness.current.design, null); assert.equal(harness.current.title, ''); assert.match(harness.current.error, /64 KiB/);
});
void test('switching to a saved study invalidates a pending File.text result', async t => {
  const args = [null, undefined], harness = await draftController(t, args), pending = deferred();
  const work = harness.current.readFile({ name: 'old.json', size: 100, text: () => pending.promise }); await harness.flush();
  args[1] = id; await harness.act(state => state.setTitle('render study selection')); pending.resolve(JSON.stringify(design())); await work; await harness.flush();
  assert.equal(harness.current.design, null); assert.equal(harness.current.loading, false);
});
void test('newer valid file wins over older deferred reads and unmount prevents late updates', async t => {
  const harness = await draftController(t), pending = deferred(), original = design();
  const oldRead = harness.current.readFile({ name: 'old.json', size: 100, text: () => pending.promise });
  const newer = { ...original, name: 'Newer' }; await harness.act(state => state.readFile({ name: 'new.json', size: 100, text: async () => JSON.stringify(newer) }));
  pending.resolve(JSON.stringify(original)); await oldRead; await harness.flush(); assert.equal(harness.current.design.name, 'Newer');
});
void test('study export selection change aborts the old response and keeps its errors out of the new study', async t => {
  const pending = deferred(), saved = [], signals = [], args = [id, async signal => { signals.push(signal); return pending.promise; }, (studyId, raw) => saved.push({ studyId, raw })];
  const harness = await createHookHarness({ filename: new URL('../features/robustness/use-study-export.ts', import.meta.url), exportName: 'useStudyExport', args, imports: {} }); t.after(() => harness.dispose());
  const work = harness.current.run(); await harness.flush(); args[0] = otherId;
  await harness.rerender(); assert.equal(signals[0].aborted, true);
  pending.reject(new Error('old export failed')); await work; await harness.flush();
  assert.equal(harness.current.error, ''); assert.equal(harness.current.busy, false); assert.deepEqual(saved, []);
});
