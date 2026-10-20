'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useState } from 'react';
import { useLanguage } from './language-provider';
import { RuntimeMessage } from './runtime-message';
import { Button } from './ui/button';
import { percent } from './performance-summary';
import { localizedEditorParentTitle, localizedRecordTitle } from '@/lib/i18n/records';
import { CONDITION_LABELS } from '@/lib/source-reception';
import { editorRecordLink, savedSourceLink, type CatalogEntry, type ExperimentReceipt } from '@/lib/records-catalog';
import type { SavedSummary } from '@/lib/local-library';

export async function downloadExperimentReceipt(receipt: ExperimentReceipt) {
  const response = await fetch(`/api/community/records/${receipt.id}/result`, { cache: 'no-store', signal: AbortSignal.timeout(30000) });
  const data = await response.json();
  if (!response.ok || !data.result) throw new Error(data.error ?? '计算记录无法读取，请重新提交');
  const url = URL.createObjectURL(new Blob([JSON.stringify(data.result, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = `eeg-result-${receipt.id}.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function CatalogExperimentDetails({ entry, parents, ar, returnHref }: { entry: CatalogEntry; parents: SavedSummary[]; ar: number; returnHref: string }) {
  const { tx, locale, date } = useLanguage();
  const [failure, setFailure] = useState(''), [downloading, setDownloading] = useState(false);
  if ('summary' in entry) return null;
  const parent = parents.find(record => record.id === entry.parent_id);
  const parentTitle = entry.kind === 'editor' ? localizedEditorParentTitle(entry.editor, parents, locale)
    : parent ? localizedRecordTitle(parent, locale) : entry.receipt.catalog?.parent_label ?? entry.parent_id;
  const href = entry.kind === 'editor' ? editorRecordLink(entry.editor, ar, returnHref) : savedSourceLink(entry.request, ar, returnHref);
  const download = async () => {
    if (entry.kind !== 'source') return;
    setDownloading(true); setFailure('');
    try { await downloadExperimentReceipt(entry.receipt); }
    catch (error) { setFailure(error instanceof Error ? error.message : '无法读取任务'); }
    finally { setDownloading(false); }
  };
  return <article className="lab-panel space-y-4">
    <header><p className="lab-eyebrow">{tx(entry.kind === 'editor' ? '编辑副本' : '信号实验')}</p><h2 className="mt-2 text-lg font-semibold">{parentTitle}</h2></header>
    <dl className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
      <div><dt className="inline text-muted-foreground">{tx('保存时间')}：</dt><dd className="inline">{entry.finished_at ? date(entry.finished_at, true) : tx('未记录')}</dd></div>
      <div><dt className="inline text-muted-foreground">{tx('电极数 / 区域数')}：</dt><dd className="inline">{entry.electrode_count ?? '—'} / {entry.region_count ?? '—'}</dd></div>
      <div><dt className="inline text-muted-foreground">{tx('评价协议')}：</dt><dd className="inline font-mono">{entry.kind === 'editor' ? entry.editor.protocol : entry.receipt.catalog?.protocol ?? (entry.request.mode ? 'source-reception/2' : 'source-reception/1')}</dd></div>
    </dl>
    <div className="flex flex-wrap gap-3">
      {href && <a className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground" href={href}>{tx(entry.kind === 'editor' ? '载入此编辑记录' : '打开信号实验')}</a>}
      {parent && <a className="rounded-lg border px-4 py-2 text-sm" href={`/library?record=${parent.id}&ar=${ar}`}>{tx('查看原布局')}</a>}
      {entry.kind === 'source' && <Button variant="outline" disabled={downloading} onClick={() => void download()}>{tx(downloading ? '读取计算结果…' : '下载计算结果')}</Button>}
    </div>
    {entry.kind === 'editor' ? <>
      <p className="text-sm leading-6 text-muted-foreground">{tx('编辑评分使用独立协议。载入后恢复这条记录的点位；重新评价时检查模型、原布局与缓存。')}</p>
      <dl className="grid gap-3 text-sm sm:grid-cols-3">
        <div><dt className="text-muted-foreground">{tx('信号重建保留率')}</dt><dd>{tx(percent(entry.editor.metrics.field_relative))}</dd></div>
        <div><dt className="text-muted-foreground">{tx('幅度保留率（最差10%）')}</dt><dd>{tx(percent(entry.editor.metrics.sensitivity_tail))}</dd></div>
        <div><dt className="text-muted-foreground">{tx('相对定位评分')}</dt><dd>{tx(percent(entry.editor.metrics.localization_relative))}</dd></div>
      </dl>
    </> : <>
      <p className="text-sm leading-6 text-muted-foreground">{tx(href ? '打开后恢复源模式、源位置、波形、干扰幅度与随机种子，并检查该场景的已有缓存。' : '历史信号协议保留原结果下载；当前信号页面使用不同源分区，不能直接恢复这个场景。')}</p>
      {entry.receipt.catalog?.conditions?.length ? <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-left text-sm"><thead><tr className="border-b"><th className="pb-2">{tx('干扰条件')}</th><th>{tx('标准布局重建解释率')}</th><th>{tx('当前布局重建解释率')}</th><th>{tx('信号重建保留率')}</th></tr></thead><tbody>{entry.receipt.catalog.conditions.map(condition => <tr className="border-b last:border-0" key={condition.condition}><th className="py-2 font-normal">{tx(CONDITION_LABELS[condition.condition])}</th><td>{tx(percent(condition.baseline_explained_energy))}</td><td>{tx(percent(condition.candidate_explained_energy))}</td><td>{tx(percent(condition.field_retention))}</td></tr>)}</tbody></table></div> : <p className="text-sm text-muted-foreground">{tx('这条旧任务未保存指标摘要，查看或下载结果时读取完整记录。')}</p>}
      <details className="text-sm"><summary className="cursor-pointer">{tx('查看场景参数')}</summary><pre className="mt-3 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-muted p-3">{JSON.stringify(entry.request, null, 2)}</pre></details>
    </>}
    {failure && <p role="alert" className="text-sm text-red-700"><RuntimeMessage message={failure} /></p>}
  </article>;
}
