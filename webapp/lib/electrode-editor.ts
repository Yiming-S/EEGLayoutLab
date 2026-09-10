import type { SavedRecord } from './local-library';
export type XYZ = [number, number, number];
export type Slot = { bank_index: number; enabled: boolean };
export type EditorRequest = {
  action: 'evaluate';
  parent_id: string;
  parent_digest: string;
  seed: 2026;
  slots: Slot[];
};
export type EditorDomain = {
  parent: SavedRecord;
  original_indices: number[];
  regions: { bank_indices: number[]; xyz_mm: XYZ[] }[];
};
export type EditorMetrics = {
  field_relative: number;
  field_absolute: number;
  sensitivity_tail: number | null;
  localization_relative: number | null;
  median_mm: number | null;
  p90_mm: number | null;
  conditional_global?: number | null;
  localization_unavailable?: string | null;
};
export type EditorResult = {
  schema: 'electrode-editor/1';
  request: EditorRequest;
  status: 'completed';
  electrode_count: number;
  active_regions: number;
  declared_regions: number;
  baseline: EditorMetrics;
  parent_metrics: EditorMetrics;
  edited_metrics: EditorMetrics;
  active_slots: number[];
  evaluated_xyz_mm: XYZ[];
  region_indices: number[];
  minimum_distance_mm: number;
  provenance: Record<string, unknown>;
};
export type EditorJob = {
  id: string;
  key: string;
  status: string;
  progress: number;
  message: string;
  cached: boolean;
  parent_digest?: string;
  result?: EditorDomain | EditorResult;
};
export type EditorRecord = {
  key: string;
  protocol: string;
  finished_at: string;
  parent_label: string;
  parent_id: string;
  electrode_count: number;
  active_regions: number;
  metrics: EditorMetrics;
  request: EditorRequest;
};
export const initialSlots = (domain: EditorDomain): Slot[] =>
  domain.original_indices.map((bank_index) => ({ bank_index, enabled: true }));
export const slotKey = (slots: Slot[]) => JSON.stringify(slots);
export const pointMap = (domain: EditorDomain) =>
  new Map(
    domain.regions.flatMap((r) =>
      r.bank_indices.map((b, i) => [b, r.xyz_mm[i]] as const),
    ),
  );
export function draftError(
  slots: Slot[],
  domain: EditorDomain,
): 'count' | 'region' | 'spacing' | null {
  if (
    !Array.isArray(slots) ||
    slots.length !== 64 ||
    slots.some(
      (s) =>
        !s || typeof s.enabled !== 'boolean' || !Number.isInteger(s.bank_index),
    ) ||
    slots.filter((s) => s.enabled).length < 2
  )
    return 'count';
  const regions = domain.parent.layout!.regionIndices;
  if (
    slots.some(
      (s, i) => !domain.regions[regions[i]].bank_indices.includes(s.bank_index),
    )
  )
    return 'region';
  const points = pointMap(domain),
    active = slots
      .filter((s) => s.enabled)
      .map((s) => points.get(s.bank_index)!);
  for (let i = 0; i < active.length; i++)
    for (let j = i + 1; j < active.length; j++)
      if (Math.hypot(...active[i].map((v, k) => v - active[j][k])) < 4 - 1e-7)
        return 'spacing';
  return null;
}
export type EditHistory = { past: Slot[][]; present: Slot[]; future: Slot[][] };
export function editHistory(
  h: EditHistory,
  action: 'undo' | 'redo' | Slot[],
): EditHistory {
  if (action === 'undo')
    return h.past.length
      ? {
          past: h.past.slice(0, -1),
          present: h.past.at(-1)!,
          future: [h.present, ...h.future],
        }
      : h;
  if (action === 'redo')
    return h.future.length
      ? {
          past: [...h.past, h.present],
          present: h.future[0],
          future: h.future.slice(1),
        }
      : h;
  if (slotKey(action) === slotKey(h.present)) return h;
  return {
    past: [...h.past, h.present].slice(-50),
    present: action.map((s) => ({ ...s })),
    future: [],
  };
}
export const editorLink = (parent: string, ar: number) =>
  `/electrodes?parent=${encodeURIComponent(parent)}&ar=${ar}`;
