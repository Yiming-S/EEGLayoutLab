"""Signal reception's test helpers (test_source.py and the reception half of test_key_parity.py; tests/service/
README.md).

``fixture(request, layout)`` is check-source-reception.mjs's ``result()`` for any canonical request: v1, or v2's
three modes with or without the atlas definition (the fields check-cross-region-contract.mjs's ``fixtureResult``
adds), on the record's frozen layout, so the contract's validators accept it. Its source (``FIXTURE_SOURCE``) is
also the body of ``FAKE_WORKER``, the stand-in for both reception workers: it reads ``{request, record}`` and writes
that result to ``--output``, or fails or holds as ``R/stub/worker-mode.txt`` says; with ``--catalog`` it prints
``R/stub/catalog.txt`` (``exit:<n>``: fails with that code). ``Fixture`` is the test's ``fixture()``: a context stub
whose ``bump()`` changes the key, the radius queue sharing the slot, and fake children.

``reception_root`` builds a reception root: an editor root (``editor_support.editor_root``: a design root of
``key_parity_support.design_root`` with parents of every kind the library offers) plus the reception workflow files,
scripts and two stub inspectors whose digest is the SHA-256 of ``R/stub/numerical-runtime.txt`` (the snapshot one
observes that file; ``R/stub/inspector-mode.txt`` makes it fail or print another schema). ``RECEPTION_VARIANTS``
name what one root changes.

The parity of the run path: ``parity_cases`` builds the case roots and the result files, ``run_node`` runs Node's own
``SourceReceptionService`` over them (``parity/reception_run.mjs``, mode ``runs``) and ``run_python`` runs
``ReceptionJobs`` over the same steps. Each root is built again at the same path for Python, so the bytes written
can be compared as they are. ``ReceptionCases`` is the Python side of mode ``contexts`` (test_key_parity.py).
"""
from __future__ import annotations

import asyncio
import base64
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Callable, Optional

from eeglayoutlab.jobs.identity import UNDEFINED
from eeglayoutlab.jobs.library import Library
from eeglayoutlab.jobs.radius import RadiusJobs
from eeglayoutlab.jobs.reception import (
    CACHE_LIMIT, RESULT_LIMIT, ReceptionJobs, _hash,
)
from eeglayoutlab.jobs.reception_records import design_reception_record
from eeglayoutlab.jobs.records import node_message
from eeglayoutlab.jobs.runtime import runtime_config
from eeglayoutlab.jobs.runtime_digest import process_env
from eeglayoutlab.jobs.slot import ExecutionSlot, InstallationLock
from eeglayoutlab.jobs.worker import _utf8
from eeglayoutlab.schemas import jsjson
from eeglayoutlab.schemas.source_reception import REGION_DEFINITION, SOURCE_REGIONS, normalize_reception_request

from .design_support import CLOCK, SETTLE, TIMEOUT_CASE_MS, _progress_lines, _stderr_chunks
from .editor_support import editor_root
from .key_parity_support import NODE_ENV
from .library_support import write
from .radius_support import FakeChild, PinnedClock, PinnedIds, Spawner, b64, line, until

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/reception_run.mjs'
SOURCE_JOBS = 'results/v2/source_reception_jobs'
SOURCE_V2_JOBS = 'results/v2/source_reception_v2_jobs'
HOLD = 120  # seconds a held fake worker waits; it is always stopped before that
BRIEF = 65536  # a record text longer than this (UTF-8 bytes) is recorded by its SHA-256
WORKER_ENV = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS',
              'PYTHONDONTWRITEBYTECODE')

# --- Results -----------------------------------------------------------------------------------------------------

FIXTURE_SOURCE = r'''
TRACES = ('brain_uv', 'ecg_uv', 'eog_uv', 'noise_uv', 'reconstructed_brain_uv', 'reconstructed_ecg_uv',
          'reconstructed_eog_uv', 'reconstructed_noise_uv')


def score(condition, artifact_scale):
    return {'condition': condition, 'artifact_scale': artifact_scale,
            'baseline': {'nmse': 0.1, 'explained_energy': 0.9, 'brain_artifact_ratio_db': 10},
            'candidate': {'nmse': 0.2, 'explained_energy': 0.8, 'brain_artifact_ratio_db': 5},
            'field_retention': 0.8 / 0.9}


def fixture(request, layout):
    """A result the validators accept for the canonical ``request`` and the record's frozen ``layout``."""
    matrix = [[1] * 400 for _ in range(64)]
    traces = {name: matrix for name in TRACES}
    mode = request.get('mode')
    scale = request['artifact_scale']
    result = {
        'schema_version': 'source-reception/2' if mode else 'source-reception/1', 'status': 'completed',
        'request': request,
        # Copies: an edit of the result's layout must not move the record's.
        'layout': {name: [list(row) if isinstance(row, list) else row for row in layout[name]]
                   for name in ('xyzMm', 'referenceXyzMm', 'regionIndices') if name in layout},
        'source': {'xyz_mm': [[1, 2, 3]]},
        'waveforms': {'time_s': [i / 50 for i in range(400)], 'baseline': traces, 'candidate': traces},
        'conditions': [score(c, 0 if c == 'clean' else scale) for c in ('clean', 'ecg', 'eog', 'mixed')],
        'strength_curve': [score('clean', 0)] + [score(c, s) for c in ('ecg', 'eog', 'mixed')
                                                 for s in (0, 0.5, 1, 2, 4)],
    }
    if not mode:
        return result
    regions = request.get('brain_regions')
    n = 1 if mode == 'single_source' else len(regions) if mode == 'cross_region' else 6
    source = {'mode': mode, 'xyz_mm': [[i, 2, 3] for i in range(n)], 'normals_mri': [[0, 0, 1] for _ in range(n)]}
    if mode == 'single_source':
        source['generation_source_indices'] = [request['source_index']]
    if mode == 'cross_region':
        source.update({'region': 'cross_region', 'source_regions': list(regions), 'patch_count': n,
                       'generation_source_indices': list(range(n)),
                       'bank_source_indices': [4096 + i for i in range(n)]})
    definition = request.get('region_definition')
    if definition:
        source.update({'region_definition': definition, 'atlas_sha256': 'e' * 64,
                       'source_regions': list(regions) if mode == 'cross_region'
                       else [request.get('brain_region', 'frontal')] * n,
                       'source_parcels': ['parcel-' + str(i) for i in range(n)]})
        result['protocol'] = {'region_definition': definition}
    result['source'] = source
    result['waveforms']['source_nam'] = [[1] * 400 for _ in range(n)]
    return result
'''
_namespace: dict[str, Any] = {}
exec(FIXTURE_SOURCE, _namespace)  # noqa: S102 - the worker's own source, run here as there
fixture: Callable[[dict, dict], dict] = _namespace['fixture']
score: Callable[[str, Any], dict] = _namespace['score']

# check-source-reception.mjs's request, layout and record.
REQ = {'record_id': 'a' * 64, 'brain_region': 'frontal', 'waveform': 'burst', 'artifact_scale': 1, 'seed': 2026}
LAYOUT = {'xyzMm': [[i * 5, 0, 0] for i in range(64)], 'referenceXyzMm': [[i * 5, 1, 0] for i in range(64)],
          'regionIndices': [i % 2 for i in range(64)]}
RECORD = {'id': REQ['record_id'], 'layout': LAYOUT}


def result(request: Any = REQ, layout: Any = LAYOUT) -> dict:
    """``result()`` of check-source-reception.mjs for the canonical form of ``request``."""
    return fixture(normalize_reception_request(request), layout)


def v1(record_id: str, **changes: Any) -> dict:
    return {'record_id': record_id, 'brain_region': 'frontal', 'waveform': 'burst', 'artifact_scale': 1, 'seed': 2026,
            **changes}


def single(record_id: str, source_index: int = 2, **changes: Any) -> dict:
    return {'record_id': record_id, 'mode': 'single_source', 'source_index': source_index, 'waveform': 'burst',
            'artifact_scale': 1, 'seed': 2026, **changes}


def multi(record_id: str, region: str = 'frontal', definition: bool = True, **changes: Any) -> dict:
    request = {'record_id': record_id, 'mode': 'multi_source', 'brain_region': region, 'waveform': 'rhythm',
               'artifact_scale': 2, 'seed': 7, **changes}
    return {**request, 'region_definition': REGION_DEFINITION} if definition else request


def cross(record_id: str, regions: list, definition: bool = True, **changes: Any) -> dict:
    request = {'record_id': record_id, 'mode': 'cross_region', 'brain_regions': regions, 'waveform': 'burst',
               'artifact_scale': 0.5, 'seed': 11, **changes}
    return {**request, 'region_definition': REGION_DEFINITION} if definition else request


# --- A stand-in worker and inspectors --------------------------------------------------------------------------------

FAKE_WORKER = r'''"""A stand-in for both reception workers (tests/service/reception_support.py)."""
import json
import os
import sys
import time
<FIXTURE>

root = sys.argv[sys.argv.index('--repository-root') + 1]
stub = os.path.join(root, 'stub')
if '--catalog' in sys.argv:
    with open(os.path.join(stub, 'catalog.txt'), encoding='utf-8') as handle:
        text = handle.read()
    if text.startswith('exit:'):
        sys.stderr.write('catalog failed\n')
        sys.exit(int(text[5:]))
    sys.stdout.write(text)
    sys.exit(0)
mode = 'done'
if os.path.exists(os.path.join(stub, 'worker-mode.txt')):
    with open(os.path.join(stub, 'worker-mode.txt'), encoding='utf-8') as handle:
        mode = handle.read().strip()
with open(sys.argv[sys.argv.index('--request') + 1], encoding='utf-8') as handle:
    data = json.load(handle)
print(json.dumps({'type': 'progress', 'progress': 0.25, 'message': '读取冻结布局'}, ensure_ascii=False), flush=True)
if mode == 'fail':
    print(json.dumps({'type': 'error', 'message': '源实验失败'}, ensure_ascii=False), flush=True)
    sys.stderr.write('Traceback: boom\n')
    sys.exit(1)
if mode == 'hold':
    time.sleep(<HOLD>)
if mode != 'none':
    with open(sys.argv[sys.argv.index('--output') + 1], 'w', encoding='utf-8') as handle:
        json.dump(fixture(data['request'], data['record']['layout']), handle)
print(json.dumps({'type': 'progress', 'progress': 0.9, 'message': '写入结果'}, ensure_ascii=False), flush=True)
sys.stderr.write('reception stderr\n')
'''.replace('<FIXTURE>', FIXTURE_SOURCE).replace('<HOLD>', str(HOLD))

_INSPECTOR = r'''"""A stand-in reception runtime inspector (tests/service/reception_support.py)."""
import hashlib
import json
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
path = os.path.join(root, 'stub', 'numerical-runtime.txt')
mode = 'ok'
if os.path.exists(os.path.join(root, 'stub', 'inspector-mode.txt')):
    with open(os.path.join(root, 'stub', 'inspector-mode.txt'), encoding='utf-8') as handle:
        mode = handle.read().strip()
if mode == 'fail':
    sys.stderr.write('inspector failed\n')
    sys.exit(2)
if mode == 'bad':
    print(json.dumps({'schema': 'reception-runtime-digest/0', 'sha256': 'b' * 64}))
    sys.exit(0)
with open(path, 'rb') as handle:
    digest = {'schema': 'reception-runtime-digest/1', 'sha256': hashlib.sha256(handle.read()).hexdigest()}
if <WATCH>:
    info = os.lstat(path)
    stamp = ':'.join(str(value) for value in (info.st_dev % (1 << 64), info.st_ino, info.st_mode, info.st_size,
                                              info.st_mtime_ns, info.st_ctime_ns))
    digest['watch'] = {'schema': 'reception-runtime-watch/1', 'entries': [[path, True, stamp]]}
print(json.dumps(digest))
'''
SNAPSHOT_INSPECTOR = _INSPECTOR.replace('<WATCH>', 'True')
LEGACY_INSPECTOR = _INSPECTOR.replace('<WATCH>', 'False')
CATALOG = {'schema_version': 'source-catalog/1',
           'sources': [{'index': i, 'region': SOURCE_REGIONS[i % 6], 'xyz_mm': [i, 0, 0]} for i in range(256)]}
RUNTIME_TEXT = 'numerical runtime 1'

# The files a reception context reads beyond the design root's (the inspectors also enter v2's code digests).
RECEPTION_FILES = {
    'src/compact_eeg/workflows/source_reception.py': 'reception workflow',
    'src/compact_eeg/workflows/source_reception_v2.py': 'reception v2 workflow',
    'src/compact_eeg/workflows/source_roi.py': 'atlas code',
    'webapp/public/models/ernie/source-roi-definition.json': '{"definition":"dk40-six-roi-v1"}',
    'scripts/source_reception.py': 'reception script',
    'scripts/source_reception_v2.py': 'reception v2 script',
    'scripts/reception_forward_provider.py': 'forward provider script',
    'scripts/run_source_reception.py': FAKE_WORKER,
    'scripts/run_source_reception_v2.py': FAKE_WORKER,
    'scripts/inspect_reception_runtime.py': LEGACY_INSPECTOR,
    'scripts/inspect_reception_runtime_snapshot.py': SNAPSHOT_INSPECTOR,
    'stub/numerical-runtime.txt': RUNTIME_TEXT,
    'stub/catalog.txt': jsjson.stringify(CATALOG),
}
# reception_root's variants: what each removes or changes.
RECEPTION_VARIANTS = (None, 'no_v1_script', 'no_v2_code', 'no_atlas', 'no_workflow', 'legacy_inspector', 'bad_digest',
                      'inspector_fails')


def reception_files(tree: Path) -> None:
    for path, body in RECEPTION_FILES.items():
        write(tree, path, body)


def reception_root(directory: Path, *, reception: Optional[str] = None, **options: Any) -> dict:
    """A reception root under ``directory``: ``editor_root(directory, **options)`` plus ``RECEPTION_FILES``.
    ``reception`` changes one thing: ``no_v1_script`` (v1's worker is gone), ``no_v2_code`` (a v2 script is gone),
    ``no_atlas`` (the atlas definition is gone), ``no_workflow`` (both versions' workflow file is gone),
    ``legacy_inspector`` (only the inspector without observations), ``bad_digest`` (the inspector prints another
    schema) or ``inspector_fails`` (it exits with 2). Returns ``editor_root``'s ``{root, tree, ids}``."""
    assert reception in RECEPTION_VARIANTS
    built = editor_root(directory, **options)
    tree = Path(built['tree'])
    reception_files(tree)
    if reception == 'no_v1_script':
        (tree / 'scripts/run_source_reception.py').unlink()
    elif reception == 'no_v2_code':
        (tree / 'scripts/source_reception_v2.py').unlink()
    elif reception == 'no_atlas':
        (tree / 'webapp/public/models/ernie/source-roi-definition.json').unlink()
    elif reception == 'no_workflow':
        (tree / 'src/compact_eeg/workflows/source_reception.py').unlink()
    elif reception == 'legacy_inspector':
        (tree / 'scripts/inspect_reception_runtime_snapshot.py').unlink()
    elif reception == 'bad_digest':
        write(tree, 'stub/inspector-mode.txt', 'bad')
    elif reception == 'inspector_fails':
        write(tree, 'stub/inspector-mode.txt', 'fail')
    return built


def worker_root(directory: Path) -> Path:
    """A root with the stand-in workers and the stub catalog only (for a context stub)."""
    directory.mkdir(parents=True, exist_ok=True)
    for path in ('scripts/run_source_reception.py', 'scripts/run_source_reception_v2.py', 'stub/catalog.txt'):
        write(directory, path, RECEPTION_FILES[path])
    return directory


def parent_records(root: str, ids: dict[str, str], python: str = 'python3') -> dict[str, Any]:
    """The record each parent's request reads: ``Library.get``, else the saved coordinate evaluation."""
    config = runtime_config(root, python, env=dict(os.environ))
    library = Library(config.repository_root, config)
    records = {}
    for name, id in ids.items():
        record = library.get(id)
        records[name] = record if record is not None else design_reception_record(config.repository_root, id)
    return records


# --- check-source-reception.mjs's fixture ----------------------------------------------------------------------------

class Fixture:
    """``fixture()`` of check-source-reception.mjs: a context stub ``{record, identity: {version}, key:
    sha256(JSON.stringify({r, version}))}`` whose ``bump()`` changes the version, the radius queue (whose permit the
    reception service shares) and fake children that record their kills."""

    def __init__(self, root: Path, **options: Any):
        self.root = root
        self.version = 1
        self.children: list[FakeChild] = []
        self.queue = RadiusJobs(str(root), 'python3', get_identity=lambda: {}, timeout_ms=3000,
                                spawn=self._unexpected)
        options.setdefault('timeout_ms', 3000)
        options.setdefault('context', self.context)
        options.setdefault('spawn', Spawner(children=self.children))
        self.source = ReceptionJobs(str(root), 'python3', None, execution_slot=self.queue.execution_slot, **options)

    @staticmethod
    def _unexpected(*args: Any) -> Any:
        raise AssertionError('unexpected radius worker')

    def context(self, request: Any) -> dict:
        return {'record': RECORD, 'identity': {'version': self.version},
                'key': jsjson.sha256_hex({'r': request, 'version': self.version})}

    def bump(self) -> None:
        self.version += 1

    async def complete(self, value: Any = None) -> Any:
        """``complete(f, r)``: writes ``result.json`` of the active job, closes the last child with 0 and waits."""
        job = self.source.active
        Path(job.batch, 'result.json').write_bytes(jsjson.stringify(result() if value is None else value).encode())
        self.children[-1].close(0)
        await until(lambda: self.source.active is None, SETTLE)
        return job

    async def aclose(self) -> None:
        try:
            await bounded_aclose(self.source)
        finally:
            self.queue.dispose()


async def bounded_aclose(*services: ReceptionJobs) -> None:
    """Each service's ``aclose()``, within ``SETTLE``: a fake child never exits by itself, so a job that a failed
    step (or a divergence from Node) leaves running fails the cleanup, chained to that failure, instead of hanging the
    test; Node's driver only disposes."""
    await asyncio.wait_for(asyncio.gather(*(service.aclose() for service in services)), SETTLE)


# --- The parity cases ----------------------------------------------------------------------------------------------

CASE_IDS = ('v1-done', 'v2-done', 'refusals', 'worker-failure', 'spawn-throws', 'invalid-v1', 'invalid-v2',
            'result-file', 'identity-changed', 'timeout', 'cancel', 'publish-once', 'saved', 'busy', 'remember',
            'dispose', 'store-failure', 'lookups', 'catalog')
# Texts V8 and Python write differently for the same failure: V8's JSON.parse messages are not reproduced.
SYNTAX = {'Unexpected end of JSON input': '<syntax>', 'Expecting value: line 1 column 1 (char 0)': '<syntax>'}


def catalog(directory: Path) -> dict:
    """The parents as every case root has them (ids and records), from a root built under ``directory``."""
    built = reception_root(directory)
    return {'ids': built['ids'], 'records': parent_records(built['root'], built['ids'])}


class Files:
    """The result and record files of the cases, written once under ``directory`` (outside every root)."""

    def __init__(self, directory: Path, parents: dict):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.records = {parents['ids'][name]: record for name, record in parents['records'].items()}
        self.plain: dict[str, str] = {}
        self.count = 0

    def text(self, text: str | bytes) -> str:
        self.count += 1
        path = self.directory / f'{self.count:03d}.json'
        path.write_bytes(text if isinstance(text, bytes) else text.encode('utf-8'))
        return str(path)

    def value(self, value: Any) -> str:
        # Both hosts parse these files and write what they parsed, so any JSON text of the value serves; Python's
        # own encoder is much faster than JSON.stringify's port for a 1 MB result.
        return self.text(_dumps(value))

    def result(self, raw: Any, edit: Optional[Callable[[dict], Any]] = None) -> str:
        """The file of a result the validators accept for ``raw`` on its parent's layout, changed by ``edit``
        (one file per request without an edit)."""
        request = normalize_reception_request(raw)
        name = jsjson.stringify(request)
        if edit is None and name in self.plain:
            return self.plain[name]
        value = fixture(request, self.records[request['record_id']]['layout'])
        if edit is not None:
            edit(value)
            return self.value(value)
        self.plain[name] = self.value(value)
        return self.plain[name]


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _round(raw: Any, path: Optional[str], close: tuple = (0, None)) -> list:
    """One job: submit, its result.json (``None``: none), the close, then its final view."""
    steps: list = [['submit', raw]]
    if path is not None:
        steps.append(['result', path])
    return steps + [['close', *close], ['settle'], ['view']]


def _set(path: str, value: Any) -> Callable[[dict], None]:
    """An edit that sets the member at the dotted ``path`` (list indices as numbers)."""
    def edit(result: dict) -> None:
        *parents, last = path.split('.')
        target: Any = result
        for name in parents:
            target = target[int(name)] if isinstance(target, list) else target[name]
        if isinstance(target, list):
            target[int(last)] = copy.deepcopy(value)
        else:
            target[last] = copy.deepcopy(value)
    return edit


def _delete(path: str) -> Callable[[dict], None]:
    def edit(result: dict) -> None:
        *parents, last = path.split('.')
        target: Any = result
        for name in parents:
            target = target[int(name)] if isinstance(target, list) else target[name]
        del target[int(last) if isinstance(target, list) else last]
    return edit


def _apply(function: Callable[[dict], Any]) -> Callable[[dict], None]:
    return function


def _invalid_v1(files: Files, ids: dict) -> list:
    """v1 results the validator refuses, one round per check and per V8 ``TypeError``, then values it accepts; each
    accepted round has a request of its own."""
    raw = v1(ids['cache'])
    low = {'nmse': 1 - 1e-9, 'explained_energy': 1e-9, 'brain_artifact_ratio_db': None}

    def first_row(name: str, value: Any) -> Callable[[dict], None]:
        def edit(r: dict) -> None:
            r['waveforms'][name] = {**r['waveforms'][name], 'brain_uv': [value, *r['waveforms'][name]['brain_uv'][1:]]}
        return edit

    def other_condition(r: dict) -> None:
        r['conditions'][3]['condition'] = 'other'

    def moved(r: dict) -> None:
        r['layout']['xyzMm'][0][0] += 0.001

    def duplicate(r: dict) -> None:
        r['strength_curve'][1] = r['strength_curve'][0]

    def flat_time(r: dict) -> None:
        r['waveforms']['time_s'][5] = r['waveforms']['time_s'][4]

    def bad_low(r: dict) -> None:
        r['conditions'][0]['baseline'] = low

    edits: list = [
        _set('status', 'failed'), _set('schema_version', 'source-reception/2'), _set('request.seed', 2027),
        _set('request.ar', 90), _set('request', None), moved, _delete('layout.regionIndices'), _set('layout', None),
        _set('waveforms.time_s', list(range(399))), flat_time, _set('waveforms.time_s.3', '0.06'),
        _set('waveforms', None), _set('waveforms.time_s', {'length': 400}),
        first_row('baseline', [1] * 399), first_row('candidate', [1] * 399 + ['1']), first_row('baseline', None),
        _delete('waveforms.candidate.noise_uv'),
        lambda r: r.__setitem__('conditions', r['conditions'][:3]), _set('conditions.1.condition', 'clean'),
        lambda r: r.__setitem__('strength_curve', r['strength_curve'][:15]), duplicate,
        _set('conditions.1.artifact_scale', 2), _set('conditions.0.artifact_scale', 1), other_condition,
        _set('conditions.0', None), _set('conditions.0.baseline', None), _set('conditions.0.candidate.nmse', -0.1),
        _set('conditions.0.candidate.explained_energy', 0.7),
        _set('conditions.0.baseline.brain_artifact_ratio_db', '10'),
        _delete('conditions.2.candidate.explained_energy'), _set('strength_curve.4.field_retention', 100),
        _set('conditions.0.field_retention', None), bad_low, _delete('source'), _set('source.xyz_mm', []),
        _set('source.xyz_mm', [[1, 2]]), _set('source.xyz_mm', [[1, 2, '3']]), _set('source.xyz_mm', 'abc'),
        _set('source.xyz_mm', [None]), _set('source.xyz_mm', {'length': 1}),
    ]
    steps: list = []
    for edit in edits:
        steps += _round(raw, files.result(raw, edit))

    def negative(r: dict) -> None:
        r['conditions'][0]['candidate'] = {**r['conditions'][0]['candidate'], 'nmse': 2, 'explained_energy': -1}
        r['conditions'][0]['field_retention'] = -1 / 0.9

    def accepted_low(r: dict) -> None:
        r['conditions'][0]['baseline'] = low
        r['conditions'][0]['field_retention'] = None
    # What the checks let through: clipped negative scores, a vanishing baseline, members V8 orders its own way.
    for index, edit in enumerate((negative, accepted_low, _set('extra', {'2': 'b', '1': 'a', 'x': -0.0}))):
        other = v1(ids['cache'], seed=100 + index)
        steps += _round(other, files.result(other, edit))
    return steps


def _invalid_v2(files: Files, ids: dict) -> list:
    """v2 results the validator refuses: the identity, then the display data as v1's, the fixed sources of each mode
    and the atlas membership, one round per check and per V8 ``TypeError``."""
    s, m = single(ids['strict']), multi(ids['cache'])
    c = cross(ids['design'], ['occipital', 'frontal', 'parietal'])

    def regions_reversed(r: dict) -> None:
        r['source']['source_regions'].reverse()

    def repeated(r: dict) -> None:  # in both lists, so only the distinctness check refuses it
        for name in ('generation_source_indices', 'bank_source_indices'):
            r['source'][name][1] = r['source'][name][0]

    def bank_shift(r: dict) -> None:
        r['source']['bank_source_indices'][0] += 1

    def pop(path: str) -> Callable[[dict], None]:
        def edit(r: dict) -> None:
            target: Any = r
            for name in path.split('.'):
                target = target[int(name)] if isinstance(target, list) else target[name]
            target.pop()
        return edit

    def multi_regions(r: dict) -> None:
        r['source']['source_regions'][2] = 'central'

    rounds = [
        (s, _set('schema_version', 'source-reception/1')), (s, _set('request.seed', 1)),
        (s, _set('request', v1(ids['strict']))), (s, _delete('request.mode')),
        (s, _set('layout.regionIndices.0', 5)), (s, _set('waveforms.time_s', [])),
        (s, _set('source.mode', 'multi_source')), (s, _set('source.normals_mri', [])),
        (s, _set('source.normals_mri', [[0, 0, 2]])), (s, _set('source.normals_mri', [None])),
        (s, _set('source.normals_mri', {'length': 1})), (s, _delete('source.normals_mri')),
        (s, _set('waveforms.source_nam', [[1] * 399])), (s, _set('waveforms.source_nam', [[1] * 399 + [None]])),
        (s, _set('waveforms.source_nam', [None])), (s, _set('waveforms.source_nam', [{'length': 400}])),
        (s, _set('source.xyz_mm', [[1, 2, 3], [1, 2, 3]])),
        (s, _set('source.generation_source_indices', [3])), (s, _delete('source.generation_source_indices')),
        (s, _set('source.generation_source_indices', 'x')),
        (c, _set('source.patch_count', 6)), (c, regions_reversed), (c, _set('source.source_regions.0', 'unknown')),
        (c, pop('source.source_regions')), (c, repeated), (c, _set('source.generation_source_indices.0', -1)),
        (c, _set('source.generation_source_indices.0', 256)), (c, _set('source.generation_source_indices.0', 0.5)),
        (c, pop('source.generation_source_indices')), (c, bank_shift), (c, _set('source.normals_mri.0', [0, 0, 2])),
        (c, pop('source.normals_mri')), (c, pop('source.xyz_mm')), (c, pop('waveforms.source_nam')),
        (c, _set('source.generation_source_indices', {'length': 3})),
        (c, _set('source.bank_source_indices', {'length': 3})), (c, _set('source.source_regions', None)),
        (c, _set('source.atlas_sha256', 'E' * 64)), (c, _delete('source.atlas_sha256')),
        (c, _set('source.region_definition', 'other')), (c, _delete('protocol')), (c, _set('protocol', None)),
        (c, pop('source.source_parcels')), (m, multi_regions), (m, _set('source.source_regions', {'length': 6})),
        (m, pop('source.source_parcels')),
    ]
    steps: list = []
    for raw, edit in rounds:
        steps += _round(raw, files.result(raw, edit))
    # Accepted: an atlas digest as a number's text is not; an extra member is.
    extra = single(ids['strict'], source_index=9)
    steps += _round(extra, files.result(extra, _set('source.note', 'extra')))
    return steps


def parity_cases(base: Path, parents: dict) -> list[dict]:
    """The cases of the run-path parity; each root is ``base/<id>/tree``, a ``reception_root`` built for the Node
    run, and the result and record files are under ``base/files``. ``parents`` is ``catalog``'s."""
    ids = parents['ids']
    files = Files(base / 'files', parents)
    cases: list[dict] = []

    def case(id: str, steps: list, *, timeout_ms: int = 3000, throw: Optional[str] = None) -> None:
        cases.append({'id': id, 'directory': str(base / id), 'root': str(base / id / 'tree'), 'python': 'python3',
                      'timeoutMs': timeout_ms, 'throw': throw, 'clock': CLOCK, 'steps': steps})

    a, b = v1(ids['cache']), v1(ids['strict'])
    s, m = single(ids['strict']), multi(ids['cache'])
    md, c = multi(ids['design'], definition=False), cross(ids['design'], ['occipital', 'frontal'])
    co, sh = cross(ids['cache-other-code'], ['central'], definition=False), single(ids['strict-2'], 255)
    spelled = {'seed': 2026.0, 'artifact_scale': 1.0, 'waveform': 'burst', 'brain_region': 'frontal',
               'record_id': ids['cache']}
    case('v1-done', [
        ['submit', a], ['view'], ['pid'], ['jobs'], ['submit', a], ['submit', b], ['submit', s],
        *(step for chunk in _progress_lines() for step in (['stdout', chunk], ['view'])),
        *(['stderr', chunk] for chunk in _stderr_chunks()),
        ['result', files.result(a)], ['close', 0, None], ['view'], ['settle'], ['view'], ['jobs'],
        ['submit', a], ['view'], ['jobs'], ['lookup', a], ['lookup', spelled], ['lookup', b], ['saved', None, a],
        ['restart', {}], ['lookup', a], ['submit', spelled], ['view'], ['jobs'],
        *_round(b, files.result(b)), ['lookup', b], ['saved', None, b],
    ])
    rounds = []
    for raw in (m, md, c, co, sh):
        rounds += [*_round(raw, files.result(raw)), ['submit', raw], ['view'], ['lookup', raw], ['saved', None, raw]]
    case('v2-done', [
        ['submit', s], ['view'], ['pid'], ['submit', a],
        ['stdout', b64(line({'type': 'progress', 'progress': 0.3, 'message': '新源协议'}))],
        ['stderr', b64('v2 stderr\n')], ['result', files.result(s)], ['close', 0, None], ['settle'], ['view'],
        ['lookup', s], ['lookup', {**s, 'source_index': 3}], ['lookup', a], ['saved', None, s], ['saved', None, a],
        *rounds,
    ])
    refused = []
    for name in ('missing', 'historical', 'offline', 'design', 'strict-no-layout', 'cache-no-layout', 'cache-spatial',
                 'cache-prior', 'cache-zero-patches'):
        refused += [['submit', v1(ids[name])], ['lookup', v1(ids[name])]]
    for name in ('missing', 'historical', 'offline', 'cache-spatial', 'cache-prior', 'strict-no-layout'):
        refused += [['submit', single(ids[name])], ['lookup', single(ids[name])]]
    case('refusals', [
        *refused,
        ['submit', multi(ids['cache'], definition=False)], ['lookup', multi(ids['strict'], definition=False)],
        ['submit', None], ['submit', {}], ['submit', {**a, 'ar': 90}], ['submit', {**s, 'mode': 'other'}],
        ['submit', {**m, 'region_definition': 'unverified'}], ['submit', cross(ids['cache'], [])],
        ['submit', {**s, 'source_index': 256}], ['lookup', []], ['lookup', {**a, 'seed': 1.5}], ['jobs'],
    ])
    case('worker-failure', [
        ['submit', a], ['stderr', b64('Traceback (most recent call last):\n  ValueError: 失败\n')],
        ['stdout', b64(line({'type': 'error', 'code': 'compute_error', 'message': '失败'}))],
        ['result', files.result(a)], ['close', 1, None], ['view'], ['settle'], ['view'], ['lookup', a],
        ['submit', a], ['error', 'spawn python3 EACCES'], ['error', 'spawn python3 ENOENT'], ['close', -2, None],
        ['settle'], ['view'],
        ['submit', s], ['stdout', b64(line({'type': 'error', 'message': 7}))], ['stdout', b64(line({'type': 'error'}))],
        ['close', None, 'SIGKILL'], ['settle'], ['view'],
    ])
    case('spawn-throws', [['submit', a], ['view'], ['settle'], ['view'], ['submit', s], ['settle'], ['view'],
                          ['jobs']], throw='spawn EINVAL')
    case('invalid-v1', _invalid_v1(files, ids))
    case('invalid-v2', _invalid_v2(files, ids))
    bad_bytes = _dumps({**fixture(normalize_reception_request(b), files.records[ids['strict']]['layout']),
                        'note': 'NOT-UTF-8'}).encode().replace(b'NOT-UTF-8', b'a\xffb\xed\xa0\x80c')
    case('result-file', [
        *_round(a, None), ['submit', a], ['result_size', RESULT_LIMIT + 1], ['close', 0, None], ['settle'], ['view'],
        ['submit', a], ['result_dir'], ['close', 0, None], ['settle'], ['view'],
        ['submit', a], ['result_text', ''], ['close', 0, None], ['settle'], ['view'],
        ['submit', a], ['result_text', 'null'], ['close', 0, None], ['settle'], ['view'],
        ['submit', s], ['result_text', '[]'], ['close', 0, None], ['settle'], ['view'],
        ['submit', s], ['result_text', '"text"'], ['close', 0, None], ['settle'], ['view'],
        *_round(b, files.text(bad_bytes)), ['lookup', b], ['saved', None, b],
    ])
    case('identity-changed', [
        ['submit', a], ['change', 'scripts/run_source_reception.py', 'changed worker'], ['result', files.result(a)],
        ['close', 0, None], ['view'], ['settle'], ['view'], ['lookup', a],
        # A result the validator refuses fails as such, before the context is computed again.
        ['submit', a], ['change', 'src/compact_eeg/workflows/source_reception.py', 'changed'],
        ['result', files.result(b)], ['close', 0, None], ['settle'], ['view'],
        ['submit', s], ['change', 'stub/numerical-runtime.txt', 'numerical runtime 2'], ['result', files.result(s)],
        ['close', 0, None], ['settle'], ['view'],
        ['submit', s], ['change', 'scripts/source_reception_v2.py', 'changed v2'], ['result', files.result(s)],
        ['close', 0, None], ['settle'], ['view'],
        ['submit', m], ['change', 'webapp/public/models/ernie/source-roi-definition.json', '{}'],
        ['result', files.result(m)], ['close', 0, None], ['settle'], ['view'],
        # The inspector runs again only when what it observed changed; failures are not kept.
        ['submit', md], ['change', 'stub/inspector-mode.txt', 'fail'], ['result', files.result(md)],
        ['close', 0, None], ['settle'], ['view'], ['lookup', md],
        ['change', 'stub/numerical-runtime.txt', 'numerical runtime 3'], ['submit', md], ['lookup', md],
        ['change', 'stub/inspector-mode.txt', 'ok'], *_round(md, files.result(md)), ['lookup', md],
    ])
    case('timeout', [
        ['submit', a], ['stdout', b64(line({'type': 'progress', 'progress': 0.4, 'message': '计算'}))],
        ['wait_kill'], ['view'], ['submit', b], ['stdout', b64(line({'type': 'progress', 'progress': 0.9}))],
        ['result', files.result(a)], ['close', None, 'SIGTERM'], ['settle'], ['view'], ['lookup', a],
        ['submit', s], ['stop', 'timeout'], ['stop', 'user'], ['view'], ['close', None, 'SIGTERM'], ['settle'],
        ['view'],
    ], timeout_ms=TIMEOUT_CASE_MS)
    case('cancel', [
        ['submit', a], ['stdout', b64(line({'type': 'progress', 'progress': 0.3, 'message': '计算'}))],
        ['cancel', None], ['cancel', None], ['view'], ['submit', b],
        ['stdout', b64(line({'type': 'progress', 'progress': 0.8, 'message': 'late'}))], ['view'],
        ['result', files.result(a)], ['close', None, 'SIGTERM'], ['settle'], ['view'], ['cancel', None],
        ['cancel_id', 'f' * 36], ['cancel_id', None],
        ['submit', a], ['cancel', 'shutdown'], ['view'], ['result', files.result(a)], ['close', 0, None], ['settle'],
        ['view'], ['lookup', a],
        ['submit', s], ['stop', 'input_error'], ['view'], ['close', None, 'SIGTERM'], ['settle'], ['view'],
    ])
    case('publish-once', [
        # Another workspace published a valid result first: Python keeps it (B16), Node replaces it.
        ['submit', a], ['write_cache', 'valid', files.result(a)], ['result', files.result(a)], ['close', 0, None],
        ['settle'], ['view'],
        # Files that are not a valid result for the job are replaced on both hosts.
        ['submit', b], ['write_cache', 'text', 'not json'], ['result', files.result(b)], ['close', 0, None],
        ['settle'], ['view'], ['lookup', b],
        ['submit', s], ['write_cache', 'tampered', files.result(s)], ['lookup', s], ['result', files.result(s)],
        ['close', 0, None], ['settle'], ['view'], ['lookup', s],
        ['submit', m], ['write_cache', 'valid', files.result(m, _set('source.atlas_sha256', 'x'))],
        ['lookup', m], ['result', files.result(m)], ['close', 0, None], ['settle'], ['view'], ['lookup', m],
    ])
    case('saved', _saved_steps(files, ids))
    case('busy', [
        ['acquire'], ['submit', a], ['lookup', a], ['release'], ['pause'], ['submit', a], ['resume'],
        ['submit_pair', a, b], ['view'], ['submit', b], ['acquire'], ['result', files.result(a)], ['close', 0, None],
        ['settle'], ['view'], ['acquire'], ['submit', b], ['release'], ['submit', b], ['view'], ['close', 1, None],
        ['settle'], ['view'],
    ])
    hits = [['lookup', a] for _ in range(11)]
    case('remember', [*_round(a, files.result(a)), ['jobs'], *hits, ['jobs'], ['submit', s], ['jobs'],
                      *[['lookup', a] for _ in range(10)], ['jobs'], ['result', files.result(s)], ['close', 0, None],
                      ['settle'], ['jobs']])
    case('dispose', [
        ['submit', a], ['dispose'], ['view'], ['submit', b], ['lookup', b], ['cancel', None],
        ['close', None, 'SIGTERM'], ['settle'], ['view'], ['restart', {}], *_round(a, files.result(a)),
    ])
    case('store-failure', [
        ['submit', a], ['block_cache'], ['result', files.result(a)], ['close', 0, None], ['settle'], ['view'],
        ['lookup', a],
        ['submit', s], ['rm_batch'], ['close', 0, None], ['settle'], ['view'],
        ['submit', b], ['result', files.result(b)], ['rm_batch'], ['close', 1, None], ['settle'], ['view'],
    ])
    case('lookups', [
        ['lookup', a], ['lookup', s], ['lookup', v1(ids['missing'])], ['lookup', {'record_id': ids['cache']}],
        *_round(a, files.result(a)), ['deny_cache'], ['lookup', a], ['submit', a], ['saved', None, a],
        ['allow_cache'], ['lookup', a],
        # A verified file is kept by its state: once read, a mode change alone does not make it unreadable.
        ['deny_cache'], ['lookup', a], ['saved', None, a], ['allow_cache'], ['submit', a], ['view'],
    ])
    case('catalog', [
        ['catalog'],
        ['change', 'stub/catalog.txt', jsjson.stringify({**CATALOG, 'schema_version': 'source-catalog/0'})],
        ['catalog'], ['change', 'stub/catalog.txt', jsjson.stringify({**CATALOG, 'sources': CATALOG['sources'][1:]})],
        ['catalog'], ['change', 'stub/catalog.txt', 'exit:3'], ['catalog'], ['change', 'stub/catalog.txt', ''],
        ['catalog'], ['change', 'stub/catalog.txt', 'null'], ['catalog'],
        ['change', 'stub/catalog.txt', '{"schema_version":"source-catalog/1","sources":{"length":256}}'], ['catalog'],
    ])
    assert tuple(item['id'] for item in cases) == CASE_IDS
    return cases


def _saved_steps(files: Files, ids: dict) -> list:
    """``savedResult`` of a computed record, then of stored records written as other versions and other workspaces
    left them: each failure in Node's order."""
    a, s = v1(ids['cache']), single(ids['strict'])
    layout = files.records[ids['strict']]['layout']
    request = normalize_reception_request(s)

    def put(kind: str, key: str, value: Any) -> list:
        return ['put', f'{kind}/{key}/cache.json', files.text(value) if isinstance(value, str) else files.value(value)]

    def v1_cache(key: str, value: dict, **members: Any) -> dict:
        return {'key': key, 'result': value, 'result_sha256': _hash(value), **members}

    old = result(a, files.records[ids['cache']]['layout'])
    regions = copy.deepcopy(old)
    regions['layout']['regionIndices'] = [i % 5 for i in range(64)]
    labels = copy.deepcopy(old)
    labels['layout']['regionIndices'] = [i % 2 + 1 for i in range(64)]
    points = copy.deepcopy(old)
    points['layout']['xyzMm'][1] = points['layout']['xyzMm'][0]
    no_layout = {**copy.deepcopy(old), 'layout': {}}
    stale = fixture(request, layout)
    identity = {'layout': copy.deepcopy(layout), 'version': 'old-model'}
    key = jsjson.sha256_hex({'request': request, 'identity': identity})
    moved = copy.deepcopy(stale)
    moved['layout']['xyzMm'][0][0] += 1.25
    keys = {name: str(n) * 64 for n, name in enumerate(('one', 'two', 'three', 'four', 'five', 'six', 'seven',
                                                       'eight', 'nine'), 1)}
    source, v2 = SOURCE_JOBS, SOURCE_V2_JOBS
    return [
        *_round(a, files.result(a)), ['saved', None, a], ['saved', None, {**a, 'seed': 43}],
        ['saved', '../../cache', a],
        ['saved', 'A' * 64, a], ['saved', 123, a], ['saved', 'f' * 64, a], ['saved', None, s], ['saved', None, {}],
        put(source, keys['one'], v1_cache(keys['one'], no_layout)), ['saved', keys['one'], a],
        put(source, keys['two'], v1_cache(keys['two'], regions)), ['saved', keys['two'], a],
        put(source, keys['three'], v1_cache(keys['three'], points)), ['saved', keys['three'], a],
        put(source, keys['four'], v1_cache('f' * 64, old)), ['saved', keys['four'], a],
        put(source, keys['five'], {**v1_cache(keys['five'], old), 'result_sha256': _hash('tampered')}),
        ['saved', keys['five'], a],
        put(source, keys['six'], 'null'), ['saved', keys['six'], a],
        ['put_size', f'{source}/{keys["seven"]}/cache.json', CACHE_LIMIT + 1], ['saved', keys['seven'], a],
        ['put_dir', f'{source}/{keys["eight"]}/cache.json'], ['saved', keys['eight'], a],
        put(source, keys['nine'], v1_cache(keys['nine'], labels)), ['saved', keys['nine'], a],
        # Node's :335: the frozen identity layout, not today's model, decides.
        put(v2, key, {'key': key, 'identity': identity, 'result': stale, 'result_sha256': _hash(stale)}),
        ['saved', key, s], ['lookup', s],
        put(v2, key, {'key': key, 'identity': identity, 'result': moved, 'result_sha256': _hash(moved)}),
        ['saved', key, s],
        put(v2, key, {'key': key, 'result': {**stale, 'layout': {}}, 'result_sha256': _hash({**stale, 'layout': {}})}),
        ['saved', key, s],
        put(v2, keys['one'], {'key': keys['one'], 'identity': identity, 'result': stale,
                              'result_sha256': _hash(stale)}),
        ['saved', keys['one'], s],
        put(v2, keys['two'], {'key': keys['two'], 'identity': {'version': 'no layout'}, 'result': stale,
                              'result_sha256': _hash(stale)}),
        ['saved', keys['two'], s],
    ]


def build(case: dict) -> None:
    """Builds the case's root (again, at the same path, for the second run; Node's is ``root.node`` by then)."""
    if Path(case['root']).exists():
        shutil.rmtree(case['root'])
    built = reception_root(Path(case['directory']))
    assert built['root'] == case['root']


# --- Runs ----------------------------------------------------------------------------------------------------------

def brief(text: str) -> str:
    """A record text, or ``sha256:<hex>`` of one longer than ``BRIEF`` UTF-8 bytes (a result is about 1 MB)."""
    data = _utf8(text)
    return text if len(data) <= BRIEF else 'sha256:' + hashlib.sha256(data).hexdigest()


_SENTINEL = '\x00result\x00'


class _Texts:
    """``JSON.stringify`` of a record whose result (a view's, a hit's or a saved one, about 1 MB) is written once
    per result object: the service hands the same object to every view of a job and every read of a verified
    record, and the port of ``JSON.stringify`` takes about 0.4 s for one."""

    def __init__(self):
        self._texts: dict[int, tuple[Any, str]] = {}

    def _result(self, value: Any) -> str:
        entry = self._texts.get(id(value))
        if entry is None or entry[0] is not value:
            entry = self._texts[id(value)] = (value, jsjson.stringify(value))
        return entry[1]

    def __call__(self, value: Any) -> str:
        if isinstance(value, dict) and isinstance(value.get('waveforms'), dict):
            return self._result(value)
        holder = value.get('job') if isinstance(value, dict) else None
        view = holder if isinstance(holder, dict) else value
        if not isinstance(view, dict) or not isinstance(view.get('result'), dict):
            return jsjson.stringify(value)
        spliced = {**view, 'result': _SENTINEL}
        text = jsjson.stringify({**value, 'job': spliced} if view is holder else spliced)
        return text.replace(jsjson.stringify(_SENTINEL), self._result(view['result']), 1)


def _message(error: BaseException) -> str:
    message = getattr(error, 'message', None)
    return message if isinstance(message, str) else node_message(error)


def _truncate(path: str, size: int) -> None:
    with open(path, 'ab'):
        pass
    os.truncate(path, size)


async def run_case(item: dict) -> dict:
    """The Python side of one case: ``ReceptionJobs`` on the root's ``Library`` driven by the steps the Node driver
    runs."""
    clock, ids = PinnedClock(**item['clock']), PinnedIds()
    records: list[list[str]] = []
    children: list[FakeChild] = []
    texts = _Texts()

    def make(options: dict) -> ReceptionJobs:
        thrown = options['throw'] if 'throw' in options else item['throw']
        runtime = runtime_config(item['root'], item['python'])
        return ReceptionJobs(runtime.repository_root, runtime.native_python,
                             Library(runtime.repository_root, runtime), compute_python=runtime.python,
                             timeout_ms=item['timeoutMs'], spawn=Spawner(thrown, children), clock=clock,
                             random_uuid=ids)

    jobs, current, release = make({}), None, None
    retired: list[ReceptionJobs] = []  # the services a restart replaced (Node's are only disposed)

    async def record(kind: str, run: Callable[[], Any]) -> Any:
        try:
            value = run()
            if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
                value = await value
            records.append([kind, brief(texts(None if value is UNDEFINED else value))])
            return value
        except Exception as error:  # noqa: BLE001 - recorded as Node records a throw
            records.append([kind, brief(jsjson.stringify({'error': _message(error)}))])
            return None

    def batch() -> str:
        return jobs.jobs[current].batch

    try:
        for kind, *args in item['steps']:
            child = children[-1] if children else None
            if kind == 'submit':
                value = await record(kind, lambda: jobs.submit(args[0]))
                if isinstance(value, dict) and 'job' in value:
                    current = value['job']['id']
            elif kind == 'submit_pair':
                first = asyncio.ensure_future(jobs.submit(args[0]))
                second = asyncio.ensure_future(jobs.submit(args[1]))
                value = await record(kind, lambda: first)
                await record(kind, lambda: second)
                if isinstance(value, dict) and 'job' in value:
                    current = value['job']['id']
            elif kind == 'lookup':
                await record(kind, lambda: jobs.lookup(args[0]))
            elif kind == 'saved':
                await record(kind, lambda: jobs.saved_result(jobs.jobs[current].key if args[0] is None else args[0],
                                                             args[1]))
            elif kind == 'catalog':
                await record(kind, jobs.catalog)
            elif kind == 'view':
                await record(kind, lambda: jobs.view(jobs.jobs[current]))
            elif kind == 'jobs':
                await record(kind, lambda: list(jobs.jobs))
            elif kind == 'pid':
                await record(kind, jobs.active_pid)
            elif kind == 'cancel':
                await record(kind, lambda: jobs.cancel(current) if args[0] is None else jobs.cancel(current, args[0]))
            elif kind == 'cancel_id':
                await record(kind, lambda: jobs.cancel(args[0]))
            elif kind == 'stop':
                await record(kind, lambda: jobs.jobs[current].worker.stop(args[0]))
            elif kind == 'dispose':
                jobs.dispose()
            elif kind == 'restart':
                jobs.dispose()
                retired.append(jobs)
                jobs = make(args[0])
            elif kind == 'acquire':
                def acquire() -> bool:
                    nonlocal release
                    release = jobs.execution_slot.acquire('other')
                    return release is not None
                await record(kind, acquire)
            elif kind == 'release':
                if release is not None:
                    release()
                release = None
            elif kind == 'pause':
                jobs.execution_slot.pause()
            elif kind == 'resume':
                jobs.execution_slot.resume()
            elif kind == 'stdout':
                child.stdout(base64.b64decode(args[0]))
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
            elif kind == 'result':
                shutil.copyfile(args[0], os.path.join(batch(), 'result.json'))
            elif kind == 'result_text':
                Path(batch(), 'result.json').write_bytes(args[0].encode('utf-8'))
            elif kind == 'result_size':
                _truncate(os.path.join(batch(), 'result.json'), args[0])
            elif kind == 'result_dir':
                os.mkdir(os.path.join(batch(), 'result.json'))
            elif kind == 'rm_batch':
                shutil.rmtree(batch())
            elif kind == 'block_cache':
                os.mkdir(os.path.join(jobs.jobs[current].directory, 'cache.json'))
            elif kind == 'write_cache':
                job = jobs.jobs[current]
                if args[0] == 'text':
                    body = args[1]
                else:
                    value = jsjson.parse(Path(args[1]).read_bytes().decode('utf-8'))
                    body = jsjson.stringify({'key': job.key, **({'identity': job.ctx['identity']}
                                                                if 'mode' in job.request else {}),
                                             'result': value,
                                             'result_sha256': _hash(value if args[0] == 'valid' else 'tampered'),
                                             'finished_at': '2026-01-01T00:00:00.000Z'})
                Path(job.directory, 'cache.json').write_bytes(body.encode('utf-8'))
            elif kind in ('deny_cache', 'allow_cache'):
                os.chmod(os.path.join(jobs.jobs[current].directory, 'cache.json'), 0 if kind == 'deny_cache' else 0o600)
            elif kind in ('put', 'put_size', 'put_dir'):
                path = Path(item['root'], args[0])
                path.parent.mkdir(parents=True, exist_ok=True)
                if kind == 'put':
                    shutil.copyfile(args[1], path)
                elif kind == 'put_size':
                    _truncate(str(path), args[1])
                else:
                    path.mkdir()
            elif kind == 'change':
                Path(item['root'], args[0]).write_bytes(args[1].encode('utf-8'))
            else:
                raise ValueError(f'unknown step {kind}')
        await until(lambda: jobs.active is None, SETTLE)
    finally:
        if release is not None:
            release()
        await bounded_aclose(*retired, jobs)
    environment = process_env()  # Node's process.env
    return {
        'id': item['id'], 'records': records, 'clock': clock.calls, 'ids': ids.count,
        'children': [{
            'executable': c.executable, 'args': c.args, 'cwd': c.options['cwd'], 'stdio': c.options['stdio'],
            'detached': c.options['detached'], 'shell': c.options['shell'],
            'env': {name: c.options['env'].get(name) for name in WORKER_ENV},
            'inherits': all(name in WORKER_ENV or c.options['env'].get(name) == value
                            for name, value in environment.items()),
            'added': sorted(name for name in c.options['env'] if name not in environment and name not in WORKER_ENV),
            'kills': c.kills,
        } for c in children],
    }


def run_python(case: dict) -> dict:
    return asyncio.run(run_case(case))


# A developer's exported worker interpreter, which the driver must drop: the Python side configures its cases with
# env={}, and a case without python would otherwise name another interpreter (and another v2 key) on Node's side.
EXPORTED_PYTHON = {'EEG_COMPUTE_PYTHON': '/eeg-layout-lab/exported/python'}
# A variable whose bytes are not UTF-8, in both hosts' environments for the run path (test_source.py sets it here):
# the workers must get it as Node's {...process.env} passes it, U+FFFD as UTF-8, which ``inherits`` compares.
NOT_UTF8 = {'EEG_RECEPTION_NOT_UTF8': os.fsdecode(b'a\xffb')}


def run_node(spec: dict, scratch: Path, name: str = 'reception', env: Optional[dict] = None) -> dict:
    """Runs ``parity/reception_run.mjs`` once over ``spec`` (its header documents the members), with
    ``EXPORTED_PYTHON`` and ``env`` in its environment; the queue directory is only resolved, never created."""
    queue = scratch / 'node-queue'
    spec_path, out_path = scratch / f'{name}-spec.json', scratch / f'{name}-node.json'
    spec_path.write_text(jsjson.stringify({'queueDirectory': str(queue), **spec}), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec_path), str(out_path)], check=True, cwd=ROOT,
                   env={**NODE_ENV, **EXPORTED_PYTHON, **(env or {})}, timeout=1200)
    assert not queue.exists()
    output = json.loads(out_path.read_text(encoding='utf-8'))
    output['by_id'] = {case['id']: case for case in output['cases']}
    return output


def run_node_cases(cases: list[dict], scratch: Path) -> dict:
    """Node's ``SourceReceptionService`` over every run-path case once."""
    keep = ('id', 'root', 'python', 'timeoutMs', 'throw', 'clock', 'steps')
    return run_node({'mode': 'runs', 'cases': [{k: case[k] for k in keep} for case in cases]}, scratch, 'reception-run',
                    NOT_UTF8)


def record_tree(root: Path, kind: str) -> dict[str, Any]:
    """Every directory (``None``) and file (its bytes) under ``root/kind``, by relative path."""
    base = root / kind
    tree: dict[str, Any] = {}
    for directory, names, files in os.walk(base):
        for name in names:
            tree[os.path.relpath(os.path.join(directory, name), base)] = None
        for name in files:
            path = os.path.join(directory, name)
            tree[os.path.relpath(path, base)] = Path(path).read_bytes()
    return tree


# --- Contexts (test_key_parity.py) -----------------------------------------------------------------------------------

def outcome_error(error: BaseException) -> dict:
    """A Python context failure in the compared form (key_parity_support.node_outcome): by Node's code where the
    error has one (system errors; an inspector's exit code), by name for text that is not JSON, else by message."""
    code = getattr(error, 'code', None)
    if isinstance(code, str) or (isinstance(code, int) and not isinstance(code, bool) and code):
        return {'code': code}
    if isinstance(error, OSError) and error.errno in errno.errorcode:
        return {'code': errno.errorcode[error.errno]}
    if isinstance(error, jsjson.JSONSyntaxError):
        return {'name': 'SyntaxError'}
    return {'message': _message(error)}


class ReceptionCases:
    """``ReceptionJobs.context`` over the driver's ``contexts`` cases: the root's ``LocalComputeQueue``
    configuration, a library of the root and the service of its interpreters, fresh per case or, with ``reuse``,
    one per root and configuration (as the driver shares Node's). The permit never takes the installation lock."""

    def __init__(self, reuse: bool = False):
        self.reuse = reuse
        self._services: dict[str, Any] = {}

    def _service(self, case: dict) -> tuple[ReceptionJobs, dict]:
        id = jsjson.stringify([case['root'], case.get('python')])
        config = runtime_config(case['root'], case.get('python'), env={})
        described = {'repositoryRoot': config.repository_root, 'python': config.python,
                     'nativePython': config.native_python}
        if self.reuse and id in self._services:
            return self._services[id], described
        service = ReceptionJobs(config.repository_root, config.native_python,
                                Library(config.repository_root, config), compute_python=config.python,
                                execution_slot=ExecutionSlot())
        if self.reuse:
            self._services[id] = service
        return service, described

    def run(self, case: dict) -> dict:
        outcome: dict[str, Any] = {'id': case['id'], 'ok': False}
        try:
            service, outcome['config'] = self._service(case)
            context = asyncio.run(service.context(case['request']))
        except Exception as error:  # noqa: BLE001 - every failure is compared with Node's
            outcome.update(outcome_error(error))
            return outcome
        finally:
            if not self.reuse and 'config' in outcome:
                asyncio.run(service.aclose())
        return {'id': case['id'], 'ok': True, 'config': outcome['config'], 'keys': list(context),
                'record': jsjson.stringify(context['record']), 'identity': jsjson.stringify(context['identity']),
                'key': context['key']}

    def close(self) -> None:
        for service in self._services.values():
            asyncio.run(service.aclose())
        self._services.clear()


def unused_installation_lock(path: Path) -> ExecutionSlot:
    """A slot whose installation lock file is ``path`` (never the root's)."""
    return ExecutionSlot(InstallationLock(str(path.parent), str(path)))
