import type { SavedRecord } from './local-library';
import { translateText, type Locale } from './i18n/core.ts';
import { localizedRecordTitle } from './i18n/records.ts';
import { parseAR } from './lab-workflow.ts';
import { validateCoordinateSource } from '../contracts/coordinate-source.mjs';
import { CONDUCTIVITY_SCENARIOS, ELECTRODE_COUNTS, NOISE_MODEL_PRESETS, normalizeDataPrior } from '../contracts/scientific-options.mjs';
import type { CoordinateSourceMetadata } from '../contracts/coordinate-source';
import type { RobustnessBlock } from './design-robustness.ts';
import type { DataPrior } from './local-compute';
import type { ConductivityScenarioId, DesignEvaluationBody, DesignEvaluationRequest, PerturbationRadius } from './api-types';

export type NoiseModel = { kind: 'spatial'; rho: 0.5; length_mm: 10 | 20 | 40 } | { kind: 'brain_background'; fraction: 0.5 };

export type ElectrodeDesign = {
  schema: 'eeg-electrode-design/1';
  coordinate_system: 'ernie_native_mm';
  unit: 'mm';
  name: string;
  xyz_mm: [number, number, number][];
  region_indices: number[];
  electrode_names?: string[];
  source_metadata?: CoordinateSourceMetadata;
};
export type RecordCoordinates = {
  name: string;
  xyz_mm: [number, number, number][];
  region_indices: number[];
  electrode_names?: string[];
};
export type DecisionThresholds = {
  mode?: 'joint' | 'custom';
  field: number;
  sensitivity: number | null;
  localization: number | null;
  p90_mm: number | null;
};
export type DesignTrial = {
  index: number;
  actual_max_mm: number;
  actual_mean_mm: number;
  target_error_max_mm: number;
  unchanged_fraction: number;
  field_relative: number | null;
  fixed_estimator_field_relative: number | null;
  status: string;
  message?: string;
};
export type DesignResult = {
  forward_mode: string;
  evaluated_xyz_mm: [number, number, number][];
  nominal: {
    field_relative: number;
    field_absolute: number;
    reference_field_absolute: number;
    sensitivity_tail: number | null;
    median_mm: number;
    p90_mm: number;
    localization_relative: number | null;
    reference_median_mm: number;
    reference_p90_mm: number;
  };
  projection_max_mm: number;
  trials: DesignTrial[];
  /** Present only for requests with `robustness: 'standard/1'`. */
  robustness?: RobustnessBlock;
};
export type DesignJob = {
  id: string;
  /** Server FIFO position while queued; 1 means next to start. */
  queue_position?: number;
  status: string;
  message: string;
  progress: number;
  result: DesignResult | null;
  key?: string;
  cached?: boolean;
  /** Normalized request echoed by the queue; present on receipts and active jobs. */
  request?: { action?: string; design?: unknown; radius_mm?: number; seed?: number; noise_model?: unknown; conductivity_scenario?: string; robustness?: string; data_prior?: unknown };
  annotation_id?: string;
  electrode_annotation?: SavedRecord['electrode_annotation'];
};
const finite = (n: unknown): n is number =>
  typeof n === 'number' && Number.isFinite(n);
function hasNameControl(value: string) {
  for (let index = 0; index < value.length; index++) if (value.charCodeAt(index) < 32 || value.charCodeAt(index) === 127) return true;
  return false;
}
export function jointDecisionThresholds(field = 90): DecisionThresholds {
  field = parseAR(String(field));
  return { mode: 'joint', field, sensitivity: field, localization: field, p90_mm: null };
}
export function decisionThresholdMode(thresholds: DecisionThresholds) {
  return thresholds.mode ?? 'custom';
}
export function parseDecisionThresholds(
  q: URLSearchParams,
): DecisionThresholds {
  const value = (key: string, maximum: number) => {
    const text = q.get(key),
      n = text === null || text === '' ? NaN : Number(text);
    return Number.isFinite(n) && n >= 0 && n <= maximum ? n : null;
  };
  const parsedField = value('ar', 100);
  const field = parsedField !== null && parsedField >= 1 && Number.isInteger(parsedField) ? parsedField : 90;
  // Old links with independent limits remain custom. A plain overview/record
  // link carries the same three-metric requirement used on its source page.
  const custom = q.get('thresholdMode') === 'custom' ||
    (q.get('thresholdMode') !== 'joint' && ['sensitivity', 'localization', 'p90'].some((key) => q.has(key)));
  if (!custom) return jointDecisionThresholds(field);
  return {
    mode: 'custom',
    field,
    sensitivity: value('sensitivity', 100),
    localization: value('localization', 100),
    p90_mm: value('p90', 500),
  };
}
export function decisionHref(ids: string[], t: DecisionThresholds) {
  if (decisionThresholdMode(t) === 'joint') t = jointDecisionThresholds(t.field);
  const q = new URLSearchParams({ ar: String(t.field), thresholdMode: decisionThresholdMode(t) });
  ids.forEach((id, i) => {
    if (id) q.set(i ? 'b' : 'a', id);
  });
  for (const [key, value] of [
    ['sensitivity', t.sensitivity],
    ['localization', t.localization],
    ['p90', t.p90_mm],
  ] as const)
    if (value !== null) q.set(key, String(value));
  return '/decision?' + q;
}
/** Display the complete active requirement beside every decision result. */
export function decisionCriteriaSummary(thresholds: DecisionThresholds) {
  if (decisionThresholdMode(thresholds) === 'joint')
    return `三项共同要求：场重建、幅度和定位效用保留率均不低于${thresholds.field}%。`;
  if (thresholds.sensitivity == null && thresholds.localization == null && thresholds.p90_mm == null)
    return `仅检查场重建保留率 ≥ ${thresholds.field}%。`;
  const rules = [`信号重建保留率 ≥ ${thresholds.field}%`];
  if (thresholds.sensitivity != null) rules.push(`幅度保留率（最差10%） ≥ ${thresholds.sensitivity}%`);
  if (thresholds.localization != null) rules.push(`相对定位评分 ≥ ${thresholds.localization}%`);
  if (thresholds.p90_mm != null) rules.push(`定位误差P90 ≤ ${thresholds.p90_mm} mm`);
  return `自定义要求：${rules.join('；')}。`;
}
export const pct = (n: unknown) =>
  finite(n) ? `${(100 * n).toFixed(2)}%` : '未提供';
export const mm = (n: unknown) => (finite(n) ? `${n.toFixed(2)} mm` : '未提供');

export function validateDesign(input: unknown): ElectrodeDesign {
  const d = input as ElectrodeDesign;
  if (
    !d ||
    d.schema !== 'eeg-electrode-design/1' ||
    d.coordinate_system !== 'ernie_native_mm' ||
    d.unit !== 'mm'
  )
    throw new Error(
      '坐标须为本App的Ernie原生毫米坐标；请使用导出模板。其他头模或坐标系需先完成配准。',
    );
  if (
    !Array.isArray(d.xyz_mm) ||
    d.xyz_mm.length !== 64 ||
    d.xyz_mm.some(
      (p) => !Array.isArray(p) || p.length !== 3 || !p.every(finite),
    )
  )
    throw new Error('需要64行有限数值坐标，每行包含x、y、z。');
  if (new Set(d.xyz_mm.map((p) => p.join(','))).size !== 64)
    throw new Error('64个电极坐标必须互不重复。');
  if (d.xyz_mm.some((p) => p.some((v) => Math.abs(v) > 500)))
    throw new Error('坐标超出Ernie毫米坐标输入范围，请检查单位和配准。');
  if (!Array.isArray(d.region_indices)) throw new Error('需要区域标签数组。');
  const r = new Set(d.region_indices).size;
  if (
    ![1, 2, 3, 4, 6].includes(r) ||
    d.region_indices.length !== 64 ||
    d.region_indices.some((v) => !Number.isInteger(v) || v < 0 || v >= r)
  )
    throw new Error('区域标签须从0连续编号，区域数量为1、2、3、4或6。');
  const counts = Array.from(
    { length: r },
    (_, i) => d.region_indices.filter((n) => n === i).length,
  ).sort((a, b) => b - a);
  if (counts.some((n, i) => n !== Math.floor(64 / r) + Number(i < 64 % r)))
    throw new Error('每区电极数须均衡分配，总数64。');
  if (d.electrode_names !== undefined && (!Array.isArray(d.electrode_names) ||
      d.electrode_names.length !== 64 || new Set(d.electrode_names).size !== 64 ||
      d.electrode_names.some(n => typeof n !== 'string' || !n.trim() || n.length > 128 || hasNameControl(n))))
    throw new Error('需要64个不重复的电极名称，每个名称最多128个字符且不含控制字符。');
  return {
    schema: d.schema,
    coordinate_system: d.coordinate_system,
    unit: d.unit,
    name: typeof d.name === 'string' ? d.name.slice(0, 100) : '导入布局',
    xyz_mm: d.xyz_mm,
    region_indices: d.region_indices,
    ...(d.electrode_names === undefined ? {} : { electrode_names: [...d.electrode_names] }),
    ...(d.source_metadata === undefined ? {} : { source_metadata: validateCoordinateSource(d.source_metadata) as CoordinateSourceMetadata }),
  };
}

/** Names are presentation metadata; this is the unchanged scientific input. */
export function scientificDesign(design: ElectrodeDesign) {
  const { electrode_names: _names, source_metadata: _source, ...request } = validateDesign(design);
  return request;
}

/** The perturbation radii of the design-evaluation contract (lib/api-types.ts). */
export const PERTURBATION_RADII = [3, 6, 10] as const satisfies readonly PerturbationRadius[];
// Does not compile if the contract gains a radius that is missing above.
const RADII_COVER_CONTRACT: Exclude<PerturbationRadius, (typeof PERTURBATION_RADII)[number]> extends never ? true : never = true;
void RADII_COVER_CONTRACT;
export const isPerturbationRadius = (value: unknown): value is PerturbationRadius => PERTURBATION_RADII.some(radius => radius === value);
// CONDUCTIVITY_SCENARIOS lists the same ids as the Python schema, from which ConductivityScenarioId is generated
// (tests/test_schema_parity.py, test_option_lists_match_node).
export const isConductivityScenario = (value: unknown): value is ConductivityScenarioId =>
  CONDUCTIVITY_SCENARIOS.some(scenario => scenario.id !== '' && scenario.id === value);

export function designSubmission(design: ElectrodeDesign, action: DesignEvaluationRequest['action'], radius_mm: PerturbationRadius, seed: number,
  noise_model?: NoiseModel, conductivity_scenario?: ConductivityScenarioId, robustness?: boolean, data_prior?: DataPrior): DesignEvaluationBody {
  // Independent noise is the default and is omitted, preserving existing request keys; a data prior carries its own noise.
  const request: DesignEvaluationRequest = { action, design: scientificDesign(design), radius_mm, seed, ...(noise_model && !data_prior ? { noise_model } : {}),
    ...(conductivity_scenario && action === 'evaluate' ? { conductivity_scenario } : {}),
    // Robustness is defined on the nominal Ernie head only.
    ...(robustness && action === 'evaluate' && !conductivity_scenario ? { robustness: 'standard/1' as const } : {}),
    ...(data_prior ? { data_prior } : {}) };
  return design.electrode_names || design.source_metadata ? { schema: 'design-submission/1' as const, request,
    electrode_names: design.electrode_names ?? Array.from({ length: 64 }, (_, index) => `E${index + 1}`),
    ...(design.source_metadata ? { source_metadata: design.source_metadata } : {}) } : request;
}

/** Restore saved original inputs; evaluated coordinates remain a separate result. */
export function restoreDesignEvaluation(bundle: unknown, record: SavedRecord) {
  const value = bundle as { schema?: string; record_id?: string; reproduction?: { request?: { action?: string; design?: unknown; radius_mm?: number; seed?: number; noise_model?: unknown; conductivity_scenario?: unknown; head_id?: unknown; robustness?: unknown; data_prior?: unknown } }; original_record?: { result?: DesignResult & { request?: unknown } } };
  const request = value?.reproduction?.request, result = value?.original_record?.result;
  if (value?.schema !== 'eeg-reproducibility-bundle/1' || value.record_id !== record.id || request?.action !== 'evaluate' ||
      !isPerturbationRadius(request.radius_mm) || !Number.isInteger(request.seed) || request.seed! < 0 || request.seed! > 9999 ||
      !result || JSON.stringify(result.request) !== JSON.stringify(request) || JSON.stringify(result.evaluated_xyz_mm) !== JSON.stringify(record.layout?.xyzMm))
    throw new Error('保存的坐标评价与原始输入不匹配');
  if (request.head_id !== undefined) throw new Error('跨头模评价只能在结果库或稳健性研究中查看');
  // The page restores the evaluation conditions with the inputs, so the result is never shown as independent noise.
  const noise_model_id = request.noise_model === undefined ? 'iid'
    : NOISE_MODEL_PRESETS.find(preset => JSON.stringify(preset.value ?? null) === JSON.stringify(request.noise_model))?.id;
  const conductivity_scenario = request.conductivity_scenario === undefined ? '' as const
    : isConductivityScenario(request.conductivity_scenario) ? request.conductivity_scenario : undefined;
  if (noise_model_id === undefined || conductivity_scenario === undefined || ![undefined, 'standard/1'].includes(request.robustness as string))
    throw new Error('保存的评价条件不在当前可选范围内');
  let data_prior: DataPrior | undefined;
  try { data_prior = normalizeDataPrior(request.data_prior) as DataPrior | undefined; } catch { throw new Error('保存的评价条件不在当前可选范围内'); }
  const design = validateDesign({ ...validateDesign(request.design), ...(record.electrode_annotation ? { electrode_names: record.electrode_annotation.electrode_names,
    ...(record.electrode_annotation.source_metadata ? { source_metadata: record.electrode_annotation.source_metadata } : {}) } : {}) });
  return { design, action: 'evaluate' as const, radius_mm: request.radius_mm as PerturbationRadius, seed: request.seed!, noise_model_id, conductivity_scenario,
    robustness: request.robustness === 'standard/1', data_prior, result };
}

export function recordElectrodeCount(record: Pick<SavedRecord, 'layout' | 'request'>): number {
  return record.layout?.xyzMm?.length ?? record.request?.electrode_count ?? 64;
}

export function exportDesign(record: SavedRecord): ElectrodeDesign {
  if (!record.layout) throw new Error('该记录没有完整布局');
  return validateDesign({
    schema: 'eeg-electrode-design/1',
    coordinate_system: 'ernie_native_mm',
    unit: 'mm',
    name: record.label,
    xyz_mm: record.layout.xyzMm,
    region_indices: record.layout.regionIndices,
    ...(record.electrode_annotation ? { electrode_names: record.electrode_annotation.electrode_names } : {}),
    ...(record.electrode_annotation?.source_metadata ? { source_metadata: record.electrode_annotation.source_metadata } : {}),
  });
}

export function tryExportDesign(record: SavedRecord | null | undefined): ElectrodeDesign | null {
  if (!record?.layout) return null;
  try { return exportDesign(record); } catch { return null; }
}

/** Extract coordinates for any valid 2–64 electrode layout (balanced or adaptive) for 2D plotting and CSV export. */
export function exportRecordCoordinates(record: SavedRecord | null | undefined): RecordCoordinates | null {
  const layout = record?.layout;
  if (!layout || !Array.isArray(layout.xyzMm) || layout.xyzMm.length < 2 || layout.xyzMm.length > 64) return null;
  if (layout.xyzMm.some((p) => !Array.isArray(p) || p.length !== 3 || !p.every(finite) || p.some((v) => Math.abs(v) > 500))) return null;
  const total = layout.xyzMm.length;
  if (new Set(layout.xyzMm.map((p) => p.join(','))).size !== total) return null;
  if (!Array.isArray(layout.regionIndices) || layout.regionIndices.length !== total) return null;
  const r = new Set(layout.regionIndices).size;
  if (![1, 2, 3, 4, 6].includes(r) || layout.regionIndices.some((v) => !Number.isInteger(v) || v < 0 || v >= r)) return null;
  const names = record.electrode_annotation?.electrode_names;
  return {
    name: typeof record.label === 'string' ? record.label.slice(0, 100) : '导出布局',
    xyz_mm: layout.xyzMm,
    region_indices: layout.regionIndices,
    ...(names && names.length === total ? { electrode_names: [...names] } : {}),
  };
}

/** Validate a completed saved layout (8–64 channels, balanced or adaptive quota) for CSV and 2D figure export. */
export function exportValidRecordCoordinates(record: SavedRecord | null | undefined): RecordCoordinates | null {
  if (!record || record.status !== 'completed' || !record.layout) return null;
  const coords = exportRecordCoordinates(record);
  if (!coords) return null;
  const total = coords.xyz_mm.length;
  if (!(ELECTRODE_COUNTS as readonly number[]).includes(total)) return null;
  const r = new Set(coords.region_indices).size;
  if (r !== record.region_count) return null;
  const counts = Array.from({ length: r }, (_, i) => coords.region_indices.filter((n) => n === i).length);
  if (record.request?.allocation_mode === 'adaptive') {
    if (r < 2 || counts.some((n) => n < 4)) return null;
  } else {
    if (total < 2 * r) return null;
    const sorted = [...counts].sort((a, b) => b - a);
    if (sorted.some((n, i) => n !== Math.floor(total / r) + Number(i < total % r))) return null;
  }
  if (
    coords.electrode_names !== undefined &&
    (new Set(coords.electrode_names).size !== total ||
      coords.electrode_names.some((n) => typeof n !== 'string' || !n.trim() || n.length > 128 || hasNameControl(n)))
  ) {
    return null;
  }
  return coords;
}

export function designCSV(design: Pick<ElectrodeDesign, 'xyz_mm' | 'region_indices' | 'electrode_names'>) {
  return [
    '# coordinate_system=ernie_native_mm; unit=mm; region=zero_based',
    'electrode,region,x_mm,y_mm,z_mm',
    ...design.xyz_mm.map((p, i) =>
      [design.electrode_names?.[i] ?? `E${i + 1}`, design.region_indices[i], ...p].map(value => {
        const cell = String(value);
        return /[",\r\n]/.test(cell) || cell.trim() !== cell ? '"' + cell.replaceAll('"', '""') + '"' : cell;
      }).join(','),
    ),
  ].join('\n');
}
export function parseDesign(text: string, name = '导入布局') {
  if (text.trimStart().startsWith('{')) return validateDesign(JSON.parse(text));
  const rows = text.replace(/\r\n/g, '\n').replace(/\n+$/, '').split('\n');
  if (
    rows.shift()?.trim() !==
      '# coordinate_system=ernie_native_mm; unit=mm; region=zero_based' ||
    rows.shift()?.trim() !== 'electrode,region,x_mm,y_mm,z_mm'
  )
    throw new Error('CSV须包含模板的坐标系声明和表头。');
  const cells = rows.map(row => {
    const cells: string[] = []; let value = '', quoted = false, closed = false;
    for (let i = 0; i < row.length; i++) {
      const c = row[i];
      if (quoted) { if (c === '"' && row[i + 1] === '"') { value += '"'; i++; } else if (c === '"') { quoted = false; closed = true; } else value += c; }
      else if (c === ',') { cells.push(value); value = ''; closed = false; }
      else if (c === '"' && !value && !closed) quoted = true;
      else { if (closed || c === '"') throw new Error('CSV引号格式无效。'); value += c; }
    }
    if (quoted) throw new Error('CSV引号格式无效。');
    cells.push(value); return cells;
  });
  if (
    cells.some((p) => p.length !== 5 || p.some((x) => !x.trim())) ||
    new Set(cells.map((p) => p[0])).size !== 64
  )
    throw new Error('CSV需要64行不重复的电极名称和完整数值。');
  return validateDesign({
    schema: 'eeg-electrode-design/1',
    coordinate_system: 'ernie_native_mm',
    unit: 'mm',
    name,
    xyz_mm: cells.map((p) => p.slice(2).map(Number)),
    region_indices: cells.map((p) => Number(p[1])),
    electrode_names: cells.map(p => p[0]),
  });
}
export function minimumDistance(design: ElectrodeDesign) {
  let distance = Infinity;
  design.xyz_mm.forEach((a, i) =>
    design.xyz_mm.slice(i + 1).forEach((b) => {
      distance = Math.min(distance, Math.hypot(...a.map((v, j) => v - b[j])));
    }),
  );
  return distance;
}

export function qualification(
  record: { metrics?: Pick<NonNullable<SavedRecord['metrics']>, 'field_relative' | 'sensitivity_tail' | 'localization_relative' | 'p90_mm'> | null },
  thresholds: DecisionThresholds,
) {
  const limits = decisionThresholdMode(thresholds) === 'joint'
    ? jointDecisionThresholds(thresholds.field)
    : thresholds;
  const rules: [string, unknown, number, boolean][] = [
    [
      '信号重建保留率',
      record.metrics?.field_relative,
      limits.field / 100,
      true,
    ],
    ...(limits.sensitivity == null
      ? []
      : [
          [
            '幅度保留率（最差10%）',
            record.metrics?.sensitivity_tail,
            limits.sensitivity / 100,
            true,
          ] as [string, unknown, number, boolean],
        ]),
    ...(limits.localization == null
      ? []
      : [
          [
            '相对定位评分',
            record.metrics?.localization_relative,
            limits.localization / 100,
            true,
          ] as [string, unknown, number, boolean],
        ]),
    ...(limits.p90_mm == null
      ? []
      : [
          ['定位误差P90', record.metrics?.p90_mm, limits.p90_mm, false] as [
            string,
            unknown,
            number,
            boolean,
          ],
        ]),
  ];
  const missing = rules.filter(([, v]) => !finite(v)).map(([label]) => label);
  const failed = rules
    .filter(([, v, t, higher]) => finite(v) && (higher ? v < t : v > t))
    .map(([label]) => label);
  return {
    state: missing.length ? 'missing' : failed.length ? 'fail' : 'pass',
    missing,
    failed,
  };
}

export function comparisonNotes(records: SavedRecord[]) {
  if (records.length < 2) return ['选择第二个方案后可查看配对差异。'];
  const [a, b] = records;
  const notes: string[] = [];
  if (a.dataset_id !== b.dataset_id)
    notes.push('实验协议不同：分别阅读分数，不据此判断布局优劣。');
  const pa = a.provenance,
    pb = b.provenance;
  if (pa.surface_admissibility_sha256 !== pb.surface_admissibility_sha256)
    notes.push('允许表面筛选版本不同：旧坐标范围与新版外部曝光范围分开解读。');
  const identityA =
    a.dataset_id === 'cache'
      ? pa.bank_sha256 &&
        pa.code_sha256 &&
        JSON.stringify([pa.bank_sha256, pa.code_sha256])
      : pa.sha256;
  const identityB =
    b.dataset_id === 'cache'
      ? pb.bank_sha256 &&
        pb.code_sha256 &&
        JSON.stringify([pb.bank_sha256, pb.code_sha256])
      : pb.sha256;
  if (!identityA || !identityB || identityA !== identityB)
    notes.push('模型或计算版本身份未匹配，需要同协议复评。');
  // Scores under another noise model, conductivity scenario or head are a different quantity.
  const condition = (r: SavedRecord) => JSON.stringify({ noise: r.request?.noise_model ?? r.evaluation_condition?.noise_model ?? null,
    scenario: r.evaluation_condition?.conductivity_scenario ?? null, head: r.evaluation_condition?.head_id ?? null });
  if (condition(a) !== condition(b))
    notes.push('评价条件不同（噪声模型、电导率情景或头模）：分数不可直接比较。');
  if (recordElectrodeCount(a) !== recordElectrodeCount(b))
    notes.push('电极总数不同：比较的是通道规模与空间分布的共同影响（均相对标准全头64导评分）。');
  if ((a.request?.allocation_mode ?? 'balanced') !== (b.request?.allocation_mode ?? 'balanced'))
    notes.push('区域通道配额方式不同（均分与跨区自适应）：各区通道数随有效孔径变化。');
  if (
    a.mode !== b.mode ||
    JSON.stringify(a.request?.mask_codes) !==
      JSON.stringify(b.request?.mask_codes)
  )
    notes.push('允许位置范围不同：比较的是区域分布与空间约束的共同影响。');
  if (
    pa.objective !== pb.objective ||
    pa.optimization_objective !== pb.optimization_objective
  )
    notes.push('原布局优化目标不同，不能直接归因于几何位置。');
  if (
    a.area_cap_cm2 !== b.area_cap_cm2 ||
    a.radius_cap_mm !== b.radius_cap_mm ||
    a.spacing_mm !== b.spacing_mm
  )
    notes.push(
      '面积、半径或点距约束不同：这是设计取舍比较，不能单独归因为区域数量。',
    );
  if (
    a.area_cap_cm2 &&
    records.some(
      (r) =>
        !finite(r.geometry?.union_area_cm2) ||
        r.geometry!.union_area_cm2 < 0.99 * r.area_cap_cm2!,
    )
  )
    notes.push('至少一个方案未使用99%的面积上限；同时比较实际面积。');
  if (a.dataset_id === 'cache')
    notes.push(
      '半径约束计算按各自面积使用情况解释；区域数变化会同时改变总面积。',
    );
  return notes;
}

export function decisionMarkdown(
  records: SavedRecord[],
  thresholds: DecisionThresholds,
  supplement?: unknown,
  locale: Locale = 'zh-CN',
) {
  // Localize the reading report, never the original JSON/provenance. Protect
  // user-entered names from the legacy display-message adapter.
  const originalNames: string[] = [];
  const reportName = (record: SavedRecord) => {
    const token = `\uE000${originalNames.length}\uE001`;
    originalNames.push(localizedRecordTitle(record, locale).replace(/[|\r\n]/g, ' '));
    return token;
  };
  const allFixed64 = records.every((r) => recordElectrodeCount(r) === 64);
  const lines = [
    '# EEG布局设计对比报告',
    '',
    `生成时间：${new Date().toISOString()}`,
    '',
    '## 比较条件',
    '',
    allFixed64
      ? '固定64个测量电极；参照为Ernie头模上的BioSemi64标签匹配全头布局。'
      : '各方案测量电极数见下表（8–64导）；参照均为Ernie头模上的BioSemi64标签匹配全头布局。',
    decisionCriteriaSummary(thresholds),
    '',
    ...comparisonNotes(records).map((n) => `- ${n}`),
    '',
    '## 原记录指标',
    '',
    allFixed64
      ? '|方案|区域数|实际面积 cm²|重建保留率|幅度保留率（最差10%）|相对定位评分|定位中位数|定位P90|条件判定|'
      : '|方案|电极数|区域数|实际面积 cm²|重建保留率|幅度保留率（最差10%）|相对定位评分|定位中位数|定位P90|条件判定|',
    allFixed64
      ? '|---|---:|---:|---:|---:|---:|---:|---:|---|'
      : '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|',
  ];
  for (const r of records) {
    const q = qualification(r, thresholds);
    const verdict = q.state === 'pass' ? '达到全部启用要求' : q.state === 'missing' ? '数据不完整' : '未达到：' + q.failed.join('、');
    lines.push(
      allFixed64
        ? `|${reportName(r)}|${r.region_count}|${r.geometry?.union_area_cm2?.toFixed(2) ?? '未提供'}|${pct(r.metrics?.field_relative)}|${pct(r.metrics?.sensitivity_tail)}|${pct(r.metrics?.localization_relative)}|${mm(r.metrics?.median_mm)}|${mm(r.metrics?.p90_mm)}|${verdict}|`
        : `|${reportName(r)}|${recordElectrodeCount(r)}|${r.region_count}|${r.geometry?.union_area_cm2?.toFixed(2) ?? '未提供'}|${pct(r.metrics?.field_relative)}|${pct(r.metrics?.sensitivity_tail)}|${pct(r.metrics?.localization_relative)}|${mm(r.metrics?.median_mm)}|${mm(r.metrics?.p90_mm)}|${verdict}|`,
    );
  }
  lines.push(
    '',
    '## 证据阶段',
    '',
    '- 本表读取原实验记录；总面积实验使用原4096字典／256生成源评分。',
    '- 后续512独立源复评单独存档，本表不混用其分数。',
    '- 单头模模型条件性结果；独立头模、实体模型及人体同步验证另列阶段。',
    '- AR是设计接受阈值；三项相对指标分别对应重建、幅度和定位效用。',
    '',
    '## 标准64参照的绝对值',
    '',
  );
  records.forEach((r) =>
    lines.push(
      `- ${reportName(r)}：重建解释率 ${pct(r.metrics?.reference_field_absolute)}；定位中位数 ${mm(r.metrics?.reference_median_mm)}。`,
    ),
  );
  if (supplement)
    lines.push(
      '',
      '## 坐标评价结果（与原表分开）',
      '',
      '```json',
      JSON.stringify(supplement, null, 2),
      '```',
    );
  lines.push(
    '',
    '## 记录身份',
    '',
    '```json',
    JSON.stringify(
      records.map((r) => ({
        id: r.id,
        dataset: r.dataset_id,
        provenance: r.provenance,
      })),
      null,
      2,
    ),
    '```',
  );
  let raw = false;
  return lines.map((line) => {
    if (line.startsWith('```')) { raw = !raw; return line; }
    return raw ? line : translateText(line, locale).replace(/\uE000(\d+)\uE001/g, (_, index) => originalNames[Number(index)]);
  }).join('\n');
}
