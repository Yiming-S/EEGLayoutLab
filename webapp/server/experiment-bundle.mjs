/** Read-only experiment packaging. No rescoring, rekeying or invented history. */
import { createHash } from 'node:crypto';
import { readFile, realpath } from 'node:fs/promises';
import { resolve, sep } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const execute = promisify(execFile);

const sha = (b) => createHash('sha256').update(b).digest('hex');
export function describeSearch(record, raw) {
  let d = null,
    configuration = record.request;
  if (record.dataset_id === 'cache') d = raw.result?.diagnostics;
  if (record.dataset_id === 'offline_radius') {
    const entry = raw.conditions?.find(
      (c) => c.condition.id === record.provenance.condition_id,
    );
    const finalist = entry?.finalists?.find(
      (f) =>
        f.evaluation?.id === record.layout?.id &&
        f.objective === record.provenance.objective,
    );
    d = finalist?.search;
    configuration = { ...raw.config, condition: entry?.condition };
  }
  if (['strict_area', 'historical_area'].includes(record.dataset_id)) {
    const entry = raw.conditions?.find(
      (c) => c.condition.id === record.provenance.condition_id,
    );
    configuration = { ...raw.config, condition: entry?.condition };
    const finalist = entry?.finalists?.find(
      (f) => f.objective === record.provenance.objective,
    );
    d = finalist && {
      ...finalist,
      attempts: entry.attempts,
      evaluated: entry.counts,
    };
  }
  const initial = d?.initial ?? null,
    final = d?.final ?? null;
  const objective =
    record.provenance.objective ?? 'min(field20,sensitivity_tail)';
  const value = (s) =>
    s == null
      ? null
      : typeof s.objective_score === 'number'
        ? s.objective_score
        : typeof s.objective === 'number'
          ? s.objective
          : typeof s.field20 === 'number' &&
              typeof s.sensitivity_tail === 'number'
            ? Math.min(s.field20, s.sensitivity_tail)
            : null;
  const trace = d?.trace ?? [];
  const curve =
    initial && value(initial) !== null
      ? [{ step: 0, value: value(initial) }]
      : [];
  for (const [i, move] of trace.entries()) {
    const after = move.after ?? move.objective_after;
    if (Number.isFinite(after)) curve.push({ step: i + 1, value: after });
  }
  return {
    configuration,
    objective,
    initial,
    final,
    trace,
    curve,
    counters: {
      scored_layouts: d?.scored_layouts ?? d?.evaluated?.field_scores ?? null,
      coordinate_proposals:
        d?.coordinate_proposals ?? d?.evaluated?.coordinate_proposals ?? null,
      geometry_attempts:
        d?.attempts?.length ?? d?.center_attempts?.length ?? null,
    },
    original_counters: d?.evaluated_counts ?? d?.evaluated ?? null,
    history_status: d
      ? 'recorded_accepted_moves'
      : 'not_available_in_loaded_record',
    history_scope: '保存的初始化及接受步骤；未记录的被拒绝提案不补造。',
    global_optimum_certified: false,
  };
}

export async function experimentBundle(root, record, { python } = {}) {
  let relative = record.provenance?.file;
  let expected = record.provenance?.sha256;
  if (record.dataset_id === 'offline_radius') {
    const pointer = JSON.parse(
      await readFile(
        resolve(root, 'results/v2/current_single_head_optimization.json'),
      ),
    );
    expected = record.provenance.original?.report_sha256;
    if (!expected || pointer.sha256 !== expected)
      throw new Error('历史优化报告与导出身份不符');
    relative = pointer.report;
  }
  if (typeof relative !== 'string') throw new Error('原始记录未提供来源文件');
  const path = await realpath(resolve(root, relative));
  if (
    !path.startsWith(resolve(root, 'results/v2') + sep) &&
    !path.startsWith(resolve(root, 'webapp/public/data') + sep)
  )
    throw new Error('来源文件不在实验目录内');
  const bytes = await readFile(path),
    digest = sha(bytes);
  if (expected && digest !== expected) throw new Error('原始文件校验失败');
  const raw = JSON.parse(bytes);
  if (
    record.dataset_id === 'cache' &&
    (raw.key !== record.id ||
      raw.result_sha256 !== sha(JSON.stringify(raw.result)))
  )
    throw new Error('原始缓存校验失败');
  const search = describeSearch(record, raw);
  const snapshots = [search.initial, search.final].map((s, i) =>
    s
      ? {
          label: i === 0 ? '初始化' : '优化后',
          xyzMm:
            s.xyz_mm ?? s.xyz_m?.map((p) => p.map((v) => v * 1000)) ?? null,
          regionIndices: s.region_indices ?? s.region_indices64,
          referenceXyzMm: record.layout?.referenceXyzMm,
        }
      : null,
  );
  let coordinateNote = null;
  if (
    python &&
    record.dataset_id === 'cache' &&
    search.initial &&
    snapshots.some((s) => s && !s.xyzMm)
  ) {
    try {
      const indices = [search.initial, search.final].map(
        (s) => s.candidate_bank_indices,
      );
      const { stdout } = await execute(
        python,
        [
          resolve(root, 'scripts/export_history_coordinates.py'),
          '--repository-root',
          root,
          '--bank-sha256',
          record.provenance.bank_sha256,
          '--indices',
          JSON.stringify(indices),
        ],
        {
          timeout: 10000,
          maxBuffer: 1024 * 1024,
          env: {
            ...process.env,
            PYTHONDONTWRITEBYTECODE: '1',
            OPENBLAS_NUM_THREADS: '1',
            OMP_NUM_THREADS: '1',
          },
        },
      );
      const coordinates = JSON.parse(stdout);
      snapshots.forEach((s, i) => {
        if (s) s.xyzMm = coordinates.xyz_mm[i];
      });
    } catch {
      coordinateNote = '原前向库坐标未载入；原始点位索引仍保留在实验包中。';
    }
  }
  return {
    schema: 'eeg-reproducibility-bundle/1',
    record_id: record.id,
    record,
    source: { path: relative, sha256: digest },
    search,
    snapshots,
    coordinate_note: coordinateNote,
    original_record: raw,
    reproduction: {
      scope: '原始输入与轨迹归档；运行需要对应代码版本、头模和前向矩阵。',
      request: record.request,
      identity: raw.identity ?? raw.provenance ?? record.provenance,
      entrypoint:
        record.dataset_id === 'cache'
          ? 'scripts/run_local_radius_compute.py'
          : record.dataset_id === 'strict_area'
            ? 'scripts/run_area_budget_study.py'
            : 'see original_record provenance and run manifest',
      metrics_recomputed: false,
      ar_changes_recompute: false,
    },
  };
}
