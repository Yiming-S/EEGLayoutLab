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
from compact_eeg import noise_models
from compact_eeg.prototype_localization import evaluate_grid_localization
from compact_eeg.surface_admissibility import load_admissibility


REQUIRED_FIELDS = {'action', 'design', 'radius_mm', 'seed'}
OPTIONAL_FIELDS = {'noise_model', 'conductivity_scenario', 'head_id', 'robustness', 'data_prior'}


def validate_request(raw):
    if not isinstance(raw, dict) or not REQUIRED_FIELDS <= set(raw) or set(raw) - REQUIRED_FIELDS - OPTIONAL_FIELDS:
        raise ValueError('Invalid design evaluation fields')
    # Optional fields are present only with a non-default value, so default requests keep their original keys.
    if 'noise_model' in raw and (raw['noise_model'] is None or noise_models.normalize(raw['noise_model']) != raw['noise_model']):
        raise ValueError('noise_model must be a non-default preset in canonical form')
    if 'conductivity_scenario' in raw:
        from .head_model import conductivity_scenario
        conductivity_scenario(ROOT, raw['conductivity_scenario'])
        if raw.get('action') != 'evaluate':
            raise ValueError('conductivity_scenario applies to the evaluate action only')
    if 'head_id' in raw:
        from .head_package import check_head_id
        check_head_id(raw['head_id'])
        if raw.get('action') != 'evaluate' or 'conductivity_scenario' in raw:
            raise ValueError('head_id applies to the evaluate action only, without a conductivity scenario')
    if 'robustness' in raw:
        from .design_robustness import validate
        validate(raw['robustness'], raw)
    if 'data_prior' in raw:
        from .data_prior import canonical
        if canonical(raw['data_prior']) != raw['data_prior'] or 'noise_model' in raw or 'head_id' in raw:
            raise ValueError('data_prior must be canonical; it replaces noise_model and applies to the Ernie head only')
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


def fixed_estimator_retention(nominal, observed, reference, weights, snr_db=20, noise=None):
    """Expected clean-target energy explained using a frozen nominal LMMSE.

    ``noise`` optionally gives unit-diagonal physical 64x64 noise correlations
    ``{'nominal', 'observed', 'reference'}``; the estimator assumes the nominal
    layout's noise while the error uses the observed layout's noise.
    """
    c = helmert_contrast(64)
    w = np.asarray(weights, float) / np.sum(weights)
    t, a, b = (c @ x for x in (reference, nominal, observed))
    scale = np.sqrt(np.sum(t * t * w) / 63)
    t, a, b = t / scale, a / scale, b / scale
    variance = 10. ** (-snr_db / 10)
    if noise is None:
        n_nominal = n_observed = n_reference = np.eye(63)
    else:
        n_nominal, n_observed, n_reference = (c @ noise[key] @ c.T for key in ('nominal', 'observed', 'reference'))
    def estimator(h, n):
        covariance = (h * w) @ h.T + variance * n
        return cho_solve(cho_factor(covariance, lower=True), ((t * w) @ h.T).T).T
    def explained(transform, h, n):
        residual = t - transform @ h
        error = np.sum(residual * residual * w) + variance * (np.sum(transform * transform) if noise is None else np.sum((transform @ n) * transform))
        return float(1 - error / np.sum(t * t * w))
    baseline = explained(estimator(t, n_reference), t, n_reference)
    return explained(estimator(a, n_nominal), b, n_observed) / baseline


def mismatch_field_retention(nominal, true, nominal_reference, true_reference, weights, snr_db=20, noise=None):
    """Nominal LMMSE applied to observations from a different, data-generating head.

    The estimator is trained on the inversion model (``nominal`` candidate and
    ``nominal_reference`` target fields); the error is evaluated on the true
    candidate observations against the true reference target. The physical
    noise variance keeps the nominal 20 dB calibration in volts, so the true
    SNR may differ. ``noise`` optionally holds unit-diagonal 64x64 correlations
    ``{'candidate', 'reference'}``. Returns (relative, candidate, reference)
    explained energies; the reference layout is evaluated under the same mismatch.
    With ``true == nominal`` this is the matched LMMSE explained energy.
    """
    c = helmert_contrast(64)
    w = np.asarray(weights, float) / np.sum(weights)
    target, true_target, a, b = (c @ np.asarray(x, float) for x in (nominal_reference, true_reference, nominal, true))
    scale = np.sqrt(np.sum(target * target * w) / 63)
    target, true_target, a, b = target / scale, true_target / scale, a / scale, b / scale
    variance = 10. ** (-snr_db / 10)
    n_candidate, n_reference = ((np.eye(63), np.eye(63)) if noise is None else
                                (c @ noise['candidate'] @ c.T, c @ noise['reference'] @ c.T))
    def estimator(h, n):
        covariance = (h * w) @ h.T + variance * n
        return cho_solve(cho_factor(covariance, lower=True), ((target * w) @ h.T).T).T
    def explained(transform, h, n):
        residual = true_target - transform @ h
        error = np.sum(residual * residual * w) + variance * np.sum((transform @ n) * transform)
        return float(1 - error / np.sum(true_target * true_target * w))
    candidate = explained(estimator(a, n_candidate), b, n_candidate)
    reference = explained(estimator(target, n_reference), true_target, n_reference)
    return candidate / reference, candidate, reference


def ernie_scalp(root, data):
    """Frozen Ernie exterior surface, which must index exactly like the screened bank surface."""
    from .head_model import load_scalp
    vertices, faces, _mapping, head_hashes = load_scalp(root)
    if not np.array_equal(faces, data['_surface_faces']) or not np.allclose(vertices, data['_surface_vertices_mm'], rtol=0, atol=1e-9):
        raise ValueError('Native and screened surface indexing differ')
    return vertices, faces, head_hashes


def scenario_tables(root, scenario):
    """Scenario and nominal tables, opened and identity-checked before any forward computation."""
    from . import scalp_node_table
    if not scalp_node_table.available(root, scenario):
        raise ValueError(f'电导率情景 {scenario} 的头皮节点表尚未预计算。')
    if not scalp_node_table.available(root):
        raise ValueError('电导率情景评价需要名义头皮节点表，用于核对同一电极采样。')
    return scalp_node_table.load(root, scenario), scalp_node_table.load(root)


def scenario_fields(root, tables, points, data, h, hb, candidate_ids=None):
    """Data-generating fields of the reference and evaluated points from a scenario table.

    ``tables`` is ``scenario_tables`` output. Both tables are superposed along
    the same projection, and the nominal table must reproduce the nominal fields
    used by the inversion, so the scenario changes conductivities only, never
    electrode sampling. ``candidate_ids`` names bank candidates in errors.
    """
    from . import scalp_node_table
    table, nominal_table = tables
    vertices, faces, head_hashes = ernie_scalp(root, data)
    projection = scalp_node_table.project(vertices, faces, np.vstack([data['reference_xyz_mm'], points]))
    if projection['distances_mm'].max() > 1e-5:
        raise ValueError('情景前向场的表面重投影移动了评价坐标')
    rows, weights = projection['vertex_rows'].copy(), projection['barycentric_weights']
    # Zero-weight corners contribute nothing; point them at the dominant vertex so
    # bank vertices on partly screened triangles stay inside the table.
    negligible = weights < 1e-12
    rows[negligible] = np.repeat(rows[np.arange(len(rows)), weights.argmax(axis=1)][:, None], 3, axis=1)[negligible]
    outside = ~(np.isin(rows, table.vertex_indices) & np.isin(rows, nominal_table.vertex_indices))
    if outside.any():
        k, corner = (int(v) for v in np.argwhere(outside)[0])
        who = (f'标准64参照第{k + 1}点' if k < 64 else f'第{k - 63}个电极'
               + ('' if candidate_ids is None else f'（候选库编号 {int(candidate_ids[k - 64])}）'))
        raise scalp_node_table.TableIdentityError(
            f'{who}所在面片的顶点 {int(rows[k, corner])} 不在电导率情景所用的预计算头皮节点表中；需按当前顶点规则重新预计算头皮节点表。')
    true = table.superpose(rows, weights)
    nominal = nominal_table.superpose(rows, weights)
    expected = np.vstack([hb, h])
    sampling_difference = float(np.linalg.norm(nominal - expected) / np.linalg.norm(expected))
    if not np.all(np.isfinite(true)) or sampling_difference > 1e-8:
        raise ValueError('情景前向场与名义前向场的电极采样不一致，需统一计算版本。')
    qa = {'scenario_table': table.provenance(), 'nominal_table_id': nominal_table.table_id, 'head_hashes': head_hashes,
          'nominal_sampling_relative_difference': sampling_difference,
          'reference_true_vs_nominal_relative_frobenius': float(np.linalg.norm(true[:64] - hb) / np.linalg.norm(hb)),
          'candidate_true_vs_nominal_relative_frobenius': float(np.linalg.norm(true[64:] - h) / np.linalg.norm(h))}
    return true[64:], true[:64], qa


def head_space(root, head_id, ernie_points, data, progress):
    """Fields, sources and positions of a layout mapped onto an additional head package.

    The layout and the standard64 reference use the same mapping (barycentric
    interpolation of Ernie scalp vertices mapped through MNI, then projection).
    Layout electrodes must pass head_package.layout_screen on that head (within
    10 mm of its scalp, on admissible triangles, at least 3 mm apart); the mapped
    reference normalizes every score, so it must pass the same screen. Corners
    with zero barycentric weight do not count: a point on a vertex or an edge is
    judged and superposed by the vertices that carry it, as in scenario_fields.
    """
    from . import head_package, scalp_node_table
    progress(.8, f'映射到头模 {head_id} 并读取其预计算前向场')
    package = head_package.load(root, head_id)
    if not scalp_node_table.available(root, head=head_id):
        raise ValueError(f'头模 {head_id} 的头皮节点表尚未预计算。')
    table = scalp_node_table.load(root, head=head_id)
    if package.manifest['ernie']['bank_candidate_sha256'] != data['_candidate_sha256']:
        raise ValueError(f'头模 {head_id} 的映射基于另一版本的Ernie表面。')
    eligible = package.admission['eligible_vertex_mask']
    if not head_package.layout_screen(eligible, package.mapping['reference_vertex_rows'], package.mapping['reference_xyz_mm'],
                                      package.mapping['reference_projection_mm'])[3]:
        raise ValueError(f'头模 {head_id} 上映射后的标准64参照未通过映射筛选（10 mm投影距离、外部曝光或3 mm间距）；该头模不用于评价。')
    mapped = head_package.map_points(ernie_points, data['_surface_vertices_mm'], data['_surface_faces'],
                                     package.mapping['ernie_scalp_to_head_mm'], package.scalp['vertices_mm'], package.scalp['triangles'])
    rows = head_package.supporting_rows(mapped['vertex_rows'], mapped['barycentric_weights'])
    screened, spacing, projection, passes = head_package.layout_screen(eligible, rows, mapped['projected_mm'],
                                                                       mapped['mapping_projection_mm'])
    screened = screened and bool(np.isin(rows, table.vertex_indices).all())
    if not (passes and screened):  # thresholds live in layout_screen; the message names the first failed test
        if projection > head_package.LAYOUT_PROJECTION_LIMIT_MM:
            shown = np.ceil(projection * 10 - 1e-9) / 10  # rounded away from the limit, never "10.0 mm, more than 10 mm"
            raise ValueError(f'布局映射到头模 {head_id} 后，有电极距该头模头皮 {shown:.1f} mm，超过10 mm；该布局在此头模上不评价。')
        if not screened:
            raise ValueError(f'布局映射到头模 {head_id} 后，有电极落在外部曝光筛选未通过的面片；该布局在此头模上不评价。')
        shown = np.floor(spacing * 100 + 1e-9) / 100
        raise ValueError(f'布局映射到头模 {head_id} 后最小电极间距为 {shown:.2f} mm，低于3 mm；该布局在此头模上不评价。')
    h = table.superpose(rows, mapped['barycentric_weights'])
    hb = table.superpose(package.mapping['reference_vertex_rows'], package.mapping['reference_weights'])
    if not (np.all(np.isfinite(h)) and np.all(np.isfinite(hb))):
        raise ValueError('头模前向场含非有限值')
    s = package.sources
    qa = {'head_package': package.provenance(), 'scalp_node_table': table.provenance(),
          'mapping_projection_mm': {'maximum': float(mapped['mapping_projection_mm'].max()),
                                    'median': float(np.median(mapped['mapping_projection_mm']))},
          'minimum_spacing_mm': spacing, 'head_xyz_mm': mapped['projected_mm'].tolist()}
    return (h, hb, mapped['projected_mm'], package.mapping['reference_xyz_mm'], s['source_area_weights'],
            (s['source_xyz_mm'], s['generation_xyz_mm'], s['generation_area_weights']), qa)


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
        data['_candidate_vertex_indices'] = g['candidate_vertex_indices']
    data['_eligible_surface'] = eligible
    data['_admission'] = admission
    data['_candidate_sha256'] = report['candidate_sha256']
    return data, p, report


def candidate_projector(vertices, faces, data):
    """Admission, registration-distance and spacing checks for requested surface points."""
    import cortech
    def project_candidate(requested):
        projection_surface = cortech.Surface(vertices, faces)
        triangles, weights, projected, _ = projection_surface.project_points(requested, pttris=20)
        if not np.all(data['_eligible_surface'][faces[triangles]]):
            raise ValueError('坐标投影位于外部曝光筛选未通过的面片；请修改该电极位置后重新评价。')
        distances = np.linalg.norm(requested - projected, axis=1)
        if distances.max() > 2:
            raise ValueError(f'坐标距Ernie表面最大{distances.max():.2f} mm，超过2 mm。请先完成配准。')
        if pdist(projected).min() < 4 - 1e-7:
            raise ValueError('表面投影后的电极点距小于4 mm。')
        return projected
    return project_candidate


def frozen_sources(root, pointer, bank_report, data, head_hashes):
    """Bank-identical source positions and normals for a native model of the frozen head."""
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
    return sources, normals


ERNIE_SOURCE_EXCEPTIONS = [698, 957, 1559, 3408]


def checked_native_model(mesh, cond, vertices, faces, mapping, sources, normals, advance, *, gauge_node=None, exceptions=ERNIE_SOURCE_EXCEPTIONS):
    """FixedMeshLeadfield with the qualified source-interpolation QA enforced.

    ``exceptions`` is the recorded list of sources outside every tissue element
    (Ernie's frozen list by default; a head package records its own).
    """
    from compact_eeg.cortical_fem import FixedMeshLeadfield
    model = FixedMeshLeadfield(mesh, cond, vertices, faces, mapping, sources, normals, progress=advance,
                               **({} if gauge_node is None else {'gauge_node': gauge_node}))
    q = model.source_qa
    if q['fallback_distance_mm']['maximum'] > 3 or q['interpolation_row_sum_max_error'] > 1e-7 or q['normal_operator_constant_field_max_abs'] > 1e-7 or q['official_operator_sample_check']['relative_frobenius_difference'] > 1e-10:
        raise ValueError('Native source interpolation QA failed')
    if exceptions is not None and source_exceptions(model) != list(exceptions):
        raise ValueError('Native source exception list changed')
    return model, q


def source_exceptions(model):
    return np.flatnonzero(model.source_qa_arrays['containing_tissue_tag_or_minus_one'] == -1).tolist()


def ernie_projection(root, points, data, progress):
    """New coordinates of a head request: table_field's Ernie gate and projections, no Ernie field.

    The head package supplies every field, so no Ernie table or FEM is read;
    the evaluated coordinates are the ones the Ernie path would produce.
    """
    from . import scalp_node_table
    progress(.12, '读取Ernie头皮表面，检查坐标到表面的投影')
    vertices, faces, head_hashes = ernie_scalp(root, data)
    projected = candidate_projector(vertices, faces, data)(points)
    projection = scalp_node_table.project(vertices, faces, np.vstack([data['reference_xyz_mm'], projected]))
    if projection['distances_mm'].max() > 1e-5:
        raise ValueError('Native surface re-projection moved fixed reference coordinates')
    actual = projection['projected_mm'][64:]
    qa = {'head_hashes': head_hashes, 'projection_distance_mm': {'maximum': float(projection['distances_mm'].max()),
                                                                 'median': float(np.median(projection['distances_mm']))}}
    return actual, float(np.linalg.norm(points - actual, axis=1).max()), qa


def table_field(root, points, data, pointer, bank_report, progress, table=None):
    """Superpose verified scalp-node rows along native_field's projection path and QA.

    No volume mesh or FEM solve is loaded. Each electrode's row is the
    barycentric sum of three precomputed unit-node rows of the same operator.
    ``table`` is the already opened current nominal table, if any.
    """
    from . import scalp_node_table
    started = time.perf_counter()
    progress(.12, '读取Ernie头皮表面，检查坐标到表面的投影')
    vertices, faces, head_hashes = ernie_scalp(root, data)
    projected = candidate_projector(vertices, faces, data)(points)
    manifest = json.loads((root / pointer['path']).parents[2].joinpath('run_manifest.json').read_text())
    if head_hashes != manifest['identity']['head_hashes']:
        raise ValueError('新位置FEM头模与参照前向库不一致；需先统一头模和参照库。')
    progress(.3, '读取预计算头皮节点FEM前向场')
    table = scalp_node_table.load(root) if table is None else table
    projection = scalp_node_table.project(vertices, faces, np.vstack([data['reference_xyz_mm'], projected]))
    if projection['distances_mm'].max() > 1e-5:
        raise ValueError('Native surface re-projection moved fixed reference coordinates')
    field = table.superpose(projection['vertex_rows'], projection['barycentric_weights'])
    if not np.all(np.isfinite(field)):
        raise ValueError('预计算头皮节点前向场含非有限值')
    reference_difference = float(np.linalg.norm(field[:64] - data['reference_leadfield_v_per_am']) / np.linalg.norm(data['reference_leadfield_v_per_am']))
    if reference_difference > 1e-8:
        raise ValueError('新FEM参照场与前向库不一致，需统一计算版本。')
    qa = {'head_hashes': head_hashes, 'reference_relative_difference': reference_difference,
          'scalp_node_table': table.provenance(), 'electrode_count': int(len(field)),
          'projection_distance_mm': {'maximum': float(projection['distances_mm'].max()),
                                     'median': float(np.median(projection['distances_mm']))},
          'superposition': 'barycentric sum of three unit-node rows per electrode (cortical_fem.balanced_sampling_rhs linearity)',
          'timings_seconds': {'table_superposition': time.perf_counter() - started}}
    actual = projection['projected_mm'][64:]
    return field[64:], actual, float(np.linalg.norm(points - actual, axis=1).max()), qa


def native_field(root, points, data, pointer, bank_report, progress, *, reception_publisher=None):
    """Direct FEM for all requested points, no montage interpolation."""
    # This loader enforces the frozen head mesh, mapping and conductivity hashes.
    from .head_model import load_head
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
        os.environ[key] = '1'
    progress(.12, '读取Ernie体积网格，检查坐标到表面的投影')
    mesh, cond, vertices, faces, mapping, head_hashes = load_head(root)
    if not np.array_equal(faces, data['_surface_faces']) or not np.allclose(vertices, data['_surface_vertices_mm'], rtol=0, atol=1e-9):
        raise ValueError('Native and screened surface indexing differ')
    project_candidate = candidate_projector(vertices, faces, data)
    projected = project_candidate(points)
    sources, normals = frozen_sources(root, pointer, bank_report, data, head_hashes)
    preparing_reception = False
    def advance(stage, **values):
        if stage == 'cortical_fem_electrode_block_complete':
            start, span = (.81, .02) if preparing_reception else (.35, .45)
            progress(start + span * values['completed_electrodes'] / values['total_electrodes'], f"新位置FEM：{values['completed_electrodes']}/{values['total_electrodes']}点")
        elif stage == 'cortical_fem_factorization_start':
            progress(.3, '分解头模矩阵；本机单任务、单线程')
    model, q = checked_native_model(mesh, cond, vertices, faces, mapping, sources, normals, advance)
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
    def checked_qa(field, solve_qa):
        if solve_qa['max_relative_full_system_residual'] > 1e-7 or solve_qa['max_relative_free_dof_residual'] > 1e-7 or solve_qa['point_transfer_reciprocity_relative_frobenius'] > 1e-8 or not np.all(np.isfinite(field)):
            raise ValueError('Native FEM residual/reciprocity QA failed')
        for key in ('net_prescribed_current_A_per_electrode', 'net_assembled_current_A_per_electrode', 'reaction_current_relative_error_per_electrode'):
            if np.max(np.abs(solve_qa[key])) > 1e-7:
                raise ValueError('Native FEM current conservation QA failed')
        reference_difference = float(np.linalg.norm(field[:64] - data['reference_leadfield_v_per_am']) / np.linalg.norm(data['reference_leadfield_v_per_am']))
        if reference_difference > 1e-8:
            raise ValueError('新FEM参照场与前向库不一致，需统一计算版本。')
        return {'head_hashes': head_hashes, 'reference_relative_difference': reference_difference,
                'source_qa': q, 'fem_qa': solve_qa, 'timings_seconds': dict(model.timings),
                'threadpools': native_threads}
    design_qa = checked_qa(h, qa)
    actual = projection.projected_mm[64:]
    if reception_publisher is not None:
        from .shared_native_forward import IdentityChanged, IntegrityError
        try:
            # Reception historically calls native_field(actual), performing both
            # projections again. Repeat that exact path: even sub-ULP coordinate
            # changes must not silently substitute the design's numerical field.
            progress(.81, '复用已分解的头模，准备信号实验的精确前向场')
            reception_projection = model.project(np.vstack([data['reference_xyz_mm'], project_candidate(actual)]))
            if reception_projection.distances_mm.max() > 1e-5:
                raise ValueError('Native surface re-projection moved fixed reference coordinates')
            same_sampling = all(
                getattr(reception_projection, name).dtype == getattr(projection, name).dtype
                and getattr(reception_projection, name).shape == getattr(projection, name).shape
                and getattr(reception_projection, name).tobytes() == getattr(projection, name).tobytes()
                for name in ('requested_mm', 'projected_mm', 'triangle_ids', 'barycentric_weights',
                             'node_rows', 'distances_mm'))
            if same_sampling:
                reception_h, reception_qa = h, design_qa
            else:
                preparing_reception = True
                with threadpool_limits(limits=1):
                    reception_h, reception_solve_qa = model.evaluate(reception_projection, block_size=4)
                reception_qa = checked_qa(reception_h, reception_solve_qa)
            reception_publisher(actual, reception_h[64:], reception_projection.projected_mm[64:], reception_qa)
        except (IdentityChanged, IntegrityError):
            raise
        except Exception as error:
            # Reception is optional: a second-path numerical or cache-write
            # failure cannot invalidate the already qualified design field.
            # Cancellation is a BaseException and still propagates unchanged.
            design_qa['reception_preparation'] = {'status': 'unavailable',
                'error_type': type(error).__name__, 'message': str(error)}
    return h[64:], actual, float(np.linalg.norm(points - actual, axis=1).max()), design_qa


def evaluate(raw, root=ROOT, progress=lambda *args: None):
    started = time.perf_counter()
    request = validate_request(raw)
    data, pointer, bank_report = load_bank(root)
    scenario, head_id = request.get('conductivity_scenario'), request.get('head_id')
    # A scenario needs both tables; a missing or stale one fails before any forward computation.
    tables = scenario_tables(root, scenario) if scenario is not None else None
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
    elif head_id is not None:
        # The head package supplies every field below; only the Ernie surface gate runs here.
        projected, projection_max, qa = ernie_projection(root, xyz, data, progress)
    else:
        from . import scalp_node_table
        if scalp_node_table.available(root):
            # A published table replaces the per-request solve; an invalid table is an error, not a fallback.
            h, projected, projection_max, qa = table_field(root, xyz, data, pointer, bank_report, progress,
                                                           table=None if tables is None else tables[1])
            mode = 'scalp_node_table'
        else:
            from .reception_forward_provider import design_forward_session
            with design_forward_session(root, xyz) as publish:
                h, projected, projection_max, qa = native_field(root, xyz, data, pointer, bank_report, progress,
                                                               reception_publisher=publish)
            mode = 'direct_fem'
    prior = request.get('data_prior')
    if prior is not None:
        from . import data_prior
        # Region gains reweight both source sets; the fitted noise enters like a spatial preset.
        weights, generation_weights = data_prior.apply(root, data, prior)
        model = data_prior.noise_model(prior)
    else:
        model, generation_weights = noise_models.normalize(request.get('noise_model')), data['generation_area_weights']
    kernel = noise_models.field_kernel(model)
    reference_xyz = data['reference_xyz_mm']
    candidate_xyz = projected
    source_sets = (data['source_xyz_mm'], data['generation_xyz_mm'], generation_weights)
    if head_id is not None:
        # Every quantity below comes from the head package; evaluated_xyz_mm stays the Ernie layout.
        h, hb, candidate_xyz, reference_xyz, weights, source_sets, head_qa = head_space(root, head_id, projected, data, progress)
        qa = {**qa, 'head': head_qa}
        mode = 'head_scalp_node_table'
    def field_engine(field, xyz):
        return LayoutSearchMetrics(field, hb[:, :n], weights, noise_kernel=None if kernel is None else (xyz, reference_xyz, *kernel))
    engine = field_engine(h[:, :n], candidate_xyz)
    own = engine.evaluate(np.arange(64), snr_db=(20,))['conditions'][0]
    sigma = np.sqrt(engine.reference_mean_contrast_signal_power_v2 * .01)
    if scenario is not None:
        progress(.8, '读取电导率情景的预计算前向场')
        true_h, true_hb, scenario_qa = scenario_fields(root, tables, projected, data, h, hb, ids if in_bank else None)
    kappa = (noise_models.background_scale(hb[:, :n], weights, sigma * sigma, model['fraction'], 1e-8)
             if model and model['kind'] == 'brain_background' else None)
    progress(.84, '固定坐标，评价重建、幅度与定位')
    def localize(field, xyz, true=None):
        # Under a conductivity scenario the generating head (sources and any brain
        # background) is the true one; the scanner keeps the nominal dictionary.
        physical = field if true is None else true
        covariance = noise_models.localization_covariance(model, xyz, physical[:, :n], weights, sigma * sigma, 1e-8, kappa)
        return evaluate_grid_localization(field[:, :n], physical[:, n:], source_sets[0], source_sets[1], source_moment_am=1e-8,
            physical_electrode_noise_std_v=sigma, noise_seed=request['seed'], layout_id='design-evaluation-paired-stream', noise_repetitions=16,
            generation_source_weights=source_sets[2], physical_noise_covariance_v2=covariance,
            noise_model=noise_models.describe(model)).report
    def summary(field_scores, sensitivity, loc, ref_loc):
        u = ref_loc['source_lower10_utility_dmax50mm']
        return {**field_scores, 'sensitivity_tail': sensitivity,
            'localization_relative': loc['source_lower10_utility_dmax50mm'] / u if u > 1e-12 else None,
            'median_mm': loc['median_error_mm'], 'p90_mm': loc['p90_error_mm'], 'reference_median_mm': ref_loc['median_error_mm'], 'reference_p90_mm': ref_loc['p90_error_mm']}
    ref_loc = localize(hb, reference_xyz); loc = ref_loc if exact_reference else localize(h, candidate_xyz)
    nominal = summary({'field_relative': own['field_retention_unclipped'], 'field_absolute': own['candidate_field_explained_energy'],
        'reference_field_absolute': own['reference_field_explained_energy']}, engine.sensitivity_tail(np.arange(64)), loc, ref_loc)
    mismatch = None
    if scenario is not None:
        # The reported scores use the scenario head as truth; the matched scores stay in provenance.
        correlations = None if kernel is None else {'candidate': noise_models.spatial_correlation(projected, *kernel),
                                                    'reference': noise_models.spatial_correlation(reference_xyz, *kernel)}
        relative, candidate, reference = mismatch_field_retention(h[:, :n], true_h[:, :n], hb[:, :n], true_hb[:, :n], weights, noise=correlations)
        true_engine = LayoutSearchMetrics(true_h[:, :n], true_hb[:, :n], weights)
        true_ref_loc = localize(hb, reference_xyz, true_hb)
        true_loc = true_ref_loc if exact_reference else localize(h, projected, true_h)
        mismatch = {'matched_model': nominal, 'scenario': scenario_qa['scenario_table']['conductivity_scenario'],
                    'inversion': 'nominal SimNIBS 4.6 conductivities (frozen bank and nominal table)',
                    'data_generation': 'scenario table: candidate, reference and generation sources',
                    'field': 'nominal LMMSE applied to scenario observations, scenario reference target; noise variance fixed in volts',
                    'sensitivity': 'scenario fields for candidate and reference',
                    'localization': 'nominal dictionary, scenario generation fields; noise covariance from the scenario head'}
        nominal = summary({'field_relative': relative, 'field_absolute': candidate, 'reference_field_absolute': reference},
                          true_engine.sensitivity_tail(np.arange(64)), true_loc, true_ref_loc)
        qa = {**qa, 'conductivity_scenario': scenario_qa}
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
                changed_engine = field_engine(changed, bank_xyz[chosen])
                trial['field_relative'] = changed_engine.make_state(np.arange(64)).field_relative
                trial['sensitivity_tail'] = changed_engine.sensitivity_tail(np.arange(64))
                correlations = None if kernel is None else {name: noise_models.spatial_correlation(points, *kernel) for name, points in
                    (('nominal', projected), ('observed', bank_xyz[chosen]), ('reference', reference_xyz))}
                trial['fixed_estimator_field_relative'] = fixed_estimator_retention(h[:, :n], changed, hb[:, :n], weights, noise=correlations)
            trials.append(trial)
    robustness = None
    if request.get('robustness'):
        from . import design_robustness
        vertices, faces, _ = ernie_scalp(root, data)
        robustness = design_robustness.evaluate({
            'root': root, 'data': data, 'kernel': kernel, 'scalp': (vertices, faces), 'n': n, 'weights': weights,
            'h': h[:, :n], 'xyz': projected, 'hb': hb[:, :n], 'reference_xyz': reference_xyz,
            'engine': engine, 'reference_engine': field_engine(hb[:, :n], reference_xyz)}, request['seed'], progress)
    return {'schema': 'design-evaluation/1', 'status': 'completed', 'request': request, 'forward_mode': mode,
        'nominal': nominal, 'projection_max_mm': projection_max, 'evaluated_xyz_mm': projected.tolist(),
        'trials': trials, 'provenance': {**data['_admission'], 'head_count': 1, 'bank_sha256': pointer['sha256'],
            **({'head': {'head_id': head_id, **qa['head']['head_package'], 'table_id': qa['head']['scalp_node_table']['table_id'],
                         'protocol': 'cross-head: package sources, mapped standard64 reference, default conductivities'}} if head_id else {}),
            'surface_point_rule': 'bank_vertex_mask; new points require all three projected face vertices; fixed standard64 reference exempt',
            'source_count': n, 'generation_count': len(data['generation_xyz_mm']), 'candidate_count': len(bank_xyz), 'noise_repetitions': 16,
            'noise_model': noise_models.describe(model), 'nominal_reference_snr_db': 20,
            **({'model_mismatch': mismatch} if mismatch else {}),
            'source_prior': 'frozen_area_weights' if prior is None else 'data_prior_region_gains_on_area_weights',
            **({'data_prior': data_prior.describe(prior)} if prior is not None else {}), 'estimator_training': 'known_prior_LMMSE',
            'reference_perturbed': False, 'regional_boundary_requalified': False,
            # Recorded by the package builder from the mesh bytes; a package without it is not claimed independent.
            'independent_head_validation': bool(head_id) and qa['head']['head_package']['mapping']['same_subject_as_ernie'] is False,
            'paired_localization_noise': True, 'thread_limit': 1, 'seed': request['seed'],
            'code_sha256': sha256_file(Path(__file__)), 'numpy': np.__version__, 'python': sys.version},
        **({'robustness': robustness} if robustness else {}),
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
