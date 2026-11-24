import { parseAR } from './lab-workflow.ts';
import { safeReturnHref } from './ui-language.ts';

export type DocumentationPage = 'guide' | 'method';

// Both documentation pages keep the original working page as their return target.
export function documentationHref(pathname: string, search: string, target: DocumentationPage, hash = '') {
  const q = new URLSearchParams(search);
  const ar = parseAR(q.get('ar'));
  const isDocumentation = pathname === '/guide' || pathname === '/method';
  const back = safeReturnHref(isDocumentation ? q.get('returnTo') : pathname + search, '/?ar=' + ar);
  const params = new URLSearchParams({ ar: String(ar), returnTo: back });
  return '/' + target + '?' + params.toString() + (hash ? '#' + hash.replace(/^#/, '') : '');
}

/** The method page's own sections (an index of the documentation). */
export const METHOD_CONTENTS = [
  ['method-model', '模型与指标'],
  ['method-details', '方法细节'],
  ['method-history', '历史研究与验证'],
  ['about-copyright', '关于与版权'],
] as const;
