import { createHash, randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import { constants } from 'node:fs';
import { lstat, mkdir, open, readdir, realpath } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { atomicJson } from '../storage/records.mjs';

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;
const SHA = /^[a-f0-9]{64}$/;
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
export const PROJECT_LIMITS = Object.freeze({ projects: 1000, entries: 100, snapshotBytes: 16 * 1024 * 1024, projectBytes: 128 * 1024 * 1024, metadataBytes: 512 * 1024 });
export const projectError = (message, status = 400) => Object.assign(new Error(message), { status, projectSafe: true });
export const validProjectId = value => typeof value === 'string' && UUID.test(value);
const clone = value => JSON.parse(JSON.stringify(value));
const object = value => value && typeof value === 'object' && !Array.isArray(value);
function fields(value, allowed) {
  if (!object(value) || Object.keys(value).some(key => !allowed.includes(key))) throw projectError('Invalid project fields.');
}
function hasControl(value) {
  for (let index = 0; index < value.length; index++) { const code = value.charCodeAt(index); if (code < 32 && ![9, 10, 13].includes(code)) return true; }
  return false;
}
function text(value, name, max, required = false) {
  if (typeof value !== 'string' || value.length > max || hasControl(value) || (required && !value.trim())) throw projectError(`Invalid ${name}.`);
  return value.trim();
}
function revision(value) { if (!Number.isSafeInteger(value) || value < 1) throw projectError('A current project revision is required.'); return value; }
function equalKey(key, expected) {
  const actual = typeof key === 'string' && SHA.test(key) ? digest(key) : '0'.repeat(64);
  return timingSafeEqual(Buffer.from(actual), Buffer.from(expected ?? 'f'.repeat(64)));
}
function workflow(value, entries) {
  fields(value, ['reference_entry_id', 'candidate_entry_id', 'comparison_href']);
  if (value.comparison_href !== undefined && value.comparison_href !== null && typeof value.comparison_href !== 'string') throw projectError('Invalid project comparison link.');
  const result = { reference_entry_id: value.reference_entry_id ?? null, candidate_entry_id: value.candidate_entry_id ?? null, comparison_href: value.comparison_href || null };
  const selected = {};
  for (const name of ['reference_entry_id', 'candidate_entry_id']) {
    const id = result[name];
    if (id === null) continue;
    const entry = entries.find(row => row.id === id && row.kind === 'layout');
    if (!validProjectId(id) || !entry) throw projectError('Choose a layout saved in this project.');
    selected[name] = entry;
  }
  if (result.reference_entry_id && result.reference_entry_id === result.candidate_entry_id) throw projectError('Choose two different saved layouts.');
  if (result.comparison_href !== null) {
    if (typeof result.comparison_href !== 'string' || result.comparison_href.length > 4096) throw projectError('Invalid project comparison link.');
    let url; try { url = new URL(result.comparison_href, 'http://localhost'); } catch { throw projectError('Invalid project comparison link.'); }
    if (!result.comparison_href.startsWith('/decision?') || url.origin !== 'http://localhost' || url.pathname !== '/decision' || url.hash) throw projectError('Invalid project comparison link.');
    const allowed = ['a', 'b', 'ar', 'thresholdMode', 'sensitivity', 'localization', 'p90'];
    if ([...url.searchParams.keys()].some(key => !allowed.includes(key) || url.searchParams.getAll(key).length !== 1)) throw projectError('Invalid project comparison parameters.');
    const reference = selected.reference_entry_id, candidate = selected.candidate_entry_id;
    if (!reference || !candidate || url.searchParams.get('a') !== reference.record_id || url.searchParams.get('b') !== candidate.record_id ||
      [reference, candidate].some(entry => !['strict_area', 'cache', 'design_evaluation'].includes(entry.summary.protocol))) throw projectError('Comparison must use the selected evaluated layouts.');
    for (const [name, maximum] of [['ar', 100], ['sensitivity', 100], ['localization', 100], ['p90', 500]]) {
      if (!url.searchParams.has(name)) continue;
      const text = url.searchParams.get(name), number = Number(text);
      if (!text || !Number.isFinite(number) || number < (name === 'ar' ? 1 : 0) || number > maximum || (name === 'ar' && !Number.isInteger(number))) throw projectError('Invalid project comparison requirement.');
    }
    if (url.searchParams.has('thresholdMode') && !['joint', 'custom'].includes(url.searchParams.get('thresholdMode'))) throw projectError('Invalid project comparison mode.');
    const mode = url.searchParams.get('thresholdMode');
    const joint = mode === 'joint' || (mode !== 'custom' && !['sensitivity', 'localization', 'p90'].some(name => url.searchParams.has(name)));
    if (joint) {
      const field = Number(url.searchParams.get('ar') ?? 90);
      if (field < 10 || field > 100 || url.searchParams.has('p90') ||
        ['sensitivity', 'localization'].some(name => url.searchParams.has(name) && Number(url.searchParams.get(name)) !== field)) throw projectError('Joint comparison requirements must use the same 10–100 percent limit for all three metrics.');
    }
    result.comparison_href = url.pathname + url.search;
  }
  return result;
}
function publicProject(record) {
  const { schema, id, title, owner_name, notes, revision, created_at, updated_at, entries } = record;
  return clone({ schema, id, title, owner_name, notes, revision, created_at, updated_at, entries, workflow: record.workflow ?? { reference_entry_id: null, candidate_entry_id: null, comparison_href: null } });
}
function validateRecord(record, id) {
  try {
    if (!object(record) || record.schema !== 'research-project/1' || record.id !== id || !SHA.test(record.owner_key_hash) || !(record.viewer_key_hash === null || SHA.test(record.viewer_key_hash)) || !Array.isArray(record.entries) || record.entries.length > PROJECT_LIMITS.entries) throw new Error();
    text(record.title, 'project title', 200, true); text(record.owner_name, 'researcher name', 120, true); text(record.notes, 'project notes', 8000); revision(record.revision);
    if (![record.created_at, record.updated_at].every(value => typeof value === 'string' && Number.isFinite(Date.parse(value)))) throw new Error();
    const ids = new Set(); let bytes = 0;
    for (const entry of record.entries) {
      if (!validProjectId(entry.id) || ids.has(entry.id) || !['layout', 'editor', 'source'].includes(entry.kind) || !SHA.test(entry.record_id) || !SHA.test(entry.snapshot_sha256) || !Number.isSafeInteger(entry.snapshot_bytes) || entry.snapshot_bytes < 2 || entry.snapshot_bytes > PROJECT_LIMITS.snapshotBytes || !object(entry.summary)) throw new Error();
      ids.add(entry.id); bytes += entry.snapshot_bytes;
      text(entry.title, 'entry title', 200, true); text(entry.notes, 'entry notes', 8000);
      if (typeof entry.created_at !== 'string' || !Number.isFinite(Date.parse(entry.created_at))) throw new Error();
    }
    if (bytes > PROJECT_LIMITS.projectBytes) throw new Error();
    if (record.workflow !== undefined) workflow(record.workflow, record.entries);
  } catch { throw projectError('Project metadata failed integrity checks.', 409); }
  return record;
}

/** Private metadata and immutable scientific copies, independent of queue receipts. */
export class ProjectStore {
  constructor(directory, { now = () => new Date().toISOString() } = {}) {
    this.directory = resolve(directory); this.now = now; this.tail = Promise.resolve(); this.pendingWrites = 0; this.closed = false;
  }
  async initialize() {
    await mkdir(dirname(this.directory), { recursive: true, mode: 0o700 });
    const parent = await realpath(dirname(this.directory));
    this.directory = join(parent, basename(this.directory));
    await mkdir(this.directory, { mode: 0o700 }).catch(error => { if (error.code !== 'EEXIST') throw error; });
    await this.safeDirectory(this.directory);
  }
  ready() { return this.initialization ??= this.initialize(); }
  async safeDirectory(path) {
    const metadata = await lstat(path);
    if (!metadata.isDirectory() || metadata.isSymbolicLink() || await realpath(path) !== path) throw projectError('Project directory is not a regular directory.', 409);
  }
  async projectDirectory(id) {
    if (!validProjectId(id)) throw projectError('Invalid project identifier.');
    await this.safeDirectory(this.directory);
    const path = join(this.directory, id); await this.safeDirectory(path); return path;
  }
  async file(path, maximum) {
    const metadata = await lstat(path);
    if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.nlink !== 1 || metadata.size > maximum) throw projectError('Project file failed integrity checks.', 409);
    const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const actual = await handle.stat();
      if (actual.ino !== metadata.ino || actual.dev !== metadata.dev || actual.size > maximum) throw projectError('Project file changed while reading.', 409);
      const bytes = await handle.readFile();
      if (bytes.length > maximum) throw projectError('Project file is too large.', 413);
      return bytes;
    } finally { await handle.close(); }
  }
  async load(id) {
    try {
      await this.ready();
      const directory = await this.projectDirectory(id);
      let value; try { value = JSON.parse(await this.file(join(directory, 'project.json'), PROJECT_LIMITS.metadataBytes)); }
      catch (error) { if (error.projectSafe || error.code === 'ENOENT') throw error; throw projectError('Project metadata failed integrity checks.', 409); }
      return validateRecord(value, id);
    } catch (error) { if (error.code === 'ENOENT') throw projectError('Project not found.', 404); throw error; }
  }
  authorize(record, key, write = false) {
    const owner = equalKey(key, record.owner_key_hash), viewer = equalKey(key, record.viewer_key_hash);
    if (!owner && (!viewer || write)) throw projectError(write && viewer ? 'This project credential is read-only.' : 'Project access denied.', 403);
    return owner ? 'owner' : 'viewer';
  }
  serialize(operation) {
    if (this.closed) return Promise.reject(projectError('Project store is stopping.', 503));
    this.pendingWrites++;
    const result = this.tail.then(operation);
    this.tail = result.catch(() => {}).finally(() => { this.pendingWrites--; });
    return result;
  }
  close() { this.closed = true; }
  flush() { return this.tail; }
  async save(record) {
    validateRecord(record, record.id);
    if (Buffer.byteLength(JSON.stringify(record)) > PROJECT_LIMITS.metadataBytes) throw projectError('Project metadata is too large.', 413);
    const directory = await this.projectDirectory(record.id), path = join(directory, 'project.json');
    await lstat(path).then(value => { if (!value.isFile() || value.isSymbolicLink() || value.nlink !== 1) throw projectError('Project metadata path is invalid.', 409); }).catch(error => { if (error.code !== 'ENOENT') throw error; });
    await atomicJson(path, record);
  }
  async create(input) {
    fields(input, ['title', 'owner_name', 'notes']);
    const values = { title: text(input.title, 'project title', 200, true), owner_name: text(input.owner_name, 'researcher name', 120, true), notes: text(input.notes ?? '', 'project notes', 8000) };
    return this.serialize(async () => {
      await this.ready();
      const entries = await readdir(this.directory, { withFileTypes: true });
      if (entries.filter(entry => validProjectId(entry.name)).length >= PROJECT_LIMITS.projects) throw projectError('Project storage limit reached.', 507);
      const id = randomUUID(), access_key = randomBytes(32).toString('hex'), at = this.now();
      await mkdir(join(this.directory, id), { mode: 0o700 }); await mkdir(join(this.directory, id, 'snapshots'), { mode: 0o700 });
      const record = { schema: 'research-project/1', id, ...values, revision: 1, created_at: at, updated_at: at, owner_key_hash: digest(access_key), viewer_key_hash: null, entries: [] };
      await this.save(record);
      return { project: publicProject(record), role: 'owner', access_key };
    });
  }
  async get(id, key) { const record = await this.load(id); const role = this.authorize(record, key); return { project: publicProject(record), role }; }
  async mutate(id, key, expectedRevision, operation) {
    revision(expectedRevision);
    return this.serialize(async () => {
      const record = await this.load(id); this.authorize(record, key, true);
      if (record.revision !== expectedRevision) throw projectError('Project changed. Reload it before saving.', 409);
      const extra = await operation(record) ?? {};
      record.revision++; record.updated_at = this.now(); await this.save(record);
      return { project: publicProject(record), role: 'owner', ...extra };
    });
  }
  patch(id, key, input) {
    fields(input, ['revision', 'title', 'owner_name', 'notes', 'workflow']);
    if (Object.keys(input).length < 2) throw projectError('No project changes supplied.');
    const values = {};
    for (const name of ['title', 'owner_name', 'notes']) if (input[name] !== undefined) values[name] = text(input[name], name, name === 'notes' ? 8000 : name === 'title' ? 200 : 120, name !== 'notes');
    return this.mutate(id, key, input.revision, record => {
      Object.assign(record, values);
      if (input.workflow !== undefined) record.workflow = workflow(input.workflow, record.entries);
    });
  }
  share(id, key, input) {
    fields(input, ['revision']);
    return this.mutate(id, key, input.revision, record => { const access_key = randomBytes(32).toString('hex'); record.viewer_key_hash = digest(access_key); return { access_key }; });
  }
  revokeShare(id, key, input) {
    fields(input, ['revision']);
    return this.mutate(id, key, input.revision, record => { record.viewer_key_hash = null; });
  }
  attach(id, key, input, snapshot, summary) {
    fields(input, ['revision', 'kind', 'record_id', 'receipt_id', 'title', 'notes']);
    if (!object(snapshot) || snapshot.schema !== 'research-project-snapshot/1' || !['layout', 'editor', 'source'].includes(snapshot.kind) || !SHA.test(snapshot.record_id) || snapshot.kind !== input.kind || !object(snapshot.payload) || !object(summary)) throw projectError('Invalid scientific snapshot.');
    const snapshot_json = JSON.stringify(snapshot), frozenSnapshot = JSON.parse(snapshot_json), frozenSummary = clone(summary), snapshot_bytes = Buffer.byteLength(snapshot_json), snapshot_sha256 = digest(snapshot_json);
    if (snapshot_bytes > PROJECT_LIMITS.snapshotBytes) throw projectError('Scientific snapshot exceeds the project size limit.', 413);
    const title = text(input.title ?? `${snapshot.kind} ${snapshot.record_id.slice(0, 8)}`, 'entry title', 200, true), notes = text(input.notes ?? '', 'entry notes', 8000);
    return this.mutate(id, key, input.revision, async record => {
      if (record.entries.length >= PROJECT_LIMITS.entries || record.entries.reduce((sum, entry) => sum + entry.snapshot_bytes, snapshot_bytes) > PROJECT_LIMITS.projectBytes) throw projectError('Project entry or storage limit reached.', 413);
      if (record.entries.some(entry => entry.kind === snapshot.kind && entry.record_id === snapshot.record_id)) throw projectError('This scientific result is already saved in the project.', 409);
      const directory = await this.projectDirectory(id), snapshots = join(directory, 'snapshots'); await this.safeDirectory(snapshots);
      const path = join(snapshots, `${snapshot_sha256}.json`);
      // Detached immutable copies still consume storage; count them in the budget.
      let storedBytes = 0, storedCount = 0, alreadyStored = false;
      for (const name of await readdir(snapshots)) {
        const finalSnapshot = /^[a-f0-9]{64}\.json$/.test(name);
        const atomicTemporary = /^[a-f0-9]{64}\.json\.[a-f0-9-]{36}\.tmp$/.test(name) && validProjectId(name.slice(70, -4));
        if (!finalSnapshot && !atomicTemporary) throw projectError('Unexpected scientific snapshot file.', 409);
        const file = await lstat(join(snapshots, name));
        if (!file.isFile() || file.isSymbolicLink() || file.nlink !== 1) throw projectError('Scientific snapshot path is invalid.', 409);
        // An interrupted atomic write can leave an unpublished temporary file.
        // Retain and count it, allowing retry within the storage budget.
        // Never load an unpublished file as a scientific result.
        storedBytes += file.size; storedCount++; if (name === `${snapshot_sha256}.json`) alreadyStored = true;
      }
      if (storedBytes + (alreadyStored ? 0 : snapshot_bytes) > PROJECT_LIMITS.projectBytes || storedCount + Number(!alreadyStored) > PROJECT_LIMITS.entries) throw projectError('Project snapshot storage limit reached.', 413);
      try { const bytes = await this.file(path, PROJECT_LIMITS.snapshotBytes); if (digest(bytes) !== snapshot_sha256) throw projectError('Scientific snapshot failed integrity checks.', 409); }
      catch (error) { if (error.code !== 'ENOENT') throw error; await atomicJson(path, frozenSnapshot); }
      const entry = { id: randomUUID(), kind: snapshot.kind, record_id: snapshot.record_id, title, notes, created_at: this.now(), snapshot_sha256, snapshot_bytes, summary: frozenSummary };
      record.entries.push(entry); return { entry: clone(entry) };
    });
  }
  patchEntry(id, key, entryId, input) {
    fields(input, ['revision', 'title', 'notes']); if (!validProjectId(entryId)) throw projectError('Invalid project entry identifier.');
    if (Object.keys(input).length < 2) throw projectError('No entry changes supplied.');
    const values = {};
    for (const name of ['title', 'notes']) if (input[name] !== undefined) values[name] = text(input[name], name, name === 'notes' ? 8000 : 200, name === 'title');
    return this.mutate(id, key, input.revision, record => { const entry = record.entries.find(value => value.id === entryId); if (!entry) throw projectError('Project entry not found.', 404); Object.assign(entry, values); return { entry: clone(entry) }; });
  }
  detach(id, key, entryId, expectedRevision) {
    if (!validProjectId(entryId)) throw projectError('Invalid project entry identifier.');
    return this.mutate(id, key, expectedRevision, record => {
      const before = record.entries.length; record.entries = record.entries.filter(value => value.id !== entryId);
      if (before === record.entries.length) throw projectError('Project entry not found.', 404);
      if (record.workflow && [record.workflow.reference_entry_id, record.workflow.candidate_entry_id].includes(entryId)) {
        for (const key of ['reference_entry_id', 'candidate_entry_id']) if (record.workflow[key] === entryId) record.workflow[key] = null;
        record.workflow.comparison_href = null;
      }
    });
  }
  async snapshot(record, entry) {
    const directory = await this.projectDirectory(record.id), snapshots = join(directory, 'snapshots'); await this.safeDirectory(snapshots);
    let bytes; try { bytes = await this.file(join(snapshots, `${entry.snapshot_sha256}.json`), PROJECT_LIMITS.snapshotBytes); } catch (error) { if (error.code === 'ENOENT') throw projectError('Scientific snapshot is missing.', 409); throw error; }
    if (bytes.length !== entry.snapshot_bytes || digest(bytes) !== entry.snapshot_sha256) throw projectError('Scientific snapshot failed integrity checks.', 409);
    let value; try { value = JSON.parse(bytes); } catch { throw projectError('Scientific snapshot failed integrity checks.', 409); }
    if (value.schema !== 'research-project-snapshot/1' || value.kind !== entry.kind || value.record_id !== entry.record_id || !object(value.payload)) throw projectError('Scientific snapshot identity mismatch.', 409);
    return { snapshot: value, snapshot_json: bytes.toString('utf8') };
  }
  async getEntry(id, key, entryId) {
    if (!validProjectId(entryId)) throw projectError('Invalid project entry identifier.');
    const record = await this.load(id); this.authorize(record, key);
    const entry = record.entries.find(value => value.id === entryId); if (!entry) throw projectError('Project entry not found.', 404);
    return { entry: clone(entry), snapshot: (await this.snapshot(record, entry)).snapshot };
  }
  async readSnapshots(id, key, { maxBytes = PROJECT_LIMITS.projectBytes } = {}) {
    const record = await this.load(id), role = this.authorize(record, key), entries = [];
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || record.entries.reduce((sum, entry) => sum + entry.snapshot_bytes, 0) > maxBytes) throw projectError('Project export exceeds the size limit.', 413);
    // Sequential reads keep peak memory bounded and preserve the saved order.
    for (const entry of record.entries) entries.push({ entry: clone(entry), ...await this.snapshot(record, entry) });
    return { project: publicProject(record), role, entries };
  }
}
