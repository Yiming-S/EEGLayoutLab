'use client';
import { useMemo, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { localizedRecordTitle, recordSearchText } from '@/lib/i18n/records';
import type { SavedSummary } from '@/lib/local-library';
import { evaluationLabels, groupByLayout } from '@/lib/layout-page';
import { protocolName } from '@/lib/ui-language';
import { locationsFor } from '@/lib/records-catalog';
import { matchesSearch, parseSearch, searchTarget, unmatchedWords } from '@/lib/library-search';

/**
 * One comparison slot, chosen in two steps: a layout (records sharing coordinates
 * are one choice, named by their nominal evaluation), then the evaluation condition
 * when the layout was evaluated under more than one. Layouts sharing a title are told
 * apart by date and code version; the current choice stays listed whatever the filter.
 */
export function RecordPicker({ label, records, value, exclude, onChange }: {
  label: string; records: SavedSummary[]; value: string; exclude: string; onChange: (id: string) => void;
}) {
  const { tx, locale, date } = useLanguage();
  const [query, setQuery] = useState('');
  const layouts = useMemo(() => {
    const rows = groupByLayout(records).map(group => ({ group, primary: group[0], title: localizedRecordTitle({ ...group[0], evaluation_condition: undefined }, locale) }));
    const counts = new Map<string, number>();
    for (const row of rows) counts.set(row.title, (counts.get(row.title) ?? 0) + 1);
    return rows.map(row => ({ ...row, title: (counts.get(row.title) ?? 0) < 2 ? row.title : [row.title,
      row.primary.finished_at ? date(row.primary.finished_at, true) : row.primary.id.slice(0, 8),
      ...(row.primary.dataset_id === 'cache' && !row.primary.compatible ? [tx('旧版本记录 · 仅供查阅')] : [])].join(' · '),
      target: searchTarget([...row.group.map(recordSearchText), row.title],
        { regionCount: row.primary.region_count, locations: locationsFor(row.primary), ids: row.group.map(record => record.id) }) }));
  }, [records, locale, date, tx]);
  const chosen = layouts.find(row => row.group.some(record => record.id === value));
  const words = useMemo(() => parseSearch(query), [query]);
  const visible = layouts.filter(row => row === chosen || matchesSearch(row.target, words));
  const misses = unmatchedWords(words, layouts.map(row => row.target));
  const groups = new Map<string, typeof visible>();
  for (const row of visible) groups.set(row.primary.dataset_id, [...(groups.get(row.primary.dataset_id) ?? []), row]);
  // The chosen layout's option carries the chosen record, so the select's value is that record.
  const optionValue = (row: (typeof layouts)[number]) => row === chosen ? value : (row.group.find(record => record.id !== exclude) ?? row.primary).id;
  return <fieldset className="lab-label min-w-0">
    <legend>{label}</legend>
    <input type="search" className="lab-select mt-2" aria-label={`${label} · ${tx('筛选记录')}`} placeholder={tx('筛选：部位、区域数、名称或编号')}
      value={query} onChange={event => setQuery(event.target.value)} />
    {words.length > 0 && visible.every(row => row === chosen) && <p className="mt-1 text-xs text-muted-foreground">
      {misses.length ? <>{tx('没有布局包含：')}{misses.map(word => `“${word}”`).join(' ')}</> : tx('没有布局同时符合全部查找词。')}</p>}
    <select className="lab-select mt-2" aria-label={label} value={chosen ? value : ''} onChange={event => onChange(event.target.value)}>
      <option value="">{tx('选择已计算布局')}</option>
      {[...groups].map(([dataset, rows]) => <optgroup key={dataset} label={tx(protocolName(dataset))}>
        {rows.map(row => <option key={row.primary.id} value={optionValue(row)} disabled={row.group.every(record => record.id === exclude)}>
          {row.title}{row.group.length > 1 ? ` · ${tx(`共${row.group.length}种条件`)}` : ''}
        </option>)}
      </optgroup>)}
    </select>
    {chosen && chosen.group.length > 1 && <select className="lab-select mt-2" aria-label={`${label} · ${tx('评价条件')}`} value={value} onChange={event => onChange(event.target.value)}>
      {chosen.group.map(record => <option key={record.id} value={record.id} disabled={record.id === exclude}>
        {evaluationLabels(record).map(text => tx(text)).join(' · ')}{record.finished_at ? ` · ${date(record.finished_at, true)}` : ''}
      </option>)}
    </select>}
    {words.length > 0 && <span className="mt-1 block text-xs font-normal text-muted-foreground">{tx(`匹配${visible.length}个布局`)}</span>}
  </fieldset>;
}
