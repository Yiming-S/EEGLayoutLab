"use client";

import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { RuntimeMessage } from "@/components/runtime-message";
import { useLanguage } from "@/components/language-provider";
import { coordinateSourceFiles } from "@/contracts/coordinate-source.mjs";
import type { RobustnessStudy } from "@/contracts/robustness-study";
import {
  conductivityScenarioLabel,
  noiseModelLabel,
} from "../../contracts/scientific-options.mjs";
import {
  studyCanCancel,
  studyCaseStatusLabel,
  studyPrimaryAction,
  studyStatusLabel,
} from "./robustness-draft";
import {
  SummaryTable,
  collectCaseMetricSamples,
  metricLabels,
  nominalMetrics,
  protocols,
  reading,
  trialMetrics,
} from "./robustness-summary-visuals";
import type { useRobustnessController } from "./use-robustness-controller";
import type { useStudyExport } from "./use-study-export";

type RobustnessController = ReturnType<typeof useRobustnessController>;
type StudyExporter = ReturnType<typeof useStudyExport>;

export function StudyDetailSection({
  study,
  controller,
  disabled,
  exporting,
}: {
  study: RobustnessStudy;
  controller: RobustnessController;
  disabled: boolean;
  exporting: StudyExporter;
}) {
  const { tx, date } = useLanguage();

  return (
    <>
      <section className="lab-panel space-y-4" aria-label={tx("当前稳健性研究")}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">{study.title}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {tx(protocols[study.protocol])} ·{" "}
              {tx(noiseModelLabel(study.noise_model))}
              {study.conductivity_scenario && (
                <> · {tx(conductivityScenarioLabel(study.conductivity_scenario))}</>
              )}{" "}
              · {date(study.created_at, true)}
            </p>
          </div>
          <output
            className="rounded-full bg-primary/12 px-3 py-1 text-xs font-semibold text-primary ring-1 ring-inset ring-primary/22"
            aria-live="polite"
          >
            {tx(studyStatusLabel(study.status))}
          </output>
        </div>
        {study.notes && (
          <p className="whitespace-pre-wrap text-sm leading-6">{study.notes}</p>
        )}
        {study.cancel_requested && (
          <p className="text-sm text-warning">
            {tx("取消意图已保存；恢复操作只保存已有结果并完成取消。")}
          </p>
        )}
        <details className="group/input rounded-xl border border-border/75 bg-muted/25 p-3.5">
          <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium select-none [&::-webkit-details-marker]:hidden">
            <span>{tx("查看研究输入坐标与名称")}</span>
            <ChevronDown
              aria-hidden
              className="size-4 text-muted-foreground transition-transform group-open/input:rotate-180"
            />
          </summary>
          <p className="mt-2.5 text-sm font-medium">
            {study.design.name} · Ernie · mm
          </p>
          {study.annotation.source_metadata && (
            <p className="mt-1 text-xs text-muted-foreground">
              {coordinateSourceFiles(study.annotation.source_metadata)}
            </p>
          )}
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
                  <tr
                    key={index}
                    className="border-b border-border/60 last:border-0"
                  >
                    <td className="px-3 py-1.5 font-medium">
                      {study.annotation.electrode_names?.[index] ??
                        `E${index + 1}`}
                    </td>
                    <td className="px-2.5 py-1.5 font-mono tabular-nums">
                      {study.design.region_indices[index]}
                    </td>
                    {point.map((value, axis) => (
                      <td
                        key={axis}
                        className="px-2.5 py-1.5 font-mono tabular-nums"
                      >
                        {value}
                      </td>
                    ))}
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
          {tx(
            "服务重启后，后续案例等待明确恢复。原队列已接受的单个案例保留其队列状态。",
          )}
        </p>
        <div className="flex flex-wrap gap-2">
          {studyPrimaryAction(study.status) && (
            <Button
              type="button"
              size="sm"
              disabled={disabled}
              onClick={() => void controller.act(studyPrimaryAction(study.status)!)}
            >
              {tx(
                study.status === "draft"
                  ? "开始此研究"
                  : study.cancel_requested
                    ? "保存已有结果并完成取消"
                    : "继续后续案例",
              )}
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
              <dt className="text-xs text-muted-foreground">
                {tx(String(label))}
              </dt>
              <dd className="mt-1 font-mono text-xl font-semibold tabular-nums">
                {value}
              </dd>
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
                {study.protocol === "heads" && (
                  <th className="px-3 py-2.5">{tx("头模")}</th>
                )}
                <th className="px-3 py-2.5">{tx("随机种子")}</th>
                <th className="px-3 py-2.5">{tx("半径参数")} (mm)</th>
                <th className="px-3 py-2.5">{tx("状态")}</th>
                {study.protocol === "heads" ? (
                  <>
                    <th className="px-3 py-2.5">
                      {tx(metricLabels.field_relative)}
                    </th>
                    <th className="px-3 py-2.5">
                      {tx(metricLabels.localization_relative)}
                    </th>
                    <th className="px-4 py-2.5">
                      {tx(metricLabels.median_mm)}
                    </th>
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
                <tr
                  key={entry.index}
                  className="border-b border-border/65 transition-colors last:border-0 hover:bg-primary/[0.03]"
                >
                  <th className="px-4 py-2.5 font-mono font-normal tabular-nums">
                    {entry.index + 1}
                  </th>
                  {study.protocol === "heads" && (
                    <td className="px-3 py-2.5 font-mono text-xs">
                      {entry.request.head_id}
                    </td>
                  )}
                  <td className="px-3 py-2.5 font-mono tabular-nums">
                    {entry.request.seed}
                  </td>
                  <td className="px-3 py-2.5 font-mono tabular-nums">
                    {entry.request.radius_mm}
                  </td>
                  <td className="px-3 py-2.5">
                    {tx(studyCaseStatusLabel(entry.status))}
                  </td>
                  {study.protocol === "heads" ? (
                    [
                      "field_relative",
                      "localization_relative",
                      "median_mm",
                    ].map((metric) => (
                      <td
                        key={metric}
                        className="px-3 py-2.5 font-mono tabular-nums"
                      >
                        {entry.summary
                          ? tx(
                              reading(
                                entry.summary.nominal[
                                  metric as keyof typeof entry.summary.nominal
                                ],
                                metric,
                              ),
                            )
                          : "—"}
                      </td>
                    ))
                  ) : (
                    <>
                      <td className="px-3 py-2.5 font-mono tabular-nums">
                        {entry.summary?.valid_trials ?? "—"}
                      </td>
                      <td className="px-4 py-2.5 font-mono tabular-nums">
                        {entry.summary?.rejected_trials ?? "—"}
                      </td>
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
                <span>
                  {tx("案例")} {entry.index + 1} ·{" "}
                  {tx(studyCaseStatusLabel(entry.status))}
                </span>
                <ChevronDown
                  aria-hidden
                  className="size-4 text-muted-foreground transition-transform group-open/case:rotate-180"
                />
              </summary>
              <p className="mt-2 break-all font-mono text-xs text-muted-foreground">
                {entry.key}
              </p>
              {entry.error && (
                <p className="mt-2 text-sm text-warning">
                  <RuntimeMessage message={entry.error.message} />
                </p>
              )}
              {entry.summary && (
                <>
                  <h4 className="mt-3 text-sm font-medium">
                    {tx("原始固定坐标指标")}
                  </h4>
                  <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
                    {nominalMetrics.map((metric) => (
                      <div
                        key={metric}
                        className="rounded-lg border border-border/65 bg-card px-3 py-2"
                      >
                        <dt className="text-muted-foreground">
                          {tx(metricLabels[metric])}
                        </dt>
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
                  {study.protocol === "grid_displacements" && (
                    <div className="mt-3">
                      <SummaryTable
                        title="本案例有效偏移摘要"
                        countLabel="有效偏移次数"
                        values={entry.summary.trial_metrics}
                        metrics={trialMetrics}
                      />
                    </div>
                  )}
                  {study.protocol === "grid_displacements" && (
                    <div className="lab-table-frame mt-3">
                      <table className="w-full min-w-[560px] text-left text-sm">
                        <thead>
                          <tr className="border-b border-border/75 bg-muted/55 text-xs font-semibold tracking-wide text-ink-soft">
                            <th className="px-3.5 py-2">
                              {tx("原协议偏移序号")}
                            </th>
                            <th className="px-3 py-2">{tx("状态")}</th>
                            {trialMetrics.map((metric) => (
                              <th key={metric} className="px-3 py-2">
                                {tx(metricLabels[metric])}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {entry.summary.trials.map((trial) => (
                            <tr
                              key={trial.index}
                              className="border-b border-border/60 last:border-0"
                            >
                              <td className="px-3.5 py-2 font-mono tabular-nums">
                                {trial.index + 1}
                              </td>
                              <td className="px-3 py-2 text-xs">
                                {tx(
                                  trial.status === "completed"
                                    ? "偏移已完成"
                                    : "几何约束拒绝",
                                )}
                              </td>
                              {trialMetrics.map((metric) => (
                                <td
                                  key={metric}
                                  className="px-3 py-2 font-mono tabular-nums"
                                >
                                  {tx(
                                    reading(
                                      trial[
                                        metric as keyof typeof trial
                                      ] as number | null,
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
                  <ChevronDown
                    aria-hidden
                    className="size-3.5 transition-transform group-open/raw:rotate-180"
                  />
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
              entry.summary?.nominal[
                metric as keyof typeof entry.summary.nominal
              ],
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
            <section
              key={group.radius_mm}
              className="space-y-4 rounded-2xl border border-border/80 bg-muted/20 p-4"
            >
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
  );
}
