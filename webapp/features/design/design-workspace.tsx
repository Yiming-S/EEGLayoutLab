'use client';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from "@/components/runtime-message";
import { localizedRecordTitle } from "@/lib/i18n/records";

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense, useRef } from 'react';
import { SiteHeader } from '@/components/site-header';
import { LocalComputePanel } from '@/components/local-compute-panel';
import { PerformanceSummary, percent } from '@/components/performance-summary';
import { Button, buttonVariants } from '@/components/ui/button';
import { layoutHref } from '@/lib/layout-page';
import { methodLink, recordLink, METRICS } from '@/lib/lab-workflow';
import { sourceExperimentLink } from '@/lib/source-reception';
import { editorLink } from '@/lib/electrode-editor';
import { DesignPlacementOptions } from '@/components/placement-options';
import { useDesignController } from './use-design-controller';
import { designViewState } from './design-state';
import { EvaluationConditions } from '@/features/conditions/evaluation-conditions';
import { ThresholdSlider } from '@/components/threshold-slider';

const Head = lazy(() => import('@/components/cluster-head-viewer').then((m) => ({ default: m.ClusterHeadViewer })));
export default function DesignWorkspace() {
  const { tx, locale } = useLanguage();
  const { error, ready, ar, comparison, here, savedId, receptionId, count, source, notice, settingsRef, editing, radius, regions, choices, choice, customSlots, selectChoice, selectSlot, changeRegions, startRadius, setRadius, noiseModelId, selectNoiseModel, dataPrior, dataPriorSource, selectDataPrior, setDraft, setAR, request, originId, setComputed, setStatus, metrics, layout, geometry, currentStatus } = useDesignController();
  const computationRef = useRef<HTMLDivElement>(null);
  const state = designViewState({ ready, error, editing, hasLayout: !!layout, hasChoice: !!choice, currentStatus });
  const revealSettings = () => {
    if (!settingsRef.current) return;
    settingsRef.current.open = true;
    const target = state.action === 'task' || state.action === 'retry' ? computationRef.current : settingsRef.current;
    (target ?? settingsRef.current).scrollIntoView({ block: 'start' });
  };
  return <main className="lab-page">
    <SiteHeader current="design" arPercent={ar} labHref={comparison} returnHref={here} selection={{ id: receptionId ?? null, phase: receptionId ? "saved" : "draft", channels: 64, regions: count }} receptionHref={receptionId ? sourceExperimentLink(receptionId, ar, here) : undefined} />
    <div className="lab-container">
      <header className="flex flex-wrap items-start justify-between gap-4 py-5" data-design-state={state.phase}>
        <div><h1 className="text-2xl font-semibold">{tx(state.title)}</h1>{state.detail && <p className="mt-2 max-w-3xl text-base text-muted-foreground" aria-live="polite">{tx(state.detail)}</p>}</div>
        {state.action && <Button variant={state.action === 'new-radius' ? 'default' : 'outline'} onClick={() => { if (state.action === 'new-radius') startRadius(); revealSettings(); }}>{tx(state.actionLabel)}</Button>}
      </header>
      {tx(error ? <div role="alert" className="lab-panel text-danger"><RuntimeMessage message={error} />。<a href={'/library?ar=' + ar} className="ml-2 underline">{tx("返回计算记录")}</a></div> : !ready ? <p className="lab-panel">{tx("正在恢复所选方案与AR…")}</p> : <>
        {tx(source && <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3 text-sm"><span>{tx("来源：")}{localizedRecordTitle(source, locale)}</span><a className="text-primary underline" href={recordLink(source, ar)}>{tx("打开原记录")}</a></div>)}
        {tx(notice && <output className="mb-4 block rounded-lg border border-warning/30 bg-warning-surface p-4 text-sm leading-6">{tx(notice)}</output>)}
        <div className="grid items-start gap-4 lg:grid-cols-[340px_minmax(0,1fr)] xl:grid-cols-[340px_minmax(0,1fr)_300px]">
          <details className="lab-panel group" ref={settingsRef} open>
            <summary className="cursor-pointer text-base font-semibold">{tx('布局参数')} · {count} {tx('个区域')}{editing && <> · {radius} mm</>}{editing && <span className="mt-1 block text-sm font-normal text-primary group-open:hidden">{tx('展开调整参数并开始计算')}</span>}</summary>
            <div className="mt-5 space-y-5">
            {editing && <DesignPlacementOptions count={regions} choices={choices} selected={choice?.id ?? ''} slots={customSlots} onSelect={selectChoice} onSlot={selectSlot} onCount={changeRegions} compact />}
            <h2 className="text-lg font-semibold">{tx(editing ? '2 · 设置每区半径' : '总面积上限约束记录 · 只读')}</h2>
            {tx(!editing && source ? <>
              <p className="text-sm leading-7">{tx(source.region_count)}{tx("个严格分离区域")}<br />{tx("总面积上限 ")}{tx(source.area_cap_cm2)} cm²<br />{tx("实际总面积 ")}{tx(source.geometry?.union_area_cm2.toFixed(2))} cm²</p>
              <p className="text-sm leading-6 text-muted-foreground">{tx("这是总面积上限约束实验的原始布局。按需计算使用每区半径约束，创建新配置后重新搜索和评价。")}</p>
              <p className="text-xs leading-5 text-muted-foreground">{tx("新建不会覆盖原方案，也不会立即启动计算。")}</p>
            </> : <>
              <p className="text-sm leading-6">{tx(choice?.label ?? '请先补全上方区域部位')}<br />{tx("各区电极数：")}{tx(Array.from({ length: regions }, (_, i) => Math.floor(64 / regions) + Number(i < 64 % regions)).join(' + '))}</p>
              <label className="lab-label">{tx("每区表面半径上限 · ")}{tx(radius)} mm<input className="mt-3 w-full accent-primary" type="range" aria-label={tx("每区半径上限")} min={15} max={80} step={5} value={radius} onChange={(e) => { setRadius(Number(e.target.value)); setDraft(true); }} /><span className="mt-1 block text-xs font-normal leading-5 text-muted-foreground">{tx("半径按头表面网格路径计算；实际半径同时受区域分离约束。")}</span></label>
              <EvaluationConditions action="search" values={{ noiseModelId, dataPrior, dataPriorSource }}
                hints={{ noise: '空间相关噪声使相邻电极共享部分噪声，搜索与评价同时使用；结果与独立噪声分开保存。' }}
                onChange={(patch) => { if (patch.noiseModelId !== undefined) selectNoiseModel(patch.noiseModelId); if ('dataPrior' in patch) selectDataPrior(patch.dataPrior ?? null, patch.dataPriorSource); }} />
            </>)}
            <ThresholdSlider className="border-t pt-4" value={ar} onChange={setAR} ariaLabel="设计接受阈值AR" term="ar" hint="只更新结果判断，不改变点位或运行计算。" />
            <details className="border-t pt-4 text-sm"><summary className="cursor-pointer font-medium">{tx("计算设置与限制")}</summary><p className="mt-3 text-xs leading-6 text-muted-foreground">{tx("固定64电极 · 最小电极直线间距4 mm · 单Ernie头模 · 标准64导名义SNR＝20 dB。各布局使用相同物理噪声尺度。算法在有限候选网格内搜索，位置范围按模型坐标近似定义。")}</p><a href={methodLink(here, ar, '#local-compute')} className="mt-2 inline-block text-primary underline">{tx("完整方法")}</a></details>
            {/* The run button stays in view while the settings above scroll. */}
            <div ref={computationRef} className={editing && request ? 'sticky bottom-0 z-10 -mx-2 rounded-b-xl bg-card px-2 pb-2 pt-2 shadow-[0_-12px_14px_-14px_rgba(16,47,58,0.45)]' : undefined}>{tx(editing && request && <LocalComputePanel key={originId + ':editor'} request={request} arPercent={ar} onResult={setComputed} onStatus={setStatus} compact />)}</div>
            </div>
          </details>
          <div className="grid min-w-0 gap-4 xl:contents">
          {metrics && <dl className="grid grid-cols-3 gap-2 rounded-xl border bg-card p-3 text-xs lg:hidden" aria-label={tx('当前布局指标摘要')}>
            {METRICS.map((metric) => <div key={metric.key}><dt className="leading-5 text-muted-foreground">{tx(metric.label)}</dt><dd className="mt-1 font-mono text-base font-semibold">{percent(metrics[metric.key])}</dd></div>)}
          </dl>}
          <div className="min-w-0 xl:sticky xl:top-[calc(var(--workspace-header-height,7rem)+1rem)]">
            <p className="mb-2 text-sm font-semibold">{tx(layout ? editing ? '已生成并评估的布局' : '总面积上限原记录 · 未修改点位' : choice ? '布局示意（非计算结果）' : '请先选择各区域部位')}</p>
            {receptionId && layout?.regionPatchVertexIndices && <a className="mb-3 inline-flex rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground" href={editorLink(receptionId, ar)}>{tx('编辑此布局的电极 →')}</a>}
            {tx(choice || !editing ? <Suspense fallback={<div className="lab-panel min-h-[520px]">{tx("加载三维头部…")}</div>}><Head compact regionCount={count} allocation={Array.from({ length: count }, (_, i) => Math.floor(64 / count) + Number(i < 64 % count))} domainMode={!editing ? source?.mode.includes('whole') ? 'whole_surface' : 'low_hair' : choice!.mode} maskCodes={editing ? choice?.maskCodes : undefined} radiusCm={!editing ? (geometry?.common_graph_radius_mm ?? 35) / 10 : radius / 10} recordedLayout={layout ?? undefined} /></Suspense> : <div className="lab-panel min-h-[400px] grid place-items-center text-muted-foreground">{tx("选择位置组合后显示示意预览")}</div>)}
            {tx(geometry && <div className="mt-3 rounded-lg border bg-card p-4 text-sm leading-7">{tx("实际 ")}{tx(geometry.union_connected_component_count)} {tx(" 个分离区域 · 实际共用表面半径 ")}{tx(geometry.common_graph_radius_mm.toFixed(2))} {tx(" mm · 总面积 ")}{tx(geometry.union_area_cm2.toFixed(2))} {tx(" cm² · 最小电极直线间距 ")}{tx(geometry.minimum_chord_distance_mm.toFixed(2))} mm</div>)}
          </div>
          <div className="xl:sticky xl:top-[calc(var(--workspace-header-height,7rem)+1rem)]"><PerformanceSummary compact metrics={metrics} ar={ar} returnHref={here} basis={tx(editing ? '每区半径上限约束搜索；新结果自动保存为计算记录' : '总面积上限约束原实验；只读，不触发计算')} empty={tx('计算完成后，这里显示三项保留率与达标判断。')} emptyTitle={tx('尚无评价结果')} /></div>
          </div>
        </div>
        <section aria-labelledby="design-next" className="lab-panel mt-5 flex flex-wrap items-center gap-3">
          <h2 id="design-next" className="font-semibold">{tx('下一步')}</h2>
          {savedId ? <>
            <a className={buttonVariants({ size: 'sm' })} href={layoutHref({ id: savedId }, ar)}>{tx('打开布局详情')}</a>
            {receptionId && <a className={buttonVariants({ size: 'sm', variant: 'outline' })} href={sourceExperimentLink(receptionId, ar, here)}>{tx('用同一脑源测试这个布局')}</a>}
            <span className="text-sm text-muted-foreground">{tx(receptionId ? '布局详情汇总这个布局在各条件下的评价；信号仿真对照标准64的时间波形与重建，加入模拟心电和眼电。'
              : '布局详情汇总这个布局在各条件下的评价。空间相关噪声或数据先验下搜索的布局不进入信号仿真。')}</span>
          </> : <span className="text-sm text-muted-foreground">{tx('计算出完整64点布局后，可打开布局详情或用同一脑源测试。')}</span>}
        </section>
        <p className="mt-5 text-sm text-muted-foreground"><a className="text-primary underline" href={comparison}>{tx(source?.dataset_id === 'strict_area' ? '返回来源比较' : '查看已有结果')}</a> {tx(" · 新半径方案不会加入固定面积曲线；在")}<a className="text-primary underline" href={'/library?ar=' + ar}>{tx("计算记录")}</a>{tx("中查看。")}</p>
      </>)}
    </div>
  </main>;
}
