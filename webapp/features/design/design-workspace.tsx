'use client';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from "@/components/runtime-message";
import { localizedRecordTitle } from "@/lib/i18n/records";

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense, useRef } from 'react';
import { ChevronDown, SlidersHorizontal } from 'lucide-react';
import { DataReadinessNotice } from '@/components/data-readiness-notice';
import { SiteHeader } from '@/components/site-header';
import { LocalComputePanel } from '@/components/local-compute-panel';
import { PerformanceSummary, percent } from '@/components/performance-summary';
import { Button, buttonVariants } from '@/components/ui/button';
import { layoutHref } from '@/lib/layout-page';
import { methodLink, recordLink, METRICS } from '@/lib/lab-workflow';
import { sourceExperimentLink } from '@/lib/source-reception';
import { editorLink } from '@/lib/electrode-editor';
import { DesignPlacementOptions } from '@/components/placement-options';
import { ELECTRODE_COUNTS } from '../../contracts/scientific-options.mjs';
import { minElectrodesFor, useDesignController } from './use-design-controller';
import { designViewState } from './design-state';
import { EvaluationConditions } from '@/features/conditions/evaluation-conditions';
import { ThresholdSlider } from '@/components/threshold-slider';
import { cn } from '@/lib/utils';

const Head = lazy(() => import('@/components/cluster-head-viewer').then((m) => ({ default: m.ClusterHeadViewer })));
export default function DesignWorkspace() {
  const { tx, locale } = useLanguage();
  const { error, ready, ar, comparison, here, savedId, receptionId, count, source, notice, settingsRef, editing, radius, regions, electrodeCount, selectElectrodeCount, allocationMode, selectAllocationMode, objectiveMode, selectObjectiveMode, choices, choice, customSlots, selectChoice, selectSlot, changeRegions, startRadius, setRadius, noiseModelId, selectNoiseModel, dataPrior, dataPriorSource, selectDataPrior, setDraft, setAR, request, originId, setComputed, setStatus, metrics, layout, geometry, currentStatus } = useDesignController();
  const computationRef = useRef<HTMLDivElement>(null);
  const state = designViewState({ ready, error, editing, hasLayout: !!layout, hasChoice: !!choice, currentStatus });
  const radiusRatio = Math.max(0, Math.min(1, (radius - 15) / (80 - 15)));
  const activeChannelTotal = editing ? electrodeCount : (layout?.xyzMm?.length ?? 64);
  const defaultAllocation = Array.from({ length: count }, (_, i) => Math.floor(activeChannelTotal / count) + Number(i < activeChannelTotal % count));
  const actualAllocation = layout?.regionIndices?.length
    ? Array.from({ length: count }, (_, r) => layout.regionIndices.filter((v) => v === r).length)
    : defaultAllocation;
  const minElectrodes = minElectrodesFor(regions, allocationMode);
  const revealSettings = () => {
    if (!settingsRef.current) return;
    settingsRef.current.open = true;
    const target = state.action === 'task' || state.action === 'retry' ? computationRef.current : settingsRef.current;
    (target ?? settingsRef.current).scrollIntoView({ block: 'start' });
  };
  return <main className="lab-page">
    <SiteHeader current="design" arPercent={ar} labHref={comparison} returnHref={here} selection={{ id: receptionId ?? null, phase: receptionId ? "saved" : "draft", channels: activeChannelTotal, regions: count }} receptionHref={receptionId ? sourceExperimentLink(receptionId, ar, here) : undefined} />
    <div className="lab-container">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-border pt-7 pb-5" data-design-state={state.phase}>
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.028em] sm:text-[1.65rem]">{tx(state.title)}</h1>
          {state.detail && <p className="mt-1.5 max-w-3xl text-sm text-muted-foreground" aria-live="polite">{tx(state.detail)}</p>}
        </div>
        {state.action && <Button size="sm" variant={state.action === 'new-radius' ? 'default' : 'outline'} onClick={() => { if (state.action === 'new-radius') startRadius(); revealSettings(); }}>{tx(state.actionLabel)}</Button>}
      </header>
      <DataReadinessNotice scope="design" className="mb-4" />
      {tx(error ? <div role="alert" className="lab-panel text-danger"><RuntimeMessage message={error} />。<a href={'/library?ar=' + ar} className="ml-2 underline">{tx("返回计算记录")}</a></div> : !ready ? <p className="lab-panel">{tx("正在恢复所选方案与AR…")}</p> : <>
        {tx(source && <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-2.5 text-sm"><span className="text-ink-soft">{tx("来源：")}<strong className="font-medium text-foreground">{localizedRecordTitle(source, locale)}</strong></span><a className="lab-link-pill" href={recordLink(source, ar)}>{tx("打开原记录")}</a></div>)}
        {tx(notice && <output className="mb-4 block rounded-lg border border-warning/30 bg-warning-surface/85 p-4 text-sm leading-6">{tx(notice)}</output>)}
        <div className="grid items-start gap-5 lg:grid-cols-[348px_minmax(0,1fr)] xl:grid-cols-[356px_minmax(0,1fr)_308px]">
          <details className="lab-panel group" ref={settingsRef} open>
            <summary className="flex cursor-pointer list-none items-center justify-between gap-2 text-sm font-semibold select-none [&::-webkit-details-marker]:hidden">
              <span className="flex items-center gap-2">
                <span aria-hidden className="grid size-6 place-items-center rounded border border-border bg-secondary/75 text-foreground/80">
                  <SlidersHorizontal className="size-3.5" />
                </span>
                <span>{tx('布局参数')} · {count} {tx('个区域')}{editing && <> · {electrodeCount} {tx('电极')} · {radius} mm</>}</span>
              </span>
              <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open:rotate-180" />
            </summary>
            {editing && <span className="mt-1.5 block text-xs font-normal text-primary group-open:hidden">{tx('展开调整参数并开始计算')}</span>}
            <div className="mt-5 space-y-5">
            {editing && <DesignPlacementOptions count={regions} choices={choices} selected={choice?.id ?? ''} slots={customSlots} onSelect={selectChoice} onSlot={selectSlot} onCount={changeRegions} compact />}
            <div className="rounded-xl border border-border/70 bg-muted/30 p-3.5 space-y-3">
              <h2 className="text-base font-semibold">{tx(editing ? '2 · 设置每区半径' : '总面积上限约束记录 · 只读')}</h2>
              {tx(!editing && source ? <>
                <p className="text-sm leading-7 font-mono tabular-nums">{tx(source.region_count)}{tx("个严格分离区域")}<br />{tx("总面积上限 ")}{tx(source.area_cap_cm2)} cm²<br />{tx("实际总面积 ")}{tx(source.geometry?.union_area_cm2.toFixed(2))} cm²</p>
                <p className="text-xs leading-5 text-muted-foreground">{tx("这是总面积上限约束实验的原始布局。按需计算使用每区半径约束，创建新配置后重新搜索和评价。")}</p>
                <p className="text-xs leading-5 text-muted-foreground">{tx("新建不会覆盖原方案，也不会立即启动计算。")}</p>
              </> : <>
                <p className="text-xs leading-5 text-ink-soft"><strong className="font-medium text-foreground">{tx(choice?.label ?? '请先补全上方区域部位')}</strong><br />{tx("各区电极数：")}<span className="font-mono tabular-nums">{layout ? actualAllocation.join(' + ') : allocationMode === 'adaptive' && regions > 1 ? `${tx('自动调配（每区 ≥ 4）')} · Σ=${electrodeCount}` : defaultAllocation.join(' + ')}</span></p>
                <fieldset className="space-y-1.5">
                  <legend className="block text-xs font-medium text-foreground">{tx('电极总数 K')}</legend>
                  <div className="grid grid-cols-4 gap-1.5 sm:grid-cols-7">
                    {ELECTRODE_COUNTS.map((k) => {
                      const disabled = k < minElectrodes;
                      const active = electrodeCount === k;
                      return (
                        <button
                          key={k}
                          type="button"
                          disabled={disabled}
                          onClick={() => selectElectrodeCount(k)}
                          aria-pressed={active}
                          className={cn(
                            'rounded-lg border px-1.5 py-1.5 text-center font-mono text-xs font-medium tabular-nums transition-colors',
                            disabled ? 'cursor-not-allowed border-border/50 bg-muted/40 text-muted-foreground/50'
                              : active ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-card text-ink-soft hover:border-foreground/30',
                          )}
                        >
                          {k}
                        </button>
                      );
                    })}
                  </div>
                  <p className="text-[11px] leading-4 text-muted-foreground">{tx('默认64导（与标准全头64导参考基线一致）；指定更少导联（如8、16、24、32导）可在固定贴片半径下测试通道饱和拐点。')}</p>
                </fieldset>
                {regions > 1 && <fieldset className="space-y-1.5">
                  <legend className="block text-xs font-medium text-foreground">{tx('区域通道配额')}</legend>
                  <div className="grid grid-cols-2 gap-1.5">
                    <button type="button" onClick={() => selectAllocationMode('balanced')} aria-pressed={allocationMode === 'balanced'} className={cn('rounded-lg border px-2.5 py-1.5 text-left text-xs font-medium transition-colors', allocationMode === 'balanced' ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-card text-ink-soft hover:border-foreground/30')}>
                      {tx('各区均分（默认）')}
                    </button>
                    <button type="button" onClick={() => selectAllocationMode('adaptive')} aria-pressed={allocationMode === 'adaptive'} className={cn('rounded-lg border px-2.5 py-1.5 text-left text-xs font-medium transition-colors', allocationMode === 'adaptive' ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-card text-ink-soft hover:border-foreground/30')}>
                      {tx('跨区自适应配额')}
                    </button>
                  </div>
                  <p className="text-[11px] leading-4 text-muted-foreground">{tx(allocationMode === 'adaptive' ? '每区至少保留 4 个锚点电极，其余通道按有效孔径与信噪比跨区自动调配。' : '固定按 K/R 均分各区电极数，与面积和历史基线口径一致。')}</p>
                </fieldset>}
                <fieldset className="space-y-1.5">
                  <legend className="block text-xs font-medium text-foreground">{tx('搜索优化目标')}</legend>
                  <div className="grid grid-cols-2 gap-1.5">
                    <button type="button" onClick={() => selectObjectiveMode('min')} aria-pressed={objectiveMode === 'min'} className={cn('rounded-lg border px-2.5 py-1.5 text-left text-xs font-medium transition-colors', objectiveMode === 'min' ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-card text-ink-soft hover:border-foreground/30')}>
                      {tx('下尾极小极大（默认）')}
                    </button>
                    <button type="button" onClick={() => selectObjectiveMode('composite')} aria-pressed={objectiveMode === 'composite'} className={cn('rounded-lg border px-2.5 py-1.5 text-left text-xs font-medium transition-colors', objectiveMode === 'composite' ? 'border-primary bg-primary/10 text-primary' : 'border-border bg-card text-ink-soft hover:border-foreground/30')}>
                      {tx('子空间信息复合目标')}
                    </button>
                  </div>
                  <p className="text-[11px] leading-4 text-muted-foreground">{tx(objectiveMode === 'composite' ? '联合优化下尾保留率、全脑场保留率与63维子空间互信息（0.55·min + 0.30·场 + 0.15·信息），为贴片内部电极提供持续空间去相关梯度。' : '最大化场重建与双极幅值下10%分位数的较小值 min(场, 幅值)，与默认基线完全一致。')}</p>
                </fieldset>
                <label className="lab-label">
                  <span className="flex items-center justify-between gap-2">
                    <span>{tx("每区表面半径上限 · ")}{tx(radius)} mm</span>
                    <span className="rounded-md bg-primary/10 px-2 py-0.5 font-mono text-xs font-semibold text-primary tabular-nums ring-1 ring-inset ring-primary/20">{radius} mm</span>
                  </span>
                  <span className="relative mt-2.5 block">
                    <span aria-hidden className="pointer-events-none absolute top-1/2 left-0 h-1.5 -translate-y-1/2 rounded-l-full bg-gradient-to-r from-primary/65 to-primary" style={{ width: `${radiusRatio * 100}%` }} />
                    <input className="relative z-10 block w-full accent-primary" type="range" aria-label={tx("每区半径上限")} min={15} max={80} step={5} value={radius} onChange={(e) => { setRadius(Number(e.target.value)); setDraft(true); }} />
                  </span>
                  <span aria-hidden className="mt-0.5 flex justify-between font-mono text-[11px] font-normal text-muted-foreground tabular-nums"><span>15 mm</span><span>50 mm</span><span>80 mm</span></span>
                  <span className="mt-1.5 block text-xs font-normal leading-5 text-muted-foreground">{tx("半径按头表面网格路径计算；实际半径同时受区域分离约束。")}</span>
                </label>
                <EvaluationConditions action="search" values={{ noiseModelId, dataPrior, dataPriorSource }}
                  hints={{ noise: '空间相关噪声使相邻电极共享部分噪声，搜索与评价同时使用；结果与独立噪声分开保存。' }}
                  onChange={(patch) => { if (patch.noiseModelId !== undefined) selectNoiseModel(patch.noiseModelId); if ('dataPrior' in patch) selectDataPrior(patch.dataPrior ?? null, patch.dataPriorSource); }} />
              </>)}
            </div>
            <ThresholdSlider className="border-t border-border/70 pt-4" value={ar} onChange={setAR} ariaLabel="设计接受阈值AR" term="ar" hint="只更新结果判断，不改变点位或运行计算。" />
            <details className="group/limits rounded-xl border border-border/65 bg-muted/25 px-3.5 py-2.5 text-sm">
              <summary className="flex cursor-pointer list-none items-center justify-between font-medium text-ink-soft select-none [&::-webkit-details-marker]:hidden">
                <span>{tx("计算设置与限制")}</span>
                <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/limits:rotate-180" />
              </summary>
              <p className="mt-2.5 text-xs leading-6 text-muted-foreground">{tx("支持8–64导（默认64导） · 最小电极直线间距4 mm · 单Ernie头模 · 标准64导名义SNR＝20 dB。各布局使用相同物理噪声尺度。算法在有限候选网格内搜索，位置范围按模型坐标近似定义。")}</p>
              <a href={methodLink(here, ar, '#local-compute')} className="mt-2 lab-link-pill">{tx("完整方法")}</a>
            </details>
            {/* The run button stays in view while the settings above scroll. */}
            <div ref={computationRef} className={editing && request ? 'sticky bottom-0 z-10 -mx-2 rounded-b-2xl bg-card/95 px-2 pb-1 pt-2 backdrop-blur-md' : undefined}>{tx(editing && request && <LocalComputePanel key={originId + ':editor'} request={request} arPercent={ar} onResult={setComputed} onStatus={setStatus} compact />)}</div>
            </div>
          </details>
          <div className="grid min-w-0 gap-4 xl:contents">
          {metrics && <dl className="grid grid-cols-3 gap-2.5 rounded-2xl border border-border/80 bg-card p-3.5 text-xs shadow-2xs lg:hidden" aria-label={tx('当前布局指标摘要')}>
            {METRICS.map((metric) => <div key={metric.key}><dt className="leading-5 text-muted-foreground">{tx(metric.label)}</dt><dd className="mt-1 font-mono text-base font-semibold tabular-nums">{percent(metrics[metric.key])}</dd></div>)}
          </dl>}
          <div className="min-w-0 xl:sticky xl:top-[calc(var(--workspace-header-height,7rem)+1rem)]">
            <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
              <p className="inline-flex items-center gap-2 text-sm font-semibold text-foreground">
                <span aria-hidden className={cn('size-2 rounded-full', layout ? 'bg-success' : 'bg-primary/60')} />
                {tx(layout ? editing ? '已生成并评估的布局' : '总面积上限原记录 · 未修改点位' : choice ? '布局示意（非计算结果）' : '请先选择各区域部位')}
              </p>
              {receptionId && layout?.regionPatchVertexIndices && <a className={buttonVariants({ size: 'sm' })} href={editorLink(receptionId, ar)}>{tx('编辑此布局的电极 →')}</a>}
            </div>
            {tx(choice || !editing ? <Suspense fallback={<div className="lab-panel min-h-[520px]">{tx("加载三维头部…")}</div>}><Head compact regionCount={count} allocation={actualAllocation} domainMode={!editing ? source?.mode.includes('whole') ? 'whole_surface' : 'low_hair' : choice!.mode} maskCodes={editing ? choice?.maskCodes : undefined} radiusCm={!editing ? (geometry?.common_graph_radius_mm ?? 35) / 10 : radius / 10} recordedLayout={layout ?? undefined} /></Suspense> : <div className="lab-panel min-h-[400px] grid place-items-center text-muted-foreground">{tx("选择位置组合后显示示意预览")}</div>)}
            {tx(geometry && <div className="mt-3 rounded-xl border border-border/80 bg-card/95 px-4 py-3 text-xs leading-6 text-ink-soft shadow-2xs font-mono tabular-nums">{tx("实际 ")}{tx(geometry.union_connected_component_count)} {tx(" 个分离区域 · 实际共用表面半径 ")}{tx(geometry.common_graph_radius_mm.toFixed(2))} {tx(" mm · 总面积 ")}{tx(geometry.union_area_cm2.toFixed(2))} {tx(" cm² · 最小电极直线间距 ")}{tx(geometry.minimum_chord_distance_mm.toFixed(2))} mm</div>)}
          </div>
          <div className="xl:sticky xl:top-[calc(var(--workspace-header-height,7rem)+1rem)]"><PerformanceSummary compact metrics={metrics} ar={ar} returnHref={here} basis={tx(editing ? '每区半径上限约束搜索；新结果自动保存为计算记录' : '总面积上限约束原实验；只读，不触发计算')} empty={tx('计算完成后，这里显示三项保留率与达标判断。')} emptyTitle={tx('尚无评价结果')} /></div>
          </div>
        </div>
        <section aria-labelledby="design-next" className="lab-panel mt-5 flex flex-wrap items-center gap-3">
          <h2 id="design-next" className="font-semibold">{tx('下一步')}</h2>
          {savedId ? <>
            <a className={buttonVariants({ size: 'sm' })} href={layoutHref({ id: savedId }, ar)}>{tx('打开布局详情')}</a>
            <a className={buttonVariants({ size: 'sm', variant: 'outline' })} href={`/decision?a=${savedId}&ar=${ar}&thresholdMode=joint&returnTo=${encodeURIComponent(here)}#compare-pick`}>{tx('与另一个布局对比')}</a>
            {receptionId && <a className={buttonVariants({ size: 'sm', variant: 'outline' })} href={sourceExperimentLink(receptionId, ar, here)}>{tx('用同一脑源测试这个布局')}</a>}
            <span className="text-sm text-muted-foreground">{tx(receptionId ? '布局详情汇总这个布局在各条件下的评价；信号仿真对照标准64的时间波形与重建，加入模拟心电和眼电。'
              : activeChannelTotal !== 64 ? '布局详情汇总这个布局在各条件下的评价并支持双栏对比；信号仿真与电极编辑仅适用于默认协议下的64导布局。'
                : '布局详情汇总这个布局在各条件下的评价。空间相关噪声或数据先验下搜索的布局不进入信号仿真。')}</span>
          </> : <span className="text-sm text-muted-foreground">{tx('计算出完整布局后，可打开布局详情、加入方案对比，或在64导默认协议下用同一脑源测试。')}</span>}
        </section>
        <p className="mt-5 text-sm text-muted-foreground"><a className="font-medium text-primary underline underline-offset-4" href={comparison}>{tx(source?.dataset_id === 'strict_area' ? '返回来源比较' : '查看已有结果')}</a> {tx(" · 新半径方案不会加入固定面积曲线；在")}<a className="font-medium text-primary underline underline-offset-4" href={'/library?ar=' + ar}>{tx("计算记录")}</a>{tx("中查看。")}</p>
      </>)}
    </div>
  </main>;
}
