'use client';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from "@/components/runtime-message";
import { localizedRecordTitle } from "@/lib/i18n/records";

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense } from 'react';
import { SiteHeader } from '@/components/site-header';
import { LocalComputePanel } from '@/components/local-compute-panel';
import { PerformanceSummary, percent } from '@/components/performance-summary';
import { Button } from '@/components/ui/button';
import { methodLink, recordLink, METRICS } from '@/lib/lab-workflow';
import { sourceExperimentLink } from '@/lib/source-reception';
import { editorLink } from '@/lib/electrode-editor';
import { DesignPlacementOptions } from '@/components/placement-options';
import { useDesignController } from './use-design-controller';

const Head = lazy(() => import('@/components/cluster-head-viewer').then((m) => ({ default: m.ClusterHeadViewer })));
export default function DesignWorkspace() {
  const { tx, locale } = useLanguage();
  const { error, ready, ar, comparison, here, receptionId, count, source, notice, settingsRef, editing, radius, regions, choices, choice, customSlots, selectChoice, selectSlot, changeRegions, startRadius, setRadius, setDraft, setAR, request, originId, setComputed, setStatus, metrics, layout, geometry, pendingText, currentStatus } = useDesignController();
  return <main className="lab-page">
    <SiteHeader current="design" arPercent={ar} labHref={comparison} returnHref={here} selection={{ id: receptionId ?? null, phase: receptionId ? "saved" : "draft", channels: 64, regions: count }} receptionHref={receptionId ? sourceExperimentLink(receptionId, ar, here) : undefined} />
    <div className="lab-container">
      <header className="py-5"><h1 className="text-2xl font-semibold">{tx("布局设计：设置条件并生成64电极布局")}</h1><p className="mt-2 text-base text-muted-foreground">{tx("先设置区域数、位置范围和每区半径，再点击“开始布局计算”。算法选择电极坐标；拖动3D只旋转视角，不会移动电极。")}</p></header>
      {tx(error ? <div role="alert" className="lab-panel text-red-800"><RuntimeMessage message={error} />。<a href={'/library?ar=' + ar} className="ml-2 underline">{tx("返回计算记录")}</a></div> : !ready ? <p className="lab-panel">{tx("正在恢复所选方案与AR…")}</p> : <>
        {tx(source && <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3 text-sm"><span>{tx("来源：")}{localizedRecordTitle(source, locale)}</span><a className="text-primary underline" href={recordLink(source, ar)}>{tx("打开原记录")}</a></div>)}
        {tx(notice && <output className="mb-4 block rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-6">{tx(notice)}</output>)}
        <div className="grid items-start gap-4 md:grid-cols-[minmax(0,1fr)_300px] min-[68.75rem]:grid-cols-[260px_minmax(0,1fr)_300px]">
          <details className="lab-panel md:col-span-2 min-[68.75rem]:col-span-1" ref={settingsRef} open>
            <summary className="cursor-pointer text-base font-semibold">{tx('布局参数')} · {count} {tx('个区域')}{editing && <> · {radius} mm</>}</summary>
            <div className="mt-5 space-y-5">
            {editing && <DesignPlacementOptions count={regions} choices={choices} selected={choice?.id ?? ''} slots={customSlots} onSelect={selectChoice} onSlot={selectSlot} onCount={changeRegions} compact />}
            <h2 className="text-lg font-semibold">{tx(editing ? '2 · 设置尺寸并计算' : '总面积上限约束记录 · 只读')}</h2>
            {tx(!editing && source ? <>
              <p className="text-sm leading-7">{tx(source.region_count)}{tx("个严格分离区域")}<br />{tx("总面积上限 ")}{tx(source.area_cap_cm2)} cm²<br />{tx("实际总面积 ")}{tx(source.geometry?.union_area_cm2.toFixed(2))} cm²</p>
              <p className="text-sm leading-6 text-muted-foreground">{tx("这是总面积上限约束实验的原始布局。按需计算使用每区半径约束，创建新配置后重新搜索和评价。")}</p>
              <Button onClick={startRadius} className="w-full">{tx("新建每区半径约束方案")}</Button>
              <p className="text-xs leading-5 text-muted-foreground">{tx("新建不会覆盖原方案，也不会立即启动计算。")}</p>
            </> : <>
              <p className="text-sm leading-6">{tx(choice?.label ?? '请先补全上方区域部位')}<br />{tx("各区电极数：")}{tx(Array.from({ length: regions }, (_, i) => Math.floor(64 / regions) + Number(i < 64 % regions)).join(' + '))}</p>
              <label className="lab-label">{tx("每区表面半径上限 · ")}{tx(radius)} mm<input className="mt-3 w-full accent-primary" type="range" aria-label={tx("每区半径上限")} min={15} max={80} step={5} value={radius} onChange={(e) => { setRadius(Number(e.target.value)); setDraft(true); }} /><span className="mt-1 block text-xs font-normal leading-5 text-muted-foreground">{tx("半径按头表面网格路径计算；实际半径同时受区域分离约束。")}</span></label>
            </>)}
            <label className="lab-label border-t pt-4">{tx("接受阈值 AR · ")}{tx(ar)}%<input className="mt-3 w-full accent-primary" type="range" aria-label={tx("设计接受阈值AR")} min={10} max={100} step={1} value={ar} onChange={(e) => setAR(Number(e.target.value))} /><span className="mt-1 block text-xs font-normal text-muted-foreground">{tx("只更新结果判断，不改变点位或运行计算。")}</span></label>
            {tx(editing && request && <LocalComputePanel key={originId + ':editor'} request={request} arPercent={ar} onResult={setComputed} onStatus={setStatus} compact />)}
            <details className="border-t pt-4 text-sm"><summary className="cursor-pointer font-medium">{tx("计算设置与限制")}</summary><p className="mt-3 text-xs leading-6 text-muted-foreground">{tx("固定64电极 · 最小电极直线间距4 mm · 单Ernie头模 · 标准64导名义SNR＝20 dB。各布局使用相同物理噪声尺度。算法在有限候选网格内搜索，位置范围按模型坐标近似定义。")}</p><a href={methodLink(here, ar, '#local-compute')} className="mt-2 inline-block text-primary underline">{tx("完整方法")}</a></details>
            </div>
          </details>
          {metrics && <dl className="grid grid-cols-3 gap-2 rounded-xl border bg-card p-3 text-xs md:hidden" aria-label={tx('当前布局指标摘要')}>
            {METRICS.map((metric) => <div key={metric.key}><dt className="leading-5 text-muted-foreground">{tx(metric.label)}</dt><dd className="mt-1 font-mono text-base font-semibold">{percent(metrics[metric.key])}</dd></div>)}
          </dl>}
          <div className="min-w-0">
            <p className="mb-2 text-sm font-semibold">{tx(layout ? editing ? '3 · 已生成并评估的布局' : '总面积上限原记录 · 未修改点位' : choice ? '布局示意 · 待计算' : '请先选择各区域部位')}</p>
            {receptionId && layout?.regionPatchVertexIndices && <a className="mb-3 inline-flex rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground" href={editorLink(receptionId, ar)}>{tx('编辑此布局的电极 →')}</a>}
            {tx(choice || !editing ? <Suspense fallback={<div className="lab-panel min-h-[520px]">{tx("加载三维头部…")}</div>}><Head compact regionCount={count} allocation={Array.from({ length: count }, (_, i) => Math.floor(64 / count) + Number(i < 64 % count))} domainMode={!editing ? source?.mode.includes('whole') ? 'whole_surface' : 'low_hair' : choice!.mode} maskCodes={editing ? choice?.maskCodes : undefined} radiusCm={!editing ? (geometry?.common_graph_radius_mm ?? 35) / 10 : radius / 10} recordedLayout={layout ?? undefined} /></Suspense> : <div className="lab-panel min-h-[400px] grid place-items-center text-muted-foreground">{tx("选择位置组合后显示示意预览")}</div>)}
            {tx(geometry && <div className="mt-3 rounded-lg border bg-card p-4 text-sm leading-7">{tx("实际 ")}{tx(geometry.union_connected_component_count)} {tx(" 个分离区域 · 实际共用表面半径 ")}{tx(geometry.common_graph_radius_mm.toFixed(2))} {tx(" mm · 总面积 ")}{tx(geometry.union_area_cm2.toFixed(2))} {tx(" cm² · 最小电极直线间距 ")}{tx(geometry.minimum_chord_distance_mm.toFixed(2))} mm</div>)}
          </div>
          <div><PerformanceSummary compact metrics={metrics} ar={ar} returnHref={here} basis={tx(editing ? '每区半径上限约束搜索；新结果自动保存为计算记录' : '总面积上限约束原实验；只读，不触发计算')} empty={tx(pendingText)} emptyTitle={tx(currentStatus?.status === 'no_layout' ? '本次未构造出完整布局' : currentStatus && ['failed', 'timeout', 'cancelled'].includes(currentStatus.status) ? '计算未完成' : undefined)} /></div>
        </div>
        <section className="lab-panel mt-5 flex flex-wrap items-center justify-between gap-4"><div><h2 className="font-semibold">{tx("用同一脑源测试这个布局")}</h2><p className="mt-1 text-sm text-muted-foreground">{tx("对照标准64的时间波形与重建，分别加入模拟心电和眼电。固定点位，不重新优化。")}</p></div>{tx(receptionId ? <a className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground" href={sourceExperimentLink(receptionId, ar, here)}>{tx("打开信号仿真 →")}</a> : <span className="text-sm text-muted-foreground">{tx("先计算出完整64点布局后可进入")}</span>)}</section>
        <p className="mt-5 text-sm text-muted-foreground"><a className="text-primary underline" href={comparison}>{tx(source?.dataset_id === 'strict_area' ? '返回来源比较' : '查看已有结果')}</a> {tx(" · 新半径方案不会加入固定面积曲线；在")}<a className="text-primary underline" href={'/library?ar=' + ar}>{tx("计算记录")}</a>{tx("中查看。")}</p>
      </>)}
    </div>
  </main>;
}
