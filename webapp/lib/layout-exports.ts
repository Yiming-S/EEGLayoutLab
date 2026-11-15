import type { SavedRecord } from './local-library';
import { designCSV, exportDesign, type ElectrodeDesign } from './design-decision.ts';
import { assessment } from './lab-workflow.ts';
import type { Locale } from './i18n/core.ts';
import catalog from './i18n/export-refresh-catalog.json' with { type: 'json' };

export type LayoutExportKind = 'coordinates_csv' | 'design_json' | 'result_json' | 'report_md' | 'bundle_json';
export type ExportFile = { filename: string; content: string; mime: string };
export type ReproducibilityBundle = {
  schema: 'eeg-reproducibility-bundle/1'; record_id: string; record: SavedRecord;
  [key: string]: unknown;
};
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const fileId = (id: string) => id.replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 12) || 'record';
const json = (value: unknown) => JSON.stringify(value, null, 2) + '\n';
const plain = (value: string) => value.replace(/[\r\n|]/g, ' ').replace(/[\\`*_{}[\]<>]/g, '\\$&');

/** Read-only serialization. Coordinates are never repaired, reordered or padded. */
export function layoutExportAvailability(record: SavedRecord): { design: ElectrodeDesign | null; reason: string | null } {
  if (record.status !== 'completed' || !record.layout) return { design: null, reason: catalog.exports_no_layout.source };
  try { return { design: exportDesign(record), reason: null }; }
  catch { return { design: null, reason: catalog.exports_bad_design.source }; }
}

export function layoutSummaryMarkdown(record: SavedRecord, ar: number, locale: Locale = 'zh-CN', generatedAt = new Date().toISOString()) {
  const t = (key: keyof typeof catalog) => locale === 'en' ? catalog[key].en : catalog[key].source;
  const missing = t('exports_unknown');
  const percent = (value: unknown) => finite(value) ? `${(100 * value).toFixed(2)}%` : missing;
  const number = (value: unknown, unit = '') => finite(value) ? `${value.toFixed(2)}${unit ? ' ' + unit : ''}` : missing;
  const thresholdValid = finite(ar) && ar > 0 && ar <= 100;
  const state = record.status === 'completed' && thresholdValid ? assessment(record.metrics, ar).state : 'undefined';
  const decision = t(state === 'pass' ? 'exports_pass' : state === 'fail' ? 'exports_fail' : 'exports_unknown');
  const row = (key: keyof typeof catalog, value: string) => `| ${t(key)} | ${value} |`;
  const m = record.metrics;
  return [
    `# ${t('exports_report_title')}`, '', t('exports_report_basis'), '',
    `- ${t('exports_report_time')}: ${plain(generatedAt)}`,
    `- ${t('exports_record_name')}: ${plain(record.label)}`,
    `- ${t('exports_record_id')}: ${plain(record.id)}`,
    `- ${t('exports_dataset')}: ${plain(record.dataset_id)}`,
    `- ${t('exports_status')}: ${plain(record.status)}`,
    `- ${t('exports_saved')}: ${record.finished_at ? plain(record.finished_at) : missing}`, '',
    `## ${t('exports_geometry')}`, '',
    `- ${t('exports_count')}: ${record.layout?.xyzMm.length ?? missing}`,
    `- ${t('exports_regions')}: ${record.region_count}`,
    `- ${t('exports_frame')}: ${record.layout ? t('exports_frame_value') : missing}`,
    `- ${t('exports_region_area')}: ${number(record.geometry?.union_area_cm2, 'cm²')}`,
    `- ${t('exports_area_cap')}: ${number(record.area_cap_cm2, 'cm²')}`,
    `- ${t('exports_radius_cap')}: ${number(record.radius_cap_mm, 'mm')}`,
    `- ${t('exports_spacing')}: ${number(record.spacing_mm, 'mm')}`, '',
    `## ${t('exports_metrics')}`, '',
    `- ${t('exports_requirement')}: ${thresholdValid ? `${ar}%` : missing}`,
    `- ${t('exports_assessment')}: ${decision}`, '', t('exports_rule'), '',
    `| ${t('exports_metric_column')} | ${t('exports_value_column')} |`, '| --- | ---: |',
    row('exports_field', percent(m?.field_relative)),
    row('exports_sensitivity', percent(m?.sensitivity_tail)),
    row('exports_localization', percent(m?.localization_relative)),
    row('exports_absolute', percent(m?.field_absolute)),
    row('exports_baseline_absolute', percent(m?.reference_field_absolute)),
    row('exports_median', number(m?.median_mm, 'mm')),
    row('exports_p90', number(m?.p90_mm, 'mm')),
    row('exports_baseline_median', number(m?.reference_median_mm, 'mm')), '',
    t('exports_metric_scope'), '', `## ${t('exports_provenance')}`, '', t('exports_provenance_note'), '',
    // Four-backtick fences keep any literal triple-backtick source strings inside the data block.
    '````json', json(record.provenance).trimEnd(), '````', '',
    `### ${t('exports_request')}`, '', '````json', json(record.request).trimEnd(), '````', '',
  ].join('\n');
}

export function layoutExportFile(record: SavedRecord, kind: Exclude<LayoutExportKind, 'bundle_json'>, ar: number, locale: Locale = 'zh-CN'): ExportFile {
  const stem = `eeg-${fileId(record.id)}`;
  if (kind === 'result_json') return { filename: `${stem}-result.json`, mime: 'application/json', content: json(record) };
  if (kind === 'report_md') return { filename: `${stem}-report-${locale}.md`, mime: 'text/markdown;charset=utf-8', content: layoutSummaryMarkdown(record, ar, locale) };
  const { design, reason } = layoutExportAvailability(record);
  if (!design) throw new Error(reason ?? catalog.exports_bad_design.source);
  return kind === 'coordinates_csv'
    ? { filename: `${stem}-coordinates.csv`, mime: 'text/csv;charset=utf-8', content: designCSV(design) + '\n' }
    : { filename: `${stem}-layout.json`, mime: 'application/json', content: json(design) };
}

/** Invoked only by the export click handler. This endpoint packages existing records. */
export async function fetchReproducibilityBundle(record: SavedRecord, fetcher: typeof fetch = fetch, signal?: AbortSignal): Promise<ExportFile> {
  if (!/^[a-f0-9]{64}$/.test(record.id)) throw new Error(catalog.exports_invalid_id.source);
  const annotation = record.electrode_annotation?.id;
  const response = await fetcher(`/api/local-compute/library/${record.id}/bundle${annotation ? '?annotation_id=' + encodeURIComponent(annotation) : ''}`, { method: 'GET', cache: 'no-store', signal });
  if (!response.ok) throw new Error(catalog.exports_bundle_failed.source);
  const value: unknown = await response.json();
  if (!value || typeof value !== 'object') throw new Error(catalog.exports_bundle_mismatch.source);
  const bundle = value as ReproducibilityBundle;
  if (bundle.schema !== 'eeg-reproducibility-bundle/1' || bundle.record_id !== record.id ||
      bundle.record?.id !== record.id || bundle.record?.dataset_id !== record.dataset_id) throw new Error(catalog.exports_bundle_mismatch.source);
  return { filename: `eeg-${fileId(record.id)}-reproducibility.json`, mime: 'application/json', content: json(bundle) };
}
