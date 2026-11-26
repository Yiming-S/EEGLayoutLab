'use client';
/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useState } from 'react';
import { Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useLanguage } from '@/components/language-provider';
import { SaveToProject } from '@/features/projects/project-context';
import {
  CONDITION_LABELS,
  sourcePass,
  type SourceCondition,
  type SourceResult,
} from '@/lib/source-reception';
import { reconstructionNotice } from '@/lib/source-result-reading';
import { ReceptionWaveformsSection } from './reception-waveforms-section';
import { recordedForwardOrigin } from './result-provenance';
import { fixed, pct } from './target-channel-topography';

const conditions = Object.keys(CONDITION_LABELS) as SourceCondition[];

export function ExperimentResult({
  result,
  label,
  ar,
  setAR,
  cached,
  onReduceArtifacts,
  receiptId,
  sourceResultKey,
  archived = false,
}: {
  result: SourceResult;
  label: string;
  ar: number;
  setAR: (ar: number) => void;
  cached: boolean;
  onReduceArtifacts?: () => void;
  receiptId?: string;
  sourceResultKey?: string;
  archived?: boolean;
}) {
  const { tx } = useLanguage();
  const [condition, setCondition] = useState<SourceCondition>('mixed'),
    [channels, setChannels] = useState([0, 0]),
    [targetChannel, setTargetChannel] = useState(0);

  const score = result.conditions.find((s) => s.condition === condition)!,
    status = sourcePass(score.field_retention, ar);
  const notice = reconstructionNotice(score);

  const download = () => {
    const u = URL.createObjectURL(
      new Blob([JSON.stringify(result)], { type: 'application/json' }),
    );
    const a = document.createElement('a');
    a.href = u;
    a.download = `source-reception-${result.request.record_id.slice(0, 8)}-${result.request.seed}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(u), 1000);
  };

  return (
    <div className="space-y-5 py-5">
      <section className="lab-panel">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">{label}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {tx(archived ? '项目保存的结果' : cached ? '已有结果' : '本次计算')} ·{' '}
              {tx(result.source.patch_count)}
              {tx('个已选皮层源 · 原布局坐标未改变')}
              {result.request.mode === 'cross_region' && (
                <> · {tx('跨区域多源')}</>
              )}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {tx(recordedForwardOrigin(result.provenance))}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {!archived && receiptId && (
              <SaveToProject
                kind="source"
                recordId={sourceResultKey}
                receiptId={receiptId}
              />
            )}
            <Button variant="outline" onClick={download}>
              <Download className="size-4" />
              {tx('导出本场景JSON')}
            </Button>
          </div>
        </div>
        <fieldset
          className="mt-4 flex flex-wrap gap-2"
          aria-label={tx('显示干扰条件')}
        >
          {tx(
            conditions.map((c) => (
              <Button
                key={c}
                variant={condition === c ? 'default' : 'outline'}
                aria-pressed={condition === c}
                onClick={() => setCondition(c)}
              >
                {tx(CONDITION_LABELS[c])}
              </Button>
            )),
          )}
        </fieldset>
        <p className="mt-3 text-sm text-muted-foreground">
          {tx(
            '切换条件查看已计算结果。各条件使用同尺度电极噪声；强度倍数控制模拟心眼伪迹的幅度。',
          )}
        </p>
      </section>
      {notice && (
        <section
          aria-live="polite"
          className="rounded-xl border border-warning/30 bg-warning-surface p-4 text-sm text-warning"
        >
          <h2 className="font-semibold">{tx(notice.title)}</h2>
          <p className="mt-2 leading-6">{tx(notice.explanation)}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {condition !== 'clean' && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCondition('clean')}
              >
                {tx('查看无心眼干扰条件')}
              </Button>
            )}
            {condition !== 'clean' && onReduceArtifacts && (
              <Button variant="outline" size="sm" onClick={onReduceArtifacts}>
                {tx('降低干扰幅度')}
              </Button>
            )}
          </div>
        </section>
      )}
      <section className="lab-panel grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div>
          <h2 className="text-lg font-semibold">
            {tx('信号重建结果 · ')}
            {tx(CONDITION_LABELS[condition])}
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {tx(
              '两套布局均以标准64位置的干净脑信号为重建真值。重建解释率＝1−归一化均方误差，按原值显示，含负值。',
            )}
          </p>
          <table className="mt-4 w-full text-left text-sm">
            <thead>
              <tr className="border-b">
                <th className="py-2">{tx('指标')}</th>
                <th>{tx('标准64')}</th>
                <th>{tx('自定义64')}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th className="py-3 font-medium">{tx('重建解释率')}</th>
                <td>{tx(pct(score.baseline.explained_energy))}</td>
                <td>{tx(pct(score.candidate.explained_energy))}</td>
              </tr>
              <tr>
                <th className="pb-3 font-medium">{tx('归一化均方误差')}</th>
                <td>{tx(score.baseline.nmse.toFixed(4))}</td>
                <td>{tx(score.candidate.nmse.toFixed(4))}</td>
              </tr>
              <tr>
                <th className="font-medium">
                  {tx('模拟脑信号／模拟心眼伪迹功率比')}
                </th>
                <td>
                  {tx(fixed(score.baseline.brain_artifact_ratio_db, ' dB'))}
                </td>
                <td>
                  {tx(fixed(score.candidate.brain_artifact_ratio_db, ' dB'))}
                </td>
              </tr>
              <tr>
                <th className="pt-3 font-medium">
                  {tx('当前脑源／电极噪声功率比')}
                </th>
                <td className="pt-3">
                  {tx(fixed(score.baseline.brain_noise_ratio_db, ' dB'))}
                </td>
                <td className="pt-3">
                  {tx(fixed(score.candidate.brain_noise_ratio_db, ' dB'))}
                </td>
              </tr>
            </tbody>
          </table>
          <p className="mt-4 text-sm leading-6 text-muted-foreground">
            {tx('干净脑最大双极幅度的时域RMS比（自定义／标准64）：')}
            {tx(pct(result.metrics.pure_brain_amplitude_ratio))}
            {tx('。这是当前源的传递幅度比，由纯脑信号计算。')}
          </p>
        </div>
        <div className="rounded-lg bg-muted/40 p-4">
          <label className="lab-label">
            {tx('接受阈值 AR（仅判断本场景重建） · ')}
            {tx(ar)}%
            <input
              className="mt-3 w-full accent-primary"
              type="range"
              min={10}
              max={100}
              value={ar}
              onChange={(e) => setAR(Number(e.target.value))}
            />
          </label>
          <p className="mt-4 text-sm font-medium">
            {tx('本场景信号重建保留率')}
          </p>
          <p className="mt-1 text-2xl font-semibold">
            {tx(pct(score.field_retention))}
          </p>
          <p className="mt-2 text-sm font-medium">
            {tx(
              status === 'pass'
                ? '本场景信号重建达到AR'
                : status === 'fail'
                  ? '本场景信号重建未达到AR'
                  : '基准重建解释率非正或过小，相对指标无法计算，无法判断是否达到AR',
            )}
          </p>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {tx(
              '这是自定义64与标准64的重建解释率之比。绝对重建质量见左侧重建解释率与均方误差；AR用于本场景的相对重建判定。',
            )}
          </p>
        </div>
      </section>
      <ReceptionWaveformsSection
        result={result}
        condition={condition}
        ar={ar}
        channels={channels}
        setChannels={setChannels}
        targetChannel={targetChannel}
        setTargetChannel={setTargetChannel}
      />
      <details className="lab-panel">
        <summary className="cursor-pointer font-semibold">
          {tx('模型、源坐标与完整实验说明')}
        </summary>
        <div className="mt-4 space-y-3 text-sm leading-7">
          <p>
            {tx(
              '传递方程：参考处理后的 Hs + A心电c + A眼电e + 电极噪声。H直接采用原FEM传递矩阵，其空间幅度变化包含头模的体积传导效应。ECG/EOG空间场为预设干扰条件；真实部位的抗干扰性能需实测验证。',
            )}
          </p>
          <p>
            {tx(
              '本页评价所选脑源的接收波形、重建与干扰响应。源区由固定坐标锚点附近的皮层点构成，结果适用于当前头模与源场景。',
            )}
          </p>
          <p>
            {tx('方法背景参考：')}
            <a
              className="text-primary underline"
              href="https://mne.tools/stable/auto_examples/simulation/source_simulator.html"
              target="_blank"
              rel="noreferrer"
            >
              {tx('源波形与前向投影方法')}
            </a>
            ；
            <a
              className="text-primary underline"
              href="https://pubmed.ncbi.nlm.nih.gov/23087632/"
              target="_blank"
              rel="noreferrer"
            >
              {tx('眼源伪迹的位置与参考依赖')}
            </a>
            {tx(
              '。本页数值由已有FEM矩阵、自定义源波形与假设伪迹空间场计算生成。',
            )}
          </p>
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">
            {JSON.stringify(
              {
                protocol: result.protocol,
                source: result.source,
                provenance: result.provenance,
              },
              null,
              2,
            )}
          </pre>
        </div>
      </details>
    </div>
  );
}
