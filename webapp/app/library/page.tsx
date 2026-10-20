'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCcw } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import { SiteHeader } from '@/components/site-header';
import { SavedLayoutDetails } from '@/components/saved-layout-details';
import { CatalogExperimentDetails } from '@/components/catalog-experiment-details';
import { Button } from '@/components/ui/button';
import { percent } from '@/components/performance-summary';
import { localizedEditorParentTitle, localizedRecordTitle, recordSearchText } from '@/lib/i18n/records';
import { preserveResultsContext, resultQualification } from '@/lib/results-library';
import { comparisonLink, parseAR, radiusDesignLink } from '@/lib/lab-workflow';
import type { LocalLibrary } from '@/lib/local-library';
import type { EditorRecord } from '@/lib/electrode-editor';
import { protocolName } from '@/lib/ui-language';
import { SOURCE_REGIONS } from '@/lib/source-regions';
import {
  buildRecordCatalog, catalogViewLink, matchesCatalogFilters, parseCatalogView, locationName,
  RECORD_KIND_LABELS, type CatalogEntry, type CatalogView, type ExperimentReceipt,
} from '@/lib/records-catalog';

const initialView = parseCatalogView(new URLSearchParams());
export default function LibraryPage() {
  const { tx, locale, date } = useLanguage();
  const [data, setData] = useState<LocalLibrary | null>(null), [editors, setEditors] = useState<EditorRecord[]>([]), [receipts, setReceipts] = useState<ExperimentReceipt[]>([]);
  const [viewContext, setViewContext] = useState(''), [view, setView] = useState<CatalogView>(initialView);
  const [selectedId, setSelectedId] = useState(''), [explicitSelection, setExplicitSelection] = useState(false);
  const [ar, setAR] = useState(90), [ready, setReady] = useState(false), [loading, setLoading] = useState(true);
  const [error, setError] = useState(''), [catalogWarnings, setCatalogWarnings] = useState<string[]>([]), [retry, setRetry] = useState(0);
  useEffect(() => {
    const restore = () => {
      const q = new URLSearchParams(window.location.search), id = q.get('record');
      setViewContext(window.location.search); setView(parseCatalogView(q)); setAR(parseAR(q.get('ar')));
      setExplicitSelection(Boolean(id)); setSelectedId(id ?? ''); setReady(true);
    };
    restore(); window.addEventListener('popstate', restore); return () => window.removeEventListener('popstate', restore);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const read = async (url: string, message: string) => {
      const response = await fetch(url, { signal: controller.signal, cache: 'no-store' });
      if (!response.ok) throw new Error(message);
      return response.json();
    };
    void Promise.allSettled([
      read('/api/local-compute/library', '本机数据服务未连接。请启动本地App后重新读取。'),
      read('/api/electrode-editor/records', '电极编辑记录未载入，请刷新记录。'),
      read('/api/community/records', '当前浏览器的信号记录未载入，请刷新记录。'),
    ]).then(([layouts, edits, signals]) => {
      if (controller.signal.aborted) return;
      if (layouts.status === 'fulfilled' && layouts.value.schema === 'local-data-library/1') { setData(layouts.value); setError(''); }
      else setError(layouts.status === 'rejected' ? layouts.reason.message : '方案目录格式错误');
      setEditors(edits.status === 'fulfilled' ? edits.value.records : []);
      setReceipts(signals.status === 'fulfilled' && signals.value.schema === 'browser-experiment-records/1' ? signals.value.records : []);
      setCatalogWarnings([edits, signals].flatMap(result => result.status === 'rejected' ? [result.reason.message] : []));
      setLoading(false);
    });
    return () => controller.abort();
  }, [retry]);
  const catalog = useMemo(() => buildRecordCatalog(data?.records ?? [], editors, receipts), [data, editors, receipts]);
  const title = useCallback((entry: CatalogEntry) => {
    if ('summary' in entry) return localizedRecordTitle(entry.summary, locale);
    if (entry.kind === 'editor') return `${tx('编辑布局')} · ${entry.electrode_count} ${tx('电极')} · ${localizedEditorParentTitle(entry.editor, data?.records ?? [], locale)}`;
    const source = entry.request.mode === 'single_source' ? `${tx('单源')} ${entry.request.source_index}`
      : entry.request.mode === 'cross_region' ? entry.request.brain_regions.map(id => tx(SOURCE_REGIONS.find(region => region.id === id)?.label ?? id)).join(' + ')
      : tx(SOURCE_REGIONS.find(region => region.id === entry.request.brain_region)?.label ?? entry.request.brain_region ?? '历史源定义');
    return `${tx('信号实验')} · ${source} · ${tx(entry.request.waveform === 'burst' ? '短时爆发' : '持续节律')}`;
  }, [locale, tx, data]);
  const choices = useMemo(() => catalog.filter(entry => {
    if (!matchesCatalogFilters(entry, view)) return false;
    const parent = data?.records.find(record => record.id === entry.parent_id);
    const search = ['summary' in entry ? recordSearchText(entry.summary) : '', parent ? recordSearchText(parent) : '',
      title(entry), entry.id, entry.parent_id ?? '', ...entry.locations.flatMap(location => [location, locationName(location), tx(locationName(location))])].join(' ').toLowerCase();
    return search.includes(view.search.toLowerCase());
  }).sort((a, b) => view.sort === 'name' ? title(a).localeCompare(title(b)) || a.id.localeCompare(b.id)
    : view.sort === 'electrodes' ? (a.electrode_count ?? Infinity) - (b.electrode_count ?? Infinity) || a.id.localeCompare(b.id)
      : (view.sort === 'oldest' ? 1 : -1) * ((Date.parse(a.finished_at ?? '') || 0) - (Date.parse(b.finished_at ?? '') || 0)) || a.id.localeCompare(b.id)), [catalog, view, data, title, tx]);
  const pages = Math.max(1, Math.ceil(choices.length / 10)), displayPage = Math.min(view.page, pages - 1);
  const selected = explicitSelection ? catalog.find(entry => entry.id === selectedId) : choices.find(entry => entry.id === selectedId) ?? choices[displayPage * 10] ?? choices[0];
  const id = selected?.id, listed = choices.slice(displayPage * 10, (displayPage + 1) * 10);
  const here = preserveResultsContext(catalogViewLink(ar, id ?? (explicitSelection ? selectedId : ''), { ...view, page: displayPage }), viewContext);
  useEffect(() => { if (ready && !loading) window.history.replaceState(null, '', here); }, [ready, loading, here]);
  const choose = (value: string) => { setSelectedId(value); setExplicitSelection(true); document.getElementById('record-details')?.scrollIntoView({ behavior: 'smooth' }); };
  const changeView = (patch: Partial<CatalogView>) => { setView(value => ({ ...value, ...patch, page: 0 })); setSelectedId(''); setExplicitSelection(false); };
  const layout = selected && 'summary' in selected ? selected.summary : data?.records.find(record => record.id === selected?.parent_id);
  const editHref = layout ? radiusDesignLink(layout, ar) : null;
  const labHref = layout?.dataset_id === 'strict_area' ? comparisonLink(layout, ar) : editHref ?? '/?ar=' + ar;
  const rootId = selected?.parent_id ?? selected?.id;
  const related = catalog.filter(entry => entry.parent_id === rootId && entry.id !== id);
  const score = (entry: CatalogEntry) => 'summary' in entry ? entry.summary.metrics?.field_relative : entry.kind === 'editor' ? entry.editor.metrics.field_relative
    : entry.receipt.catalog?.conditions?.find(condition => condition.condition === 'mixed')?.field_retention;
  const protocol = (entry: CatalogEntry) => 'summary' in entry ? tx(protocolName(entry.summary.dataset_id)) : entry.kind === 'editor' ? entry.editor.protocol
    : `${entry.receipt.catalog?.protocol ?? (entry.request.mode ? 'source-reception/2' : 'source-reception/1')}${entry.request.region_definition === 'dk40-six-roi-v1' ? ' · DK40' : ' · ' + tx('历史信号协议')}`;
  const electrodeCounts = [...new Set(catalog.flatMap(entry => entry.electrode_count === null ? [] : [entry.electrode_count]))].sort((a, b) => a - b);
  const locations = [...new Set(catalog.flatMap(entry => entry.locations))];
  const regionCounts = [...new Set(catalog.flatMap(entry => entry.region_count === null ? [] : [entry.region_count]))].sort((a, b) => a - b);
  return <main className="lab-page">
    <SiteHeader current="library" arPercent={ar} labHref={labHref} returnHref={here} selection={{ id: layout?.id ?? null,
      phase: selected?.kind === 'editor' ? 'edited' : 'saved', channels: selected?.electrode_count ?? undefined, regions: selected?.region_count ?? undefined }} />
    <div className="lab-container">
      <header className="flex flex-wrap items-end justify-between gap-4 py-6"><div><h1 className="text-2xl font-semibold">{tx('布局与实验记录')}</h1><p className="mt-2 text-base text-muted-foreground">{tx('统一查找布局、坐标评价、编辑副本和信号实验。每条记录保留自己的评价协议与原布局关联。')}</p></div><Button variant="outline" disabled={loading} onClick={() => { setLoading(true); setRetry(value => value + 1); }}><RefreshCcw className="size-4" />{tx('刷新记录')}</Button></header>
      {error && <p role="alert" className="lab-panel mb-4 text-red-800"><RuntimeMessage message={error} /> <a href={'/results?ar=' + ar} className="underline">{tx('仍可查看已导出的历史半径结果')}</a></p>}
      <div className="lab-panel mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="lab-label">{tx('记录类型')}<select className="lab-select" value={view.kind} onChange={event => changeView({ kind: event.target.value as CatalogView['kind'], filter: 'all' })}><option value="all">{tx('全部记录类型')}</option>{Object.entries(RECORD_KIND_LABELS).map(([kind, label]) => <option value={kind} key={kind}>{tx(label)}</option>)}</select></label>
        <label className="lab-label">{tx('布局实验协议')}<select className="lab-select" value={view.filter} onChange={event => changeView({ filter: event.target.value, kind: 'all' })}><option value="all">{tx('全部协议')}</option><option value="design_evaluation">{tx('已评价坐标布局')}</option><option value="current">{tx('面积实验与按需计算记录')}</option><option value="strict_area">{tx('总面积上限约束实验')}</option><option value="cache">{tx('每区半径约束计算')}</option><option value="historical_area">{tx('历史面积实验 · 原坐标范围')}</option><option value="offline_radius">{tx('历史实验 · 允许区域相交')}</option></select></label>
        <label className="lab-label">{tx('实际电极数')}<select className="lab-select" value={view.electrodes} onChange={event => changeView({ electrodes: Number(event.target.value) })}><option value={0}>{tx('全部电极数量')}</option>{electrodeCounts.map(count => <option value={count} key={count}>{count}</option>)}</select></label>
        <label className="lab-label">{tx('电极所在部位')}<select className="lab-select" value={view.location} onChange={event => changeView({ location: event.target.value })}><option value="">{tx('全部部位')}</option>{locations.map(location => <option value={location} key={location}>{tx(locationName(location))}</option>)}</select></label>
        <label className="lab-label">{tx('电极分布区域数')}<select className="lab-select" value={view.region} onChange={event => changeView({ region: Number(event.target.value) })}><option value={0}>{tx('全部区域数量')}</option>{regionCounts.map(count => <option value={count} key={count}>{tx(`${count}个区域`)}</option>)}</select></label>
        <label className="lab-label">{tx('查找方案')}<input className="lab-select" placeholder={tx('例如：耳后、前额、2个区域')} value={view.search} onChange={event => changeView({ search: event.target.value })} /></label>
        <label className="lab-label">{tx('最低保留要求 ')}{ar}%<input className="mt-3 w-full accent-primary" aria-label={tx('记录接受阈值AR')} type="range" min={10} max={100} value={ar} onChange={event => setAR(Number(event.target.value))} /><span className="mt-1 block text-sm font-normal text-muted-foreground">{tx('只判断原记录，不重新计算。')}</span></label>
        <label className="lab-label">{tx('排序方式')}<select className="lab-select" value={view.sort} onChange={event => changeView({ sort: event.target.value })}><option value="newest">{tx('最近保存优先')}</option><option value="oldest">{tx('最早保存优先')}</option><option value="name">{tx('按方案名称')}</option><option value="electrodes">{tx('电极数从少到多')}</option></select></label>
      </div>
      <p className="mb-4 text-sm leading-6 text-muted-foreground">{tx('信号实验仅收录当前浏览器的已完成任务；队列保留最近500个结束任务。筛选记录不会读取完整波形或启动计算。')}</p>
      {[...(data?.warnings ?? []), ...catalogWarnings].map(warning => <p className="mb-3 text-sm text-amber-800" key={warning}><RuntimeMessage message={warning} /></p>)}
      {loading && !catalog.length ? <p className="lab-panel">{tx('读取方案目录…')}</p> : <>
        <section className="lab-panel overflow-x-auto" aria-label={tx('已保存方案列表')}>
          <table className="w-full min-w-[900px] text-left text-sm"><thead><tr className="border-b text-muted-foreground"><th className="pb-3">{tx('记录与协议')}</th><th>{tx('电极 / 区域')}</th><th>{tx('信号重建保留率')}</th><th>{tx('计算状态')}</th><th>{tx('性能判断')}</th><th><span className="sr-only">{tx('操作')}</span></th></tr></thead><tbody>
            {listed.map(row => <tr className={'border-b last:border-0 ' + (row.id === id ? 'bg-primary/5' : '')} key={row.id}><th className="max-w-[350px] py-3 pr-4 font-medium leading-6">{title(row)}<span className="mt-1 block text-xs font-normal text-muted-foreground">{tx(RECORD_KIND_LABELS[row.kind])} · {protocol(row)}</span><span className="mt-1 block text-xs font-normal text-muted-foreground">{row.finished_at ? date(row.finished_at) : tx('保存时间未记录')}</span></th><td className="tabular-nums">{row.electrode_count ?? '—'} / {row.region_count ?? '—'}</td><td className="tabular-nums">{'summary' in row && row.summary.status === 'no_layout' ? tx('未评估') : row.kind === 'source' && !row.receipt.catalog?.conditions?.length ? tx('未保存指标摘要') : tx(percent(score(row)))}{row.kind === 'source' && <span className="block text-xs text-muted-foreground">{tx('心眼混合干扰条件')}</span>}</td><td>{tx('summary' in row && row.summary.status === 'no_layout' ? '本轮未找到完整布局' : '已完成评价')}{'summary' in row && row.summary.dataset_id === 'cache' && !row.summary.compatible && <span className="block text-xs text-amber-800">{tx('旧版本记录 · 仅供查阅')}</span>}</td><td>{'summary' in row ? tx(resultQualification(row.summary, ar)) : row.kind === 'editor' ? tx('按编辑协议解释') : tx('按干扰条件分别解释')}</td><td><Button variant="outline" size="sm" onClick={() => choose(row.id)}>{tx('查看结果')}</Button></td></tr>)}
          </tbody></table>
          {!choices.length && <p className="py-5 text-sm text-muted-foreground">{tx('当前筛选下没有记录。')}</p>}
          <div className="mt-3 flex items-center justify-between gap-4 text-sm text-muted-foreground"><span>{choices.length}{tx('条记录 · 不同协议分开解释')}</span><div className="flex items-center gap-2"><Button size="sm" variant="outline" disabled={displayPage === 0} onClick={() => setView(value => ({ ...value, page: displayPage - 1 }))}>{tx('上一页')}</Button><span>{displayPage + 1} / {pages}</span><Button size="sm" variant="outline" disabled={displayPage + 1 >= pages} onClick={() => setView(value => ({ ...value, page: displayPage + 1 }))}>{tx('下一页')}</Button></div></div>
        </section>
        {explicitSelection && selected && !choices.some(row => row.id === selected.id) && <p className="lab-panel mt-4 text-sm">{tx('链接指定的方案不在当前筛选列表中；下方仍显示该方案的原始记录。')}</p>}
        {explicitSelection && !selected && !loading ? <p role="alert" className="lab-panel mt-5">{tx('指定记录无法读取，请刷新记录或重新选择。')}</p> : selected && <section id="record-details" className="mt-6 scroll-mt-32 space-y-4">
          {'summary' in selected ? <SavedLayoutDetails key={selected.id + '-' + retry} summary={selected.summary} ar={ar} returnHref={here} /> : <CatalogExperimentDetails key={selected.id} entry={selected} parents={data?.records ?? []} ar={ar} returnHref={here} />}
          {related.length > 0 && <div className="lab-panel"><h3 className="font-semibold">{tx('同一原布局的关联记录')}</h3><p className="mt-2 text-sm text-muted-foreground">{tx('编辑副本与信号实验分别关联原布局；信号实验使用其记录指定的完整布局。')}</p><ul className="mt-3 max-h-80 space-y-2 overflow-y-auto text-sm">{related.map(entry => <li key={entry.id}><button className="text-left text-primary underline underline-offset-4" onClick={() => choose(entry.id)}>{tx(RECORD_KIND_LABELS[entry.kind])} · {title(entry)} · {entry.finished_at ? date(entry.finished_at, true) : ''}</button></li>)}</ul></div>}
        </section>}
      </>}
    </div>
  </main>;
}
