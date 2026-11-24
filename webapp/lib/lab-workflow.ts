import type { SavedSummary } from './local-library';
import type { ComputeResult } from './local-compute';
import { layoutHref } from './layout-page.ts';
export const REGION_COUNTS = [1, 2, 3, 4, 6];
export const AREA_CAPS = [60, 120, 180];
export const MANUAL_COMPUTE_DEFAULT = false;
export const METRICS = [
  { key: 'field_relative', label: '信号重建保留率', explanation: '两套布局各自重建同一无噪声目标场的重建解释率之比' },
  { key: 'sensitivity_tail', label: '幅度保留率（最差10%）', explanation: '逐源最大双极幅度比中，最低10%皮层面积权重的平均值' },
  { key: 'localization_relative', label: '相对定位评分', explanation: '定位误差评分按源面积取最低10%均值，再与标准布局比较；同时查看毫米误差' },
] as const;
export function parseAR(value: string | null) {
  const n = value === null || value.trim() === '' ? NaN : Number(value);
  return Number.isInteger(n) && n >= 10 && n <= 100 ? n : 90;
}
export function assessment(metrics: ComputeResult['metrics'], ar: number) {
  if (!metrics || METRICS.some((m) => metrics[m.key] == null || !Number.isFinite(metrics[m.key]))) return { state: 'undefined', limiting: [] as string[] };
  const limiting = METRICS.filter((m) => metrics[m.key]! < ar / 100).map((m) => m.label);
  return { state: limiting.length ? 'fail' : 'pass', limiting };
}
export function areaRows(records: SavedSummary[], domain: string, area: number) {
  return REGION_COUNTS.map((r) => records.find((row) => row.dataset_id === 'strict_area' && row.mode === domain && row.area_cap_cm2 === area && row.region_count === r));
}
export function minimumTestedArea(records: SavedSummary[], domain: string, r: number, ar: number) {
  return records.filter((row) => row.dataset_id === 'strict_area' && row.mode === domain && row.region_count === r && assessment(row.metrics, ar).state === 'pass')
    .sort((a, b) => a.area_cap_cm2! - b.area_cap_cm2!)[0];
}
export function areaConclusion(records: SavedSummary[], domain: string, r: number, ar: number) {
  const rows = AREA_CAPS.map((a) => areaRows(records, domain, a).find((row) => row?.region_count === r));
  if (rows.every((row) => !row)) return '暂无同协议可判断数据';
  const complete = rows.every((row) => row && assessment(row.metrics, ar).state !== 'undefined');
  const pass = minimumTestedArea(records, domain, r, ar);
  if (!complete) return pass ? `数据不完整；已知${pass.area_cap_cm2} cm²上限达标` : '数据不完整，不能判定整个已测范围';
  return pass ? `首个达标面积上限：${pass.area_cap_cm2} cm²` : '已测范围内未达标';
}
export function methodLink(returnHref: string, ar: number, hash = '') {
  return `/method?ar=${ar}&returnTo=${encodeURIComponent(returnHref)}${hash}`;
}
export function comparisonLink(record?: SavedSummary | null, ar = 90) {
  return record?.dataset_id === 'strict_area' ? `/findings?domain=${record.mode}&area=${record.area_cap_cm2}&r=${record.region_count}&ar=${ar}` : `/findings?ar=${ar}`;
}
/** A saved layout record opens on its layout's page. */
export function recordLink(record: SavedSummary, ar: number) { return layoutHref({ id: record.id }, ar); }
export function radiusDesignLink(record: SavedSummary, ar: number) {
  if (record.dataset_id === 'cache') return record.request ? `/design?saved=${record.id}&ar=${ar}` : null;
  // Area record opens read-only; creating a radius configuration requires a separate explicit action.
  return record.dataset_id === 'strict_area' ? `/design?from=${record.id}&ar=${ar}` : null;
}
