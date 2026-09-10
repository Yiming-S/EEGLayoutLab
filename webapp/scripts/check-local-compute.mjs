import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { LocalComputeQueue, normalizeRequest, loopbackRequest, validateWorkerResult, computeMiddleware } from './local-compute-server.mjs';
import { requestKey, matchingResult, currentAR, displayJob } from '../lib/local-compute.ts';

const request = { region_count: 2, radius_mm: 35, mode: 'preset', mask_codes: ['PL', 'PR'] };
function resultFor(config = request) {
  const xyz = Array.from({ length: 64 }, (_, i) => [i * 5, 0, 0]);
  const labels = Array.from({ length: 64 }, (_, i) => Math.min(config.region_count - 1, Math.floor(i * config.region_count / 64)));
  return { status: 'completed', request: config, layout: { id: 'fixture', xyzMm: xyz,
    referenceXyzMm: xyz, regionIndices: labels }, geometry: { union_connected_component_count: config.region_count,
    common_graph_radius_mm: config.radius_mm, union_area_cm2: 30 }, metrics: { field_relative: .8,
    sensitivity_tail: .3, localization_relative: .5, conditional_global: .3 } };
}
function fakeSpawner() {
  const children = [];
  const spawnProcess = (...args) => {
    const child = new EventEmitter();
    child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.stdin = new PassThrough();
    child.kills = []; child.kill = (signal) => { child.kills.push(signal); return true; };
    child.args = args; children.push(child); return child;
  };
  return { spawnProcess, children };
}
async function makeQueue(options = {}) {
  const root = await mkdtemp(join(tmpdir(), 'eeg-queue-test-'));
  const fake = fakeSpawner();
  const queue = new LocalComputeQueue({ repositoryRoot: root, spawnProcess: fake.spawnProcess,
    getIdentity: () => ({}), timeoutMs: 3000, ...options });
  return { queue, ...fake };
}
async function waitUntil(predicate) {
  for (let i = 0; i < 100; i++) { if (predicate()) return; await new Promise((r) => setTimeout(r, 5)); }
  throw new Error('test timed out');
}
function complete(child, result) { child.stdout.write(JSON.stringify({ type: 'result', result }) + '\n'); child.emit('close', 0); }

void test('only bounded parameter schema is accepted; AR cannot trigger a compute request', () => {
  assert.deepEqual(normalizeRequest(request), request);
  for (const bad of [{ ...request, radius_mm: 9999 }, { ...request, radius_mm: 36 },
    { ...request, region_count: 5 }, { ...request, mask_codes: ['PL_superior', 'PR'] },
    { ...request, command: 'anything' }, { ...request, AR: .9 }, null, []]) {
    assert.throws(() => normalizeRequest(bad));
  }
  assert.deepEqual(normalizeRequest({ region_count: 1, radius_mm: 15, mode: 'whole_surface', mask_codes: [] }),
    { region_count: 1, radius_mm: 15, mode: 'whole_surface' });
});
void test('local origin, Host and remote address are all checked', () => {
  const req = { socket: { remoteAddress: '127.0.0.1' }, headers: { host: 'localhost:3000', origin: 'http://localhost:3000' } };
  assert.equal(loopbackRequest(req), true);
  assert.equal(loopbackRequest({ ...req, headers: { ...req.headers, origin: 'https://example.org' } }), false);
  assert.equal(loopbackRequest({ ...req, headers: { host: 'attacker.example:3000' } }), false);
  assert.equal(loopbackRequest({ ...req, socket: { remoteAddress: '192.168.1.3' } }), false);
  assert.equal(loopbackRequest({ ...req, headers: { ...req.headers, 'sec-fetch-site': 'cross-site' } }), false);
});
void test('result validation rejects stale request, duplicated points, wrong components and false G', () => {
  validateWorkerResult(resultFor(), request);
  assert.throws(() => validateWorkerResult(resultFor({ ...request, radius_mm: 40 }), request));
  const duplicate = resultFor(); duplicate.layout.xyzMm[1] = duplicate.layout.xyzMm[0];
  assert.throws(() => validateWorkerResult(duplicate, request));
  const merged = resultFor(); merged.geometry.union_connected_component_count = 1;
  assert.throws(() => validateWorkerResult(merged, request));
  const wrong = resultFor(); wrong.metrics.conditional_global = .9;
  assert.throws(() => validateWorkerResult(wrong, request));
  validateWorkerResult({ status: 'no_layout', request, layout: null, metrics: null }, request);
});
void test('queue has one child, deduplicates identical in-flight requests and records progress', async () => {
  const { queue, children } = await makeQueue();
  const first = await queue.submit(request), same = await queue.submit(request);
  assert.equal(first.job.id, same.job.id); assert.equal(children.length, 1);
  assert.equal((await queue.submit({ ...request, radius_mm: 40 })).busy, true);
  assert.equal(children[0].args[2].shell, false);
  assert.equal(children[0].args[2].env.OPENBLAS_NUM_THREADS, '2');
  children[0].stdout.write(JSON.stringify({ type: 'progress', progress: .5, stage: 'geometry', message: '真实检查' }) + '\n');
  assert.equal(queue.active.progress, .5);
  complete(children[0], resultFor()); await waitUntil(() => !queue.active);
  assert.equal(queue.jobs.get(first.job.id).status, 'completed');
  const cached = await queue.submit(request); assert.equal(cached.job.cached, true); assert.equal(children.length, 1);
  queue.dispose();
});
void test('disk cache survives queue restart and source identity invalidates it', async () => {
  const { queue, children } = await makeQueue(); await queue.submit(request); complete(children[0], resultFor());
  await waitUntil(() => !queue.active);
  const job = [...queue.jobs.values()][0]; assert.equal(JSON.parse(await readFile(join(job.batch, 'job.json'), 'utf8')).status, 'completed');
  const next = new LocalComputeQueue({ repositoryRoot: queue.root, getIdentity: () => ({}), spawnProcess: () => { throw new Error('cache must not spawn'); } });
  assert.equal((await next.submit(request)).job.cached, true);
  const changed = new LocalComputeQueue({ repositoryRoot: queue.root, getIdentity: () => ({ version: 'changed' }), spawnProcess: () => { throw new Error('expected new calculation'); } });
  const newJob = await changed.submit(request); assert.notEqual(newJob.job.key, job.key);
  await waitUntil(() => !changed.active); assert.equal(changed.jobs.get(newJob.job.id).status, 'failed');
  queue.dispose(); next.dispose(); changed.dispose();
});
void test('cancellation does not release capacity until child closes; no result is cached', async () => {
  const { queue, children } = await makeQueue(); const first = await queue.submit(request);
  assert.equal(queue.cancel(first.job.id), true); assert.deepEqual(children[0].kills, ['SIGTERM']);
  assert.equal((await queue.submit({ ...request, radius_mm: 40 })).busy, true);
  children[0].emit('close', null); await waitUntil(() => !queue.active);
  assert.equal(queue.jobs.get(first.job.id).status, 'cancelled');
  await queue.submit(request); assert.equal(children.length, 2);
  complete(children[1], { status: 'no_layout', request }); await waitUntil(() => !queue.active); queue.dispose();
});
void test('wall-clock timeout terminates the worker and returns a non-numeric failure', async () => {
  const { queue, children } = await makeQueue({ timeoutMs: 20 }); const first = await queue.submit(request);
  await waitUntil(() => children[0].kills.length > 0); children[0].emit('close', null); await waitUntil(() => !queue.active);
  assert.equal(queue.jobs.get(first.job.id).status, 'timeout'); assert.equal(queue.jobs.get(first.job.id).result, null); queue.dispose();
});
void test('malformed or mismatched worker output fails without crashing the server', async () => {
  const { queue, children } = await makeQueue(); const first = await queue.submit(request);
  complete(children[0], { status: 'completed', request: { command: 'bad' } }); await waitUntil(() => !queue.active);
  assert.equal(queue.jobs.get(first.job.id).status, 'failed'); queue.dispose();
});
void test('mutation endpoint requires the random local-session token, including unicode input', async () => {
  const { queue } = await makeQueue(); const middleware = computeMiddleware(queue);
  for (const token of [undefined, 'wrong', '文'.repeat(64)]) {
    let code;
    const req = { url: '/api/local-compute/jobs', method: 'POST', socket: { remoteAddress: '127.0.0.1' },
      headers: { host: 'localhost:3000', 'x-eeg-compute-token': token } };
    await middleware(req, { writeHead(status) { code = status; }, end() {} }, () => assert.fail());
    assert.equal(code, 403);
  }
  queue.dispose();
});
void test('changing radius hides stale scores and AR never changes compute identity', () => {
  const job = { request, status: 'completed', result: resultFor() };
  assert.ok(matchingResult(job, request));
  assert.equal(matchingResult(job, { ...request, radius_mm: 40 }), null);
  assert.equal(matchingResult({ ...job, status: 'running' }, request), null);
  const key = requestKey(request);
  assert.equal(currentAR(.85, 90), false); assert.equal(currentAR(.85, 80), true);
  assert.equal(currentAR(null, 80), null); assert.equal(requestKey(request), key);
});

void test('current cache displays during another job, and new computation retains its fresh source label', () => {
  const cached = { request, status: 'completed', result: resultFor(), cached: true };
  const other = { request: { ...request, radius_mm: 40 }, status: 'running', result: null };
  assert.equal(displayJob(other, cached, request), cached);
  assert.ok(matchingResult(displayJob(other, cached, request), request));
  const fresh = { ...cached, cached: false };
  assert.equal(displayJob(fresh, cached, request), fresh);
  assert.equal(displayJob(fresh, cached, request).cached, false);
  assert.equal(matchingResult(displayJob(other, cached, other.request), other.request), null);
});
