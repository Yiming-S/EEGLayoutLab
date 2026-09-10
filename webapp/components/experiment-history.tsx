'use client';
import { useLanguage } from '@/components/language-provider';
import { RuntimeMessage } from "@/components/runtime-message";

import { lazy, Suspense, useEffect, useState } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Button } from '@/components/ui/button';
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
    objective: string;
    configuration: unknown;
    initial: unknown;
    final: unknown;
    trace: unknown[];
    curve: { step: number; value: number }[];
    counters: Record<string, number | null>;
    history_status: string;
  };
};
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
  return (
    <section className="lab-panel mt-4" aria-label={tx("可复现实验记录")}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-semibold">{tx("优化过程与复现数据")}</h3>
        <Button variant="outline" disabled={!b} onClick={download}>
          {tx("导出完整实验包")}</Button>
      </div>
      {tx(error ? (
        <p role="alert" className="mt-3 text-sm text-red-800">
          <RuntimeMessage message={error} />
        </p>
      ) : !b ? (
        <p className="mt-3 text-sm">{tx("读取原始实验记录…")}</p>
      ) : (
        <>
          <p className="mt-3 text-sm leading-6">
            {tx("配置 → 初始化 → 已接受的位置交换 → 最终评价。曲线是保存的搜索目标，不是综合准确率；AR只用于判定已计算结果。")}</p>
          <p className="mt-2 text-sm">
            {tx("搜索目标：")}<code>{b.search.objective}</code> {tx(" · 已保存交换：")}{tx(b.search.trace.length)}{tx("步")}</p>
          {tx(b.search.curve.length > 0 ? (
            <div className="mt-3 h-48">
              <ResponsiveContainer>
                <LineChart data={b.search.curve}>
                  <XAxis dataKey="step" name={tx("接受步数")} />
                  <YAxis domain={['auto', 'auto']} width={65} />
                  <Tooltip />
                  <Line
                    type="linear"
                    dataKey="value"
                    name={tx("搜索目标值")}
                    stroke="#128a80"
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">
              {tx("这条记录未保存可绘制的搜索轨迹。完整原始记录仍可导出。")}</p>
          ))}
          <p className="mt-2 text-sm text-muted-foreground">
            {tx("仅显示已保存的初始化与接受步骤。未接受的提案不在曲线中；零次交换表示没有保存的改进步骤。")}</p>
          <details
            className="mt-3 text-sm"
            open={showPositions}
            onToggle={(e) => setShowPositions(e.currentTarget.open)}
          >
            <summary className="cursor-pointer font-medium">
              {tx("对照初始化与优化后的点位")}</summary>
            <div className="my-3 flex gap-2">
              {tx(['初始化', '优化后'].map((label, i) => (
                <Button
                  key={label}
                  size="sm"
                  variant={snapshot === i ? 'default' : 'outline'}
                  onClick={() => setSnapshot(i)}
                >
                  {tx(label)}
                </Button>
              )))}
            </div>
            {tx(showPositions && position?.xyzMm?.length === 64 ? (
              <Suspense fallback={<p>{tx("加载点位对照…")}</p>}>
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
                {tx(b.coordinate_note ??
                  '本记录未载入这一阶段的64点坐标，原始索引见下方技术数据。')}
              </p>
            ))}
          </details>
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer">
              {tx("配置、初始化、最终布局与搜索计数")}</summary>
            <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">
              {JSON.stringify(
                {
                  configuration: b.search.configuration,
                  counters: b.search.counters,
                  initial: b.search.initial,
                  final: b.search.final,
                },
                null,
                2,
              )}
            </pre>
          </details>
          <p className="mt-3 break-all font-mono text-xs text-muted-foreground">
            {tx("原始文件 SHA256：")}{tx(b.source.sha256)}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            {tx("实验包包含原始配置、记录、轨迹和校验身份；重新计算需要对应版本代码及头模/前向库文件。")}</p>
        </>
      ))}
    </section>
  );
}
