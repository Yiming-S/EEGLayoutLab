import type { SavedRecord, SavedSummary } from './local-library';
import { canSimulateRecord } from './local-library.ts';
import { radiusDesignLink, parseAR } from './lab-workflow.ts';
import { safeReturnHref, type PageId } from './ui-language.ts';
import { documentationHref } from './documentation.ts';
import { decisionHref, parseDecisionThresholds } from './design-decision.ts';

export type WorkspaceGroup = 'results' | 'design' | 'reception' | 'docs';
export type LayoutPhase = 'saved' | 'draft' | 'edited';
export type WorkspaceSelection = {
  id: string | null;
  phase: LayoutPhase;
  channels?: number;
  regions?: number;
};
export const WORKSPACES = [
  { id: 'results', label: '结果库' },
  { id: 'design', label: '布局设计' },
  { id: 'reception', label: '信号仿真' },
  { id: 'docs', label: '文档' },
] as const;
export const WORKSPACE_TABS = {
  results: [
    ['compare', '实验总览'],
    ['library', '布局记录'],
    ['decision', '方案对比'],
  ],
  design: [
    ['design', '区域设计'],
    ['electrodes', '电极编辑'],
    ['coordinates', '坐标导入'],
  ],
  reception: [],
  docs: [
    ['guide', '使用指南'],
    ['method', '建模与原理'],
  ],
} as const;
export function workspaceGroup(page: PageId): WorkspaceGroup {
  if (['design', 'electrodes', 'coordinates'].includes(page)) return 'design';
  if (page === 'reception') return 'reception';
  if (page === 'guide' || page === 'method') return 'docs';
  return 'results';
}
export function canCompareRecord(r: SavedSummary) {
  return (
    r.status === 'completed' &&
    ['strict_area', 'cache', 'design_evaluation'].includes(r.dataset_id)
  );
}
export function workingHref(href: string) {
  const url = new URL(href, 'http://localhost');
  return url.origin === 'http://localhost' &&
    ['/guide', '/method'].includes(url.pathname)
    ? safeReturnHref(url.searchParams.get('returnTo'), '/')
    : safeReturnHref(href, '/');
}
export function routeSelection(href: string): WorkspaceSelection {
  const url = new URL(workingHref(href), 'http://localhost'),
    q = url.searchParams;
  const raw =
    q.get('layoutRecord') ??
    (url.pathname === '/electrodes'
      ? q.get('parent')
      : url.pathname === '/decision' || url.pathname === '/coordinates'
        ? q.get('a')
        : url.pathname === '/design'
          ? (q.get('saved') ?? q.get('from'))
          : q.get('record'));
  const count = (key: string, maximum: number) => {
    const value = q.get(key),
      n = Number(value);
    return value !== null &&
      value !== '' &&
      Number.isInteger(n) &&
      n >= 0 &&
      n <= maximum
      ? n
      : undefined;
  };
  return {
    id: raw && /^[a-f0-9]{64}$/.test(raw) ? raw : null,
    channels: count('layoutChannels', 64),
    regions: count('layoutRegions', 6),
    phase:
      q.get('layoutState') === 'edited'
        ? 'edited'
        : q.get('layoutState') === 'saved'
          ? 'saved'
          : q.get('layoutState') === 'draft' || q.get('draft') === '1'
            ? 'draft'
            : 'saved',
  };
}
export function selectionHref(href: string, selection: WorkspaceSelection) {
  const url = new URL(href, 'http://localhost');
  url.searchParams.set('layoutRecord', selection.id ?? '');
  url.searchParams.set('layoutState', selection.phase);
  for (const [key, value] of [
    ['layoutChannels', selection.channels],
    ['layoutRegions', selection.regions],
  ] as const) {
    if (value == null) url.searchParams.delete(key);
    else url.searchParams.set(key, String(value));
  }
  return url.pathname + url.search + url.hash;
}
export function layoutCapabilities(
  record: SavedRecord | null,
  selection: WorkspaceSelection,
) {
  const current =
    selection.phase === 'saved' &&
    record?.id === selection.id &&
    record.status === 'completed' &&
    record.layout?.xyzMm.length === 64;
  return {
    design: !!current && !!radiusDesignLink(record, 90),
    edit:
      !!current &&
      ['strict_area', 'cache'].includes(record.dataset_id) &&
      !!record.layout?.regionPatchVertexIndices?.length,
    compare: !!current && canCompareRecord(record),
    reception: !!current && canSimulateRecord(record),
  };
}
export function workingPage(href: string): PageId {
  const path = new URL(workingHref(href), 'http://localhost').pathname;
  return (
    (
      {
        '/': 'compare',
        '/library': 'library',
        '/design': 'design',
        '/electrodes': 'electrodes',
        '/coordinates': 'coordinates',
        '/decision': 'decision',
        '/reception': 'reception',
      } as Record<string, PageId>
    )[path] ?? 'results'
  );
}
export function workspaceLinks(
  here: string,
  ar: number,
  record: SavedRecord | null,
  selection: WorkspaceSelection,
) {
  const url = new URL(here, 'http://localhost'),
    work = workingHref(here),
    source = new URL(work, url);
  const capabilities = layoutCapabilities(record, selection);
  const decisionParameters = new URLSearchParams(source.searchParams);
  decisionParameters.set('ar', String(ar));
  const decision = parseDecisionThresholds(decisionParameters);
  const comparisonParameters = new URL(decisionHref([], decision), url).searchParams;
  const origin = safeReturnHref(source.searchParams.get('returnTo'), work),
    originUrl = new URL(origin, url);
  const results = new URLSearchParams({ ar: String(ar) });
  for (const key of [
    'domain',
    'area',
    'r',
    'metric',
    'record',
    'filter',
    'regions',
    'q',
    'page',
    'sort',
    'history',
    'kind',
    'electrodes',
    'location',
  ]) {
    const value =
      source.searchParams.get(key) ?? originUrl.searchParams.get(key);
    if (value !== null) results.set(key, value);
  }
  if (selection.id) results.set('record', selection.id);
  if (!results.has('domain') && record?.dataset_id === 'strict_area') {
    results.set('domain', record.mode);
    results.set('area', String(record.area_cap_cm2));
    results.set('r', String(record.region_count));
  }
  const links: Record<PageId, string> = {
    compare: '/?' + results,
    library: '/library?' + results,
    results: '/results?ar=' + ar,
    design: capabilities.design
      ? radiusDesignLink(record!, ar)!
      : '/design?ar=' + ar,
    electrodes: capabilities.edit
      ? '/electrodes?parent=' + selection.id + '&ar=' + ar
      : '/electrodes?ar=' + ar,
    decision: decisionHref(capabilities.compare ? [selection.id!] : [], decision),
    coordinates: capabilities.compare
      ? decisionHref([selection.id!], decision).replace('/decision?', '/coordinates?')
      : decisionHref([], decision).replace('/decision?', '/coordinates?'),
    reception: capabilities.reception
      ? '/reception?record=' + selection.id + '&ar=' + ar
      : '/reception?ar=' + ar,
    guide: documentationHref(url.pathname, url.search, 'guide'),
    method: documentationHref(url.pathname, url.search, 'method'),
  };
  for (const page of [
    'design',
    'electrodes',
    'decision',
    'coordinates',
    'reception',
  ] as const) {
    const target = new URL(links[page], url);
    // These are passive comparison controls on other tools. They never enter
    // a layout or signal request, but survive a return to the comparison.
    for (const key of ['thresholdMode', 'sensitivity', 'localization', 'p90']) {
      const value = comparisonParameters.get(key);
      if (value === null) target.searchParams.delete(key);
      else target.searchParams.set(key, value);
    }
    target.searchParams.set('returnTo', origin);
    links[page] = target.pathname + target.search;
  }
  // Documentation is an excursion from a working page, not a fresh task.
  if (url.pathname === '/guide' || url.pathname === '/method')
    links[workingPage(here)] = work;
  return links;
}

export function navigationAR(href: string) {
  return parseAR(new URL(href, 'http://localhost').searchParams.get('ar'));
}
