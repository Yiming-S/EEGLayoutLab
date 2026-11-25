// Node reference for tests/service/test_compute_routes.py: the job routes of Node's composed service over HTTP.
// Usage: node tests/service/parity/compute_routes.mjs <spec.json> <out.json>
//
// spec: {root, queueDirectory, python, owner, steps, settle_ms}. createLocalComputeService(root, {queueDirectory,
// python}) (the middleware the Node host runs) serves an ephemeral 127.0.0.1 port, its scheduler's session pinned
// to `owner`. The public service's per-visitor and per-network admission limits, which the Python service does not
// have, are lifted: the submission rate, the pending tasks per browser and network, and the annotation window. The
// global queue bound and the electrode-name bounds per receipt stay. Each step is {method, path, body?, raw?, type?,
// token?, chunks?, until?, progress?}:
// - `{N}` in a path is the N-th distinct UUID string found in the response bodies so far (the receipts), `{aN}`
//   the N-th distinct "annotation_id" value and `{kN}` the N-th distinct "key" value;
// - a POST sends `raw` as it is, else JSON.stringify(body), with content-type `type` (default application/json)
//   and the CSRF token of the health answer unless `token` is false; with `chunks` its UTF-8 bytes go one per
//   chunk of a streamed body;
// - with `until` (statuses) the GET is repeated every 20 ms until body.job.status is one of them (and, with
//   `progress`, body.job.progress > 0), for at most settle_ms;
// - a step {method: 'FILE', path, text} sends nothing: it writes `text` (UTF-8, its `{N}`, `{aN}` and `{kN}`
//   replaced too) to `path` below the root, or removes that file when `text` is null, and is recorded as
//   {method: 'FILE', path, status: 0, type: null, body: ''}.
// Each answer is recorded as {method, path, status, type, body} (the body as text). The token is recorded too.
// The root's workers are the fakes of tests/service/compute_support.py (the radius search's, and on an editor root
// the coordinate evaluation's and the electrode editor's, on a reception root also both reception workers, all
// kinds sharing the one queue and slot); the records they write stay under the root, which must be a synthetic
// root. The scheduler's state goes to
// <queueDirectory>, a scratch directory, never R/results/web-service of a real installation.
import { createServer } from 'node:http';
import { readFileSync, rmSync, writeFileSync } from 'node:fs';
import { isAbsolute, join } from 'node:path';
import { createLocalComputeService } from '../../../webapp/server/local-compute-server.mjs';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: compute_routes.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
if (!isAbsolute(spec.queueDirectory ?? '')) throw new Error('spec.queueDirectory must be absolute');

delete process.env.EEG_COMPUTE_PYTHON;
const service = createLocalComputeService(spec.root, { queueDirectory: spec.queueDirectory, python: spec.python });
service.scheduler.session = () => ({ id: spec.owner, ip: '127.0.0.1', network: 'loopback' });
service.scheduler.rate = () => {};
service.scheduler.maxPerVisitor = service.scheduler.maxPerNetwork = Number.MAX_SAFE_INTEGER;
service.scheduler.annotationWindow.take = () => {};
const server = createServer((req, res) => {
  void service.middleware(req, res, () => { res.statusCode = 404; res.end(); });
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;
// Receipts are UUIDs that are whole JSON strings, not ones inside a path such as the interpreter's.
const UUID = /"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"/g;
const ANNOTATION = /"annotation_id":"([a-f0-9]{64})"/g, KEY = /"key":"([a-f0-9]{64})"/g;
const seen = { '': [], a: [], k: [] };
const remember = (kind, values) => {
  for (const value of values) if (!seen[kind].includes(value)) seen[kind].push(value);
};
const answers = [];
let token;
try {
  token = (await (await fetch(`${base}/api/local-compute/health`)).json()).token;
  const substitute = text => text.replace(/\{([ak]?)(\d+)\}/g, (_, kind, n) => seen[kind][Number(n)]);
  for (const step of spec.steps) {
    const target = substitute(step.path);
    if (step.method === 'FILE') {
      const file = join(spec.root, target);
      if (step.text === null) rmSync(file); else writeFileSync(file, substitute(step.text));
      answers.push({ method: 'FILE', path: step.path, status: 0, type: null, body: '' });
      continue;
    }
    const headers = { 'accept-encoding': 'identity' };
    let payload;
    if (step.method === 'POST') {
      headers['content-type'] = step.type ?? 'application/json';
      if (step.token !== false) headers['x-eeg-compute-token'] = token;
      payload = 'raw' in step ? step.raw : 'body' in step ? JSON.stringify(step.body) : undefined;
    }
    const bodyOptions = () => {
      if (!step.chunks) return { body: payload };
      const bytes = Buffer.from(payload ?? '', 'utf8');
      let at = 0;
      return { duplex: 'half', body: new ReadableStream({ pull(controller) {
        if (at < bytes.length) controller.enqueue(new Uint8Array(bytes.subarray(at, ++at))); else controller.close();
      } }) };
    };
    const deadline = Date.now() + spec.settle_ms;
    let response, body;
    for (;;) {
      response = await fetch(base + target, { method: step.method, headers, ...bodyOptions() });
      body = await response.text();
      if (!step.until) break;
      const job = JSON.parse(body).job;
      if (!job) throw new Error(`${target} answered ${response.status}: ${body}`);
      if (step.until.includes(job.status) && (!step.progress || job.progress > 0)) break;
      if (Date.now() > deadline) throw new Error(`${target} did not settle: ${body}`);
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    remember('', [...body.matchAll(UUID)].map(match => match[1]));
    remember('a', [...body.matchAll(ANNOTATION)].map(match => match[1]));
    remember('k', [...body.matchAll(KEY)].map(match => match[1]));
    answers.push({ method: step.method, path: step.path, status: response.status,
      type: response.headers.get('content-type'), body });
  }
} finally {
  server.close(); server.closeAllConnections();
  await service.dispose();
}
writeFileSync(outPath, JSON.stringify({ node: process.version, token, answers }));
// The scheduler's timers are unref'd, but other modules may hold some; the result is written.
process.exit(0);
