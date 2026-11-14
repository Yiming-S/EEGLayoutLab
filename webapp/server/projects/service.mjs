import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { experimentBundle } from '../experiment-bundle.mjs';
import { ProjectStore, projectError, validProjectId } from './store.mjs';
import { ProjectDelivery } from '../delivery/project-delivery.mjs';

const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const SHA = /^[a-f0-9]{64}$/;
const plain = value => value && typeof value === 'object' && !Array.isArray(value);
function attachment(input) {
  if (!plain(input) || Object.keys(input).some(key => !['revision', 'kind', 'record_id', 'receipt_id', 'title', 'notes'].includes(key)) || !['layout', 'editor', 'source'].includes(input.kind)) throw projectError('Invalid project attachment.');
  if (input.kind === 'source') {
    if (!validProjectId(input.receipt_id) || input.record_id !== undefined) throw projectError('A completed signal task receipt is required.');
  } else if (typeof input.record_id !== 'string' || !SHA.test(input.record_id) || input.receipt_id !== undefined) throw projectError('A saved scientific record is required.');
}

export class ProjectService {
  constructor({ queue, scheduler, guard, send, tokenMatches, directory, store, bundle = experimentBundle, delivery, beforeWrite = async () => {} }) {
    if (typeof beforeWrite !== 'function') throw new TypeError('Project write admission must be a function.');
    this.beforeWrite = beforeWrite;
    this.queue = queue; this.scheduler = scheduler; this.guard = guard; this.send = send; this.tokenMatches = tokenMatches; this.bundle = bundle;
    this.store = store ?? new ProjectStore(directory ?? join(queue.runtime.queueDirectory, 'projects'));
    this.delivery = delivery ?? new ProjectDelivery({ store: this.store, scientificRoot: queue.root });
  }
  close() { this.store.close(); }
  async admitWrite() {
    if (this.store.closed) throw projectError('Project store is stopping.', 503);
    await this.beforeWrite();
    if (this.store.closed) throw projectError('Project store is stopping.', 503);
  }
  flush() { return this.store.flush(); }
  async resolveSnapshot(input, visitor) {
    attachment(input);
    let record_id, payload, summary;
    if (input.kind === 'layout') {
      const record = await this.queue.library.get(input.record_id);
      if (record?.status !== 'completed' || !record.layout) throw projectError('Choose a completed layout evaluation.', 404);
      payload = await this.bundle(this.queue.root, record, { python: this.queue.python }); record_id = record.id;
      summary = { protocol: record.dataset_id, electrode_count: record.layout.xyzMm.length, region_count: record.region_count };
    } else if (input.kind === 'editor') {
      const records = await this.queue.editor.records(), record = records.find(value => value.key === input.record_id);
      if (!record) throw projectError('Completed electrode edit not found.', 404);
      const cache = await this.queue.editor.store.read(this.queue.editor.store.path('editor', input.record_id, 'cache.json'));
      if (cache.key !== input.record_id || hash(cache.result) !== cache.result_sha256 || hash({ request: cache.result?.request, identity: cache.identity }) !== input.record_id || cache.result?.request?.action !== 'evaluate') throw projectError('Electrode edit failed integrity checks.', 409);
      this.queue.editor.validate(cache.result, cache.result.request);
      record_id = cache.key; payload = { record, cache };
      summary = { protocol: cache.result.schema, electrode_count: cache.result.electrode_count, region_count: cache.result.active_regions, parent_id: cache.result.request.parent_id };
    } else {
      const task = this.scheduler.own(input.receipt_id, visitor, 'source-reception');
      if (task.status !== 'completed') throw projectError('Only completed signal results can be saved.', 409);
      payload = await this.scheduler.adapters['source-reception'].savedResult(task.key, task.request);
      if (!plain(payload) || payload.request?.record_id !== task.request.record_id || !['source-reception/1', 'source-reception/2'].includes(payload.schema_version)) throw projectError('Saved signal result failed integrity checks.', 409);
      record_id = task.key;
      summary = { protocol: payload.schema_version, electrode_count: payload.layout.xyzMm.length, parent_id: payload.request.record_id, mode: payload.request.mode ?? 'legacy' };
    }
    if (typeof record_id !== 'string' || !SHA.test(record_id)) throw projectError('Scientific record identity is invalid.', 409);
    return { snapshot: { schema: 'research-project-snapshot/1', kind: input.kind, record_id, payload }, summary };
  }
  async body(req) {
    if (!String(req.headers['content-type']).startsWith('application/json')) throw projectError('JSON is required.', 415);
    let bytes = 0; const chunks = [];
    for await (const chunk of req) { bytes += Buffer.byteLength(chunk); if (bytes > 65536) throw projectError('Project request is too large.', 413); chunks.push(chunk); }
    try { const value = JSON.parse(Buffer.concat(chunks.map(chunk => Buffer.from(chunk))).toString()); if (!plain(value)) throw new Error(); return value; }
    catch { throw projectError('Invalid project JSON.'); }
  }
  middleware(next) {
    return async (req, res, fallback) => {
      const path = req.url?.split('?')[0] ?? '/';
      if (path !== '/api/projects' && !path.startsWith('/api/projects/')) return next(req, res, fallback);
      const send = (status, data) => this.send(res, status, data);
      if (!this.guard(req)) return send(403, { error: 'Request rejected by access policy.' });
      try {
        const write = ['POST', 'PATCH', 'DELETE'].includes(req.method);
        if (!['GET', 'POST', 'PATCH', 'DELETE'].includes(req.method)) return send(405, { error: 'Unsupported project method.' });
        if (write && !this.tokenMatches(req.headers['x-eeg-compute-token'], this.queue.token)) return send(403, { error: 'Refresh the page before saving the project.' });
        if (req.url.includes('?')) throw projectError('Project API credentials and parameters must not use a query string.');
        if (path === '/api/projects') {
          if (req.method !== 'POST') return send(405, { error: 'Projects are opened with their identifier and credential.' });
          const visitor = this.scheduler.session(req, res); this.scheduler.rate(visitor);
          await this.admitWrite();
          return send(201, await this.store.create(await this.body(req)));
        }
        const match = path.match(/^\/api\/projects\/([a-f0-9-]{36})(?:\/(share|revoke-share|entries|export)(?:\/([a-f0-9-]{36}))?)?$/);
        if (!match || !validProjectId(match[1])) throw projectError('Project endpoint not found.', 404);
        const [, id, action, entryId] = match, key = req.headers['x-eeg-project-key'];
        // Authenticate before reading a request body or loading scientific payloads.
        const access = await this.store.get(id, key);
        if (write && access.role !== 'owner') throw projectError('This project credential is read-only.', 403);
        if (write) { const visitor = this.scheduler.session(req, res); this.scheduler.rate(visitor); await this.admitWrite(); }
        if (action === 'export' && !entryId && req.method === 'GET') {
          this.scheduler.rate(this.scheduler.session(req, res));
          const bundle = await this.delivery.export(id, key);
          if (!res.closed && !res.destroyed && !res.writableEnded && !res.headersSent)
            res.setHeader('Content-Disposition', `attachment; filename="eeg-research-${id}.json"`);
          return send(200, bundle);
        }
        if (!action) {
          if (req.method === 'GET') return send(200, access);
          if (req.method === 'PATCH') return send(200, await this.store.patch(id, key, await this.body(req)));
        } else if (action === 'share' && !entryId && req.method === 'POST') return send(200, await this.store.share(id, key, await this.body(req)));
        else if (action === 'revoke-share' && !entryId && req.method === 'POST') return send(200, await this.store.revokeShare(id, key, await this.body(req)));
        else if (action === 'entries') {
          if (entryId && req.method === 'GET') return send(200, await this.store.getEntry(id, key, entryId));
          if (entryId && req.method === 'PATCH') return send(200, await this.store.patchEntry(id, key, entryId, await this.body(req)));
          if (entryId && req.method === 'DELETE') {
            const value = req.headers['if-match']?.replace(/^"|"$/g, '');
            const expected = value === undefined ? (await this.body(req)).revision : Number(value);
            return send(200, await this.store.detach(id, key, entryId, expected));
          }
          if (!entryId && req.method === 'POST') {
            const input = await this.body(req); attachment(input);
            if (input.revision !== access.project.revision) throw projectError('Project changed. Reload it before saving.', 409);
            const visitor = this.scheduler.session(req, res), resolved = await this.resolveSnapshot(input, visitor);
            return send(201, await this.store.attach(id, key, input, resolved.snapshot, resolved.summary));
          }
        }
        return send(405, { error: 'Unsupported project operation.' });
      } catch (error) {
        const status = error.status && Number.isInteger(error.status) ? error.status : 500;
        // Internal filesystem paths and native error payloads never enter API responses.
        if (error.resourceSafe && Number.isInteger(error.retryAfter) && error.retryAfter > 0 && error.retryAfter <= 3600 && !res.headersSent && !res.closed && !res.destroyed) res.setHeader('Retry-After', String(error.retryAfter));
        return send(status, { error: error.projectSafe || error.resourceSafe || status < 500 ? error.message : 'Project storage or scientific record is unavailable.', ...(error.resourceSafe ? { code: 'resource_unavailable' } : {}) });
      }
    };
  }
}
