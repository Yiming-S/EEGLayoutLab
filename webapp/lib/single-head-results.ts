import type { XYZ } from './fixed64-results';

export type SingleMetric = {
  snr_db: number;
  field_relative: number | null;
  field_absolute: number | null;
  sensitivity_tail: number | null;
  localization_relative: number | null;
  localization_utility: number | null;
  conditional_global: number | null;
  median_mm: number;
  p90_mm: number;
  p95_mm: number;
  effective_rank: number;
};
export type SingleVariant = {
  id: string;
  objective: string;
  xyz_mm: XYZ[];
  region_indices: number[];
  center_xyz_mm: XYZ[];
  region_areas_cm2: number[];
  initial: { field20: number; sensitivity_tail: number | null };
  accepted_moves: number;
  conditions: SingleMetric[];
};
export type SingleCondition = {
  id: string;
  family_id: string;
  R: number;
  radius_mm: number;
  spacing_mm: number;
  region_roi_ids: string[];
  mode: string;
  status: string;
  failure_reason: string | null;
  max_achieved_counts: number[] | null;
  variants: SingleVariant[];
};
export type SingleHeadResults = {
  schema: 'single-head-app/1';
  scope: {
    head_count: 1;
    physical_electrode_count: 64;
    formal_ar: false;
    conditional_ar: true;
  };
  baseline: {
    xyz_mm: XYZ[];
    conditions: Array<{
      snr_db: number;
      field_absolute: number;
      field_relative: number;
      sensitivity_tail: number;
      loc_util: number;
      loc_relative: number | null;
      conditional_global: number | null;
      median_mm: number;
      p90_mm: number;
      p95_mm: number;
    }>;
  };
  conditions: SingleCondition[];
  families: Array<{ id: string; R: number; regions: string[]; mode: string }>;
  config: { radius_caps_mm: number[]; minimum_chord_spacings_mm: number[] };
  limits: string[];
  provenance: {
    run_id: string;
    batch_id: string;
    report_sha256: string;
    bank_sha256: string;
  };
  summary_counts: Record<string, number>;
};
export type Criterion =
  | 'field_relative'
  | 'sensitivity_tail'
  | 'localization_relative'
  | 'conditional_global';
export const CRITERIA: Array<{ id: Criterion; label: string }> = [
  { id: 'field_relative', label: '信号重建保留率' },
  { id: 'sensitivity_tail', label: '幅度保留率（最差10%）' },
  { id: 'localization_relative', label: '相对定位评分' },
  { id: 'conditional_global', label: '三项最低相对评分 G' },
];
export const REGION_COUNTS = [1, 2, 3, 4, 6];
export const REGION_COLORS = [
  '#157e81',
  '#b87232',
  '#7277bd',
  '#a55779',
  '#547b35',
];
const FAMILY_LABELS: Record<string, string> = {
  bilateral_near_ear: '双侧耳后邻近',
  left_ear_forehead: '左耳后＋前额',
  right_ear_forehead: '右耳后＋前额',
  bilateral_expanded_ear: '双侧扩展耳周',
  bilateral_ear_forehead: '双耳后＋前额',
  bilateral_ear_split_forehead: '双耳后＋双侧前额',
  bilateral_ear_forehead_orbital: '双耳后＋双侧前额＋双侧眶周',
};
export function familyLabel(id: string) {
  if (id.endsWith('_whole_scalp_free')) return '全头候选区';
  if (id.endsWith('_low_hair_free')) return '少毛发候选区（模型近似）';
  return FAMILY_LABELS[id] ?? id;
}
export function metricAt(variant: SingleVariant | undefined, snr: number) {
  return variant?.conditions.find((row) => row.snr_db === snr);
}
export function bestVariant(
  condition: SingleCondition | undefined,
  snr: number,
  criterion: Criterion,
) {
  return condition?.variants
    .filter((variant) => {
      const value = metricAt(variant, snr)?.[criterion];
      return value != null && Number.isFinite(value);
    })
    .sort(
      (a, b) => metricAt(b, snr)![criterion]! - metricAt(a, snr)![criterion]!,
    )[0];
}
export function allocationFor(r: number) {
  return Array.from(
    { length: r },
    (_, i) => Math.floor(64 / r) + (i < 64 % r ? 1 : 0),
  );
}
export function arDecision(
  row: SingleMetric | undefined,
  ar: number,
): 'pass' | 'fail' | 'undefined' {
  if (
    row?.conditional_global == null ||
    !Number.isFinite(row.conditional_global)
  )
    return 'undefined';
  return row.conditional_global >= ar ? 'pass' : 'fail';
}
export function checkSingleHeadResults(value: unknown): SingleHeadResults {
  const data = value as SingleHeadResults;
  const xyz = (v: unknown): v is XYZ[] =>
    Array.isArray(v) &&
    v.length === 64 &&
    v.every(
      (p) => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite),
    );
  if (
    data?.schema !== 'single-head-app/1' ||
    data.scope?.head_count !== 1 ||
    data.scope.physical_electrode_count !== 64 ||
    data.scope.formal_ar !== false ||
    data.scope.conditional_ar !== true ||
    !xyz(data.baseline?.xyz_mm)
  )
    throw new Error('单头模结果格式或证据等级不符');
  if (
    !Array.isArray(data.conditions) ||
    data.conditions.length !== 204 ||
    new Set(data.conditions.map((c) => c.id)).size !== 204
  )
    throw new Error('204个实验条件记录不完整');
  for (const c of data.conditions) {
    if (
      !REGION_COUNTS.includes(c.R) ||
      !Array.isArray(c.variants) ||
      !['completed_best_found', 'no_complete_layout_constructed'].includes(
        c.status,
      )
    )
      throw new Error('存在非终态实验条件');
    if ((c.status === 'completed_best_found') !== c.variants.length > 0)
      throw new Error('布局状态与数据不一致');
    for (const v of c.variants) {
      if (
        !xyz(v.xyz_mm) ||
        v.region_indices.length !== 64 ||
        new Set(v.xyz_mm.map((p) => p.join(','))).size !== 64 ||
        v.region_indices.some(
          (i) => !Number.isInteger(i) || i < 0 || i >= c.R,
        ) ||
        allocationFor(c.R).some(
          (count, i) =>
            v.region_indices.filter((r) => r === i).length !== count,
        )
      )
        throw new Error('64点布局或区域分配不符');
      if (
        v.conditions.length !== 3 ||
        new Set(v.conditions.map((m) => m.snr_db)).size !== 3
      )
        throw new Error('噪声条件不完整');
      for (const m of v.conditions) {
        if (
          ![0, 10, 20].includes(m.snr_db) ||
          ![m.median_mm, m.p90_mm, m.p95_mm].every(
            (n) => Number.isFinite(n) && n >= 0,
          )
        )
          throw new Error('定位误差记录无效');
        const values = [
          m.field_relative,
          m.sensitivity_tail,
          m.localization_relative,
        ];
        if (values.some((n) => n !== null && !Number.isFinite(n)))
          throw new Error('存在无效保留率');
        const expected = values.every((n) => n !== null)
          ? Math.min(...(values as number[]))
          : null;
        if (
          expected === null
            ? m.conditional_global !== null
            : m.conditional_global === null ||
              Math.abs(m.conditional_global - expected) > 1e-9
        )
          throw new Error('条件AR最小值计算不符');
      }
    }
  }
  if (
    REGION_COUNTS.some(
      (r) => !data.conditions.some((c) => c.R === r && c.variants.length),
    )
  )
    throw new Error('五种区域数尚未全部获得评分布局');
  return data;
}
