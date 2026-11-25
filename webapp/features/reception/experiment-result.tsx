'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { useMemo, useState } from 'react';
import { Play, Pause, Download } from 'lucide-react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Button } from '@/components/ui/button';

import {
  combinedTrace,
  CONDITION_LABELS,
  sourcePass,
  type SourceCondition,
  type SourceResult,
} from '@/lib/source-reception';
import biosemi from '@/lib/biosemi64-reference.json';
import { FIELD_LAYERS, fieldFrames, type FieldLayer } from '@/lib/source-field';
import { sourceRegion } from '@/lib/source-regions';
import { ReceiverComparison } from './receiver-comparison';
import { useResultPlayback } from './use-result-playback';
import {
  sourcePresentation,
  receiverTraces,
  reconstructionTrace,
  sharedAmplitude,
  strengthCurve,
  sourceTraceAt,
  layoutPresentation,
} from './result-view-model';
import { reconstructionNotice } from '@/lib/source-result-reading';
import { SaveToProject } from '@/features/projects/project-context';
import { recordedForwardOrigin } from './result-provenance';

const pct = (n: number | null | undefined) =>
  n == null ? '指标无法计算' : `${(n * 100).toFixed(2)}%`;
const fixed = (n: number | null | undefined, unit = '') =>
  n == null ? '无干扰' : `${n.toFixed(2)}${unit}`;
const conditions = Object.keys(CONDITION_LABELS) as SourceCondition[];

const BIOSEMI_PROJECTED = (() => {
  const projected = biosemi.channels.map((ch) => {
    const [x, y, z] = ch.xyz_m,
      r = Math.atan2(Math.hypot(x, y), z) / (Math.PI / 2),
      azimuth = Math.atan2(y, x);
    return { name: ch.name, x: r * Math.cos(azimuth), y: r * Math.sin(azimuth), r };
  });
  const maxR = Math.max(1, ...projected.map((p) => p.r)),
    scale = Math.min(92, 108 / maxR);
  return {
    headRadius: scale,
    points: projected.map((p) => ({
      name: p.name,
      cx: 130 + p.x * scale,
      cy: 136 - p.y * scale,
    })),
  };
})();

const mixChannel = (a: number, b: number, t: number) => Math.round(a + (b - a) * t);
const rgbCss = (rgb: [number, number, number]) => `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
function r2FillColor(r2: number | null): string {
  if (r2 == null || !Number.isFinite(r2)) return '#cbd5e1';
  const clamped = Math.max(0, Math.min(1, r2));
  const low: [number, number, number] = [217, 119, 6],
    mid: [number, number, number] = [226, 232, 240],
    high: [number, number, number] = [18, 138, 128];
  if (clamped < 0.5) {
    const t = clamped / 0.5;
    return rgbCss([
      mixChannel(low[0], mid[0], t),
      mixChannel(low[1], mid[1], t),
      mixChannel(low[2], mid[2], t),
    ]);
  }
  const t = (clamped - 0.5) / 0.5;
  return rgbCss([
    mixChannel(mid[0], high[0], t),
    mixChannel(mid[1], high[1], t),
    mixChannel(mid[2], high[2], t),
  ]);
}

function deltaR2FillColor(delta: number | null): string {
  if (delta == null || !Number.isFinite(delta)) return '#cbd5e1';
  const clamped = Math.max(-0.3, Math.min(0.3, delta));
  const neg: [number, number, number] = [192, 71, 104],
    zero: [number, number, number] = [241, 245, 249],
    pos: [number, number, number] = [18, 138, 128];
  if (clamped < 0) {
    const t = (clamped + 0.3) / 0.3;
    return rgbCss([
      mixChannel(neg[0], zero[0], t),
      mixChannel(neg[1], zero[1], t),
      mixChannel(neg[2], zero[2], t),
    ]);
  }
  const t = clamped / 0.3;
  return rgbCss([
    mixChannel(zero[0], pos[0], t),
    mixChannel(zero[1], pos[1], t),
    mixChannel(zero[2], pos[2], t),
  ]);
}

function computeChannelR2(
  result: SourceResult,
  condition: SourceCondition,
): { cand: number | null; base: number | null; delta: number | null }[] {
  return Array.from({ length: 64 }, (_, channel) => {
    const truth = result.waveforms.baseline.brain_uv[channel];
    let energy = 0;
    for (let t = 0; t < truth.length; t++) energy += truth[t] * truth[t];
    if (!Number.isFinite(energy) || energy <= 1e-18) {
      return { cand: null, base: null, delta: null };
    }
    const baseTrace = combinedTrace(result.waveforms.baseline, channel, condition, true),
      candTrace = combinedTrace(result.waveforms.candidate, channel, condition, true);
    let baseErr = 0,
      candErr = 0;
    for (let t = 0; t < truth.length; t++) {
      const db = baseTrace[t].mixed - truth[t],
        dc = candTrace[t].mixed - truth[t];
      baseErr += db * db;
      candErr += dc * dc;
    }
    const base = 1 - baseErr / energy,
      cand = 1 - candErr / energy;
    return {
      cand: Number.isFinite(cand) ? cand : null,
      base: Number.isFinite(base) ? base : null,
      delta: Number.isFinite(cand) && Number.isFinite(base) ? cand - base : null,
    };
  });
}

function TargetChannelTopography({
  result,
  condition,
  targetChannel,
  onSelectChannel,
}: {
  result: SourceResult;
  condition: SourceCondition;
  targetChannel: number;
  onSelectChannel: (channel: number) => void;
}) {
  const { tx } = useLanguage();
  const [mapMode, setMapMode] = useState<'candidate' | 'delta'>('candidate');
  const channelScores = useMemo(
    () => computeChannelR2(result, condition),
    [result, condition],
  );
  const current = channelScores[targetChannel],
    r = BIOSEMI_PROJECTED.headRadius,
    cx = 130,
    cy = 136;

  return (
    <div
      className="flex flex-col justify-between rounded-xl border bg-muted/20 p-3.5"
      data-target-channel-topography
    >
      <div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">
            {tx('64导目标通道重建拓扑（点击选点）')}
          </h3>
          <div className="inline-flex rounded-md border bg-background p-0.5 text-[11px]">
            <button
              type="button"
              aria-pressed={mapMode === 'candidate'}
              onClick={() => setMapMode('candidate')}
              className={`rounded px-2 py-0.5 font-medium transition-colors ${
                mapMode === 'candidate'
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {tx('自定义64解释率')}
            </button>
            <button
              type="button"
              aria-pressed={mapMode === 'delta'}
              onClick={() => setMapMode('delta')}
              className={`rounded px-2 py-0.5 font-medium transition-colors ${
                mapMode === 'delta'
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {tx('相对标准64差值')}
            </button>
          </div>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {tx('预览波形逐通道解释率（1−NMSE）；点击头表电极切换右侧重建波形。')}
        </p>
        <svg
          viewBox="0 0 260 264"
          className="mx-auto mt-2 w-full max-w-[260px]"
          aria-label={tx('64导目标通道重建拓扑（点击选点）')}
        >
          <title>{tx('64导目标通道重建拓扑（点击选点）')}</title>
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            className="stroke-border"
            strokeWidth={1.5}
          />
          <path
            d={`M ${(cx - r * 0.1).toFixed(1)} ${(cy - r * 0.99).toFixed(1)} L ${cx} ${(cy - r * 1.1).toFixed(1)} L ${(cx + r * 0.1).toFixed(1)} ${(cy - r * 0.99).toFixed(1)}`}
            fill="none"
            className="stroke-border"
            strokeWidth={1.5}
            strokeLinejoin="round"
          />
          {[-1, 1].map((side) => (
            <path
              key={side}
              d={`M ${(cx + side * r).toFixed(1)} ${(cy - r * 0.12).toFixed(1)} q ${(side * r * 0.08).toFixed(1)} ${(r * 0.02).toFixed(1)} ${(side * r * 0.08).toFixed(1)} ${(r * 0.12).toFixed(1)} t ${(-side * r * 0.08).toFixed(1)} ${(r * 0.12).toFixed(1)}`}
              fill="none"
              className="stroke-border"
              strokeWidth={1.5}
            />
          ))}
          {BIOSEMI_PROJECTED.points.map((pt, index) => {
            const sc = channelScores[index],
              selected = index === targetChannel,
              fill =
                mapMode === 'candidate'
                  ? r2FillColor(sc.cand)
                  : deltaR2FillColor(sc.delta);
            return (
              <g
                key={pt.name}
                className="cursor-pointer"
                onClick={() => onSelectChannel(index)}
              >
                <title>
                  {`${pt.name} · ${tx('自定义64')} ${tx(pct(sc.cand))} · ${tx('标准64')} ${tx(pct(sc.base))}`}
                </title>
                {selected && (
                  <circle
                    cx={pt.cx}
                    cy={pt.cy}
                    r={9.2}
                    fill="none"
                    stroke="var(--primary)"
                    strokeWidth={2}
                  />
                )}
                <circle
                  cx={pt.cx}
                  cy={pt.cy}
                  r={selected ? 6.2 : 4.8}
                  fill={fill}
                  stroke={selected ? '#0f172a' : '#ffffff'}
                  strokeWidth={selected ? 1.8 : 1.1}
                />
                {selected && (
                  <text
                    x={pt.cx}
                    y={pt.cy - 11}
                    textAnchor="middle"
                    fontSize="10"
                    fontWeight="600"
                    fill="currentColor"
                  >
                    {pt.name}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="space-y-2 pt-1">
        {mapMode === 'candidate' ? (
          <div>
            <div
              aria-hidden="true"
              className="h-2 rounded bg-gradient-to-r from-[#d97706] via-[#e2e8f0] to-[#128a80]"
            />
            <div className="mt-0.5 flex justify-between font-mono text-[10px] text-muted-foreground">
              <span>≤0%</span>
              <span>50%</span>
              <span>100%</span>
            </div>
          </div>
        ) : (
          <div>
            <div
              aria-hidden="true"
              className="h-2 rounded bg-gradient-to-r from-[#c04768] via-[#f1f5f9] to-[#128a80]"
            />
            <div className="mt-0.5 flex justify-between font-mono text-[10px] text-muted-foreground">
              <span>−30 pp</span>
              <span>0</span>
              <span>+30 pp</span>
            </div>
          </div>
        )}
        <p className="rounded-md bg-background/80 px-2.5 py-1.5 font-mono text-xs tabular-nums">
          {tx(
            `当前目标 ${biosemi.channels[targetChannel].name} · 自定义 ${tx(pct(current?.cand))} · 标准64 ${tx(pct(current?.base))}`,
          )}
        </p>
      </div>
    </div>
  );
}

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
  const { time, setTime, playing, setPlaying } = useResultPlayback(
    result.waveforms,
  );
  const [sourceIndex, setSourceIndex] = useState(0);
  const { regions: sourceRegions, colors: sourceColors } = useMemo(
    () => sourcePresentation(result),
    [result],
  );
  const [fieldLayer, setFieldLayer] = useState<FieldLayer>('brain');
  const score = result.conditions.find((s) => s.condition === condition)!,
    status = sourcePass(score.field_retention, ar);
  const notice = reconstructionNotice(score);
  const times = result.waveforms.time_s;
  const fields = useMemo(
    () => fieldFrames(result, condition, fieldLayer),
    [result, condition, fieldLayer],
  );
  const traces = useMemo(
    () => receiverTraces(result, channels, condition),
    [result, channels, condition],
  );
  const recovered = useMemo(
    () => reconstructionTrace(result, targetChannel, condition),
    [result, targetChannel, condition],
  );
  const amplitude = useMemo(() => sharedAmplitude(traces), [traces]);
  const { curve, passing } = useMemo(
    () => strengthCurve(result, condition, ar),
    [result, condition, ar],
  );
  const sourceTrace = useMemo(
    () => sourceTraceAt(result, sourceIndex),
    [result, sourceIndex],
  );
  const layouts = useMemo(() => layoutPresentation(result), [result]);
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
            <p className="mt-1 text-xs text-muted-foreground">{tx(recordedForwardOrigin(result.provenance))}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
          {!archived && receiptId && <SaveToProject kind="source" recordId={sourceResultKey} receiptId={receiptId} />}
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
      <div className="space-y-5">
        <div
          data-sticky-playback
          className="sticky top-[calc(var(--workspace-header-height,0px)+0.5rem)] z-30 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-border bg-card/95 px-3 py-2 shadow-sm backdrop-blur-md sm:flex-nowrap sm:px-4 sm:py-2.5"
        >
          <Button
            size="sm"
            variant={playing ? 'default' : 'outline'}
            onClick={() => setPlaying((p) => !p)}
          >
            {playing ? (
              <Pause className="size-4" />
            ) : (
              <Play className="size-4" />
            )}
            {tx(playing ? '暂停时间标记' : '播放时间标记')}
          </Button>
          <span className="ml-auto shrink-0 font-mono text-xs font-medium tabular-nums text-foreground sm:ml-0 sm:text-sm">
            {tx('时间 · ')}
            {times[time].toFixed(2)} / {(times[times.length - 1] ?? 0).toFixed(2)} s
          </span>
          <input
            className="order-last h-2 w-full cursor-pointer accent-primary sm:order-none sm:min-w-[140px] sm:flex-1"
            aria-label={tx('波形观察时间')}
            type="range"
            min={0}
            max={times.length - 1}
            value={time}
            onChange={(e) => {
              setTime(Number(e.target.value));
              setPlaying(false);
            }}
          />
          <div
            aria-hidden="true"
            className="hidden shrink-0 items-center gap-2.5 border-l border-border pl-3 text-xs text-muted-foreground xl:flex"
          >
            <span className="rounded-md bg-secondary px-2 py-0.5 font-medium text-foreground">
              {tx(CONDITION_LABELS[condition])}
            </span>
            <span>
              {tx(
                FIELD_LAYERS.find(([v]) => v === fieldLayer)?.[1] ??
                  FIELD_LAYERS[0][1],
              )}
            </span>
            <span className="flex items-center gap-1.5 font-mono tabular-nums text-foreground">
              <span className="h-2 w-12 rounded-sm bg-gradient-to-r from-[#2166ac] via-[#f5f5f4] to-[#b2182b] ring-1 ring-inset ring-black/10" />
              ±{fields.limit.toPrecision(3)} μV
            </span>
          </div>
        </div>
        <section className="lab-panel">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold">
                {tx('查看脑源与接收波形')}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {tx(
                  '预览经过抗混叠降采样；所有分数由完整20秒200 Hz数据计算。播放移动时间标记，不模拟传播延迟。',
                )}
              </p>
            </div>
            <label className="lab-label w-full sm:w-auto sm:min-w-[280px]">
              {tx('观察皮层源 · 偶极矩 nA·m')}
              <select
                className="lab-select"
                value={sourceIndex}
                onChange={(e) => setSourceIndex(Number(e.target.value))}
              >
                {result.source.xyz_mm.map((xyz, i) => (
                  <option key={i} value={i}>
                    S{i + 1} ·{' '}
                    {tx(
                      sourceRegion(sourceRegions[i])?.label ??
                        '其他皮层或分区边界',
                    )}{' '}
                    · {xyz.map((v) => v.toFixed(1)).join(', ')} mm
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="mt-3 h-36">
            <ResponsiveContainer width="100%" height={144}>
              <LineChart data={sourceTrace}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="time"
                  type="number"
                  domain={['dataMin', 'dataMax']}
                  tick={{ fontSize: 12 }}
                />
                <YAxis width={60} tick={{ fontSize: 12 }} />
                <Tooltip />
                <ReferenceLine x={times[time]} stroke="#a16716" />
                <Line
                  type="linear"
                  dataKey="source"
                  name={tx('脑源偶极矩 nA·m')}
                  stroke={sourceColors[sourceIndex]}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
        <section className="lab-panel">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <label className="lab-label">
              {tx('三维点位颜色')}
              <select
                className="lab-select"
                value={fieldLayer}
                onChange={(e) => setFieldLayer(e.target.value as FieldLayer)}
              >
                {FIELD_LAYERS.map(([v, label]) => (
                  <option value={v} key={v}>
                    {tx(label)}
                  </option>
                ))}
              </select>
            </label>
            <div className="min-w-60 text-sm">
              <div className="h-3 rounded bg-gradient-to-r from-[#2166ac] via-[#f5f5f4] to-[#b2182b]" />
              <div className="mt-1 flex justify-between">
                <span>−{tx(fields.limit.toPrecision(3))}</span>
                <span>0 μV</span>
                <span>+{tx(fields.limit.toPrecision(3))}</span>
              </div>
            </div>
          </div>
          <p className="mt-3 text-sm leading-6">
            {tx(
              '两侧共用固定色标，范围由当前分量的全部预览时间和128个电极值确定。拖动时间或播放同步更新电位；点击电极联动通道，点击黄色源标记联动源波形。',
            )}
          </p>
          <p className="mt-2 text-sm text-muted-foreground">
            {tx(
              fields.target
                ? '重建与残差均显示在标准64个目标坐标。残差＝重建−干净脑真值。'
                : '接收电位采用各自64通道平均参考；颜色表示实际电极电位，点间不做场插值。',
            )}{' '}
            {tx(' 固定法向箭头只在具有原始方向记录的新实验中显示。')}
          </p>
        </section>
        <ReceiverComparison
          result={result}
          channels={channels}
          setChannels={setChannels}
          targetChannel={targetChannel}
          setTargetChannel={setTargetChannel}
          sourceIndex={sourceIndex}
          setSourceIndex={setSourceIndex}
          sourceRegions={sourceRegions}
          time={time}
          traces={traces}
          amplitude={amplitude}
          fields={fields}
          layouts={layouts}
        />
        <section className="lab-panel">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold">
                {tx('恢复到同一个标准64位置')}
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">
                {tx(
                  '两套估计器由纯脑信号先验与测量噪声预先确定；本次源真值、心电和眼电分量仅用于仿真评估。',
                )}
              </p>
            </div>
            <label className="lab-label">
              {tx('重建目标')}
              <select
                className="lab-select"
                value={targetChannel}
                onChange={(e) => setTargetChannel(Number(e.target.value))}
              >
                {biosemi.channels.map((c, i) => (
                  <option key={c.name} value={i}>
                    {tx(c.name)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="mt-4 grid items-stretch gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
            <TargetChannelTopography
              result={result}
              condition={condition}
              targetChannel={targetChannel}
              onSelectChannel={setTargetChannel}
            />
            <div className="flex min-w-0 flex-col justify-between">
              <div className="h-72">
                <ResponsiveContainer width="100%" height={288}>
                  <LineChart data={recovered}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="time"
                      type="number"
                      domain={['dataMin', 'dataMax']}
                    />
                    <YAxis
                      width={65}
                      tickFormatter={(v) => tx(Number(v).toPrecision(3))}
                    />
                    <Tooltip />
                    <ReferenceLine x={times[time]} stroke="#a16716" />
                    <Line
                      dataKey="truth"
                      name={tx('干净脑真值 μV')}
                      stroke="#182f3a"
                      dot={false}
                      isAnimationActive={false}
                    />
                    <Line
                      dataKey="baseline"
                      name={tx('标准64重建 μV')}
                      stroke="#376ec6"
                      dot={false}
                      isAnimationActive={false}
                    />
                    <Line
                      dataKey="candidate"
                      name={tx('自定义64重建 μV')}
                      stroke="#128a80"
                      dot={false}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-2 text-sm">
                {tx('黑色：干净脑真值 · 蓝色：标准64重建 · 绿色：自定义64重建')}
              </p>
            </div>
          </div>
        </section>
      </div>
      <section className="lab-panel">
        <h2 className="text-lg font-semibold">{tx('干扰强度—重建曲线')}</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          {tx(
            '点为实际计算值，连线仅引导阅读。源波形、噪声和估计器固定；只改变模拟心眼伪迹的幅度。',
          )}
        </p>
        {tx(
          condition === 'clean' ? (
            <p className="mt-4 text-sm">
              {tx(
                '当前为仅脑源与测量噪声的基线。切换心电、眼电或混合条件查看强度曲线。',
              )}
            </p>
          ) : (
            <>
              <div className="mt-4 h-72">
                <ResponsiveContainer width="100%" height={288}>
                  <LineChart data={curve}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="strength"
                      type="number"
                      ticks={[0, 0.5, 1, 2, 4]}
                    />
                    <YAxis
                      width={65}
                      tickFormatter={(v) => tx(Number(v).toFixed(0) + '%')}
                    />
                    <Tooltip />
                    <Line
                      dataKey="baseline"
                      name={tx('标准64重建解释率 %')}
                      stroke="#376ec6"
                      isAnimationActive={false}
                    />
                    <Line
                      dataKey="candidate"
                      name={tx('自定义64重建解释率 %')}
                      stroke="#128a80"
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="text-sm">
                {tx(
                  '蓝色：标准64 · 绿色：自定义64。纵轴是两套布局各自的重建解释率。',
                )}
              </p>
              <p className="mt-2 text-sm">
                {tx('本场景在已测强度中')}
                {tx(
                  passing.length
                    ? `达到AR的点：${passing.map((s) => s.artifact_scale + '×').join('、')}`
                    : '没有达到AR的点',
                )}
                {tx('。判定范围为已计算干扰强度。')}
              </p>
            </>
          ),
        )}
      </section>
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
