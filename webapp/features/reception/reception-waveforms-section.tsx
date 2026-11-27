'use client';

import { useMemo, useState, type Dispatch, type SetStateAction } from 'react';
import { Pause, Play } from 'lucide-react';
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
import { useLanguage } from '@/components/language-provider';
import biosemi from '@/lib/biosemi64-reference.json';
import { FIELD_LAYERS, fieldFrames, type FieldLayer } from '@/lib/source-field';
import {
  CONDITION_LABELS,
  type SourceCondition,
  type SourceResult,
} from '@/lib/source-reception';
import { sourceRegion } from '@/lib/source-regions';
import { ReceiverComparison } from './receiver-comparison';
import {
  layoutPresentation,
  receiverTraces,
  reconstructionTrace,
  sharedAmplitude,
  sourcePresentation,
  sourceTraceAt,
  strengthCurve,
} from './result-view-model';
import { TargetChannelTopography } from './target-channel-topography';
import { useResultPlayback } from './use-result-playback';

const TOOLTIP_STYLE = {
  backgroundColor: 'var(--popover)',
  borderColor: 'var(--border)',
  color: 'var(--popover-foreground)',
  borderRadius: '0.5rem',
};

export function ReceptionWaveformsSection({
  result,
  condition,
  ar,
  channels,
  setChannels,
  targetChannel,
  setTargetChannel,
}: {
  result: SourceResult;
  condition: SourceCondition;
  ar: number;
  channels: number[];
  setChannels: Dispatch<SetStateAction<number[]>>;
  targetChannel: number;
  setTargetChannel: Dispatch<SetStateAction<number>>;
}) {
  const { tx } = useLanguage();
  const { time, setTime, playing, setPlaying } = useResultPlayback(
    result.waveforms,
  );
  const [sourceIndex, setSourceIndex] = useState(0);
  const [fieldLayer, setFieldLayer] = useState<FieldLayer>('brain');

  const { regions: sourceRegions, colors: sourceColors } = useMemo(
    () => sourcePresentation(result),
    [result],
  );
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

  return (
    <>
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
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis
                  dataKey="time"
                  type="number"
                  domain={['dataMin', 'dataMax']}
                  tick={{ fontSize: 12 }}
                />
                <YAxis width={60} tick={{ fontSize: 12 }} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
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
                    <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                    <XAxis
                      dataKey="time"
                      type="number"
                      domain={['dataMin', 'dataMax']}
                    />
                    <YAxis
                      width={65}
                      tickFormatter={(v) => tx(Number(v).toPrecision(3))}
                    />
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                    <ReferenceLine x={times[time]} stroke="#a16716" />
                    <Line
                      dataKey="truth"
                      name={tx('干净脑真值 μV')}
                      stroke="var(--foreground)"
                      strokeWidth={1.6}
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
                {tx('主色：干净脑真值 · 蓝色：标准64重建 · 绿色：自定义64重建')}
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
                    <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                    <XAxis
                      dataKey="strength"
                      type="number"
                      ticks={[0, 0.5, 1, 2, 4]}
                    />
                    <YAxis
                      width={65}
                      tickFormatter={(v) => tx(Number(v).toFixed(0) + '%')}
                    />
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                    <ReferenceLine
                      y={ar}
                      stroke="var(--chart-threshold)"
                      strokeDasharray="4 4"
                      ifOverflow="extendDomain"
                      label={{
                        value: `AR ${ar}%`,
                        position: 'insideTopRight',
                        fill: 'var(--chart-threshold)',
                        fontSize: 11,
                      }}
                    />
                    <Line
                      dataKey="baseline"
                      name={tx('标准64重建解释率 %')}
                      stroke="#376ec6"
                      dot={{ r: 3.5 }}
                      isAnimationActive={false}
                    />
                    <Line
                      dataKey="candidate"
                      name={tx('自定义64重建解释率 %')}
                      stroke="#128a80"
                      dot={{ r: 3.5 }}
                      isAnimationActive={false}
                    />
                    <Line
                      dataKey="retention"
                      name={tx('相对标准64保留率 %')}
                      stroke="#d97706"
                      strokeDasharray="4 3"
                      dot={{ r: 3.5 }}
                      connectNulls={false}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="text-sm">
                {tx(
                  '蓝色：标准64解释率 · 绿色：自定义64解释率 · 橙色虚线：相对标准64保留率（对照AR阈值线）。',
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
    </>
  );
}
