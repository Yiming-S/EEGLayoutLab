import { isIP } from 'node:net';

const normalizedIP = value => typeof value === 'string' && value.startsWith('::ffff:') ? value.slice(7) : value;
const loopback = value => ['127.0.0.1', '::1'].includes(normalizedIP(value));
const sameSite = req => !req.headers['sec-fetch-site'] || ['same-origin', 'none'].includes(req.headers['sec-fetch-site']);

export function loopbackRequest(req) {
  if (!loopback(req.socket?.remoteAddress)) return false;
  const host = req.headers.host;
  if (typeof host !== 'string' || !/^(localhost|127\.0\.0\.1|\[::1\])(?::\d{1,5})?$/.test(host)) return false;
  if (req.headers.origin && req.headers.origin !== `http://${host}`) return false;
  return sameSite(req);
}

/** Explicit single-proxy boundary. Forwarding headers are never trusted by default. */
export function createAccessPolicy({ publicOrigin, trustedProxyAddresses = [] } = {}) {
  if (!publicOrigin) {
    if (trustedProxyAddresses.length) throw new Error('Trusted proxies require EEG_PUBLIC_ORIGIN.');
    return { localOnly: true, secureCookies: false, guard: loopbackRequest,
      visitorAddress: req => req.socket?.remoteAddress || 'unknown' };
  }
  const origin = new URL(publicOrigin);
  if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) {
    throw new Error('EEG_PUBLIC_ORIGIN must be an HTTPS origin without a path.');
  }
  if (!trustedProxyAddresses.length || trustedProxyAddresses.some(ip => typeof ip !== 'string' || !isIP(ip))) {
    throw new Error('EEG_TRUSTED_PROXIES must contain explicit IP addresses.');
  }
  const trusted = new Set(trustedProxyAddresses.map(normalizedIP));
  const isProxyRequest = req => trusted.has(normalizedIP(req.socket?.remoteAddress)) &&
    typeof req.headers.host === 'string' && req.headers.host.toLowerCase() === origin.host &&
    req.headers['x-forwarded-proto'] === 'https' && typeof req.headers['x-forwarded-for'] === 'string' &&
    Boolean(isIP(req.headers['x-forwarded-for'])) &&
    (!req.headers.origin || req.headers.origin === origin.origin) && sameSite(req);
  return { localOnly: false, secureCookies: true, publicOrigin: origin.origin,
    guard: req => loopbackRequest(req) || isProxyRequest(req),
    visitorAddress: req => isProxyRequest(req) ? normalizedIP(req.headers['x-forwarded-for']) : req.socket?.remoteAddress || 'unknown' };
}
