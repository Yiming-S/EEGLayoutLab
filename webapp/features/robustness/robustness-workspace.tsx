"use client";
/* oxlint-disable next/no-html-link-for-pages -- preserve established local navigation */
import { useEffect, useState } from "react";
import { DataReadinessNotice } from "@/components/data-readiness-notice";
import { Button } from "@/components/ui/button";
import { SiteHeader } from "@/components/site-header";
import { RuntimeMessage } from "@/components/runtime-message";
import { useLanguage } from "@/components/language-provider";
import type { StudyProtocol } from "@/contracts/robustness-study";
import { listHeadPackages, type HeadPackageEntry } from "@/client/robustness";
import { NOISE_MODEL_PRESETS } from "../../contracts/scientific-options.mjs";
import type { NoiseModel } from "@/lib/design-decision";
import { useRobustnessController } from "./use-robustness-controller";
import { useStudyDesignDraft } from "./use-study-design-draft";
import { useStudyExport } from "./use-study-export";
import {
  createStudyInput,
  studyStatusLabel,
  fillHeads,
  type CaseDraft,
} from "./robustness-draft";
import { StudyDraftSection } from "./study-draft-section";
import { StudyDetailSection } from "./study-detail-section";

const download = (id: string, text: string) => {
  const href = URL.createObjectURL(
      new Blob([text], { type: "application/json" }),
    ),
    anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = `eeg-robustness-study-${id}.json`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
};

export default function RobustnessWorkspace() {
  const { tx } = useLanguage(),
    controller = useRobustnessController();
  const input = useStudyDesignDraft(controller.handoff, controller.study?.id);
  const { design, title } = input;
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
        if (!abort.signal.aborted)
          setHeadsError(
            caught instanceof Error && caught.message
              ? caught.message
              : "头模列表读取失败",
          );
      });
    return () => abort.abort();
  }, [protocol, heads, headsError]);

  const exporting = useStudyExport(
    controller.study?.id,
    controller.exportText,
    download,
  );
  const study = controller.study,
    disabled = controller.busy || controller.uncertain;

  const create = async () => {
    setFormError("");
    try {
      const noiseModel = NOISE_MODEL_PRESETS.find(
        (preset) => preset.id === noiseModelId,
      )?.value as NoiseModel | undefined;
      await controller.create(
        createStudyInput(
          design,
          protocol,
          cases,
          title,
          notes,
          noiseModel,
          protocol === "noise_seeds" ? scenarioId || undefined : undefined,
        ),
      );
    } catch (caught) {
      setFormError(
        caught instanceof Error ? caught.message : "研究草稿无法保存",
      );
    }
  };

  return (
    <main className="lab-page">
      <SiteHeader current="robustness" />
      <div className="lab-container space-y-5 pb-10">
        <header className="border-b border-border pt-7 pb-5">
          <h1 className="text-2xl font-semibold tracking-[-0.028em] sm:text-[1.65rem]">
            {tx("稳健性研究")}
          </h1>
          <p className="mt-1.5 max-w-4xl text-sm text-muted-foreground">
            {tx(
              "可复现的重复评估：按明确的种子与偏移参数重复原评价协议，逐项保存请求、结果及失败原因。",
            )}
          </p>
        </header>
        <DataReadinessNotice scope="robustness" />
        <section
          className="lab-panel space-y-3.5"
          aria-label={tx("此工作区的稳健性研究")}
        >
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
                  {entry.title} · {tx(studyStatusLabel(entry.status))} ·{" "}
                  {entry.completed_cases}/{entry.case_count}
                </option>
              ))}
            </select>
          </label>
          {controller.notice && (
            <p className="text-sm text-ink-soft">{tx(controller.notice)}</p>
          )}
          {controller.error && (
            <p role="alert" className="text-sm text-danger">
              <RuntimeMessage message={controller.error} />
            </p>
          )}
          {controller.uncertain && (
            <p className="text-sm text-warning">
              {tx(
                "操作结果待核对，写入按钮已暂停。重新读取当前研究，或刷新目录并打开已保存研究。",
              )}
            </p>
          )}
          {controller.busy && (
            <output aria-live="polite" className="text-sm text-primary">
              {tx("正在提交研究操作…")}
            </output>
          )}
          {controller.loading && (
            <output aria-live="polite" className="text-sm text-muted-foreground">
              {tx("正在读取研究…")}
            </output>
          )}
        </section>
        {!study && !controller.loading && (
          <StudyDraftSection
            input={input}
            disabled={disabled}
            busy={controller.busy}
            protocol={protocol}
            setProtocol={setProtocol}
            cases={cases}
            setCases={setCases}
            batchStartSeed={batchStartSeed}
            setBatchStartSeed={setBatchStartSeed}
            noiseModelId={noiseModelId}
            setNoiseModelId={setNoiseModelId}
            scenarioId={scenarioId}
            setScenarioId={setScenarioId}
            notes={notes}
            setNotes={setNotes}
            heads={heads}
            headsError={headsError}
            setHeadsError={setHeadsError}
            formError={formError}
            setFormError={setFormError}
            onCreate={create}
          />
        )}
        {study && (
          <StudyDetailSection
            study={study}
            controller={controller}
            disabled={disabled}
            exporting={exporting}
          />
        )}
      </div>
    </main>
  );
}
