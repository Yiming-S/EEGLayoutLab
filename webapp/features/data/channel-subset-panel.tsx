'use client';
import { useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { FilePicker } from '@/components/ui/file-picker';
import { Button } from '@/components/ui/button';
import { DEFAULT_COUNTS, channelSubsets, type Stats } from '@/lib/channel-subset';
import { ChannelSubsetChart } from './channel-subset-chart';

type Report = ReturnType<typeof channelSubsets>;
type MethodRow = { count: number; channels: string[]; train_error: number; test_error: Stats | null };
const FILE_BYTES = 20 * 1024 * 1024, MAX_FILES = 2000;
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
  const [report, setReport] = useState<Report | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const pick = (set: (value: unknown[]) => void) => async (list: FileList | null) => {
    setError(''); setReport(null);
    try { set(await readFiles(list)); } catch (e) { setError(e instanceof Error ? e.message : '文件无法读取'); }
  };
  function run() {
    setBusy(true); setError('');
    // Yield once so the busy state renders; the calculation takes well under a second for 128 channels.
    setTimeout(() => {
      try {
        setReport(channelSubsets({ training, test, prior, counts: counts.trim() ? counts.split(',').map((v) => Number(v.trim())) : undefined }));
      } catch (e) {
        setReport(null); setError(e instanceof Error ? e.message : '计算失败');
      } finally { setBusy(false); }
    }, 0);
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
    <section className="lab-panel">
      <h2 className="text-lg font-semibold">{tx('从记录选择通道子集')}</h2>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        {tx('载入由eeglayoutlab eeg-summary生成的协方差摘要。每个子集以自身的一个通道为参考记录，用训练摘要拟合的线性重建器重建全部共同通道的平均参考信号；误差为未解释方差比例。原始记录不需要上传，计算在浏览器内完成。')}
      </p>
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <label className="lab-label">{tx('训练摘要')}<FilePicker accept="application/json,.json" multiple onChange={(event) => { void pick(setTraining)(event.target.files); }} /></label>
        <label className="lab-label">{tx('留出检验摘要（可选）')}<FilePicker accept="application/json,.json" multiple onChange={(event) => { void pick(setTest)(event.target.files); }} /></label>
        <label className="lab-label">{tx('数据先验（可选）')}<FilePicker accept="application/json,.json" onChange={(event) => {
          void readFiles(event.target.files).then((items) => { setPrior(items[0]); setReport(null); }, (e) => setError(e.message));
        }} /></label>
        <label className="lab-label">{tx('子集通道数（逗号分隔）')}<input className="lab-select mt-2" value={counts} placeholder={DEFAULT_COUNTS.join(',')} onChange={(e) => setCounts(e.target.value)} /></label>
      </div>
      <Button className="mt-4" onClick={run} disabled={busy || !training.length}>{tx(busy ? '计算中…' : '选择通道子集')}</Button>
      {error && <p className="mt-2 text-sm text-destructive" role="alert">{tx(error)}</p>}
      {report && (
        <div className="mt-5 overflow-x-auto">
          <p className="text-xs leading-5 text-muted-foreground">
            {[`${report.universe.length}个共同通道`, `${report.training.length}份训练摘要`, ...(held ? [`${report.test.length}份留出摘要`] : []),
              `${report.band_hz[0]}–${report.band_hz[1]} Hz`].map((part) => tx(part)).join(' · ')}
            {report.training_skipped.length > 0 && tx(`；${report.training_skipped.length}份训练摘要缺少共同通道，未计入`)}
            {report.test_skipped.length > 0 && tx(`；${report.test_skipped.length}份留出摘要缺少共同通道，未计入`)}
            {report.channels_outside_prior.length > 0 && tx(`；${report.channels_outside_prior.length}个通道不在数据先验中，已排除`)}
          </p>
          <ChannelSubsetChart report={report} />
          <table className="mt-2 w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr>
                <th className="py-2">{tx('通道数')}</th>
                {methods.map(([id]) => <th key={id}>{tx(METHOD_LABELS[id] ?? id)}</th>)}
                <th>{tx('随机子集中位数')}</th>
              </tr>
            </thead>
            <tbody>
              {report.counts.map((count, k) => {
                const random = report.random.counts[k];
                return (
                  <tr key={count} className="border-t">
                    <th className="py-2 font-normal">{count}</th>
                    {methods.map(([id, method]) => <td key={id}>{cell(method.counts[k].train_error, method.counts[k].test_error?.mean)}</td>)}
                    <td>{cell(random.train_error.median, random.test_error_mean?.median)}
                      {random.test_error_mean && <span className="block text-xs text-muted-foreground">P10–P90 {pct(random.test_error_mean.p10)}–{pct(random.test_error_mean.p90)}</span>}</td>
                  </tr>
                );
              })}
              {report.standard_10_20 && (
                <tr className="border-t">
                  <th className="py-2 font-normal">{tx(`10-20系统（${report.standard_10_20.count}个）`)}</th>
                  <td colSpan={methods.length + 1}>{cell(report.standard_10_20.train_error, report.standard_10_20.test_error?.mean)}
                    {report.standard_10_20.data_same_count && <span className="block text-xs text-muted-foreground">
                      {tx('同通道数按数据贪心选择')} {cell(report.standard_10_20.data_same_count.train_error, report.standard_10_20.data_same_count.test_error?.mean)}</span>}</td>
                </tr>
              )}
            </tbody>
          </table>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            {tx(held ? '每格为训练误差 / 留出摘要的平均误差；随机子集为同一通道数随机抽取的分布。' : '每格为训练误差；未载入留出摘要时，按数据贪心选择的误差偏乐观。')}
          </p>
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer font-medium">{tx('按数据贪心选择的通道')}</summary>
            <ul className="mt-2 space-y-1 text-xs leading-5">
              {(report.methods.data as { counts: MethodRow[] }).counts.map((row) => <li key={row.count}><span className="font-medium">{row.count}</span>: {row.channels.join(', ')}</li>)}
            </ul>
          </details>
          <Button className="mt-3" size="sm" variant="outline" onClick={download}>{tx('导出通道子集JSON')}</Button>
        </div>
      )}
    </section>
  );
}
