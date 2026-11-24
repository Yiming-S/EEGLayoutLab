// Node reference for tests/service/test_editor.py and the editor half of tests/service/test_key_parity.py:
// ElectrodeEditorService (webapp/server/electrode-editor-server.mjs) on a LocalComputeQueue of the case root, as
// createLocalComputeService builds it, so its library, design context and digests are Node's own on that root.
// Writes only under the case roots of the `runs` mode and <out.json>; the queue directory is resolved, never created.
// Usage: node tests/service/parity/editor_run.mjs <spec.json> <out.json>
//
// spec: {mode: 'contexts' | 'runs', queueDirectory, ...}
//
// mode 'contexts': {reuse?, cases: [{id, root, python?, env?, request}]}
// - Each case builds `new LocalComputeQueue({repositoryRoot: root, python, queueDirectory})` and
//   `new ElectrodeEditorService(queue)` after setting process.env.EEG_COMPUTE_PYTHON from `env` (or deleting it),
//   then records `await service.context(request)`: the configuration, the identity, admission and parent as
//   JSON text, the parent digest, the key, the context's member order and the worker input of a job with that
//   request and context; or the error's name, message and code. With `reuse`, cases with the same root, python and
//   env share one queue and service (the real installation, where hashing every input again is slow).
//
// mode 'runs': {cases: [{id, root, python, timeoutMs, throw, clock: {start, step}, steps}]}, the run path as
// parity/design_run.mjs drives DesignEvaluationService (its header documents the clock, the pinned job identifiers
// and the steps), with the editor's service and one more step: ['tamper', path, text] writes `text` (as many bytes
// as the file had) to a file of the root and gives it back its access and modification times, so the library's
// memo (modification time and size) keeps the file while InputIntegrity's (which also reads the change time)
// hashes it again.
// out: {node, platform, cases: [...]}
import { createHash } from 'node:crypto';
import { EventEmitter } from 'node:events';
import { chmodSync, mkdirSync, readFileSync, renameSync, rmdirSync, rmSync, statSync, utimesSync, writeFileSync } from 'node:fs';
import { createRequire, syncBuiltinESMExports } from 'node:module';
import { join } from 'node:path';
import { PassThrough } from 'node:stream';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: editor_run.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
if (typeof spec.queueDirectory !== 'string' || !spec.queueDirectory.startsWith('/')) throw new Error('spec.queueDirectory must be absolute');

// Pin the job identifiers before design-evaluation-server.mjs binds randomUUID (syncBuiltinESMExports carries the
// replacement to the named export of node:crypto). The editor's submit and lookup are DesignEvaluationService's, so
// only calls made directly by that module are pinned.
const require = createRequire(import.meta.url);
const crypto = require('node:crypto');
const randomUUID = crypto.randomUUID;
let ids = 0;
crypto.randomUUID = function (...args) {
  const caller = new Error().stack.split('\n')[2] ?? '';
  if (caller.includes('/design-evaluation-server.mjs:')) return `00000000-0000-4000-8000-${String(++ids).padStart(12, '0')}`;
  return randomUUID.apply(this, args);
};
syncBuiltinESMExports();

const RealDate = Date;
const clock = { start: 0, step: 0, calls: 0 };
globalThis.Date = class extends RealDate {
  constructor(...args) {
    if (args.length) super(...args);
    else super(clock.start + clock.step * clock.calls++);
  }
};

const { LocalComputeQueue } = await import('../../../webapp/server/local-compute-server.mjs');
const { ElectrodeEditorService } = await import('../../../webapp/server/electrode-editor-server.mjs');

const THREADS = ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'PYTHONDONTWRITEBYTECODE'];
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const failure = error => ({ name: error?.name ?? null, message: String(error?.message ?? error), code: error?.code ?? null });

// --- contexts ------------------------------------------------------------------------------------------------------

async function contexts() {
  const services = new Map();
  const serviceFor = (c) => {
    const id = JSON.stringify([c.root, c.python ?? null, c.env ?? null]);
    if (spec.reuse && services.has(id)) return services.get(id);
    if (c.env && 'EEG_COMPUTE_PYTHON' in c.env) process.env.EEG_COMPUTE_PYTHON = c.env.EEG_COMPUTE_PYTHON;
    else delete process.env.EEG_COMPUTE_PYTHON;
    const queue = new LocalComputeQueue({ repositoryRoot: c.root, python: c.python, queueDirectory: spec.queueDirectory });
    const entry = { queue, service: new ElectrodeEditorService(queue) };
    if (spec.reuse) services.set(id, entry);
    return entry;
  };
  const cases = [];
  for (const c of spec.cases) {
    let config;
    try {
      const { queue, service } = serviceFor(c);
      config = { repositoryRoot: queue.root, python: queue.python, nativePython: service.python };
      const ctx = await service.context(c.request);
      cases.push({ id: c.id, ok: true, config, keys: Object.keys(ctx), identity: JSON.stringify(ctx.identity),
        admission: JSON.stringify(ctx.admission), parent: JSON.stringify(ctx.parent), parent_digest: ctx.parent_digest,
        key: ctx.key, worker_input: JSON.stringify(service.workerInput({ request: c.request, ctx })) });
    } catch (error) {
      cases.push({ id: c.id, ok: false, ...(config ? { config } : {}), ...failure(error) });
    }
  }
  return cases;
}

// --- runs ----------------------------------------------------------------------------------------------------------

async function until(check, limit = 20000) {
  const deadline = RealDate.now() + limit;
  while (!check()) {
    if (RealDate.now() > deadline) throw new Error('editor run did not settle');
    await new Promise(resolve => setTimeout(resolve, 5));
  }
}

async function runCase(item) {
  clock.start = item.clock.start; clock.step = item.clock.step; clock.calls = 0; ids = 0;
  const records = [], children = [];
  const make = (options = {}) => {
    const thrown = 'throw' in options ? options.throw : item.throw;
    const queue = new LocalComputeQueue({ repositoryRoot: item.root, python: item.python, queueDirectory: spec.queueDirectory });
    const service = new ElectrodeEditorService(queue, {
      timeoutMs: item.timeoutMs,
      spawnProcess: (executable, args, options) => {
        if (thrown !== null) throw new Error(thrown);
        const child = new EventEmitter();
        child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.stdin = new PassThrough();
        child.input = []; child.stdin.on('data', chunk => child.input.push(chunk));
        child.kills = []; child.kill = signal => { child.kills.push(signal); return true; };
        children.push({ child, executable, args, options });
        return child;
      },
    });
    return { queue, service };
  };
  let { queue, service } = make(), current = null, release = null;
  const child = () => children.at(-1).child;
  const record = async (kind, run) => {
    try {
      const value = await run();
      records.push([kind, JSON.stringify(value === undefined ? null : value)]);
      return value;
    } catch (error) {
      records.push([kind, JSON.stringify({ error: error.message })]);
      return null;
    }
  };
  for (const [kind, ...args] of item.steps) {
    if (kind === 'submit') {
      const value = await record(kind, () => service.submit(args[0]));
      if (value?.job) current = value.job.id;
    } else if (kind === 'submit_pair') {
      const first = service.submit(args[0]), second = service.submit(args[1]);
      const value = await record(kind, () => first);
      await record(kind, () => second);
      if (value?.job) current = value.job.id;
    } else if (kind === 'lookup') await record(kind, () => service.lookup(args[0]));
    else if (kind === 'view') await record(kind, () => service.view(service.jobs.get(current)));
    else if (kind === 'jobs') await record(kind, () => [...service.jobs.keys()]);
    else if (kind === 'pid') await record(kind, () => service.active?.child?.pid ?? null);
    else if (kind === 'cancel') await record(kind, () => (args[0] === null ? service.cancel(current) : service.cancel(current, args[0])));
    else if (kind === 'cancel_id') await record(kind, () => service.cancel(args[0]));
    else if (kind === 'stop') await record(kind, () => service.jobs.get(current).worker.stop(args[0]));
    else if (kind === 'dispose') service.dispose();
    else if (kind === 'restart') { service.dispose(); ({ queue, service } = make(args[0] ?? {})); }
    else if (kind === 'acquire') await record(kind, () => { release = queue.executionSlot.acquire('other'); return Boolean(release); });
    else if (kind === 'release') { release?.(); release = null; }
    else if (kind === 'pause') queue.executionSlot.pause();
    else if (kind === 'resume') queue.executionSlot.resume();
    else if (kind === 'stdout') child().stdout.write(Buffer.from(args[0], 'base64'));
    else if (kind === 'stdout_fill') child().stdout.write(Buffer.alloc(args[0], 32));
    else if (kind === 'stderr') child().stderr.write(Buffer.from(args[0], 'base64'));
    else if (kind === 'error') child().emit('error', new Error(args[0]));
    else if (kind === 'stdin_error') child().stdin.emit('error', Object.assign(new Error(args[0]), { code: args[1] }));
    else if (kind === 'close') child().emit('close', args[0], args[1]);
    else if (kind === 'wait_kill') await until(() => child().kills.length > 0);
    else if (kind === 'settle') await until(() => !service.active);
    else if (kind === 'rm_batch') rmSync(service.jobs.get(current).batch, { recursive: true, force: true });
    else if (kind === 'block_cache') mkdirSync(join(service.jobs.get(current).directory, 'cache.json'));
    else if (kind === 'write_cache') {
      const j = service.jobs.get(current), path = join(j.directory, 'cache.json');
      writeFileSync(path, args[0] === 'text' ? args[1] : JSON.stringify({ key: j.key, identity: j.ctx.identity, result: args[1],
        result_sha256: args[0] === 'valid' ? hash(args[1]) : hash('tampered'), finished_at: '2026-01-01T00:00:00.000Z' }));
    } else if (kind === 'deny_cache') chmodSync(join(service.jobs.get(current).directory, 'cache.json'), 0o000);
    else if (kind === 'allow_cache') chmodSync(join(service.jobs.get(current).directory, 'cache.json'), 0o600);
    else if (kind === 'change') writeFileSync(join(item.root, args[0]), args[1]);
    else if (kind === 'tamper') {
      const path = join(item.root, args[0]), before = statSync(path);
      writeFileSync(path, args[1]);
      if (statSync(path).size !== before.size) throw new Error('tamper changed the size');
      utimesSync(path, before.atime, before.mtime);
    } else if (kind === 'move') renameSync(join(item.root, args[0]), join(item.root, args[1]));
    else if (kind === 'mkdir') mkdirSync(join(item.root, args[0]));
    else if (kind === 'rmdir') rmdirSync(join(item.root, args[0]));
    else if (kind === 'chmod') chmodSync(join(item.root, args[0]), args[1]);
    else throw new Error(`unknown step ${kind}`);
  }
  await until(() => !service.active);
  service.dispose();
  release?.();
  await new Promise(resolve => setImmediate(resolve)); // the PassThrough delivers stdin data asynchronously
  return {
    id: item.id, records, clock: clock.calls, ids,
    children: children.map(({ child, executable, args, options }) => ({
      executable, args, cwd: options.cwd, stdio: options.stdio, detached: options.detached, shell: options.shell,
      env: Object.fromEntries(THREADS.map(name => [name, options.env[name] ?? null])),
      inherits: Object.entries(process.env).every(([name, value]) => THREADS.includes(name) || options.env[name] === value),
      added: Object.keys(options.env).filter(name => !(name in process.env) && !THREADS.includes(name)).sort(),
      input: Buffer.concat(child.input).toString('base64'), kills: child.kills,
    })),
  };
}

async function runs() {
  const cases = [];
  for (const item of spec.cases) cases.push(await runCase(item));
  return cases;
}

const cases = spec.mode === 'contexts' ? await contexts() : spec.mode === 'runs' ? await runs() : null;
if (!cases) throw new Error(`unknown mode ${spec.mode}`);
writeFileSync(outPath, JSON.stringify({ node: process.version, platform: process.platform, cases }));
// The services hold no timers once settled, but the imported modules may; the result is written.
process.exit(0);
