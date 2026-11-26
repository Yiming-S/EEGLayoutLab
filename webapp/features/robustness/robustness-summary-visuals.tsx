"use client";

import { useLanguage } from "@/components/language-provider";
import type { EmpiricalSummary, StudyCase } from "@/contracts/robustness-study";

export const protocols = {
  noise_seeds: "定位噪声随机种子重复",
  grid_displacements: "候选网格位置偏移重复",
  heads: "跨头模评价（每案例一个头模）",
};

export const metricLabels: Record<string, string> = {
  field_relative: "场重建保留率",
  sensitivity_tail: "幅度保留率",
  localization_relative: "定位效用保留率",
  median_mm: "定位误差中位数",
  p90_mm: "定位误差P90",
  fixed_estimator_field_relative: "固定估计器场保留率",
};

export const nominalMetrics = [
  "field_relative",
  "sensitivity_tail",
  "localization_relative",
  "median_mm",
  "p90_mm",
];

export const trialMetrics = [
  "field_relative",
  "fixed_estimator_field_relative",
  "sensitivity_tail",
];

const isDistanceMetric = (metric: string) => metric.endsWith("_mm");
const scaleMetricValue = (value: number, metric: string) =>
  isDistanceMetric(metric) ? value : value * 100;

export const reading = (value: number | null | undefined, metric: string) =>
  value == null || !Number.isFinite(value)
    ? "无有效读数"
    : isDistanceMetric(metric)
      ? `${value.toFixed(4)} mm`
      : `${(value * 100).toFixed(4)}%`;

const compactReading = (value: number | null | undefined, metric: string) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : isDistanceMetric(metric)
      ? `${value.toFixed(2)} mm`
      : `${(value * 100).toFixed(1)}%`;

const hasFiniteSummary = (value?: EmpiricalSummary) =>
  Boolean(
    value &&
      value.n > 0 &&
      value.median != null &&
      Number.isFinite(value.median) &&
      value.p10 != null &&
      Number.isFinite(value.p10) &&
      value.p90 != null &&
      Number.isFinite(value.p90),
  );

const niceDistanceCeiling = (maxValue: number) => {
  if (!Number.isFinite(maxValue) || maxValue <= 0) return 4;
  const padded = maxValue * 1.12,
    magnitude = 10 ** Math.floor(Math.log10(padded)),
    normalized = padded / magnitude,
    step =
      [1, 1.2, 1.6, 2, 2.4, 3, 4, 5, 6, 8, 10].find(
        (item) => item >= normalized,
      ) ?? 10;
  return step * magnitude;
};

const formatAxisTick = (value: number, distance: boolean) => {
  const rounded = Math.abs(value) < 1e-9 ? 0 : value;
  if (!distance)
    return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}%`;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)} mm`;
};

export const collectCaseMetricSamples = (
  cases: StudyCase[],
  radiusMm: number,
  metrics: string[],
  selector: (entry: StudyCase, metric: string) => number | null | undefined,
): Record<string, number[]> => {
  const completed = cases.filter(
    (entry) =>
      entry.request.radius_mm === radiusMm &&
      entry.status === "completed" &&
      entry.summary !== null,
  );
  return Object.fromEntries(
    metrics.map((metric) => [
      metric,
      completed
        .map((entry) => selector(entry, metric))
        .filter(
          (item): item is number =>
            typeof item === "number" && Number.isFinite(item),
        ),
    ]),
  );
};

function MetricSubPanel({
  subtitle,
  metrics,
  values,
  caseSamples,
  distance,
}: {
  subtitle: string;
  metrics: string[];
  values: Record<string, EmpiricalSummary>;
  caseSamples?: Record<string, number[]>;
  distance: boolean;
}) {
  const { tx } = useLanguage();
  const finitePoints: number[] = [];
  for (const metric of metrics) {
    const summary = values[metric];
    if (hasFiniteSummary(summary)) {
      finitePoints.push(
        scaleMetricValue(summary.p10!, metric),
        scaleMetricValue(summary.median!, metric),
        scaleMetricValue(summary.p90!, metric),
      );
    }
    for (const sample of caseSamples?.[metric] ?? []) {
      if (Number.isFinite(sample))
        finitePoints.push(scaleMetricValue(sample, metric));
    }
  }
  const minObs = finitePoints.length ? Math.min(...finitePoints) : 0,
    maxObs = finitePoints.length ? Math.max(...finitePoints) : distance ? 20 : 100;
  const domainMin = distance
      ? minObs < 0
        ? -niceDistanceCeiling(Math.abs(minObs))
        : 0
      : minObs < 0
        ? Math.floor(minObs / 10) * 10
        : 0,
    domainMax = distance
      ? niceDistanceCeiling(maxObs)
      : maxObs > 100
        ? Math.ceil(maxObs / 10) * 10
        : 100;
  const span = Math.max(1e-9, domainMax - domainMin),
    padX = 8,
    trackWidth = 344,
    toX = (scaled: number) => padX + ((scaled - domainMin) / span) * trackWidth,
    ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => domainMin + span * ratio),
    bandClass = distance
      ? "fill-amber-500/20 stroke-amber-600/50 dark:stroke-amber-400/50"
      : "fill-primary/20 stroke-primary/50",
    whiskerClass = distance
      ? "stroke-amber-600 dark:stroke-amber-400"
      : "stroke-primary",
    markerClass = distance
      ? "fill-amber-600 stroke-background dark:fill-amber-400"
      : "fill-primary stroke-background",
    dotClass = distance
      ? "fill-amber-700/45 dark:fill-amber-300/45"
      : "fill-primary/45";
  return (
    <div
      className="space-y-2"
      data-distribution-unit={distance ? "mm" : "percent"}
    >
      <p className="text-xs font-medium text-muted-foreground">{tx(subtitle)}</p>
      <div className="space-y-1.5">
        {metrics.map((metric) => {
          const summary = values[metric],
            valid = hasFiniteSummary(summary),
            samples = (caseSamples?.[metric] ?? []).filter(Number.isFinite),
            label = tx(metricLabels[metric]);
          const p10Scaled = valid ? scaleMetricValue(summary.p10!, metric) : 0,
            medScaled = valid ? scaleMetricValue(summary.median!, metric) : 0,
            p90Scaled = valid ? scaleMetricValue(summary.p90!, metric) : 0,
            xLow = valid ? toX(Math.min(p10Scaled, p90Scaled)) : padX,
            xHigh = valid ? toX(Math.max(p10Scaled, p90Scaled)) : padX,
            xMed = valid ? toX(medScaled) : padX,
            ariaSummary = valid
              ? tx(
                  `${metricLabels[metric]}：中位数 ${reading(summary.median, metric)}，P10 ${reading(summary.p10, metric)}，P90 ${reading(summary.p90, metric)}（有效案例 ${summary.n}）`,
                )
              : `${label}: ${tx("无有效读数")}`;
          return (
            <div
              key={metric}
              className="grid items-center gap-2 text-xs sm:grid-cols-[minmax(140px,180px)_minmax(0,1fr)_minmax(150px,190px)]"
            >
              <div className="flex items-center justify-between gap-1.5 sm:justify-start">
                <span className="truncate font-medium text-foreground">
                  {label}
                </span>
                <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                  n={summary?.n ?? 0}
                </span>
              </div>
              <svg
                viewBox="0 0 360 28"
                className="h-7 w-full overflow-visible"
                aria-label={ariaSummary}
              >
                <title>{ariaSummary}</title>
                {ticks.map((tick, tickIndex) => {
                  const x = toX(tick);
                  return (
                    <line
                      key={tickIndex}
                      x1={x}
                      x2={x}
                      y1={3}
                      y2={25}
                      className="stroke-border"
                      strokeWidth={1}
                    />
                  );
                })}
                {domainMin < 0 && domainMax > 0 && (
                  <line
                    x1={toX(0)}
                    x2={toX(0)}
                    y1={2}
                    y2={26}
                    className="stroke-foreground/35"
                    strokeWidth={1}
                    strokeDasharray="2 2"
                  />
                )}
                <line
                  x1={padX}
                  x2={padX + trackWidth}
                  y1={14}
                  y2={14}
                  className="stroke-border"
                  strokeWidth={1}
                  strokeDasharray={valid ? undefined : "3 3"}
                />
                {valid && (
                  <>
                    <rect
                      x={xLow}
                      y={8}
                      width={Math.max(2, xHigh - xLow)}
                      height={12}
                      rx={3}
                      className={bandClass}
                      strokeWidth={1}
                    />
                    <line
                      x1={xLow}
                      x2={xHigh}
                      y1={14}
                      y2={14}
                      className={whiskerClass}
                      strokeWidth={1.5}
                    />
                    <line
                      x1={xLow}
                      x2={xLow}
                      y1={7}
                      y2={21}
                      className={whiskerClass}
                      strokeWidth={1.75}
                    />
                    <line
                      x1={xHigh}
                      x2={xHigh}
                      y1={7}
                      y2={21}
                      className={whiskerClass}
                      strokeWidth={1.75}
                    />
                    {samples.map((sample, sampleIndex) => (
                      <circle
                        key={sampleIndex}
                        cx={toX(scaleMetricValue(sample, metric))}
                        cy={14}
                        r={2.4}
                        className={dotClass}
                      />
                    ))}
                    <polygon
                      points={`${xMed},5 ${xMed + 5},14 ${xMed},23 ${xMed - 5},14`}
                      className={markerClass}
                      strokeWidth={1.25}
                    />
                  </>
                )}
              </svg>
              <div className="text-right font-mono text-[11px] tabular-nums text-muted-foreground">
                {valid ? (
                  <span>
                    {compactReading(summary.p10, metric)} ·{" "}
                    <strong className="font-semibold text-foreground">
                      {compactReading(summary.median, metric)}
                    </strong>{" "}
                    · {compactReading(summary.p90, metric)}
                  </span>
                ) : (
                  <span>{tx("无有效读数")}</span>
                )}
              </div>
            </div>
          );
        })}
        <div className="grid items-center gap-2 pt-0.5 text-[10px] text-muted-foreground sm:grid-cols-[minmax(140px,180px)_minmax(0,1fr)_minmax(150px,190px)]">
          <span className="hidden sm:inline" />
          <div className="flex justify-between font-mono tabular-nums">
            {ticks.map((tick, index) => (
              <span key={index}>{formatAxisTick(tick, distance)}</span>
            ))}
          </div>
          <span className="hidden text-right font-mono sm:inline">
            P10 · {tx("中位数")} · P90
          </span>
        </div>
      </div>
    </div>
  );
}

export function SummaryDistributionChart({
  values,
  metrics,
  caseSamples,
}: {
  values: Record<string, EmpiricalSummary>;
  metrics: string[];
  caseSamples?: Record<string, number[]>;
}) {
  const { tx } = useLanguage();
  const hasAnyValid = metrics.some((metric) => hasFiniteSummary(values[metric]));
  const retentionMetrics = metrics.filter((metric) => !isDistanceMetric(metric)),
    distanceMetrics = metrics.filter((metric) => isDistanceMetric(metric));
  const hasSampleDots = metrics.some(
    (metric) => (caseSamples?.[metric]?.length ?? 0) > 0,
  );
  if (!hasAnyValid) {
    return (
      <div
        className="rounded-xl border border-dashed bg-muted/25 px-3.5 py-2.5 text-xs text-muted-foreground"
        data-summary-distribution="empty"
      >
        {tx(
          "暂无已完成案例的有效读数，运行完成后将显示中位数与 P10–P90 分布图。",
        )}
      </div>
    );
  }
  return (
    <div
      className="space-y-3 rounded-xl border border-border/75 bg-muted/25 p-3.5"
      data-summary-distribution="ready"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold text-foreground">
          {tx("中位数与 P10–P90 分布图")}
        </span>
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block h-2.5 w-5 rounded-sm border border-primary/60 bg-primary/20"
            />
            {tx("P10–P90 区间")}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="inline-block h-2.5 w-2.5 rotate-45 bg-primary"
            />
            {tx("中位数")}
          </span>
          {hasSampleDots && (
            <span className="inline-flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="inline-block h-2 w-2 rounded-full bg-primary/50"
              />
              {tx("单案例值")}
            </span>
          )}
        </div>
      </div>
      {retentionMetrics.length > 0 && (
        <MetricSubPanel
          subtitle="保留率指标（%，越高越优）"
          metrics={retentionMetrics}
          values={values}
          caseSamples={caseSamples}
          distance={false}
        />
      )}
      {distanceMetrics.length > 0 && (
        <MetricSubPanel
          subtitle="定位误差指标（mm，越低越优）"
          metrics={distanceMetrics}
          values={values}
          caseSamples={caseSamples}
          distance={true}
        />
      )}
    </div>
  );
}

export function SummaryTable({
  title,
  values,
  metrics,
  countLabel = "有效案例数",
  showDistribution = false,
  caseSamples,
}: {
  title: string;
  values: Record<string, EmpiricalSummary>;
  metrics: string[];
  countLabel?: string;
  showDistribution?: boolean;
  caseSamples?: Record<string, number[]>;
}) {
  const { tx } = useLanguage();
  return (
    <section className="space-y-3">
      <h4 className="text-sm font-semibold">{tx(title)}</h4>
      {showDistribution && (
        <SummaryDistributionChart
          values={values}
          metrics={metrics}
          caseSamples={caseSamples}
        />
      )}
      <div className="lab-table-frame">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead>
            <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
              <th className="px-4 py-2.5">{tx("指标")}</th>
              <th className="px-3 py-2.5">{tx(countLabel)}</th>
              <th className="px-3 py-2.5">{tx("中位数")}</th>
              <th className="px-3 py-2.5">P10</th>
              <th className="px-4 py-2.5">P90</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((metric) => {
              const value = values[metric];
              return (
                <tr
                  key={metric}
                  className="border-b border-border/65 transition-colors last:border-0 hover:bg-primary/[0.03]"
                >
                  <th className="px-4 py-2.5 font-normal">
                    {tx(metricLabels[metric])}
                  </th>
                  <td className="px-3 py-2.5 font-mono tabular-nums">
                    {value?.n ?? 0}
                  </td>
                  {(["median", "p10", "p90"] as const).map((key) => (
                    <td key={key} className="px-3 py-2.5 font-mono tabular-nums">
                      {tx(reading(value?.[key], metric))}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
