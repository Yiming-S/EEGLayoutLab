import { readFile } from 'node:fs/promises';

const RUNTIME_SCHEMA = 'eeglayoutlab-runtime/1';

/**
 * @typedef {object} ServiceSession
 * @property {string} base Origin the session was opened at (the service, or a Vite proxy in front of it).
 * @property {string} cookie Session cookie as a `name=value` pair for the Cookie header.
 * @property {string} csrf 64-hex token that writes send as X-EEG-Compute-Token.
 * @property {(extra?: HeadersInit) => Record<string, string>} headers `extra` plus the cookie and the token.
 */

/**
 * The origin of a URL of the Python service, or of a Vite proxy in front of it; both listen on 127.0.0.1 only.
 * `localhost` and `[::1]` are refused: Node connects to ::1 first, where any local user may listen on the same
 * port and would receive the launch token and the cookie. With `exact`, the URL must be the origin itself.
 * @param {string | undefined} value
 * @param {{ exact?: boolean, name?: string }} [options]
 * @returns {string}
 */
export function serviceOrigin(value, { exact = false, name = 'The service URL' } = {}) {
  let url;
  try { url = new URL(value ?? ''); } catch { url = undefined; }
  if (!url || url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.username || url.password
    || exact && (url.pathname !== '/' || url.search || url.hash)) {
    throw new Error(`${name} must be http://127.0.0.1:<port>, not ${JSON.stringify(value)}.`);
  }
  return url.origin;
}

async function readRuntime(path) {
  const runtime = JSON.parse(await readFile(path, 'utf8'));
  if (runtime?.schema !== RUNTIME_SCHEMA || !Number.isInteger(runtime.port) || runtime.port < 1 || runtime.port > 65535
    || typeof runtime.token !== 'string' || !runtime.token) {
    throw new Error(`${path} is not an ${RUNTIME_SCHEMA} file.`);
  }
  return runtime;
}

/**
 * Sign in to the Python service as its launched browser does: exchange the launch token at /open for the
 * session cookie, then read the CSRF token from health. `runtime` is the path of
 * `<workspace>/.eeglayoutlab/runtime.json` and takes precedence; otherwise `token` is the launch token and
 * `base` is required. `base` defaults to the runtime's port and may name a Vite proxy in front of the service.
 * @param {{ runtime?: string, token?: string, base?: string }} [options]
 * @returns {Promise<ServiceSession>}
 */
export async function openServiceSession({ runtime = process.env.EEG_SERVICE_RUNTIME, token = process.env.EEG_SERVICE_TOKEN, base } = {}) {
  let port;
  if (runtime) {
    ({ port, token } = await readRuntime(runtime));
    base ||= `http://127.0.0.1:${port}`;
  } else if (!token) {
    throw new Error('Set EEG_SERVICE_RUNTIME to the runtime.json path or EEG_SERVICE_TOKEN to the launch token.');
  } else if (!base) {
    throw new Error('A launch token needs the service base URL.');
  }
  const origin = serviceOrigin(base);
  const open = new URL('/open', origin);
  open.searchParams.set('token', token);
  // Error messages name the origin only, never the URL that carries the token.
  const opened = await fetch(open, { redirect: 'manual' });
  await opened.arrayBuffer();
  if (opened.status !== 303) throw new Error(`${origin}/open refused the launch token: HTTP ${opened.status}.`);
  // The cookie name carries the service's own port, which differs from a proxy's.
  const name = port === undefined ? /^eeglayoutlab-\d{1,5}=\S+$/ : new RegExp(`^eeglayoutlab-${port}=\\S+$`);
  const cookie = opened.headers.getSetCookie().map(line => line.split(';', 1)[0].trim()).find(pair => name.test(pair));
  if (!cookie) throw new Error(`${origin}/open set no eeglayoutlab session cookie.`);

  const response = await fetch(origin + '/api/local-compute/health', { headers: { Cookie: cookie } });
  const health = await response.json().catch(() => undefined);
  if (!response.ok || typeof health?.token !== 'string' || !/^[a-f0-9]{64}$/.test(health.token)) {
    throw new Error(`${origin}/api/local-compute/health returned no CSRF token: HTTP ${response.status}.`);
  }
  const csrf = health.token;
  return {
    base: origin, cookie, csrf,
    headers(extra) {
      const merged = new Headers(extra);
      merged.set('Cookie', [cookie, merged.get('Cookie')].filter(Boolean).join('; '));
      merged.set('X-EEG-Compute-Token', csrf);
      return Object.fromEntries(merged);
    },
  };
}

/**
 * The session cookie in the form `BrowserContext.addCookies` takes, for pages opened at `session.base`.
 * @param {Pick<ServiceSession, 'base' | 'cookie'>} session
 */
export function playwrightCookies({ base, cookie }) {
  const at = cookie.indexOf('=');
  return [{ name: cookie.slice(0, at), value: cookie.slice(at + 1), url: base, httpOnly: true, sameSite: 'Strict' }];
}
