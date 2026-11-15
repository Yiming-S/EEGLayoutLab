import { validateDesign, type ElectrodeDesign } from "../../lib/design-decision.ts";
import type { CreateStudyInput } from "../../client/robustness";
import type { StudyProtocol, StudyStatus } from "../../contracts/robustness-study";

export const STUDY_DRAFT_KEY = "eeg-robustness-coordinate-draft/1";
export const STUDY_DRAFT_LIMIT = 65536;
export const STUDY_CASE_LIMIT = 12;
export const STUDY_RADII = [3, 6, 10] as const;
export type CaseDraft = { seed: string; radius: string };
export function saveStudyHandoff(storage: Pick<Storage, "setItem">, input: ElectrodeDesign) {
  const text = JSON.stringify({
    schema: "eeg-robustness-coordinate-draft/1",
    design: validateDesign(input),
  });
  if (new TextEncoder().encode(text).byteLength > STUDY_DRAFT_LIMIT)
    throw new Error("研究坐标草稿超过64 KiB");
  storage.setItem(STUDY_DRAFT_KEY, text);
}
export function readStudyHandoff(storage: Pick<Storage, "getItem">): ElectrodeDesign | null {
  const raw = storage.getItem(STUDY_DRAFT_KEY);
  if (!raw) return null;
  if (new TextEncoder().encode(raw).byteLength > STUDY_DRAFT_LIMIT)
    throw new Error("研究坐标草稿超过64 KiB");
  const value = JSON.parse(raw);
  if (value?.schema !== "eeg-robustness-coordinate-draft/1")
    throw new Error("研究坐标草稿格式无效");
  return validateDesign(value.design);
}
export function createStudyInput(
  design: ElectrodeDesign | null,
  protocol: StudyProtocol,
  rows: CaseDraft[],
  title: string,
  notes: string,
): CreateStudyInput {
  if (!design) throw new Error("请先导入64电极坐标");
  if (!title.trim() || title.length > 200 || notes.length > 2000)
    throw new Error("请填写研究名称；名称上限200字，备注上限2000字");
  if (
    !["noise_seeds", "grid_displacements"].includes(protocol) ||
    rows.length < 1 ||
    rows.length > STUDY_CASE_LIMIT
  )
    throw new Error("请列出1至12个明确案例");
  const cases = rows.map((row) => {
    const seed = Number(row.seed),
      radius_mm = Number(row.radius);
    if (
      !row.seed.trim() ||
      !Number.isInteger(seed) ||
      seed < 0 ||
      seed > 9999 ||
      !STUDY_RADII.some((radius) => radius === radius_mm)
    )
      throw new Error("每个案例须填写0至9999的整数种子和3、6或10 mm半径");
    return { seed, radius_mm };
  });
  if (new Set(cases.map((row) => `${row.seed}:${row.radius_mm}`)).size !== cases.length)
    throw new Error("案例的种子与半径组合不能重复");
  if (protocol === "noise_seeds" && new Set(cases.map((row) => row.radius_mm)).size !== 1)
    throw new Error("随机种子研究的所有案例须保持同一半径参数");
  const input = { protocol, design: validateDesign(design), cases, title: title.trim(), notes };
  if (new TextEncoder().encode(JSON.stringify(input)).byteLength > 65536)
    throw new Error("研究请求超过64 KiB");
  return input;
}
export const studyRunning = (status?: StudyStatus) =>
  status === "running" || status === "cancelling";
export const studyPrimaryAction = (status: StudyStatus) =>
  status === "draft"
    ? "start"
    : ["paused_recovery", "paused_resource"].includes(status)
      ? "resume"
      : null;
export const studyCanCancel = (status: StudyStatus) =>
  ["draft", "running", "paused_recovery", "paused_resource"].includes(status);
export const studyStatusLabel = (status: string) =>
  ({
    draft: "研究草稿",
    running: "研究运行中",
    paused_recovery: "等待明确恢复",
    paused_resource: "资源不足，研究已暂停",
    cancelling: "正在取消研究",
    completed: "研究已完成",
    completed_with_failures: "研究已结束，部分案例失败",
    cancelled: "研究已取消",
    pending: "待开始",
    submitting: "正在提交案例",
    queued: "案例排队中",
    failed: "案例失败",
    failed_uncertain: "提交结果未确认",
    geometry_rejected: "几何约束拒绝",
  })[status] ?? status;
export const studyCaseStatusLabel = (status: string) =>
  ({
    pending: "待开始",
    submitting: "正在提交案例",
    queued: "案例排队中",
    running: "案例运行中",
    cancelling: "正在取消案例",
    completed: "案例已完成",
    failed: "案例失败",
    cancelled: "案例已取消",
    failed_uncertain: "提交结果未确认",
  })[status] ?? status;
