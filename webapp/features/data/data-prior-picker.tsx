'use client';
import { useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { FilePicker } from '@/components/ui/file-picker';
import { Button } from '@/components/ui/button';
import { dataPriorLabel } from '../../contracts/scientific-options.mjs';
import { DATA_PRIOR_FILE_BYTES, dataPriorRows, readDataPriorFile, type DataPriorDetails } from '@/lib/data-prior';
import type { DataPrior } from '@/lib/local-compute';

const fixed = (value: number, digits = 2) => value.toFixed(digits);

/** Loads an eeg-data-prior/1 file (made with `eeglayoutlab prior`) and shows what it changes. */
export function DataPriorPicker({ value, source, onChange, disabled }: {
  value: DataPrior | null; source: string; disabled?: boolean;
  onChange: (value: DataPrior | null, source?: string) => void;
}) {
  const { tx } = useLanguage();
  const [details, setDetails] = useState<{ value: DataPrior; details: DataPriorDetails } | null>(null);
  const [error, setError] = useState('');
  // Fit details belong to the file loaded on this page; a restored request shows the request alone.
  const shown = details && value && JSON.stringify(details.value) === JSON.stringify(value) ? details.details : null;
  async function load(file: File | undefined) {
    setError('');
    if (!file) return;
    try {
      if (file.size > DATA_PRIOR_FILE_BYTES) throw new Error('数据先验文件超过20 MB');
      const read = readDataPriorFile(await file.text());
      setDetails(read);
      onChange(read.value, file.name);
    } catch (e) {
      setError(e instanceof Error ? e.message : '数据先验文件无法读取');
    }
  }
  return (
    <div className="col-span-2 text-sm">
      <label className="lab-label">
        {tx('数据先验（可选）')}
        <FilePicker accept="application/json,.json" disabled={disabled} buttonLabel="选择数据先验文件"
          onChange={(event) => { void load(event.target.files?.[0]); event.target.value = ''; }} />
      </label>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">
        {tx('由真实EEG记录拟合的区域源功率与噪声结构（eeglayoutlab prior）。载入后替换噪声模型；增益相对面积先验，1表示不变。结果只适用于与这些记录相似的数据。')}
      </p>
      {error && <p className="mt-1 text-xs text-destructive" role="alert">{tx(error)}</p>}
      {value && (
        <div className="mt-2 rounded-md border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">{tx(dataPriorLabel(value))}{source && <span className="ml-2 font-normal text-muted-foreground">{source}</span>}</span>
            <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => onChange(null)}>{tx('移除数据先验')}</Button>
          </div>
          <table className="mt-2 w-full text-left text-xs">
            <thead><tr><th className="py-1 font-medium">{tx('脑区')}</th><th className="font-medium">{tx('源功率增益')}</th></tr></thead>
            <tbody>
              {dataPriorRows(value).map((row) => (
                <tr key={row.label} className="border-t"><td className="py-1">{tx(row.label)}</td><td>{fixed(row.gain)}</td></tr>
              ))}
            </tbody>
          </table>
          {shown && (
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {tx(`由${shown.summaries}份摘要、${shown.channels}个通道、${shown.band_hz[0]}–${shown.band_hz[1]} Hz拟合；相对残差${fixed(shown.relative_residual, 3)}（面积先验${fixed(shown.uniform_relative_residual, 3)}）。`)}
              {tx(shown.held_out
                ? `留一检验：${shown.held_out.better}/${shown.held_out.summaries}份留出摘要的残差低于面积先验，残差中位数${fixed(shown.held_out.prior_median, 3)}（面积先验${fixed(shown.held_out.uniform_median, 3)}）；收缩系数${shown.shrinkage}。`
                : '摘要少于3份，未做留一检验，增益未收缩。')}
              {shown.excluded > 0 && tx(`${shown.excluded}份摘要缺少共同通道，未参与拟合。`)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
