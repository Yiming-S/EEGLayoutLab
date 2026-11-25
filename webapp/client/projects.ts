import { apiJson, sessionToken, type ApiOptions } from './task-client.ts';

/**
 * Research projects of the open workspace (`W/projects`). The local user owns every project: requests carry the
 * session cookie and, for writes, the CSRF token, and no project credential.
 */
export type ProjectEntryKind = 'layout' | 'editor' | 'source';
export type ProjectEntry = {
  id: string; kind: ProjectEntryKind; title: string; notes: string; record_id: string;
  annotation_id?: string;
  created_at: string; snapshot_sha256: string;
  summary?: { protocol?: string; electrode_count?: number; region_count?: number; parent_id?: string; mode?: string;
    brain_region?: string; brain_regions?: string[]; source_index?: number; seed?: number; simulation?: boolean };
};
export type ResearchProject = {
  id: string; title: string; owner_name: string; notes: string; revision: number;
  created_at: string; updated_at: string; entries: ProjectEntry[];
  workflow?: ProjectWorkflow;
};
export type ProjectWorkflow = { reference_entry_id: string | null; candidate_entry_id: string | null; comparison_href: string | null };
export type ProjectResponse = { project: ResearchProject };
/** One row of `GET /api/projects`, most recently updated first. */
export type ProjectSummary = {
  id: string; title: string; owner_name: string; revision: number; created_at: string; updated_at: string; entry_count: number;
};
const projectId = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
export const isProjectId = (value: unknown): value is string => typeof value === 'string' && projectId.test(value);
const object = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value));

/** The rows of a project directory that name a project; others are skipped. */
export function readProjectDirectory(value: unknown): ProjectSummary[] {
  if (!object(value) || !Array.isArray(value.projects)) throw new Error('项目目录格式无效');
  return value.projects.filter((row): row is ProjectSummary => object(row) && isProjectId(row.id) && typeof row.title === 'string'
    && typeof row.owner_name === 'string' && Number.isSafeInteger(row.revision) && typeof row.updated_at === 'string'
    && typeof row.created_at === 'string' && Number.isSafeInteger(row.entry_count));
}

/** The directory row of a project the service has just answered with. */
export const projectSummary = (project: ResearchProject): ProjectSummary => ({
  id: project.id, title: project.title, owner_name: project.owner_name, revision: project.revision,
  created_at: project.created_at, updated_at: project.updated_at, entry_count: project.entries.length,
});

export async function listProjects(signal?: AbortSignal) {
  return readProjectDirectory(await apiJson<unknown>('/api/projects', { signal, errorMessage: '项目目录未载入，请重新读取。' }));
}

export async function projectRequest<T>(id: string, suffix = '', options: ApiOptions = {}) {
  if (!isProjectId(id)) throw new Error('项目编号无效');
  if (suffix && !/^\/(?:entries(?:\/[a-f0-9-]+)?|export)$/.test(suffix)) throw new Error('项目接口路径无效');
  const headers = new Headers(options.headers);
  const write = Boolean(options.method && options.method !== 'GET');
  if (write) headers.set('Content-Type', 'application/json');
  const token = write ? await sessionToken(options.signal ?? undefined) : undefined;
  return apiJson<T>(`/api/projects/${id}${suffix}`, { ...options, headers, token });
}

export async function createProject(input: { title: string; owner_name: string; notes?: string }) {
  const token = await sessionToken();
  return apiJson<ProjectResponse>('/api/projects', {
    method: 'POST', token, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  });
}
