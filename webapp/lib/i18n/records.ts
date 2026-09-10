import { translateText, type Locale } from './core.ts';
import { recordTitle } from '../ui-language.ts';
import type { SavedSummary } from '../local-library';

/** User-assigned names are data, not translation keys. Old source records stay untouched. */
export function localizedRecordTitle(record: SavedSummary, locale: Locale): string {
  if (!record.mode) return record.label;
  if (record.dataset_id === 'design_evaluation') return locale === 'en'
    ? `${record.region_count} ${record.region_count === 1 ? 'region' : 'regions'} · ${record.label} · evaluated coordinates`
    : `${record.region_count}个区域 · ${record.label} · 已评价坐标`;
  return translateText(recordTitle(record), locale);
}

/** Both languages remain searchable without changing selection when locale changes. */
export function recordSearchText(record: SavedSummary): string {
  const masks = record.request?.mask_codes ?? [];
  const synonyms = [
    masks.some((m) => ['PL', 'PR', 'AL', 'AR'].includes(m)) ? 'ear around-ear ear-surround periauricular' : '',
    masks.some((m) => ['FL', 'FM', 'FR'].includes(m)) ? 'forehead frontal' : '',
    masks.some((m) => ['OL', 'OR'].includes(m)) ? 'eye orbital periocular' : '',
  ];
  return [recordTitle(record), record.label, record.id, localizedRecordTitle(record, 'en'), localizedRecordTitle(record, 'zh-CN'), ...synonyms].join(' ').toLowerCase();
}
