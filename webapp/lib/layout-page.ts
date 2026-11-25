import type { SavedSummary } from './local-library';
import { protocolName, recordAllocationLabel, recordConditionLabels, recordNoiseLabel, recordObjectiveLabel } from './ui-language.ts';

/** Address of a layout's page: by its layout key, or by one of its records (the page finds the key). */
export function layoutHref(target: { key: string } | { id: string }, ar = 90) {
  const q = new URLSearchParams('key' in target ? { key: target.key } : { id: target.id });
  q.set('ar', String(ar));
  return '/layout?' + q.toString();
}

/** Nominal evaluations first, then robustness, then other conditions. */
export function conditionRank(record: SavedSummary) {
  if (record.evaluation_condition || record.request?.noise_model || record.request?.data_prior) return 2;
  return record.robustness ? 1 : 0;
}
const DATASET_ORDER: SavedSummary['dataset_id'][] = ['strict_area', 'cache', 'design_evaluation', 'historical_area', 'offline_radius'];
const finished = (record: SavedSummary) => (record.finished_at ? Date.parse(record.finished_at) : 0) || 0;
export function byCondition(a: SavedSummary, b: SavedSummary) {
  return conditionRank(a) - conditionRank(b) || DATASET_ORDER.indexOf(a.dataset_id) - DATASET_ORDER.indexOf(b.dataset_id) ||
    finished(b) - finished(a) || a.id.localeCompare(b.id);
}

/** Every saved evaluation of one set of coordinates, nominal first. */
export function layoutEvaluations(records: SavedSummary[], key: string) {
  return records.filter(record => record.layout_key === key).sort(byCondition);
}
export const primaryRecord = (records: SavedSummary[]) => records.slice().sort(byCondition)[0] ?? null;

/** One library row per layout key; a record without a key (no layout) is its own row. */
export function groupByLayout(records: SavedSummary[]) {
  const groups = new Map<string, SavedSummary[]>(), rows: SavedSummary[][] = [];
  for (const record of records) {
    if (!record.layout_key) { rows.push([record]); continue; }
    const group = groups.get(record.layout_key);
    if (group) group.push(record);
    else { const created = [record]; groups.set(record.layout_key, created); rows.push(created); }
  }
  return rows.map(group => group.sort(byCondition));
}

/** The conditions of one evaluation, one label each: protocol, allocation, noise, non-default conditions, robustness. */
export function evaluationLabels(record: SavedSummary) {
  const noise = recordNoiseLabel(record), allocation = recordAllocationLabel(record), objective = recordObjectiveLabel(record);
  return [protocolName(record.dataset_id), ...(allocation ? [allocation] : []), ...(objective ? [objective] : []), ...(noise ? [noise] : []), ...recordConditionLabels(record), ...(record.robustness ? ['跨会话稳健性'] : [])];
}

const completed = (records: SavedSummary[]) => records.filter(record => record.status === 'completed' && finished(record));
const latest = (group: SavedSummary[]) => Math.max(...group.map(finished));

/** The most recently evaluated layouts, one entry per layout (a record without coordinates is its own), each nominal evaluation first. */
export function recentLayouts(records: SavedSummary[], count: number) {
  return groupByLayout(completed(records)).sort((a, b) => latest(b) - latest(a)).slice(0, count);
}

/** A layout to open as an example: the one evaluated under the most conditions, then the most recent. */
export function exampleLayout(records: SavedSummary[]) {
  const [best] = groupByLayout(completed(records).filter(record => record.layout_key)).sort((a, b) => b.length - a.length || latest(b) - latest(a));
  return best?.[0].layout_key ?? null;
}
