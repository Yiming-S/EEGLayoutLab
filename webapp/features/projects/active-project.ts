import { isProjectId } from '../../client/projects.ts';

/** The project a tab saves results into: its id and, for display, its title. */
export type ActiveProject = { project_id: string; title?: string };
export const ACTIVE_PROJECT_STORAGE = 'eeg-active-project/1';
export const ACTIVE_PROJECT_EVENT = 'eeg-project-access-changed';

/** Only the id and title are kept; a value from an earlier version may carry more and is read the same way. */
function activeProject(value: unknown): ActiveProject {
  const data = value as Partial<ActiveProject> | null;
  if (!isProjectId(data?.project_id)) throw new Error('项目编号无效');
  return { project_id: data.project_id, ...(typeof data.title === 'string' ? { title: data.title.slice(0, 200) } : {}) };
}

export function readActiveProject(storage: Pick<Storage, 'getItem'>): ActiveProject | null {
  try {
    const value = storage.getItem(ACTIVE_PROJECT_STORAGE);
    return value ? activeProject(JSON.parse(value)) : null;
  } catch { return null; }
}
export function writeActiveProject(storage: Pick<Storage, 'setItem' | 'removeItem'>, project: ActiveProject | null) {
  if (project) storage.setItem(ACTIVE_PROJECT_STORAGE, JSON.stringify(activeProject(project)));
  else storage.removeItem(ACTIVE_PROJECT_STORAGE);
}
/** The tab's active project is UI context, separate from all scientific URLs. */
export function activateProject(project: ActiveProject | null) {
  writeActiveProject(window.sessionStorage, project);
  window.dispatchEvent(new Event(ACTIVE_PROJECT_EVENT));
}
