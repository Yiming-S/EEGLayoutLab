// Node reference for tests/service/test_queue.py: webapp/server/community-queue.mjs (CommunityQueue) with the stub
// adapters of check-community-queue.mjs:11-38, driven by scripted scenarios. Writes only its own temporary queue
// directories (removed at the end) and <out.json>.
// Usage: node tests/service/parity/queue_views.mjs <spec.json> <out.json>
//
// spec: {scenarios: [{id, clock, options?: {maxQueued, receiptLimits: {computed, cached}}, steps: [...]}]}.
// One visitor without an address (so no networks); rate limits and per-visitor caps are switched off, and
// cache-hit retention has no per-network share, as in the local queue. `clock` pins Date.now for the queue
// (`now` option). Steps, each recorded as [op, value] or [op, {error: {status, message}}]:
//   ['submit', kind, n, lookupOnly?]  submit {n} (or the raw body given as n when it is not a number)
//   ['tick']                          one dispatch/finalization step (recorded as null)
//   ['finish', kind]                  the fixture's finish(kind): running -> completed (cached), cancelling -> cancelled
//   ['fail', kind, message]           the running job of the kind fails with that message
//   ['progress', kind, progress, stage, message]  the running job reports progress
//   ['cancel', ref, kind?]            cancel the ref-th job id this scenario returned
//   ['view', ref, result?]            view(task, result) of that receipt
//   ['own', ref]                      the receipt's own members (id, sequence, kind, key, status, created_at,
//                                     progress, cached, catalog, finished_at, message)
//   ['stats'], ['active', kind], ['status']  stats(visitor), active(kind, visitor), maintenanceStatus()
//   ['cache', kind, n, status, result, finished_at?]  store a result for the current revision's key
//   ['change']                        the scientific revision becomes v2 (keys change)
//   ['clock', ms]                     move the pinned clock
//   ['restart', {keep?, cacheOnly?}]  dispose, then a new queue on the same directory (new adapters unless keep;
//                                     cacheOnly is initialMaintenance; a later restart without it resumes)
// Each scenario's records are one JSON.stringify text, so member order is compared too.
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { CommunityQueue } from '../../../webapp/server/community-queue.mjs';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: queue_views.mjs <spec.json> <out.json>');
const { scenarios } = JSON.parse(readFileSync(specPath, 'utf8'));
const KINDS = ['local-compute', 'source-reception', 'design-evaluation', 'electrode-editor'];
const visitor = { id: 'local' };

function stubs(state) {
  const adapters = {}, workers = {}, caches = {};
  for (const kind of KINDS) {
    workers[kind] = new Map(); caches[kind] = new Map();
    adapters[kind] = {
      prepare: async r => { if (!r || !Number.isInteger(r.n)) throw new Error('invalid'); return { request: r, key: state.revision + '-' + r.n }; },
      lookup: async p => caches[kind].has(p.key) ? { hit: true, job: caches[kind].get(p.key) } : { hit: false },
      start: async r => {
        state.starts.push(kind + ':' + r.n);
        const j = { id: randomUUID(), key: state.revision + '-' + r.n, request: r, status: 'running', result: null };
        workers[kind].set(j.id, j); return { job: j };
      },
      get: id => workers[kind].get(id),
      pid: () => undefined,
      busy: () => [...workers[kind].values()].some(j => ['running', 'cancelling'].includes(j.status)),
      cancel: id => { workers[kind].get(id).status = 'cancelling'; },
    };
  }
  const running = kind => [...workers[kind].values()].find(j => ['running', 'cancelling'].includes(j.status));
  const finish = kind => {
    const j = running(kind);
    j.status = j.status === 'cancelling' ? 'cancelled' : 'completed'; j.result = { scientific: true };
    if (j.status === 'completed') caches[kind].set(j.key, { ...j, cached: true });
  };
  return { adapters, workers, caches, running, finish };
}

const pick = task => {
  const out = {};
  for (const name of ['id', 'sequence', 'kind', 'key', 'status', 'created_at', 'progress', 'cached', 'catalog', 'finished_at', 'message']) {
    if (task[name] !== undefined) out[name] = task[name];
  }
  return out;
};

async function run(scenario) {
  const directory = mkdtempSync(join(tmpdir(), 'eeg-queue-views-'));
  const state = { revision: 'v1', starts: [], clock: scenario.clock };
  const options = scenario.options ?? {};
  const limits = options.receiptLimits ?? {};
  let fixture = stubs(state), queue;
  const open = cacheOnly => {
    queue = new CommunityQueue({ directory, adapters: fixture.adapters, pollMs: 3600000, now: () => state.clock,
      maxQueued: options.maxQueued ?? 50, maxPerVisitor: 1e9, maxPerNetwork: 1e9, initialMaintenance: Boolean(cacheOnly),
      receiptLimits: { computed: limits.computed ?? 1000, cached: limits.cached ?? 300, cachedPerNetwork: 1e9 } });
    queue.rate = () => {};
    if (!cacheOnly && queue.maintenance) queue.setMaintenance(false);
  };
  open(options.cacheOnly);
  const ids = [], records = [];
  try {
    for (const step of scenario.steps) {
      const [op, ...args] = step;
      let value = null;
      try {
        if (op === 'submit') {
          const [kind, n, lookupOnly] = args;
          value = await queue.submit(kind, typeof n === 'number' ? { n } : n, visitor, Boolean(lookupOnly));
          if (value.job?.id && !ids.includes(value.job.id)) ids.push(value.job.id);
        } else if (op === 'tick') await queue.tick();
        else if (op === 'finish') fixture.finish(args[0]);
        else if (op === 'fail') { const j = fixture.running(args[0]); j.status = 'failed'; j.message = args[1]; }
        else if (op === 'progress') { const j = fixture.running(args[0]); j.progress = args[1]; j.stage = args[2]; j.message = args[3]; }
        else if (op === 'cancel') value = await queue.cancel(ids[args[0]], visitor, args[1]);
        else if (op === 'view') value = await queue.view(queue.own(ids[args[0]], visitor), args[1] ?? true, visitor);
        else if (op === 'own') value = pick(queue.own(ids[args[0]], visitor));
        else if (op === 'stats') value = await queue.stats(visitor);
        else if (op === 'active') value = await queue.active(args[0], visitor);
        else if (op === 'status') value = queue.maintenanceStatus();
        else if (op === 'cache') {
          const [kind, n, status, result, finished] = args;
          const key = state.revision + '-' + n;
          fixture.caches[kind].set(key, { key, status, result, cached: true, ...(finished ? { finished_at: finished } : {}) });
        } else if (op === 'change') state.revision = 'v2';
        else if (op === 'clock') state.clock = args[0];
        else if (op === 'restart') {
          const { keep, cacheOnly } = args[0] ?? {};
          queue.dispose();
          if (!keep) { fixture = stubs(state); state.revision = 'v1'; }
          open(cacheOnly);
        } else throw new Error(`unknown step ${op}`);
        records.push([op, value === undefined ? null : value]);
      } catch (error) {
        if (error.message?.startsWith('unknown step')) throw error;
        records.push([op, { error: { status: error.status ?? null, message: error.message } }]);
      }
    }
    records.push(['starts', state.starts]);
  } finally {
    queue.dispose();
    rmSync(directory, { recursive: true, force: true });
  }
  return { id: scenario.id, records: JSON.stringify(records) };
}

const out = [];
for (const scenario of scenarios) out.push(await run(scenario));
writeFileSync(outPath, JSON.stringify({ scenarios: out }));
