import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { ProjectService } from '../server/projects/service.mjs';
import { sendJson } from '../server/http/responses.mjs';
import { createAccessPolicy } from '../server/http/access-policy.mjs';
import { validateResearchDelivery } from '../server/delivery/research-bundle.mjs';

const token = 'a'.repeat(64), recordId = 'b'.repeat(64), signalKey = 'c'.repeat(64);
const result = { schema_version: 'source-reception/2', request: { record_id: recordId, mode: 'single_source', source_index: 2, seed: 2026 }, layout: { xyzMm: [[1, 2, 3]] }, waveforms: { time_s: [0, 0.1], baseline: [1.252e-12, -9.13e-8] }, provenance: { threads: 1, source: 'validated-cache' }, qa: { residual: 1e-13 } };
async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'eeg-project-http-')); t.after(() => rm(root, { recursive: true, force: true }));
  const receipt = { id: randomUUID(), kind: 'source-reception', status: 'completed', key: signalKey, request: result.request, owners: ['browser-a'] }, tasks = [receipt];
  let savedReads = 0, rateCalls = 0;
  const scheduler = {
    session: req => ({ id: req.headers.cookie === 'browser=b' ? 'browser-b' : 'browser-a' }),
    rate: () => { rateCalls++; },
    own: (id, visitor, kind) => { const task = tasks.find(value => value.id === id && value.kind === kind && value.owners.includes(visitor.id)); if (!task) throw Object.assign(new Error('Not owned'), { status: 404 }); return task; },
    adapters: { 'source-reception': { savedResult: async () => { savedReads++; return structuredClone(result); } } },
  };
  const layout = { id: recordId, status: 'completed', dataset_id: 'cache', layout: { xyzMm: [[3.5, -7, 11]] }, region_count: 1, metrics: { field_relative: 0.95 } };
  const queue = { token, root, python: 'unused', runtime: { queueDirectory: root }, library: { get: async id => id === recordId ? layout : null } };
  const service = new ProjectService({ queue, scheduler, guard: createAccessPolicy().guard, send: sendJson, tokenMatches: (value, expected) => value === expected, bundle: async (_root, record) => ({ schema: 'eeg-reproducibility-bundle/1', record_id: record.id, record, original_record: { result: { request: { seed: 2026 }, fields: [1e-14] } } }) });
  const server = createServer(service.middleware((_req, res) => res.writeHead(404).end())); server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(async () => { service.close(); await service.flush(); const closed = once(server, 'close'); server.close(); server.closeAllConnections(); await closed; });
  const origin = `http://127.0.0.1:${server.address().port}`;
  async function call(path, { method = 'GET', key, body, browser = 'a', extraHeaders = {}, rawBody } = {}) {
    const options = { method, headers: { Origin: origin, Cookie: `browser=${browser}`, ...(method !== 'GET' ? { 'X-EEG-Compute-Token': token, 'Content-Type': 'application/json' } : {}), ...(key ? { 'X-EEG-Project-Key': key } : {}), ...extraHeaders } };
    if (method !== 'GET' && (rawBody !== undefined || body !== undefined)) options.body = rawBody ?? JSON.stringify(body);
    const response = await fetch(origin + path, options);
    return { status: response.status, headers: response.headers, data: await response.json() };
  }
  const created = await call('/api/projects', { method: 'POST', body: { title: 'Study', owner_name: 'Researcher' } });
  assert.equal(created.status, 201);
  return { service, call, ...created.data, tasks, receipt, getSavedReads: () => savedReads, getRateCalls: () => rateCalls };
}

void test('project API restores credentials across browsers and never lists private projects', async t => {
  const { call, project, access_key } = await fixture(t);
  assert.equal((await call('/api/projects')).status, 405);
  const restored = await call(`/api/projects/${project.id}`, { key: access_key, browser: 'b' });
  assert.equal(restored.status, 200); assert.equal(restored.data.role, 'owner'); assert.deepEqual(restored.data.project, project);
  assert.equal((await call(`/api/projects/${project.id}`)).status, 403);
  assert.equal((await call(`/api/projects/${project.id}?key=${access_key}`)).status, 400);
  assert.ok(!JSON.stringify(restored.data).includes(access_key)); assert.ok(!JSON.stringify(restored.data).includes('key_hash'));
});

void test('research export authenticates, preserves saved science and remains read-only for shared access', async t => {
  const { service, call, project, access_key, receipt, getSavedReads } = await fixture(t), path = `/api/projects/${project.id}`;
  await mkdir(join(service.queue.root, 'data'));
  await mkdir(join(service.queue.root, 'configs/runtime'), { recursive: true });
  await writeFile(join(service.queue.root, 'data/manifest.json'), JSON.stringify({ schema_version: 'eeglayoutlab-data-bundle/1', bundle_id: 'fixture-data' }));
  await writeFile(join(service.queue.root, 'configs/runtime/manifest.json'), JSON.stringify({ schema: 'eeglayoutlab-runtime-lock/1' }));
  const attached = await call(path + '/entries', { method: 'POST', key: access_key, body: { revision: 1, kind: 'source', receipt_id: receipt.id } });
  assert.equal(attached.status, 201);
  assert.equal((await call(path + '/export')).status, 403);
  const reads = getSavedReads(), exported = await call(path + '/export', { key: access_key });
  assert.equal(exported.status, 200); assert.equal(validateResearchDelivery(exported.data), true);
  assert.equal(exported.headers.get('cache-control'), 'no-store'); assert.match(exported.headers.get('content-disposition'), /attachment/);
  assert.deepEqual(JSON.parse(exported.data.files[1].content).payload, result);
  assert.equal(getSavedReads(), reads, 'Export accessed the old scientific cache again.');
  assert.ok(!JSON.stringify(exported.data).includes(access_key));
  const shared = await call(path + '/share', { method: 'POST', key: access_key, body: { revision: 2 } });
  assert.equal((await call(path + '/export', { key: shared.data.access_key, browser: 'b' })).status, 200);
  service.delivery.maximumBytes = 100;
  assert.equal((await call(path + '/export', { key: access_key })).status, 413);
  service.delivery.maximumBytes = 32 * 1024 * 1024;
  await call(path + '/revoke-share', { method: 'POST', key: access_key, body: { revision: 3 } });
  assert.equal((await call(path + '/export', { key: shared.data.access_key })).status, 403);
});

void test('project writes require policy, session token, bounded JSON and current revisions', async t => {
  const { call, project, access_key } = await fixture(t), path = `/api/projects/${project.id}`;
  assert.equal((await call(path, { method: 'PATCH', key: access_key, body: { revision: 1, title: 'Forbidden' }, extraHeaders: { 'X-EEG-Compute-Token': '' } })).status, 403);
  assert.equal((await call(path, { key: access_key, extraHeaders: { Origin: 'https://attacker.invalid' } })).status, 403);
  assert.equal((await call(path, { method: 'PATCH', key: access_key, rawBody: '{broken' })).status, 400);
  assert.equal((await call(path, { method: 'PATCH', key: access_key, body: { revision: 1, notes: 'x'.repeat(70000) } })).status, 413);
  assert.equal((await call(path, { method: 'PATCH', key: access_key, body: { revision: 1, title: 'Renamed' } })).status, 200);
  assert.equal((await call(path, { method: 'PATCH', key: access_key, body: { revision: 1, title: 'Stale' } })).status, 409);
  assert.equal((await call(path, { method: 'PATCH', key: access_key, body: { revision: 2, identity: { fake: true } } })).status, 400);
});

void test('shared credentials read but cannot edit, attach, remove or rotate sharing', async t => {
  const { call, project, access_key } = await fixture(t), path = `/api/projects/${project.id}`;
  const shared = await call(path + '/share', { method: 'POST', key: access_key, body: { revision: 1 } });
  assert.equal(shared.status, 200); const key = shared.data.access_key;
  assert.equal((await call(path, { key, browser: 'b' })).data.role, 'viewer');
  for (const operation of [{ suffix: '', method: 'PATCH', body: { revision: 2, title: 'Blocked' } }, { suffix: '/entries', method: 'POST', body: { revision: 2, kind: 'layout', record_id: recordId } }, { suffix: '/share', method: 'POST', body: { revision: 2 } }, { suffix: '/revoke-share', method: 'POST', body: { revision: 2 } }]) assert.equal((await call(path + operation.suffix, { method: operation.method, key, body: operation.body })).status, 403);
  assert.equal((await call(path + '/revoke-share', { method: 'POST', key: access_key, body: { revision: 2 } })).status, 200);
  assert.equal((await call(path, { key })).status, 403);
});

void test('saved source copies survive receipt pruning and cache loss with every scientific field intact', async t => {
  const { service, call, project, access_key, receipt, tasks, getSavedReads } = await fixture(t), path = `/api/projects/${project.id}`;
  const attached = await call(path + '/entries', { method: 'POST', key: access_key, body: { revision: 1, kind: 'source', receipt_id: receipt.id, title: 'Signal case' } });
  assert.equal(attached.status, 201); assert.equal(getSavedReads(), 1);
  tasks.length = 0; service.scheduler.adapters['source-reception'].savedResult = () => { throw new Error('Cache removed'); };
  const entry = await call(path + '/entries/' + attached.data.entry.id, { key: access_key, browser: 'b' });
  assert.equal(entry.status, 200); assert.deepEqual(entry.data.snapshot.payload, result);
  assert.equal(entry.data.entry.record_id, signalKey);
  assert.equal((await call(path + '/entries/' + attached.data.entry.id, { method: 'PATCH', key: access_key, body: { revision: 2, title: 'Renamed case', notes: 'Original values retained' } })).status, 200);
  assert.deepEqual((await call(path + '/entries/' + attached.data.entry.id, { key: access_key })).data.snapshot.payload, result);
});

void test('source attachment rejects foreign, incomplete or client-supplied scientific data before reading cache', async t => {
  const { call, project, access_key, receipt, getSavedReads } = await fixture(t), path = `/api/projects/${project.id}/entries`;
  const input = { revision: 1, kind: 'source', receipt_id: receipt.id };
  assert.equal((await call(path, { method: 'POST', key: access_key, browser: 'b', body: input })).status, 404);
  receipt.status = 'running'; assert.equal((await call(path, { method: 'POST', key: access_key, body: input })).status, 409);
  assert.equal((await call(path, { method: 'POST', key: access_key, body: { ...input, payload: result } })).status, 400);
  assert.equal(getSavedReads(), 0);
});

void test('layout attachment loads the trusted archive and detach retains original science', async t => {
  const { call, project, access_key } = await fixture(t), path = `/api/projects/${project.id}`;
  assert.equal((await call(path + '/entries', { method: 'POST', key: access_key, body: { revision: 1, kind: 'layout', record_id: 'd'.repeat(64) } })).status, 404);
  const attached = await call(path + '/entries', { method: 'POST', key: access_key, body: { revision: 1, kind: 'layout', record_id: recordId } });
  assert.equal(attached.status, 201);
  const saved = await call(path + '/entries/' + attached.data.entry.id, { key: access_key });
  assert.equal(saved.data.snapshot.payload.schema, 'eeg-reproducibility-bundle/1');
  assert.equal(saved.data.snapshot.payload.record.id, recordId);
  assert.equal((await call(path + '/entries/' + attached.data.entry.id, { method: 'DELETE', key: access_key, extraHeaders: { 'If-Match': '2' } })).status, 200);
  assert.deepEqual((await call(path, { key: access_key })).data.project.entries, []);
});
