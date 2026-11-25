'use client';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from '@/components/runtime-message';

import { lazy, Suspense, useEffect, useState } from 'react';
import {
  CartesianGrid,
  LineChart,
  Line,
  ReferenceLine,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Button } from '@/components/ui/button';
import { FIGURE_REGION_COLORS, projectLayout } from '@/lib/layout-figure';

type Snapshot = {
  label: string;
  xyzMm: [number, number, number][] | null;
  regionIndices: number[];
  referenceXyzMm: [number, number, number][];
};
const Head = lazy(() =>
  import('@/components/cluster-head-viewer').then((m) => ({
    default: m.ClusterHeadViewer,
  })),
);
type Bundle = {
  schema: string;
  source: { sha256: string };
  snapshots: (Snapshot | null)[];
  coordinate_note: string | null;
  search: {
    objective: string | null;
    configuration: unknown;
    initial: unknown;
    final: unknown;
    trace: unknown[];
    curve: { step: number; value: number }[];
    counters: Record<string, number | null>;
    history_status: string;
  };
};

function SnapshotTrajectoryMap({
  initial,
  optimized,
}: {
  initial: Snapshot;
  optimized: Snapshot;
}) {
  const { tx } = useLanguage();
  if (initial.xyzMm?.length !== 64 || optimized.xyzMm?.length !== 64) return null;
  const projInit = projectLayout(initial.xyzMm),
    projOpt = projectLayout(optimized.xyzMm),
    maxR = Math.max(1, ...projInit.map((p) => p.r), ...projOpt.map((p) => p.r)),
    radius = Math.min(92, 108 / maxR),
    cx = 130,
    cy = 134,
    at = (p: { x: number; y: number }) => ({
      x: cx + p.x * radius,
      y: cy - p.y * radius,
    });
  const pairs = initial.xyzMm.map((startPt, idx) => {
    const endPt = optimized.xyzMm![idx],
      distMm = Math.hypot(
        endPt[0] - startPt[0],
        endPt[1] - startPt[1],
        endPt[2] - startPt[2],
      ),
      moved = distMm > 1e-3;
    return {
      idx,
      moved,
      distMm,
      region: optimized.regionIndices[idx] ?? 0,
      from: at(projInit[idx]),
      to: at(projOpt[idx]),
    };
  });
  const movedCount = pairs.filter((p) => p.moved).length,
    maxMoveMm = pairs.reduce((hi, p) => (p.distMm > hi ? p.distMm : hi), 0);

  return (
    <div
      className="mb-3 rounded-lg border bg-muted/20 p-3 space-y-2"
      data-snapshot-trajectory
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
        <span className="font-semibold text-foreground">
          {tx('二维电极移动轨迹（初始化 → 优化后）')}
        </span>
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
          {tx(`共 ${movedCount}/64 个槽位发生移动，最大三维位移 ${maxMoveMm.toFixed(1)} mm`)}
        </span>
      </div>
      <svg
        viewBox="0 0 260 260"
        className="mx-auto w-full max-w-[260px]"
        aria-label={tx('二维电极移动轨迹（初始化 → 优化后）')}
      >
        <title>{tx('二维电极移动轨迹（初始化 → 优化后）')}</title>
        <defs>
          <marker
            id="traj-arrow"
            viewBox="0 0 8 8"
            refX="6"
            refY="4"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M 0 1 L 7 4 L 0 7 z" fill="currentColor" opacity="0.7" />
          </marker>
        </defs>
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          className="stroke-border"
          strokeWidth={1.4}
        />
        <path
          d={`M ${(cx - radius * 0.1).toFixed(1)} ${(cy - radius * 0.99).toFixed(1)} L ${cx} ${(cy - radius * 1.1).toFixed(1)} L ${(cx + radius * 0.1).toFixed(1)} ${(cy - radius * 0.99).toFixed(1)}`}
          fill="none"
          className="stroke-border"
          strokeWidth={1.4}
          strokeLinejoin="round"
        />
        {pairs.map((p) => {
          const color = FIGURE_REGION_COLORS[p.region] ?? FIGURE_REGION_COLORS[0];
          if (!p.moved) {
            return (
              <circle
                key={p.idx}
                cx={p.to.x}
                cy={p.to.y}
                r={3.2}
                fill={color}
                fillOpacity={0.55}
              >
                <title>{`E${p.idx + 1}: 0.0 mm`}</title>
              </circle>
            );
          }
          return (
            <g key={p.idx} className="text-foreground/65">
              <title>{`E${p.idx + 1}: ${p.distMm.toFixed(1)} mm`}</title>
              <circle
                cx={p.from.x}
                cy={p.from.y}
                r={2.8}
                fill="none"
                stroke={color}
                strokeWidth={1.2}
                strokeOpacity={0.65}
              />
              <line
                x1={p.from.x}
                y1={p.from.y}
                x2={p.to.x}
                y2={p.to.y}
                stroke="currentColor"
                strokeWidth={1.1}
                strokeOpacity={0.65}
                markerEnd="url(#traj-arrow)"
              />
              <circle
                cx={p.to.x}
                cy={p.to.y}
                r={3.8}
                fill={color}
                stroke="#ffffff"
                strokeWidth={1.1}
              />
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function ExperimentHistory({ recordId }: { recordId: string }) {
  const { tx } = useLanguage();
  const [bundle, setBundle] = useState<{ id: string; value: Bundle } | null>(
    null,
  );
  const [error, setError] = useState('');
  const [snapshot, setSnapshot] = useState(1);
  const [showPositions, setShowPositions] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    fetch(`/api/local-compute/library/${recordId}/bundle`, {
      signal: c.signal,
      cache: 'no-store',
    })
      .then(async (r) => {
        const b = (await r.json()) as Bundle & { error?: string };
        if (!r.ok) throw new Error(b.error);
        return b;
      })
      .then((value) => {
        if (!c.signal.aborted) {
          setBundle({ id: recordId, value });
          setError('');
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(e.message);
      });
    return () => c.abort();
  }, [recordId]);
  const b = bundle?.id === recordId ? bundle.value : null;
  const coordinateEvaluation =
    b?.search.history_status === 'not_applicable_coordinate_evaluation';
  const position = b?.snapshots[snapshot];
  const regionCount = position ? new Set(position.regionIndices).size : 0;
  const download = () => {
    if (!b) return;
    const u = URL.createObjectURL(
      new Blob([JSON.stringify(b, null, 2)], { type: 'application/json' }),
    );
    const a = document.createElement('a');
    a.href = u;
    a.download = `eeg-experiment-${recordId.slice(0, 12)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(u), 1000);
  };
  const curve = b?.search.curve ?? [],
    initialVal = curve.length > 0 ? curve[0].value : null,
    finalVal = curve.length > 0 ? curve[curve.length - 1].value : null,
    netDelta =
      initialVal != null &&
      finalVal != null &&
      Number.isFinite(initialVal) &&
      Number.isFinite(finalVal)
        ? finalVal - initialVal
        : null;

  return (
    <section className="lab-panel mt-4" aria-label={tx('可复现实验记录')}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold">
          {tx(coordinateEvaluation ? '坐标评价与复现数据' : '优化过程与复现数据')}
        </h3>
        <Button variant="outline" disabled={!b} onClick={download}>
          {tx('导出完整实验包')}
        </Button>
      </div>
      {tx(
        error ? (
          <p role="alert" className="mt-3 text-sm text-danger">
            <RuntimeMessage message={error} />
          </p>
        ) : !b ? (
          <p className="mt-3 text-sm">{tx('读取原始实验记录…')}</p>
        ) : (
          <>
            {coordinateEvaluation ? (
              <p className="mt-3 text-sm leading-6">
                {tx(
                  '这条记录评价固定的64点坐标，没有执行布局搜索。实验包分别保存输入坐标和实际评价坐标，并保留原始指标。',
                )}
              </p>
            ) : (
              <>
                <p className="mt-3 text-sm leading-6">
                  {tx(
                    '配置 → 初始化 → 已接受的位置交换 → 最终评价。曲线是保存的搜索目标，不是综合准确率；AR只用于判定已计算结果。',
                  )}
                </p>
                <p className="mt-2 text-sm">
                  {tx('搜索目标：')}
                  <code>{b.search.objective}</code> {tx(' · 已保存交换：')}
                  {tx(b.search.trace.length)}
                  {tx('步')}
                </p>
                {tx(
                  curve.length > 0 ? (
                    <div className="mt-3 space-y-2.5" data-search-convergence>
                      {initialVal != null && finalVal != null && netDelta != null && (
                        <dl className="grid gap-2 rounded-lg border bg-muted/20 px-3 py-2 text-xs sm:grid-cols-3">
                          <div>
                            <dt className="text-muted-foreground">{tx('初始目标值')}</dt>
                            <dd className="mt-0.5 font-mono font-semibold tabular-nums">
                              {initialVal.toPrecision(4)}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-muted-foreground">{tx('最终目标值')}</dt>
                            <dd className="mt-0.5 font-mono font-semibold tabular-nums">
                              {finalVal.toPrecision(4)}
                            </dd>
                          </div>
                          <div>
                            <dt className="text-muted-foreground">{tx('优化净变化')}</dt>
                            <dd
                              className={`mt-0.5 font-mono font-semibold tabular-nums ${
                                netDelta > 1e-12
                                  ? 'text-success'
                                  : netDelta < -1e-12
                                    ? 'text-warning'
                                    : ''
                              }`}
                            >
                              {`${netDelta > 0 ? '+' : netDelta < 0 ? '−' : '±'}${Math.abs(netDelta).toPrecision(3)}`}
                            </dd>
                          </div>
                        </dl>
                      )}
                      <div className="h-52">
                        <ResponsiveContainer width="100%" height={208}>
                          <LineChart
                            data={curve}
                            margin={{ top: 8, right: 12, left: 0, bottom: 4 }}
                          >
                            <CartesianGrid strokeDasharray="3 3" vertical={false} />
                            <XAxis
                              dataKey="step"
                              name={tx('接受步数')}
                              tick={{ fontSize: 12 }}
                            />
                            <YAxis
                              domain={['auto', 'auto']}
                              width={68}
                              tick={{ fontSize: 12 }}
                              tickFormatter={(v) => Number(v).toPrecision(4)}
                            />
                            <Tooltip
                              formatter={(v) => [
                                Number(v).toPrecision(5),
                                tx('搜索目标值'),
                              ]}
                              labelFormatter={(step) => tx(`步数 ${step}`)}
                            />
                            {initialVal != null && Number.isFinite(initialVal) && (
                              <ReferenceLine
                                y={initialVal}
                                stroke="var(--muted-foreground)"
                                strokeDasharray="4 3"
                              />
                            )}
                            <Line
                              type="linear"
                              dataKey="value"
                              name={tx('搜索目标值')}
                              stroke="#128a80"
                              strokeWidth={2}
                              dot={curve.length <= 24 ? { r: 2.5 } : false}
                              isAnimationActive={false}
                            />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  ) : (
                    <p className="mt-3 text-sm text-muted-foreground">
                      {tx('这条记录未保存可绘制的搜索轨迹。完整原始记录仍可导出。')}
                    </p>
                  ),
                )}
                <p className="mt-2 text-sm text-muted-foreground">
                  {tx(
                    '仅显示已保存的初始化与接受步骤。未接受的提案不在曲线中；零次交换表示没有保存的改进步骤。',
                  )}
                </p>
                <details
                  className="mt-3 text-sm"
                  open={showPositions}
                  onToggle={(e) => setShowPositions(e.currentTarget.open)}
                >
                  <summary className="cursor-pointer font-medium">
                    {tx('对照初始化与优化后的点位')}
                  </summary>
                  <div className="my-3 flex gap-2">
                    {tx(
                      ['初始化', '优化后'].map((label, i) => (
                        <Button
                          key={label}
                          size="sm"
                          variant={snapshot === i ? 'default' : 'outline'}
                          onClick={() => setSnapshot(i)}
                        >
                          {tx(label)}
                        </Button>
                      )),
                    )}
                  </div>
                  {showPositions && b.snapshots[0] && b.snapshots[1] && (
                    <SnapshotTrajectoryMap
                      initial={b.snapshots[0]}
                      optimized={b.snapshots[1]}
                    />
                  )}
                  {tx(
                    showPositions && position?.xyzMm?.length === 64 ? (
                      <Suspense fallback={<p>{tx('加载点位对照…')}</p>}>
                        <Head
                          regionCount={regionCount}
                          allocation={Array.from(
                            { length: regionCount },
                            (_, r) =>
                              position.regionIndices.filter((v) => v === r).length,
                          )}
                          domainMode="whole_surface"
                          radiusCm={3.5}
                          recordedLayout={{
                            id: recordId + '-history-' + snapshot,
                            xyzMm: position.xyzMm,
                            regionIndices: position.regionIndices,
                            referenceXyzMm: position.referenceXyzMm,
                          }}
                        />
                      </Suspense>
                    ) : (
                      <p>
                        {tx(
                          b.coordinate_note ??
                            '本记录未载入这一阶段的64点坐标，原始索引见下方技术数据。',
                        )}
                      </p>
                    ),
                  )}
                </details>
              </>
            )}
            <details className="mt-3 text-sm">
              <summary className="cursor-pointer">
                {tx(
                  coordinateEvaluation
                    ? '坐标评价的原始请求'
                    : '配置、初始化、最终布局与搜索计数',
                )}
              </summary>
              <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">
                {JSON.stringify(
                  {
                    configuration: b.search.configuration,
                    ...(!coordinateEvaluation
                      ? {
                          counters: b.search.counters,
                          initial: b.search.initial,
                          final: b.search.final,
                        }
                      : {}),
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
            <p className="mt-3 break-all font-mono text-xs text-muted-foreground">
              {tx('原始文件 SHA256：')}
              {tx(b.source.sha256)}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              {tx(
                coordinateEvaluation
                  ? '实验包包含坐标评价请求、评价结果和校验身份；重新计算需要对应版本代码及头模/前向库文件。'
                  : '实验包包含原始配置、记录、轨迹和校验身份；重新计算需要对应版本代码及头模/前向库文件。',
              )}
            </p>
          </>
        ),
      )}
    </section>
  );
}
