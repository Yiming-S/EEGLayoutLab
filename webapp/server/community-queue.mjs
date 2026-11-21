/** Single-host durable FIFO. Scientific services retain their own caches and workers. */
import { createHash, randomBytes, randomUUID, timingSafeEqual, createHmac } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, renameSync, statSync, unlinkSync, writeFileSync, appendFileSync } from 'node:fs';
import { join } from 'node:path';
import { ANNOTATION_LIMITS } from './annotations/electrode-names.mjs';
import { networkId, NetworkWindow } from './http/network-identity.mjs';
import { publicFailure, publicMessage } from './http/public-errors.mjs';
import { Gate } from './http/concurrency.mjs';

const pending = j => ['queued', 'running', 'cancelling'].includes(j.status);
const digest = text => createHash('sha256').update(text).digest('hex');
const alive = pid => { try { process.kill(pid, 0); return true; } catch (e) { return e.code !== 'ESRCH'; } };
const error = (message, status = 400) => Object.assign(new Error(message), { status });
function save(path, value) {
  const tmp = `${path}.${randomUUID()}.tmp`;
  const fd = openSync(tmp, 'wx', 0o600);
  try {
    try { writeFileSync(fd, JSON.stringify(value)); fsyncSync(fd); } finally { closeSync(fd); }
    renameSync(tmp, path);
  } catch (e) {
    // A full disk must not also leave a partial temporary file behind.
    try { unlinkSync(tmp); } catch {}
    throw e;
  }
  const dir = openSync(join(path, '..'), 'r');
  try { fsyncSync(dir); } finally { closeSync(dir); }
}

export class CommunityQueue {
  constructor({ directory, adapters, now = Date.now, maxQueued = 50, maxPerVisitor = 3, maxPerNetwork = 6, pollMs = 250,
    receiptLimits = RECEIPT_LIMITS, initialMaintenance = false, executionSlot, secureCookies = false, visitorAddress, annotations, visibility, beforeNewWork = async () => {} } = {}) {
    if (typeof beforeNewWork !== 'function') throw new TypeError('New work admission must be a function.');
    this.beforeNewWork = beforeNewWork; this.resourceBlocked = null; this.stopping = false;
    if (typeof initialMaintenance !== 'boolean') throw new TypeError('initialMaintenance must be boolean');
    this.directory = directory; this.adapters = adapters; this.now = now; this.annotations = annotations; this.visibility = visibility;
    this.executionSlot = executionSlot;
    this.secureCookies = secureCookies;
    this.visitorAddress = visitorAddress ?? (req => req.socket?.remoteAddress || 'unknown');
    this.maintenance = initialMaintenance;
    this.maxQueued = maxQueued; this.maxPerVisitor = maxPerVisitor; this.maxPerNetwork = maxPerNetwork;
    this.receiptLimits = { ...RECEIPT_LIMITS, ...receiptLimits };
    // Electrode-name variants are cheap to request and each one is a file; bound them per network.
    this.annotationWindow = new NetworkWindow({ limit: 60, windowMs: 3600000, now: () => this.now(),
      message: '同一网络一小时内最多新建60组电极名称，请稍后再试' });
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
      if (data.version !== 1 || !Array.isArray(data.tasks) ||
          (data.maintenance !== undefined && typeof data.maintenance !== 'boolean')) throw new Error('Unsupported queue state; preserve the file for recovery.');
      this.tasks = data.tasks; this.sequence = data.sequence;
      // Startup may force a pause, but only an explicit operator action resumes
      // a durable maintenance state. Older version-1 files default to running.
      this.maintenance = initialMaintenance || data.maintenance === true;
      if (this.maintenance) this.executionSlot?.pause();
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
    this.tasks = retainReceipts(this.tasks, this.receiptLimits);
    try { save(join(this.directory, 'queue.json'), { version: 1, sequence: this.sequence, maintenance: this.maintenance, tasks: this.tasks }); }
    catch (e) { this.persistFailed = true; this.failClosed(e); throw e; }
  }
  failClosed(e) { this.failure = e.message; console.error('[eeg] computation queue stopped:', e); }
  /** A failed write (for example a full disk) stops the queue; retry it so freeing space resumes service. */
  recoverPersistence() {
    if (!this.persistFailed || this.disposed || this.stopping) return false;
    try { save(join(this.directory, 'queue.json'), { version: 1, sequence: this.sequence, maintenance: this.maintenance, tasks: this.tasks }); }
    catch { return false; }
    this.persistFailed = false; this.failure = null; return true;
  }
  setMaintenance(enabled) {
    if (typeof enabled !== 'boolean') throw new TypeError('Maintenance state must be boolean');
    if (this.disposed || this.stopping || this.failure) throw error('计算队列不可用，请稍后重试', 503);
    // Deliberately synchronous: a pending prepare/start must observe the gate as
    // soon as the operator requests it, rather than waiting behind serial work.
    this.maintenance = enabled;
    if (enabled) this.executionSlot?.pause();
    try { this.persist(); }
    catch (e) { this.maintenance = true; this.executionSlot?.pause(); throw e; }
    if (!enabled) this.executionSlot?.resume();
    return this.maintenanceStatus();
  }
  maintenanceStatus() {
    const guarded = this.unconfirmedWorker || this.blockedPids.some(alive) ||
      this.tasks.some(task => task.starting || (task.workerPid && alive(task.workerPid)));
    return { maintenance: this.maintenance,
      drained: Boolean(this.maintenance && !this.disposed && !this.failure && !this.activeId && !guarded &&
        !this.executionSlot?.busy && !Object.values(this.adapters).some(adapter => adapter.busy())) };
  }
  session(req, res, { renew = false } = {}) {
    const cookies = String(req.headers.cookie || '').split(';').map(s => s.trim());
    let value = cookies.find(s => s.startsWith('eeg_visitor='))?.slice(12);
    const valid = v => {
      if (!/^[a-f0-9]{64}\.[a-f0-9]{64}$/.test(v || '')) return false;
      const [id, signature] = v.split('.');
      const expected = createHmac('sha256', this.secret).update(id).digest('hex');
      return timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
    };
    const fresh = !valid(value);
    if (fresh) {
      const id = randomBytes(32).toString('hex');
      value = `${id}.${createHmac('sha256', this.secret).update(id).digest('hex')}`;
    }
    // Page visits renew the 30-day lifetime, so a returning browser keeps its records listed.
    if (fresh || renew) res.setHeader('Set-Cookie', `eeg_visitor=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000${this.secureCookies ? '; Secure' : ''}`);
    // The configured access policy resolves client addresses only after validating the proxy.
    const ip = this.visitorAddress(req);
    return { id: digest(value), ip, network: networkId(this.secret, ip) };
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
  network(visitor) {
    return visitor?.network ?? (visitor?.ip ? networkId(this.secret, visitor.ip) : undefined);
  }
  rate(visitor) {
    const now = this.now();
    for (const [key, v] of this.rates) if (now - v.start > 60000) this.rates.delete(key);
    // Per network rather than per address: one IPv6 subscriber controls a whole /64.
    const network = this.network(visitor);
    for (const [key, max] of [[`v:${visitor.id}`, 20], ...(network ? [[`net:${network}`, 100]] : [])]) {
      const entry = this.rates.get(key) || { start: now, count: 0 };
      entry.count++; this.rates.set(key, entry);
      if (entry.count > max) throw error('提交过于频繁，请一分钟后重试', 429);
    }
  }
  async submit(kind, raw, visitor, lookupOnly = false, expectedKey, canAccept) {
    if (canAccept !== undefined && typeof canAccept !== 'function') throw new TypeError('Task admission guard must be a function.');
    const accept = prepared => {
      if (expectedKey !== undefined && prepared.key !== expectedKey) throw error('Scientific identity changed before task acceptance.', 409);
      if (canAccept && canAccept() !== true) throw Object.assign(error('Study no longer authorizes this child submission.', 409), { studyAdmissionCancelled: true });
    };
    // This lock establishes server acceptance order before asynchronous identity validation.
    return this.serial(async () => {
      if (this.disposed || this.stopping || this.failure) throw error('计算队列不可用，请稍后重试', 503);
      this.rate(visitor);
      const adapter = this.adapters[kind];
      const prepared = await adapter.prepare(raw);
      accept(prepared);
      const ready = await adapter.lookup(prepared);
      accept(prepared);
      if (this.disposed || this.stopping || this.failure) throw error('计算队列不可用，请稍后重试', 503);
      if (ready.hit) {
        const previous = this.tasks.find(t => t.kind === kind && t.key === prepared.key && t.owners.includes(visitor.id) && t.status === ready.job.status);
        const annotation = await this.annotationFor(prepared, visitor, previous, false, () => accept(prepared));
        accept(prepared);
        if (this.disposed || this.stopping || this.failure) throw error('计算队列不可用，请稍后重试', 503);
        const count = this.tasks.length;
        const task = this.receipt(kind, prepared, visitor, ready.job.status);
        this.attachAnnotation(task, visitor, annotation);
        // A receipt this browser earned by computing keeps that status (and its retention pool);
        // this reply is still a replay of the saved result.
        const created = this.tasks.length !== count;
        if (created) {
          task.cached = true;
          task.finished_at = ready.job.finished_at || new Date(this.now()).toISOString();
          task.catalog = receiptCatalog(kind, prepared, ready.job.result);
        }
        if (['completed', 'no_layout'].includes(ready.job.status)) await this.claim(kind, prepared.key, visitor.id);
        // Repeating a lookup of a result this browser already holds changes nothing durable.
        if (created || annotation) this.persist();
        return { hit: true, job: { ...ready.job, ...taskView(task), cached: true, ...this.annotationView(task, visitor, annotation?.id) } };
      }
      const existing = this.tasks.find(t => t.kind === kind && t.key === prepared.key && ['queued', 'running'].includes(t.status));
      if (existing) {
        if (!existing.owners.includes(visitor.id)) this.checkVisitorLimit(visitor);
        const annotation = await this.annotationFor(prepared, visitor, existing, false, () => accept(prepared));
        accept(prepared);
        if (this.disposed || this.stopping || this.failure) throw error('计算队列不可用，请稍后重试', 503);
        if (!existing.owners.includes(visitor.id)) {
          this.checkVisitorLimit(visitor); existing.owners.push(visitor.id);
          const network = this.network(visitor);
          if (network && !(existing.networks ??= []).includes(network)) existing.networks.push(network);
        }
        this.attachAnnotation(existing, visitor, annotation); this.persist();
        return { hit: true, job: await this.view(existing, true, visitor, annotation?.id) };
      }
      if (lookupOnly) return { hit: false };
      if (this.maintenance) throw Object.assign(error('服务维护中，已有结果仍可读取；请稍后提交新计算', 503), { admissionRejected: true });
      this.checkVisitorLimit(visitor);
      if (this.tasks.filter(pending).length >= this.maxQueued) throw error('队列已满，请稍后提交；已有结果仍可读取', 429);
      await this.beforeNewWork();
      accept(prepared);
      if (this.disposed || this.stopping || this.failure) throw error('计算队列不可用，请稍后重试', 503);
      if (this.maintenance || this.executionSlot?.paused) throw Object.assign(error('服务维护中，已有结果仍可读取；请稍后提交新计算', 503), { admissionRejected: true });
      this.resourceBlocked = null;
      const annotation = await this.annotationFor(prepared, visitor, null, true, () => accept(prepared));
      accept(prepared);
      if (this.disposed || this.stopping || this.failure) throw error('计算队列不可用，请稍后重试', 503);
      if (this.maintenance || this.executionSlot?.paused) throw Object.assign(error('服务维护中，已有结果仍可读取；请稍后提交新计算', 503), { admissionRejected: true });
      const task = this.receipt(kind, prepared, visitor, 'queued');
      this.attachAnnotation(task, visitor, annotation);
      this.persist();
      return { job: await this.view(task, true, visitor, annotation?.id) };
    });
  }
  async annotationFor(prepared, visitor, task, admitted = false, accept = () => {}) {
    if (!prepared.electrode_names) return null;
    if (!this.annotations) throw error('Electrode name storage is unavailable.', 503);
    const id = this.annotations.identity(prepared, visitor.id).id, refs = task?.annotation_refs?.[visitor.id] ?? [];
    if (refs.includes(id)) return this.annotations.read(id, visitor.id, prepared.key);
    if (!refs.includes(id) && refs.length >= ANNOTATION_LIMITS.referencesPerOwner) throw error('This task already has 20 electrode name variants.', 413);
    if (Object.values(task?.annotation_refs ?? {}).reduce((sum, ids) => sum + ids.length, 0) >= ANNOTATION_LIMITS.referencesPerTask) throw error('This task already has 100 electrode name variants.', 413);
    if (!admitted) await this.beforeNewWork();
    accept();
    if (this.disposed || this.stopping || this.failure) throw error('计算队列不可用，请稍后重试', 503);
    this.annotationWindow.take(this.network(visitor));
    return this.annotations.create(prepared, visitor.id);
  }
  attachAnnotation(task, visitor, annotation) {
    if (!annotation) return;
    task.annotation_refs ??= {};
    const previous = task.annotation_refs[visitor.id] ?? [];
    task.annotation_refs[visitor.id] = [...previous.filter(id => id !== annotation.id), annotation.id];
  }
  annotationView(task, visitor, selected) {
    if (!visitor) return {};
    const refs = task.annotation_refs?.[visitor.id] ?? [], id = selected;
    if (!id) return {};
    if (!refs.includes(id)) throw error('Electrode name annotation not found.', 404);
    return { annotation_id: id, electrode_annotation: this.annotations.read(id, visitor.id, task.key) };
  }
  checkVisitorLimit(visitor) {
    if (this.tasks.filter(t => pending(t) && t.owners.includes(visitor.id)).length >= this.maxPerVisitor) throw error(`当前浏览器最多保留${this.maxPerVisitor}个未完成任务`, 429);
    // A fresh cookie is free, so the same cap also applies to the client network.
    const network = this.network(visitor);
    if (network && this.tasks.filter(t => pending(t) && t.networks?.includes(network)).length >= this.maxPerNetwork)
      throw error(`同一网络最多保留${this.maxPerNetwork}个未完成任务，请等前面的任务完成`, 429);
  }
  async claim(kind, key, owner) {
    // Library ownership is presentation metadata; failing to record it must not stop the queue.
    try { await this.visibility?.claim(kind, key, owner); }
    catch (e) { console.error('[eeg] library ownership not recorded:', e); }
  }
  receipt(kind, prepared, visitor, status) {
    if (['completed', 'no_layout'].includes(status)) {
      const same = this.tasks.find(t => t.kind === kind && t.key === prepared.key && t.owners.includes(visitor.id) && t.status === status);
      if (same) return same;
    }
    const network = this.network(visitor);
    const task = { id: randomUUID(), sequence: ++this.sequence, kind, key: prepared.key, request: prepared.request,
      owners: [visitor.id], ...(network ? { networks: [network] } : {}), status, created_at: new Date(this.now()).toISOString(), progress: 0, cached: false,
      catalog: receiptCatalog(kind, prepared) };
    this.tasks.push(task); return task;
  }
  async view(task, result = true, visitor, annotationId) {
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
    return { ...combined, ...this.annotationView(task, visitor, annotationId) };
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
    if (this.failure && !this.recoverPersistence()) return;
    if (this.disposed || this.stopping || this.failure) return;
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
      // Browsers still subscribed when the record is written own it; a browser that left does not.
      if (['completed', 'no_layout'].includes(task.status)) for (const owner of task.owners) await this.claim(task.kind, task.key, owner);
    }
    // Finish reconciliation above while paused; queued work stays in FIFO order.
    if (this.maintenance || this.executionSlot?.paused || this.executionSlot?.busy || Object.values(this.adapters).some(a => a.busy())) return;
    const next = this.tasks.find(t => t.status === 'queued');
    if (!next) return;
    const adapter = this.adapters[next.kind];
    try {
      // Once resource-blocked, retry the inexpensive observation before preparing science again.
      if (this.resourceBlocked) { await this.beforeNewWork(); this.resourceBlocked = null; }
      if (this.disposed || this.stopping || this.failure || this.maintenance || this.executionSlot?.paused) return;
      const prepared = await adapter.prepare(next.request);
      if (this.disposed || this.stopping || this.failure || this.maintenance || this.executionSlot?.paused ||
          this.executionSlot?.busy || Object.values(this.adapters).some(a => a.busy())) return;
      if (prepared.key !== next.key) throw new Error('排队后模型或代码已更新，请重新提交');
      await this.beforeNewWork();
      if (this.disposed || this.stopping || this.failure || this.maintenance || this.executionSlot?.paused || this.executionSlot?.busy || Object.values(this.adapters).some(a => a.busy())) return;
      this.resourceBlocked = null;
      // Persist starting intent before launching a subprocess.
      next.status = 'running'; next.starting = true; this.activeId = next.id; this.persist();
      let started;
      this.launching = next.id;
      try { started = await adapter.start(next.request); } finally { this.launching = null; }
      if (this.disposed) return;
      if (started.busy) {
        // Another submission can acquire the slot, or maintenance can pause it,
        // during service-side preparation. Both explicitly confirm no launch.
        // Preserve the receipt/order and clear the now-resolved spawn intent.
        next.status = 'queued'; delete next.starting; delete next.workerPid; delete next.backendId;
        this.activeId = null; this.persist(); return;
      }
      if (!started.job) throw new Error('计算资源被其他进程占用，请重新提交');
      next.backendId = started.job.id;
      next.workerPid = adapter.pid(); next.starting = false; this.persist();
      if (started.job.key !== next.key) { adapter.cancel(next.backendId); throw new Error('排队后模型或代码已更新，请重新提交'); }
    } catch (e) {
      if (this.disposed || this.stopping) return;
      if (e.resourceSafe) { this.resourceBlocked = { code: 'resource_unavailable' }; return; }
      next.status = 'failed'; next.message = publicMessage(e); next.finished_at = new Date(this.now()).toISOString();
      this.activeId = null; this.persist();
    }
  }
  async stats(visitor) {
    const jobs = this.tasks.filter(t => t.owners.includes(visitor.id)).slice(-12).reverse();
    return { online_visitors: [...this.visitors.values()].filter(t => this.now() - t <= 90000).length,
      queued_tasks: this.tasks.filter(t => t.status === 'queued').length,
      running_tasks: Number(Boolean(this.activeId || this.blockedPids.length)),
      available: !this.failure && !this.disposed && !this.stopping, resource_blocked: Boolean(this.resourceBlocked), recovery_blocked: this.blockedPids.length > 0 || Boolean(this.unconfirmedWorker),
      ...this.maintenanceStatus(),
      jobs: await Promise.all(jobs.map(t => this.view(t, false, visitor, t.annotation_refs?.[visitor.id]?.at(-1)))) };
  }
  records(visitor) {
    // The durable receipts are small and bounded by RECEIPT_LIMITS.
    // Do not load waveform caches or expose another browser's request history.
    const newest = new Map();
    for (const task of this.tasks) {
      if (task.kind !== 'source-reception' || task.status !== 'completed' || !task.owners.includes(visitor.id)) continue;
      const previous = newest.get(task.key);
      if (!previous || task.sequence > previous.sequence) newest.set(task.key, task);
    }
    return { schema: 'browser-experiment-records/1', scope: 'current_browser', receipt_limit: this.receiptLimits.computed,
      records: [...newest.values()].sort((a, b) => b.sequence - a.sequence).map(taskView) };
  }
  async active(kind, visitor) {
    const task = this.tasks.find(t => t.kind === kind && pending(t) && t.owners.includes(visitor.id));
    return task ? this.view(task, false, visitor, task.annotation_refs?.[visitor.id]?.at(-1)) : null;
  }
  releaseLock() {
    if (existsSync(this.lockPath) && JSON.parse(readFileSync(this.lockPath, 'utf8')).token === this.lockToken) unlinkSync(this.lockPath);
  }
  stopScheduling() { this.stopping = true; clearInterval(this.timer); }
  dispose() {
    if (this.disposed) return;
    this.stopScheduling(); this.disposed = true;
    // A shutdown that lands while a launch is still in flight: the service host disposes the
    // compute services first, which refuse to spawn afterwards and stop their active worker,
    // so this task never ran to completion. Keep its place in the queue rather than leave a
    // marker that blocks all dispatch after the restart. A launch that failed with an unknown
    // outcome is not in flight and keeps its guard for the operator.
    const launching = this.tasks.find(task => task.id === this.launching && task.starting && !task.workerPid);
    if (launching) { launching.status = 'queued'; delete launching.starting; delete launching.backendId; }
    // Leave queued receipts intact. A running job is reported as interrupted on restart.
    this.persist(); this.releaseLock();
  }
}
/** Computed receipts are bounded by compute throughput. Cache-hit receipts cost nothing to
 * create, so they have their own smaller pool with a per-network share: a script cannot push
 * other visitors' results out, and a visitor who loses a cache-hit receipt gets it back by
 * opening the result again. */
export const RECEIPT_LIMITS = Object.freeze({ computed: 1000, cached: 300, cachedPerNetwork: 40 });
export function retainReceipts(tasks, limits = RECEIPT_LIMITS) {
  const terminal = tasks.filter(t => !pending(t) && !t.workerPid && !t.starting);
  const keep = new Set(terminal.filter(t => !t.cached).slice(-limits.computed));
  const perNetwork = new Map(); let cached = 0;
  for (const t of terminal.filter(t => t.cached).reverse()) {
    if (cached >= limits.cached) break;
    const network = t.networks?.[0] ?? '', count = perNetwork.get(network) ?? 0;
    if (count >= limits.cachedPerNetwork) continue;
    perNetwork.set(network, count + 1); keep.add(t); cached++;
  }
  return tasks.filter(t => pending(t) || t.workerPid || t.starting || keep.has(t));
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
  // Saved signal results are about 8 MB each; serializing them is main-thread work.
  const heavy = new Gate({ limit: 2, waiting: 8 });
  return async (req, res, next) => {
    const path = req.url?.split('?')[0] || '/';
    const endpoint = path.match(/^\/api\/(local-compute|source-reception|design-evaluation|electrode-editor)\/(jobs|lookup|health)(?:\/([a-f0-9-]{36})(\/cancel)?)?$/);
    const community = path.startsWith('/api/community/');
    if (!endpoint && !community) {
      // Set the cookie on document navigation before concurrent client API requests begin.
      if (guard(req) && req.method === 'GET' && (req.headers['sec-fetch-dest'] === 'document' || String(req.headers.accept).includes('text/html'))) scheduler.session(req, res, { renew: true });
      return legacy(req, res, next);
    }
    if (!guard(req)) return send(res, 403, { error: 'Request rejected by access policy.' });
    try {
      const visitor = scheduler.session(req, res);
      if (community) {
        if (path === '/api/community/status' && req.method === 'GET') return send(res, 200, await scheduler.stats(visitor));
        if (path === '/api/community/records' && req.method === 'GET') return send(res, 200, scheduler.records(visitor));
        const savedMatch = path.match(/^\/api\/community\/records\/([a-f0-9-]{36})\/result$/);
        if (savedMatch && req.method === 'GET') {
          const task = scheduler.own(savedMatch[1], visitor, 'source-reception');
          if (task.status !== 'completed') return send(res, 404, { error: '计算记录无法读取，请重新提交' });
          scheduler.rate(visitor);
          return await heavy.run(async () => send(res, 200, { result: await scheduler.adapters['source-reception'].savedResult(task.key, task.request) }));
        }
        if (path === '/api/community/heartbeat' && req.method === 'POST') {
          if (!tokenMatches(req.headers['x-eeg-compute-token'], queue.token)) return send(res, 403, { error: '刷新页面后重试' });
          scheduler.touch(visitor, req.headers['x-eeg-visible'] === '1');
          return send(res, 200, await scheduler.stats(visitor));
        }
        return send(res, 404, { error: 'Unknown community endpoint' });
      }
      const [, kind, action, id, cancel] = endpoint;
      if (action === 'health' && req.method === 'GET') return send(res, 200, { ...queue.health(), ...scheduler.maintenanceStatus(), active_job: await scheduler.active(kind, visitor) });
      if (req.method === 'POST' && !tokenMatches(req.headers['x-eeg-compute-token'], queue.token)) return send(res, 403, { error: '会话已更新，请刷新页面后重新计算' });
      if (id && action === 'jobs') {
        if (req.method === 'GET' && !cancel) {
          const query = new URL(req.url, 'http://localhost').searchParams;
          if ([...query.keys()].some(key => key !== 'annotation_id') || query.getAll('annotation_id').length > 1) throw error('Unsupported task query.');
          const annotationId = query.get('annotation_id') ?? undefined;
          if (annotationId !== undefined && !/^[a-f0-9]{64}$/.test(annotationId)) throw error('Invalid electrode name annotation.');
          const task = scheduler.own(id, visitor, kind);
          const respond = async () => send(res, 200, { job: await scheduler.view(task, true, visitor, annotationId) });
          return kind === 'source-reception' && ['completed', 'no_layout'].includes(task.status) ? await heavy.run(respond) : await respond();
        }
        if (req.method === 'POST' && cancel) return send(res, 202, { job: await scheduler.cancel(id, visitor, kind) });
      }
      if (req.method === 'POST' && !id && ['jobs', 'lookup'].includes(action)) {
        if (!String(req.headers['content-type']).startsWith('application/json')) return send(res, 415, { error: 'JSON required' });
        const limit = kind === 'design-evaluation' ? 65536 : kind === 'electrode-editor' ? 32768 : 4096;
        const chunks = []; let bytes = 0;
        for await (const chunk of req) { const data = Buffer.from(chunk); bytes += data.length; if (bytes > limit) return send(res, 413, { error: '配置过大' }); chunks.push(data); }
        const value = await scheduler.submit(kind, JSON.parse(Buffer.concat(chunks, bytes).toString('utf8')), visitor, action === 'lookup');
        return send(res, action === 'lookup' ? 200 : 202, value);
      }
      return send(res, 404, { error: 'Unknown queue endpoint' });
    } catch (e) {
      if ((e.resourceSafe || e.status === 503) && Number.isInteger(e.retryAfter) && e.retryAfter > 0 && e.retryAfter <= 3600 && !res.headersSent && !res.closed && !res.destroyed) res.setHeader('Retry-After', String(e.retryAfter));
      const failure = publicFailure(e);
      return send(res, failure.status, { error: failure.message, ...(e.resourceSafe ? { code: 'resource_unavailable' } : {}) });
    }
  };
}
