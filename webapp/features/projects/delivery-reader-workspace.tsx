'use client';
/* oxlint-disable next/no-html-link-for-pages -- retain static local-file navigation */
import { lazy, Suspense } from 'react';
import { ChevronDown } from 'lucide-react';
import { SiteHeader } from '@/components/site-header';
import { useLanguage } from '@/components/language-provider';
import { Button } from '@/components/ui/button';
import { RuntimeMessage } from '@/components/runtime-message';
import { DELIVERY_INPUT_LIMIT } from './research-delivery-reader';
import { useDeliveryReader } from './use-delivery-reader';
import { originalDeliveryDownload, deliveryReadmeDownload, deliverySnapshotDownload, saveLocalDeliveryFile } from './delivery-reader-downloads';
import { FilePicker } from '@/components/ui/file-picker';

const SnapshotViewer = lazy(() => import('./project-snapshot-viewer').then(module => ({ default: module.ProjectSnapshotViewer })));
const kindLabel = { layout: '布局评价', editor: '电极编辑副本', source: '信号实验' };

export default function DeliveryReaderWorkspace() {
  const { tx, date } = useLanguage(), reader = useDeliveryReader();
  const { opened, selected, status, error, notice } = reader;
  return <main className="lab-page">
    <SiteHeader current="projects" offline selection={{ id: null, phase: 'saved' }} />
    <div className="lab-container space-y-5 py-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-[1.65rem]">{tx('打开本地交付包')}</h1>
        <p className="mt-1.5 max-w-3xl text-sm text-ink-soft sm:text-base">{tx('在当前浏览器读取项目交付包，查看说明、指标、坐标与波形。')}</p>
      </header>
      <section className="lab-panel space-y-3" aria-label={tx('选择交付包文件')}>
        <label className="lab-label">{tx('项目交付包 JSON')}<FilePicker accept="application/json,.json" onChange={event => {
          const file = event.target.files?.[0]; event.target.value = ''; if (file) void reader.openFile(file);
        }} /></label>
        <p className="text-xs text-muted-foreground">{tx('文件上限')}：{DELIVERY_INPUT_LIMIT / 1048576} MiB</p>
        {status === 'loading' && <div className="flex flex-wrap items-center gap-3"><output aria-live="polite" className="text-sm text-primary">{tx('正在读取并校验交付包…')}</output><Button type="button" size="sm" variant="outline" onClick={() => reader.clear(true)}>{tx('取消读取')}</Button></div>}
        {notice && <output className="block text-sm text-muted-foreground" aria-live="polite">{tx(notice)}</output>}
        {error && <p role="alert" className="text-sm text-danger"><RuntimeMessage message={error} /></p>}
      </section>
      {opened && <>
        <section className="lab-panel space-y-4" aria-label={tx('已校验的交付项目')}>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold">{opened.delivery.project.title}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{tx('负责人')}：{opened.delivery.project.owner_name}</p>
            </div>
            <Button type="button" size="sm" variant="outline" onClick={() => reader.clear()}>{tx('关闭交付包')}</Button>
          </div>
          <dl className="grid gap-2.5 text-xs sm:grid-cols-3">
            <div className="lab-subpanel py-2.5"><dt className="text-muted-foreground">{tx('文件名称')}</dt><dd className="mt-0.5 break-all font-medium text-foreground">{opened.file.name}</dd></div>
            <div className="lab-subpanel py-2.5"><dt className="text-muted-foreground">{tx('导出时间')}</dt><dd className="mt-0.5 font-mono tabular-nums text-foreground">{date(opened.delivery.exported_at, true)}</dd></div>
            <div className="lab-subpanel py-2.5"><dt className="text-muted-foreground">{tx('项目版本')}</dt><dd className="mt-0.5 font-mono font-semibold tabular-nums text-foreground">{opened.delivery.project.revision}</dd></div>
            <div className="lab-subpanel py-2.5"><dt className="text-muted-foreground">{tx('交付记录数')}</dt><dd className="mt-0.5 font-mono font-semibold tabular-nums text-foreground">{opened.delivery.entries.length}</dd></div>
            <div className="lab-subpanel py-2.5"><dt className="text-muted-foreground">{tx('文件总大小')}</dt><dd className="mt-0.5 font-mono tabular-nums text-foreground">{(opened.file.size / 1048576).toFixed(2)} MiB</dd></div>
            <div className="lab-subpanel py-2.5 sm:col-span-3"><dt className="text-muted-foreground">{tx('交付清单 SHA-256')}</dt><dd className="mt-0.5 break-all font-mono text-[11px] text-foreground">{opened.delivery.manifest_sha256}</dd></div>
          </dl>
          {opened.delivery.project.notes && <p className="whitespace-pre-wrap text-sm leading-6">{opened.delivery.project.notes}</p>}
          <div className="flex flex-wrap gap-2.5"><Button type="button" size="sm" onClick={() => saveLocalDeliveryFile(originalDeliveryDownload(opened.delivery, opened.file))}>{tx('下载原始交付包')}</Button><Button type="button" size="sm" variant="outline" onClick={() => saveLocalDeliveryFile(deliveryReadmeDownload(opened.delivery))}>{tx('下载交付说明')}</Button></div>
          <details className="group/readme rounded-xl border border-border/75 bg-muted/25 p-3.5">
            <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium select-none [&::-webkit-details-marker]:hidden">
              <span>{tx('查看交付说明')}</span>
              <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/readme:rotate-180" />
            </summary>
            <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-border/65 bg-card p-3.5 text-xs leading-6">{opened.delivery.readme}</pre>
          </details>
        </section>
        <section className="lab-panel space-y-4" aria-label={tx('交付记录浏览')}>
          <label className="lab-label">{tx('选择交付记录')}<select aria-label={tx('选择交付记录')} className="lab-select" value={selected?.entry.id ?? ''} onChange={event => reader.select(event.target.value)}>{opened.delivery.entries.map(row => <option key={row.entry.id} value={row.entry.id}>{row.entry.title} · {tx(kindLabel[row.entry.kind])}</option>)}</select></label>
          {selected ? <article key={selected.entry.id} data-delivery-entry-id={selected.entry.id} className="space-y-4">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="lab-chip text-primary">{tx(kindLabel[selected.entry.kind])}</span>
                <span className="text-xs text-muted-foreground">{date(selected.entry.created_at, true)}</span>
              </div>
              <h2 className="mt-1.5 text-lg font-semibold">{selected.entry.title}</h2>
              <p className="mt-1 inline-block max-w-full truncate rounded-md bg-muted/65 px-2 py-0.5 font-mono text-xs text-muted-foreground" title={selected.entry.record_id}>{selected.entry.record_id}</p>
            </div>
            {selected.entry.notes && <p className="whitespace-pre-wrap text-sm leading-6">{selected.entry.notes}</p>}
            <Suspense fallback={<p>{tx('正在载入结果视图…')}</p>}><SnapshotViewer entry={selected.entry} snapshot={selected.snapshot} /></Suspense>
            <Button type="button" size="sm" variant="outline" onClick={() => saveLocalDeliveryFile(deliverySnapshotDownload(selected))}>{tx('下载此记录的原始快照')}</Button>
            <details className="group/snap"><summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-primary select-none [&::-webkit-details-marker]:hidden"><span>{tx('展开原始数据')}</span><ChevronDown aria-hidden className="size-3.5 transition-transform group-open/snap:rotate-180" /></summary><pre className="mt-2.5 max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-xl border border-border/70 bg-muted/45 p-3.5 font-mono text-xs">{selected.snapshot_json}</pre></details>
          </article> : <p className="text-sm text-muted-foreground">{tx('交付包中没有实验记录。')}</p>}
        </section>
      </>}
    </div>
  </main>;
}
