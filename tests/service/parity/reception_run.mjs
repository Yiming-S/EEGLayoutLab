// Node reference for tests/service/test_source.py and the reception half of tests/service/test_key_parity.py:
// SourceReceptionService (webapp/server/source-reception-server.mjs) on a LocalComputeQueue of the case root, as
// createLocalComputeService builds it, so its library, contexts, digests and runtime inspector are Node's own on
// that root. Writes only under the case roots of the `runs` mode and <out.json>; the queue directory is resolved,
// never created. EEG_COMPUTE_PYTHON is deleted first, so a case without `python` is configured as the Python side's
// `runtime_config(root, python, env={})` configures it.
// Usage: node tests/service/parity/reception_run.mjs <spec.json> <out.json>
//
// spec: {mode: 'contexts' | 'runs', queueDirectory, ...}
//
// mode 'contexts': {reuse?, cases: [{id, root, python?, request}]}
// - Each case builds `new LocalComputeQueue({repositoryRoot: root, python, queueDirectory})` and
//   `new SourceReceptionService(queue)` and records `await service.context(request)`: the configuration, the
//   context's member order, the record and identity as JSON text and the key; or the error's name, message and code.
//   With `reuse`, cases with the same root and python share one queue and service (and so one runtime memo).
//
// mode 'runs': {cases: [{id, root, python, timeoutMs, throw, clock: {start, step}, steps}]}, the run path as
// parity/design_run.mjs drives DesignEvaluationService (its header documents the clock, the pinned job identifiers
// and most steps; here the service's own randomUUID calls are pinned), with these steps of the reception service:
// ['saved', key | null, raw] (savedResult of that key, or the current job's), ['catalog'] (sourceCatalog of the
// service), ['result', file] (the file's bytes as the current job's result.json), ['result_text', text],
// ['result_size', bytes] (a result.json of that size, as truncate makes it), ['result_dir'] (a directory named
// result.json), ['write_cache', 'valid' | 'tampered', file] (a cache.json of the current job's key, with its identity
// for v2, the result parsed from the file, its checksum or another's, finished 2026-01-01) or ['write_cache', 'text',
// text], ['put', path, file] (the file's bytes at a path of the root), ['put_size', path, bytes] and ['put_dir', path].
// A fake child has no stdin (the workers' stdio is ['ignore', 'pipe', 'pipe']). A record whose JSON text is longer
// than 65,536 UTF-8 bytes (a view with its result) is recorded as `sha256:<hex>` of that text.
// out: {node, platform, cases: [...]}
import { createHash } from 'node:crypto';
import { EventEmitter } from 'node:events';
import { chmodSync, closeSync, copyFileSync, mkdirSync, openSync, readFileSync, rmSync, truncateSync, writeFileSync } from 'node:fs';
import { createRequire, syncBuiltinESMExports } from 'node:module';
import { dirname, join } from 'node:path';
import { PassThrough } from 'node:stream';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: reception_run.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
if (typeof spec.queueDirectory !== 'string' || !spec.queueDirectory.startsWith('/')) throw new Error('spec.queueDirectory must be absolute');
delete process.env.EEG_COMPUTE_PYTHON;

// Pin the job identifiers before source-reception-server.mjs binds randomUUID (syncBuiltinESMExports carries the
// replacement to the named export of node:crypto); only calls made directly by that module are pinned.
const require = createRequire(import.meta.url);
const crypto = require('node:crypto');
const randomUUID = crypto.randomUUID;
let ids = 0;
crypto.randomUUID = function (...args) {
  const caller = new Error().stack.split('\n')[2] ?? '';
  if (caller.includes('/source-reception-server.mjs:')) return `00000000-0000-4000-8000-${String(++ids).padStart(12, '0')}`;
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
const { SourceReceptionService } = await import('../../../webapp/server/source-reception-server.mjs');
const { sourceCatalog } = await import('../../../webapp/server/reception-v2-support.mjs');

const THREADS = ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'PYTHONDONTWRITEBYTECODE'];
// source-reception-server.mjs's hash: a string as it is, anything else as JSON.stringify writes it.
const hash = x => createHash('sha256').update(typeof x === 'string' ? x : JSON.stringify(x)).digest('hex');
const brief = text => (Buffer.byteLength(text) > 65536 ? `sha256:${createHash('sha256').update(text).digest('hex')}` : text);
const failure = error => ({ name: error?.name ?? null, message: String(error?.message ?? error), code: error?.code ?? null });

// --- contexts ------------------------------------------------------------------------------------------------------

async function contexts() {
  const services = new Map();
  const serviceFor = (c) => {
    const id = JSON.stringify([c.root, c.python ?? null]);
    if (spec.reuse && services.has(id)) return services.get(id);
    const queue = new LocalComputeQueue({ repositoryRoot: c.root, python: c.python, queueDirectory: spec.queueDirectory });
    const entry = { queue, service: new SourceReceptionService(queue) };
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
      cases.push({ id: c.id, ok: true, config, keys: Object.keys(ctx), record: JSON.stringify(ctx.record),
        identity: JSON.stringify(ctx.identity), key: ctx.key });
    } catch (error) {
      cases.push({ id: c.id, ok: false, ...(config ? { config } : {}), ...failure(error) });
    }
  }
  for (const { queue, service } of services.values()) { service.dispose(); queue.dispose(); }
  return cases;
}

// --- runs ----------------------------------------------------------------------------------------------------------

async function until(check, limit = 20000) {
  const deadline = RealDate.now() + limit;
  while (!check()) {
    if (RealDate.now() > deadline) throw new Error('reception run did not settle');
    await new Promise(resolve => setTimeout(resolve, 5));
  }
}

const truncate = (path, size) => { closeSync(openSync(path, 'a')); truncateSync(path, size); };

async function runCase(item) {
  clock.start = item.clock.start; clock.step = item.clock.step; clock.calls = 0; ids = 0;
  const records = [], children = [];
  const make = (options = {}) => {
    const thrown = 'throw' in options ? options.throw : item.throw;
    const queue = new LocalComputeQueue({ repositoryRoot: item.root, python: item.python, queueDirectory: spec.queueDirectory });
    const service = new SourceReceptionService(queue, {
      timeoutMs: item.timeoutMs,
      spawnProcess: (executable, args, options) => {
        if (thrown !== null) throw new Error(thrown);
        const child = new EventEmitter();
        child.stdout = new PassThrough(); child.stderr = new PassThrough();
        child.kills = []; child.kill = signal => { child.kills.push(signal); return true; };
        children.push({ child, executable, args, options });
        return child;
      },
    });
    return { queue, service };
  };
  let { queue, service } = make(), current = null, release = null;
  const child = () => children.at(-1).child;
  const job = () => service.jobs.get(current);
  const record = async (kind, run) => {
    try {
      const value = await run();
      records.push([kind, brief(JSON.stringify(value === undefined ? null : value))]);
      return value;
    } catch (error) {
      records.push([kind, brief(JSON.stringify({ error: error.message }))]);
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
    else if (kind === 'saved') await record(kind, () => service.savedResult(args[0] ?? job().key, args[1]));
    else if (kind === 'catalog') await record(kind, () => sourceCatalog(service));
    else if (kind === 'view') await record(kind, () => service.view(job()));
    else if (kind === 'jobs') await record(kind, () => [...service.jobs.keys()]);
    else if (kind === 'pid') await record(kind, () => service.active?.child?.pid ?? null);
    else if (kind === 'cancel') await record(kind, () => (args[0] === null ? service.cancel(current) : service.cancel(current, args[0])));
    else if (kind === 'cancel_id') await record(kind, () => service.cancel(args[0]));
    else if (kind === 'stop') await record(kind, () => job().worker.stop(args[0]));
    else if (kind === 'dispose') service.dispose();
    else if (kind === 'restart') { service.dispose(); queue.dispose(); ({ queue, service } = make(args[0] ?? {})); }
    else if (kind === 'acquire') await record(kind, () => { release = queue.executionSlot.acquire('other'); return Boolean(release); });
    else if (kind === 'release') { release?.(); release = null; }
    else if (kind === 'pause') queue.executionSlot.pause();
    else if (kind === 'resume') queue.executionSlot.resume();
    else if (kind === 'stdout') child().stdout.write(Buffer.from(args[0], 'base64'));
    else if (kind === 'stderr') child().stderr.write(Buffer.from(args[0], 'base64'));
    else if (kind === 'error') child().emit('error', new Error(args[0]));
    else if (kind === 'close') child().emit('close', args[0], args[1]);
    else if (kind === 'wait_kill') await until(() => child().kills.length > 0);
    else if (kind === 'settle') await until(() => !service.active);
    else if (kind === 'result') copyFileSync(args[0], join(job().batch, 'result.json'));
    else if (kind === 'result_text') writeFileSync(join(job().batch, 'result.json'), args[0]);
    else if (kind === 'result_size') truncate(join(job().batch, 'result.json'), args[0]);
    else if (kind === 'result_dir') mkdirSync(join(job().batch, 'result.json'));
    else if (kind === 'rm_batch') rmSync(job().batch, { recursive: true, force: true });
    else if (kind === 'block_cache') mkdirSync(join(job().directory, 'cache.json'));
    else if (kind === 'write_cache') {
      const j = job(), path = join(j.directory, 'cache.json');
      if (args[0] === 'text') writeFileSync(path, args[1]);
      else {
        const result = JSON.parse(readFileSync(args[1], 'utf8'));
        writeFileSync(path, JSON.stringify({ key: j.key, ...(j.request.mode ? { identity: j.ctx.identity } : {}), result,
          result_sha256: hash(args[0] === 'valid' ? result : 'tampered'), finished_at: '2026-01-01T00:00:00.000Z' }));
      }
    } else if (kind === 'deny_cache') chmodSync(join(job().directory, 'cache.json'), 0o000);
    else if (kind === 'allow_cache') chmodSync(join(job().directory, 'cache.json'), 0o600);
    else if (['put', 'put_size', 'put_dir'].includes(kind)) {
      const path = join(item.root, args[0]);
      mkdirSync(dirname(path), { recursive: true });
      if (kind === 'put') copyFileSync(args[1], path);
      else if (kind === 'put_size') truncate(path, args[1]);
      else mkdirSync(path);
    } else if (kind === 'change') writeFileSync(join(item.root, args[0]), args[1]);
    else throw new Error(`unknown step ${kind}`);
  }
  await until(() => !service.active);
  service.dispose();
  queue.dispose();
  release?.();
  return {
    id: item.id, records, clock: clock.calls, ids,
    children: children.map(({ child, executable, args, options }) => ({
      executable, args, cwd: options.cwd, stdio: options.stdio, detached: options.detached, shell: options.shell,
      env: Object.fromEntries(THREADS.map(name => [name, options.env[name] ?? null])),
      inherits: Object.entries(process.env).every(([name, value]) => THREADS.includes(name) || options.env[name] === value),
      added: Object.keys(options.env).filter(name => !(name in process.env) && !THREADS.includes(name)).sort(),
      kills: child.kills,
    })),
  };
}

async function runs() {
  const cases = [];
  for (const item of spec.cases) {
    try { cases.push(await runCase(item)); } catch (error) { error.message = `${item.id}: ${error.message}`; throw error; }
  }
  return cases;
}

const cases = spec.mode === 'contexts' ? await contexts() : spec.mode === 'runs' ? await runs() : null;
if (!cases) throw new Error(`unknown mode ${spec.mode}`);
writeFileSync(outPath, JSON.stringify({ node: process.version, platform: process.platform, cases }));
// The services hold no timers once settled, but the imported modules may; the result is written.
process.exit(0);
