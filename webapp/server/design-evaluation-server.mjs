import { nativePythonPath, NATIVE_RUNTIME_RELATIVE, DESIGN_WORKFLOW } from './project-paths.mjs';
/** On-device only. Independent result namespace, one shared physical worker slot. */
import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { readFile, mkdir, writeFile, rename, readdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { join, dirname, relative } from 'node:path';
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
async function atomic(path, value) {
  const temp = `${path}.${randomUUID()}.tmp`;
  await writeFile(temp, JSON.stringify(value), { flag: 'wx' });
  await rename(temp, path);
}

export class DesignEvaluationService {
  constructor(
    queue,
    { spawnProcess = spawn, timeoutMs = 600000, context } = {},
  ) {
    this.queue = queue;
    this.root = queue.root;
    this.spawnProcess = spawnProcess;
    this.timeoutMs = timeoutMs;
    this.contextOverride = context;
    this.inputs = new InputIntegrity(this.root);
    this.jobs = new Map();
    this.active = null;
    this.submitting = false;
    this.disposed = false;
    this.python = existsSync(
      nativePythonPath(this.root),
    )
      ? nativePythonPath(this.root)
      : queue.python;
  }
  async context(request) {
    if (this.contextOverride) return this.contextOverride(request);
    const pointerFile = 'results/v2/current_multiregion_bank.json';
    const p = JSON.parse(await readFile(join(this.root, pointerFile), 'utf8'));
    const admissionFile = 'results/v2/current_surface_admissibility.json';
    const admission = JSON.parse(await readFile(join(this.root, admissionFile), 'utf8'));
    const config = JSON.parse(
      await readFile(
        join(this.root, 'configs/ernie_fem_point_pilot.json'),
        'utf8',
      ),
    );
    const files = [
      ...DESIGN_WORKFLOW,
      pointerFile,
      p.path,
      p.candidates,
      p.report,
      admissionFile, admission.path, 'src/compact_eeg/surface_admissibility.py',
      'scripts/design_evaluation.py',
      'scripts/inspect_ernie_cortical_forward.py',
      'src/compact_eeg/cortical_fem.py',
      'src/compact_eeg/layout_search_metrics.py',
      'src/compact_eeg/metrics.py',
      'src/compact_eeg/prototype_localization.py',
      'src/compact_eeg/inverse_pilot.py',
      'configs/ernie_fem_point_pilot.json',
      config.mesh_path,
      config.external_node_mapping_path,
    ];
    const manifestPath = join(
      dirname(dirname(dirname(p.path))),
      'run_manifest.json',
    );
    const manifest = JSON.parse(
      await readFile(join(this.root, manifestPath), 'utf8'),
    );
    const scalp = dirname(config.external_node_mapping_path);
    files.push(
      manifestPath,
      manifest.source_inputs,
      join(scalp, 'external_scalp_vertices_m.npy'),
      join(scalp, 'external_scalp_triangles.npy'),
    );
    const runtimeRoot = NATIVE_RUNTIME_RELATIVE;
    if (this.python === join(this.root, runtimeRoot, 'bin/python')) {
      files.push(relative(this.root, this.python));
      const metadata = join(runtimeRoot, 'conda-meta');
      for (const name of (await readdir(join(this.root, metadata)))
        .filter((n) => n.endsWith('.json'))
        .sort())
        files.push(join(metadata, name));
      const site = join(runtimeRoot, 'lib/python3.11/site-packages');
      for (const name of (await readdir(join(this.root, site)))
        .filter((n) => /^(simnibs|cortech|numpy|scipy)-.*\.dist-info$/.test(n))
        .sort())
        files.push(join(site, name, 'METADATA'));
      files.push(
        join(site, 'simnibs/simulation/fem.py'),
        join(site, 'simnibs/mesh_tools/mesh_io.py'),
      );
    }
    const digests = Object.fromEntries(
      await Promise.all(
        files.map(async (p) => [p, await this.inputs.digest(p)]),
      ),
    );
    if (digests[p.path] !== p.sha256) throw new Error('前向库身份不匹配');
    const report = JSON.parse(
      await readFile(join(this.root, p.report), 'utf8'),
    );
    if (digests[p.candidates] !== report.candidate_sha256)
      throw new Error('候选坐标身份不匹配');
    if (digests[admission.path] !== admission.sha256 || admission.geometry_sha256 !== report.candidate_sha256) throw new Error('外部表面筛选文件身份不匹配');
    const identity = {
      schema: 'design-evaluation-cache/1',
      digests,
      python: this.python,
      threads: 1,
    };
    return { identity, admission, key: hash({ request, identity }) };
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
  async submit(raw) {
    if (this.disposed) throw new Error('本地服务正在重启');
    const request = this.normalize(raw);
    if (this.submitting)
      return { busy: true, error: '正在处理另一项设计评价请求' };
    this.submitting = true;
    try {
      const ctx = await this.context(request);
      if (this.disposed) throw new Error('本地服务正在重启');
      const directory = join(
        this.root,
        this.directoryName || 'results/v2/design_evaluation_jobs',
        ctx.key,
      );
      try {
        const cache = JSON.parse(
          await readFile(join(directory, 'cache.json'), 'utf8'),
        );
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
      if (
        this.active ||
        this.queue.active ||
        this.queue.submitting ||
        this.queue.sources?.active ||
        this.queue.sources?.submitting ||
        (this.queue.editor !== this && (this.queue.editor?.active || this.queue.editor?.submitting)) ||
        (this.queue.designTests !== this && (this.queue.designTests?.active || this.queue.designTests?.submitting))
      )
        return {
          busy: true,
          error: '本机已有计算任务；完成后可提交。已有缓存仍可读取。',
        };
      const id = randomUUID(),
        batch = join(directory, id);
      await mkdir(batch, { recursive: true });
      await atomic(join(batch, 'request.json'), {
        request,
        identity: ctx.identity,
      });
      if (this.disposed) throw new Error('本地服务正在重启');
      const j = {
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
      this.remember(j);
      this.run(j);
      return { job: this.view(j) };
    } finally {
      this.submitting = false;
    }
  }
  run(j) {
    if (this.disposed) {
      void this.finish(j, 'cancelled', '服务重启，任务未启动');
      return;
    }
    try {
      j.child = this.spawnProcess(
        this.python,
        ['-u', join(this.root, this.scriptName || 'scripts/design_evaluation.py')],
        {
          cwd: this.root,
          shell: false,
          stdio: ['pipe', 'pipe', 'pipe'],
          env: {
            ...process.env,
            OMP_NUM_THREADS: '1',
            OPENBLAS_NUM_THREADS: '1',
            MKL_NUM_THREADS: '1',
            VECLIB_MAXIMUM_THREADS: '1',
            PYTHONDONTWRITEBYTECODE: '1',
          },
        },
      );
    } catch (e) {
      void this.finish(j, 'failed', e.message);
      return;
    }
    let buffer = '',
      bytes = 0;
    j.timer = setTimeout(() => this.cancel(j.id, 'timeout'), this.timeoutMs);
    j.child.stdout.on('data', (c) => {
      bytes += c.length;
      if (bytes > 4 * 1024 * 1024) {
        this.cancel(j.id, 'output_limit');
        return;
      }
      buffer += c.toString();
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines)
        try {
          const e = JSON.parse(line);
          if (e.type === 'progress' && !j.cancelReason) {
            j.progress = Math.max(
              j.progress,
              Math.min(0.99, Number(e.progress) || 0),
            );
            j.message = String(e.message);
          }
          if (e.type === 'result') j.terminal = e.result;
          if (e.type === 'error') j.workerError = String(e.message);
        } catch {
          /* Native solver logs are not result data. */
        }
    });
    j.child.stderr.on('data', (c) => {
      j.stderr = (j.stderr + c).slice(-16000);
    });
    j.child.stdin.on('error', () => {});
    j.child.on('error', (e) => {
      j.workerError = e.message;
    });
    j.child.once('close', (code) => {
      void this.close(j, code);
    });
    j.child.stdin.end(JSON.stringify(this.workerInput(j)));
  }
  async close(j, code) {
    clearTimeout(j.timer);
    clearTimeout(j.killTimer);
    if (j.cancelReason)
      return this.finish(
        j,
        j.cancelReason === 'timeout' ? 'timeout' : 'cancelled',
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
        await atomic(join(j.directory, 'cache.json'), {
          key: j.key,
          identity: j.ctx.identity,
          result: j.result,
          result_sha256: hash(j.result),
          finished_at: new Date().toISOString(),
        });
      }
      await atomic(join(j.batch, 'job.json'), {
        ...this.view(j),
        stderr: j.stderr,
      });
    } catch (e) {
      j.status = 'failed';
      j.result = null;
      j.message = '结果保存失败：' + e.message;
    } finally {
      if (this.active === j) this.active = null;
    }
  }
  cancel(id, reason = 'user') {
    const j = this.jobs.get(id);
    if (!j || !['running', 'cancelling'].includes(j.status)) return;
    if (j.cancelReason) return;
    j.cancelReason = reason;
    j.status = 'cancelling';
    j.message = '正在停止计算';
    j.child?.kill('SIGTERM');
    j.killTimer = setTimeout(() => j.child?.kill('SIGKILL'), 2000);
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
