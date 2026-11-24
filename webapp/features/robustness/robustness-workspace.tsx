"use client";
/* oxlint-disable next/no-html-link-for-pages -- preserve established local navigation */
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { SiteHeader } from "@/components/site-header";
import { RuntimeMessage } from "@/components/runtime-message";
import { useLanguage } from "@/components/language-provider";
import type { EmpiricalSummary, StudyProtocol } from "@/contracts/robustness-study";
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
  type CaseDraft,
} from "./robustness-draft";
import { FilePicker } from '@/components/ui/file-picker';

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
const reading = (value: number | null | undefined, metric: string) =>
  value == null || !Number.isFinite(value)
    ? "无有效读数"
    : metric.endsWith("_mm")
      ? `${value.toFixed(4)} mm`
      : `${(value * 100).toFixed(4)}%`;
const download = (id: string, text: string) => {
  const href = URL.createObjectURL(new Blob([text], { type: "application/json" })),
    anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = `eeg-robustness-study-${id}.json`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
};

function SummaryTable({
  title,
  values,
  metrics,
  countLabel = "有效案例数",
}: {
  title: string;
  values: Record<string, EmpiricalSummary>;
  metrics: string[];
  countLabel?: string;
}) {
  const { tx } = useLanguage();
  return (
    <section className="space-y-2">
      <h4 className="font-semibold">{tx(title)}</h4>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead>
            <tr className="border-b">
              <th className="py-2">{tx("指标")}</th>
              <th>{tx(countLabel)}</th>
              <th>{tx("中位数")}</th>
              <th>P10</th>
              <th>P90</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((metric) => {
              const value = values[metric];
              return (
                <tr key={metric} className="border-b">
                  <th className="py-2 font-normal">{tx(metricLabels[metric])}</th>
                  <td>{value?.n ?? 0}</td>
                  {(["median", "p10", "p90"] as const).map((key) => (
                    <td key={key} className="font-mono">
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
    [cases, setCases] = useState<CaseDraft[]>([{ seed: "42", radius: "6" }]);
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
      <div className="lab-container space-y-5 py-6">
        <header>
          <h1 className="text-2xl font-semibold">{tx("稳健性研究")}</h1>
          <p className="mt-2 max-w-4xl text-muted-foreground">
            {tx("可复现的重复评估：按明确的种子与偏移参数重复原评价协议，逐项保存请求、结果及失败原因。")}
          </p>
        </header>
        <section className="lab-panel space-y-3" aria-label={tx("本浏览器的稳健性研究")}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">{tx("已保存研究")}</h2>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={controller.busy}
                onClick={() => void controller.refreshDirectory()}
              >
                {tx("刷新研究目录")}
              </Button>
              <Button
                type="button"
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
          {controller.notice && <p className="text-sm">{tx(controller.notice)}</p>}
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
          {controller.busy && <output aria-live="polite">{tx("正在提交研究操作…")}</output>}
          {controller.loading && <output aria-live="polite">{tx("正在读取研究…")}</output>}
        </section>
        {!study && !controller.loading && (
          <section className="lab-panel space-y-4" aria-label={tx("创建稳健性研究草稿")}>
            <h2 className="text-lg font-semibold">{tx("创建研究草稿")}</h2>
            <div className="grid gap-4 md:grid-cols-2">
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
              <div className="rounded-lg border p-3 text-sm" data-study-design>
                <p>
                  {design.name} · 64 {tx("电极")} · {new Set(design.region_indices).size} {tx("区")}
                </p>
                <p className="mt-1 text-muted-foreground">
                  {tx("使用导入的原始坐标；名称和来源说明独立保存。")}
                </p>
                <details className="mt-2">
                  <summary className="cursor-pointer text-primary">
                    {tx("查看研究输入坐标与名称")}
                  </summary>
                  <div className="mt-2 max-h-60 overflow-auto">
                    <table className="w-full text-left text-xs">
                      <thead>
                        <tr>
                          <th>{tx("电极")}</th>
                          <th>{tx("区域")}</th>
                          <th>X (mm)</th>
                          <th>Y (mm)</th>
                          <th>Z (mm)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {design.xyz_mm.map((point, index) => (
                          <tr key={index}>
                            <td>{design.electrode_names?.[index] ?? `E${index + 1}`}</td>
                            <td>{design.region_indices[index]}</td>
                            {point.map((value, axis) => (
                              <td key={axis}>{value}</td>
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
            <p className="text-sm text-muted-foreground">
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
                  className="lab-input"
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
            <div className="overflow-x-auto">
              <table className="w-full min-w-[400px] text-left text-sm">
                <thead>
                  <tr>
                    <th>{tx("案例")}</th>
                    {protocol === "heads" && <th>{tx("头模")}</th>}
                    <th>{tx("随机种子")}</th>
                    <th>{tx("半径参数")} (mm)</th>
                    <th>{tx("操作")}</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((entry, index) => (
                    <tr key={index}>
                      <th className="py-2 font-normal">{index + 1}</th>
                      {protocol === "heads" && (
                        <td>
                          <select
                            className="lab-select"
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
                      <td>
                        <input
                          className="lab-input"
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
                      <td>
                        <select
                          className="lab-select"
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
                      <td>
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
            <p className="text-sm text-muted-foreground">
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
                <output className="rounded-full bg-primary/10 px-3 py-1 text-sm" aria-live="polite">
                  {tx(studyStatusLabel(study.status))}
                </output>
              </div>
              {study.notes && <p className="whitespace-pre-wrap text-sm">{study.notes}</p>}
              {study.cancel_requested && <p className="text-sm text-warning">{tx("取消意图已保存；恢复操作只保存已有结果并完成取消。")}</p>}
              <details className="rounded-lg border p-3"><summary className="cursor-pointer font-medium">{tx("查看研究输入坐标与名称")}</summary>
                <p className="mt-2 text-sm">{study.design.name} · Ernie · mm</p>
                {study.annotation.source_metadata && <p className="mt-1 text-sm text-muted-foreground">{coordinateSourceFiles(study.annotation.source_metadata)}</p>}
                <div className="mt-3 max-h-64 overflow-auto"><table className="w-full min-w-[560px] text-left text-xs"><thead><tr><th>{tx("电极")}</th><th>{tx("区域")}</th><th>X (mm)</th><th>Y (mm)</th><th>Z (mm)</th></tr></thead><tbody>{study.design.xyz_mm.map((point, index) => <tr key={index}><td>{study.annotation.electrode_names?.[index] ?? `E${index + 1}`}</td><td>{study.design.region_indices[index]}</td>{point.map((value, axis) => <td key={axis}>{value}</td>)}</tr>)}</tbody></table></div>
              </details>
              <p className="break-all font-mono text-xs">
                {study.id} · eeg-robustness-study/1 · {tx("版本")} {study.revision}
              </p>
              <p className="text-sm text-muted-foreground">
                {tx(
                  study.protocol === "heads"
                    ? "本研究描述所列头模上这批案例的经验分布；映射后被拒绝的头模计为失败案例。中位数、P10和P90按案例计算，使用第7型线性插值。"
                    : "本研究描述Ernie头模内这批案例的经验分布。中位数、P10和P90按案例计算，使用第7型线性插值。",
                )}
              </p>
              <p className="text-sm text-muted-foreground">
                {tx("服务重启后，后续案例等待明确恢复。原队列已接受的单个案例保留其队列状态。")}
              </p>
              <div className="flex flex-wrap gap-2">
                {studyPrimaryAction(study.status) && (
                  <Button
                    type="button"
                    disabled={disabled}
                    onClick={() => void controller.act(studyPrimaryAction(study.status)!)}
                  >
                    {tx(study.status === "draft" ? "开始此研究" : study.cancel_requested ? "保存已有结果并完成取消" : "继续后续案例")}
                  </Button>
                )}
                {studyCanCancel(study.status) && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={disabled}
                    onClick={() => void controller.act("cancel")}
                  >
                    {tx("取消此研究")}
                  </Button>
                )}
                <Button
                  type="button"
                  variant="outline"
                  disabled={controller.busy}
                  onClick={controller.reload}
                >
                  {tx("重新读取研究状态")}
                </Button>
                <Button
                  type="button"
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
              <dl className="grid gap-3 text-sm sm:grid-cols-5">
                {[
                  ["全部案例", study.aggregation.case_count],
                  ["完成案例", study.aggregation.completed_cases],
                  ["失败案例", study.aggregation.failed_cases],
                  ["取消案例", study.aggregation.cancelled_cases],
                  ["未结束案例", study.aggregation.pending_cases],
                ].map(([label, value]) => (
                  <div key={String(label)}>
                    <dt className="text-muted-foreground">{tx(String(label))}</dt>
                    <dd className="mt-1 font-semibold">{value}</dd>
                  </div>
                ))}
              </dl>
            </section>
            <section className="lab-panel space-y-4" aria-label={tx("逐案例结果")}>
              <h3 className="text-lg font-semibold">{tx("逐案例结果")}</h3>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[650px] text-left text-sm">
                  <thead>
                    <tr>
                      <th>{tx("案例")}</th>
                      {study.protocol === "heads" && <th>{tx("头模")}</th>}
                      <th>{tx("随机种子")}</th>
                      <th>{tx("半径参数")} (mm)</th>
                      <th>{tx("状态")}</th>
                      {study.protocol === "heads" ? (
                        <>
                          <th>{tx(metricLabels.field_relative)}</th>
                          <th>{tx(metricLabels.localization_relative)}</th>
                          <th>{tx(metricLabels.median_mm)}</th>
                        </>
                      ) : (
                        <>
                          <th>{tx("有效偏移次数")}</th>
                          <th>{tx("几何拒绝次数")}</th>
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {study.cases.map((entry) => (
                      <tr key={entry.index} className="border-b">
                        <th className="py-3 font-normal">{entry.index + 1}</th>
                        {study.protocol === "heads" && <td>{entry.request.head_id}</td>}
                        <td>{entry.request.seed}</td>
                        <td>{entry.request.radius_mm}</td>
                        <td>{tx(studyCaseStatusLabel(entry.status))}</td>
                        {study.protocol === "heads" ? (
                          ["field_relative", "localization_relative", "median_mm"].map((metric) => (
                            <td key={metric}>
                              {entry.summary ? tx(reading(entry.summary.nominal[metric as keyof typeof entry.summary.nominal], metric)) : "—"}
                            </td>
                          ))
                        ) : (
                          <>
                            <td>{entry.summary?.valid_trials ?? "—"}</td>
                            <td>{entry.summary?.rejected_trials ?? "—"}</td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {study.cases.map((entry) => (
                <details
                  key={entry.index}
                  className="rounded-lg border p-3"
                  data-study-case={entry.index}
                >
                  <summary className="cursor-pointer font-medium">
                    {tx("案例")} {entry.index + 1} · {tx(studyCaseStatusLabel(entry.status))}
                  </summary>
                  <p className="mt-2 break-all font-mono text-xs">{entry.key}</p>
                  {entry.error && (
                    <p className="mt-2 text-sm text-warning">
                      <RuntimeMessage message={entry.error.message} />
                    </p>
                  )}
                  {entry.summary && (
                    <>
                      <h4 className="mt-3 font-medium">{tx("原始固定坐标指标")}</h4>
                      <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-3">
                        {nominalMetrics.map((metric) => (
                          <div key={metric}>
                            <dt className="text-muted-foreground">{tx(metricLabels[metric])}</dt>
                            <dd>
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
                      {study.protocol === "grid_displacements" && <SummaryTable title="本案例有效偏移摘要" countLabel="有效偏移次数" values={entry.summary.trial_metrics} metrics={trialMetrics} />}
                      {study.protocol === "grid_displacements" && (
                        <div className="mt-3 overflow-x-auto">
                          <table className="w-full min-w-[560px] text-left text-sm">
                            <thead>
                              <tr>
                                <th>{tx("原协议偏移序号")}</th>
                                <th>{tx("状态")}</th>
                                {trialMetrics.map((metric) => (
                                  <th key={metric}>{tx(metricLabels[metric])}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {entry.summary.trials.map((trial) => (
                                <tr key={trial.index}>
                                  <td>{trial.index + 1}</td>
                                  <td>
                                    {tx(
                                      trial.status === "completed" ? "偏移已完成" : "几何约束拒绝",
                                    )}
                                  </td>
                                  {trialMetrics.map((metric) => (
                                    <td key={metric}>
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
                  <details className="mt-3">
                    <summary className="cursor-pointer text-sm text-primary">
                      {tx("查看该案例的原始请求与摘要")}
                    </summary>
                    <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded bg-muted p-3 text-xs">
                      {JSON.stringify(entry, null, 2)}
                    </pre>
                  </details>
                </details>
              ))}
            </section>
            <section className="lab-panel space-y-5" aria-label={tx("案例级汇总")}>
              <h3 className="text-lg font-semibold">{tx("案例级汇总")}</h3>
              {study.aggregation.groups.map((group) => (
                <section key={group.radius_mm} className="space-y-4 rounded-lg border p-4">
                  <h4 className="font-semibold">
                    {tx("半径参数")} {group.radius_mm} mm · {group.completed_cases}/
                    {group.case_count} {tx("完成案例")}
                  </h4>
                  <SummaryTable
                    title="原始固定坐标指标分布"
                    values={group.nominal}
                    metrics={nominalMetrics}
                  />
                  {study.protocol === "grid_displacements" && (
                    <>
                      <p className="text-sm text-muted-foreground">
                        {tx(
                          "先汇总每个案例内的有效偏移，再对案例摘要计算分布。几何拒绝保留在案例表中。",
                        )}
                      </p>
                      <SummaryTable
                        title="各案例偏移中位数的分布"
                        values={group.trial_case_medians}
                        metrics={trialMetrics}
                      />
                      <SummaryTable
                        title="各案例偏移P10的分布"
                        values={group.trial_case_p10}
                        metrics={trialMetrics}
                      />
                    </>
                  )}
                </section>
              ))}
            </section>
          </>
        )}
      </div>
    </main>
  );
}
