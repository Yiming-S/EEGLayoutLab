import { createAccessPolicy } from './http/access-policy.mjs';
import { DATA_PRIOR_FILES, MIN_ADAPTIVE_REGION_ELECTRODES, normalizeAllocationMode, normalizeDataPrior, normalizeElectrodeCount, normalizeNoiseModel, normalizeObjectiveMode } from '../contracts/scientific-options.mjs';
import { startPythonWorker } from './jobs/python-worker.mjs';
import { executionSlotFor } from './jobs/execution-slot.mjs';
import { runtimeConfig } from './runtime/config.mjs';
import { runtimeIdentity } from './runtime/python-fingerprint.mjs';
import { RecordStore } from './storage/records.mjs';
import { ProjectService } from './projects/service.mjs';
import { RobustnessStudyService } from './studies/service.mjs';
import { ElectrodeAnnotations } from './annotations/electrode-names.mjs';
import { operationsConfig } from './operations/config.mjs';
import { ResourceGate } from './operations/resource-gate.mjs';
import { OperationsMonitor } from './operations/monitor.mjs';
/** Local Node service, shared by development and production hosts. */
import { spawn } from 'node:child_process';
import { createHash, randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { LocalDataLibrary } from './local-data-library.mjs';
import { InputIntegrity } from './local-input-integrity.mjs';
import { SourceReceptionService } from './source-reception-server.mjs';
import { receptionLayouts } from './reception-v2-support.mjs';
import { RecordVisibility, libraryConfig } from './library/record-visibility.mjs';
import { experimentBundle } from './experiment-bundle.mjs';
import { DesignEvaluationService } from './design-evaluation-server.mjs';
import { ElectrodeEditorService } from './electrode-editor-server.mjs';
import { CommunityQueue, communityMiddleware } from './community-queue.mjs';
import { communityAdapters } from './community-adapters.mjs';
import { sendJson as send } from './http/responses.mjs';

export const MASK_CODES = ['PL', 'PR', 'AL', 'AR', 'FL', 'FM', 'FR', 'OL', 'OR'];
const RUNNING = new Set(['queued', 'running', 'cancelling']);
const hash = (value) => createHash('sha256').update(value).digest('hex');

export function normalizeRequest(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('配置必须是JSON对象');
  if (Object.keys(input).some((key) => !['region_count', 'radius_mm', 'mode', 'mask_codes', 'noise_model', 'data_prior', 'allocation_mode', 'objective_mode', 'electrode_count'].includes(key))) {
    throw new Error('配置含未支持字段');
  }
  // Independent noise, balanced quota, min objective and 64 electrodes are defaults and omitted, keeping existing keys and seeds.
  const noiseModel = normalizeNoiseModel(input.noise_model, { allowBrainBackground: false });
  const prior = normalizeDataPrior(input.data_prior, { noiseModel });
  const { region_count, radius_mm, mode } = input;
  if (![1, 2, 3, 4, 6].includes(region_count)) throw new Error('区域数只支持1、2、3、4、6');
  const allocationMode = normalizeAllocationMode(input.allocation_mode, region_count);
  const objectiveMode = normalizeObjectiveMode(input.objective_mode);
  const electrodeCount = normalizeElectrodeCount(input.electrode_count, region_count, allocationMode);
  const options = { ...(noiseModel ? { noise_model: noiseModel } : {}), ...(prior ? { data_prior: prior } : {}),
    ...(allocationMode ? { allocation_mode: allocationMode } : {}),
    ...(objectiveMode ? { objective_mode: objectiveMode } : {}),
    ...(electrodeCount ? { electrode_count: electrodeCount } : {}) };
  if (!Number.isInteger(radius_mm) || radius_mm < 15 || radius_mm > 80 || radius_mm % 5) {
    throw new Error('半径须为15–80 mm，步长5 mm');
  }
  if (!['whole_surface', 'low_hair', 'preset'].includes(mode)) throw new Error('不支持的区域模式');
  if (mode === 'preset') {
    if (!Array.isArray(input.mask_codes) || input.mask_codes.length !== region_count ||
        input.mask_codes.some((code) => !MASK_CODES.includes(code))) {
      throw new Error('该组合的细分解剖掩膜尚未建立；请选择已支持的耳后、耳周、前额或眶周代理区域');
    }
    return { region_count, radius_mm, mode, mask_codes: [...input.mask_codes], ...options };
  }
  if (input.mask_codes !== undefined && (!Array.isArray(input.mask_codes) || input.mask_codes.length)) {
    throw new Error('自由中心模式不接受指定掩膜');
  }
  return { region_count, radius_mm, mode, ...options };
}

export { loopbackRequest } from './http/access-policy.mjs';

export function validateWorkerResult(result, request) {
  if (!result || !['completed', 'no_layout'].includes(result.status) ||
      JSON.stringify(normalizeRequest(result.request)) !== JSON.stringify(request)) throw new Error('结果配置不一致');
  if (result.status === 'no_layout') {
    if (result.layout != null || result.metrics != null) throw new Error('无布局任务不能附带分数');
    return;
  }
  const layout = result.layout, geometry = result.geometry, metrics = result.metrics;
  const expectedCount = request.electrode_count ?? 64;
  const coordinates = (rows, len) => Array.isArray(rows) && rows.length === len &&
    rows.every((row) => Array.isArray(row) && row.length === 3 && row.every(Number.isFinite));
  if (!layout || !coordinates(layout.xyzMm, expectedCount) || !coordinates(layout.referenceXyzMm, 64) ||
      new Set(layout.xyzMm.map((row) => row.join(','))).size !== expectedCount ||
      !Array.isArray(layout.regionIndices) || layout.regionIndices.length !== expectedCount ||
      !layout.regionIndices.every((r) => Number.isInteger(r) && r >= 0 && r < request.region_count)) throw new Error(`无效${expectedCount}点坐标`);
  const counts = Array.from({ length: request.region_count }, (_, r) => layout.regionIndices.filter((v) => v === r).length);
  if (request.allocation_mode === 'adaptive'
    ? counts.some((count) => count < MIN_ADAPTIVE_REGION_ELECTRODES)
    : counts.some((count, r) => count !== Math.floor(expectedCount / request.region_count) + Number(r < expectedCount % request.region_count))) throw new Error('区域分配错误');
  if (!geometry || geometry.union_connected_component_count !== request.region_count ||
      !Number.isFinite(geometry.common_graph_radius_mm) || geometry.common_graph_radius_mm <= 0 ||
      geometry.common_graph_radius_mm > request.radius_mm + 1e-7 ||
      !Number.isFinite(geometry.union_area_cm2) || geometry.union_area_cm2 <= 0) throw new Error('区域几何无效');
  for (let i = 0; i < expectedCount; i++) for (let j = i + 1; j < expectedCount; j++) {
    if (Math.hypot(...layout.xyzMm[i].map((x, axis) => x - layout.xyzMm[j][axis])) < 4 - 1e-7) throw new Error('电极间距不足');
  }
  const names = ['field_relative', 'sensitivity_tail', 'localization_relative'];
  if (!metrics || names.some((name) => metrics[name] !== null && !Number.isFinite(metrics[name]))) throw new Error('指标无效');
  const expected = names.some((name) => metrics[name] === null) ? null : Math.min(...names.map((name) => metrics[name]));
  if (expected === null ? metrics.conditional_global !== null : Math.abs(metrics.conditional_global - expected) > 1e-10 || !Number.isFinite(metrics.conditional_global)) throw new Error('综合约束计算不一致');
}

function tokenMatches(value, token) {
  return typeof value === 'string' && /^[a-f0-9]{64}$/.test(value) && value.length === token.length &&
    timingSafeEqual(Buffer.from(value), Buffer.from(token));
}

export function codeIdentity(repositoryRoot) {
  const paths = [
    'scripts/run_local_radius_compute.py',
    'configs/single_head_optimization.json',
    'results/v2/current_multiregion_bank.json',
    'results/v2/current_surface_admissibility.json',
    ...readdirSync(join(repositoryRoot, 'src/compact_eeg')).filter((name) => name.endsWith('.py'))
      .sort().map((name) => `src/compact_eeg/${name}`),
  ];
  return Object.fromEntries(paths.map((path) => [path, hash(readFileSync(join(repositoryRoot, path)))]));
}

export class LocalComputeQueue {
  constructor({ repositoryRoot, python, queueDirectory, timeoutMs = 180000,
    spawnProcess = spawn, getIdentity, getRuntime, verifyInputs } = {}) {
    this.runtime = runtimeConfig({ repositoryRoot, python, queueDirectory });
    this.root = this.runtime.repositoryRoot;
    this.store = new RecordStore(this.root);
    this.executionSlot = executionSlotFor(this);
    this.python = this.runtime.python;
    this.timeoutMs = timeoutMs;
    this.spawnProcess = spawnProcess;
    this.getIdentity = getIdentity || (() => codeIdentity(this.root));
    this.getRuntime = getRuntime || (getIdentity ? () => null : () => runtimeIdentity(this.python));
    const inputs = new InputIntegrity(this.root);
    this.verifyInputs = verifyInputs || (getIdentity ? async () => {} : (result) => inputs.verify(result.provenance));
    this.jobs = new Map();
    this.active = null;
    this.submitting = false;
    this.disposed = false;
    this.token = randomBytes(32).toString('hex');
    this.library = new LocalDataLibrary(this);
  }

  health() {
    const available = existsSync(join(this.root, 'scripts/run_local_radius_compute.py')) &&
      existsSync(join(this.root, 'results/v2/current_multiregion_bank.json'));
    return { available, local_only: this.localOnly ?? true, token: this.token, max_concurrent_jobs: 1, threads: 2,
      timeout_seconds: this.timeoutMs / 1000, supported_masks: MASK_CODES,
      active_job: this.active ? this.view(this.active) : null };
  }

  view(job) {
    return { id: job.id, key: job.key, request: job.request, status: job.status, stage: job.stage,
      progress: job.progress, message: job.message, result: job.result ?? null,
      created_at: job.created_at, finished_at: job.finished_at ?? null, cached: job.cached ?? false,
      source: job.cached ? 'local_cache' : 'local_compute' };
  }

  identityFor(request, code = this.getIdentity()) {
    // Preserve the existing key format so records made before the library remain reusable.
    const runtime = this.getRuntime();
    // A data prior adds its modules and atlas, which other requests do not read, so their keys are unchanged.
    const prior = request.data_prior ? Object.fromEntries(DATA_PRIOR_FILES.map((path) => [path, hash(readFileSync(join(this.root, path)))])) : {};
    const identity = { version: 'local-radius-queue/1', code: { ...code, ...prior }, threads: 2, ...(runtime ? { runtime } : {}) };
    return { identity, key: hash(JSON.stringify({ request, identity })) };
  }

  async readCache(key, request) {
    try {
      const cache = await this.store.read(this.store.path('radius', key, 'cache.json'));
      if (cache.key !== key || cache.result_sha256 !== hash(JSON.stringify(cache.result))) return null;
      const normalized = normalizeRequest(cache.request);
      if (request && JSON.stringify(normalized) !== JSON.stringify(request)) return null;
      validateWorkerResult(cache.result, normalized);
      return { ...cache, request: normalized };
    } catch (error) {
      // Incomplete/corrupt records are never data hits. Keep the original task audit files.
      if (['EACCES', 'EPERM'].includes(error.code)) throw error;
      return null;
    }
  }

  async lookup(raw, identityKey) {
    const request = normalizeRequest(raw);
    const { key } = identityKey || this.identityFor(request);
    const same = [...this.jobs.values()].find((job) => job.key === key && ['completed', 'no_layout'].includes(job.status));
    if (same) {
      await this.verifyInputs(same.result);
      return { hit: true, job: { ...this.view(same), cached: true, source: 'local_cache' } };
    }
    const cache = await this.readCache(key, request);
    if (!cache) return { hit: false };
    await this.verifyInputs(cache.result);
    const job = { id: randomUUID(), key, request, status: cache.result.status, stage: 'cached',
      progress: 1, message: '已读取相同模型与配置的已有计算记录', result: cache.result,
      created_at: new Date().toISOString(), finished_at: cache.finished_at, cached: true };
    this.jobs.set(job.id, job);
    while (this.jobs.size > 100) {
      const oldest = [...this.jobs.values()].find((entry) => entry !== this.active);
      if (!oldest) break;
      this.jobs.delete(oldest.id);
    }
    return { hit: true, job: this.view(job) };
  }

  async submit(raw) {
    if (this.disposed) throw new Error('计算服务正在重启');
    const request = normalizeRequest(raw);
    if (this.submitting) return { busy: true };
    this.submitting = true;
    let release;
    try {
      const { identity, key } = this.identityFor(request);
      // Reading a ready result does not consume compute capacity, even while another job runs.
      const stored = await this.lookup(request, { key });
      if (stored.hit) return { job: stored.job };
      if (this.disposed) throw new Error('计算服务正在重启');
      if (this.active) {
        if (this.active.key === key) return { job: this.view(this.active) };
        return { busy: true, active_job: this.view(this.active) };
      }
      release = this.executionSlot.acquire(this);
      if (!release) return { busy: true, maintenance: this.executionSlot.paused };
      const cachePath = this.store.path('radius', key, 'cache.json');
      const id = randomUUID(), batch = await this.store.createBatch('radius', key, id);
      await this.store.write(join(batch, 'request.json'), { request, identity, key });
      if (this.disposed) throw new Error('计算服务正在重启');
      if (this.executionSlot.paused) return { busy: true, maintenance: true };
      const job = { releaseExecution: release, id, key, request, status: 'queued', stage: 'queued', progress: 0,
        message: '等待计算进程启动', created_at: new Date().toISOString(), batch, cachePath,
        events: [], stderr: '', result: null, child: null, identity };
      this.jobs.set(id, job);
      this.active = job;
      release = null;
      // Spawn only after the previous process has emitted close, never on cancel request.
      this.run(job);
      return { job: this.view(job) };
    } finally { release?.(); this.submitting = false; }
  }

  run(job) {
    if (this.disposed) { void this.finish(job, 'cancelled', '服务重启，任务未启动'); return; }
    let terminalResult = null;
    job.status = 'running'; job.stage = 'starting'; job.message = '正在加载本地头模与前向矩阵';
    try {
      job.worker = startPythonWorker({
        spawnProcess: this.spawnProcess, executable: this.python,
        args: ['-u', join(this.root, 'scripts/run_local_radius_compute.py')],
        options: { cwd: this.root, stdio: ['pipe', 'pipe', 'pipe'],
          env: { ...process.env, OMP_NUM_THREADS: '2', OPENBLAS_NUM_THREADS: '2', MKL_NUM_THREADS: '2',
            VECLIB_MAXIMUM_THREADS: '2', PYTHONUNBUFFERED: '1' } },
        input: job.request, timeoutMs: this.timeoutMs, maxOutputBytes: 8 * 1024 * 1024,
        onEvent: event => {
          if (event.type === 'progress' && !job.cancelReason) {
            job.progress = Math.max(job.progress, Math.min(.99, Number(event.progress) || 0));
            job.stage = String(event.stage || 'computing'); job.message = String(event.message || '正在计算');
          } else if (event.type === 'result') terminalResult = event.result;
          job.events.push(event);
        },
        onLog: text => job.events.push({ type: 'log', text }),
        onStderr: text => { job.stderr = text; },
        onError: error => { job.spawnError = error.message; },
        onStop: reason => { job.cancelReason = reason; job.status = 'cancelling'; job.message = '正在停止计算'; },
        onClose: code => {
          if (job.cancelReason) {
            const timed = job.cancelReason === 'timeout';
            void this.finish(job, timed ? 'timeout' : job.cancelReason === 'input_error' ? 'failed' : 'cancelled', timed ? '达到计算时限，任务已停止；未把缺失结果写成0' : '任务已停止');
          } else if (code === 0 && terminalResult && ['completed', 'no_layout'].includes(terminalResult.status)) {
            try {
              validateWorkerResult(terminalResult, job.request);
              const sources = terminalResult.provenance?.code_sha256 ?? {};
              for (const [path, digest] of Object.entries(sources)) {
                if (job.identity.code[path] !== digest) throw new Error('任务排队后科学代码已变化');
              }
            } catch (error) { void this.finish(job, 'failed', `计算结果校验失败：${error.message}`); return; }
            job.result = terminalResult;
            void this.finish(job, terminalResult.status, terminalResult.status === 'completed' ? '当前配置已计算' : `本次搜索预算内未构造出${job.request.electrode_count ?? 64}点布局`);
          } else {
            void this.finish(job, 'failed', job.spawnError ? `Python启动失败：${job.spawnError}` : '计算未成功完成；错误记录已保存，可重新计算');
          }
        },
      });
      job.child = job.worker.child;
    } catch (error) { void this.finish(job, 'failed', `无法启动Python：${error.message}`); }
  }

  async finish(job, status, message) {
    job.status = status; job.stage = status; job.message = message;
    job.finished_at = new Date().toISOString(); job.progress = ['completed', 'no_layout'].includes(status) ? 1 : job.progress;
    try {
      await this.store.write(join(job.batch, 'job.json'), { ...this.view(job), events: job.events, stderr: job.stderr });
      if (['completed', 'no_layout'].includes(status)) {
        await this.store.write(job.cachePath, { key: job.key, request: job.request, result: job.result,
          result_sha256: hash(JSON.stringify(job.result)), finished_at: job.finished_at });
      }
    } catch (error) {
      job.status = 'failed'; job.message = `计算记录保存失败：${error.message}`; job.result = null;
    } finally {
      if (this.active === job) this.active = null;
      job.releaseExecution?.(); job.releaseExecution = null;
      // Retain a bounded number of job summaries; durable results stay on disk.
      while (this.jobs.size > 100) this.jobs.delete(this.jobs.keys().next().value);
    }
  }

  cancel(id, reason = 'user') {
    const job = this.jobs.get(id);
    if (!job || !RUNNING.has(job.status)) return false;
    if (job.cancelReason) return true;
    job.worker?.stop(reason);
    return true;
  }

  dispose() { this.disposed = true; if (this.active) this.cancel(this.active.id, 'server_restart'); }
}

export function computeMiddleware(queue, guard = createAccessPolicy().guard, scheduler) {
  return async (req, res, next) => {
    const path = req.url?.split('?')[0];
    if (!path?.startsWith('/api/local-compute') && !path?.startsWith('/api/source-reception') && !path?.startsWith('/api/design-evaluation') && !path?.startsWith('/api/electrode-editor')) return next();
    if (!guard(req)) return send(res, 403, { error: 'Request rejected by access policy.' });
    try {
      if (req.method === 'GET' && path === '/api/local-compute/health') return send(res, 200, queue.health());
      const access = libraryAccess(req, res, scheduler);
      if (req.method === 'GET' && path === '/api/local-compute/library') {
        const library = await queue.library.list();
        if (scheduler?.annotations) library.electrode_annotations = scheduler.annotations.list(scheduler.session(req, res).id);
        if (access) {
          library.records = access.present(library.records);
          if (Array.isArray(library.datasets)) library.datasets = library.datasets.map(d => ({ ...d, count: library.records.filter(r => r.dataset_id === d.id).length }));
          library.library_scope = access.settings;
        }
        return send(res, 200, library);
      }
      if (req.method === 'GET' && access && path === '/api/electrode-editor/records')
        return send(res, 200, { records: access.present(await queue.editor.records(), r => r.key, () => true) });
      if (req.method === 'GET' && access && path === '/api/electrode-editor/parents')
        return send(res, 200, { records: await queue.editor.parents(rows => access.present(rows)) });
      if (req.method === 'GET' && access && path === '/api/source-reception/layouts') {
        const layouts = await receptionLayouts(queue);
        return send(res, 200, { ...layouts, records: access.present(layouts.records) });
      }
      const bundleMatch = path.match(/^\/api\/local-compute\/library\/([a-f0-9]{64})\/bundle$/);
      if (req.method === 'GET' && bundleMatch) {
        const record = await queue.library.get(bundleMatch[1]);
        if (!record || (access && !access.readable(record))) return send(res, 404, { error: '记录不存在' });
        const bundle = await experimentBundle(queue.root, record, { python: queue.python });
        const annotation = readAnnotation(req, res, scheduler, record.id);
        return send(res, 200, annotation ? { ...bundle, electrode_annotation: annotation, record: { ...bundle.record, electrode_annotation: annotation } } : bundle);
      }
      const recordMatch = path.match(/^\/api\/local-compute\/library\/([a-f0-9]{64})$/);
      if (req.method === 'GET' && recordMatch) {
        let record = await queue.library.get(recordMatch[1]);
        if (record && access && !access.readable(record)) record = null;
        if (record && access && VISITOR_DATASETS.has(record.dataset_id)) record = { ...record, visibility: access.view(record.id) };
        const annotation = record && readAnnotation(req, res, scheduler, record.id);
        return send(res, record ? 200 : 404, record ? { record: annotation ? { ...record, electrode_annotation: annotation } : record } : { error: '记录不存在或完整性校验未通过' });
      }
      if (req.method === 'POST' && !tokenMatches(req.headers['x-eeg-compute-token'], queue.token)) {
        return send(res, 403, { error: '会话已更新，请刷新页面后重新计算' });
      }
      const visibilityMatch = path.match(/^\/api\/local-compute\/library\/([a-f0-9]{64})\/visibility$/);
      if (visibilityMatch) {
        if (req.method !== 'POST' || !access) return send(res, access ? 405 : 404, { error: access ? '请使用POST' : '未知计算接口' });
        return send(res, 200, { visibility: await publishRecord(req, queue, scheduler, access, visibilityMatch[1]) });
      }
      if (path.startsWith('/api/source-reception') && queue.sources) return await queue.sources.handle(req, res, path, send);
      if (path.startsWith('/api/design-evaluation') && queue.designTests) return await queue.designTests.handle(req, res, path, send);
      if (path.startsWith('/api/electrode-editor') && queue.editor) return await queue.editor.handle(req, res, path, send);
      if (req.method === 'POST' && ['/api/local-compute/jobs', '/api/local-compute/lookup'].includes(path)) {
        if (!String(req.headers['content-type']).startsWith('application/json')) return send(res, 415, { error: '须提交JSON配置' });
        let body = '';
        for await (const chunk of req) {
          body += chunk.toString();
          if (Buffer.byteLength(body) > 4096) return send(res, 413, { error: '配置过大' });
        }
        let request;
        try { request = normalizeRequest(JSON.parse(body)); } catch (error) { return send(res, 400, { error: error.message }); }
        if (path.endsWith('/lookup')) return send(res, 200, await queue.lookup(request));
        const submitted = await queue.submit(request);
        return send(res, submitted.busy ? 409 : 202, submitted);
      }
      const match = path.match(/^\/api\/local-compute\/jobs\/([a-f0-9-]{36})(\/cancel)?$/);
      if (match) {
        const job = queue.jobs.get(match[1]);
        if (!job) return send(res, 404, { error: '任务不存在；相同配置可从保存记录重新载入' });
        if (req.method === 'GET' && !match[2]) return send(res, 200, { job: queue.view(job) });
        if (req.method === 'POST' && match[2]) { queue.cancel(job.id); return send(res, 202, { job: queue.view(job) }); }
      }
      return send(res, 404, { error: '未知计算接口' });
    } catch (error) {
      const safe = error.annotationSafe || error.visibilitySafe || error.status === 429;
      return send(res, safe ? error.status : 500, { error: safe ? error.message : '计算记录无法读取' });
    }
  };
}

const VISITOR_DATASETS = new Set(['cache', 'design_evaluation']);
/** One browser's view of the shared lists; null when no scheduler (and so no visitor) is mounted. */
function libraryAccess(req, res, scheduler) {
  const visibility = scheduler?.visibility;
  if (!visibility) return null;
  const owner = scheduler.session(req, res).id;
  return {
    owner, visibility, settings: { scope: visibility.scope, review: visibility.review },
    present: (rows, idOf = r => r.id, visitorRow = r => VISITOR_DATASETS.has(r.dataset_id)) => visibility.present(rows, owner, idOf, visitorRow),
    readable: record => !VISITOR_DATASETS.has(record.dataset_id) || visibility.readable(record.id, owner),
    view: id => visibility.view(id, owner),
  };
}

async function publishRecord(req, queue, scheduler, access, id) {
  if (!String(req.headers['content-type']).startsWith('application/json')) throw Object.assign(new Error('JSON required'), { status: 415, visibilitySafe: true });
  const chunks = []; let bytes = 0;
  for await (const chunk of req) {
    const data = Buffer.from(chunk); bytes += data.length;
    if (bytes > 256) throw Object.assign(new Error('配置过大'), { status: 413, visibilitySafe: true });
    chunks.push(data);
  }
  let body;
  try { body = JSON.parse(Buffer.concat(chunks, bytes).toString('utf8')); } catch { body = null; }
  if (!body || typeof body !== 'object' || Array.isArray(body) || Object.keys(body).join() !== 'public')
    throw Object.assign(new Error('请选择是否公开这条记录'), { status: 400, visibilitySafe: true });
  scheduler.rate({ id: access.owner, ip: scheduler.visitorAddress(req) });
  // Only completed visitor records can be listed; the label is kept for the operator's review list.
  const record = await queue.library.get(id);
  let label = VISITOR_DATASETS.has(record?.dataset_id) && record.status === 'completed' ? record.label : null;
  if (label === null) {
    const edit = (await queue.editor.records()).find(value => value.key === id);
    if (edit) label = `${edit.parent_label ?? ''} · 电极编辑 · ${edit.electrode_count}电极`;
  }
  if (label === null) throw Object.assign(new Error('记录不存在'), { status: 404, visibilitySafe: true });
  return access.visibility.publish(id, access.owner, body.public, label);
}

function readAnnotation(req, res, scheduler, recordId) {
  const q = new URL(req.url, 'http://localhost').searchParams;
  if (!q.has('annotation_id')) return null;
  if (!scheduler?.annotations || [...q.keys()].some(key => key !== 'annotation_id') || q.getAll('annotation_id').length !== 1)
    throw Object.assign(new Error('Invalid electrode name annotation query.'), { annotationSafe: true, status: 400 });
  return scheduler.annotations.read(q.get('annotation_id'), scheduler.session(req, res).id, recordId);
}

export function createLocalComputeService(repositoryRoot, options = {}) {
  const { initialMaintenance = false, policy = createAccessPolicy(), operations: operationSettings = operationsConfig(),
    library: librarySettings = libraryConfig({}), resourceGate, operationsLogger, ...queueOptions } = options;
  const queue = new LocalComputeQueue({ ...queueOptions, repositoryRoot });
  queue.localOnly = policy.localOnly;
  queue.sources = new SourceReceptionService(queue);
  queue.designTests = new DesignEvaluationService(queue);
  queue.editor = new ElectrodeEditorService(queue);
  const resources = resourceGate ?? new ResourceGate({ config: operationSettings, directories: [
    { scope: 'queue', path: queue.runtime.queueDirectory }, { scope: 'scientific', path: queue.root },
  ] });
  let disposing = false, disposal;
  const admit = async () => {
    if (disposing) throw Object.assign(new Error('The service is stopping.'), { status: 503, resourceSafe: true });
    await resources.assertAvailable();
    if (disposing) throw Object.assign(new Error('The service is stopping.'), { status: 503, resourceSafe: true });
  };
  const scheduler = new CommunityQueue({ directory: queue.runtime.queueDirectory,
    executionSlot: queue.executionSlot, initialMaintenance,
    secureCookies: policy.secureCookies, visitorAddress: policy.visitorAddress,
    annotations: new ElectrodeAnnotations(queue.root), beforeNewWork: admit, adapters: communityAdapters(queue, normalizeRequest),
    visibility: new RecordVisibility({ directory: queue.runtime.queueDirectory, ...librarySettings }) });
  const projects = new ProjectService({ queue, scheduler, guard: policy.guard, send, tokenMatches, beforeWrite: admit });
  const studies = new RobustnessStudyService({ queue, scheduler, guard: policy.guard, send, tokenMatches, beforeWrite: admit });
  const operations = new OperationsMonitor({ queue, scheduler, gate: resources, config: operationSettings, logger: operationsLogger });
  return {
    queue, scheduler, projects, studies, operations, resources,
    middleware: operations.middleware(studies.middleware(projects.middleware(communityMiddleware({ scheduler, queue, legacy: computeMiddleware(queue, policy.guard, scheduler), guard: policy.guard, send, tokenMatches })))),
    dispose() {
      if (disposing) return disposal;
      disposing = true; studies.stop(); projects.close(); scheduler.stopScheduling();
      queue.sources.dispose(); queue.designTests.dispose(); queue.editor.dispose(); queue.dispose();
      const finish = () => { operations.close(); return operations.flush(); };
      if (projects.store.pendingWrites || studies.store.pendingWrites || studies.inflight.size || operations.logger.pending || operations.active) {
        disposal = Promise.resolve().then(async () => {
          try {
            await projects.flush();
            await studies.flush(); studies.close();
            // Let accepted responses finish or observe closed sockets before closing the log.
            await new Promise(resolve => setImmediate(resolve));
            await finish();
          } finally { scheduler.dispose(); }
        });
        return disposal;
      }
      studies.close(); operations.close(); scheduler.dispose();
    },
  };
}
