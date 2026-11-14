import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer, request } from 'node:http';
import { once } from 'node:events';
import { mkdtemp, mkdir, readFile, readdir, rm, stat, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { operationsConfig } from '../server/operations/config.mjs';
import { ResourceGate } from '../server/operations/resource-gate.mjs';
import { OperationsRequestLog, safeRequestLog } from '../server/operations/request-log.mjs';
import { OperationsMonitor, correlateOperation, directOperatorRequest, operationRoute } from '../server/operations/monitor.mjs';

const MIB = 1024 * 1024;
const healthyStats = async () => ({ bsize: 1024n, bavail: 1024n * 1024n });
const config = () => operationsConfig({});
function gate(options = {}) { return new ResourceGate({ directories: [{ scope: 'queue', path: '/private/queue-path' }, { scope: 'scientific', path: '/private/science-path' }], config: config(), statfs: healthyStats, memoryUsage: () => ({ rss: 128 * MIB }), ...options }); }
const record = overrides => ({ at: '2026-11-13T12:00:00.000Z', request_id: randomUUID(), method: 'POST', route: 'source-reception.lookup', status: 200, duration_ms: 12.345678, aborted: false, ...overrides });
async function operatorRead(base, path, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = request(base + path, { headers, agent: false }, res => {
      const chunks = []; res.on('data', chunk => chunks.push(chunk)); res.on('error', reject);
      res.on('end', () => resolve({ status: res.statusCode, data: JSON.parse(Buffer.concat(chunks).toString()) }));
    });
    req.on('error', reject); req.end();
  });
}
async function directory(t) { const root = await mkdtemp(join(tmpdir(), 'eeg-operations-')); t.after(() => rm(root, { recursive: true, force: true })); return root; }
async function host(t, { logger, resourceGate = gate(), handler } = {}) {
  const root = await directory(t), scheduler = { tasks: [], maintenanceStatus: () => ({ maintenance: false, drained: false }), disposed: false, failure: null, blockedPids: [] };
  const monitor = new OperationsMonitor({ queue: { runtime: { queueDirectory: root }, token: 'PRIVATE_COMPUTE_TOKEN' }, scheduler, gate: resourceGate, logger });
  const server = createServer(monitor.middleware(handler ?? ((_req, res) => { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{"ok":true}'); })));
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(async () => { const closed = once(server, 'close'); server.close(); server.closeAllConnections(); await closed; monitor.close(); await monitor.flush(); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const read = async (path, options = {}) => { const response = await fetch(base + path, options); return { status: response.status, headers: response.headers, data: await response.json() }; };
  return { root, base, monitor, scheduler, read };
}

void test('operations settings are bounded and kept outside scientific parameters', () => {
  const defaults = config(); assert.equal(defaults.minFreeDiskBytes, 512 * MIB); assert.equal(defaults.maxHostRssBytes, 0); assert.equal(defaults.logRetentionDays, 7); assert.equal(defaults.logQueueLimit, 128);
  const custom = operationsConfig({ EEG_MIN_FREE_DISK_MB: '1024', EEG_MAX_HOST_RSS_MB: '2048', EEG_OPERATIONS_LOG_MB: '10' });
  assert.equal(custom.minFreeDiskBytes, 1024 * MIB); assert.equal(custom.maxHostRssBytes, 2048 * MIB); assert.equal(custom.logMaxBytes, 10 * MIB);
  for (const env of [{ EEG_MIN_FREE_DISK_MB: '-1' }, { EEG_MIN_FREE_DISK_MB: '1.5' }, { EEG_MIN_FREE_DISK_MB: '' }, { EEG_MAX_HOST_RSS_MB: 'NaN' }, { EEG_OPERATIONS_LOG_MB: '11' }, { EEG_OPERATIONS_LOG_MB: '0' }]) assert.throws(() => operationsConfig(env));
});

void test('resource samples expose measured free disk and current host RSS without private paths', async () => {
  const sample = await gate().sample(); assert.equal(sample.allowed, true); assert.equal(sample.host_rss_bytes, 128 * MIB); assert.equal(sample.disks.length, 2);
  assert.equal(sample.disks[0].free_bytes, 1024 * MIB); assert.match(sample.memory_scope, /peak memory is not measured/);
  assert.ok(!JSON.stringify(sample).includes('/private/'));
});

void test('low disk refuses new work with a safe retryable error and explicit scope', async () => {
  const resource = gate({ statfs: async path => ({ bsize: 1024n, bavail: path.endsWith('queue-path') ? 1n : 1024n * 1024n }) });
  const sample = await resource.sample(); assert.equal(sample.allowed, false); assert.equal(sample.alerts.length, 1); assert.equal(sample.alerts[0].code, 'low_disk'); assert.equal(sample.alerts[0].scope, 'queue');
  await assert.rejects(resource.assertAvailable(), error => error.status === 503 && error.code === 'resource_unavailable' && error.retryAfter === 30 && !error.message.includes('/private/'));
});

void test('host RSS admission threshold is optional and does not claim worker memory limits', async () => {
  assert.equal((await gate({ memoryUsage: () => ({ rss: 10 * 1024 * MIB }) }).sample()).allowed, true);
  const resource = gate({ config: { ...config(), maxHostRssBytes: 64 * MIB } });
  assert.equal((await resource.sample()).alerts[0].code, 'host_memory_limit'); await assert.rejects(resource.assertAvailable(), { status: 503 });
});

void test('failed or invalid resource observations fail closed without leaking exception text', async () => {
  for (const statfs of [async () => { throw new Error('PRIVATE_PATH_AND_TOKEN'); }, async () => ({ bsize: 0, bavail: 1 }), async () => ({ bsize: 1024, bavail: -1 })]) {
    const resource = gate({ statfs }); const sample = await resource.sample(); assert.equal(sample.allowed, false); assert.equal(sample.alerts[0].code, 'disk_sampling_failed');
    assert.ok(!JSON.stringify(sample).includes('PRIVATE_PATH_AND_TOKEN')); await assert.rejects(resource.assertAvailable(), { status: 503 });
  }
  const failedMemory = await gate({ memoryUsage: () => ({ rss: NaN }) }).sample(); assert.equal(failedMemory.allowed, false); assert.equal(failedMemory.alerts[0].code, 'memory_sampling_failed');
});

void test('log allowlist excludes all credentials, query values, inputs and response payloads', () => {
  const safe = safeRequestLog(record({ task_id: randomUUID(), task_status: 'completed', authorization: 'SECRET_AUTH', cookie: 'SECRET_COOKIE', query: 'SECRET_QUERY', input: { seed: 'SECRET_INPUT' }, response: { result: 'SECRET_RESULT' } }));
  assert.ok(!JSON.stringify(safe).includes('SECRET_')); assert.equal(safe.duration_ms, 12.346); assert.equal(safe.task_status, 'completed');
  assert.throws(() => safeRequestLog(record({ route: '/api/private?key=SECRET' })));
});

void test('operations logs have private permissions, bounded daily bytes and seven-day retention', async t => {
  const root = await directory(t), logDir = join(root, 'operations'); await mkdir(logDir, { mode: 0o700 });
  await writeFile(join(logDir, '2026-11-01.ndjson'), 'expired', { mode: 0o600 });
  await writeFile(join(logDir, '2099-01-01.ndjson'), 'future-after-clock-rollback', { mode: 0o600 });
  const logger = new OperationsRequestLog(logDir, { config: { ...config(), logMaxBytes: 500 }, now: () => Date.parse('2026-11-13T12:00:00Z') });
  for (let index = 0; index < 8; index++) logger.record(record()); await logger.flush();
  const names = await readdir(logDir); assert.deepEqual(names, ['2026-11-13.ndjson']);
  assert.ok((await stat(join(logDir, names[0]))).size <= 500); assert.equal((await stat(join(logDir, names[0]))).mode & 0o077, 0); assert.equal((await stat(logDir)).mode & 0o077, 0);
  assert.ok(logger.status().written > 0); assert.ok(logger.status().dropped > 0);
});

void test('log queue backpressure and close bound in-memory work while accepted logs flush', async t => {
  const root = await directory(t), logger = new OperationsRequestLog(join(root, 'operations'), { config: { ...config(), logQueueLimit: 2 } });
  let release; const blocked = new Promise(resolve => { release = resolve; }); let appended = 0;
  logger.append = async () => { await blocked; appended++; };
  for (let index = 0; index < 8; index++) logger.record(record());
  assert.equal(logger.status().pending, 2); assert.equal(logger.status().dropped, 6);
  logger.close(); logger.record(record()); assert.equal(logger.status().dropped, 7);
  release(); await logger.flush(); assert.equal(appended, 2); assert.equal(logger.status().pending, 0);
});

void test('symlink log targets fail without breaking application responses', async t => {
  const root = await directory(t), outside = join(root, 'outside'); await mkdir(outside); await symlink(outside, join(root, 'operations'));
  const logger = new OperationsRequestLog(join(root, 'operations'));
  const { read, monitor } = await host(t, { logger });
  assert.equal((await read('/api/local-compute/health')).status, 200); await logger.flush();
  assert.equal(logger.status().unavailable, true); assert.equal((await readdir(outside)).length, 0);
  assert.equal((await monitor.status()).alerts.find(alert => alert.code === 'operations_log_unavailable').scope, 'operations');
});

void test('real HTTP generates server request IDs, correlates only task ID/status and redacts sensitive values', async t => {
  const taskId = randomUUID();
  const { read, monitor, root } = await host(t, { handler: (_req, res) => { correlateOperation(res, { id: taskId, status: 'completed', request: { token: 'SECRET_RESPONSE' } }); res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{"ok":true}'); } });
  const response = await read('/api/source-reception/lookup?key=SECRET_QUERY', { method: 'POST', headers: { 'X-EEG-Request-Id': 'SECRET_REQUEST_ID', Authorization: 'SECRET_AUTH', Cookie: 'SECRET_COOKIE', 'X-EEG-Compute-Token': 'SECRET_COMPUTE', 'X-EEG-Project-Key': 'SECRET_PROJECT', 'Content-Type': 'application/json' }, body: '{"secret":"SECRET_INPUT"}' });
  assert.equal(response.status, 200); assert.match(response.headers.get('x-eeg-request-id'), /^[a-f0-9-]{36}$/); assert.notEqual(response.headers.get('x-eeg-request-id'), 'SECRET_REQUEST_ID');
  await monitor.flush();
  const file = (await readdir(join(root, 'operations')))[0], text = await readFile(join(root, 'operations', file), 'utf8'), logged = JSON.parse(text.trim());
  assert.ok(!text.includes('SECRET_')); assert.equal(logged.task_id, taskId); assert.equal(logged.task_status, 'completed'); assert.equal(logged.route, 'source-reception.lookup');
  assert.equal(logged.request_id, response.headers.get('x-eeg-request-id')); assert.equal(monitor.totals.completed, 1);
});

void test('operator status requires a direct local non-browser non-proxy request', async t => {
  const { base, scheduler } = await host(t);
  scheduler.tasks = [{ status: 'queued', created_at: '2026-11-13T00:00:00Z', request: { token: 'SECRET_JOB' } }, { status: 'running' }];
  const local = await operatorRead(base, '/api/operations/status'); assert.equal(local.status, 200); assert.equal(local.data.schema, 'operations-status/1'); assert.equal(local.data.queue.queued, 1); assert.equal(local.data.queue.running, 1); assert.ok(!JSON.stringify(local.data).includes('SECRET_'));
  for (const headers of [{ Origin: 'http://127.0.0.1' }, { 'Sec-Fetch-Site': 'same-origin', 'X-EEG-Compute-Token': 'PRIVATE_COMPUTE_TOKEN' }, { 'X-Forwarded-For': '203.0.113.2' }, { Forwarded: 'for=203.0.113.2' }, { Host: 'eeg.example.org' }, { 'X-Real-IP': '203.0.113.2' }]) assert.equal((await operatorRead(base, '/api/operations/status', headers)).status, 403);
  assert.equal((await operatorRead(base, '/api/operations/status?token=SECRET_QUERY')).status, 405);
  assert.equal(directOperatorRequest({ socket: { remoteAddress: '192.0.2.2' }, headers: { host: 'localhost' } }), false);
});

void test('client cancellation increments aborts once, closes active count and keeps next request usable', async t => {
  let announce;
  const ready = new Promise(resolve => { announce = resolve; });
  const { base, read, monitor } = await host(t, { handler: (req, res) => { if (req.url === '/abort') { announce(res); return; } res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{"ok":true}'); } });
  const req = request(base + '/abort'); req.on('error', () => {}); req.end();
  const res = await ready, closed = once(res, 'close'); req.destroy(); await closed;
  assert.equal(monitor.totals.aborted, 1); assert.equal(monitor.active, 0); assert.equal((await read('/api/local-compute/health')).status, 200);
  assert.equal(monitor.totals.completed, 1); assert.equal(monitor.totals.aborted, 1);
});

void test('application failures become safe 500 responses and logging exceptions remain non-fatal', async t => {
  const logger = { record() { throw new Error('SECRET_LOG_FAILURE'); }, status: () => ({ unavailable: true }), flush: async () => {}, close() {} };
  const { read, monitor } = await host(t, { logger, handler: (req, res) => { if (req.url === '/fail') throw new Error('SECRET_NATIVE_PATH'); res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{"ok":true}'); } });
  const failed = await read('/fail'); assert.equal(failed.status, 500); assert.ok(!JSON.stringify(failed.data).includes('SECRET_')); assert.equal(monitor.totals.errors, 1);
  assert.equal((await read('/api/local-compute/health')).status, 200);
});

void test('resource refusal leaves cached lookup, reads and cancellation available through monitoring', async t => {
  const resource = gate({ statfs: async () => ({ bsize: 1024n, bavail: 1n }) });
  const { read } = await host(t, { resourceGate: resource, handler: async (req, res) => {
    if (req.url === '/new') {
      try { await resource.assertAvailable(); } catch (error) { res.writeHead(error.status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ code: error.code })); return; }
    }
    res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{"cached":true}');
  } });
  assert.equal((await read('/new', { method: 'POST' })).status, 503);
  for (const path of ['/api/source-reception/lookup', '/api/local-compute/library', `/api/source-reception/jobs/${randomUUID()}/cancel`]) assert.equal((await read(path)).status, 200);
});

void test('unknown URL variation cannot grow route counters or expose request values', async t => {
  const { read, monitor } = await host(t);
  for (let index = 0; index < 25; index++) await read(`/api/unknown-${index}?private=SECRET_${index}`);
  assert.equal(monitor.routes.size, 1); assert.equal(monitor.routes.get('api.other').requests, 25);
  assert.equal(operationRoute('/api/projects/' + randomUUID() + '/entries/' + randomUUID() + '?token=SECRET'), 'projects.entries');
  const status = await monitor.status(); status.requests.routes['api.other'].requests = 999;
  assert.equal(monitor.routes.get('api.other').requests, 25);
});

void test('stalled filesystem observations time out, remain bounded and recover without duplicate probes', async () => {
  let resolveProbe, calls = 0;
  const pending = new Promise(resolve => { resolveProbe = resolve; });
  const resource = gate({ statfs: () => { calls++; return pending; }, sampleTimeoutMs: 15 });
  const first = await resource.sample(); assert.equal(first.allowed, false); assert.equal(calls, 2);
  const second = await resource.sample(); assert.equal(second.allowed, false); assert.equal(calls, 2);
  assert.equal(resource.diskChecks.size, 2);
  resolveProbe({ bsize: 1024n, bavail: 1024n * 1024n }); await new Promise(resolve => setImmediate(resolve));
  assert.equal((await resource.sample()).allowed, true); assert.equal(resource.diskChecks.size, 0);
});
