'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState, type InputHTMLAttributes } from 'react';
import { ChevronDown, RefreshCcw, SlidersHorizontal } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { SiteHeader } from '@/components/site-header';
import { SavedLayoutDetails } from '@/components/saved-layout-details';
import { CatalogExperimentDetails } from '@/components/catalog-experiment-details';
import { visibilityLabel } from '@/components/record-visibility-control';
import { Button } from '@/components/ui/button';
import { OutcomeBadge, RetentionBar, type Outcome } from '@/components/retention-bar';
import { ThresholdSlider } from '@/components/threshold-slider';
import { assessment } from '@/lib/lab-workflow';
import { resultQualification } from '@/lib/results-library';
import { cn } from '@/lib/utils';
import { metricPercent } from '@/lib/ui-language';
import { stackedCell } from '@/lib/responsive-table';
import { locationName, RECORD_KIND_LABELS, type CatalogEntry, type CatalogRow, type CatalogView } from '@/lib/records-catalog';
import { useLibraryController } from './use-library-controller';

/** Filters once typing pauses, so each keystroke does not re-rank the whole catalog. */
function SearchInput({ value, onSearch, ...props }: { value: string; onSearch: (value: string) => void } & Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'>) {
  const [text, setText] = useState(value), [applied, setApplied] = useState(value);
  if (value !== applied) { setApplied(value); setText(value); }
  useEffect(() => {
    if (text === value) return;
    const timer = setTimeout(() => onSearch(text), 250);
    return () => clearTimeout(timer);
  }, [text, value, onSearch]);
  return <input {...props} value={text} onChange={event => setText(event.target.value)} />;
}

const rowVisibility = (row: CatalogEntry) => visibilityLabel('summary' in row ? row.summary.visibility : row.kind === 'editor' ? row.editor.visibility : undefined);
const rowOutcome = (row: CatalogEntry, ar: number): Outcome | null => 'summary' in row
  ? (row.summary.status !== 'completed' ? 'undefined' : assessment(row.summary.metrics, ar).state as Outcome) : null;
const median = (values: number[]) => { const sorted = [...values].sort((a, b) => a - b), mid = sorted.length >> 1; return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2; };
const cell = stackedCell;

export default function LibraryWorkspace() {
  const { tx, date } = useLanguage();
  const { isExpanded, toggleGroup, groupTitle, conditionTitle, latestPerCondition, showSuperseded, setShowSuperseded, foldedCount, ar, setAR, labHref, here, layout, selected, loading, setLoading, retry, setRetry, error, view, changeView, electrodeCounts, locations, regionCounts, data, catalogWarnings, catalog, listed, id, title, protocol, score, choose, choices, displayPage, setView, pages, explicitSelection, related } = useLibraryController();
  const refresh = () => { setLoading(true); setRetry(value => value + 1); };
  const [filtersOpen, setFiltersOpen] = useState(false);
  const extraFilters = [view.filter !== 'all', view.electrodes > 0, !!view.location, view.region > 0, view.sort !== 'newest'].filter(Boolean).length;
  const scoreCell = (row: CatalogEntry) => 'summary' in row && row.summary.status === 'no_layout' ? tx('未评估')
    : row.kind === 'source' && !row.receipt.catalog?.conditions?.length ? tx('未保存指标摘要')
    : <RetentionBar value={score(row)} threshold={'summary' in row ? ar / 100 : undefined} />;
  const renderEntry = (row: CatalogEntry, nested = false) => {
    const outcome = rowOutcome(row, ar);
    return <tr className={cn('border-b last:border-0 max-md:block max-md:py-3', row.id === id && 'bg-primary/5', nested && 'bg-secondary/40')} key={row.id}>
      <th className={cn('font-medium leading-6 max-md:block md:max-w-[350px] md:py-3 md:pr-4', nested && 'md:pl-6')}>
        {nested ? <span className="flex items-center gap-2"><span aria-hidden className="h-4 w-0.5 rounded bg-primary/40" />{conditionTitle(row)}</span> : title(row)}
        {!nested && <span className="mt-1 block text-xs font-normal text-muted-foreground">{tx(RECORD_KIND_LABELS[row.kind])} · {protocol(row)}</span>}
        <span className="mt-1 block text-xs font-normal text-muted-foreground">{row.finished_at ? date(row.finished_at) : tx('保存时间未记录')}</span>
        {rowVisibility(row) && <span className="mt-1 block text-xs font-normal text-primary">{tx(rowVisibility(row)!)}</span>}
      </th>
      <td data-label={tx('电极 / 区域')} className={cn(cell, 'tabular-nums')}>{row.electrode_count ?? '—'} / {row.region_count ?? '—'}</td>
      <td data-label={tx('信号重建保留率')} className={cell}><span>{scoreCell(row)}{row.kind === 'source' && <span className="block text-xs text-muted-foreground">{tx('心眼混合干扰条件')}</span>}</span></td>
      <td data-label={tx('计算状态')} className={cell}><span>{tx('summary' in row && row.summary.status === 'no_layout' ? '本轮未找到完整布局' : '已完成评价')}{'summary' in row && row.summary.dataset_id === 'cache' && !row.summary.compatible && <span className="block text-xs text-warning">{tx('旧版本记录 · 仅供查阅')}</span>}</span></td>
      <td data-label={tx('性能判断')} className={cell}>{'summary' in row && outcome ? <OutcomeBadge outcome={outcome}>{tx(resultQualification(row.summary, ar))}</OutcomeBadge> : <span className="text-muted-foreground">{tx(row.kind === 'editor' ? '按编辑协议解释' : '按干扰条件分别解释')}</span>}</td>
      <td className="max-md:mt-2 max-md:block md:py-3"><Button variant="outline" size="sm" className="max-md:w-full" onClick={() => choose(row.id)}>{tx('查看结果')}</Button></td>
    </tr>;
  };
  const renderGroup = (row: Extract<CatalogRow, { kind: 'group' }>) => {
    const open = isExpanded(row), first = row.entries[0], distinct = latestPerCondition(row.entries);
    const values = distinct.flatMap(entry => { const value = score(entry); return value != null && Number.isFinite(value) ? [value] : []; });
    const passed = distinct.filter(entry => rowOutcome(entry, ar) === 'pass').length;
    const kinds = [...new Set(distinct.flatMap(entry => 'summary' in entry ? Object.keys(entry.summary.evaluation_condition ?? {}) : []))]
      .map(key => tx(({ head_id: '头模', noise_model: '噪声模型', conductivity_scenario: '电导率' } as Record<string, string>)[key] ?? key));
    return [<tr key={row.key} className={cn('border-b max-md:block max-md:py-3', open && 'border-b-0')}>
      <th className="font-medium leading-6 max-md:block md:max-w-[350px] md:py-3 md:pr-4">{groupTitle(first)}
        <span className="mt-1 block text-xs font-normal text-muted-foreground">{tx(RECORD_KIND_LABELS[first.kind])} · {tx('多条件评价')} · {tx(`共${distinct.length}种条件`)} · {kinds.join(' / ')}</span>
        <span className="mt-1 block text-xs font-normal text-muted-foreground">{tx('最近一次')} {first.finished_at ? date(first.finished_at) : tx('保存时间未记录')}</span>
      </th>
      <td data-label={tx('电极 / 区域')} className={cn(cell, 'tabular-nums')}>{first.electrode_count ?? '—'} / {first.region_count ?? '—'}</td>
      <td data-label={tx('信号重建保留率')} className={cell}>{values.length ? <span><RetentionBar value={median(values)} threshold={ar / 100} /><span className="mt-1 block text-xs text-muted-foreground">{tx(`中位数 · 范围 ${metricPercent(Math.min(...values))}–${metricPercent(Math.max(...values))}`)}</span></span> : tx('未保存指标摘要')}</td>
      <td data-label={tx('计算状态')} className={cell}>{tx('已完成评价')}</td>
      <td data-label={tx('性能判断')} className={cell}><OutcomeBadge outcome={passed === distinct.length ? 'pass' : 'fail'}>{tx(`${passed}/${distinct.length}种条件达到要求`)}</OutcomeBadge></td>
      <td className="max-md:mt-2 max-md:block md:py-3"><Button variant="outline" size="sm" className="max-md:w-full" aria-expanded={open} onClick={() => toggleGroup(row.key)}><ChevronDown className={cn('transition-transform', open && 'rotate-180')} />{tx(open ? '收起' : `展开全部${row.entries.length}条`)}</Button></td>
    </tr>, ...(open ? row.entries.map(entry => renderEntry(entry, true)) : [])];
  };
  return <main className="lab-page">
    <SiteHeader current="library" arPercent={ar} labHref={labHref} returnHref={here} selection={{ id: layout?.id ?? null,
      phase: selected?.kind === 'editor' ? 'edited' : 'saved', channels: selected?.electrode_count ?? undefined, regions: selected?.region_count ?? undefined }} />
    <div className="lab-container">
      <header className="flex flex-wrap items-end justify-between gap-4 py-6"><div><h1 className="text-2xl font-semibold">{tx('布局与实验记录')}</h1><p className="mt-2 text-base text-muted-foreground">{tx('统一查找布局、坐标评价、编辑副本和信号实验。每条记录保留自己的评价协议与原布局关联。')}</p></div><Button variant="outline" disabled={loading} onClick={() => { setLoading(true); setRetry(value => value + 1); }}><RefreshCcw className="size-4" />{tx('刷新记录')}</Button></header>
      {error && <p role="alert" className="lab-panel mb-4 text-danger"><RuntimeMessage message={error} /> <a href={'/results?ar=' + ar} className="underline">{tx('仍可查看已导出的历史半径结果')}</a></p>}
      <div className="lab-panel mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="lab-label">{tx('记录类型')}<select className="lab-select" value={view.kind} onChange={event => changeView({ kind: event.target.value as CatalogView['kind'], filter: 'all' })}><option value="all">{tx('全部记录类型')}</option>{Object.entries(RECORD_KIND_LABELS).map(([kind, label]) => <option value={kind} key={kind}>{tx(label)}</option>)}</select></label>
        <label className="lab-label">{tx('查找方案')}<SearchInput className="lab-select" placeholder={tx('例如：耳后、前额、2个区域')} value={view.search} onSearch={search => changeView({ search })} /></label>
        <ThresholdSlider value={ar} onChange={setAR} ariaLabel="记录接受阈值AR" hint="只判断原记录，不重新计算。" />
        <button type="button" className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm font-medium sm:hidden" aria-expanded={filtersOpen} aria-controls="library-more-filters" onClick={() => setFiltersOpen(open => !open)}><span className="flex items-center gap-2"><SlidersHorizontal className="size-4" />{tx('更多筛选与排序')}{extraFilters > 0 && <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground">{extraFilters}</span>}</span><ChevronDown className={cn('size-4 transition-transform', filtersOpen && 'rotate-180')} /></button>
        <div id="library-more-filters" className={cn(filtersOpen ? 'grid gap-4' : 'hidden', 'sm:contents')}>
          <label className="lab-label">{tx('布局实验协议')}<select className="lab-select" value={view.filter} onChange={event => changeView({ filter: event.target.value, kind: 'all' })}><option value="all">{tx('全部协议')}</option><option value="design_evaluation">{tx('已评价坐标布局')}</option><option value="current">{tx('面积实验与按需计算记录')}</option><option value="strict_area">{tx('总面积上限约束实验')}</option><option value="cache">{tx('每区半径约束计算')}</option><option value="historical_area">{tx('历史面积实验 · 原坐标范围')}</option><option value="offline_radius">{tx('历史实验 · 允许区域相交')}</option></select></label>
          <label className="lab-label">{tx('实际电极数')}<select className="lab-select" value={view.electrodes} onChange={event => changeView({ electrodes: Number(event.target.value) })}><option value={0}>{tx('全部电极数量')}</option>{electrodeCounts.map(count => <option value={count} key={count}>{count}</option>)}</select></label>
          <label className="lab-label">{tx('电极所在部位')}<select className="lab-select" value={view.location} onChange={event => changeView({ location: event.target.value })}><option value="">{tx('全部部位')}</option>{locations.map(location => <option value={location} key={location}>{tx(locationName(location))}</option>)}</select></label>
          <label className="lab-label">{tx('电极分布区域数')}<select className="lab-select" value={view.region} onChange={event => changeView({ region: Number(event.target.value) })}><option value={0}>{tx('全部区域数量')}</option>{regionCounts.map(count => <option value={count} key={count}>{tx(`${count}个区域`)}</option>)}</select></label>
          <label className="lab-label">{tx('排序方式')}<select className="lab-select" value={view.sort} onChange={event => changeView({ sort: event.target.value })}><option value="newest">{tx('最近保存优先')}</option><option value="oldest">{tx('最早保存优先')}</option><option value="name">{tx('按方案名称')}</option><option value="electrodes">{tx('电极数从少到多')}</option></select></label>
        </div>
      </div>
      <p className="mb-4 text-sm leading-6 text-muted-foreground">{tx('信号实验仅收录当前浏览器的已完成任务；服务器保留最近1000个计算回执，打开已有结果生成的回执另保留300个。筛选记录不会读取完整波形或启动计算。')}</p>
      {data?.library_scope?.scope === 'owner' && <p className="mb-4 text-sm leading-6 text-muted-foreground">{tx(data.library_scope.review
        ? '本浏览器提交的计算默认只有本浏览器能在列表中看到。公开到共享库的记录经管理员审核后对所有访客列出；官方实验记录始终列出。清除浏览器数据后列表将找不到自己的记录，需要长期保留请加入研究项目。'
        : '本浏览器提交的计算默认只有本浏览器能在列表中看到。公开到共享库的记录对所有访客列出；官方实验记录始终列出。清除浏览器数据后列表将找不到自己的记录，需要长期保留请加入研究项目。')}</p>}
      {[...(data?.warnings ?? []), ...catalogWarnings].map(warning => <p className="mb-3 text-sm text-warning" key={warning}><RuntimeMessage message={warning} /></p>)}
      {loading && !catalog.length ? <p className="lab-panel">{tx('读取方案目录…')}</p> : <>
        <section className="lab-panel md:overflow-x-auto" aria-label={tx('已保存方案列表')}>
          <table className="w-full text-left text-sm md:min-w-[900px]"><thead className="max-md:sr-only"><tr className="border-b text-muted-foreground"><th className="pb-3">{tx('记录与协议')}</th><th>{tx('电极 / 区域')}</th><th>{tx('信号重建保留率')}</th><th>{tx('计算状态')}</th><th>{tx('性能判断')}</th><th><span className="sr-only">{tx('操作')}</span></th></tr></thead><tbody className="max-md:block">
            {listed.map(row => row.kind === 'entry' ? renderEntry(row.entry) : renderGroup(row))}
          </tbody></table>
          {!choices.length && <p className="py-5 text-sm text-muted-foreground">{tx('当前筛选下没有记录。')}</p>}
          {(foldedCount > 0 || showSuperseded) && <p className="mt-3 text-sm text-muted-foreground">{showSuperseded ? tx('已显示较早代码版本的同配置记录。') : tx(`另有${foldedCount}条同配置记录来自较早的代码版本，已折叠。`)} <button type="button" className="text-primary underline underline-offset-2" onClick={() => setShowSuperseded(value => !value)}>{tx(showSuperseded ? '折叠旧版本' : '显示旧版本')}</button></p>}
          {!selected && choices.length > 0 && <p className="mt-3 text-sm text-muted-foreground">{tx('点击“查看结果”打开记录详情。')}</p>}
          <div className="mt-3 flex items-center justify-between gap-4 text-sm text-muted-foreground"><span>{choices.length}{tx('条记录 · 不同协议分开解释')}</span><div className="flex items-center gap-2"><Button size="sm" variant="outline" disabled={displayPage === 0} onClick={() => setView(value => ({ ...value, page: displayPage - 1 }))}>{tx('上一页')}</Button><span>{displayPage + 1} / {pages}</span><Button size="sm" variant="outline" disabled={displayPage + 1 >= pages} onClick={() => setView(value => ({ ...value, page: displayPage + 1 }))}>{tx('下一页')}</Button></div></div>
        </section>
        {explicitSelection && selected && !choices.some(row => row.id === selected.id) && <p className="lab-panel mt-4 text-sm">{tx('链接指定的方案不在当前筛选列表中；下方仍显示该方案的原始记录。')}</p>}
        {explicitSelection && !selected && !loading ? <p role="alert" className="lab-panel mt-5">{tx('指定记录无法读取，请刷新记录或重新选择。')}</p> : selected && <section id="record-details" className="mt-6 scroll-mt-32 space-y-4">
          {'summary' in selected ? <SavedLayoutDetails key={selected.id + '-' + retry} summary={selected.summary} ar={ar} returnHref={here} onVisibilityChange={refresh} /> : <CatalogExperimentDetails key={selected.id + '-' + retry} entry={selected} parents={data?.records ?? []} ar={ar} returnHref={here} onVisibilityChange={refresh} />}
          {related.length > 0 && <div className="lab-panel"><h3 className="font-semibold">{tx('同一原布局的关联记录')}</h3><p className="mt-2 text-sm text-muted-foreground">{tx('编辑副本与信号实验分别关联原布局；信号实验使用其记录指定的完整布局。')}</p><ul className="mt-3 max-h-80 space-y-2 overflow-y-auto text-sm">{related.map(entry => <li key={entry.id}><button className="text-left text-primary underline underline-offset-4" onClick={() => choose(entry.id)}>{tx(RECORD_KIND_LABELS[entry.kind])} · {title(entry)} · {entry.finished_at ? date(entry.finished_at, true) : ''}</button></li>)}</ul></div>}
        </section>}
      </>}
    </div>
  </main>;
}
