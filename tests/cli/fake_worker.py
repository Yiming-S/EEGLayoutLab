"""Deterministic fake worker for CLI parity tests (phase 3 slices 6 & 7).

Run as ``<python> -u <root>/scripts/<worker_script>`` via a tiny ``#!/bin/sh`` wrapper passed to ``--python``.
Reads the canonical JSON request from stdin and emits NDJSON events matching ``design_evaluation.py`` and
``run_local_radius_compute.py``, with failure and example-score modes controlled by ``EEG_FAKE_WORKER_MODE``.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _emit(event: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(event) + '\n')
    sys.stdout.flush()


def _grid64(offset_x: float = 0.0) -> list[list[float]]:
    return [[offset_x + (i % 8) * 6.0, (i // 8) * 6.0, 20.0] for i in range(64)]


def _balanced_regions(region_count: int) -> list[int]:
    sizes = [64 // region_count + (1 if r < 64 % region_count else 0) for r in range(region_count)]
    return [r for r, sz in enumerate(sizes) for _ in range(sz)]


def _robustness_block() -> dict[str, Any]:
    def summ(med: float, count: int) -> dict[str, Any]:
        return {'median': med, 'p10': med - 0.02, 'minimum': med - 0.05, 'count': count}

    return {
        'protocol': 'standard/1',
        'snr_db': 20,
        'dropout': {
            'single': {'candidate': [0.95] * 64, 'reference': summ(0.98, 64)},
            'random': [
                {'removed': lvl, 'draws': 32, 'candidate': summ(0.92 - 0.01 * i, 32), 'reference': summ(0.96 - 0.01 * i, 32)}
                for i, lvl in enumerate((2, 4, 8))
            ],
        },
        'impedance': [
            {'log_sd': lvl, 'draws': 32, 'candidate': summ(0.93 - 0.02 * i, 32), 'reference': summ(0.97 - 0.02 * i, 32)}
            for i, lvl in enumerate((0.5, 1.0))
        ],
        'replacement': {
            'status': 'completed',
            'centre_mm': [0.0, 0.0, 40.0],
            'jitter_mm': 2,
            'table_id': 't' * 64,
            'levels': [
                {
                    'rms_mm': rms,
                    'trials': 16,
                    'rotation_deg': 2.5 * (i + 1),
                    'candidate': {
                        'completed': 16,
                        'rejected': 0,
                        'fixed_estimator': summ(0.85 - 0.04 * i, 16),
                        'redigitized': summ(0.91 - 0.02 * i, 16),
                        'displacement_rms_mm': float(rms),
                    },
                    'reference': {
                        'completed': 16,
                        'rejected': 0,
                        'fixed_estimator': summ(0.90 - 0.03 * i, 16),
                        'redigitized': summ(0.95 - 0.01 * i, 16),
                        'displacement_rms_mm': float(rms),
                    },
                }
                for i, rms in enumerate((5, 10))
            ],
        },
    }


def _design_result(root: Path, request: dict[str, Any], mode: str) -> dict[str, Any]:
    admission = json.loads((root / 'results/v2/current_surface_admissibility.json').read_text(encoding='utf-8'))
    xyz = [list(pt) for pt in request['design']['xyz_mm']]
    forward_mode = 'head_scalp_node_table' if request.get('head_id') else 'scalp_node_table'

    # Default deterministic nominal scores, or exact expected.json scores in examples mode.
    design_name = request['design'].get('name', '')
    head_id = request.get('head_id')
    drift = 1e-3 if mode == 'examples_drift' else 0.0

    if mode in ('examples_expected', 'examples_drift'):
        expected = json.loads((root / 'examples/expected.json').read_text(encoding='utf-8'))['scores']
        if head_id:
            # 11 heads ordered in heads.json: set case values so median/p10/p90 match expected.json!
            heads_order = [
                'ernie_xh', 'ixi002', 'ixi012', 'ixi013', 'ixi015', 'ixi017',
                'ixi019', 'ixi020', 'ixi035', 'ixi230', 'ixi231',
            ]
            idx = heads_order.index(head_id) if head_id in heads_order else 5
            ex3 = expected['03-cross-head']
            # For n=11 sorted values v[0..10], type-7 p10 is v[1], median is v[5], p90 is v[9]!
            f_p10, f_med, f_p90 = ex3['field_relative']['p10'], ex3['field_relative']['median'], ex3['field_relative']['p90']
            l_p10, l_med, l_p90 = (
                ex3['localization_relative']['p10'],
                ex3['localization_relative']['median'],
                ex3['localization_relative']['p90'],
            )
            f_vals = [f_p10 - 0.01, f_p10, (f_p10 + f_med) / 2, (f_p10 + f_med) / 2, (f_p10 + f_med) / 2,
                      f_med, (f_med + f_p90) / 2, (f_med + f_p90) / 2, (f_med + f_p90) / 2, f_p90, f_p90 + 0.01]
            l_vals = [l_p10 - 0.01, l_p10, (l_p10 + l_med) / 2, (l_p10 + l_med) / 2, (l_p10 + l_med) / 2,
                      l_med, (l_med + l_p90) / 2, (l_med + l_p90) / 2, (l_med + l_p90) / 2, l_p90, l_p90 + 0.01]
            field_rel = f_vals[idx] + drift
            sens_tail = 0.25
            loc_rel = l_vals[idx]
            med_mm, p90_mm = 20.0, 45.0
        elif design_name == 'standard64':
            s = expected['01-standard64']
            field_rel = s['field_relative'] + drift
            sens_tail = s['sensitivity_tail']
            loc_rel = s['localization_relative']
            med_mm = s['median_mm']
            p90_mm = s['p90_mm']
        else:
            s = expected['02-compact-search']['evaluation']
            field_rel = s['field_relative'] + drift
            sens_tail = s['sensitivity_tail']
            loc_rel = s['localization_relative']
            med_mm = s['median_mm']
            p90_mm = s['p90_mm']
    else:
        seed_offset = float(request.get('seed', 42)) * 0.0001
        field_rel = round(0.82 + seed_offset, 8)
        sens_tail = 0.74
        loc_rel = 0.79
        med_mm = 12.5
        p90_mm = 24.0

    ref_abs = 0.5
    field_abs = field_rel * ref_abs

    trials = []
    if request['action'] == 'perturb':
        for t_idx in range(4):
            moved_xyz = [[p[0] + 1.0, p[1], p[2]] for p in xyz]
            dists = []
            for a in range(64):
                for b in range(a + 1, 64):
                    dx = moved_xyz[a][0] - moved_xyz[b][0]
                    dy = moved_xyz[a][1] - moved_xyz[b][1]
                    dz = moved_xyz[a][2] - moved_xyz[b][2]
                    dists.append((dx * dx + dy * dy + dz * dz) ** 0.5)
            trials.append({
                'index': t_idx,
                'status': 'completed',
                'requested_xyz_mm': moved_xyz,
                'xyz_mm': moved_xyz,
                'candidate_bank_indices': list(range(t_idx, t_idx + 64)),
                'region_indices': list(request['design']['region_indices']),
                'minimum_chord_distance_mm': min(dists),
                'actual_max_mm': 1.0,
                'actual_mean_mm': 1.0,
                'target_error_max_mm': 0.0,
                'unchanged_fraction': 0.0,
                'field_relative': field_rel - 0.01 * (t_idx + 1),
                'fixed_estimator_field_relative': field_rel - 0.02 * (t_idx + 1),
            })

    out: dict[str, Any] = {
        'schema': 'design-evaluation/1',
        'status': 'completed',
        'forward_mode': forward_mode,
        'request': request,
        'projection_max_mm': 0.0,
        'evaluated_xyz_mm': xyz,
        'nominal': {
            'field_relative': field_rel,
            'field_absolute': field_abs,
            'reference_field_absolute': ref_abs,
            'sensitivity_tail': sens_tail,
            'localization_relative': loc_rel,
            'median_mm': med_mm,
            'p90_mm': p90_mm,
            'reference_median_mm': 10.5,
            'reference_p90_mm': 21.0,
        },
        'trials': trials,
        'provenance': {
            'surface_admissibility_sha256': admission['sha256'],
            'surface_admissibility_version': admission['schema_version'],
            'candidate_count': 256,
        },
    }
    if request.get('robustness'):
        out['robustness'] = _robustness_block()
    return out


def _radius_result(root: Path, request: dict[str, Any], mode: str) -> dict[str, Any]:
    pointer_path = root / 'results/v2/current_multiregion_bank.json'
    pointer = json.loads(pointer_path.read_text(encoding='utf-8'))
    admission_path = root / 'results/v2/current_surface_admissibility.json'
    admission = json.loads(admission_path.read_text(encoding='utf-8'))

    code_sha = {
        'scripts/run_local_radius_compute.py': (
            '0' * 64 if mode == 'bad_code_digest' else _sha_file(root / 'scripts/run_local_radius_compute.py')
        )
    }
    provenance = {
        'algorithm_version': 'strict-radius-local/3-external-exposure',
        'pointer_sha256': _sha_file(pointer_path),
        'bank_path': pointer['path'],
        'bank_sha256': pointer['sha256'],
        'geometry_path': pointer['candidates'],
        'geometry_sha256': _sha_file(root / pointer['candidates']),
        'bank_report_sha256': _sha_file(root / pointer['report']),
        'surface_admissibility_path': admission['path'],
        'surface_admissibility_sha256': admission['sha256'],
        'surface_admissibility_version': admission['schema_version'],
        'code_sha256': code_sha,
    }
    if mode == 'no_layout':
        return {'status': 'no_layout', 'request': request, 'provenance': provenance}

    regions = int(request['region_count'])
    xyz = _grid64(5.0)
    if mode in ('examples_expected', 'examples_drift'):
        s = json.loads((root / 'examples/expected.json').read_text(encoding='utf-8'))['scores']['02-compact-search']['search']
        metrics = {
            'field_relative': s['field_relative'],
            'sensitivity_tail': s['sensitivity_tail'],
            'localization_relative': s['localization_relative'],
            'conditional_global': s['conditional_global'],
        }
        area = s['union_area_cm2']
    else:
        metrics = {
            'field_relative': 0.80,
            'sensitivity_tail': 0.65,
            'localization_relative': 0.72,
            'conditional_global': 0.65,
        }
        area = 48.5

    return {
        'status': 'completed',
        'request': request,
        'layout': {
            'xyzMm': xyz,
            'referenceXyzMm': _grid64(0.0),
            'regionIndices': _balanced_regions(regions),
        },
        'geometry': {
            'union_connected_component_count': regions,
            'common_graph_radius_mm': float(request['radius_mm']),
            'union_area_cm2': area,
        },
        'metrics': metrics,
        'provenance': provenance,
    }


def main() -> int:
    script = sys.argv[1]
    root = Path.cwd()
    raw_stdin = sys.stdin.read()
    request = json.loads(raw_stdin)
    mode = os.environ.get('EEG_FAKE_WORKER_MODE', 'ok')

    _emit({'type': 'progress', 'progress': 0.25, 'message': 'step 1'})
    _emit({'type': 'progress', 'progress': 1.0, 'message': 'done'})

    if mode == 'error_event':
        sys.stderr.write('ignored stderr line\n')
        sys.stderr.flush()
        _emit({'type': 'error', 'message': 'synthetic worker error event'})
        return 1
    if mode == 'stderr_only':
        sys.stderr.write('first line\nfinal diagnostic line\n')
        sys.stderr.flush()
        return 1
    if mode == 'silent_exit':
        return 3
    if mode == 'invalid_result':
        _emit({'type': 'result', 'result': {'schema': 'wrong', 'status': 'completed'}})
        return 0
    if mode == 'fail_case_seed_43' and request.get('seed') == 43:
        _emit({'type': 'error', 'message': 'seed 43 failed'})
        return 1

    if script.endswith('design_evaluation.py'):
        if mode == 'mutate_input_during_run':
            target = root / 'data/sources.npz'
            target.write_text('mutated during worker execution', encoding='utf-8')
        _emit({'type': 'result', 'result': _design_result(root, request, mode)})
        return 0
    if script.endswith('run_local_radius_compute.py'):
        _emit({'type': 'result', 'result': _radius_result(root, request, mode)})
        return 0
    if script.endswith('eeg_data.py'):
        action = request.get('action')
        if action == 'summary':
            rec_path = str(request['path'])
            if mode == 'fail_second_recording' and 'rec2' in rec_path:
                _emit({'type': 'error', 'message': 'corrupted EDF header in rec2'})
                return 1
            channels = ['Fp1', 'Fp2', 'F3', 'F4', 'C3', 'C4', 'P3', 'P4', 'O1', 'O2', 'Fz', 'Cz']
            n = len(channels)
            digest = hashlib.sha256(rec_path.encode('utf-8')).hexdigest()
            cov = [[(1.5 if i == j else 0.25 / (abs(i - j) + 1.0)) for j in range(n)] for i in range(n)]
            _emit({
                'type': 'result',
                'result': {
                    'schema': 'eeg-covariance-summary/1',
                    'label': request.get('label'),
                    'channels': channels,
                    'xyz_mm': [[float(i), float(i * 2), 20.0] for i in range(n)],
                    'covariance': cov,
                    'bad_channels': [],
                    'skipped_channels': [],
                    'epochs': {'total': 20, 'analysed': 19, 'used': 18, 'rejected': 1},
                    'processing': {'band_hz': list(request['band_hz']), 'epoch_s': request['epoch_s']},
                    'source': {
                        'file': Path(rec_path).name,
                        'bytes': 4096,
                        'duration_s': 40,
                        'sha256': digest,
                        'recording_sha256': digest,
                        'files': [{'role': 'entry', 'file': Path(rec_path).name, 'bytes': 4096, 'sha256': digest}],
                    },
                },
            })
            return 0
        if action == 'prior':
            files = list(request['files'])
            channels = ['Fp1', 'Fp2', 'F3', 'F4', 'C3', 'C4', 'P3', 'P4', 'O1', 'O2', 'Fz', 'Cz']
            n = len(channels)
            indep = mode == 'prior_independent'
            held_out = (
                {
                    'summaries': len(files),
                    'prior_better_count': len(files) - 1,
                    'selected_shrinkage': 0.25,
                }
                if len(files) >= 3
                else None
            )
            cmat = [[(1.2 if i == j else 0.15) for j in range(n)] for i in range(n)]
            amat = [[(1.0 if i == j else 0.10) for j in range(n)] for i in range(n)]
            _emit({
                'type': 'result',
                'result': {
                    'schema': 'eeg-data-prior/1',
                    'id': 'deadbeef01234567',
                    'regions': ['frontal', 'central', 'parietal', 'occipital', 'temporal_left', 'temporal_right', 'other'],
                    'channels': channels,
                    'band_hz': [1, 40],
                    'request': {
                        'region_gain': [1.25, 0.95, 1.1, 0.85, 1.05, 0.9, 1.0],
                        'rho': 0.0 if indep else 0.35,
                        'length_mm': None if indep else 20,
                    },
                    'fit': {'summaries': len(files), 'held_out': held_out},
                    'channel_model': {'data_prior': cmat, 'area_prior': amat},
                },
            })
            return 0

    sys.stderr.write(f'unexpected script {script}\n')
    return 2


if __name__ == '__main__':
    sys.exit(main())
