'use client';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from "@/components/runtime-message";
import { localizedRecordTitle, recordSearchText } from "@/lib/i18n/records";

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useMemo, useState } from 'react';
import { RefreshCcw } from 'lucide-react';
import { SiteHeader } from '@/components/site-header';
import { SavedLayoutDetails } from '@/components/saved-layout-details';
import { preserveResultsContext, resultQualification } from '@/lib/results-library';
import { Button } from '@/components/ui/button';
import { percent } from '@/components/performance-summary';
import { comparisonLink, parseAR, radiusDesignLink } from '@/lib/lab-workflow';
import type { LocalLibrary } from '@/lib/local-library';
import { protocolName, parseLibraryView, libraryViewLink } from '@/lib/ui-language';

export default function LibraryPage() {
  const { tx, locale, date } = useLanguage();
  const [data, setData] = useState<LocalLibrary | null>(null);
  const [viewContext, setViewContext] = useState('');
  const [sort, setSort] = useState('newest');
  const [selectedId, setSelectedId] = useState(''), [explicitSelection, setExplicitSelection] = useState(false);
  const [region, setRegion] = useState(0), [filter, setFilter] = useState('all'), [search, setSearch] = useState(''), [page, setPage] = useState(0);
  const [ar, setAR] = useState(90), [ready, setReady] = useState(false), [error, setError] = useState(''), [retry, setRetry] = useState(0);
  useEffect(() => {
    const restore = () => {
    const q = new URLSearchParams(window.location.search), id = q.get('record');
    const view = parseLibraryView(q);
    setViewContext(window.location.search); setSort(['newest', 'oldest', 'name'].includes(q.get('sort') ?? '') ? q.get('sort')! : 'newest');
    setAR(parseAR(q.get('ar'))); setFilter(view.filter); setRegion(view.region); setSearch(view.search); setPage(view.page);
    setExplicitSelection(Boolean(id)); setSelectedId(id ?? '');
    setReady(true);
    };
    restore(); window.addEventListener('popstate', restore); return () => window.removeEventListener('popstate', restore);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/local-compute/library', { signal: controller.signal, cache: 'no-store' }).then(async (r) => {
      if (!r.ok) throw new Error('本机数据服务未连接。请启动本地App后重新读取。');
      const value = await r.json() as LocalLibrary;
      if (value.schema !== 'local-data-library/1') throw new Error('方案目录格式错误');
      setData(value); setError('');
    }).catch((e) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [retry]);
  const choices = useMemo(() => data?.records.filter((r) => (filter === 'all' || (filter === 'current' ? ['strict_area', 'cache'].includes(r.dataset_id) : r.dataset_id === filter)) && (!region || r.region_count === region) && recordSearchText(r).includes(search.toLowerCase())).sort((a, b) => sort === 'name'
    ? localizedRecordTitle(a, locale).localeCompare(localizedRecordTitle(b, locale)) || a.id.localeCompare(b.id)
    : (sort === 'oldest' ? 1 : -1) * ((Date.parse(a.finished_at ?? '') || 0) - (Date.parse(b.finished_at ?? '') || 0)) || a.id.localeCompare(b.id)) ?? [], [data, filter, region, search, sort, locale]);
  const pages = Math.max(1, Math.ceil(choices.length / 10));
  const displayPage = data ? Math.min(page, pages - 1) : page;
  const selected = explicitSelection ? data?.records.find((r) => r.id === selectedId) : choices.find((r) => r.id === selectedId) ?? choices[displayPage * 10] ?? choices[0];
  const id = selected?.id;
  const listed = choices.slice(displayPage * 10, (displayPage + 1) * 10);
  useEffect(() => {
    if (!ready) return;
    window.history.replaceState(null, '', preserveResultsContext(libraryViewLink(ar, id ?? (explicitSelection ? selectedId : ''), { filter, region, search, page: displayPage }), viewContext) + '&sort=' + sort);
  }, [ready, id, ar, explicitSelection, selectedId, filter, region, search, displayPage, viewContext, sort]);
  const choose = (value: string) => { setSelectedId(value); setExplicitSelection(true); document.getElementById('record-details')?.scrollIntoView({ behavior: 'smooth' }); };
  const changeFilter = (value: string) => { setFilter(value); setSelectedId(''); setExplicitSelection(false); setPage(0); };
  const editHref = selected ? radiusDesignLink(selected, ar) : null;
  const labHref = selected?.dataset_id === 'strict_area' ? comparisonLink(selected, ar) : editHref ?? '/?ar=' + ar;
  const here = preserveResultsContext(libraryViewLink(ar, id ?? (explicitSelection ? selectedId : ''), { filter, region, search, page: displayPage }), viewContext) + '&sort=' + sort;
  return <main className="lab-page">
    <SiteHeader current="library" arPercent={ar} labHref={labHref} returnHref={here} selection={{ id: selected?.id ?? null, phase: "saved" }} />
    <div className="lab-container">
      <header className="flex flex-wrap items-end justify-between gap-4 py-6"><div><h1 className="text-2xl font-semibold">{tx("布局记录")}</h1><p className="mt-2 text-base text-muted-foreground">{tx("找回布局、指标和未找到布局的搜索记录。按实验类型分开阅读；本页只读取记录，不会启动计算。")}</p></div><Button variant="outline" onClick={() => setRetry((n) => n + 1)}><RefreshCcw className="size-4" />{tx("刷新记录")}</Button></header>
      
      <a className="mb-4 inline-block text-sm text-primary underline" href={'/electrodes?ar=' + ar + '#records'}>{tx('查看可变电极数的独立编辑记录 →')}</a>
      {tx(error && <p role="alert" className="lab-panel mb-4 text-red-800"><RuntimeMessage message={error} /> <a href={'/results?ar=' + ar} className="underline">{tx("仍可查看已导出的历史半径结果")}</a></p>)}
      <div className="lab-panel mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="lab-label">{tx("实验类型")}<select className="lab-select" value={filter} onChange={(e) => changeFilter(e.target.value)}><option value="all">{tx("全部已收录记录")}</option><option value="design_evaluation">{tx("已评价坐标布局")}</option><option value="current">{tx("面积实验与按需计算记录")}</option><option value="strict_area">{tx("总面积上限约束实验")}</option><option value="cache">{tx("每区半径约束计算")}</option><option value="historical_area">{tx("历史面积实验 · 原坐标范围")}</option><option value="offline_radius">{tx("历史实验 · 允许区域相交")}</option></select></label>
        <label className="lab-label">{tx("电极分布区域数")}<select className="lab-select" value={region} onChange={(e) => { setRegion(Number(e.target.value)); setPage(0); setExplicitSelection(false); }}><option value={0}>{tx("全部区域数量")}</option>{tx([1, 2, 3, 4, 6].map((r) => <option value={r} key={r}>{tx(`${r}个区域`)}</option>))}</select></label>
        <label className="lab-label">{tx("查找方案")}<input className="lab-select" placeholder={tx("例如：耳后、前额、2个区域")} value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); setExplicitSelection(false); }} /></label>
        <label className="lab-label">{tx("最低保留要求 ")}{ar}%<input className="mt-3 w-full accent-primary" aria-label={tx("记录接受阈值AR")} type="range" min={10} max={100} value={ar} onChange={(event) => setAR(Number(event.target.value))} /><span className="mt-1 block text-sm font-normal text-muted-foreground">{tx("只判断原记录，不重新计算。")}</span></label>
      </div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
        <p className="text-sm leading-6 text-muted-foreground">{tx("收录已有布局与搜索记录；不同协议分别解释。电极编辑记录保留独立入口。")}</p>
        <label className="lab-label">{tx("排序方式")}<select className="lab-select" value={sort} onChange={(event) => { setSort(event.target.value); setPage(0); }}><option value="newest">{tx("最近保存优先")}</option><option value="oldest">{tx("最早保存优先")}</option><option value="name">{tx("按方案名称")}</option></select></label>
      </div>
      {tx(data?.warnings.map((w) => <p className="mb-3 text-sm text-amber-800" key={w}>{tx(w)}</p>))}
      {tx(!data && !error ? <p className="lab-panel">{tx("读取方案目录…")}</p> : data && <>
        <section className="lab-panel overflow-x-auto" aria-label={tx("已保存方案列表")}>
          <table className="w-full min-w-[850px] text-left text-sm"><thead><tr className="border-b text-muted-foreground"><th className="pb-3">{tx("方案")}</th><th>{tx("实验类型")}</th><th>{tx("信号重建保留率")}</th><th>{tx("计算状态")}</th><th>{tx("性能判断")}</th><th><span className="sr-only">{tx("操作")}</span></th></tr></thead><tbody>
            {tx(listed.map((row) => <tr className={'border-b last:border-0 ' + (row.id === id ? 'bg-primary/5' : '')} key={row.id}><th className="max-w-[340px] py-3 pr-4 font-medium leading-6">{localizedRecordTitle(row, locale)}<span className="mt-1 block font-mono text-xs text-muted-foreground">{tx("记录 ")}{tx(row.id.slice(0, 10))}{tx(row.finished_at ? " · " + date(row.finished_at) : "")}</span></th><td>{tx(protocolName(row.dataset_id))}</td><td className="font-mono">{tx(row.status === 'no_layout' ? '未评估' : percent(row.metrics?.field_relative))}</td><td>{tx(row.status === 'no_layout' ? '本轮未找到完整布局' : '布局已评估')}{tx(row.dataset_id === 'cache' && !row.compatible && <span className="block text-xs text-amber-800">{tx("旧版本记录 · 仅供查阅")}</span>)}</td><td>{tx(resultQualification(row, ar))}</td><td><Button variant="outline" size="sm" onClick={() => choose(row.id)}>{tx("查看结果")}</Button></td></tr>))}
          </tbody></table>
          {tx(!choices.length && <p className="py-5 text-sm text-muted-foreground">{tx("当前筛选下没有记录。")}</p>)}
          <div className="mt-3 flex items-center justify-between gap-4 text-sm text-muted-foreground"><span>{tx(choices.length)}{tx("条记录 · 不同协议分开解释")}</span><div className="flex items-center gap-2"><Button size="sm" variant="outline" disabled={displayPage === 0} onClick={() => setPage(displayPage - 1)}>{tx("上一页")}</Button><span>{tx(displayPage + 1)} / {tx(pages)}</span><Button size="sm" variant="outline" disabled={displayPage + 1 >= pages} onClick={() => setPage(displayPage + 1)}>{tx("下一页")}</Button></div></div>
        </section>
        {tx(explicitSelection && selected && !choices.some((row) => row.id === selected.id) && <p className="lab-panel mt-4 text-sm">{tx("链接指定的方案不在当前筛选列表中；下方仍显示该方案的原始记录。")}</p>)}
        {explicitSelection && !selected ? <p role="alert" className="lab-panel mt-5">{tx("指定记录无法读取，请刷新记录或重新选择。")}</p> : selected && <section id="record-details" className="mt-6 scroll-mt-32">
          <SavedLayoutDetails key={selected.id + '-' + retry} summary={selected} ar={ar} returnHref={here} />
        </section>}
      </>)}
    </div>
  </main>;
}
