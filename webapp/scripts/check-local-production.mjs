import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer, get } from 'node:http';
import { once } from 'node:events';
import { attachLocalApi } from '../server/start.mjs';
import { computeMiddleware, LocalComputeQueue } from '../server/local-compute-server.mjs';

void test('production host preserves UI routing, local API guards and disposal', async () => {
  const queue = new LocalComputeQueue({ repositoryRoot: '..', getIdentity: () => ({}) });
  const server = createServer((_req, res) => { res.end('ui'); });
  let disposed = false;
  attachLocalApi(server, { middleware: computeMiddleware(queue), dispose() { disposed = true; queue.dispose(); } });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    assert.equal(await (await fetch(base + '/design')).text(), 'ui');
    const healthResponse = await fetch(base + '/api/local-compute/health');
    assert.equal(healthResponse.headers.get('x-eeg-api-version'), '1');
    const health = await healthResponse.json();
    assert.equal(health.local_only, true);
    assert.equal(typeof health.token, 'string');
    assert.equal((await fetch(base + '/api/local-compute/health', { headers: { Origin: 'https://example.org' } })).status, 403);
    assert.equal((await fetch(base + '/api/local-compute/jobs', { method: 'POST' })).status, 403);
    const rejected = await fetch(base + '/api/local-compute/jobs', { method: 'POST' });
    const failure = await rejected.json();
    assert.equal(failure.code, 'request_forbidden');
    assert.equal(typeof failure.error, 'string');
    const foreignHostStatus = await new Promise((resolve, reject) => {
      get(base + '/api/local-compute/health', { headers: { Host: 'example.org' } }, (res) => {
        res.resume();
        resolve(res.statusCode);
      }).on('error', reject);
    });
    assert.equal(foreignHostStatus, 403);
  } finally {
    const closed = once(server, 'close');
    server.close();
    server.closeAllConnections();
    await closed;
  }
  assert.equal(disposed, true);
});
