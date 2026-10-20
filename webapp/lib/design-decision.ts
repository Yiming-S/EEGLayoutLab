import type { SavedRecord } from './local-library';
import { translateText, type Locale } from './i18n/core.ts';
import { localizedRecordTitle } from './i18n/records.ts';
import { parseAR } from './lab-workflow.ts';

export type ElectrodeDesign = {
  schema: 'eeg-electrode-design/1';
  coordinate_system: 'ernie_native_mm';
  unit: 'mm';
  name: string;
  xyz_mm: [number, number, number][];
  region_indices: number[];
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
};
export type DesignJob = {
  id: string;
  status: string;
  message: string;
  progress: number;
  result: DesignResult | null;
  key?: string;
  cached?: boolean;
};
const finite = (n: unknown): n is number =>
  typeof n === 'number' && Number.isFinite(n);
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
  return {
    schema: d.schema,
    coordinate_system: d.coordinate_system,
    unit: d.unit,
    name: typeof d.name === 'string' ? d.name.slice(0, 100) : '导入布局',
    xyz_mm: d.xyz_mm,
    region_indices: d.region_indices,
  };
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
  });
}
export function designCSV(design: ElectrodeDesign) {
  return [
    '# coordinate_system=ernie_native_mm; unit=mm; region=zero_based',
    'electrode,region,x_mm,y_mm,z_mm',
    ...design.xyz_mm.map((p, i) =>
      [`E${i + 1}`, design.region_indices[i], ...p].join(','),
    ),
  ].join('\n');
}
export function parseDesign(text: string, name = '导入布局') {
  if (text.trimStart().startsWith('{')) return validateDesign(JSON.parse(text));
  const rows = text.trim().split(/\r?\n/);
  if (
    rows.shift()?.trim() !==
      '# coordinate_system=ernie_native_mm; unit=mm; region=zero_based' ||
    rows.shift()?.trim() !== 'electrode,region,x_mm,y_mm,z_mm'
  )
    throw new Error('CSV须包含模板的坐标系声明和表头。');
  const cells = rows.map((row) => row.split(',').map((x) => x.trim()));
  if (
    cells.some((p) => p.length !== 5 || p.some((x) => !x)) ||
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
  const lines = [
    '# EEG布局设计对比报告',
    '',
    `生成时间：${new Date().toISOString()}`,
    '',
    '## 比较条件',
    '',
    '固定64个测量电极；参照为Ernie头模上的BioSemi64标签匹配全头布局。',
    decisionCriteriaSummary(thresholds),
    '',
    ...comparisonNotes(records).map((n) => `- ${n}`),
    '',
    '## 原记录指标',
    '',
    '|方案|区域数|实际面积 cm²|重建保留率|幅度保留率（最差10%）|相对定位评分|定位中位数|定位P90|条件判定|',
    '|---|---:|---:|---:|---:|---:|---:|---:|---|',
  ];
  for (const r of records) {
    const q = qualification(r, thresholds);
    lines.push(
      `|${reportName(r)}|${r.region_count}|${r.geometry?.union_area_cm2?.toFixed(2) ?? '未提供'}|${pct(r.metrics?.field_relative)}|${pct(r.metrics?.sensitivity_tail)}|${pct(r.metrics?.localization_relative)}|${mm(r.metrics?.median_mm)}|${mm(r.metrics?.p90_mm)}|${q.state === 'pass' ? '达到全部启用要求' : q.state === 'missing' ? '数据不完整' : '未达到：' + q.failed.join('、')}|`,
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
      '## 新计算结果（与原表分开）',
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
