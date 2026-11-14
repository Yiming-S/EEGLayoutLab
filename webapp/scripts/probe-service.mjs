/** Read-only local operator probe. No tokens, queue changes or scientific work. */
import { request } from 'node:http';
import { lstat, mkdir, realpath } from 'node:fs/promises';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { atomicJson } from '../server/storage/records.mjs';

const PROJECT_ROOT = resolve(import.meta.dirname, '../..');
const MAX_RESPONSE_BYTES = 1024 * 1024;
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
const ACTIONS = Object.freeze({
  low_disk: 'Free disk space or apply the approved retention policy.',
  host_memory_limit: 'Inspect current Node host memory before admitting new work.',
  memory_sampling_failed: 'Check the local resource probe.',
  disk_sampling_failed: 'Check filesystem access for the configured scientific and queue roots.',
  queue_unavailable: 'Inspect the queue owner and recorded service failure.',
  queue_recovery_blocked: 'Complete the documented worker recovery procedure.',
  operations_log_unavailable: 'Check operations log permissions and free space.',
  operations_log_dropped: 'Inspect log queue pressure and the daily size limit; request records were dropped.',
  operations_log_failed: 'Inspect prior operations logging failures before declaring readiness.',
  maintenance_active: 'The service is paused; resume explicitly only after acceptance.',
  queue_not_drained: 'Wait for active work to finish or cancel it before stopped-service operations.',
  admission_blocked: 'Inspect direct local operations status before accepting new work.',
  service_alert: 'Inspect direct local operations status for the reported service alert.',
});
const scopes = new Set(['queue', 'scientific', 'host', 'operations', 'service']);
const count = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
const object = value => value && typeof value === 'object' && !Array.isArray(value);

export function probeUrl(value = 'http://127.0.0.1:3000') {
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || url.username || url.password || url.search || url.hash || !['/', '/api/operations/status'].includes(url.pathname)) throw new Error('A direct loopback HTTP origin is required.');
  url.pathname = '/api/operations/status'; return url;
}
export function parseProbeArgs(args) {
  const parsed = { url: 'http://127.0.0.1:3000', timeoutMs: 5000, allowPaused: false };
  const seen = new Set();
  for (let index = 0; index < args.length; index++) {
    const name = args[index]; if (seen.has(name)) throw new Error('Invalid probe arguments.'); seen.add(name);
    if (name === '--allow-paused') parsed.allowPaused = true;
    else if (name === '--help') parsed.help = true;
    else if (['--url', '--timeout-ms', '--output'].includes(name) && args[index + 1] !== undefined && !args[index + 1].startsWith('--')) {
      const value = args[++index];
      if (name === '--url') parsed.url = value;
      else if (name === '--output') parsed.output = value;
      else { if (!/^\d+$/.test(value)) throw new Error('Invalid probe timeout.'); parsed.timeoutMs = Number(value); }
    } else throw new Error('Invalid probe arguments.');
  }
  probeUrl(parsed.url);
  if (!Number.isSafeInteger(parsed.timeoutMs) || parsed.timeoutMs < 100 || parsed.timeoutMs > 60000) throw new Error('Probe timeout must be 100 through 60000 milliseconds.');
  return parsed;
}
function addAlert(alerts, code, scope = 'service') {
  const safeCode = Object.hasOwn(ACTIONS, code) ? code : 'service_alert', safeScope = scopes.has(scope) ? scope : 'service';
  if (!alerts.some(value => value.code === safeCode && value.scope === safeScope)) alerts.push({ code: safeCode, scope: safeScope, action: ACTIONS[safeCode] });
}
export function summarizeStatus(status, { allowPaused = false } = {}) {
  if (!object(status) || status.schema !== 'operations-status/1' || !object(status.queue) || !object(status.resources) || !object(status.logging) || !Array.isArray(status.alerts) || typeof status.queue.available !== 'boolean' || typeof status.queue.maintenance !== 'boolean' || typeof status.queue.drained !== 'boolean' || typeof status.resources.allowed !== 'boolean' || typeof status.new_work_allowed !== 'boolean' || typeof status.logging.unavailable !== 'boolean' || count(status.logging.dropped) === null || count(status.logging.failed) === null) throw new Error('Invalid operations response.');
  const alerts = [];
  for (const alert of status.alerts.slice(0, 32)) if (object(alert)) addAlert(alerts, alert.code, alert.scope);
  if (!status.queue.available) addAlert(alerts, 'queue_unavailable', 'queue');
  if (status.logging.unavailable) addAlert(alerts, 'operations_log_unavailable', 'operations');
  if (count(status.logging.dropped) > 0) addAlert(alerts, 'operations_log_dropped', 'operations');
  if (count(status.logging.failed) > 0) addAlert(alerts, 'operations_log_failed', 'operations');
  if (status.queue.maintenance && !allowPaused) addAlert(alerts, 'maintenance_active', 'queue');
  if (status.queue.maintenance && !status.queue.drained) addAlert(alerts, 'queue_not_drained', 'queue');
  const admissionReady = status.queue.maintenance ? allowPaused && status.queue.drained : status.new_work_allowed;
  if ((!status.resources.allowed || !admissionReady) && alerts.length === 0) addAlert(alerts, 'admission_blocked');
  const ready = status.queue.available && status.resources.allowed && admissionReady && alerts.length === 0;
  return { ready, state: ready ? status.queue.maintenance ? 'paused-ready' : 'ready' : 'not-ready', exit_code: ready ? 0 : 2, alerts,
    queue: { available: status.queue.available, maintenance: status.queue.maintenance, drained: status.queue.drained, queued: count(status.queue.queued), running: count(status.queue.running), cancelling: count(status.queue.cancelling) },
    resources: { allowed: status.resources.allowed, host_rss_bytes: count(status.resources.host_rss_bytes), min_free_disk_bytes: count(status.resources.min_free_disk_bytes), max_host_rss_bytes: count(status.resources.max_host_rss_bytes),
      disks: Array.isArray(status.resources.disks) ? status.resources.disks.slice(0, 2).map(disk => ({ scope: scopes.has(disk.scope) ? disk.scope : 'service', free_bytes: count(disk.free_bytes) })) : [] },
    logging: { unavailable: Boolean(status.logging.unavailable), dropped: count(status.logging.dropped), failed: count(status.logging.failed) } };
}

export async function probeService({ url: input = 'http://127.0.0.1:3000', timeoutMs = 5000, allowPaused = false } = {}) {
  const url = probeUrl(input);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 60000) throw new Error('Invalid probe timeout.');
  const base = { schema: 'service-probe/1', checked_at: new Date().toISOString(), origin: url.origin, request_id: null };
  return new Promise(resolveReport => {
    let done = false;
    const finish = report => { if (!done) { done = true; clearTimeout(timer); resolveReport({ ...base, ...report }); } };
    const failed = code => finish({ ready: false, state: 'probe-failed', exit_code: 3, error: code, alerts: [{ code: 'probe_failed', scope: 'service', action: 'Check the service process, port and direct local operator access.' }] });
    const req = request(url, { method: 'GET', agent: false, headers: { Accept: 'application/json' },
      // Pin localhost to loopback rather than trusting a changed hosts/DNS entry.
      lookup: (_hostname, options, callback) => options.all ? callback(null, [{ address: '127.0.0.1', family: 4 }]) : callback(null, '127.0.0.1', 4),
    }, res => {
      const id = res.headers['x-eeg-request-id']; if (typeof id === 'string' && UUID.test(id)) base.request_id = id;
      if (res.statusCode !== 200) { failed('unexpected_http_status'); req.destroy(); return; }
      if (base.request_id === null) { failed('missing_request_id'); req.destroy(); return; }
      if (Number(res.headers['content-length']) > MAX_RESPONSE_BYTES) { failed('response_too_large'); req.destroy(); return; }
      const chunks = []; let bytes = 0;
      res.on('data', chunk => { bytes += chunk.length; if (bytes > MAX_RESPONSE_BYTES) { failed('response_too_large'); req.destroy(); } else chunks.push(chunk); });
      res.on('error', () => failed('response_interrupted'));
      res.on('aborted', () => failed('response_interrupted'));
      res.on('end', () => {
        if (done) return;
        try { const value = JSON.parse(Buffer.concat(chunks).toString('utf8')); finish(summarizeStatus(value, { allowPaused })); }
        catch { failed('invalid_operations_response'); }
      });
    });
    const timer = setTimeout(() => { failed('timeout'); req.destroy(); }, timeoutMs);
    req.on('error', () => failed('connection_failed')); req.end();
  });
}

export async function writeProbeReport(report, output, { projectRoot = PROJECT_ROOT } = {}) {
  const root = await realpath(projectRoot), artifacts = join(root, 'artifacts'), path = resolve(root, output), suffix = relative(artifacts, path);
  if (!suffix || isAbsolute(suffix) || suffix === '..' || suffix.startsWith('..' + sep)) throw new Error('Probe output must be inside this project artifacts directory.');
  let cursor = root;
  for (const part of relative(root, dirname(path)).split(sep)) {
    cursor = join(cursor, part); await mkdir(cursor, { mode: 0o700 }).catch(error => { if (error.code !== 'EEXIST') throw error; });
    const metadata = await lstat(cursor);
    if (!metadata.isDirectory() || metadata.isSymbolicLink() || await realpath(cursor) !== cursor) throw new Error('Probe output path is invalid.');
  }
  await lstat(path).then(metadata => { if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.nlink !== 1) throw new Error('Probe output path is invalid.'); }).catch(error => { if (error.code !== 'ENOENT') throw error; });
  await atomicJson(path, report);
}
export async function runProbe(args) {
  let options;
  try { options = parseProbeArgs(args); }
  catch { return { schema: 'service-probe/1', ready: false, state: 'invalid-arguments', exit_code: 4, error: 'Use a loopback HTTP URL, a bounded timeout and a project artifacts output path.' }; }
  if (options.help) return { schema: 'service-probe/1', exit_code: 0, usage: 'node scripts/probe-service.mjs [--url http://127.0.0.1:3000] [--timeout-ms 5000] [--allow-paused] [--output artifacts/qa/probe.json]' };
  const report = await probeService(options);
  if (options.output) {
    try { await writeProbeReport(report, options.output); }
    catch { return { schema: 'service-probe/1', ready: false, state: 'invalid-output', exit_code: 4, error: 'Probe output must use a regular path inside this project artifacts directory.' }; }
  }
  return report;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const report = await runProbe(process.argv.slice(2)); process.stdout.write(JSON.stringify(report) + '\n'); process.exitCode = report.exit_code;
}
