import type { XYZ } from '../../contracts/layout';
export type { XYZ } from '../../contracts/layout';
export type FieldCondition = {
  snr_db: number;
  field_absolute: number;
  field_relative: number;
  effective_rank: number;
};
export type LocalizationCondition = {
  snr_db: number;
  median_mm: number;
  p90_mm: number;
  p95_mm: number;
};
type Metrics = { conditions: FieldCondition[]; sensitivity_tail: number };
export type SimulationLayout = {
  id: string;
  index: number;
  family_id: string;
  radius_cap_mm: number;
  spacing_min_mm: number;
  region_areas_cm2: number[];
  xyz_mm: XYZ[];
  region_indices: number[];
  metrics: Metrics;
  localization: LocalizationCondition[] | null;
};
export type Fixed64Results = {
  schema_version: string;
  run_id: string;
  evidence_level: 'exploratory';
  formal_ar: false;
  head_count: number;
  configuration_count: number;
  unique_layout_count: number;
  snr_db: number[];
  reference: {
    label: string;
    xyz_mm: XYZ[];
    metrics: Metrics;
    localization: LocalizationCondition[];
  };
  layouts: SimulationLayout[];
  provenance: {
    report_sha256: string;
    forward_sha256: string;
    metrics_sha256: string;
    repeat_batches: string[];
    byte_reproducible: boolean;
  };
  limitations: string[];
};
export const RESULT_FAMILIES = [
  {
    id: 'bilateral_near_ear_posterolateral_approx_32_32',
    label: '双侧耳后邻近',
    color: '#147d92',
  },
  {
    id: 'left_near_ear_posterolateral_approx_32_upper_forehead_approx_32',
    label: '左耳后邻近＋前额',
    color: '#b96c29',
  },
  {
    id: 'right_near_ear_posterolateral_approx_32_upper_forehead_approx_32',
    label: '右耳后邻近＋前额',
    color: '#8965b0',
  },
  {
    id: 'bilateral_expanded_periauricular_approx_32_32',
    label: '双侧扩展耳周',
    color: '#409568',
  },
] as const;

export function selectRecordedLayout(
  data: Fixed64Results,
  family: string,
  radius: number,
  spacing: number,
) {
  // Exact matching only. No nearest configuration, interpolation, or fabricated scores.
  return (
    data.layouts.find(
      (r) =>
        r.family_id === family &&
        r.radius_cap_mm === radius &&
        r.spacing_min_mm === spacing,
    ) ?? null
  );
}

export function atSnr<T extends { snr_db: number }>(
  conditions: T[] | null,
  snr: number,
): T | null {
  return conditions?.find((c) => c.snr_db === snr) ?? null;
}

export function retentionPercent(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value)
    ? '未计算'
    : `${(value * 100).toFixed(2)}%`;
}

export function mriMmToDisplay(xyz: XYZ): XYZ {
  if (xyz.length !== 3 || !xyz.every(Number.isFinite))
    throw new Error('无效的实验坐标');
  // The Ernie display uses the original right/anterior/superior frame. 1 unit = 100 mm.
  return xyz.map((v) => v / 100) as XYZ;
}

export function checkResults(value: unknown): Fixed64Results {
  const data = value as Fixed64Results | null;
  const validPoints = (points: unknown) =>
    Array.isArray(points) &&
    points.length === 64 &&
    points.every(
      (point: unknown) =>
        Array.isArray(point) &&
        point.length === 3 &&
        point.every(Number.isFinite),
    );
  const validMetrics = (metrics: Metrics | undefined) =>
    metrics &&
    Number.isFinite(metrics.sensitivity_tail) &&
    Array.isArray(metrics.conditions) &&
    metrics.conditions.length === 3 &&
    [0, 10, 20].every((snr) => {
      const condition = metrics.conditions.find((item) => item?.snr_db === snr);
      return (
        condition &&
        [
          condition.field_absolute,
          condition.field_relative,
          condition.effective_rank,
        ].every(Number.isFinite)
      );
    });
  const validLocalization = (
    conditions: LocalizationCondition[] | null | undefined,
  ) =>
    conditions === null ||
    (Array.isArray(conditions) &&
      conditions.length === 3 &&
      [0, 10, 20].every((snr) => {
        const condition = conditions.find((item) => item?.snr_db === snr);
        return (
          condition &&
          [condition.median_mm, condition.p90_mm, condition.p95_mm].every(
            (v) => Number.isFinite(v) && v >= 0,
          ) &&
          condition.median_mm <= condition.p90_mm &&
          condition.p90_mm <= condition.p95_mm
        );
      }));
  if (
    !data ||
    data.schema_version !== 'compact-eeg-fixed64-app-results/1' ||
    data.evidence_level !== 'exploratory' ||
    data.formal_ar !== false ||
    data.head_count !== 1 ||
    !Array.isArray(data.snr_db) ||
    data.snr_db.join(',') !== '0,10,20' ||
    !Array.isArray(data.layouts) ||
    data.layouts.length !== data.configuration_count ||
    !Number.isInteger(data.unique_layout_count) ||
    data.unique_layout_count > data.configuration_count ||
    !validPoints(data.reference?.xyz_mm) ||
    !validMetrics(data.reference?.metrics) ||
    !Array.isArray(data.reference?.localization) ||
    !validLocalization(data.reference.localization) ||
    !data.provenance ||
    !Array.isArray(data.provenance.repeat_batches) ||
    data.layouts.some(
      (r) =>
        !r ||
        !validPoints(r.xyz_mm) ||
        !Array.isArray(r.region_indices) ||
        r.region_indices.length !== 64 ||
        r.region_indices.filter((i) => i === 0).length !== 32 ||
        r.region_indices.filter((i) => i === 1).length !== 32 ||
        !Array.isArray(r.region_areas_cm2) ||
        r.region_areas_cm2.length !== 2 ||
        !r.region_areas_cm2.every((a) => Number.isFinite(a) && a > 0) ||
        !RESULT_FAMILIES.some((f) => f.id === r.family_id) ||
        !validMetrics(r.metrics) ||
        !validLocalization(r.localization),
    )
  ) {
    throw new Error('结果文件的证据等级或64电极结构不一致');
  }
  return data;
}
