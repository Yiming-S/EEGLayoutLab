import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer, request } from 'node:http';
import { once } from 'node:events';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { createLocalComputeService } from '../server/local-compute-server.mjs';
import { ResourceGate } from '../server/operations/resource-gate.mjs';
import { operationsConfig } from '../server/operations/config.mjs';

const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const key = n => createHash('sha256').update(`synthetic-policy-fixture-${n}`).digest('hex');
async function fixture(t, options = {}) {
  const root = await mkdtemp(join(tmpdir(), 'eeg-product-operations-'));
  let lowDisk = false, admissionCalls = 0;
  const gate = new ResourceGate({ config: operationsConfig({}), directories: [{ scope: 'queue', path: root }, { scope: 'scientific', path: root }], memoryUsage: () => ({ rss: 128 * 1024 * 1024 }), statfs: async () => ({ bsize: 1024n, bavail: lowDisk ? 1n : 1024n * 1024n }) });
  const assertAvailable = gate.assertAvailable.bind(gate);
  gate.assertAvailable = async () => { admissionCalls++; return options.admit ? options.admit(assertAvailable) : assertAvailable(); };
  const service = createLocalComputeService(root, { getIdentity: () => ({}), verifyInputs: () => {}, resourceGate: gate });
  clearInterval(service.scheduler.timer);
  const starts = [], jobs = new Map(), cache = new Map(); let prepares = 0;
  const adapter = {
    async prepare(raw) { prepares++; if (!raw || !Number.isInteger(raw.n)) throw new Error('Invalid fixture'); return { request: { n: raw.n }, key: key(raw.n) }; },
    async lookup(prepared) { return cache.has(prepared.key) ? { hit: true, job: cache.get(prepared.key) } : { hit: false }; },
    async start(raw) { starts.push(raw.n); const job = { id: randomUUID(), key: key(raw.n), request: raw, status: 'completed', result: { numerical_values: [raw.n, 1.23456789012345e-12], provenance: { unchanged: true } }, progress: 1 }; jobs.set(job.id, job); cache.set(job.key, job); return { job }; },
    get: id => jobs.get(id), busy: () => false, pid: () => undefined, cancel: id => { const job = jobs.get(id); if (job) job.status = 'cancelled'; },
  };
  service.scheduler.adapters['local-compute'] = adapter;
  cache.set(key(0), { id: randomUUID(), key: key(0), request: { n: 0 }, status: 'completed', result: { numerical_values: [0, 1.23456789012345e-12], provenance: { unchanged: true } }, cached: true });
  service.queue.library.list = async () => ({ schema: 'local-data-library/1', records: [] });
  const server = createServer((req, res) => { void service.middleware(req, res, () => { res.writeHead(404).end(); }); });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const base = `http://127.0.0.1:${server.address().port}`, cookies = new Map();
  async function call(path, { method = 'GET', body, access, headers = {} } = {}) {
    const response = await fetch(base + path, { method, headers: { Origin: base, ...(cookies.size ? { Cookie: [...cookies].map(([name, value]) => `${name}=${value}`).join('; ') } : {}), ...(method !== 'GET' ? { 'Content-Type': 'application/json', 'X-EEG-Compute-Token': token } : {}), ...(access ? { 'X-EEG-Project-Key': access } : {}), ...headers }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    for (const cookie of response.headers.getSetCookie()) { const pair = cookie.split(';')[0], split = pair.indexOf('='); cookies.set(pair.slice(0, split), pair.slice(split + 1)); }
    return { status: response.status, headers: response.headers, data: await response.json() };
  }
  const token = (await call('/api/local-compute/health')).data.token;
  t.after(async () => { const closed = once(server, 'close'); server.close(); server.closeAllConnections(); await closed; await service.dispose(); await rm(root, { recursive: true, force: true }); });
  return { root, base, service, call, starts, jobs, cache, low: value => { lowDisk = value; }, admissionCalls: () => admissionCalls, prepares: () => prepares };
}
function operator(base, headers = {}) {
  return new Promise((resolve, reject) => { const req = request(base + '/api/operations/status', { headers }, res => { const chunks = []; res.on('data', chunk => chunks.push(chunk)); res.on('end', () => resolve({ status: res.statusCode, data: JSON.parse(Buffer.concat(chunks)) })); }); req.on('error', reject); req.end(); });
}

void test('actual service refuses new uncached work and project writes while preserving cached jobs, lookup, reads and cancellation', async t => {
  const f = await fixture(t);
  const created = await f.call('/api/projects', { method: 'POST', body: { title: 'Resource test', owner_name: 'Researcher' } }); assert.equal(created.status, 201);
  const queued = await f.call('/api/local-compute/jobs', { method: 'POST', body: { n: 1 } }); assert.equal(queued.status, 202); assert.equal(queued.data.job.status, 'queued');
  f.low(true);
  const failed = await f.call('/api/local-compute/jobs', { method: 'POST', body: { n: 2 } }); assert.equal(failed.status, 503); assert.equal(failed.headers.get('retry-after'), '30'); assert.equal(failed.data.code, 'resource_unavailable');
  const calls = f.admissionCalls();
  const replay = await f.call('/api/local-compute/jobs', { method: 'POST', body: { n: 0 } }); assert.equal(replay.status, 202); assert.equal(replay.data.job.status, 'completed');
  assert.deepEqual(replay.data.job.result.numerical_values, [0, 1.23456789012345e-12]);
  const lookup = await f.call('/api/local-compute/lookup', { method: 'POST', body: { n: 0 } }); assert.equal(lookup.status, 200); assert.equal(lookup.data.hit, true);
  const miss = await f.call('/api/local-compute/lookup', { method: 'POST', body: { n: 3 } }); assert.equal(miss.status, 200); assert.equal(miss.data.hit, false);
  assert.equal(f.admissionCalls(), calls);
  assert.equal((await f.call('/api/local-compute/library')).status, 200);
  assert.equal((await f.call(`/api/projects/${created.data.project.id}`, { access: created.data.access_key })).status, 200);
  const patched = await f.call(`/api/projects/${created.data.project.id}`, { method: 'PATCH', access: created.data.access_key, body: { revision: 1, title: 'Not admitted' } }); assert.equal(patched.status, 503); assert.equal(patched.data.code, 'resource_unavailable');
  assert.equal((await f.call(`/api/projects/${created.data.project.id}`, { access: created.data.access_key })).data.project.title, 'Resource test');
  assert.equal((await f.call(`/api/local-compute/jobs/${queued.data.job.id}/cancel`, { method: 'POST' })).data.job.status, 'cancelled');
  assert.deepEqual(f.starts, []); assert.equal(f.service.scheduler.failure, undefined);
});

void test('resource-blocked dispatch preserves FIFO and queue bytes until recovery or cancellation', async t => {
  const f = await fixture(t);
  const first = await f.call('/api/local-compute/jobs', { method: 'POST', body: { n: 1 } }), second = await f.call('/api/local-compute/jobs', { method: 'POST', body: { n: 2 } });
  const path = join(f.service.scheduler.directory, 'queue.json'), before = await readFile(path, 'utf8');
  f.low(true); await f.service.scheduler.tick(); const preparedAtBlock = f.prepares();
  await f.service.scheduler.tick(); assert.equal(f.prepares(), preparedAtBlock); assert.equal(await readFile(path, 'utf8'), before);
  assert.deepEqual(f.service.scheduler.tasks.map(task => task.status), ['queued', 'queued']); assert.equal(f.service.scheduler.failure, undefined);
  await f.call(`/api/local-compute/jobs/${first.data.job.id}/cancel`, { method: 'POST' });
  f.low(false); await f.service.scheduler.tick(); assert.deepEqual(f.starts, [2]);
  await f.service.scheduler.tick();
  const completed = await f.call(`/api/local-compute/jobs/${second.data.job.id}`); assert.equal(completed.data.job.status, 'completed'); assert.deepEqual(completed.data.job.result.numerical_values, [2, 1.23456789012345e-12]);
});

void test('maintenance requested during asynchronous admission prevents late receipt acceptance', async t => {
  const entered = deferred(), release = deferred();
  const f = await fixture(t, { admit: async normal => { entered.resolve(); await release.promise; return normal(); } });
  const submitting = f.call('/api/local-compute/jobs', { method: 'POST', body: { n: 1 } });
  await entered.promise; f.service.scheduler.setMaintenance(true); release.resolve();
  assert.equal((await submitting).status, 503); assert.equal(f.service.scheduler.tasks.length, 0); assert.deepEqual(f.starts, []);
});

void test('maintenance requested during dispatch admission preserves queued state without a worker launch', async t => {
  let hold = false; const entered = deferred(), release = deferred();
  const f = await fixture(t, { admit: async normal => { if (hold) { entered.resolve(); await release.promise; } return normal(); } });
  await f.call('/api/local-compute/jobs', { method: 'POST', body: { n: 1 } });
  hold = true; const dispatch = f.service.scheduler.tick(); await entered.promise; f.service.scheduler.setMaintenance(true); release.resolve(); await dispatch;
  assert.equal(f.service.scheduler.tasks[0].status, 'queued'); assert.deepEqual(f.starts, []); assert.equal(f.service.scheduler.failure, undefined);
});

void test('actual request IDs and task correlation are logged without credentials or scientific payloads', async t => {
  const f = await fixture(t);
  const cached = await f.call('/api/local-compute/jobs', { method: 'POST', body: { n: 0 }, headers: { 'X-EEG-Request-Id': 'SECRET_REQUEST', 'X-EEG-Project-Key': 'SECRET_PROJECT', Authorization: 'SECRET_AUTH' } });
  const trace = cached.headers.get('x-eeg-request-id'); assert.match(trace, /^[a-f0-9-]{36}$/); assert.notEqual(trace, 'SECRET_REQUEST');
  await f.service.operations.flush();
  const directory = join(f.service.scheduler.directory, 'operations'), names = await readdir(directory), text = (await Promise.all(names.map(name => readFile(join(directory, name), 'utf8')))).join('');
  assert.ok(!text.includes('SECRET_')); assert.ok(!text.includes('numerical_values')); assert.ok(!text.includes(f.service.queue.token));
  const found = text.trim().split('\n').map(line => JSON.parse(line)).find(row => row.request_id === trace);
  assert.equal(found.task_id, cached.data.job.id); assert.equal(found.task_status, 'completed');
  assert.equal((await operator(f.base)).status, 200);
  assert.equal((await operator(f.base, { Origin: f.base, 'X-EEG-Compute-Token': f.service.queue.token })).status, 403);
  assert.equal((await operator(f.base, { 'X-Forwarded-For': '203.0.113.1' })).status, 403);
});

void test('service disposal waits for accepted project writes and log flushing before releasing its queue lock', async t => {
  const f = await fixture(t), created = await f.call('/api/projects', { method: 'POST', body: { title: 'Flush test', owner_name: 'Researcher' } });
  await f.service.operations.flush();
  const entered = deferred(), releaseWrite = deferred(), logEntered = deferred(), releaseLog = deferred();
  const save = f.service.projects.store.save.bind(f.service.projects.store);
  f.service.projects.store.save = async record => { entered.resolve(); await releaseWrite.promise; return save(record); };
  const logger = f.service.operations.logger, append = logger.append.bind(logger);
  logger.append = async record => { logEntered.resolve(); await releaseLog.promise; return append(record); };
  const updating = f.call(`/api/projects/${created.data.project.id}`, { method: 'PATCH', access: created.data.access_key, body: { revision: 1, title: 'Accepted before stop' } });
  await entered.promise;
  const disposing = f.service.dispose(); assert.ok(disposing instanceof Promise); assert.equal(f.service.dispose(), disposing);
  await new Promise(resolve => setImmediate(resolve)); assert.equal(existsSync(f.service.scheduler.lockPath), true);
  releaseWrite.resolve(); await logEntered.promise; assert.equal(existsSync(f.service.scheduler.lockPath), true);
  releaseLog.resolve(); await disposing; assert.equal(existsSync(f.service.scheduler.lockPath), false);
  assert.equal((await updating).status, 200);
  assert.equal((await f.service.projects.store.get(created.data.project.id, created.data.access_key)).project.title, 'Accepted before stop');
});

void test('shutdown during asynchronous admission cannot persist a late queued task or project', async t => {
  let hold = true; const entered = deferred(), release = deferred();
  const f = await fixture(t, { admit: async normal => { if (hold) { entered.resolve(); await release.promise; } return normal(); } });
  const submitting = f.call('/api/local-compute/jobs', { method: 'POST', body: { n: 1 } }); await entered.promise;
  await f.service.dispose(); const queuePath = join(f.service.scheduler.directory, 'queue.json'), stopped = await readFile(queuePath, 'utf8');
  assert.equal(existsSync(f.service.scheduler.lockPath), false); hold = false; release.resolve();
  assert.equal((await submitting).status, 503); assert.equal(f.service.scheduler.tasks.length, 0); assert.equal(await readFile(queuePath, 'utf8'), stopped); assert.deepEqual(f.starts, []);
});
