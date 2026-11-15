import type { ComputedLayout, ComputeRequest, ComputeResult } from './local-compute';
import type { CoordinateSourceMetadata } from '../contracts/coordinate-source';

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
export type ElectrodeAnnotation = { schema: 'eeg-electrode-annotation/1'; id: string; record_id: string; request_sha256: string; electrode_names: string[]; source_metadata?: CoordinateSourceMetadata };
export type SavedRecord = SavedSummary & { layout: ComputedLayout | null; provenance: Record<string, unknown>; electrode_annotation?: ElectrodeAnnotation };
export type LocalLibrary = {
  schema: 'local-data-library/1';
  datasets: Array<{ id: SavedSummary['dataset_id']; label: string; note: string; count: number }>;
  records: SavedSummary[];
  warnings: string[];
  electrode_annotations?: ElectrodeAnnotation[];
};

export function recordAnnotationId(href: string, recordId: string | null | undefined) {
  if (!recordId) return undefined;
  const q = new URL(href, 'http://localhost').searchParams;
  const value = q.get('annotation_record') === recordId ? q.get('annotation_id') :
    q.get('a') === recordId ? q.get('annotation_a') : q.get('b') === recordId ? q.get('annotation_b') :
    q.get('record') === recordId ? q.get('annotation_id') : null;
  return value && /^[a-f0-9]{64}$/.test(value) ? value : undefined;
}

export function canSimulateRecord(record: SavedRecord | null | undefined) {
  return !!record && record.status === 'completed' &&
    ['cache', 'strict_area', 'design_evaluation'].includes(record.dataset_id) &&
    record.layout?.xyzMm.length === 64;
}

export function designLink(record: SavedSummary, ar = 90) {
  // A historical record may supply parameters, never a current cache result.
  return record.dataset_id === 'cache' && record.request
    ? `/design?saved=${record.id}&ar=${ar}` : null;
}
