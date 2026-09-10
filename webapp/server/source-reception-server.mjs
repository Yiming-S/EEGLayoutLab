import { RECEPTION_WORKFLOW } from './project-paths.mjs';
/** Local-only, bounded time-series experiments. Never changes the layout cache. */
import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { readFile, mkdir, rename, writeFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { InputIntegrity } from './local-input-integrity.mjs';
import { normalizeReceptionRequest, validateReceptionResult, receptionV2Context, receptionLayouts, sourceCatalog } from './reception-v2-support.mjs';

export const SOURCE_REGIONS = [
  'frontal',
  'central',
  'parietal',
  'occipital',
  'temporal_left',
  'temporal_right',
];
const TYPES = ['clean', 'ecg', 'eog', 'mixed'];
const SCALES = [0, 0.5, 1, 2, 4];
const hash = (x) =>
  createHash('sha256')
    .update(typeof x === 'string' ? x : JSON.stringify(x))
    .digest('hex');
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
export function normalizeSourceRequest(x) {
  if (
    !x ||
    Array.isArray(x) ||
    typeof x !== 'object' ||
    Object.keys(x).some(
      (k) =>
        ![
          'record_id',
          'brain_region',
          'waveform',
          'artifact_scale',
          'seed',
        ].includes(k),
    )
  )
    throw new Error('源实验配置字段无效');
  if (
    typeof x.record_id !== 'string' || !/^[a-f0-9]{64}$/.test(x.record_id) ||
    !SOURCE_REGIONS.includes(x.brain_region) ||
    !['burst', 'rhythm'].includes(x.waveform) ||
    !SCALES.includes(x.artifact_scale) ||
    !Number.isInteger(x.seed) ||
    x.seed < 0 ||
    x.seed > 9999
  )
    throw new Error('请选择已有完整布局、支持的源区与波形；种子范围0–9999');
  return {
    record_id: x.record_id,
    brain_region: x.brain_region,
    waveform: x.waveform,
    artifact_scale: x.artifact_scale,
    seed: x.seed,
  };
}
export function validateSourceResult(result, request, record) {
  if (
    result?.status !== 'completed' ||
    result.schema_version !== 'source-reception/1' ||
    !equal(normalizeSourceRequest(result.request), request)
  )
    throw new Error('源实验结果身份不一致');
  if (
    !equal(result.layout?.xyzMm, record.layout.xyzMm) ||
    !equal(result.layout?.regionIndices, record.layout.regionIndices) ||
    !equal(result.layout?.referenceXyzMm, record.layout.referenceXyzMm)
  )
    throw new Error('源实验替换了冻结点位');
  const wave = result.waveforms,
    n = wave?.time_s?.length;
  if (
    n !== 400 ||
    !wave.time_s.every(Number.isFinite) ||
    wave.time_s.some((t, i) => i && t <= wave.time_s[i - 1])
  )
    throw new Error('时间轴无效');
  for (const side of ['baseline', 'candidate'])
    for (const key of [
      'brain_uv',
      'ecg_uv',
      'eog_uv',
      'noise_uv',
      'reconstructed_brain_uv',
      'reconstructed_ecg_uv',
      'reconstructed_eog_uv',
      'reconstructed_noise_uv',
    ]) {
      const a = wave[side]?.[key];
      if (
        !Array.isArray(a) ||
        a.length !== 64 ||
        a.some(
          (row) =>
            !Array.isArray(row) ||
            row.length !== n ||
            !row.every(Number.isFinite),
        )
      )
        throw new Error('64通道波形无效');
    }
  if (
    !Array.isArray(result.conditions) ||
    result.conditions.length !== 4 ||
    new Set(result.conditions.map((c) => c.condition)).size !== 4 ||
    !Array.isArray(result.strength_curve) ||
    result.strength_curve.length !== 16
  )
    throw new Error('缺少对照条件');
  const combinations = [
    'clean:0',
    ...['ecg', 'eog', 'mixed'].flatMap((c) => SCALES.map((s) => `${c}:${s}`)),
  ].sort();
  if (
    !equal(
      result.strength_curve
        .map((c) => `${c.condition}:${c.artifact_scale}`)
        .sort(),
      combinations,
    )
  )
    throw new Error('干扰曲线点重复或缺失');
  if (
    result.conditions.some(
      (c) =>
        c.artifact_scale !==
        (c.condition === 'clean' ? 0 : request.artifact_scale),
    )
  )
    throw new Error('条件强度与请求不符');
  for (const c of [...result.conditions, ...result.strength_curve]) {
    if (!TYPES.includes(c.condition) || !SCALES.includes(c.artifact_scale))
      throw new Error('干扰条件无效');
    for (const side of ['baseline', 'candidate']) {
      const m = c[side];
      if (
        !m ||
        !Number.isFinite(m.nmse) ||
        m.nmse < 0 ||
        !Number.isFinite(m.explained_energy) ||
        Math.abs(m.explained_energy - (1 - m.nmse)) > 1e-8 ||
        (m.brain_artifact_ratio_db !== null &&
          !Number.isFinite(m.brain_artifact_ratio_db))
      )
        throw new Error('重建指标无效');
    }
    const expected =
      c.baseline.explained_energy > 1e-8
        ? c.candidate.explained_energy / c.baseline.explained_energy
        : null;
    if (
      expected === null
        ? c.field_retention !== null
        : !Number.isFinite(c.field_retention) ||
          Math.abs(expected - c.field_retention) >
            1e-8 * Math.max(1, Math.abs(expected))
    )
      throw new Error('AR相对保留率无效');
  }
  if (
    !result.source?.xyz_mm?.length ||
    result.source.xyz_mm.some(
      (x) => x.length !== 3 || !x.every(Number.isFinite),
    )
  )
    throw new Error('缺少实际源坐标');
}
async function atomic(path, data) {
  const temp = `${path}.${randomUUID()}.tmp`;
  await writeFile(temp, JSON.stringify(data), { flag: 'wx' });
  await rename(temp, path);
}

export class SourceReceptionService {
  constructor(
    queue,
    { spawnProcess = spawn, timeoutMs = 120000, getContext } = {},
  ) {
    this.queue = queue;
    this.root = queue.root;
    this.spawnProcess = spawnProcess;
    this.timeoutMs = timeoutMs;
    this.jobs = new Map();
    this.active = null;
    this.submitting = false;
    this.disposed = false;
    this.inputs = new InputIntegrity(this.root);
    this.customContext = getContext;
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
      const path = join(
        this.root,
        request.mode ? 'results/v2/source_reception_v2_jobs' : 'results/v2/source_reception_jobs',
        ctx.key,
        'cache.json',
      );
      if ((await stat(path)).size > 32 * 1024 * 1024)
        throw new Error('结果记录过大');
      const cache = JSON.parse(await readFile(path, 'utf8'));
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
    try {
      const ctx = await this.context(request),
        cached = await this.lookup(request, ctx);
      if (cached.hit) return { job: cached.job };
      if (this.disposed) throw new Error('本地服务正在重启');
      if (this.active?.key === ctx.key) return { job: this.view(this.active) };
      if (this.active || this.queue.active || this.queue.submitting || this.queue.designTests?.active || this.queue.designTests?.submitting || this.queue.editor?.active || this.queue.editor?.submitting)
        return {
          busy: true,
          error: '本机正在运行另一项计算，请完成后再提交。已有结果仍可读取。',
        };
      const id = randomUUID(),
        directory = join(
          this.root,
          request.mode ? 'results/v2/source_reception_v2_jobs' : 'results/v2/source_reception_jobs',
          ctx.key,
        ),
        batch = join(directory, id);
      await mkdir(batch, { recursive: true });
      await atomic(join(batch, 'request.json'), {
        request,
        record: ctx.record,
      });
      if (this.disposed) throw new Error('本地服务正在重启');
      const job = {
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
      this.remember(job);
      this.run(job);
      return { job: this.view(job) };
    } finally {
      this.submitting = false;
    }
  }
  run(job) {
    try {
      job.child = this.spawnProcess(
        job.request.mode ? this.queue.designTests.python : this.queue.python,
        [
          '-u',
          join(this.root, job.request.mode ? 'scripts/run_source_reception_v2.py' : 'scripts/run_source_reception.py'),
          '--repository-root',
          this.root,
          '--request',
          join(job.batch, 'request.json'),
          '--output',
          join(job.batch, 'result.json'),
        ],
        {
          cwd: this.root,
          shell: false,
          stdio: ['ignore', 'pipe', 'pipe'],
          env: {
            ...process.env,
            OMP_NUM_THREADS: job.request.mode ? '1' : '2',
            OPENBLAS_NUM_THREADS: job.request.mode ? '1' : '2',
            MKL_NUM_THREADS: job.request.mode ? '1' : '2',
            VECLIB_MAXIMUM_THREADS: job.request.mode ? '1' : '2',
            PYTHONDONTWRITEBYTECODE: '1',
          },
        },
      );
    } catch (e) {
      void this.finish(job, 'failed', `无法启动计算：${e.message}`);
      return;
    }
    let buffer = '',
      bytes = 0;
    job.timer = setTimeout(
      () => this.cancel(job.id, 'timeout'),
      job.request.mode ? Math.max(this.timeoutMs, 600000) : this.timeoutMs,
    );
    job.child.stdout.on('data', (chunk) => {
      bytes += chunk.length;
      if (bytes > 1024 * 1024) {
        this.cancel(job.id, 'output_limit');
        return;
      }
      buffer += chunk.toString();
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        try {
          const e = JSON.parse(line);
          if (e.type === 'progress' && !job.cancelReason) {
            job.progress = Math.max(
              job.progress,
              Math.min(0.99, Number(e.progress) || 0),
            );
            job.message = String(e.message ?? '正在计算源—接收对照');
          }
          if (e.type === 'error')
            job.stderr = (
              job.stderr + String(e.message ?? 'worker error')
            ).slice(-16000);
        } catch {
          /* Non-JSON diagnostic output is not a result. */
        }
      }
    });
    job.child.stderr.on('data', (c) => {
      job.stderr = (job.stderr + c).slice(-16000);
    });
    job.child.on('error', (e) => {
      job.stderr += e.message;
    });
    job.child.once('close', (code) => {
      void this.close(job, code);
    });
  }
  async close(job, code) {
    clearTimeout(job.timer);
    clearTimeout(job.killTimer);
    if (job.cancelReason)
      return this.finish(
        job,
        job.cancelReason === 'timeout' ? 'timeout' : 'cancelled',
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
        await atomic(join(job.directory, 'cache.json'), {
          key: job.key,
          ...(job.request.mode ? { identity: job.ctx.identity } : {}),
          result: job.result,
          result_sha256: hash(job.result),
          finished_at: job.finished_at,
        });
        job.progress = 1;
      }
      await atomic(join(job.batch, 'job.json'), {
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
    }
  }
  cancel(id, reason = 'user') {
    const job = this.jobs.get(id);
    if (!job || !['running', 'cancelling'].includes(job.status)) return false;
    if (job.cancelReason) return true;
    job.cancelReason = reason;
    job.status = 'cancelling';
    job.message = '正在停止源实验';
    job.child?.kill('SIGTERM');
    job.killTimer = setTimeout(() => job.child?.kill('SIGKILL'), 2000);
    return true;
  }
  dispose() {
    this.disposed = true;
    if (this.active) this.cancel(this.active.id, 'restart');
  }
  async handle(req, res, path, send) {
    if (req.method === 'GET' && path === '/api/source-reception/layouts') return send(res, 200, await receptionLayouts(this.queue));
    if (req.method === 'GET' && path === '/api/source-reception/catalog') {
      this.catalogPromise ??= sourceCatalog(this.queue).finally(() => { this.catalogPromise = null; });
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
