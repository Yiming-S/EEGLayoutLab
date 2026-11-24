import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { CommunityQueue, communityMiddleware } from '../server/community-queue.mjs';
import { COMMUNITY_HEARTBEAT_PATH, COMMUNITY_STATUS_PATH, REQUEST_TIMEOUT_MS, fetchCommunityStatus, hasVisitorCounts,
  readCommunityStatus, refreshCommunityStatus } from '../components/community-status-model.ts';

// The two shapes of GET /api/community/status: the Python service's workspace queue, and the Node host's scheduler,
// which adds its visitor count.
const job = { id: '6f1c2b8e-3d4a-4f5b-9c6d-7e8f9a0b1c2d', key: 'a'.repeat(64), kind: 'local-compute', status: 'queued',
  created_at: '2026-11-23T08:00:00.000Z', finished_at: null, queue_position: 1, message: '已加入计算队列', progress: 0,
  cached: false, request: { region_count: 1, radius_mm: 15, mode: 'whole_surface' }, catalog: {} };
const python = { queued_tasks: 1, running_tasks: 0, available: true, resource_blocked: false, recovery_blocked: false,
  maintenance: false, drained: false, jobs: [job] };
const node = { online_visitors: 2, ...python };
const reply = (value, status = 200) => ({ ok: status < 400, status, json: async () => value });
const nativeFetch = globalThis.fetch;

void test('the task menu reads both status shapes and counts visitors only when the host does', () => {
  assert.deepEqual(readCommunityStatus(python), python);
  assert.deepEqual(readCommunityStatus(node), node);
  assert.equal(hasVisitorCounts(readCommunityStatus(python)), false);
  assert.equal(hasVisitorCounts(readCommunityStatus(node)), true);
  assert.equal(hasVisitorCounts(readCommunityStatus({ ...node, online_visitors: 0 })), true);
  assert.equal(hasVisitorCounts(null), false);
});

void test('an answer the menu cannot show is not a status', () => {
  for (const value of [null, [], 'text', { ...python, jobs: null }, { ...python, queued_tasks: -1 },
    { ...python, running_tasks: 0.5 }, { ...python, available: 'yes' }, { ...python, recovery_blocked: undefined },
    { ...python, jobs: [{ ...job, id: 7 }] }, { ...python, jobs: [null] }, { ...node, online_visitors: '2' }]) {
    assert.equal(readCommunityStatus(value), null, JSON.stringify(value));
  }
});

void test('the status route is read with a plain GET: no token, no heartbeat, no visibility header', async t => {
  const calls = [];
  for (const shape of [python, node]) {
    t.mock.method(globalThis, 'fetch', async (url, options = {}) => { calls.push({ url, options }); return reply(shape); });
    assert.deepEqual(await fetchCommunityStatus(), shape);
    t.mock.restoreAll();  // a second mock of the same method would otherwise outlive the test
  }
  assert.equal(COMMUNITY_STATUS_PATH, '/api/community/status');
  for (const { url, options } of calls) {
    assert.equal(url, COMMUNITY_STATUS_PATH);
    assert.equal(options.method ?? 'GET', 'GET');
    assert.equal(options.headers, undefined);
    assert.equal(options.body, undefined);
    assert.equal(options.cache, 'no-store');
  }
});

// The host's answers by route: health gives the token, the heartbeat counts this browser.
function host(t, status, heartbeat = status) {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options = {}) => {
    calls.push({ url, options });
    if (url === COMMUNITY_STATUS_PATH) return reply(status);
    if (url === '/api/local-compute/health') return reply({ token: 'compute-token' });
    if (url === COMMUNITY_HEARTBEAT_PATH) return typeof heartbeat === 'number' ? reply({ error: '刷新页面后重试' }, heartbeat) : reply(heartbeat);
    throw new Error(`unexpected ${url}`);
  });
  return calls;
}

void test('the Python service gets the plain status read only', async t => {
  for (const visible of [true, false]) {
    const calls = host(t, python);
    assert.deepEqual(await refreshCommunityStatus(visible), python);
    assert.deepEqual(calls.map(call => call.url), [COMMUNITY_STATUS_PATH]);
    t.mock.restoreAll();
  }
});

void test('the Node host, which counts visitors, gets its visible-page heartbeat and the menu shows its answer', async t => {
  const counted = { ...node, online_visitors: 3 };
  for (const [visible, flag] of [[true, '1'], [false, '0']]) {
    const calls = host(t, { ...node, online_visitors: 0 }, counted);
    assert.deepEqual(await refreshCommunityStatus(visible), counted);
    assert.deepEqual(calls.map(call => call.url), [COMMUNITY_STATUS_PATH, '/api/local-compute/health', COMMUNITY_HEARTBEAT_PATH]);
    const beat = calls[2].options;
    assert.equal(beat.method, 'POST');
    assert.deepEqual(beat.headers, { 'x-eeg-compute-token': 'compute-token', 'x-eeg-visible': flag });
    assert.equal(beat.body, undefined);
    assert.equal(beat.cache, 'no-store');
    // Each request has its own time limit, as health and the heartbeat each had.
    assert.ok(calls.every(call => call.options.signal instanceof AbortSignal));
    assert.equal(new Set(calls.map(call => call.options.signal)).size, 3);
    t.mock.restoreAll();
  }
  // As before the status route existed: a refused heartbeat is offline.
  host(t, node, 403);
  await assert.rejects(refreshCommunityStatus(true), /offline/);
  t.mock.restoreAll();
  host(t, node, { ...node, jobs: 'none' });
  await assert.rejects(refreshCommunityStatus(true), /offline/);
});

void test('each request of a refresh has its own time limit, so a slow Node host still answers', async t => {
  // Every request answers after `delay` ms (or fails when its signal aborts first). Three of them take longer than
  // one limit, each one less: the Node host's refresh succeeds, as health and the heartbeat did with 8 s each.
  const delay = 200, limit = 500;
  const slow = (answer) => t.mock.method(globalThis, 'fetch', (url, options = {}) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => resolve(answer(url)), delay);
    options.signal?.addEventListener('abort', () => { clearTimeout(timer); reject(options.signal.reason); }, { once: true });
  }));
  assert.equal(REQUEST_TIMEOUT_MS, 8000);
  const counted = { ...node, online_visitors: 3 };
  slow(url => reply(url === '/api/local-compute/health' ? { token: 'compute-token' } : url === COMMUNITY_HEARTBEAT_PATH ? counted : node));
  const started = performance.now();
  assert.deepEqual(await refreshCommunityStatus(true, limit), counted);
  assert.ok(performance.now() - started >= 3 * delay - 5);
  t.mock.restoreAll();
  slow(() => reply(python));
  assert.deepEqual(await refreshCommunityStatus(true, limit), python);
  t.mock.restoreAll();
  // One request slower than the limit is offline.
  slow(() => reply(python));
  await assert.rejects(refreshCommunityStatus(true, delay / 2), { name: 'TimeoutError' });
});

void test('on the Node host the menu still counts each browser and logs its visit', async t => {
  // Node's own scheduler and community routes, with its queue directory in a temporary folder.
  const directory = mkdtempSync(join(tmpdir(), 'eeg-community-status-'));
  const adapters = {};
  for (const kind of ['local-compute', 'source-reception', 'design-evaluation', 'electrode-editor']) {
    adapters[kind] = { prepare: async r => ({ request: r, key: 'k' }), lookup: async () => ({ hit: false }),
      start: async () => ({}), get: () => undefined, pid: () => undefined, busy: () => false, cancel: () => {} };
  }
  const scheduler = new CommunityQueue({ directory, adapters, pollMs: 3600000 });
  const token = 't'.repeat(64);
  const send = (res, status, body) => { res.writeHead(status, { 'content-type': 'application/json' }); res.end(JSON.stringify(body)); };
  const middleware = communityMiddleware({ scheduler, legacy: (req, res) => send(res, 404, {}), guard: () => true, send,
    queue: { token, health: () => ({ token }) }, tokenMatches: (a, b) => a === b });
  const server = createServer((req, res) => { void middleware(req, res, () => {}); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => {
    await new Promise(resolve => { server.close(resolve); server.closeAllConnections(); });
    scheduler.dispose();
    rmSync(directory, { recursive: true, force: true });
  });
  const base = `http://127.0.0.1:${server.address().port}`;
  const counts = [];
  for (let browser = 0; browser < 2; browser += 1) {
    // A browser without the other's cookie.
    let cookie = '';
    t.mock.method(globalThis, 'fetch', async (url, options = {}) => {
      const response = await nativeFetch(base + url, { ...options, headers: { ...options.headers, ...(cookie ? { cookie } : {}) } });
      cookie = response.headers.get('set-cookie')?.split(';')[0] || cookie;
      return response;
    });
    for (let poll = 0; poll < 2; poll += 1) counts.push((await refreshCommunityStatus(true)).online_visitors);
    t.mock.restoreAll();
  }
  assert.deepEqual(counts, [1, 1, 2, 2]);
  const access = join(directory, 'access');
  assert.ok(existsSync(access));
  const lines = readdirSync(access).flatMap(name => readFileSync(join(access, name), 'utf8').trim().split('\n'));
  assert.equal(lines.length, 2);
});

void test('a refused or unreadable status is offline', async t => {
  for (const answer of [reply({ error: 'Unknown community endpoint' }, 404), reply({ error: '计算队列不可用' }, 503),
    reply({ ...python, jobs: 'none' })]) {
    t.mock.method(globalThis, 'fetch', async () => answer);
    await assert.rejects(fetchCommunityStatus(), /offline/);
    t.mock.restoreAll();
  }
});

void test('the component refreshes through the model with the page visibility and shows the visitor notices only with a count', () => {
  const source = readFileSync(new URL('../components/community-status.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /\/api\/community\/|x-eeg-visible/);
  assert.match(source, /refreshCommunityStatus\(document\.visibilityState === 'visible'\)/);
  const start = source.indexOf('{hasVisitorCounts(status) && <>');
  assert.ok(start > 0);
  const guarded = source.slice(start, source.indexOf('</>}', start));
  for (const notice of ['在线访客', '在线访客按最近90秒活跃的浏览器估算', '后台记录IP用于访问日志和限流']) {
    assert.ok(guarded.includes(notice), notice);
    assert.equal(source.split(notice).length - 1, notice === '在线访客' ? 2 : 1, notice);
  }
});
