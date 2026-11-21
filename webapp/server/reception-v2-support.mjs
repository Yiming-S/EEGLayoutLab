import { RECEPTION_V2_WORKFLOW } from './project-paths.mjs';
import { createHash } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
export { normalizeReceptionRequest, validateReceptionResult } from './contracts/source-reception.mjs';
import { normalizeDesignRequest, validateDesignResult } from './design-evaluation-server.mjs';
import { RecordStore } from './storage/records.mjs';
import { createRuntimeIdentityCache } from './runtime/identity-cache.mjs';
const digest = (bytes) => createHash('sha256').update(bytes).digest('hex');
const run = promisify(execFile);
const runtimeReaders = new WeakMap();
/**
 * A saved coordinate evaluation as a library record. Evaluations under another noise model,
 * conductivity scenario or head are returned only with `conditions` (the library), carrying
 * `evaluation_condition`; signal simulation keeps the default protocol.
 */
export async function designReceptionRecord(root, id, store = new RecordStore(root), { conditions = false } = {}) {
  if (!/^[a-f0-9]{64}$/.test(id)) return null;
  const path = `results/v2/design_evaluation_jobs/${id}/cache.json`;
  let bytes;
  try {
    const storedPath = await store.contained(store.path('design', id, 'cache.json'));
    if ((await stat(storedPath)).size > 8 * 1024 * 1024)
      throw new Error('设计记录过大');
    // Provenance hashes the exact persisted bytes, including JSON whitespace.
    bytes = await readFile(storedPath);
  } catch (e) {
    if (e.code === 'ENOENT') return null;
    throw e;
  }
  const cache = JSON.parse(bytes),
    r = cache.result;
  if (cache.key !== id || cache.result_sha256 !== digest(JSON.stringify(r)))
    throw new Error('设计记录校验失败');
  const request = normalizeDesignRequest(r.request);
  if (cache.identity && digest(JSON.stringify({ request, identity: cache.identity })) !== id) throw new Error('设计记录身份校验失败');
  // Perturbation trials are not nominal coordinate designs for this workflow.
  if (r.request?.action === 'perturb') return null;
  validateDesignResult(r, request);
  if (r.request.action !== 'evaluate') return null;
  const condition = {
    ...(request.noise_model ? { noise_model: request.noise_model } : {}),
    ...(request.conductivity_scenario ? { conductivity_scenario: request.conductivity_scenario } : {}),
    ...(request.head_id ? { head_id: request.head_id } : {}),
  };
  const variant = Object.keys(condition).length > 0;
  if (variant && !conditions) return null;
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
    ...(variant ? { evaluation_condition: condition } : {}),
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
      r.status === 'completed' &&
      !r.request?.noise_model,
  );
  const store = queue.store ?? new RecordStore(queue.root);
  const entries = await store.keys('design');
  const warnings = [...library.warnings];
  for (const key of entries) {
    try {
      const r = await designReceptionRecord(queue.root, key, store);
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
/** Signal simulation keeps independent noise; layouts searched under another noise model stay out of it. */
export function assertIndependentNoiseParent(record) {
  if (record?.request?.noise_model || record?.evaluation_condition) throw new Error('信号仿真只接受独立噪声协议下的布局');
}
export async function receptionV2Context(service, request) {
  const q = service.queue;
  const record =
    (await q.library.get(request.record_id)) ??
    (await designReceptionRecord(service.root, request.record_id, service.store));
  if (
    !record ||
    record.status !== 'completed' ||
    !['cache', 'strict_area', 'design_evaluation'].includes(record.dataset_id)
  )
    throw new Error('需要完整的已保存布局或已评价坐标');
  assertIndependentNoiseParent(record);
  if (
    request.mode === 'multi_source' &&
    !request.region_definition &&
    record.dataset_id !== 'design_evaluation'
  )
    throw new Error('已有前向库布局使用原多源协议');
  const context = await service.nativeContext({});
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
  // Source-result hits keep the original numerical digest. Every call checks
  // file/discovery observations; changed inputs require a full byte inspection.
  let readRuntime = runtimeReaders.get(service);
  if (!readRuntime) {
    readRuntime = createRuntimeIdentityCache();
    runtimeReaders.set(service, readRuntime);
  }
  const runtime = await readRuntime({ python: service.python, root: service.root });
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
export async function sourceCatalog(service) {
  const { stdout } = await run(
    service.python,
    [
      '-u',
      join(service.root, 'scripts/run_source_reception_v2.py'),
      '--repository-root',
      service.root,
      '--catalog',
    ],
    {
      cwd: service.root,
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
