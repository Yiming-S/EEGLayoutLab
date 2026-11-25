import { translateText, type Locale } from './core.ts';
import { labelNamesEvaluation, labelNamesRegions, recordAllocationLabel, recordBaseTitle, recordConditionLabels, recordElectrodeLabel, recordNoiseLabel, recordObjectiveLabel, recordTitle } from '../ui-language.ts';
import type { SavedSummary } from '../local-library';
import type { EditorRecord } from '../electrode-editor';

/** User-assigned names are data, not translation keys. Old source records stay untouched. */
export function localizedRecordTitle(record: SavedSummary, locale: Locale): string {
  if (!record.mode) return record.label;
  if (record.dataset_id === 'design_evaluation') {
    const count = labelNamesRegions(record.label, record.region_count) ? [] : [locale === 'en'
      ? `${record.region_count} ${record.region_count === 1 ? 'region' : 'regions'}` : `${record.region_count}个区域`];
    return [...count, record.label, ...(labelNamesEvaluation(record.label) ? [] : [locale === 'en' ? 'evaluated coordinates' : '已评价坐标']),
      ...recordConditionLabels(record).map(label => translateText(label, locale))].join(' · ');
  }
  const noise = recordNoiseLabel(record);
  const allocation = recordAllocationLabel(record);
  const objective = recordObjectiveLabel(record);
  const electrodes = recordElectrodeLabel(record);
  return [translateText(recordBaseTitle(record), locale), ...(noise ? [translateText(noise, locale)] : []),
    ...(allocation ? [translateText(allocation, locale)] : []),
    ...(objective ? [translateText(objective, locale)] : []),
    ...(electrodes ? [translateText(electrodes, locale)] : [])].join(' · ');
}

/** Use parent metadata for system titles; unknown names remain original data. */
export function localizedEditorParentTitle(
  record: Pick<EditorRecord, 'parent_id' | 'parent_label'>,
  parents: SavedSummary[],
  locale: Locale,
) {
  const parent = parents.find((row) => row.id === record.parent_id);
  return parent ? localizedRecordTitle(parent, locale) : record.parent_label;
}

/** Both languages remain searchable without changing selection when locale changes. The id is searched separately (lib/library-search.ts). */
export function recordSearchText(record: SavedSummary): string {
  const masks = record.request?.mask_codes ?? [];
  const synonyms = [
    masks.some((m) => ['PL', 'PR'].includes(m)) ? 'ear behind-ear postauricular' : '',
    masks.some((m) => ['AL', 'AR'].includes(m)) ? 'ear around-ear ear-surround periauricular' : '',
    masks.some((m) => ['FL', 'FM', 'FR'].includes(m)) ? 'forehead frontal' : '',
    masks.some((m) => ['OL', 'OR'].includes(m)) ? 'eye orbital periocular' : '',
  ];
  return [recordTitle(record), record.label, localizedRecordTitle(record, 'en'), localizedRecordTitle(record, 'zh-CN'), ...synonyms].join(' ').toLowerCase();
}
