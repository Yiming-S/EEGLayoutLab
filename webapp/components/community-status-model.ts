/**
 * The task menu's data (components/community-status.tsx): GET /api/community/status, which both hosts serve.
 *
 * The Node host answers its scheduler's stats, with `online_visitors`; the Python service (eeglayoutlab serve)
 * answers the workspace queue's, without it. The menu reads the route without a token. Node counts a browser as
 * online, and logs its visit, only from the visible-page heartbeat (POST /api/community/heartbeat with the token
 * from health), so when the answer counts visitors the menu sends that heartbeat as it always did and shows its
 * answer; the Python service has no heartbeat and gets the plain GET only. The visitor count and its notices are
 * shown only when the answer has one. Each request has its own time limit (`timeoutMs`, 8 s), as each of health
 * and the heartbeat had before the status route was read.
 */
export const COMMUNITY_STATUS_PATH = '/api/community/status';
export const COMMUNITY_HEARTBEAT_PATH = '/api/community/heartbeat';
export const REQUEST_TIMEOUT_MS = 8000;

export type CommunityTask = {
  id: string; key: string; kind: string; status: string; created_at: string; finished_at?: string | null;
  queue_position: number; message: string; progress?: number; cached?: boolean; request?: unknown; catalog?: unknown;
};
export type CommunityStatus = {
  queued_tasks: number; running_tasks: number; available: boolean; recovery_blocked: boolean;
  jobs: CommunityTask[]; online_visitors?: number; maintenance?: boolean; drained?: boolean;
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
  if ('online_visitors' in value && !isCount(value.online_visitors)) return null;
  return value as CommunityStatus;
}

/** Whether the answer counts online visitors (the Node host): only then are the count and its notices shown. */
export function hasVisitorCounts(status: CommunityStatus | null): status is CommunityStatus & { online_visitors: number } {
  return status !== null && isCount(status.online_visitors);
}

async function statusOf(response: Response): Promise<CommunityStatus> {
  if (!response.ok) throw new Error('offline');
  const status = readCommunityStatus(await response.json());
  if (!status) throw new Error('offline');
  return status;
}

/** GET /api/community/status: no token, no request body; throws when the service cannot answer within `timeoutMs`
 * (the body included). */
export async function fetchCommunityStatus(timeoutMs = REQUEST_TIMEOUT_MS): Promise<CommunityStatus> {
  const signal = AbortSignal.timeout(timeoutMs);
  return statusOf(await fetch(COMMUNITY_STATUS_PATH, { signal, cache: 'no-store' }));
}

/** The Node host's heartbeat: the token from health, then POST /api/community/heartbeat with the page's visibility
 * (`x-eeg-visible`), which counts this browser and answers the same stats; throws when either request fails or
 * takes longer than `timeoutMs`. */
export async function sendCommunityHeartbeat(visible: boolean, timeoutMs = REQUEST_TIMEOUT_MS): Promise<CommunityStatus> {
  const healthSignal = AbortSignal.timeout(timeoutMs);
  const health = await fetch('/api/local-compute/health', { signal: healthSignal, cache: 'no-store' });
  if (!health.ok) throw new Error('offline');
  const { token } = await health.json() as { token: string };
  const signal = AbortSignal.timeout(timeoutMs);
  return statusOf(await fetch(COMMUNITY_HEARTBEAT_PATH, { method: 'POST',
    headers: { 'x-eeg-compute-token': token, 'x-eeg-visible': visible ? '1' : '0' }, signal, cache: 'no-store' }));
}

/** One refresh of the menu: the status, and on a host that counts visitors (Node) its heartbeat's answer. */
export async function refreshCommunityStatus(visible: boolean, timeoutMs = REQUEST_TIMEOUT_MS): Promise<CommunityStatus> {
  const status = await fetchCommunityStatus(timeoutMs);
  return hasVisitorCounts(status) ? sendCommunityHeartbeat(visible, timeoutMs) : status;
}
