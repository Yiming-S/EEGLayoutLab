"""The electrode editor's test helpers (test_editor.py and the editor half of test_key_parity.py; tests/service/
README.md).

``editor_root`` builds an editor root: a design root (``key_parity_support.design_root``, so the design context the
editor's builds on is the scientific one) with the radius code files, the editor's worker and workflow, and parents
of each kind the library offers: strict-area layouts of a current (external exposure) report whose identity names
its region geometry, a historical strict-area layout, an early radius experiment, a saved coordinate evaluation, and
radius caches whose layouts carry region patches or not, under a noise model or a data prior, with another region
geometry or surface admission, under another code identity, without a layout or with an empty patch list.
``EDITOR_ROOTS`` (key_parity_support) names the variants. The ids of the parents come back by name;
``parent_records`` reads the full records as ``Library.get`` gives them, whose digests an ``evaluate`` request
carries.

The requests and results are check-electrode-editor.mjs's (``prepare``, ``evaluate``, ``prepare_result``,
``evaluate_result``). ``FAKE_WORKER`` stands in for ``scripts/electrode_editor.py``: it reads ``{request, parent}``
and answers with a result the validator accepts, or, as ``R/editor-mode.txt`` says, fails, holds or echoes another
request.

The parity of the run path: ``parity_cases`` builds the case roots and scripts, ``run_node`` runs Node's own
``ElectrodeEditorService`` over them (``parity/editor_run.mjs``, mode ``runs``) and ``run_python`` runs
``EditorJobs`` over the same steps, with the parents' ids and digests of a catalog root built first (``catalog``).
Each root is built again at the same path for Python, so the bytes written can be compared as they are.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable, Optional

from eeglayoutlab.jobs.design import MAX_OUTPUT_BYTES, WORKER_ENV
from eeglayoutlab.jobs.editor import WORKER_SCRIPT, EditorJobs
from eeglayoutlab.jobs.identity import EDITOR_WORKFLOW
from eeglayoutlab.jobs.integrity import ADMISSION_POINTER, BANK_POINTER
from eeglayoutlab.jobs.library import Library, _id_for
from eeglayoutlab.jobs.radius import RadiusCache
from eeglayoutlab.jobs.runtime import runtime_config
from eeglayoutlab.schemas import jsjson

from .design_support import (
    CLOCK, SETTLE, TIMEOUT_CASE_MS, _message, _progress_lines, _round, _stderr_chunks, odd_result_line, result_line,
)
from .key_parity_support import (
    EDITOR_CACHES, EDITOR_PARENTS, EDITOR_ROOTS, EDITOR_STRICT, NODE_ENV, PRIOR, SPATIAL, design_root, digest,
)
from .library_support import (
    GRID, PROVENANCE_VERSION, area_report, cache_path, design_record, design_request, offline_datasets,
    radius_result, sha, write, write_cache,
)
from .radius_support import FakeChild, PinnedClock, PinnedIds, Spawner, b64, line, until

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/editor_run.mjs'
EDITOR_JOBS = 'results/v2/electrode_editor_jobs'
EDITOR_CODE = EDITOR_WORKFLOW[0]
RADIUS_WORKER = 'scripts/run_local_radius_compute.py'
REPORT = 'results/v2/campaigns/area/current.json'
# The current report's times, a whole second: Node gives a file's times back in milliseconds (the tamper step), so
# both hosts restore them exactly and the library's memo keeps the report.
REPORT_TIME = 1790000000
HOLD = 120  # seconds a held fake worker waits; it is always stopped before that
MISSING = 'c' * 64
STALE = 'd' * 64

# The radius caches by name (key_parity_support.EDITOR_CACHES): the request and how the record differs.
CACHE_REQUESTS: dict[str, dict] = {
    'cache': {'region_count': 2, 'radius_mm': 35, 'mode': 'preset', 'mask_codes': ['PL', 'PR']},
    'cache-prior': {'region_count': 4, 'radius_mm': 25, 'mode': 'whole_surface', 'data_prior': PRIOR},
    'cache-spatial': {'region_count': 3, 'radius_mm': 20, 'mode': 'low_hair', 'noise_model': SPATIAL},
    'cache-unpatched': {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'},
    'cache-zero-patches': {'region_count': 2, 'radius_mm': 40, 'mode': 'low_hair'},
    'cache-no-layout': {'region_count': 1, 'radius_mm': 55, 'mode': 'low_hair'},
    'cache-geometry': {'region_count': 3, 'radius_mm': 45, 'mode': 'whole_surface'},
    'cache-admission': {'region_count': 6, 'radius_mm': 80, 'mode': 'preset',
                        'mask_codes': ['FL', 'FM', 'FR', 'OL', 'OR', 'AL']},
    'cache-other-code': {'region_count': 2, 'radius_mm': 50, 'mode': 'whole_surface'},
}
assert tuple(CACHE_REQUESTS) == EDITOR_CACHES
# Region counts of the strict-area parents (area_report: (1, 2, 3, 4, 6)[n % 5]; n = 29 has no layout).
STRICT_REGIONS = {name: (1, 2, 3, 4, 6)[n % 5] for name, n in EDITOR_STRICT.items()}
REGIONS = {**STRICT_REGIONS, **{name: request['region_count'] for name, request in CACHE_REQUESTS.items()}}

# --- Roots -------------------------------------------------------------------------------------------------------


def current_report(geometry: bool = True) -> dict:
    """The current strict-area report (``area_report``), whose identity also names the region geometry."""
    report = area_report()
    if geometry:
        report['identity']['geometry_sha256'] = digest('candidates')
    return report


def tampered_report(geometry: bool = True) -> str:
    """The current report's text with one character changed, as many bytes as before."""
    text = jsjson.stringify(current_report(geometry))
    assert text.count('"batch-1"') == 1
    return text.replace('"batch-1"', '"batch-2"')


def _provenance(tree: Path) -> dict:
    """A radius provenance of the root's forward inputs (``InputIntegrity.verify`` accepts it), as
    library_support.forward_inputs returns one."""
    pointer_bytes = (tree / BANK_POINTER).read_bytes()
    pointer = jsjson.parse(pointer_bytes.decode('utf-8'))
    admission = jsjson.parse((tree / ADMISSION_POINTER).read_text(encoding='utf-8'))
    return {'algorithm_version': PROVENANCE_VERSION, 'bank_path': pointer['path'],
            'geometry_path': pointer['candidates'], 'bank_sha256': pointer['sha256'],
            'pointer_sha256': sha(pointer_bytes), 'geometry_sha256': sha((tree / pointer['candidates']).read_bytes()),
            'bank_report_sha256': sha((tree / pointer['report']).read_bytes()),
            'surface_admissibility_path': admission['path'],
            'surface_admissibility_sha256': admission['sha256'],
            'surface_admissibility_version': admission['schema_version']}


def _cache_result(name: str, request: dict, provenance: dict) -> dict:
    if name == 'cache-no-layout':
        return radius_result(request, provenance, status='no_layout')
    if name == 'cache-geometry':
        provenance = {**provenance, 'geometry_sha256': sha('other candidates')}
    if name == 'cache-admission':
        provenance = {**provenance, 'surface_admissibility_sha256': sha('another mask')}
    result = radius_result(request, provenance)
    regions = request['region_count']
    if name == 'cache-zero-patches':
        result['layout']['regionPatchVertexIndices'] = []
        result['layout']['regionAreasCm2'] = []
    elif name != 'cache-unpatched':
        result['layout']['regionPatchVertexIndices'] = [[k * 10 + j for j in range(3)] for k in range(regions)]
        result['layout']['regionAreasCm2'] = [12.5] * regions
    return result


def _parents(tree: Path, geometry: bool) -> dict[str, str]:
    """Writes the parents of every kind; returns their ids by name."""
    provenance = _provenance(tree)
    offline_datasets(tree, current=current_report(geometry))
    report = tree / REPORT
    os.utime(report, (REPORT_TIME, REPORT_TIME))
    report_sha = sha(report.read_bytes())
    ids = {name: _id_for('strict_area', f'area-run:{report_sha}:area-{n:02d}') for name, n in EDITOR_STRICT.items()}
    ids['historical'] = _id_for('strict_area', 'area-01')
    ids['offline'] = _id_for('offline_radius', 'c1:v1-field_20db')
    ids['design'] = design_record(tree, design_request('editor parent'))
    radius = RadiusCache(str(tree), 'python3')
    code = radius.get_identity()
    for index, (name, request) in enumerate(CACHE_REQUESTS.items()):
        identity = {**code, 'retired.py': sha('old')} if name == 'cache-other-code' else code
        ids[name] = radius.identity_for(request, identity)[1]
        write_cache(tree, ids[name], request, _cache_result(name, request, provenance),
                    f'2026-11-{index + 1:02d}T08:00:00Z')
    return ids


def editor_root(directory: Path, *, editor: Optional[str] = None, **options: Any) -> dict:
    """An editor root under ``directory`` (``design_root(directory, **options)`` plus the editor's files and the
    parents). ``editor`` changes one thing: ``no_geometry`` (the current report's identity names no region
    geometry), ``other_admission`` (the surface admission is replaced after the parents were found), ``no_script``
    and ``no_code`` (the worker or the workflow file is gone), ``code_dir`` (the workflow file is a directory) or
    ``no_library`` (no dataset, cache or saved evaluation). Returns ``{root, tree, ids}``: the root string to
    configure, its real path and the parents' ids by name (``missing`` names no record)."""
    assert editor in (None, 'no_geometry', 'other_admission', 'no_script', 'no_code', 'code_dir', 'no_library')
    root = design_root(directory, **options)
    tree = Path(os.path.realpath(root))
    write(tree, RADIUS_WORKER, 'radius worker')
    write(tree, 'configs/single_head_optimization.json', '{"restarts":2}')
    write(tree, WORKER_SCRIPT, 'editor worker')
    write(tree, EDITOR_CODE, 'editor code')
    ids = {**_parents(tree, geometry=editor != 'no_geometry'), 'missing': MISSING}
    assert set(ids) == set(EDITOR_PARENTS)
    if editor == 'other_admission':
        admission = jsjson.parse((tree / ADMISSION_POINTER).read_text(encoding='utf-8'))
        admission['sha256'] = digest('another mask')
        write(tree, ADMISSION_POINTER, admission)
        write(tree, admission['path'], 'another mask')
    elif editor == 'no_script':
        (tree / WORKER_SCRIPT).unlink()
    elif editor == 'no_code':
        (tree / EDITOR_CODE).unlink()
    elif editor == 'code_dir':
        (tree / EDITOR_CODE).unlink()
        (tree / EDITOR_CODE).mkdir()
    elif editor == 'no_library':
        for path in ('results/v2/local_app_jobs', 'results/v2/design_evaluation_jobs', 'results/v2/campaigns',
                     'webapp/public/data'):
            shutil.rmtree(tree / path)
        for path in ('results/v2/current_strict_area_budget_study.json',
                     'results/v2/historical_strict_area_budget_study.json'):
            (tree / path).unlink()
    return {'root': root, 'tree': str(tree), 'ids': ids}


def build_editor_roots(base: Path) -> dict[str, dict]:
    """Every root of ``EDITOR_ROOTS`` under ``base``, by name."""
    return {name: editor_root(base / name, **options) for name, options in EDITOR_ROOTS.items()}


def parent_records(root: str, ids: dict[str, str], python: Optional[str] = None,
                   env: Optional[dict] = None) -> dict[str, Any]:
    """``Library.get`` of every parent, by name, on a fresh library of the root as ``LocalComputeQueue`` configures
    it (``python``, and ``env`` for ``EEG_COMPUTE_PYTHON``; the radius records' ``compatible`` depends on it)."""
    config = runtime_config(root, python, env={} if env is None else env)
    library = Library(config.repository_root, config)
    return {name: library.get(id) for name, id in ids.items()}


def parent_digests(root: str, ids: dict[str, str], python: Optional[str] = None,
                   env: Optional[dict] = None) -> dict[str, Optional[str]]:
    """The digest an ``evaluate`` request carries for each parent (``None`` where there is no record)."""
    return {name: None if record is None else jsjson.sha256_hex(record)
            for name, record in parent_records(root, ids, python, env).items()}


# --- Requests and results ----------------------------------------------------------------------------------------

METRICS = {'field_relative': 0.8, 'field_absolute': 0.7, 'sensitivity_tail': 0.4, 'localization_relative': 0.3,
           'median_mm': 20, 'p90_mm': 40, 'conditional_global': 0.3}


def prepare(parent_id: str) -> dict:
    return {'action': 'prepare', 'parent_id': parent_id}


def evaluate(parent_id: str, parent_digest: Optional[str], disabled: tuple = ()) -> dict:
    """A canonical ``evaluate`` request with the given slots switched off."""
    return {'action': 'evaluate', 'parent_id': parent_id, 'parent_digest': parent_digest or STALE, 'seed': 2026,
            'slots': [{'bank_index': i, 'enabled': i not in disabled} for i in range(64)]}


def prepare_result(request: dict, region_count: int = 2, **members: Any) -> dict:
    """A preparation result ``validateEditorResult`` accepts: the parent's echo and its regions' slots."""
    labels = [i % region_count for i in range(64)]
    result = {'schema': 'electrode-editor/1', 'status': 'completed', 'request': request,
              'parent': {'id': request['parent_id'], 'region_count': region_count},
              'original_indices': list(range(64)),
              'regions': [{'bank_indices': [i for i in range(64) if labels[i] == r],
                           'xyz_mm': [GRID[i] for i in range(64) if labels[i] == r]} for r in range(region_count)]}
    result.update(members)
    return result


def evaluate_result(request: dict, **members: Any) -> dict:
    """An evaluation result ``validateEditorResult`` accepts (check-electrode-editor.mjs ``result``, for the active
    slots of ``request``)."""
    active = [i for i, slot in enumerate(request['slots']) if slot['enabled']]
    result = {'schema': 'electrode-editor/1', 'status': 'completed', 'request': request,
              'electrode_count': len(active), 'active_regions': 2, 'parent_label': '2区 · PL + PR · 半径≤35 mm',
              'active_slots': active, 'evaluated_xyz_mm': [GRID[i] for i in active],
              'region_indices': [i % 2 for i in active], 'minimum_distance_mm': 6,
              'baseline': METRICS, 'parent_metrics': METRICS, 'edited_metrics': METRICS}
    result.update(members)
    return result


# --- A stand-in worker ---------------------------------------------------------------------------------------------

FAKE_WORKER = r'''import json
import os
import sys
import time

data = json.loads(sys.stdin.read())
request, parent = data['request'], data['parent']
mode = 'done'
if os.path.exists('editor-mode.txt'):
    with open('editor-mode.txt', encoding='utf-8') as handle:
        mode = handle.read().strip()
print(json.dumps({'type': 'progress', 'progress': 0.25, 'message': '读取父布局'}), flush=True)
if mode == 'fail':
    print(json.dumps({'type': 'error', 'message': '编辑评价失败'}), flush=True)
    sys.stderr.write('Traceback: boom\n')
    sys.exit(1)
if mode == 'hold':
    time.sleep(%(hold)d)
layout = parent['layout']
labels, xyz = layout['regionIndices'], layout['xyzMm']
if request['action'] == 'prepare':
    regions = parent['region_count']
    result = {'schema': 'electrode-editor/1', 'status': 'completed', 'request': request,
              'parent': {'id': parent['id'], 'region_count': regions, 'label': parent['label']},
              'original_indices': list(range(64)),
              'regions': [{'bank_indices': [i for i in range(64) if labels[i] == r],
                           'xyz_mm': [xyz[i] for i in range(64) if labels[i] == r]} for r in range(regions)]}
else:
    metrics = json.loads(%(metrics)r)
    active = [i for i, slot in enumerate(request['slots']) if slot['enabled']]
    result = {'schema': 'electrode-editor/1', 'status': 'completed', 'request': request,
              'electrode_count': len(active), 'active_regions': len({labels[i] for i in active}),
              'parent_label': parent['label'], 'active_slots': active,
              'evaluated_xyz_mm': [xyz[i] for i in active], 'region_indices': [labels[i] for i in active],
              'minimum_distance_mm': 6, 'baseline': metrics, 'parent_metrics': metrics, 'edited_metrics': metrics}
if mode == 'stale':
    result['request'] = dict(request, parent_id='f' * 64)
print(json.dumps({'type': 'progress', 'progress': 0.75, 'message': '写入编辑结果'}), flush=True)
sys.stderr.write('editor stderr\n')
print(json.dumps({'type': 'result', 'result': result}, ensure_ascii=False), flush=True)
''' % {'hold': HOLD, 'metrics': jsjson.stringify(METRICS)}


def worker_root(directory: Path, **options: Any) -> dict:
    """An editor root whose ``scripts/electrode_editor.py`` is ``FAKE_WORKER``."""
    built = editor_root(directory, **options)
    Path(built['tree'], WORKER_SCRIPT).write_text(FAKE_WORKER, encoding='utf-8')
    return built


# --- The parity cases ----------------------------------------------------------------------------------------------

CASE_IDS = ('prepare-done', 'evaluate-done', 'refusals', 'worker-failure', 'spawn-throws', 'invalid-result',
            'identity-changed', 'timeout', 'cancel', 'output-limit', 'publish-once', 'lookups')


def catalog(directory: Path) -> dict:
    """The base root's parents as every case root has them: ids, digests (``python3``, as the cases configure),
    region counts and the radius cache texts, from a root built under ``directory``."""
    built = editor_root(directory)
    ids = built['ids']
    texts = {name: (Path(built['tree']) / cache_path(ids[name])).read_text(encoding='utf-8')
             for name in CACHE_REQUESTS}
    return {'ids': ids, 'digests': parent_digests(built['root'], ids, 'python3', dict(os.environ)), 'texts': texts}


def _invalid_results(ids: dict, digests: dict) -> list:
    """Results ``validateEditorResult`` refuses, one round per check and per V8 ``TypeError``, then the odd values
    it accepts; every evaluation round has its own request, so a result it accepts never makes a later round a hit."""
    p = prepare(ids['cache'])
    base = prepare_result(p)
    region = base['regions'][0]
    rounds: list = [
        _round(p, None),  # no result event
        _round(p, None)[:1] + [['stdout', b64(line({'type': 'result', 'result': None}))], ['close', 0, None],
                               ['settle'], ['view']],
        _round(p, {**base, 'schema': 'electrode-editor/2'}),
        _round(p, {**base, 'status': 'failed'}),
        _round(p, {**base, 'request': prepare(ids['strict'])}),
        _round(p, {k: v for k, v in base.items() if k != 'parent'}),
        _round(p, {**base, 'parent': {'id': ids['strict'], 'region_count': 2}}),
        _round(p, {**base, 'original_indices': list(range(63))}),
        _round(p, {k: v for k, v in base.items() if k != 'original_indices'}),
        _round(p, {**base, 'regions': base['regions'][:1]}),
        _round(p, {k: v for k, v in base.items() if k != 'regions'}),
        _round(p, {**base, 'parent': {'id': ids['cache'], 'region_count': '2'}}),
        _round(p, {**base, 'regions': [{**region, 'bank_indices': []}, base['regions'][1]]}),
        _round(p, {**base, 'regions': [{**region, 'xyz_mm': region['xyz_mm'][1:]}, base['regions'][1]]}),
        _round(p, {**base, 'regions': [{'bank_indices': region['bank_indices']}, base['regions'][1]]}),
        _round(p, {**base, 'regions': [None, base['regions'][1]]}),  # V8's TypeError
        _round(p, {**base, 'regions': {'length': 2}}),  # r.regions.some is not a function
    ]
    # Each evaluation switches two slots off (62 active), so the counts below are one short or one over.
    changes: tuple[Callable[[list], dict], ...] = (
        lambda active: {'electrode_count': 63}, lambda active: {'electrode_count': '62'},
        lambda active: {'evaluated_xyz_mm': GRID[:61]}, lambda active: {'active_slots': active[:61]},
        lambda active: {'region_indices': [0] * 63}, lambda active: {'active_slots': active[::-1]},
        lambda active: {'minimum_distance_mm': 3.9}, lambda active: {'minimum_distance_mm': '6'},
        lambda active: {'minimum_distance_mm': None},
        lambda active: {'evaluated_xyz_mm': [[0, 0]] + GRID[1:62]},
        lambda active: {'evaluated_xyz_mm': [[0, 0, '1']] + GRID[1:62]},
        lambda active: {'evaluated_xyz_mm': [None] + GRID[1:62]},  # V8's TypeError
        lambda active: {'baseline': None},
        lambda active: {'parent_metrics': {k: v for k, v in METRICS.items() if k != 'field_absolute'}},
        lambda active: {'edited_metrics': {**METRICS, 'field_relative': '0.8'}},
        lambda active: {'edited_metrics': {**METRICS, 'median_mm': '20'}},
        lambda active: {'baseline': {**METRICS, 'sensitivity_tail': [0.4]}},
        lambda active: {'edited_metrics': {**METRICS, 'conditional_global': 0.8}},
        lambda active: {'parent_metrics': {**METRICS, 'localization_relative': None}},
        lambda active: {'edited_metrics': {**METRICS, 'conditional_global': None}},
        lambda active: {'edited_metrics': {**METRICS, 'conditional_global': '0.3'}},
    )
    for index, change in enumerate(changes):
        request = evaluate(ids['cache'], digests['cache'], (62 + index % 2, index))
        active = [i for i, slot in enumerate(request['slots']) if slot['enabled']]
        rounds.append(_round(request, evaluate_result(request, **change(active))))
    # What the checks let through: null scores with a null decision score, and a string whose length matches.
    for index, change in enumerate((
            {'edited_metrics': {**METRICS, 'localization_relative': None, 'conditional_global': None,
                                'median_mm': None, 'p90_mm': None}},
            {'minimum_distance_mm': 4})):
        request = evaluate(ids['cache'], digests['cache'], (40 + index,))
        rounds.append(_round(request, evaluate_result(request, **change)))
    rounds.append(_round(p, {**base, 'regions': [{'bank_indices': 'abc', 'xyz_mm': [[0, 0, 0]] * 3},
                                                 base['regions'][1]]}))
    return [step for steps in rounds for step in steps]


def parity_cases(base: Path, parents: dict) -> list[dict]:
    """The cases of the run-path parity; each root is ``base/<id>/tree``, an ``editor_root`` built for the Node run.
    ``parents`` is ``catalog``'s."""
    ids, digests, texts = parents['ids'], parents['digests'], parents['texts']
    cases: list[dict] = []

    def case(id: str, steps: list, *, timeout_ms: int = 3000, throw: Optional[str] = None) -> None:
        cases.append({'id': id, 'directory': str(base / id), 'root': str(base / id / 'tree'), 'python': 'python3',
                      'timeoutMs': timeout_ms, 'throw': throw, 'clock': CLOCK, 'steps': steps})

    p, strict = prepare(ids['cache']), prepare(ids['strict'])
    e = evaluate(ids['cache'], digests['cache'])
    other = evaluate(ids['cache'], digests['cache'], (0, 63))
    done = prepare_result(p)
    case('prepare-done', [
        ['submit', p], ['view'], ['pid'], ['jobs'], ['submit', p], ['submit', strict],
        *(step for chunk in _progress_lines() for step in (['stdout', chunk], ['view'])),
        *(['stderr', chunk] for chunk in _stderr_chunks()),
        odd_result_line(done), ['close', 0, None], ['view'], ['settle'], ['view'], ['jobs'],
        # A hit has no context: the view's parent digest is the digest of the result's parent echo.
        ['submit', p], ['view'], ['jobs'], ['lookup', p], ['lookup', strict], ['lookup', e], ['lookup', {}],
        ['lookup', {**p, 'seed': 2026}], ['submit', {**p, 'parent_id': 'C' * 64}], ['jobs'],
        ['restart', {}], ['lookup', p], ['submit', p], ['jobs'],
        ['restart', {'throw': 'expected new calculation'}], ['change', WORKER_SCRIPT, 'changed editor'],
        ['lookup', p], ['submit', p], ['settle'], ['view'],
    ])
    # The canonical request: slot members in another order and numbers written as floats give the same key.
    spelled = {**e, 'seed': 2026.0, 'slots': [{'enabled': s['enabled'], 'bank_index': float(s['bank_index'])}
                                              for s in e['slots']]}
    evaluations = []
    for name in ('strict', 'strict-2', 'strict-null-localization', 'cache-prior', 'cache-other-code'):
        prepared, evaluated = prepare(ids[name]), evaluate(ids[name], digests[name], (5,))
        evaluations += [*_round(prepared, prepare_result(prepared, REGIONS[name])),
                        *_round(evaluated, evaluate_result(evaluated))]
    case('evaluate-done', [
        ['submit', e], result_line(evaluate_result(e)), ['close', 0, None], ['settle'], ['view'],
        # A hit: the view's parent digest is the result request's.
        ['submit', e], ['view'], ['lookup', e], ['lookup', spelled], ['submit', spelled], ['view'],
        *_round(other, evaluate_result(other)), *evaluations,
    ])
    refused = []
    for name in ('missing', 'historical', 'offline', 'design', 'strict-no-layout', 'cache-unpatched',
                 'cache-zero-patches', 'cache-no-layout', 'cache-spatial', 'cache-geometry', 'cache-admission'):
        refused += [['submit', prepare(ids[name])], ['lookup', prepare(ids[name])]]
    case('refusals', [
        *refused,
        # Each check in Node's order: the record, the noise model, the digest.
        ['submit', evaluate(ids['cache'], STALE)], ['lookup', evaluate(ids['cache'], STALE)],
        ['submit', evaluate(ids['cache-spatial'], STALE)], ['submit', evaluate(ids['missing'], STALE)],
        ['submit', evaluate(ids['cache-geometry'], digests['cache-geometry'])],
        # The protocol's own refusals.
        ['submit', {**p, 'seed': 2026}], ['submit', {**e, 'seed': 2027}], ['submit', {**e, 'slots': e['slots'][1:]}],
        ['submit', evaluate(ids['cache'], digests['cache'], tuple(range(63)))], ['submit', {'action': 'other'}],
        ['submit', None], ['lookup', []], ['jobs'],
        # The strict report rewritten in place (same size and times): the library keeps what it read, the input
        # digest does not.
        ['lookup', strict], ['tamper', REPORT, tampered_report()], ['submit', strict], ['lookup', strict],
        ['submit', evaluate(ids['strict'], digests['strict'])], ['jobs'],
    ])
    case('worker-failure', [
        ['submit', p], ['stderr', b64('Traceback (most recent call last):\n  ValueError: 失败\n')],
        ['stdout', b64(line({'type': 'error', 'code': 'compute_error', 'message': '失败'}))],
        ['close', 1, None], ['view'], ['settle'], ['view'],
        ['submit', p], ['error', 'spawn python3 EACCES'], ['error', 'spawn python3 ENOENT'],
        ['close', -2, None], ['settle'], ['view'],
        *_round(e, evaluate_result(e), (1, None)),
        ['submit', e], ['stdout', b64(line({'type': 'error', 'message': 7}))], ['close', None, 'SIGKILL'],
        ['settle'], ['view'],
    ])
    case('spawn-throws', [['submit', p], ['view'], ['settle'], ['view'], ['submit', e], ['jobs']],
         throw='spawn EINVAL')
    case('invalid-result', _invalid_results(ids, digests))
    moved = f'results/v2/local_app_jobs/{ids["cache-prior"]}'
    rewritten = texts['cache'].replace('"finished_at":"2026-11-01T08:00:00Z"',
                                       '"finished_at":"2026-11-01T08:00:00.000Z"')
    assert rewritten != texts['cache']
    case('identity-changed', [
        ['submit', p], ['change', WORKER_SCRIPT, 'changed editor'], result_line(done), ['close', 0, None],
        ['view'], ['settle'], ['view'],
        ['submit', p], ['change', EDITOR_CODE, 'changed code'], result_line(done), ['close', 0, None], ['settle'],
        ['view'],
        # A result the validator refuses fails as such, before the context is computed again.
        ['submit', p], ['change', EDITOR_CODE, 'changed again'], result_line(prepare_result(strict)),
        ['close', 0, None], ['settle'], ['view'],
        ['submit', p], result_line(done), ['close', 0, None], ['settle'], ['view'], ['lookup', p],
        # The parent record rewritten while its evaluation runs; the parent removed; the strict report rewritten.
        ['submit', e], ['change', cache_path(ids['cache']), rewritten], result_line(evaluate_result(e)),
        ['close', 0, None], ['settle'], ['view'], ['lookup', e],
        ['submit', prepare(ids['cache-prior'])], ['move', moved, 'moved'],
        result_line(prepare_result(prepare(ids['cache-prior']), 4)), ['close', 0, None], ['settle'], ['view'],
        ['submit', strict], ['tamper', REPORT, tampered_report()], result_line(prepare_result(strict, 1)),
        ['close', 0, None], ['settle'], ['view'], ['lookup', strict],
    ])
    case('timeout', [
        ['submit', p], ['stdout', b64(line({'type': 'progress', 'progress': 0.4, 'message': '几何'}))],
        ['wait_kill'], ['view'], ['stdout', b64(line({'type': 'progress', 'progress': 0.9, 'message': 'late'}))],
        result_line(done), ['close', None, 'SIGTERM'], ['settle'], ['view'],
    ], timeout_ms=TIMEOUT_CASE_MS)
    case('cancel', [
        ['submit', e], ['stdout', b64(line({'type': 'progress', 'progress': 0.3, 'message': '计算'}))],
        ['cancel', None], ['cancel', None], ['view'], ['submit', p],
        ['stdout', b64(line({'type': 'progress', 'progress': 0.8, 'message': 'late'}))],
        result_line(evaluate_result(e)), ['close', None, 'SIGTERM'], ['settle'], ['view'], ['cancel', None],
        ['submit', p], ['cancel', 'shutdown'], ['view'], ['close', 0, None], ['settle'], ['view'], ['lookup', p],
        ['lookup', e],
    ])
    started = line({'type': 'progress', 'progress': 0.2, 'message': '开始'})
    case('output-limit', [
        ['submit', p], ['stdout', b64(started)], ['stdout_fill', MAX_OUTPUT_BYTES - len(started)], ['view'],
        ['stdout_fill', 1], ['view'], ['close', None, 'SIGTERM'], ['settle'], ['view'],
    ])
    case('publish-once', [
        # Another workspace published a valid result first: Python keeps it (B16), Node replaces it.
        ['submit', p], ['write_cache', 'valid', done], result_line(done), ['close', 0, None], ['settle'],
        ['view'], ['lookup', p], ['submit', p], ['view'],
        # Files that are not a valid result for the job are replaced on both hosts.
        ['submit', e], ['write_cache', 'text', 'not json'], result_line(evaluate_result(e)), ['close', 0, None],
        ['settle'], ['view'], ['lookup', e],
        ['submit', other], ['write_cache', 'tampered', evaluate_result(other)], ['lookup', other],
        result_line(evaluate_result(other)), ['close', 0, None], ['settle'], ['view'], ['lookup', other],
    ])
    case('lookups', [
        ['lookup', p], ['lookup', e], ['lookup', prepare(ids['missing'])], ['lookup', evaluate(ids['cache'], STALE)],
        ['lookup', prepare(ids['cache-spatial'])], ['lookup', {'action': 'prepare'}],
        *_round(p, done), ['lookup', p], ['lookup', strict], ['lookup', e],
        ['deny_cache'], ['lookup', p], ['submit', p], ['allow_cache'], ['lookup', p], ['submit', p], ['view'],
    ])
    assert tuple(c['id'] for c in cases) == CASE_IDS
    return cases


def build(case: dict) -> None:
    """Builds the case's root (again, at the same path, for the second run; Node's is ``root.node`` by then)."""
    if Path(case['root']).exists():
        shutil.rmtree(case['root'])
    built = editor_root(Path(case['directory']))
    assert built['root'] == case['root']


# --- Runs ----------------------------------------------------------------------------------------------------------

async def run_case(item: dict) -> dict:
    """The Python side of one case: ``EditorJobs`` on the root's ``Library`` driven by the steps the Node driver
    runs."""
    clock, ids = PinnedClock(**item['clock']), PinnedIds()
    records: list[list[str]] = []
    children: list[FakeChild] = []

    def make(options: dict) -> EditorJobs:
        thrown = options['throw'] if 'throw' in options else item['throw']
        runtime = runtime_config(item['root'], item['python'])
        return EditorJobs(runtime.repository_root, runtime.native_python, Library(runtime.repository_root, runtime),
                          timeout_ms=item['timeoutMs'], spawn=Spawner(thrown, children), clock=clock,
                          random_uuid=ids)

    jobs, current = make({}), None

    async def record(kind: str, run: Callable[[], Any]) -> Any:
        try:
            value = run()
            if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
                value = await value
            records.append([kind, jsjson.stringify(value)])
            return value
        except Exception as error:  # noqa: BLE001 - recorded as Node records a throw
            records.append([kind, jsjson.stringify({'error': _message(error)})])
            return None

    for kind, *args in item['steps']:
        child = children[-1] if children else None
        if kind == 'submit':
            value = await record(kind, lambda: jobs.submit(args[0]))
            if isinstance(value, dict) and 'job' in value:
                current = value['job']['id']
        elif kind == 'lookup':
            await record(kind, lambda: jobs.lookup(args[0]))
        elif kind == 'view':
            await record(kind, lambda: jobs.view(jobs.jobs[current]))
        elif kind == 'jobs':
            await record(kind, lambda: list(jobs.jobs))
        elif kind == 'pid':
            await record(kind, jobs.active_pid)
        elif kind == 'cancel':
            await record(kind, lambda: jobs.cancel(current) if args[0] is None else jobs.cancel(current, args[0]))
        elif kind == 'restart':
            jobs.dispose()
            jobs = make(args[0])
        elif kind == 'stdout':
            child.stdout(base64.b64decode(args[0]))
        elif kind == 'stdout_fill':
            child.stdout(b' ' * args[0])
        elif kind == 'stderr':
            child.stderr(base64.b64decode(args[0]))
        elif kind == 'error':
            child.error(args[0])
        elif kind == 'close':
            child.close(args[0], args[1])
        elif kind == 'wait_kill':
            await until(lambda: bool(children[-1].kills), SETTLE)
        elif kind == 'settle':
            await until(lambda: jobs.active is None, SETTLE)
        elif kind == 'write_cache':
            job = jobs.jobs[current]
            body = args[1] if args[0] == 'text' else jsjson.stringify({
                'key': job.key, 'identity': job.ctx['identity'], 'result': args[1],
                'result_sha256': jsjson.sha256_hex(args[1] if args[0] == 'valid' else 'tampered'),
                'finished_at': '2026-01-01T00:00:00.000Z'})
            Path(job.directory, 'cache.json').write_bytes(body.encode('utf-8'))
        elif kind in ('deny_cache', 'allow_cache'):
            os.chmod(os.path.join(jobs.jobs[current].directory, 'cache.json'), 0 if kind == 'deny_cache' else 0o600)
        elif kind == 'change':
            Path(item['root'], args[0]).write_bytes(args[1].encode('utf-8'))
        elif kind == 'tamper':
            path = Path(item['root'], args[0])
            before = path.stat()
            path.write_bytes(args[1].encode('utf-8'))
            if path.stat().st_size != before.st_size:
                raise AssertionError('tamper changed the size')
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        elif kind == 'move':
            os.rename(os.path.join(item['root'], args[0]), os.path.join(item['root'], args[1]))
        else:
            raise ValueError(f'unknown step {kind}')
    await until(lambda: jobs.active is None, SETTLE)
    jobs.dispose()
    return {
        'id': item['id'], 'records': records, 'clock': clock.calls, 'ids': ids.count,
        'children': [{
            'executable': c.executable, 'args': c.args, 'cwd': c.options['cwd'], 'stdio': c.options['stdio'],
            'detached': c.options['detached'], 'shell': c.options['shell'],
            'env': {name: c.options['env'].get(name) for name in WORKER_ENV},
            'inherits': all(name in WORKER_ENV or c.options['env'].get(name) == value
                            for name, value in os.environ.items()),
            'added': sorted(name for name in c.options['env'] if name not in os.environ and name not in WORKER_ENV),
            'input': b64(b''.join(c.inputs)), 'kills': c.kills,
        } for c in children],
    }


def run_python(case: dict) -> dict:
    return asyncio.run(run_case(case))


def run_node(spec: dict, scratch: Path, name: str = 'editor') -> dict:
    """Runs ``parity/editor_run.mjs`` once over ``spec`` (its header documents the members); the queue directory is
    only resolved, never created."""
    queue = scratch / 'node-queue'
    spec_path, out_path = scratch / f'{name}-spec.json', scratch / f'{name}-node.json'
    spec_path.write_text(jsjson.stringify({'queueDirectory': str(queue), **spec}), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV,
                   timeout=600)
    assert not queue.exists()
    return json.loads(out_path.read_text(encoding='utf-8'))


def run_node_cases(cases: list[dict], scratch: Path) -> dict:
    """Node's ``ElectrodeEditorService`` over every run-path case once."""
    keep = ('id', 'root', 'python', 'timeoutMs', 'throw', 'clock', 'steps')
    return run_node({'mode': 'runs', 'cases': [{k: case[k] for k in keep} for case in cases]}, scratch, 'editor-run')
