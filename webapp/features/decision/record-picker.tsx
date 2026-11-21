'use client';
import { useMemo, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { localizedRecordTitle, recordSearchText } from '@/lib/i18n/records';
import type { SavedSummary } from '@/lib/local-library';
import { protocolName } from '@/lib/ui-language';

/**
 * One comparison slot: a text filter over the saved records and a select grouped by
 * protocol. Records sharing a title are told apart by date and code version; the
 * current choice stays listed whatever the filter.
 */
export function RecordPicker({ label, records, value, exclude, onChange }: {
  label: string; records: SavedSummary[]; value: string; exclude: string; onChange: (id: string) => void;
}) {
  const { tx, locale, date } = useLanguage();
  const [query, setQuery] = useState('');
  const titled = useMemo(() => {
    const rows = records.map(record => ({ record, title: localizedRecordTitle(record, locale), search: recordSearchText(record) }));
    const counts = new Map<string, number>();
    for (const row of rows) counts.set(row.title, (counts.get(row.title) ?? 0) + 1);
    return rows.map(row => ({ ...row, title: (counts.get(row.title) ?? 0) < 2 ? row.title : [row.title,
      row.record.finished_at ? date(row.record.finished_at, true) : row.record.id.slice(0, 8),
      ...(row.record.dataset_id === 'cache' && !row.record.compatible ? [tx('旧版本记录 · 仅供查阅')] : [])].join(' · ') }));
  }, [records, locale, date, tx]);
  const needle = query.trim().toLowerCase();
  const visible = titled.filter(row => row.record.id === value || !needle || row.search.includes(needle) || row.title.toLowerCase().includes(needle));
  const groups = new Map<string, typeof visible>();
  for (const row of visible) groups.set(row.record.dataset_id, [...(groups.get(row.record.dataset_id) ?? []), row]);
  return <fieldset className="lab-label min-w-0">
    <legend>{label}</legend>
    <input type="search" className="lab-select mt-2" aria-label={`${label} · ${tx('筛选记录')}`} placeholder={tx('筛选：部位、区域数、名称或编号')}
      value={query} onChange={event => setQuery(event.target.value)} />
    <select className="lab-select mt-2" aria-label={label} value={value} onChange={event => onChange(event.target.value)}>
      <option value="">{tx('选择已计算布局')}</option>
      {[...groups].map(([dataset, rows]) => <optgroup key={dataset} label={tx(protocolName(dataset))}>
        {rows.map(row => <option key={row.record.id} value={row.record.id} disabled={row.record.id === exclude}>{row.title}</option>)}
      </optgroup>)}
    </select>
    {needle && <span className="mt-1 block text-xs font-normal text-muted-foreground">{tx(`匹配${visible.length}条记录`)}</span>}
  </fieldset>;
}
