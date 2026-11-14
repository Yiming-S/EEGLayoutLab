type Asset = { url: string; sha256?: string };
export type AssetCacheOptions = {
  fetch?: typeof globalThis.fetch;
  sha256?: (buffer: ArrayBuffer) => Promise<string>;
  maxCacheBytes?: number;
  maxCacheEntries?: number;
};
type Entry = {
  controller: AbortController;
  promise: Promise<ArrayBuffer>;
  subscribers: number;
  settled: boolean;
  retainedBytes: number;
};

async function sha256(buffer: ArrayBuffer) {
  return Array.from(
    new Uint8Array(await crypto.subtle.digest('SHA-256', buffer)),
  )
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}

/** Shared immutable bytes; callers must copy any arrays handed to a scene. */
export function createModelByteCache(options: AssetCacheOptions = {}) {
  const fetchAsset = options.fetch ?? ((url, init) => fetch(url, init));
  const digest = options.sha256 ?? sha256;
  const maxBytes = options.maxCacheBytes ?? 32 * 1024 * 1024;
  const maxEntries = options.maxCacheEntries ?? 4;
  if (
    !Number.isFinite(maxBytes) ||
    maxBytes < 0 ||
    !Number.isInteger(maxEntries) ||
    maxEntries < 0
  )
    throw new Error('Invalid model cache limit');
  const entries = new Map<string, Entry>();
  // A corrupt 200 response can also reside in the browser cache. Bypass it on
  // retry; retain only a bounded number of keys, never failed model bodies.
  const retryKeys = new Set<string>();
  let retainedBytes = 0;

  function remove(key: string, entry: Entry) {
    // A canceled request may finish after its replacement has started.
    if (entries.get(key) !== entry) return;
    entries.delete(key);
    retainedBytes -= entry.retainedBytes;
    entry.retainedBytes = 0;
  }

  function trim() {
    let retainedCount = Array.from(entries.values()).filter(
      (entry) => entry.settled,
    ).length;
    for (const [key, entry] of entries) {
      if (retainedBytes <= maxBytes && retainedCount <= maxEntries) break;
      if (entry.settled) {
        remove(key, entry);
        retainedCount--;
      }
    }
  }

  return function read(
    asset: Asset,
    signal: AbortSignal,
  ): Promise<ArrayBuffer> {
    if (signal.aborted) return Promise.reject(signal.reason);
    const key = JSON.stringify([asset.url, asset.sha256 ?? null]);
    let entry = entries.get(key);
    if (!entry) {
      entry = {
        controller: new AbortController(),
        promise: Promise.resolve(new ArrayBuffer(0)),
        subscribers: 0,
        settled: false,
        retainedBytes: 0,
      };
      const pending = entry;
      entries.set(key, pending);
      pending.promise = (async () => {
        // Pin the HTTP cache as well as the memory cache to the published bytes.
        const url = asset.sha256
          ? `${asset.url}${asset.url.includes('?') ? '&' : '?'}sha256=${encodeURIComponent(asset.sha256)}`
          : asset.url;
        const response = await fetchAsset(url, {
          signal: pending.controller.signal,
          cache: retryKeys.has(key)
            ? 'reload'
            : asset.sha256
              ? 'default'
              : 'no-cache',
        });
        if (!response.ok) throw new Error('解剖模型文件加载失败');
        const buffer = await response.arrayBuffer();
        pending.controller.signal.throwIfAborted();
        if (asset.sha256 && (await digest(buffer)) !== asset.sha256)
          throw new Error('Atlas surface checksum mismatch');
        pending.controller.signal.throwIfAborted();
        return buffer;
      })().then(
        (buffer) => {
          pending.settled = true;
          if (entries.get(key) === pending) retryKeys.delete(key);
          // Unversioned files can share an in-flight request, but are never retained.
          if (asset.sha256 && entries.get(key) === pending) {
            pending.retainedBytes = buffer.byteLength;
            retainedBytes += buffer.byteLength;
            trim();
          } else remove(key, pending);
          return buffer;
        },
        (error: unknown) => {
          pending.settled = true;
          if (!pending.controller.signal.aborted) {
            retryKeys.delete(key);
            retryKeys.add(key);
            if (retryKeys.size > 16)
              retryKeys.delete(retryKeys.values().next().value!);
          }
          remove(key, pending);
          throw error;
        },
      );
    } else {
      // Map insertion order supplies least-recently-used eviction.
      entries.delete(key);
      entries.set(key, entry);
    }
    const current = entry;
    current.subscribers++;
    return new Promise((resolve, reject) => {
      let finished = false;
      const detach = () => {
        if (finished) return false;
        finished = true;
        signal.removeEventListener('abort', abort);
        current.subscribers--;
        if (!current.settled && current.subscribers === 0) {
          remove(key, current);
          current.controller.abort();
        }
        return true;
      };
      const abort = () => {
        if (detach()) reject(signal.reason);
      };
      signal.addEventListener('abort', abort, { once: true });
      if (signal.aborted) abort();
      current.promise.then(
        (buffer) => {
          if (detach()) resolve(buffer);
        },
        (error: unknown) => {
          if (detach()) reject(error);
        },
      );
    });
  };
}
