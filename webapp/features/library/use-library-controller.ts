'use client';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiJson } from '@/client/task-client';
import { useLanguage } from '@/components/language-provider';
import { localizedEditorParentTitle, localizedRecordTitle, recordSearchText } from '@/lib/i18n/records';
import { preserveResultsContext } from '@/lib/results-library';
import { comparisonLink, parseAR, radiusDesignLink } from '@/lib/lab-workflow';
import type { LocalLibrary } from '@/lib/local-library';
import type { EditorRecord } from '@/lib/electrode-editor';
import { protocolName } from '@/lib/ui-language';
import { evaluationLabels, layoutHref, primaryRecord } from '@/lib/layout-page';
import { SOURCE_REGIONS } from '@/lib/source-regions';
import { matchesSearch, parseSearch, searchTarget, unmatchedWords } from '@/lib/library-search';
import { buildRecordCatalog, catalogViewLink, groupConditionVariants, latestPerCondition, matchesCatalogFilters, parseCatalogView, locationName,
  type CatalogEntry, type CatalogRow, type CatalogView, type ExperimentReceipt, type ExperimentRecords } from '@/lib/records-catalog';

const initialView = parseCatalogView(new URLSearchParams());

export function useLibraryController() {
  const { tx, locale } = useLanguage();
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
    const read = <T>(url: string, errorMessage: string) => apiJson<T>(url, { signal: controller.signal, errorMessage });
    void Promise.allSettled([
      read<LocalLibrary>('/api/local-compute/library', '数据服务暂不可用，请稍后重新读取。'),
      read<{ records: EditorRecord[] }>('/api/electrode-editor/records', '电极编辑记录未载入，请刷新记录。'),
      read<ExperimentRecords>('/api/community/records', '此工作区的信号记录未载入，请刷新记录。'),
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
  // The same radius request computed by older code versions: keep the current-code (else newest)
  // record in the list and fold the others away; they still open from their links.
  const [showSuperseded, setShowSuperseded] = useState(false);
  const superseded = useMemo(() => {
    const groups = new Map<string, CatalogEntry[]>(), hidden = new Set<string>();
    for (const entry of catalog) if ('summary' in entry && entry.summary.dataset_id === 'cache' && entry.summary.request) {
      const key = JSON.stringify(entry.summary.request);
      groups.set(key, [...(groups.get(key) ?? []), entry]);
    }
    for (const rows of groups.values()) {
      if (rows.length < 2) continue;
      const rank = (entry: CatalogEntry) => ('summary' in entry && entry.summary.compatible ? 1 : 0);
      rows.sort((a, b) => rank(b) - rank(a) || (Date.parse(b.finished_at ?? '') || 0) - (Date.parse(a.finished_at ?? '') || 0) || a.id.localeCompare(b.id));
      for (const entry of rows.slice(1)) hidden.add(entry.id);
    }
    return hidden;
  }, [catalog]);
  const title = useCallback((entry: CatalogEntry) => {
    if ('summary' in entry) return localizedRecordTitle(entry.summary, locale);
    if (entry.kind === 'editor') return `${tx('编辑布局')} · ${entry.electrode_count} ${tx('电极')} · ${localizedEditorParentTitle(entry.editor, data?.records ?? [], locale)}`;
    const source = entry.request.mode === 'single_source' ? `${tx('单源')} ${entry.request.source_index}`
      : entry.request.mode === 'cross_region' ? entry.request.brain_regions.map(id => tx(SOURCE_REGIONS.find(region => region.id === id)?.label ?? id)).join(' + ')
      : tx(SOURCE_REGIONS.find(region => region.id === entry.request.brain_region)?.label ?? entry.request.brain_region ?? '历史源定义');
    return `${tx('信号实验')} · ${source} · ${tx(entry.request.waveform === 'burst' ? '短时爆发' : '持续节律')}`;
  }, [locale, tx, data]);
  /** A layout row is named by its nominal evaluation; each member by its own evaluation condition. */
  const groupPrimary = (entries: CatalogEntry[]) => {
    const primary = primaryRecord(entries.flatMap(entry => 'summary' in entry ? [entry.summary] : []));
    return entries.find(entry => entry.id === primary?.id) ?? entries[0];
  };
  const groupTitle = (entry: CatalogEntry) => 'summary' in entry ? localizedRecordTitle({ ...entry.summary, evaluation_condition: undefined }, locale) : title(entry);
  const conditionTitle = (entry: CatalogEntry) => 'summary' in entry ? evaluationLabels(entry.summary).map(label => tx(label)).join(' · ') : title(entry);
  // Each entry's search target is built once per catalog and language, not on every keystroke.
  const targets = useMemo(() => new Map(catalog.map(entry => {
    const parent = data?.records.find(record => record.id === entry.parent_id);
    return [entry.id, searchTarget(['summary' in entry ? recordSearchText(entry.summary) : '', parent ? recordSearchText(parent) : '', title(entry),
      ...entry.locations.flatMap(location => [location, locationName(location), tx(locationName(location))])],
    { regionCount: entry.region_count, electrodeCount: entry.electrode_count, locations: entry.locations, ids: [entry.id, entry.parent_id ?? ''] })];
  })), [catalog, data, title, tx]);
  const searchWords = useMemo(() => parseSearch(view.search), [view.search]);
  const filtered = useMemo(() => catalog.filter(entry => matchesCatalogFilters(entry, view)), [catalog, view]);
  /** Words of the query that no record under the other filters contains, so the page can name them. */
  const searchMisses = useMemo(() => unmatchedWords(searchWords, filtered.map(entry => targets.get(entry.id)!)), [searchWords, filtered, targets]);
  const matched = useMemo(() => filtered.filter(entry => matchesSearch(targets.get(entry.id)!, searchWords)).sort((a, b) => view.sort === 'name' ? title(a).localeCompare(title(b)) || a.id.localeCompare(b.id)
    : view.sort === 'electrodes' ? (a.electrode_count ?? Infinity) - (b.electrode_count ?? Infinity) || a.id.localeCompare(b.id)
      : (view.sort === 'oldest' ? 1 : -1) * ((Date.parse(a.finished_at ?? '') || 0) - (Date.parse(b.finished_at ?? '') || 0)) || a.id.localeCompare(b.id)), [filtered, targets, searchWords, view.sort, title]);
  const choices = useMemo(() => showSuperseded ? matched : matched.filter(entry => !superseded.has(entry.id)), [matched, superseded, showSuperseded]);
  const foldedCount = matched.length - choices.length;
  // Study cases of one design (one row per head, noise or conductivity condition) page as one row.
  const rows = useMemo(() => groupConditionVariants(choices), [choices]);
  const [expanded, setExpanded] = useState<string[]>([]);
  const toggleGroup = (key: string) => setExpanded(keys => keys.includes(key) ? keys.filter(value => value !== key) : [...keys, key]);
  const pages = Math.max(1, Math.ceil(rows.length / 10)), displayPage = Math.min(view.page, pages - 1);
  // Details (and their full record) load only for a record the visitor opened.
  const selected = explicitSelection ? catalog.find(entry => entry.id === selectedId) : undefined;
  const id = selected?.id, listed: CatalogRow[] = rows.slice(displayPage * 10, (displayPage + 1) * 10);
  const isExpanded = (row: Extract<CatalogRow, { kind: 'group' }>) => expanded.includes(row.key) || row.entries.some(entry => entry.id === id);
  const here = preserveResultsContext(catalogViewLink(ar, id ?? (explicitSelection ? selectedId : ''), { ...view, page: displayPage }), viewContext);
  useEffect(() => { if (ready && !loading) window.history.replaceState(null, '', here); }, [ready, loading, here]);
  // A layout or coordinate evaluation opens on its layout's page; editor copies and
  // signal experiments keep their details here.
  const layoutPage = (value: string) => {
    const q = new URLSearchParams(viewContext), next = new URL(layoutHref({ id: value }, ar), 'http://localhost');
    const annotation = q.get('record') === value ? q.get('annotation_id') : null;
    if (annotation) next.searchParams.set('annotation_id', annotation);
    return next.pathname + next.search;
  };
  const isLayout = (value: string) => catalog.some(entry => entry.id === value && 'summary' in entry);
  useEffect(() => {
    if (ready && !loading && explicitSelection && isLayout(selectedId)) window.location.replace(layoutPage(selectedId));
  });
  const choose = (value: string) => {
    if (isLayout(value)) { window.location.assign(layoutPage(value)); return; }
    // A new history entry, so Back returns to the list rather than leaving the page.
    window.history.pushState(null, '', preserveResultsContext(catalogViewLink(ar, value, { ...view, page: displayPage }), viewContext));
    setSelectedId(value); setExplicitSelection(true);
    requestAnimationFrame(() => document.getElementById('record-details')?.scrollIntoView({ behavior: 'smooth' }));
  };
  const changeView = (patch: Partial<CatalogView>) => { setView(value => ({ ...value, ...patch, page: 0 })); setSelectedId(''); setExplicitSelection(false); };
  const layout = selected && 'summary' in selected ? selected.summary : data?.records.find(record => record.id === selected?.parent_id);
  const editHref = layout ? radiusDesignLink(layout, ar) : null;
  const labHref = layout?.dataset_id === 'strict_area' ? comparisonLink(layout, ar) : editHref ?? '/findings?ar=' + ar;
  const rootId = selected?.parent_id ?? selected?.id;
  const related = catalog.filter(entry => entry.parent_id === rootId && entry.id !== id);
  const score = (entry: CatalogEntry) => 'summary' in entry ? entry.summary.metrics?.field_relative : entry.kind === 'editor' ? entry.editor.metrics.field_relative
    : entry.receipt.catalog?.conditions?.find(condition => condition.condition === 'mixed')?.field_retention;
  const protocol = (entry: CatalogEntry) => 'summary' in entry ? tx(protocolName(entry.summary.dataset_id)) : entry.kind === 'editor' ? entry.editor.protocol
    : `${entry.receipt.catalog?.protocol ?? (entry.request.mode ? 'source-reception/2' : 'source-reception/1')}${entry.request.region_definition === 'dk40-six-roi-v1' ? ' · DK40' : ' · ' + tx('历史信号协议')}`;
  const electrodeCounts = [...new Set(catalog.flatMap(entry => entry.electrode_count === null ? [] : [entry.electrode_count]))].sort((a, b) => a - b);
  const locations = [...new Set(catalog.flatMap(entry => entry.locations))];
  const regionCounts = [...new Set(catalog.flatMap(entry => entry.region_count === null ? [] : [entry.region_count]))].sort((a, b) => a - b);
  return { rows, isExpanded, toggleGroup, groupPrimary, groupTitle, conditionTitle, latestPerCondition, showSuperseded, setShowSuperseded, foldedCount, ar, setAR, labHref, here, layout, selected, loading, setLoading, retry, setRetry, error, view, changeView, electrodeCounts, locations, regionCounts, data, catalogWarnings, catalog, listed, id, title, protocol, score, choose, choices, displayPage, setView, pages, explicitSelection, related, searchWords, searchMisses };
}
