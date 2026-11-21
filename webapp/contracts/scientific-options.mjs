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
