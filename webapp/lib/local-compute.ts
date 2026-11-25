import type { DomainMode, RecordedLayout } from '../../contracts/layout';
import type { DataPriorRequest } from './api-types';

export type ComputeRequest = {
  region_count: number;
  radius_mm: number;
  mode: DomainMode;
  mask_codes?: string[];
  /** Optional search noise model; absent means independent equal noise. */
  noise_model?: SearchNoiseModel;
  /** Optional data-derived source prior and noise (eeg-data-prior/1 request value); replaces noise_model. */
  data_prior?: DataPrior;
  /** Optional multi-region electrode quota mode; absent means balanced K/R default. */
  allocation_mode?: 'adaptive';
  /** Optional search objective mode; absent means min(field, sensitivity) default. */
  objective_mode?: 'composite';
  /** Optional total electrode count; absent means 64 default. */
  electrode_count?: 8 | 12 | 16 | 24 | 32 | 48;
};
/** Region gains in DATA_PRIOR_REGIONS order and the fitted noise correlation (eeg-data-prior/1 request value). */
export type DataPrior = DataPriorRequest;
export type SearchNoiseModel = { kind: 'spatial'; rho: 0.5; length_mm: 10 | 20 | 40 };
export type ComputedLayout = RecordedLayout;
export type ComputeResult = {
  status: 'completed' | 'no_layout';
  request: ComputeRequest;
  layout?: ComputedLayout | null;
  metrics?: {
    field_relative: number | null;
    field_absolute: number | null;
    reference_field_absolute: number | null;
    sensitivity_tail: number | null;
    localization_relative: number | null;
    conditional_global: number | null;
    median_mm: number | null;
    p90_mm: number | null;
    reference_median_mm: number | null;
  } | null;
  geometry?: {
    common_graph_radius_mm: number;
    union_area_cm2: number;
    minimum_chord_distance_mm: number;
    union_connected_component_count: number;
  } | null;
};
export type ComputeJob = {
  id: string;
  /** Server FIFO position while queued; 1 means next to start. */
  queue_position?: number;
  key: string;
  request: ComputeRequest;
  status: 'queued' | 'running' | 'cancelling' | 'completed' | 'no_layout' | 'failed' | 'cancelled' | 'timeout';
  stage: string;
  progress: number;
  message: string;
  result: ComputeResult | null;
  cached?: boolean;
  source?: 'local_cache' | 'local_compute';
};
export type ComputeHealth = {
  available: boolean;
  token: string;
  supported_masks: string[];
  active_job: ComputeJob | null;
};

export function requestKey(request: ComputeRequest) {
  return JSON.stringify({ region_count: request.region_count, radius_mm: request.radius_mm,
    mode: request.mode, ...(request.mode === 'preset' ? { mask_codes: request.mask_codes } : {}),
    ...(request.noise_model ? { noise_model: request.noise_model } : {}),
    ...(request.data_prior ? { data_prior: request.data_prior } : {}),
    ...(request.allocation_mode ? { allocation_mode: request.allocation_mode } : {}),
    ...(request.objective_mode ? { objective_mode: request.objective_mode } : {}),
    ...(request.electrode_count ? { electrode_count: request.electrode_count } : {}) });
}

export function matchingResult(job: ComputeJob | null, request: ComputeRequest) {
  return job?.status === 'completed' && job.result?.status === 'completed' &&
    requestKey(job.request) === requestKey(request) && requestKey(job.result.request) === requestKey(request)
    ? job.result : null;
}

export function displayJob(active: ComputeJob | null, stored: ComputeJob | null, request: ComputeRequest) {
  const key = requestKey(request);
  if (active && requestKey(active.request) === key && ['completed', 'no_layout'].includes(active.status)) return active;
  return stored && requestKey(stored.request) === key ? stored : active;
}

export const jobRunning = (job: ComputeJob | null) => !!job && ['queued', 'running', 'cancelling'].includes(job.status);

export function currentAR(globalRetention: number | null | undefined, arPercent: number) {
  if (globalRetention == null || !Number.isFinite(globalRetention)) return null;
  return globalRetention >= arPercent / 100;
}
