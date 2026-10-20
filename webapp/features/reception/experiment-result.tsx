'use client';
import { useLanguage } from '@/components/language-provider';

/* oxlint-disable next/no-html-link-for-pages -- preserve established vinext navigation */
import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
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
  CONDITION_LABELS,
  combinedTrace,
  sourcePass,
  type SourceCondition,
  type SourceResult,
} from '@/lib/source-reception';
import biosemi from '@/lib/biosemi64-reference.json';
import { FIELD_LAYERS, fieldFrames, type FieldLayer } from '@/lib/source-field';
import { SOURCE_ROI_DEFINITION, UNASSIGNED_SOURCE_COLOR, sourceRegion } from '@/lib/source-regions';
import { reconstructionNotice } from '@/lib/source-result-reading';

const Head = lazy(() =>
  import('@/components/cluster-head-viewer').then((m) => ({
    default: m.ClusterHeadViewer,
  })),
);
const pct = (n: number | null | undefined) =>
  n == null ? '指标无法计算' : `${(n * 100).toFixed(2)}%`;
const fixed = (n: number | null | undefined, unit = '') =>
  n == null ? '无干扰' : `${n.toFixed(2)}${unit}`;
const conditions = Object.keys(CONDITION_LABELS) as SourceCondition[];

export function ExperimentResult({
  result,
  label,
  ar,
  setAR,
  cached,
  onReduceArtifacts,
}: {
  result: SourceResult;
  label: string;
  ar: number;
  setAR: (ar: number) => void;
  cached: boolean;
  onReduceArtifacts?: () => void;
}) {
  const { tx } = useLanguage();
  const [condition, setCondition] = useState<SourceCondition>('mixed'),
    [channels, setChannels] = useState([0, 0]),
    [targetChannel, setTargetChannel] = useState(0),
    [time, setTime] = useState(() => {
      const energy = result.waveforms.time_s.map((_, t) =>
        result.waveforms.source_nam.reduce((sum, row) => sum + row[t] ** 2, 0),
      );
      return energy.indexOf(Math.max(...energy));
    }),
    [playing, setPlaying] = useState(false);
  const [showHead, setShowHead] = useState([true, true]);
  const [sourceIndex, setSourceIndex] = useState(0);
  const sourceRegions = useMemo(() => result.source.region_definition === SOURCE_ROI_DEFINITION ? result.source.source_regions ?? [] : result.source.xyz_mm.map(() => null), [result]);
  const sourceColors = useMemo(() => result.source.xyz_mm.map((_, i) => sourceRegion(sourceRegions[i])?.color ?? UNASSIGNED_SOURCE_COLOR), [result, sourceRegions]);
  const [fieldLayer, setFieldLayer] = useState<FieldLayer>('brain');
  const score = result.conditions.find((s) => s.condition === condition)!,
    status = sourcePass(score.field_retention, ar);
  const notice = reconstructionNotice(score);
  const times = result.waveforms.time_s;
  const fields = useMemo(
    () => fieldFrames(result, condition, fieldLayer),
    [result, condition, fieldLayer],
  );
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setTime((i) => (i + 5) % times.length), 100);
    return () => clearInterval(t);
  }, [playing, times.length]);
  const traces = useMemo(
    () =>
      ['baseline', 'candidate'].map((side, i) =>
        combinedTrace(
          result.waveforms[side as 'baseline' | 'candidate'],
          channels[i],
          condition,
        ).map((v, t) => ({ time: times[t], ...v })),
      ),
    [result, channels, condition, times],
  );
  const recovered = useMemo(() => {
    const b = combinedTrace(
        result.waveforms.baseline,
        targetChannel,
        condition,
        true,
      ),
      c = combinedTrace(
        result.waveforms.candidate,
        targetChannel,
        condition,
        true,
      );
    return times.map((t, i) => ({
      time: t,
      truth: result.waveforms.baseline.brain_uv[targetChannel][i],
      baseline: b[i].mixed,
      candidate: c[i].mixed,
    }));
  }, [result, targetChannel, condition, times]);
  const amplitude = useMemo(
    () =>
      Math.max(
        1e-3,
        ...traces
          .flat()
          .flatMap((r) => [
            Math.abs(r.brain),
            Math.abs(r.artifact),
            Math.abs(r.mixed),
          ]),
      ) * 1.08,
    [traces],
  );
  const curve = result.strength_curve
    .filter((s) => s.condition === condition)
    .map((s) => ({
      strength: s.artifact_scale,
      baseline: s.baseline.explained_energy * 100,
      candidate: s.candidate.explained_energy * 100,
      retention: s.field_retention == null ? null : s.field_retention * 100,
    }));
  const curveAll = result.strength_curve.filter(
    (s) => s.condition === condition,
  );
  const passing = curveAll.filter(
    (s) => sourcePass(s.field_retention, ar) === 'pass',
  );
  const sourceTrace = times.map((t, i) => ({
    time: t,
    source: result.waveforms.source_nam[sourceIndex][i],
  }));
  const counts = new Set(result.layout.regionIndices).size;
  const allocation = useMemo(
    () =>
      Array.from(
        { length: counts },
        (_, r) => result.layout.regionIndices.filter((v) => v === r).length,
      ),
    [counts, result],
  );
  const baselineAllocation = useMemo(() => [64], []);
  const baselineLayout = useMemo(
    () => ({
      id: result.request.record_id + '-baseline',
      xyzMm: result.layout.referenceXyzMm,
      referenceXyzMm: result.layout.referenceXyzMm,
      regionIndices: Array(64).fill(0),
    }),
    [result],
  );
  const candidateLayout = useMemo(
    () => ({ id: result.request.record_id, ...result.layout }),
    [result],
  );
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
              {tx(cached ? '本地缓存' : '本次计算')} ·{' '}
              {tx(result.source.patch_count)}
              {tx('个已选皮层源 · 原布局坐标未改变')}
              {result.request.mode === 'cross_region' && <> · {tx('跨区域多源')}</>}
            </p>
          </div>
          <Button variant="outline" onClick={download}>
            <Download className="size-4" />
            {tx('导出本场景JSON')}
          </Button>
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
      {notice && <section aria-live="polite" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
        <h2 className="font-semibold">{tx(notice.title)}</h2>
        <p className="mt-2 leading-6">{tx(notice.explanation)}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {condition !== 'clean' && <Button variant="outline" size="sm" onClick={() => setCondition('clean')}>{tx('查看无心眼干扰条件')}</Button>}
          {condition !== 'clean' && onReduceArtifacts && <Button variant="outline" size="sm" onClick={onReduceArtifacts}>{tx('降低干扰幅度')}</Button>}
        </div>
      </section>}
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
      <section className="lab-panel">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">
              {tx('查看脑源与接收波形')}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {tx(
                '预览经过抗混叠降采样；所有分数由完整20秒200 Hz数据计算。播放移动时间标记，不模拟传播延迟。',
              )}
            </p>
          </div>
          <Button variant="outline" onClick={() => setPlaying((p) => !p)}>
            {tx(
              playing ? (
                <Pause className="size-4" />
              ) : (
                <Play className="size-4" />
              ),
            )}
            {tx(playing ? '暂停时间标记' : '播放时间标记')}
          </Button>
        </div>
        <label className="mt-4 block text-sm">
          {tx('时间 · ')}
          {tx(times[time].toFixed(2))} s
          <input
            className="mt-2 w-full accent-primary"
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
        </label>
        <label className="mt-3 block text-sm font-medium">
          {tx('观察皮层源 · 偶极矩 nA·m')}
          <select
            className="lab-select mt-2"
            value={sourceIndex}
            onChange={(e) => setSourceIndex(Number(e.target.value))}
          >
            {tx(
              result.source.xyz_mm.map((xyz, i) => (
                <option key={i} value={i}>
                  S{i + 1} · {tx(sourceRegion(sourceRegions[i])?.label ?? '其他皮层或分区边界')} · {tx(xyz.map((v) => v.toFixed(1)).join(', '))} mm
                </option>
              )),
            )}
          </select>
        </label>
        <div className="mt-2 h-36">
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
              {tx(
                FIELD_LAYERS.map(([v, label]) => (
                  <option value={v} key={v}>
                    {tx(label)}
                  </option>
                )),
              )}
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
      <div className="grid gap-5 xl:grid-cols-2">
        {tx(
          (['baseline', 'candidate'] as const).map((side, i) => (
            <section className="lab-panel min-w-0" key={side}>
              <h2 className="text-lg font-semibold">
                {tx(i === 0 ? '标准全头64 · 接收' : '自定义64 · 接收')}
              </h2>
              <label className="mt-3 lab-label">
                {tx('查看电极')}
                <select
                  className="lab-select"
                  value={channels[i]}
                  onChange={(e) =>
                    setChannels((old) =>
                      old.map((c, j) => (j === i ? Number(e.target.value) : c)),
                    )
                  }
                >
                  {tx(
                    Array.from({ length: 64 }, (_, c) => (
                      <option key={c} value={c}>
                        {tx(
                          i === 0
                            ? biosemi.channels[c].name
                            : `电极${c + 1} · 区域${result.layout.regionIndices[c] + 1}`,
                        )}
                      </option>
                    )),
                  )}
                </select>
              </label>
              <p className="mt-2 text-sm text-muted-foreground">
                {tx('MRI坐标：')}
                {tx(
                  (i === 0
                    ? result.layout.referenceXyzMm
                    : result.layout.xyzMm)[channels[i]]
                    .map((v) => v.toFixed(1))
                    .join(', '),
                )}
                {tx(' ')}
                mm
              </p>
              <div className="mt-3 h-60">
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={traces[i]} syncId="source-receivers">
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="time"
                      type="number"
                      domain={['dataMin', 'dataMax']}
                      tick={{ fontSize: 12 }}
                    />
                    <YAxis
                      domain={[-amplitude, amplitude]}
                      width={65}
                      tick={{ fontSize: 12 }}
                      tickFormatter={(v) => tx(Number(v).toPrecision(3))}
                    />
                    <Tooltip />
                    <ReferenceLine x={times[time]} stroke="#a16716" />
                    <Line
                      dataKey="mixed"
                      name={tx('混合接收 μV')}
                      stroke="#718096"
                      dot={false}
                      isAnimationActive={false}
                    />
                    <Line
                      dataKey="brain"
                      name={tx('脑贡献 μV')}
                      stroke="#128a80"
                      dot={false}
                      isAnimationActive={false}
                    />
                    <Line
                      dataKey="artifact"
                      name={tx('模拟心眼伪迹 μV')}
                      stroke="#c04768"
                      dot={false}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="text-sm">
                <span className="text-[#128a80]">{tx('脑贡献')}</span> ·
                {tx(' ')}
                <span className="text-[#c04768]">
                  {tx('模拟心眼伪迹')}
                </span> ·
                {tx(' ')}
                <span className="text-[#718096]">
                  {tx('混合接收（含电极噪声）')}
                </span>
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                {tx('两侧共享微伏刻度。电极位置不同，波形不要求逐点相同。')}
              </p>
              <details
                className="mt-4"
                open={showHead[i]}
                onToggle={(e) => {
                  const open = e.currentTarget.open;
                  setShowHead((old) =>
                    old[i] === open
                      ? old
                      : old.map((v, j) => (j === i ? open : v)),
                  );
                }}
              >
                <summary className="cursor-pointer text-sm font-medium">
                  {tx('三维电位与源位置 · ')}
                  {tx(times[time].toFixed(2))} s
                </summary>
                {tx(
                  showHead[i] && (
                    <div className="mt-3">
                      <Suspense fallback={<p>{tx('加载3D…')}</p>}>
                        <Head
                          regionCount={i === 0 || fields.target ? 1 : counts}
                          allocation={
                            i === 0 || fields.target
                              ? baselineAllocation
                              : allocation
                          }
                          domainMode="whole_surface"
                          radiusCm={3.5}
                          recordedLayout={
                            i === 0 || fields.target
                              ? baselineLayout
                              : candidateLayout
                          }
                          sourceXyzMm={result.source.xyz_mm}
                          sourceNormals={result.source.normals_mri}
                          sourceRegions={sourceRegions}
                          selectedSource={sourceIndex}
                          onSourceSelect={setSourceIndex}
                          electrodeValues={fields.sides[i].map(
                            (row) => row[time],
                          )}
                          potentialLimit={fields.limit}
                          selectedElectrode={
                            fields.target ? targetChannel : channels[i]
                          }
                          onElectrodeSelect={(c) =>
                            fields.target
                              ? setTargetChannel(c)
                              : setChannels((old) =>
                                  old.map((v, j) => (j === i ? c : v)),
                                )
                          }
                        />
                      </Suspense>
                    </div>
                  ),
                )}
                <p className="mt-2 text-sm text-muted-foreground">
                  {tx('S编号标记为实际源点，颜色与所属源区域一致；选中源的曲线使用同色。')}
                  {tx(
                    fields.target
                      ? `标准目标 ${biosemi.channels[targetChannel].name}`
                      : `接收电极 ${channels[i] + 1}`,
                  )}
                  ：
                  {tx(
                    fields.sides[i][
                      fields.target ? targetChannel : channels[i]
                    ][time].toPrecision(4),
                  )}{' '}
                  μV。
                </p>
              </details>
            </section>
          )),
        )}
      </div>
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
              {tx(
                biosemi.channels.map((c, i) => (
                  <option key={c.name} value={i}>
                    {tx(c.name)}
                  </option>
                )),
              )}
            </select>
          </label>
        </div>
        <div className="mt-4 h-72">
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
        <p className="text-sm">
          {tx('黑色：干净脑真值 · 蓝色：标准64重建 · 绿色：自定义64重建')}
        </p>
      </section>
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
