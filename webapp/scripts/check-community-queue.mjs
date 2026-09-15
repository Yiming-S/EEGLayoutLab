import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { CommunityQueue, communityMiddleware } from '../server/community-queue.mjs';
import { loopbackRequest } from '../server/local-compute-server.mjs';
import { createServer } from 'node:http';

const visitor = n => ({ id: n, ip: '127.0.0.1' });
function fixture(t, options = {}) {
  const directory = options.directory || mkdtempSync(join(tmpdir(), 'eeg-queue-test-'));
  const starts = [], adapters = {}, workers = {}, caches = {};
  let revision = 'v1';
  for (const kind of ['local-compute', 'source-reception', 'design-evaluation', 'electrode-editor']) {
    workers[kind] = new Map(); caches[kind] = new Map();
    adapters[kind] = {
      prepare: async r => { if (!r || !Number.isInteger(r.n)) throw new Error('invalid'); return { request: r, key: revision + '-' + r.n }; },
      lookup: async p => caches[kind].has(p.key) ? { hit: true, job: caches[kind].get(p.key) } : { hit: false },
      start: async r => {
        starts.push(kind + ':' + r.n);
        const j = { id: randomUUID(), key: revision + '-' + r.n, request: r, status: 'running', result: null };
        workers[kind].set(j.id, j); return { job: j };
      },
      get: id => workers[kind].get(id),
      pid: () => undefined,
      busy: () => [...workers[kind].values()].some(j => ['running', 'cancelling'].includes(j.status)),
      cancel: id => { workers[kind].get(id).status = 'cancelling'; },
    };
  }
  const q = new CommunityQueue({ directory, adapters, pollMs: 3600000, ...options });
  t.after(() => q.dispose());
  const finish = kind => {
    const j = [...workers[kind].values()].find(j => ['running', 'cancelling'].includes(j.status));
    j.status = j.status === 'cancelling' ? 'cancelled' : 'completed'; j.result = { scientific: true };
    if (j.status === 'completed') caches[kind].set(j.key, { ...j, cached: true });
  };
  return { q, directory, starts, adapters, workers, caches, finish, change: () => { revision = 'v2'; } };
}

void test('all four services share one persistent FIFO slot; timeout starts in the worker', async t => {
  const f = fixture(t);
  for (const [i, kind] of Object.keys(f.adapters).entries()) await f.q.submit(kind, { n: i }, visitor('v' + i));
  assert.deepEqual(f.starts, []);
  assert.equal(JSON.parse(readFileSync(join(f.directory, 'queue.json'))).tasks.length, 4);
  await f.q.tick(); assert.deepEqual(f.starts, ['local-compute:0']);
  await f.q.tick(); assert.equal(f.starts.length, 1);
  for (const kind of Object.keys(f.adapters)) { f.finish(kind); await f.q.tick(); }
  assert.deepEqual(f.starts, ['local-compute:0', 'source-reception:1', 'design-evaluation:2', 'electrode-editor:3']);
  assert.equal((await f.q.stats(visitor('v0'))).running_tasks, 0);
});
void test('exact pending keys share work; one subscriber cannot cancel the others', async t => {
  const f = fixture(t), a = visitor('a'), b = visitor('b');
  const first = await f.q.submit('local-compute', { n: 1 }, a);
  const second = await f.q.submit('local-compute', { n: 1 }, b);
  assert.equal(first.job.id, second.job.id);
  await f.q.cancel(first.job.id, a, 'local-compute');
  assert.throws(() => f.q.own(first.job.id, a), /not|不属于/);
  assert.equal(f.q.own(first.job.id, b).status, 'queued');
  await f.q.tick(); assert.equal(f.starts.length, 1);
});
void test('completed cache bypasses a busy worker and repeated lookup reuses a receipt', async t => {
  const f = fixture(t), v = visitor('v');
  f.caches['source-reception'].set('v1-2', { key: 'v1-2', status: 'completed', result: { cached: 1 }, cached: true });
  await f.q.submit('local-compute', { n: 1 }, v); await f.q.tick();
  const a = await f.q.submit('source-reception', { n: 2 }, v, true);
  const b = await f.q.submit('source-reception', { n: 2 }, v, true);
  assert.equal(a.job.id, b.job.id); assert.deepEqual(a.job.result, { cached: 1 }); assert.equal(f.starts.length, 1);
});
void test('queued cancellation advances; running cancellation waits for actual close; cancelling is not shared', async t => {
  const f = fixture(t), v = visitor('v');
  const a = await f.q.submit('local-compute', { n: 1 }, v);
  const b = await f.q.submit('source-reception', { n: 2 }, v);
  await f.q.cancel(a.job.id, v); await f.q.tick();
  assert.deepEqual(f.starts, ['source-reception:2']);
  await f.q.cancel(b.job.id, v);
  const c = await f.q.submit('source-reception', { n: 2 }, v);
  assert.notEqual(c.job.id, b.job.id);
  await f.q.tick(); assert.equal(f.starts.length, 1);
  f.finish('source-reception'); await f.q.tick(); assert.equal(f.starts.length, 2);
});
void test('queued receipt survives restart and changed scientific identity fails without starting', async t => {
  const f = fixture(t), v = visitor('v');
  const { job } = await f.q.submit('electrode-editor', { n: 1 }, v);
  f.q.dispose();
  const g = fixture(t, { directory: f.directory });
  assert.equal(g.q.own(job.id, v).status, 'queued');
  g.change(); await g.q.tick(); assert.equal(g.q.own(job.id, v).status, 'failed'); assert.equal(g.starts.length, 0);
});
void test('queued receipt executes after clean restart and same-key pending lookup restores it', async t => {
  const f = fixture(t), v = visitor('v');
  const { job } = await f.q.submit('design-evaluation', { n: 4 }, v); f.q.dispose();
  const g = fixture(t, { directory: f.directory });
  const found = await g.q.submit('design-evaluation', { n: 4 }, v, true);
  assert.equal(found.job.id, job.id); await g.q.tick(); assert.deepEqual(g.starts, ['design-evaluation:4']);
});
void test('worker PID blocks consecutive restarts; an unconfirmed spawn fails closed', async t => {
  const f = fixture(t), v = visitor('v');
  await f.q.submit('local-compute', { n: 1 }, v);
  const task = f.q.tasks[0]; task.status = 'running'; task.workerPid = process.pid; f.q.dispose();
  const g = fixture(t, { directory: f.directory });
  await g.q.tick(); assert.equal((await g.q.stats(v)).recovery_blocked, true); g.q.dispose();
  const h = fixture(t, { directory: f.directory });
  await h.q.tick(); assert.equal((await h.q.stats(v)).recovery_blocked, true); assert.equal(h.starts.length, 0); h.q.dispose();
  const disk = JSON.parse(readFileSync(join(f.directory, 'queue.json'))); delete disk.tasks[0].workerPid; disk.tasks[0].starting = true;
  writeFileSync(join(f.directory, 'queue.json'), JSON.stringify(disk));
  const k = fixture(t, { directory: f.directory });
  assert.equal((await k.q.stats(v)).recovery_blocked, true);
});
void test('one live owner prevents a second scheduler; invalid queue JSON is not overwritten', t => {
  const f = fixture(t);
  assert.throws(() => new CommunityQueue({ directory: f.directory, adapters: f.adapters }), /already owned/);
  f.q.dispose(); writeFileSync(join(f.directory, 'queue.json'), 'corrupt');
  assert.throws(() => new CommunityQueue({ directory: f.directory, adapters: f.adapters }));
  assert.equal(readFileSync(join(f.directory, 'queue.json'), 'utf8'), 'corrupt');
});
void test('per-browser and global queue bounds, invalid inputs, and unknown ownership', async t => {
  const f = fixture(t, { maxQueued: 4 }), v = visitor('v');
  for (let n = 0; n < 3; n++) await f.q.submit('local-compute', { n }, v);
  await assert.rejects(f.q.submit('local-compute', { n: 4 }, v), { status: 429 });
  await f.q.submit('local-compute', { n: 5 }, visitor('b'));
  await assert.rejects(f.q.submit('local-compute', { n: 6 }, visitor('c')), { status: 429 });
  await assert.rejects(f.q.submit('local-compute', { n: 'bad' }, v));
  assert.throws(() => f.q.own(f.q.tasks[0].id, visitor('stranger')), { status: 404 });
});
void test('online estimates deduplicate a browser and expire at 90 seconds; cookies survive restart', t => {
  let now = Date.now(); const f = fixture(t, { now: () => now });
  let header; const req = { headers: {}, socket: { remoteAddress: '127.0.0.1' } }, res = { setHeader: (_, v) => { header = v; } };
  const a = f.q.session(req, res), cookie = header.split(';')[0];
  assert.match(header, /HttpOnly; SameSite=Strict/);
  assert.equal(f.q.session({ ...req, headers: { cookie } }, res).id, a.id);
  f.q.touch(a, true); f.q.touch(a, true); assert.equal(f.q.visitors.size, 1);
  now += 90001; f.q.touch(a, false); assert.equal(f.q.visitors.size, 0);
  f.q.dispose(); const g = fixture(t, { directory: f.directory });
  assert.equal(g.q.session({ ...req, headers: { cookie } }, res).id, a.id);
});
void test('HTTP enforces same-origin, token, cookie ownership; stats never expose IP or other receipts', async t => {
  const f = fixture(t);
  const send = (res, status, body) => { res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); };
  const queue = { token: 'token', health: () => ({ available: true, token: 'token' }) };
  const middleware = communityMiddleware({ scheduler: f.q, queue, guard: loopbackRequest, send,
    tokenMatches: (a, b) => a === b, legacy: (_req, res) => send(res, 404, {}) });
  const server = createServer((req, res) => { void middleware(req, res, () => send(res, 404, {})); });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  t.after(() => server.close());
  const url = `http://127.0.0.1:${server.address().port}`;
  const h = await fetch(url + '/api/local-compute/health'); const cookie = h.headers.get('set-cookie').split(';')[0];
  const headers = { cookie, 'x-eeg-compute-token': 'token', 'Content-Type': 'application/json' };
  const response = await fetch(url + '/api/local-compute/jobs', { method: 'POST', headers, body: '{"n":1}' });
  assert.equal(response.status, 202); const { job } = await response.json();
  assert.equal((await fetch(url + '/api/local-compute/jobs/' + job.id)).status, 404);
  assert.equal((await fetch(url + '/api/local-compute/jobs/' + job.id, { headers: { cookie } })).status, 200);
  assert.equal((await fetch(url + '/api/local-compute/jobs', { method: 'POST', headers: { cookie }, body: '{}' })).status, 403);
  assert.equal((await fetch(url + '/api/local-compute/health', { headers: { origin: 'http://evil.example' } })).status, 403);
  const publicStatus = await fetch(url + '/api/community/status').then(r => r.json());
  assert.deepEqual(publicStatus.jobs, []); assert.ok(!JSON.stringify(publicStatus).includes('127.0.0.1'));
  const own = await fetch(url + '/api/community/status', { headers: { cookie } }).then(r => r.json());
  assert.equal(own.jobs[0].id, job.id);
});

void test('backend key mismatch is cancelled and never presented as an old-key result', async t => {
  const f = fixture(t), v = visitor('v');
  const start = f.adapters['local-compute'].start;
  f.adapters['local-compute'].start = async r => { const out = await start(r); out.job.key = 'changed'; return out; };
  const { job } = await f.q.submit('local-compute', { n: 1 }, v);
  await f.q.tick(); assert.equal(f.q.own(job.id, v).status, 'failed');
  assert.equal([...f.workers['local-compute'].values()][0].status, 'cancelling');
});
void test('dispose during identity preparation cannot enqueue or launch a late task', async t => {
  const f = fixture(t); let release;
  const started = new Promise(resolve => { release = resolve; });
  f.adapters['local-compute'].prepare = async request => { await started; return { request, key: 'v1-1' }; };
  const request = f.q.submit('local-compute', { n: 1 }, visitor('v'));
  await new Promise(resolve => setImmediate(resolve)); f.q.dispose(); release();
  await assert.rejects(request, { status: 503 });
  assert.equal(f.starts.length, 0); assert.equal(f.q.tasks.length, 0);
});
void test('old IP logs expire and rate-limited visitors can still inspect status', async t => {
  let now = Date.now(); const f = fixture(t, { now: () => now }), v = visitor('v');
  f.q.touch(v, true); const oldDay = new Date(now).toISOString().slice(0, 10);
  now += 8 * 86400000; f.q.pruneLogs();
  assert.throws(() => readFileSync(join(f.directory, 'access', oldDay + '.jsonl')), { code: 'ENOENT' });
  for (let i = 0; i < 20; i++) await f.q.submit('local-compute', { n: 1 }, v, true);
  await assert.rejects(f.q.submit('local-compute', { n: 1 }, v, true), { status: 429 });
  assert.equal((await f.q.stats(v)).queued_tasks, 0);
});
