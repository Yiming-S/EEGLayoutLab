import test from 'node:test';
import assert from 'node:assert/strict';
import { chmodSync, mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { CommunityQueue, RECEIPT_LIMITS, retainReceipts } from '../server/community-queue.mjs';
import { networkPrefix, networkId, NetworkWindow } from '../server/http/network-identity.mjs';
import { INTERNAL_MESSAGE, publicFailure, redactPaths, redactPayload } from '../server/http/public-errors.mjs';
import { Gate } from '../server/http/concurrency.mjs';
import { ProjectStore } from '../server/projects/store.mjs';
import { pythonFingerprint, runtimeIdentity } from '../server/runtime/python-fingerprint.mjs';

const later = [];
test.after(() => { for (const fn of later.reverse()) fn(); });
const temporary = prefix => { const path = mkdtempSync(join(tmpdir(), prefix)); later.push(() => rmSync(path, { recursive: true, force: true })); return path; };

function queue(options = {}) {
  const starts = [], workers = new Map(), caches = new Map();
  const adapter = {
    prepare: async r => ({ request: r, key: 'k-' + r.n }),
    lookup: async p => caches.has(p.key) ? { hit: true, job: caches.get(p.key) } : { hit: false },
    start: async r => { starts.push(r.n); const j = { id: randomUUID(), key: 'k-' + r.n, request: r, status: 'running' }; workers.set(j.id, j); return { job: j }; },
    get: id => workers.get(id), pid: () => undefined,
    busy: () => [...workers.values()].some(j => j.status === 'running'),
    cancel: () => {},
  };
  const directory = options.directory ?? temporary('eeg-abuse-');
  const q = new CommunityQueue({ directory, adapters: { 'local-compute': adapter }, pollMs: 3600000, ...options });
  later.push(() => q.dispose());
  return { q, adapter, starts, workers, caches, directory };
}
const browser = (id, ip) => ({ id, ip });

void test('client networks group IPv4 by address and IPv6 by /64', () => {
  assert.equal(networkPrefix('203.0.113.8'), 'v4:203.0.113.8');
  assert.equal(networkPrefix('::ffff:203.0.113.8'), 'v4:203.0.113.8');
  assert.equal(networkPrefix('2001:db8:1:2:aaaa::1'), 'v6:2001:db8:1:2');
  assert.equal(networkPrefix('2001:db8:1:2:ffff:ffff:ffff:ffff'), 'v6:2001:db8:1:2');
  assert.equal(networkPrefix('2001:db8::1'), 'v6:2001:db8:0:0');
  assert.equal(networkPrefix('fe80::1%en0'), 'v6:fe80:0:0:0');
  assert.equal(networkPrefix('unknown'), 'other:unknown');
  assert.equal(networkId('s', '2001:db8:1:2::5'), networkId('s', '2001:db8:1:2:9::9'));
  assert.notEqual(networkId('s', '2001:db8:1:3::5'), networkId('s', '2001:db8:1:2::5'));
  assert.notEqual(networkId('s', '203.0.113.8'), networkId('t', '203.0.113.8'));
  assert.match(networkId('s', '203.0.113.8'), /^[a-f0-9]{64}$/);
  let now = 0; const window = new NetworkWindow({ limit: 2, windowMs: 1000, message: 'slow', now: () => now });
  window.take('n'); window.take('n');
  assert.throws(() => window.take('n'), { status: 429 });
  window.take('other'); now = 1001; window.take('n');
});

void test('fresh cookies on one network share its pending-task cap', async () => {
  const { q } = queue({ maxPerNetwork: 2 });
  await q.submit('local-compute', { n: 1 }, browser('a', '2001:db8:1:2::1'));
  await q.submit('local-compute', { n: 2 }, browser('b', '2001:db8:1:2::2'));
  await assert.rejects(q.submit('local-compute', { n: 3 }, browser('c', '2001:db8:1:2::3')), { status: 429, message: /同一网络/ });
  // Joining a task already queued also counts against the joining network.
  await assert.rejects(q.submit('local-compute', { n: 1 }, browser('d', '2001:db8:1:2::4')), { status: 429 });
  await q.submit('local-compute', { n: 3 }, browser('e', '2001:db8:9:9::1'));
  const stored = JSON.parse(readFileSync(join(q.directory, 'queue.json'), 'utf8'));
  assert.ok(stored.tasks.every(task => task.networks.every(value => /^[a-f0-9]{64}$/.test(value))));
  assert.ok(!JSON.stringify(stored).includes('2001:db8'));
});

void test('the per-network request rate replaces the per-address rate', async () => {
  const { q } = queue();
  for (let i = 0; i < 100; i++) q.rate(browser('v' + i, `2001:db8:1:2::${i.toString(16)}`));
  assert.throws(() => q.rate(browser('w', '2001:db8:1:2::ffff')), { status: 429 });
  q.rate(browser('w', '2001:db8:1:3::1'));
});

void test('cache-hit receipts cannot push out computed receipts or other networks', () => {
  const limits = { computed: 3, cached: 4, cachedPerNetwork: 2 };
  let sequence = 0;
  const task = (cached, network, status = 'completed') => ({ id: randomUUID(), sequence: ++sequence, status, cached, owners: ['o'], networks: [network] });
  const computed = [task(false, 'x'), task(false, 'y'), task(false, 'x'), task(false, 'x')];
  const victims = [task(true, 'y'), task(true, 'z')];
  const flood = Array.from({ length: 50 }, () => task(true, 'attacker'));
  const queued = task(false, 'attacker', 'queued');
  const kept = retainReceipts([...computed, ...victims, queued, ...flood], limits);
  assert.deepEqual(kept.filter(t => !t.cached && t.status === 'completed'), computed.slice(-3));
  assert.ok(victims.every(t => kept.includes(t)));
  assert.equal(kept.filter(t => t.networks[0] === 'attacker' && t.cached).length, 2);
  assert.ok(kept.includes(queued));
  assert.deepEqual(RECEIPT_LIMITS, { computed: 1000, cached: 300, cachedPerNetwork: 40 });
});

void test('a lookup of a computed result keeps the computed receipt and writes nothing new', async () => {
  const { q, caches, directory } = queue();
  const owner = browser('a', '203.0.113.8');
  const { job } = await q.submit('local-compute', { n: 1 }, owner);
  await q.tick();
  const running = q.tasks.find(t => t.id === job.id);
  const backend = q.adapters['local-compute'].get(running.backendId);
  backend.status = 'completed'; backend.result = { ok: true };
  caches.set('k-1', { ...backend, cached: true, finished_at: '2026-11-20T00:00:00.000Z' });
  await q.tick();
  assert.equal(q.own(job.id, owner).cached, false);
  const before = readFileSync(join(directory, 'queue.json'), 'utf8');
  const hit = await q.submit('local-compute', { n: 1 }, owner, true);
  assert.equal(hit.hit, true); assert.equal(hit.job.id, job.id);
  // The reply says it replayed the saved result; the receipt stays in the computed pool.
  assert.equal(hit.job.cached, true); assert.equal(q.own(job.id, owner).cached, false);
  assert.equal(readFileSync(join(directory, 'queue.json'), 'utf8'), before);
  const other = await q.submit('local-compute', { n: 1 }, browser('b', '198.51.100.1'), true);
  assert.notEqual(other.job.id, job.id); assert.equal(q.own(other.job.id, browser('b')).cached, true);
});

void test('server faults are generic 500s and paths never reach visitors', () => {
  const quiet = console.error; console.error = () => {};
  try {
    const missing = Object.assign(new Error("ENOENT: no such file or directory, open '/srv/eeg/results/v2/current_multiregion_bank.json'"), { code: 'ENOENT' });
    assert.deepEqual(publicFailure(missing), { status: 500, message: INTERNAL_MESSAGE });
    assert.deepEqual(publicFailure(new TypeError('x is undefined')), { status: 500, message: INTERNAL_MESSAGE });
  } finally { console.error = quiet; }
  assert.equal(publicFailure(new SyntaxError('Unexpected token')).status, 400);
  assert.deepEqual(publicFailure(new Error('区域数只支持1、2、3、4、6')), { status: 400, message: '区域数只支持1、2、3、4、6' });
  assert.deepEqual(publicFailure(Object.assign(new Error('队列已满'), { status: 429 })), { status: 429, message: '队列已满' });
  assert.equal(redactPaths("FileNotFoundError: [Errno 2] No such file: '/Users/me/EEG/results/v2/x.npy'"), "FileNotFoundError: [Errno 2] No such file: '[server path]'");
  assert.equal(redactPaths('半径须为15–80 mm，步长5 mm'), '半径须为15–80 mm，步长5 mm');
  assert.equal(redactPaths('see http://127.0.0.1:3000/api and results/v2/heads'), 'see http://127.0.0.1:3000/api and results/v2/heads');
  const payload = redactPayload({ job: { message: '保存失败：EACCES /srv/eeg/queue/x.json', result: { file: '/keep/scientific/value' } }, warnings: ['bad /opt/eeg/file.json'] });
  assert.equal(payload.job.message, '保存失败：EACCES [server path]');
  assert.equal(payload.job.result.file, '/keep/scientific/value');
  assert.deepEqual(payload.warnings, ['bad [server path]']);
});

void test('heavy reads run two at a time and refuse a long wait line', async () => {
  const gate = new Gate({ limit: 2, waiting: 1 });
  let release; const held = new Promise(resolve => { release = resolve; });
  let active = 0, peak = 0;
  const work = () => gate.run(async () => { active++; peak = Math.max(peak, active); await held; active--; return true; });
  const running = [work(), work(), work()];
  await assert.rejects(work(), { status: 503, retryAfter: 5 });
  release(); assert.deepEqual(await Promise.all(running), [true, true, true]);
  assert.equal(peak, 2); assert.equal(gate.active, 0);
});

void test('a shutdown during a launch keeps the task queued instead of blocking restart', async () => {
  const f = queue();
  let enter, release;
  const entered = new Promise(resolve => { enter = resolve; }), released = new Promise(resolve => { release = resolve; });
  f.adapter.start = async () => { enter(); await released; throw new Error('本地服务正在重启'); };
  const owner = browser('a', '203.0.113.8');
  const { job } = await f.q.submit('local-compute', { n: 1 }, owner);
  const dispatch = f.q.tick();
  await entered; f.q.stopScheduling(); f.q.dispose();
  release(); await dispatch;
  const g = queue({ directory: f.directory });
  assert.equal(g.q.own(job.id, owner).status, 'queued');
  assert.equal((await g.q.stats(owner)).recovery_blocked, false);
  await g.q.tick(); assert.deepEqual(g.starts, [1]);
});

void test('a failed queue write stops new work until the disk accepts writes again', async () => {
  const { q, directory } = queue();
  const quiet = console.error; console.error = () => {};
  chmodSync(directory, 0o500);
  try {
    await assert.rejects(q.submit('local-compute', { n: 1 }, browser('a', '203.0.113.8')));
    assert.ok(q.failure);
    assert.ok(!readdirSync(directory).some(name => name.endsWith('.tmp')));
    await q.tick(); assert.ok(q.failure);
  } finally { chmodSync(directory, 0o700); console.error = quiet; }
  await q.tick(); assert.equal(q.failure, null);
  await q.submit('local-compute', { n: 2 }, browser('b', '203.0.113.9'));
});

void test('projects are capped per network; never-used empty projects are removed after a month', async () => {
  const root = temporary('eeg-projects-');
  let now = '2026-11-01T00:00:00.000Z';
  const store = new ProjectStore(join(root, 'projects'), { now: () => now });
  const input = { title: 'T', owner_name: 'R', notes: '' };
  const limit = 30;
  const made = [];
  for (let i = 0; i < limit; i++) made.push(await store.create(input, { network: 'a'.repeat(64) }));
  await assert.rejects(store.create(input, { network: 'a'.repeat(64) }), { status: 429 });
  await store.create(input, { network: 'b'.repeat(64) });
  const kept = await store.patch(made[0].project.id, made[0].access_key, { revision: 1, notes: 'edited' });
  assert.equal(kept.project.revision, 2);
  now = '2026-12-15T00:00:00.000Z';
  await store.create(input, { network: 'a'.repeat(64) });
  const ids = readdirSync(store.directory);
  assert.ok(ids.includes(made[0].project.id));
  assert.ok(!ids.includes(made[1].project.id));
  const stored = JSON.parse(readFileSync(join(store.directory, made[0].project.id, 'project.json'), 'utf8'));
  assert.equal(stored.creator_network, 'a'.repeat(64));
  assert.equal(JSON.stringify((await store.get(made[0].project.id, made[0].access_key)).project).includes('creator_network'), false);
});

void test('cache keys carry the interpreter identity off macOS only', () => {
  let calls = 0;
  const run = () => { calls++; return 'noise\n{"machine": "x86_64", "numpy": "2.1.0", "python": "3.11.9", "scipy": "1.14.1", "system": "Linux"}\n'; };
  const value = pythonFingerprint('/opt/fake/python-a', run);
  assert.deepEqual(value, { machine: 'x86_64', numpy: '2.1.0', python: '3.11.9', scipy: '1.14.1', system: 'Linux' });
  pythonFingerprint('/opt/fake/python-a', run); assert.equal(calls, 1);
  assert.deepEqual(pythonFingerprint('/opt/fake/python-b', () => { throw new Error('missing'); }), { python: null });
  assert.equal(runtimeIdentity('/opt/fake/python-a', 'darwin'), null);
  assert.deepEqual(runtimeIdentity('/opt/fake/python-a', 'linux'), value);
});
