import * as taskClient from '../client/task-client.ts';
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';
import { createHookHarness } from './helpers/hook-harness.mjs';
import * as editor from '../lib/electrode-editor.ts';
import { parseAR } from '../lib/lab-workflow.ts';

const parentId = 'a'.repeat(64), digest = 'b'.repeat(64), recordKey = 'c'.repeat(64);
const controllerFile = new URL('../features/electrodes/use-electrodes-controller.ts', import.meta.url);
const workspaceFile = new URL('../features/electrodes/electrodes-workspace.tsx', import.meta.url);
const labels = Array.from({ length: 64 }, (_, i) => Number(i >= 32));
const xyz = Array.from({ length: 64 }, (_, i) => [i * 5, 0, 0]);
const domain = {
  parent: { id: parentId, status: 'completed', dataset_id: 'strict_area', region_count: 2,
    layout: { xyzMm: xyz, regionIndices: labels, referenceXyzMm: xyz } },
  original_indices: Array.from({ length: 64 }, (_, i) => i),
  regions: [0, 1].map(r => ({ bank_indices: Array.from({ length: 32 }, (_, i) => i + r * 32), xyz_mm: xyz.slice(r * 32, (r + 1) * 32) })),
};
const savedSlots = editor.initialSlots(domain).map((s, i) => ({ ...s, enabled: i !== 63 }));
const savedRecord = { key: recordKey, parent_id: parentId, electrode_count: 63,
  request: { action: 'evaluate', parent_id: parentId, parent_digest: digest, seed: 2026, slots: savedSlots } };

// Extract the real slider callback through the TSX tree, then execute it below.
const source = await readFile(workspaceFile, 'utf8');
const tree = ts.createSourceFile('electrodes-workspace.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let sliderCallback;
function findSlider(node) {
  if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(tree) === 'input') {
    const attrs = node.attributes.properties;
    const value = attrs.find(a => ts.isJsxAttribute(a) && a.name.getText(tree) === 'value');
    if (value?.initializer && ts.isJsxExpression(value.initializer) && value.initializer.expression?.getText(tree) === 'ar') {
      const change = attrs.find(a => ts.isJsxAttribute(a) && a.name.getText(tree) === 'onChange');
      sliderCallback = change.initializer.expression.getText(tree);
    }
  }
  ts.forEachChild(node, findSlider);
}
findSlider(tree);
assert.ok(sliderCallback, 'The AR slider must expose its actual callback');

function environment(href, storage = new Map()) {
  const location = new URL(href, 'http://localhost'), requests = [];
  const window = { location, addEventListener() {}, removeEventListener() {}, confirm: () => true,
    history: { replaceState(_state, _title, next) { location.href = new URL(next, location).href; } } };
  const sessionStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) };
  const fetch = async (url, options = {}) => {
    requests.push({ url, action: options.body && JSON.parse(options.body).action });
    let body;
    if (url.endsWith('/parents')) body = { records: [domain.parent] };
    else if (url.endsWith('/records')) body = { records: [savedRecord] };
    else if (url.endsWith('/health')) body = { token: 'isolated-test' };
    else if (url.endsWith('/jobs')) {
      const request = JSON.parse(options.body);
      const result = request.action === 'prepare' ? domain : {
        schema: 'electrode-editor/1', request, electrode_count: request.slots.filter(s => s.enabled).length,
        edited_metrics: { field_relative: 0.8 }, parent_metrics: { field_relative: 0.9 },
      };
      body = { job: { id: 'isolated-job', key: recordKey, parent_digest: digest,
        status: 'completed', progress: 1, cached: true, result } };
    } else throw new Error(`Unexpected test request: ${url}`);
    return { ok: true, headers: { get: name => name.toLowerCase() === 'content-type' ? 'application/json' : null }, json: async () => body };
  };
  return { window, storage, requests, globals: { window, sessionStorage, fetch } };
}
async function open(env) {
  const hook = await createHookHarness({ filename: controllerFile, exportName: 'useElectrodesController',
    imports: { ...taskClient, ...editor, parseAR, useLanguage: () => ({ tx: x => x, locale: 'en', date: x => x }) }, globals: env.globals });
  try { await hook.waitFor(current => !!current.domain && !current.busy); }
  catch (error) { hook.dispose(); throw error; }
  return hook;
}
async function changeAR(hook, value) {
  assert.ok(hook.current.result, 'The real slider appears only after evaluation');
  const handler = hook.evaluate(sliderCallback, { setAr: hook.current.setAr,
    domain: hook.current.domain, originalLayout: hook.current.originalLayout });
  await hook.act(() => handler({ target: { value: String(value) } }));
}
const savedHref = `/electrodes?parent=${parentId}&editorRecord=${recordKey}&ar=90&returnTo=%2Flibrary`;

void test('changing AR preserves the saved 63-point record and all working URL parameters across reload', async () => {
  const env = environment(savedHref); let hook;
  try {
    hook = await open(env);
    assert.equal(hook.current.activeCount, 63);
    await hook.act(current => current.evaluate());
    const url = env.window.location;
    url.searchParams.set('thresholdMode', 'custom'); url.searchParams.set('p90', '20'); url.hash = 'evaluation';
    const before = new URL(url);
    await changeAR(hook, 85);
    assert.equal(hook.current.ar, 85);
    assert.equal(hook.current.activeCount, 63);
    for (const [key, value] of before.searchParams) if (key !== 'ar') assert.equal(url.searchParams.get(key), value, key);
    assert.equal(url.hash, before.hash);
    hook.dispose();
    hook = await open(environment(url.href, env.storage));
    assert.equal(hook.current.activeCount, 63);
    assert.equal(hook.current.originalLayout, false);
    assert.deepEqual(hook.current.slots, savedSlots);
    assert.equal(hook.current.result, null, 'A restored draft must not display parent scores as its evaluation');
    assert.equal(hook.current.error, '');
  } finally { hook?.dispose(); }
});

void test('a newly evaluated 63-point draft retains its tab draft when AR changes', async () => {
  const env = environment(`/electrodes?parent=${parentId}&ar=90`); let hook;
  try {
    hook = await open(env);
    await hook.act(current => current.commit(savedSlots));
    await hook.act(current => current.evaluate());
    await changeAR(hook, 85);
    assert.equal(env.window.location.searchParams.get('resume'), '1');
    const href = env.window.location.href;
    hook.dispose();
    hook = await open(environment(href, env.storage));
    assert.equal(hook.current.activeCount, 63);
    assert.deepEqual(hook.current.slots, savedSlots);
    assert.equal(hook.current.result, null);
  } finally { hook?.dispose(); }
});

void test('explicit resume restores later edits to a saved record without reusing old scores', async () => {
  const env = environment(savedHref); let hook;
  try {
    hook = await open(env);
    const changed = hook.current.slots.map((s, i) => ({ ...s, enabled: s.enabled && i !== 0 }));
    await hook.act(current => current.commit(changed));
    await hook.act(current => current.evaluate());
    await changeAR(hook, 85);
    const href = env.window.location.href;
    hook.dispose();
    hook = await open(environment(href, env.storage));
    assert.equal(hook.current.activeCount, 62);
    assert.deepEqual(hook.current.slots, changed);
    assert.equal(hook.current.result, null);
  } finally { hook?.dispose(); }
});

void test('missing, stale, invalid, or other-parent tab drafts fall back to the specified saved record', async () => {
  const changed = savedSlots.map((s, i) => ({ ...s, enabled: s.enabled && i !== 0 }));
  const key = 'eeg-editor-tab-draft:' + parentId;
  const cases = [
    new Map(),
    new Map([[key, '{invalid-json']]),
    new Map([[key, JSON.stringify({ digest: 'd'.repeat(64), slots: changed })]]),
    new Map([[key, JSON.stringify({ digest, slots: [] })]]),
    new Map([['eeg-editor-tab-draft:' + 'e'.repeat(64), JSON.stringify({ digest, slots: changed })]]),
  ];
  for (const storage of cases) {
    const hook = await open(environment(savedHref + '&resume=1', storage));
    try {
      assert.equal(hook.current.activeCount, 63);
      assert.deepEqual(hook.current.slots, savedSlots);
      assert.equal(hook.current.result, null);
      assert.equal(hook.current.error, '');
    } finally { hook.dispose(); }
  }
});
