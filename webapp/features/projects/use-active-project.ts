'use client';
import { useEffect, useState } from 'react';
import { ACTIVE_PROJECT_EVENT, readActiveProject, type ActiveProject } from './active-project';

export function useActiveProject() {
  const [active, setActive] = useState<ActiveProject | null>(null);
  useEffect(() => {
    let disposed = false;
    const restore = () => {
      if (disposed) return;
      try { setActive(readActiveProject(window.sessionStorage)); } catch { setActive(null); }
    };
    queueMicrotask(restore);
    window.addEventListener(ACTIVE_PROJECT_EVENT, restore);
    window.addEventListener('storage', restore);
    return () => {
      disposed = true;
      window.removeEventListener(ACTIVE_PROJECT_EVENT, restore);
      window.removeEventListener('storage', restore);
    };
  }, []);
  return active;
}
