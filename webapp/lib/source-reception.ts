import { SOURCE_REGIONS, canonicalSourceRegions, type SourceRegionId } from './source-regions.ts';
export const BRAIN_REGIONS = SOURCE_REGIONS.map(r => [r.id, r.label] as const);
export const CONDITION_LABELS = {
  clean: '仅脑源＋测量噪声',
  ecg: '加入模拟心电干扰',
  eog: '加入模拟眼电干扰',
  mixed: '加入模拟心电＋眼电',
};
export type SourceCondition = keyof typeof CONDITION_LABELS;
export type SourceRequest = {
  record_id: string;
  waveform: 'burst' | 'rhythm';
  artifact_scale: number;
  seed: number;
  region_definition?: 'dk40-six-roi-v1';
} & ({ mode?: undefined; brain_region: string; source_index?: never; brain_regions?: never } | { mode: 'multi_source'; brain_region: string; source_index?: never; brain_regions?: never } | { mode: 'single_source'; source_index: number; brain_region?: never; brain_regions?: never } | { mode: 'cross_region'; brain_regions: SourceRegionId[]; brain_region?: never; source_index?: never });
export type SourceCatalog = { schema_version: 'source-catalog/1'; region_definition?: string; sources: { id: number; xyz_mm: [number, number, number]; normal: [number, number, number]; roi_id?: SourceRegionId | null; parcel_names?: string[] }[]; cross_region_representatives?: { source_region: SourceRegionId; generation_source_index: number; xyz_mm: [number, number, number]; normal: [number, number, number] }[]; provenance: Record<string, unknown> };
export type SourceMetrics = {
  nmse: number;
  explained_energy: number;
  brain_artifact_ratio_db: number | null;
  brain_noise_ratio_db: number | null;
};
export type SourceScore = {
  condition: SourceCondition;
  artifact_scale: number;
  baseline: SourceMetrics;
  candidate: SourceMetrics;
  field_retention: number | null;
};
export type Components = Record<
  | 'brain_uv'
  | 'ecg_uv'
  | 'eog_uv'
  | 'noise_uv'
  | 'reconstructed_brain_uv'
  | 'reconstructed_ecg_uv'
  | 'reconstructed_eog_uv'
  | 'reconstructed_noise_uv',
  number[][]
>;
export type SourceResult = {
  status: 'completed';
  schema_version: 'source-reception/1' | 'source-reception/2';
  request: SourceRequest;
  source: {
    region: string;
    selection_method: string;
    xyz_mm: [number, number, number][];
    bank_source_indices: number[];
    patch_count: number;
    normals_mri?: [number, number, number][];
    source_regions?: (SourceRegionId | null)[];
    region_definition?: string;
    source_parcels?: string[][];
    generation_source_indices?: number[];
  };
  layout: {
    xyzMm: [number, number, number][];
    referenceXyzMm: [number, number, number][];
    regionIndices: number[];
  };
  conditions: SourceScore[];
  strength_curve: SourceScore[];
  waveforms: {
    time_s: number[];
    source_nam: number[][];
    ecg_latent: number[];
    eog_latent: number[];
    baseline: Components;
    candidate: Components;
  };
  metrics: { pure_brain_amplitude_ratio: number | null };
  protocol: Record<string, unknown>;
  provenance: Record<string, unknown>;
};
export type SourceJob = {
  id: string;
  key: string;
  request: SourceRequest;
  status:
    | 'queued'
    | 'running'
    | 'cancelling'
    | 'completed'
    | 'failed'
    | 'timeout'
    | 'cancelled';
  progress: number;
  message: string;
  result: SourceResult | null;
  cached: boolean;
};
export function sourceKey(r: SourceRequest) {
  if (r.mode) return JSON.stringify({ record_id: r.record_id, waveform: r.waveform, artifact_scale: r.artifact_scale, seed: r.seed, mode: r.mode,
    ...(r.region_definition ? { region_definition: r.region_definition } : {}),
    ...(r.mode === 'single_source' ? { source_index: r.source_index } : r.mode === 'cross_region' ? { brain_regions: canonicalSourceRegions(r.brain_regions) } : { brain_region: r.brain_region }) });
  return JSON.stringify({
    record_id: r.record_id,
    brain_region: r.brain_region,
    waveform: r.waveform,
    artifact_scale: r.artifact_scale,
    seed: r.seed,
  });
}
export function sourcePass(value: number | null | undefined, ar: number) {
  return value == null || !Number.isFinite(value)
    ? 'undefined'
    : value >= ar / 100
      ? 'pass'
      : 'fail';
}
export function combinedTrace(
  components: Components,
  channel: number,
  condition: SourceCondition,
  reconstructed = false,
) {
  const p = reconstructed ? 'reconstructed_' : '';
  const brain = components[`${p}brain_uv`],
    ecg = components[`${p}ecg_uv`],
    eog = components[`${p}eog_uv`],
    noise = components[`${p}noise_uv`];
  return brain[channel].map((b, t) => {
    const artifact =
      (condition === 'ecg' || condition === 'mixed' ? ecg[channel][t] : 0) +
      (condition === 'eog' || condition === 'mixed' ? eog[channel][t] : 0);
    return { brain: b, artifact, mixed: b + artifact + noise[channel][t] };
  });
}
export function sourceExperimentLink(id: string, ar: number, returnTo: string) {
  return `/reception?record=${id}&ar=${ar}&returnTo=${encodeURIComponent(returnTo)}`;
}
export function sourceBackLink(back: string, ar: number) {
  const url = new URL(back, 'http://localhost');
  url.searchParams.set('ar', String(ar));
  return url.pathname + url.search;
}
