// Node reference for tests/service/test_radius.py: the run path of LocalComputeQueue
// (webapp/server/local-compute-server.mjs) with an injected spawnProcess that replays a scripted worker, a pinned
// clock and pinned job identifiers, so the request.json, job.json and cache.json it writes can be compared byte for
// byte with those of eeglayoutlab.jobs.radius.RadiusJobs given the same script. Writes only under the case roots and
// <out.json>; the queue directory is resolved, never created.
// Usage: node tests/service/parity/radius_run.mjs <spec.json> <out.json>
//
// spec: {queueDirectory, cases: [{id, root, python, timeoutMs, identity, throw, clock: {start, step}, steps}]}
// - identity: the code identity getIdentity returns, or null for Node's own codeIdentity, runtime and input check;
//   throw: a message the spawnProcess throws (null: it returns a fake child as check-local-compute.mjs builds one).
// - clock: `new Date()` without arguments is start + step * n at its n-th call (from 0); Date.now stays real.
// - the queue's own randomUUID calls (job identifiers) return 00000000-0000-4000-8000-<n, 12 digits> from n = 1;
//   the record store's temporary names stay random.
// - steps, run in order (the "current" job is the one the last submit returned, the current child the last one
//   spawned): ['submit', raw], ['lookup', raw], ['view'], ['health'] (without its token), ['pid'],
//   ['cancel', reason | null], ['cancel_id', id], ['dispose'], ['restart', {identity?, throw?}] (dispose, then a
//   new queue on the same root), ['stdout', base64], ['stdout_fill', bytes] (that many spaces in one chunk),
//   ['stderr', base64], ['error', message], ['stdin_error', message, code], ['close', code, signal],
//   ['wait_kill'] (until the current child got a signal), ['settle'] (until no job is active),
//   ['rm_batch'] (removes the current job's batch directory), ['block_cache'] (a directory named cache.json in its
//   key directory).
// out: {node, cases: [{id, records: [[kind, JSON text]], children: [...], clock, ids}]}; a step that throws is
//   recorded as {error: message}.
import { EventEmitter } from 'node:events';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire, syncBuiltinESMExports } from 'node:module';
import { dirname, join } from 'node:path';
import { PassThrough } from 'node:stream';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: radius_run.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));

// Pin the job identifiers before local-compute-server.mjs binds randomUUID (syncBuiltinESMExports carries the
// replacement to the named export of node:crypto). Only calls made directly by that module are pinned.
const require = createRequire(import.meta.url);
const crypto = require('node:crypto');
const randomUUID = crypto.randomUUID;
let ids = 0;
crypto.randomUUID = function (...args) {
  const caller = new Error().stack.split('\n')[2] ?? '';
  if (caller.includes('/local-compute-server.mjs:')) return `00000000-0000-4000-8000-${String(++ids).padStart(12, '0')}`;
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

const THREADS = ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'PYTHONUNBUFFERED'];

async function until(check, limit = 20000) {
  const deadline = RealDate.now() + limit;
  while (!check()) {
    if (RealDate.now() > deadline) throw new Error('radius run did not settle');
    await new Promise(resolve => setTimeout(resolve, 5));
  }
}

async function runCase(item) {
  clock.start = item.clock.start; clock.step = item.clock.step; clock.calls = 0; ids = 0;
  const records = [], children = [];
  const make = (options = {}) => {
    const identity = 'identity' in options ? options.identity : item.identity;
    const thrown = 'throw' in options ? options.throw : item.throw;
    return new LocalComputeQueue({
      repositoryRoot: item.root, python: item.python, queueDirectory: spec.queueDirectory, timeoutMs: item.timeoutMs,
      ...(identity !== null ? { getIdentity: () => identity } : {}),
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
  };
  let queue = make(), current = null;
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
      const value = await record(kind, () => queue.submit(args[0]));
      if (value?.job) current = value.job.id;
    } else if (kind === 'lookup') await record(kind, () => queue.lookup(args[0]));
    else if (kind === 'view') await record(kind, () => queue.view(queue.jobs.get(current)));
    else if (kind === 'health') await record(kind, () => { const { token, ...rest } = queue.health(); return rest; });
    else if (kind === 'pid') await record(kind, () => queue.active?.child?.pid ?? null);
    else if (kind === 'cancel') await record(kind, () => (args[0] === null ? queue.cancel(current) : queue.cancel(current, args[0])));
    else if (kind === 'cancel_id') await record(kind, () => queue.cancel(args[0]));
    else if (kind === 'dispose') queue.dispose();
    else if (kind === 'restart') { queue.dispose(); queue = make(args[0] ?? {}); }
    else if (kind === 'stdout') child().stdout.write(Buffer.from(args[0], 'base64'));
    else if (kind === 'stdout_fill') child().stdout.write(Buffer.alloc(args[0], 32));
    else if (kind === 'stderr') child().stderr.write(Buffer.from(args[0], 'base64'));
    else if (kind === 'error') child().emit('error', new Error(args[0]));
    else if (kind === 'stdin_error') child().stdin.emit('error', Object.assign(new Error(args[0]), { code: args[1] }));
    else if (kind === 'close') child().emit('close', args[0], args[1]);
    else if (kind === 'wait_kill') await until(() => child().kills.length > 0);
    else if (kind === 'settle') await until(() => !queue.active);
    else if (kind === 'rm_batch') rmSync(queue.jobs.get(current).batch, { recursive: true, force: true });
    else if (kind === 'block_cache') mkdirSync(join(dirname(queue.jobs.get(current).batch), 'cache.json'));
    else throw new Error(`unknown step ${kind}`);
  }
  await until(() => !queue.active);
  queue.dispose();
  await new Promise(resolve => setImmediate(resolve)); // the PassThrough delivers stdin data asynchronously
  return {
    id: item.id, records, clock: clock.calls, ids,
    children: children.map(({ child, executable, args, options }) => ({
      executable, args, cwd: options.cwd, stdio: options.stdio, detached: options.detached, shell: options.shell,
      env: Object.fromEntries(THREADS.map(name => [name, options.env[name]])),
      inherits: Object.entries(process.env).every(([name, value]) => THREADS.includes(name) || options.env[name] === value),
      input: Buffer.concat(child.input).toString('base64'), kills: child.kills,
    })),
  };
}

const cases = [];
for (const item of spec.cases) cases.push(await runCase(item));
writeFileSync(outPath, JSON.stringify({ node: process.version, cases }));
process.exit(0);
