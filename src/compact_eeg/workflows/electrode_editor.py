#!/usr/bin/env python3
"""Finite-bank, parent-constrained electrode edits. Old fixed64 protocols stay intact."""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

from . import design_evaluation as design
import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.spatial import cKDTree
from scipy.spatial.distance import pdist
from threadpoolctl import threadpool_limits
from compact_eeg.metrics import helmert_contrast, weighted_lower_cvar
from compact_eeg.inverse_pilot import fixed_normal_scan, error_summary
from compact_eeg.prototype_localization import _layout_noise_generator

SCHEMA = 'electrode-editor/1'


def parent_domain(parent, data, pointer, root, current_geometry_sha):
    """Use recorded native vertex patches, not a hull inferred from contacts."""
    layout = parent['layout']
    provenance = parent.get('provenance', {})
    geometry_sha = provenance.get('geometry_sha256')
    if parent.get('dataset_id') == 'strict_area':
        path = (root / provenance['file']).resolve()
        if not path.is_relative_to((root / 'results/v2').resolve()) or design.sha256_file(path) != provenance.get('sha256'):
            raise ValueError('Parent report identity mismatch')
        identity = json.loads(path.read_text())['identity']
        geometry_sha = identity.get('geometry_sha256')
    if geometry_sha != current_geometry_sha or provenance.get('surface_admissibility_sha256') != data['_admission']['surface_admissibility_sha256']:
        raise ValueError('Parent region geometry or surface-admission identity differs')
    xyz = np.asarray(layout['xyzMm'], float)
    labels = np.asarray(layout['regionIndices'])
    if xyz.shape != (64, 3) or labels.shape != (64,) or labels.dtype.kind not in 'iu':
        raise ValueError('Parent must contain 64 recorded electrodes')
    if not np.array_equal(np.asarray(layout['referenceXyzMm']), data['reference_xyz_mm']):
        raise ValueError('Parent and current standard64 references differ')
    patches = layout.get('regionPatchVertexIndices')
    if not patches or len(patches) != parent['region_count']:
        raise ValueError('This historical layout has no saved region boundaries; choose a current layout')
    distance, original = cKDTree(data['candidate_xyz_mm']).query(xyz)
    if np.max(distance) > 1e-7 or len(np.unique(original)) != 64:
        raise ValueError('Parent coordinates are not in the current forward bank')
    with np.load(root / pointer['candidates'], allow_pickle=False) as g:
        vertices = g['candidate_vertex_indices']
    allowed = [np.flatnonzero(np.isin(vertices, ids) & data['_allowed_bank']) for ids in patches]
    for slot, bank_index in enumerate(original):
        if bank_index not in allowed[int(labels[slot])]:
            raise ValueError('Parent electrode is outside its recorded admissible region')
    return original, labels, allowed


def validate_slots(slots, original, labels, allowed, bank_xyz):
    if not isinstance(slots, list) or len(slots) != 64:
        raise ValueError('The draft must retain 64 stable electrode slots')
    for i, s in enumerate(slots):
        if not isinstance(s, dict) or set(s) != {'bank_index', 'enabled'} or type(s['bank_index']) is not int or type(s['enabled']) is not bool:
            raise ValueError('Invalid electrode slot')
        if s['bank_index'] not in allowed[int(labels[i])]:
            raise ValueError('Electrode is outside its inherited region')
    active = np.array([i for i, s in enumerate(slots) if s['enabled']], dtype=int)
    if not 2 <= len(active) <= 64:
        raise ValueError('At least two active electrodes are required')
    indices = np.array([slots[i]['bank_index'] for i in active], dtype=int)
    if len(np.unique(indices)) != len(indices) or pdist(bank_xyz[indices]).min() < 4 - 1e-7:
        raise ValueError('Active electrodes must be distinct and at least 4 mm apart')
    return active, indices


def field_metrics(h, reference, weights):
    """N-1 observations, 63-dimensional fixed target and fixed physical noise."""
    w = np.asarray(weights, float); w = w / w.max(); w = w / w.sum()
    target = helmert_contrast(64) @ (reference - reference.mean(axis=0))
    observation = helmert_contrast(len(h)) @ (h - h.mean(axis=0))
    scale = np.max(np.abs(target))
    normal = np.sqrt(np.sum((target / scale) ** 2 * w) / 63)
    t, x = target / scale / normal, observation / scale / normal
    cbb, cxx, cbx = (t * w) @ t.T, (x * w) @ x.T, (t * w) @ x.T
    def energy(cross, cov):
        return float(np.sum(cross * cho_solve(cho_factor(cov + .01 * np.eye(len(cov)), lower=True), cross.T).T) / np.trace(cbb))
    baseline = energy(cbb, cbb)
    absolute = energy(cbx, cxx)
    centered = reference - reference.mean(axis=0)
    amplitude = np.ptp(centered, axis=0)
    valid = amplitude > 2e-8 * np.max(np.abs(centered))
    sensitivity = weighted_lower_cvar(np.ptp(h, axis=0)[valid] / amplitude[valid], w[valid], .1) if valid.any() and w[~valid].sum() <= .001 else None
    return {'field_absolute': absolute, 'reference_field_absolute': baseline,
            'field_relative': absolute / baseline, 'sensitivity_tail': sensitivity}, float(scale * normal * 1e-8 * .1)


def localize(h, data, sigma, stable_slots, seed):
    n = len(h); count = len(data['generation_xyz_mm']); dictionary_count = int(data['dictionary_source_count'])
    if n < 3:
        return None, 'single_contrast_unknown_amplitude'
    contrast = helmert_contrast(n)
    hd = contrast @ (h[:, :dictionary_count] - h[:, :dictionary_count].mean(axis=0))
    hg = contrast @ (h[:, dictionary_count:] - h[:, dictionary_count:].mean(axis=0))
    norms = np.linalg.norm(hd, axis=0)
    if np.any(norms <= np.finfo(float).tiny):
        return None, 'zero_dictionary_column'
    generator, _ = _layout_noise_generator(seed, 'design-evaluation-paired-stream')
    z = generator.normal(size=(63, count, 16))
    if n != 64 or not np.array_equal(stable_slots, np.arange(64)):
        # Subselect physical channels, then re-reference. Never slice Z63.
        physical = (helmert_contrast(64).T @ z.reshape(63, -1))[stable_slots]
        z = (contrast @ physical).reshape(n - 1, count, 16)
    observations = (hg[:, :, None] * 1e-8 + sigma * z).reshape(n - 1, -1)
    indices = fixed_normal_scan(hd, observations, sigma**2 * np.eye(n - 1), batch_size=128).reshape(count, 16)
    errors = np.linalg.norm(data['source_xyz_mm'][indices] - data['generation_xyz_mm'][:, None, :], axis=2)
    return error_summary(errors, data['generation_area_weights']), None


def evaluate(envelope, root=design.ROOT, progress=lambda *args: None):
    start = time.perf_counter(); request, parent = envelope['request'], envelope['parent']
    if request['parent_id'] != parent['id']:
        raise ValueError('Parent identity mismatch')
    progress(.05, 'Loading verified forward bank')
    data, pointer, report = design.load_bank(root)
    original, labels, allowed = parent_domain(parent, data, pointer, root, report['candidate_sha256'])
    if request['action'] == 'prepare':
        return {'schema': SCHEMA, 'status': 'completed', 'request': request,
                'parent': parent, 'original_indices': original.tolist(),
                'regions': [{'bank_indices': a.tolist(), 'xyz_mm': data['candidate_xyz_mm'][a].tolist()} for a in allowed]}
    active, chosen = validate_slots(request['slots'], original, labels, allowed, data['candidate_xyz_mm'])
    dictionary_count = int(data['dictionary_source_count'])
    if dictionary_count != 4096 or len(data['generation_xyz_mm']) != 256:
        raise ValueError('Editor requires the frozen 4096/256 source protocol')
    if np.min(cKDTree(data['source_xyz_mm']).query(data['generation_xyz_mm'])[0]) <= 1e-6:
        raise ValueError('Generation sources must be off the inverse dictionary')
    hb = data['reference_leadfield_v_per_am']; hp = data['candidate_leadfield_v_per_am'][original]; hx = data['candidate_leadfield_v_per_am'][chosen]
    progress(.25, 'Re-evaluating the reference and parent under one protocol')
    parent_metrics, sigma = field_metrics(hp[:, :dictionary_count], hb[:, :dictionary_count], data['source_area_weights'])
    ref_loc, _ = localize(hb, data, sigma, np.arange(64), request['seed'])
    parent_loc, parent_reason = localize(hp, data, sigma, np.arange(64), request['seed'])
    progress(.65, 'Evaluating the edited layout')
    edited, _ = field_metrics(hx[:, :dictionary_count], hb[:, :dictionary_count], data['source_area_weights'])
    loc, reason = localize(hx, data, sigma, active, request['seed'])
    def append_location(metrics, location, missing_reason):
        baseline_utility = ref_loc['source_lower10_utility_dmax50mm'] if ref_loc else 0
        metrics.update(localization_relative=location['source_lower10_utility_dmax50mm'] / baseline_utility if location and baseline_utility > 1e-12 else None,
                       median_mm=location['median_error_mm'] if location else None,
                       p90_mm=location['p90_error_mm'] if location else None,
                       localization_unavailable=missing_reason or ('reference_utility_zero' if baseline_utility <= 1e-12 else None))
        values = [metrics[k] for k in ('field_relative', 'sensitivity_tail', 'localization_relative')]
        metrics['conditional_global'] = min(values) if all(v is not None for v in values) else None
    append_location(parent_metrics, parent_loc, parent_reason); append_location(edited, loc, reason)
    baseline = {'field_relative': 1., 'field_absolute': parent_metrics['reference_field_absolute'], 'sensitivity_tail': 1. if parent_metrics['sensitivity_tail'] is not None else None,
                'localization_relative': 1. if ref_loc and ref_loc['source_lower10_utility_dmax50mm'] > 1e-12 else None, 'median_mm': ref_loc['median_error_mm'] if ref_loc else None,
                'p90_mm': ref_loc['p90_error_mm'] if ref_loc else None}
    return {'schema': SCHEMA, 'status': 'completed', 'request': request,
            'electrode_count': len(active), 'active_regions': len(np.unique(labels[active])), 'declared_regions': len(allowed),
            'baseline': baseline, 'parent_metrics': parent_metrics, 'edited_metrics': edited,
            'active_slots': active.tolist(), 'region_indices': labels[active].tolist(),
            'evaluated_xyz_mm': data['candidate_xyz_mm'][chosen].tolist(),
            'parent_label': parent['label'], 'minimum_distance_mm': float(pdist(data['candidate_xyz_mm'][chosen]).min()),
            'provenance': {**data['_admission'], 'bank_sha256': pointer['sha256'], 'candidate_sha256': report['candidate_sha256'],
                'head_count': 1, 'dictionary_sources': dictionary_count, 'generation_sources': 256, 'noise_repetitions': 16,
                'reference_snr_db': 20, 'physical_noise_std_v': sigma, 'seed': request['seed'],
                'source_moment_am': 1e-8, 'source_prior': 'normalized_frozen_cortical_area_weights',
                'noise_stream_sha256': _layout_noise_generator(request['seed'], 'design-evaluation-paired-stream')[1],
                'noise_rule': 'paired_physical_parent_slots_then_new_Helmert_contrast', 'parent_recomputed': True,
                'region_rule': 'inherited_vertex_patches; exact_existing_candidate_coordinates',
                'region_area_changed': False, 'forward_mode': 'exact_bank_rows', 'optimized': False},
            'elapsed_seconds': time.perf_counter() - start}


def main():
    def emit(value): print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)
    try:
        body = sys.stdin.read(2_000_001)
        if len(body) > 2_000_000: raise ValueError('Worker input too large')
        with threadpool_limits(limits=1):
            result = evaluate(json.loads(body), progress=lambda p, m: emit({'type': 'progress', 'progress': p, 'message': m}))
        emit({'type': 'result', 'result': result}); return 0
    except Exception as e:
        emit({'type': 'error', 'message': str(e)}); return 1


if __name__ == '__main__':
    raise SystemExit(main())
