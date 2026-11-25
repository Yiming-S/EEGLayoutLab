'use client';
import { useEffect, useState } from 'react';
import type { DocsSite } from '@/lib/method-index';
import { apiFetch } from '@/client/task-client';

/**
 * Whether this host serves the built documentation under /docs/: the local service
 * does once `mkdocs build` has run, and the website publishes it beside the showcase
 * (.github/workflows/pages.yml). Otherwise links go to GitHub.
 */
export function useDocsSite(): DocsSite {
  const [site, setSite] = useState<DocsSite>('github');
  useEffect(() => {
    const controller = new AbortController();
    apiFetch('/docs/', { method: 'HEAD', cache: 'no-store', signal: controller.signal })
      .then(response => { if (response.ok && (response.headers.get('content-type') ?? '').startsWith('text/html')) setSite('local'); })
      .catch(() => {});
    return () => controller.abort();
  }, []);
  return site;
}
