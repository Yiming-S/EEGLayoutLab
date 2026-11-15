import { createAccessPolicy } from './http/access-policy.mjs';
import { startPythonWorker } from './jobs/python-worker.mjs';
import { executionSlotFor } from './jobs/execution-slot.mjs';
import { runtimeConfig } from './runtime/config.mjs';
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
  if (Object.keys(input).some((key) => !['region_count', 'radius_mm', 'mode', 'mask_codes'].includes(key))) {
    throw new Error('配置含未支持字段');
  }
  const { region_count, radius_mm, mode } = input;
  if (![1, 2, 3, 4, 6].includes(region_count)) throw new Error('区域数只支持1、2、3、4、6');
  if (!Number.isInteger(radius_mm) || radius_mm < 15 || radius_mm > 80 || radius_mm % 5) {
    throw new Error('半径须为15–80 mm，步长5 mm');
  }
  if (!['whole_surface', 'low_hair', 'preset'].includes(mode)) throw new Error('不支持的区域模式');
  if (mode === 'preset') {
    if (!Array.isArray(input.mask_codes) || input.mask_codes.length !== region_count ||
        input.mask_codes.some((code) => !MASK_CODES.includes(code))) {
      throw new Error('该组合的细分解剖掩膜尚未建立；请选择已支持的耳后、耳周、前额或眶周代理区域');
    }
    return { region_count, radius_mm, mode, mask_codes: [...input.mask_codes] };
  }
  if (input.mask_codes !== undefined && (!Array.isArray(input.mask_codes) || input.mask_codes.length)) {
    throw new Error('自由中心模式不接受指定掩膜');
  }
  return { region_count, radius_mm, mode };
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
  const coordinates = (rows) => Array.isArray(rows) && rows.length === 64 &&
    rows.every((row) => Array.isArray(row) && row.length === 3 && row.every(Number.isFinite));
  if (!layout || !coordinates(layout.xyzMm) || !coordinates(layout.referenceXyzMm) ||
      new Set(layout.xyzMm.map((row) => row.join(','))).size !== 64 ||
      !Array.isArray(layout.regionIndices) || layout.regionIndices.length !== 64 ||
      !layout.regionIndices.every((r) => Number.isInteger(r) && r >= 0 && r < request.region_count)) throw new Error('无效64点坐标');
  const counts = Array.from({ length: request.region_count }, (_, r) => layout.regionIndices.filter((v) => v === r).length);
  if (counts.some((count, r) => count !== Math.floor(64 / request.region_count) + Number(r < 64 % request.region_count))) throw new Error('区域分配错误');
  if (!geometry || geometry.union_connected_component_count !== request.region_count ||
      !Number.isFinite(geometry.common_graph_radius_mm) || geometry.common_graph_radius_mm <= 0 ||
      geometry.common_graph_radius_mm > request.radius_mm + 1e-7 ||
      !Number.isFinite(geometry.union_area_cm2) || geometry.union_area_cm2 <= 0) throw new Error('区域几何无效');
  for (let i = 0; i < 64; i++) for (let j = i + 1; j < 64; j++) {
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
    spawnProcess = spawn, getIdentity, verifyInputs } = {}) {
    this.runtime = runtimeConfig({ repositoryRoot, python, queueDirectory });
    this.root = this.runtime.repositoryRoot;
    this.store = new RecordStore(this.root);
    this.executionSlot = executionSlotFor(this);
    this.python = this.runtime.python;
    this.timeoutMs = timeoutMs;
    this.spawnProcess = spawnProcess;
    this.getIdentity = getIdentity || (() => codeIdentity(this.root));
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

  identityFor(request) {
    // Preserve the existing key format so records made before the library remain reusable.
    const identity = { version: 'local-radius-queue/1', code: this.getIdentity(), threads: 2 };
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
      progress: 1, message: '已读取相同模型与配置的本地计算记录', result: cache.result,
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
    if (this.disposed) throw new Error('本地计算服务正在重启');
    const request = normalizeRequest(raw);
    if (this.submitting) return { busy: true };
    this.submitting = true;
    let release;
    try {
      const { identity, key } = this.identityFor(request);
      // Reading a ready result does not consume compute capacity, even while another job runs.
      const stored = await this.lookup(request, { key });
      if (stored.hit) return { job: stored.job };
      if (this.disposed) throw new Error('本地计算服务正在重启');
      if (this.active) {
        if (this.active.key === key) return { job: this.view(this.active) };
        return { busy: true, active_job: this.view(this.active) };
      }
      release = this.executionSlot.acquire(this);
      if (!release) return { busy: true, maintenance: this.executionSlot.paused };
      const cachePath = this.store.path('radius', key, 'cache.json');
      const id = randomUUID(), batch = await this.store.createBatch('radius', key, id);
      await this.store.write(join(batch, 'request.json'), { request, identity, key });
      if (this.disposed) throw new Error('本地计算服务正在重启');
      if (this.executionSlot.paused) return { busy: true, maintenance: true };
      const job = { releaseExecution: release, id, key, request, status: 'queued', stage: 'queued', progress: 0,
        message: '等待本地计算进程启动', created_at: new Date().toISOString(), batch, cachePath,
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
            void this.finish(job, terminalResult.status, terminalResult.status === 'completed' ? '当前配置已计算' : '本次搜索预算内未构造出64点布局');
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
      if (req.method === 'GET' && path === '/api/local-compute/library') {
        const library = await queue.library.list();
        if (scheduler?.annotations) library.electrode_annotations = scheduler.annotations.list(scheduler.session(req, res).id);
        return send(res, 200, library);
      }
      const bundleMatch = path.match(/^\/api\/local-compute\/library\/([a-f0-9]{64})\/bundle$/);
      if (req.method === 'GET' && bundleMatch) {
        const record = await queue.library.get(bundleMatch[1]);
        if (!record) return send(res, 404, { error: '记录不存在' });
        const bundle = await experimentBundle(queue.root, record, { python: queue.python });
        const annotation = readAnnotation(req, res, scheduler, record.id);
        return send(res, 200, annotation ? { ...bundle, electrode_annotation: annotation, record: { ...bundle.record, electrode_annotation: annotation } } : bundle);
      }
      const recordMatch = path.match(/^\/api\/local-compute\/library\/([a-f0-9]{64})$/);
      if (req.method === 'GET' && recordMatch) {
        const record = await queue.library.get(recordMatch[1]);
        const annotation = record && readAnnotation(req, res, scheduler, record.id);
        return send(res, record ? 200 : 404, record ? { record: annotation ? { ...record, electrode_annotation: annotation } : record } : { error: '记录不存在或完整性校验未通过' });
      }
      if (req.method === 'POST' && !tokenMatches(req.headers['x-eeg-compute-token'], queue.token)) {
        return send(res, 403, { error: '本地会话已更新，请刷新页面后重新计算' });
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
      return send(res, 404, { error: '未知本地计算接口' });
    } catch (error) { return send(res, error.annotationSafe ? error.status : 500, { error: error.annotationSafe ? error.message : '本地计算记录无法读取' }); }
  };
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
    resourceGate, operationsLogger, ...queueOptions } = options;
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
    annotations: new ElectrodeAnnotations(queue.root), beforeNewWork: admit, adapters: communityAdapters(queue, normalizeRequest) });
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
