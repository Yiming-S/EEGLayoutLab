import { repositoryRootForWebapp, nativePythonPath } from './project-paths.mjs';
/** Local Node service, shared by development and production hosts. */
import { spawn } from 'node:child_process';
import { createHash, randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { LocalDataLibrary } from './local-data-library.mjs';
import { InputIntegrity } from './local-input-integrity.mjs';
import { SourceReceptionService } from './source-reception-server.mjs';
import { experimentBundle } from './experiment-bundle.mjs';
import { DesignEvaluationService } from './design-evaluation-server.mjs';
import { ElectrodeEditorService } from './electrode-editor-server.mjs';

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

export function loopbackRequest(req) {
  const remote = req.socket?.remoteAddress;
  if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(remote)) return false;
  const host = req.headers.host;
  if (typeof host !== 'string' || !/^(localhost|127\.0\.0\.1|\[::1\])(?::\d{1,5})?$/.test(host)) return false;
  if (req.headers.origin && req.headers.origin !== `http://${host}`) return false;
  return !req.headers['sec-fetch-site'] || ['same-origin', 'none'].includes(req.headers['sec-fetch-site']);
}

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

async function atomicJson(path, value) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  await writeFile(temporary, JSON.stringify(value), { flag: 'wx' });
  await rename(temporary, path);
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
  constructor({ repositoryRoot, python, timeoutMs = 180000,
    spawnProcess = spawn, getIdentity, verifyInputs } = {}) {
    this.root = resolve(repositoryRoot);
    this.python = python || process.env.EEG_COMPUTE_PYTHON ||
      (existsSync(nativePythonPath(this.root)) ? nativePythonPath(this.root) : 'python3');
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
    return { available, local_only: true, token: this.token, max_concurrent_jobs: 1, threads: 2,
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
      const cache = JSON.parse(await readFile(join(this.root, 'results/v2/local_app_jobs', key, 'cache.json'), 'utf8'));
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
    try {
      const { identity, key } = this.identityFor(request);
      // Reading a ready result does not consume compute capacity, even while another job runs.
      const stored = await this.lookup(request, { key });
      if (stored.hit) return { job: stored.job };
      if (this.sources?.active || this.sources?.submitting || this.designTests?.active || this.designTests?.submitting || this.editor?.active || this.editor?.submitting) return { busy: true, error: '本机实验正在计算，请完成后再提交布局搜索' };
      if (this.active) {
        if (this.active.key === key) return { job: this.view(this.active) };
        return { busy: true, active_job: this.view(this.active) };
      }
      const directory = join(this.root, 'results/v2/local_app_jobs', key);
      const cachePath = join(directory, 'cache.json');
      const id = randomUUID(), batch = join(directory, id);
      await mkdir(batch, { recursive: true });
      await atomicJson(join(batch, 'request.json'), { request, identity, key });
      const job = { id, key, request, status: 'queued', stage: 'queued', progress: 0,
        message: '等待本地计算进程启动', created_at: new Date().toISOString(), batch, cachePath,
        events: [], stderr: '', result: null, child: null, identity };
      this.jobs.set(id, job);
      this.active = job;
      // Spawn only after the previous process has emitted close, never on cancel request.
      this.run(job);
      return { job: this.view(job) };
    } finally { this.submitting = false; }
  }

  run(job) {
    let child;
    try {
      child = this.spawnProcess(this.python, ['-u', join(this.root, 'scripts/run_local_radius_compute.py')], {
        cwd: this.root, shell: false, stdio: ['pipe', 'pipe', 'pipe'],
        env: { ...process.env, OMP_NUM_THREADS: '2', OPENBLAS_NUM_THREADS: '2', MKL_NUM_THREADS: '2',
          VECLIB_MAXIMUM_THREADS: '2', PYTHONUNBUFFERED: '1' },
      });
    } catch (error) { void this.finish(job, 'failed', `无法启动Python：${error.message}`); return; }
    job.child = child;
    job.status = 'running'; job.stage = 'starting'; job.message = '正在加载本地头模与前向矩阵';
    let buffer = '', bytes = 0, terminalResult = null;
    const timer = setTimeout(() => this.cancel(job.id, 'timeout'), this.timeoutMs);
    job.timer = timer;
    child.stdout.on('data', (chunk) => {
      bytes += chunk.length;
      if (bytes > 8 * 1024 * 1024) { this.cancel(job.id, 'output_limit'); return; }
      buffer += chunk.toString();
      const lines = buffer.split('\n'); buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line);
          if (event.type === 'progress' && !job.cancelReason) {
            job.progress = Math.max(job.progress, Math.min(.99, Number(event.progress) || 0));
            job.stage = String(event.stage || 'computing'); job.message = String(event.message || '正在计算');
          } else if (event.type === 'result') terminalResult = event.result;
          job.events.push(event);
        } catch { job.events.push({ type: 'log', text: line.slice(0, 2000) }); }
      }
    });
    child.stderr.on('data', (chunk) => { job.stderr = (job.stderr + chunk).slice(-16000); });
    child.stdin.on('error', () => {});
    child.on('error', (error) => { job.spawnError = error.message; });
    child.once('close', (code) => {
      clearTimeout(timer); clearTimeout(job.killTimer);
      if (job.cancelReason) {
        const timed = job.cancelReason === 'timeout';
        void this.finish(job, timed ? 'timeout' : 'cancelled', timed ? '达到计算时限，任务已停止；未把缺失结果写成0' : '任务已停止');
      } else if (code === 0 && terminalResult && ['completed', 'no_layout'].includes(terminalResult.status)) {
        try {
          validateWorkerResult(terminalResult, job.request);
          const sources = terminalResult.provenance?.code_sha256 ?? {};
          for (const [path, digest] of Object.entries(sources)) {
            if (job.identity.code[path] !== digest) throw new Error('任务排队后科学代码已变化');
          }
        } catch (error) {
          void this.finish(job, 'failed', `计算结果校验失败：${error.message}`);
          return;
        }
        job.result = terminalResult;
        void this.finish(job, terminalResult.status, terminalResult.status === 'completed' ? '当前配置已计算' : '本次搜索预算内未构造出64点布局');
      } else {
        void this.finish(job, 'failed', job.spawnError ? `Python启动失败：${job.spawnError}` : '计算未成功完成；错误记录已保存，可重新计算');
      }
    });
    child.stdin.end(JSON.stringify(job.request));
  }

  async finish(job, status, message) {
    job.status = status; job.stage = status; job.message = message;
    job.finished_at = new Date().toISOString(); job.progress = ['completed', 'no_layout'].includes(status) ? 1 : job.progress;
    try {
      await atomicJson(join(job.batch, 'job.json'), { ...this.view(job), events: job.events, stderr: job.stderr });
      if (['completed', 'no_layout'].includes(status)) {
        await atomicJson(job.cachePath, { key: job.key, request: job.request, result: job.result,
          result_sha256: hash(JSON.stringify(job.result)), finished_at: job.finished_at });
      }
    } catch (error) {
      job.status = 'failed'; job.message = `计算记录保存失败：${error.message}`; job.result = null;
    } finally {
      if (this.active === job) this.active = null;
      // Retain a bounded number of job summaries; durable results stay on disk.
      while (this.jobs.size > 100) this.jobs.delete(this.jobs.keys().next().value);
    }
  }

  cancel(id, reason = 'user') {
    const job = this.jobs.get(id);
    if (!job || !RUNNING.has(job.status)) return false;
    if (job.cancelReason) return true;
    job.cancelReason = reason; job.status = 'cancelling'; job.message = '正在停止计算';
    job.child?.kill('SIGTERM');
    job.killTimer = setTimeout(() => job.child?.kill('SIGKILL'), 2000);
    return true;
  }

  dispose() { this.disposed = true; if (this.active) this.cancel(this.active.id, 'server_restart'); }
}

function send(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', 'Cross-Origin-Resource-Policy': 'same-origin' });
  res.end(JSON.stringify(data));
}

export function computeMiddleware(queue) {
  return async (req, res, next) => {
    const path = req.url?.split('?')[0];
    if (!path?.startsWith('/api/local-compute') && !path?.startsWith('/api/source-reception') && !path?.startsWith('/api/design-evaluation') && !path?.startsWith('/api/electrode-editor')) return next();
    if (!loopbackRequest(req)) return send(res, 403, { error: '计算接口只接受本机同源请求' });
    try {
      if (req.method === 'GET' && path === '/api/local-compute/health') return send(res, 200, queue.health());
      if (req.method === 'GET' && path === '/api/local-compute/library') return send(res, 200, await queue.library.list());
      const bundleMatch = path.match(/^\/api\/local-compute\/library\/([a-f0-9]{64})\/bundle$/);
      if (req.method === 'GET' && bundleMatch) {
        const record = await queue.library.get(bundleMatch[1]);
        return send(res, record ? 200 : 404, record ? await experimentBundle(queue.root, record, { python: queue.python }) : { error: '记录不存在' });
      }
      const recordMatch = path.match(/^\/api\/local-compute\/library\/([a-f0-9]{64})$/);
      if (req.method === 'GET' && recordMatch) {
        const record = await queue.library.get(recordMatch[1]);
        return send(res, record ? 200 : 404, record ? { record } : { error: '记录不存在或完整性校验未通过' });
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
    } catch (error) { return send(res, 500, { error: `本地计算服务错误：${error.message}` }); }
  };
}

export function createLocalComputeService(repositoryRoot) {
  const queue = new LocalComputeQueue({ repositoryRoot });
  queue.sources = new SourceReceptionService(queue);
  queue.designTests = new DesignEvaluationService(queue);
  queue.editor = new ElectrodeEditorService(queue);
  return {
    queue,
    middleware: computeMiddleware(queue),
    dispose() {
      queue.sources.dispose();
      queue.designTests.dispose();
      queue.editor.dispose();
      queue.dispose();
    },
  };
}

export function localComputePlugin() {
  return { name: 'eeg-local-compute', apply: 'serve',
    configureServer(server) {
      const service = createLocalComputeService(repositoryRootForWebapp(server.config.root));
      server.middlewares.use(service.middleware);
      server.httpServer?.once('close', () => service.dispose());
    } };
}
