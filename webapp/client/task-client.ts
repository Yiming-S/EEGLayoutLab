/** Browser-side transport and task observation. Only the server owns job status. */
export type TaskConnection = 'connected' | 'reconnecting' | 'blocked';
export type TaskState = { id: string; status: string; annotation_id?: string };
export const isTaskRunning = (job: TaskState | null | undefined) =>
  Boolean(job && ['queued', 'running', 'cancelling'].includes(job.status));

export class ApiError extends Error {
  readonly status: number;
  readonly data: Record<string, unknown> | null;
  constructor(message: string, status = 0, data: Record<string, unknown> | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
  get retryable() {
    return this.status === 0 || this.status === 408 || this.status === 429 || this.status >= 500;
  }
  /** The outcome is unknown (no answer, timeout, server fault), unlike a request the server rejected. */
  get connectionLost() {
    return this.status === 0 || this.status === 408 || this.status >= 500;
  }
}
const abortError = () => new DOMException('Aborted', 'AbortError');
const taskStatuses = ['queued', 'running', 'cancelling', 'completed', 'no_layout', 'failed', 'cancelled', 'timeout'];
function validateTask(data: unknown, expectedId?: string) {
  const job = (data as { job?: TaskState } | null)?.job;
  if (!job || typeof job.id !== 'string' || !taskStatuses.includes(job.status) ||
      (expectedId !== undefined && job.id !== expectedId))
    throw new ApiError('Job status unavailable', 502);
}
export type ApiOptions = RequestInit & { token?: string; errorMessage?: string; timeoutMs?: number };

/** No mutation is retried: an unknown POST outcome must be recovered by lookup. */
export async function apiJson<T>(url: string, options: ApiOptions = {}): Promise<T> {
  const { token, errorMessage = '任务连接中断', timeoutMs = 15000, signal, ...init } = options;
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) throw abortError();
  signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(abort, timeoutMs);
  try {
    const headers = new Headers(init.headers);
    if (token) headers.set('X-EEG-Compute-Token', token);
    const response = await fetch(url, { cache: 'no-store', ...init, headers, signal: controller.signal });
    const apiVersion = response.headers?.get('X-EEG-API-Version');
    if (apiVersion && apiVersion !== '1')
      throw new ApiError('The application was updated. Reload this page to reconnect.', 426);
    let data: T & { error?: string };
    try { data = await response.json(); }
    catch { throw new ApiError(errorMessage, response.ok ? 502 : response.status); }
    if (signal?.aborted) throw abortError();
    if (controller.signal.aborted) throw new ApiError(errorMessage);
    if (!response.ok) throw new ApiError(data?.error || errorMessage, response.status, data as Record<string, unknown>);
    return data;
  } catch (error) {
    if (signal?.aborted) throw abortError();
    if (error instanceof ApiError) throw error;
    throw new ApiError(errorMessage);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

export async function sessionToken(signal?: AbortSignal) {
  const health = await apiJson<{ token: string }>('/api/local-compute/health', { signal });
  if (typeof health.token !== 'string' || !health.token) throw new ApiError('计算服务未连接', 502);
  return health.token;
}

export async function submitTask<T>(service: string, body: unknown, options: ApiOptions = {}) {
  const token = options.token ?? await sessionToken(options.signal ?? undefined);
  const data = await apiJson<T>(`/api/${service}/jobs`, {
    ...options, method: 'POST', token, headers: { 'Content-Type': 'application/json' },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
  validateTask(data);
  return data;
}

export async function cancelTask<T>(service: string, id: string, options: ApiOptions = {}) {
  const token = options.token ?? await sessionToken(options.signal ?? undefined);
  const data = await apiJson<T>(`/api/${service}/jobs/${encodeURIComponent(id)}/cancel`, { ...options, method: 'POST', token });
  validateTask(data, id);
  return data;
}

export async function readTask<T extends TaskState>(service: string, id: string, signal?: AbortSignal, annotationId?: string) {
  const query = annotationId && /^[a-f0-9]{64}$/.test(annotationId) ? `?annotation_id=${annotationId}` : '';
  const data = await apiJson<{ job: T }>(`/api/${service}/jobs/${encodeURIComponent(id)}${query}`, { signal });
  validateTask(data, id);
  if (annotationId && data.job.annotation_id !== annotationId) throw new ApiError('Electrode name annotation unavailable', 502);
  return data.job;
}

const wait = (ms: number, signal: AbortSignal) => new Promise<void>((resolve, reject) => {
  if (signal.aborted) { reject(abortError()); return; }
  const abort = () => { clearTimeout(timer); reject(abortError()); };
  const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, ms);
  signal.addEventListener('abort', abort, { once: true });
});

type FollowOptions<T extends TaskState> = {
  service: string; initial: T; signal: AbortSignal;
  onJob: (job: T) => void;
  onConnection: (connection: TaskConnection, error?: ApiError) => void;
  firstDelayMs?: number; intervalMs?: number; maxFailures?: number; maxRetryMs?: number;
};

/** One request at a time, bounded recovery, cancellation and stale-response protection. */
export async function followTask<T extends TaskState>({
  service, initial, signal, onJob, onConnection,
  firstDelayMs = 300, intervalMs = 900, maxFailures = 5, maxRetryMs = 10000,
}: FollowOptions<T>): Promise<T> {
  let current = initial, failures = 0, delay = firstDelayMs;
  while (isTaskRunning(current)) {
    await wait(delay, signal);
    try {
      const next = await readTask<T>(service, current.id, signal, initial.annotation_id);
      if (signal.aborted) throw abortError();
      current = next;
      failures = 0;
      onConnection('connected');
      onJob(current);
      delay = intervalMs;
    } catch (error) {
      if (signal.aborted) throw abortError();
      const failure = error instanceof ApiError ? error : new ApiError('任务连接中断');
      failures += 1;
      if (!failure.retryable || failures >= maxFailures) {
        onConnection('blocked', failure);
        throw failure;
      }
      onConnection('reconnecting', failure);
      delay = Math.min(maxRetryMs, intervalMs * 2 ** (failures - 1));
    }
  }
  return current;
}
