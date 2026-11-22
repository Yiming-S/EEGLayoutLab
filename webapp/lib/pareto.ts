/**
 * Multi-objective comparison of saved layouts: Pareto ranks by non-dominated sorting.
 *
 * A layout dominates another when it is at least as good on every chosen objective and better on one.
 * Rank 1 is the Pareto front; rank k is the front after removing ranks below k. Only layouts evaluated
 * under the same protocol and condition are compared, since their scores are the same quantity.
 */
import type { SavedSummary } from './local-library';

export type ObjectiveId = 'field' | 'sensitivity' | 'localization' | 'p90' | 'area' | 'dropout' | 'impedance' | 'replacement';
export type ParetoObjective = { id: ObjectiveId; label: string; direction: 'max' | 'min'; unit: 'ratio' | 'mm' | 'cm2' };
export const PARETO_OBJECTIVES: ParetoObjective[] = [
  { id: 'field', label: '重建保留率', direction: 'max', unit: 'ratio' },
  { id: 'sensitivity', label: '幅度保留率', direction: 'max', unit: 'ratio' },
  { id: 'localization', label: '相对定位评分', direction: 'max', unit: 'ratio' },
  { id: 'p90', label: '定位误差P90', direction: 'min', unit: 'mm' },
  { id: 'area', label: '电极贴片总面积', direction: 'min', unit: 'cm2' },
  { id: 'dropout', label: '随机脱落4个电极后的重建保留率', direction: 'max', unit: 'ratio' },
  { id: 'impedance', label: '电极噪声不均（对数标准差1.0）后的重建保留率', direction: 'max', unit: 'ratio' },
  { id: 'replacement', label: '重新佩戴10 mm后的重建保留率（沿用原重建器）', direction: 'max', unit: 'ratio' },
];
export const DEFAULT_OBJECTIVES: ObjectiveId[] = ['field', 'sensitivity', 'localization'];
export type ObjectiveValues = Partial<Record<ObjectiveId, number | null>>;

const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const level = (levels: number[] | undefined, values: (number | null)[] | undefined, wanted: number) => {
  const index = levels?.indexOf(wanted) ?? -1;
  return index >= 0 ? values?.[index] ?? null : null;
};

/** Objective values of a library record; null where the record did not compute them. */
export function summaryObjectives(record: Pick<SavedSummary, 'metrics' | 'geometry' | 'robustness'>): ObjectiveValues {
  const m = record.metrics, robust = record.robustness;
  return {
    field: m?.field_relative ?? null, sensitivity: m?.sensitivity_tail ?? null, localization: m?.localization_relative ?? null,
    p90: m?.p90_mm ?? null, area: record.geometry?.union_area_cm2 ?? null,
    dropout: level(robust?.dropout.removed, robust?.dropout.candidate, 4),
    impedance: level(robust?.impedance.log_sd, robust?.impedance.candidate, 1),
    replacement: level(robust?.replacement?.rms_mm, robust?.replacement?.fixed.candidate, 10),
  };
}

/**
 * Records whose scores are the same quantity: current-protocol datasets with identical noise model,
 * conductivity scenario, head and data prior. Historical experiments are interpreted under their own protocols.
 */
export function comparisonGroup(record: Pick<SavedSummary, 'dataset_id' | 'status' | 'compatible' | 'request' | 'evaluation_condition'>) {
  const current = record.dataset_id === 'design_evaluation' || record.dataset_id === 'strict_area' || (record.dataset_id === 'cache' && record.compatible);
  if (!current || record.status !== 'completed') return null;
  const c = record.evaluation_condition;
  const prior = record.request?.data_prior ?? c?.data_prior;
  return JSON.stringify({ noise: record.request?.noise_model ?? c?.noise_model ?? null, scenario: c?.conductivity_scenario ?? null, head: c?.head_id ?? null,
    ...(prior ? { prior } : {}) });
}

/** a dominates b: no worse on every objective, strictly better on one (ties within 1e-12 are equal). */
export function dominates(a: number[], b: number[], directions: ParetoObjective['direction'][]) {
  let better = false;
  for (let k = 0; k < a.length; k++) {
    const gain = directions[k] === 'max' ? a[k] - b[k] : b[k] - a[k];
    if (gain < -1e-12) return false;
    if (gain > 1e-12) better = true;
  }
  return better;
}

/** Non-dominated sorting: 1-based rank per point and how many points dominate it. */
export function paretoRanks(points: number[][], directions: ParetoObjective['direction'][]) {
  const n = points.length, dominatedBy: number[] = Array.from({ length: n }, () => 0), dominating: number[][] = points.map(() => []);
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++)
      if (i !== j && dominates(points[i], points[j], directions)) { dominating[i].push(j); dominatedBy[j]++; }
  const rank: number[] = Array.from({ length: n }, () => 0), remaining = [...dominatedBy];
  let front = remaining.flatMap((count, i) => (count === 0 ? [i] : [])), current = 1;
  while (front.length) {
    const next: number[] = [];
    for (const i of front) {
      rank[i] = current;
      for (const j of dominating[i]) if (--remaining[j] === 0) next.push(j);
    }
    front = next; current++;
  }
  return { rank, dominatedBy };
}

export type ParetoRow<T> = { item: T; values: number[]; rank: number; dominated_by: number };
/** Ranked items (front first, then by the first objective) and the items missing a chosen objective. */
export function paretoAnalysis<T>(items: { item: T; values: ObjectiveValues }[], objectives: ObjectiveId[]) {
  if (!objectives.length || new Set(objectives).size !== objectives.length || objectives.some(id => !PARETO_OBJECTIVES.some(o => o.id === id)))
    throw new Error('请选择不重复的比较目标');
  const chosen = objectives.map(id => PARETO_OBJECTIVES.find(o => o.id === id)!);
  const complete = items.filter(entry => objectives.every(id => finite(entry.values[id])));
  const excluded = items.filter(entry => !complete.includes(entry)).map(entry => entry.item);
  const points = complete.map(entry => objectives.map(id => entry.values[id] as number));
  const { rank, dominatedBy } = paretoRanks(points, chosen.map(o => o.direction));
  const first = chosen[0].direction === 'max' ? -1 : 1;
  const rows: ParetoRow<T>[] = complete.map((entry, i) => ({ item: entry.item, values: points[i], rank: rank[i], dominated_by: dominatedBy[i] }))
    .sort((a, b) => a.rank - b.rank || first * (a.values[0] - b.values[0]));
  return { objectives: chosen, rows, excluded };
}
