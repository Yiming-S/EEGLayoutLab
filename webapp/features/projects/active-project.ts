import { validateProjectAccess, type ProjectAccess } from '../../client/projects.ts';

export const ACTIVE_PROJECT_STORAGE = 'eeg-active-project/1';
export const ACTIVE_PROJECT_EVENT = 'eeg-project-access-changed';

export function readActiveProject(storage: Pick<Storage, 'getItem'>): ProjectAccess | null {
  try {
    const value = storage.getItem(ACTIVE_PROJECT_STORAGE);
    return value ? validateProjectAccess(JSON.parse(value)) : null;
  } catch { return null; }
}
export function writeActiveProject(storage: Pick<Storage, 'setItem' | 'removeItem'>, access: ProjectAccess | null) {
  if (access) storage.setItem(ACTIVE_PROJECT_STORAGE, JSON.stringify(validateProjectAccess(access)));
  else storage.removeItem(ACTIVE_PROJECT_STORAGE);
}
/** The tab's active project is UI context, separate from all scientific URLs. */
export function activateProject(access: ProjectAccess | null) {
  writeActiveProject(window.sessionStorage, access);
  window.dispatchEvent(new Event(ACTIVE_PROJECT_EVENT));
}
