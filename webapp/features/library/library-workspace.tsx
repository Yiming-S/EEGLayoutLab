'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useEffect, useState, type InputHTMLAttributes } from 'react';
import { ChevronDown, RefreshCcw, Search, SlidersHorizontal } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { SiteHeader } from '@/components/site-header';
import { CatalogExperimentDetails } from '@/components/catalog-experiment-details';
import { visibilityLabel } from '@/components/record-visibility-control';
import { Button, buttonVariants } from '@/components/ui/button';
import { OutcomeBadge, RetentionBar, type Outcome } from '@/components/retention-bar';
import { ThresholdSlider } from '@/components/threshold-slider';
import { assessment } from '@/lib/lab-workflow';
import { resultQualification } from '@/lib/results-library';
import { cn } from '@/lib/utils';
import { metricPercent } from '@/lib/ui-language';
import { stackedCell } from '@/lib/responsive-table';
import { layoutHref } from '@/lib/layout-page';
import { locationName, RECORD_KIND_LABELS, type CatalogEntry, type CatalogRow, type CatalogView } from '@/lib/records-catalog';
import { useLibraryController } from './use-library-controller';
import { ParetoPanel } from './pareto-panel';

/** Filters once typing pauses, so each keystroke does not re-rank the whole catalog. */
function SearchInput({ value, onSearch, className, ...props }: { value: string; onSearch: (value: string) => void } & Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'>) {
  const [text, setText] = useState(value), [applied, setApplied] = useState(value);
  if (value !== applied) { setApplied(value); setText(value); }
  useEffect(() => {
    if (text === value) return;
    const timer = setTimeout(() => onSearch(text), 250);
    return () => clearTimeout(timer);
  }, [text, value, onSearch]);
  return (
    <span className="relative mt-2 block">
      <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
      <input {...props} className={cn(className, 'mt-0 pl-9')} value={text} onChange={event => setText(event.target.value)} />
    </span>
  );
}

const rowVisibility = (row: CatalogEntry) => visibilityLabel('summary' in row ? row.summary.visibility : row.kind === 'editor' ? row.editor.visibility : undefined);
const rowOutcome = (row: CatalogEntry, ar: number): Outcome | null => 'summary' in row
  ? (row.summary.status !== 'completed' ? 'undefined' : assessment(row.summary.metrics, ar).state as Outcome) : null;
const cell = stackedCell;

export default function LibraryWorkspace() {
  const { tx, date } = useLanguage();
  const { isExpanded, toggleGroup, groupPrimary, groupTitle, conditionTitle, latestPerCondition, showSuperseded, setShowSuperseded, foldedCount, ar, setAR, labHref, here, layout, selected, loading, setLoading, retry, setRetry, error, view, changeView, electrodeCounts, locations, regionCounts, data, catalogWarnings, catalog, listed, id, title, protocol, score, choose, choices, displayPage, setView, pages, explicitSelection, related } = useLibraryController();
  const refresh = () => { setLoading(true); setRetry(value => value + 1); };
  const [filtersOpen, setFiltersOpen] = useState(false);
  const extraFilters = [view.filter !== 'all', view.electrodes > 0, !!view.location, view.region > 0, view.sort !== 'newest'].filter(Boolean).length;
  const otherMetrics = (row: CatalogEntry) => {
    const metrics = 'summary' in row ? row.summary.metrics : row.kind === 'editor' ? row.editor.metrics : null;
    return metrics && <span className="mt-1 block font-mono text-xs tabular-nums text-muted-foreground">{tx('幅度')} {metricPercent(metrics.sensitivity_tail)} · {tx('定位')} {metricPercent(metrics.localization_relative)}</span>;
  };
  const scoreCell = (row: CatalogEntry) => 'summary' in row && row.summary.status === 'no_layout' ? tx('未评估')
    : row.kind === 'source' && !row.receipt.catalog?.conditions?.length ? tx('未保存指标摘要')
    : <span><RetentionBar value={score(row)} threshold={'summary' in row ? ar / 100 : undefined} />{otherMetrics(row)}</span>;
  const open = (row: CatalogEntry, nested = false) => 'summary' in row
    ? <a className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'max-md:w-full')} href={layoutHref({ id: row.id }, ar)}>{tx(nested ? '查看' : '查看布局')}</a>
    : <Button variant="outline" size="sm" className="max-md:w-full" onClick={() => choose(row.id)}>{tx('查看结果')}</Button>;
  const renderEntry = (row: CatalogEntry, nested = false) => {
    const outcome = rowOutcome(row, ar);
    return <tr className={cn('border-b border-border/65 transition-colors last:border-0 max-md:block max-md:py-3 md:hover:bg-primary/[0.03]', row.id === id && 'bg-primary/[0.055]', nested && 'bg-muted/35')} key={row.id}>
      <th className={cn('font-medium leading-6 max-md:block md:max-w-[360px] md:px-4 md:py-3.5', nested && 'md:pl-7')}>
        {nested ? <span className="flex items-center gap-2"><span aria-hidden className="h-4 w-0.5 rounded bg-primary/50" />{conditionTitle(row)}</span> : title(row)}
        {!nested && <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs font-normal text-muted-foreground"><span className="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] font-medium text-secondary-foreground">{tx(RECORD_KIND_LABELS[row.kind])}</span><span>{protocol(row)}</span></span>}
        <span className="mt-1 block text-xs font-normal text-muted-foreground">{row.finished_at ? date(row.finished_at) : tx('保存时间未记录')}</span>
        {rowVisibility(row) && <span className="mt-1 inline-block rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">{tx(rowVisibility(row)!)}</span>}
      </th>
      <td data-label={tx('电极 / 区域')} className={cn(cell, 'font-mono tabular-nums md:px-3')}>{row.electrode_count ?? '—'} / {row.region_count ?? '—'}</td>
      <td data-label={tx('三项保留率')} className={cn(cell, 'md:px-3')}><span>{scoreCell(row)}{row.kind === 'source' && <span className="block text-xs text-muted-foreground">{tx('心眼混合干扰条件')}</span>}</span></td>
      <td data-label={tx('计算状态')} className={cn(cell, 'md:px-3')}><span>{tx('summary' in row && row.summary.status === 'no_layout' ? '本轮未找到完整布局' : '已完成评价')}{'summary' in row && row.summary.dataset_id === 'cache' && !row.summary.compatible && <span className="block text-xs text-warning">{tx('旧版本记录 · 仅供查阅')}</span>}</span></td>
      <td data-label={tx('性能判断')} className={cn(cell, 'md:px-3')}>{'summary' in row && outcome ? <OutcomeBadge outcome={outcome}>{tx(resultQualification(row.summary, ar))}</OutcomeBadge> : <span className="text-xs text-muted-foreground">{tx(row.kind === 'editor' ? '按编辑协议解释' : '按干扰条件分别解释')}</span>}</td>
      <td className="max-md:mt-2 max-md:block md:px-4 md:py-3.5">{open(row, nested)}</td>
    </tr>;
  };
  const renderGroup = (row: Extract<CatalogRow, { kind: 'group' }>) => {
    const expanded = isExpanded(row), first = groupPrimary(row.entries), distinct = latestPerCondition(row.entries);
    const key = 'summary' in first ? first.summary.layout_key : undefined;
    const values = distinct.flatMap(entry => { const value = score(entry); return value != null && Number.isFinite(value) ? [value] : []; });
    const passed = distinct.filter(entry => rowOutcome(entry, ar) === 'pass').length;
    const kinds = [...new Set(distinct.flatMap(entry => 'summary' in entry ? Object.keys(entry.summary.evaluation_condition ?? {}) : []))]
      .map(key => tx(({ head_id: '头模', noise_model: '噪声模型', conductivity_scenario: '电导率', data_prior: '数据先验' } as Record<string, string>)[key] ?? key));
    return [<tr key={row.key} className={cn('border-b border-border/65 transition-colors max-md:block max-md:py-3 md:hover:bg-primary/[0.03]', expanded && 'border-b-0 bg-muted/20', row.entries.some(entry => entry.id === id) && 'bg-primary/[0.055]')}>
      <th className="font-medium leading-6 max-md:block md:max-w-[360px] md:px-4 md:py-3.5">{groupTitle(first)}
        <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs font-normal text-muted-foreground"><span className="rounded-md bg-secondary px-1.5 py-0.5 text-[11px] font-medium text-secondary-foreground">{tx(RECORD_KIND_LABELS[first.kind])}</span><span>{tx(`共${distinct.length}种条件`)}{kinds.length > 0 && <> · {kinds.join(' / ')}</>}</span></span>
        <span className="mt-1 block text-xs font-normal text-muted-foreground">{tx('最近一次')} {first.finished_at ? date(first.finished_at) : tx('保存时间未记录')}</span>
      </th>
      <td data-label={tx('电极 / 区域')} className={cn(cell, 'font-mono tabular-nums md:px-3')}>{first.electrode_count ?? '—'} / {first.region_count ?? '—'}</td>
      <td data-label={tx('三项保留率')} className={cn(cell, 'md:px-3')}>{values.length ? <span><RetentionBar value={score(first)} threshold={ar / 100} />{otherMetrics(first)}<span className="mt-1 block font-mono text-xs text-muted-foreground tabular-nums">{tx(`各条件场重建 ${metricPercent(Math.min(...values))}–${metricPercent(Math.max(...values))}`)}</span></span> : tx('未保存指标摘要')}</td>
      <td data-label={tx('计算状态')} className={cn(cell, 'md:px-3')}>{tx('已完成评价')}</td>
      <td data-label={tx('性能判断')} className={cn(cell, 'md:px-3')}><OutcomeBadge outcome={passed === distinct.length ? 'pass' : 'fail'}>{tx(`${passed}/${distinct.length}种条件达到要求`)}</OutcomeBadge></td>
      <td className="max-md:mt-2 max-md:flex max-md:gap-2 md:px-4 md:py-3.5">
        <a className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'max-md:flex-1 md:mb-1.5 md:flex')} href={key ? layoutHref({ key }, ar) : layoutHref({ id: first.id }, ar)}>{tx('查看布局')}</a>
        <Button variant="ghost" size="sm" className="max-md:flex-1 md:flex" aria-expanded={expanded} onClick={() => toggleGroup(row.key)}><ChevronDown className={cn('transition-transform', expanded && 'rotate-180')} />{tx(expanded ? '收起' : `展开全部${row.entries.length}条`)}</Button>
      </td>
    </tr>, ...(expanded ? row.entries.map(entry => renderEntry(entry, true)) : [])];
  };
  return <main className="lab-page">
    <SiteHeader current="library" arPercent={ar} labHref={labHref} returnHref={here} selection={{ id: layout?.id ?? null,
      phase: selected?.kind === 'editor' ? 'edited' : 'saved', channels: selected?.electrode_count ?? undefined, regions: selected?.region_count ?? undefined }} />
    <div className="lab-container">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-border pt-6 pb-4">
        <div className="max-w-3xl">
          <h1 className="text-[1.45rem] font-semibold tracking-[-0.03em]">{tx('布局列表')}</h1>
          <p className="mt-1 text-[0.8125rem] leading-6 text-muted-foreground">{tx('每个布局一行：同一组坐标在不同条件下的评价合并显示，“查看布局”打开它的详情页。编辑副本和信号实验保留自己的协议与原布局关联。')}</p>
        </div>
        <Button variant="outline" size="sm" disabled={loading} onClick={() => { setLoading(true); setRetry(value => value + 1); }}><RefreshCcw className="size-3.5" />{tx('刷新记录')}</Button>
      </header>
      {error && <p role="alert" className="lab-panel mb-4 text-danger"><RuntimeMessage message={error} /> <a href={'/results?ar=' + ar} className="underline">{tx('仍可查看已导出的历史半径结果')}</a></p>}
      <div className="lab-panel mb-4 space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-[1fr_1.3fr_1.3fr]">
          <label className="lab-label">{tx('记录类型')}<select className="lab-select" value={view.kind} onChange={event => changeView({ kind: event.target.value as CatalogView['kind'], filter: 'all' })}><option value="all">{tx('全部记录类型')}</option>{Object.entries(RECORD_KIND_LABELS).map(([kind, label]) => <option value={kind} key={kind}>{tx(label)}</option>)}</select></label>
          <label className="lab-label">{tx('查找方案')}<SearchInput className="lab-select" placeholder={tx('例如：耳后、前额、2个区域')} value={view.search} onSearch={search => changeView({ search })} /></label>
          <ThresholdSlider value={ar} onChange={setAR} ariaLabel="记录接受阈值AR" term="ar" hint="只判断原记录，不重新计算。" />
        </div>
        <button type="button" className="flex w-full items-center justify-between rounded-xl border border-border/80 bg-muted/40 px-3.5 py-2 text-sm font-medium sm:hidden" aria-expanded={filtersOpen} aria-controls="library-more-filters" onClick={() => setFiltersOpen(open => !open)}><span className="flex items-center gap-2"><SlidersHorizontal className="size-4" />{tx('更多筛选与排序')}{extraFilters > 0 && <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground">{extraFilters}</span>}</span><ChevronDown className={cn('size-4 transition-transform', filtersOpen && 'rotate-180')} /></button>
        <div id="library-more-filters" className={cn(filtersOpen ? 'grid gap-3.5' : 'hidden', 'rounded-xl border border-border/65 bg-muted/30 p-3.5 sm:grid sm:grid-cols-2 lg:grid-cols-5')}>
          <label className="lab-label text-xs">{tx('布局实验协议')}<select className="lab-select" value={view.filter} onChange={event => changeView({ filter: event.target.value, kind: 'all' })}><option value="all">{tx('全部协议')}</option><option value="design_evaluation">{tx('已评价坐标布局')}</option><option value="current">{tx('面积实验与按需计算记录')}</option><option value="strict_area">{tx('总面积上限约束实验')}</option><option value="cache">{tx('每区半径约束计算')}</option><option value="historical_area">{tx('历史面积实验 · 原坐标范围')}</option><option value="offline_radius">{tx('历史实验 · 允许区域相交')}</option></select></label>
          <label className="lab-label text-xs">{tx('实际电极数')}<select className="lab-select" value={view.electrodes} onChange={event => changeView({ electrodes: Number(event.target.value) })}><option value={0}>{tx('全部电极数量')}</option>{electrodeCounts.map(count => <option value={count} key={count}>{count}</option>)}</select></label>
          <label className="lab-label text-xs">{tx('电极所在部位')}<select className="lab-select" value={view.location} onChange={event => changeView({ location: event.target.value })}><option value="">{tx('全部部位')}</option>{locations.map(location => <option value={location} key={location}>{tx(locationName(location))}</option>)}</select></label>
          <label className="lab-label text-xs">{tx('电极分布区域数')}<select className="lab-select" value={view.region} onChange={event => changeView({ region: Number(event.target.value) })}><option value={0}>{tx('全部区域数量')}</option>{regionCounts.map(count => <option value={count} key={count}>{tx(`${count}个区域`)}</option>)}</select></label>
          <label className="lab-label text-xs">{tx('排序方式')}<select className="lab-select" value={view.sort} onChange={event => changeView({ sort: event.target.value })}><option value="newest">{tx('最近保存优先')}</option><option value="oldest">{tx('最早保存优先')}</option><option value="name">{tx('按方案名称')}</option><option value="electrodes">{tx('电极数从少到多')}</option></select></label>
        </div>
      </div>
      <div className="mb-4 space-y-1.5 px-1 text-xs leading-5 text-muted-foreground">
        <p>{tx('信号实验只列出当前浏览器完成的任务，较早的任务可能已不在列表中。筛选记录不会读取完整波形或启动计算。')}</p>
        {data?.library_scope?.scope === 'owner' && <p>{tx(data.library_scope.review
          ? '本浏览器提交的计算默认只有本浏览器能在列表中看到。公开到共享库的记录经管理员审核后对所有访客列出；官方实验记录始终列出。清除浏览器数据后列表将找不到自己的记录，需要长期保留请加入研究项目。'
          : '本浏览器提交的计算默认只有本浏览器能在列表中看到。公开到共享库的记录对所有访客列出；官方实验记录始终列出。清除浏览器数据后列表将找不到自己的记录，需要长期保留请加入研究项目。')}</p>}
      </div>
      {[...(data?.warnings ?? []), ...catalogWarnings].map(warning => <p className="mb-3 text-sm text-warning" key={warning}><RuntimeMessage message={warning} /></p>)}
      {loading && !catalog.length ? <p className="lab-panel">{tx('读取方案目录…')}</p> : <>
        <section className="lab-panel" aria-label={tx('已保存方案列表')}>
          <div className="rounded-xl border border-border/75 bg-card md:overflow-x-auto">
            <table className="w-full text-left text-sm md:min-w-[920px]">
              <thead className="max-md:sr-only">
                <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                  <th className="px-4 py-3">{tx('记录与协议')}</th>
                  <th className="px-3 py-3">{tx('电极 / 区域')}</th>
                  <th className="px-3 py-3">{tx('三项保留率')}</th>
                  <th className="px-3 py-3">{tx('计算状态')}</th>
                  <th className="px-3 py-3">{tx('性能判断')}</th>
                  <th className="px-4 py-3"><span className="sr-only">{tx('操作')}</span></th>
                </tr>
              </thead>
              <tbody className="max-md:block max-md:px-3">
                {listed.map(row => row.kind === 'entry' ? renderEntry(row.entry) : renderGroup(row))}
              </tbody>
            </table>
            {!choices.length && <p className="px-4 py-6 text-sm text-muted-foreground">{tx('当前筛选下没有记录。')}</p>}
          </div>
          {(foldedCount > 0 || showSuperseded) && <p className="mt-3 text-xs text-muted-foreground">{showSuperseded ? tx('已显示较早代码版本的同配置记录。') : tx(`另有${foldedCount}条同配置记录来自较早的代码版本，已折叠。`)} <button type="button" className="font-medium text-primary underline underline-offset-2" onClick={() => setShowSuperseded(value => !value)}>{tx(showSuperseded ? '折叠旧版本' : '显示旧版本')}</button></p>}
          {!selected && choices.length > 0 && <p className="mt-2.5 text-xs text-muted-foreground">{tx('点击“查看布局”打开布局详情；编辑副本与信号实验的“查看结果”在本页下方展开。')}</p>}
          <div className="mt-4 flex flex-wrap items-center justify-between gap-4 border-t border-border/70 pt-3.5 text-xs text-muted-foreground">
            <span className="font-medium">{choices.length}{tx('条记录 · 不同协议分开解释')}</span>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" disabled={displayPage === 0} onClick={() => setView(value => ({ ...value, page: displayPage - 1 }))}>{tx('上一页')}</Button>
              <span className="px-1 font-mono tabular-nums">{displayPage + 1} / {pages}</span>
              <Button size="sm" variant="outline" disabled={displayPage + 1 >= pages} onClick={() => setView(value => ({ ...value, page: displayPage + 1 }))}>{tx('下一页')}</Button>
            </div>
          </div>
        </section>
        <ParetoPanel entries={choices} title={title} onChoose={choose} />
        {explicitSelection && selected && !choices.some(row => row.id === selected.id) && <p className="lab-panel mt-4 text-sm">{tx('链接指定的方案不在当前筛选列表中；下方仍显示该方案的原始记录。')}</p>}
        {explicitSelection && !selected && !loading ? <p role="alert" className="lab-panel mt-5">{tx('指定记录无法读取，请刷新记录或重新选择。')}</p> : selected && <section id="record-details" className="mt-6 scroll-mt-32 space-y-4">
          {'summary' in selected ? <p className="lab-panel">{tx('正在打开布局详情…')}</p> : <CatalogExperimentDetails key={selected.id + '-' + retry} entry={selected} parents={data?.records ?? []} ar={ar} returnHref={here} onVisibilityChange={refresh} />}
          {related.length > 0 && <div className="lab-panel"><h3 className="font-semibold">{tx('同一原布局的关联记录')}</h3><p className="mt-2 text-sm text-muted-foreground">{tx('编辑副本与信号实验分别关联原布局；信号实验使用其记录指定的完整布局。')}</p><ul className="mt-3 max-h-80 space-y-2 overflow-y-auto text-sm">{related.map(entry => <li key={entry.id}><button className="text-left text-primary underline underline-offset-4" onClick={() => choose(entry.id)}>{tx(RECORD_KIND_LABELS[entry.kind])} · {title(entry)} · {entry.finished_at ? date(entry.finished_at, true) : ''}</button></li>)}</ul></div>}
        </section>}
      </>}
    </div>
  </main>;
}
