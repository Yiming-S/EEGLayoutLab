import { apiJson, sessionToken } from './task-client.ts';
import type { RecordVisibility } from '../lib/local-library.ts';

/** Publish a record this browser submitted to the shared library, or withdraw its publication. */
export async function setRecordVisibility(id: string, value: boolean, signal?: AbortSignal): Promise<RecordVisibility> {
  if (!/^[a-f0-9]{64}$/.test(id)) throw new Error('记录编号无效');
  const token = await sessionToken(signal);
  const response = await apiJson<{ visibility: RecordVisibility }>(`/api/local-compute/library/${id}/visibility`, {
    method: 'POST', token, signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ public: value }),
    errorMessage: '公开状态未能更新，请刷新后重试',
  });
  return response.visibility;
}
