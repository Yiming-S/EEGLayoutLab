import test from 'node:test';
import { CONDUCTIVITY_SCENARIOS, NOISE_MODEL_PRESETS } from '../contracts/scientific-options.mjs';
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { mkdtemp, mkdir, readFile, readdir, realpath, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { designCSV, designSubmission, exportDesign, parseDesign, scientificDesign, validateDesign } from '../lib/design-decision.ts';
import { ElectrodeAnnotations, ANNOTATION_LIMITS } from '../server/annotations/electrode-names.mjs';
import { DesignEvaluationService, normalizeDesignRequest } from '../server/design-evaluation-server.mjs';
import { communityAdapters } from '../server/community-adapters.mjs';
import { CommunityQueue, communityMiddleware } from '../server/community-queue.mjs';
import { computeMiddleware } from '../server/local-compute-server.mjs';
import { createAccessPolicy } from '../server/http/access-policy.mjs';
import { sendJson } from '../server/http/responses.mjs';
import { ProjectService } from '../server/projects/service.mjs';
import { ProjectStore } from '../server/projects/store.mjs';
import { projectSnapshotView } from '../features/projects/project-snapshot-view.ts';
import { projectChoiceId, projectRecordChoices } from '../features/projects/project-record-choices.ts';
import { buildResearchDelivery, validateResearchDelivery } from '../server/delivery/research-bundle.mjs';
import { followTask } from '../client/task-client.ts';
import * as decision from '../lib/design-decision.ts';
import { canCompareRecord } from '../lib/workspace-navigation.ts';
import { safeReturnHref } from '../lib/ui-language.ts';
import { createHookHarness } from './helpers/hook-harness.mjs';

const hash = value => createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex');
const base = { schema: 'eeg-electrode-design/1', coordinate_system: 'ernie_native_mm', unit: 'mm', name: 'Shared layout',
  xyz_mm: Array.from({ length: 64 }, (_, i) => [(i % 8) * 6, Math.floor(i / 8) * 6, 1e-14]), region_indices: Array.from({ length: 64 }, (_, i) => i % 2) };
const names = prefix => Array.from({ length: 64 }, (_, i) => `${prefix}${i + 1}`);
const a = { ...base, electrode_names: names('A') }, b = { ...base, electrode_names: names('B') };
const request = normalizeDesignRequest({ action: 'evaluate', design: base, radius_mm: 6, seed: 42 });
const cleanups = new WeakMap();
const cleanup = (t, fn) => cleanups.get(t).push(fn);
const rootFor = async t => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'eeg-names-'))); cleanups.set(t, []);
  t.after(async () => { try { for (const fn of cleanups.get(t).reverse()) await fn(); } finally { await rm(root, { recursive: true, force: true }); } });
  return root;
};

void test('CSV and JSON preserve exact names, coordinate row order and zero-based regions; legacy JSON stays bare', () => {
  const design = { ...a, electrode_names: names('电极').map((n, i) => i === 0 ? ' "Fp,1" ' : i === 1 ? '<script>channel</script>' : n) };
  assert.deepEqual(parseDesign(JSON.stringify(design)), design);
  assert.deepEqual(parseDesign(designCSV(design), design.name), design);
  assert.deepEqual(validateDesign(base), base);
  assert.deepEqual(scientificDesign(design), base);
  assert.equal(designCSV(base).split('\n')[2].split(',')[0], 'E1');
  for (const invalid of [names('A').slice(1), names('A').fill('duplicate'), names('A').map((v, i) => i ? v : 'line\nfeed'), names('A').map((v, i) => i ? v : 'x'.repeat(129))])
    assert.throws(() => validateDesign({ ...base, electrode_names: invalid }));
});

async function fixture(t, { cached = true } = {}) {
  const root = await rootFor(t), identity = { test_identity: 'frozen' }, key = hash({ request, identity }), token = 'c'.repeat(64);
  const result = { schema: 'design-evaluation/1', status: 'completed', request, forward_mode: 'cached_fem', evaluated_xyz_mm: base.xyz_mm,
    nominal: { field_relative: 1, field_absolute: 0.9, reference_field_absolute: 0.9, sensitivity_tail: 1, localization_relative: 1, median_mm: 10, p90_mm: 20, reference_median_mm: 10, reference_p90_mm: 20 }, projection_max_mm: 0, trials: [], provenance: { candidate_count: 64, original: [1 / 3, -1e-18, 1.0000000000000002] } };
  const cache = { key, identity, result, result_sha256: hash(result) }, cachePath = join(root, 'results/v2/design_evaluation_jobs', key, 'cache.json');
  await mkdir(join(cachePath, '..'), { recursive: true }); if (cached) await writeFile(cachePath, JSON.stringify(cache));
  const record = { id: key, label: base.name, dataset_id: 'design_evaluation', status: 'completed', region_count: 2, mode: 'design_evaluation', compatible: true,
    request: null, spacing_mm: 6, geometry: null, metrics: { ...result.nominal, conditional_global: 1 }, layout: { id: key, xyzMm: result.evaluated_xyz_mm, regionIndices: base.region_indices, referenceXyzMm: base.xyz_mm },
    provenance: { forward_mode: 'cached_fem', design_result: { path: `results/v2/design_evaluation_jobs/${key}/cache.json`, sha256: hash(JSON.stringify(cache)) } } };
  const queue = { root, token, python: 'unused', runtime: { queueDirectory: join(root, 'queue'), nativePython: 'unused' }, health: () => ({ token, available: true }),
    library: { get: async id => id === key ? structuredClone(record) : null, list: async () => ({ schema: 'local-data-library/1', records: [structuredClone(record)], warnings: [], datasets: [] }) } };
  queue.designTests = new DesignEvaluationService(queue, { context: async r => ({ identity, key: hash({ request: r, identity }) }), spawnProcess: () => { throw new Error('A metadata test must never launch a worker.'); } });
  let blocked = false;
  const annotations = new ElectrodeAnnotations(root), scheduler = new CommunityQueue({ directory: queue.runtime.queueDirectory, adapters: communityAdapters(queue), annotations, pollMs: 3600000,
    beforeNewWork: async () => { if (blocked) throw Object.assign(new Error('Resources unavailable.'), { status: 503, resourceSafe: true, retryAfter: 5 }); } });
  cleanup(t, () => { scheduler.dispose(); queue.designTests.dispose(); });
  return { root, queue, scheduler, annotations, key, record, cache, cachePath, setBlocked: value => { blocked = value; } };
}

void test('production adapter normalization excludes A/B names from request, worker input and scientific key', async t => {
  const { queue, scheduler, key } = await fixture(t);
  const adapter = scheduler.adapters['design-evaluation'];
  const prepared = await Promise.all([request, designSubmission(a, 'evaluate', 6, 42), designSubmission(b, 'evaluate', 6, 42)].map(raw => adapter.prepare(raw)));
  for (const value of prepared) { assert.deepEqual(value.request, request); assert.equal(value.key, key); assert.deepEqual(queue.designTests.workerInput({ request: value.request }), request); }
  assert.equal(JSON.stringify(prepared[0].request), JSON.stringify(prepared[1].request));
  assert.equal(JSON.stringify(prepared[0].request), JSON.stringify(prepared[2].request));
});

void test('shared receipts retain owner-specific and same-owner variants across restart without scientific file changes', async t => {
  const f = await fixture(t, { cached: false }), ownerA = { id: 'a'.repeat(64), ip: 'local' }, ownerB = { id: 'b'.repeat(64), ip: 'local' };
  const first = await f.scheduler.submit('design-evaluation', designSubmission(a, 'evaluate', 6, 42), ownerA);
  const second = await f.scheduler.submit('design-evaluation', designSubmission(b, 'evaluate', 6, 42), ownerB);
  const third = await f.scheduler.submit('design-evaluation', designSubmission(b, 'evaluate', 6, 42), ownerA);
  assert.equal(first.job.id, second.job.id); assert.equal(second.job.id, third.job.id);
  assert.equal(first.job.key, second.job.key); assert.notEqual(first.job.annotation_id, second.job.annotation_id); assert.notEqual(second.job.annotation_id, third.job.annotation_id);
  assert.deepEqual((await f.scheduler.view(f.scheduler.own(first.job.id, ownerA), false, ownerA, first.job.annotation_id)).electrode_annotation.electrode_names, a.electrode_names);
  assert.deepEqual((await f.scheduler.view(f.scheduler.own(third.job.id, ownerA), false, ownerA, third.job.annotation_id)).electrode_annotation.electrode_names, b.electrode_names);
  assert.throws(() => f.annotations.read(first.job.annotation_id, ownerB.id, f.key), { status: 404 });
  f.scheduler.dispose();
  const restored = new CommunityQueue({ directory: f.queue.runtime.queueDirectory, adapters: f.scheduler.adapters, annotations: new ElectrodeAnnotations(f.root), pollMs: 3600000 });
  cleanup(t, () => restored.dispose());
  assert.deepEqual((await restored.view(restored.own(first.job.id, ownerA), false, ownerA, first.job.annotation_id)).electrode_annotation.electrode_names, a.electrode_names);
  assert.deepEqual(restored.own(first.job.id, ownerA).request, request);
  assert.deepEqual(await readdir(join(f.root, 'results/v2/design_evaluation_jobs', f.key)), []);
});

void test('sidecar integrity, paths, crashed temporaries, private output and storage limits are enforced', async t => {
  const f = await fixture(t), prepared = await f.scheduler.adapters['design-evaluation'].prepare(designSubmission(a, 'evaluate', 6, 42)), owner = 'a'.repeat(64);
  const first = f.annotations.create(prepared, owner), directory = f.annotations.directory();
  assert.equal(JSON.stringify(first).includes(owner), false);
  await writeFile(join(directory, `.${randomUUID()}.tmp`), 'interrupted');
  assert.equal(f.annotations.create({ ...prepared, electrode_names: b.electrode_names }, owner).record_id, f.key);
  assert.equal(f.annotations.list(owner).length, 2);
  const limited = new ElectrodeAnnotations(f.root, { limits: { ...ANNOTATION_LIMITS, files: 3 } });
  assert.throws(() => limited.create({ ...prepared, electrode_names: names('C') }, owner), { status: 507 });
  assert.throws(() => f.annotations.read('../outside', owner, f.key), { status: 404 });
  const path = join(directory, first.id + '.json'), original = await readFile(path, 'utf8');
  await writeFile(path, original.replace('A1', 'changed'));
  assert.throws(() => f.annotations.read(first.id, owner, f.key), { status: 409 });
  await rm(path); await symlink(f.cachePath, path);
  assert.throws(() => f.annotations.read(first.id, owner, f.key), { status: 409 });
});

void test('lookup misses do not create metadata, blocked writes fail before receipts, bare cached reads stay available', async t => {
  const f = await fixture(t, { cached: false }), visitor = { id: 'a'.repeat(64), ip: 'local' }, envelope = designSubmission(a, 'evaluate', 6, 42);
  assert.deepEqual(await f.scheduler.submit('design-evaluation', envelope, visitor, true), { hit: false });
  assert.equal(f.annotations.directory(), null); assert.equal(f.scheduler.tasks.length, 0);
  f.setBlocked(true);
  await assert.rejects(f.scheduler.submit('design-evaluation', envelope, visitor), { status: 503 });
  assert.equal(f.annotations.directory(), null); assert.equal(f.scheduler.tasks.length, 0);
  await writeFile(f.cachePath, JSON.stringify(f.cache));
  assert.equal((await f.scheduler.submit('design-evaluation', request, visitor, true)).hit, true);
  await assert.rejects(f.scheduler.submit('design-evaluation', envelope, visitor, true), { status: 503 });
  assert.equal(f.annotations.directory(), null); assert.equal(f.scheduler.tasks.length, 1);
  f.setBlocked(false);
  const saved = await f.scheduler.submit('design-evaluation', envelope, visitor, true);
  f.setBlocked(true);
  const retry = await f.scheduler.submit('design-evaluation', envelope, visitor, true);
  assert.equal(retry.job.annotation_id, saved.job.annotation_id, 'A retry must not create or replace metadata.');
});

void test('per-owner and per-receipt metadata bounds reject new variants without creating files', async t => {
  const f = await fixture(t), visitor = { id: 'a'.repeat(64), ip: 'local' };
  const first = await f.scheduler.submit('design-evaluation', designSubmission(a, 'evaluate', 6, 42), visitor);
  const task = f.scheduler.own(first.job.id, visitor);
  task.annotation_refs[visitor.id] = Array(20).fill(first.job.annotation_id);
  await assert.rejects(f.scheduler.submit('design-evaluation', designSubmission(b, 'evaluate', 6, 42), visitor), { status: 413 });
  assert.equal(f.annotations.list(visitor.id).length, 1);
  task.annotation_refs[visitor.id] = [first.job.annotation_id]; task.annotation_refs.other = Array(99).fill(first.job.annotation_id);
  await assert.rejects(f.scheduler.submit('design-evaluation', designSubmission(b, 'evaluate', 6, 42), visitor), { status: 413 });
  assert.equal(f.annotations.list(visitor.id).length, 1);
});

void test('HTTP annotations require policy/token and owner; snapshots and delivery preserve each variant after sidecars disappear', async t => {
  const f = await fixture(t), guard = createAccessPolicy().guard, tokenMatches = (value, expected) => value === expected;
  const projects = new ProjectService({ queue: f.queue, scheduler: f.scheduler, guard, send: sendJson, tokenMatches });
  cleanup(t, async () => { projects.close(); await projects.flush(); });
  const legacy = computeMiddleware(f.queue, guard, f.scheduler), middleware = projects.middleware(communityMiddleware({ scheduler: f.scheduler, queue: f.queue, legacy, guard, send: sendJson, tokenMatches }));
  const server = createServer((req, res) => middleware(req, res, () => res.writeHead(404).end()));
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  cleanup(t, async () => { const stopped = once(server, 'close'); server.close(); server.closeAllConnections(); await stopped; });
  const origin = `http://127.0.0.1:${server.address().port}`, cookies = new Map();
  const call = async (path, { browser = 'A', method = 'GET', body, key, token = f.queue.token, originHeader = origin } = {}) => {
    const response = await fetch(origin + path, { method, headers: { Origin: originHeader, Cookie: cookies.get(browser) ?? '',
      ...(method === 'GET' ? {} : { 'Content-Type': 'application/json', ...(token ? { 'X-EEG-Compute-Token': token } : {}) }), ...(key ? { 'X-EEG-Project-Key': key } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
    if (response.headers.get('set-cookie')) cookies.set(browser, response.headers.get('set-cookie').split(';')[0]);
    return { status: response.status, data: await response.json() };
  };
  await call('/api/local-compute/health'); await call('/api/local-compute/health', { browser: 'B' });
  const before = await readFile(f.cachePath, 'utf8');
  assert.equal((await call('/api/design-evaluation/lookup', { method: 'POST', token: '', body: designSubmission(a, 'evaluate', 6, 42) })).status, 403);
  assert.equal((await call('/api/design-evaluation/lookup', { method: 'POST', originHeader: 'https://foreign.test', body: designSubmission(a, 'evaluate', 6, 42) })).status, 403);
  const first = await call('/api/design-evaluation/lookup', { method: 'POST', body: designSubmission(a, 'evaluate', 6, 42) });
  const second = await call('/api/design-evaluation/lookup', { method: 'POST', body: designSubmission(b, 'evaluate', 6, 42) });
  assert.equal(first.status, 200); assert.equal(second.status, 200);
  const aid = first.data.job.annotation_id, bid = second.data.job.annotation_id;
  assert.notEqual(aid, bid); assert.equal(first.data.job.key, second.data.job.key);
  const old = await call(`/api/design-evaluation/jobs/${first.data.job.id}?annotation_id=${aid}`);
  assert.deepEqual(old.data.job.electrode_annotation.electrode_names, a.electrode_names);
  assert.equal((await call(`/api/design-evaluation/jobs/${first.data.job.id}?annotation_id=${aid}&extra=1`)).status, 400);
  assert.equal((await call(`/api/local-compute/library/${f.key}?annotation_id=${aid}`, { browser: 'B' })).status, 404);
  const shown = await call(`/api/local-compute/library/${f.key}?annotation_id=${aid}`);
  assert.deepEqual(exportDesign(shown.data.record).electrode_names, a.electrode_names);
  assert.equal((await f.queue.library.get(f.key)).electrode_annotation, undefined);
  const bundle = await call(`/api/local-compute/library/${f.key}/bundle?annotation_id=${aid}`);
  assert.equal(bundle.status, 200); assert.deepEqual(bundle.data.original_record, f.cache); assert.deepEqual(bundle.data.electrode_annotation.electrode_names, a.electrode_names);
  const choices = projectRecordChoices('layout', (await call('/api/local-compute/library')).data, 'en');
  assert.equal(new Set(choices.map(projectChoiceId)).size, 3);
  const created = await call('/api/projects', { method: 'POST', body: { title: 'Named electrodes', owner_name: 'Researcher' } }), key = created.data.access_key, projectId = created.data.project.id;
  const path = `/api/projects/${projectId}`, entries = [];
  for (const [i, id] of [aid, bid].entries()) {
    const attached = await call(path + '/entries', { method: 'POST', key, body: { revision: i + 1, kind: 'layout', record_id: f.key, annotation_id: id } });
    assert.equal(attached.status, 201); entries.push(attached.data.entry);
  }
  assert.equal((await call(path + '/entries', { browser: 'B', method: 'POST', key, body: { revision: 3, kind: 'layout', record_id: f.key, annotation_id: aid } })).status, 404);
  const share = await call(path + '/share', { method: 'POST', key, body: { revision: 3 } });
  await rm(f.annotations.directory(), { recursive: true });
  const restored = new ProjectStore(projects.store.directory);
  for (const [i, entry] of entries.entries()) {
    const loaded = await restored.getEntry(projectId, share.data.access_key, entry.id), viaHttp = await call(`${path}/entries/${entry.id}`, { browser: 'B', key: share.data.access_key });
    assert.equal(viaHttp.status, 200); assert.deepEqual(loaded.snapshot.payload.original_record, f.cache);
    assert.deepEqual(projectSnapshotView(loaded.entry, loaded.snapshot).record.electrode_annotation.electrode_names, i ? b.electrode_names : a.electrode_names);
    assert.equal(JSON.stringify(loaded.snapshot).includes('"owner"'), false);
  }
  const delivery = buildResearchDelivery(await restored.readSnapshots(projectId, key));
  assert.equal(validateResearchDelivery(delivery), true);
  assert.deepEqual(delivery.records.map(row => row.annotation_id), [aid, bid]);
  assert.deepEqual(JSON.parse(delivery.files[1].content).electrode_annotation.electrode_names, a.electrode_names);
  assert.equal(await readFile(f.cachePath, 'utf8'), before);
});

void test('task polling retains the explicitly selected name variant when a shared receipt has a newer variant', async t => {
  const id = 'd'.repeat(64), calls = [], initial = { id: randomUUID(), status: 'running', annotation_id: id };
  t.mock.method(globalThis, 'fetch', async url => { calls.push(url); return { ok: true, status: 200, json: async () => ({ job: { ...initial, status: 'completed' } }) }; });
  await followTask({ service: 'design-evaluation', initial, signal: new AbortController().signal, onJob() {}, onConnection() {}, firstDelayMs: 0 });
  assert.equal(calls[0], `/api/design-evaluation/jobs/${initial.id}?annotation_id=${id}`);
});

void test('multibyte electrode names survive request chunks split inside every UTF-8 character', async t => {
  const f = await fixture(t), labels = names('电极🧠'), body = Buffer.from(JSON.stringify(designSubmission({ ...base, electrode_names: labels }, 'evaluate', 6, 42)));
  const req = { url: '/api/design-evaluation/lookup', method: 'POST', headers: { 'content-type': 'application/json', 'x-eeg-compute-token': f.queue.token },
    async *[Symbol.asyncIterator]() { for (let index = 0; index < body.length; index++) yield body.subarray(index, index + 1); } };
  let response;
  const middleware = communityMiddleware({ scheduler: f.scheduler, queue: f.queue, legacy() { throw new Error('Unexpected legacy call'); }, guard: () => true,
    tokenMatches: (value, expected) => value === expected, send: (_res, status, data) => { response = { status, data }; } });
  await middleware(req, { setHeader() {} }, () => {});
  assert.equal(response.status, 200); assert.deepEqual(response.data.job.electrode_annotation.electrode_names, labels);
});

void test('opening and refreshing a saved evaluation restores original inputs, exact names, seed and radius with GET only', async t => {
  const f = await fixture(t), annotation = f.annotations.create(await f.scheduler.adapters['design-evaluation'].prepare(designSubmission(a, 'evaluate', 6, 42)), 'a'.repeat(64));
  const savedRequest = { ...request, radius_mm: 10, seed: 97 }, actual = base.xyz_mm.map(point => [point[0], point[1], point[2] + 0.25]);
  const record = { ...f.record, electrode_annotation: annotation, layout: { ...f.record.layout, xyzMm: actual } };
  const result = { ...f.cache.result, request: savedRequest, evaluated_xyz_mm: actual, projection_max_mm: 0.25 };
  const bundle = { schema: 'eeg-reproducibility-bundle/1', record_id: f.key, reproduction: { request: savedRequest }, original_record: { result } };
  const calls = [], writes = [], stored = new Map(), location = { search: `?a=${f.key}&annotation_a=${annotation.id}` };
  const globals = { window: { location, history: { replaceState(_state, _unused, href) { location.search = new URL(href, 'http://localhost').search; } } },
    sessionStorage: { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value) },
    fetch: async url => { calls.push(url); return { ok: true, json: async () => url === '/api/local-compute/library' ? { schema: 'local-data-library/1', records: [record] } : url.includes('/bundle') ? bundle : { record } }; } };
  const imports = { ...decision, CONDUCTIVITY_SCENARIOS, NOISE_MODEL_PRESETS, canCompareRecord, safeReturnHref, useLanguage: () => ({ tx: text => text, locale: 'en' }), followTask,
    isTaskRunning: job => ['queued', 'running'].includes(job?.status), cancelTask: () => { throw new Error('Unexpected cancellation'); },
    submitTask: async (_kind, body) => { writes.push(body); return { job: { id: randomUUID(), status: 'completed', key: f.key, result } }; } };
  const create = () => createHookHarness({ filename: new URL('../features/decision/use-decision-controller.ts', import.meta.url), exportName: 'useDecisionController', imports, globals, args: ['coordinates'] });
  let harness = await create();
  cleanup(t, () => harness.dispose());
  await harness.waitFor(value => Boolean(value.result));
  assert.deepEqual(harness.current.design, { ...base, electrode_names: a.electrode_names });
  assert.deepEqual(harness.current.result.evaluated_xyz_mm, actual);
  assert.equal(harness.current.seed, 97); assert.equal(harness.current.radius, 10); assert.equal(writes.length, 0);
  assert.ok(calls.some(url => url.endsWith(`/bundle?annotation_id=${annotation.id}`)));
  assert.equal(new URL(harness.current.here, 'http://localhost').searchParams.has('resume'), false);
  harness.dispose(); harness = await create();
  await harness.waitFor(value => Boolean(value.result));
  assert.equal(writes.length, 0); assert.deepEqual(harness.current.design.electrode_names, a.electrode_names);
  await harness.act(value => value.runEvaluation('evaluate'));
  assert.deepEqual(writes[0].request, savedRequest);
  assert.deepEqual(writes[0].electrode_names, a.electrode_names);
});
