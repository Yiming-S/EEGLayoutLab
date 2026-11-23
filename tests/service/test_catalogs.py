"""The read-only catalogs of phase 2 slice 3 equal Node's: the editor's saved evaluations and parent layouts
(``eeglayoutlab.jobs.editor_records``: ``ElectrodeEditorService.records``, ``parents`` and ``validateEditorResult``),
the signal-simulation layouts (``reception_records.reception_layouts``: ``receptionLayouts``) and the head packages
(``eeglayoutlab.jobs.design_heads``: ``DesignEvaluationService.heads``).

- Unit tests on synthetic roots built with tests/service/library_support.py plus editor records, radius caches with
  saved region patches and head packages: which rows each catalog offers, the order, and the errors that propagate.
- Parity: ``CATALOG_DRIVER`` runs Node's own ``LocalComputeQueue``, ``ElectrodeEditorService``,
  ``DesignEvaluationService`` and ``receptionLayouts`` over the same roots (one thread-pool worker, a queue directory
  that is never created) and ``validateEditorResult`` over a table of results. The editor records and the heads
  must be equal text (also for 2 to 70 rows whose stamps make V8's sort throw or not, Python sorting with the
  running Node's limit, ``library_support.sorting_as_node``: rows that Node 26 sorts by binary insertion alone and
  older Node does not); the parents and layouts are compared as sets of record texts plus the ``finished_at`` order
  (Node sorts the library's labels with ``localeCompare``), the layouts' saved evaluations in Node's order, and the
  rest of the documents as text. Failures compare by Node's code where the error has one, else by message.
- With ``EEG_KEY_PARITY_ROOT`` (marked ``data_bundle``) the same comparison runs on that installation. Nothing is
  written under any root.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Optional

import pytest

from schema_parity_support import require

require('pydantic')

from eeglayoutlab.jobs import jssort  # noqa: E402
from eeglayoutlab.jobs.design_heads import heads  # noqa: E402
from eeglayoutlab.jobs.editor_records import (  # noqa: E402
    EditorResultError, parents, records, validate_editor_result,
)
from eeglayoutlab.jobs.identity import JSTypeError, request_key  # noqa: E402
from eeglayoutlab.jobs.library import Library  # noqa: E402
from eeglayoutlab.jobs.radius import RadiusCache  # noqa: E402
from eeglayoutlab.jobs.reception_records import reception_layouts  # noqa: E402
from eeglayoutlab.jobs.records import RecordError, RecordStore  # noqa: E402
from eeglayoutlab.jobs.runtime import runtime_config  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402

from .key_parity_support import NODE_ENV, PRIOR, SPATIAL, needs_node  # noqa: E402
from .library_support import (  # noqa: E402
    WEBAPP, attempt, code_tree, forward_inputs, library_root, node_failure, node_generation, offline_datasets,
    radius_result, sha, sorting_as_node, write, write_cache,
)

ROOT = Path(__file__).resolve().parents[2]
EDITOR_JOBS = 'results/v2/electrode_editor_jobs'

# --- Editor records ----------------------------------------------------------------------------------------------

PARENT = sha('parent layout')
METRICS = {'field_relative': 0.8, 'field_absolute': 0.7, 'sensitivity_tail': 0.4, 'localization_relative': 0.3,
           'median_mm': 20, 'p90_mm': 40, 'conditional_global': 0.3}
EDITOR_IDENTITY = {'schema': 'electrode-editor-cache/1', 'parent_digest': sha('parent digest'), 'threads': 1}
FINISHED = '2026-10-01T10:00:00.000Z'
ABSENT = object()  # a member left out of a written file (``None`` writes ``null``)


def editor_request(disabled: tuple = (), parent: str = PARENT) -> dict:
    """A canonical ``evaluate`` request (``normalizeEditorRequest``) with the given slots switched off."""
    return {'action': 'evaluate', 'parent_id': parent, 'parent_digest': sha('parent digest'), 'seed': 2026,
            'slots': [{'bank_index': i, 'enabled': i not in disabled} for i in range(64)]}


def editor_result(request: dict, **patch: Any) -> dict:
    """A worker result ``validateEditorResult`` accepts (check-electrode-editor.mjs ``result``)."""
    active = [i for i, slot in enumerate(request['slots']) if slot['enabled']]
    result = {'schema': 'electrode-editor/1', 'status': 'completed', 'request': request,
              'electrode_count': len(active), 'active_regions': 2, 'parent_label': '2区 · PL + PR · 半径≤35 mm',
              'active_slots': active, 'evaluated_xyz_mm': [[i * 5, 0, 0] for i in active],
              'region_indices': [int(i >= 32) for i in active], 'minimum_distance_mm': 5,
              'baseline': METRICS, 'parent_metrics': METRICS, 'edited_metrics': METRICS}
    result.update(patch)
    return result


def prepare_result(request: dict) -> dict:
    xyz = [[i * 5, 0, 0] for i in range(64)]
    return {'schema': 'electrode-editor/1', 'status': 'completed', 'request': request,
            'parent': {'id': request['parent_id'], 'region_count': 2},
            'original_indices': list(range(64)),
            'regions': [{'bank_indices': list(range(32 * r, 32 * r + 32)), 'xyz_mm': xyz[32 * r:32 * r + 32]}
                        for r in range(2)]}


def write_editor(root: Path, result: dict, *, identity: Any = EDITOR_IDENTITY, finished_at: Any = FINISHED,
                 change: Optional[Callable[[dict], None]] = None, key: Optional[str] = None) -> str:
    """An editor ``cache.json`` as Node's ``finish`` writes it (``ABSENT`` leaves a member out); ``change`` edits the
    cache before it is written. Returns its key."""
    if key is None:
        key = (jsjson.sha256_hex({'request': result['request']}) if identity is ABSENT
               else request_key(result['request'], identity))
    cache: dict[str, Any] = {'key': key}
    if identity is not ABSENT:
        cache['identity'] = identity
    cache.update({'result': result, 'result_sha256': jsjson.sha256_hex(result)})
    if finished_at is not ABSENT:
        cache['finished_at'] = finished_at
    if change is not None:
        change(cache)
    write(root, f'{EDITOR_JOBS}/{key}/cache.json', cache)
    return key


def editor_records(root: Path, outside: Path) -> dict[str, str]:
    """Saved editor evaluations: valid ones (two at the same time, one without identity, one without the optional
    members), a preparation, and records that fail each check or cannot be read."""
    keys = {
        'newest': write_editor(root, editor_result(editor_request()), finished_at='2026-10-03T10:00:00.000Z'),
        'older': write_editor(root, editor_result(editor_request(tuple(range(8))))),
        'tie': write_editor(root, editor_result(editor_request((0, 63)))),
        'no-identity': write_editor(root, editor_result(editor_request((5,))), identity=ABSENT,
                                    finished_at='2026-10-02T10:00:00.000Z'),
    }
    bare = editor_result(editor_request((6,)))
    del bare['parent_label'], bare['active_regions']
    keys['bare'] = write_editor(root, bare, finished_at='2026-10-02T11:00:00.000Z')
    prepare = {'action': 'prepare', 'parent_id': PARENT}
    keys['prepare'] = write_editor(root, prepare_result(prepare))

    def stale(cache: dict) -> None:
        cache['result_sha256'] = sha('stale')

    def other_identity(cache: dict) -> None:
        cache['identity'] = {**EDITOR_IDENTITY, 'threads': 2}

    def other_key(cache: dict) -> None:
        cache['key'] = sha('another key')

    keys['checksum'] = write_editor(root, editor_result(editor_request((9,))), change=stale)
    keys['identity'] = write_editor(root, editor_result(editor_request((10,))), change=other_identity)
    keys['key'] = write_editor(root, editor_result(editor_request((11,))), change=other_key)
    keys['count'] = write_editor(root, editor_result(editor_request((12,)), electrode_count=64))
    keys['score'] = write_editor(root, editor_result(editor_request((13,)),
                                                     edited_metrics={**METRICS, 'conditional_global': 0.8}))
    keys['slots'] = write_editor(root, editor_result(editor_request((14,)),
                                                     active_slots=[1] * 63))
    keys['null'] = sha('null editor cache')
    write(root, f'{EDITOR_JOBS}/{keys["null"]}/cache.json', 'null')
    keys['malformed'] = sha('malformed editor cache')
    write(root, f'{EDITOR_JOBS}/{keys["malformed"]}/cache.json', '{broken')
    keys['missing'] = sha('editor directory without a cache')
    (root / EDITOR_JOBS / keys['missing']).mkdir()
    keys['unreadable'] = write_editor(root, editor_result(editor_request((15,))))
    unreadable = root / EDITOR_JOBS / keys['unreadable'] / 'cache.json'
    if os.geteuid() != 0:
        unreadable.chmod(0)
    else:
        unreadable.unlink()
    # A cache that links out of the root, and a key directory that is itself a link: neither is read.
    linked = outside / 'editor-cache.json'
    linked.parent.mkdir(parents=True, exist_ok=True)
    key = request_key(editor_request((16,)), EDITOR_IDENTITY)
    write_editor(outside, editor_result(editor_request((16,))), key=key)
    linked.write_bytes((outside / EDITOR_JOBS / key / 'cache.json').read_bytes())
    keys['linked-cache'] = key
    (root / EDITOR_JOBS / key).mkdir()
    (root / EDITOR_JOBS / key / 'cache.json').symlink_to(linked)
    keys['linked-directory'] = request_key(editor_request((17,)), EDITOR_IDENTITY)
    target = write_editor(outside, editor_result(editor_request((17,))))
    (root / EDITOR_JOBS / keys['linked-directory']).symlink_to(outside / EDITOR_JOBS / target)
    (root / EDITOR_JOBS / 'not-a-key').mkdir()
    return keys


VALID_EDITOR = ('newest', 'bare', 'no-identity', 'older', 'tie')

# --- Radius caches with saved region patches ---------------------------------------------------------------------

PATCHED = {
    'patched': {'region_count': 2, 'radius_mm': 30, 'mode': 'preset', 'mask_codes': ['FL', 'FR']},
    'patched-noise': {'region_count': 2, 'radius_mm': 30, 'mode': 'low_hair', 'noise_model': SPATIAL},
    'patched-prior': {'region_count': 3, 'radius_mm': 30, 'mode': 'whole_surface', 'data_prior': PRIOR},
    'patched-other-code': {'region_count': 4, 'radius_mm': 30, 'mode': 'whole_surface'},
}


def patched_result(request: dict, provenance: dict) -> dict:
    result = radius_result(request, provenance)
    regions = request['region_count']
    result['layout']['regionPatchVertexIndices'] = [[k * 10 + j for j in range(3)] for k in range(regions)]
    result['layout']['regionAreasCm2'] = [12.5] * regions
    return result


def patched_caches(root: Path, provenance: dict, python: str) -> dict[str, str]:
    """Radius caches whose layouts carry region patches: compatible, under a noise model, with a data prior and
    under another code identity."""
    radius = RadiusCache(str(root), python)
    code = radius.get_identity()
    keys = {}
    for index, (name, request) in enumerate(PATCHED.items()):
        other = {**code, 'retired.py': sha('old')} if name == 'patched-other-code' else code
        keys[name] = radius.identity_for(request, other)[1]
        write_cache(root, keys[name], request, patched_result(request, provenance), f'2026-11-0{index + 1}T08:00:00Z')
    return keys


# --- Head packages -----------------------------------------------------------------------------------------------

def head_package(root: Path, head_id: str, *, skip: tuple = (), manifest: str = 'manifest',
                 package: Any = None) -> None:
    """A head package as check-design-decision.mjs ``headPackage`` writes it."""
    table = f'results/v2/heads/{head_id}/table/{"h" * 64}'
    files = {'package.json': package if package is not None else {'head_id': head_id,
                                                                     'dataset': {'name': 'IXI', 'subject': head_id}},
             'scalp.npz': 'scalp', 'admissibility.npz': 'mask', 'sources.npz': 'sources', 'mapping.npz': 'mapping',
             'table.json': {'manifest_path': table + '/manifest.json', 'manifest_sha256': sha('manifest')}}
    for name, body in files.items():
        if name not in skip:
            write(root, f'results/v2/heads/{head_id}/{name}', body)
    for name, body in (('manifest.json', manifest), ('index.npz', 'index'), ('rows.npy', 'rows')):
        if name not in skip:
            write(root, f'{table}/{name}', body)


# --- Roots -------------------------------------------------------------------------------------------------------

def catalog_root(root: Path, outside: Path, python: str) -> dict:
    """The library's base root plus editor records, patched radius caches and two head packages."""
    keys = library_root(root, python)
    keys['patched'] = patched_caches(root, keys['provenance'], python)
    keys['editor'] = editor_records(root, outside)
    head_package(root, 'ixi002')
    head_package(root, 'ixi012', skip=('mapping.npz',))
    return keys


def sort_root(root: Path, finished: list) -> list[str]:
    """Valid editor records whose ``finished_at`` values, in key order, are ``finished``; returns their keys."""
    root.mkdir(parents=True)
    requests = [editor_request((index % 64,), parent=sha(f'sort parent {index}')) for index in range(len(finished))]
    keys = sorted((request_key(request, EDITOR_IDENTITY), request) for request in requests)
    for (key, request), finished_at in zip(keys, finished):
        write_editor(root, editor_result(request), finished_at=finished_at)
    return [key for key, _ in keys]


# The first two rows are compared as (a: row 1, b: row 0); only ``b`` must have a string stamp. Stamps of one format
# order alike by code units and by ICU (which puts ``-`` before ``,``, so ``['2026', 10]`` would not).
SORT_ROOTS = {
    'sort-b-undefined': [ABSENT, '2026-10-01T00:00:00.000Z'],
    'sort-a-undefined': ['2026-10-01T00:00:00.000Z', ABSENT],
    'sort-b-null': [None, '2026-10-01T00:00:00.000Z'],
    'sort-a-null': ['9', None],
    'sort-b-number': [5, '2026-10-01T00:00:00.000Z'],
    'sort-a-number': ['2026-10-01T00:00:00.000Z', 5],
    'sort-insertion': ['2026-10-02T00:00:00.000Z', '2026-10-01T00:00:00.000Z', '2026-10-03T00:00:00.000Z',
                       '2026-10-01T00:00:00.000Z', '2026-10-04T00:00:00.000Z', '2026-10-01T00:00:00.000Z'],
    'sort-insertion-undefined': ['2026-10-02T00:00:00.000Z', '2026-10-01T00:00:00.000Z', ABSENT,
                                 '2026-10-05T00:00:00.000Z'],
    'sort-run-undefined': ['2026-10-02T00:00:00.000Z', '2026-10-03T00:00:00.000Z', ABSENT],
    'sort-object': ['2026-10-02T00:00:00.000Z', {'toString': 'x'}],
    'sort-array': ['2026-10-02T00:00:00.000Z', ['2026-10-03T00:00:00.000Z']],
    # Node 26 sorts up to 7 rows by binary insertion alone, comparing (1, 0), then (2, 0): the bad row is never b.
    'sort-short-undefined': ['2026-10-03T00:00:00.000Z', ABSENT, '2026-10-01T00:00:00.000Z'],
    'sort-short-number': ['2026-10-02T00:00:00.000Z', '2026-10-05T00:00:00.000Z', 5, '2026-10-01T00:00:00.000Z',
                          '2026-10-04T00:00:00.000Z'],
}
SHORT_ROOTS = ('sort-short-undefined', 'sort-short-number')
SORT_OUTCOMES = {
    'sort-b-undefined': "Cannot read properties of undefined (reading 'localeCompare')",
    'sort-a-undefined': [1, 0],
    'sort-b-null': "Cannot read properties of null (reading 'localeCompare')",
    'sort-a-null': [1, 0],
    'sort-b-number': 'b.finished_at.localeCompare is not a function',
    'sort-a-number': [1, 0],
    'sort-insertion': [4, 2, 0, 1, 3, 5],
    'sort-insertion-undefined': "Cannot read properties of undefined (reading 'localeCompare')",
    'sort-run-undefined': [2, 1, 0],
    'sort-object': 'Cannot convert object to primitive value',
    'sort-array': [1, 0],
    'sort-short-undefined': [1, 0, 2],
    'sort-short-number': [2, 1, 4, 0, 3],
}
# 64 rows and more: V8 merges runs; with stamps of one format the order is the stable one.
MANY = [f'2026-10-{(index * 7) % 5 + 1:02d}T00:00:00.000Z' for index in range(70)]


def run_catalog_node(roots: list[dict], cases: list, scratch: Path) -> dict:
    """Runs ``CATALOG_DRIVER`` once over ``roots`` (``{id, root}``) and the ``validateEditorResult`` cases."""
    queue = scratch / 'node-queue'  # resolved by the queue, never created
    driver, spec_path, out_path = scratch / 'catalogs.mjs', scratch / 'catalogs-spec.json', scratch / 'catalogs.json'
    driver.write_text(CATALOG_DRIVER, encoding='utf-8')
    spec_path.write_text(jsjson.stringify({'webapp': str(WEBAPP), 'queueDirectory': str(queue), 'roots': roots,
                                           'validate': cases}), encoding='utf-8')
    subprocess.run(['node', str(driver), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV)
    assert not queue.exists()
    return json.loads(out_path.read_text(encoding='utf-8'))


CATALOG_DRIVER = r"""
// Node reference of tests/service/test_catalogs.py: for each root a fresh LocalComputeQueue (with a queue directory
// that is never created) and its editor and design services give the editor records and parents, the reception
// layouts and the head packages; then validateEditorResult runs over the cases.
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const [specPath, outPath] = process.argv.slice(2);
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const load = path => import(pathToFileURL(`${spec.webapp}/${path}`).href);
const { LocalComputeQueue } = await load('server/local-compute-server.mjs');
const { ElectrodeEditorService, validateEditorResult } = await load('server/electrode-editor-server.mjs');
const { DesignEvaluationService } = await load('server/design-evaluation-server.mjs');
const { receptionLayouts } = await load('server/reception-v2-support.mjs');
const failure = error => ({ ok: false, code: error?.code ?? null, name: error?.name ?? null,
  message: String(error?.message ?? error), status: error?.status ?? null });
async function attempt(run) {
  try { return { ok: true, value: await run() }; } catch (error) { return failure(error); }
}
const out = { roots: {}, validate: [] };
for (const item of spec.roots) {
  const queue = new LocalComputeQueue({ repositoryRoot: item.root, queueDirectory: spec.queueDirectory });
  const editor = new ElectrodeEditorService(queue), design = new DesignEvaluationService(queue);
  out.roots[item.id] = {
    records: await attempt(async () => JSON.stringify(await editor.records())),
    parents: await attempt(async () => JSON.stringify(await editor.parents())),
    layouts: await attempt(async () => JSON.stringify(await receptionLayouts(queue))),
    heads: await attempt(async () => JSON.stringify(await design.heads())),
  };
  editor.dispose(); design.dispose(); queue.dispose();
}
for (const [result, request] of spec.validate)
  out.validate.push(await attempt(() => { validateEditorResult(result, request); return null; }));
writeFileSync(outPath, JSON.stringify(out));
process.exit(0);
"""


def python_catalogs(root: str) -> dict:
    """The driver's entry for one root, computed with ``eeglayoutlab.jobs`` (one library, Node's call order)."""
    library = Library(root, runtime_config(root))
    return {
        'records': attempt(lambda: jsjson.stringify(records(library.store))),
        'parents': attempt(lambda: jsjson.stringify(parents(library))),
        'layouts': attempt(lambda: jsjson.stringify(reception_layouts(library))),
        'heads': attempt(lambda: jsjson.stringify(heads(library.root))),
    }


def python_validate(result: Any, request: Any) -> dict:
    def run() -> None:
        validate_editor_result(result, request)
    return attempt(run)


def _texts(rows: list) -> list[str]:
    return sorted(jsjson.stringify(row) for row in rows)


def _finished(rows: list) -> list:
    return [row.get('finished_at') for row in rows]


def assert_same_catalogs(node: dict, python: dict) -> None:
    for name in ('records', 'heads'):
        assert python[name] == node_failure(node[name]), name
    if not node['parents']['ok']:
        assert python['parents'] == node_failure(node['parents'])
    else:
        assert python['parents']['ok'], python['parents']
        mine, theirs = jsjson.parse(python['parents']['value']), jsjson.parse(node['parents']['value'])
        assert _texts(mine) == _texts(theirs)
        assert _finished(mine) == _finished(theirs)
    if not node['layouts']['ok']:
        assert python['layouts'] == node_failure(node['layouts'])
    else:
        assert python['layouts']['ok'], python['layouts']
        mine, theirs = jsjson.parse(python['layouts']['value']), jsjson.parse(node['layouts']['value'])
        mine_rows, theirs_rows = mine.pop('records'), theirs.pop('records')
        assert jsjson.stringify(mine) == jsjson.stringify(theirs)
        assert _texts(mine_rows) == _texts(theirs_rows)
        assert _finished(mine_rows) == _finished(theirs_rows)
        evaluations = [[jsjson.stringify(row) for row in rows if row['dataset_id'] == 'design_evaluation']
                       for rows in (mine_rows, theirs_rows)]
        assert evaluations[0] == evaluations[1]


# --- validateEditorResult cases ----------------------------------------------------------------------------------

def validation_cases() -> list[list]:
    """``[result, request]`` pairs: accepted ones, and each check failing (V8's TypeErrors included)."""
    request = editor_request((3, 40))
    good = editor_result(request)
    prepare = {'action': 'prepare', 'parent_id': PARENT}
    prepared = prepare_result(prepare)
    cases: list[list] = [[good, request], [prepared, prepare],
                         [editor_result(request, edited_metrics={**METRICS, 'sensitivity_tail': None,
                                                                 'conditional_global': None}), request],
                         [editor_result(request, baseline={**METRICS, 'p90_mm': None}), request]]

    def changed(**patch: Any) -> list:
        return [editor_result(request, **patch), request]

    cases += [[None, request], [[], request], [{**good, 'schema': 'electrode-editor/2'}, request],
              [{**good, 'status': 'failed'}, request], [good, editor_request((3,))],
              [{**good, 'request': dict(reversed(list(request.items())))}, request]]
    cases += [[{**good, 'request': None}, None], [{**good, 'request': {}}, {}],
              [{**good, 'request': {'slots': 'x' * 64}}, {'slots': 'x' * 64}],
              [{**good, 'request': {'slots': [None]}}, {'slots': [None]}]]
    cases += [changed(electrode_count=61), changed(electrode_count='62'), changed(evaluated_xyz_mm=None),
              changed(active_slots={'length': 62}), changed(region_indices='x' * 62),
              changed(active_slots=list(range(62))), changed(active_slots=[1, 0, 2, *range(4, 40), *range(41, 64)]),
              changed(minimum_distance_mm=0), changed(minimum_distance_mm=3.9999999), changed(minimum_distance_mm=True),
              changed(minimum_distance_mm='5'), changed(evaluated_xyz_mm='x' * 62),
              changed(evaluated_xyz_mm=[None] * 62), changed(evaluated_xyz_mm=['abc'] * 62),
              changed(evaluated_xyz_mm=[{'length': 3}] * 62), changed(evaluated_xyz_mm=[[0, 0]] * 62),
              changed(evaluated_xyz_mm=[[0, 0, '0']] * 62), changed(evaluated_xyz_mm=[5] * 62)]
    for name in ('baseline', 'parent_metrics', 'edited_metrics'):
        cases += [changed(**{name: None}), changed(**{name: 5}), changed(**{name: []}),
                  changed(**{name: {**METRICS, 'field_absolute': '0.7'}}),
                  changed(**{name: {key: value for key, value in METRICS.items() if key != 'median_mm'}}),
                  changed(**{name: {**METRICS, 'p90_mm': False}})]
    for name in ('parent_metrics', 'edited_metrics'):
        cases += [changed(**{name: {**METRICS, 'conditional_global': 0.8}}),
                  changed(**{name: {**METRICS, 'conditional_global': None}}),
                  changed(**{name: {**METRICS, 'sensitivity_tail': None}}),
                  changed(**{name: {key: value for key, value in METRICS.items() if key != 'conditional_global'}}),
                  changed(**{name: {**METRICS, 'conditional_global': 0.3 + 1e-11}}),
                  changed(**{name: {**METRICS, 'conditional_global': 0.3 + 1e-9}})]

    def prepared_with(**patch: Any) -> list:
        return [{**prepared, **patch}, prepare]

    cases += [prepared_with(parent={'id': sha('other'), 'region_count': 2}), prepared_with(parent=None),
              [{**prepared, 'parent': None, 'request': {'action': 'prepare'}}, {'action': 'prepare'}],
              prepared_with(original_indices='x' * 64), prepared_with(original_indices=list(range(63))),
              prepared_with(regions='ab'), prepared_with(regions=None), prepared_with(regions=[None, None]),
              prepared_with(regions=[{'bank_indices': [], 'xyz_mm': []}] * 2),
              prepared_with(regions=[{'bank_indices': [1, 2], 'xyz_mm': [[0, 0, 0]]}] * 2),
              prepared_with(regions=[{'bank_indices': 'ab', 'xyz_mm': 'cd'}] * 2),
              prepared_with(regions=[{'bank_indices': {'length': 2}, 'xyz_mm': [1, 2]}] * 2),
              prepared_with(regions=[5, 5]), prepared_with(regions={'length': 2})]
    return cases


# --- Unit tests --------------------------------------------------------------------------------------------------

@pytest.fixture(scope='module')
def base(tmp_path_factory):
    directory = tmp_path_factory.mktemp('catalogs-unit')
    python = runtime_config(str(directory)).python
    keys = catalog_root(directory / 'root', directory / 'outside', python)
    return directory / 'root', keys


def test_editor_records_offer_saved_evaluations_newest_first(base):
    root, keys = base
    rows = records(RecordStore(str(root)))
    editor = keys['editor']
    # Equal stamps keep the key order (V8's sort is stable).
    tied = sorted([editor['older'], editor['tie']])
    assert [row['key'] for row in rows] == [editor['newest'], editor['bare'], editor['no-identity'], *tied]
    request = editor_request()
    assert jsjson.stringify(rows[0]) == jsjson.stringify({
        'key': editor['newest'], 'finished_at': '2026-10-03T10:00:00.000Z', 'parent_id': PARENT,
        'parent_label': '2区 · PL + PR · 半径≤35 mm', 'electrode_count': 64, 'active_regions': 2,
        'metrics': METRICS, 'request': request, 'protocol': 'electrode-editor/1',
        'restored_as': 'draft_requires_current_evaluation'})
    assert 'parent_label' not in rows[1] and 'active_regions' not in rows[1]


def test_editor_records_never_expose_incomplete_or_mismatched_evaluations(base):
    root, keys = base
    listed = {row['key'] for row in records(RecordStore(str(root)))}
    assert listed == {keys['editor'][name] for name in VALID_EDITOR}


def test_editor_records_of_a_missing_or_escaping_tree(tmp_path):
    root, outside = tmp_path / 'root', tmp_path / 'outside'
    root.mkdir()
    assert records(RecordStore(str(root))) == []
    (outside / 'jobs').mkdir(parents=True)
    (root / 'results/v2').mkdir(parents=True)
    (root / EDITOR_JOBS).symlink_to(outside / 'jobs')
    with pytest.raises(RecordError, match='Record path leaves the repository.'):
        records(RecordStore(str(root)))


@pytest.mark.parametrize('name', list(SORT_ROOTS))
def test_editor_record_sort_compares_like_v8(tmp_path, name):
    """``b.finished_at.localeCompare(a.finished_at)``: only a row compared as ``b`` must have a string stamp."""
    keys = sort_root(tmp_path / 'root', SORT_ROOTS[name])
    outcome = attempt(lambda: [row['key'] for row in records(RecordStore(str(tmp_path / 'root')))])
    expected = SORT_OUTCOMES[name]
    if isinstance(expected, str):
        assert outcome == {'ok': False, 'message': expected}
    else:
        assert outcome == {'ok': True, 'value': [keys[index] for index in expected]}


@pytest.mark.parametrize('name', SHORT_ROOTS)
def test_editor_record_sort_of_short_lists_is_node_26s(tmp_path, monkeypatch, name):
    """Node 24 and older have no insertion-only path (limit 2): they compare the bad row as ``b`` and throw."""
    sort_root(tmp_path / 'root', SORT_ROOTS[name])
    monkeypatch.setattr(jssort, 'INSERTION_LIMIT', 2)
    with pytest.raises(JSTypeError, match='localeCompare'):
        records(RecordStore(str(tmp_path / 'root')))


def test_editor_record_sort_of_many_rows_is_stable(tmp_path):
    keys = sort_root(tmp_path / 'root', MANY)
    order = sorted(range(len(MANY)), key=lambda index: MANY[index], reverse=True)
    assert [row['key'] for row in records(RecordStore(str(tmp_path / 'root')))] == [keys[index] for index in order]


def test_validate_editor_result_messages():
    """The checks of check-electrode-editor.mjs:48 (its port is slice 6), with Node's messages."""
    request = editor_request()
    good = editor_result(request)
    validate_editor_result(good, request)
    for patch, message in (({'electrode_count': 63}, 'Invalid edited electrode count'),
                           ({'minimum_distance_mm': 0}, 'Invalid edited geometry'),
                           ({'active_slots': [1] * 64}, 'Stable electrode identities changed'),
                           ({'edited_metrics': {**METRICS, 'conditional_global': 0.8}},
                            'Invalid editor decision score'),
                           ({'baseline': None}, 'Missing field metric'),
                           ({'parent_metrics': {**METRICS, 'median_mm': '20'}}, 'Invalid editor metric'),
                           ({'request': editor_request((1,))}, 'Editor result identity mismatch')):
        with pytest.raises(EditorResultError) as caught:
            validate_editor_result({**good, **patch}, request)
        assert str(caught.value) == message
    with pytest.raises(JSTypeError, match=r"^Cannot read properties of undefined \(reading 'filter'\)$"):
        validate_editor_result({**good, 'request': {}}, {})


def test_parents_offer_patched_layouts_searched_under_independent_noise(base):
    root, keys = base
    library = Library(str(root), runtime_config(str(root)))
    rows = parents(library)
    patched = keys['patched']
    cache = {row['id'] for row in rows if row['dataset_id'] == 'cache'}
    # Compatibility is not a condition: a layout found under another code identity is still a parent.
    assert cache == {patched['patched'], patched['patched-prior'], patched['patched-other-code']}
    area = [row for row in rows if row['dataset_id'] == 'strict_area']
    assert len(area) == 29 and all(row['status'] == 'completed' for row in area)
    assert {row['dataset_id'] for row in rows} == {'cache', 'strict_area'}
    listed = [row['id'] for row in library.list()['records']]
    assert [row['id'] for row in rows] == [id for id in listed if id in {row['id'] for row in rows}]
    assert all('layout' not in row and 'provenance' not in row for row in rows)


def test_reception_layouts_keep_saved_default_protocol_layouts(base):
    root, keys = base
    library = Library(str(root), runtime_config(str(root)))
    document = reception_layouts(library)
    listed = library.list()
    assert list(document) == list(listed)
    assert document['datasets'] == listed['datasets']
    rows = document['records']
    cache = {row['id'] for row in rows if row['dataset_id'] == 'cache'}
    assert keys['patched']['patched-noise'] not in cache and keys['patched']['patched-prior'] not in cache
    assert keys['patched']['patched'] in cache and keys['patched']['patched-other-code'] in cache
    assert all(not (row.get('request') or {}).get('noise_model') and not (row.get('request') or {}).get('data_prior')
               for row in rows)
    evaluations = [row for row in rows if row['dataset_id'] == 'design_evaluation']
    design = keys['design']
    assert {row['id'] for row in evaluations} == {design['default'], design['robustness']}
    assert rows[-len(evaluations):] == evaluations and all('layout' not in row for row in evaluations)
    assert '一条坐标评价记录未载入：设计记录校验失败' in document['warnings']
    assert document['warnings'][:len(listed['warnings'])] == listed['warnings']


def test_heads_offer_complete_packages(base):
    root, _ = base
    assert heads(str(root)) == [{'head_id': 'ixi002', 'dataset': 'IXI', 'subject': 'ixi002'}]


# --- Parity with Node -------------------------------------------------------------------------------------------

def snapshot(root: Path) -> dict:
    """Every path under ``root`` with its type, size and modification time (links not followed)."""
    state = {}
    for directory, names, files in os.walk(root):
        for name in names + files:
            info = os.lstat(os.path.join(directory, name))
            state[os.path.join(directory, name)] = (info.st_mode, info.st_size, info.st_mtime_ns)
    return state


@pytest.fixture(scope='session')
def parity(tmp_path_factory):
    base = tmp_path_factory.mktemp('catalogs-parity')
    python = runtime_config(str(base)).python
    roots = {}
    catalog_root(base / 'base', base / 'outside', python)
    roots['base'] = base / 'base'
    (base / 'symlinked').symlink_to(base / 'base')
    roots['symlinked'] = base / 'symlinked'
    (base / 'bare').mkdir()
    roots['bare'] = base / 'bare'
    minimal = base / 'minimal'
    minimal.mkdir()
    code_tree(minimal)
    provenance = forward_inputs(minimal)
    patched_caches(minimal, provenance, python)
    roots['minimal'] = minimal
    # The offline datasets without a strict-area report: every saved evaluation fails on its reference report.
    reportless = base / 'reportless'
    keys = library_root(reportless, python)
    (reportless / 'results/v2/campaigns/area/current.json').unlink()
    assert keys['design']
    roots['reportless'] = reportless
    for name, finished in (*SORT_ROOTS.items(), ('sort-many', MANY)):
        sort_root(base / name, finished)
        roots[name] = base / name
    escaping = base / 'escaping'
    escaping.mkdir()
    code_tree(escaping)
    forward_inputs(escaping)
    offline_datasets(escaping)
    (base / 'elsewhere/jobs').mkdir(parents=True)
    (escaping / EDITOR_JOBS).symlink_to(base / 'elsewhere/jobs')
    (escaping / 'results/v2/heads').write_text('not a directory', encoding='utf-8')
    roots['escaping'] = escaping
    if os.geteuid() != 0:
        closed = base / 'closed'
        closed.mkdir()
        code_tree(closed)
        forward_inputs(closed)
        (closed / EDITOR_JOBS).mkdir(parents=True)
        (closed / EDITOR_JOBS).chmod(0)
        (closed / 'results/v2/heads').mkdir()
        (closed / 'results/v2/heads').chmod(0)
        roots['closed'] = closed
    items = [{'id': name, 'root': str(path)} for name, path in roots.items()]
    cases = validation_cases()
    before = snapshot(base)
    try:
        node = run_catalog_node(items, cases, tmp_path_factory.mktemp('catalogs-node'))
        with sorting_as_node():
            python = {item['id']: python_catalogs(item['root']) for item in items}
        # The values Node's validator saw: parsed JSON, every number a double.
        validated = [python_validate(result, request) for result, request in jsjson.parse(jsjson.stringify(cases))]
        assert snapshot(base) == before
    finally:
        if 'closed' in roots:
            (base / 'closed' / EDITOR_JOBS).chmod(0o700)
            (base / 'closed/results/v2/heads').chmod(0o700)
    return roots, node, python, validated


PARITY_ROOTS = ['base', 'symlinked', 'bare', 'minimal', 'reportless', 'escaping', 'closed', *SORT_ROOTS, 'sort-many']


@needs_node
@pytest.mark.parametrize('root', PARITY_ROOTS)
def test_catalog_parity(root, parity):
    roots, node, python, _ = parity
    if root not in roots:
        pytest.skip('permissions do not apply to root')
    assert_same_catalogs(node['roots'][root], python[root])


@needs_node
def test_validate_editor_result_parity(parity):
    _, node, _, validated = parity
    assert validated == [node_failure(result) for result in node['validate']]


@needs_node
def test_catalog_parity_covers_each_outcome(parity):
    """The roots reach what the comparison is for: every kind of editor row, parents of both datasets, layouts
    with saved evaluations and warnings, a listed head, and each failure of a whole catalog."""
    roots, node, _, _ = parity
    base = {name: jsjson.parse(result['value']) for name, result in node['roots']['base'].items()}
    assert len(base['records']) == len(VALID_EDITOR)
    assert {row['dataset_id'] for row in base['parents']} == {'cache', 'strict_area'}
    assert any(row['dataset_id'] == 'design_evaluation' for row in base['layouts']['records'])
    assert base['heads'] == [{'head_id': 'ixi002', 'dataset': 'IXI', 'subject': 'ixi002'}]
    linked = jsjson.parse(node['roots']['symlinked']['parents']['value'])
    assert linked and {row['dataset_id'] for row in linked} == {'cache'}
    reportless = jsjson.parse(node['roots']['reportless']['layouts']['value'])
    assert any(w.startswith('一条坐标评价记录未载入：ENOENT') for w in reportless['warnings'])
    assert node['roots']['bare']['parents']['code'] == 'ENOENT'
    escaping = node['roots']['escaping']
    assert escaping['records']['message'] == 'Record path leaves the repository.'
    assert escaping['heads']['code'] == 'ENOTDIR'
    if 'closed' in roots:
        assert node['roots']['closed']['records']['code'] == 'EACCES'
        assert node['roots']['closed']['heads']['code'] == 'EACCES'
    short = [node['roots'][name]['records']['ok'] for name in SHORT_ROOTS]
    assert short == [node_generation()['insertionLimit'] >= 7] * len(SHORT_ROOTS)
    outcomes = node['validate']
    assert sum(result['ok'] for result in outcomes) >= 4
    messages = {result['message'] for result in outcomes if not result['ok']}
    assert {'Editor result identity mismatch', 'Invalid editor region data', 'Invalid edited electrode count',
            'Stable electrode identities changed', 'Invalid edited geometry', 'Missing field metric',
            'Invalid editor metric', 'Invalid editor decision score'} < messages
    assert sum(result.get('name') == 'TypeError' for result in outcomes) >= 8


# --- The real installation (EEG_KEY_PARITY_ROOT) ----------------------------------------------------------------

REAL_ROOT = os.environ.get('EEG_KEY_PARITY_ROOT')
real_root = pytest.mark.skipif(not REAL_ROOT, reason='set EEG_KEY_PARITY_ROOT to a checkout with results/v2')


@pytest.mark.data_bundle
@real_root
@needs_node
def test_real_root_catalog_parity(tmp_path):
    """The installation's editor records, parents, reception layouts and heads, as Node gives them."""
    before = snapshot(Path(REAL_ROOT) / 'results/v2')
    node = run_catalog_node([{'id': 'real', 'root': REAL_ROOT}], [], tmp_path)['roots']['real']
    python = python_catalogs(REAL_ROOT)
    assert_same_catalogs(node, python)
    assert all(node[name]['ok'] for name in node)
    assert snapshot(Path(REAL_ROOT) / 'results/v2') == before
