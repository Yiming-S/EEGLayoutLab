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

export const METHOD_CONTENTS = [
  ['simulation-model', '脑源、头模与信号生成'],
  ['simulation-forward', '组织传播与导联场 H'],
  ['simulation-sources', '4096、256与当前模拟源'],
  ['simulation-comparison', '标准64导与布局对照'],
  ['retention-guide', '三项指标与计算公式'],
  ['simulation-artifacts', '噪声、心电与眼电干扰'],
  ['local-compute', '布局搜索与缓存规则'],
  ['planned-validation', '历史实验与后续验证'],
  ['method-references', '参考文献与模型来源'],
] as const;
