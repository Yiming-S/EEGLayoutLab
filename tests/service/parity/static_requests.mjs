// Node reference for tests/service/test_static.py: how the Node host's static files (vinext's tryServeStatic)
// answer conditional and range requests.
// Usage: node tests/service/parity/static_requests.mjs <cases.json> <out.json>
//
// cases.json is {"etag", "mtimeMs", "size", "requests": [[[name, value], ...], ...], "dates": [...]}, every
// string Latin-1. Each request is sent as raw HTTP to a node:http server, so repeated headers are joined or dropped
// as in Node's req.headers, and evaluated with vinext's own functions in tryServeStatic's order: the
// preconditions, then If-Range and Range. Each date is given to vinext's parseHttpDate.
import { createServer } from 'node:http';
import { connect } from 'node:net';
import { readFileSync, writeFileSync } from 'node:fs';

const [casesPath, outPath] = process.argv.slice(2);
if (!casesPath || !outPath) throw new Error('usage: static_requests.mjs <cases.json> <out.json>');
const vinext = new URL('../../../webapp/node_modules/vinext/dist/server/', import.meta.url);
const { evaluateStaticPreconditions } = await import(new URL('http-conditional.js', vinext));
const { ifRangeAllowsRange, parseByteRange } = await import(new URL('http-range.js', vinext));
const { parseHttpDate } = await import(new URL('http-date.js', vinext));

const { etag, mtimeMs, size, requests, dates } = JSON.parse(readFileSync(casesPath, 'utf8'));

// evaluateRequestPreconditions and resolveRequestedRange of vinext/dist/server/prod-server.js, which it does not
// export.
function preconditions(req) {
  const h = req.headers;
  if (h['if-match'] === undefined && h['if-unmodified-since'] === undefined && h['if-none-match'] === undefined
    && h['if-modified-since'] === undefined) return 'proceed';
  return evaluateStaticPreconditions({
    cacheControl: h['cache-control'], ifMatch: h['if-match'], ifUnmodifiedSince: h['if-unmodified-since'],
    ifNoneMatch: h['if-none-match'], ifModifiedSince: h['if-modified-since'],
  }, req.method, etag, mtimeMs);
}
function range(req) {
  const ifRange = typeof req.headers['if-range'] === 'string' ? req.headers['if-range'] : undefined;
  return ifRangeAllowsRange(ifRange, etag, mtimeMs) ? parseByteRange(req.headers.range, size) : { kind: 'ignore' };
}

const outcomes = new Map();
const server = createServer({ maxHeaderSize: 65536 }, (req, res) => {
  const precondition = preconditions(req);
  outcomes.set(req.headers['x-case'], { precondition, range: precondition === 'proceed' ? range(req) : null });
  res.end();
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const { port } = server.address();

function send(index, headers) {
  const lines = ['GET /file HTTP/1.1', `Host: 127.0.0.1:${port}`, `X-Case: ${index}`, 'Connection: close',
    ...headers.map(([name, value]) => `${name}: ${value}`)];
  return new Promise((resolve, reject) => {
    const socket = connect(port, '127.0.0.1', () => socket.end(Buffer.from(lines.join('\r\n') + '\r\n\r\n', 'latin1')));
    socket.on('data', () => {});
    socket.on('close', resolve);
    socket.on('error', reject);
  });
}

try {
  for (const [index, headers] of requests.entries()) await send(index, headers);
} finally {
  server.close();
}
const results = requests.map((_, index) => {
  const outcome = outcomes.get(String(index));
  if (!outcome) throw new Error(`request ${index} was not evaluated`);
  return outcome;
});
writeFileSync(outPath, JSON.stringify({
  node: process.version, results,
  dates: dates.map(value => { const ms = parseHttpDate(value); return Number.isFinite(ms) ? ms : null; }),
}));
