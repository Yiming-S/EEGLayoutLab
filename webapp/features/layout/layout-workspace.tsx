'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { SiteHeader } from '@/components/site-header';
import { SavedLayoutContent } from '@/components/saved-layout-details';
import { OutcomeBadge, type Outcome } from '@/components/retention-bar';
import { ThresholdSlider } from '@/components/threshold-slider';
import { TermHint } from '@/components/term-hint';
import { Button, buttonVariants } from '@/components/ui/button';
import { apiJson } from '@/client/task-client';
import { CoordinateStudyLink } from '@/features/robustness/coordinate-study-link';
import { exportDesign, decisionHref, jointDecisionThresholds } from '@/lib/design-decision';
import { localizedRecordTitle } from '@/lib/i18n/records';
import { assessment, parseAR } from '@/lib/lab-workflow';
import { evaluationLabels, layoutHref, primaryRecord, layoutEvaluations } from '@/lib/layout-page';
import { canSimulateRecord, type LocalLibrary, type SavedRecord, type SavedSummary } from '@/lib/local-library';
import { editorRecordLink, type ExperimentReceipt } from '@/lib/records-catalog';
import type { EditorRecord } from '@/lib/electrode-editor';
import { metricPercent, protocolName } from '@/lib/ui-language';
import { cn } from '@/lib/utils';

type Related = { editors: EditorRecord[]; signals: ExperimentReceipt[] };
const ORIGIN: Record<string, string> = {
  design_evaluation: '导入的坐标', cache: '按区域搜索', strict_area: '总面积研究', historical_area: '历史面积实验', offline_radius: '历史半径实验',
};

function useLayoutPage() {
  const [q, setQ] = useState<URLSearchParams | null>(null);
  const [library, setLibrary] = useState<SavedSummary[] | null>(null);
  const [related, setRelated] = useState<Related>({ editors: [], signals: [] });
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const restore = () => setQ(new URLSearchParams(window.location.search));
    restore(); window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const read = <T,>(url: string) => apiJson<T>(url, { signal: controller.signal, errorMessage: '数据服务暂不可用，请稍后重新读取。' });
    void Promise.allSettled([
      read<LocalLibrary>('/api/local-compute/library'),
      read<{ records: EditorRecord[] }>('/api/electrode-editor/records'),
      read<{ schema: string; records: ExperimentReceipt[] }>('/api/community/records'),
    ]).then(([layouts, editors, signals]) => {
      if (controller.signal.aborted) return;
      if (layouts.status === 'fulfilled') { setLibrary(layouts.value.records); setError(''); }
      else setError(layouts.reason instanceof Error ? layouts.reason.message : '数据服务暂不可用，请稍后重新读取。');
      setRelated({
        editors: editors.status === 'fulfilled' ? editors.value.records : [],
        signals: signals.status === 'fulfilled' && signals.value.schema === 'browser-experiment-records/1' ? signals.value.records : [],
      });
    });
    return () => controller.abort();
  }, [retry]);
  const ar = parseAR(q?.get('ar') ?? null);
  const id = q?.get('id') ?? '', requestedKey = q?.get('key') ?? '';
  const named = library?.find(record => record.id === id) ?? null;
  const key = requestedKey || named?.layout_key || '';
  const records = useMemo(() => key ? layoutEvaluations(library ?? [], key) : named ? [named] : [], [library, key, named]);
  const shown = named && records.some(record => record.id === named.id) ? named : primaryRecord(records);
  const select = useCallback((recordId: string, nextAR = ar) => {
    const next = new URLSearchParams(key ? { key } : { id: recordId });
    if (key) next.set('id', recordId);
    next.set('ar', String(nextAR));
    window.history.replaceState(null, '', '/layout?' + next.toString());
    setQ(next);
  }, [ar, key]);
  return { ready: !!q, ar, key, id, records, shown, library, related, error, retry: () => setRetry(value => value + 1), select };
}

export default function LayoutWorkspace() {
  const { tx, locale, date } = useLanguage();
  const { ready, ar, key, id, records, shown, library, related, error, retry, select } = useLayoutPage();
  const [full, setFull] = useState<SavedRecord | null>(null);
  const [fullError, setFullError] = useState('');
  useEffect(() => {
    if (!shown) return;
    const controller = new AbortController();
    apiJson<{ record: SavedRecord }>('/api/local-compute/library/' + shown.id, { signal: controller.signal, errorMessage: '方案读取失败或完整性校验未通过' })
      .then(value => { if (value.record.id === shown.id) { setFull(value.record); setFullError(''); } })
      .catch(reason => { if (!controller.signal.aborted) setFullError(reason instanceof Error ? reason.message : '方案读取失败或完整性校验未通过'); });
    return () => controller.abort();
  }, [shown]);
  const record = full?.id === shown?.id ? full : null;
  const here = shown ? (key ? `/layout?key=${key}&id=${shown.id}&ar=${ar}` : layoutHref({ id: shown.id }, ar)) : '/layout';
  const ids = new Set(records.map(row => row.id));
  const editors = related.editors.filter(editor => ids.has(editor.parent_id));
  const signals = related.signals.filter(receipt => receipt.kind === 'source-reception' && receipt.status === 'completed'
    && ids.has((receipt.request as { record_id?: string }).record_id ?? ''));
  const design = record?.layout && record.status === 'completed' ? (() => { try { return exportDesign(record); } catch { return null; } })() : null;
  const missing = ready && library && !shown;
  return <main className="lab-page">
    <SiteHeader current="layout" arPercent={ar} returnHref={here} selection={{ id: shown?.id ?? null, phase: 'saved' }} />
    <div className="lab-container space-y-5 pb-10">
      <nav aria-label={tx('位置')} className="flex flex-wrap items-center gap-1.5 pt-5 text-xs text-muted-foreground">
        <a className="lab-link-pill" href={'/library?ar=' + ar}>{tx('布局列表')}</a>
        <ChevronRight aria-hidden className="size-3.5 text-muted-foreground/60" />
        <span className="truncate font-medium text-foreground/90">{shown ? localizedRecordTitle(shown, locale) : tx('布局详情')}</span>
      </nav>
      {error && <p role="alert" className="lab-panel text-danger"><RuntimeMessage message={error} /> <button type="button" className="underline" onClick={retry}>{tx('重新读取')}</button></p>}
      {!ready || (!library && !error) ? <p className="lab-panel">{tx('读取方案目录…')}</p>
        : missing ? <p role="alert" className="lab-panel">{tx(key || id ? '找不到这个布局的记录。它可能来自其他工作区，或记录已被移除。' : '请从布局列表选择一个布局。')} <a className="lab-link-pill ml-2" href={'/library?ar=' + ar}>{tx('打开布局列表')}</a></p>
        : shown && <>
          <header className="space-y-1.5 border-b border-border pb-5">
            <p className="lab-eyebrow">{tx('布局')} · {tx(ORIGIN[shown.dataset_id] ?? protocolName(shown.dataset_id))}</p>
            <h1 className="text-2xl font-semibold tracking-[-0.028em] sm:text-[1.65rem]">{localizedRecordTitle(shown, locale)}</h1>
            <p className="font-mono text-xs text-muted-foreground">
              {record?.layout ? `${record.layout.xyzMm.length} ${tx('电极')} · ` : ''}{shown.region_count} {tx('个区域')} · {tx(`共${records.length}次评价`)}
              {editors.length > 0 && <> · {tx(`${editors.length}个编辑副本`)}</>}{signals.length > 0 && <> · {tx(`${signals.length}次信号实验`)}</>}
            </p>
          </header>

          <section aria-labelledby="layout-evaluations" className="lab-panel space-y-4">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div className="max-w-3xl">
                <h2 id="layout-evaluations" className="text-lg font-semibold">{tx('各条件下的评价')}</h2>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">{tx('同一组坐标在不同噪声模型、电导率、头模或数据先验下的评价。名义Ernie评价排在最前；不同条件的分数只与相同条件比较。')}</p>
                <span className="mt-2 flex flex-wrap gap-x-4 gap-y-1"><TermHint term="retention" ar={ar} /><TermHint term="head" ar={ar} /></span>
              </div>
              <ThresholdSlider className="min-w-[250px]" value={ar} onChange={value => select(shown.id, value)} ariaLabel="布局接受阈值AR" term="ar" hint="只更新判断，不重新计算。" />
            </div>
            <div className="relative overflow-x-auto rounded-xl border border-border/75 bg-card">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead>
                  <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                    <th className="px-4 py-3">{tx('评价条件')}</th>
                    <th className="px-3 py-3">{tx('场重建保留率')}</th>
                    <th className="px-3 py-3">{tx('幅度保留率（最差10%）')}</th>
                    <th className="px-3 py-3">{tx('定位效用保留率')}</th>
                    <th className="px-3 py-3">{tx('参考线对照')}</th>
                    <th className="px-4 py-3"><span className="sr-only">{tx('操作')}</span></th>
                  </tr>
                </thead>
                <tbody>{records.map(row => {
                  const outcome = (row.status === 'completed' ? assessment(row.metrics, ar).state : 'undefined') as Outcome;
                  const labels = evaluationLabels(row);
                  return <tr key={row.id} className={cn('border-b border-border/65 transition-colors last:border-0 hover:bg-primary/[0.03]', row.id === shown.id && 'bg-primary/[0.055]')}>
                    <th className="px-4 py-3 font-normal">
                      <span className="flex flex-wrap gap-1.5">{labels.map(label => <span key={label} className="lab-chip">{tx(label)}</span>)}</span>
                      <span className="mt-1 block text-xs text-muted-foreground">{row.finished_at ? date(row.finished_at) : tx('保存时间未记录')}</span>
                    </th>
                    <td className="px-3 py-3 font-mono tabular-nums">{metricPercent(row.metrics?.field_relative)}</td>
                    <td className="px-3 py-3 font-mono tabular-nums">{metricPercent(row.metrics?.sensitivity_tail)}</td>
                    <td className="px-3 py-3 font-mono tabular-nums">{metricPercent(row.metrics?.localization_relative)}</td>
                    <td className="px-3 py-3"><OutcomeBadge outcome={outcome}>{tx(outcome === 'pass' ? '三项高于 τ' : outcome === 'fail' ? '部分低于 τ' : '无指标')}</OutcomeBadge></td>
                    <td className="px-4 py-3 text-right">{row.id === shown.id ? <span className="lab-chip text-primary">{tx('当前显示')}</span>
                      : <Button type="button" size="xs" variant="outline" onClick={() => select(row.id)}>{tx('查看')}</Button>}</td>
                  </tr>;
                })}</tbody>
              </table>
            </div>
          </section>

          <section aria-labelledby="layout-actions" className="lab-panel space-y-3">
            <h2 id="layout-actions" className="text-lg font-semibold">{tx('对这个布局提问')}</h2>
            <p className="text-sm text-muted-foreground">{tx('一次请求就能回答的问题在这里发起；需要多次请求的问题是稳健性研究。')}</p>
            <div className="flex flex-wrap gap-2">
              {['strict_area', 'cache', 'design_evaluation'].includes(shown.dataset_id) && shown.status === 'completed' && !shown.request?.allocation_mode && !shown.request?.electrode_count && <>
                <a className={buttonVariants({ variant: 'default' })} href={decisionHref([shown.id], jointDecisionThresholds(ar))}>{tx('在其他条件下评价 · 位置偏移测试')}</a>
              </>}
              {['strict_area', 'cache', 'design_evaluation'].includes(shown.dataset_id) && shown.status === 'completed' && (
                <a className={buttonVariants({ variant: !shown.request?.allocation_mode && !shown.request?.electrode_count ? 'outline' : 'default' })} href={decisionHref([shown.id], jointDecisionThresholds(ar)) + '#compare-pick'}>{tx('与另一个布局对比')}</a>
              )}
              {record && canSimulateRecord(record) && <a className={buttonVariants({ variant: 'outline' })} href={`/reception?record=${shown.id}&ar=${ar}&returnTo=${encodeURIComponent(here)}`}>{tx('信号仿真')}</a>}
            </div>
            {design && design.xyz_mm.length === 64 && <CoordinateStudyLink design={design} />}
          </section>

          {fullError && <p role="alert" className="lab-panel"><RuntimeMessage message={fullError} /></p>}
          {record ? <SavedLayoutContent key={record.id} record={record} ar={ar} returnHref={here} /> : !fullError && <p className="lab-panel">{tx('读取所选方案的坐标与指标…')}</p>}

          {(editors.length > 0 || signals.length > 0) && <section aria-labelledby="layout-related" className="lab-panel">
            <h2 id="layout-related" className="text-lg font-semibold">{tx('由这个布局派生的记录')}</h2>
            <ul className="mt-3 divide-y divide-border/65 text-sm">
              {editors.map(editor => <li key={editor.key} className="flex flex-wrap items-center justify-between gap-2 py-2.5"><a className="font-medium text-primary underline-offset-4 hover:underline" href={editorRecordLink(editor, ar, here)}>{tx('编辑副本')} · {editor.electrode_count} {tx('电极')} · {editor.active_regions} {tx('区')}</a>{editor.finished_at && <span className="text-xs text-muted-foreground">{date(editor.finished_at, true)}</span>}</li>)}
              {signals.map(receipt => <li key={receipt.key} className="flex flex-wrap items-center justify-between gap-2 py-2.5"><a className="font-medium text-primary underline-offset-4 hover:underline" href={`/library?record=source:${receipt.key}&ar=${ar}`}>{tx('信号实验')}</a><span className="text-xs text-muted-foreground">{date(receipt.finished_at ?? receipt.created_at, true)}</span></li>)}
            </ul>
          </section>}
        </>}
    </div>
  </main>;
}
