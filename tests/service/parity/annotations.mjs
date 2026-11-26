// Node reference for tests/service/test_annotations.py and the envelope ports of tests/service/test_key_parity.py:
// Node's designSubmission, ElectrodeAnnotations (identity, create, read, list) and the design-evaluation adapter.
// Writes annotation files only under spec.root and <out.json>; reads the roots it is given.
// Usage: node tests/service/parity/annotations.mjs <spec.json> <out.json>
//
// spec: {root?, queueDirectory?, submissions?, identities?, reads?, lists?, prepares?}
// - submissions: [{id, text}]: designSubmission(JSON.parse(text)), recorded as the JSON text of its value.
// - identities: [{id, owner, prepared, create?}], with `root` a scratch root and `prepared` a JSON text (so that
//   numbers JSON.stringify cannot write, such as 1e400, arrive as Node parses them): new ElectrodeAnnotations(root)
//   .identity(prepared, owner) as JSON text and, with `create`, create(prepared, owner) as JSON text plus the
//   base64 bytes of results/v2/design_evaluation_jobs/electrode_annotations/<id>.json under `root` after it. One
//   store for all cases, so a repeated identity reads the file written before.
// - reads: [{id, root, annotation, owner, record}]: new ElectrodeAnnotations(root).read(annotation, owner, record).
// - lists: [{id, root, owner}]: new ElectrodeAnnotations(root).list(owner), each value as JSON text.
// - prepares: [{id, root, python?, raw}]: the production design-evaluation adapter (communityAdapters over a
//   LocalComputeQueue({repositoryRoot: root, python, queueDirectory}) with its DesignEvaluationService, as
//   createLocalComputeService wires it, EEG_COMPUTE_PYTHON deleted): prepare(raw) as JSON texts of the request,
//   the names, the source metadata and workerInput({request}), plus the key.
// A failure is {ok: false, name, message, status, safe (annotationSafe), code}. LocalComputeQueue only resolves
// queueDirectory, which is never created.
import { readFileSync, writeFileSync } from 'node:fs';
import { isAbsolute, join } from 'node:path';
import { ElectrodeAnnotations, designSubmission } from '../../../webapp/server/annotations/electrode-names.mjs';
import { communityAdapters } from '../../../webapp/server/community-adapters.mjs';
import { DesignEvaluationService } from '../../../webapp/server/design-evaluation-server.mjs';
import { LocalComputeQueue } from '../../../webapp/server/local-compute-server.mjs';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: annotations.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
for (const name of ['root', 'queueDirectory'])
  if (spec[name] !== undefined && !isAbsolute(spec[name])) throw new Error(`spec.${name} must be absolute`);

const failure = error => ({ ok: false, name: error?.name ?? null, message: String(error?.message ?? error),
  status: error?.status ?? null, safe: Boolean(error?.annotationSafe), code: error?.code ?? null });
async function attempt(run) {
  try { return { ok: true, ...(await run()) }; } catch (error) { return failure(error); }
}
const NODE_DIRECTORY = 'results/v2/design_evaluation_jobs/electrode_annotations';
const out = { node: process.version, submissions: {}, identities: {}, reads: {}, lists: {}, prepares: {} };

for (const c of spec.submissions ?? [])
  out.submissions[c.id] = await attempt(() => ({ value: JSON.stringify(designSubmission(JSON.parse(c.text))) }));

if (spec.identities?.length) {
  const store = new ElectrodeAnnotations(spec.root);
  for (const c of spec.identities) {
    const prepared = JSON.parse(c.prepared);
    const entry = { identity: await attempt(() => ({ value: JSON.stringify(store.identity(prepared, c.owner)) })) };
    if (c.create) {
      entry.create = await attempt(() => {
        const value = store.create(prepared, c.owner);
        const file = readFileSync(join(store.root, NODE_DIRECTORY, `${value.id}.json`));
        return { value: JSON.stringify(value), file: file.toString('base64') };
      });
    }
    out.identities[c.id] = entry;
  }
}

for (const c of spec.reads ?? [])
  out.reads[c.id] = await attempt(() => ({ value: JSON.stringify(new ElectrodeAnnotations(c.root).read(c.annotation, c.owner, c.record)) }));
for (const c of spec.lists ?? [])
  out.lists[c.id] = await attempt(() => ({ values: new ElectrodeAnnotations(c.root).list(c.owner).map(value => JSON.stringify(value)) }));

if (spec.prepares?.length) {
  if (!isAbsolute(spec.queueDirectory ?? '')) throw new Error('spec.queueDirectory must be absolute for prepares');
  delete process.env.EEG_COMPUTE_PYTHON;
  const adapters = new Map();
  const adapterFor = c => {
    const id = JSON.stringify([c.root, c.python ?? null]);
    if (!adapters.has(id)) {
      const queue = new LocalComputeQueue({ repositoryRoot: c.root, python: c.python, queueDirectory: spec.queueDirectory });
      queue.designTests = new DesignEvaluationService(queue);
      adapters.set(id, { queue, adapter: communityAdapters(queue)['design-evaluation'] });
    }
    return adapters.get(id);
  };
  for (const c of spec.prepares) {
    out.prepares[c.id] = await attempt(async () => {
      const { queue, adapter } = adapterFor(c);
      const prepared = await adapter.prepare(c.raw);
      return {
        keys: Object.keys(prepared), request: JSON.stringify(prepared.request), key: prepared.key,
        identity: JSON.stringify(prepared.ctx.identity),
        electrode_names: prepared.electrode_names === undefined ? null : JSON.stringify(prepared.electrode_names),
        source_metadata: prepared.source_metadata === undefined ? null : JSON.stringify(prepared.source_metadata),
        worker_input: JSON.stringify(queue.designTests.workerInput({ request: prepared.request })),
      };
    });
  }
}

writeFileSync(outPath, JSON.stringify(out));
// The services hold no timers, but the imported modules may; the result is written.
process.exit(0);
