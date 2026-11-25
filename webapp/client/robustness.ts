import {
  apiJson,
  sessionToken,
  ApiError,
  apiFailure,
  apiFetch,
  type ApiOptions,
} from './task-client.ts';
import type { ElectrodeDesign, NoiseModel } from '../lib/design-decision';
import type {
  StudyProtocol,
  StudyResponse,
  StudyDirectoryEntry,
} from '../contracts/robustness-study';

export type CreateStudyInput = {
  protocol: StudyProtocol;
  design: ElectrodeDesign;
  cases: { seed: number; radius_mm: number; head_id?: string }[];
  title: string;
  notes: string;
  noise_model?: NoiseModel;
  conductivity_scenario?: string;
};
const path = (id: string) => {
  if (
    !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(id)
  )
    throw new Error('研究编号无效');
  return '/api/robustness-studies/' + id;
};
export type HeadPackageEntry = { head_id: string; dataset: string; subject: string };
export const listHeadPackages = (signal?: AbortSignal) =>
  apiJson<{ heads: HeadPackageEntry[] }>('/api/design-evaluation/heads', { signal });
export const listRobustnessStudies = (signal?: AbortSignal) =>
  apiJson<{ studies: StudyDirectoryEntry[] }>('/api/robustness-studies', {
    signal,
  });
export const readRobustnessStudy = (id: string, signal?: AbortSignal) =>
  apiJson<StudyResponse>(path(id), { signal });
async function write(url: string, body: unknown, signal?: AbortSignal) {
  const token = await sessionToken(signal);
  return apiJson<StudyResponse>(url, {
    method: 'POST',
    token,
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}
export const createRobustnessStudy = (
  input: CreateStudyInput,
  signal?: AbortSignal,
) => write('/api/robustness-studies', input, signal);
export const actOnRobustnessStudy = (
  id: string,
  action: 'start' | 'resume' | 'cancel',
  signal?: AbortSignal,
) => write(path(id) + '/' + action, {}, signal);
/** Keep the original wire text rather than serializing scientific cache objects again. */
export async function exportRobustnessStudy(id: string, signal?: AbortSignal) {
  const controller = new AbortController(),
    forward = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener('abort', forward, { once: true });
  const timeout = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await apiFetch(path(id) + '/export', {
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal,
    });
    const apiVersion = response.headers.get('X-EEG-API-Version');
    if (apiVersion && apiVersion !== '1') throw new ApiError('The application was updated. Reload this page to reconnect.', 426);
    const raw = await response.text();
    if (!response.ok) {
      let data: unknown = null;
      try {
        data = JSON.parse(raw);
      } catch {
        /* Keep the bounded fallback. */
      }
      throw apiFailure(response.status, data, '研究导出失败');
    }
    let value;
    try { value = JSON.parse(raw); } catch { throw new ApiError('研究导出格式无效', 502); }
    if (value?.schema !== 'eeg-robustness-study-export/1' || value.study?.id !== id || !Array.isArray(value.cases)) throw new ApiError('研究导出与所选研究不匹配', 502);
    return raw;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', forward);
  }
}
export type StudyApiOptions = Pick<ApiOptions, 'signal'>;
