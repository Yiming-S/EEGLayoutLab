'use client';
import { useEffect, useMemo, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { apiJson } from '@/client/task-client';
import { exportDesign, type ElectrodeDesign } from '@/lib/design-decision';
import { localizedRecordTitle } from '@/lib/i18n/records';
import { groupByLayout } from '@/lib/layout-page';
import type { LocalLibrary, SavedRecord } from '@/lib/local-library';

const STUDY_SOURCES = ['strict_area', 'cache', 'design_evaluation'];

/** A study's coordinates taken from a saved layout: one choice per layout, nominal record named. */
export function RecordDesignPicker({ disabled, onChoose }: { disabled?: boolean; onChoose: (design: ElectrodeDesign) => void }) {
  const { tx, locale } = useLanguage();
  const [library, setLibrary] = useState<LocalLibrary['records'] | null>(null), [error, setError] = useState(''), [reading, setReading] = useState(false);
  const [value, setValue] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    apiJson<LocalLibrary>('/api/local-compute/library', { signal: controller.signal, errorMessage: '方案目录暂时无法读取，请稍后重试。' })
      .then(data => setLibrary(data.records))
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '方案目录暂时无法读取，请稍后重试。'); });
    return () => controller.abort();
  }, []);
  const layouts = useMemo(() => groupByLayout((library ?? []).filter(record => record.status === 'completed' && record.layout_key && STUDY_SOURCES.includes(record.dataset_id)))
    .map(group => group[0]), [library]);
  const choose = async (id: string) => {
    setValue(id); setError('');
    if (!id) return;
    setReading(true);
    try {
      const { record } = await apiJson<{ record: SavedRecord }>('/api/local-compute/library/' + id, { errorMessage: '方案读取失败或完整性校验未通过' });
      const design = exportDesign(record);
      if (design.xyz_mm.length !== 64) throw new Error('稳健性研究只接受64电极布局');
      onChoose({ ...design, name: localizedRecordTitle({ ...record, evaluation_condition: undefined }, locale) });
    } catch (reason) { setError(reason instanceof Error ? reason.message : '方案读取失败或完整性校验未通过'); setValue(''); }
    finally { setReading(false); }
  };
  return <label className="lab-label">
    {tx('从已保存布局选择')}
    <select className="lab-select mt-2" value={value} disabled={disabled || reading || !library} onChange={event => void choose(event.target.value)}>
      <option value="">{tx(library ? '选择已保存布局' : '读取方案目录…')}</option>
      {layouts.map(record => <option key={record.id} value={record.id}>{localizedRecordTitle({ ...record, evaluation_condition: undefined }, locale)}</option>)}
    </select>
    {reading && <span className="mt-1 block text-xs font-normal text-muted-foreground">{tx('读取所选方案的坐标与指标…')}</span>}
    {error && <span role="alert" className="mt-1 block text-xs font-normal text-danger"><RuntimeMessage message={error} /></span>}
  </label>;
}
