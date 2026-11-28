'use client';
import { useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { FilePicker } from '@/components/ui/file-picker';
import { Button } from '@/components/ui/button';
import { dataPriorLabel } from '../../contracts/scientific-options.mjs';
import {
  DATA_PRIOR_FILE_BYTES,
  dataPriorRows,
  readDataPriorFile,
  type DataPriorDetails,
} from '@/lib/data-prior';
import {
  SCENARIO_PRIOR_PRESETS,
  buildSyntheticFmriNifti,
  decompressGzipIfNeeded,
  exportScenarioDataPriorJson,
  niftiVolumeToDataPrior,
  parseFmriPeakTable,
  projectMniPeaksToDataPrior,
  type FmriPriorSummary,
} from '@/lib/fmri-prior';
import type { DataPrior } from '@/lib/local-compute';
import { cn } from '@/lib/utils';

const fixed = (value: number, digits = 2) => value.toFixed(digits);
const NIFTI_MAX_BYTES = 64 * 1024 * 1024;
const SAMPLE_MNI_PEAKS =
  '# label, x_mm, y_mm, z_mm, t_stat, fwhm_mm\nL_V1,-12,-88,2,6.4,18\nR_V1,14,-86,4,6.1,18\nR_SPL,24,-56,54,3.8,20';

function downloadDataUrl(filename: string, text: string, mime: string) {
  const anchor = document.createElement('a');
  anchor.href = `data:${mime};charset=utf-8,${encodeURIComponent(text)}`;
  anchor.download = filename;
  anchor.click();
}

/**
 * Scenario & functional brain prior selector: supports 1-click cognitive/BCI scenario presets,
 * individual/task fMRI activation maps (NIfTI-1 `.nii`/`.nii.gz` or MNI peak tables), and `eeg-data-prior/1` files.
 */
export function DataPriorPicker({
  value,
  source,
  onChange,
  disabled,
}: {
  value: DataPrior | null;
  source: string;
  disabled?: boolean;
  onChange: (value: DataPrior | null, source?: string) => void;
}) {
  const { tx } = useLanguage();
  const [tab, setTab] = useState<'preset' | 'fmri' | 'eeg_json'>('preset');
  const [details, setDetails] = useState<{ value: DataPrior; details: DataPriorDetails } | null>(
    null,
  );
  const [fmriInfo, setFmriInfo] = useState<{ value: DataPrior; summary: FmriPriorSummary } | null>(
    null,
  );
  const [statThreshold, setStatThreshold] = useState(2.0);
  const [peakText, setPeakText] = useState(SAMPLE_MNI_PEAKS);
  const [error, setError] = useState('');

  const shown =
    details && value && JSON.stringify(details.value) === JSON.stringify(value)
      ? details.details
      : null;
  const shownFmri =
    fmriInfo && value && JSON.stringify(fmriInfo.value) === JSON.stringify(value)
      ? fmriInfo.summary
      : null;

  async function loadJson(file: File | undefined) {
    setError('');
    if (!file) return;
    try {
      if (file.size > DATA_PRIOR_FILE_BYTES) throw new Error('数据先验文件超过20 MB');
      const read = readDataPriorFile(await file.text());
      setDetails(read);
      setFmriInfo(null);
      onChange(read.value, file.name);
    } catch (e) {
      setError(e instanceof Error ? e.message : '数据先验文件无法读取');
    }
  }

  async function loadNifti(file: File | undefined) {
    setError('');
    if (!file) return;
    try {
      if (file.size > NIFTI_MAX_BYTES) throw new Error('fMRI统计图文件超过64 MB');
      const buffer = await decompressGzipIfNeeded(await file.arrayBuffer());
      const mapped = niftiVolumeToDataPrior(buffer, {
        statThreshold,
        title: file.name,
      });
      setDetails(null);
      setFmriInfo({ value: mapped.prior, summary: mapped.summary });
      onChange(mapped.prior, `fMRI: ${file.name}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'fMRI图像解析失败');
    }
  }

  function applyPeakTable() {
    setError('');
    try {
      const peaks = parseFmriPeakTable(peakText);
      const mapped = projectMniPeaksToDataPrior(peaks);
      setDetails(null);
      setFmriInfo({ value: mapped.prior, summary: mapped.summary });
      onChange(mapped.prior, `fMRI MNI (${peaks.length})`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'MNI峰值解析失败');
    }
  }

  function loadSyntheticFmriDemo() {
    setError('');
    try {
      const peaks = parseFmriPeakTable(SAMPLE_MNI_PEAKS);
      const buffer = buildSyntheticFmriNifti(peaks);
      const mapped = niftiVolumeToDataPrior(buffer, {
        statThreshold,
        title: 'demo_visual_parietal_tstat.nii',
      });
      setDetails(null);
      setFmriInfo({ value: mapped.prior, summary: mapped.summary });
      onChange(mapped.prior, 'fMRI: demo_visual_parietal_tstat.nii');
    } catch (e) {
      setError(e instanceof Error ? e.message : '合成fMRI示例加载失败');
    }
  }

  const maxGain = value ? Math.max(1, ...value.region_gain) : 1;

  return (
    <div className="col-span-2 space-y-2.5 text-sm" data-scenario-prior-picker>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold text-foreground">
          {tx('实验场景脑源先验（范式预设 / fMRI激活图 / EEG协方差）')}
        </span>
        <div
          className="inline-flex rounded-lg border border-border bg-secondary/60 p-0.5 text-xs"
          role="tablist"
          aria-label={tx('脑源先验来源类型')}
        >
          {(
            [
              ['preset', '场景预设'],
              ['fmri', 'fMRI 图像/峰值'],
              ['eeg_json', 'EEG 先验文件'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              disabled={disabled}
              onClick={() => {
                setTab(id);
                setError('');
              }}
              className={cn(
                'rounded-md px-2.5 py-1 font-medium transition-colors',
                tab === id
                  ? 'bg-card text-foreground shadow-2xs'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {tx(label)}
            </button>
          ))}
        </div>
      </div>

      {tab === 'preset' && (
        <div className="space-y-2 rounded-xl border border-border/75 bg-card/70 p-3">
          <p className="text-xs leading-5 text-muted-foreground">
            {tx(
              '针对具体实验范式聚焦目标功能脑区权重，使算法将有限电极优先排布在目标脑源信噪比最高的位置（不选则默认全皮层按面积均匀加权）。',
            )}
          </p>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {SCENARIO_PRIOR_PRESETS.map((preset) => {
              const active =
                !!value && JSON.stringify(value) === JSON.stringify(preset.prior);
              return (
                <button
                  key={preset.id}
                  type="button"
                  disabled={disabled}
                  aria-pressed={active}
                  onClick={() => {
                    setError('');
                    setDetails(null);
                    setFmriInfo(null);
                    onChange(active ? null : preset.prior, active ? '' : preset.id);
                  }}
                  className={cn(
                    'rounded-lg border p-2.5 text-left transition-colors',
                    active
                      ? 'border-primary bg-primary/10 text-foreground'
                      : 'border-border/80 bg-background/70 hover:border-foreground/30',
                  )}
                >
                  <span className="block text-xs font-semibold text-foreground">
                    {tx(preset.label)}
                  </span>
                  <span className="mt-0.5 block text-[11px] leading-4.5 text-muted-foreground">
                    {tx(preset.description)}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {tab === 'fmri' && (
        <div className="space-y-3 rounded-xl border border-border/75 bg-card/70 p-3">
          <p className="text-xs leading-5 text-muted-foreground">
            {tx(
              '导入个体或组水平任务态 fMRI 三维统计图（NIfTI-1 .nii / .nii.gz，MNI152 空间）或激活峰值表，自动投影至皮层 DK40 脑区源权重以定制该受试者/任务的电极布局。',
            )}
          </p>
          <div className="grid gap-2.5 sm:grid-cols-[1fr_auto]">
            <label className="lab-label text-xs">
              {tx('载入 NIfTI 三维统计图（.nii / .nii.gz）')}
              <FilePicker
                accept=".nii,.gz,application/gzip,application/octet-stream"
                disabled={disabled}
                buttonLabel="选择 fMRI NIfTI 文件"
                onChange={(event) => {
                  void loadNifti(event.target.files?.[0]);
                  event.target.value = '';
                }}
              />
            </label>
            <label className="lab-label text-xs">
              <span>
                {tx('统计量阈值 |t| ≥')}{' '}
                <span className="font-mono tabular-nums">{statThreshold.toFixed(1)}</span>
              </span>
              <input
                type="number"
                aria-label={tx('统计量阈值 |t| ≥')}
                min={0.1}
                max={15}
                step={0.5}
                disabled={disabled}
                value={statThreshold}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  if (Number.isFinite(n) && n >= 0.1 && n <= 15) setStatThreshold(n);
                }}
                className="lab-input mt-1 h-9 w-28 font-mono text-xs tabular-nums"
              />
            </label>
          </div>
          <div className="space-y-1.5 border-t border-border/60 pt-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-medium text-foreground">
                {tx('或输入 MNI152 激活峰值簇（x, y, z, t_stat, fwhm_mm）')}
              </span>
              <Button
                type="button"
                size="xs"
                variant="outline"
                disabled={disabled}
                onClick={loadSyntheticFmriDemo}
              >
                {tx('一键载入合成 NIfTI 体素示例')}
              </Button>
            </div>
            <textarea
              rows={3}
              disabled={disabled}
              value={peakText}
              aria-label={tx('MNI激活峰值坐标列表')}
              onChange={(e) => setPeakText(e.target.value)}
              className="lab-input font-mono text-xs leading-5"
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={disabled}
              onClick={applyPeakTable}
            >
              {tx('将 MNI 峰值映射为脑源先验')}
            </Button>
          </div>
        </div>
      )}

      {tab === 'eeg_json' && (
        <div className="space-y-1.5 rounded-xl border border-border/75 bg-card/70 p-3">
          <label className="lab-label text-xs">
            {tx('选择 eeg-data-prior/1 文件')}
            <FilePicker
              accept="application/json,.json"
              disabled={disabled}
              buttonLabel="选择数据先验文件"
              onChange={(event) => {
                void loadJson(event.target.files?.[0]);
                event.target.value = '';
              }}
            />
          </label>
          <p className="text-xs leading-5 text-muted-foreground">
            {tx(
              '由真实 EEG 记录协方差拟合的区域源功率与空间相关噪声结构（eeglayoutlab prior），1 表示与均匀面积先验相同。',
            )}
          </p>
        </div>
      )}

      {error && (
        <p className="text-xs text-destructive" role="alert">
          {tx(error)}
        </p>
      )}

      {value && (
        <div className="rounded-xl border border-primary/25 bg-primary/[0.03] p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-semibold text-foreground">
              {tx(dataPriorLabel(value))}
              {source && (() => {
                // A preset is stored by its id; show its name instead.
                const preset = SCENARIO_PRIOR_PRESETS.find((p) => p.id === source);
                return (
                  <span className={cn('ml-2 font-normal text-muted-foreground', !preset && 'font-mono')}>
                    {preset ? tx(preset.label) : source}
                  </span>
                );
              })()}
            </span>
            <div className="flex flex-wrap gap-1.5">
              <Button
                type="button"
                variant="outline"
                size="xs"
                onClick={() =>
                  downloadDataUrl(
                    'eeg-scenario-data-prior.json',
                    exportScenarioDataPriorJson(value, source || 'scenario'),
                    'application/json',
                  )
                }
              >
                {tx('导出先验JSON')}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="xs"
                disabled={disabled}
                onClick={() => onChange(null)}
              >
                {tx('恢复均匀先验')}
              </Button>
            </div>
          </div>
          {shownFmri && (
            <p className="mt-1.5 text-xs text-muted-foreground">
              {tx(
                `已激活 ${shownFmri.activeSources}/${shownFmri.totalSources} 个皮层锚点源（阈值 ≥ ${shownFmri.threshold}）`,
              )}
              {shownFmri.dimensions &&
                ` · ${shownFmri.dimensions[0]}×${shownFmri.dimensions[1]}×${shownFmri.dimensions[2]}`}
            </p>
          )}
          <table className="mt-2 w-full text-left text-xs">
            <thead>
              <tr>
                <th className="py-1 font-medium text-muted-foreground">{tx('脑区')}</th>
                <th className="py-1 font-medium text-muted-foreground">
                  {tx('源功率增益')}
                </th>
              </tr>
            </thead>
            <tbody>
              {dataPriorRows(value).map((row) => (
                <tr key={row.label} className="border-t border-border/60">
                  <td className="py-1 pr-3">{tx(row.label)}</td>
                  <td className="py-1">
                    {fixed(row.gain)}×
                    <span
                      aria-hidden="true"
                      className="mt-1 block h-1.5 w-full overflow-hidden rounded-full bg-secondary"
                    >
                      <span
                        className="block h-full rounded-full bg-primary"
                        style={{
                          width: `${Math.max(3, Math.min(100, (row.gain / maxGain) * 100))}%`,
                        }}
                      />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown && (
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {tx(
                `由${shown.summaries}份摘要、${shown.channels}个通道、${shown.band_hz[0]}–${shown.band_hz[1]} Hz拟合；相对残差${fixed(shown.relative_residual, 3)}（面积先验${fixed(shown.uniform_relative_residual, 3)}）。`,
              )}
              {tx(
                shown.held_out
                  ? `留一检验：${shown.held_out.better}/${shown.held_out.summaries}份留出摘要的残差低于面积先验，残差中位数${fixed(shown.held_out.prior_median, 3)}（面积先验${fixed(shown.held_out.uniform_median, 3)}）；收缩系数${shown.shrinkage}。`
                  : '摘要少于3份，未做留一检验，增益未收缩。',
              )}
              {shown.excluded > 0 && tx(`${shown.excluded}份摘要缺少共同通道，未参与拟合。`)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
