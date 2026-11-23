// Node reference for tests/service/test_key_parity.py: the design-evaluation identity, admission and request key
// that Node's own wiring gives for each case. Reads the roots it is given; writes only <out.json>.
// Usage: node tests/service/parity/identity.mjs <spec.json> <out.json>
//
// spec: {queueDirectory, reuse?, cases: [{id, root, python?, env?, direct?, request}]}
// - Each case builds `new LocalComputeQueue({repositoryRoot: root, python, queueDirectory})` and
//   `new DesignEvaluationService(queue)` after setting process.env.EEG_COMPUTE_PYTHON from `env` (or deleting it),
//   so it exercises the real root, interpreter and scientificContext wiring. A fresh queue per case keeps the
//   InputIntegrity memos apart; with `reuse`, cases with the same root, python, env and direct share one (the real
//   installation, where hashing every input again per case is slow).
// - `direct: {python}` calls scientificContext({root: queue.root, python, inputs}) with that interpreter string
//   instead of service.context, to reach the exact-string rule for the managed-runtime rows.
// - The queue directory is only resolved by the constructors; nothing is written there or under the roots.
import { readFileSync, writeFileSync } from 'node:fs';
import { LocalComputeQueue } from '../../../webapp/server/local-compute-server.mjs';
import { DesignEvaluationService } from '../../../webapp/server/design-evaluation-server.mjs';
import { InputIntegrity } from '../../../webapp/server/local-input-integrity.mjs';
import { scientificContext } from '../../../webapp/server/runtime/scientific-context.mjs';
import {
  DESIGN_WORKFLOW, EDITOR_WORKFLOW, NATIVE_RUNTIME_RELATIVE, RECEPTION_V2_WORKFLOW, RECEPTION_WORKFLOW,
  TABLE_RUNTIME_RELATIVE, WORKFLOW_BASE,
} from '../../../webapp/server/project-paths.mjs';
import { DATA_PRIOR_FILES } from '../../../webapp/contracts/scientific-options.mjs';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: identity.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
if (typeof spec.queueDirectory !== 'string' || !spec.queueDirectory.startsWith('/')) throw new Error('spec.queueDirectory must be absolute');

const services = new Map();
const serviceFor = (c) => {
  const id = JSON.stringify([c.root, c.python ?? null, c.env ?? null]);
  if (spec.reuse && services.has(id)) return services.get(id);
  if (c.env && 'EEG_COMPUTE_PYTHON' in c.env) process.env.EEG_COMPUTE_PYTHON = c.env.EEG_COMPUTE_PYTHON;
  else delete process.env.EEG_COMPUTE_PYTHON;
  const queue = new LocalComputeQueue({ repositoryRoot: c.root, python: c.python, queueDirectory: spec.queueDirectory });
  const service = new DesignEvaluationService(queue);
  const entry = { queue, service, inputs: new InputIntegrity(queue.root) };
  if (spec.reuse) services.set(id, entry);
  return entry;
};

const cases = [];
for (const c of spec.cases) {
  let config;
  try {
    const { queue, service, inputs } = serviceFor(c);
    config = { repositoryRoot: queue.root, python: queue.python, nativePython: service.python };
    const ctx = c.direct
      ? await scientificContext({ root: queue.root, python: c.direct.python, inputs }, c.request)
      : await service.context(c.request);
    cases.push({ id: c.id, ok: true, config, identity: JSON.stringify(ctx.identity), admission: JSON.stringify(ctx.admission), key: ctx.key });
  } catch (error) {
    cases.push({ id: c.id, ok: false, ...(config ? { config } : {}), name: error?.name ?? null, message: String(error?.message ?? error), code: error?.code ?? null });
  }
}

const constants = {
  NATIVE_RUNTIME_RELATIVE, TABLE_RUNTIME_RELATIVE, WORKFLOW_BASE, DESIGN_WORKFLOW, RECEPTION_WORKFLOW,
  RECEPTION_V2_WORKFLOW, EDITOR_WORKFLOW, DATA_PRIOR_FILES,
};
writeFileSync(outPath, JSON.stringify({ node: process.version, platform: process.platform, constants, cases }));
// The services hold no timers, but the imported modules may; the result is written.
process.exit(0);
