'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense, useEffect, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { Button, buttonVariants } from '@/components/ui/button';
import { PerformanceSummary } from '@/components/performance-summary';
import { LayoutExportMenu } from '@/components/layout-export-menu';
import { RecordVisibilityControl } from '@/components/record-visibility-control';
import { localizedRecordTitle } from '@/lib/i18n/records';
import { comparisonLink } from '@/lib/lab-workflow';
import { metricDistance, protocolName } from '@/lib/ui-language';
import { savedLayoutActions } from '@/lib/results-library';
import { cn } from '@/lib/utils';
import type { SavedRecord, SavedSummary } from '@/lib/local-library';

const Head = lazy(() => import('@/components/cluster-head-viewer').then((m) => ({ default: m.ClusterHeadViewer })));
// The search history and its charts load only when the visitor opens them.
const ExperimentHistory = lazy(() => import('@/components/experiment-history').then((m) => ({ default: m.ExperimentHistory })));

export function SavedLayoutDetails({ summary, ar, returnHref, compact = false, onVisibilityChange }: { summary: SavedSummary; ar: number; returnHref: string; compact?: boolean; onVisibilityChange?: () => void }) {
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
  return <SavedLayoutContent key={shown.id} record={shown} ar={ar} returnHref={returnHref} compact={compact} onVisibilityChange={onVisibilityChange} />;
}

export function SavedLayoutContent({ record, ar, returnHref, compact = false, onVisibilityChange }: { record: SavedRecord; ar: number; returnHref: string; compact?: boolean; onVisibilityChange?: () => void }) {
  const { tx, locale, date } = useLanguage();
  const [historyOpen, setHistoryOpen] = useState(false);
  const actions = savedLayoutActions(record, ar, returnHref);
  const basis = record.dataset_id === 'strict_area' ? '总面积上限约束实验 · 原4096点定位字典／256个生成源'
    : record.dataset_id === 'cache' ? '每区半径上限约束搜索 · 已保存指标'
    : record.dataset_id === 'historical_area' ? '历史面积实验 · 原坐标范围，未做外部曝光筛选'
    : record.dataset_id === 'offline_radius' ? '历史半径实验，允许区域相交' : protocolName(record.dataset_id);
  const layout = record.status === 'completed' ? record.layout : null;
  const allocation = Array.from({ length: record.region_count }, (_, region) => layout?.regionIndices.filter((index) => index === region).length ?? 0);
  // One filled button for the most direct next step; the rest are outlined.
  const nextSteps = [
    actions.edit && { href: actions.edit, label: '编辑电极' },
    actions.compare && { href: actions.compare, label: '加入方案对比' },
    actions.reception && { href: actions.reception, label: '运行信号仿真' },
    actions.design && { href: actions.design, label: record.dataset_id === 'strict_area' ? '查看设计条件' : record.compatible ? '调整条件并计算' : '沿用条件进行新版计算' },
    record.dataset_id === 'strict_area' && !compact && { href: comparisonLink(record, ar), label: '查看对应面积比较' },
  ].filter((step): step is { href: string; label: string } => !!step);
  return <article aria-label={tx('方案详情')} className="@container space-y-5">
    <header className="lab-panel space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="lab-eyebrow">{tx('方案详情')} · {tx(protocolName(record.dataset_id))}</p>
          <h2 className="mt-1 text-lg font-semibold tracking-tight">{localizedRecordTitle(record, locale)}</h2>
        </div>
        <LayoutExportMenu record={record} ar={ar} />
      </div>
      <dl className="grid gap-2.5 text-sm sm:grid-cols-3">
        <div className="lab-subpanel py-2.5">
          <dt className="text-xs text-muted-foreground">{tx('计算状态')}</dt>
          <dd className="mt-0.5 font-medium text-foreground">{tx(record.status === 'no_layout' ? '本轮未找到完整布局' : '已完成评价')}</dd>
        </div>
        <div className="lab-subpanel py-2.5">
          <dt className="text-xs text-muted-foreground">{tx('电极数 / 区域数')}</dt>
          <dd className="mt-0.5 font-mono font-semibold tabular-nums">{layout ? `${layout.xyzMm.length} / ${record.region_count}` : tx('未记录')}</dd>
        </div>
        <div className="lab-subpanel py-2.5">
          <dt className="text-xs text-muted-foreground">{tx('实际区域总面积')}</dt>
          <dd className="mt-0.5 font-mono font-semibold tabular-nums">{record.geometry ? record.geometry.union_area_cm2.toFixed(1) + ' cm²' : tx('未记录')}</dd>
        </div>
      </dl>
      {record.dataset_id === 'cache' && !record.compatible && <p className="rounded-lg border border-warning/30 bg-warning-surface/75 px-3 py-2 text-xs text-warning">{tx('旧版本记录 · 仅供查阅')}</p>}
      {!compact && <RecordVisibilityControl id={record.id} name={localizedRecordTitle(record, locale)} visibility={record.visibility} onChange={onVisibilityChange} />}
      {nextSteps.length > 0 && (
        <section aria-label={tx('下一步操作')} className="space-y-2 border-t border-border/70 pt-3.5">
          <div className="flex flex-wrap gap-2">
            {nextSteps.map((step, index) => (
              <a key={step.label} className={cn(buttonVariants({ variant: index === 0 ? 'default' : 'outline', size: 'default' }))} href={step.href}>
                {tx(step.label)}
              </a>
            ))}
          </div>
          {layout && layout.xyzMm.length !== 64 && <p className="text-xs text-muted-foreground">{tx('此布局为少于64导方案，支持三维查看、导出与双栏方案对比；电极编辑与信号仿真仅适用于64导布局。')}</p>}
          {record.request?.data_prior && <p className="text-xs text-muted-foreground">{tx('此布局按数据先验（区域源功率与拟合噪声）搜索；分数只与相同数据先验的记录直接比较，不进入信号仿真和电极编辑。')}</p>}
          {record.request?.noise_model && <p className="text-xs text-muted-foreground">{tx('信号仿真使用独立噪声；空间相关噪声下搜索的布局不进入信号仿真')}</p>}
          {record.evaluation_condition && <p className="text-xs text-muted-foreground">{tx('此坐标评价使用非默认的噪声模型、电导率情景或头模；分数只与相同条件的评价直接比较，信号仿真只接受默认协议下的布局。')}</p>}
        </section>
      )}
    </header>

    {(record.dataset_id === 'historical_area' || record.dataset_id === 'offline_radius') && <p className="rounded-xl border border-border/75 bg-muted/35 px-4 py-2.5 text-xs leading-5 text-muted-foreground">{tx('此历史协议的记录仅供查看与导出。信号仿真支持当前总面积布局、半径计算布局和已评价坐标布局。')}</p>}

    {record.status === 'no_layout' ? <p className="lab-panel text-sm leading-6">{tx('本次搜索未找到完整布局，尚无性能指标。相同版本和配置会复用这条搜索记录；可调整半径或位置范围后启动新计算。')}</p> : layout ?
      <div className="grid items-start gap-5 @min-[840px]:grid-cols-[minmax(0,1fr)_320px] @min-[1100px]:grid-cols-[minmax(0,1fr)_370px]">
        <div className="min-w-0 space-y-4">
          <Suspense fallback={<div className="lab-panel min-h-[440px]">{tx('加载三维布局…')}</div>}><Head regionCount={record.region_count} allocation={allocation} domainMode={record.mode.includes('whole') ? 'whole_surface' : 'low_hair'} radiusCm={(record.radius_cap_mm ?? record.geometry?.common_graph_radius_mm ?? 35) / 10} recordedLayout={layout} compact={compact} /></Suspense>
          <dl className="lab-panel grid gap-3 py-4 text-sm sm:grid-cols-2">
            <div className="lab-subpanel py-2.5">
              <dt className="text-xs text-muted-foreground">{tx('各区电极数')}</dt>
              <dd className="mt-0.5 font-mono font-semibold tabular-nums">{allocation.join(' + ')}</dd>
            </div>
            <div className="lab-subpanel py-2.5">
              <dt className="text-xs text-muted-foreground">{tx('当前布局定位90分位误差')}</dt>
              <dd className="mt-0.5 font-mono font-semibold tabular-nums">{tx(metricDistance(record.metrics?.p90_mm))}</dd>
            </div>
          </dl>
        </div>
        <PerformanceSummary metrics={record.metrics} ar={ar} returnHref={returnHref} basis={tx(basis)} compact={compact} />
      </div> : <p className="lab-panel">{tx('记录缺少完整坐标，无法显示布局或启动后续分析。')}</p>}

    <details className="group/prov lab-panel text-sm">
      <summary className="flex cursor-pointer list-none items-center justify-between font-semibold select-none [&::-webkit-details-marker]:hidden">
        <span>{tx('实验来源、保存信息与技术详情')}</span>
        <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/prov:rotate-180" />
      </summary>
      <p className="my-3 text-xs leading-6 text-muted-foreground">{tx(record.dataset_id === 'cache' ? record.compatible ? '当前计算版本兼容，可直接读取。' : '旧版本或不同模型的记录，可沿用条件创建当前版本计算。' : '原实验记录，按其保存的协议解读。')}{record.finished_at && <> {tx('保存时间：')}{date(record.finished_at, true)}</>}</p>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all rounded-xl border border-border/70 bg-muted/45 p-3.5 font-mono text-xs leading-5">{JSON.stringify({ original_label: record.label, ...record.provenance }, null, 2)}</pre>
    </details>
    <details className="group/hist lab-panel" onToggle={(event) => setHistoryOpen(event.currentTarget.open)}>
      <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold select-none [&::-webkit-details-marker]:hidden">
        <span>{tx('计算过程与实验包')}</span>
        <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/hist:rotate-180" />
      </summary>
      {historyOpen && <div className="mt-4"><Suspense fallback={<p className="text-sm text-muted-foreground">{tx('读取搜索过程…')}</p>}><ExperimentHistory recordId={record.id} /></Suspense></div>}
    </details>
  </article>;
}
