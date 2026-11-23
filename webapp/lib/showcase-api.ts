/**
 * The read-only showcase: the same interface built as static files, with no service behind it.
 *
 * In a showcase build, `installShowcaseApi()` answers every same-origin `/api` and `/open` request in the
 * browser. A GET whose path is listed in `/showcase-api/index.json` reads the JSON file written for it by
 * `scripts/build-showcase-data.mjs` (catalogs, curated records, and health that reports no computation);
 * every other request (computation, writes, annotation views)
 * gets a 403 `{error, code: 'showcase_read_only'}`, whose message the existing error displays show. No
 * request leaves the page for a missing file, so the browser console stays clean.
 */
export const SHOWCASE_DATA_SCHEMA = 'eeglayoutlab-showcase-data/1';
export const SHOWCASE_READ_ONLY_CODE = 'showcase_read_only';

/** The refusal text, in the page's language (LanguageProvider keeps <html lang> current). */
export function showcaseRefusal(lang: string): string {
  return lang.toLowerCase().startsWith('zh')
    ? '这是只读展示版，不运行计算，也不保存数据。安装 EEGLayoutLab 本地版后即可计算。'
    : 'This is the read-only showcase: it runs no calculations and stores nothing. Install EEGLayoutLab to compute.';
}

/** The file that answers a GET of `pathname`, or null when the showcase has none. */
export function showcaseFile(pathname: string, search: string, paths: ReadonlySet<string>): string | null {
  if (search || !pathname.startsWith('/api/') || !paths.has(pathname)) return null;
  return '/showcase-api/' + pathname.slice('/api/'.length) + '.json';
}

const json = (body: unknown, status: number) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'X-EEG-API-Version': '1', 'X-EEG-Showcase': '1' },
  });

/** Replaces window.fetch for `/api` and `/open`; other requests pass through unchanged. */
export function installShowcaseApi() {
  if (typeof window === 'undefined' || (window.fetch as { showcase?: boolean }).showcase) return;
  const network = window.fetch.bind(window);
  let index: Promise<ReadonlySet<string>> | null = null;
  const paths = () =>
    (index ??= network('/showcase-api/index.json', { cache: 'no-cache' })
      .then(async (response) => {
        const data = response.ok ? ((await response.json()) as { schema?: string; paths?: unknown }) : null;
        return new Set(data?.schema === SHOWCASE_DATA_SCHEMA && Array.isArray(data.paths) ? data.paths.filter((p): p is string => typeof p === 'string') : []);
      })
      .catch(() => new Set<string>()));

  const showcaseFetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.href);
    if (url.origin !== window.location.origin || !/^\/(?:api|open)(?:\/|$)/.test(url.pathname)) return network(input, init);
    const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined);
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (method === 'GET' || method === 'HEAD') {
      const file = showcaseFile(url.pathname, url.search, await paths());
      if (file) {
        const response = await network(file, { signal, cache: 'no-cache' });
        if (response.ok) return json(await response.json(), 200);
      }
    }
    return json({ error: showcaseRefusal(document.documentElement.lang), code: SHOWCASE_READ_ONLY_CODE }, 403);
  };
  window.fetch = Object.assign(showcaseFetch, { showcase: true });
}
