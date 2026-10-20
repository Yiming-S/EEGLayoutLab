import { parseAR, methodLink } from './lab-workflow.ts';
import { safeReturnHref } from './ui-language.ts';

// First publication year and rights holders confirmed by the project owner.
export const COPYRIGHT_NOTICE = '© 2026 Yiming Shen & Yi Wang';
export const COPYRIGHT_SECTIONS = ['about-copyright', 'third-party-licenses'] as const;
export type CopyrightSection = (typeof COPYRIGHT_SECTIONS)[number];

export const isCopyrightHash = (hash: string) =>
  COPYRIGHT_SECTIONS.some((id) => hash === '#' + id);

export function copyrightHref(pathname: string, search: string, section: CopyrightSection) {
  if (pathname === '/method') return '#' + section;
  const ar = parseAR(new URLSearchParams(search).get('ar'));
  const returnTo = safeReturnHref(pathname === '/guide' ? new URLSearchParams(search).get('returnTo') : pathname + search, '/?ar=' + ar);
  return methodLink(returnTo, ar, '#' + section);
}
