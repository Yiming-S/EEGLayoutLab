'use client';

import { useEffect, useRef, useState } from 'react';
import { Download, ChevronDown } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';
import type { SavedRecord } from '@/lib/local-library';
import { fetchReproducibilityBundle, layoutExportAvailability, layoutExportFile, type ExportFile, type LayoutExportKind } from '@/lib/layout-exports';
import { SHOWCASE } from '@/lib/showcase';

const options: { kind: LayoutExportKind; label: string; note: string }[] = [
  { kind: 'coordinates_csv', label: '电极坐标 CSV', note: 'Ernie原生毫米坐标；保留原电极顺序与区域编号。' },
  { kind: 'design_json', label: '可导入布局 JSON', note: '仅布局坐标与区域标签，可用于本App的坐标导入。' },
  { kind: 'result_json', label: '完整结果 JSON', note: '原始保存记录，包括指标、坐标和来源字段。' },
  { kind: 'report_md', label: '简明结果报告 Markdown', note: '当前指标、最低保留要求和模型来源，适合阅读与分享。' },
  { kind: 'bundle_json', label: '复现实验包 JSON', note: '读取原始配置、轨迹与校验身份；不包含代码、头模或前向矩阵文件。' },
];

function download(file: ExportFile) {
  const url = URL.createObjectURL(new Blob([file.content], { type: file.mime }));
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = file.filename;
  document.body.appendChild(anchor);
  try { anchor.click(); } finally { anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }
}

export function LayoutExportMenu({ record, ar, showcase = SHOWCASE }: { record: SavedRecord; ar: number; showcase?: boolean }) {
  const { locale, tx } = useLanguage();
  const request = useRef<AbortController | null>(null);
  const [state, setState] = useState<{ id: string; kind: LayoutExportKind; pending: boolean; error: string | null; ready: boolean } | null>(null);
  useEffect(() => () => request.current?.abort(), [record.id]);
  const active = state?.id === record.id ? state : null;
  const availability = layoutExportAvailability(record);
  const run = async (kind: LayoutExportKind) => {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setState({ id: record.id, kind, pending: true, error: null, ready: false });
    try {
      const file = kind === 'bundle_json' ? await fetchReproducibilityBundle(record, fetch, controller.signal) : layoutExportFile(record, kind, ar, locale);
      if (controller.signal.aborted) return;
      download(file);
      setState({ id: record.id, kind, pending: false, error: null, ready: true });
    } catch (error) {
      if (!controller.signal.aborted) setState({ id: record.id, kind, pending: false, error: error instanceof Error ? error.message : '导出未完成，请重试。', ready: false });
    }
  };
  return <details className="group relative w-full sm:w-auto" data-layout-export-menu>
    <summary className="inline-flex cursor-pointer list-none items-center justify-center gap-2 rounded-lg border border-border bg-background px-4 py-2.5 text-sm font-semibold text-foreground shadow-sm transition hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring [&::-webkit-details-marker]:hidden">
      <Download size={16} aria-hidden="true" />{tx('导出当前方案')}<ChevronDown size={14} aria-hidden="true" className="transition group-open:rotate-180" />
    </summary>
    <div className="relative z-30 mt-2 w-full rounded-xl border border-border bg-background p-2 text-left shadow-xl sm:absolute sm:right-0 sm:w-[23rem]" aria-label={tx('导出当前方案')}>
      <p className="px-3 py-2 text-xs font-normal leading-5 text-muted-foreground">{tx('导出只读取已有结果，不启动仿真。布局JSON与结果JSON用途不同。')}</p>
      <div className="space-y-1">
        {options.map((option) => {
          const blocked = option.kind === 'coordinates_csv'
            ? !availability.coordinates
            : option.kind === 'design_json'
              ? !availability.design
              : false;
          const blockedReason = option.kind === 'coordinates_csv' ? availability.csvReason : availability.reason;
          const label = showcase && option.kind === 'bundle_json' ? '脱敏展示副本 JSON'
            : showcase && option.kind === 'result_json' ? '展示记录 JSON' : option.label;
          const note = showcase && option.kind === 'bundle_json'
            ? '含脱敏结果及副本校验值；原始文件摘要和科学编号仅作来源引用，不能用此副本重算。'
            : showcase && option.kind === 'result_json'
              ? '展示用指标、坐标与脱敏来源字段；不是原始计算缓存。' : option.note;
          return <button key={option.kind} type="button" disabled={!!active?.pending || blocked} onClick={() => void run(option.kind)}
            className="block w-full rounded-lg px-3 py-2.5 text-left transition hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-45">
            <span className="block text-sm font-semibold text-foreground">{tx(label)}</span>
            <span className="mt-1 block text-xs font-normal leading-5 text-muted-foreground">{tx(blocked ? blockedReason! : note)}</span>
          </button>;
        })}
      </div>
      {active?.pending && <output className="block px-3 py-2 text-xs font-normal text-muted-foreground">{tx(showcase ? '正在读取并校验展示副本…' : '正在读取复现实验包…')}</output>}
      {active?.ready && <output className="block px-3 py-2 text-xs font-normal leading-5 text-muted-foreground">{tx('文件已准备下载，可在浏览器下载列表中查看。')}</output>}
      {active?.error && <div className="m-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm font-normal">
        <div role="alert"><RuntimeMessage message={active.error} /></div>
        <button type="button" className="mt-2 font-semibold underline underline-offset-4" onClick={() => void run(active.kind)}>{tx('重试本次导出')}</button>
      </div>}
    </div>
  </details>;
}
