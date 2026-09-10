import type { ComputedLayout, ComputeRequest, ComputeResult } from './local-compute';

export type SavedSummary = {
  id: string;
  dataset_id: 'cache' | 'strict_area' | 'offline_radius' | 'historical_area' | 'design_evaluation';
  label: string;
  region_count: number;
  mode: string;
  status: 'completed' | 'no_layout';
  compatible: boolean;
  request: ComputeRequest | null;
  radius_cap_mm?: number;
  area_cap_cm2?: number;
  spacing_mm: number;
  finished_at?: string;
  metrics: ComputeResult['metrics'];
  geometry: ComputeResult['geometry'];
};
export type SavedRecord = SavedSummary & { layout: ComputedLayout | null; provenance: Record<string, unknown> };
export type LocalLibrary = {
  schema: 'local-data-library/1';
  datasets: Array<{ id: SavedSummary['dataset_id']; label: string; note: string; count: number }>;
  records: SavedSummary[];
  warnings: string[];
};

export function designLink(record: SavedSummary, ar = 90) {
  // A historical record may supply parameters, never a current cache result.
  return record.dataset_id === 'cache' && record.request
    ? `/design?saved=${record.id}&ar=${ar}` : null;
}
