// Node reference for tests/service/test_design.py: the run path of DesignEvaluationService
// (webapp/server/design-evaluation-server.mjs) on a LocalComputeQueue of the case root, as createLocalComputeService
// builds it, with an injected spawnProcess that replays a scripted worker, a pinned clock and pinned job identifiers,
// so the request.json, job.json and cache.json it writes can be compared byte for byte with those of
// eeglayoutlab.jobs.design.DesignJobs given the same script. The scientific context is Node's own on the case root.
// Writes only under the case roots and <out.json>; the queue directory is resolved, never created.
// Usage: node tests/service/parity/design_run.mjs <spec.json> <out.json>
//
// spec: {queueDirectory, cases: [{id, root, python, timeoutMs, throw, clock: {start, step}, steps}]}
// - throw: a message the spawnProcess throws (null: it returns a fake child as check-design-decision.mjs builds one).
// - clock: `new Date()` without arguments is start + step * n at its n-th call (from 0); Date.now stays real.
// - the service's own randomUUID calls (job identifiers) return 00000000-0000-4000-8000-<n, 12 digits> from n = 1;
//   the record store's temporary names stay random.
// - steps, run in order (the "current" job is the one the last submit returned, the current child the last one
//   spawned): ['submit', raw], ['submit_pair', raw, raw] (the second while the first awaits its context),
//   ['lookup', raw], ['view'], ['jobs'] (the identifiers the service remembers), ['pid'], ['cancel', reason | null],
//   ['cancel_id', id], ['stop', reason] (the current worker's stop), ['dispose'], ['restart', {throw?}] (dispose,
//   then a new queue and service on the same root), ['acquire'] and ['release'] (the execution permit for another
//   owner), ['pause'], ['resume'], ['stdout', base64], ['stdout_fill', bytes] (that many spaces in one chunk),
//   ['stderr', base64], ['error', message], ['stdin_error', message, code], ['close', code, signal],
//   ['wait_kill'] (until the current child got a signal), ['settle'] (until no job is active), ['rm_batch'] (removes
//   the current job's batch directory), ['block_cache'] (a directory named cache.json in its key directory),
//   ['write_cache', 'valid', result] (a cache.json for its key, identity and that result, finished 2026-01-01),
//   ['write_cache', 'tampered', result] (the same with another checksum) or ['write_cache', 'text', text],
//   ['deny_cache'] and ['allow_cache'] (its cache.json made unreadable, then readable again), ['change', path, text]
//   (writes a file of the root), ['move', from, to], ['mkdir', path], ['rmdir', path] and ['chmod', path, mode]
//   (paths of the root).
// out: {node, cases: [{id, records: [[kind, JSON text]], children: [...], clock, ids}]}; a step that throws is
//   recorded as {error: message}.
import { createHash } from 'node:crypto';
import { EventEmitter } from 'node:events';
import { chmodSync, mkdirSync, readFileSync, renameSync, rmdirSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire, syncBuiltinESMExports } from 'node:module';
import { join } from 'node:path';
import { PassThrough } from 'node:stream';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: design_run.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));

// Pin the job identifiers before design-evaluation-server.mjs binds randomUUID (syncBuiltinESMExports carries the
// replacement to the named export of node:crypto). Only calls made directly by that module are pinned.
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
const { DesignEvaluationService } = await import('../../../webapp/server/design-evaluation-server.mjs');

const THREADS = ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'PYTHONDONTWRITEBYTECODE'];
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');

async function until(check, limit = 20000) {
  const deadline = RealDate.now() + limit;
  while (!check()) {
    if (RealDate.now() > deadline) throw new Error('design run did not settle');
    await new Promise(resolve => setTimeout(resolve, 5));
  }
}

async function runCase(item) {
  clock.start = item.clock.start; clock.step = item.clock.step; clock.calls = 0; ids = 0;
  const records = [], children = [];
  const make = (options = {}) => {
    const thrown = 'throw' in options ? options.throw : item.throw;
    const queue = new LocalComputeQueue({ repositoryRoot: item.root, python: item.python, queueDirectory: spec.queueDirectory });
    const service = new DesignEvaluationService(queue, {
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
    else if (kind === 'move') renameSync(join(item.root, args[0]), join(item.root, args[1]));
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

const cases = [];
for (const item of spec.cases) cases.push(await runCase(item));
writeFileSync(outPath, JSON.stringify({ node: process.version, cases }));
process.exit(0);
