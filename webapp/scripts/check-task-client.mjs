import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { ApiError, apiFetch, apiJson, followTask, submitTask, cancelTask, readTask, sessionToken, isServiceUnreachable, SERVICE_CONNECTION_EVENT,
  SERVICE_UNREACHABLE_MESSAGE, SESSION_REOPEN_MESSAGE } from '../client/task-client.ts';
import { translateText } from '../lib/i18n/core.ts';

const json = (value, status = 200) => ({ ok: status < 400, status, json: async () => value });
const initial = { id: 'task-a', status: 'running', progress: 0.2 };
const fast = { firstDelayMs: 0, intervalMs: 0, maxRetryMs: 0 };
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

void test('temporary disconnection preserves server state and recovers the same task', async t => {
  const jobs = [], connections = [], calls = [];
  t.mock.method(globalThis, 'fetch', async url => {
    calls.push(url);
    if (calls.length === 1) throw new TypeError('Offline');
    if (calls.length === 2) return json({ error: 'Restarting' }, 503);
    return json({ job: { ...initial, status: 'completed' } });
  });
  const result = await followTask({ ...fast, service: 'source-reception', initial,
    signal: new AbortController().signal, onJob: job => jobs.push(job), onConnection: state => connections.push(state) });
  assert.deepEqual(connections, ['reconnecting', 'reconnecting', 'connected']);
  assert.deepEqual(jobs.map(j => j.status), ['completed']);
  assert.equal(initial.status, 'running');
  assert.equal(result.id, initial.id);
  assert.equal(new Set(calls).size, 1);
});

for (const status of [401, 403, 404]) {
  void test(`HTTP ${status} ends automatic observation without inventing a failed job`, async t => {
    let calls = 0; const jobs = [], connections = [];
    t.mock.method(globalThis, 'fetch', async () => { calls++; return json({ error: 'Unavailable' }, status); });
    await assert.rejects(followTask({ ...fast, service: 'electrode-editor', initial,
      signal: new AbortController().signal, onJob: job => jobs.push(job), onConnection: state => connections.push(state) }),
    error => error instanceof ApiError && error.status === status);
    assert.equal(calls, 1);
    assert.deepEqual(jobs, []);
    assert.deepEqual(connections, ['blocked']);
    assert.equal(initial.status, 'running');
  });
}

void test('network retry count is bounded and explicit observation can recover afterwards', async t => {
  let calls = 0; let offline = true;
  t.mock.method(globalThis, 'fetch', async () => {
    calls++;
    if (offline) throw new TypeError('Offline');
    return json({ job: { ...initial, status: 'completed' } });
  });
  const states = [], opts = { ...fast, service: 'design-evaluation', initial,
    signal: new AbortController().signal, maxFailures: 3, onJob() {}, onConnection: state => states.push(state) };
  await assert.rejects(followTask(opts), ApiError);
  assert.equal(calls, 3);
  assert.deepEqual(states, ['reconnecting', 'reconnecting', 'blocked']);
  offline = false;
  assert.equal((await followTask(opts)).status, 'completed');
});

void test('unmount or selected-task change discards a late reply and ends observation', async t => {
  const response = deferred(), started = deferred(), controller = new AbortController();
  const jobs = [], states = [];
  t.mock.method(globalThis, 'fetch', async () => { started.resolve(); return response.promise; });
  const observed = followTask({ ...fast, service: 'source-reception', initial, signal: controller.signal,
    onJob: value => jobs.push(value), onConnection: value => states.push(value) });
  const rejected = assert.rejects(observed, { name: 'AbortError' });
  await started.promise;
  controller.abort();
  response.resolve(json({ job: { ...initial, status: 'completed' } }));
  await rejected;
  assert.deepEqual(jobs, []);
  assert.deepEqual(states, []);
});

for (const invalid of [{ id: 'another-task', status: 'completed' }, { ...initial, status: 'invented' }]) {
  void test(`observation rejects invalid task identity or status: ${JSON.stringify(invalid)}`, async t => {
    const jobs = [];
    t.mock.method(globalThis, 'fetch', async () => json({ job: invalid }));
    await assert.rejects(followTask({ ...fast, service: 'local-compute', initial,
      signal: new AbortController().signal, maxFailures: 1, onJob: job => jobs.push(job), onConnection() {} }), ApiError);
    assert.deepEqual(jobs, []);
  });
}

void test('submission and cancellation refresh session tokens and preserve request bytes', async t => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith('/health')) return json({ token: calls.length === 1 ? 'first-token' : 'fresh-token' });
    return json({ job: initial });
  });
  const body = '{"region_count":2,"radius_mm":20,"mode":"whole_surface"}';
  await submitTask('local-compute', body);
  await cancelTask('local-compute', initial.id);
  assert.equal(calls[1].options.body, body);
  assert.equal(calls[1].options.headers.get('X-EEG-Compute-Token'), 'first-token');
  assert.equal(calls[3].options.headers.get('X-EEG-Compute-Token'), 'fresh-token');
  assert.equal(calls[3].options.method, 'POST');
  // The session cookie goes with every same-origin request; nothing opts out of it.
  assert.ok(calls.every(call => call.options.credentials === undefined && !call.options.headers.has('Cookie')));
});

void test('a request refused for a session of an earlier run asks to reopen from the eeglayoutlab command', async t => {
  // The service's answer to a request without its current session cookie (server/access.py).
  const refused = json({ error: '本地服务会话已失效，请重新运行 eeglayoutlab 打开', code: 'authentication_required' }, 401);
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; return refused; });
  for (const request of [() => apiJson('/api/local-compute/library'), () => sessionToken(), () => readTask('local-compute', initial.id),
    () => submitTask('local-compute', '{}', { token: 'stale-token' }), () => cancelTask('local-compute', initial.id, { token: 'stale-token' })]) {
    await assert.rejects(request(), error => error instanceof ApiError && error.status === 401 && !error.retryable
      && error.message === SESSION_REOPEN_MESSAGE && error.data.code === 'authentication_required');
  }
  // Observation stops at once instead of retrying with the same cookie.
  const states = [];
  await assert.rejects(followTask({ ...fast, service: 'source-reception', initial, signal: new AbortController().signal,
    onJob() {}, onConnection: state => states.push(state) }), { message: SESSION_REOPEN_MESSAGE });
  assert.deepEqual(states, ['blocked']);
  assert.equal(calls, 6);
  // Both languages say how to reopen; another 401, or another refusal, keeps the service's message.
  assert.match(SESSION_REOPEN_MESSAGE, /eeglayoutlab/);
  assert.match(translateText(SESSION_REOPEN_MESSAGE, 'en'), /^The local session has ended: .* Run the eeglayoutlab command again in a terminal and use the page it opens\.$/);
  assert.doesNotMatch(translateText('本地服务会话已失效，请重新运行 eeglayoutlab 打开', 'en'), /[\u3400-\u9fff]/);
  t.mock.restoreAll();
  for (const [status, value] of [[401, { error: 'Unauthorized' }], [403, { error: '会话已更新，请刷新页面后重新计算', code: 'authentication_required' }]]) {
    t.mock.method(globalThis, 'fetch', async () => json(value, status));
    await assert.rejects(apiJson('/api/test'), { message: value.error });
    t.mock.restoreAll();
  }
});

void test('a request that reaches no server asks to run the eeglayoutlab command again', async t => {
  // `eeglayoutlab serve` takes a new port on every start: after a stop or a restart a tab of the earlier run gets a
  // network error (connection refused), not a 401.
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => { calls++; throw new TypeError('fetch failed'); });
  for (const request of [() => apiJson('/api/projects', { errorMessage: '项目目录读取失败' }), () => sessionToken(), () => readTask('local-compute', initial.id)]) {
    await assert.rejects(request(), error => isServiceUnreachable(error) && error.message === SERVICE_UNREACHABLE_MESSAGE && error.retryable);
  }
  // Observation keeps its bounded retries, then stops with the advice.
  const states = [];
  await assert.rejects(followTask({ ...fast, service: 'source-reception', initial, signal: new AbortController().signal, maxFailures: 2,
    onJob() {}, onConnection: state => states.push(state) }), { message: SERVICE_UNREACHABLE_MESSAGE });
  assert.deepEqual(states, ['reconnecting', 'blocked']);
  assert.equal(calls, 5);
  assert.match(SERVICE_UNREACHABLE_MESSAGE, /eeglayoutlab/);
  assert.match(translateText(SERVICE_UNREACHABLE_MESSAGE, 'en'), /^Cannot reach the local service: .* Run the eeglayoutlab command again in a terminal and use the page it opens\.$/);
  // A timeout or a refusal is not a lost service.
  t.mock.restoreAll();
  t.mock.method(globalThis, 'fetch', async (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
  }));
  await assert.rejects(apiJson('/api/test', { timeoutMs: 1, errorMessage: 'slow' }), error => !isServiceUnreachable(error) && error.message === 'slow');
  t.mock.restoreAll();
  t.mock.method(globalThis, 'fetch', async () => json({ error: '计算队列不可用' }, 503));
  await assert.rejects(apiJson('/api/test'), error => !isServiceUnreachable(error) && error.message === '计算队列不可用');
});

void test('every request of the interface tells the task menu of an ended session or a lost service', async t => {
  const events = new EventTarget();
  let announced = 0;
  events.addEventListener(SERVICE_CONNECTION_EVENT, () => { announced++; });
  globalThis.window = events;
  t.after(() => { delete globalThis.window; });
  const refused = json({ error: '本地服务会话已失效，请重新运行 eeglayoutlab 打开', code: 'authentication_required' }, 401);
  // apiFetch passes every answer and error on unchanged; a 401 or a network error is also announced.
  for (const [answer, count] of [[json({ ok: 1 }), 0], [json({ error: '记录不存在' }, 404), 0], [refused, 1]]) {
    t.mock.method(globalThis, 'fetch', async () => answer);
    announced = 0;
    assert.equal(await apiFetch('/api/local-compute/library'), answer);
    assert.equal(announced, count, `HTTP ${answer.status}`);
    t.mock.restoreAll();
  }
  const lost = new TypeError('fetch failed');
  t.mock.method(globalThis, 'fetch', async () => { throw lost; });
  announced = 0;
  await assert.rejects(apiFetch('/data/fixed64_results.json'), error => error === lost);
  assert.equal(announced, 1);
  // A caller's own abort is no lost service.
  t.mock.restoreAll();
  t.mock.method(globalThis, 'fetch', async (_url, options) => { options.signal.throwIfAborted(); throw new TypeError('fetch failed'); });
  const controller = new AbortController(); controller.abort();
  announced = 0;
  await assert.rejects(apiFetch('/api/test', { signal: controller.signal }));
  assert.equal(announced, 0);
  // apiJson announces through apiFetch.
  t.mock.restoreAll();
  t.mock.method(globalThis, 'fetch', async () => refused);
  announced = 0;
  await assert.rejects(apiJson('/api/projects'), { message: SESSION_REOPEN_MESSAGE });
  assert.equal(announced, 1);
  // No interface module calls fetch itself: only the task client and the task menu's status read (which answers the
  // announcement) do, and the showcase's stand-in for the service.
  const exempt = new Set(['client/task-client.ts', 'components/community-status-model.ts', 'lib/showcase-api.ts']);
  const direct = [];
  const walk = directory => {
    for (const entry of readdirSync(new URL(`../${directory}/`, import.meta.url), { withFileTypes: true })) {
      const path = `${directory}/${entry.name}`;
      if (entry.isDirectory()) walk(path);
      else if (/\.(ts|tsx|mjs)$/.test(entry.name) && !exempt.has(path)
        && /(?<![\w.$])fetch\(/.test(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'))) direct.push(path);
    }
  };
  for (const directory of ['app', 'client', 'components', 'features', 'lib']) walk(directory);
  assert.deepEqual(direct, []);
});

void test('lost submission response is never retried automatically', async t => {
  let posts = 0;
  t.mock.method(globalThis, 'fetch', async url => {
    if (url.endsWith('/health')) return json({ token: 'token' });
    posts++;
    throw new TypeError('Response lost');
  });
  await assert.rejects(submitTask('source-reception', { record_id: 'a'.repeat(64) }), ApiError);
  assert.equal(posts, 1);
});

void test('a request timeout is recoverable while caller cancellation is silent', async t => {
  t.mock.method(globalThis, 'fetch', async (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
  }));
  await assert.rejects(apiJson('/api/test', { timeoutMs: 1 }), error => error instanceof ApiError && error.retryable);
  const controller = new AbortController();
  const pending = apiJson('/api/test', { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, { name: 'AbortError' });
});

void test('an incompatible API header stops observation instead of retrying', async t => {
  let calls = 0;
  t.mock.method(globalThis, 'fetch', async () => {
    calls++;
    return { ...json({ job: initial }), headers: new Headers({ 'X-EEG-API-Version': '2' }) };
  });
  await assert.rejects(followTask({ ...fast, service: 'source-reception', initial,
    signal: new AbortController().signal, onJob() {}, onConnection() {} }), error => error.status === 426);
  assert.equal(calls, 1);
});
