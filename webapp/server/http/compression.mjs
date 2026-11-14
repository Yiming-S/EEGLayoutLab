import { constants, createBrotliCompress, createGzip } from 'node:zlib';
import { Readable, pipeline } from 'node:stream';

const MIN_BYTES = 1024;

/** Respect explicit exclusions and quality weights; identity is the fallback. */
export function selectJsonEncoding(header, preferIdentity = false) {
  if (typeof header !== 'string') return 'identity';
  const qualities = new Map();
  for (const member of header.split(',')) {
    const [token, ...parameters] = member.trim().toLowerCase().split(';');
    if (!token) continue;
    let quality = 1;
    for (const parameter of parameters) {
      const match = parameter.trim().match(/^q\s*=\s*(.*)$/);
      if (match) quality = /^(?:0(?:\.\d{0,3})?|1(?:\.0{0,3})?)$/.test(match[1]) ? Number(match[1]) : 0;
    }
    qualities.set(token, quality);
  }
  const identityAllowed = (qualities.get('identity') ?? (qualities.get('*') === 0 ? 0 : 1)) > 0;
  if (preferIdentity && identityAllowed) return 'identity';
  let selected = identityAllowed ? 'identity' : null;
  let best = qualities.get('identity') ?? 0;
  for (const encoding of ['br', 'gzip']) {
    const quality = qualities.get(encoding) ?? qualities.get('*') ?? 0;
    if (quality > best || (selected === 'identity' && quality === best && quality > 0)) {
      selected = encoding;
      best = quality;
    }
  }
  return selected;
}

/** Compress outside the JS thread; retain exactly the original JSON text. */
export function sendJsonPayload(res, status, serialized, headers) {
  // Async record reads can finish after navigation has closed the socket.
  if (res.closed || res.destroyed || res.writableEnded) return;
  // An error after a response starts cannot be replaced with another JSON body.
  if (res.headersSent) { res.destroy(); return; }
  const emptyStatus = status < 200 || status === 204 || status === 304;
  const body = serialized ?? '';
  const encoding = emptyStatus ? 'identity'
    : selectJsonEncoding(res.req?.headers?.['accept-encoding'], Buffer.byteLength(body) < MIN_BYTES);
  const vary = headers.Vary ?? headers.vary;
  const responseHeaders = { ...headers, Vary: [vary, 'Accept-Encoding'].filter(Boolean).join(', ') };
  delete responseHeaders.vary;
  for (const name of Object.keys(responseHeaders)) if (name.toLowerCase() === 'content-length') delete responseHeaders[name];
  res.removeHeader?.('Content-Length');
  if (encoding === null) { res.writeHead(406, responseHeaders); res.end(); return; }
  if (encoding !== 'identity') {
    responseHeaders['Content-Encoding'] = encoding;
  }
  res.writeHead(status, responseHeaders);
  if (emptyStatus || res.req?.method === 'HEAD') { res.end(); return; }
  if (encoding === 'identity') { res.end(body); return; }
  const compressor = encoding === 'br'
    ? createBrotliCompress({ params: { [constants.BROTLI_PARAM_QUALITY]: 4 } })
    : createGzip({ level: 6 });
  // pipeline destroys the source and compressor when the visitor disconnects.
  pipeline(Readable.from([body]), compressor, res, error => {
    if (error && !res.destroyed) res.destroy(error);
  });
}
