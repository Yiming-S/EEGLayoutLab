import { useMemo, useState } from 'react';
import { useLanguage } from '@/components/language-provider';
import { Button } from '@/components/ui/button';
import type { CatalogEntry } from '@/lib/records-catalog';
import {
  DEFAULT_OBJECTIVES,
  PARETO_OBJECTIVES,
  comparisonGroup,
  paretoAnalysis,
  paretoRanks,
  summaryObjectives,
  type ObjectiveId,
} from '@/lib/pareto';
import {
  conductivityScenarioLabel,
  dataPriorLabel,
  noiseModelLabel,
} from '../../contracts/scientific-options.mjs';
import { cn } from '@/lib/utils';

type LayoutEntry = Extract<CatalogEntry, { summary: unknown }>;
const format = (value: number, unit: string) =>
  unit === 'ratio'
    ? `${(100 * value).toFixed(2)}%`
    : unit === 'mm'
      ? `${value.toFixed(1)} mm`
      : `${value.toFixed(1)} cm²`;
/**
 * Axis ticks at round steps (1, 2, 2.5 or 5 × 10^k) that cover the values. Every objective is
 * non-negative, so an axis never extends below zero.
 */
export function niceAxis(values: number[]): { ticks: number[]; step: number } {
  if (!values.length) return { ticks: [0, 0.25, 0.5, 0.75, 1], step: 0.25 };
  const lo = Math.min(...values),
    hi = Math.max(...values),
    range = hi - lo || Math.abs(hi) * 0.1 || 1;
  const raw = range / 4,
    magnitude = 10 ** Math.floor(Math.log10(raw)),
    step = ([1, 2, 2.5, 5, 10].find((m) => m * magnitude >= raw) ?? 10) * magnitude;
  const start = Math.max(0, Math.floor((lo - range * 0.04) / step) * step),
    end = Math.ceil((hi + range * 0.04) / step) * step;
  const ticks: number[] = [];
  for (let k = 0; start + k * step <= end + step * 1e-9; k++) ticks.push(Number((start + k * step).toPrecision(12)));
  return { ticks: ticks.length > 1 ? ticks : [start, start + step], step };
}
/** A tick label with only as many decimals as the step needs. */
const tickLabel = (value: number, unit: string, step: number) => {
  const scale = unit === 'ratio' ? 100 : 1,
    digits = Math.min(2, (String(Number((step * scale).toPrecision(6))).split('.')[1] ?? '').length);
  const text = (value * scale).toFixed(digits);
  return unit === 'ratio' ? `${text}%` : unit === 'mm' ? `${text} mm` : `${text} cm²`;
};
const groupLabel = (key: string, locale: string): string[] => {
  const g = JSON.parse(key) as {
    noise: unknown;
    scenario: string | null;
    head: string | null;
    prior?: unknown;
  };
  return [
    g.prior ? dataPriorLabel(g.prior) : noiseModelLabel(g.noise ?? undefined),
    g.scenario ? conductivityScenarioLabel(g.scenario) : '',
    g.head ? (locale === 'en' ? `Head ${g.head}` : `头模 ${g.head}`) : '',
  ].filter(Boolean);
};

/** Pareto ranks of the listed layouts under chosen objectives; one evaluation condition at a time. */
export function ParetoPanel({
  entries,
  title,
  onChoose,
}: {
  entries: CatalogEntry[];
  title: (entry: CatalogEntry) => string;
  onChoose: (id: string) => void;
}) {
  const { tx, locale } = useLanguage();
  const [objectives, setObjectives] = useState<ObjectiveId[]>(DEFAULT_OBJECTIVES);
  const [axes, setAxes] = useState<[ObjectiveId, ObjectiveId]>(['field', 'localization']);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const groups = useMemo(() => {
    const map = new Map<string, LayoutEntry[]>();
    for (const entry of entries) {
      if (!('summary' in entry)) continue;
      const key = comparisonGroup(entry.summary);
      if (key) map.set(key, [...(map.get(key) ?? []), entry as LayoutEntry]);
    }
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [entries]);
  const [groupKey, setGroupKey] = useState('');
  const active = groups.find(([key]) => key === groupKey) ?? groups[0];
  const analysis = useMemo(
    () =>
      active && objectives.length
        ? paretoAnalysis(
            active[1].map((item) => ({ item, values: summaryObjectives(item.summary) })),
            objectives,
          )
        : null,
    [active, objectives],
  );
  if (!groups.length) return null;
  const toggle = (id: ObjectiveId) =>
    setObjectives((list) =>
      list.includes(id)
        ? list.filter((value) => value !== id)
        : PARETO_OBJECTIVES.map((o) => o.id).filter((o) => o === id || list.includes(o)),
    );
  const front = analysis?.rows.filter((row) => row.rank === 1) ?? [];
  const x = PARETO_OBJECTIVES.find((o) => o.id === axes[0])!,
    y = PARETO_OBJECTIVES.find((o) => o.id === axes[1])!;
  const plotted = (active?.[1] ?? [])
    .map((item) => ({ item, v: summaryObjectives(item.summary) }))
    .filter((p) => Number.isFinite(p.v[x.id]) && Number.isFinite(p.v[y.id])) as {
    item: LayoutEntry;
    v: Record<ObjectiveId, number>;
  }[];
  const rankOf = new Map(analysis?.rows.map((row) => [row.item.id, row.rank]) ?? []);
  const xAxis = niceAxis(plotted.map((p) => p.v[x.id])),
    yAxis = niceAxis(plotted.map((p) => p.v[y.id]));
  const [x0, x1] = [xAxis.ticks[0], xAxis.ticks[xAxis.ticks.length - 1]],
    [y0, y1] = [yAxis.ticks[0], yAxis.ticks[yAxis.ticks.length - 1]];
  const W = 560,
    H = 320,
    L = 64,
    R = 18,
    T = 18,
    B = 42;
  const px = (v: number) => L + ((v - x0) / (x1 - x0)) * (W - L - R),
    py = (v: number) => H - B - ((v - y0) / (y1 - y0)) * (H - T - B);
  const xTicks = xAxis.ticks,
    yTicks = yAxis.ticks;

  const envelopePath = (() => {
    if (plotted.length < 2 || x.id === y.id) return '';
    const ranks2d = paretoRanks(
      plotted.map((p) => [p.v[x.id], p.v[y.id]]),
      [x.direction, y.direction],
    ).rank;
    const sameSign = x.direction === y.direction;
    const front2d = plotted
      .filter((_, idx) => ranks2d[idx] === 1)
      .sort(
        (a, b) =>
          a.v[x.id] - b.v[x.id] ||
          (sameSign ? b.v[y.id] - a.v[y.id] : a.v[y.id] - b.v[y.id]),
      );
    if (front2d.length < 2) return '';
    const cmds = [`M ${px(front2d[0].v[x.id]).toFixed(2)} ${py(front2d[0].v[y.id]).toFixed(2)}`];
    for (let i = 1; i < front2d.length; i++) {
      const prev = front2d[i - 1],
        curr = front2d[i],
        cornerX = x.direction === 'max' ? prev.v[x.id] : curr.v[x.id],
        cornerY = x.direction === 'max' ? curr.v[y.id] : prev.v[y.id];
      cmds.push(
        `L ${px(cornerX).toFixed(2)} ${py(cornerY).toFixed(2)}`,
        `L ${px(curr.v[x.id]).toFixed(2)} ${py(curr.v[y.id]).toFixed(2)}`,
      );
    }
    return cmds.join(' ');
  })();

  const cornerLabel =
    x.direction === 'max'
      ? y.direction === 'max'
        ? '最优方向：右上'
        : '最优方向：右下'
      : y.direction === 'max'
        ? '最优方向：左上'
        : '最优方向：左下';
  const cornerArrow =
    x.direction === 'max'
      ? y.direction === 'max'
        ? '↗'
        : '↘'
      : y.direction === 'max'
        ? '↖'
        : '↙';
  const activePoint = plotted.find((p) => p.item.id === hoveredId) ?? null;
  const activeRank = activePoint ? rankOf.get(activePoint.item.id) : undefined;

  return (
    <details className="lab-panel mt-4">
      <summary className="cursor-pointer font-semibold">{tx('多目标比较（Pareto前沿）')}</summary>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        {tx(
          '在当前筛选的已完成布局中，找出没有被其他布局在全部所选目标上同时超过的方案（第1层）。只比较同一评价条件下的记录；历史实验按原协议单独解释。',
        )}
      </p>
      <div className="mt-3 grid gap-3 md:grid-cols-[1fr_2fr]">
        <label className="lab-label">
          {tx('评价条件')}
          <select
            className="lab-select"
            value={active?.[0] ?? ''}
            onChange={(event) => setGroupKey(event.target.value)}
          >
            {groups.map(([key, list]) => (
              <option key={key} value={key}>
                {groupLabel(key, locale).map((part) => tx(part)).join(' · ')} ·{' '}
                {locale === 'en'
                  ? `${list.length} ${list.length === 1 ? 'record' : 'records'}`
                  : `${list.length}条`}
              </option>
            ))}
          </select>
        </label>
        <fieldset className="text-sm">
          <legend className="lab-label">{tx('比较目标')}</legend>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            {PARETO_OBJECTIVES.map((o) => (
              <label key={o.id} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={objectives.includes(o.id)}
                  onChange={() => toggle(o.id)}
                />
                {tx(o.label)}
                {tx(o.direction === 'min' ? '（越小越好）' : '')}
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      {!objectives.length ? (
        <p className="mt-3 text-sm text-warning">{tx('请至少选择一个目标。')}</p>
      ) : (
        analysis && (
          <>
            <p className="mt-3 text-sm">
              {tx(`${analysis.rows.length}条记录参与比较，${front.length}条位于Pareto前沿。`)}
              {analysis.excluded.length > 0 && (
                <span className="text-muted-foreground">
                  {tx(
                    `另有${analysis.excluded.length}条缺少所选目标（如面积只属于搜索记录，稳健性只属于加评稳健性的坐标评价），未参与。`,
                  )}
                </span>
              )}
            </p>
            <div className="relative mt-2 overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead>
                  <tr className="border-b text-muted-foreground">
                    <th className="py-2">{tx('层')}</th>
                    <th>{tx('布局')}</th>
                    {analysis.objectives.map((o) => (
                      <th key={o.id}>{tx(o.label)}</th>
                    ))}
                    <th>
                      <span className="sr-only">{tx('操作')}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.rows.slice(0, 20).map((row) => {
                    const isHovered = hoveredId === row.item.id;
                    return (
                      <tr
                        key={row.item.id}
                        className={cn(
                          'border-b transition-colors last:border-0',
                          isHovered && 'bg-primary/10',
                        )}
                        onMouseEnter={() => setHoveredId(row.item.id)}
                        onMouseLeave={() =>
                          setHoveredId((cur) => (cur === row.item.id ? null : cur))
                        }
                      >
                        <td className="py-2 tabular-nums font-medium">{row.rank}</td>
                        <td>
                          {title(row.item)}
                          {row.dominated_by > 0 && (
                            <span className="block text-xs text-muted-foreground">
                              {tx(`被${row.dominated_by}条记录全面超过`)}
                            </span>
                          )}
                        </td>
                        {row.values.map((value, k) => (
                          <td key={k} className="tabular-nums">
                            {format(value, analysis.objectives[k].unit)}
                          </td>
                        ))}
                        <td>
                          <Button
                            size="sm"
                            variant="outline"
                            onFocus={() => setHoveredId(row.item.id)}
                            onBlur={() =>
                              setHoveredId((cur) => (cur === row.item.id ? null : cur))
                            }
                            onClick={() => onChoose(row.item.id)}
                          >
                            {tx('查看布局')}
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {analysis.rows.length > 20 && (
              <p className="mt-1 text-xs text-muted-foreground">
                {tx(`只列出前20条，共${analysis.rows.length}条。`)}
              </p>
            )}
          </>
        )
      )}
      <div className="mt-4 flex flex-wrap items-end justify-between gap-3 text-sm">
        <div className="flex flex-wrap gap-3">
          {(['横轴', '纵轴'] as const).map((name, k) => (
            <label key={name} className="lab-label">
              {tx(name)}
              <select
                className="lab-select"
                value={axes[k]}
                onChange={(event) =>
                  setAxes((a) =>
                    k
                      ? [a[0], event.target.value as ObjectiveId]
                      : [event.target.value as ObjectiveId, a[1]],
                  )
                }
              >
                {PARETO_OBJECTIVES.map((o) => (
                  <option key={o.id} value={o.id}>
                    {tx(o.label)}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
        {plotted.length > 0 && (
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-0.5 font-medium text-primary">
              <span aria-hidden="true">{cornerArrow}</span>
              {tx(cornerLabel)}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span aria-hidden="true" className="inline-block size-2.5 rounded-full bg-primary" />
              {tx('第1层（Pareto前沿）')}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="inline-block size-2.5 rounded-full border-2 border-primary bg-primary/25"
              />
              {tx('第2层')}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="inline-block size-2.5 rounded-full border border-primary/50 bg-transparent"
              />
              {tx('第3层及以后')}
            </span>
            {envelopePath && (
              <span className="inline-flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="inline-block w-4 border-t-2 border-dashed border-primary/70"
                />
                {tx('二维前沿包络')}
              </span>
            )}
          </div>
        )}
      </div>
      {plotted.length > 0 ? (
        <div className="mt-3 max-w-[680px] space-y-2" data-pareto-scatter>
          <div className="min-h-9 rounded-md border bg-muted/25 px-3 py-1.5 text-xs flex flex-wrap items-center justify-between gap-2">
            {activePoint ? (
              <>
                <span className="font-medium text-foreground">
                  {activeRank != null && (
                    <span className="mr-2 rounded bg-primary/15 px-1.5 py-0.5 font-mono text-[11px] text-primary">
                      #{activeRank}
                    </span>
                  )}
                  {title(activePoint.item)}
                </span>
                <span className="font-mono tabular-nums text-muted-foreground">
                  {tx(x.label)} {format(activePoint.v[x.id], x.unit)} · {tx(y.label)}{' '}
                  {format(activePoint.v[y.id], y.unit)}
                </span>
              </>
            ) : (
              <span className="text-muted-foreground">
                {tx('悬停或聚焦图上圆点与表格行可联动查看精确指标；点击圆点直接打开布局。')}
              </span>
            )}
          </div>
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="w-full rounded-lg border bg-background/50"
          >
            <title>{tx('两项目标的散点图，前沿方案以实心点表示')}</title>
            {xTicks.map((v, i) => (
              <g key={'xg' + i}>
                <line
                  x1={px(v)}
                  y1={T}
                  x2={px(v)}
                  y2={H - B}
                  stroke="currentColor"
                  strokeOpacity={i === 0 ? 0.32 : 0.1}
                  strokeDasharray={i === 0 ? undefined : '3 3'}
                />
                <text
                  x={px(v)}
                  y={H - B + 16}
                  fontSize="10.5"
                  textAnchor={i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle'}
                  fill="currentColor"
                  opacity=".72"
                >
                  {tickLabel(v, x.unit, xAxis.step)}
                </text>
              </g>
            ))}
            {yTicks.map((v, i) => (
              <g key={'yg' + i}>
                <line
                  x1={L}
                  y1={py(v)}
                  x2={W - R}
                  y2={py(v)}
                  stroke="currentColor"
                  strokeOpacity={i === 0 ? 0.32 : 0.1}
                  strokeDasharray={i === 0 ? undefined : '3 3'}
                />
                <text
                  x={L - 6}
                  y={py(v) + 3.5}
                  fontSize="10.5"
                  textAnchor="end"
                  fill="currentColor"
                  opacity=".72"
                >
                  {tickLabel(v, y.unit, yAxis.step)}
                </text>
              </g>
            ))}
            <text
              x={(L + W - R) / 2}
              y={H - 6}
              fontSize="11.5"
              fontWeight="500"
              textAnchor="middle"
              fill="currentColor"
            >
              {tx(x.label)}
              {x.direction === 'min' ? tx('（越小越好）') : ''}
            </text>
            {envelopePath && (
              <path
                d={envelopePath}
                fill="none"
                stroke="var(--primary)"
                strokeWidth={1.6}
                strokeDasharray="5 3"
                strokeOpacity={0.75}
              />
            )}
            {plotted.map((p) => {
              const rank = rankOf.get(p.item.id) ?? 3,
                isHovered = hoveredId === p.item.id,
                cx = px(p.v[x.id]),
                cy = py(p.v[y.id]),
                baseRadius = rank === 1 ? 5.2 : rank === 2 ? 4.3 : 3.5;
              return (
                <g
                  key={p.item.id}
                  className="cursor-pointer"
                  onMouseEnter={() => setHoveredId(p.item.id)}
                  onMouseLeave={() =>
                    setHoveredId((cur) => (cur === p.item.id ? null : cur))
                  }
                  onClick={() => onChoose(p.item.id)}
                >
                  <title>
                    {`${title(p.item)} · ${tx(x.label)} ${format(p.v[x.id], x.unit)} · ${tx(y.label)} ${format(p.v[y.id], y.unit)}`}
                  </title>
                  {(rank === 1 || isHovered) && (
                    <circle
                      cx={cx}
                      cy={cy}
                      r={isHovered ? baseRadius + 4.5 : baseRadius + 2.5}
                      fill="var(--primary)"
                      fillOpacity={isHovered ? 0.22 : 0.12}
                    />
                  )}
                  <circle
                    cx={cx}
                    cy={cy}
                    r={isHovered ? baseRadius + 1.5 : baseRadius}
                    fill={
                      rank === 1
                        ? 'var(--primary)'
                        : rank === 2
                          ? 'color-mix(in srgb, var(--primary) 28%, transparent)'
                          : 'transparent'
                    }
                    stroke="var(--primary)"
                    strokeWidth={isHovered ? 2.2 : rank <= 2 ? 1.6 : 1.2}
                    strokeOpacity={rank === 1 || isHovered ? 1 : rank === 2 ? 0.8 : 0.48}
                  />
                </g>
              );
            })}
          </svg>
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">
          {tx('当前条件下没有同时具有这两项目标的记录。')}
        </p>
      )}
      <p className="mt-1.5 text-xs text-muted-foreground">
        {tx('纵轴：')}
        {tx(y.label)}
        {tx('。实心点为所选全部目标下的第1层；点击打开记录。')}
      </p>
    </details>
  );
}
