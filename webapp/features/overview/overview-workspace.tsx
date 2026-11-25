'use client';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from "@/components/runtime-message";

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useState } from 'react';
import { ArrowDown, ArrowUpRight, ChevronDown } from 'lucide-react';
import { useOverviewController } from './use-overview-controller';
import { LineChart, Line, CartesianGrid, XAxis, YAxis, Tooltip, Legend, ReferenceLine, ResponsiveContainer, Dot } from 'recharts';
import { SiteHeader } from '@/components/site-header';
import { SavedLayoutDetails } from '@/components/saved-layout-details';
import { OutcomeBadge, RetentionBar } from '@/components/retention-bar';
import { ThresholdSlider } from '@/components/threshold-slider';
import { stackedAction, stackedBody, stackedCell, stackedHead, stackedRow, stackedTitle } from '@/lib/responsive-table';
import { cn } from '@/lib/utils';
import { Button, buttonVariants } from '@/components/ui/button';
import { Sheet } from '@/components/ui/sheet';
import { HomePlacementOptions, PlacementDesignPresets } from '@/components/placement-options';
import { assessment, areaConclusion, methodLink, REGION_COUNTS, AREA_CAPS, METRICS } from '@/lib/lab-workflow';

/** First-visit orientation: sleek 3-column architectural hairline strip. */
function GettingStarted({ ar }: { ar: number }) {
  const { tx } = useLanguage();
  const steps = [
    { title: '查看已有结果', text: '比较1–6个区域在相同面积下保留多少信号。', href: '#area-comparison' },
    { title: '设计新布局', text: '选择部位和每区半径，计算并保存新的64电极布局。', href: '/design?ar=' + ar },
    { title: '信号仿真', text: '用同一模拟脑源，对照标准64导与新布局的接收信号。', href: '/reception?ar=' + ar },
  ];
  return (
    <nav
      aria-label={tx('三步上手')}
      className="mb-5 grid divide-y divide-border overflow-hidden rounded-xl border border-border bg-card shadow-[0_1px_2px_rgba(20,20,19,0.025)] sm:grid-cols-3 sm:divide-x sm:divide-y-0"
    >
      {steps.map((step, index) => (
        <a
          key={step.title}
          href={step.href}
          className="group flex items-start justify-between gap-3 px-4 py-3.5 transition-colors hover:bg-secondary/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        >
          <span className="flex min-w-0 items-start gap-3">
            <span className="mt-0.5 font-mono text-[11px] font-medium tracking-wider text-muted-foreground">
              0{index + 1}
            </span>
            <span className="min-w-0">
              <span className="block text-[0.8125rem] font-semibold text-foreground">{tx(step.title)}</span>
              <span className="mt-0.5 hidden text-xs leading-5 text-muted-foreground sm:block">{tx(step.text)}</span>
            </span>
          </span>
          <ArrowUpRight aria-hidden className="mt-0.5 size-3.5 shrink-0 text-muted-foreground/50 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-foreground" />
        </a>
      ))}
    </nav>
  );
}

/** The early batches, read-only on their own pages (design 0004, section 7). */
const HISTORICAL_BATCHES = [
  { path: '/results', title: '历史半径实验 · 原始比较', date: '2026-09-08', protocol: '每区半径上限，区域允许相交 · 单Ernie头模' },
  { path: '/pilot-results', title: '历史原型：双区域初始布局', date: '2026-09-08', protocol: '两个32电极区域按几何规则构造，未做优化 · 单Ernie头模' },
] as const;
const colors = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)'];
export default function OverviewWorkspace() {
  const { tx } = useLanguage();
  const [detailsOpen, setDetailsOpen] = useState(false);
  const { data, domain, setDomain, area, setArea, r, setR, ar, setAR, metric, setMetric, error, setRetry, rows, selected, curve, inspect, here } = useOverviewController();
  const openDetails = (count: number) => { inspect(count); setDetailsOpen(true); };
  const plotted = curve.flatMap(point => REGION_COUNTS.flatMap(n => { const value = point[`r${n}`]; return value != null && Number.isFinite(value) ? [value] : []; }));
  const lowest = plotted.reduce((low, value) => value < low ? value : low, ar);
  const highest = plotted.reduce((high, value) => value > high ? value : high, 100);
  const yMin = Math.max(0, Math.floor((lowest - 5) / 10) * 10), yMax = Math.ceil(highest / 10) * 10;
  const conclusions = (records: Parameters<typeof areaConclusion>[0]) => {
    const groups = new Map<string, number[]>();
    for (const n of REGION_COUNTS) { const text = areaConclusion(records, domain, n, ar); groups.set(text, [...(groups.get(text) ?? []), n]); }
    return [...groups].map(([text, counts]) => ({ text, counts }));
  };
  return <main className="lab-page">
    <SiteHeader current="findings" arPercent={ar} labHref={here} returnHref={here} selection={{ id: selected?.id ?? null, phase: "saved" }} />
    <div className="lab-container">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-border pt-7 pb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.028em] sm:text-[1.65rem]">{tx("总面积研究")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{tx('64个电极，集中布置后还能保留多少信号？')}</p>
        </div>
        <a href="#create-layout" className={buttonVariants({ variant: 'outline', size: 'sm' })}>
          {tx('按部位创建布局 ↓')}
          <ArrowDown aria-hidden className="size-3.5" />
        </a>
      </header>
      <GettingStarted ar={ar} />

      <HomePlacementOptions domain={domain} setDomain={setDomain}>
      <div className="grid items-start gap-4 rounded-lg border border-border bg-secondary/35 p-4 md:grid-cols-[1fr_1fr_1.3fr]">
        <label className="lab-label">{tx("区域表面总面积上限")}<select className="lab-select" value={area} onChange={(e) => setArea(Number(e.target.value))}>{tx(AREA_CAPS.map((n) => <option key={n} value={n}>{tx(n)} {tx(" cm² · 各区域合计面积")}</option>))}</select></label>
        <fieldset>
          <legend className="mb-1.5 text-[0.8125rem] font-medium">{tx('查看几个区域的布局？')}</legend>
          <div className="flex flex-wrap gap-1 rounded-md border border-border bg-card p-1">
            {REGION_COUNTS.map(count => <Button key={count} size="sm" variant={r === count ? 'default' : 'ghost'} className="flex-1 px-2" aria-pressed={r === count} onClick={() => setR(count)}>{tx(`${count}区`)}</Button>)}
          </div>
        </fieldset>
        <ThresholdSlider value={ar} onChange={setAR} ariaLabel="比较接受阈值AR" term="ar" hint="要求三项相对指标分别达到此阈值。" />
      </div>
      <p className="text-xs leading-5 text-muted-foreground">{tx('切换以上条件只读取已有结果。单Ernie头模 · 标准64导名义SNR 20 dB。')}</p>
      </HomePlacementOptions>
      {tx(error && <div role="alert" className="lab-panel mb-4"><p><RuntimeMessage message={error} /></p><Button variant="outline" className="mt-3" onClick={() => setRetry((n) => n + 1)}>{tx("重新读取")}</Button></div>)}
      {tx(data?.warnings.length ? <details className="mb-4 text-sm text-warning"><summary>{tx("部分数据未载入")}</summary>{tx(data.warnings.map((w) => <p key={w}>{tx(w)}</p>))}</details> : null)}
      {tx(!data && !error ? <p className="lab-panel">{tx("正在读取已有比较，不运行仿真…")}</p> : data && <>
        <Sheet open={detailsOpen && !!selected} onOpenChange={setDetailsOpen} closeLabel={tx('关闭方案详情')}
          title={tx('方案详情')} description={tx('总面积上限约束实验 · 只读，不触发计算')}>
          {selected && <SavedLayoutDetails key={selected.id} summary={selected} ar={ar} returnHref={here} compact />}
        </Sheet>
        <section id="area-comparison" className="lab-panel relative scroll-mt-[calc(var(--workspace-header-height,160px)+16px)]" aria-label={tx("五种区域数量统一比较")}>
          <h2 className="mb-4 text-base font-semibold">{tx('相同面积上限下，几个区域更合适？')}</h2>
          <div className="rounded-lg border border-border bg-card md:overflow-x-auto">
            <table className="w-full text-left text-sm md:min-w-[840px]">
              <thead className={stackedHead}>
                <tr className="border-b border-border bg-secondary/55 text-xs font-medium tracking-wide text-muted-foreground">
                  <th className="px-4 py-2.5">{tx("区域数 / 各区电极数")}</th>
                  <th className="px-3 py-2.5">{tx("实际区域总面积")}</th>
                  {tx(METRICS.map((m) => <th key={m.key} className="px-3 py-2.5">{tx(m.label)}</th>))}
                  <th className="px-3 py-2.5">{tx("最低保留要求 ")}{tx(ar)}%</th>
                  <th className="px-4 py-2.5"><span className="sr-only">{tx("操作")}</span></th>
                </tr>
              </thead>
              <tbody className={stackedBody}>
                {tx(rows.map((row, i) => { const count = REGION_COUNTS[i], a = assessment(row?.metrics, ar), shortfall = row?.geometry && row.geometry.union_area_cm2 < area * .99;
                  return <tr key={count} className={cn('border-b border-border/75 transition-colors last:border-0 md:hover:bg-secondary/35', stackedRow, r === count && 'bg-secondary/55')}>
                    <th className={cn('font-semibold md:px-4 md:py-3.5', stackedTitle)}>{tx(count)}{tx("个区域")}<span className="mt-1 block font-mono text-xs font-normal text-muted-foreground tabular-nums">{tx(Array.from({ length: count }, (_, j) => Math.floor(64 / count) + Number(j < 64 % count)).join(' + '))}</span></th>
                    <td data-label={tx('实际区域总面积')} className={cn(stackedCell, 'md:px-3')}><span className="font-mono text-[0.8125rem] tabular-nums">{tx(row?.geometry ? `${row.geometry.union_area_cm2.toFixed(1)} cm²` : '未记录')}{tx(shortfall && <span className="mt-0.5 block font-sans text-xs text-warning">{tx("未用满面积预算")}</span>)}</span></td>
                    {tx(METRICS.map((m) => <td data-label={tx(m.label)} className={cn(stackedCell, 'md:px-3')} key={m.key}><RetentionBar value={row?.metrics?.[m.key]} threshold={ar / 100} showBadge /></td>))}
                    <td data-label={tx(`最低保留要求 ${ar}%`)} className={cn(stackedCell, 'md:px-3')}>{!row ? <span className="text-muted-foreground">{tx('暂无数据')}</span> : <span><OutcomeBadge outcome={a.state as 'pass' | 'fail' | 'undefined'}>{tx(a.state === 'pass' ? '三项达标' : a.state === 'undefined' ? '无法判断' : `${METRICS.filter(m => row.metrics?.[m.key] != null && row.metrics[m.key]! >= ar / 100).length}/3项达标`)}</OutcomeBadge>{a.state === 'fail' && <span className="mt-1 block text-xs text-muted-foreground">{tx('联合要求未通过')}</span>}</span>}</td>
                    <td className={cn(stackedAction, 'md:px-4')}><Button size="sm" variant={r === count ? 'default' : 'outline'} className="max-md:w-full" disabled={!row} onClick={() => openDetails(count)}>{tx("查看布局与指标")}</Button></td>
                  </tr>;
                }))}
                <tr className={cn('border-t border-border bg-secondary/45', stackedRow)}><th className={cn('md:px-4 md:py-3', stackedTitle)}>{tx("标准全头64导")}</th><td data-label={tx('实际区域总面积')} className={cn(stackedCell, 'md:px-3')}>{tx("全头分布")}</td>{tx(METRICS.map((m) => <td key={m.key} data-label={tx(m.label)} className={cn(stackedCell, 'font-mono md:px-3')}>100%</td>))}<td colSpan={2} className={cn(stackedCell, 'max-md:before:content-none text-xs text-muted-foreground md:px-3')}>{tx("同协议归一化基准")}</td></tr>
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs leading-5 text-muted-foreground">{tx("各布局的实际面积可低于相同上限，表中已标记。三项指标分别评价重建、幅度和定位，各行采用同一预设优化目标。采用4,096点定位字典和256个生成源；半径约束实验另列。")}</p>
        </section>
        <section className="lab-panel mt-5">
          <div className="flex flex-wrap items-end justify-between gap-4"><div><h2 className="text-base font-semibold">{tx("扩大总面积后，性能怎样变化？")}</h2><p className="mt-1 text-[0.8125rem] text-muted-foreground">{tx("仅连接已测的60、120、180 cm²条件。点击曲线上的已计算点查看对应方案。")}</p></div>
            <label className="lab-label min-w-[200px]">{tx("曲线指标")}<select value={metric} onChange={(e) => setMetric(e.target.value as typeof metric)} className="lab-select">{tx(METRICS.map((m) => <option value={m.key} key={m.key}>{tx(m.label)}</option>))}</select></label></div>
          <div className="mt-4 h-[310px] rounded-lg border border-border bg-secondary/20 p-3"><ResponsiveContainer width="100%" height="100%"><LineChart data={curve} margin={{ top: 12, right: 76, left: 4, bottom: 8 }}><CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} /><XAxis dataKey="area" unit=" cm²" tick={{ fontSize: 12 }} /><YAxis unit="%" domain={[yMin, yMax]} allowDecimals={false} tick={{ fontSize: 12 }} /><Tooltip contentStyle={{ borderRadius: '0.5rem', borderColor: 'var(--border)' }} formatter={(v) => tx(v == null ? '未定义' : `${Number(v).toFixed(2)}%`)} labelFormatter={(v) => tx(`总面积上限 ${v} cm²`)} /><Legend /><ReferenceLine y={ar} stroke="var(--chart-threshold)" strokeDasharray="4 4" ifOverflow="extendDomain" label={{ value: tx(`要求 ${ar}%`), position: 'right', fill: 'var(--chart-threshold)', fontSize: 12 }} /><ReferenceLine y={100} stroke="var(--chart-reference)" strokeDasharray="2 3" ifOverflow="extendDomain" label={{ value: tx('标准64导'), position: 'right', fill: 'var(--chart-reference)', fontSize: 12 }} />
            {tx(REGION_COUNTS.map((n, i) => <Line key={n} name={tx(`${n}区`)} dataKey={`r${n}`} stroke={colors[i]} strokeWidth={2} connectNulls={false} isAnimationActive={false} dot={{ r: 3.5 }} activeDot={(point) => <Dot {...point} r={6} style={{ cursor: 'pointer' }} onClick={() => { const a = (point.payload as { area?: number })?.area; if (a && AREA_CAPS.includes(a)) { setArea(a); openDetails(n); } }} />} />))}
          </LineChart></ResponsiveContainer></div>
          <p className="mt-3 text-xs text-muted-foreground">{tx('曲线阈值线对应当前所选指标；下方结论要求三项指标均达到最低保留要求。')}</p>
          <h3 className="mt-5 text-sm font-semibold">{tx('三项联合达标情况')}</h3>
          <ul className="mt-2.5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{conclusions(data.records).map(({ text, counts }) => <li key={text} className={cn('flex items-start gap-3 rounded-lg border p-3 text-sm', text.startsWith('首个达标') ? 'border-success/30 bg-success-surface/75' : text === '已测范围内未达标' ? 'border-warning/30 bg-warning-surface/75' : 'border-border bg-secondary/40')}>
            <span className="flex shrink-0 flex-wrap gap-1">{counts.map(n => <span key={n} className="rounded border border-border bg-card px-1.5 py-0.5 font-mono text-xs font-medium tabular-nums">{tx(`${n}区`)}</span>)}</span>
            <span className={cn('text-[0.8125rem] font-medium', text.startsWith('首个达标') ? 'text-success' : text === '已测范围内未达标' ? 'text-warning' : '')}>{tx(text)}</span></li>)}</ul>
          <p className="mt-3 text-xs text-muted-foreground">{tx("“首个达标”指三个已计算面积档位中达到AR的最小上限。当前结果采用单Ernie头模，独立头模验证另列阶段。")}</p>
        </section>
      </>)}
      <PlacementDesignPresets ar={ar} />
      <details className="group mt-5 rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
        <summary className="flex cursor-pointer list-none items-center justify-between text-[0.8125rem] font-medium text-foreground/85 select-none [&::-webkit-details-marker]:hidden">
          <span>{tx('本页实验条件与阅读说明')}</span>
          <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open:rotate-180" />
        </summary>
        <div className="mt-3 space-y-2 border-t border-border pt-3 text-[0.8125rem] leading-6">
          <p>{tx("总数固定64个电极。选择允许范围与总面积上限，比较1、2、3、4、6个区域的已有仿真结果。本页不运行新计算；也可从导航直接进入布局设计。")}</p>
          <p>{tx("本页范围：总面积上限约束实验 · 区域互不相接")}{tx(" · 单Ernie头模 · 标准64导名义SNR＝20 dB。少毛发候选区按模型坐标近似定义。")}</p>
          <p>{tx('全头候选区：不限制毛发位置，由算法选择区域。')}</p>
          <p>{tx('少毛发候选区：耳后、前额与眶周的模型近似范围，不包含完整扩展耳周。')}</p>
        </div>
      </details>
      <section id="historical-batches" aria-labelledby="historical-batches-title" className="lab-panel my-5">
        <h2 id="historical-batches-title" className="text-base font-semibold">{tx('历史批次')}</h2>
        <p className="mt-1 text-[0.8125rem] text-muted-foreground">{tx('两个早期批次按各自协议保留，只读查看；它们的分数只评价各自的布局，不与本页结果混合。')}</p>
        <ul className="mt-4 grid gap-3 md:grid-cols-2">{HISTORICAL_BATCHES.map(batch => <li key={batch.path} className="rounded-lg border border-border bg-secondary/30 p-4 transition-colors hover:border-foreground/25 hover:bg-card">
          <a className="text-sm font-semibold text-foreground underline decoration-border underline-offset-4 hover:decoration-foreground" href={`${batch.path}?ar=${ar}`}>{tx(batch.title)}</a>
          <p className="mt-1.5 text-[0.8125rem] leading-6 text-muted-foreground">{tx(batch.protocol)}</p>
          <p className="mt-1.5 font-mono text-[11px] text-muted-foreground tabular-nums">{tx('计算日期')} · <time dateTime={batch.date}>{batch.date}</time></p>
        </li>)}</ul>
        <div className="mt-4 flex flex-wrap gap-2"><a className="lab-link-pill" href={`/library?history=1&ar=${ar}`}>{tx("查看历史方案")}</a><a className="lab-link-pill" href={methodLink(here, ar)}>{tx("方法与证据边界")}</a></div>
      </section>
    </div>
  </main>;
}
