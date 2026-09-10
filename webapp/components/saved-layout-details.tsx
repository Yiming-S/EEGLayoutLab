'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense, useEffect, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { Button } from '@/components/ui/button';
import { PerformanceSummary } from '@/components/performance-summary';
import { ExperimentHistory } from '@/components/experiment-history';
import { localizedRecordTitle } from '@/lib/i18n/records';
import { comparisonLink } from '@/lib/lab-workflow';
import { metricDistance, protocolName } from '@/lib/ui-language';
import { resultQualification, savedLayoutActions } from '@/lib/results-library';
import type { SavedRecord, SavedSummary } from '@/lib/local-library';

const Head = lazy(() => import('@/components/cluster-head-viewer').then((m) => ({ default: m.ClusterHeadViewer })));

export function SavedLayoutDetails({ summary, ar, returnHref }: { summary: SavedSummary; ar: number; returnHref: string }) {
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
  return <SavedLayoutContent key={shown.id} record={shown} ar={ar} returnHref={returnHref} />;
}

export function SavedLayoutContent({ record, ar, returnHref }: { record: SavedRecord; ar: number; returnHref: string }) {
  const { tx, locale, date } = useLanguage();
  const [historyOpen, setHistoryOpen] = useState(false);
  const actions = savedLayoutActions(record, ar, returnHref);
  const basis = record.dataset_id === 'strict_area' ? '总面积上限约束实验 · 原4096点定位字典／256个生成源'
    : record.dataset_id === 'cache' ? '每区半径上限约束搜索 · 已保存指标'
    : record.dataset_id === 'historical_area' ? '历史面积实验 · 原坐标范围，未做外部曝光筛选'
    : record.dataset_id === 'offline_radius' ? '历史半径实验，允许区域相交' : protocolName(record.dataset_id);
  const layout = record.status === 'completed' ? record.layout : null;
  const allocation = Array.from({ length: record.region_count }, (_, region) => layout?.regionIndices.filter((index) => index === region).length ?? 0);
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'eeg-scheme-' + record.id.slice(0, 12) + '.json'; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <article aria-label={tx('方案详情')} className="space-y-5">
    <header className="lab-panel space-y-3">
      <p className="lab-eyebrow">{tx('方案详情')} · {tx(protocolName(record.dataset_id))}</p>
      <h2 className="text-xl font-semibold">{localizedRecordTitle(record, locale)}</h2>
      <dl className="grid gap-4 text-base sm:grid-cols-2 lg:grid-cols-4">
        <div><dt className="text-sm text-muted-foreground">{tx('计算状态')}</dt><dd>{tx(record.status === 'no_layout' ? '本轮未找到完整布局' : '已完成评价')}</dd></div>
        <div><dt className="text-sm text-muted-foreground">{tx('性能判断')}</dt><dd>{tx(resultQualification(record, ar))} · {ar}%</dd></div>
        <div><dt className="text-sm text-muted-foreground">{tx('电极数 / 区域数')}</dt><dd>{layout ? `${layout.xyzMm.length} / ${record.region_count}` : tx('未记录')}</dd></div>
        <div><dt className="text-sm text-muted-foreground">{tx('实际区域总面积')}</dt><dd>{record.geometry ? record.geometry.union_area_cm2.toFixed(1) + ' cm²' : tx('未记录')}</dd></div>
      </dl>
      {record.dataset_id === 'cache' && !record.compatible && <p className="text-sm text-amber-800">{tx('旧版本记录 · 仅供查阅')}</p>}
    </header>

    {record.status === 'no_layout' ? <p className="lab-panel text-base leading-7">{tx('本次搜索未找到完整布局，尚无性能指标。相同版本和配置会复用这条搜索记录；可调整半径或位置范围后启动新计算。')}</p> : layout ?
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_330px]">
        <div className="min-w-0 space-y-4">
          <Suspense fallback={<div className="lab-panel min-h-[540px]">{tx('加载三维布局…')}</div>}><Head regionCount={record.region_count} allocation={allocation} domainMode={record.mode.includes('whole') ? 'whole_surface' : 'low_hair'} radiusCm={(record.radius_cap_mm ?? record.geometry?.common_graph_radius_mm ?? 35) / 10} recordedLayout={layout} /></Suspense>
          <dl className="lab-panel grid gap-3 text-base sm:grid-cols-2">
            <div><dt className="text-sm text-muted-foreground">{tx('各区电极数')}</dt><dd>{allocation.join(' + ')}</dd></div>
            <div><dt className="text-sm text-muted-foreground">{tx('当前布局定位90分位误差')}</dt><dd>{tx(metricDistance(record.metrics?.p90_mm))}</dd></div>
          </dl>
        </div>
        <PerformanceSummary metrics={record.metrics} ar={ar} returnHref={returnHref} basis={tx(basis)} />
      </div> : <p className="lab-panel">{tx('记录缺少完整坐标，无法显示布局或启动后续分析。')}</p>}

    <section className="lab-panel space-y-3" aria-label={tx('下一步操作')}>
      <h3 className="text-lg font-semibold">{tx('下一步操作')}</h3>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-4 text-base font-semibold text-primary">
        {actions.design && <a className="underline underline-offset-4" href={actions.design}>{tx(record.dataset_id === 'strict_area' ? '查看设计条件' : record.compatible ? '调整条件并计算' : '沿用条件进行新版计算')}</a>}
        {actions.edit && <a className="underline underline-offset-4" href={actions.edit}>{tx('编辑电极')}</a>}
        {actions.compare && <a className="underline underline-offset-4" href={actions.compare}>{tx('加入方案对比')}</a>}
        {actions.reception && <a className="underline underline-offset-4" href={actions.reception}>{tx('运行信号仿真')}</a>}
        <Button variant="outline" onClick={download}>{tx('导出JSON')}</Button>
        {record.dataset_id === 'strict_area' && <a className="underline underline-offset-4" href={comparisonLink(record, ar)}>{tx('查看对应面积比较')}</a>}
      </div>
      <p className="text-sm leading-6 text-muted-foreground">{tx('仅显示该记录支持的操作。报告与坐标导出、位置偏移测试在“方案对比”中进行。')}</p>
    </section>

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
