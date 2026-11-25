"use client";
/* oxlint-disable next/no-html-link-for-pages -- preserve established local navigation */
import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SiteHeader } from "@/components/site-header";
import { RuntimeMessage } from "@/components/runtime-message";
import { useLanguage } from "@/components/language-provider";
import type { EmpiricalSummary, StudyCase, StudyProtocol } from "@/contracts/robustness-study";
import { useRobustnessController } from "./use-robustness-controller";
import { listHeadPackages, type HeadPackageEntry } from "@/client/robustness";
import { NOISE_MODEL_PRESETS, conductivityScenarioLabel, noiseModelLabel } from "../../contracts/scientific-options.mjs";
import { EvaluationConditions } from "@/features/conditions/evaluation-conditions";
import type { NoiseModel } from "@/lib/design-decision";
import { useStudyDesignDraft } from "./use-study-design-draft";
import { RecordDesignPicker } from "./record-design-picker";
import { useStudyExport } from "./use-study-export";
import { coordinateSourceFiles } from "@/contracts/coordinate-source.mjs";
import {
  createStudyInput,
  studyCanCancel,
  studyPrimaryAction,
  studyStatusLabel,
  studyCaseStatusLabel,
  STUDY_CASE_LIMIT,
  STUDY_RADII,
  fillHeads,
  generateAllHeadCases,
  generateConsecutiveSeedCases,
  generateRadiusSeedGridCases,
  type CaseDraft,
} from "./robustness-draft";
import { FilePicker } from "@/components/ui/file-picker";

const protocols = {
  noise_seeds: "定位噪声随机种子重复",
  grid_displacements: "候选网格位置偏移重复",
  heads: "跨头模评价（每案例一个头模）",
};
const metricLabels: Record<string, string> = {
  field_relative: "场重建保留率",
  sensitivity_tail: "幅度保留率",
  localization_relative: "定位效用保留率",
  median_mm: "定位误差中位数",
  p90_mm: "定位误差P90",
  fixed_estimator_field_relative: "固定估计器场保留率",
};
const nominalMetrics = [
  "field_relative",
  "sensitivity_tail",
  "localization_relative",
  "median_mm",
  "p90_mm",
];
const trialMetrics = ["field_relative", "fixed_estimator_field_relative", "sensitivity_tail"];
const isDistanceMetric = (metric: string) => metric.endsWith("_mm");
const scaleMetricValue = (value: number, metric: string) =>
  isDistanceMetric(metric) ? value : value * 100;
const reading = (value: number | null | undefined, metric: string) =>
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
    step = [1, 1.2, 1.6, 2, 2.4, 3, 4, 5, 6, 8, 10].find((item) => item >= normalized) ?? 10;
  return step * magnitude;
};
const formatAxisTick = (value: number, distance: boolean) => {
  const rounded = Math.abs(value) < 1e-9 ? 0 : value;
  if (!distance) return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}%`;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)} mm`;
};
const collectCaseMetricSamples = (
  cases: StudyCase[],
  radiusMm: number,
  metrics: string[],
  selector: (entry: StudyCase, metric: string) => number | null | undefined,
): Record<string, number[]> => {
  const completed = cases.filter(
    (entry) => entry.request.radius_mm === radiusMm && entry.status === "completed" && entry.summary !== null,
  );
  return Object.fromEntries(
    metrics.map((metric) => [
      metric,
      completed
        .map((entry) => selector(entry, metric))
        .filter((item): item is number => typeof item === "number" && Number.isFinite(item)),
    ]),
  );
};
const download = (id: string, text: string) => {
  const href = URL.createObjectURL(new Blob([text], { type: "application/json" })),
    anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = `eeg-robustness-study-${id}.json`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
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
      if (Number.isFinite(sample)) finitePoints.push(scaleMetricValue(sample, metric));
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
    <div className="space-y-2" data-distribution-unit={distance ? "mm" : "percent"}>
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
                <span className="truncate font-medium text-foreground">{label}</span>
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

function SummaryDistributionChart({
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
  const hasSampleDots = metrics.some((metric) => (caseSamples?.[metric]?.length ?? 0) > 0);
  if (!hasAnyValid) {
    return (
      <div
        className="rounded-xl border border-dashed bg-muted/25 px-3.5 py-2.5 text-xs text-muted-foreground"
        data-summary-distribution="empty"
      >
        {tx("暂无已完成案例的有效读数，运行完成后将显示中位数与 P10–P90 分布图。")}
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

function SummaryTable({
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
                <tr key={metric} className="border-b border-border/65 transition-colors last:border-0 hover:bg-primary/[0.03]">
                  <th className="px-4 py-2.5 font-normal">{tx(metricLabels[metric])}</th>
                  <td className="px-3 py-2.5 font-mono tabular-nums">{value?.n ?? 0}</td>
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

export default function RobustnessWorkspace() {
  const { tx, date } = useLanguage(),
    controller = useRobustnessController();
  const input = useStudyDesignDraft(controller.handoff, controller.study?.id);
  const { design, title, setTitle } = input;
  const [notes, setNotes] = useState("");
  const [protocol, setProtocol] = useState<StudyProtocol>("noise_seeds"),
    [cases, setCases] = useState<CaseDraft[]>([{ seed: "42", radius: "6" }]),
    [batchStartSeed, setBatchStartSeed] = useState("42");
  const [noiseModelId, setNoiseModelId] = useState("iid"),
    [scenarioId, setScenarioId] = useState("");
  const [formError, setFormError] = useState("");
  const [heads, setHeads] = useState<HeadPackageEntry[] | null>(null),
    [headsError, setHeadsError] = useState("");
  useEffect(() => {
    if (protocol !== "heads" || heads || headsError) return;
    const abort = new AbortController();
    listHeadPackages(abort.signal)
      .then(({ heads: found }) => {
        setHeads(found);
        setCases((rows) => fillHeads(rows, found));
      })
      .catch((caught) => {
        if (!abort.signal.aborted) setHeadsError(caught instanceof Error && caught.message ? caught.message : "头模列表读取失败");
      });
    return () => abort.abort();
  }, [protocol, heads, headsError]);
  const exporting = useStudyExport(controller.study?.id, controller.exportText, download);
  const study = controller.study,
    disabled = controller.busy || controller.uncertain;
  const create = async () => {
    setFormError("");
    try {
      const noiseModel = NOISE_MODEL_PRESETS.find((preset) => preset.id === noiseModelId)?.value as NoiseModel | undefined;
      await controller.create(createStudyInput(design, protocol, cases, title, notes, noiseModel, protocol === "noise_seeds" ? scenarioId || undefined : undefined));
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : "研究草稿无法保存");
    }
  };
  return (
    <main className="lab-page">
      <SiteHeader current="robustness" />
      <div className="lab-container space-y-5 pb-10">
        <header className="border-b border-border pt-7 pb-5">
          <h1 className="text-2xl font-semibold tracking-[-0.028em] sm:text-[1.65rem]">{tx("稳健性研究")}</h1>
          <p className="mt-1.5 max-w-4xl text-sm text-muted-foreground">
            {tx("可复现的重复评估：按明确的种子与偏移参数重复原评价协议，逐项保存请求、结果及失败原因。")}
          </p>
        </header>
        <section className="lab-panel space-y-3.5" aria-label={tx("本浏览器的稳健性研究")}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">{tx("已保存研究")}</h2>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={controller.busy}
                onClick={() => void controller.refreshDirectory()}
              >
                {tx("刷新研究目录")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={controller.busy}
                onClick={controller.newDraft}
              >
                {tx("编辑新的研究草稿")}
              </Button>
            </div>
          </div>
          <label className="lab-label">
            {tx("选择已保存研究")}
            <select
              className="lab-select"
              aria-label={tx("选择已保存研究")}
              value={study?.id ?? ""}
              disabled={controller.busy}
              onChange={(event) => {
                if (event.target.value) void controller.open(event.target.value);
              }}
            >
              <option value="">{tx("选择研究以读取状态")}</option>
              {controller.directory.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.title} · {tx(studyStatusLabel(entry.status))} · {entry.completed_cases}/
                  {entry.case_count}
                </option>
              ))}
            </select>
          </label>
          {controller.notice && <p className="text-sm text-ink-soft">{tx(controller.notice)}</p>}
          {controller.error && (
            <p role="alert" className="text-sm text-danger">
              <RuntimeMessage message={controller.error} />
            </p>
          )}
          {controller.uncertain && (
            <p className="text-sm text-warning">
              {tx("操作结果待核对，写入按钮已暂停。重新读取当前研究，或刷新目录并打开已保存研究。")}
            </p>
          )}
          {controller.busy && <output aria-live="polite" className="text-sm text-primary">{tx("正在提交研究操作…")}</output>}
          {controller.loading && <output aria-live="polite" className="text-sm text-muted-foreground">{tx("正在读取研究…")}</output>}
        </section>
        {!study && !controller.loading && (
          <section className="lab-panel space-y-4" aria-label={tx("创建稳健性研究草稿")}>
            <h2 className="text-lg font-semibold">{tx("创建研究草稿")}</h2>
            <div className="grid gap-4 rounded-xl border border-border/70 bg-muted/30 p-4 md:grid-cols-2">
              <RecordDesignPicker disabled={disabled} onChoose={(chosen) => { setFormError(""); input.chooseDesign(chosen); }} />
              <label className="lab-label">
                {tx("导入64电极CSV或JSON")}
                <FilePicker
                  accept=".csv,.json,application/json,text/csv"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (!file) return;
                    setFormError("");
                    void input.readFile(file);
                  }}
                />
              </label>
            </div>
            {design && (
              <div className="rounded-xl border border-primary/25 bg-primary/[0.035] p-3.5 text-sm" data-study-design>
                <p className="font-medium">
                  {design.name} · 64 {tx("电极")} · {new Set(design.region_indices).size} {tx("区")}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {tx("使用导入的原始坐标；名称和来源说明独立保存。")}
                </p>
                <details className="group/design mt-2">
                  <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-primary select-none [&::-webkit-details-marker]:hidden">
                    <span>{tx("查看研究输入坐标与名称")}</span>
                    <ChevronDown aria-hidden className="size-3.5 transition-transform group-open/design:rotate-180" />
                  </summary>
                  <div className="lab-table-frame mt-2.5 max-h-60">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr className="border-b border-border/75 bg-muted/55 font-semibold text-ink-soft">
                          <th className="px-3 py-2">{tx("电极")}</th>
                          <th className="px-2.5 py-2">{tx("区域")}</th>
                          <th className="px-2.5 py-2">X (mm)</th>
                          <th className="px-2.5 py-2">Y (mm)</th>
                          <th className="px-3 py-2">Z (mm)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {design.xyz_mm.map((point, index) => (
                          <tr key={index} className="border-b border-border/60 last:border-0">
                            <td className="px-3 py-1.5 font-medium">{design.electrode_names?.[index] ?? `E${index + 1}`}</td>
                            <td className="px-2.5 py-1.5 font-mono tabular-nums">{design.region_indices[index]}</td>
                            {point.map((value, axis) => (
                              <td key={axis} className="px-2.5 py-1.5 font-mono tabular-nums">{value}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </div>
            )}
            <div className="grid gap-4 md:grid-cols-2">
              <label className="lab-label">
                {tx("研究名称")}
                <input
                  className="lab-input"
                  maxLength={200}
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </label>
              <label className="lab-label">
                {tx("重复评估协议")}
                <select
                  className="lab-select"
                  aria-label={tx("重复评估协议")}
                  value={protocol}
                  onChange={(event) => {
                    const next = event.target.value as StudyProtocol;
                    setProtocol(next);
                    if (next === "noise_seeds")
                      setCases((rows) => rows.map((row) => ({ ...row, radius: rows[0].radius })));
                    if (next === "heads") setCases((rows) => fillHeads(rows, heads ?? []));
                  }}
                >
                  {Object.entries(protocols).map(([value, label]) => (
                    <option key={value} value={value}>
                      {tx(label)}
                    </option>
                  ))}
                </select>
              </label>
              <EvaluationConditions className="md:col-span-2 md:grid-cols-2" action="study" protocol={protocol}
                values={{ noiseModelId, scenarioId }}
                onChange={(patch) => {
                  if (patch.noiseModelId !== undefined) setNoiseModelId(patch.noiseModelId);
                  if (patch.scenarioId !== undefined) setScenarioId(patch.scenarioId);
                }} />
            </div>
            <p className="text-xs leading-5 text-muted-foreground">
              {tx(
                protocol === "noise_seeds"
                  ? "改变定位噪声随机种子；固定原坐标及半径参数，每案例仍使用原16次定位噪声重复。"
                  : protocol === "heads"
                    ? "每案例把同一坐标经MNI映射到一个头模后评价，参考布局同样映射；电导率取默认值。案例构成跨头模分布，不代替Ernie生产结果。"
                    : "每案例执行原4次网格偏移；仅支持候选前向库中的64点，半径使用毫米。",
              )}
            </p>
            {protocol === "heads" && heads?.length === 0 && (
              <p className="text-sm text-destructive">{tx("尚无已预计算的头模包")}</p>
            )}
            {protocol === "heads" && headsError && (
              <div role="alert" className="flex flex-wrap items-center gap-3 text-sm text-danger">
                <RuntimeMessage message={headsError} />
                <Button type="button" size="sm" variant="outline" onClick={() => setHeadsError("")}>
                  {tx("重新读取头模列表")}
                </Button>
              </div>
            )}
            {protocol !== "grid_displacements" && (
              <label className="lab-label max-w-xs">
                {tx("固定半径参数（mm）")}
                <select
                  className="lab-select"
                  aria-label={tx("固定半径参数（mm）")}
                  value={cases[0].radius}
                  onChange={(event) =>
                    setCases((rows) => rows.map((row) => ({ ...row, radius: event.target.value })))
                  }
                >
                  {STUDY_RADII.map((radius) => (
                    <option key={radius} value={radius}>
                      {radius}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {protocol === "heads" && (
              <label className="lab-label max-w-xs">
                {tx("所有头模共用的随机种子")}
                <input
                  className="lab-input font-mono tabular-nums"
                  type="number"
                  aria-label={tx("所有头模共用的随机种子")}
                  min={0}
                  max={9999}
                  step={1}
                  value={cases[0].seed}
                  onChange={(event) =>
                    setCases((rows) => rows.map((row) => ({ ...row, seed: event.target.value })))
                  }
                />
              </label>
            )}
            <div
              className="rounded-xl border border-border/75 bg-muted/30 p-3.5 space-y-2.5"
              data-batch-case-generator
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{tx("快速批量生成案例")}</span>
                  <span className="rounded-full border border-border/80 bg-card px-2.5 py-0.5 font-mono text-xs text-muted-foreground tabular-nums">
                    {tx(`已列 ${cases.length}/${STUDY_CASE_LIMIT} 个案例`)}
                  </span>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={cases.length <= 1}
                  onClick={() => {
                    setFormError("");
                    setCases((rows) => {
                      const baseRow = {
                        seed: rows[0]?.seed ?? "42",
                        radius: rows[0]?.radius ?? "6",
                      };
                      return protocol === "heads" ? fillHeads([baseRow], heads ?? []) : [baseRow];
                    });
                  }}
                >
                  {tx("重置为单案例")}
                </Button>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {protocol !== "heads" ? (
                  <>
                    <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                      <span>{tx("起始种子")}</span>
                      <input
                        className="lab-input mt-0 h-8 min-h-8 w-24 px-2 py-1 font-mono text-xs tabular-nums"
                        type="number"
                        aria-label={tx("批量生成起始种子")}
                        min={0}
                        max={9999}
                        step={1}
                        value={batchStartSeed}
                        onChange={(event) => setBatchStartSeed(event.target.value)}
                      />
                    </label>
                    {([4, 8, 12] as const).map((count) => (
                      <Button
                        key={count}
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setFormError("");
                          setCases(
                            generateConsecutiveSeedCases(
                              batchStartSeed,
                              count,
                              cases[0]?.radius ?? "6",
                            ),
                          );
                        }}
                      >
                        {tx(`生成${count}个连续种子`)}
                      </Button>
                    ))}
                    {protocol === "grid_displacements" && (
                      <>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setFormError("");
                            setCases(generateRadiusSeedGridCases(batchStartSeed, 2));
                          }}
                        >
                          {tx("3种半径×2种子（6案例）")}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setFormError("");
                            setCases(generateRadiusSeedGridCases(batchStartSeed, 4));
                          }}
                        >
                          {tx("3种半径×4种子（12案例）")}
                        </Button>
                      </>
                    )}
                  </>
                ) : (
                  <>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={!heads?.length}
                      onClick={() => {
                        setFormError("");
                        setCases(
                          generateAllHeadCases(
                            cases[0]?.seed ?? "42",
                            cases[0]?.radius ?? "6",
                            heads ?? [],
                          ),
                        );
                      }}
                    >
                      {tx("填入全部可用头模")}
                    </Button>
                    <span className="text-xs text-muted-foreground">
                      {tx("按当前共用随机种子与固定半径一键填入可用头模（最多12个）。")}
                    </span>
                  </>
                )}
              </div>
            </div>
            <div className="lab-table-frame">
              <table className="w-full min-w-[420px] text-left text-sm">
                <thead>
                  <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                    <th className="px-4 py-2.5">{tx("案例")}</th>
                    {protocol === "heads" && <th className="px-3 py-2.5">{tx("头模")}</th>}
                    <th className="px-3 py-2.5">{tx("随机种子")}</th>
                    <th className="px-3 py-2.5">{tx("半径参数")} (mm)</th>
                    <th className="px-4 py-2.5">{tx("操作")}</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((entry, index) => (
                    <tr key={index} className="border-b border-border/65 last:border-0">
                      <th className="px-4 py-2 font-mono font-normal tabular-nums">{index + 1}</th>
                      {protocol === "heads" && (
                        <td className="px-3 py-2">
                          <select
                            className="lab-select mt-0"
                            aria-label={`${tx("案例")} ${index + 1} ${tx("头模")}`}
                            value={entry.head ?? ""}
                            onChange={(event) =>
                              setCases((rows) =>
                                rows.map((row, rowIndex) =>
                                  rowIndex === index ? { ...row, head: event.target.value } : row,
                                ),
                              )
                            }
                          >
                            <option value="">{tx("选择头模")}</option>
                            {(heads ?? []).map((head) => (
                              <option key={head.head_id} value={head.head_id}>
                                {head.head_id}
                                {head.dataset ? ` · ${head.dataset}` : ""}
                              </option>
                            ))}
                          </select>
                        </td>
                      )}
                      <td className="px-3 py-2">
                        <input
                          className="lab-input mt-0 font-mono tabular-nums"
                          type="number"
                          aria-label={`${tx("案例")} ${index + 1} ${tx("随机种子")}`}
                          disabled={protocol === "heads"}
                          min={0}
                          max={9999}
                          step={1}
                          value={entry.seed}
                          onChange={(event) =>
                            setCases((rows) =>
                              rows.map((row, rowIndex) =>
                                rowIndex === index ? { ...row, seed: event.target.value } : row,
                              ),
                            )
                          }
                        />
                      </td>
                      <td className="px-3 py-2">
                        <select
                          className="lab-select mt-0"
                          aria-label={`${tx("案例")} ${index + 1} ${tx("半径参数")} (mm)`}
                          disabled={protocol !== "grid_displacements"}
                          value={entry.radius}
                          onChange={(event) =>
                            setCases((rows) =>
                              rows.map((row, rowIndex) =>
                                rowIndex === index ? { ...row, radius: event.target.value } : row,
                              ),
                            )
                          }
                        >
                          {STUDY_RADII.map((radius) => (
                            <option key={radius} value={radius}>
                              {radius}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-4 py-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          disabled={cases.length === 1}
                          aria-label={`${tx("删除案例")} ${index + 1}`}
                          onClick={() =>
                            setCases((rows) => rows.filter((_, rowIndex) => rowIndex !== index))
                          }
                        >
                          {tx("删除")}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={
                cases.length >= STUDY_CASE_LIMIT ||
                (protocol === "heads" && cases.length >= (heads?.length ?? 0))
              }
              onClick={() =>
                setCases((rows) => {
                  if (protocol === "heads") return fillHeads([...rows, { seed: rows[0].seed, radius: rows[0].radius }], heads ?? []);
                  const used = new Set(rows.map((row) => Number(row.seed)));
                  let next = 0;
                  while (used.has(next)) next++;
                  return [...rows, { seed: String(next), radius: rows[0].radius }];
                })
              }
            >
              {tx("添加明确案例")}
            </Button>
            <label className="lab-label">
              {tx("研究备注")}
              <textarea
                className="lab-input min-h-24"
                maxLength={2000}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </label>
            <p className="text-xs text-muted-foreground">
              {tx("每项研究最多12个案例。保存草稿后，点击开始才提交计算。")}
            </p>
            {(formError || input.error) && (
              <p role="alert" className="text-sm text-danger">
                <RuntimeMessage message={formError || input.error} />
              </p>
            )}
            <Button type="button" disabled={disabled || input.loading || !design} onClick={() => void create()}>
              {tx(controller.busy ? "正在保存研究草稿…" : "保存研究草稿")}
            </Button>
          </section>
        )}
        {study && (
          <>
            <section className="lab-panel space-y-4" aria-label={tx("当前稳健性研究")}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold">{study.title}</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {tx(protocols[study.protocol])} · {tx(noiseModelLabel(study.noise_model))}{study.conductivity_scenario && <> · {tx(conductivityScenarioLabel(study.conductivity_scenario))}</>} · {date(study.created_at, true)}
                  </p>
                </div>
                <output className="rounded-full bg-primary/12 px-3 py-1 text-xs font-semibold text-primary ring-1 ring-inset ring-primary/22" aria-live="polite">
                  {tx(studyStatusLabel(study.status))}
                </output>
              </div>
              {study.notes && <p className="whitespace-pre-wrap text-sm leading-6">{study.notes}</p>}
              {study.cancel_requested && <p className="text-sm text-warning">{tx("取消意图已保存；恢复操作只保存已有结果并完成取消。")}</p>}
              <details className="group/input rounded-xl border border-border/75 bg-muted/25 p-3.5">
                <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium select-none [&::-webkit-details-marker]:hidden">
                  <span>{tx("查看研究输入坐标与名称")}</span>
                  <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/input:rotate-180" />
                </summary>
                <p className="mt-2.5 text-sm font-medium">{study.design.name} · Ernie · mm</p>
                {study.annotation.source_metadata && <p className="mt-1 text-xs text-muted-foreground">{coordinateSourceFiles(study.annotation.source_metadata)}</p>}
                <div className="lab-table-frame mt-3 max-h-64">
                  <table className="w-full min-w-[560px] text-left text-xs">
                    <thead>
                      <tr className="border-b border-border/75 bg-muted/55 font-semibold text-ink-soft">
                        <th className="px-3 py-2">{tx("电极")}</th>
                        <th className="px-2.5 py-2">{tx("区域")}</th>
                        <th className="px-2.5 py-2">X (mm)</th>
                        <th className="px-2.5 py-2">Y (mm)</th>
                        <th className="px-3 py-2">Z (mm)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {study.design.xyz_mm.map((point, index) => (
                        <tr key={index} className="border-b border-border/60 last:border-0">
                          <td className="px-3 py-1.5 font-medium">{study.annotation.electrode_names?.[index] ?? `E${index + 1}`}</td>
                          <td className="px-2.5 py-1.5 font-mono tabular-nums">{study.design.region_indices[index]}</td>
                          {point.map((value, axis) => <td key={axis} className="px-2.5 py-1.5 font-mono tabular-nums">{value}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
              <p className="inline-block max-w-full truncate rounded-md bg-muted/65 px-2.5 py-1 font-mono text-xs text-muted-foreground">
                {study.id} · eeg-robustness-study/1 · {tx("版本")} {study.revision}
              </p>
              <p className="text-xs leading-5 text-muted-foreground">
                {tx(
                  study.protocol === "heads"
                    ? "本研究描述所列头模上这批案例的经验分布；映射后被拒绝的头模计为失败案例。中位数、P10和P90按案例计算，使用第7型线性插值。"
                    : "本研究描述Ernie头模内这批案例的经验分布。中位数、P10和P90按案例计算，使用第7型线性插值。",
                )}
              </p>
              <p className="text-xs leading-5 text-muted-foreground">
                {tx("服务重启后，后续案例等待明确恢复。原队列已接受的单个案例保留其队列状态。")}
              </p>
              <div className="flex flex-wrap gap-2">
                {studyPrimaryAction(study.status) && (
                  <Button
                    type="button"
                    size="sm"
                    disabled={disabled}
                    onClick={() => void controller.act(studyPrimaryAction(study.status)!)}
                  >
                    {tx(study.status === "draft" ? "开始此研究" : study.cancel_requested ? "保存已有结果并完成取消" : "继续后续案例")}
                  </Button>
                )}
                {studyCanCancel(study.status) && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={disabled}
                    onClick={() => void controller.act("cancel")}
                  >
                    {tx("取消此研究")}
                  </Button>
                )}
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={controller.busy}
                  onClick={controller.reload}
                >
                  {tx("重新读取研究状态")}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={exporting.busy || controller.busy}
                  onClick={() => void exporting.run()}
                >
                  {tx(exporting.busy ? "正在导出研究…" : "下载完整研究JSON")}
                </Button>
              </div>
              {controller.connection !== "connected" && (
                <p className="text-sm text-warning">
                  {tx(
                    controller.connection === "reconnecting"
                      ? "正在重新连接研究状态…"
                      : "状态读取已暂停，请重新读取研究。",
                  )}
                </p>
              )}
              {study.last_error && (
                <output className="block text-sm text-warning">
                  <RuntimeMessage message={study.last_error.message} />
                </output>
              )}
              {exporting.error && (
                <p role="alert" className="text-sm text-danger">
                  <RuntimeMessage message={exporting.error} />
                </p>
              )}
              <dl className="grid gap-2.5 text-sm sm:grid-cols-5">
                {[
                  ["全部案例", study.aggregation.case_count],
                  ["完成案例", study.aggregation.completed_cases],
                  ["失败案例", study.aggregation.failed_cases],
                  ["取消案例", study.aggregation.cancelled_cases],
                  ["未结束案例", study.aggregation.pending_cases],
                ].map(([label, value]) => (
                  <div key={String(label)} className="lab-subpanel py-2.5">
                    <dt className="text-xs text-muted-foreground">{tx(String(label))}</dt>
                    <dd className="mt-1 font-mono text-xl font-semibold tabular-nums">{value}</dd>
                  </div>
                ))}
              </dl>
            </section>
            <section className="lab-panel space-y-4" aria-label={tx("逐案例结果")}>
              <h3 className="text-lg font-semibold">{tx("逐案例结果")}</h3>
              <div className="lab-table-frame">
                <table className="w-full min-w-[650px] text-left text-sm">
                  <thead>
                    <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                      <th className="px-4 py-2.5">{tx("案例")}</th>
                      {study.protocol === "heads" && <th className="px-3 py-2.5">{tx("头模")}</th>}
                      <th className="px-3 py-2.5">{tx("随机种子")}</th>
                      <th className="px-3 py-2.5">{tx("半径参数")} (mm)</th>
                      <th className="px-3 py-2.5">{tx("状态")}</th>
                      {study.protocol === "heads" ? (
                        <>
                          <th className="px-3 py-2.5">{tx(metricLabels.field_relative)}</th>
                          <th className="px-3 py-2.5">{tx(metricLabels.localization_relative)}</th>
                          <th className="px-4 py-2.5">{tx(metricLabels.median_mm)}</th>
                        </>
                      ) : (
                        <>
                          <th className="px-3 py-2.5">{tx("有效偏移次数")}</th>
                          <th className="px-4 py-2.5">{tx("几何拒绝次数")}</th>
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {study.cases.map((entry) => (
                      <tr key={entry.index} className="border-b border-border/65 transition-colors last:border-0 hover:bg-primary/[0.03]">
                        <th className="px-4 py-2.5 font-mono font-normal tabular-nums">{entry.index + 1}</th>
                        {study.protocol === "heads" && <td className="px-3 py-2.5 font-mono text-xs">{entry.request.head_id}</td>}
                        <td className="px-3 py-2.5 font-mono tabular-nums">{entry.request.seed}</td>
                        <td className="px-3 py-2.5 font-mono tabular-nums">{entry.request.radius_mm}</td>
                        <td className="px-3 py-2.5">{tx(studyCaseStatusLabel(entry.status))}</td>
                        {study.protocol === "heads" ? (
                          ["field_relative", "localization_relative", "median_mm"].map((metric) => (
                            <td key={metric} className="px-3 py-2.5 font-mono tabular-nums">
                              {entry.summary ? tx(reading(entry.summary.nominal[metric as keyof typeof entry.summary.nominal], metric)) : "—"}
                            </td>
                          ))
                        ) : (
                          <>
                            <td className="px-3 py-2.5 font-mono tabular-nums">{entry.summary?.valid_trials ?? "—"}</td>
                            <td className="px-4 py-2.5 font-mono tabular-nums">{entry.summary?.rejected_trials ?? "—"}</td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="space-y-2.5">
                {study.cases.map((entry) => (
                  <details
                    key={entry.index}
                    className="group/case rounded-xl border border-border/75 bg-muted/25 p-3.5"
                    data-study-case={entry.index}
                  >
                    <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium select-none [&::-webkit-details-marker]:hidden">
                      <span>{tx("案例")} {entry.index + 1} · {tx(studyCaseStatusLabel(entry.status))}</span>
                      <ChevronDown aria-hidden className="size-4 text-muted-foreground transition-transform group-open/case:rotate-180" />
                    </summary>
                    <p className="mt-2 break-all font-mono text-xs text-muted-foreground">{entry.key}</p>
                    {entry.error && (
                      <p className="mt-2 text-sm text-warning">
                        <RuntimeMessage message={entry.error.message} />
                      </p>
                    )}
                    {entry.summary && (
                      <>
                        <h4 className="mt-3 text-sm font-medium">{tx("原始固定坐标指标")}</h4>
                        <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
                          {nominalMetrics.map((metric) => (
                            <div key={metric} className="rounded-lg border border-border/65 bg-card px-3 py-2">
                              <dt className="text-muted-foreground">{tx(metricLabels[metric])}</dt>
                              <dd className="mt-0.5 font-mono font-medium tabular-nums">
                                {tx(
                                  reading(
                                    entry.summary!.nominal[
                                      metric as keyof typeof entry.summary.nominal
                                    ],
                                    metric,
                                  ),
                                )}
                              </dd>
                            </div>
                          ))}
                        </dl>
                        {study.protocol === "grid_displacements" && <div className="mt-3"><SummaryTable title="本案例有效偏移摘要" countLabel="有效偏移次数" values={entry.summary.trial_metrics} metrics={trialMetrics} /></div>}
                        {study.protocol === "grid_displacements" && (
                          <div className="lab-table-frame mt-3">
                            <table className="w-full min-w-[560px] text-left text-sm">
                              <thead>
                                <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                                  <th className="px-3.5 py-2">{tx("原协议偏移序号")}</th>
                                  <th className="px-3 py-2">{tx("状态")}</th>
                                  {trialMetrics.map((metric) => (
                                    <th key={metric} className="px-3 py-2">{tx(metricLabels[metric])}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {entry.summary.trials.map((trial) => (
                                  <tr key={trial.index} className="border-b border-border/60 last:border-0">
                                    <td className="px-3.5 py-2 font-mono tabular-nums">{trial.index + 1}</td>
                                    <td className="px-3 py-2 text-xs">
                                      {tx(
                                        trial.status === "completed" ? "偏移已完成" : "几何约束拒绝",
                                      )}
                                    </td>
                                    {trialMetrics.map((metric) => (
                                      <td key={metric} className="px-3 py-2 font-mono tabular-nums">
                                        {tx(
                                          reading(
                                            trial[metric as keyof typeof trial] as number | null,
                                            metric,
                                          ),
                                        )}
                                      </td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                      </>
                    )}
                    <details className="group/raw mt-3">
                      <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-primary select-none [&::-webkit-details-marker]:hidden">
                        <span>{tx("查看该案例的原始请求与摘要")}</span>
                        <ChevronDown aria-hidden className="size-3.5 transition-transform group-open/raw:rotate-180" />
                      </summary>
                      <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-xl border border-border/70 bg-card p-3 font-mono text-xs">
                        {JSON.stringify(entry, null, 2)}
                      </pre>
                    </details>
                  </details>
                ))}
              </div>
            </section>
            <section className="lab-panel space-y-5" aria-label={tx("案例级汇总")}>
              <h3 className="text-lg font-semibold">{tx("案例级汇总")}</h3>
              {study.aggregation.groups.map((group) => {
                const nominalSamples = collectCaseMetricSamples(
                  study.cases,
                  group.radius_mm,
                  nominalMetrics,
                  (entry, metric) =>
                    entry.summary?.nominal[metric as keyof typeof entry.summary.nominal],
                );
                const trialMedianSamples =
                  study.protocol === "grid_displacements"
                    ? collectCaseMetricSamples(
                        study.cases,
                        group.radius_mm,
                        trialMetrics,
                        (entry, metric) => entry.summary?.trial_metrics[metric]?.median,
                      )
                    : undefined;
                const trialP10Samples =
                  study.protocol === "grid_displacements"
                    ? collectCaseMetricSamples(
                        study.cases,
                        group.radius_mm,
                        trialMetrics,
                        (entry, metric) => entry.summary?.trial_metrics[metric]?.p10,
                      )
                    : undefined;
                return (
                  <section key={group.radius_mm} className="space-y-4 rounded-2xl border border-border/80 bg-muted/20 p-4">
                    <h4 className="font-semibold">
                      {tx("半径参数")} {group.radius_mm} mm · {group.completed_cases}/
                      {group.case_count} {tx("完成案例")}
                    </h4>
                    <SummaryTable
                      title="原始固定坐标指标分布"
                      values={group.nominal}
                      metrics={nominalMetrics}
                      showDistribution
                      caseSamples={nominalSamples}
                    />
                    {study.protocol === "grid_displacements" && (
                      <>
                        <p className="text-xs text-muted-foreground">
                          {tx(
                            "先汇总每个案例内的有效偏移，再对案例摘要计算分布。几何拒绝保留在案例表中。",
                          )}
                        </p>
                        <SummaryTable
                          title="各案例偏移中位数的分布"
                          values={group.trial_case_medians}
                          metrics={trialMetrics}
                          showDistribution
                          caseSamples={trialMedianSamples}
                        />
                        <SummaryTable
                          title="各案例偏移P10的分布"
                          values={group.trial_case_p10}
                          metrics={trialMetrics}
                          showDistribution
                          caseSamples={trialP10Samples}
                        />
                      </>
                    )}
                  </section>
                );
              })}
            </section>
          </>
        )}
      </div>
    </main>
  );
}
