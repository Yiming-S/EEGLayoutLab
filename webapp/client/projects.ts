import { apiJson, sessionToken, type ApiOptions } from './task-client.ts';

export type ProjectRole = 'owner' | 'viewer';
export type ProjectAccess = { project_id: string; access_key: string; title?: string; role?: ProjectRole };
export type ProjectEntryKind = 'layout' | 'editor' | 'source';
export type ProjectEntry = {
  id: string; kind: ProjectEntryKind; title: string; notes: string; record_id: string;
  created_at: string; snapshot_sha256: string;
  summary?: { protocol?: string; electrode_count?: number; region_count?: number; parent_id?: string; mode?: string };
};
export type ResearchProject = {
  id: string; title: string; owner_name: string; notes: string; revision: number;
  created_at: string; updated_at: string; entries: ProjectEntry[];
  workflow?: ProjectWorkflow;
};
export type ProjectWorkflow = { reference_entry_id: string | null; candidate_entry_id: string | null; comparison_href: string | null };
export type ProjectResponse = { project: ResearchProject; role: ProjectRole };
export const PROJECT_ACCESS_STORAGE = 'eeg-layout-project-access/1';
export const PROJECT_ACCESS_SCHEMA = 'eeg-project-access/1';
const projectId = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const accessKey = /^[A-Za-z0-9_-]{32,128}$/;

export function validateProjectAccess(value: unknown): ProjectAccess {
  const data = value as Partial<ProjectAccess> | null;
  if (!data || !projectId.test(data.project_id ?? '') || !accessKey.test(data.access_key ?? ''))
    throw new Error('项目编号或访问凭据无效');
  return { project_id: data.project_id!.toLowerCase(), access_key: data.access_key!,
    ...(typeof data.title === 'string' ? { title: data.title.slice(0, 200) } : {}),
    ...(data.role === 'owner' || data.role === 'viewer' ? { role: data.role } : {}) };
}

export function readProjectAccess(storage: Pick<Storage, 'getItem'>): ProjectAccess[] {
  try {
    const rows: unknown = JSON.parse(storage.getItem(PROJECT_ACCESS_STORAGE) ?? '[]');
    if (!Array.isArray(rows)) return [];
    const unique = new Map<string, ProjectAccess>();
    for (const row of rows) {
      try { const access = validateProjectAccess(row); unique.set(access.project_id, access); } catch { /* Ignore invalid local entries. */ }
    }
    return [...unique.values()];
  } catch { return []; }
}

export function saveProjectAccess(storage: Pick<Storage, 'getItem' | 'setItem'>, value: ProjectAccess) {
  const access = validateProjectAccess(value);
  const current = readProjectAccess(storage), existing = current.find(row => row.project_id === access.project_id);
  const rows = current.filter(row => row.project_id !== access.project_id);
  rows.unshift(access.role === 'viewer' && existing?.role === 'owner' ? existing : access);
  storage.setItem(PROJECT_ACCESS_STORAGE, JSON.stringify(rows));
  return rows;
}

export function forgetProjectAccess(storage: Pick<Storage, 'getItem' | 'setItem'>, id: string) {
  const rows = readProjectAccess(storage).filter(row => row.project_id !== id);
  storage.setItem(PROJECT_ACCESS_STORAGE, JSON.stringify(rows));
  return rows;
}

export function projectAccessFile(value: ProjectAccess) {
  return JSON.stringify({ schema: PROJECT_ACCESS_SCHEMA, ...validateProjectAccess(value) }, null, 2) + '\n';
}

export function parseProjectAccessFile(text: string) {
  if (text.length > 8192) throw new Error('项目凭据文件过大');
  const value = JSON.parse(text);
  if (value?.schema !== PROJECT_ACCESS_SCHEMA) throw new Error('项目凭据文件格式无效');
  return validateProjectAccess(value);
}

/** Credentials use a fragment, which is not sent in HTTP requests. */
export function projectShareHref(origin: string, value: ProjectAccess) {
  const access = validateProjectAccess(value), url = new URL('/projects', origin);
  url.hash = new URLSearchParams({ project: access.project_id, access: access.access_key }).toString();
  return url.href;
}

export function projectAccessFromFragment(hash: string): ProjectAccess | null {
  const query = new URLSearchParams(hash.replace(/^#/, ''));
  if (!query.has('access')) return null;
  return validateProjectAccess({ project_id: query.get('project'), access_key: query.get('access') });
}

export async function projectRequest<T>(access: ProjectAccess, suffix = '', options: ApiOptions = {}) {
  const checked = validateProjectAccess(access);
  if (suffix && !/^\/(?:entries(?:\/[a-f0-9-]+)?|share|revoke-share|export)$/.test(suffix))
    throw new Error('项目接口路径无效');
  const headers = new Headers(options.headers);
  headers.set('X-EEG-Project-Key', checked.access_key);
  if (options.method && options.method !== 'GET') headers.set('Content-Type', 'application/json');
  const token = options.method && options.method !== 'GET' ? await sessionToken(options.signal ?? undefined) : undefined;
  return apiJson<T>(`/api/projects/${checked.project_id}${suffix}`, { ...options, headers, token });
}

export async function createProject(input: { title: string; owner_name: string; notes?: string }) {
  const token = await sessionToken();
  return apiJson<ProjectResponse & { access_key: string }>('/api/projects', {
    method: 'POST', token, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  });
}
