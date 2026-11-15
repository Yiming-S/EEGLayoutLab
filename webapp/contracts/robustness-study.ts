import type {
  ElectrodeDesign,
  DesignResult,
  DesignTrial,
} from '../lib/design-decision';
import type { CoordinateSourceMetadata } from './coordinate-source';

export type StudyProtocol = 'noise_seeds' | 'grid_displacements';
export type StudyStatus =
  | 'draft'
  | 'running'
  | 'paused_recovery'
  | 'paused_resource'
  | 'cancelling'
  | 'completed'
  | 'completed_with_failures'
  | 'cancelled';
export type StudyCaseStatus =
  | 'pending'
  | 'submitting'
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'failed_uncertain';
export type EmpiricalSummary = {
  n: number;
  median: number | null;
  p10: number | null;
  p90: number | null;
};
export type StudyRequest = {
  action: 'evaluate' | 'perturb';
  design: Omit<ElectrodeDesign, 'electrode_names' | 'source_metadata'>;
  radius_mm: number;
  seed: number;
};
export type StudyCaseSummary = {
  nominal: DesignResult['nominal'];
  trials: DesignTrial[];
  valid_trials: number;
  rejected_trials: number;
  trial_metrics: Record<string, EmpiricalSummary>;
};
export type StudyCase = {
  index: number;
  request: StudyRequest;
  key: string;
  status: StudyCaseStatus;
  receipt_id: string | null;
  annotation_id?: string;
  error: { code: string; message: string } | null;
  summary: StudyCaseSummary | null;
  source_sha256?: string;
  source_bytes?: number;
};
export type StudyAggregation = {
  protocol: StudyProtocol;
  case_count: number;
  completed_cases: number;
  failed_cases: number;
  cancelled_cases: number;
  pending_cases: number;
  quantile_method: 'type7_linear';
  interpretation: 'Ernie_within_model_empirical_cases';
  groups: {
    radius_mm: number;
    case_count: number;
    completed_cases: number;
    failed_cases: number;
    nominal: Record<string, EmpiricalSummary>;
    trial_case_medians: Record<string, EmpiricalSummary>;
    trial_case_p10: Record<string, EmpiricalSummary>;
  }[];
};
export type RobustnessStudy = {
  cancel_requested?: boolean;
  schema: 'eeg-robustness-study/1';
  id: string;
  title: string;
  notes: string;
  protocol: StudyProtocol;
  status: StudyStatus;
  revision: number;
  created_at: string;
  updated_at: string;
  design: StudyRequest['design'];
  annotation: {
    electrode_names?: string[];
    source_metadata?: CoordinateSourceMetadata;
  };
  cases: StudyCase[];
  aggregation: StudyAggregation;
  last_error?: { code: string; message: string } | null;
};
export type StudyResponse = { study: RobustnessStudy };
export type StudyDirectoryEntry = Pick<
  RobustnessStudy,
  'id' | 'title' | 'protocol' | 'status' | 'created_at' | 'updated_at'
> & { case_count: number; completed_cases: number };
export type StudyExport = {
  schema: 'eeg-robustness-study-export/1';
  study: RobustnessStudy;
  cases: {
    index: number;
    key: string;
    source_sha256: string | null;
    cache: Record<string, unknown> | null;
    cache_json: string | null;
  }[];
};
