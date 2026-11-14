import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiError, apiJson, followTask, submitTask, cancelTask } from '../client/task-client.ts';

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
