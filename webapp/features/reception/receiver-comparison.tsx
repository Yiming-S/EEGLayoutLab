'use client';
import { useState, type Dispatch, type SetStateAction } from 'react';
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
import { useLanguage } from '@/components/language-provider';
import biosemi from '@/lib/biosemi64-reference.json';
import type { SourceResult } from '@/lib/source-reception';
import type { fieldFrames } from '@/lib/source-field';
import type { receiverTraces, layoutPresentation } from './result-view-model';
import { DeferredHeadViewer } from './deferred-head-viewer';

type Props = {
  result: SourceResult;
  channels: number[];
  setChannels: Dispatch<SetStateAction<number[]>>;
  targetChannel: number;
  setTargetChannel: (channel: number) => void;
  sourceIndex: number;
  setSourceIndex: (index: number) => void;
  sourceRegions: (string | null)[];
  time: number;
  traces: ReturnType<typeof receiverTraces>;
  amplitude: number;
  fields: ReturnType<typeof fieldFrames>;
  layouts: ReturnType<typeof layoutPresentation>;
};

export function ReceiverComparison({
  result,
  channels,
  setChannels,
  targetChannel,
  setTargetChannel,
  sourceIndex,
  setSourceIndex,
  sourceRegions,
  time,
  traces,
  amplitude,
  fields,
  layouts,
}: Props) {
  const { tx } = useLanguage();
  const [showHead, setShowHead] = useState([true, true]);
  const times = result.waveforms.time_s;
  const {
    counts,
    allocation,
    baselineAllocation,
    baselineLayout,
    candidateLayout,
  } = layouts;
  return (
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
                (i === 0 ? result.layout.referenceXyzMm : result.layout.xyzMm)[
                  channels[i]
                ]
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
              <span className="text-[#128a80]">{tx('脑贡献')}</span> ·{tx(' ')}
              <span className="text-[#c04768]">{tx('模拟心眼伪迹')}</span> ·
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
                    <DeferredHeadViewer
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
                      electrodeValues={fields.sides[i].map((row) => row[time])}
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
                  </div>
                ),
              )}
              <p className="mt-2 text-sm text-muted-foreground">
                {tx(
                  'S编号标记为实际源点，颜色与所属源区域一致；选中源的曲线使用同色。',
                )}
                {tx(
                  fields.target
                    ? `标准目标 ${biosemi.channels[targetChannel].name}`
                    : `接收电极 ${channels[i] + 1}`,
                )}
                ：
                {tx(
                  fields.sides[i][fields.target ? targetChannel : channels[i]][
                    time
                  ].toPrecision(4),
                )}{' '}
                μV。
              </p>
            </details>
          </section>
        )),
      )}
    </div>
  );
}
