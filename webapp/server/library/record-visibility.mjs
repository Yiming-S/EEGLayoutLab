/**
 * Who may see a visitor-produced record in the shared lists.
 *
 * The browsers that submitted (or looked up) a record own it. In the default
 * `shared` scope every record is listed to everyone. In the optional `owner`
 * scope a record is listed only to its owners until an owner publishes it; with
 * review on, a published record is listed to others only after the operator
 * approves it. The operator may remove any record from the lists. Reading a
 * record by its 64-hex identifier stays possible for anyone holding the link,
 * except a removed record, which only its owners can open.
 *
 * Files under `<queue directory>/library/`:
 * - `records/<id>.json`: owners and publishers, written only by the server.
 * - `moderation.json`: approvals and removals, written only by the operator tool.
 */
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { atomicJson } from '../storage/records.mjs';

export const VISITOR_KINDS = Object.freeze(['local-compute', 'design-evaluation', 'electrode-editor']);
export const LIBRARY_SCOPES = Object.freeze(['shared', 'owner']);
const ID = /^[a-f0-9]{64}$/;
const VISITOR = /^[a-f0-9]{64}$/;
const MAX_OWNERS = 1000;
const MAX_LABEL = 200;
const error = (message, status) => Object.assign(new Error(message), { status, visibilitySafe: true });

/** `EEG_LIBRARY_SCOPE` (default `shared`: every record listed) and `EEG_LIBRARY_REVIEW` (default on in `owner` scope). */
export function libraryConfig(env = process.env) {
  const scope = env.EEG_LIBRARY_SCOPE ?? 'shared';
  if (!LIBRARY_SCOPES.includes(scope)) throw new Error('EEG_LIBRARY_SCOPE must be shared or owner.');
  if (env.EEG_LIBRARY_REVIEW !== undefined && !['0', '1'].includes(env.EEG_LIBRARY_REVIEW)) throw new Error('EEG_LIBRARY_REVIEW must be 0 or 1.');
  const review = env.EEG_LIBRARY_REVIEW === undefined ? scope === 'owner' : env.EEG_LIBRARY_REVIEW === '1';
  return Object.freeze({ scope, review });
}

export function moderationPath(queueDirectory) { return join(queueDirectory, 'library', 'moderation.json'); }
export function recordsDirectory(queueDirectory) { return join(queueDirectory, 'library', 'records'); }

/** Parse and check the operator's moderation file; an invalid file is an error, never "no moderation". */
export function readModeration(path) {
  if (!existsSync(path)) return { version: 1, records: {} };
  const value = JSON.parse(readFileSync(path, 'utf8'));
  if (value?.version !== 1 || typeof value.records !== 'object' || value.records === null || Array.isArray(value.records)) throw new Error('Unsupported library moderation file.');
  for (const [id, entry] of Object.entries(value.records)) {
    if (!ID.test(id) || !['approved', 'removed'].includes(entry?.state) || typeof entry.at !== 'string' ||
        (entry.reason !== undefined && (typeof entry.reason !== 'string' || entry.reason.length > 500))) throw new Error(`Invalid moderation entry ${id}.`);
  }
  return value;
}

export function validEntry(value, id) {
  return value?.version === 1 && value.id === id && VISITOR_KINDS.includes(value.kind) &&
    Array.isArray(value.owners) && value.owners.every(owner => VISITOR.test(owner)) &&
    Array.isArray(value.published) && value.published.every(entry => VISITOR.test(entry?.owner) && typeof entry.at === 'string') &&
    (value.label === undefined || (typeof value.label === 'string' && value.label.length <= MAX_LABEL));
}

export class RecordVisibility {
  constructor({ directory, scope = 'shared', review = false, now = Date.now } = {}) {
    if (!LIBRARY_SCOPES.includes(scope) || typeof review !== 'boolean') throw new TypeError('Invalid library visibility settings.');
    this.scope = scope; this.review = review; this.now = now;
    this.directory = recordsDirectory(directory); this.moderationFile = moderationPath(directory);
    mkdirSync(this.directory, { recursive: true, mode: 0o700 });
    this.entries = new Map();
    for (const name of readdirSync(this.directory)) {
      const id = name.slice(0, -5);
      if (!name.endsWith('.json') || !ID.test(id)) continue;
      const value = JSON.parse(readFileSync(join(this.directory, name), 'utf8'));
      if (!validEntry(value, id)) throw new Error(`Invalid library visibility record ${id}; preserve it for recovery.`);
      this.entries.set(id, value);
    }
    this.writes = Promise.resolve(); this.moderationStamp = null; this.moderated = { version: 1, records: {} };
    this.refreshModeration();
  }
  refreshModeration() {
    let stamp = 'missing';
    try { const info = statSync(this.moderationFile); stamp = `${info.mtimeMs}:${info.size}:${info.ino}`; }
    catch (e) { if (e.code !== 'ENOENT') throw e; }
    if (stamp === this.moderationStamp) return;
    // Keep the last valid moderation if the operator saved a broken file; removals must not lapse.
    try { this.moderated = readModeration(this.moderationFile); this.moderationStamp = stamp; this.moderationError = null; }
    catch (e) { this.moderationError = e.message; }
  }
  save(id) {
    const value = this.entries.get(id);
    const write = this.writes.then(() => atomicJson(join(this.directory, `${id}.json`), value));
    this.writes = write.catch(() => {});
    return write;
  }
  flush() { return this.writes; }
  /** Record that a browser holds this record. Idempotent; the oldest owners drop beyond 1000. */
  async claim(kind, id, owner) {
    if (!VISITOR_KINDS.includes(kind) || !ID.test(id) || !VISITOR.test(owner)) return;
    const entry = this.entries.get(id) ?? { version: 1, id, kind, owners: [], published: [] };
    if (entry.owners.includes(owner)) return;
    entry.owners = [...entry.owners, owner].slice(-MAX_OWNERS);
    entry.published = entry.published.filter(item => entry.owners.includes(item.owner));
    this.entries.set(id, entry);
    await this.save(id);
  }
  owns(id, owner) { return Boolean(owner && this.entries.get(id)?.owners.includes(owner)); }
  state(id, refresh = true) {
    if (refresh) this.refreshModeration();
    const moderation = this.moderated.records[id];
    if (moderation?.state === 'removed') return 'removed';
    if (!this.entries.get(id)?.published.length) return 'private';
    return this.review && moderation?.state !== 'approved' ? 'pending' : 'public';
  }
  /** Per-visitor view of one visitor-produced record. */
  view(id, owner, refresh = true) {
    const state = this.state(id, refresh), owned = this.owns(id, owner);
    return { scope: this.scope, review: this.review, owned, state,
      published_by_me: owned && this.entries.get(id).published.some(item => item.owner === owner),
      ...(owned && state === 'removed' && this.moderated.records[id]?.reason ? { reason: this.moderated.records[id].reason } : {}) };
  }
  listable(id, owner, refresh = true) {
    const state = this.state(id, refresh);
    if (this.owns(id, owner)) return true;
    if (state === 'removed') return false;
    return this.scope === 'shared' || state === 'public';
  }
  readable(id, owner) { return this.owns(id, owner) || this.state(id) !== 'removed'; }
  /** Filter visitor-produced rows for one browser and attach its view; other rows pass unchanged. */
  present(rows, owner, idOf = row => row.id, visitorRow = () => true) {
    this.refreshModeration();
    return rows.filter(row => !visitorRow(row) || this.listable(idOf(row), owner, false))
      .map(row => visitorRow(row) ? { ...row, visibility: this.view(idOf(row), owner, false) } : row);
  }
  async publish(id, owner, wanted, label) {
    if (!ID.test(id)) throw error('记录编号无效', 400);
    if (typeof wanted !== 'boolean') throw error('请选择是否公开这条记录', 400);
    const entry = this.entries.get(id);
    if (!entry?.owners.includes(owner)) throw error('只有提交过这条记录的浏览器才能更改公开状态', 403);
    if (wanted && this.state(id) === 'removed') throw error('管理员已将这条记录从共享库移除，不能再次公开', 409);
    const mine = entry.published.some(item => item.owner === owner);
    if (wanted !== mine) {
      entry.published = wanted ? [...entry.published, { owner, at: new Date(this.now()).toISOString() }]
        : entry.published.filter(item => item.owner !== owner);
      if (typeof label === 'string') entry.label = label.slice(0, MAX_LABEL);
      await this.save(id);
    }
    return this.view(id, owner);
  }
}
