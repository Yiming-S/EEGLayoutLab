'use client';

import { useMemo, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { type channelSubsets } from '@/lib/channel-subset';
import { ERNIE_MNI_MAPPING, type Point } from '@/lib/ernie-mni';
import { projectLayout } from '@/lib/layout-figure';
import { cn } from '@/lib/utils';

type Report = ReturnType<typeof channelSubsets>;
type MethodRow = {
  count: number;
  channels: string[];
  train_error: number;
  test_error: { mean: number } | null;
};

const METHOD_NAMES: Record<string, string> = {
  data: '按数据贪心选择',
  data_prior: '按数据先验模型选择',
  area_prior: '按面积先验模型选择',
};

const pct = (value: number) => `${(100 * value).toFixed(1)}%`;

function buildErnieLabelLookup(): Map<string, Point> {
  const map = new Map<string, Point>();
  for (const entry of ERNIE_MNI_MAPPING.labels.positions_mm) {
    const [label, x, y, z] = entry as [string, number, number, number];
    map.set(label.toUpperCase(), [x, y, z]);
  }
  for (const [alias, canonical] of Object.entries(
    ERNIE_MNI_MAPPING.labels.aliases,
  )) {
    const pt = map.get(canonical.toUpperCase());
    if (pt && !map.has(alias.toUpperCase())) {
      map.set(alias.toUpperCase(), pt);
    }
  }
  return map;
}

const LABEL_LOOKUP = buildErnieLabelLookup();

function HeadDisc({
  title,
  subtitle,
  points,
  selectedNames,
  accentColor,
  showLabels,
}: {
  title: string;
  subtitle: string;
  points: { name: string; x: number; y: number }[];
  selectedNames: string[];
  accentColor: string;
  showLabels: boolean;
}) {
  const rankMap = new Map(selectedNames.map((name, idx) => [name, idx + 1]));
  const cx = 136,
    cy = 142,
    r = 98;
  return (
    <div className="rounded-xl border border-border/80 bg-card p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-xs font-semibold text-foreground">{title}</h4>
        <span className="font-mono text-[11px] text-muted-foreground tabular-nums">
          {subtitle}
        </span>
      </div>
      <svg
        viewBox="0 0 272 272"
        className="mx-auto mt-1.5 w-full max-w-[264px]"
        aria-label={title}
      >
        <title>{title}</title>
        <path
          d={`M ${(cx - r * 0.09).toFixed(1)} ${(cy - r * 0.996).toFixed(1)} L ${cx} ${(cy - r * 1.09).toFixed(1)} L ${(cx + r * 0.09).toFixed(1)} ${(cy - r * 0.996).toFixed(1)}`}
          fill="none"
          className="stroke-border"
          strokeWidth={1.5}
          strokeLinejoin="round"
        />
        {[-1, 1].map((side) => (
          <path
            key={side}
            d={`M ${(cx + side * r).toFixed(1)} ${(cy - r * 0.12).toFixed(1)} q ${(side * r * 0.07).toFixed(1)} ${(r * 0.02).toFixed(1)} ${(side * r * 0.07).toFixed(1)} ${(r * 0.12).toFixed(1)} t ${(-side * r * 0.07).toFixed(1)} ${(r * 0.12).toFixed(1)}`}
            fill="none"
            className="stroke-border"
            strokeWidth={1.5}
          />
        ))}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          className="stroke-border"
          strokeWidth={1.5}
        />
        {/* Unselected universe channels first */}
        {points
          .filter((pt) => !rankMap.has(pt.name))
          .map((pt) => (
            <g key={pt.name}>
              <title>{pt.name}</title>
              <circle
                cx={pt.x}
                cy={pt.y}
                r={3.2}
                className="fill-muted stroke-muted-foreground/55"
                strokeWidth={1}
              />
            </g>
          ))}
        {/* Selected subset channels on top */}
        {points
          .filter((pt) => rankMap.has(pt.name))
          .map((pt) => {
            const rank = rankMap.get(pt.name)!;
            return (
              <g key={pt.name}>
                <title>{`#${rank} · ${pt.name}`}</title>
                <circle
                  cx={pt.x}
                  cy={pt.y}
                  r={5.2}
                  fill={accentColor}
                  stroke="var(--card)"
                  strokeWidth={1.5}
                />
                {showLabels && (
                  <text
                    x={pt.x}
                    y={pt.y + 12}
                    textAnchor="middle"
                    className="fill-foreground font-mono text-[8.5px] font-medium"
                  >
                    {pt.name}
                  </text>
                )}
              </g>
            );
          })}
      </svg>
    </div>
  );
}

export function ChannelSubsetMap({ report }: { report: Report }) {
  const { tx } = useLanguage();
  const methodKeys = Object.keys(report.methods);
  const [selectedCount, setSelectedCount] = useState<number | null>(null);
  const [selectedMethod, setSelectedMethod] = useState<string>('data');
  const [showLabels, setShowLabels] = useState(true);

  const activeCount =
    selectedCount !== null && report.counts.includes(selectedCount)
      ? selectedCount
      : (report.counts[Math.min(1, report.counts.length - 1)] ??
        report.counts[0]);
  const activeMethod = methodKeys.includes(selectedMethod)
    ? selectedMethod
    : methodKeys[0];

  const projected = useMemo(() => {
    const matched: { name: string; xyz: Point }[] = [];
    const unmatched: string[] = [];
    for (const ch of report.universe) {
      const xyz = LABEL_LOOKUP.get(ch.trim().toUpperCase());
      if (xyz) matched.push({ name: ch, xyz });
      else unmatched.push(ch);
    }
    if (matched.length < 2) {
      return { points: [], unmatched };
    }
    const disc = projectLayout(matched.map((m) => m.xyz));
    const maxR = Math.max(1, ...disc.map((p) => p.r));
    const scale = Math.min(98, 114 / maxR);
    const cx = 136,
      cy = 142;
    return {
      points: matched.map((m, idx) => ({
        name: m.name,
        x: cx + disc[idx].x * scale,
        y: cy - disc[idx].y * scale,
      })),
      unmatched,
    };
  }, [report.universe]);

  if (projected.points.length < 2) {
    return (
      <p className="rounded-lg border border-border/70 bg-muted/25 px-3 py-2 text-xs text-muted-foreground">
        {tx(
          '当前摘要使用自定义通道名称，未匹配到标准10-05模板坐标，已略过二维头皮位置对照。',
        )}
      </p>
    );
  }

  const countIdx = Math.max(0, report.counts.indexOf(activeCount));
  const methodRows = (
    report.methods as Record<string, { counts: MethodRow[] }>
  )[activeMethod]?.counts;
  const currentRow = methodRows?.[countIdx];
  const held = Boolean(report.test.length);
  const errorSummary = currentRow
    ? `${tx('训练')} ${pct(currentRow.train_error)}${held && currentRow.test_error ? ` · ${tx('留出')} ${pct(currentRow.test_error.mean)}` : ''}`
    : '';
  const standard1020 = report.standard_10_20;
  const standardSummary = standard1020
    ? `${tx('训练')} ${pct(standard1020.train_error)}${held && standard1020.test_error ? ` · ${tx('留出')} ${pct(standard1020.test_error.mean)}` : ''}`
    : '';

  return (
    <div
      data-channel-subset-map
      className="space-y-3 rounded-xl border border-border/75 bg-muted/20 p-3.5"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            {tx('所选子集头皮分布示意（Ernie 10-05 模板投影）')}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {tx(
              '彩色实心点为选入子集的通道，浅色圆点为其余共同通道，直观检查空间覆盖度。',
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <fieldset
            className="flex flex-wrap gap-1 rounded-lg border border-border bg-card p-0.5"
            aria-label={tx('预览子集通道数')}
          >
            {report.counts.map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={activeCount === k}
                onClick={() => setSelectedCount(k)}
                className={cn(
                  'rounded-md px-2 py-1 font-mono text-xs font-medium tabular-nums transition-colors',
                  activeCount === k
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {k}
              </button>
            ))}
          </fieldset>
          {methodKeys.length > 1 && (
            <select
              aria-label={tx('子集选择方法')}
              className="lab-select h-8 py-1 text-xs"
              value={activeMethod}
              onChange={(e) => setSelectedMethod(e.target.value)}
            >
              {methodKeys.map((id) => (
                <option key={id} value={id}>
                  {tx(METHOD_NAMES[id] ?? id)}
                </option>
              ))}
            </select>
          )}
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <input
              type="checkbox"
              className="accent-primary"
              checked={showLabels}
              onChange={(e) => setShowLabels(e.target.checked)}
            />
            {tx('显示通道名')}
          </label>
        </div>
      </div>

      <div
        className={cn(
          'grid gap-3',
          standard1020 ? 'md:grid-cols-2' : 'max-w-sm',
        )}
      >
        {currentRow && (
          <HeadDisc
            title={`${tx(METHOD_NAMES[activeMethod] ?? activeMethod)} · ${currentRow.count}`}
            subtitle={errorSummary}
            points={projected.points}
            selectedNames={currentRow.channels}
            accentColor="#2a78d6"
            showLabels={showLabels}
          />
        )}
        {standard1020 && (
          <HeadDisc
            title={tx(`10-20系统（${standard1020.count}个）`)}
            subtitle={standardSummary}
            points={projected.points}
            selectedNames={standard1020.channels}
            accentColor="#eb6834"
            showLabels={showLabels}
          />
        )}
      </div>
      {projected.unmatched.length > 0 && (
        <p className="text-[11px] text-muted-foreground">
          {tx(
            `注：${projected.unmatched.length}个非标准命名通道未包含在10-05模板示意中。`,
          )}
        </p>
      )}
    </div>
  );
}
