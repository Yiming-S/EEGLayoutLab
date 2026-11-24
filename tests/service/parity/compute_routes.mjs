// Node reference for tests/service/test_compute_routes.py: the job routes of Node's composed service over HTTP.
// Usage: node tests/service/parity/compute_routes.mjs <spec.json> <out.json>
//
// spec: {root, queueDirectory, python, owner, steps, settle_ms}. createLocalComputeService(root, {queueDirectory,
// python}) (the middleware the Node host runs) serves an ephemeral 127.0.0.1 port, its scheduler's session pinned
// to `owner`. Each step is {method, path, body?, raw?, type?, token?, until?, progress?}:
// - `{N}` in a path is the N-th distinct UUID found in the response bodies so far (the receipts, in order);
// - a POST sends `raw` as it is, else JSON.stringify(body), with content-type `type` (default application/json)
//   and the CSRF token of the health answer unless `token` is false;
// - with `until` (statuses) the GET is repeated every 20 ms until body.job.status is one of them (and, with
//   `progress`, body.job.progress > 0), for at most settle_ms.
// Each answer is recorded as {method, path, status, type, body} (the body as text). The token is recorded too.
// The root's worker is the fake of tests/service/compute_support.py; the records it writes stay under the root,
// which must be a synthetic root. The scheduler's state goes to <queueDirectory>, a scratch directory, never
// R/results/web-service of a real installation.
import { createServer } from 'node:http';
import { readFileSync, writeFileSync } from 'node:fs';
import { isAbsolute } from 'node:path';
import { createLocalComputeService } from '../../../webapp/server/local-compute-server.mjs';

const [specPath, outPath] = process.argv.slice(2);
if (!specPath || !outPath) throw new Error('usage: compute_routes.mjs <spec.json> <out.json>');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
if (!isAbsolute(spec.queueDirectory ?? '')) throw new Error('spec.queueDirectory must be absolute');

delete process.env.EEG_COMPUTE_PYTHON;
const service = createLocalComputeService(spec.root, { queueDirectory: spec.queueDirectory, python: spec.python });
service.scheduler.session = () => ({ id: spec.owner, ip: '127.0.0.1', network: 'loopback' });
const server = createServer((req, res) => {
  void service.middleware(req, res, () => { res.statusCode = 404; res.end(); });
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;
const ids = [];
const answers = [];
let token;
try {
  token = (await (await fetch(`${base}/api/local-compute/health`)).json()).token;
  for (const step of spec.steps) {
    const target = step.path.replace(/\{(\d+)\}/g, (_, n) => ids[Number(n)]);
    const headers = { 'accept-encoding': 'identity' };
    let payload;
    if (step.method === 'POST') {
      headers['content-type'] = step.type ?? 'application/json';
      if (step.token !== false) headers['x-eeg-compute-token'] = token;
      payload = 'raw' in step ? step.raw : 'body' in step ? JSON.stringify(step.body) : undefined;
    }
    const deadline = Date.now() + spec.settle_ms;
    let response, body;
    for (;;) {
      response = await fetch(base + target, { method: step.method, headers, body: payload });
      body = await response.text();
      if (!step.until) break;
      const job = JSON.parse(body).job;
      if (step.until.includes(job.status) && (!step.progress || job.progress > 0)) break;
      if (Date.now() > deadline) throw new Error(`${target} did not settle: ${body}`);
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    for (const id of body.match(UUID) ?? []) if (!ids.includes(id)) ids.push(id);
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
