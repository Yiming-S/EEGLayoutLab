import type { SavedSummary } from '../../lib/local-library';
import type { Locale } from '../../lib/i18n/core';
import { localizedRecordTitle, recordSearchText } from '../../lib/i18n/records.ts';
import { groupByLayout } from '../../lib/layout-page.ts';
import { locationsFor } from '../../lib/records-catalog.ts';
import { matchesSearch, parseSearch, searchTarget, unmatchedWords } from '../../lib/library-search.ts';

/** The options and search facts used by both comparison slots. */
export function recordPickerChoices(records: SavedSummary[], locale: Locale,
  tx: (text: string) => string, date: (value: string, time?: boolean) => string) {
  const rows = groupByLayout(records).map(group => ({ group, primary: group[0],
    title: localizedRecordTitle({ ...group[0], evaluation_condition: undefined }, locale) }));
  const counts = new Map<string, number>();
  for (const row of rows) counts.set(row.title, (counts.get(row.title) ?? 0) + 1);
  return rows.map(row => ({ ...row, title: (counts.get(row.title) ?? 0) < 2 ? row.title : [row.title,
    row.primary.finished_at ? date(row.primary.finished_at, true) : row.primary.id.slice(0, 8),
    ...(row.primary.dataset_id === 'cache' && !row.primary.compatible ? [tx('旧版本记录 · 仅供查阅')] : [])].join(' · '),
    target: searchTarget([...row.group.map(recordSearchText), row.title],
      { regionCount: row.primary.region_count, electrodeCount: row.primary.status === 'completed' ? 64 : null,
        locations: locationsFor(row.primary), ids: row.group.map(record => record.id) }) }));
}

/** Keep a selected option available without counting it as a search hit. */
export function filterRecordPickerChoices(layouts: ReturnType<typeof recordPickerChoices>, query: string, value: string) {
  const chosen = layouts.find(row => row.group.some(record => record.id === value));
  const words = parseSearch(query);
  const matched = layouts.filter(row => matchesSearch(row.target, words));
  const visible = layouts.filter(row => row === chosen || matchesSearch(row.target, words));
  return { chosen, words, matched, visible, misses: unmatchedWords(words, layouts.map(row => row.target)) };
}
