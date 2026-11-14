import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { mkdtemp, readFile, rm, symlink, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { probeService, parseProbeArgs, probeUrl, summarizeStatus, writeProbeReport } from './probe-service.mjs';

const status = () => ({ schema: 'operations-status/1', queue: { available: true, maintenance: false, drained: false, queued: 0, running: 0, cancelling: 0 }, resources: { allowed: true, host_rss_bytes: 12345, min_free_disk_bytes: 512 * 1024 * 1024, max_host_rss_bytes: 0, disks: [{ scope: 'queue', free_bytes: 1024 ** 3 }, { scope: 'scientific', free_bytes: 1024 ** 3 }] }, logging: { unavailable: false, dropped: 0, failed: 0 }, alerts: [], new_work_allowed: true });
async function server(t, handler) {
  const instance = createServer(handler); instance.listen(0, '127.0.0.1'); await once(instance, 'listening');
  t.after(async () => { const closed = once(instance, 'close'); instance.close(); instance.closeAllConnections(); await closed; });
  return `http://127.0.0.1:${instance.address().port}`;
}
const send = (res, value, code = 200) => { res.writeHead(code, { 'Content-Type': 'application/json', 'X-EEG-Request-Id': randomUUID() }); res.end(JSON.stringify(value)); };
function cli(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [new URL('./probe-service.mjs', import.meta.url).pathname, ...args], { stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '', stderr = ''; child.stdout.on('data', chunk => { stdout += chunk; }); child.stderr.on('data', chunk => { stderr += chunk; }); child.on('error', reject); child.on('close', code => resolve({ code, data: JSON.parse(stdout), stderr }));
  });
}

void test('probe arguments accept only direct loopback HTTP and bounded timeouts', () => {
  assert.equal(probeUrl('http://localhost:3000').pathname, '/api/operations/status');
  assert.equal(parseProbeArgs(['--allow-paused', '--timeout-ms', '1000']).allowPaused, true);
  for (const value of ['https://127.0.0.1:3000', 'http://example.org', 'http://127.0.0.1:3000/?token=SECRET', 'http://user:secret@localhost:3000', 'http://localhost:3000/projects']) assert.throws(() => probeUrl(value));
  for (const args of [['--timeout-ms', '99'], ['--timeout-ms', '60001'], ['--timeout-ms', 'x'], ['--url'], ['--unknown'], ['--url', 'http://localhost', '--url', 'http://localhost']]) assert.throws(() => parseProbeArgs(args));
});

void test('probe uses raw HTTP without browser metadata and preserves a generated request identifier', async t => {
  let observed;
  const id = randomUUID(), url = await server(t, (req, res) => { observed = { method: req.method, url: req.url, headers: req.headers }; res.writeHead(200, { 'X-EEG-Request-Id': id }); res.end(JSON.stringify(status())); });
  const result = await probeService({ url }); assert.equal(result.exit_code, 0); assert.equal(result.state, 'ready'); assert.equal(result.request_id, id);
  assert.equal(observed.method, 'GET'); assert.equal(observed.url, '/api/operations/status');
  assert.equal(observed.headers['sec-fetch-mode'], undefined); assert.equal(observed.headers.origin, undefined); assert.equal(observed.headers.cookie, undefined); assert.equal(observed.headers['x-eeg-compute-token'], undefined);
  assert.equal((await probeService({ url: url.replace('127.0.0.1', 'localhost') })).exit_code, 0);
});

void test('paused readiness is explicit and does not confuse drained with deleted waiting tasks', () => {
  const paused = status(); paused.queue.maintenance = true; paused.queue.drained = true; paused.queue.queued = 2; paused.new_work_allowed = false;
  assert.equal(summarizeStatus(paused).exit_code, 2);
  const allowed = summarizeStatus(paused, { allowPaused: true }); assert.equal(allowed.exit_code, 0); assert.equal(allowed.state, 'paused-ready'); assert.equal(allowed.queue.queued, 2);
  paused.queue.drained = false; assert.equal(summarizeStatus(paused, { allowPaused: true }).exit_code, 2);
});

void test('resource and logging alerts yield nonzero readiness without exposing private response fields', async t => {
  const value = status(); value.resources.allowed = false; value.new_work_allowed = false; value.logging.dropped = 2; value.logging.failed = 1;
  value.alerts = [{ code: 'low_disk', scope: 'queue', action: 'SECRET_PRIVATE_PATH' }, { code: 'PRIVATE_SECRET_CODE', scope: 'PRIVATE_SCOPE', action: 'PRIVATE_ACTION' }];
  value.private_path = '/private/SECRET'; value.token = 'SECRET_TOKEN'; value.queue.jobs = [{ secret: 'SECRET_JOB' }];
  const url = await server(t, (_req, res) => send(res, value)), report = await probeService({ url });
  assert.equal(report.exit_code, 2); assert.ok(report.alerts.some(alert => alert.code === 'low_disk')); assert.ok(report.alerts.some(alert => alert.code === 'operations_log_dropped')); assert.ok(report.alerts.some(alert => alert.code === 'operations_log_failed'));
  assert.ok(!JSON.stringify(report).includes('SECRET')); assert.ok(!JSON.stringify(report).includes('PRIVATE_'));
});

void test('invalid schemas, missing trace headers and HTTP failures produce machine-readable probe failure', async t => {
  for (const handler of [(_req, res) => send(res, { schema: 'unknown' }), (_req, res) => res.end(JSON.stringify(status())), (_req, res) => send(res, { error: 'SECRET_NATIVE_PATH' }, 503)]) {
    const url = await server(t, handler), report = await probeService({ url }); assert.equal(report.exit_code, 3); assert.equal(report.state, 'probe-failed'); assert.ok(!JSON.stringify(report).includes('SECRET'));
  }
});

void test('response size and absolute deadline bound oversized and continuously trickling responses', async t => {
  const oversized = await server(t, (_req, res) => { res.writeHead(200, { 'X-EEG-Request-Id': randomUUID(), 'Content-Length': 2 * 1024 * 1024 }); res.end(); });
  assert.equal((await probeService({ url: oversized })).error, 'response_too_large');
  const trickle = await server(t, (_req, res) => { res.writeHead(200, { 'X-EEG-Request-Id': randomUUID() }); const timer = setInterval(() => res.write(' '), 20); res.once('close', () => clearInterval(timer)); });
  const start = Date.now(), timedOut = await probeService({ url: trickle, timeoutMs: 100 });
  assert.equal(timedOut.error, 'timeout'); assert.ok(Date.now() - start < 2000);
});

void test('output is confined to regular project artifacts paths and rejects links and traversal', async t => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-probe-output-')); t.after(() => rm(root, { recursive: true, force: true }));
  const report = { schema: 'service-probe/1', ready: true, exit_code: 0 };
  await writeProbeReport(report, 'artifacts/qa/probe.json', { projectRoot: root });
  assert.deepEqual(JSON.parse(await readFile(join(root, 'artifacts/qa/probe.json'), 'utf8')), report);
  await assert.rejects(writeProbeReport(report, '../outside.json', { projectRoot: root }));
  const outside = join(root, 'outside'); await mkdir(outside); await symlink(outside, join(root, 'artifacts/link'));
  await assert.rejects(writeProbeReport(report, 'artifacts/link/probe.json', { projectRoot: root }));
  await writeFile(join(root, 'outside-file'), 'Original'); await symlink(join(root, 'outside-file'), join(root, 'artifacts/file-link'));
  await assert.rejects(writeProbeReport(report, 'artifacts/file-link', { projectRoot: root })); assert.equal(await readFile(join(root, 'outside-file'), 'utf8'), 'Original');
});

void test('CLI exits distinguish ready, reachable-not-ready and invalid arguments without stderr secrets', async t => {
  const value = status(), url = await server(t, (_req, res) => send(res, value));
  const ready = await cli(['--url', url]); assert.equal(ready.code, 0); assert.equal(ready.data.ready, true); assert.equal(ready.stderr, '');
  value.queue.maintenance = true; value.queue.drained = true; value.new_work_allowed = false;
  assert.equal((await cli(['--url', url])).code, 2); assert.equal((await cli(['--url', url, '--allow-paused'])).code, 0);
  const invalid = await cli(['--url', 'http://SECRET_PUBLIC_HOST/path']); assert.equal(invalid.code, 4); assert.ok(!JSON.stringify(invalid.data).includes('SECRET'));
});
