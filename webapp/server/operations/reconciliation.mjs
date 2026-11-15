/** Offline receipt repair only. This module never schedules work or edits scientific records. */
import { createHash } from 'node:crypto';

export const RECONCILIATION_SCHEMA = 'eeglayoutlab-service-reconciliation/1';
export const INTERRUPTED_MESSAGE = '服务重启中断了计算，可重新提交';
export const RECONCILIATION_KINDS = ['local-compute', 'source-reception', 'design-evaluation', 'electrode-editor'];
export const jsonHash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
export const textHash = value => createHash('sha256').update(value).digest('hex');
const plain = value => value && typeof value === 'object' && !Array.isArray(value);
const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
export const eligibleReceipt = task => task.status === 'running' ||
  (task.status === 'failed' && task.message === INTERRUPTED_MESSAGE);

export function validateQueue(value) {
  if (!plain(value) || value.version !== 1 || !Number.isSafeInteger(value.sequence) || value.sequence < 0 || !Array.isArray(value.tasks)) throw new Error('Unsupported queue state.');
  const ids = new Set();
  for (const task of value.tasks) {
    if (!plain(task) || typeof task.id !== 'string' || !task.id || ids.has(task.id) || !Number.isSafeInteger(task.sequence) ||
        task.sequence < 1 || !Array.isArray(task.owners) || !task.owners.length || task.owners.some(owner => typeof owner !== 'string' || !owner) ||
        !plain(task.request) || typeof task.status !== 'string' || typeof task.kind !== 'string' || typeof task.key !== 'string') throw new Error('Invalid queue receipt.');
    ids.add(task.id);
  }
  return value;
}

export function buildReconciliation(queue, observations) {
  validateQueue(queue);
  if (!Array.isArray(observations)) throw new Error('Invalid cache observations.');
  const observed = new Map();
  for (const item of observations) {
    if (!plain(item) || typeof item.id !== 'string' || observed.has(item.id)) throw new Error('Duplicate or invalid cache observation.');
    observed.set(item.id, item);
  }
  const changes = [], retained = [];
  const tasks = queue.tasks.map(task => {
    const item = observed.get(task.id);
    const reason = !eligibleReceipt(task) ? 'status_not_recoverable' : !RECONCILIATION_KINDS.includes(task.kind) ? 'unsupported_kind'
      : !item ? 'cache_not_inspected' : item.verdict !== 'verified' ? item.reason || 'cache_not_verified'
      : item.key !== task.key || item.kind !== task.kind || item.request_sha256 !== jsonHash(task.request) ? 'receipt_identity_changed'
      : !['completed', 'no_layout'].includes(item.status) || (item.status === 'no_layout' && task.kind !== 'local-compute') || !sha(item.cache_sha256) || !sha(item.identity_sha256) ||
        !Number.isFinite(Date.parse(item.finished_at)) || !plain(item.catalog) ? 'invalid_verified_observation' : null;
    if (reason) { retained.push({ id: task.id, status: task.status, reason }); return task; }
    const next = { ...task, status: item.status, cached: true, progress: 1, finished_at: item.finished_at,
      message: '已核对停机前保存的完整缓存', catalog: { ...task.catalog, ...item.catalog } };
    for (const field of ['starting', 'workerPid', 'backendId']) delete next[field];
    changes.push({ id: task.id, kind: task.kind, key: task.key, from: task.status, to: item.status,
      cache_path: item.cache_path, cache_sha256: item.cache_sha256, identity_sha256: item.identity_sha256 });
    return next;
  });
  return { changes, retained, proposed_queue: { ...queue, tasks } };
}
