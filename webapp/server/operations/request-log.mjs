import { constants } from 'node:fs';
import { lstat, mkdir, open, readdir, realpath, unlink } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { operationsConfig } from './config.mjs';

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
const METHODS = new Set(['GET', 'HEAD', 'POST', 'PATCH', 'PUT', 'DELETE', 'OPTIONS', 'OTHER']);
const TASK_STATUS = new Set(['queued', 'running', 'cancelling', 'completed', 'no_layout', 'failed', 'cancelled', 'timeout']);
export function safeRequestLog(record) {
  if (!record || !UUID.test(record.request_id) || typeof record.route !== 'string' || !/^[a-z0-9_.:-]{1,80}$/.test(record.route) || typeof record.at !== 'string' || !Number.isFinite(Date.parse(record.at))) throw new Error('Invalid operations log record.');
  const value = { event: 'http_request', at: record.at, request_id: record.request_id, method: METHODS.has(record.method) ? record.method : 'OTHER', route: record.route,
    status: Number.isInteger(record.status) && record.status >= 100 && record.status <= 599 ? record.status : 0,
    duration_ms: Number.isFinite(record.duration_ms) && record.duration_ms >= 0 ? Math.round(record.duration_ms * 1000) / 1000 : 0,
    aborted: Boolean(record.aborted) };
  if (UUID.test(record.task_id)) value.task_id = record.task_id;
  if (TASK_STATUS.has(record.task_status)) value.task_status = record.task_status;
  return value;
}

/** A bounded, private best-effort log; failures never reject an application response. */
export class OperationsRequestLog {
  constructor(directory, { config = operationsConfig(), now = Date.now } = {}) {
    this.directory = resolve(directory); this.config = config; this.now = now;
    this.tail = Promise.resolve(); this.pending = 0; this.written = 0; this.dropped = 0; this.failed = 0; this.closed = false; this.unavailable = false;
  }
  async initialize() {
    await mkdir(dirname(this.directory), { recursive: true, mode: 0o700 });
    this.directory = join(await realpath(dirname(this.directory)), basename(this.directory));
    await mkdir(this.directory, { mode: 0o700 }).catch(error => { if (error.code !== 'EEXIST') throw error; });
    await this.safeDirectory();
  }
  async safeDirectory() {
    const value = await lstat(this.directory);
    if (!value.isDirectory() || value.isSymbolicLink() || (value.mode & 0o077) || await realpath(this.directory) !== this.directory) throw new Error('Operations log directory unavailable.');
  }
  async append(value) {
    await (this.initialization ??= this.initialize()); await this.safeDirectory();
    const now = this.now(), day = new Date(now).toISOString().slice(0, 10);
    for (const name of await readdir(this.directory)) {
      if (/^\d{4}-\d{2}-\d{2}\.ndjson$/.test(name) && (!Number.isFinite(Date.parse(name.slice(0, 10))) || name.slice(0, 10) > day || now - Date.parse(name.slice(0, 10)) >= this.config.logRetentionDays * 86400000)) {
        const path = join(this.directory, name), metadata = await lstat(path);
        if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.nlink !== 1) throw new Error('Operations log path unavailable.');
        await unlink(path);
      }
    }
    const path = join(this.directory, `${day}.ndjson`), line = JSON.stringify(value) + '\n';
    try {
      const metadata = await lstat(path);
      if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.nlink !== 1 || (metadata.mode & 0o077)) throw new Error('Operations log path unavailable.');
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    const file = await open(path, constants.O_WRONLY | constants.O_CREAT | constants.O_APPEND | constants.O_NOFOLLOW, 0o600);
    try {
      const metadata = await file.stat();
      if (!metadata.isFile() || metadata.nlink !== 1) throw new Error('Operations log path unavailable.');
      if (metadata.size + Buffer.byteLength(line) > this.config.logMaxBytes) { this.dropped++; return; }
      await file.writeFile(line); this.written++; this.unavailable = false;
    } finally { await file.close(); }
  }
  record(raw) {
    if (this.closed || this.pending >= this.config.logQueueLimit) { this.dropped++; return; }
    let value; try { value = safeRequestLog(raw); } catch { this.dropped++; return; }
    this.pending++;
    this.tail = this.tail.then(() => this.append(value)).catch(() => { this.failed++; this.unavailable = true; this.initialization = undefined; }).finally(() => { this.pending--; });
  }
  status() { return { pending: this.pending, written: this.written, dropped: this.dropped, failed: this.failed, unavailable: this.unavailable, max_daily_bytes: this.config.logMaxBytes, retention_days: this.config.logRetentionDays }; }
  close() { this.closed = true; }
  flush() { return this.tail; }
}
