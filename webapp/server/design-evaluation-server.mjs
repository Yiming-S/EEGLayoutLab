import { startPythonWorker } from './jobs/python-worker.mjs';
import { executionSlotFor } from './jobs/execution-slot.mjs';
import { runtimeConfig } from './runtime/config.mjs';
import { scientificContext } from './runtime/scientific-context.mjs';
import { RecordStore } from './storage/records.mjs';
/** On-device only. Independent result namespace, one shared physical worker slot. */
import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { join } from 'node:path';
import { InputIntegrity } from './local-input-integrity.mjs';

const hash = (value) =>
  createHash('sha256').update(JSON.stringify(value)).digest('hex');
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
export function normalizeDesignRequest(x) {
  if (
    !x ||
    typeof x !== 'object' ||
    Array.isArray(x) ||
    Object.keys(x).sort().join(',') !== 'action,design,radius_mm,seed'
  )
    throw new Error('设计评价字段错误');
  const d = x.design;
  if (
    !d ||
    d.schema !== 'eeg-electrode-design/1' ||
    d.coordinate_system !== 'ernie_native_mm' ||
    d.unit !== 'mm'
  )
    throw new Error('需要已配准的Ernie原生毫米坐标');
  if (
    !Array.isArray(d.xyz_mm) ||
    d.xyz_mm.length !== 64 ||
    d.xyz_mm.some(
      (p) =>
        !Array.isArray(p) ||
        p.length !== 3 ||
        p.some((v) => !Number.isFinite(v) || Math.abs(v) > 500),
    ) ||
    new Set(d.xyz_mm.map((p) => p.join(','))).size !== 64
  )
    throw new Error('需要64个互异的有限坐标');
  if (!Array.isArray(d.region_indices) || d.region_indices.length !== 64)
    throw new Error('需要64个区域标签');
  const r = new Set(d.region_indices).size;
  if (
    ![1, 2, 3, 4, 6].includes(r) ||
    d.region_indices.some((v) => !Number.isInteger(v) || v < 0 || v >= r)
  )
    throw new Error('区域编号错误');
  const counts = Array.from(
    { length: r },
    (_, i) => d.region_indices.filter((v) => v === i).length,
  ).sort((a, b) => b - a);
  if (counts.some((n, i) => n !== Math.floor(64 / r) + Number(i < 64 % r)))
    throw new Error('区域分配须均衡，总数64');
  for (let i = 0; i < 64; i++)
    for (let j = i + 1; j < 64; j++)
      if (
        Math.hypot(...d.xyz_mm[i].map((v, k) => v - d.xyz_mm[j][k])) <
        4 - 1e-7
      )
        throw new Error('最小直线点距需达到4 mm');
  if (
    !['evaluate', 'perturb'].includes(x.action) ||
    ![3, 6, 10].includes(x.radius_mm) ||
    !Number.isInteger(x.seed) ||
    x.seed < 0 ||
    x.seed > 9999
  )
    throw new Error('计算动作、偏移或种子无效');
  return {
    action: x.action,
    design: {
      schema: d.schema,
      coordinate_system: d.coordinate_system,
      unit: d.unit,
      name: typeof d.name === 'string' ? d.name.slice(0, 100) : '导入布局',
      xyz_mm: d.xyz_mm,
      region_indices: d.region_indices,
    },
    radius_mm: x.radius_mm,
    seed: x.seed,
  };
}
export function validateDesignResult(r, request, admission) {
  if (admission && (r?.provenance?.surface_admissibility_sha256 !== admission.sha256 || r?.provenance?.surface_admissibility_version !== admission.schema_version)) throw new Error('设计评价表面筛选身份不匹配');
  if (
    r?.schema !== 'design-evaluation/1' ||
    r.status !== 'completed' ||
    !same(r.request, request) ||
    !['cached_fem', 'direct_fem'].includes(r.forward_mode)
  )
    throw new Error('设计评价结果身份错误');
  if (
    !r.nominal ||
    !Number.isFinite(r.nominal.field_relative) ||
    !Number.isFinite(r.nominal.median_mm) ||
    !Number.isFinite(r.nominal.reference_median_mm)
  )
    throw new Error('评价指标无效');
  for (const key of [
    'field_absolute',
    'reference_field_absolute',
    'p90_mm',
    'reference_p90_mm',
  ])
    if (!Number.isFinite(r.nominal[key]))
      throw new Error('缺少绝对指标或误差分位数');
  for (const key of ['sensitivity_tail', 'localization_relative'])
    if (r.nominal[key] !== null && !Number.isFinite(r.nominal[key]))
      throw new Error('无效相对指标');
  if (
    r.nominal.median_mm < 0 ||
    r.nominal.p90_mm < r.nominal.median_mm ||
    r.nominal.reference_median_mm < 0 ||
    r.nominal.reference_p90_mm < r.nominal.reference_median_mm ||
    r.nominal.reference_field_absolute <= 0 ||
    Math.abs(
      r.nominal.field_relative -
        r.nominal.field_absolute / r.nominal.reference_field_absolute,
    ) > 1e-8
  )
    throw new Error('绝对指标与相对指标不一致');
  if (
    !Number.isFinite(r.projection_max_mm) ||
    r.projection_max_mm < 0 ||
    r.projection_max_mm > 2 + 1e-7 ||
    !Array.isArray(r.evaluated_xyz_mm) ||
    r.evaluated_xyz_mm.length !== 64 ||
    r.evaluated_xyz_mm.some(
      (p, i) =>
        !Array.isArray(p) ||
        p.length !== 3 ||
        !p.every(Number.isFinite) ||
        Math.hypot(...p.map((v, k) => v - request.design.xyz_mm[i][k])) >
          2 + 1e-7,
    )
  )
    throw new Error('结果投影坐标无效');
  const xyzValid = (a) =>
    Array.isArray(a) &&
    a.length === 64 &&
    a.every(
      (p) => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite),
    );
  const gap = (a, b) => Math.hypot(...a.map((v, k) => v - b[k]));
  const minimum = (a) =>
    Math.min(...a.flatMap((p, i) => a.slice(i + 1).map((q) => gap(p, q))));
  if (minimum(r.evaluated_xyz_mm) < 4 - 1e-7)
    throw new Error('实际评价坐标点距不足');
  const adjustment = Math.max(
    ...r.evaluated_xyz_mm.map((p, i) => gap(p, request.design.xyz_mm[i])),
  );
  if (Math.abs(adjustment - r.projection_max_mm) > 1e-7)
    throw new Error('投影距离与实际坐标不一致');
  if (
    !Array.isArray(r.trials) ||
    r.trials.length !== (request.action === 'perturb' ? 4 : 0)
  )
    throw new Error('偏移试验不完整');
  for (const [i, t] of r.trials.entries()) {
    if (
      !xyzValid(t.xyz_mm) ||
      !xyzValid(t.requested_xyz_mm) ||
      new Set(t.xyz_mm.map((p) => p.join(','))).size !== 64 ||
      !Number.isInteger(r.provenance?.candidate_count) ||
      !Array.isArray(t.candidate_bank_indices) ||
      t.candidate_bank_indices.length !== 64 ||
      new Set(t.candidate_bank_indices).size !== 64 ||
      t.candidate_bank_indices.some((v) => !Number.isInteger(v) || v < 0 || v >= r.provenance.candidate_count) ||
      !same(t.region_indices, request.design.region_indices)
    )
      throw new Error('偏移坐标或区域标签无效');
    const moved = t.xyz_mm.map((p, i) => gap(p, request.design.xyz_mm[i]));
    const targetError = Math.max(
      ...t.xyz_mm.map((p, i) => gap(p, t.requested_xyz_mm[i])),
    );
    const unchanged = moved.filter((v) => v <= 1e-7).length / 64;
    if (
      !Number.isFinite(t.minimum_chord_distance_mm) ||
      Math.abs(minimum(t.xyz_mm) - t.minimum_chord_distance_mm) > 1e-7 ||
      Math.abs(Math.max(...moved) - t.actual_max_mm) > 1e-7 ||
      !Number.isFinite(t.actual_mean_mm) ||
      Math.abs(moved.reduce((sum, v) => sum + v, 0) / 64 - t.actual_mean_mm) > 1e-7 ||
      !Number.isFinite(t.target_error_max_mm) ||
      Math.abs(targetError - t.target_error_max_mm) > 1e-7 ||
      Math.abs(unchanged - t.unchanged_fraction) > 1e-10
    )
      throw new Error('偏移几何量与坐标不一致');
    if (
      t.index !== i ||
      !['completed', 'geometry_rejected'].includes(t.status) ||
      !Number.isFinite(t.actual_max_mm) ||
      t.actual_max_mm < 0 ||
      t.actual_max_mm > request.radius_mm + 1e-7 ||
      !Number.isFinite(t.unchanged_fraction) ||
      t.unchanged_fraction < 0 ||
      t.unchanged_fraction > 1
    )
      throw new Error('偏移结果无效');
    if (
      t.status === 'completed' &&
      (!Number.isFinite(t.field_relative) ||
        !Number.isFinite(t.fixed_estimator_field_relative) ||
        t.minimum_chord_distance_mm < 4 - 1e-7)
    )
      throw new Error('偏移评分或点距无效');
    if (
      t.status !== 'completed' &&
      (t.field_relative !== null || t.fixed_estimator_field_relative !== null)
    )
      throw new Error('几何失败不能携带评分');
  }
}
export class DesignEvaluationService {
  constructor(
    queue,
    { spawnProcess = spawn, timeoutMs = 600000, context } = {},
  ) {
    this.queue = queue;
    this.root = queue.root;
    this.store = queue.store ?? new RecordStore(this.root);
    this.recordKind = 'design';
    this.executionSlot = executionSlotFor(queue);
    this.spawnProcess = spawnProcess;
    this.timeoutMs = timeoutMs;
    this.contextOverride = context;
    this.inputs = new InputIntegrity(this.root);
    this.jobs = new Map();
    this.active = null;
    this.submitting = false;
    this.disposed = false;
    this.python = (queue.runtime ?? runtimeConfig({ repositoryRoot: this.root, python: queue.python })).nativePython;
  }
  async context(request) {
    if (this.contextOverride) return this.contextOverride(request);
    return scientificContext(this, request);
  }
  view(j) {
    return {
      id: j.id,
      key: j.key,
      status: j.status,
      message: j.message,
      progress: j.progress,
      result: j.result ?? null,
      cached: Boolean(j.cached),
    };
  }
  remember(j) {
    this.jobs.set(j.id, j);
    while (this.jobs.size > 20) {
      const id = [...this.jobs.keys()].find((id) => id !== this.active?.id);
      if (!id) break;
      this.jobs.delete(id);
    }
  }
  normalize(raw) { return normalizeDesignRequest(raw); }
  validate(result, request, admission) { return validateDesignResult(result, request, admission); }
  workerInput(j) { return j.request; }
  async lookup(raw, context) {
    const request = this.normalize(raw), ctx = context ?? await this.context(request);
    const directory = this.store.path(this.recordKind, ctx.key);
    try {
      const cache = await this.store.read(join(directory, 'cache.json'));
      if (cache.key !== ctx.key || hash(cache.result) !== cache.result_sha256) return { hit: false };
      this.validate(cache.result, request, ctx.admission);
      return { hit: true, job: this.view({ id: randomUUID(), key: ctx.key, request, ctx,
        status: 'completed', progress: 1, message: '设计评价已完成', result: cache.result, cached: true }) };
    } catch (e) {
      if (['EACCES', 'EPERM'].includes(e.code)) throw e;
      return { hit: false };
    }
  }
  async submit(raw) {
    if (this.disposed) throw new Error('本地服务正在重启');
    const request = this.normalize(raw);
    if (this.submitting)
      return { busy: true, error: '正在处理另一项设计评价请求' };
    this.submitting = true;
    let release;
    try {
      const ctx = await this.context(request);
      if (this.disposed) throw new Error('本地服务正在重启');
      const directory = this.store.path(this.recordKind, ctx.key);
      try {
        const cache = await this.store.read(join(directory, 'cache.json'));
        if (
          cache.key === ctx.key &&
          hash(cache.result) === cache.result_sha256
        ) {
          this.validate(cache.result, request, ctx.admission);
          const j = {
            id: randomUUID(),
            key: ctx.key,
            status: 'completed',
            progress: 1,
            message: '设计评价已完成',
            result: cache.result,
            cached: true,
          };
          this.remember(j);
          return { job: this.view(j) };
        }
      } catch (e) {
        if (['EACCES', 'EPERM'].includes(e.code)) throw e;
      }
      if (this.disposed) throw new Error('本地服务正在重启');
      if (this.active?.key === ctx.key) return { job: this.view(this.active) };
      release = this.executionSlot.acquire(this);
      if (!release) return { busy: true, maintenance: this.executionSlot.paused };
      const id = randomUUID(),
        batch = await this.store.createBatch(this.recordKind, ctx.key, id);
      await this.store.write(join(batch, 'request.json'), {
        request,
        identity: ctx.identity,
      });
      if (this.disposed) throw new Error('本地服务正在重启');
      if (this.executionSlot.paused) return { busy: true, maintenance: true };
      const j = {
        releaseExecution: release,
        id,
        key: ctx.key,
        request,
        ctx,
        batch,
        directory,
        status: 'running',
        progress: 0,
        message: '准备本地坐标评价',
        stderr: '',
        result: null,
      };
      this.active = j;
      release = null;
      this.remember(j);
      this.run(j);
      return { job: this.view(j) };
    } finally {
      release?.();
      this.submitting = false;
    }
  }
  run(j) {
    if (this.disposed) { void this.finish(j, 'cancelled', '服务重启，任务未启动'); return; }
    try {
      j.worker = startPythonWorker({
        spawnProcess: this.spawnProcess, executable: this.python,
        args: ['-u', join(this.root, this.scriptName || 'scripts/design_evaluation.py')],
        options: { cwd: this.root, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env,
          OMP_NUM_THREADS: '1', OPENBLAS_NUM_THREADS: '1', MKL_NUM_THREADS: '1', VECLIB_MAXIMUM_THREADS: '1', PYTHONDONTWRITEBYTECODE: '1' } },
        input: this.workerInput(j), timeoutMs: this.timeoutMs, maxOutputBytes: 4 * 1024 * 1024,
        onEvent: event => {
          if (event.type === 'progress' && !j.cancelReason) {
            j.progress = Math.max(j.progress, Math.min(.99, Number(event.progress) || 0));
            j.message = String(event.message);
          }
          if (event.type === 'result') j.terminal = event.result;
          if (event.type === 'error') j.workerError = String(event.message);
        },
        onStderr: text => { j.stderr = text; },
        onError: error => { j.workerError = error.message; },
        onStop: reason => { j.cancelReason = reason; j.status = 'cancelling'; j.message = '正在停止计算'; },
        onClose: code => { void this.close(j, code); },
      });
      j.child = j.worker.child;
    } catch (error) { void this.finish(j, 'failed', error.message); }
  }
  async close(j, code) {
    if (j.cancelReason)
      return this.finish(
        j,
        j.cancelReason === 'timeout' ? 'timeout' : j.cancelReason === 'input_error' ? 'failed' : 'cancelled',
        j.cancelReason === 'timeout'
          ? `达到${Math.round(this.timeoutMs / 60000)}分钟计算时限，未保存未完成结果`
          : '计算已停止',
      );
    if (code !== 0)
      return this.finish(
        j,
        'failed',
        j.workerError ?? '计算未完成，错误记录已保存',
      );
    try {
      this.validate(j.terminal, j.request, j.ctx.admission);
      if ((await this.context(j.request)).key !== j.key)
        throw new Error('计算期间输入或代码发生变化');
      j.result = j.terminal;
      await this.finish(j, 'completed', '设计评价已完成并保存');
    } catch (e) {
      await this.finish(j, 'failed', e.message);
    }
  }
  async finish(j, status, message) {
    j.status = status;
    j.message = message;
    if (status !== 'completed') j.result = null;
    try {
      if (status === 'completed') {
        j.progress = 1;
        await this.store.write(join(j.directory, 'cache.json'), {
          key: j.key,
          identity: j.ctx.identity,
          result: j.result,
          result_sha256: hash(j.result),
          finished_at: new Date().toISOString(),
        });
      }
      await this.store.write(join(j.batch, 'job.json'), {
        ...this.view(j),
        stderr: j.stderr,
      });
    } catch (e) {
      j.status = 'failed';
      j.result = null;
      j.message = '结果保存失败：' + e.message;
    } finally {
      if (this.active === j) this.active = null;
      j.releaseExecution?.(); j.releaseExecution = null;
    }
  }
  cancel(id, reason = 'user') {
    const j = this.jobs.get(id);
    if (!j || !['running', 'cancelling'].includes(j.status)) return;
    if (j.cancelReason) return;
    j.worker?.stop(reason);
  }
  dispose() {
    this.disposed = true;
    if (this.active) this.cancel(this.active.id, 'restart');
  }
  async handle(req, res, path, send) {
    if (req.method === 'POST' && path === '/api/design-evaluation/jobs') {
      if (!String(req.headers['content-type']).startsWith('application/json'))
        return send(res, 415, { error: '须提交JSON配置' });
      let body = '';
      for await (const c of req) {
        body += c.toString();
        if (Buffer.byteLength(body) > 65536)
          return send(res, 413, { error: '配置超过64 KB' });
      }
      let request;
      try {
        request = normalizeDesignRequest(JSON.parse(body));
      } catch (e) {
        return send(res, 400, { error: e.message });
      }
      const v = await this.submit(request);
      return send(res, v.busy ? 409 : 202, v);
    }
    const match = path.match(
      /^\/api\/design-evaluation\/jobs\/([a-f0-9-]{36})(\/cancel)?$/,
    );
    if (match) {
      const j = this.jobs.get(match[1]);
      if (!j)
        return send(res, 404, {
          error: '任务不存在，重新提交同一配置可读取缓存',
        });
      if (req.method === 'GET' && !match[2])
        return send(res, 200, { job: this.view(j) });
      if (req.method === 'POST' && match[2]) {
        this.cancel(j.id);
        return send(res, 202, { job: this.view(j) });
      }
    }
    return send(res, 404, { error: '未知设计评价接口' });
  }
}
