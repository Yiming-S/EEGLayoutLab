import { apiFailure, serviceUnreachable } from '../client/task-client.ts';

/**
 * The task menu's data (components/community-status.tsx): GET /api/community/status, the workspace queue of
 * `eeglayoutlab serve` (the legacy Node host serves the same route). The menu reads it without a token or a request
 * body, with one time limit per request (`timeoutMs`, 8 s). A visitor count in the answer (the Node host's) is not
 * read: the application has one local user.
 */
export const COMMUNITY_STATUS_PATH = '/api/community/status';
export const REQUEST_TIMEOUT_MS = 8000;

export type CommunityTask = {
  id: string; key: string; kind: string; status: string; created_at: string; finished_at?: string | null;
  queue_position: number; message: string; progress?: number; cached?: boolean; request?: unknown; catalog?: unknown;
};
export type CommunityStatus = {
  queued_tasks: number; running_tasks: number; available: boolean; recovery_blocked: boolean;
  jobs: CommunityTask[]; maintenance?: boolean; drained?: boolean;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const isCount = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;

/** The status when `value` has the members the menu reads, else null (an answer it cannot show). */
export function readCommunityStatus(value: unknown): CommunityStatus | null {
  if (!isRecord(value) || !isCount(value.queued_tasks) || !isCount(value.running_tasks)) return null;
  if (typeof value.available !== 'boolean' || typeof value.recovery_blocked !== 'boolean') return null;
  if (!Array.isArray(value.jobs) || !value.jobs.every(job => isRecord(job) && typeof job.id === 'string'
    && typeof job.kind === 'string' && typeof job.status === 'string')) return null;
  return value as CommunityStatus;
}

/** GET /api/community/status. Throws when the service cannot answer within `timeoutMs` (the body included):
 * `ApiError` with the reopen message for a session from an earlier run (401) or for no server at all (a network
 * error: the service stopped, or restarted on another port), a TimeoutError, else an error 'offline'. It calls
 * `fetch` itself: it answers SERVICE_CONNECTION_EVENT, so it must not announce it (apiFetch would). */
export async function fetchCommunityStatus(timeoutMs = REQUEST_TIMEOUT_MS): Promise<CommunityStatus> {
  const signal = AbortSignal.timeout(timeoutMs);
  let response: Response;
  try { response = await fetch(COMMUNITY_STATUS_PATH, { signal, cache: 'no-store' }); }
  catch (error) { throw error instanceof TypeError && !signal.aborted ? serviceUnreachable() : error; }
  if (response.status === 401) throw apiFailure(401, await response.json().catch(() => null), 'offline');
  if (!response.ok) throw new Error('offline');
  const status = readCommunityStatus(await response.json());
  if (!status) throw new Error('offline');
  return status;
}
