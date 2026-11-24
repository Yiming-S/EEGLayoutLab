/** Read-only adapters. Original experiments are NOT cache hits for the strict-radius algorithm. */
import { createHash } from 'node:crypto';
import { readFile, stat, realpath } from 'node:fs/promises';
import { join, resolve, sep } from 'node:path';
import { designReceptionRecord } from './reception-v2-support.mjs';
import { dataPriorLabel, noiseModelLabel } from '../contracts/scientific-options.mjs';
import { RecordStore } from './storage/records.mjs';
import { layoutKeyText } from '../contracts/layout-key.mjs';

const hash = (value) => createHash('sha256').update(value).digest('hex');
const idFor = (dataset, id) => hash(`${dataset}:${id}`);
const domainLabel = (mode) => mode.includes('whole') ? '全头' : mode.includes('low_hair') ? '低毛发代理' : '指定解剖组合';
const familyNames = { bilateral_near_ear: '双侧耳后代理', left_ear_forehead: '左耳后＋前额', right_ear_forehead: '右耳后＋前额',
  bilateral_expanded_ear: '双侧扩展耳周', bilateral_ear_forehead: '双耳后＋前额',
  bilateral_ear_split_forehead: '双耳后＋双侧前额', bilateral_ear_forehead_orbital: '双耳后＋双侧前额＋眶周' };
const summary = ({ layout: _layout, provenance: _provenance, ...record }) => record;
const layoutKey = (layout) => layout?.xyzMm && layout.regionIndices ? hash(layoutKeyText(layout.xyzMm, layout.regionIndices)) : null;
// A listed record carries its layout key last; resident full records are keyed once per row.
const offlineKeys = new WeakMap();
const listed = (row) => {
  if ('layout_key' in row || !row.layout) return summary(row);
  if (!offlineKeys.has(row)) offlineKeys.set(row, layoutKey(row.layout));
  const key = offlineKeys.get(row);
  return key ? { ...summary(row), layout_key: key } : summary(row);
};
const DATASETS = [
  { id: 'design_evaluation', label: '已评价坐标布局', note: '已保存的固定64点坐标评价；保留原坐标与评价协议。' },
  { id: 'cache', label: '按需计算缓存', note: '严格半径上限快速搜索；完整配置和科学代码身份一致时自动复用。' },
  { id: 'strict_area', label: '外部曝光筛选 · 30面积布局', note: '4096字典／256源、20 dB；固定 min(field,sensitivity) 分支。所有中心、电极和区域面片使用同一外部曝光筛选。' },
  { id: 'historical_area', label: '历史面积实验 · 原坐标范围', note: '未使用外部曝光筛选；原坐标和分数保留，不属于当前候选表面协议。' },
  { id: 'offline_radius', label: '早期半径实验 · 原始记录', note: '区域允许相交，不保证R个分离区域；不同搜索预算。只能按原实验口径查看，不能替代当前设计结果。' },
];

export function validateSavedRecord(record) {
  if (!record || !['completed', 'no_layout'].includes(record.status)) throw new Error('无效记录状态');
  if (record.status === 'no_layout') {
    if (record.layout != null || record.metrics != null) throw new Error('缺失布局带有分数');
    return record;
  }
  const { layout, region_count: r, metrics: m } = record;
  const xyz = (a) => Array.isArray(a) && a.length === 64 && a.every((p) => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite));
  if (![1, 2, 3, 4, 6].includes(r) || !xyz(layout?.xyzMm) || !xyz(layout?.referenceXyzMm) ||
      new Set(layout.xyzMm.map((p) => p.join(','))).size !== 64 ||
      !Array.isArray(layout.regionIndices) || layout.regionIndices.length !== 64 ||
      layout.regionIndices.some((n) => !Number.isInteger(n) || n < 0 || n >= r) ||
      Array.from({ length: r }, (_, n) => n).some((n) => layout.regionIndices.filter((i) => i === n).length !== Math.floor(64 / r) + Number(n < 64 % r))) throw new Error('记录坐标与区域标签无效');
  const scores = ['field_relative', 'sensitivity_tail', 'localization_relative'].map((k) => m?.[k]);
  if (!m || scores.some((v) => v !== null && !Number.isFinite(v))) throw new Error('无效保留率');
  const g = scores.includes(null) ? null : Math.min(...scores);
  if (g === null ? m.conditional_global !== null : !Number.isFinite(m.conditional_global) || Math.abs(g - m.conditional_global) > 1e-9) throw new Error('保留率最小值不一致');
  if (record.dataset_id === 'strict_area' && record.geometry?.union_connected_component_count !== r) throw new Error('面积实验连通数不符');
  if (layout.regionPatchVertexIndices && (layout.regionPatchVertexIndices.length !== r || layout.regionAreasCm2?.length !== r || layout.regionAreasCm2.some(a => !Number.isFinite(a) || a <= 0) || layout.regionPatchVertexIndices.some(ids => !Array.isArray(ids) || !ids.length || new Set(ids).size !== ids.length || ids.some(i => !Number.isInteger(i) || i < 0 || i >= 52410)))) throw new Error('保存的区域面片或面积无效');
  if (record.provenance?.surface_status === 'external_exposure_screened' && !layout.regionPatchVertexIndices) throw new Error('新版面积记录缺少原生区域面片');
  return record;
}

export function radiusRecords(data, provenance) {
  if (data.schema !== 'single-head-app/1' || data.scope?.head_count !== 1 || data.scope?.physical_electrode_count !== 64) throw new Error('半径实验格式错误');
  const baseline = data.baseline.conditions.find((m) => m.snr_db === 20);
  return data.conditions.flatMap((c) => c.variants.map((v) => {
    const m = v.conditions.find((row) => row.snr_db === 20);
    return validateSavedRecord({ id: idFor('offline_radius', `${c.id}:${v.id}`), dataset_id: 'offline_radius',
      label: `${c.R}区 · ${familyNames[c.family_id] ?? domainLabel(c.mode)} · 半径≤${c.radius_mm} mm · 点距${c.spacing_mm} mm · ${v.objective === 'field_20db' ? '场重建优化' : '场与敏感度优化'}`,
      region_count: c.R, mode: c.mode, radius_cap_mm: c.radius_mm, spacing_mm: c.spacing_mm,
      status: 'completed', compatible: false, request: null, geometry: null,
      layout: { id: v.id, xyzMm: v.xyz_mm, regionIndices: v.region_indices, referenceXyzMm: data.baseline.xyz_mm },
      metrics: { ...m, reference_field_absolute: baseline.field_absolute, reference_median_mm: baseline.median_mm },
      provenance: { ...provenance, original: data.provenance, condition_id: c.id, objective: v.objective,
        snr_db: 20, overlapping_regions_allowed: true, formal_population_ar: false },
    });
  }));
}

export function areaRecords(data, provenance, { historical = false } = {}) {
  const exterior = data.schema_version === 'compact-eeg-area-budget-study/4-external-exposure';
  if ((!exterior && data.schema_version !== 'compact-eeg-area-budget-study/3-strict-merge-limited') ||
      data.config?.physical_electrode_count !== 64 || data.config?.spacing_mm !== 4 ||
      data.config?.evaluation?.snr_db !== 20 || data.config?.require_disconnected_regions !== true ||
      data.formal_population_ar !== false || data.conditions?.length !== 30) throw new Error('严格面积报告协议与本导入器不符');
  const baseline = data.baseline;
  if (exterior && !/^[a-f0-9]{64}$/.test(data.identity?.surface_admissibility_sha256)) throw new Error('缺少外部表面筛选身份');
  return data.conditions.map((entry) => {
    const c = entry.condition, f = entry.finalists.find((v) => v.objective === 'min_field_sensitivity20');
    const base = { id: idFor('strict_area', exterior ? `${data.run_id}:${provenance.sha256}:${c.id}` : c.id),
      dataset_id: historical ? 'historical_area' : 'strict_area',
      label: `${c.region_count}区 · ${domainLabel(c.domain)} · 总面积≤${c.area_cap_cm2} cm²`,
      region_count: c.region_count, mode: c.domain, area_cap_cm2: c.area_cap_cm2, spacing_mm: 4,
      compatible: false, request: null,
      provenance: { ...provenance, run_id: data.run_id, batch_id: data.batch_id, condition_id: c.id,
        surface_admissibility_sha256: data.identity?.surface_admissibility_sha256 ?? null,
        surface_admissibility_version: data.identity?.surface_admissibility_version ?? 'legacy_coordinate_roi',
        surface_status: exterior ? 'external_exposure_screened' : 'historical_unqualified',
        objective: f?.objective, snr_db: 20, dictionary_sources: 4096, generation_sources: 256,
        formal_population_ar: false, reevaluation_512_sources: false } };
    if (!f) {
      if (entry.status === 'completed_best_found') throw new Error('缺少冻结主分支');
      return validateSavedRecord({ ...base, status: 'no_layout', layout: null, metrics: null, geometry: null });
    }
    const e = f.evaluation, field = e.field_metrics.conditions.find((m) => m.nominal_reference_snr_db === 20);
    if (!field || e.localization.dictionary_source_count !== 4096 || e.localization.generation_source_count !== 256 ||
        baseline.localization.dictionary_source_count !== 4096 || baseline.localization.generation_source_count !== 256) throw new Error('严格面积原始评分的源模型不符');
    // final.xyz_mm is region ordered; evaluation.xyz_mm is bank-index ordered. Never mix these arrays.
    return validateSavedRecord({ ...base,
      status: 'completed', compatible: false, request: null, geometry: f.final.geometry,
      layout: { id: e.id, xyzMm: f.final.xyz_mm, regionIndices: f.final.region_indices, referenceXyzMm: baseline.reference_xyz_mm,
        ...(exterior ? { regionPatchVertexIndices: f.final.surface_patch_vertex_indices, regionAreasCm2: f.final.geometry.region_areas_cm2 } : {}) },
      metrics: { field_relative: e.field20, field_absolute: field.candidate_field_explained_energy,
        reference_field_absolute: baseline.field_metrics.conditions[0].candidate_field_explained_energy,
        sensitivity_tail: e.sensitivity_tail, localization_relative: e.localization_relative20,
        conditional_global: e.conditional_global20, median_mm: e.localization.median_error_mm,
        p90_mm: e.localization.p90_error_mm, reference_median_mm: baseline.localization.median_error_mm },
    });
  });
}

export class LocalDataLibrary {
  constructor(queue) { this.queue = queue; this.root = queue.root; this.store = queue.store ?? new RecordStore(queue.root); this.records = new Map(); this.loaded = new Map(); this.warnings = []; }

  async offline(datasetId, file, convert, digest) {
    const info = await stat(file), fingerprint = `${info.mtimeMs}:${info.size}:${digest || ''}`;
    if (this.loaded.get(datasetId) === fingerprint) return;
    const bytes = await readFile(file), sha256 = hash(bytes);
    if (digest && sha256 !== digest) throw new Error('报告SHA256校验失败');
    const rows = convert(JSON.parse(bytes), { file: file.slice(this.root.length + 1), sha256 });
    for (const [id, row] of this.records) if (row.dataset_id === datasetId) this.records.delete(id);
    for (const row of rows) this.records.set(row.id, row);
    this.loaded.set(datasetId, fingerprint);
  }

  async refresh() {
    this.warnings = [];
    for (const dataset of ['offline_radius', 'historical_area', 'strict_area']) {
      try {
        if (dataset === 'offline_radius') await this.offline(dataset, join(this.root, 'webapp/public/data/single_head_optimization.json'), radiusRecords);
        else {
          const pointer = JSON.parse(await readFile(join(this.root, dataset === 'historical_area' ? 'results/v2/historical_strict_area_budget_study.json' : 'results/v2/current_strict_area_budget_study.json'), 'utf8'));
          const file = await realpath(resolve(this.root, pointer.report));
          if (!file.startsWith(join(this.root, 'results/v2/campaigns') + sep) || !/^[a-f0-9]{64}$/.test(pointer.sha256)) throw new Error('报告路径或身份无效');
          await this.offline(dataset, file, (data, source) => areaRecords(data, source, { historical: dataset === 'historical_area' }), pointer.sha256);
        }
      } catch (error) {
        for (const [id, row] of this.records) if (row.dataset_id === dataset) this.records.delete(id);
        this.loaded.delete(dataset);
        this.warnings.push(`${DATASETS.find((d) => d.id === dataset).label}：${error.code === 'ENOENT' ? '数据未提供' : error.message}`);
      }
    }
    const directory = this.store.directory('radius');
    const keys = await this.store.keys('radius');
    // Only summary metadata remains resident for the cache; full arrays load on demand.
    for (const [id, row] of this.records) if (row.dataset_id === 'cache' && !keys.includes(id)) this.records.delete(id);
    const identity = this.queue.getIdentity();
    for (const key of keys) {
      const path = join(directory, key, 'cache.json');
      try {
        const info = await stat(path), stamp = `${info.mtimeMs}:${info.size}`;
        let row = this.records.get(key);
        if (this.loaded.get(key) !== stamp || !row) {
          const cache = await this.queue.readCache(key);
          if (!cache) throw new Error('缓存完整性校验未通过');
          row = this.cacheRecord(cache, false);
          const layout_key = layoutKey(row.layout);
          this.records.set(key, layout_key ? { ...summary(row), layout_key } : summary(row)); this.loaded.set(key, stamp);
        }
        row = this.records.get(key);
        // The queue owns the key formula (code identity, threads and, off macOS, the runtime).
        row.compatible = this.queue.identityFor(row.request, identity).key === key;
        if (row.compatible) {
          const cache = await this.queue.readCache(key);
          try { await this.queue.verifyInputs(cache.result); }
          catch { row.compatible = false; this.warnings.push('前向输入文件与部分缓存的原模型不符；这些历史记录仍可查看，但不能作为当前配置命中。'); }
        }
      } catch (error) {
        this.records.delete(key); this.loaded.delete(key);
        if (error.code !== 'ENOENT') this.warnings.push(`一条计算缓存未载入：${error.message}`);
      }
    }
    const coordinateDirectory = this.store.directory('design');
    const coordinateKeys = await this.store.keys('design');
    for (const [id, row] of this.records) if (row.dataset_id === 'design_evaluation' && !coordinateKeys.includes(id)) this.records.delete(id);
    for (const key of coordinateKeys) {
      try {
        const info = await stat(join(coordinateDirectory, key, 'cache.json')), stamp = `${info.mtimeMs}:${info.size}`;
        if (this.loaded.get('coordinates:' + key) === stamp && this.records.has(key)) continue;
        const record = await designReceptionRecord(this.root, key, this.store, { conditions: true, layoutKey: true });
        if (record) this.records.set(key, summary(record));
        else this.records.delete(key);
        this.loaded.set('coordinates:' + key, stamp);
      } catch (error) {
        this.records.delete(key); this.loaded.delete('coordinates:' + key);
        if (error.code !== 'ENOENT') this.warnings.push(`一条坐标评价记录未载入：${error.message}`);
      }
    }
  }

  cacheRecord(cache, compatible) {
    const r = cache.result, request = cache.request;
    return validateSavedRecord({ id: cache.key, dataset_id: 'cache', status: r.status,
      label: `${request.region_count}区 · ${request.mode === 'preset' ? request.mask_codes.join(' + ') : domainLabel(request.mode)} · 半径≤${request.radius_mm} mm${request.noise_model ? ' · ' + noiseModelLabel(request.noise_model) : ''}${request.data_prior ? ' · ' + dataPriorLabel(request.data_prior) : ''}`,
      region_count: request.region_count, radius_cap_mm: request.radius_mm, mode: request.mode,
      spacing_mm: 4, compatible, request, finished_at: cache.finished_at,
      metrics: r.metrics ?? null, geometry: r.geometry ?? null, layout: r.layout ?? null,
      provenance: { ...r.provenance, result_sha256: cache.result_sha256, file: `results/v2/local_app_jobs/${cache.key}/cache.json` },
    });
  }

  async list() {
    await this.refresh();
    const records = [...this.records.values()].map(listed).sort((a, b) => (b.finished_at || '').localeCompare(a.finished_at || '') || a.label.localeCompare(b.label));
    return { schema: 'local-data-library/1', local_only: true, records, warnings: [...new Set(this.warnings)],
      datasets: DATASETS.map((d) => ({ ...d, count: records.filter((r) => r.dataset_id === d.id).length })),
      retention: 'Files on this computer; original experiments are read-only. No browser storage, automatic expiry or background batch computation.' };
  }

  async get(id) {
    if (!/^[a-f0-9]{64}$/.test(id)) return null;
    await this.refresh();
    const row = this.records.get(id);
    if (row?.dataset_id === 'design_evaluation') return designReceptionRecord(this.root, id, this.store, { conditions: true });
    if (!row || row.dataset_id !== 'cache') return row ?? null;
    const cache = await this.queue.readCache(id);
    return cache ? this.cacheRecord(cache, row.compatible) : null;
  }
}
