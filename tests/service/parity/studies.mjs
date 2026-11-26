// Node reference for tests/service/test_studies.py: the robustness-study code of webapp/server/studies/.
// Writes only <out.json> and under the directories the spec names (synthetic roots, scratch queues and studies).
// Usage: node tests/service/parity/studies.mjs <spec.json> <out.json>
//
// spec: {mode, ...}; the output is {node: process.version, cases: [...]}, one entry per case with its `id`.
//
// Mode 'aggregate' (protocol.mjs): spec.cases are [{id, op, text}]. `text` is JSON that is parsed and then revived:
// an object {"$js": "NaN" | "Infinity" | "-Infinity" | "undefined"} anywhere becomes that value (an undefined
// object member stays an own property, an undefined item stays an item). By op:
// - 'empirical': empiricalSummary(value);
// - 'summarize': summarizeStudyCase(value);
// - 'aggregate': value is {protocol, cases}; a case with an own '$result' member has it removed and gets
//   `summary = summarizeStudyCase($result)`, as the study store sets it from a snapshot, then
//   aggregateStudy(protocol, cases).
// Recorded: {ok: true, json, after} with json = JSON.stringify(result) and after = JSON.stringify(value) once the
// function returned (an input must not change), or {ok: false, name, message} when it throws.
//
// A failure of the modes below is recorded as {ok: false, status, safe, message, code, name}: `safe` when Node's
// middleware would show the message (studySafe, resourceSafe or projectSafe), `code` a system error's code.
//
// Mode 'identity' (service.mjs create on Node's own scientific context): spec {owner, now, cases: [{id, root,
// python, base, input, study_id}]}. Per case: LocalComputeQueue({repositoryRoot: root, python}) with its
// DesignEvaluationService, communityAdapters' 'design-evaluation' adapter in a CommunityQueue at <base>/queue
// (never dispatching), a StudyStore at <base>/studies whose clock is `now` and whose study identifier is study_id,
// and RobustnessStudyService.create(input) for the visitor {id: owner}. Recorded: {ok, response: JSON text,
// bytes: the study.json text, tasks: the receipt count} or the failure.
//
// Mode 'store' (store.mjs): spec {owner, cases: [{id, directory, limits, steps}]}: a StudyStore at
// <directory> (limits over STUDY_LIMITS, the count caps out of reach), whose clock is 2026-11-25T00:00:<n>.000Z at
// step n and whose study identifiers are 5d5d0000-0000-4000-8000-<k, 12 digits> from k = 1. Steps, each recorded
// as {ok, value: JSON text} or the failure:
//   ['create', prepared], ['update', id, change], ['control', id, change] (control update), ['archive', id, index,
//   base64], ['load', id], ['all'], ['ids'], ['usage'], ['present', id, export], ['snapshot', id, index],
//   ['before', null | 'resource' | 'quota'] (beforeWrite then passes or throws a resource or a 507 refusal),
//   and file steps on paths relative to <directory>: ['write', path, base64], ['symlink', target, path],
//   ['link', existing, path], ['mkdir', path], ['rm', path], ['chmod', path, mode], ['rename', from, to],
//   ['copy', from, to] (a new file with the same bytes).
//   A change is {set: [[path, value]], delete: [path]} on the loaded record (a path is a list of members).
// Each case also records `tree`: [[relative path, 'dir' | 'file' | 'link', mode, base64 | target]] in byte order
// (empty unless <directory> is a directory).
//
// Mode 'export' (service.mjs and store.mjs through the check's fixture): spec {owner, cases: [{id, root, queue,
// studies, clock: {start, step}, caches: [[key, text]], steps}]}. The adapter is the check-robustness-studies.mjs
// fixture's (identity {protocol: 'unchanged-design-evaluation/1', version, head_id?}, lookup of
// <root>/results/v2/design_evaluation_jobs/<key>/cache.json, never a worker) in a CommunityQueue at <queue> that never
// dispatches, with `now` = clock.start. `new Date()` without arguments and the store's clock are clock.start +
// clock.step * n at the n-th call (the draft pruning reads the clock without advancing it); study, operation and
// receipt identifiers are 5d5d0000-..., 0e0e0000-... and 7e7e0000-0000-4000-8000-<k> from k = 1. Steps:
//   ['create', input], ['start', resume], ['cancel'], ['flush'], ['get'], ['list'], ['export'], ['restart'],
//   ['version', n], ['task', index, {member: value}] (changes a receipt), ['tasks'] (the receipts' id, key, status),
//   ['case', index | null, {member: value}] (a store update of the current study's case, or of the study itself
//   for null), ['cache', key, text | null]
//   (writes or removes a cache.json), ['symlink_key', key] (the key directory becomes a link to a copy).
// The current study is the one the last create returned. Recorded per step as in 'store'; the case also records the
// study.json text and the snapshot names.
//
// Mode 'dates': spec.cases are [{id, text}]; recorded {id, finite: Number.isFinite(Date.parse(text))}, the check
// validate() applies to created_at and updated_at.
import { createRequire, syncBuiltinESMExports } from 'node:module';
import { createHash } from 'node:crypto';
import {
  chmodSync, cpSync, linkSync, lstatSync, mkdirSync, readFileSync, readdirSync, readlinkSync, renameSync, rmSync,
  symlinkSync, writeFileSync,
} from 'node:fs';
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { aggregateStudy, empiricalSummary, summarizeStudyCase } from '../../../webapp/server/studies/protocol.mjs';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: studies.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));

// Pinned identifiers: only the study store's study identifiers, the study service's operation identifiers and the
// community queue's receipt identifiers (syncBuiltinESMExports carries the replacement to the named exports).
const require = createRequire(import.meta.url);
const crypto = require('node:crypto');
const realUUID = crypto.randomUUID;
const pins = { study: null, operation: null, receipt: null };
crypto.randomUUID = function (...args) {
  const caller = new Error().stack.split('\n')[2] ?? '';
  if (pins.study && caller.includes('/studies/store.mjs:') && !caller.includes('atomicBytes')) return pins.study();
  if (pins.operation && caller.includes('/studies/service.mjs:')) return pins.operation();
  if (pins.receipt && caller.includes('/community-queue.mjs:') && caller.includes('receipt')) return pins.receipt();
  return realUUID.apply(this, args);
};
syncBuiltinESMExports();
const sequence = (prefix) => {
  let n = 0;
  return () => `${prefix}-0000-4000-8000-${String(++n).padStart(12, '0')}`;
};

const RealDate = Date;
const clock = { start: 0, step: 0, calls: 0, on: false };
globalThis.Date = class extends RealDate {
  constructor(...args) {
    if (args.length || !clock.on) super(...args);
    else super(clock.start + clock.step * clock.calls++);
  }
};

const SPECIAL = { NaN: NaN, Infinity: Infinity, '-Infinity': -Infinity, undefined };
const define = (target, key, value) =>
  Object.defineProperty(target, key, { value, enumerable: true, writable: true, configurable: true });
function revive(value) {
  if (Array.isArray(value)) return value.map(revive);
  if (!value || typeof value !== 'object') return value;
  const keys = Object.keys(value);
  if (keys.length === 1 && keys[0] === '$js') {
    if (!Object.hasOwn(SPECIAL, value.$js)) throw new Error(`unknown special ${value.$js}`);
    return SPECIAL[value.$js];
  }
  const out = {};
  for (const key of keys) define(out, key, revive(value[key]));  // '__proto__' stays an own member
  return out;
}

const AGGREGATE_OPS = {
  empirical: value => empiricalSummary(value),
  summarize: value => summarizeStudyCase(value),
  aggregate: value => {
    for (const entry of value.cases)
      if (entry && typeof entry === 'object' && Object.hasOwn(entry, '$result')) {
        const result = entry.$result;
        delete entry.$result;
        entry.summary = summarizeStudyCase(result);
      }
    return aggregateStudy(value.protocol, value.cases);
  },
};

function aggregate() {
  return spec.cases.map(({ id, op, text }) => {
    const run = AGGREGATE_OPS[op];
    if (!run) throw new Error(`unknown op ${op}`);
    const value = revive(JSON.parse(text));
    try {
      const result = run(value);
      return { id, ok: true, json: JSON.stringify(result) ?? null, after: JSON.stringify(value) ?? null };
    } catch (error) {
      return { id, ok: false, name: error.name, message: error.message };
    }
  });
}

// --- The study modes -----------------------------------------------------------------------------------------------

const hash = (value) => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const failure = (error) => ({
  ok: false,
  status: error?.status ?? null,
  safe: Boolean(error?.studySafe || error?.resourceSafe || error?.projectSafe),
  message: error?.studySafe || error?.resourceSafe || error?.projectSafe ? error.message : null,
  code: typeof error?.code === 'string' ? error.code : null,
  name: error?.name ?? null,
});
async function record(run) {
  try {
    const value = await run();
    return { ok: true, value: value == null ? null : JSON.stringify(value) };
  } catch (error) {
    return failure(error);
  }
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
function applyChange(record, change) {
  for (const [path, value] of change.set ?? []) {
    let target = record;
    for (const key of path.slice(0, -1)) target = target[key];
    target[path.at(-1)] = revive(value);
  }
  for (const path of change.delete ?? []) {
    let target = record;
    for (const key of path.slice(0, -1)) target = target[key];
    delete target[path.at(-1)];
  }
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
  else if (kind === 'copy') writeFileSync(at(args[1]), readFileSync(at(args[0])), { flag: 'wx' });
  else return false;
  return true;
}
const blocked = (kind) => {
  if (kind === 'resource') return Object.assign(new Error('Resource blocked'), { status: 503, resourceSafe: true });
  if (kind === 'quota') return Object.assign(new Error('Study quota'), { status: 507, studySafe: true });
  return null;
};

async function identity() {
  const { LocalComputeQueue } = await import('../../../webapp/server/local-compute-server.mjs');
  const { DesignEvaluationService } = await import('../../../webapp/server/design-evaluation-server.mjs');
  const { communityAdapters } = await import('../../../webapp/server/community-adapters.mjs');
  const { CommunityQueue } = await import('../../../webapp/server/community-queue.mjs');
  const { StudyStore } = await import('../../../webapp/server/studies/store.mjs');
  const { RobustnessStudyService } = await import('../../../webapp/server/studies/service.mjs');
  const out = [];
  for (const item of spec.cases) {
    const queue = new LocalComputeQueue({ repositoryRoot: item.root, python: item.python,
      queueDirectory: join(item.base, 'queue') });
    queue.designTests = new DesignEvaluationService(queue);
    const scheduler = new CommunityQueue({ directory: join(item.base, 'queue'), pollMs: 3600000,
      adapters: { 'design-evaluation': communityAdapters(queue, (r) => r)['design-evaluation'] } });
    const store = new StudyStore(join(item.base, 'studies'), { now: () => spec.now });
    const service = new RobustnessStudyService({ queue, scheduler, store, pollMs: 3600000 });
    pins.study = () => item.study_id;
    let result;
    try {
      const created = await service.create(revive(item.input), { id: spec.owner });
      result = { ok: true, response: JSON.stringify(created),
        bytes: readFileSync(join(store.directory, created.study.id, 'study.json'), 'utf8'),
        tasks: scheduler.tasks.length };
    } catch (error) {
      result = { ...failure(error), tasks: scheduler.tasks.length };
    } finally {
      pins.study = null;
      service.stop();
      await service.flush();
      service.close();
      scheduler.dispose();
      queue.designTests.dispose();
    }
    out.push({ id: item.id, ...result });
  }
  return out;
}

async function store() {
  const { StudyStore } = await import('../../../webapp/server/studies/store.mjs');
  const { STUDY_LIMITS } = await import('../../../webapp/server/studies/protocol.mjs');
  const out = [];
  for (const item of spec.cases) {
    let step = 0, before = null;
    pins.study = sequence('5d5d0000');
    const studies = new StudyStore(item.directory, {
      now: () => new RealDate(RealDate.UTC(2026, 10, 25, 0, 0, step)).toISOString(),
      beforeWrite: async () => { const error = blocked(before); if (error) throw error; },
      limits: { ...STUDY_LIMITS, studies: 1e9, perOwner: 1e9, perNetwork: 1e9, ...(item.limits ?? {}) },
    });
    const records = [];
    for (const [kind, ...args] of item.steps) {
      step++;
      if (kind === 'before') { before = args[0]; records.push({ ok: true, value: null }); continue; }
      if (fileStep(item.directory, kind, args)) { records.push({ ok: true, value: null }); continue; }
      records.push(await record(async () => {
        if (kind === 'create') return studies.create(spec.owner, revive(args[0]));
        if (kind === 'update') return studies.update(args[0], undefined, (value) => applyChange(value, args[1]));
        if (kind === 'control')
          return studies.controlUpdate(args[0], undefined, (value) => applyChange(value, args[1]));
        if (kind === 'archive') return studies.archive(args[0], undefined, args[1], Buffer.from(args[2], 'base64'));
        if (kind === 'load') return studies.load(args[0]);
        if (kind === 'all') return studies.all();
        if (kind === 'ids') return studies.ids();
        if (kind === 'usage') return studies.usage();
        if (kind === 'present') return studies.present(args[0], undefined, args[1]);
        if (kind === 'snapshot') {
          const value = await studies.load(args[0]);
          return studies.snapshot(value, value.cases[args[1]]);
        }
        throw new Error(`unknown step ${kind}`);
      }));
    }
    await studies.flush();
    pins.study = null;
    out.push({ id: item.id, records, tree: tree(item.directory) });
  }
  return out;
}

async function exportMode() {
  const { CommunityQueue } = await import('../../../webapp/server/community-queue.mjs');
  const { StudyStore } = await import('../../../webapp/server/studies/store.mjs');
  const { RobustnessStudyService } = await import('../../../webapp/server/studies/service.mjs');
  const { normalizeDesignRequest, validateDesignResult } =
    await import('../../../webapp/server/design-evaluation-server.mjs');
  const out = [];
  for (const item of spec.cases) {
    const visitor = { id: spec.owner };
    let version = 1, current = null;
    const cachePath = (key) => join(item.root, 'results/v2/design_evaluation_jobs', key, 'cache.json');
    const writeCache = (key, text) => {
      if (text === null) return rmSync(cachePath(key), { force: true });
      mkdirSync(dirname(cachePath(key)), { recursive: true });
      writeFileSync(cachePath(key), text);
    };
    for (const [key, text] of item.caches) writeCache(key, text);
    const identityOf = (request) => ({ protocol: 'unchanged-design-evaluation/1', version,
      ...(request?.head_id ? { head_id: request.head_id } : {}) });
    const adapter = {
      async prepare(raw) {
        const request = normalizeDesignRequest(raw?.schema === 'design-submission/1' ? raw.request : raw),
          ctx = { identity: identityOf(request) };
        return { request, key: hash({ request, identity: ctx.identity }), ctx };
      },
      async lookup(prepared) {
        try {
          const cache = JSON.parse(await readFile(cachePath(prepared.key), 'utf8'));
          validateDesignResult(cache.result, prepared.request);
          return { hit: true, job: { id: realUUID(), key: prepared.key, request: prepared.request, status: 'completed',
            cached: true, result: cache.result } };
        } catch {
          return { hit: false };
        }
      },
      start() { throw new Error('Studies parity must not launch a scientific worker'); },
      busy: () => false,
      get: () => null,
      cancel() {},
    };
    clock.start = item.clock.start; clock.step = item.clock.step; clock.calls = 0; clock.on = true;
    pins.study = sequence('5d5d0000'); pins.operation = sequence('0e0e0000'); pins.receipt = sequence('7e7e0000');
    const scheduler = new CommunityQueue({ directory: item.queue, adapters: { 'design-evaluation': adapter },
      pollMs: 3600000, now: () => item.clock.start });
    const make = () => new RobustnessStudyService({ queue: { root: item.root }, scheduler, pollMs: 3600000,
      store: new StudyStore(item.studies, {
        // The draft pruning reads the clock as well; it must not advance it (Python does not prune).
        now: () => new Error().stack.includes('pruneDrafts')
          ? new RealDate(clock.start + clock.step * clock.calls).toISOString()
          : new Date().toISOString(),
      }) });
    let service = make();
    const records = [];
    for (const [kind, ...args] of item.steps) {
      records.push(await record(async () => {
        if (kind === 'create') {
          const created = await service.create(revive(args[0]), visitor);
          current = created.study.id;
          return created;
        }
        if (kind === 'start') return service.start(current, visitor, args[0]);
        if (kind === 'cancel') return service.cancel(current, visitor);
        if (kind === 'flush') return service.flush();
        if (kind === 'get') return service.get(current, visitor);
        if (kind === 'list') return service.list(visitor);
        if (kind === 'export') return service.store.present(current, visitor.id, true);
        if (kind === 'restart') {
          service.stop();
          await service.flush();
          service.close();
          service = make();
          return service.ready();
        }
        if (kind === 'version') { version = args[0]; return null; }
        if (kind === 'task') { Object.assign(scheduler.tasks[args[0]], args[1]); return null; }
        if (kind === 'tasks')
          return scheduler.tasks.map(({ id, key, status, message }) => ({ id, key, status, message }));
        if (kind === 'case')
          return service.store.update(current, undefined, (value) => {
            Object.assign(args[0] === null ? value : value.cases[args[0]], args[1]);
          });
        if (kind === 'cache') { writeCache(args[0], args[1]); return null; }
        if (kind === 'symlink_key') {
          const directory = dirname(cachePath(args[0]));
          cpSync(directory, `${directory}.copy`, { recursive: true });
          rmSync(directory, { recursive: true });
          symlinkSync(`${directory}.copy`, directory);
          return null;
        }
        throw new Error(`unknown step ${kind}`);
      }));
    }
    service.stop();
    await service.flush();
    service.close();
    scheduler.dispose();
    clock.on = false;
    pins.study = pins.operation = pins.receipt = null;
    const study = current ? join(item.studies, current) : null;
    out.push({
      id: item.id, records,
      study: study ? readFileSync(join(study, 'study.json'), 'utf8') : null,
      snapshots: study ? readdirSync(join(study, 'snapshots')).sort() : null,
    });
  }
  return out;
}

const dates = () => spec.cases.map(({ id, text }) => ({ id, finite: Number.isFinite(Date.parse(text)) }));

const MODES = { aggregate, identity, store, export: exportMode, dates };
const mode = MODES[spec.mode];
if (!mode) throw new Error(`unknown mode ${spec.mode}`);
writeFileSync(outPath, JSON.stringify({ node: process.version, cases: await mode() }));
process.exit(0);
