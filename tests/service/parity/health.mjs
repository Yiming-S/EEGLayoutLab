// Node reference for tests/service/test_health.py: the health answer of each task kind from Node's real service.
// Usage: node tests/service/parity/health.mjs <root> <queueDirectory> <out.json>
//
// Builds createLocalComputeService(root, {queueDirectory}) (the composed middleware the Node host runs), serves it
// on an ephemeral 127.0.0.1 port and sends GET /api/<kind>/health from a loopback client for the four kinds.
// The scheduler writes its state into <queueDirectory>, which must be a scratch directory: never
// R/results/web-service of a real installation. The root is only read.
import { createServer } from 'node:http';
import { writeFileSync } from 'node:fs';
import { isAbsolute } from 'node:path';
import { createLocalComputeService } from '../../../webapp/server/local-compute-server.mjs';

const [root, queueDirectory, outPath] = process.argv.slice(2);
if (!root || !queueDirectory || !outPath) throw new Error('usage: health.mjs <root> <queueDirectory> <out.json>');
if (!isAbsolute(queueDirectory)) throw new Error('the queue directory must be absolute');

const KINDS = ['local-compute', 'design-evaluation', 'source-reception', 'electrode-editor'];
const HEADERS = ['content-type', 'cache-control', 'x-content-type-options', 'cross-origin-resource-policy',
  'x-eeg-api-version'];
const service = createLocalComputeService(root, { queueDirectory });
const server = createServer((req, res) => {
  void service.middleware(req, res, () => { res.statusCode = 404; res.end(); });
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const kinds = {};
try {
  for (const kind of KINDS) {
    const response = await fetch(`${base}/api/${kind}/health`, { headers: { 'accept-encoding': 'identity' } });
    const headers = Object.fromEntries(HEADERS.map(name => [name, response.headers.get(name)]));
    kinds[kind] = { status: response.status, headers, body: await response.text() };
  }
} finally {
  server.close(); server.closeAllConnections();
  await service.dispose();
}
writeFileSync(outPath, JSON.stringify({ node: process.version, kinds }));
// The scheduler's timers are unref'd, but other modules may hold some; the result is written.
process.exit(0);
