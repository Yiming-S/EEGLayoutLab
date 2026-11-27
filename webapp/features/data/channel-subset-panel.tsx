'use client';
import { useState } from 'react';
import { Check, ChevronDown, Copy, Sparkles } from 'lucide-react';
import { useLanguage } from '@/components/language-provider';
import { FilePicker } from '@/components/ui/file-picker';
import { Button } from '@/components/ui/button';
import { DEFAULT_COUNTS, channelSubsets, type Stats } from '@/lib/channel-subset';
import { buildDemoChannelSubsetInput } from '@/lib/channel-subset-demo';
import { ChannelSubsetChart } from './channel-subset-chart';
import { ChannelSubsetMap } from './channel-subset-map';

type Report = ReturnType<typeof channelSubsets>;
type MethodRow = { count: number; channels: string[]; train_error: number; test_error: Stats | null };
const FILE_BYTES = 20 * 1024 * 1024, MAX_FILES = 2000;
const CLI_SUMMARY_COMMAND = 'eeglayoutlab eeg-summary recording.edf --out-dir ./summaries';
const METHOD_LABELS: Record<string, string> = { data: '按数据贪心选择', data_prior: '按数据先验模型选择', area_prior: '按面积先验模型选择' };
const pct = (value: number) => `${(100 * value).toFixed(1)}%`;

async function readFiles(list: FileList | null) {
  const files = Array.from(list ?? []);
  if (files.length > MAX_FILES) throw new Error(`一次最多选择${MAX_FILES}个文件`);
  return Promise.all(files.map(async (file) => {
    if (file.size > FILE_BYTES) throw new Error(`${file.name}超过20 MB`);
    try { return JSON.parse(await file.text()) as unknown; } catch { throw new Error(`${file.name}不是有效的JSON`); }
  }));
}

/** Channel-subset selection from covariance summaries (eeglayoutlab eeg-summary), computed in the browser. */
export function ChannelSubsetPanel() {
  const { tx } = useLanguage();
  const [training, setTraining] = useState<unknown[]>([]), [test, setTest] = useState<unknown[]>([]), [prior, setPrior] = useState<unknown>(undefined);
  // Empty means the default sizes that fit the recording.
  const [counts, setCounts] = useState('');
  const [demoActive, setDemoActive] = useState(false);
  const [copied, setCopied] = useState(false);
  const [report, setReport] = useState<Report | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const pick = (set: (value: unknown[]) => void) => async (list: FileList | null) => {
    setError(''); setReport(null); setDemoActive(false);
    try { set(await readFiles(list)); } catch (e) { setError(e instanceof Error ? e.message : '文件无法读取'); }
  };
  const copyCli = () => {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) return;
    void navigator.clipboard.writeText(CLI_SUMMARY_COMMAND).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  };
  function computeWith(nextTraining: unknown[], nextTest: unknown[], nextPrior: unknown) {
    setBusy(true); setError('');
    // Yield once so the busy state renders; the calculation takes well under a second for 128 channels.
    setTimeout(() => {
      try {
        setReport(channelSubsets({
          training: nextTraining,
          test: nextTest,
          prior: nextPrior,
          counts: counts.trim() ? counts.split(',').map((v) => Number(v.trim())) : undefined,
        }));
      } catch (e) {
        setReport(null); setError(e instanceof Error ? e.message : '计算失败');
      } finally { setBusy(false); }
    }, 0);
  }
  function loadDemo() {
    const demo = buildDemoChannelSubsetInput();
    setTraining(demo.training);
    setTest(demo.test);
    setPrior(undefined);
    setDemoActive(true);
    computeWith(demo.training, demo.test, undefined);
  }
  function clearDemo() {
    setTraining([]);
    setTest([]);
    setPrior(undefined);
    setReport(null);
    setError('');
    setDemoActive(false);
  }
  function run() {
    computeWith(training, test, prior);
  }
  function download() {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2) + '\n'], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'eeg-channel-subset.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const held = Boolean(report?.test.length);
  const cell = (train: number, heldOut: number | undefined) => `${pct(train)}${heldOut === undefined ? '' : ` / ${pct(heldOut)}`}`;
  const methods = report ? Object.entries(report.methods as Record<string, { counts: MethodRow[] }>) : [];
  return (
    <section className="lab-panel space-y-4">
      <div>
        <h2 className="text-lg font-semibold">{tx('从记录选择通道子集')}</h2>
        <p className="mt-1.5 max-w-4xl text-sm leading-6 text-muted-foreground">
          {tx('载入由eeglayoutlab eeg-summary生成的协方差摘要。每个子集以自身的一个通道为参考记录，用训练摘要拟合的线性重建器重建全部共同通道的平均参考信号；误差为未解释方差比例。原始记录不需要上传，计算在浏览器内完成。')}
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2.5 rounded-xl border border-border/75 bg-muted/35 px-3.5 py-2.5 text-xs">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-muted-foreground">{tx('本地生成协方差摘要（原始脑电记录仅在本机读取，不上传）：')}</span>
          <code className="rounded-md border border-border bg-card px-2.5 py-1 font-mono text-[11px] font-medium text-foreground select-all">
            {CLI_SUMMARY_COMMAND}
          </code>
        </div>
        <Button type="button" size="sm" variant="outline" onClick={copyCli}>
          {copied ? <Check aria-hidden className="size-3.5" /> : <Copy aria-hidden className="size-3.5" />}
          {tx(copied ? '已复制' : '复制命令')}
        </Button>
      </div>
      <div className="grid grid-cols-1 gap-4 rounded-xl border border-border/70 bg-muted/30 p-4 md:grid-cols-2">
        <label className="lab-label">{tx('训练摘要')}<FilePicker accept="application/json,.json" multiple onChange={(event) => { void pick(setTraining)(event.target.files); }} /></label>
        <label className="lab-label">{tx('留出检验摘要（可选）')}<FilePicker accept="application/json,.json" multiple onChange={(event) => { void pick(setTest)(event.target.files); }} /></label>
        <label className="lab-label">{tx('数据先验（可选）')}<FilePicker accept="application/json,.json" onChange={(event) => {
          void readFiles(event.target.files).then((items) => { setPrior(items[0]); setReport(null); setDemoActive(false); }, (e) => setError(e.message));
        }} /></label>
        <label className="lab-label">{tx('子集通道数（逗号分隔）')}<input className="lab-select font-mono" value={counts} placeholder={DEFAULT_COUNTS.join(',')} onChange={(e) => setCounts(e.target.value)} /></label>
      </div>
      <div className="flex flex-wrap items-center gap-2.5">
        <Button onClick={run} disabled={busy || !training.length}>{tx(busy ? '计算中…' : '选择通道子集')}</Button>
        <Button type="button" variant="outline" onClick={loadDemo} disabled={busy}>
          <Sparkles aria-hidden className="size-3.5" />
          {tx('载入示例协方差摘要')}
        </Button>
        {demoActive && (
          <Button type="button" variant="ghost" size="sm" onClick={clearDemo} disabled={busy}>
            {tx('清空示例数据')}
          </Button>
        )}
      </div>
      {demoActive && (
        <output aria-live="polite" className="block rounded-xl border border-primary/25 bg-primary/[0.045] px-3.5 py-2.5 text-xs leading-5 text-ink-soft">
          {tx('当前显示合成示例摘要（32导10-05电极 · 4份训练摘要＋2份留出检验摘要，1–40 Hz），仅用于演示子集选择流程与误差曲线，不代表真实被试统计结论。')}
        </output>
      )}
      {error && <p className="rounded-lg border border-destructive/30 bg-danger-surface/65 px-3 py-2 text-sm text-destructive" role="alert">{tx(error)}</p>}
      {report && (
        <div className="space-y-4 border-t border-border/70 pt-4">
          <p className="text-xs leading-5 text-muted-foreground">
            {[`${report.universe.length}个共同通道`, `${report.training.length}份训练摘要`, ...(held ? [`${report.test.length}份留出摘要`] : []),
              `${report.band_hz[0]}–${report.band_hz[1]} Hz`].map((part) => tx(part)).join(' · ')}
            {report.training_skipped.length > 0 && tx(`；${report.training_skipped.length}份训练摘要缺少共同通道，未计入`)}
            {report.test_skipped.length > 0 && tx(`；${report.test_skipped.length}份留出摘要缺少共同通道，未计入`)}
            {report.channels_outside_prior.length > 0 && tx(`；${report.channels_outside_prior.length}个通道不在数据先验中，已排除`)}
          </p>
          <ChannelSubsetChart report={report} />
          <ChannelSubsetMap report={report} />
          <div className="lab-table-frame">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                  <th className="px-4 py-3">{tx('通道数')}</th>
                  {methods.map(([id]) => <th key={id} className="px-3 py-3">{tx(METHOD_LABELS[id] ?? id)}</th>)}
                  <th className="px-4 py-3">{tx('随机子集中位数')}</th>
                </tr>
              </thead>
              <tbody>
                {report.counts.map((count, k) => {
                  const random = report.random.counts[k];
                  return (
                    <tr key={count} className="border-b border-border/65 transition-colors hover:bg-primary/[0.03]">
                      <th className="px-4 py-2.5 font-mono font-semibold tabular-nums">{count}</th>
                      {methods.map(([id, method]) => <td key={id} className="px-3 py-2.5 font-mono tabular-nums">{cell(method.counts[k].train_error, method.counts[k].test_error?.mean)}</td>)}
                      <td className="px-4 py-2.5 font-mono tabular-nums">{cell(random.train_error.median, random.test_error_mean?.median)}
                        {random.test_error_mean && <span className="block text-xs text-muted-foreground">P10–P90 {pct(random.test_error_mean.p10)}–{pct(random.test_error_mean.p90)}</span>}</td>
                    </tr>
                  );
                })}
                {report.standard_10_20 && (
                  <tr className="border-t border-border/75 bg-muted/35">
                    <th className="px-4 py-2.5 font-medium">{tx(`10-20系统（${report.standard_10_20.count}个）`)}</th>
                    <td colSpan={methods.length + 1} className="px-3 py-2.5 font-mono tabular-nums">{cell(report.standard_10_20.train_error, report.standard_10_20.test_error?.mean)}
                      {report.standard_10_20.data_same_count && <span className="block font-sans text-xs text-muted-foreground">
                        {tx('同通道数按数据贪心选择')} {cell(report.standard_10_20.data_same_count.train_error, report.standard_10_20.data_same_count.test_error?.mean)}</span>}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <p className="text-xs leading-5 text-muted-foreground">
            {tx(held ? '每格为训练误差 / 留出摘要的平均误差；随机子集为同一通道数随机抽取的分布。' : '每格为训练误差；未载入留出摘要时，按数据贪心选择的误差偏乐观。')}
          </p>
          <details className="group/ch rounded-xl border border-border/70 bg-muted/25 px-3.5 py-2.5 text-sm">
            <summary className="flex cursor-pointer list-none items-center justify-between font-medium select-none [&::-webkit-details-marker]:hidden">
              <span>{tx('按数据贪心选择的通道')}</span>
              <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/ch:rotate-180" />
            </summary>
            <ul className="mt-2.5 space-y-1.5 font-mono text-xs leading-5">
              {(report.methods.data as { counts: MethodRow[] }).counts.map((row) => <li key={row.count}><span className="font-semibold text-primary">{row.count}</span>: {row.channels.join(', ')}</li>)}
            </ul>
          </details>
          <Button size="sm" variant="outline" onClick={download}>{tx('导出通道子集JSON')}</Button>
        </div>
      )}
    </section>
  );
}
