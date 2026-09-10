#!/usr/bin/env python3
"""Local fixed-coordinate evaluation and finite-bank displacement diagnostics.

No optimization or anatomy registration is performed. New surface coordinates
use native FEM; candidate bank perturbations use exact cached FEM rows. The
unchanged reference defines the target and the physical noise scale throughout.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import time

for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[key] = '1'
sys.dont_write_bytecode = True
from .paths import PROJECT_ROOT as ROOT
import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import cdist, pdist
from threadpoolctl import threadpool_limits, threadpool_info
from compact_eeg.artifacts import sha256_file
from compact_eeg.layout_search_metrics import LayoutSearchMetrics
from compact_eeg.metrics import helmert_contrast
from compact_eeg.prototype_localization import evaluate_grid_localization
from compact_eeg.surface_admissibility import load_admissibility


def validate_request(raw):
    if not isinstance(raw, dict) or set(raw) != {'action', 'design', 'radius_mm', 'seed'}:
        raise ValueError('Invalid design evaluation fields')
    d = raw['design']
    if not isinstance(d, dict) or d.get('schema') != 'eeg-electrode-design/1' or d.get('coordinate_system') != 'ernie_native_mm' or d.get('unit') != 'mm':
        raise ValueError('Requires Ernie native millimetre coordinates')
    xyz = np.asarray(d.get('xyz_mm'), dtype=float)
    labels = np.asarray(d.get('region_indices'))
    if xyz.shape != (64, 3) or not np.all(np.isfinite(xyz)) or np.max(np.abs(xyz)) > 500 or len(np.unique(xyz, axis=0)) != 64:
        raise ValueError('Requires 64 distinct finite electrode coordinates')
    if labels.shape != (64,) or labels.dtype.kind not in 'iu' or len(np.unique(labels)) not in (1, 2, 3, 4, 6):
        raise ValueError('Invalid region labels')
    r = len(np.unique(labels))
    if not np.array_equal(np.unique(labels), np.arange(r)) or sorted(np.bincount(labels), reverse=True) != [64 // r + int(i < 64 % r) for i in range(r)]:
        raise ValueError('Region allocation must be balanced and zero-based')
    if raw['action'] not in ('evaluate', 'perturb') or type(raw['radius_mm']) is not int or raw['radius_mm'] not in (3, 6, 10) or type(raw['seed']) is not int or not 0 <= raw['seed'] <= 9999:
        raise ValueError('Unsupported evaluation action, displacement or seed')
    if float(pdist(xyz).min()) < 4 - 1e-7:
        raise ValueError('最小直线点距需达到4 mm；请修改坐标后计算。')
    return raw


def fixed_estimator_retention(nominal, observed, reference, weights, snr_db=20):
    """Expected clean-target energy explained using a frozen nominal LMMSE."""
    c = helmert_contrast(64)
    w = np.asarray(weights, float) / np.sum(weights)
    t, a, b = (c @ x for x in (reference, nominal, observed))
    scale = np.sqrt(np.sum(t * t * w) / 63)
    t, a, b = t / scale, a / scale, b / scale
    noise = 10. ** (-snr_db / 10)
    def estimator(h):
        covariance = (h * w) @ h.T + noise * np.eye(63)
        return cho_solve(cho_factor(covariance, lower=True), ((t * w) @ h.T).T).T
    def explained(transform, h):
        residual = t - transform @ h
        error = np.sum(residual * residual * w) + noise * np.sum(transform * transform)
        return float(1 - error / np.sum(t * t * w))
    baseline = explained(estimator(t), t)
    return explained(estimator(a), b) / baseline


def displaced_indices(xyz, labels, bank_xyz, radius, rng, allowed=None):
    """One global distinct-node assignment; no performance-based resampling."""
    directions = rng.normal(size=(int(max(labels)) + 1, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    target = xyz + radius * directions[labels]
    actual = cdist(xyz, bank_xyz)
    target_cost = cdist(target, bank_xyz)
    cost = np.where(actual <= radius + 1e-7, target_cost ** 2, 1e15)
    if allowed is not None:
        cost[:, ~np.asarray(allowed, bool)] = 1e15
    row, chosen = linear_sum_assignment(cost)
    if len(row) != 64 or np.any(cost[row, chosen] >= 1e15):
        raise ValueError('No distinct bank assignment within displacement cap')
    moved = bank_xyz[chosen]
    distance = np.linalg.norm(moved - xyz, axis=1)
    return chosen, {
        'actual_max_mm': float(distance.max()), 'actual_mean_mm': float(distance.mean()),
        'target_error_max_mm': float(np.linalg.norm(moved - target, axis=1).max()),
        'unchanged_fraction': float(np.mean(distance <= 1e-7)),
        'minimum_chord_distance_mm': float(pdist(moved).min()),
        'xyz_mm': moved.tolist(), 'requested_xyz_mm': target.tolist(),
        'candidate_bank_indices': chosen.tolist(), 'region_indices': labels.tolist(),
    }


def load_bank(root):
    pp = root / 'results/v2/current_multiregion_bank.json'
    p = json.loads(pp.read_text())
    report = json.loads((root / p['report']).read_text())
    if sha256_file(root / p['path']) != p['sha256'] or sha256_file(root / p['candidates']) != report['candidate_sha256']:
        raise ValueError('Forward bank integrity mismatch')
    with np.load(root / p['path'], allow_pickle=False) as bank:
        data = {k: bank[k] for k in bank.files}
    eligible, admission = load_admissibility(root, report['candidate_sha256'])
    with np.load(root / p['candidates'], allow_pickle=False) as g:
        if len(eligible) != len(g['surface_vertices_m']):
            raise ValueError('Exposure mask vertex indexing mismatch')
        data['_surface_vertices_mm'] = g['surface_vertices_m'] * 1000
        data['_surface_faces'] = g['surface_triangles']
        data['_allowed_bank'] = eligible[g['candidate_vertex_indices']]
    data['_eligible_surface'] = eligible
    data['_admission'] = admission
    return data, p, report


def native_field(root, points, data, pointer, bank_report, progress):
    """Direct FEM for all requested points, no montage interpolation."""
    import cortech
    from compact_eeg.cortical_fem import FixedMeshLeadfield
    # This loader enforces the frozen head mesh, mapping and conductivity hashes.
    from .head_model import load_head
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
        os.environ[key] = '1'
    progress(.12, '读取Ernie体积网格，检查坐标到表面的投影')
    mesh, cond, vertices, faces, mapping, head_hashes = load_head(root)
    if not np.array_equal(faces, data['_surface_faces']) or not np.allclose(vertices, data['_surface_vertices_mm'], rtol=0, atol=1e-9):
        raise ValueError('Native and screened surface indexing differ')
    projection_surface = cortech.Surface(vertices, faces)
    triangles, weights, projected, _ = projection_surface.project_points(points, pttris=20)
    if not np.all(data['_eligible_surface'][faces[triangles]]):
        raise ValueError('坐标投影位于外部曝光筛选未通过的面片；请修改该电极位置后重新评价。')
    distances = np.linalg.norm(points - projected, axis=1)
    if distances.max() > 2:
        raise ValueError(f'坐标距Ernie表面最大{distances.max():.2f} mm，超过2 mm。请先完成配准。')
    if pdist(projected).min() < 4 - 1e-7:
        raise ValueError('表面投影后的电极点距小于4 mm。')
    manifest = json.loads((root / pointer['path']).parents[2].joinpath('run_manifest.json').read_text())
    if head_hashes != manifest['identity']['head_hashes']:
        raise ValueError('新位置FEM头模与参照前向库不一致；需先统一头模和参照库。')
    source_path = root / manifest['source_inputs']
    if sha256_file(source_path) != bank_report['source_input_sha256']:
        raise ValueError('Native source input identity mismatch')
    with np.load(source_path, allow_pickle=False) as s:
        sources = np.vstack([s['source_xyz_mm'], s['generation_xyz_mm']])
        normals = np.vstack([s['source_normals'], s['generation_normals']])
    if not np.array_equal(sources, np.vstack([data['source_xyz_mm'], data['generation_xyz_mm']])):
        raise ValueError('Native sources and existing bank differ')
    def advance(stage, **values):
        if stage == 'cortical_fem_electrode_block_complete':
            progress(.35 + .45 * values['completed_electrodes'] / values['total_electrodes'], f"新位置FEM：{values['completed_electrodes']}/{values['total_electrodes']}点")
        elif stage == 'cortical_fem_factorization_start':
            progress(.3, '分解头模矩阵；本机单任务、单线程')
    model = FixedMeshLeadfield(mesh, cond, vertices, faces, mapping, sources, normals, progress=advance)
    q = model.source_qa
    if q['fallback_distance_mm']['maximum'] > 3 or q['interpolation_row_sum_max_error'] > 1e-7 or q['normal_operator_constant_field_max_abs'] > 1e-7 or q['official_operator_sample_check']['relative_frobenius_difference'] > 1e-10:
        raise ValueError('Native source interpolation QA failed')
    if np.flatnonzero(model.source_qa_arrays['containing_tissue_tag_or_minus_one'] == -1).tolist() != [698, 957, 1559, 3408]:
        raise ValueError('Native source exception list changed')
    # Recompute the reference with the same new native solve, and require it to
    # reproduce the saved reference before using any cross-layout ratio.
    projection = model.project(np.vstack([data['reference_xyz_mm'], projected]))
    if projection.distances_mm.max() > 1e-5:
        raise ValueError('Native surface re-projection moved fixed reference coordinates')
    # Apply again after SimNIBS/MUMPS imports: native libraries load lazily.
    # Nested MUMPS OpenMP + OpenBLAS OpenMP stalled with two threads on this host.
    with threadpool_limits(limits=1):
        native_threads = threadpool_info()
        if any(p['num_threads'] != 1 for p in native_threads):
            raise ValueError('Native FEM thread limit could not be enforced')
        h, qa = model.evaluate(projection, block_size=4)
    if qa['max_relative_full_system_residual'] > 1e-7 or qa['max_relative_free_dof_residual'] > 1e-7 or qa['point_transfer_reciprocity_relative_frobenius'] > 1e-8 or not np.all(np.isfinite(h)):
        raise ValueError('Native FEM residual/reciprocity QA failed')
    for key in ('net_prescribed_current_A_per_electrode', 'net_assembled_current_A_per_electrode', 'reaction_current_relative_error_per_electrode'):
        if np.max(np.abs(qa[key])) > 1e-7:
            raise ValueError('Native FEM current conservation QA failed')
    reference_difference = float(np.linalg.norm(h[:64] - data['reference_leadfield_v_per_am']) / np.linalg.norm(data['reference_leadfield_v_per_am']))
    if reference_difference > 1e-8:
        raise ValueError('新FEM参照场与前向库不一致，需统一计算版本。')
    actual = projection.projected_mm[64:]
    return h[64:], actual, float(np.linalg.norm(points - actual, axis=1).max()), {'head_hashes': head_hashes, 'reference_relative_difference': reference_difference, 'source_qa': q, 'fem_qa': qa, 'timings_seconds': model.timings, 'threadpools': native_threads}


def evaluate(raw, root=ROOT, progress=lambda *args: None):
    started = time.perf_counter()
    request = validate_request(raw)
    data, pointer, bank_report = load_bank(root)
    d = request['design']; xyz = np.asarray(d['xyz_mm']); labels = np.asarray(d['region_indices'])
    bank_xyz = data['candidate_xyz_mm']; hc = data['candidate_leadfield_v_per_am']; hb = data['reference_leadfield_v_per_am']
    n = int(data['dictionary_source_count']); weights = data['source_area_weights']
    if n != 4096 or len(data['generation_xyz_mm']) != 256:
        raise ValueError('本评价协议要求4096个字典源与256个生成源；新源协议需单独注册。')
    distances = cdist(xyz, bank_xyz); ids = distances.argmin(axis=1)
    in_bank = bool(np.all(distances[np.arange(64), ids] <= 1e-7) and len(np.unique(ids)) == 64)
    exact_reference = bool(np.allclose(xyz, data['reference_xyz_mm'], atol=1e-7, rtol=0))
    if request['action'] == 'perturb' and not in_bank:
        raise ValueError('网格偏移需要64点均存在于候选前向库。新坐标请使用“评价当前坐标”，执行FEM评价。')
    progress(.08, '核对64点坐标与前向模型')
    mode = 'cached_fem'; projected = xyz; projection_max = 0.; qa = {}
    if in_bank:
        if not np.all(data['_allowed_bank'][ids]):
            raise ValueError('该布局含未通过外部表面筛选的电极，请使用新版布局或修改坐标。')
        h = hc[ids]
        projected = bank_xyz[ids]
        projection_max = float(np.linalg.norm(projected - xyz, axis=1).max())
    elif exact_reference:
        h = hb.copy()
        projected = data['reference_xyz_mm']
        projection_max = float(np.linalg.norm(projected - xyz, axis=1).max())
    else:
        h, projected, projection_max, qa = native_field(root, xyz, data, pointer, bank_report, progress)
        mode = 'direct_fem'
    engine = LayoutSearchMetrics(h[:, :n], hb[:, :n], weights)
    own = engine.evaluate(np.arange(64), snr_db=(20,))['conditions'][0]
    sigma = np.sqrt(engine.reference_mean_contrast_signal_power_v2 * .01)
    progress(.84, '固定坐标，评价重建、幅度与定位')
    def localize(field):
        return evaluate_grid_localization(field[:, :n], field[:, n:], data['source_xyz_mm'], data['generation_xyz_mm'], source_moment_am=1e-8,
            physical_electrode_noise_std_v=sigma, noise_seed=request['seed'], layout_id='design-evaluation-paired-stream', noise_repetitions=16,
            generation_source_weights=data['generation_area_weights']).report
    ref_loc = localize(hb); loc = ref_loc if exact_reference else localize(h)
    u = ref_loc['source_lower10_utility_dmax50mm']
    nominal = {'field_relative': own['field_retention_unclipped'], 'field_absolute': own['candidate_field_explained_energy'],
        'reference_field_absolute': own['reference_field_explained_energy'], 'sensitivity_tail': engine.sensitivity_tail(np.arange(64)),
        'localization_relative': loc['source_lower10_utility_dmax50mm'] / u if u > 1e-12 else None,
        'median_mm': loc['median_error_mm'], 'p90_mm': loc['p90_error_mm'], 'reference_median_mm': ref_loc['median_error_mm'], 'reference_p90_mm': ref_loc['p90_error_mm']}
    trials = []
    if request['action'] == 'perturb':
        for i in range(4):
            progress(.87 + i * .025, f'网格位置偏移 {i + 1}/4')
            chosen, trial = displaced_indices(xyz, labels, bank_xyz, request['radius_mm'], np.random.default_rng(np.random.SeedSequence([request['seed'], i])), data['_allowed_bank'])
            trial.update(index=i, status='completed')
            if trial['minimum_chord_distance_mm'] < 4 - 1e-7:
                trial.update(status='geometry_rejected', message='偏移后点距小于4 mm', field_relative=None, fixed_estimator_field_relative=None)
            else:
                changed = hc[chosen, :n]
                changed_engine = LayoutSearchMetrics(changed, hb[:, :n], weights)
                trial['field_relative'] = changed_engine.make_state(np.arange(64)).field_relative
                trial['sensitivity_tail'] = changed_engine.sensitivity_tail(np.arange(64))
                trial['fixed_estimator_field_relative'] = fixed_estimator_retention(h[:, :n], changed, hb[:, :n], weights)
            trials.append(trial)
    return {'schema': 'design-evaluation/1', 'status': 'completed', 'request': request, 'forward_mode': mode,
        'nominal': nominal, 'projection_max_mm': projection_max, 'evaluated_xyz_mm': projected.tolist(),
        'trials': trials, 'provenance': {**data['_admission'], 'head_count': 1, 'bank_sha256': pointer['sha256'],
            'surface_point_rule': 'bank_vertex_mask; new points require all three projected face vertices; fixed standard64 reference exempt',
            'source_count': n, 'generation_count': len(data['generation_xyz_mm']), 'candidate_count': len(bank_xyz), 'noise_repetitions': 16,
            'noise_model': 'iid_equal_variance', 'nominal_reference_snr_db': 20,
            'source_prior': 'frozen_area_weights', 'estimator_training': 'known_prior_LMMSE',
            'reference_perturbed': False, 'regional_boundary_requalified': False, 'independent_head_validation': False,
            'paired_localization_noise': True, 'thread_limit': 1, 'seed': request['seed'],
            'code_sha256': sha256_file(Path(__file__)), 'numpy': np.__version__, 'python': sys.version},
        'native_qa': qa, 'elapsed_seconds': time.perf_counter() - started}


def main():
    def emit(x): print(json.dumps(x, ensure_ascii=False, allow_nan=False), flush=True)
    try:
        body = sys.stdin.read(65537)
        if len(body) > 65536: raise ValueError('Request too large')
        with threadpool_limits(limits=1):
            result = evaluate(json.loads(body), progress=lambda p, message: emit({'type': 'progress', 'progress': p, 'message': message}))
        emit({'type': 'result', 'result': result})
        return 0
    except Exception as e:
        emit({'type': 'error', 'message': str(e)})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
