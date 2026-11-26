import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { COMMUNITY_STATUS_PATH, REQUEST_TIMEOUT_MS, fetchCommunityStatus, readCommunityStatus } from '../components/community-status-model.ts';
import { ApiError, isServiceUnreachable, SERVICE_CONNECTION_EVENT, SERVICE_UNREACHABLE_MESSAGE, SESSION_REOPEN_MESSAGE } from '../client/task-client.ts';

// GET /api/community/status of the Python service's workspace queue; the legacy Node host adds a visitor count.
const job = { id: '6f1c2b8e-3d4a-4f5b-9c6d-7e8f9a0b1c2d', key: 'a'.repeat(64), kind: 'local-compute', status: 'queued',
  created_at: '2026-11-23T08:00:00.000Z', finished_at: null, queue_position: 1, message: '已加入计算队列', progress: 0,
  cached: false, request: { region_count: 1, radius_mm: 15, mode: 'whole_surface' }, catalog: {} };
const python = { queued_tasks: 1, running_tasks: 0, available: true, resource_blocked: false, recovery_blocked: false,
  maintenance: false, drained: false, jobs: [job] };
const node = { online_visitors: 2, ...python };
const reply = (value, status = 200) => ({ ok: status < 400, status, json: async () => value });

void test('the task menu reads the status of both hosts and ignores a visitor count', () => {
  assert.deepEqual(readCommunityStatus(python), python);
  assert.deepEqual(readCommunityStatus(node), node);
  assert.deepEqual(readCommunityStatus({ ...node, online_visitors: '2' }), { ...node, online_visitors: '2' });
});

void test('an answer the menu cannot show is not a status', () => {
  for (const value of [null, [], 'text', { ...python, jobs: null }, { ...python, queued_tasks: -1 },
    { ...python, running_tasks: 0.5 }, { ...python, available: 'yes' }, { ...python, recovery_blocked: undefined },
    { ...python, jobs: [{ ...job, id: 7 }] }, { ...python, jobs: [null] }]) {
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
  assert.equal(calls.length, 2);
  for (const { url, options } of calls) {
    assert.equal(url, COMMUNITY_STATUS_PATH);
    assert.equal(options.method ?? 'GET', 'GET');
    assert.equal(options.headers, undefined);
    assert.equal(options.body, undefined);
    assert.equal(options.cache, 'no-store');
    assert.ok(options.signal instanceof AbortSignal);
  }
});

void test('a status slower than its time limit is offline', async t => {
  const delay = 200;
  t.mock.method(globalThis, 'fetch', (_url, options = {}) => new Promise((resolve, reject) => {
    const timer = setTimeout(() => resolve(reply(python)), delay);
    options.signal?.addEventListener('abort', () => { clearTimeout(timer); reject(options.signal.reason); }, { once: true });
  }));
  assert.equal(REQUEST_TIMEOUT_MS, 8000);
  assert.deepEqual(await fetchCommunityStatus(delay * 4), python);
  await assert.rejects(fetchCommunityStatus(delay / 2), { name: 'TimeoutError' });
});

void test('a refused or unreadable status is offline', async t => {
  for (const answer of [reply({ error: 'Unknown community endpoint' }, 404), reply({ error: '计算队列不可用' }, 503),
    reply({ ...python, jobs: 'none' }), reply({ error: 'Request rejected by access policy.', code: 'request_forbidden' }, 403)]) {
    t.mock.method(globalThis, 'fetch', async () => answer);
    await assert.rejects(fetchCommunityStatus(), /offline/);
    t.mock.restoreAll();
  }
});

void test('a status refused for the session of an earlier run asks to reopen from the eeglayoutlab command', async t => {
  t.mock.method(globalThis, 'fetch', async () => reply({ error: '本地服务会话已失效，请重新运行 eeglayoutlab 打开', code: 'authentication_required' }, 401));
  await assert.rejects(fetchCommunityStatus(), error => error instanceof ApiError && error.status === 401 && error.message === SESSION_REOPEN_MESSAGE);
  // The component keeps the reopen message for the menu and marks the header (useTaskStatus).
  const source = readFileSync(new URL('../components/community-status.tsx', import.meta.url), 'utf8');
  assert.match(source, /setOffline\(error instanceof ApiError && error\.status === 401 \? 'expired' : isServiceUnreachable\(error\) \? 'unreachable' : 'failed'\)/);
  assert.match(source, /offline === 'expired' \? SESSION_REOPEN_MESSAGE : offline === 'unreachable' \? SERVICE_UNREACHABLE_MESSAGE : null/);
  assert.match(source, /\{reopen && <p role="alert"[^>]*>\{tx\(reopen\)\}<\/p>\}/);
});

void test('a status that reaches no server asks to run the eeglayoutlab command again and claims no empty queue', async t => {
  // `eeglayoutlab serve` takes a new port on every start, so a tab of an earlier run gets a network error.
  const events = new EventTarget();
  let announced = 0;
  events.addEventListener(SERVICE_CONNECTION_EVENT, () => { announced++; });
  globalThis.window = events;
  t.after(() => { delete globalThis.window; });
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('fetch failed'); });
  await assert.rejects(fetchCommunityStatus(), error => isServiceUnreachable(error) && error.message === SERVICE_UNREACHABLE_MESSAGE);
  // The status read answers the announcement, so it never makes one (two menus would wake each other forever).
  assert.equal(announced, 0);
  const component = readFileSync(new URL('../components/community-status.tsx', import.meta.url), 'utf8');
  const home = readFileSync(new URL('../features/workspace/home-workspace.tsx', import.meta.url), 'utf8');
  // A request of the page that finds the session ended or no server makes the menu read its status at once.
  assert.match(component, /window\.addEventListener\(SERVICE_CONNECTION_EVENT, refresh\)/);
  assert.match(component, /window\.removeEventListener\(SERVICE_CONNECTION_EVENT, refresh\)/);
  // The advice is a notice at the foot of the window at every width, outside the header (whose backdrop filter
  // would hold a fixed element), not only the header's text, which is hidden on narrow screens.
  assert.match(component, /\{reopen && createPortal\(<p role="alert" className="fixed [^"]*">\{tx\(reopen\)\}<\/p>, document\.body\)\}/);
  assert.doesNotMatch(component.match(/createPortal\(<p[^>]*>/)[0], /\bhidden\b|sm:/);
  // Without a status the workspace's queue is unknown, not empty: the menu and the home say so only with a status.
  assert.match(component, /\{status && !status\.jobs\.length && <p[^>]*>\{tx\('此工作区暂无计算任务'\)\}<\/p>\}/);
  assert.equal(component.match(/此工作区暂无计算任务/g).length, 1);
  assert.match(home, /const idle = !failure && \(status \? !status\.jobs\.length && !status\.recovery_blocked && status\.available !== false : offline === 'loading'\);/);
});

void test('the component reads the status through the model and shows no visitor count or access-log notice', () => {
  const component = readFileSync(new URL('../components/community-status.tsx', import.meta.url), 'utf8');
  const home = readFileSync(new URL('../features/workspace/home-workspace.tsx', import.meta.url), 'utf8');
  assert.match(component, /await fetchCommunityStatus\(\)/);
  for (const source of [component, home]) {
    assert.doesNotMatch(source, /\/api\/community\/|x-eeg-visible|heartbeat|online_visitors|VisitorNotice|访客|记录IP|当前浏览器/i);
    assert.match(source, /此工作区暂无计算任务/);
  }
  // Task actions go through the task client, which sends the session token and reads an expired session.
  assert.match(component, /cancelTask</); assert.match(component, /readTask</);
  assert.doesNotMatch(component, /fetch\(/);
});
