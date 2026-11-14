import { createHash } from 'node:crypto';
import { readFile, readdir } from 'node:fs/promises';
import { dirname, join, relative } from 'node:path';
import { DESIGN_WORKFLOW, NATIVE_RUNTIME_RELATIVE } from '../project-paths.mjs';

const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');

/** Shared frozen-model identity; preserve file order and serialized cache keys. */
export async function scientificContext({ root, python, inputs }, request) {
  const pointerFile = 'results/v2/current_multiregion_bank.json';
  const p = JSON.parse(await readFile(join(root, pointerFile), 'utf8'));
  const admissionFile = 'results/v2/current_surface_admissibility.json';
  const admission = JSON.parse(await readFile(join(root, admissionFile), 'utf8'));
  const config = JSON.parse(
    await readFile(
      join(root, 'configs/ernie_fem_point_pilot.json'),
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
    await readFile(join(root, manifestPath), 'utf8'),
  );
  const scalp = dirname(config.external_node_mapping_path);
  files.push(
    manifestPath,
    manifest.source_inputs,
    join(scalp, 'external_scalp_vertices_m.npy'),
    join(scalp, 'external_scalp_triangles.npy'),
  );
  const runtimeRoot = NATIVE_RUNTIME_RELATIVE;
  if (python === join(root, runtimeRoot, 'bin/python')) {
    files.push(relative(root, python));
    const metadata = join(runtimeRoot, 'conda-meta');
    for (const name of (await readdir(join(root, metadata)))
      .filter((n) => n.endsWith('.json'))
      .sort())
      files.push(join(metadata, name));
    const site = join(runtimeRoot, 'lib/python3.11/site-packages');
    for (const name of (await readdir(join(root, site)))
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
      files.map(async (p) => [p, await inputs.digest(p)]),
    ),
  );
  if (digests[p.path] !== p.sha256) throw new Error('前向库身份不匹配');
  const report = JSON.parse(
    await readFile(join(root, p.report), 'utf8'),
  );
  if (digests[p.candidates] !== report.candidate_sha256)
    throw new Error('候选坐标身份不匹配');
  if (digests[admission.path] !== admission.sha256 || admission.geometry_sha256 !== report.candidate_sha256) throw new Error('外部表面筛选文件身份不匹配');
  const identity = {
    schema: 'design-evaluation-cache/1',
    digests,
    python: python,
    threads: 1,
  };
  return { identity, admission, key: hash({ request, identity }) };
}
