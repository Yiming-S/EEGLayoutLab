'use client';
import { lazy, Suspense } from 'react';
import { Activity, ChevronDown } from 'lucide-react';

import { RuntimeMessage } from '@/components/runtime-message';
import { localizedRecordTitle } from '@/lib/i18n/records';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */

import { Button } from '@/components/ui/button';
import { SiteHeader } from '@/components/site-header';
import { cn } from '@/lib/utils';

import { BRAIN_REGIONS, sourceKey } from '@/lib/source-reception';
import { SOURCE_REGIONS, canonicalSourceRegions } from '@/lib/source-regions';
import { lowerArtifactScale } from '@/lib/source-result-reading';

import { useReceptionController, running } from './use-reception-controller';
// The result view and its charts load with the first result, not with the page.
const ExperimentResult = lazy(() => import('./experiment-result').then((module) => ({ default: module.ExperimentResult })));

export default function ReceptionPage() {
  const {
    tx,
    locale,
    library,
    id,
    setId,
    ready,
    region,
    setRegion,
    waveform,
    setWaveform,
    scale,
    setScale,
    seed,
    setSeed,
    ar,
    setAR,
    mode,
    setMode,
    crossRegions,
    setCrossRegions,
    validSources,
    singleIndex,
    setSingleIndex,
    catalog,
    catalogError,
    token,
    fatal,
    setRetry,
    active,
    submitting,
    lookup,
    error,
    records,
    selected,
    key,
    job,
    result,
    returnHref,
    here,
    busy,
    submit,
    cancel,
  } = useReceptionController();
  return (
    <main className="lab-page">
      <SiteHeader
        current="reception"
        arPercent={ar}
        labHref={returnHref}
        returnHref={here}
        selection={{ id: selected?.id ?? null, phase: 'saved' }}
      />
      <div className="lab-container space-y-4">
        <header className="border-b border-border pt-7 pb-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h1 className="text-2xl font-semibold tracking-[-0.028em] sm:text-[1.65rem]">{tx('信号仿真')}</h1>
            <a className="lab-link-pill" href={returnHref}>
              {tx('← 返回来源页面')}
            </a>
          </div>
          <p className="mt-1.5 max-w-4xl text-sm leading-6 text-muted-foreground">
            {tx(
              '选择已计算布局，再设置脑源位置、波形和干扰。对比标准全头64导与所选64电极布局的接收和重建；本页不重新优化电极位置。',
            )}
          </p>
        </header>
        <div className="rounded-xl border border-warning/30 bg-warning-surface/75 px-4 py-3 text-xs leading-5 text-warning shadow-2xs">
          {tx(
            '单头模仿真：脑信号通过已有FEM传递矩阵投影；心电、眼电采用假设性空间场。源区由坐标定义，用于表示皮层位置。本页AR用于当前场景的信号重建判定；布局评估采用三项联合判定。',
          )}
        </div>
        {tx(
          !id && (
            <div className="lab-panel py-4 text-sm leading-6">
              {tx('尚未选择布局。可从下方列表选择，或先去')}
              <a
                className="mx-1.5 font-medium text-primary underline underline-offset-4"
                href={'/design?ar=' + ar}
              >
                {tx('布局设计')}
              </a>
              {tx('生成64个电极坐标。选择和浏览不会自动开始新仿真。')}
            </div>
          ),
        )}
        {tx(
          fatal && (
            <p role="alert" className="lab-panel border-danger/35 bg-danger-surface/65 text-sm text-danger">
              <RuntimeMessage message={fatal} />
              {tx(' ')}
              <Button variant="outline" size="sm" className="ml-2" onClick={() => setRetry((n) => n + 1)}>
                {tx('刷新服务')}
              </Button>
            </p>
          ),
        )}
        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.35fr)]">
          <section className="lab-panel h-full" aria-label={tx('布局')}>
            <h2 className="text-base font-semibold">{tx('1 · 选择布局')}</h2>
            <label className="lab-label mt-3 block">
              {tx('选择已计算布局（64电极）')}
              <select
                className="lab-select"
                value={id}
                onChange={(e) => setId(e.target.value)}
              >
                <option value="">{tx('选择已计算布局')}</option>
                {tx(
                  id && !selected && (
                    <option value={id}>{tx('指定记录正在读取或不可用')}</option>
                  ),
                )}
                {tx(
                  records.map((r) => (
                    <option key={r.id} value={r.id}>
                      {tx(
                        r.dataset_id === 'cache' && !r.compatible
                          ? '历史布局 · '
                          : '',
                      )}
                      {localizedRecordTitle(r, locale)}
                    </option>
                  )),
                )}
              </select>
            </label>
          </section>
          <section className="lab-panel" aria-label={tx('源模式')}>
            <h2 className="text-base font-semibold">{tx('2 · 选择实验源模式')}</h2>
            <div className="mt-3 flex flex-wrap gap-1 rounded-xl border border-border/75 bg-muted/55 p-1">
              <Button
                size="sm"
                variant={mode === 'multi_source' ? 'default' : 'ghost'}
                className="flex-1"
                aria-pressed={mode === 'multi_source'}
                onClick={() => setMode('multi_source')}
              >
                {tx('区域内6源')}
              </Button>
              <Button
                size="sm"
                variant={mode === 'cross_region' ? 'default' : 'ghost'}
                className="flex-1"
                aria-pressed={mode === 'cross_region'}
                onClick={() => setMode('cross_region')}
              >
                {tx('跨区域多源（1–6源）')}
              </Button>
              <Button
                size="sm"
                variant={mode === 'single_source' ? 'default' : 'ghost'}
                className="flex-1"
                aria-pressed={mode === 'single_source'}
                onClick={() => setMode('single_source')}
              >
                {tx('固定法向单源探索')}
              </Button>
            </div>
            <p className="mt-3 text-xs leading-5 text-ink-soft">
              {tx(
                mode === 'cross_region'
                  ? '选择1–6个源区域，每区启用一个固定生成源。源点使用皮层法向；共享节律与各自波动叠加。总源均方能量固定，各源均分，不随选中数量增加。'
                  : mode === 'single_source'
                  ? '从256个已冻结、不同于反演字典网格的生成源中选择一个位置。方向使用原皮层法向，重建器仍使用全脑源先验。每个源单独保存结果，不改变布局的全脑指标。'
                  : '在所选DK图谱研究区内选择6个固定生成源。节律/间歇波形和四组干扰对照保持不变；新分区结果使用独立缓存。',
              )}
            </p>
            {mode === 'cross_region' && <fieldset className="mt-3.5 rounded-xl border border-border/70 bg-muted/30 p-3.5">
              <legend className="px-1 text-xs font-semibold text-foreground">{tx('选择发出信号的区域')} · <span className="font-mono text-primary tabular-nums">{crossRegions.length}/6</span></legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {SOURCE_REGIONS.map(item => {
                  const activeRegion = crossRegions.includes(item.id);
                  return (
                    <label
                      key={item.id}
                      className={cn(
                        'flex cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2.5 text-sm transition-all',
                        activeRegion
                          ? 'border-primary/60 bg-primary/[0.06] font-medium shadow-2xs'
                          : 'border-border/80 bg-card/90 hover:border-primary/35',
                      )}
                    >
                      <input type="checkbox" className="size-4 accent-primary" checked={activeRegion} onChange={e => setCrossRegions(canonicalSourceRegions(e.target.checked ? [...crossRegions, item.id] : crossRegions.filter(id => id !== item.id)))} />
                      <span aria-hidden="true" className="size-2.5 shrink-0 rounded-full ring-1 ring-black/10" style={{ backgroundColor: item.color }} />
                      <span>{tx(item.label)}</span>
                    </label>
                  );
                })}
              </div>
              <p className="mt-2.5 text-xs leading-5 text-muted-foreground">{tx('颜色对应DK图谱标签定义的六个研究区，与透视图中的分区和实际选源一致。')}</p>
              {!validSources && <output className="mt-2 block text-xs font-medium text-warning">{tx('至少选择一个源区域才能运行。')}</output>}
              {catalog?.cross_region_representatives && <details className="group/coords mt-2.5 text-xs leading-6 text-muted-foreground">
                <summary className="inline-flex cursor-pointer list-none items-center gap-1 font-medium text-primary select-none [&::-webkit-details-marker]:hidden">
                  <span>{tx('查看所选生成源坐标')}</span>
                  <ChevronDown aria-hidden className="size-3.5 transition-transform group-open/coords:rotate-180" />
                </summary>
                <div className="mt-2 rounded-lg border border-border/65 bg-card p-2.5 font-mono text-[11px] tabular-nums">
                  {catalog.cross_region_representatives.filter(s => crossRegions.includes(s.source_region)).map((s, i) => <p key={s.source_region}>S{i + 1} · {tx(SOURCE_REGIONS.find(r => r.id === s.source_region)!.label)} · {tx('源')}{s.generation_source_index} · ({s.xyz_mm.map(v => v.toFixed(1)).join(', ')}) mm</p>)}
                </div>
              </details>}
              {catalogError && <output className="mt-2 block text-xs"><RuntimeMessage message={catalogError} /></output>}
            </fieldset>}
            {tx(
              mode === 'single_source' && (
                <label className="lab-label mt-3.5 block rounded-xl border border-border/70 bg-muted/30 p-3.5">
                  {tx('冻结生成源')}
                  <select
                    className="lab-select"
                    value={singleIndex}
                    onChange={(e) => setSingleIndex(Number(e.target.value))}
                    disabled={!catalog}
                  >
                    {tx(
                      !catalog ? (
                        <option value={singleIndex}>{tx('读取源目录…')}</option>
                      ) : (
                        catalog.sources.map((s) => (
                          <option key={s.id} value={s.id}>
                            {tx('源')}
                            {tx(s.id)} · {tx(SOURCE_REGIONS.find(r => r.id === s.roi_id)?.label ?? '其他皮层或分区边界')} · (
                            {tx(s.xyz_mm.map((v) => v.toFixed(1)).join(', '))}) mm
                          </option>
                        ))
                      ),
                    )}
                  </select>
                  {tx(
                    catalog && (
                      <span className="mt-2 block font-mono text-xs font-normal text-muted-foreground tabular-nums">
                        {tx('皮层法向：')}
                        {tx(
                          catalog.sources[singleIndex].normal
                            .map((v) => v.toFixed(4))
                            .join(', '),
                        )}{' '}
                        {tx(' · 坐标系：Ernie MRI RAS / mm')}
                      </span>
                    ),
                  )}
                  {tx(
                    catalogError && (
                      <span role="alert" className="mt-2 block text-danger">
                        <RuntimeMessage message={catalogError} />
                      </span>
                    ),
                  )}
                </label>
              ),
            )}
          </section>
        </div>
        <section
          className="lab-panel space-y-4"
          aria-label={tx('源实验设置')}
        >
          <h2 className="text-base font-semibold">{tx('3 · 选择信号条件')}</h2>
          <div className="grid items-end gap-4 rounded-xl border border-border/65 bg-muted/30 p-3.5 sm:grid-cols-2 lg:grid-cols-4">
            <label className="lab-label" hidden={mode !== 'multi_source'}>
              {tx('模拟脑源位置')}
              <select
                className="lab-select"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
              >
                {tx(
                  BRAIN_REGIONS.map(([k, label]) => (
                    <option key={k} value={k}>
                      {tx(label)}
                    </option>
                  )),
                )}
              </select>
            </label>
            <label className="lab-label">
              {tx('脑源波形')}
              <select
                className="lab-select"
                value={waveform}
                onChange={(e) =>
                  setWaveform(e.target.value as 'burst' | 'rhythm')
                }
              >
                <option value="burst">{tx('间歇振荡')}</option>
                <option value="rhythm">{tx('持续振荡')}</option>
              </select>
            </label>
            <label className="lab-label">
              {tx('模拟干扰幅度倍数')}
              <select
                className="lab-select"
                value={scale}
                onChange={(e) => setScale(Number(e.target.value))}
              >
                {tx(
                  [0, 0.5, 1, 2, 4].map((a) => (
                    <option key={a} value={a}>
                      {tx(a)}×
                    </option>
                  )),
                )}
              </select>
            </label>
            <label className="lab-label">
              {tx('随机种子（控制重复生成）')}
              <input
                className="lab-select font-mono tabular-nums"
                type="number"
                min={0}
                max={9999}
                step={1}
                value={seed}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  if (Number.isInteger(n) && n >= 0 && n <= 9999) setSeed(n);
                }}
              />
            </label>
          </div>
          <p className="text-xs leading-5 text-muted-foreground">
            {tx(
              selected?.dataset_id === 'design_evaluation' &&
                '已评价坐标按完整身份检查前向场：优先复用已有精确场，缺失时进入计算队列。',
            )}
            {tx(
              '1×标定：心电为标准64全脑先验信号标准差的1倍，眼电为3倍；随后共用同一空间场采样两套布局。2×表示干扰幅度翻倍、功率变为4倍。幅度倍数与接收SNR分别表示。',
            )}
          </p>
          {tx(
            selected?.dataset_id === 'cache' && !selected.compatible && (
              <p className="rounded-xl border border-warning/30 bg-warning-surface/75 p-3 text-xs leading-5 text-warning">
                {tx(
                  '历史布局：沿用该记录的原始64点坐标进行源场景对照。其计算版本与当前布局搜索不同，本页不重新检验当前表面准入或区域分离条件；结果归属于原坐标协议。',
                )}
              </p>
            ),
          )}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/70 pt-3.5">
            <div className="text-sm text-muted-foreground">
              {tx(
                !validSources ? '至少选择一个源区域才能运行。' : lookup.key === key
                  ? lookup.message
                  : selected
                    ? '查询相同源场景的缓存…'
                    : '请先选择一个已计算的完整布局。',
              )}
              {tx(
                busy && (
                  <output className="mt-1 block font-medium text-primary">
                    {tx(
                      sourceKey(active!.request) !== key
                        ? '另一源场景正在计算。'
                        : '',
                    )}
                    <RuntimeMessage
                      message={active!.message}
                      status={active!.status}
                      queuePosition={active!.queue_position}
                    />
                    {active!.status !== 'queued' && <>{' '}· {tx(Math.round(active!.progress * 100))}%</>}
                  </output>
                ),
              )}
              {tx(
                job && !running(job) && job.status !== 'completed' && (
                  <p className="mt-1 text-danger">
                    <RuntimeMessage message={job.message} status={job.status} />
                  </p>
                ),
              )}
            </div>
            <div className="flex gap-2">
              {tx(
                busy && (
                  <Button variant="outline" onClick={cancel}>
                    {tx('停止计算')}
                  </Button>
                ),
              )}
              <Button
                onClick={submit}
                disabled={!selected || !ready || !token || busy || submitting || !validSources}
              >
                {tx(
                  submitting
                    ? '正在提交…'
                    : result
                      ? '读取已保存结果'
                      : '4 · 开始信号仿真',
                )}
              </Button>
            </div>
          </div>
          {tx(
            error.key === key && error.message && (
              <p
                role="alert"
                className="text-sm text-danger"
              >
                <RuntimeMessage message={error.message} />
              </p>
            ),
          )}
        </section>
        {tx(
          library && id && !selected && (
            <p role="alert" className="lab-panel">
              {tx('指定记录没有可用的完整布局。请选择其他已计算布局。')}
            </p>
          ),
        )}
        {tx(
          result && selected ? (
            <Suspense fallback={<section className="lab-panel my-5 py-10 text-center text-sm text-muted-foreground">{tx('正在载入结果视图…')}</section>}>
            <ExperimentResult
              key={key}
              result={result}
              label={localizedRecordTitle(selected, locale)}
              ar={ar}
              setAR={setAR}
              cached={Boolean(job?.cached)}
              receiptId={job?.status === 'completed' ? job.id : undefined}
              sourceResultKey={job?.status === 'completed' ? job.key : undefined}
              onReduceArtifacts={lowerArtifactScale(scale) === null ? undefined : () => setScale(lowerArtifactScale(scale)!)}
            />
            </Suspense>
          ) : (
            <section className="lab-panel my-5 flex flex-col items-center py-10 text-center">
              <span aria-hidden="true" className="mb-3 grid size-9 place-items-center rounded-lg border border-border bg-secondary/70 text-foreground/75">
                <Activity className="size-4" />
              </span>
              <h2 className="text-lg font-semibold">
                {tx(
                  busy && sourceKey(active!.request) === key
                    ? '正在计算当前场景'
                    : '等待当前源场景的结果',
                )}
              </h2>
              <p className="mt-2 max-w-xl text-sm leading-6 text-ink-soft">
                {tx(
                  '完成后显示：源位置、两套接收波形、干净脑信号重建，以及0–4×干扰强度曲线。',
                )}
              </p>
              <p className="mt-3 rounded-full border border-border/75 bg-muted/50 px-3.5 py-1 font-mono text-xs text-muted-foreground">
                {tx(
                  '20秒模拟 · 200 Hz计算 · 8秒50 Hz预览 · 不下载新头模 · 结果独立缓存',
                )}
              </p>
            </section>
          ),
        )}
      </div>
    </main>
  );
}
