"""Synthetic library roots and the Node reference for test_library.py and test_radius.py (tests/service/README.md).

``library_root`` builds a root with everything the read-only library loads: the radius code files and forward
inputs, the early radius experiments (``single-head-app/1``), a current (external exposure, v4) and a historical
(v3) strict-area report behind their pointers, radius cache records (compatible, written under another code
identity, failing the input check, with a bad checksum, malformed, unreadable, without ``cache.json``), saved
coordinate evaluations (the default protocol, each ``evaluation_condition``, robustness, a perturbation trial, and
records that fail their checks) and electrode-name annotations. ``broken_root`` breaks the three offline datasets
in a chosen way.

``run_node`` runs ``LIBRARY_DRIVER`` (Node's own ``LocalComputeQueue`` and ``ElectrodeAnnotations``) once over a
list of roots, with one thread-pool worker and a queue directory that is never created; ``python_entry`` computes
the same entry with ``eeglayoutlab.jobs``. ``node_generation`` measures where the running Node differs from the
releases the service follows, and ``sorting_as_node`` runs Python's sorts with that Node's V8 limit. Nothing here
needs Pydantic until a root is built.
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Iterator, Optional

from eeglayoutlab.jobs.identity import DATA_PRIOR_FILES, request_key
from eeglayoutlab.jobs.integrity import ADMISSION_POINTER, BANK_POINTER
from eeglayoutlab.schemas import jsjson

from .key_parity_support import NODE_ENV, PRIOR, SPATIAL

ROOT = Path(__file__).resolve().parents[2]
WEBAPP = ROOT / 'webapp'

# --- Files -------------------------------------------------------------------------------------------------------


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode('utf-8') if isinstance(data, str) else data).hexdigest()


def write(root: Path, relative: str, body: Any) -> bytes:
    """Writes text, bytes or a JSON value (``JSON.stringify`` text); returns the bytes written."""
    if isinstance(body, bytes):
        data = body
    else:
        data = (body if isinstance(body, str) else jsjson.stringify(body)).encode('utf-8')
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data


GRID = [[(i % 8) * 6.0, (i // 8) * 6.0, 0.0] for i in range(64)]
# Sorted by UTF-16 code units, U+1F600 (a surrogate pair) comes before U+FF5A; by UTF-8 bytes it comes after.
CODE_NAMES = ('b.py', 'a.py', 'Z.py', 'ä.py', 'ｚ.py', '\U0001F600.py', 'notes.txt', 'cache.pyc')
PROVENANCE_VERSION = 'strict-radius-local/3'


def grid(shift: float = 0.0) -> list[list[float]]:
    return [[x + shift, y, z] for x, y, z in GRID]


def balanced(regions: int) -> list[int]:
    return [i % regions for i in range(64)]


def code_tree(root: Path, linked: Optional[Path] = None) -> None:
    """The radius code files (``codeIdentity``) and the data-prior files; ``linked`` adds a code file that is a
    link to a file outside the root, which Node follows."""
    write(root, 'scripts/run_local_radius_compute.py', 'worker')
    write(root, 'configs/single_head_optimization.json', '{}')
    for name in CODE_NAMES:
        write(root, f'src/compact_eeg/{name}', name)
    (root / 'src/compact_eeg/workflows.py.d').mkdir()
    for path in DATA_PRIOR_FILES:
        write(root, path, path)
    if linked is not None:
        (root / 'src/compact_eeg/linked.py').symlink_to(linked)


def forward_inputs(root: Path) -> dict:
    """The bank pointer, the surface-admission pointer and their files; returns a radius provenance that
    ``InputIntegrity.verify`` accepts."""
    pointer = {'path': 'results/v2/bank/runs/r/batches/b/bank.npz', 'candidates': 'data/candidates.npz',
               'report': 'data/report.json', 'sha256': sha('bank')}
    write(root, pointer['path'], 'bank')
    write(root, pointer['candidates'], 'candidates')
    report = write(root, pointer['report'], {'candidate_sha256': sha('candidates')})
    pointer_bytes = write(root, BANK_POINTER, pointer)
    admission = {'path': 'data/admission.npz', 'sha256': sha('mask'), 'geometry_sha256': sha('candidates'),
                 'schema_version': 'native-external-exposure/1'}
    write(root, ADMISSION_POINTER, admission)
    write(root, admission['path'], 'mask')
    return {'algorithm_version': PROVENANCE_VERSION, 'bank_path': pointer['path'],
            'geometry_path': pointer['candidates'], 'bank_sha256': pointer['sha256'],
            'pointer_sha256': sha(pointer_bytes), 'geometry_sha256': sha('candidates'),
            'bank_report_sha256': sha(report), 'surface_admissibility_path': admission['path'],
            'surface_admissibility_sha256': admission['sha256'],
            'surface_admissibility_version': admission['schema_version']}


# --- Radius results ----------------------------------------------------------------------------------------------

def radius_result(request: dict, provenance: Optional[dict] = None, *, status: str = 'completed',
                  metrics: Optional[dict] = None) -> dict:
    """A worker result ``validateWorkerResult`` accepts for ``request`` (check-local-compute.mjs ``resultFor``)."""
    if status == 'no_layout':
        result: dict[str, Any] = {'status': 'no_layout', 'request': request, 'layout': None, 'metrics': None}
    else:
        regions = request['region_count']
        result = {'status': 'completed', 'request': request,
                  'layout': {'id': 'fixture', 'xyzMm': grid(), 'referenceXyzMm': grid(0.5),
                             'regionIndices': balanced(regions)},
                  'geometry': {'union_connected_component_count': regions,
                               'common_graph_radius_mm': request['radius_mm'] - 2.5, 'union_area_cm2': 30.25},
                  'metrics': metrics or {'field_relative': 0.8, 'sensitivity_tail': 0.3,
                                         'localization_relative': 0.5, 'conditional_global': 0.3}}
    if provenance is not None:
        result['provenance'] = provenance
    return result


def cache_path(key: str) -> str:
    return f'results/v2/local_app_jobs/{key}/cache.json'


def write_cache(root: Path, key: str, request: dict, result: Any, finished_at: Optional[str] = None, *,
                result_sha256: Optional[str] = None) -> Path:
    cache: dict[str, Any] = {'key': key, 'request': request, 'result': result,
                             'result_sha256': result_sha256 or jsjson.sha256_hex(result)}
    if finished_at is not None:
        cache['finished_at'] = finished_at
    write(root, cache_path(key), cache)
    return root / cache_path(key)


RADIUS_REQUESTS = {
    'preset': {'region_count': 2, 'radius_mm': 35, 'mode': 'preset', 'mask_codes': ['PL', 'PR']},
    'whole': {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'},
    'spatial': {'region_count': 3, 'radius_mm': 20, 'mode': 'low_hair', 'noise_model': SPATIAL},
    'prior': {'region_count': 4, 'radius_mm': 25, 'mode': 'whole_surface', 'data_prior': PRIOR},
    'prior-iid': {'region_count': 6, 'radius_mm': 80, 'mode': 'preset',
                  'mask_codes': ['FL', 'FM', 'FR', 'OL', 'OR', 'AL'],
                  'data_prior': {**PRIOR, 'rho': 0, 'length_mm': None}},
    'other-code': {'region_count': 2, 'radius_mm': 40, 'mode': 'low_hair'},
    'changed-input': {'region_count': 3, 'radius_mm': 45, 'mode': 'whole_surface'},
    'old-algorithm': {'region_count': 2, 'radius_mm': 50, 'mode': 'whole_surface'},
    'no-provenance': {'region_count': 1, 'radius_mm': 55, 'mode': 'low_hair'},
    'bad-checksum': {'region_count': 1, 'radius_mm': 60, 'mode': 'whole_surface'},
    'malformed': {'region_count': 1, 'radius_mm': 65, 'mode': 'whole_surface'},
    'unreadable': {'region_count': 1, 'radius_mm': 70, 'mode': 'whole_surface'},
    'missing': {'region_count': 1, 'radius_mm': 75, 'mode': 'whole_surface'},
}


def radius_caches(root: Path, provenance: dict, python: str) -> dict[str, str]:
    """The radius cache records of the base root; returns their keys by name."""
    from eeglayoutlab.jobs.radius import RadiusCache

    radius = RadiusCache(str(root), python)
    code = radius.get_identity()
    keys = {name: radius.identity_for(request, code)[1] for name, request in RADIUS_REQUESTS.items()}
    keys['other-code'] = radius.identity_for(RADIUS_REQUESTS['other-code'], {**code, 'retired.py': sha('old')})[1]
    stamp = '2026-09-0{}T12:00:00Z'.format
    for index, name in enumerate(('preset', 'spatial', 'prior', 'prior-iid', 'other-code')):
        write_cache(root, keys[name], RADIUS_REQUESTS[name], radius_result(RADIUS_REQUESTS[name], provenance),
                    stamp(index + 1) if name != 'spatial' else None)
    no_null = {'field_relative': 0.8, 'sensitivity_tail': None, 'localization_relative': 0.5,
               'conditional_global': None}
    write_cache(root, keys['whole'], RADIUS_REQUESTS['whole'],
                radius_result(RADIUS_REQUESTS['whole'], provenance, status='no_layout'), stamp(6))
    write_cache(root, keys['changed-input'], RADIUS_REQUESTS['changed-input'],
                radius_result(RADIUS_REQUESTS['changed-input'], {**provenance, 'pointer_sha256': sha('old pointer')},
                              metrics=no_null), stamp(7))
    old = {key: value for key, value in provenance.items() if not key.startswith('surface_')}
    write_cache(root, keys['old-algorithm'], RADIUS_REQUESTS['old-algorithm'],
                radius_result(RADIUS_REQUESTS['old-algorithm'], {**old, 'algorithm_version': 'strict-radius-local/2'}),
                stamp(8))
    write_cache(root, keys['no-provenance'], RADIUS_REQUESTS['no-provenance'],
                radius_result(RADIUS_REQUESTS['no-provenance']), stamp(9))
    write_cache(root, keys['bad-checksum'], RADIUS_REQUESTS['bad-checksum'],
                radius_result(RADIUS_REQUESTS['bad-checksum'], provenance, status='no_layout'), stamp(1),
                result_sha256=sha('stale'))
    write(root, cache_path(keys['malformed']), '{broken')
    unreadable = write_cache(root, keys['unreadable'], RADIUS_REQUESTS['unreadable'],
                             radius_result(RADIUS_REQUESTS['unreadable'], provenance, status='no_layout'), stamp(2))
    if os.geteuid() != 0:
        unreadable.chmod(0)
    else:
        unreadable.unlink()
    (root / cache_path(keys['missing'])).parent.mkdir(parents=True)
    (root / 'results/v2/local_app_jobs/not-a-key').mkdir()
    return keys


# --- Offline experiments -----------------------------------------------------------------------------------------

def offline_radius() -> dict:
    """An early radius experiment file (``webapp/public/data/single_head_optimization.json``)."""
    conditions = []
    rows = [(1, 'bilateral_near_ear', 'whole', 15, 4), (2, None, 'low_hair', 22.5, 4.5),
            (3, 'unknown_family', ['left_ear', 'forehead'], 40, 4), (4, 'left_ear_forehead', 'whole', 60, 5),
            (6, None, 'whole_surface', 80, 4)]
    for index, (regions, family, mode, radius, spacing) in enumerate(rows):
        variants = []
        for objective in ('field_20db', 'field_sensitivity_20db'):
            tail = None if index == 1 and objective == 'field_20db' else 0.3 + index * 1e-3
            scores = [0.8 - index * 1e-2, tail, 0.5]
            variants.append({
                'id': f'v{index}-{objective}', 'objective': objective, 'xyz_mm': grid(index),
                'region_indices': balanced(regions),
                'conditions': [{'snr_db': 10, 'field_relative': 0.1}, {
                    'snr_db': 20, 'field_relative': scores[0], 'sensitivity_tail': tail, 'localization_relative': 0.5,
                    'conditional_global': None if tail is None else min(scores), 'median_mm': 11.5 + index}],
            })
        condition: dict[str, Any] = {'id': f'c{index}', 'R': regions, 'mode': mode, 'radius_mm': radius,
                                     'spacing_mm': spacing, 'variants': variants}
        if family is not None:
            condition['family_id'] = family
        conditions.append(condition)
    return {'schema': 'single-head-app/1', 'scope': {'head_count': 1, 'physical_electrode_count': 64},
            'provenance': {'source': 'fixture', 'generated': '2025-01-01'},
            'baseline': {'xyz_mm': grid(0.25), 'conditions': [{'snr_db': 10, 'field_absolute': 0.5, 'median_mm': 20},
                                                              {'snr_db': 20, 'field_absolute': 0.98, 'median_mm': 8.5}]},
            'conditions': conditions}


AREA_V3 = 'compact-eeg-area-budget-study/3-strict-merge-limited'
AREA_V4 = 'compact-eeg-area-budget-study/4-external-exposure'


def area_report(exterior: bool = True, run_id: str = 'area-run') -> dict:
    """A strict-area report with 30 conditions; the last has no layout."""
    domains = ('whole', 'low_hair', ['PL', 'PR'], 'whole_surface')
    entries = []
    for n in range(30):
        regions = (1, 2, 3, 4, 6)[n % 5]
        cap = (20, 37.5, 60)[n % 3]
        condition = {'id': f'area-{n:02d}', 'region_count': regions, 'domain': domains[n % 4], 'area_cap_cm2': cap}
        if n == 29:
            entries.append({'condition': condition, 'status': 'no_feasible_layout', 'finalists': []})
            continue
        localization = None if n % 7 == 3 else 0.5 + n * 1e-3
        scores = [0.8 + n * 1e-3, 0.3, localization]
        evaluation = {
            'id': f'layout-{n}', 'field20': scores[0], 'sensitivity_tail': 0.3, 'localization_relative20': localization,
            'conditional_global20': None if localization is None else min(scores),
            'field_metrics': {'conditions': [
                {'nominal_reference_snr_db': 10, 'candidate_field_explained_energy': 0.4},
                {'nominal_reference_snr_db': 20, 'candidate_field_explained_energy': 0.7 + n * 1e-3}]},
            'localization': {'dictionary_source_count': 4096, 'generation_source_count': 256,
                             'median_error_mm': 12.5 + n, 'p90_error_mm': 30.25 + n},
            'xyz_mm': grid(-n),
        }
        geometry = {'union_connected_component_count': regions, 'union_area_cm2': cap}
        final: dict[str, Any] = {'xyz_mm': grid(n), 'region_indices': balanced(regions), 'geometry': geometry}
        if exterior:
            geometry['region_areas_cm2'] = [cap / regions] * regions
            final['surface_patch_vertex_indices'] = [[n * 100 + k * 3 + j for j in range(3)] for k in range(regions)]
        entries.append({'condition': condition, 'status': 'completed_best_found', 'finalists': [
            {'objective': 'max_field20', 'evaluation': {}, 'final': {}},
            {'objective': 'min_field_sensitivity20', 'evaluation': evaluation, 'final': final},
        ]})
    report: dict[str, Any] = {
        'schema_version': AREA_V4 if exterior else AREA_V3, 'run_id': run_id, 'batch_id': 'batch-1',
        'formal_population_ar': False,
        'config': {'physical_electrode_count': 64, 'spacing_mm': 4, 'evaluation': {'snr_db': 20},
                   'require_disconnected_regions': True},
        'baseline': {'reference_xyz_mm': grid(0.75),
                     'localization': {'dictionary_source_count': 4096, 'generation_source_count': 256,
                                      'median_error_mm': 9.5},
                     'field_metrics': {'conditions': [{'candidate_field_explained_energy': 0.99}]}},
        'conditions': entries,
    }
    if exterior:
        report['identity'] = {'surface_admissibility_sha256': sha('mask'),
                              'surface_admissibility_version': 'native-external-exposure/1'}
    return report


CURRENT_POINTER = 'results/v2/current_strict_area_budget_study.json'
HISTORICAL_POINTER = 'results/v2/historical_strict_area_budget_study.json'
OFFLINE_RADIUS = 'webapp/public/data/single_head_optimization.json'


def offline_datasets(root: Path, *, radius: Any = None, current: Any = None, historical: Any = None,
                     pointers: Optional[dict] = None) -> None:
    """The three offline datasets; a value replaces a dataset's file body, ``pointers`` its pointer."""
    write(root, OFFLINE_RADIUS, offline_radius() if radius is None else radius)
    for pointer, name, body in ((CURRENT_POINTER, 'current', current if current is not None else area_report()),
                                (HISTORICAL_POINTER, 'historical',
                                 historical if historical is not None else area_report(False, 'historical-run'))):
        report = f'results/v2/campaigns/area/{name}.json'
        data = write(root, report, body)
        write(root, pointer, (pointers or {}).get(name, {'report': report, 'sha256': sha(data)}))


# --- Coordinate evaluations --------------------------------------------------------------------------------------

DESIGN_IDENTITY = {'schema': 'design-evaluation-cache/1', 'digests': {'fixture': sha('serialization fixture')},
                   'threads': 1}


def _stats(median: float, count: int) -> dict:
    return {'median': median, 'p10': median - 1e-3, 'minimum': median - 2e-3, 'count': count}


def _side(completed: int, rejected: int) -> dict:
    if completed:
        return {'completed': completed, 'rejected': rejected, 'fixed_estimator': _stats(0.99, completed),
                'redigitized': _stats(0.999, completed), 'displacement_rms_mm': 5.6}
    return {'completed': completed, 'rejected': rejected, 'fixed_estimator': None, 'redigitized': None,
            'displacement_rms_mm': None}


def robustness_block(table: bool = True) -> dict:
    """``robustnessBlock({table})`` of webapp/scripts/helpers/robustness-fixture.mjs."""
    replacement = ({'status': 'completed', 'centre_mm': [0, -10, 40], 'jitter_mm': 2, 'table_id': 't' * 64,
                    'levels': [{'rms_mm': rms, 'trials': 16, 'rotation_deg': 3.6 * (i + 1), 'candidate': _side(15, 1),
                                'reference': _side(0, 16) if i else _side(16, 0)} for i, rms in enumerate((5, 10))]}
                   if table else {'status': 'unavailable', 'reason': '重新佩戴试验需要预计算头皮节点表，本安装没有。'})
    return {'protocol': 'standard/1', 'snr_db': 20,
            'dropout': {'single': {'candidate': [0.999 - i * 1e-6 for i in range(64)], 'reference': _stats(0.9996, 64)},
                        'random': [{'removed': removed, 'draws': 32, 'candidate': _stats(0.999 - i * 1e-3, 32),
                                    'reference': _stats(0.9993 - i * 1e-3, 32)} for i, removed in enumerate((2, 4, 8))]},
            'impedance': [{'log_sd': log_sd, 'draws': 32, 'candidate': _stats(0.999 - i * 2e-3, 32),
                           'reference': _stats(0.9991 - i * 2e-3, 32)} for i, log_sd in enumerate((0.5, 1))],
            'replacement': replacement}


def design_request(name: str, **extra: Any) -> dict:
    from eeglayoutlab.jobs.design_result import normalize_design_request

    design = {'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm', 'name': name,
              'xyz_mm': GRID, 'region_indices': [float(i >= 32) for i in range(64)]}
    return normalize_design_request({'action': 'evaluate', 'radius_mm': 6.0, 'seed': 42.0, 'design': design, **extra})


def design_record(root: Path, request: dict, *, finished_at: Optional[str] = '2026-10-14T00:00:00Z',
                  change: Optional[Callable[[dict], None]] = None) -> str:
    """A saved evaluation of ``request`` (check-coordinate-bundles.mjs ``fixture``); ``change`` edits the cache
    before it is written. Returns its key."""
    key = request_key(request, DESIGN_IDENTITY)
    result: dict[str, Any] = {
        'schema': 'design-evaluation/1', 'status': 'completed', 'request': request,
        'forward_mode': 'head_scalp_node_table' if request.get('head_id') else 'direct_fem',
        'nominal': {'field_relative': 0.9 / 0.99, 'field_absolute': 0.9, 'reference_field_absolute': 0.99,
                    'sensitivity_tail': 0.4, 'localization_relative': 0.5, 'median_mm': 10, 'p90_mm': 20,
                    'reference_median_mm': 9, 'reference_p90_mm': 18},
        'projection_max_mm': 1, 'evaluated_xyz_mm': [[x, y, 1] for x, y, _ in GRID],
        'provenance': {'candidate_count': 64}, 'trials': [],
    }
    if request.get('robustness'):
        result['robustness'] = robustness_block()
    cache = {'key': key, 'identity': DESIGN_IDENTITY, 'result': result, 'result_sha256': jsjson.sha256_hex(result)}
    if finished_at is not None:
        cache['finished_at'] = finished_at
    if change is not None:
        change(cache)
    write(root, f'results/v2/design_evaluation_jobs/{key}/cache.json', cache)
    return key


def design_records(root: Path) -> dict[str, str]:
    """One saved evaluation per protocol variant, a perturbation trial, and records that fail their checks."""
    keys = {
        'default': design_record(root, design_request('默认协议 fixture')),
        'noise': design_record(root, design_request('spatial', noise_model=SPATIAL), finished_at='2026-10-15T00:00:00Z'),
        'scenario': design_record(root, design_request('skull', conductivity_scenario='skull_x2'), finished_at=None),
        'head': design_record(root, design_request('head', head_id='ixi002'), finished_at='2026-10-13T00:00:00Z'),
        'prior': design_record(root, design_request('prior', data_prior=PRIOR), finished_at='2026-10-16T00:00:00Z'),
        'robustness': design_record(root, design_request('robust', robustness='standard/1'),
                                    finished_at='2026-10-17T00:00:00Z'),
        'perturb': design_record(root, design_request('perturb', action='perturb')),
    }

    def checksum(cache: dict) -> None:
        cache['result_sha256'] = sha('stale')

    def identity(cache: dict) -> None:
        cache['identity'] = {**DESIGN_IDENTITY, 'threads': 2}

    def metrics(cache: dict) -> None:
        cache['result']['nominal']['median_mm'] = None
        cache['result_sha256'] = jsjson.sha256_hex(cache['result'])

    keys['checksum'] = design_record(root, design_request('checksum'), change=checksum)
    keys['identity'] = design_record(root, design_request('identity'), change=identity)
    keys['metrics'] = design_record(root, design_request('metrics'), change=metrics)
    keys['missing'] = sha('missing design record')
    (root / f'results/v2/design_evaluation_jobs/{keys["missing"]}').mkdir(parents=True)
    return keys


# --- Annotations -------------------------------------------------------------------------------------------------

NAMES = [f'E{i}' for i in range(64)]


def annotation(owner: str, record_id: str, names: Optional[list] = None) -> dict:
    """An annotation file as Node's ``ElectrodeAnnotations.identity`` writes it."""
    identity = {'schema': 'eeg-electrode-annotation/1', 'owner': owner, 'record_id': record_id,
                'request_sha256': sha(owner + record_id), 'xyz_sha256': sha('xyz'), 'regions_sha256': sha('regions'),
                'electrode_names': names or NAMES}
    return {'id': jsjson.sha256_hex(identity), **identity}


def write_annotation(directory: Path, value: dict, body: Any = None) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f'{value["id"]}.json').write_bytes(jsjson.stringify(value if body is None else body).encode('utf-8'))
    return value['id']


NODE_ANNOTATIONS = 'results/v2/design_evaluation_jobs/electrode_annotations'


def annotations(root: Path, record_id: str, *, broken: bool = False) -> dict:
    """Annotations in Node's directory: two owners of one record or, ``broken``, a tampered file and one with
    invalid names."""
    directory = root / NODE_ANNOTATIONS
    if broken:
        tampered = annotation('browser-a', record_id)
        invalid = annotation('browser-c', record_id, ['same'] * 64)
        write_annotation(directory, tampered, {**tampered, 'owner': 'browser-z'})
        write_annotation(directory, invalid)
        return {'tampered': tampered, 'invalid': invalid}
    first, second = annotation('browser-a', record_id), annotation('browser-b', record_id, [f'Ch{i}' for i in range(64)])
    write_annotation(directory, first)
    write_annotation(directory, second)
    return {'first': first, 'second': second}


# --- Roots -------------------------------------------------------------------------------------------------------

def library_root(root: Path, python: str, *, linked: Optional[Path] = None) -> dict:
    """The base root; returns the keys and annotations it holds."""
    root.mkdir(parents=True)
    code_tree(root, linked)
    provenance = forward_inputs(root)
    offline_datasets(root)
    return {'radius': radius_caches(root, provenance, python), 'design': design_records(root),
            'provenance': provenance}


def broken_offline(root: Path, kind: str) -> None:
    """A root whose offline datasets each fail in one way (``kind`` picks the set)."""
    root.mkdir(parents=True)
    code_tree(root)
    forward_inputs(root)
    current, historical = area_report(), area_report(False, 'historical-run')
    if kind == 'paths':
        radius = {**offline_radius(), 'schema': 'single-head-app/2'}
        offline_datasets(root, radius=radius, pointers={
            'current': {'sha256': sha('x')},
            'historical': {'report': 'results/v2/elsewhere/historical.json', 'sha256': sha('x')}})
        write(root, 'results/v2/elsewhere/historical.json', historical)
    elif kind == 'digests':
        radius = {**offline_radius(), 'conditions': {'0': {}}}
        historical['config']['spacing_mm'] = 2
        offline_datasets(root, radius=radius, historical=historical, pointers={
            'current': {'report': 'results/v2/campaigns/area/current.json', 'sha256': sha('another report')}})
    elif kind == 'protocols':
        radius = offline_radius()
        del radius['baseline']
        historical['schema_version'] = AREA_V4
        current['conditions'][0]['finalists'] = []
        offline_datasets(root, radius=radius, current=current, historical=historical)
    elif kind == 'records':
        radius = offline_radius()
        radius['conditions'][1]['variants'][0]['region_indices'] = [0] * 64
        current['baseline']['localization']['generation_source_count'] = 512
        historical['conditions'][3]['finalists'][1]['evaluation']['conditional_global20'] = 0.9
        offline_datasets(root, radius=radius, current=current, historical=historical)
    elif kind == 'patches':
        radius = offline_radius()
        radius['conditions'][1]['mode'] = 5
        current['conditions'][4]['finalists'][1]['final']['surface_patch_vertex_indices'][0] = [1, 1, 2]
        historical['conditions'][1]['condition']['region_count'] = 5
        offline_datasets(root, radius=radius, current=current, historical=historical)
    elif kind == 'counts':
        radius = offline_radius()
        radius['conditions'][2]['variants'][1]['conditions'] = [{'snr_db': 10}]
        current['conditions'][5]['finalists'][1]['final']['geometry']['union_connected_component_count'] = 99
        historical['conditions'][0]['condition'] = None
        offline_datasets(root, radius=radius, current=current, historical=historical)
    else:
        raise ValueError(kind)


BROKEN = ('paths', 'digests', 'protocols', 'records', 'patches', 'counts')


# --- Node reference ----------------------------------------------------------------------------------------------

LIBRARY_DRIVER = r"""
// Node reference of tests/service/library_support.py: for each root, Node's own LocalComputeQueue (a fresh one,
// with a queue directory that is never created) lists the library, gets every listed id and the extra ids, derives
// identityFor of each request, and reads the annotations of Node's directory.
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const [specPath, outPath] = process.argv.slice(2);
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const load = path => import(pathToFileURL(`${spec.webapp}/${path}`).href);
const { LocalComputeQueue } = await load('server/local-compute-server.mjs');
const { ElectrodeAnnotations } = await load('server/annotations/electrode-names.mjs');
const failure = error => ({ ok: false, code: error?.code ?? null, name: error?.name ?? null,
  message: String(error?.message ?? error), status: error?.status ?? null });
async function attempt(run) {
  try { return { ok: true, value: await run() }; } catch (error) { return failure(error); }
}
const out = {};
for (const item of spec.roots) {
  const queue = new LocalComputeQueue({ repositoryRoot: item.root, queueDirectory: spec.queueDirectory });
  const entry = { root: queue.root, python: queue.python, get: {}, identity: {} };
  entry.list = await attempt(async () => JSON.stringify(await queue.library.list()));
  const ids = [...item.ids];
  if (entry.list.ok) for (const row of JSON.parse(entry.list.value).records) if (!ids.includes(row.id)) ids.push(row.id);
  for (const id of ids) entry.get[id] = await attempt(async () => JSON.stringify(await queue.library.get(id)));
  for (const [name, request] of Object.entries(item.requests)) {
    entry.identity[name] = await attempt(() => {
      const { identity, key } = queue.identityFor(request);
      return { identity: JSON.stringify(identity), key };
    });
  }
  if (item.annotations) {
    const store = new ElectrodeAnnotations(item.root);
    entry.annotations = { reads: [], lists: [] };
    for (const [id, owner, record] of item.annotations.reads)
      entry.annotations.reads.push(await attempt(() => JSON.stringify(store.read(id, owner, record))));
    for (const owner of item.annotations.owners)
      entry.annotations.lists.push(await attempt(() => store.list(owner).map(value => JSON.stringify(value))));
  }
  queue.dispose();
  out[item.id] = entry;
}
writeFileSync(outPath, JSON.stringify(out));
process.exit(0);
"""


def run_node(roots: list[dict], scratch: Path) -> dict:
    """Runs ``LIBRARY_DRIVER`` once over ``roots`` (``{id, root, ids, requests, annotations?}``)."""
    queue = scratch / 'node-queue'  # resolved by the queue, never created
    driver, spec_path, out_path = scratch / 'library.mjs', scratch / 'library-spec.json', scratch / 'library-node.json'
    driver.write_text(LIBRARY_DRIVER, encoding='utf-8')
    spec_path.write_text(jsjson.stringify({'webapp': str(WEBAPP), 'queueDirectory': str(queue), 'roots': roots}),
                         encoding='utf-8')
    subprocess.run(['node', str(driver), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV)
    assert not queue.exists()
    return json.loads(out_path.read_text(encoding='utf-8'))


# Where Node releases differ in what the service reproduces: V8's short-array sort (jobs/jssort) and the Received part
# of ERR_INVALID_ARG_TYPE (reception_records.received).
GENERATION_PROBE = r"""
const path = require('node:path');
const reversedCalls = n => {
  let count = 0;
  Array.from({ length: n }, (_, i) => n - i).sort((a, b) => { count += 1; return a - b; });
  return count;
};
// A reversed array is one run for TimSort (n - 1 comparisons); binary insertion alone makes more from n = 3.
const sizes = Array.from({ length: 30 }, (_, i) => i + 3);
let received = '';
try { path.join('/r', { constructor: 5 }); } catch (error) { received = error.message; }
process.stdout.write(JSON.stringify({
  node: process.versions.node,
  insertionLimit: Math.max(2, ...sizes.filter(n => reversedCalls(n) !== n - 1)),
  receivedHardened: received.endsWith('Received [Object]'),
}));
"""


@functools.cache
def node_generation() -> dict:
    """The running Node: ``insertionLimit``, the longest array its V8 sorts by binary insertion alone (7 on Node 26,
    the service's; 2, no such path, on Node 24 and older), and ``receivedHardened``, whether its
    ``ERR_INVALID_ARG_TYPE`` names an object only by a non-empty string ``constructor.name`` (nodejs/node#65607,
    the service's; Node 26.5 and 24.21 do not)."""
    done = subprocess.run(['node', '-e', GENERATION_PROBE], check=True, capture_output=True, text=True, cwd=ROOT,
                          env=NODE_ENV)
    return json.loads(done.stdout)


@contextlib.contextmanager
def sorting_as_node() -> Iterator[None]:
    """Python's sorts (``jssort.INSERTION_LIMIT``) with the running Node's limit, for comparisons with that Node."""
    from eeglayoutlab.jobs import jssort

    saved = jssort.INSERTION_LIMIT
    jssort.INSERTION_LIMIT = node_generation()['insertionLimit']
    try:
        yield
    finally:
        jssort.INSERTION_LIMIT = saved


# --- Python side -------------------------------------------------------------------------------------------------

def failure(error: BaseException) -> dict:
    """A Python failure in the compared form (see ``node_failure``)."""
    from eeglayoutlab.jobs.records import error_code

    code = error_code(error)
    if code is not None:
        return {'ok': False, 'code': code}
    if isinstance(error, jsjson.JSONSyntaxError):
        return {'ok': False, 'name': 'SyntaxError'}
    status = getattr(error, 'status', None)
    return {'ok': False, 'message': str(error), **({'status': status} if status is not None else {})}


def node_failure(result: dict) -> dict:
    """A driver result in the compared form: by Node's code where the error has one (system errors carry absolute
    paths), a ``SyntaxError`` by name, the others by message (and status for annotation errors)."""
    if result['ok']:
        return result
    if result['code']:
        return {'ok': False, 'code': result['code']}
    if result['name'] == 'SyntaxError':
        return {'ok': False, 'name': 'SyntaxError'}
    return {'ok': False, 'message': result['message'],
            **({'status': result['status']} if result['status'] is not None else {})}


def attempt(run: Callable[[], Any]) -> dict:
    try:
        return {'ok': True, 'value': run()}
    except Exception as error:  # noqa: BLE001 - compared with Node
        return failure(error)


def python_entry(item: dict) -> dict:
    """The driver's entry for one root, computed with ``eeglayoutlab.jobs``."""
    from eeglayoutlab.jobs.annotations import ElectrodeAnnotations
    from eeglayoutlab.jobs.library import Library
    from eeglayoutlab.jobs.runtime import runtime_config

    config = runtime_config(item['root'])
    library = Library(item['root'], config)
    entry: dict[str, Any] = {'root': library.root, 'python': config.python, 'get': {}, 'identity': {}}
    entry['list'] = attempt(lambda: jsjson.stringify(library.list()))
    ids = list(item['ids'])
    if entry['list']['ok']:
        ids += [row['id'] for row in jsjson.parse(entry['list']['value'])['records'] if row['id'] not in ids]
    for id in ids:
        entry['get'][id] = attempt(lambda: jsjson.stringify(library.get(id)))
    for name, request in item['requests'].items():
        def derive(request: dict = request) -> dict:
            identity, key = library.radius.identity_for(request)
            return {'identity': jsjson.stringify(identity), 'key': key}
        entry['identity'][name] = attempt(derive)
    if 'annotations' in item:
        store = ElectrodeAnnotations.local(None, item['root'])
        entry['annotations'] = {
            'reads': [attempt(lambda id=id, record=record: jsjson.stringify(store.read(id, record)))
                      for id, _, record in item['annotations']['reads']],
            'list': attempt(lambda: [jsjson.stringify(value) for value in store.list()]),
        }
    return entry


def records_by_text(list_text: str) -> tuple[list[str], dict]:
    """A library list as the sorted texts of its records and the rest of the document."""
    document = jsjson.parse(list_text)
    records = document.pop('records')
    return sorted(jsjson.stringify(record) for record in records), document


def finished_order(list_text: str) -> list:
    return [record.get('finished_at') for record in jsjson.parse(list_text)['records']]
