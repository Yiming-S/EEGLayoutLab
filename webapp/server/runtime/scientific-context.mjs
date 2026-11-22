import { createHash } from 'node:crypto';
import { readFile, readdir } from 'node:fs/promises';
import { dirname, join, relative } from 'node:path';
import { DESIGN_WORKFLOW, NATIVE_RUNTIME_RELATIVE, TABLE_RUNTIME_RELATIVE } from '../project-paths.mjs';
import { runtimeIdentity } from './python-fingerprint.mjs';

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
    'src/compact_eeg/noise_models.py',
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
  // A published scalp-node table replaces per-request FEM for new coordinates;
  // its pointer, manifest, index and full row bytes enter the identity.
  const tablePointerFile = 'results/v2/current_scalp_node_table.json';
  let table = null;
  try {
    table = JSON.parse(await readFile(join(root, tablePointerFile), 'utf8'));
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  if (table) {
    const directory = dirname(table.manifest_path);
    files.push(tablePointerFile, table.manifest_path, join(directory, 'index.npz'), join(directory, 'rows.npy'));
  }
  // A conductivity scenario adds its definition and its own published table.
  let scenarioTable = null;
  if (request?.conductivity_scenario) {
    if (!/^[a-z0-9]+(?:[_.][a-z0-9]+)*$/.test(request.conductivity_scenario)) throw new Error('电导率情景名称无效');
    // The worker checks scenario rows against the nominal table; without it, new coordinates would solve FEM first and fail after.
    if (!table) throw new Error('电导率情景评价需要名义头皮节点表，用于核对同一电极采样。');
    const scenarioPointer = `results/v2/scalp_node_table_scenarios/${request.conductivity_scenario}/current.json`;
    try {
      scenarioTable = JSON.parse(await readFile(join(root, scenarioPointer), 'utf8'));
    } catch (error) {
      if (error.code === 'ENOENT') throw new Error('该电导率情景的头皮节点表尚未预计算');
      throw error;
    }
    const directory = dirname(scenarioTable.manifest_path);
    files.push('configs/conductivity_scenarios.json', scenarioPointer, scenarioTable.manifest_path,
      join(directory, 'index.npz'), join(directory, 'rows.npy'));
  }
  // An additional head adds its package files and its own table only when requested.
  let headTable = null;
  if (request?.head_id) {
    if (!/^[a-z0-9]+(?:[_-][a-z0-9]+)*$/.test(request.head_id)) throw new Error('头模编号无效');
    const head = `results/v2/heads/${request.head_id}`;
    try {
      headTable = JSON.parse(await readFile(join(root, head, 'table.json'), 'utf8'));
    } catch (error) {
      if (error.code === 'ENOENT') throw new Error('该头模或其头皮节点表尚未预计算');
      throw error;
    }
    const directory = dirname(headTable.manifest_path);
    files.push(...['package.json', 'scalp.npz', 'admissibility.npz', 'sources.npz', 'mapping.npz', 'table.json'].map(name => `${head}/${name}`),
      headTable.manifest_path, join(directory, 'index.npz'), join(directory, 'rows.npy'));
  }
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
  } else if (python === join(root, TABLE_RUNTIME_RELATIVE, 'bin/python')) {
    // The Linux table runtime has no SimNIBS; its conda records and the projection packages identify it.
    files.push(relative(root, python));
    const metadata = join(TABLE_RUNTIME_RELATIVE, 'conda-meta');
    for (const name of (await readdir(join(root, metadata))).filter((n) => n.endsWith('.json')).sort())
      files.push(join(metadata, name));
    const site = join(TABLE_RUNTIME_RELATIVE, 'lib/python3.11/site-packages');
    for (const name of (await readdir(join(root, site)))
      .filter((n) => /^(cortech|llvmlite|nibabel|numba|numpy|scipy)-.*\.dist-info$/.test(n))
      .sort())
      files.push(join(site, name, 'METADATA'));
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
  if (table && digests[table.manifest_path] !== table.manifest_sha256) throw new Error('预计算头皮节点表身份不匹配');
  if (scenarioTable && digests[scenarioTable.manifest_path] !== scenarioTable.manifest_sha256) throw new Error('电导率情景头皮节点表身份不匹配');
  if (headTable && digests[headTable.manifest_path] !== headTable.manifest_sha256) throw new Error('头模头皮节点表身份不匹配');
  const runtime = runtimeIdentity(python);
  const identity = {
    schema: 'design-evaluation-cache/1',
    digests,
    python: python,
    threads: 1,
    ...(runtime ? { runtime } : {}),
  };
  return { identity, admission, key: hash({ request, identity }) };
}
