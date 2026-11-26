"use client";

import type { Dispatch, SetStateAction } from "react";
import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FilePicker } from "@/components/ui/file-picker";
import { RuntimeMessage } from "@/components/runtime-message";
import { useLanguage } from "@/components/language-provider";
import type { HeadPackageEntry } from "@/client/robustness";
import type { StudyProtocol } from "@/contracts/robustness-study";
import { EvaluationConditions } from "@/features/conditions/evaluation-conditions";
import { RecordDesignPicker } from "./record-design-picker";
import {
  STUDY_CASE_LIMIT,
  STUDY_RADII,
  fillHeads,
  generateAllHeadCases,
  generateConsecutiveSeedCases,
  generateRadiusSeedGridCases,
  type CaseDraft,
} from "./robustness-draft";
import { protocols } from "./robustness-summary-visuals";
import type { useStudyDesignDraft } from "./use-study-design-draft";

type StudyDesignDraft = ReturnType<typeof useStudyDesignDraft>;

export function StudyDraftSection({
  input,
  disabled,
  busy,
  protocol,
  setProtocol,
  cases,
  setCases,
  batchStartSeed,
  setBatchStartSeed,
  noiseModelId,
  setNoiseModelId,
  scenarioId,
  setScenarioId,
  notes,
  setNotes,
  heads,
  headsError,
  setHeadsError,
  formError,
  setFormError,
  onCreate,
}: {
  input: StudyDesignDraft;
  disabled: boolean;
  busy: boolean;
  protocol: StudyProtocol;
  setProtocol: Dispatch<SetStateAction<StudyProtocol>>;
  cases: CaseDraft[];
  setCases: Dispatch<SetStateAction<CaseDraft[]>>;
  batchStartSeed: string;
  setBatchStartSeed: Dispatch<SetStateAction<string>>;
  noiseModelId: string;
  setNoiseModelId: Dispatch<SetStateAction<string>>;
  scenarioId: string;
  setScenarioId: Dispatch<SetStateAction<string>>;
  notes: string;
  setNotes: Dispatch<SetStateAction<string>>;
  heads: HeadPackageEntry[] | null;
  headsError: string;
  setHeadsError: Dispatch<SetStateAction<string>>;
  formError: string;
  setFormError: Dispatch<SetStateAction<string>>;
  onCreate: () => Promise<void>;
}) {
  const { tx } = useLanguage();
  const { design, title, setTitle } = input;

  return (
    <section
      className="lab-panel space-y-4"
      aria-label={tx("创建稳健性研究草稿")}
    >
      <h2 className="text-lg font-semibold">{tx("创建研究草稿")}</h2>
      <div className="grid gap-4 rounded-xl border border-border/70 bg-muted/30 p-4 md:grid-cols-2">
        <RecordDesignPicker
          disabled={disabled}
          onChoose={(chosen) => {
            setFormError("");
            input.chooseDesign(chosen);
          }}
        />
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
        <div
          className="rounded-xl border border-primary/25 bg-primary/[0.035] p-3.5 text-sm"
          data-study-design
        >
          <p className="font-medium">
            {design.name} · 64 {tx("电极")} ·{" "}
            {new Set(design.region_indices).size} {tx("区")}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {tx("使用导入的原始坐标；名称和来源说明独立保存。")}
          </p>
          <details className="group/design mt-2">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-primary select-none [&::-webkit-details-marker]:hidden">
              <span>{tx("查看研究输入坐标与名称")}</span>
              <ChevronDown
                aria-hidden
                className="size-3.5 transition-transform group-open/design:rotate-180"
              />
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
                    <tr
                      key={index}
                      className="border-b border-border/60 last:border-0"
                    >
                      <td className="px-3 py-1.5 font-medium">
                        {design.electrode_names?.[index] ?? `E${index + 1}`}
                      </td>
                      <td className="px-2.5 py-1.5 font-mono tabular-nums">
                        {design.region_indices[index]}
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
                setCases((rows) =>
                  rows.map((row) => ({ ...row, radius: rows[0].radius })),
                );
              if (next === "heads")
                setCases((rows) => fillHeads(rows, heads ?? []));
            }}
          >
            {Object.entries(protocols).map(([value, label]) => (
              <option key={value} value={value}>
                {tx(label)}
              </option>
            ))}
          </select>
        </label>
        <EvaluationConditions className="md:col-span-2 md:grid-cols-2"
          action="study"
          protocol={protocol}
          values={{ noiseModelId, scenarioId }}
          onChange={(patch) => {
            if (patch.noiseModelId !== undefined)
              setNoiseModelId(patch.noiseModelId);
            if (patch.scenarioId !== undefined) setScenarioId(patch.scenarioId);
          }}
        />
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
        <p className="text-sm text-destructive">
          {tx("尚无已预计算的头模包")}
        </p>
      )}
      {protocol === "heads" && headsError && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 text-sm text-danger"
        >
          <RuntimeMessage message={headsError} />
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setHeadsError("")}
          >
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
              setCases((rows) =>
                rows.map((row) => ({ ...row, radius: event.target.value })),
              )
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
              setCases((rows) =>
                rows.map((row) => ({ ...row, seed: event.target.value })),
              )
            }
          />
        </label>
      )}
      <div
        className="space-y-2.5 rounded-xl border border-border/75 bg-muted/30 p-3.5"
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
                return protocol === "heads"
                  ? fillHeads([baseRow], heads ?? [])
                  : [baseRow];
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
                {tx(
                  "按当前共用随机种子与固定半径一键填入可用头模（最多12个）。",
                )}
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
              <tr
                key={index}
                className="border-b border-border/65 last:border-0"
              >
                <th className="px-4 py-2 font-mono font-normal tabular-nums">
                  {index + 1}
                </th>
                {protocol === "heads" && (
                  <td className="px-3 py-2">
                    <select
                      className="lab-select mt-0"
                      aria-label={`${tx("案例")} ${index + 1} ${tx("头模")}`}
                      value={entry.head ?? ""}
                      onChange={(event) =>
                        setCases((rows) =>
                          rows.map((row, rowIndex) =>
                            rowIndex === index
                              ? { ...row, head: event.target.value }
                              : row,
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
                          rowIndex === index
                            ? { ...row, seed: event.target.value }
                            : row,
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
                          rowIndex === index
                            ? { ...row, radius: event.target.value }
                            : row,
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
                      setCases((rows) =>
                        rows.filter((_, rowIndex) => rowIndex !== index),
                      )
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
            if (protocol === "heads")
              return fillHeads(
                [...rows, { seed: rows[0].seed, radius: rows[0].radius }],
                heads ?? [],
              );
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
      <Button
        type="button"
        disabled={disabled || input.loading || !design}
        onClick={() => void onCreate()}
      >
        {tx(busy ? "正在保存研究草稿…" : "保存研究草稿")}
      </Button>
    </section>
  );
}
