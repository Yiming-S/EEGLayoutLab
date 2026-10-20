/** Single-host durable FIFO. Scientific services retain their own caches and workers. */
import { createHash, randomBytes, randomUUID, timingSafeEqual, createHmac } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, renameSync, statSync, unlinkSync, writeFileSync, appendFileSync } from 'node:fs';
import { join } from 'node:path';

const pending = j => ['queued', 'running', 'cancelling'].includes(j.status);
const digest = text => createHash('sha256').update(text).digest('hex');
const alive = pid => { try { process.kill(pid, 0); return true; } catch (e) { return e.code !== 'ESRCH'; } };
const error = (message, status = 400) => Object.assign(new Error(message), { status });
function save(path, value) {
  const tmp = `${path}.${randomUUID()}.tmp`;
  const fd = openSync(tmp, 'wx', 0o600);
  try { writeFileSync(fd, JSON.stringify(value)); fsyncSync(fd); } finally { closeSync(fd); }
  renameSync(tmp, path);
  const dir = openSync(join(path, '..'), 'r');
  try { fsyncSync(dir); } finally { closeSync(dir); }
}

export class CommunityQueue {
  constructor({ directory, adapters, now = Date.now, maxQueued = 50, maxPerVisitor = 3, pollMs = 250 }) {
    this.directory = directory; this.adapters = adapters; this.now = now;
    this.maxQueued = maxQueued; this.maxPerVisitor = maxPerVisitor;
    this.tasks = []; this.sequence = 0; this.visitors = new Map(); this.rates = new Map();
    this.chain = Promise.resolve(); this.disposed = false; this.activeId = null; this.blockedPids = [];
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    this.lockPath = join(directory, 'worker.lock');
    this.lockToken = randomUUID();
    // Serialize all lock acquisition, including stale-owner takeover. A leftover
    // acquisition guard fails closed and requires operator inspection.
    const guardPath = join(directory, 'acquiring.lock');
    const guardFd = openSync(guardPath, 'wx', 0o600);
    try {
      writeFileSync(guardFd, String(process.pid));
      if (existsSync(this.lockPath)) {
        const lock = JSON.parse(readFileSync(this.lockPath, 'utf8'));
        if (!Number.isInteger(lock.pid) || alive(lock.pid)) throw new Error('The computation queue is already owned by another server.');
        unlinkSync(this.lockPath);
      }
      const fd = openSync(this.lockPath, 'wx', 0o600);
      try { writeFileSync(fd, JSON.stringify({ pid: process.pid, token: this.lockToken })); fsyncSync(fd); } finally { closeSync(fd); }
    } finally { closeSync(guardFd); unlinkSync(guardPath); }
    try {
      const path = join(directory, 'queue.json');
      const data = existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')) : { version: 1, sequence: 0, tasks: [] };
      if (data.version !== 1 || !Array.isArray(data.tasks)) throw new Error('Unsupported queue state; preserve the file for recovery.');
      this.tasks = data.tasks; this.sequence = data.sequence;
      const secretPath = join(directory, 'session-secret.json');
      if (!existsSync(secretPath)) save(secretPath, { key: randomBytes(32).toString('hex') });
      this.secret = JSON.parse(readFileSync(secretPath, 'utf8')).key;
      for (const task of this.tasks) {
        if (task.workerPid && alive(task.workerPid)) this.blockedPids.push(task.workerPid);
        if (task.starting && !task.workerPid) this.unconfirmedWorker = true;
        if (['running', 'cancelling'].includes(task.status)) {
          task.status = 'failed'; task.message = '服务重启中断了计算，可重新提交'; task.finished_at = new Date(this.now()).toISOString();
        }
      }
      this.persist();
    } catch (e) { this.releaseLock(); throw e; }
    this.timer = setInterval(() => { void this.serial(() => this.tick()).catch(e => this.failClosed(e)); }, pollMs);
    this.timer.unref();
  }
  serial(fn) {
    const next = this.chain.then(fn);
    this.chain = next.catch(() => {});
    return next;
  }
  persist() {
    // Retain active tasks and the newest 500 terminal receipts. Results live in scientific caches.
    const terminal = this.tasks.filter(t => !pending(t)).slice(-500);
    this.tasks = this.tasks.filter(t => pending(t) || t.workerPid || t.starting || terminal.includes(t));
    try { save(join(this.directory, 'queue.json'), { version: 1, sequence: this.sequence, tasks: this.tasks }); }
    catch (e) { this.failClosed(e); throw e; }
  }
  failClosed(e) { this.failure = e.message; }
  session(req, res) {
    const cookies = String(req.headers.cookie || '').split(';').map(s => s.trim());
    let value = cookies.find(s => s.startsWith('eeg_visitor='))?.slice(12);
    const valid = v => {
      if (!/^[a-f0-9]{64}\.[a-f0-9]{64}$/.test(v || '')) return false;
      const [id, signature] = v.split('.');
      const expected = createHmac('sha256', this.secret).update(id).digest('hex');
      return timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
    };
    if (!valid(value)) {
      const id = randomBytes(32).toString('hex');
      value = `${id}.${createHmac('sha256', this.secret).update(id).digest('hex')}`;
      res.setHeader('Set-Cookie', `eeg_visitor=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000`);
    }
    // Never trust X-Forwarded-For on this loopback-only service.
    return { id: digest(value), ip: req.socket?.remoteAddress || 'unknown' };
  }
  touch(visitor, visible) {
    const now = this.now();
    for (const [id, last] of this.visitors) if (now - last > 90000) this.visitors.delete(id);
    if (!visible) return;
    if (!this.visitors.has(visitor.id)) this.logVisit(visitor);
    this.visitors.set(visitor.id, now);
  }
  logVisit(visitor) {
    const directory = this.pruneLogs();
    const today = new Date(this.now()).toISOString().slice(0, 10);
    const path = join(directory, `${today}.jsonl`);
    // Bound logs even under repeated anonymous-cookie resets.
    if (existsSync(path) && statSync(path).size >= 10 * 1024 * 1024) return;
    appendFileSync(path, JSON.stringify({ at: new Date(this.now()).toISOString(), ip: visitor.ip, visitor: visitor.id }) + '\n', { mode: 0o600 });
  }
  pruneLogs() {
    const directory = join(this.directory, 'access'); mkdirSync(directory, { recursive: true, mode: 0o700 });
    for (const name of readdirSync(directory)) {
      if (/^\d{4}-\d{2}-\d{2}\.jsonl$/.test(name) && this.now() - Date.parse(name.slice(0, 10)) > 7 * 86400000) unlinkSync(join(directory, name));
    }
    this.lastLogPrune = this.now(); return directory;
  }
  rate(visitor) {
    const now = this.now();
    for (const [key, v] of this.rates) if (now - v.start > 60000) this.rates.delete(key);
    for (const [key, max] of [[`v:${visitor.id}`, 20], [`ip:${visitor.ip}`, 100]]) {
      const entry = this.rates.get(key) || { start: now, count: 0 };
      entry.count++; this.rates.set(key, entry);
      if (entry.count > max) throw error('提交过于频繁，请一分钟后重试', 429);
    }
  }
  async submit(kind, raw, visitor, lookupOnly = false) {
    // This lock establishes server acceptance order before asynchronous identity validation.
    return this.serial(async () => {
      if (this.disposed || this.failure) throw error('计算队列不可用，请稍后重试', 503);
      this.rate(visitor);
      const adapter = this.adapters[kind];
      const prepared = await adapter.prepare(raw);
      const ready = await adapter.lookup(prepared);
      if (this.disposed) throw error('计算队列不可用，请稍后重试', 503);
      if (ready.hit) {
        const task = this.receipt(kind, prepared, visitor, ready.job.status);
        task.cached = true; task.finished_at = ready.job.finished_at || new Date(this.now()).toISOString();
        task.catalog = receiptCatalog(kind, prepared, ready.job.result);
        this.persist();
        return { hit: true, job: { ...ready.job, id: task.id, kind } };
      }
      const existing = this.tasks.find(t => t.kind === kind && t.key === prepared.key && ['queued', 'running'].includes(t.status));
      if (existing) {
        if (!existing.owners.includes(visitor.id)) {
          this.checkVisitorLimit(visitor); existing.owners.push(visitor.id); this.persist();
        }
        return { hit: true, job: await this.view(existing) };
      }
      if (lookupOnly) return { hit: false };
      this.checkVisitorLimit(visitor);
      if (this.tasks.filter(pending).length >= this.maxQueued) throw error('队列已满，请稍后提交；已有结果仍可读取', 429);
      const task = this.receipt(kind, prepared, visitor, 'queued');
      this.persist();
      return { job: await this.view(task) };
    });
  }
  checkVisitorLimit(visitor) {
    if (this.tasks.filter(t => pending(t) && t.owners.includes(visitor.id)).length >= this.maxPerVisitor) throw error('当前浏览器最多保留3个未完成任务', 429);
  }
  receipt(kind, prepared, visitor, status) {
    if (['completed', 'no_layout'].includes(status)) {
      const same = this.tasks.find(t => t.kind === kind && t.key === prepared.key && t.owners.includes(visitor.id) && t.status === status);
      if (same) return same;
    }
    const task = { id: randomUUID(), sequence: ++this.sequence, kind, key: prepared.key, request: prepared.request,
      owners: [visitor.id], status, created_at: new Date(this.now()).toISOString(), progress: 0, cached: false,
      catalog: receiptCatalog(kind, prepared) };
    this.tasks.push(task); return task;
  }
  async view(task, result = true) {
    const adapter = this.adapters[task.kind];
    const worker = task.backendId ? adapter.get(task.backendId) : null;
    let value = worker || {};
    if (!worker && result && ['completed', 'no_layout'].includes(task.status)) {
      const prepared = await adapter.prepare(task.request);
      if (prepared.key !== task.key) return { ...taskView(task), status: 'failed', message: '模型或代码已更新，请重新提交', result: null };
      const cached = await adapter.lookup(prepared);
      if (!cached.hit) return { ...taskView(task), status: 'failed', message: '计算记录无法读取，请重新提交', result: null };
      value = cached.job;
    }
    const position = task.status === 'queued' ? this.tasks.filter(t => t.status === 'queued' && t.sequence <= task.sequence).length : 0;
    const combined = { ...value, ...taskView(task), progress: value.progress ?? task.progress, cached: task.cached || Boolean(value.cached), queue_position: position };
    combined.message = task.status === 'queued' ? '已加入计算队列' : task.message || value.message || task.status;
    combined.result = result ? (['completed', 'no_layout'].includes(task.status) ? value.result ?? null : null) : undefined;
    return combined;
  }
  own(id, visitor, kind) {
    const task = this.tasks.find(t => t.id === id && (!kind || t.kind === kind) && t.owners.includes(visitor.id));
    if (!task) throw error('任务不存在或不属于当前浏览器', 404);
    return task;
  }
  cancel(id, visitor, kind) {
    return this.serial(async () => {
      const task = this.own(id, visitor, kind);
      if (!pending(task)) return this.view(task);
      if (task.owners.length > 1) {
        task.owners = task.owners.filter(id => id !== visitor.id); this.persist();
        return { ...taskView(task), status: 'cancelled', result: null, message: '已退出共享任务，其他访客的计算继续' };
      }
      if (task.status === 'queued') {
        task.status = 'cancelled'; task.finished_at = new Date(this.now()).toISOString();
      } else { this.adapters[task.kind].cancel(task.backendId); task.status = 'cancelling'; }
      this.persist(); return this.view(task);
    });
  }
  async tick() {
    if (this.disposed || this.failure) return;
    if (!this.lastLogPrune || this.now() - this.lastLogPrune > 3600000) this.pruneLogs();
    this.blockedPids = this.blockedPids.filter(alive);
    if (this.blockedPids.length || this.unconfirmedWorker) return;
    if (this.activeId) {
      const task = this.tasks.find(t => t.id === this.activeId), adapter = this.adapters[task.kind];
      const worker = adapter.get(task.backendId);
      // Services clear active only after result validation and durable cache writes.
      if (adapter.busy()) return;
      task.status = worker?.status || 'failed'; task.message = worker?.message || '计算进程未返回结果';
      task.finished_at = new Date(this.now()).toISOString(); task.progress = worker?.progress || 0;
      if (worker?.result) task.catalog = { ...task.catalog, ...receiptCatalog(task.kind, { request: task.request }, worker.result) };
      task.cached = Boolean(worker?.cached); delete task.workerPid; delete task.starting; this.activeId = null; this.persist();
    }
    if (Object.values(this.adapters).some(a => a.busy())) return;
    const next = this.tasks.find(t => t.status === 'queued');
    if (!next) return;
    const adapter = this.adapters[next.kind];
    try {
      const prepared = await adapter.prepare(next.request);
      if (this.disposed) return;
      if (prepared.key !== next.key) throw new Error('排队后模型或代码已更新，请重新提交');
      // Persist starting intent before launching a subprocess.
      next.status = 'running'; next.starting = true; this.activeId = next.id; this.persist();
      const started = await adapter.start(next.request);
      if (this.disposed) return;
      if (started.busy || !started.job) throw new Error('计算资源被其他进程占用，请重新提交');
      next.backendId = started.job.id;
      next.workerPid = adapter.pid(); next.starting = false; this.persist();
      if (started.job.key !== next.key) { adapter.cancel(next.backendId); throw new Error('排队后模型或代码已更新，请重新提交'); }
    } catch (e) {
      if (this.disposed) return;
      next.status = 'failed'; next.message = e.message; next.finished_at = new Date(this.now()).toISOString();
      this.activeId = null; this.persist();
    }
  }
  async stats(visitor) {
    const jobs = this.tasks.filter(t => t.owners.includes(visitor.id)).slice(-12).reverse();
    return { online_visitors: [...this.visitors.values()].filter(t => this.now() - t <= 90000).length,
      queued_tasks: this.tasks.filter(t => t.status === 'queued').length,
      running_tasks: Number(Boolean(this.activeId || this.blockedPids.length)),
      available: !this.failure && !this.disposed, recovery_blocked: this.blockedPids.length > 0 || Boolean(this.unconfirmedWorker),
      jobs: await Promise.all(jobs.map(t => this.view(t, false))) };
  }
  records(visitor) {
    // The durable receipts are small and already bounded to 500 terminal tasks.
    // Do not load waveform caches or expose another browser's request history.
    const newest = new Map();
    for (const task of this.tasks) {
      if (task.kind !== 'source-reception' || task.status !== 'completed' || !task.owners.includes(visitor.id)) continue;
      const previous = newest.get(task.key);
      if (!previous || task.sequence > previous.sequence) newest.set(task.key, task);
    }
    return { schema: 'browser-experiment-records/1', scope: 'current_browser', receipt_limit: 500,
      records: [...newest.values()].sort((a, b) => b.sequence - a.sequence).map(taskView) };
  }
  async active(kind, visitor) {
    const task = this.tasks.find(t => t.kind === kind && pending(t) && t.owners.includes(visitor.id));
    return task ? this.view(task, false) : null;
  }
  releaseLock() {
    if (existsSync(this.lockPath) && JSON.parse(readFileSync(this.lockPath, 'utf8')).token === this.lockToken) unlinkSync(this.lockPath);
  }
  dispose() {
    if (this.disposed) return;
    this.disposed = true; clearInterval(this.timer);
    // Leave queued receipts intact. A running job is reported as interrupted on restart.
    this.persist(); this.releaseLock();
  }
}
function taskView(t) {
  return { id: t.id, key: t.key, kind: t.kind, request: t.request, status: t.status, stage: t.status,
    created_at: t.created_at, finished_at: t.finished_at ?? null, cached: t.cached,
    source: t.cached ? 'local_cache' : 'local_compute', catalog: t.catalog ?? null };
}

export function receiptCatalog(kind, prepared, result) {
  const request = prepared.request, parent = prepared.ctx?.record ?? prepared.ctx?.parent;
  const catalog = {};
  if (parent) {
    catalog.parent_label = parent.label;
    catalog.region_count = parent.region_count;
    catalog.mask_codes = parent.request?.mask_codes ?? [];
    catalog.location_mode = parent.mode;
    if (parent.layout?.xyzMm) catalog.electrode_count = parent.layout.xyzMm.length;
  }
  if (kind === 'source-reception') {
    catalog.parent_id = request.record_id;
    catalog.protocol = result?.schema_version ?? (request.mode ? 'source-reception/2' : 'source-reception/1');
    if (result?.layout?.xyzMm) catalog.electrode_count = result.layout.xyzMm.length;
    if (result?.conditions) catalog.conditions = result.conditions.map(({ condition, field_retention, baseline, candidate }) => ({
      condition, field_retention,
      baseline_explained_energy: baseline.explained_energy,
      candidate_explained_energy: candidate.explained_energy,
    }));
  }
  if (kind === 'electrode-editor') {
    catalog.parent_id = request.parent_id;
    catalog.protocol = result?.schema ?? 'electrode-editor/1';
    if (request.action === 'evaluate') catalog.electrode_count = request.slots.filter(slot => slot.enabled).length;
  }
  return catalog;
}

export function communityMiddleware({ scheduler, legacy, queue, guard, send, tokenMatches }) {
  return async (req, res, next) => {
    const path = req.url?.split('?')[0] || '/';
    const endpoint = path.match(/^\/api\/(local-compute|source-reception|design-evaluation|electrode-editor)\/(jobs|lookup|health)(?:\/([a-f0-9-]{36})(\/cancel)?)?$/);
    const community = path.startsWith('/api/community/');
    if (!endpoint && !community) {
      // Set the cookie on document navigation before concurrent client API requests begin.
      if (guard(req) && req.method === 'GET' && (req.headers['sec-fetch-dest'] === 'document' || String(req.headers.accept).includes('text/html'))) scheduler.session(req, res);
      return legacy(req, res, next);
    }
    if (!guard(req)) return send(res, 403, { error: '计算接口只接受本机同源请求' });
    try {
      const visitor = scheduler.session(req, res);
      if (community) {
        if (path === '/api/community/status' && req.method === 'GET') return send(res, 200, await scheduler.stats(visitor));
        if (path === '/api/community/records' && req.method === 'GET') return send(res, 200, scheduler.records(visitor));
        const savedMatch = path.match(/^\/api\/community\/records\/([a-f0-9-]{36})\/result$/);
        if (savedMatch && req.method === 'GET') {
          const task = scheduler.own(savedMatch[1], visitor, 'source-reception');
          if (task.status !== 'completed') return send(res, 404, { error: '计算记录无法读取，请重新提交' });
          return send(res, 200, { result: await scheduler.adapters['source-reception'].savedResult(task.key, task.request) });
        }
        if (path === '/api/community/heartbeat' && req.method === 'POST') {
          if (!tokenMatches(req.headers['x-eeg-compute-token'], queue.token)) return send(res, 403, { error: '刷新页面后重试' });
          scheduler.touch(visitor, req.headers['x-eeg-visible'] === '1');
          return send(res, 200, await scheduler.stats(visitor));
        }
        return send(res, 404, { error: 'Unknown community endpoint' });
      }
      const [, kind, action, id, cancel] = endpoint;
      if (action === 'health' && req.method === 'GET') return send(res, 200, { ...queue.health(), active_job: await scheduler.active(kind, visitor) });
      if (req.method === 'POST' && !tokenMatches(req.headers['x-eeg-compute-token'], queue.token)) return send(res, 403, { error: '本地会话已更新，请刷新页面后重新计算' });
      if (id && action === 'jobs') {
        if (req.method === 'GET' && !cancel) return send(res, 200, { job: await scheduler.view(scheduler.own(id, visitor, kind)) });
        if (req.method === 'POST' && cancel) return send(res, 202, { job: await scheduler.cancel(id, visitor, kind) });
      }
      if (req.method === 'POST' && !id && ['jobs', 'lookup'].includes(action)) {
        if (!String(req.headers['content-type']).startsWith('application/json')) return send(res, 415, { error: 'JSON required' });
        const limit = kind === 'design-evaluation' ? 65536 : kind === 'electrode-editor' ? 32768 : 4096;
        let body = '';
        for await (const chunk of req) { body += chunk; if (Buffer.byteLength(body) > limit) return send(res, 413, { error: '配置过大' }); }
        const value = await scheduler.submit(kind, JSON.parse(body), visitor, action === 'lookup');
        return send(res, action === 'lookup' ? 200 : 202, value);
      }
      return send(res, 404, { error: 'Unknown queue endpoint' });
    } catch (e) { return send(res, e.status || 400, { error: e.message }); }
  };
}
