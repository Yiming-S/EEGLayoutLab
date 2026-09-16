import { RECEPTION_V2_WORKFLOW } from './project-paths.mjs';
import { createHash } from 'node:crypto';
import { readFile, readdir, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import {
  normalizeSourceRequest,
  validateSourceResult,
} from './source-reception-server.mjs';
import { validateDesignResult } from './design-evaluation-server.mjs';
const digest = (bytes) => createHash('sha256').update(bytes).digest('hex');
const run = promisify(execFile);
const CROSS_REGIONS = ['frontal', 'central', 'parietal', 'occipital', 'temporal_left', 'temporal_right'];
export function normalizeReceptionRequest(x) {
  if (x?.mode === undefined) return normalizeSourceRequest(x);
  if ('region_definition' in x && x.region_definition !== 'dk40-six-roi-v1') throw new Error('Unsupported source ROI definition');
  const single = x.mode === 'single_source';
  const cross = x.mode === 'cross_region';
  const expected = [
    'record_id',
    'mode',
    single ? 'source_index' : cross ? 'brain_regions' : 'brain_region',
    'waveform',
    'artifact_scale',
    'seed',
    ...('region_definition' in x ? ['region_definition'] : []),
  ]
    .sort()
    .join(',');
  if (
    !['single_source', 'multi_source', 'cross_region'].includes(x.mode) ||
    Object.keys(x).sort().join(',') !== expected
  )
    throw new Error('源模式或字段无效');
  const common = normalizeSourceRequest({
    record_id: x.record_id,
    brain_region: single || cross ? 'frontal' : x.brain_region,
    waveform: x.waveform,
    artifact_scale: x.artifact_scale,
    seed: x.seed,
  });
  if (
    single &&
    (!Number.isInteger(x.source_index) ||
      x.source_index < 0 ||
      x.source_index > 255)
  )
    throw new Error('选择0–255中的一个冻结生成源');
  const { brain_region, ...rest } = common;
  if (cross && (!Array.isArray(x.brain_regions) || x.brain_regions.length < 1 || x.brain_regions.length > 6 || new Set(x.brain_regions).size !== x.brain_regions.length || x.brain_regions.some(id => !CROSS_REGIONS.includes(id))))
    throw new Error('跨区域模式需要选择1–6个不同的源区域');
  return {
    ...rest,
    mode: x.mode,
    ...(x.region_definition ? { region_definition: x.region_definition } : {}),
    ...(single ? { source_index: x.source_index } : cross ? { brain_regions: CROSS_REGIONS.filter(id => x.brain_regions.includes(id)) } : { brain_region }),
  };
}
export function validateReceptionResult(result, request, record) {
  if (!request.mode) return validateSourceResult(result, request, record);
  if (
    result?.schema_version !== 'source-reception/2' ||
    JSON.stringify(normalizeReceptionRequest(result.request)) !==
      JSON.stringify(request)
  )
    throw new Error('新源协议结果身份不一致');
  const legacy = normalizeSourceRequest({
    record_id: request.record_id,
    brain_region: request.brain_region ?? 'frontal',
    waveform: request.waveform,
    artifact_scale: request.artifact_scale,
    seed: request.seed,
  });
  validateSourceResult(
    { ...result, schema_version: 'source-reception/1', request: legacy },
    legacy,
    record,
  );
  const n = request.mode === 'single_source' ? 1 : request.mode === 'cross_region' ? request.brain_regions.length : 6;
  if (
    result.source.mode !== request.mode ||
    result.source.xyz_mm.length !== n ||
    result.source.normals_mri?.length !== n ||
    result.waveforms.source_nam?.length !== n ||
    result.source.normals_mri.some(
      (v) =>
        !Array.isArray(v) ||
        v.length !== 3 ||
        !v.every(Number.isFinite) ||
        Math.abs(Math.hypot(...v) - 1) > 1e-5,
    ) ||
    result.waveforms.source_nam.some(
      (row) => row.length !== 400 || !row.every(Number.isFinite),
    )
  )
    throw new Error('固定源方向或波形记录不完整');
  if (
    request.mode === 'single_source' &&
    result.source.generation_source_indices?.[0] !== request.source_index
  )
    throw new Error('返回源与选择源不符');
  if (request.mode === 'cross_region' && (
    JSON.stringify(result.source.source_regions) !== JSON.stringify(request.brain_regions) ||
    result.source.patch_count !== n ||
    result.source.generation_source_indices?.length !== n ||
    new Set(result.source.generation_source_indices).size !== n ||
    result.source.generation_source_indices.some(i => !Number.isInteger(i) || i < 0 || i > 255) ||
    result.source.bank_source_indices?.length !== n ||
    result.source.bank_source_indices.some((i, index) => i !== 4096 + result.source.generation_source_indices[index])
  )) throw new Error('跨区域源位置记录与选择不一致');
  if (request.region_definition && (
    result.source.region_definition !== request.region_definition ||
    result.protocol.region_definition !== request.region_definition ||
    !/^[a-f0-9]{64}$/.test(result.source.atlas_sha256 ?? '') ||
    result.source.source_regions?.length !== n ||
    result.source.source_parcels?.length !== n ||
    (request.mode === 'multi_source' && result.source.source_regions.some(r => r !== request.brain_region))
  )) throw new Error('Atlas source membership is inconsistent');
}
export async function designReceptionRecord(root, id) {
  if (!/^[a-f0-9]{64}$/.test(id)) return null;
  const path = `results/v2/design_evaluation_jobs/${id}/cache.json`;
  let bytes;
  try {
    if ((await stat(join(root, path))).size > 8 * 1024 * 1024)
      throw new Error('设计记录过大');
    bytes = await readFile(join(root, path));
  } catch (e) {
    if (e.code === 'ENOENT') return null;
    throw e;
  }
  const cache = JSON.parse(bytes),
    r = cache.result;
  if (cache.key !== id || cache.result_sha256 !== digest(JSON.stringify(r)))
    throw new Error('设计记录校验失败');
  // Perturbation trials are not nominal coordinate designs for this workflow.
  if (r.request?.action === 'perturb') return null;
  validateDesignResult(r, r.request);
  if (r.request.action !== 'evaluate') return null;
  const p = JSON.parse(
    await readFile(
      join(root, 'results/v2/current_strict_area_budget_study.json'),
    ),
  );
  const report = await readFile(join(root, p.report));
  if (digest(report) !== p.sha256) throw new Error('参照坐标报告校验失败');
  const baseline = JSON.parse(report).baseline.reference_xyz_mm;
  return {
    id,
    dataset_id: 'design_evaluation',
    label: r.request.design.name,
    status: 'completed',
    region_count: new Set(r.request.design.region_indices).size,
    mode: 'imported_coordinates',
    spacing_mm: 4,
    compatible: false,
    request: null,
    geometry: null,
    finished_at: cache.finished_at,
    metrics: {
      ...r.nominal,
      conditional_global: [
        r.nominal.field_relative,
        r.nominal.sensitivity_tail,
        r.nominal.localization_relative,
      ].some((v) => v == null)
        ? null
        : Math.min(
            r.nominal.field_relative,
            r.nominal.sensitivity_tail,
            r.nominal.localization_relative,
          ),
    },
    layout: {
      id,
      xyzMm: r.evaluated_xyz_mm,
      referenceXyzMm: baseline,
      regionIndices: r.request.design.region_indices,
    },
    provenance: {
      ...r.provenance,
      forward_mode: r.forward_mode,
      design_result: { path, sha256: digest(bytes) },
    },
  };
}
export async function receptionLayouts(queue) {
  const library = await queue.library.list();
  const records = library.records.filter(
    (r) =>
      ['cache', 'strict_area'].includes(r.dataset_id) &&
      r.status === 'completed',
  );
  let entries = [];
  try {
    entries = await readdir(
      join(queue.root, 'results/v2/design_evaluation_jobs'),
      { withFileTypes: true },
    );
  } catch (e) {
    if (e.code !== 'ENOENT') throw e;
  }
  const warnings = [...library.warnings];
  for (const entry of entries)
    if (entry.isDirectory() && /^[a-f0-9]{64}$/.test(entry.name)) {
      try {
        const r = await designReceptionRecord(queue.root, entry.name);
        if (r) {
          const { layout: _layout, provenance: _provenance, ...summary } = r;
          records.push(summary);
        }
      } catch (e) {
        warnings.push(`一条坐标评价记录未载入：${e.message}`);
      }
    }
  return { ...library, records, warnings };
}
export async function receptionV2Context(service, request) {
  const q = service.queue;
  const record =
    (await q.library.get(request.record_id)) ??
    (await designReceptionRecord(service.root, request.record_id));
  if (
    !record ||
    record.status !== 'completed' ||
    !['cache', 'strict_area', 'design_evaluation'].includes(record.dataset_id)
  )
    throw new Error('需要完整的已保存布局或已评价坐标');
  if (
    request.mode === 'multi_source' &&
    !request.region_definition &&
    record.dataset_id !== 'design_evaluation'
  )
    throw new Error('已有前向库布局使用原多源协议');
  const context = await q.designTests.context({});
  const names = [
    ...RECEPTION_V2_WORKFLOW,
    'scripts/source_reception.py',
    'scripts/run_source_reception.py',
    'scripts/source_reception_v2.py',
    'scripts/run_source_reception_v2.py',
    'scripts/reception_forward_provider.py',
    'scripts/inspect_reception_runtime.py',
    ...(request.region_definition ? ['src/compact_eeg/workflows/source_roi.py', 'webapp/public/models/ernie/source-roi.json', 'webapp/public/models/ernie/source-roi-definition.json'] : []),
  ];
  const code = Object.fromEntries(
    await Promise.all(
      names.map(async (p) => [p, await service.inputs.digest(p)]),
    ),
  );
  // Source-result hits must verify the same installed bytes as inner FEM hits.
  const { stdout: runtimeOutput } = await run(
    q.designTests.python,
    [join(service.root, 'scripts/inspect_reception_runtime.py')],
    {
      cwd: service.root,
      timeout: 15000,
      maxBuffer: 4096,
      env: {
        ...process.env,
        PYTHONDONTWRITEBYTECODE: '1',
        OMP_NUM_THREADS: '1',
        OPENBLAS_NUM_THREADS: '1',
        MKL_NUM_THREADS: '1',
        VECLIB_MAXIMUM_THREADS: '1',
      },
    },
  );
  const runtime = JSON.parse(runtimeOutput);
  if (
    runtime.schema !== 'reception-runtime-digest/1' ||
    !/^[a-f0-9]{64}$/.test(runtime.sha256)
  )
    throw new Error('接收数值环境身份无效');
  const layout_scope =
    record.dataset_id === 'cache' && !record.compatible
      ? 'historical_frozen_coordinates_not_requalified'
      : 'saved_coordinates_no_new_layout_optimization';
  const identity = {
    version: 'source-reception-cache/2',
    forward: context.identity,
    code,
    layout: record.layout,
    record_provenance: record.provenance,
    layout_scope,
    numerical_runtime_sha256: runtime.sha256,
    threads: 1,
  };
  return {
    record,
    identity,
    key: digest(JSON.stringify({ request, identity })),
  };
}
export async function sourceCatalog(queue) {
  const { stdout } = await run(
    queue.designTests.python,
    [
      '-u',
      join(queue.root, 'scripts/run_source_reception_v2.py'),
      '--repository-root',
      queue.root,
      '--catalog',
    ],
    {
      cwd: queue.root,
      timeout: 30000,
      maxBuffer: 1024 * 1024,
      env: {
        ...process.env,
        PYTHONDONTWRITEBYTECODE: '1',
        OMP_NUM_THREADS: '1',
        OPENBLAS_NUM_THREADS: '1',
        MKL_NUM_THREADS: '1',
        VECLIB_MAXIMUM_THREADS: '1',
      },
    },
  );
  const catalog = JSON.parse(stdout);
  if (
    catalog.schema_version !== 'source-catalog/1' ||
    catalog.sources?.length !== 256
  )
    throw new Error('源目录格式无效');
  return catalog;
}
