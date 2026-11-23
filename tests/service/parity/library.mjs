// Node reference for tests/service/test_library_parity.py (the read-only library, its bundles and catalogs, and their
// HTTP routes) and the radius identities of tests/service/test_key_parity.py. Reads the roots it is given; writes
// <out.json> and the composed service's state under spec.serviceDirectory.
// Usage: node tests/service/parity/library.mjs <spec.json> <out.json>
//
// spec: {queueDirectory, serviceDirectory?, owner?, identities?: [...], roots?: [...]}
// - identities: [{id, root, python?, env?, request}]. Per case EEG_COMPUTE_PYTHON is set from `env` (or deleted)
//   and a fresh LocalComputeQueue({repositoryRoot: root, python, queueDirectory}) gives identityFor(request): the
//   configured root and interpreter, the identity text and the key, or the error.
// - roots: [{id, root, python?, requests?, ids?, listed?, bundles?, catalogs?, http?}]. EEG_COMPUTE_PYTHON is
//   deleted and one LocalComputeQueue per root, with Node's ElectrodeEditorService and DesignEvaluationService,
//   gives identityFor of each request, library.list(), library.get(id) of `ids` and of every listed id (unless
//   `listed` is false), the bundle of each id in `bundles` (every listed id when true) as the library route
//   builds it (experimentBundle with queue.python), and with `catalogs` editor.records(), editor.parents(),
//   receptionLayouts() and design.heads().
//   A bundle is recorded with original_record replaced by the SHA-256 of that member's text (computed once per
//   source file: the original report is 33 MB on a real installation), plus that digest.
// - http: request targets. Node's composed service (createLocalComputeService, the middleware the Node host runs,
//   with `python`) serves them on an ephemeral 127.0.0.1 port, its scheduler's session pinned to `owner` so that
//   one owner's electrode-name annotations are listed and read; each target is fetched with GET and its status,
//   content type and body are recorded (a bundle over 4 MiB by the SHA-256 and length of the body, plus the packed
//   bundle).
// LocalComputeQueue only resolves queueDirectory, which is never created; the composed service writes its state
// (visitors, visibility, logs) under <serviceDirectory>/<n>, which must be a scratch directory, never
// R/results/web-service of a real installation.
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { readFileSync, writeFileSync } from 'node:fs';
import { isAbsolute, join } from 'node:path';
import { LocalComputeQueue, createLocalComputeService } from '../../../webapp/server/local-compute-server.mjs';
import { ElectrodeEditorService } from '../../../webapp/server/electrode-editor-server.mjs';
import { DesignEvaluationService } from '../../../webapp/server/design-evaluation-server.mjs';
import { receptionLayouts } from '../../../webapp/server/reception-v2-support.mjs';
import { experimentBundle } from '../../../webapp/server/experiment-bundle.mjs';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: library.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
if (!isAbsolute(spec.queueDirectory ?? '')) throw new Error('spec.queueDirectory must be absolute');

const MAX_BODY = 4 * 1024 * 1024;
const sha = text => createHash('sha256').update(text).digest('hex');
const failure = error => ({ ok: false, code: error?.code ?? null, name: error?.name ?? null,
  message: String(error?.message ?? error), status: error?.status ?? null });
async function attempt(run) {
  try { return { ok: true, value: await run() }; } catch (error) { return failure(error); }
}
const setPython = env => {
  if (env && 'EEG_COMPUTE_PYTHON' in env) process.env.EEG_COMPUTE_PYTHON = env.EEG_COMPUTE_PYTHON;
  else delete process.env.EEG_COMPUTE_PYTHON;
};
const originals = new Map();
function packed(bundle) {
  const key = bundle?.source?.sha256;
  if (!originals.has(key)) originals.set(key, sha(JSON.stringify(bundle.original_record)));
  const original = originals.get(key);
  return { text: JSON.stringify({ ...bundle, original_record: original }), original };
}

const out = { node: process.version, platform: process.platform, identities: [], roots: {} };

for (const c of spec.identities ?? []) {
  let config;
  try {
    setPython(c.env);
    const queue = new LocalComputeQueue({ repositoryRoot: c.root, python: c.python, queueDirectory: spec.queueDirectory });
    config = { repositoryRoot: queue.root, python: queue.python };
    const { identity, key } = queue.identityFor(c.request);
    out.identities.push({ id: c.id, ok: true, config, identity: JSON.stringify(identity), key });
    queue.dispose();
  } catch (error) {
    out.identities.push({ id: c.id, ...failure(error), ...(config ? { config } : {}) });
  }
}

async function library(item) {
  setPython(null);
  const queue = new LocalComputeQueue({ repositoryRoot: item.root, python: item.python, queueDirectory: spec.queueDirectory });
  const editor = new ElectrodeEditorService(queue), design = new DesignEvaluationService(queue);
  const entry = { root: queue.root, python: queue.python, identity: {}, get: {}, bundle: {} };
  for (const [name, request] of Object.entries(item.requests ?? {})) {
    entry.identity[name] = await attempt(() => {
      const { identity, key } = queue.identityFor(request);
      return { identity: JSON.stringify(identity), key };
    });
  }
  entry.list = await attempt(async () => JSON.stringify(await queue.library.list()));
  const listed = entry.list.ok ? JSON.parse(entry.list.value).records.map(row => row.id) : [];
  for (const id of [...new Set([...(item.ids ?? []), ...(item.listed === false ? [] : listed)])])
    entry.get[id] = await attempt(async () => JSON.stringify(await queue.library.get(id)));
  for (const id of item.bundles === true ? listed : item.bundles ?? []) {
    entry.bundle[id] = await attempt(async () => {
      const record = await queue.library.get(id);
      return record ? packed(await experimentBundle(queue.root, record, { python: queue.python })) : null;
    });
  }
  if (item.catalogs) {
    entry.records = await attempt(async () => JSON.stringify(await editor.records()));
    entry.parents = await attempt(async () => JSON.stringify(await editor.parents()));
    entry.layouts = await attempt(async () => JSON.stringify(await receptionLayouts(queue)));
    entry.heads = await attempt(async () => JSON.stringify(await design.heads()));
  }
  editor.dispose(); design.dispose(); queue.dispose();
  return entry;
}

let services = 0;
async function http(item) {
  if (!isAbsolute(spec.serviceDirectory ?? '')) throw new Error('spec.serviceDirectory must be absolute');
  setPython(null);
  const service = createLocalComputeService(item.root, { queueDirectory: join(spec.serviceDirectory, String(services++)),
    python: item.python });
  const owner = spec.owner;
  service.scheduler.session = () => ({ id: owner, ip: '127.0.0.1', network: 'loopback' });
  const server = createServer((req, res) => {
    void service.middleware(req, res, () => { res.statusCode = 404; res.end(); });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const answers = [];
  try {
    for (const target of item.http) {
      const response = await fetch(base + target, { headers: { 'accept-encoding': 'identity' } });
      const body = await response.text();
      const answer = { target, status: response.status, type: response.headers.get('content-type') };
      const value = Buffer.byteLength(body) > MAX_BODY ? JSON.parse(body) : null;
      if (value && typeof value === 'object' && 'original_record' in value) {
        answer.sha256 = sha(body);
        answer.length = Buffer.byteLength(body);
        answer.packed = packed(value);
      } else answer.body = body;
      answers.push(answer);
    }
  } finally {
    server.close(); server.closeAllConnections();
    await service.dispose();
  }
  return answers;
}

for (const item of spec.roots ?? []) {
  const entry = await library(item);
  if (item.http) entry.http = await http(item);
  out.roots[item.id] = entry;
}
writeFileSync(outPath, JSON.stringify(out));
// The services hold timers (the scheduler's are unref'd, other modules may hold some); the result is written.
process.exit(0);
