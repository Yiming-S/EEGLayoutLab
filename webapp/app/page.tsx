'use client';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from "@/components/runtime-message";

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useMemo, useState } from 'react';
import { LineChart, Line, CartesianGrid, XAxis, YAxis, Tooltip, Legend, ReferenceLine, ResponsiveContainer, Dot } from 'recharts';
import { SiteHeader } from '@/components/site-header';
import { SavedLayoutDetails } from '@/components/saved-layout-details';
import { preserveResultsContext } from '@/lib/results-library';
import { percent } from '@/components/performance-summary';
import { Button } from '@/components/ui/button';
import { HomePlacementOptions, PlacementDesignPresets } from '@/components/placement-options';
import { areaRows, assessment, areaConclusion, methodLink, parseAR, REGION_COUNTS, AREA_CAPS, METRICS } from '@/lib/lab-workflow';
import type { LocalLibrary } from '@/lib/local-library';

const colors = ['#0d8178', '#c08030', '#7b6fc2', '#bc577c', '#416ca0'];
export default function Home() {
  const { tx } = useLanguage();
  const [data, setData] = useState<LocalLibrary | null>(null);
  const [viewContext, setViewContext] = useState('');
  const [domain, setDomain] = useState('whole_scalp_free'), [area, setArea] = useState(120), [r, setR] = useState(2), [ar, setAR] = useState(90);
  const [metric, setMetric] = useState<(typeof METRICS)[number]['key']>('field_relative');
  const [error, setError] = useState(''), [retry, setRetry] = useState(0), [ready, setReady] = useState(false);
  useEffect(() => {
    const restore = () => {
      const q = new URLSearchParams(window.location.search);
      setViewContext(window.location.search);
      if (q.has('saved')) { window.location.replace(`/design?${q.toString()}`); return; }
      setDomain(q.get('domain') === 'low_hair_free' ? 'low_hair_free' : 'whole_scalp_free');
      setArea(AREA_CAPS.includes(Number(q.get('area'))) ? Number(q.get('area')) : 120);
      setR(REGION_COUNTS.includes(Number(q.get('r'))) ? Number(q.get('r')) : 2);
      setAR(parseAR(q.get('ar'))); setMetric(METRICS.find((m) => m.key === q.get('metric'))?.key ?? 'field_relative'); setReady(true);
    };
    restore(); window.addEventListener('popstate', restore); return () => window.removeEventListener('popstate', restore);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/local-compute/library', { signal: controller.signal, cache: 'no-store' }).then(async (response) => {
      if (!response.ok) throw new Error('当前比较需要连接本机数据服务。请启动本地App后重新读取。');
      const value = await response.json() as LocalLibrary;
      if (value.schema !== 'local-data-library/1') throw new Error('结果目录格式不符');
      setData(value); setError('');
    }).catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [retry]);
  const rows = areaRows(data?.records ?? [], domain, area), selected = rows.find((row) => row?.region_count === r);
  useEffect(() => { if (ready) window.history.replaceState(null, '', preserveResultsContext(`/?domain=${domain}&area=${area}&r=${r}&ar=${ar}&metric=${metric}`, viewContext)); }, [ready, domain, area, r, ar, metric, viewContext]);
  const curve = useMemo(() => AREA_CAPS.map((a) => {
    const point: Record<string, number | null> = { area: a };
    areaRows(data?.records ?? [], domain, a).forEach((row, i) => { const value = row?.metrics?.[metric]; point[`r${REGION_COUNTS[i]}`] = value == null ? null : value * 100; });
    return point;
  }), [data, domain, metric]);
  const inspect = (count: number) => { setR(count); document.getElementById('selected-layout')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
  const here = preserveResultsContext(`/?domain=${domain}&area=${area}&r=${r}&ar=${ar}&metric=${metric}`, viewContext);
  return <main className="lab-page">
    <SiteHeader current="compare" arPercent={ar} labHref={here} returnHref={here} selection={{ id: selected?.id ?? null, phase: "saved" }} />
    <div className="lab-container">
      <header className="flex flex-wrap items-center justify-between gap-3 py-5"><div><h1 className="text-2xl font-semibold tracking-tight">{tx("实验总览")}</h1><p className="mt-1 text-base text-muted-foreground">{tx('64个电极，集中布置后还能保留多少信号？')}</p></div><a href="#create-layout" className="rounded-lg border bg-white px-4 py-2 text-sm font-medium text-primary">{tx('按部位创建布局 ↓')}</a></header>
      
      <HomePlacementOptions domain={domain} setDomain={setDomain}>
      <div className="grid items-start gap-4 border-t pt-4 md:grid-cols-[1fr_1fr_1.3fr]">
        <label className="lab-label">{tx("区域表面总面积上限")}<select className="lab-select" value={area} onChange={(e) => setArea(Number(e.target.value))}>{tx(AREA_CAPS.map((n) => <option key={n} value={n}>{tx(n)} {tx(" cm² · 各区域合计面积")}</option>))}</select></label>
        <fieldset><legend className="mb-2 text-sm font-semibold">{tx('查看几个区域的布局？')}</legend><div className="flex flex-wrap gap-1.5">{REGION_COUNTS.map(count => <Button key={count} size="sm" variant={r === count ? 'default' : 'outline'} aria-pressed={r === count} onClick={() => setR(count)}>{tx(`${count}区`)}</Button>)}</div></fieldset>
        <label className="lab-label">{tx("接受阈值 AR · ")}{tx(ar)}%<input className="mt-4 w-full accent-primary" aria-label={tx("比较接受阈值AR")} type="range" min={10} max={100} step={1} value={ar} onChange={(e) => setAR(Number(e.target.value))} /><span className="mt-1 block text-xs font-normal text-muted-foreground">{tx("要求三项相对指标分别达到此阈值。")}</span></label>
      </div>
      <p className="text-xs leading-5 text-muted-foreground">{tx('切换以上条件只读取已有结果。单Ernie头模 · 标准64导名义SNR 20 dB。')}</p>
      </HomePlacementOptions>
      {tx(error && <div role="alert" className="lab-panel mb-4"><p><RuntimeMessage message={error} /></p><Button variant="outline" className="mt-3" onClick={() => setRetry((n) => n + 1)}>{tx("重新读取")}</Button></div>)}
      {tx(data?.warnings.length ? <details className="mb-4 text-sm text-amber-800"><summary>{tx("部分数据未载入")}</summary>{tx(data.warnings.map((w) => <p key={w}>{tx(w)}</p>))}</details> : null)}
      {tx(!data && !error ? <p className="lab-panel">{tx("正在读取已有比较，不运行仿真…")}</p> : data && <>
        <section id="selected-layout" className="scroll-mt-[calc(var(--workspace-header-height,160px)+16px)]">
          {selected ? <SavedLayoutDetails key={selected.id} summary={selected} ar={ar} returnHref={here} compact /> : <p className="lab-panel">{tx("此配置暂无记录。可选择其他配置，或前往布局设计计算。")}</p>}
        </section>
        <section className="lab-panel relative mt-6 overflow-x-auto" aria-label={tx("五种区域数量统一比较")}>
          <h2 className="mb-4 text-lg font-semibold">{tx('相同面积上限下，几个区域更合适？')}</h2>
          <table className="w-full min-w-[820px] text-left text-sm"><thead><tr className="border-b text-muted-foreground"><th className="pb-3">{tx("区域数 / 各区电极数")}</th><th>{tx("实际区域总面积")}</th>{tx(METRICS.map((m) => <th key={m.key}>{tx(m.label)}</th>))}<th>{tx("最低保留要求 ")}{tx(ar)}%</th><th><span className="sr-only">{tx("操作")}</span></th></tr></thead><tbody>
            {tx(rows.map((row, i) => { const count = REGION_COUNTS[i], a = assessment(row?.metrics, ar), shortfall = row?.geometry && row.geometry.union_area_cm2 < area * .99;
              return <tr key={count} className={`border-b last:border-0 ${r === count ? 'bg-primary/5' : ''}`}>
                <th className="py-4 font-semibold">{tx(count)}{tx("个区域")}<span className="mt-1 block font-mono text-xs font-normal text-muted-foreground">{tx(Array.from({ length: count }, (_, j) => Math.floor(64 / count) + Number(j < 64 % count)).join(' + '))}</span></th>
                <td>{tx(row?.geometry ? `${row.geometry.union_area_cm2.toFixed(1)} cm²` : '未记录')}{tx(shortfall && <span className="block text-xs text-amber-800">{tx("未用满面积预算")}</span>)}</td>
                {tx(METRICS.map((m) => { const value = row?.metrics?.[m.key], valid = value != null && Number.isFinite(value); return <td className="font-mono" key={m.key}>{tx(percent(value))}{valid && <span className={`mt-1 block font-sans text-xs ${value >= ar / 100 ? 'text-primary' : 'text-muted-foreground'}`}>{tx(value >= ar / 100 ? '达标' : '未达标')}</span>}</td>; }))}
                <td className={a.state === 'pass' ? 'font-medium text-primary' : 'text-muted-foreground'}>{tx(!row ? '暂无数据' : a.state === 'pass' ? '三项达标' : a.state === 'undefined' ? '无法判断' : `${METRICS.filter(m => row.metrics?.[m.key] != null && row.metrics[m.key]! >= ar / 100).length}/3项达标`)}{row && a.state === 'fail' && <span className="mt-1 block text-xs">{tx('联合要求未通过')}</span>}</td>
                <td><Button size="sm" variant="outline" disabled={!row} onClick={() => inspect(count)}>{tx("查看布局与指标")}</Button></td>
              </tr>;
            }))}
            <tr className="border-t bg-secondary/40"><th className="py-3">{tx("标准全头64导")}</th><td>{tx("全头分布")}</td><td>100%</td><td>100%</td><td>100%</td><td colSpan={2}>{tx("同协议归一化基准")}</td></tr>
          </tbody></table>
          <p className="mt-3 text-xs leading-5 text-muted-foreground">{tx("各布局的实际面积可低于相同上限，表中已标记。三项指标分别评价重建、幅度和定位，各行采用同一预设优化目标。采用4,096点定位字典和256个生成源；半径约束实验另列。")}</p>
        </section>
        <section className="lab-panel mt-6">
          <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-lg font-semibold">{tx("扩大总面积后，性能怎样变化？")}</h2><p className="mt-2 text-sm text-muted-foreground">{tx("仅连接已测的60、120、180 cm²条件。点击曲线上的已计算点查看对应方案。")}</p></div>
            <label className="lab-label">{tx("曲线指标")}<select value={metric} onChange={(e) => setMetric(e.target.value as typeof metric)} className="lab-select">{tx(METRICS.map((m) => <option value={m.key} key={m.key}>{tx(m.label)}</option>))}</select></label></div>
          <div className="mt-5 h-[300px]"><ResponsiveContainer width="100%" height="100%"><LineChart data={curve} margin={{ top: 12, right: 20, left: 4, bottom: 8 }}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="area" unit=" cm²" /><YAxis unit="%" domain={[0, 'auto']} /><Tooltip formatter={(v) => tx(v == null ? '未定义' : `${Number(v).toFixed(2)}%`)} labelFormatter={(v) => tx(`总面积上限 ${v} cm²`)} /><Legend /><ReferenceLine y={ar} stroke="#aa792a" strokeDasharray="4 4" label={tx(`AR ${ar}%`)} /><ReferenceLine y={100} stroke="#73878a" strokeDasharray="2 3" />
            {tx(REGION_COUNTS.map((n, i) => <Line key={n} name={tx(`${n}区`)} dataKey={`r${n}`} stroke={colors[i]} strokeWidth={2} connectNulls={false} isAnimationActive={false} dot={{ r: 4 }} activeDot={(point) => <Dot {...point} r={7} style={{ cursor: 'pointer' }} onClick={() => { const a = (point.payload as { area?: number })?.area; if (a && AREA_CAPS.includes(a)) { setArea(a); inspect(n); } }} />} />))}
          </LineChart></ResponsiveContainer></div>
          <div className="mt-4 grid gap-3 sm:grid-cols-5">{tx(REGION_COUNTS.map((n) => <div key={n} className="rounded-lg bg-secondary/60 p-3 text-sm"><span className="font-semibold">{tx(n)}{tx("区")}</span><p className="mt-1">{tx(areaConclusion(data.records, domain, n, ar))}</p></div>))}</div>
          <p className="mt-3 text-xs text-muted-foreground">{tx("“首个达标”指三个已计算面积档位中达到AR的最小上限。当前结果采用单Ernie头模，独立头模验证另列阶段。")}</p>
          <p className="mt-2 text-sm text-muted-foreground">{tx('曲线阈值线对应当前所选指标；三项联合判断见上方比较表。')}</p>
        </section>
      </>)}
      <PlacementDesignPresets ar={ar} />
      <details className="mt-6 text-sm text-muted-foreground"><summary className="cursor-pointer">{tx('本页实验条件与阅读说明')}</summary><p className="mt-3 leading-6">{tx("总数固定64个电极。选择允许范围与总面积上限，比较1、2、3、4、6个区域的已有仿真结果。本页不运行新计算；也可从导航直接进入布局设计。")}</p><p className="mt-2 leading-6">{tx("本页范围：总面积上限约束实验 · 区域互不相接")}{tx(" · 单Ernie头模 · 标准64导名义SNR＝20 dB。少毛发候选区按模型坐标近似定义。")}</p><p className="mt-2 leading-6">{tx('全头候选区：不限制毛发位置，由算法选择区域。')}</p><p className="mt-2 leading-6">{tx('少毛发候选区：耳后、前额与眶周的模型近似范围，不包含完整扩展耳周。')}</p></details>
      <details className="my-6 text-sm text-muted-foreground"><summary className="cursor-pointer">{tx("历史实验与计算细节")}</summary><p className="mt-3 leading-6">{tx("本页使用30个总面积上限约束主布局，固定min(信号重建,敏感度)优化分支。其他实验协议在历史记录中单独查看。")}</p><div className="mt-3 flex flex-wrap gap-5 text-primary"><a href={`/library?history=1&ar=${ar}`}>{tx("查看历史方案")}</a><a href={`/results?ar=${ar}`}>{tx("早期半径实验完整曲线")}</a><a href={methodLink(here, ar)}>{tx("方法与证据边界")}</a></div></details>
    </div>
  </main>;
}
