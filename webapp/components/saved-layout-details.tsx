'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense, useEffect, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { Button } from '@/components/ui/button';
import { PerformanceSummary } from '@/components/performance-summary';
import { ExperimentHistory } from '@/components/experiment-history';
import { LayoutExportMenu } from '@/components/layout-export-menu';
import { localizedRecordTitle } from '@/lib/i18n/records';
import { comparisonLink } from '@/lib/lab-workflow';
import { metricDistance, protocolName } from '@/lib/ui-language';
import { savedLayoutActions } from '@/lib/results-library';
import type { SavedRecord, SavedSummary } from '@/lib/local-library';

const Head = lazy(() => import('@/components/cluster-head-viewer').then((m) => ({ default: m.ClusterHeadViewer })));

export function SavedLayoutDetails({ summary, ar, returnHref, compact = false }: { summary: SavedSummary; ar: number; returnHref: string; compact?: boolean }) {
  const { tx } = useLanguage();
  const [result, setResult] = useState<SavedRecord | null>(null);
  const [error, setError] = useState({ id: '', message: '' });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/local-compute/library/' + summary.id, { signal: controller.signal, cache: 'no-store' }).then(async (response) => {
      if (!response.ok) throw new Error('方案读取失败或完整性校验未通过');
      const value = await response.json() as { record: SavedRecord };
      if (value.record.id !== summary.id || value.record.dataset_id !== summary.dataset_id) throw new Error('返回方案与选择不符');
      setResult(value.record); setError({ id: '', message: '' });
    }).catch((reason) => { if (!controller.signal.aborted) setError({ id: summary.id, message: reason.message }); });
    return () => controller.abort();
  }, [summary.id, summary.dataset_id, retry]);
  const shown = result?.id === summary.id ? result : null;
  if (error.id === summary.id) return <div role="alert" className="lab-panel"><RuntimeMessage message={error.message} /><Button className="mt-3" variant="outline" onClick={() => setRetry((value) => value + 1)}>{tx('重新读取')}</Button></div>;
  if (!shown) return <p className="lab-panel">{tx('读取所选方案的坐标与指标…')}</p>;
  return <SavedLayoutContent key={shown.id} record={shown} ar={ar} returnHref={returnHref} compact={compact} />;
}

export function SavedLayoutContent({ record, ar, returnHref, compact = false }: { record: SavedRecord; ar: number; returnHref: string; compact?: boolean }) {
  const { tx, locale, date } = useLanguage();
  const [historyOpen, setHistoryOpen] = useState(false);
  const actions = savedLayoutActions(record, ar, returnHref);
  const basis = record.dataset_id === 'strict_area' ? '总面积上限约束实验 · 原4096点定位字典／256个生成源'
    : record.dataset_id === 'cache' ? '每区半径上限约束搜索 · 已保存指标'
    : record.dataset_id === 'historical_area' ? '历史面积实验 · 原坐标范围，未做外部曝光筛选'
    : record.dataset_id === 'offline_radius' ? '历史半径实验，允许区域相交' : protocolName(record.dataset_id);
  const layout = record.status === 'completed' ? record.layout : null;
  const allocation = Array.from({ length: record.region_count }, (_, region) => layout?.regionIndices.filter((index) => index === region).length ?? 0);
  return <article aria-label={tx('方案详情')} className="space-y-5">
    <header className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="lab-eyebrow">{tx('方案详情')} · {tx(protocolName(record.dataset_id))}</p><h2 className="mt-1 text-lg font-semibold">{localizedRecordTitle(record, locale)}</h2></div><LayoutExportMenu record={record} ar={ar} /></div>
      <dl className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
        <div className="flex gap-2"><dt className="text-muted-foreground">{tx('计算状态')}</dt><dd>{tx(record.status === 'no_layout' ? '本轮未找到完整布局' : '已完成评价')}</dd></div>
        <div className="flex gap-2"><dt className="text-muted-foreground">{tx('电极数 / 区域数')}</dt><dd>{layout ? `${layout.xyzMm.length} / ${record.region_count}` : tx('未记录')}</dd></div>
        <div className="flex gap-2"><dt className="text-muted-foreground">{tx('实际区域总面积')}</dt><dd>{record.geometry ? record.geometry.union_area_cm2.toFixed(1) + ' cm²' : tx('未记录')}</dd></div>
      </dl>
      {record.dataset_id === 'cache' && !record.compatible && <p className="text-sm text-amber-800">{tx('旧版本记录 · 仅供查阅')}</p>}
    </header>

    <section aria-label={tx('下一步操作')} className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm font-medium text-primary">
      {actions.edit && <a className="rounded-lg bg-primary px-4 py-2 text-primary-foreground" href={actions.edit}>{tx('编辑电极')}</a>}
      {actions.compare && <a className="underline underline-offset-4" href={actions.compare}>{tx('加入方案对比')}</a>}
      {actions.reception && <a className="underline underline-offset-4" href={actions.reception}>{tx('运行信号仿真')}</a>}
      {actions.design && <a className="underline underline-offset-4" href={actions.design}>{tx(record.dataset_id === 'strict_area' ? '查看设计条件' : record.compatible ? '调整条件并计算' : '沿用条件进行新版计算')}</a>}
      {record.dataset_id === 'strict_area' && !compact && <a className="underline underline-offset-4" href={comparisonLink(record, ar)}>{tx('查看对应面积比较')}</a>}
    </section>

    {record.status === 'no_layout' ? <p className="lab-panel text-base leading-7">{tx('本次搜索未找到完整布局，尚无性能指标。相同版本和配置会复用这条搜索记录；可调整半径或位置范围后启动新计算。')}</p> : layout ?
      <div className="grid items-start gap-5 min-[900px]:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[minmax(0,1fr)_370px]">
        <div className="min-w-0 space-y-4">
          <Suspense fallback={<div className="lab-panel min-h-[440px]">{tx('加载三维布局…')}</div>}><Head regionCount={record.region_count} allocation={allocation} domainMode={record.mode.includes('whole') ? 'whole_surface' : 'low_hair'} radiusCm={(record.radius_cap_mm ?? record.geometry?.common_graph_radius_mm ?? 35) / 10} recordedLayout={layout} compact={compact} /></Suspense>
          <dl className="lab-panel grid gap-3 text-base sm:grid-cols-2">
            <div><dt className="text-sm text-muted-foreground">{tx('各区电极数')}</dt><dd>{allocation.join(' + ')}</dd></div>
            <div><dt className="text-sm text-muted-foreground">{tx('当前布局定位90分位误差')}</dt><dd>{tx(metricDistance(record.metrics?.p90_mm))}</dd></div>
          </dl>
        </div>
        <PerformanceSummary metrics={record.metrics} ar={ar} returnHref={returnHref} basis={tx(basis)} compact={compact} />
      </div> : <p className="lab-panel">{tx('记录缺少完整坐标，无法显示布局或启动后续分析。')}</p>}

    <details className="lab-panel text-base"><summary className="cursor-pointer font-semibold">{tx('实验来源、保存信息与技术详情')}</summary>
      <p className="my-3 leading-7">{tx(record.dataset_id === 'cache' ? record.compatible ? '当前计算版本兼容，可直接读取。' : '旧版本或不同模型的记录，可沿用条件创建当前版本计算。' : '原实验记录，按其保存的协议解读。')}{record.finished_at && <> {tx('保存时间：')}{date(record.finished_at, true)}</>}</p>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-sm leading-6">{JSON.stringify({ original_label: record.label, ...record.provenance }, null, 2)}</pre>
    </details>
    <details className="lab-panel" onToggle={(event) => setHistoryOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer text-base font-semibold">{tx('计算过程与实验包')}</summary>
      {historyOpen && <div className="mt-4"><ExperimentHistory recordId={record.id} /></div>}
    </details>
  </article>;
}
