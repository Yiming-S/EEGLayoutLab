'use client';
import { useEffect, useState } from 'react';
import { SHOWCASE } from '@/lib/showcase';
import type { DocsSite } from '@/lib/method-index';

/**
 * Whether this host serves the built documentation under /docs/ (the local
 * service does once `mkdocs build` has run); otherwise links go to GitHub.
 */
export function useDocsSite(): DocsSite {
  const [site, setSite] = useState<DocsSite>('github');
  useEffect(() => {
    if (SHOWCASE) return;
    const controller = new AbortController();
    fetch('/docs/', { method: 'HEAD', cache: 'no-store', signal: controller.signal })
      .then(response => { if (response.ok && (response.headers.get('content-type') ?? '').startsWith('text/html')) setSite('local'); })
      .catch(() => {});
    return () => controller.abort();
  }, []);
  return site;
}
