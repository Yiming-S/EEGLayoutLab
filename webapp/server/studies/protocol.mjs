import { normalizeDesignRequest } from "../design-evaluation-server.mjs";
import { electrodeNames } from "../annotations/electrode-names.mjs";
import { validateCoordinateSource } from "../../contracts/coordinate-source.mjs";

export const STUDY_LIMITS = Object.freeze({
  cases: 12,
  perOwner: 10,
  studies: 100,
  metadataBytes: 256 * 1024,
  caseBytes: 16 * 1024 * 1024,
  studyBytes: 64 * 1024 * 1024,
  totalBytes: 512 * 1024 * 1024,
});
export const studyError = (message, status = 400) =>
  Object.assign(new Error(message), { status, studySafe: true });
export const terminalCase = (status) =>
  ["completed", "failed", "cancelled", "failed_uncertain"].includes(status);
export const nominalMetrics = [
  "field_relative",
  "field_absolute",
  "reference_field_absolute",
  "sensitivity_tail",
  "localization_relative",
  "median_mm",
  "p90_mm",
  "reference_median_mm",
  "reference_p90_mm",
];
export const trialMetrics = [
  "field_relative",
  "fixed_estimator_field_relative",
  "sensitivity_tail",
];
const plain = (value) => value && typeof value === "object" && !Array.isArray(value);
export function normalizeStudyInput(input) {
  try {
    if (
      !plain(input) ||
      Object.keys(input).some(
        (key) => !["protocol", "design", "cases", "title", "notes"].includes(key),
      ) ||
      !["noise_seeds", "grid_displacements"].includes(input.protocol) ||
      !Array.isArray(input.cases) ||
      !input.cases.length ||
      input.cases.length > STUDY_LIMITS.cases
    )
      throw studyError("Choose a study protocol and 1–12 explicit cases.");
    const title = input.title ?? "Robustness study",
      notes = input.notes ?? "";
    if (
      typeof title !== "string" ||
      !title.trim() ||
      title.length > 200 ||
      typeof notes !== "string" ||
      notes.length > 2000
    )
      throw studyError("Invalid study title or notes.");
    const action = input.protocol === "noise_seeds" ? "evaluate" : "perturb";
    const requests = input.cases.map((value) => {
      if (!plain(value) || Object.keys(value).sort().join(",") !== "radius_mm,seed")
        throw studyError("Each case requires only an explicit seed and radius_mm.");
      return normalizeDesignRequest({
        action,
        design: input.design,
        radius_mm: value.radius_mm,
        seed: value.seed,
      });
    });
    if (
      new Set(requests.map((request) => `${request.seed}:${request.radius_mm}`)).size !==
      requests.length
    )
      throw studyError("Each seed/radius pair must be unique.");
    if (
      input.protocol === "noise_seeds" &&
      new Set(requests.map((request) => request.radius_mm)).size !== 1
    )
      throw studyError(
        "Noise-seed studies hold radius fixed; radius affects displacement trials only.",
      );
    const annotation = {};
    if (input.design?.electrode_names !== undefined)
      annotation.electrode_names = electrodeNames(input.design.electrode_names);
    if (input.design?.source_metadata !== undefined) {
      annotation.source_metadata = validateCoordinateSource(input.design.source_metadata);
      annotation.electrode_names ??= Array.from({ length: 64 }, (_, index) => `E${index + 1}`);
    }
    return {
      protocol: input.protocol,
      title: title.trim(),
      notes,
      design: requests[0].design,
      annotation,
      requests,
    };
  } catch (error) {
    if (error.studySafe) throw error;
    throw studyError(error.message || "Invalid study input.");
  }
}
export function empiricalSummary(values) {
  const sorted = values
    .filter((value) => typeof value === "number" && Number.isFinite(value))
    .sort((a, b) => a - b);
  const quantile = (p) => {
    if (!sorted.length) return null;
    const h = (sorted.length - 1) * p,
      lower = Math.floor(h),
      upper = Math.ceil(h);
    return sorted[lower] + (sorted[upper] - sorted[lower]) * (h - lower);
  };
  return {
    n: sorted.length,
    median: quantile(0.5),
    p10: quantile(0.1),
    p90: quantile(0.9),
  };
}
export function summarizeStudyCase(result) {
  const trials = result.trials,
    valid = trials.filter((trial) => trial.status === "completed");
  return {
    nominal: structuredClone(result.nominal),
    trials: structuredClone(trials),
    valid_trials: valid.length,
    rejected_trials: trials.filter((trial) => trial.status === "geometry_rejected").length,
    trial_metrics: Object.fromEntries(
      trialMetrics.map((metric) => [metric, empiricalSummary(valid.map((trial) => trial[metric]))]),
    ),
  };
}
export function aggregateStudy(protocol, cases) {
  const count = (status) => cases.filter((value) => status.includes(value.status)).length;
  return {
    protocol,
    case_count: cases.length,
    completed_cases: count(["completed"]),
    failed_cases: count(["failed", "failed_uncertain"]),
    cancelled_cases: count(["cancelled"]),
    pending_cases: cases.filter((value) => !terminalCase(value.status)).length,
    quantile_method: "type7_linear",
    interpretation: "Ernie_within_model_empirical_cases",
    groups: [...new Set(cases.map((value) => value.request.radius_mm))]
      .sort((a, b) => a - b)
      .map((radius_mm) => {
        const selected = cases.filter((value) => value.request.radius_mm === radius_mm),
          complete = selected.filter((value) => value.status === "completed" && value.summary);
        return {
          radius_mm,
          case_count: selected.length,
          completed_cases: complete.length,
          failed_cases: selected.filter((value) =>
            ["failed", "failed_uncertain"].includes(value.status),
          ).length,
          nominal: Object.fromEntries(
            nominalMetrics.map((metric) => [
              metric,
              empiricalSummary(complete.map((value) => value.summary.nominal[metric])),
            ]),
          ),
          trial_case_medians: Object.fromEntries(
            trialMetrics.map((metric) => [
              metric,
              empiricalSummary(complete.map((value) => value.summary.trial_metrics[metric].median)),
            ]),
          ),
          trial_case_p10: Object.fromEntries(
            trialMetrics.map((metric) => [
              metric,
              empiricalSummary(complete.map((value) => value.summary.trial_metrics[metric].p10)),
            ]),
          ),
        };
      }),
  };
}
