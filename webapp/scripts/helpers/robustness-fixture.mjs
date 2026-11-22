import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { createHash } from 'node:crypto';

/** A robustness block shaped like the worker's (src/compact_eeg/workflows/design_robustness.py), for contract tests. */
export const stats = (median, count) => ({ median, p10: median - 1e-3, minimum: median - 2e-3, count });
const side = (completed, rejected) => completed
  ? { completed, rejected, fixed_estimator: stats(.99, completed), redigitized: stats(.999, completed), displacement_rms_mm: 5.6 }
  : { completed, rejected, fixed_estimator: null, redigitized: null, displacement_rms_mm: null };
/** The block the worker returns (src/compact_eeg/workflows/design_robustness.py). */
export function robustnessBlock({ table = true } = {}) {
  return { protocol: 'standard/1', snr_db: 20,
    dropout: { single: { candidate: Array.from({ length: 64 }, (_, i) => .999 - i * 1e-6), reference: stats(.9996, 64) },
      random: [2, 4, 8].map((removed, i) => ({ removed, draws: 32, candidate: stats(.999 - i * 1e-3, 32), reference: stats(.9993 - i * 1e-3, 32) })) },
    impedance: [.5, 1].map((log_sd, i) => ({ log_sd, draws: 32, candidate: stats(.999 - i * 2e-3, 32), reference: stats(.9991 - i * 2e-3, 32) })),
    replacement: table
      ? { status: 'completed', centre_mm: [0, -10, 40], jitter_mm: 2, table_id: 't'.repeat(64),
          levels: [5, 10].map((rms_mm, i) => ({ rms_mm, trials: 16, rotation_deg: 3.6 * (i + 1), candidate: side(15, 1), reference: i ? side(0, 16) : side(16, 0) })) }
      : { status: 'unavailable', reason: '重新佩戴试验需要预计算头皮节点表，本安装没有。' } };
}

/** A scientific root with placeholder files for every input of a design-evaluation context identity. */
export async function designContextRoot(prefix) {
  const root = await mkdtemp(join(tmpdir(), prefix));
  const digest = x => createHash('sha256').update(x).digest('hex');
  const pointer = { path: 'results/v2/bank/runs/r/batches/b/bank.npz', candidates: 'data/candidates.npz', report: 'data/report.json', sha256: digest('bank') };
  const files = {
    'results/v2/current_multiregion_bank.json': JSON.stringify(pointer),
    'results/v2/current_surface_admissibility.json': JSON.stringify({ path: 'data/admission.npz', sha256: digest('mask'), geometry_sha256: digest('candidates'), schema_version: 'native-external-exposure/1' }),
    'data/admission.npz': 'mask', [pointer.path]: 'bank', [pointer.candidates]: 'candidates', [pointer.report]: JSON.stringify({ candidate_sha256: digest('candidates') }),
    'results/v2/bank/runs/r/run_manifest.json': JSON.stringify({ source_inputs: 'data/sources.npz' }),
    'configs/ernie_fem_point_pilot.json': JSON.stringify({ mesh_path: 'data/head.msh', external_node_mapping_path: 'data/scalp/mapping.npy' }),
    'data/head.msh': 'mesh', 'data/scalp/mapping.npy': 'mapping', 'data/scalp/external_scalp_vertices_m.npy': 'vertices',
    'data/scalp/external_scalp_triangles.npy': 'triangles', 'data/sources.npz': 'sources',
    'webapp/public/models/ernie/source-roi.json': 'atlas',
  };
  for (const file of ['__init__', 'paths', 'design_evaluation', 'head_model', 'reception_forward_provider', 'shared_native_forward', 'scalp_node_table', 'head_package',
    'design_robustness', 'data_prior', 'eeg_recording'])
    files[`src/compact_eeg/workflows/${file}.py`] = 'code';
  for (const file of ['scripts/design_evaluation.py', 'scripts/inspect_ernie_cortical_forward.py', 'src/compact_eeg/cortical_fem.py', 'src/compact_eeg/surface_admissibility.py',
    'src/compact_eeg/layout_search_metrics.py', 'src/compact_eeg/noise_models.py', 'src/compact_eeg/metrics.py', 'src/compact_eeg/prototype_localization.py', 'src/compact_eeg/inverse_pilot.py'])
    files[file] = 'code';
  for (const [path, body] of Object.entries(files)) {
    await mkdir(dirname(join(root, path)), { recursive: true });
    await writeFile(join(root, path), body);
  }
  return root;
}
