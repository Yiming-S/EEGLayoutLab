/**
 * Optional scientific model choices shared by browser, server and Python
 * (src/compact_eeg/noise_models.py). Defaults are returned as undefined so a
 * default request keeps its original fields and cache key.
 */
export const SPATIAL_NOISE_LENGTHS_MM = [10, 20, 40];
export const NOISE_MODEL_PRESETS = [
  { id: 'iid', label: '独立噪声（默认）', value: undefined, search: true },
  ...SPATIAL_NOISE_LENGTHS_MM.map(length => ({
    id: `spatial_${length}`, label: `空间相关噪声 ρ=0.5，L=${length} mm`,
    value: { kind: 'spatial', rho: 0.5, length_mm: length }, search: true,
  })),
  { id: 'brain_background', label: '脑背景活动噪声（仅定位，50%）', value: { kind: 'brain_background', fraction: 0.5 }, search: false },
];

/** Canonical non-default noise model, or undefined for independent noise. */
export function normalizeNoiseModel(value, { allowBrainBackground = true } = {}) {
  if (value === undefined || value === null) return undefined;
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('噪声模型格式无效');
  const keys = Object.keys(value).sort().join(',');
  if (value.kind === 'iid' && keys === 'kind') return undefined;
  if (value.kind === 'spatial' && keys === 'kind,length_mm,rho' && value.rho === 0.5 && SPATIAL_NOISE_LENGTHS_MM.includes(value.length_mm))
    return { kind: 'spatial', rho: 0.5, length_mm: value.length_mm };
  if (value.kind === 'brain_background' && keys === 'fraction,kind' && value.fraction === 0.5) {
    if (!allowBrainBackground) throw new Error('脑背景噪声只用于定位评价，布局搜索不支持');
    return { kind: 'brain_background', fraction: 0.5 };
  }
  throw new Error('不支持的噪声模型');
}

/** Data-generating conductivity scenarios (configs/conductivity_scenarios.json); inversion stays nominal. */
export const CONDUCTIVITY_SCENARIOS = [
  { id: '', label: '与反演模型一致（默认）' },
  { id: 'skull_x0.5', label: '颅骨电导率 ×0.5（反演仍用名义值）' },
  { id: 'skull_x2', label: '颅骨电导率 ×2（反演仍用名义值）' },
];

/** Scenario name, or undefined for the matched model; evaluation only. */
export function normalizeConductivityScenario(value, action) {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value !== 'string' || !CONDUCTIVITY_SCENARIOS.some(scenario => scenario.id && scenario.id === value))
    throw new Error('不支持的电导率情景');
  if (action !== 'evaluate') throw new Error('电导率情景只用于坐标评价，不用于网格偏移');
  return value;
}

const HEAD_ID = /^[a-z0-9]+(?:[_-][a-z0-9]+)*$/;

/** Additional head package ID, or undefined for the production Ernie head; evaluation only. */
export function normalizeHeadId(value, action, scenario) {
  if (value === undefined || value === null || value === '') return undefined;
  if (typeof value !== 'string' || value.length > 40 || !HEAD_ID.test(value)) throw new Error('头模编号无效');
  if (action !== 'evaluate') throw new Error('其他头模只用于坐标评价，不用于网格偏移');
  if (scenario) throw new Error('电导率情景只定义在Ernie头模上');
  return value;
}

export function conductivityScenarioLabel(value) {
  return CONDUCTIVITY_SCENARIOS.find(scenario => scenario.id === (value ?? ''))?.label ?? '未记录';
}

export function noiseModelId(value) {
  const model = normalizeNoiseModel(value);
  if (!model) return 'iid';
  return model.kind === 'spatial' ? `spatial_${model.length_mm}` : 'brain_background';
}

export function noiseModelLabel(value) {
  return NOISE_MODEL_PRESETS.find(preset => preset.id === noiseModelId(value))?.label ?? '未记录';
}

/** Session-robustness protocol (src/compact_eeg/workflows/design_robustness.py); evaluation on Ernie only. */
export const ROBUSTNESS_PROTOCOL = 'standard/1';
export const ROBUSTNESS_LEVELS = { dropout: [2, 4, 8], impedance: [0.5, 1.0], replacement: [5, 10] };

/** The protocol name, or undefined when not requested. */
export function normalizeRobustness(value, action, scenario, head) {
  if (value === undefined || value === null || value === '' || value === false) return undefined;
  if (value !== ROBUSTNESS_PROTOCOL) throw new Error('不支持的稳健性协议');
  if (action !== 'evaluate') throw new Error('稳健性评价只用于坐标评价，不用于网格偏移');
  if (scenario || head) throw new Error('稳健性评价只定义在Ernie名义头模上，不与电导率情景或其他头模同时使用');
  return value;
}

/**
 * Library-sized summary of a robustness block: per level, the median retention of the layout and of standard64
 * (relative to the unperturbed standard64). Replacement is null when the installation had no scalp-node table.
 */
export function robustnessSummary(block) {
  const pick = (levels, side) => levels.map(level => level[side]?.median ?? null);
  const replacement = block.replacement?.status === 'completed' ? {
    rms_mm: block.replacement.levels.map(level => level.rms_mm),
    fixed: { candidate: block.replacement.levels.map(l => l.candidate.fixed_estimator?.median ?? null), reference: block.replacement.levels.map(l => l.reference.fixed_estimator?.median ?? null) },
    redigitized: { candidate: block.replacement.levels.map(l => l.candidate.redigitized?.median ?? null), reference: block.replacement.levels.map(l => l.reference.redigitized?.median ?? null) },
  } : null;
  return {
    protocol: block.protocol,
    dropout: { removed: block.dropout.random.map(level => level.removed), candidate: pick(block.dropout.random, 'candidate'), reference: pick(block.dropout.random, 'reference') },
    impedance: { log_sd: block.impedance.map(level => level.log_sd), candidate: pick(block.impedance, 'candidate'), reference: pick(block.impedance, 'reference') },
    replacement,
  };
}

/** Data-derived source prior (src/compact_eeg/workflows/data_prior.py): region gains and fitted noise. */
export const DATA_PRIOR_SCHEMA = 'eeg-data-prior/1';
export const DATA_PRIOR_REGIONS = ['frontal', 'central', 'parietal', 'occipital', 'temporal_left', 'temporal_right', 'other'];
export const DATA_PRIOR_REGION_LABELS = ['额叶', '中央感觉运动区', '顶叶', '枕叶', '左颞叶', '右颞叶', '其他（未归入）'];
export const DATA_PRIOR_LENGTHS_MM = [5, 10, 15, 20, 30, 40];
/** Files a data-prior request adds to the computation identity. */
export const DATA_PRIOR_FILES = ['src/compact_eeg/workflows/data_prior.py', 'src/compact_eeg/workflows/eeg_recording.py', 'webapp/public/models/ernie/source-roi.json'];

const fourDigits = value => typeof value === 'number' && Number.isFinite(value) && value >= 1e-3 && value <= 1e3 && Number(value.toPrecision(4)) === value;

/** Canonical request value, or undefined when absent; a prior replaces the noise model and stays on the Ernie head. */
export function normalizeDataPrior(value, { noiseModel, head } = {}) {
  if (value === undefined || value === null) return undefined;
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join(',') !== 'length_mm,region_gain,rho')
    throw new Error('数据先验格式无效');
  const { region_gain: gains, rho, length_mm: length } = value;
  if (!Array.isArray(gains) || gains.length !== DATA_PRIOR_REGIONS.length || !gains.every(fourDigits))
    throw new Error('数据先验的区域增益须为7个保留4位有效数字的正数');
  if (typeof rho !== 'number' || !(rho >= 0 && rho <= 0.95) || Math.round(rho * 100) / 100 !== rho)
    throw new Error('数据先验的噪声相关比例无效');
  if (rho === 0 ? length !== null : !DATA_PRIOR_LENGTHS_MM.includes(length)) throw new Error('数据先验的噪声相关长度无效');
  if (noiseModel) throw new Error('数据先验已包含噪声结构，不能同时选择噪声模型');
  if (head) throw new Error('数据先验只定义在Ernie头模上');
  return { region_gain: [...gains], rho, length_mm: length };
}

export function dataPriorLabel(value) {
  const prior = normalizeDataPrior(value);
  if (!prior) return '';
  return `数据先验（噪声${prior.rho ? `ρ=${prior.rho}，L=${prior.length_mm} mm` : '独立'}）`;
}

/** The request value of an eeg-data-prior/1 file, after checking the fields the interface shows. */
export function dataPriorFromFile(document) {
  if (!document || typeof document !== 'object' || document.schema !== DATA_PRIOR_SCHEMA ||
      JSON.stringify(document.regions) !== JSON.stringify(DATA_PRIOR_REGIONS) || !document.fit || !Array.isArray(document.channels))
    throw new Error('不是eeg-data-prior/1数据先验文件');
  return normalizeDataPrior(document.request);
}

/** Regional electrode quota allocation mode for multi-region radius search; balanced is omitted as default. */
export const MIN_ADAPTIVE_REGION_ELECTRODES = 4;
export const ALLOCATION_MODES = [
  { id: 'balanced', label: '各区均分（默认）', value: undefined },
  { id: 'adaptive', label: '跨区自适应配额（每区≥4，共64）', value: 'adaptive' },
];

export function normalizeAllocationMode(value, regionCount) {
  if (value === undefined || value === null || value === 'balanced') return undefined;
  if (value !== 'adaptive') throw new Error('区域通道配额模式无效');
  if (regionCount === 1) throw new Error('单区域不支持跨区自适应配额');
  return 'adaptive';
}

export function allocationModeLabel(value) {
  return value === 'adaptive' ? '跨区自适应配额' : '';
}

/** Search optimization objective mode for radius search; min(field, sensitivity) is omitted as default. */
export const OBJECTIVE_MODES = [
  { id: 'min', label: '下尾极小极大（默认）', value: undefined },
  { id: 'composite', label: '子空间信息复合目标', value: 'composite' },
];

export function normalizeObjectiveMode(value) {
  if (value === undefined || value === null || value === 'min') return undefined;
  if (value !== 'composite') throw new Error('搜索优化目标模式无效');
  return 'composite';
}

export function objectiveModeLabel(value) {
  return value === 'composite' ? '子空间信息复合目标' : '';
}
