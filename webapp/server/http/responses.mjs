/** Additive API metadata. Existing endpoints and error strings remain supported. */
import { sendJsonPayload } from './compression.mjs';
import { correlateOperation } from '../operations/monitor.mjs';
export const API_VERSION = '1';
const codes = {
  400: 'invalid_request', 401: 'authentication_required', 403: 'request_forbidden',
  404: 'not_found', 405: 'method_not_allowed', 409: 'compute_busy',
  413: 'request_too_large', 415: 'unsupported_media_type', 429: 'queue_limited',
  500: 'internal_error', 503: 'service_unavailable',
};

export function sendJson(res, status, data) {
  correlateOperation(res, data?.job);
  const body = status >= 400 && typeof data?.error === 'string'
    ? { ...data, code: data.code || codes[status] || 'request_failed' } : data;
  sendJsonPayload(res, status, JSON.stringify(body), {
    'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', 'Cross-Origin-Resource-Policy': 'same-origin',
    'X-EEG-API-Version': API_VERSION,
  });
}
