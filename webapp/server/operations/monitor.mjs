import { randomUUID } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { join } from 'node:path';
import { OperationsRequestLog } from './request-log.mjs';
import { operationsConfig } from './config.mjs';

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
const STATUS = new Set(['queued', 'running', 'cancelling', 'completed', 'no_layout', 'failed', 'cancelled', 'timeout']);
const METHODS = new Set(['GET', 'HEAD', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS']);
const CONTEXT = Symbol('EEG operations request context');
const finiteCount = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
export function correlateOperation(res, job) {
  const context = res[CONTEXT];
  if (!context || context.done || !job || !UUID.test(job.id)) return;
  context.task_id = job.id;
  if (STATUS.has(job.status)) context.task_status = job.status;
}
/** Fixed labels bound both cardinality and the data that can reach logs. */
export function operationRoute(url) {
  const path = typeof url === 'string' ? url.split('?')[0] : '';
  if (path === '/api/operations/status') return 'operations.status';
  if (path === '/api/robustness-studies') return 'studies.directory';
  if (/^\/api\/robustness-studies\/[a-f0-9-]{36}$/.test(path)) return 'studies.study';
  const study = path.match(/^\/api\/robustness-studies\/[a-f0-9-]{36}\/(start|resume|cancel|export)$/);
  if (study) return 'studies.' + study[1];
  if (path === '/api/projects') return 'projects.create';
  if (/^\/api\/projects\/[a-f0-9-]{36}$/.test(path)) return 'projects.project';
  if (/^\/api\/projects\/[a-f0-9-]{36}\/(share|revoke-share|export)$/.test(path)) return 'projects.' + path.split('/').at(-1);
  if (/^\/api\/projects\/[a-f0-9-]{36}\/entries(?:\/[a-f0-9-]{36})?$/.test(path)) return 'projects.entries';
  const task = path.match(/^\/api\/(local-compute|source-reception|design-evaluation|electrode-editor)\/(health|lookup|jobs)(?:\/[a-f0-9-]{36}(\/cancel)?)?$/);
  if (task) return `${task[1]}.${task[3] ? 'cancel' : task[2]}`;
  if (/^\/api\/local-compute\/library(?:\/[a-f0-9]{64}(?:\/bundle)?)?$/.test(path)) return 'local-compute.library';
  if (/^\/api\/(source-reception|design-evaluation|electrode-editor)\/(catalog|layouts|parents|records)$/.test(path)) return 'science.catalog';
  if (/^\/api\/community\/(status|records|heartbeat)(?:\/[a-f0-9-]{36}\/result)?$/.test(path)) return 'community.' + path.split('/')[3];
  if (path.startsWith('/api/')) return 'api.other';
  if (path.startsWith('/models/')) return 'asset.model';
  if (path.startsWith('/_next/') || path.startsWith('/assets/') || path.startsWith('/favicon.')) return 'asset.web';
  if (['/', '/findings', '/layout', '/channels', '/projects', '/deliveries', '/robustness', '/design', '/coordinates', '/electrodes', '/decision', '/reception', '/library', '/results', '/pilot-results', '/guide', '/method'].includes(path)) return 'page';
  return 'other';
}
export function directOperatorRequest(req) {
  const ip = req.socket?.remoteAddress;
  if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(ip) || typeof req.headers.host !== 'string' || !/^(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?$/.test(req.headers.host)) return false;
  return !Object.keys(req.headers).some(name => ['origin', 'forwarded', 'x-real-ip'].includes(name.toLowerCase()) || name.toLowerCase().startsWith('x-forwarded-') || name.toLowerCase().startsWith('sec-fetch-'));
}
function emptyCounter() { return { requests: 0, completed: 0, aborted: 0, errors: 0, duration_ms_total: 0, duration_ms_max: 0, statuses: { '1xx': 0, '2xx': 0, '3xx': 0, '4xx': 0, '5xx': 0, disconnected: 0 } }; }
function response(res, status, data) {
  if (res.closed || res.destroyed || res.writableEnded) return;
  if (res.headersSent) { res.destroy(); return; }
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-EEG-API-Version': '1', 'X-Content-Type-Options': 'nosniff', 'Cross-Origin-Resource-Policy': 'same-origin' });
  res.end(JSON.stringify(data));
}
export class OperationsMonitor {
  constructor({ queue, scheduler, gate, config = operationsConfig(), logger, now = () => new Date().toISOString(), clock = () => performance.now() }) {
    this.queue = queue; this.scheduler = scheduler; this.gate = gate; this.config = config; this.now = now; this.clock = clock; this.started = clock();
    this.logger = logger ?? new OperationsRequestLog(join(queue.runtime.queueDirectory, 'operations'), { config });
    this.totals = emptyCounter(); this.active = 0; this.routes = new Map();
  }
  correlate(res, job) { correlateOperation(res, job); }
  async status() {
    const resources = await this.gate.sample(), queue = this.scheduler, states = Object.fromEntries([...STATUS].map(status => [status, 0]));
    for (const task of queue.tasks ?? []) if (STATUS.has(task.status)) states[task.status]++;
    let maintenance = { maintenance: true, drained: false };
    try { maintenance = queue.maintenanceStatus(); } catch { /* Failure remains visible as an unavailable queue below. */ }
    const queuedTimes = (queue.tasks ?? []).filter(task => task.status === 'queued').map(task => Date.parse(task.created_at)).filter(Number.isFinite);
    const oldestQueuedAge = queuedTimes.length ? Math.max(0, Date.parse(this.now()) - Math.min(...queuedTimes)) : 0;
    const queueAvailable = !queue.disposed && !queue.stopping && !queue.failure, logs = this.logger.status();
    const alerts = [...resources.alerts];
    if (!queueAvailable) alerts.push({ code: 'queue_unavailable', scope: 'queue', action: 'Inspect the queue owner and service recovery before resuming submissions.' });
    if (queue.unconfirmedWorker || queue.blockedPids?.length) alerts.push({ code: 'queue_recovery_blocked', scope: 'queue', action: 'Follow the recorded worker recovery procedure before resuming submissions.' });
    if (logs.dropped > 0) alerts.push({ code: 'operations_log_dropped', scope: 'operations', action: 'Inspect request log queue pressure and the daily size limit; some request events were dropped.' });
    if (logs.unavailable) alerts.push({ code: 'operations_log_unavailable', scope: 'operations', action: 'Check log directory access, permissions and disk space.' });
    return { schema: 'operations-status/1', sampled_at: this.now(), uptime_ms: Math.max(0, this.clock() - this.started),
      requests: { ...structuredClone(this.totals), active: this.active, routes: structuredClone(Object.fromEntries(this.routes)) },
      queue: { available: queueAvailable, maintenance: Boolean(maintenance.maintenance), drained: Boolean(maintenance.drained), states,
        queued: states.queued, running: states.running, cancelling: states.cancelling, oldest_queued_age_ms: oldestQueuedAge, blocked_workers: finiteCount(queue.blockedPids?.length) + Number(Boolean(queue.unconfirmedWorker)) },
      resources, logging: logs, alerts, new_work_allowed: resources.allowed && queueAvailable && !maintenance.maintenance && !(queue.unconfirmedWorker || queue.blockedPids?.length) };
  }
  middleware(next) {
    return async (req, res, fallback) => {
      const request_id = randomUUID(), route = operationRoute(req.url), method = METHODS.has(req.method) ? req.method : 'OTHER';
      const context = { request_id, route, method, start: this.clock(), done: false }; res[CONTEXT] = context;
      if (!res.headersSent && !res.destroyed) res.setHeader('X-EEG-Request-Id', request_id);
      this.active++; this.totals.requests++;
      const counter = this.routes.get(route) ?? emptyCounter(); counter.requests++; this.routes.set(route, counter);
      const finish = aborted => {
        if (context.done) return; context.done = true; this.active--;
        const duration_ms = Math.max(0, this.clock() - context.start), status = aborted ? 0 : res.statusCode;
        for (const value of [this.totals, counter]) {
          value[aborted ? 'aborted' : 'completed']++; if (!aborted && status >= 500) value.errors++;
          value.duration_ms_total += duration_ms; value.duration_ms_max = Math.max(value.duration_ms_max, duration_ms);
          const bucket = aborted ? 'disconnected' : `${Math.floor(status / 100)}xx`; if (bucket in value.statuses) value.statuses[bucket]++;
        }
        try { this.logger.record({ at: this.now(), ...context, status, duration_ms, aborted }); } catch { /* Logging cannot fail an application request. */ }
      };
      res.once('finish', () => finish(false)); res.once('close', () => finish(!res.writableFinished));
      if ((req.url?.split('?')[0] ?? '') === '/api/operations/status') {
        if (!directOperatorRequest(req)) return response(res, 403, { error: 'Operations status requires a direct local operator request.', code: 'request_forbidden' });
        if (req.method !== 'GET' || req.url.includes('?')) return response(res, 405, { error: 'Use a direct local GET without query parameters.', code: 'method_not_allowed' });
        try { return response(res, 200, await this.status()); }
        catch { return response(res, 503, { error: 'Operations status is unavailable.', code: 'service_unavailable' }); }
      }
      try { return await next(req, res, fallback); }
      catch { return response(res, 500, { error: 'Request processing failed.', code: 'internal_error' }); }
    };
  }
  close() { this.logger.close(); }
  flush() { return this.logger.flush(); }
}
