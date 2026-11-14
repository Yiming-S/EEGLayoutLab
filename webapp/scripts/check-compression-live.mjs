/** Raw HTTP acceptance: lossless response compression against an isolated host. */
import assert from 'node:assert/strict';
import { request as httpRequest } from 'node:http';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { brotliDecompressSync, gunzipSync } from 'node:zlib';
import { isDeepStrictEqual } from 'node:util';
import { dirname, isAbsolute, join, relative, resolve } from 'node:path';
import { performance } from 'node:perf_hooks';

const project = resolve(import.meta.dirname, '../..');
assert.ok(process.env.EEG_TEST_URL, 'Set EEG_TEST_URL to the isolated verification server.');
const base = new URL(process.env.EEG_TEST_URL);
assert.ok(base.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(base.hostname) && base.port && base.port !== '3000', 'Use an explicit isolated loopback port.');
const fixturePath = process.env.EEG_SIGNAL_FIXTURE || join(project, 'artifacts/performance-optimizations/2026-11-13/bank-signal-result.json');
const output = process.env.EEG_COMPRESSION_REPORT || join(project, 'artifacts/performance-optimizations/2026-11-13/stage3-http-compression.json');
assert.ok(isAbsolute(output) && relative(project, output).startsWith('artifacts/'), 'Keep the report inside this project artifacts directory.');
await mkdir(dirname(output), { recursive: true });
const fixture = JSON.parse(await readFile(fixturePath, 'utf8'));
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const checks = [], requests = [], cookies = new Map();
const responseHeaderNames = ['content-type', 'content-encoding', 'content-length', 'content-range', 'vary', 'cache-control', 'x-eeg-api-version', 'etag', 'accept-ranges'];
let failure;

function request(path, { method = 'GET', headers = {}, body } = {}) {
  assert.ok(!/\/jobs(?:\/|$)/.test(path), 'This acceptance script must not request or submit computation jobs.');
  const payload = body === undefined ? undefined : Buffer.from(JSON.stringify(body));
  const started = performance.now();
  return new Promise((resolveResponse, reject) => {
    const req = httpRequest(new URL(path, base.origin), { method, headers: {
      ...headers,
      ...(cookies.size ? { Cookie: [...cookies].map(([name, value]) => `${name}=${value}`).join('; ') } : {}),
      ...(payload ? { 'Content-Type': 'application/json', 'Content-Length': payload.length } : {}),
    } }, res => {
      for (const value of res.headers['set-cookie'] ?? []) {
        const pair = value.split(';')[0], at = pair.indexOf('=');
        cookies.set(pair.slice(0, at), pair.slice(at + 1));
      }
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('error', reject);
      res.on('end', () => {
        const bytes = Buffer.concat(chunks);
        const response = { status: res.statusCode, headers: res.headers, bytes, durationMs: performance.now() - started };
        requests.push({ method, path, acceptedEncoding: headers['Accept-Encoding'] ?? null,
          status: response.status, encodedBytes: bytes.length, durationMs: response.durationMs,
          headers: Object.fromEntries(responseHeaderNames.filter(name => res.headers[name] !== undefined).map(name => [name, res.headers[name]])) });
        resolveResponse(response);
      });
    });
    req.setTimeout(30000, () => req.destroy(new Error(`HTTP acceptance timed out: ${method} ${path}`)));
    req.on('error', reject);
    req.end(payload);
  });
}

function decode(response) {
  if (!response.bytes.length) return response.bytes;
  const encoding = response.headers['content-encoding'];
  if (encoding === 'br') return brotliDecompressSync(response.bytes);
  if (encoding === 'gzip') return gunzipSync(response.bytes);
  assert.ok(!encoding || encoding === 'identity', `Unexpected encoding: ${encoding}`);
  return response.bytes;
}

function assertVary(response) {
  assert.ok(String(response.headers.vary).toLowerCase().split(',').map(value => value.trim()).includes('accept-encoding'));
}

function assertApiHeaders(response) {
  assert.equal(response.headers['cache-control'], 'no-store');
  assert.equal(response.headers['x-eeg-api-version'], '1');
  assert.equal(response.headers['x-content-type-options'], 'nosniff');
  assert.equal(response.headers['cross-origin-resource-policy'], 'same-origin');
  assert.match(response.headers['content-type'], /^application\/json/);
  assertVary(response);
}

try {
  for (const name of ['scalp.bin', 'source-roi-cortex.bin']) {
    const original = await readFile(join(project, 'webapp/public/models/ernie', name));
    const sha256 = digest(original), path = `/models/ernie/${name}?sha256=${sha256}`;
    const variants = new Map();
    for (const encoding of ['identity', 'br', 'gzip']) {
      const response = await request(path, { headers: { 'Accept-Encoding': encoding } });
      assert.equal(response.status, 200);
      assert.equal(response.headers['content-encoding'] ?? 'identity', encoding);
      assertVary(response);
      assert.equal(Number(response.headers['content-length']), response.bytes.length);
      const decoded = decode(response);
      assert.equal(decoded.length, original.length); assert.equal(digest(decoded), sha256);
      if (encoding !== 'identity') assert.ok(response.bytes.length < original.length);
      variants.set(encoding, response);
      checks.push({ check: `${name}: ${encoding} GET restores original bytes`, pass: true, originalBytes: original.length, encodedBytes: response.bytes.length, sha256 });
    }
    for (const [accepted, expected] of [['br;q=0, gzip;q=0, identity;q=1', 'identity'], ['br;q=0, gzip;q=1', 'gzip']]) {
      const response = await request(path, { headers: { 'Accept-Encoding': accepted } });
      assert.equal(response.status, 200); assert.equal(response.headers['content-encoding'] ?? 'identity', expected);
      assert.equal(digest(decode(response)), sha256);
      checks.push({ check: `${name}: quality exclusions select ${expected}`, pass: true });
    }
    for (const encoding of ['identity', 'br', 'gzip']) {
      const head = await request(path, { method: 'HEAD', headers: { 'Accept-Encoding': encoding } });
      assert.equal(head.status, 200); assert.equal(head.bytes.length, 0); assertVary(head);
      assert.equal(head.headers['content-encoding'] ?? 'identity', encoding);
      assert.equal(Number(head.headers['content-length']), variants.get(encoding).bytes.length);
      checks.push({ check: `${name}: ${encoding} HEAD has correct headers and no body`, pass: true });
    }
    const cached = await request(path, { headers: { 'Accept-Encoding': 'br', 'If-None-Match': variants.get('br').headers.etag } });
    assert.equal(cached.status, 304); assert.equal(cached.bytes.length, 0); assertVary(cached);
    checks.push({ check: `${name}: ETag revalidation returns 304 without a body`, pass: true });
    const start = 192, end = 1023;
    for (const method of ['GET', 'HEAD']) {
      const part = await request(path, { method, headers: { 'Accept-Encoding': 'br, gzip', Range: `bytes=${start}-${end}` } });
      assert.equal(part.status, 206); assert.equal(part.headers['content-encoding'], undefined);
      assert.equal(part.headers['content-range'], `bytes ${start}-${end}/${original.length}`);
      assert.equal(Number(part.headers['content-length']), end - start + 1);
      assert.deepEqual(part.bytes, method === 'GET' ? original.subarray(start, end + 1) : Buffer.alloc(0));
      checks.push({ check: `${name}: ${method} Range uses original uncompressed byte offsets`, pass: true });
    }
    const outside = await request(path, { headers: { 'Accept-Encoding': 'br', Range: `bytes=${original.length}-` } });
    assert.equal(outside.status, 416); assert.equal(outside.headers['content-range'], `bytes */${original.length}`);
    checks.push({ check: `${name}: out-of-bounds Range remains 416`, pass: true });
  }

  const healthResponse = await request('/api/local-compute/health', { headers: { 'Accept-Encoding': 'identity' } });
  assert.equal(healthResponse.status, 200); assertApiHeaders(healthResponse);
  const health = JSON.parse(decode(healthResponse));
  assert.equal(health.active_job, null); assert.equal(typeof health.token, 'string'); assert.ok(cookies.size);
  for (const [accepted, expected] of [['identity', 'identity'], ['br', 'br'], ['gzip', 'gzip'], ['br;q=0, gzip;q=0, identity;q=1', 'identity'], ['br;q=0, gzip;q=1', 'gzip']]) {
    const response = await request('/api/source-reception/lookup', { method: 'POST',
      headers: { 'Accept-Encoding': accepted, Origin: base.origin, 'X-EEG-Compute-Token': health.token }, body: fixture.request });
    assert.equal(response.status, 200); assertApiHeaders(response);
    assert.equal(response.headers['content-encoding'] ?? 'identity', expected);
    const decoded = decode(response), value = JSON.parse(decoded);
    assert.equal(value.hit, true); assert.equal(value.job.status, 'completed'); assert.equal(value.job.cached, true);
    assert.ok(isDeepStrictEqual(value.job.request, fixture.request), 'The cached request changed.');
    assert.ok(isDeepStrictEqual(value.job.result, fixture), 'The decoded scientific result differs from the saved fixture.');
    if (expected !== 'identity') assert.ok(response.bytes.length < decoded.length);
    checks.push({ check: `Signal lookup with ${accepted} preserves the complete scientific result`, pass: true,
      encoding: expected, decodedBytes: decoded.length, encodedBytes: response.bytes.length,
      resultSha256: digest(JSON.stringify(value.job.result)), numericalResultExactlyEqual: true });
  }
  const denied = await request('/api/source-reception/lookup', { method: 'POST', headers: { 'Accept-Encoding': 'br', Origin: base.origin }, body: fixture.request });
  assert.equal(denied.status, 403); assertApiHeaders(denied); assert.equal(JSON.parse(decode(denied)).code, 'request_forbidden');
  checks.push({ check: 'Compression preserves CSRF rejection and API metadata', pass: true });
  const finalHealth = await request('/api/source-reception/health', { headers: { 'Accept-Encoding': 'identity' } });
  assert.equal(finalHealth.status, 200); assert.equal(JSON.parse(decode(finalHealth)).active_job, null);
  assert.ok(requests.every(item => !/\/jobs(?:\/|$)/.test(item.path)));
} catch (error) {
  failure = { message: error.message, stack: error.stack };
  console.error(error.message);
} finally {
  const report = { passed: !failure, origin: base.origin, fixturePath, fixtureSha256: digest(JSON.stringify(fixture)),
    transport: 'node:http raw encoded response bytes; compression decoded explicitly before comparison',
    noJobEndpointsRequested: requests.every(item => !/\/jobs(?:\/|$)/.test(item.path)), checks, requests, failure };
  await writeFile(output, JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ passed: report.passed, checks: checks.length, report: output }));
}
if (failure) process.exitCode = 1;
