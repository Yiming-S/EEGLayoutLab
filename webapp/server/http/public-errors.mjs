/**
 * What a visitor may see of a failure. Server paths never leave the host, and faults
 * of the server itself (file system, programming errors) are 500s, so monitoring
 * counts them; the full error is written to the service log.
 */
const ABSOLUTE_PATH = /(^|[\s'"(=[])((?:\/[^\s/'"`:,;)\]]+){2,})/g;
export const INTERNAL_MESSAGE = '服务器内部错误，已记录；请稍后重试';

export function redactPaths(text) {
  return typeof text === 'string' ? text.replace(ABSOLUTE_PATH, (_, before) => `${before}[server path]`) : text;
}

/** A Node system error or a programming error, rather than a rejected request. */
export function internalFault(error) {
  return (typeof error?.code === 'string' && /^E[A-Z]+$/.test(error.code)) ||
    error instanceof TypeError || error instanceof ReferenceError || error instanceof RangeError;
}

export function publicFailure(error, fallbackStatus = 400) {
  if (Number.isInteger(error?.status) && error.status >= 400 && error.status < 600)
    return { status: error.status, message: redactPaths(String(error.message)) };
  if (error instanceof SyntaxError) return { status: 400, message: '请求内容不是有效的JSON' };
  if (internalFault(error)) {
    console.error('[eeg] internal error:', error);
    return { status: 500, message: INTERNAL_MESSAGE };
  }
  return { status: fallbackStatus, message: redactPaths(String(error?.message ?? error)) };
}

/** Message text stored on a job receipt and shown to every owner of that job. */
export function publicMessage(error) {
  return publicFailure(error).message;
}

/** Redacts the message-like fields of an API payload in place of the original. */
export function redactPayload(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return data;
  const job = value => (value && typeof value === 'object' && typeof value.message === 'string' ? { ...value, message: redactPaths(value.message) } : value);
  const out = { ...data };
  if (typeof out.error === 'string') out.error = redactPaths(out.error);
  if (typeof out.message === 'string') out.message = redactPaths(out.message);
  if (out.job) out.job = job(out.job);
  if (Array.isArray(out.jobs)) out.jobs = out.jobs.map(job);
  if (Array.isArray(out.warnings)) out.warnings = out.warnings.map(redactPaths);
  return out;
}
