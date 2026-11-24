import type { SavedSummary } from './local-library';
import { conductivityScenarioLabel, dataPriorLabel, noiseModelLabel } from '../contracts/scientific-options.mjs';

// Display vocabulary only: preserve calculation keys, record IDs and raw data.
export const metricPercent = (value: number | null | undefined, missing = '尚未计算') =>
  value === undefined ? missing : value === null || !Number.isFinite(value) ? '指标无法计算' : `${(value * 100).toFixed(2)}%`;
export const metricDistance = (value: number | null | undefined) =>
  value === undefined ? '尚未计算' : value === null || !Number.isFinite(value) ? '指标无法计算' : `${value.toFixed(2)} mm`;
export const PAGES = [
  { id: 'home', path: '/', label: '工作区' },
  { id: 'findings', path: '/findings', label: '总面积研究' },
  { id: 'library', path: '/library', label: '布局列表' },
  { id: 'layout', path: '/layout', label: '布局详情' },
  { id: 'design', path: '/design', label: '区域设计' },
  { id: 'coordinates', path: '/coordinates', label: '坐标导入' },
  { id: 'electrodes', path: '/electrodes', label: '电极编辑' },
  { id: 'decision', path: '/decision', label: '方案对比' },
  { id: 'robustness', path: '/robustness', label: '稳健性研究' },
  { id: 'reception', path: '/reception', label: '信号仿真' },
  { id: 'channels', path: '/channels', label: '通道子集' },
  { id: 'projects', path: '/projects', label: '研究项目' },
  { id: 'results', path: '/results', label: '历史批次' },
  { id: 'guide', path: '/guide', label: '使用指南' },
  { id: 'method', path: '/method', label: '建模与原理' },
] as const;
export type PageId = (typeof PAGES)[number]['id'];
export const MASK_NAMES: Record<string, string> = {
  PL: '左耳后邻近区', PR: '右耳后邻近区', AL: '左耳周扩展区', AR: '右耳周扩展区',
  FL: '左前额', FM: '中部前额', FR: '右前额', OL: '左眶周上外侧', OR: '右眶周上外侧',
};
export const DOMAIN_NAMES = { whole: '全头候选区', lowHair: '少毛发候选区（模型近似）' };
export function protocolName(id: string) {
  if (id === 'design_evaluation') return '已评价坐标布局';
  if (id === 'historical_area') return '历史面积实验（原坐标范围）';
  return id === 'strict_area' ? '总面积上限约束实验' : id === 'cache' ? '每区半径约束计算' : '历史半径实验（区域可相交）';
}
/**
 * A coordinate evaluation's label is often an earlier title: it starts with its region
 * count ("2区 · …") or ends with "已评价坐标". The title then states neither twice.
 */
export function labelNamesRegions(label: string, count: number) {
  return new RegExp(`^\\s*${count}\\s*(区|个区域|regions?\\b)`, 'i').test(label);
}
export function labelNamesEvaluation(label: string) {
  return /(已评价坐标|evaluated coordinates)\s*$/i.test(label);
}
/** Title without the noise-model suffix, so each part matches its own translation. */
export function recordBaseTitle(record: SavedSummary) {
  if (record.dataset_id === 'design_evaluation') return [...(labelNamesRegions(record.label, record.region_count) ? [] : [`${record.region_count}个区域`]),
    record.label, ...(labelNamesEvaluation(record.label) ? [] : ['已评价坐标'])].join(' · ');
  if (record.dataset_id === 'offline_radius') return record.label;
  const masks = record.request?.mask_codes;
  const location = masks?.length ? masks.map((m) => MASK_NAMES[m] ?? m).join(' + ')
    : record.mode.includes('whole') ? DOMAIN_NAMES.whole : DOMAIN_NAMES.lowHair;
  const size = ['strict_area', 'historical_area'].includes(record.dataset_id)
    ? `总面积 ≤ ${record.area_cap_cm2} cm²`
    : `每区半径 ≤ ${record.radius_cap_mm ?? record.request?.radius_mm} mm`;
  return `${record.region_count}个区域 · ${location} · ${size}`;
}
export function recordNoiseLabel(record: SavedSummary) {
  if (['design_evaluation', 'offline_radius'].includes(record.dataset_id)) return '';
  // A data prior replaces the noise model and names its own noise.
  if (record.request?.data_prior) return dataPriorLabel(record.request.data_prior);
  return record.request?.noise_model ? noiseModelLabel(record.request.noise_model) : '';
}
/** The non-default evaluation conditions of a saved coordinate evaluation, one label each. */
export function recordConditionLabels(record: SavedSummary): string[] {
  const condition = record.dataset_id === 'design_evaluation' ? record.evaluation_condition : undefined;
  if (!condition) return [];
  return [
    ...(condition.noise_model ? [noiseModelLabel(condition.noise_model)] : []),
    ...(condition.conductivity_scenario ? [conductivityScenarioLabel(condition.conductivity_scenario)] : []),
    ...(condition.head_id ? [`头模：${condition.head_id}`] : []),
    ...(condition.data_prior ? [dataPriorLabel(condition.data_prior)] : []),
  ];
}
export function recordTitle(record: SavedSummary) {
  const noise = recordNoiseLabel(record);
  return [recordBaseTitle(record), ...(noise ? [noise] : []), ...recordConditionLabels(record)].join(' · ');
}
export function safeReturnHref(value: string | null | undefined, fallback: string) {
  if (!value?.startsWith('/') || value.startsWith('//')) return fallback;
  try {
    const url = new URL(value, 'http://localhost');
    const allowed = ['/', '/findings', '/layout', '/design', '/electrodes', '/decision', '/coordinates', '/library', '/reception', '/channels', '/robustness', '/results', '/pilot-results', '/projects'];
    if (url.origin !== 'http://localhost' || !allowed.includes(url.pathname)) return fallback;
    // A project sharing credential is consumed by its page, never forwarded as
    // navigation context or encoded into a documentation return query.
    if (new URLSearchParams(url.hash.slice(1)).has('access')) url.hash = '';
    return url.pathname + url.search + url.hash;
  } catch { return fallback; }
}
export const LIBRARY_FILTERS = ['all', 'current', 'strict_area', 'cache', 'offline_radius', 'historical_area', 'design_evaluation'] as const;
export function parseLibraryView(q: URLSearchParams) {
  const f = q.get('filter'), r = Number(q.get('regions')), p = Number(q.get('page'));
  return {
    filter: LIBRARY_FILTERS.includes(f as typeof LIBRARY_FILTERS[number]) ? f! : q.get('history') === '1' ? 'offline_radius' : 'all',
    region: [1, 2, 3, 4, 6].includes(r) ? r : 0,
    search: q.get('q') ?? '',
    page: Number.isInteger(p) && p > 0 ? p - 1 : 0,
  };
}
export function libraryViewLink(ar: number, id: string, view: { filter: string; region: number; search: string; page: number }) {
  const q = new URLSearchParams({ ar: String(ar) });
  if (id) q.set('record', id);
  if (view.filter !== 'all') q.set('filter', view.filter);
  if (view.filter === 'offline_radius') q.set('history', '1');
  if (view.region) q.set('regions', String(view.region));
  if (view.search) q.set('q', view.search);
  if (view.page) q.set('page', String(view.page + 1));
  return '/library?' + q.toString();
}
