import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { CommunityQueue, communityMiddleware } from '../server/community-queue.mjs';
import { ExecutionSlot } from '../server/jobs/execution-slot.mjs';

const kind = 'local-compute';
const visitor = { id: 'visitor', ip: '127.0.0.1' };
const cleanups = new WeakMap();
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};

function fixture(t, options = {}) {
  const directory = options.directory ?? mkdtempSync(join(tmpdir(), 'eeg-maintenance-'));
  const workers = new Map(), cache = new Map(), starts = [];
  const executionSlot = options.executionSlot ?? new ExecutionSlot();
  const adapter = {
    prepare: async request => ({ request, key: `v1-${request.n}` }),
    lookup: async prepared => cache.has(prepared.key) ? { hit: true, job: cache.get(prepared.key) } : { hit: false },
    start: async request => {
      const release = executionSlot.acquire(request.n);
      if (!release) return { busy: true, maintenance: executionSlot.paused };
      starts.push(request.n);
      const job = { id: randomUUID(), key: `v1-${request.n}`, request, status: 'running', result: null, release };
      workers.set(job.id, job);
      return { job };
    },
    get: id => workers.get(id),
    busy: () => [...workers.values()].some(job => ['running', 'cancelling'].includes(job.status)),
    pid: () => undefined,
    cancel: id => { workers.get(id).status = 'cancelling'; },
  };
  const q = new CommunityQueue({ directory, adapters: { [kind]: adapter }, pollMs: 3600000, maxPerVisitor: 10,
    ...options, executionSlot });
  if (!cleanups.has(t)) {
    const cleanup = { queues: [], directories: new Set() }; cleanups.set(t, cleanup);
    t.after(() => {
      for (const queue of cleanup.queues) queue.dispose();
      for (const path of cleanup.directories) rmSync(path, { recursive: true, force: true });
    });
  }
  cleanups.get(t).queues.push(q); cleanups.get(t).directories.add(directory);
  const finish = () => {
    const job = [...workers.values()].find(value => ['running', 'cancelling'].includes(value.status));
    job.status = job.status === 'cancelling' ? 'cancelled' : 'completed';
    job.result = { scientific: true };
    if (job.status === 'completed') cache.set(job.key, { ...job, cached: true });
    job.release();
  };
  return { q, adapter, directory, cache, workers, starts, executionSlot, finish };
}

void test('initial maintenance is durable and permits cache reads and lookup misses', async t => {
  const f = fixture(t, { initialMaintenance: true });
  assert.deepEqual(f.q.maintenanceStatus(), { maintenance: true, drained: true });
  assert.equal(f.executionSlot.paused, true);
  assert.equal(JSON.parse(readFileSync(join(f.directory, 'queue.json'))).maintenance, true);
  await assert.rejects(f.q.submit(kind, { n: 1 }, visitor), { status: 503 });
  assert.deepEqual(await f.q.submit(kind, { n: 1 }, visitor, true), { hit: false });
  f.cache.set('v1-2', { key: 'v1-2', status: 'completed', result: { n: 2 } });
  const cached = await f.q.submit(kind, { n: 2 }, visitor);
  assert.equal(cached.hit, true);
  assert.deepEqual((await f.q.view(f.q.own(cached.job.id, visitor))).result, { n: 2 });
  await f.q.tick();
  assert.deepEqual(f.starts, []);
});

void test('pause preserves pending IDs and FIFO order across restart until explicitly resumed', async t => {
  const f = fixture(t);
  const first = await f.q.submit(kind, { n: 1 }, visitor);
  const second = await f.q.submit(kind, { n: 2 }, visitor);
  const before = f.q.tasks.map(({ id, sequence }) => ({ id, sequence }));
  f.q.setMaintenance(true);
  await f.q.tick();
  assert.deepEqual(f.starts, []);
  const shared = await f.q.submit(kind, { n: 1 }, { ...visitor, id: 'second-visitor' });
  assert.equal(shared.job.id, first.job.id);
  f.q.dispose();
  const g = fixture(t, { directory: f.directory, initialMaintenance: false });
  assert.deepEqual(g.q.tasks.map(({ id, sequence }) => ({ id, sequence })), before);
  assert.equal(g.q.maintenance, true);
  assert.equal(g.executionSlot.paused, true);
  await g.q.tick(); assert.deepEqual(g.starts, []);
  assert.deepEqual(g.q.setMaintenance(false), { maintenance: false, drained: false });
  await g.q.tick(); assert.deepEqual(g.starts, [1]);
  g.finish(); await g.q.tick(); assert.deepEqual(g.starts, [1, 2]);
  assert.equal(g.q.own(second.job.id, visitor).status, 'running');
});

void test('maintenance waits for active cancellation and reconciles completion without dispatch', async t => {
  const f = fixture(t);
  const first = await f.q.submit(kind, { n: 1 }, visitor);
  const second = await f.q.submit(kind, { n: 2 }, visitor);
  const third = await f.q.submit(kind, { n: 3 }, visitor);
  await f.q.tick();
  assert.deepEqual(f.q.setMaintenance(true), { maintenance: true, drained: false });
  await f.q.cancel(third.job.id, visitor);
  assert.equal(f.q.own(third.job.id, visitor).status, 'cancelled');
  await f.q.cancel(first.job.id, visitor);
  await f.q.tick(); assert.equal(f.q.maintenanceStatus().drained, false);
  f.finish();
  assert.equal(f.q.maintenanceStatus().drained, false, 'terminal backend must first reconcile its receipt');
  await f.q.tick();
  assert.equal(f.q.own(first.job.id, visitor).status, 'cancelled');
  assert.equal(f.q.own(second.job.id, visitor).status, 'queued');
  assert.deepEqual(f.starts, [1]);
  assert.equal((await f.q.stats(visitor)).drained, true);
});

for (const stage of ['prepare', 'lookup']) {
  void test(`pause during submission ${stage} rejects new work after the await`, async t => {
    const f = fixture(t), entered = deferred(), release = deferred();
    const original = f.adapter[stage];
    f.adapter[stage] = async value => { entered.resolve(); await release.promise; return original(value); };
    const submission = f.q.submit(kind, { n: 1 }, visitor);
    await entered.promise;
    f.q.setMaintenance(true);
    release.resolve();
    await assert.rejects(submission, { status: 503 });
    assert.equal(f.q.tasks.length, 0); assert.deepEqual(f.starts, []);
  });
}

void test('a cache hit discovered after maintenance starts is still readable', async t => {
  const f = fixture(t), entered = deferred(), release = deferred();
  f.adapter.lookup = async () => {
    entered.resolve(); await release.promise;
    return { hit: true, job: { key: 'v1-1', status: 'completed', result: { scientific: true } } };
  };
  const submission = f.q.submit(kind, { n: 1 }, visitor);
  await entered.promise; f.q.setMaintenance(true); release.resolve();
  assert.equal((await submission).hit, true);
  assert.deepEqual(f.starts, []);
});

void test('pause during dispatch preparation leaves the queued task untouched', async t => {
  const f = fixture(t), entered = deferred(), release = deferred();
  const { job } = await f.q.submit(kind, { n: 1 }, visitor);
  const original = f.adapter.prepare;
  f.adapter.prepare = async request => { entered.resolve(); await release.promise; return original(request); };
  const dispatch = f.q.tick();
  await entered.promise; f.q.setMaintenance(true); release.resolve(); await dispatch;
  assert.equal(f.q.own(job.id, visitor).status, 'queued');
  assert.equal(f.q.tasks[0].starting, undefined); assert.deepEqual(f.starts, []);
});

void test('an external worker acquiring the slot during dispatch preparation keeps the task queued', async t => {
  const f = fixture(t), entered = deferred(), release = deferred();
  const { job } = await f.q.submit(kind, { n: 1 }, visitor);
  const original = f.adapter.prepare;
  f.adapter.prepare = async request => { entered.resolve(); await release.promise; return original(request); };
  const dispatch = f.q.tick();
  await entered.promise;
  const permit = f.executionSlot.acquire('external service');
  release.resolve(); await dispatch;
  assert.equal(f.q.own(job.id, visitor).status, 'queued'); assert.deepEqual(f.starts, []);
  permit();
});

void test('pause during service preparation releases the permit and restores the same queue position', async t => {
  const f = fixture(t), entered = deferred(), release = deferred();
  const first = await f.q.submit(kind, { n: 1 }, visitor);
  await f.q.submit(kind, { n: 2 }, visitor);
  const original = f.adapter.start;
  f.adapter.start = async request => {
    const permit = f.executionSlot.acquire(request.n);
    assert.equal(typeof permit, 'function');
    entered.resolve(); await release.promise;
    assert.equal(f.executionSlot.paused, true);
    permit(); return { busy: true, maintenance: true };
  };
  const dispatch = f.q.tick();
  await entered.promise;
  assert.equal(f.q.setMaintenance(true).drained, false);
  release.resolve(); await dispatch;
  const task = f.q.own(first.job.id, visitor);
  assert.equal(task.status, 'queued'); assert.equal(task.sequence, 1);
  assert.equal((await f.q.view(task)).queue_position, 1);
  assert.equal(f.q.maintenanceStatus().drained, true);
  f.adapter.start = original; f.q.setMaintenance(false); await f.q.tick();
  assert.deepEqual(f.starts, [1]);
});

void test('confirmed busy contention clears spawn intent and preserves FIFO through maintenance and restart', async t => {
  const f = fixture(t), entered = deferred(), release = deferred();
  const first = await f.q.submit(kind, { n: 1 }, visitor);
  const second = await f.q.submit(kind, { n: 2 }, visitor);
  f.adapter.start = async () => {
    entered.resolve(); await release.promise;
    assert.equal(f.executionSlot.busy, true);
    return { busy: true, maintenance: false };
  };
  const dispatch = f.q.tick();
  await entered.promise;
  const permit = f.executionSlot.acquire('competing direct submission');
  assert.equal(typeof permit, 'function');
  release.resolve(); await dispatch;
  const task = f.q.own(first.job.id, visitor);
  assert.equal(task.status, 'queued'); assert.equal(task.starting, undefined);
  assert.equal(task.workerPid, undefined); assert.equal(task.backendId, undefined);
  assert.equal((await f.q.view(task)).queue_position, 1);
  assert.equal(f.q.setMaintenance(true).drained, false);
  permit(); assert.equal(f.q.maintenanceStatus().drained, true);
  f.q.dispose();
  const g = fixture(t, { directory: f.directory });
  assert.deepEqual(g.q.maintenanceStatus(), { maintenance: true, drained: true });
  assert.equal((await g.q.stats(visitor)).recovery_blocked, false);
  assert.deepEqual(g.q.tasks.map(task => task.id), [first.job.id, second.job.id]);
  g.q.setMaintenance(false); await g.q.tick(); assert.deepEqual(g.starts, [1]);
  g.finish(); await g.q.tick(); assert.deepEqual(g.starts, [1, 2]);
});

void test('an ambiguous thrown start keeps its recovery guard through maintenance and restart', async t => {
  const f = fixture(t);
  await f.q.submit(kind, { n: 1 }, visitor);
  f.adapter.start = async () => { throw new Error('Launch outcome unknown'); };
  await f.q.tick();
  assert.equal(f.q.tasks[0].starting, true);
  assert.equal(f.q.setMaintenance(true).drained, false);
  f.q.dispose();
  const g = fixture(t, { directory: f.directory });
  assert.equal(g.q.maintenanceStatus().drained, false);
  assert.equal((await g.q.stats(visitor)).recovery_blocked, true);
});

void test('a worker launched before the pause stays tracked when start resolves afterwards', async t => {
  const f = fixture(t), entered = deferred(), release = deferred();
  const { job } = await f.q.submit(kind, { n: 1 }, visitor);
  const original = f.adapter.start;
  f.adapter.start = async request => { const value = await original(request); entered.resolve(); await release.promise; return value; };
  const dispatch = f.q.tick();
  await entered.promise; assert.equal(f.q.setMaintenance(true).drained, false);
  release.resolve(); await dispatch;
  assert.equal(f.q.own(job.id, visitor).status, 'running');
  assert.equal(f.q.maintenanceStatus().drained, false);
  f.finish(); await f.q.tick();
  assert.equal(f.q.own(job.id, visitor).status, 'completed');
  assert.equal(f.q.maintenanceStatus().drained, true);
});

void test('drained accounts for external backend activity, permits and uncertain worker guards', async t => {
  const f = fixture(t);
  const release = f.executionSlot.acquire('direct submission');
  f.q.setMaintenance(true);
  assert.equal(f.q.maintenanceStatus().drained, false);
  release(); assert.equal(f.q.maintenanceStatus().drained, true);
  const busy = f.adapter.busy;
  f.adapter.busy = () => true; assert.equal(f.q.maintenanceStatus().drained, false);
  f.adapter.busy = busy;
  f.q.blockedPids = [process.pid]; assert.equal(f.q.maintenanceStatus().drained, false);
  f.q.blockedPids = []; f.q.unconfirmedWorker = true;
  assert.equal(f.q.maintenanceStatus().drained, false);
  delete f.q.unconfirmedWorker;
  const task = f.q.receipt(kind, { key: 'v1-1', request: { n: 1 } }, visitor, 'failed');
  task.starting = true; assert.equal(f.q.maintenanceStatus().drained, false);
  delete task.starting; task.workerPid = process.pid;
  assert.equal(f.q.maintenanceStatus().drained, false);
  delete task.workerPid; assert.equal(f.q.maintenanceStatus().drained, true);
  f.q.dispose(); assert.equal(f.q.maintenanceStatus().drained, false);
});

void test('a failed maintenance write keeps all execution paused and reports unavailable', async t => {
  const f = fixture(t, { initialMaintenance: true });
  f.q.directory = join(f.directory, 'missing-directory');
  try { assert.throws(() => f.q.setMaintenance(false), { code: 'ENOENT' }); }
  finally { f.q.directory = f.directory; }
  assert.equal(f.q.maintenance, true); assert.equal(f.executionSlot.paused, true);
  assert.deepEqual(f.q.maintenanceStatus(), { maintenance: true, drained: false });
  assert.equal((await f.q.stats(visitor)).available, false);
  await assert.rejects(f.q.submit(kind, { n: 1 }, visitor), { status: 503 });
  assert.throws(() => f.q.setMaintenance(false), { status: 503 });
  assert.equal(JSON.parse(readFileSync(join(f.directory, 'queue.json'))).maintenance, true);
});

void test('legacy queue files default to running and invalid maintenance state preserves the file', t => {
  const f = fixture(t); f.q.dispose();
  const path = join(f.directory, 'queue.json');
  const state = JSON.parse(readFileSync(path)); delete state.maintenance;
  writeFileSync(path, JSON.stringify(state));
  const g = fixture(t, { directory: f.directory });
  assert.equal(g.q.maintenance, false); assert.equal(g.executionSlot.paused, false); g.q.dispose();
  state.maintenance = 'false'; const corrupt = JSON.stringify(state); writeFileSync(path, corrupt);
  assert.throws(() => new CommunityQueue({ directory: f.directory, adapters: {} }), /Unsupported queue state/);
  assert.equal(readFileSync(path, 'utf8'), corrupt);
});

for (const guard of ['live PID', 'uncertain start']) {
  void test(`paused restart with a ${guard} guard never reports drained`, async t => {
    const f = fixture(t);
    const { job } = await f.q.submit(kind, { n: 1 }, visitor);
    const task = f.q.own(job.id, visitor); task.status = 'running';
    if (guard === 'live PID') task.workerPid = process.pid;
    else task.starting = true;
    f.q.setMaintenance(true); f.q.dispose();
    const g = fixture(t, { directory: f.directory });
    assert.deepEqual(g.q.maintenanceStatus(), { maintenance: true, drained: false });
    assert.equal((await g.q.stats(visitor)).recovery_blocked, true);
    await g.q.tick(); assert.deepEqual(g.starts, []);
  });
}

void test('a rejected second queue owner cannot pause the existing execution slot', t => {
  const f = fixture(t);
  assert.throws(() => new CommunityQueue({ directory: f.directory, adapters: {},
    executionSlot: f.executionSlot, initialMaintenance: true }), /already owned/);
  assert.equal(f.executionSlot.paused, false);
  assert.throws(() => f.q.setMaintenance('true'), TypeError);
});

void test('public health shows maintenance but a public token cannot change it', async t => {
  const f = fixture(t, { initialMaintenance: true });
  const middleware = communityMiddleware({ scheduler: f.q,
    queue: { token: 'public-token', health: () => ({ token: 'public-token', available: true }) },
    guard: () => true, tokenMatches: (left, right) => left === right,
    send: (res, status, body) => { res.status = status; res.body = body; },
    legacy: (_req, res) => { res.status = 404; } });
  const call = async (url, method = 'GET') => {
    const res = { setHeader() {} };
    await middleware({ url, method, headers: { 'x-eeg-compute-token': 'public-token' } }, res, () => {});
    return res;
  };
  const health = await call('/api/local-compute/health');
  assert.equal(health.status, 200); assert.equal(health.body.maintenance, true); assert.equal(health.body.drained, true);
  const status = await call('/api/community/status'); assert.equal(status.body.maintenance, true);
  for (const url of ['/api/community/maintenance', '/api/local-compute/maintenance']) {
    assert.equal((await call(url, 'POST')).status, 404);
  }
  assert.equal(f.q.maintenance, true);
});
