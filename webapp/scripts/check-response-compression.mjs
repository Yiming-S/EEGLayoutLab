import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer, request } from 'node:http';
import { once } from 'node:events';
import { brotliDecompressSync, gunzipSync } from 'node:zlib';
import { mkdtemp, mkdir, readFile, writeFile, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomBytes } from 'node:crypto';
import { sendJsonPayload, selectJsonEncoding } from '../server/http/compression.mjs';
import { precompressModels } from './precompress-models.mjs';

const values = { potentials: Array.from({ length: 4096 }, (_, i) => Math.sin(i / 17) * 1e-12),
  coordinates: [[-0, 1e-14, -112.31415926535898]], text: '脑电源与通道' };
const body = JSON.stringify(values);

function raw(base, { method = 'GET', headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const req = request(base, { method, headers, agent: false }, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({ status: response.statusCode, headers: response.headers, bytes: Buffer.concat(chunks) }));
      response.on('error', reject);
    });
    req.on('error', reject); req.end();
  });
}

async function host(t, handler) {
  const server = createServer(handler); server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(async () => { const closed = once(server, 'close'); server.close(); server.closeAllConnections(); await closed; });
  return `http://127.0.0.1:${server.address().port}`;
}

void test('response encoding honors quality values, explicit refusals and identity', () => {
  for (const [header, expected] of [
    [undefined, 'identity'], ['', 'identity'], ['br, gzip', 'br'], ['gzip;q=1, br;q=0.5', 'gzip'],
    ['br;q=0,gzip;q=0', 'identity'], ['BR;Q=1, gzip;q=0.5', 'br'], ['gzip;q=0,*;q=1', 'br'],
    ['identity;q=1,gzip;q=0.5', 'identity'], ['br;q=0, gzip;q=0, identity;q=0', null], ['*;q=0', null],
    ['br;q=broken, gzip;q=1', 'gzip'], ['deflate', 'identity'],
  ]) assert.equal(selectJsonEncoding(header), expected, header);
});

void test('compressed JSON preserves every decoded byte, numeric value and API header', async t => {
  const base = await host(t, (_req, res) => sendJsonPayload(res, 200, body, {
    'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
    'X-EEG-API-Version': '1', 'X-Content-Type-Options': 'nosniff', Vary: 'Origin',
    'Content-Length': String(Buffer.byteLength(body)),
  }));
  for (const encoding of ['br', 'gzip', 'identity']) {
    const response = await raw(base, { headers: { 'Accept-Encoding': encoding } });
    assert.equal(response.status, 200);
    assert.equal(response.headers['content-encoding'], encoding === 'identity' ? undefined : encoding);
    assert.equal(response.headers['cache-control'], 'no-store');
    assert.equal(response.headers['x-eeg-api-version'], '1');
    assert.equal(response.headers['x-content-type-options'], 'nosniff');
    assert.equal(response.headers.vary, 'Origin, Accept-Encoding');
    const decoded = encoding === 'br' ? brotliDecompressSync(response.bytes) : encoding === 'gzip' ? gunzipSync(response.bytes) : response.bytes;
    assert.equal(decoded.toString(), body);
    assert.deepEqual(JSON.parse(decoded), JSON.parse(body));
    if (encoding !== 'identity') {
      assert.ok(response.bytes.length < decoded.length);
      assert.equal(response.headers['content-length'], undefined);
    }
    const head = await raw(base, { method: 'HEAD', headers: { 'Accept-Encoding': encoding } });
    assert.equal(head.headers['content-encoding'], response.headers['content-encoding']);
    assert.equal(head.bytes.length, 0);
  }
  assert.equal((await raw(base, { headers: { 'Accept-Encoding': '*;q=0' } })).status, 406);
});

void test('small JSON avoids compression unless identity was refused; empty statuses stay empty', async t => {
  const base = await host(t, (req, res) => sendJsonPayload(res, req.url === '/empty' ? 204 : 200, '{"ok":true}', {}));
  const small = await raw(base, { headers: { 'Accept-Encoding': 'br' } });
  assert.equal(small.headers['content-encoding'], undefined);
  const forced = await raw(base, { headers: { 'Accept-Encoding': 'br, identity;q=0' } });
  assert.equal(forced.headers['content-encoding'], 'br');
  assert.equal(brotliDecompressSync(forced.bytes).toString(), '{"ok":true}');
  const empty = await raw(`${base}/empty`, { headers: { 'Accept-Encoding': 'br' } });
  assert.equal(empty.status, 204); assert.equal(empty.bytes.length, 0);
  assert.equal(empty.headers['content-encoding'], undefined);
});

void test('disconnecting during a compressed response leaves subsequent requests usable', async t => {
  const large = JSON.stringify({ data: randomBytes(1024 * 1024).toString('base64') });
  const base = await host(t, (_req, res) => sendJsonPayload(res, 200, large, {}));
  await new Promise((resolve, reject) => {
    const req = request(base, { headers: { 'Accept-Encoding': 'gzip' }, agent: false }, res => {
      res.once('data', () => { req.destroy(); res.destroy(); resolve(); });
    });
    req.on('error', error => { if (error.code === 'ECONNRESET') resolve(); else reject(error); }); req.end();
  });
  const next = await raw(base, { headers: { 'Accept-Encoding': 'gzip' } });
  assert.equal(gunzipSync(next.bytes).toString(), large);
});

void test('a lookup completing after client cancellation does not write a late response', async t => {
  let announce, releaseLookup, finish;
  const started = new Promise(resolve => { announce = resolve; });
  const lookup = new Promise(resolve => { releaseLookup = resolve; });
  const finished = new Promise(resolve => { finish = resolve; });
  const base = await host(t, async (req, res) => {
    if (req.url !== '/cancel') { sendJsonPayload(res, 200, body, {}); return; }
    announce({ res, closed: once(res, 'close') });
    await lookup;
    let writes = 0, error;
    const writeHead = res.writeHead;
    res.writeHead = function (...args) { writes++; return writeHead.apply(this, args); };
    try { sendJsonPayload(res, 200, body, {}); } catch (caught) { error = caught; }
    finish({ writes, error });
  });
  const req = request(`${base}/cancel`, { headers: { 'Accept-Encoding': 'br' }, agent: false });
  req.on('error', () => {}); req.end();
  const { res, closed } = await started;
  req.destroy(); await closed;
  assert.equal(res.destroyed, true);
  releaseLookup();
  assert.deepEqual(await finished, { writes: 0, error: undefined });
  const next = await raw(base, { headers: { 'Accept-Encoding': 'br' } });
  assert.equal(brotliDecompressSync(next.bytes).toString(), body);
});

void test('a late error after headers are sent closes the response without a second header write', async t => {
  let finish;
  const finished = new Promise(resolve => { finish = resolve; });
  const base = await host(t, (req, res) => {
    if (req.url !== '/partial') { sendJsonPayload(res, 200, body, {}); return; }
    res.writeHead(200); res.write('partial');
    let error;
    try { sendJsonPayload(res, 500, '{"error":"late failure"}', {}); } catch (caught) { error = caught; }
    finish({ error, destroyed: res.destroyed });
    res.destroy();
  });
  await assert.rejects(raw(`${base}/partial`));
  assert.deepEqual(await finished, { error: undefined, destroyed: true });
  const next = await raw(base, { headers: { 'Accept-Encoding': 'gzip' } });
  assert.equal(gunzipSync(next.bytes).toString(), body);
});

void test('build variants preserve binary models and replace stale sidecars on rebuild', async t => {
  const root = await mkdtemp(join(tmpdir(), 'eeg-model-compression-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const directory = join(root, 'ernie'); await mkdir(directory);
  const path = join(directory, 'model.bin'), bytes = Buffer.alloc(32768);
  for (let i = 0; i < bytes.length; i++) bytes[i] = i % 251;
  await writeFile(path, bytes); await writeFile(join(directory, 'index.json'), '{"version":1}');
  const outputs = await precompressModels(root);
  assert.equal(outputs.length, 2); assert.deepEqual(await readFile(path), bytes);
  assert.deepEqual(brotliDecompressSync(await readFile(`${path}.br`)), bytes);
  assert.deepEqual(gunzipSync(await readFile(`${path}.gz`)), bytes);
  const changed = Buffer.from(bytes); changed[17] ^= 255;
  await writeFile(path, changed); await precompressModels(root);
  assert.deepEqual(brotliDecompressSync(await readFile(`${path}.br`)), changed);
  assert.deepEqual(gunzipSync(await readFile(`${path}.gz`)), changed);
  assert.equal(await readFile(join(directory, 'index.json'), 'utf8'), '{"version":1}');
  await symlink(path, join(directory, 'alias.bin'));
  await assert.rejects(() => precompressModels(root), /symlink/);
});
