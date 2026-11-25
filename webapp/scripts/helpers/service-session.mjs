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

/**
 * The parsed text of `<workspace>/.eeglayoutlab/runtime.json`, checked: its port and launch token.
 * @param {unknown} runtime
 * @param {string} path Named in the error.
 * @returns {{ port: number, token: string }}
 */
export function checkedRuntime(runtime, path) {
  const value = /** @type {{ schema?: unknown, port?: unknown, token?: unknown } | null} */ (runtime);
  if (value?.schema !== RUNTIME_SCHEMA || !Number.isInteger(value.port) || Number(value.port) < 1 || Number(value.port) > 65535
    || typeof value.token !== 'string' || !value.token) {
    throw new Error(`${path} is not an ${RUNTIME_SCHEMA} file.`);
  }
  return { port: Number(value.port), token: value.token };
}

async function readRuntime(path) {
  return checkedRuntime(JSON.parse(await readFile(path, 'utf8')), path);
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

const SERVER_HINT = 'Start the Python service (eeglayoutlab serve <workspace> --no-browser) and set EEG_SERVICE_RUNTIME '
  + 'to its <workspace>/.eeglayoutlab/runtime.json, or EEG_SERVICE_TOKEN to its launch token with EEG_TEST_URL.';

/**
 * The server a live or browser script checks. The Python service (`eeglayoutlab serve`) when EEG_SERVICE_RUNTIME or
 * EEG_SERVICE_TOKEN is set: the script signs in as its launched browser, and EEG_TEST_URL, when set, is the base (a
 * Vite proxy in front of it, or the service itself with a token). Otherwise, where the script still supports it
 * (`node`), the legacy Node host (`npm start`, kept until phase 4) at EEG_TEST_URL. There is no default address.
 * @param {{ node?: boolean }} [options] `node: false` for a script that checks the Python service only.
 * @returns {Promise<{ base: string, service: ServiceSession | null }>} `base` is an origin without a trailing slash.
 */
export async function scriptServer({ node = true } = {}) {
  if (process.env.EEG_SERVICE_RUNTIME || process.env.EEG_SERVICE_TOKEN) {
    const service = await openServiceSession({ base: process.env.EEG_TEST_URL || undefined });
    return { base: service.base, service };
  }
  if (!node) throw new Error(`This check runs against the Python service only. ${SERVER_HINT}`);
  if (!process.env.EEG_TEST_URL) {
    throw new Error(`No server to check. ${SERVER_HINT} A legacy Node host (npm start) is checked at EEG_TEST_URL alone.`);
  }
  let url;
  try { url = new URL(process.env.EEG_TEST_URL); } catch { url = undefined; }
  if (!url || url.protocol !== 'http:') throw new Error(`EEG_TEST_URL must be an http:// URL, not ${JSON.stringify(process.env.EEG_TEST_URL)}.`);
  return { base: url.origin, service: null };
}

/**
 * Asserts the cache-only state that a script needs before it submits anything: health reports `maintenance` (the
 * Python service runs with `eeglayoutlab serve --cache-only`; a legacy Node host with EEG_MAINTENANCE=1) and
 * `drained` (no task is waiting or running), so that only stored results can answer.
 * @param {{ maintenance?: unknown, drained?: unknown }} health The body of GET /api/local-compute/health.
 */
export function assertCacheOnly(health) {
  if (health?.maintenance !== true) throw new Error('The server must serve stored results only: run eeglayoutlab serve --cache-only.');
  if (health?.drained !== true) throw new Error('The server queue must be drained: no task may be waiting or running.');
}

/**
 * The session cookie in the form `BrowserContext.addCookies` takes, for pages opened at `session.base`.
 * @param {Pick<ServiceSession, 'base' | 'cookie'>} session
 */
export function playwrightCookies({ base, cookie }) {
  const at = cookie.indexOf('=');
  return [{ name: cookie.slice(0, at), value: cookie.slice(at + 1), url: base, httpOnly: true, sameSite: 'Strict' }];
}
