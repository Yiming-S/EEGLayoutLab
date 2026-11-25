// Node reference for tests/service/test_projects.py: the research-project code of webapp/server/projects/.
// Writes only <out.json> and under the directories the spec names (scratch project directories).
// Usage: node tests/service/parity/projects.mjs <spec.json> <out.json>
//
// spec: {mode, cases: [...]}; the output is {node: process.version, cases: [...]}, one entry per case with its `id`.
// Every value in a spec is JSON revived as in parity/studies.mjs ({"$js": "undefined" | "NaN" | ...}).
//
// Identifiers and keys are pinned: ProjectStore's randomUUID calls (a project's and an entry's identifier) give
// 0a0a0000-0000-4000-8000-<k, 12 digits> from k = 1 in each case, and its randomBytes calls (a new project's access
// key) give sha256('key-<n>') from n = 1 (a case's `prefix` replaces 0a0a0000). The clock is
// 2026-11-25T00:00:<step>.000Z at step n. A string in a step
// has `$P<n>` and `$E<n>` replaced by the n-th project and entry identifier the case has created; every call names
// the project's owner key (that of its create, else that of the case's `keys` ({project id: key}), else 'c' x 64,
// the key of a hand-written project).
//
// A failure is recorded as {ok: false, status, safe, message, code, name, sync}: `safe` when Node's middleware shows
// the message (projectSafe or resourceSafe), `code` a system error's code, `sync` when the call threw instead of
// returning a rejected promise. A result is {ok: true, value: JSON text}; a create's access_key is replaced by
// '<access_key>' and recorded as `access_key`.
//
// Mode 'store' (store.mjs): spec.cases are [{id, directory, steps}], a ProjectStore at <directory>. Steps:
//   ['create', input], ['get', id], ['load', id], ['patch', id, input], ['workflow', id, value] (a patch of the
//   comparison settings at the current revision), ['attach', id, input, snapshot, summary],
//   ['patch_entry', id, entry, input], ['detach', id, entry, revision], ['get_entry', id, entry],
//   ['read', id, maxBytes?] (readSnapshots), ['snapshot', id, index], ['resave', id, [file step, ...]] (the record
//   loaded, the file steps made, then the loaded record saved), ['concurrent', [step, ...]] (the calls made
//   one after another without waiting, then awaited together; recorded as a list), ['close'], ['flush'] (records
//   pendingWrites after it), ['restart'] (a new store on the directory), and file steps on paths relative to
//   <directory>: ['write', path, base64], ['symlink', target, path], ['link', existing, path], ['mkdir', path],
//   ['rm', path], ['chmod', path, mode], ['rename', from, to]. Each case also records `tree`:
//   [[relative path, 'dir' | 'file' | 'link', mode, base64 | target]] in byte order.
//
// Mode 'service' (service.mjs middleware, after the access policy and the token): spec.cases are [{id, directory,
// state, steps}]. The stand-ins read `state`: records (library.get), bundles (the bundle of a record id, or
// {"$error": message}), editor {rows, caches} (editor.records, store.read of editor/<key>/cache.json; a result with
// `invalid: true` fails editor.validate), tasks (scheduler.own by id and kind, else 404), saved (savedResult by key,
// or {"$error": message}), annotations (read by id for its record_id, else annotationSafe 404) and before (null or
// 'resource': beforeWrite throws a resourceSafe 503 with retryAfter 7). The delivery's export is
// {entries: [entry id, ...]} of readSnapshots. Steps: ['request', method, url, headers, body text | null] recorded as
// {status, body: JSON text, headers: {content-disposition?, retry-after?}}, ['state', {member: value}] (replaces
// members of state), and the file steps. The case records `tree` too.
//
// Mode 'read': spec.cases are [{id, directory, projects}]: for each project id, load(id), recorded as {ok: true,
// record: JSON text, snapshots} or the failure, where snapshots holds, for every entry, snapshot(record, entry)
// recorded as {ok: true, value: snapshot_json} or the failure.
import { createRequire, syncBuiltinESMExports } from 'node:module';
import { createHash } from 'node:crypto';
import {
  chmodSync, linkSync, lstatSync, mkdirSync, readFileSync, readdirSync, readlinkSync, renameSync, rmSync, symlinkSync,
  writeFileSync,
} from 'node:fs';
import { join } from 'node:path';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: projects.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));

const require = createRequire(import.meta.url);
const crypto = require('node:crypto');
const realUUID = crypto.randomUUID, realBytes = crypto.randomBytes;
const pins = { uuid: null, key: null };
const fromStore = () => (new Error().stack.split('\n')[3] ?? '').includes('/projects/store.mjs:');
crypto.randomUUID = function (...args) { return pins.uuid && fromStore() ? pins.uuid() : realUUID.apply(this, args); };
crypto.randomBytes = function (...args) { return pins.key && fromStore() ? Buffer.from(pins.key(), 'hex') : realBytes.apply(this, args); };
syncBuiltinESMExports();
const { ProjectStore } = await import('../../../webapp/server/projects/store.mjs');
const { ProjectService } = await import('../../../webapp/server/projects/service.mjs');

const sha = text => createHash('sha256').update(text).digest('hex');
const sequence = (prefix) => {
  let n = 0;
  return () => `${prefix}-0000-4000-8000-${String(++n).padStart(12, '0')}`;
};
const keySequence = () => { let n = 0; return () => sha(`key-${++n}`); };
const CRAFTED_KEY = 'c'.repeat(64);
const EPOCH = Date.UTC(2026, 10, 25);

const SPECIAL = { NaN: NaN, Infinity: Infinity, '-Infinity': -Infinity, undefined };
const define = (target, key, value) =>
  Object.defineProperty(target, key, { value, enumerable: true, writable: true, configurable: true });
function revive(value) {
  if (Array.isArray(value)) return value.map(revive);
  if (!value || typeof value !== 'object') return value;
  const keys = Object.keys(value);
  if (keys.length === 1 && keys[0] === '$js') return SPECIAL[value.$js];
  const out = {};
  for (const key of keys) define(out, key, revive(value[key]));
  return out;
}

const failure = (error, sync = false) => ({
  ok: false,
  status: error?.status ?? null,
  safe: Boolean(error?.projectSafe || error?.resourceSafe),
  message: error?.projectSafe || error?.resourceSafe ? error.message : null,
  code: typeof error?.code === 'string' ? error.code : null,
  name: error?.name ?? null,
  sync,
});
const success = (value) => {
  if (value && typeof value === 'object' && typeof value.access_key === 'string')
    return { ok: true, value: JSON.stringify({ ...value, access_key: '<access_key>' }), access_key: value.access_key };
  return { ok: true, value: value == null ? null : JSON.stringify(value) };
};
/** Calls `run` and returns a promise of its record, keeping a synchronous throw apart. */
function call(run) {
  let pending;
  try { pending = run(); } catch (error) { return Promise.resolve(failure(error, true)); }
  return Promise.resolve(pending).then(success, error => failure(error));
}

function tree(directory) {
  const rows = [];
  const walk = (relative) => {
    const names = readdirSync(join(directory, relative)).sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)));
    for (const name of names) {
      const path = relative ? `${relative}/${name}` : name, full = join(directory, path), info = lstatSync(full);
      if (info.isSymbolicLink()) rows.push([path, 'link', info.mode & 0o777, readlinkSync(full)]);
      else if (info.isDirectory()) {
        rows.push([path, 'dir', info.mode & 0o777, null]);
        walk(path);
      } else rows.push([path, 'file', info.mode & 0o777, readFileSync(full).toString('base64')]);
    }
  };
  let root = null;
  try { root = lstatSync(directory); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (root?.isDirectory()) walk('');
  return rows;
}
function fileStep(directory, kind, args) {
  const at = (path) => join(directory, path);
  if (kind === 'write') writeFileSync(at(args[0]), Buffer.from(args[1], 'base64'));
  else if (kind === 'symlink') symlinkSync(args[0], at(args[1]));
  else if (kind === 'link') linkSync(at(args[0]), at(args[1]));
  else if (kind === 'mkdir') mkdirSync(at(args[0]));
  else if (kind === 'rm') rmSync(at(args[0]), { recursive: true });
  else if (kind === 'chmod') chmodSync(at(args[0]), args[1]);
  else if (kind === 'rename') renameSync(at(args[0]), at(args[1]));
  else return false;
  return true;
}

/** The identifiers a case has created, and `$P<n>` / `$E<n>` replaced in every string of a value. */
function names() {
  const created = { P: [], E: [] };
  const fill = value => {
    if (typeof value === 'string') return value.replace(/\$([PE])(\d+)/g, (_, kind, n) => created[kind][n - 1] ?? `$${kind}${n}`);
    if (Array.isArray(value)) return value.map(fill);
    if (value && typeof value === 'object') {
      const out = {};
      for (const key of Object.keys(value)) define(out, key, fill(value[key]));
      return out;
    }
    return value;
  };
  const note = (value) => {
    if (value?.access_key && value.project?.id) created.P.push(value.project.id);
    if (value?.entry?.id && !created.E.includes(value.entry.id)) created.E.push(value.entry.id);
  };
  return { created, fill, note };
}

async function storeMode() {
  const out = [];
  for (const item of spec.cases) {
    let step = 0;
    pins.uuid = sequence(item.prefix ?? '0a0a0000'); pins.key = keySequence();
    const make = () => new ProjectStore(item.directory, { now: () => new Date(EPOCH + 1000 * step).toISOString() });
    let store = make();
    const keys = new Map(Object.entries(item.keys ?? {})), { fill, note } = names();
    const keyOf = id => keys.get(id) ?? CRAFTED_KEY;
    const operation = (kind, args) => {
      if (kind === 'create') return store.create(args[0]);
      if (kind === 'get') return store.get(args[0], keyOf(args[0]));
      if (kind === 'load') return store.load(args[0]);
      if (kind === 'patch') return store.patch(args[0], keyOf(args[0]), args[1]);
      if (kind === 'workflow') return store.load(args[0]).then(record => store.patch(args[0], keyOf(args[0]), { revision: record.revision, workflow: args[1] }));
      if (kind === 'attach') return store.attach(args[0], keyOf(args[0]), args[1], args[2], args[3]);
      if (kind === 'patch_entry') return store.patchEntry(args[0], keyOf(args[0]), args[1], args[2]);
      if (kind === 'detach') return store.detach(args[0], keyOf(args[0]), args[1], args[2]);
      if (kind === 'get_entry') return store.getEntry(args[0], keyOf(args[0]), args[1]);
      if (kind === 'read') return store.readSnapshots(args[0], keyOf(args[0]), args.length > 1 ? { maxBytes: args[1] } : {});
      if (kind === 'snapshot') return store.load(args[0]).then(record => store.snapshot(record, record.entries[args[1]]));
      if (kind === 'resave') {
        return store.load(args[0]).then(record => {
          for (const [inner, ...rest] of args[1]) fileStep(item.directory, inner, rest);
          return store.save(record);
        });
      }
      if (kind === 'close') return store.close();
      if (kind === 'flush') return store.flush().then(() => ({ pending: store.pendingWrites }));
      if (kind === 'restart') { store = make(); return null; }
      throw new Error(`unknown step ${kind}`);
    };
    const remember = (kind, entry) => {
      if (entry.ok && kind === 'create') { keys.set(JSON.parse(entry.value).project.id, entry.access_key); }
      if (entry.ok && entry.value) note({ ...JSON.parse(entry.value), access_key: entry.access_key });
      return entry;
    };
    const records = [];
    for (const raw of item.steps) {
      step++;
      const [kind, ...args] = fill(revive(raw));
      if (fileStep(item.directory, kind, args)) { records.push({ ok: true, value: null }); continue; }
      if (kind === 'concurrent') {
        const pending = args[0].map(([inner, ...rest]) => call(() => operation(inner, rest)).then(entry => remember(inner, entry)));
        records.push(await Promise.all(pending));
        continue;
      }
      records.push(remember(kind, await call(() => operation(kind, args))));
    }
    await store.flush();
    pins.uuid = pins.key = null;
    out.push({ id: item.id, records, tree: tree(item.directory) });
  }
  return out;
}

function standIns(state) {
  const clone = value => (value === undefined ? undefined : structuredClone(value));
  const fail = value => value && typeof value === 'object' && Object.hasOwn(value, '$error');
  const queue = {
    root: '/nonexistent-root', python: 'python3', token: 'unused',
    library: { get: async id => clone(state.records?.[id]) ?? null },
    editor: {
      records: async () => clone(state.editor?.rows ?? []),
      store: {
        path: (kind, key, file) => `${kind}/${key}/${file}`,
        read: async path => {
          const key = path.split('/')[1];
          if (!Object.hasOwn(state.editor?.caches ?? {}, key)) throw Object.assign(new Error(`ENOENT: no such file, open '${path}'`), { code: 'ENOENT' });
          return clone(state.editor.caches[key]);
        },
      },
      validate: (result) => { if (result?.invalid === true) throw new Error('Invalid electrode editor result.'); },
    },
  };
  const scheduler = {
    session: () => ({ id: 'visitor' }), rate: () => {},
    own: (id, _visitor, kind) => {
      const task = (state.tasks ?? []).find(value => value.id === id && value.kind === kind);
      if (!task) throw Object.assign(new Error('任务不存在或不属于当前浏览器'), { status: 404 });
      return clone(task);
    },
    adapters: { 'source-reception': { savedResult: async key => {
      const value = state.saved?.[key];
      if (fail(value)) throw new Error(value.$error);
      return clone(value);
    } } },
    annotations: { read: (id, _owner, recordId) => {
      const value = state.annotations?.[id];
      if (!value || value.record_id !== recordId) throw Object.assign(new Error('Electrode name annotation not found.'), { status: 404, annotationSafe: true });
      return clone(value);
    } },
  };
  const bundle = async (_root, record) => {
    const value = state.bundles?.[record.id];
    if (fail(value)) throw new Error(value.$error);
    return clone(value);
  };
  return { queue, scheduler, bundle };
}

async function serviceMode() {
  const out = [];
  for (const item of spec.cases) {
    let step = 0;
    pins.uuid = sequence(item.prefix ?? '0a0a0000'); pins.key = keySequence();
    const state = revive(item.state ?? {});
    const store = new ProjectStore(item.directory, { now: () => new Date(EPOCH + 1000 * step).toISOString() });
    const { queue, scheduler, bundle } = standIns(state);
    const delivery = { export: async (id, key) => ({ entries: (await store.readSnapshots(id, key)).entries.map(row => row.entry.id) }) };
    const beforeWrite = async () => {
      if (state.before === 'resource') throw Object.assign(new Error('Resource blocked'), { status: 503, resourceSafe: true, retryAfter: 7 });
    };
    let sent = null;
    const send = (res, status, data) => { sent = { status, body: JSON.stringify(data), headers: res.headers }; };
    const service = new ProjectService({ queue, scheduler, guard: () => true, send, tokenMatches: () => true, store, bundle, delivery, beforeWrite });
    const middleware = service.middleware(() => { sent = { status: 'next' }; });
    const keys = new Map(Object.entries(item.keys ?? {})), { fill, note } = names();
    const records = [];
    for (const raw of item.steps) {
      step++;
      const [kind, ...args] = fill(revive(raw));
      if (fileStep(item.directory, kind, args)) { records.push({ ok: true }); continue; }
      if (kind === 'state') { Object.assign(state, args[0]); records.push({ ok: true }); continue; }
      if (kind !== 'request') throw new Error(`unknown step ${kind}`);
      const [method, url, headers, body] = args;
      const project = url.match(/^\/api\/projects\/([a-f0-9-]{36})/)?.[1];
      const req = {
        method, url,
        headers: { ...Object.fromEntries(Object.entries(headers ?? {}).map(([name, value]) => [name.toLowerCase(), value])),
          ...(project ? { 'x-eeg-project-key': keys.get(project) ?? CRAFTED_KEY } : {}) },
        async *[Symbol.asyncIterator]() { if (body !== null && body !== undefined) yield Buffer.from(body, 'utf8'); },
      };
      const res = { headers: {}, headersSent: false, closed: false, destroyed: false, writableEnded: false,
        setHeader(name, value) { this.headers[name.toLowerCase()] = value; } };
      sent = null;
      await middleware(req, res);
      const value = JSON.parse(sent.body);
      if (sent.status === 201 && value.access_key && value.project) keys.set(value.project.id, value.access_key);
      note(value);
      records.push({ status: sent.status, body: value.access_key ? JSON.stringify({ ...value, access_key: '<access_key>' }) : sent.body,
        headers: sent.headers });
    }
    service.close(); await service.flush();
    pins.uuid = pins.key = null;
    out.push({ id: item.id, records, tree: tree(item.directory) });
  }
  return out;
}

async function readMode() {
  const out = [];
  for (const item of spec.cases) {
    const store = new ProjectStore(item.directory);
    const projects = [];
    for (const id of item.projects) {
      let record;
      try { record = await store.load(id); } catch (error) { projects.push(failure(error)); continue; }
      const snapshots = [];
      for (const entry of record.entries) {
        try { snapshots.push({ ok: true, value: (await store.snapshot(record, entry)).snapshot_json }); }
        catch (error) { snapshots.push(failure(error)); }
      }
      projects.push({ ok: true, record: JSON.stringify(record), snapshots });
    }
    out.push({ id: item.id, projects });
  }
  return out;
}

const MODES = { store: storeMode, service: serviceMode, read: readMode };
const mode = MODES[spec.mode];
if (!mode) throw new Error(`unknown mode ${spec.mode}`);
writeFileSync(outPath, JSON.stringify({ node: process.version, cases: await mode() }));
process.exit(0);
