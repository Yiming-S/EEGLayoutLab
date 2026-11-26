// Node reference for tests/service/test_legacy_import.py: the receipts of webapp/server/community-queue.mjs
// (CommunityQueue), which the legacy import copies from Node's queue directory Q into a workspace.
// Writes only <out.json> and under the directory the spec names (a synthetic Q).
// Usage: node tests/service/parity/legacy_queue.mjs <spec.json> <out.json>
//
// Mode 'build': spec {directory, clock, visitors: {name: {id, network?}}, steps}. Node's own CommunityQueue on
// <directory> with stub adapters for the four kinds (no worker, never polling), its clock pinned to `clock`
// (milliseconds), rate limits and per-visitor caps out of reach. Its queue.json is the synthetic Q's. Steps:
//   ['submit', visitor, kind, request]   queue.submit(kind, request, visitor); recorded as the answer's job id
//   ['tick']                             one dispatch or finalization step
//   ['finish', kind, result]             the running job of the kind completes with `result` (stored, so a later
//                                        submit of the same request is a cache hit)
//   ['fail', kind, message]              the running job of the kind fails
//   ['cancel', visitor, ref]             queue.cancel of the ref-th job id this spec recorded
//   ['clock', ms]                        moves the clock
// then queue.dispose() (which releases worker.lock). The stub's key is sha256(`${kind}:${JSON.stringify(request)}`)
// and its context names a parent record, so receipts carry Node's catalog. Recorded: {ids, records: {visitor name:
// JSON.stringify(queue.records(visitor))}, tasks: the receipts' JSON text}.
//
// Mode 'records': spec {path}: Node's records(visitor) (CommunityQueue.prototype.records on the tasks of the
// queue.json at <path>, read only) for every owner the receipts name, and for one visitor '*' who owns every receipt
// (the workspace's single user). Recorded: {owners: {owner: JSON text}, all: JSON text}.
import { createHash, randomUUID } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { CommunityQueue, RECEIPT_LIMITS } from '../../../webapp/server/community-queue.mjs';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: legacy_queue.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const KINDS = ['local-compute', 'source-reception', 'design-evaluation', 'electrode-editor'];
const sha = text => createHash('sha256').update(text).digest('hex');

function stubs() {
  const adapters = {}, workers = {}, caches = {};
  for (const kind of KINDS) {
    workers[kind] = new Map(); caches[kind] = new Map();
    const keyOf = request => sha(`${kind}:${JSON.stringify(request)}`);
    adapters[kind] = {
      prepare: async request => ({ request, key: keyOf(request),
        ctx: { record: { label: `Layout ${request.record_id?.slice(0, 4) ?? kind}`, region_count: 4,
          request: { mask_codes: [] }, mode: 'whole_scalp_free', layout: { xyzMm: [[1, 2, 3], [4, 5, 6]] } } } }),
      lookup: async prepared =>
        (caches[kind].has(prepared.key) ? { hit: true, job: caches[kind].get(prepared.key) } : { hit: false }),
      start: async request => {
        const job = { id: randomUUID(), key: keyOf(request), request, status: 'running', progress: 0.5, result: null };
        workers[kind].set(job.id, job); return { job };
      },
      get: id => workers[kind].get(id),
      pid: () => undefined,
      busy: () => [...workers[kind].values()].some(job => ['running', 'cancelling'].includes(job.status)),
      cancel: id => { workers[kind].get(id).status = 'cancelling'; },
    };
  }
  const running = kind => [...workers[kind].values()].find(job => ['running', 'cancelling'].includes(job.status));
  return { adapters, workers, caches, running };
}

async function build() {
  const state = { clock: spec.clock };
  const fixture = stubs();
  const queue = new CommunityQueue({ directory: spec.directory, adapters: fixture.adapters, pollMs: 3600000,
    now: () => state.clock, maxPerVisitor: 1e9, maxPerNetwork: 1e9 });
  queue.rate = () => {};
  const visitors = spec.visitors, ids = [];
  try {
    for (const [op, ...args] of spec.steps) {
      if (op === 'submit') {
        const [name, kind, request] = args;
        const answer = await queue.submit(kind, request, visitors[name]);
        ids.push(answer.job?.id ?? null);
      } else if (op === 'tick') await queue.serial(() => queue.tick());
      else if (op === 'finish') {
        const job = fixture.running(args[0]);
        if (job.status === 'cancelling') job.status = 'cancelled';
        else {
          job.status = 'completed'; job.progress = 1; job.message = 'done'; job.result = args[1];
          job.finished_at = new Date(state.clock).toISOString();
          fixture.caches[args[0]].set(job.key, { ...job, cached: true });
        }
      } else if (op === 'fail') { const job = fixture.running(args[0]); job.status = 'failed'; job.message = args[1]; }
      else if (op === 'cancel') await queue.cancel(ids[args[1]], visitors[args[0]]);
      else if (op === 'clock') state.clock = args[0];
      else throw new Error(`unknown step ${op}`);
    }
    const records = {};
    for (const [name, visitor] of Object.entries(visitors)) records[name] = JSON.stringify(queue.records(visitor));
    return { ids, records, tasks: JSON.stringify(queue.tasks) };
  } finally {
    queue.dispose();
  }
}

function records() {
  const data = JSON.parse(readFileSync(spec.path, 'utf8'));
  const owners = {};
  const self = { tasks: data.tasks, receiptLimits: { ...RECEIPT_LIMITS } };
  for (const task of data.tasks) {
    for (const owner of task.owners ?? [])
      owners[owner] ??= JSON.stringify(CommunityQueue.prototype.records.call(self, { id: owner }));
  }
  const all = { tasks: data.tasks.map(task => ({ ...task, owners: ['*'] })), receiptLimits: { ...RECEIPT_LIMITS } };
  return { owners, all: JSON.stringify(CommunityQueue.prototype.records.call(all, { id: '*' })) };
}

const result = spec.mode === 'build' ? await build() : spec.mode === 'records' ? records() : null;
if (!result) throw new Error(`unknown mode ${spec.mode}`);
writeFileSync(outPath, JSON.stringify({ node: process.version, ...result }));
