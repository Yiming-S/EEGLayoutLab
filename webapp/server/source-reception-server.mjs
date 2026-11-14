import { startPythonWorker } from './jobs/python-worker.mjs';
import { executionSlotFor } from './jobs/execution-slot.mjs';
import { RECEPTION_WORKFLOW } from './project-paths.mjs';
import { runtimeConfig } from './runtime/config.mjs';
import { scientificContext } from './runtime/scientific-context.mjs';
import { RecordStore } from './storage/records.mjs';
/** Local-only, bounded time-series experiments. Never changes the layout cache. */
import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { InputIntegrity } from './local-input-integrity.mjs';
import { receptionV2Context, receptionLayouts, sourceCatalog } from './reception-v2-support.mjs';
import { normalizeReceptionRequest, validateReceptionResult } from './contracts/source-reception.mjs';
export { SOURCE_REGIONS, normalizeSourceRequest, validateSourceResult } from './contracts/source-reception.mjs';

const hash = (x) =>
  createHash('sha256')
    .update(typeof x === 'string' ? x : JSON.stringify(x))
    .digest('hex');
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
export class SourceReceptionService {
  constructor(
    queue,
    { spawnProcess = spawn, timeoutMs = 120000, getContext, nativeContext } = {},
  ) {
    this.queue = queue;
    this.root = queue.root;
    this.store = queue.store ?? new RecordStore(this.root);
    this.python = (queue.runtime ?? runtimeConfig({ repositoryRoot: this.root, python: queue.python })).nativePython;
    this.executionSlot = executionSlotFor(queue);
    this.spawnProcess = spawnProcess;
    this.timeoutMs = timeoutMs;
    this.jobs = new Map();
    this.active = null;
    this.submitting = false;
    this.disposed = false;
    this.inputs = new InputIntegrity(this.root);
    this.customContext = getContext;
    this.nativeContext = nativeContext ?? (request => scientificContext(this, request));
  }
  async context(request) {
    if (this.customContext) return this.customContext(request);
    if (request.mode) return receptionV2Context(this, request);
    const record = await this.queue.library.get(request.record_id);
    if (
      !record?.layout ||
      record.status !== 'completed' ||
      !['cache', 'strict_area'].includes(record.dataset_id)
    )
      throw new Error(
        '源实验需要已有完整64点布局；不会将几何预览或历史相交方案当作计算布局',
      );
    const pointerPath = 'results/v2/current_multiregion_bank.json';
    const pointer = JSON.parse(
      await readFile(join(this.root, pointerPath), 'utf8'),
    );
    const paths = [
      ...RECEPTION_WORKFLOW,
      pointerPath,
      pointer.path,
      pointer.candidates,
      pointer.report,
      'scripts/source_reception.py',
      'scripts/run_source_reception.py',
    ];
    const digests = Object.fromEntries(
      await Promise.all(
        paths.map(async (p) => [p, await this.inputs.digest(p)]),
      ),
    );
    if (digests[pointer.path] !== pointer.sha256)
      throw new Error('前向矩阵校验失败');
    const report = JSON.parse(
      await readFile(join(this.root, pointer.report), 'utf8'),
    );
    if (report.candidate_sha256 !== digests[pointer.candidates])
      throw new Error('候选坐标校验失败');
    const identity = {
      version: 'source-reception-cache/1',
      record_id: record.id,
      layout: record.layout,
      digests,
      threads: 2,
    };
    return { record, identity, key: hash({ request, identity }) };
  }
  view(job) {
    return {
      id: job.id,
      key: job.key,
      request: job.request,
      status: job.status,
      progress: job.progress,
      message: job.message,
      result: job.result ?? null,
      cached: Boolean(job.cached),
      finished_at: job.finished_at ?? null,
    };
  }
  async lookup(raw, context) {
    const request = normalizeReceptionRequest(raw),
      ctx = context ?? (await this.context(request));
    try {
      const path = this.store.path(request.mode ? 'sourceV2' : 'source', ctx.key, 'cache.json');
      if ((await stat(path)).size > 32 * 1024 * 1024)
        throw new Error('结果记录过大');
      const cache = await this.store.read(path);
      if (cache.key !== ctx.key || cache.result_sha256 !== hash(cache.result))
        throw new Error('结果记录校验失败');
      validateReceptionResult(cache.result, request, ctx.record);
      const job = {
        id: randomUUID(),
        key: ctx.key,
        request,
        status: 'completed',
        progress: 1,
        message: '已读取同一源、布局和干扰条件的本地结果',
        result: cache.result,
        cached: true,
        finished_at: cache.finished_at,
      };
      this.remember(job);
      return { hit: true, job: this.view(job) };
    } catch (error) {
      if (['EACCES', 'EPERM'].includes(error.code)) throw error;
      return { hit: false };
    }
  }
  async savedResult(key, raw) {
    // Historical downloads validate the saved protocol, not today's model identity.
    // The caller authorizes the owning browser's durable receipt before this read.
    if (!/^[a-f0-9]{64}$/.test(key)) throw new Error('Invalid saved signal record');
    const request = normalizeReceptionRequest(raw);
    const path = this.store.path(request.mode ? 'sourceV2' : 'source', key, 'cache.json');
    let cache;
    try {
      if ((await stat(path)).size > 32 * 1024 * 1024) throw new Error('结果记录过大');
      cache = await this.store.read(path);
    } catch (error) { if (error.code === 'ENOENT') throw new Error('计算记录无法读取，请重新提交'); throw error; }
    if (cache.key !== key || cache.result_sha256 !== hash(cache.result) ||
      !equal(normalizeReceptionRequest(cache.result?.request), request) ||
      (request.mode && (!cache.identity?.layout || hash({ request, identity: cache.identity }) !== key))) throw new Error('结果记录校验失败');
    const layout = cache.result.layout;
    const validXYZ = coordinates => Array.isArray(coordinates) && coordinates.length === 64 &&
      coordinates.every(point => Array.isArray(point) && point.length === 3 && point.every(Number.isFinite)) && new Set(coordinates.map(point => point.join(','))).size === 64;
    const regions = layout?.regionIndices;
    if (!validXYZ(layout?.xyzMm) || !validXYZ(layout?.referenceXyzMm) || !Array.isArray(regions) || regions.length !== 64 ||
      ![1, 2, 3, 4, 6].includes(new Set(regions).size) || regions.some(region => !Number.isInteger(region) || region < 0 || region >= new Set(regions).size)) throw new Error('保存的信号布局坐标或区域标签无效');
    validateReceptionResult(cache.result, request, { layout: cache.identity?.layout ?? layout });
    return cache.result;
  }
  remember(job) {
    this.jobs.set(job.id, job);
    while (this.jobs.size > 10) {
      const id = [...this.jobs.keys()].find((x) => x !== this.active?.id);
      if (!id) break;
      this.jobs.delete(id);
    }
  }
  async submit(raw) {
    if (this.disposed) throw new Error('本地服务正在重启');
    const request = normalizeReceptionRequest(raw);
    if (this.submitting) return { busy: true };
    this.submitting = true;
    let release;
    try {
      const ctx = await this.context(request),
        cached = await this.lookup(request, ctx);
      if (cached.hit) return { job: cached.job };
      if (this.disposed) throw new Error('本地服务正在重启');
      if (this.active?.key === ctx.key) return { job: this.view(this.active) };
      release = this.executionSlot.acquire(this);
      if (!release) return { busy: true, maintenance: this.executionSlot.paused };
      const id = randomUUID(),
        kind = request.mode ? 'sourceV2' : 'source',
        directory = this.store.path(kind, ctx.key),
        batch = await this.store.createBatch(kind, ctx.key, id);
      await this.store.write(join(batch, 'request.json'), {
        request,
        record: ctx.record,
      });
      if (this.disposed) throw new Error('本地服务正在重启');
      if (this.executionSlot.paused) return { busy: true, maintenance: true };
      const job = {
        releaseExecution: release,
        id,
        key: ctx.key,
        request,
        ctx,
        batch,
        directory,
        status: 'running',
        progress: 0,
        message: '加载冻结布局与前向矩阵',
        result: null,
        stderr: '',
      };
      this.active = job;
      release = null;
      this.remember(job);
      this.run(job);
      return { job: this.view(job) };
    } finally {
      release?.();
      this.submitting = false;
    }
  }
  run(job) {
    if (this.disposed) { void this.finish(job, 'cancelled', '服务重启，任务未启动'); return; }
    try {
      job.worker = startPythonWorker({
        spawnProcess: this.spawnProcess,
        executable: job.request.mode ? this.python : this.queue.python,
        args: ['-u', join(this.root, job.request.mode ? 'scripts/run_source_reception_v2.py' : 'scripts/run_source_reception.py'),
          '--repository-root', this.root, '--request', join(job.batch, 'request.json'), '--output', join(job.batch, 'result.json')],
        options: { cwd: this.root, stdio: ['ignore', 'pipe', 'pipe'], env: {
          ...process.env, OMP_NUM_THREADS: job.request.mode ? '1' : '2', OPENBLAS_NUM_THREADS: job.request.mode ? '1' : '2',
          MKL_NUM_THREADS: job.request.mode ? '1' : '2', VECLIB_MAXIMUM_THREADS: job.request.mode ? '1' : '2', PYTHONDONTWRITEBYTECODE: '1' } },
        timeoutMs: job.request.mode ? Math.max(this.timeoutMs, 600000) : this.timeoutMs, maxOutputBytes: 1024 * 1024,
        onEvent: (event, diagnostic) => {
          if (event.type === 'progress' && !job.cancelReason) {
            job.progress = Math.max(job.progress, Math.min(.99, Number(event.progress) || 0));
            job.message = String(event.message ?? '正在计算源—接收对照');
          }
          if (event.type === 'error') diagnostic(String(event.message ?? 'worker error'));
        },
        onStderr: text => { job.stderr = text; },
        onError: error => { job.stderr = (job.stderr + error.message).slice(-16000); },
        onStop: reason => { job.cancelReason = reason; job.status = 'cancelling'; job.message = '正在停止源实验'; },
        onClose: code => { void this.close(job, code); },
      });
      job.child = job.worker.child;
    } catch (error) { void this.finish(job, 'failed', `无法启动计算：${error.message}`); }
  }
  async close(job, code) {
    if (job.cancelReason)
      return this.finish(
        job,
        job.cancelReason === 'timeout' ? 'timeout' : job.cancelReason === 'input_error' ? 'failed' : 'cancelled',
        '计算已停止；没有缓存未完成结果',
      );
    if (code !== 0)
      return this.finish(
        job,
        'failed',
        '源实验未完成；错误记录已保存，没有替换为旧分数',
      );
    try {
      const path = join(job.batch, 'result.json');
      if ((await stat(path)).size > 24 * 1024 * 1024)
        throw new Error('结果超过安全大小限制');
      const result = JSON.parse(await readFile(path, 'utf8'));
      validateReceptionResult(result, job.request, job.ctx.record);
      if ((await this.context(job.request)).key !== job.key)
        throw new Error('计算期间模型、源代码或原始布局已变化');
      job.result = result;
      return this.finish(job, 'completed', '源—接收对照已计算并保存');
    } catch (e) {
      return this.finish(job, 'failed', `结果校验失败：${e.message}`);
    }
  }
  async finish(job, status, message) {
    job.status = status;
    job.message = message;
    job.finished_at = new Date().toISOString();
    if (status !== 'completed') job.result = null;
    try {
      if (status === 'completed') {
        await this.store.write(join(job.directory, 'cache.json'), {
          key: job.key,
          ...(job.request.mode ? { identity: job.ctx.identity } : {}),
          result: job.result,
          result_sha256: hash(job.result),
          finished_at: job.finished_at,
        });
        job.progress = 1;
      }
      await this.store.write(join(job.batch, 'job.json'), {
        ...this.view(job),
        result: undefined,
        stderr: job.stderr,
      });
    } catch (e) {
      job.status = 'failed';
      job.result = null;
      job.message = `保存失败：${e.message}`;
    } finally {
      if (this.active === job) this.active = null;
      job.releaseExecution?.(); job.releaseExecution = null;
    }
  }
  cancel(id, reason = 'user') {
    const job = this.jobs.get(id);
    if (!job || !['running', 'cancelling'].includes(job.status)) return false;
    if (job.cancelReason) return true;
    job.worker?.stop(reason);
    return true;
  }
  dispose() {
    this.disposed = true;
    if (this.active) this.cancel(this.active.id, 'restart');
  }
  async handle(req, res, path, send) {
    if (req.method === 'GET' && path === '/api/source-reception/layouts') return send(res, 200, await receptionLayouts(this.queue));
    if (req.method === 'GET' && path === '/api/source-reception/catalog') {
      this.catalogPromise ??= sourceCatalog(this).finally(() => { this.catalogPromise = null; });
      return send(res, 200, await this.catalogPromise);
    }
    if (req.method === 'GET' && path === '/api/source-reception/health')
      return send(res, 200, {
        available: true,
        local_only: true,
        token: this.queue.token,
        active_job: this.active ? this.view(this.active) : null,
      });
    if (
      req.method === 'POST' &&
      ['/api/source-reception/jobs', '/api/source-reception/lookup'].includes(
        path,
      )
    ) {
      if (!String(req.headers['content-type']).startsWith('application/json'))
        return send(res, 415, { error: '须提交JSON配置' });
      let body = '';
      for await (const c of req) {
        body += c.toString();
        if (Buffer.byteLength(body) > 4096)
          return send(res, 413, { error: '配置过大' });
      }
      let request;
      try {
        request = normalizeReceptionRequest(JSON.parse(body));
      } catch (e) {
        return send(res, 400, { error: e.message });
      }
      if (path.endsWith('/lookup'))
        return send(res, 200, await this.lookup(request));
      const value = await this.submit(request);
      return send(res, value.busy ? 409 : 202, value);
    }
    const match = path.match(
      /^\/api\/source-reception\/jobs\/([a-f0-9-]{36})(\/cancel)?$/,
    );
    if (match) {
      const job = this.jobs.get(match[1]);
      if (!job)
        return send(res, 404, { error: '任务不存在，请按原配置重新读取缓存' });
      if (req.method === 'GET' && !match[2])
        return send(res, 200, { job: this.view(job) });
      if (req.method === 'POST' && match[2]) {
        this.cancel(job.id);
        return send(res, 202, { job: this.view(job) });
      }
    }
    return send(res, 404, { error: '未知源实验接口' });
  }
}
