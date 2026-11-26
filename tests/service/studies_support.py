"""Shared setup for the robustness-study tests (``test_studies.py``).

``parity/studies.mjs`` is the Node reference; ``run_driver`` runs one of its modes over a list of cases. In the
``aggregate`` mode each case is a JSON text that both sides parse and then revive: ``{"$js": "NaN"}``,
``"Infinity"``, ``"-Infinity"`` and ``"undefined"`` stand for the values JSON has no spelling for, and ``to_text``
writes such values (and ``-0``) that way. ``python_aggregate`` computes a case with ``eeglayoutlab.jobs.studies`` in
the driver's output form, and ``random_aggregate_cases`` draws case results, case lists and value lists with
JavaScript's awkward numbers: ``-0``, subnormals, doubles from random bits, sums that overflow, numbers mixed with
strings, booleans, ``null`` and containers.

The study store and service (``eeglayoutlab.server.workspace_studies``): ``StudyFixture`` is the ``fixture()`` of
check-robustness-studies.mjs for the workspace (a stand-in design-evaluation adapter whose identity is
``{protocol: 'unchanged-design-evaluation/1', version, head_id?}``, seeded ``cache.json`` files, a workspace queue
that never dispatches, the store under ``W/studies``). ``python_identity``, ``python_store`` and ``python_export`` run
the driver's ``identity``, ``store`` and ``export`` modes (documented in ``parity/studies.mjs``) in Python;
``outcome`` puts a failure in the compared form.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
from typing import Any, Awaitable, Callable, Optional
import uuid

from eeglayoutlab.jobs import queue as queue_module
from eeglayoutlab.jobs.identity import UNDEFINED
from eeglayoutlab.jobs.queue import WorkspaceQueue, iso
from eeglayoutlab.jobs.studies import (CASE_STATUSES, NOMINAL_METRICS, STUDY_PROTOCOLS, TRIAL_METRICS, StudyError,
                                       aggregate_study, empirical_summary, normalize_study_input, summarize_study_case)
from eeglayoutlab.schemas import jsjson
from eeglayoutlab.server.workspace import LOCAL_OWNER
from eeglayoutlab.server.workspace_studies import ResourceError, RobustnessStudyService, StudyStore

from .key_parity_support import NODE_ENV

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/studies.mjs'
_SPECIAL = {'NaN': math.nan, 'Infinity': math.inf, '-Infinity': -math.inf, 'undefined': UNDEFINED}


def run_driver(mode: str, cases: list[dict], scratch: Path, **spec: Any) -> dict:
    """Runs ``parity/studies.mjs`` once; returns its output with the cases by id."""
    spec_path, out_path = scratch / f'studies-{mode}.json', scratch / f'studies-{mode}-node.json'
    spec_path.write_text(jsjson.stringify({'mode': mode, **spec, 'cases': cases}), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV,
                   timeout=300)
    output = json.loads(out_path.read_text(encoding='utf-8'))
    output['by_id'] = {case['id']: case for case in output['cases']}
    return output


# --- Texts with the values JSON cannot spell -----------------------------------------------------------------------

def revive(value: Any) -> Any:
    """The driver's ``revive``: ``{"$js": name}`` objects become ``NaN``, the infinities or ``UNDEFINED``."""
    if isinstance(value, list):
        return [revive(item) for item in value]
    if isinstance(value, dict):
        if list(value) == ['$js']:
            return _SPECIAL[value['$js']]
        return {key: revive(child) for key, child in value.items()}
    return value


def to_text(value: Any) -> str:
    """A JSON text whose ``revive(JSON.parse(text))`` is ``value``, ``-0`` included."""
    if value is UNDEFINED:
        return '{"$js":"undefined"}'
    if isinstance(value, float) and not math.isfinite(value):
        return '{"$js":"%s"}' % ('NaN' if math.isnan(value) else 'Infinity' if value > 0 else '-Infinity')
    if isinstance(value, float) and value == 0 and math.copysign(1, value) < 0:
        return '-0'
    if isinstance(value, dict):
        return '{' + ','.join(jsjson.quote(key) + ':' + to_text(child) for key, child in value.items()) + '}'
    if isinstance(value, (list, tuple)):
        return '[' + ','.join(to_text(item) for item in value) + ']'
    return jsjson.stringify(value)


def js_stringify(value: Any) -> Any:
    """``JSON.stringify(value)``: an ``undefined`` member is left out, an ``undefined`` item is ``null``, and
    ``undefined`` itself gives ``None`` (the driver writes ``?? null``)."""
    if value is UNDEFINED:
        return None

    def plain(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: plain(child) for key, child in item.items() if child is not UNDEFINED}
        if isinstance(item, (list, tuple)):
            return [None if child is UNDEFINED else plain(child) for child in item]
        return item

    return jsjson.stringify(plain(value))


# --- The Python side of the aggregate mode -----------------------------------------------------------------------

def _aggregate(value: Any) -> dict:
    cases = value['cases'] if isinstance(value, dict) else UNDEFINED
    for entry in cases:
        if isinstance(entry, dict) and '$result' in entry:
            entry['summary'] = summarize_study_case(entry.pop('$result'))
    return aggregate_study(value.get('protocol', UNDEFINED), cases)


AGGREGATE_OPS = {'empirical': empirical_summary, 'summarize': summarize_study_case, 'aggregate': _aggregate}


def python_aggregate(case: dict) -> dict:
    """A case of the aggregate mode computed in Python, in the driver's output form (failures by name)."""
    value = revive(jsjson.parse(case['text']))
    try:
        result = AGGREGATE_OPS[case['op']](value)
    except TypeError as error:
        return {'id': case['id'], 'ok': False, 'name': 'TypeError', 'message': str(error)}
    return {'id': case['id'], 'ok': True, 'json': js_stringify(result), 'after': js_stringify(value)}


def node_form(output: dict) -> dict:
    """A driver result compared by outcome: V8's messages are not reproduced, so a failure compares by name."""
    if output['ok']:
        return output
    return {'id': output['id'], 'ok': False, 'name': output['name']}


# --- Cases ------------------------------------------------------------------------------------------------------

def _random_double(rng: random.Random) -> float:
    return struct.unpack('>d', rng.getrandbits(64).to_bytes(8, 'big'))[0]


def random_number(rng: random.Random) -> Any:
    """A number as a case result may hold it, or a value that is not a finite number."""
    kind = rng.random()
    if kind < 0.35:
        return rng.random()
    if kind < 0.5:
        return rng.choice([0, 1, 2, 0.5, 0.25, 1e-7, -0.0, 0.0, 100, 1 / 3, 0.1 + 0.2, 2 ** 53, 2 ** 53 + 2])
    if kind < 0.6:
        return rng.uniform(-1e3, 1e3)
    if kind < 0.7:
        return _random_double(rng)  # NaN and the infinities included
    if kind < 0.78:
        return rng.choice([1.7976931348623157e308, -1.7976931348623157e308, 1e308, -1e308, 5e-324, -5e-324,
                           2.2250738585072014e-308, 1e21, -1e-21])
    if kind < 0.86:
        return rng.randint(-10, 10)
    return rng.choice([None, True, False, '1', '', 'x', [], [1], {}, {'median': 1}, UNDEFINED, math.nan, math.inf])


def random_values(rng: random.Random, size: int | None = None) -> list:
    size = rng.choice([0, 1, 1, 2, 3, 4, 5, 7, 10, 11, 20, 33]) if size is None else size
    values = [random_number(rng) for _ in range(size)]
    if values and rng.random() < 0.3:
        values += rng.sample(values, k=min(len(values), 3))  # repeated readings
    return values


def random_trial(rng: random.Random) -> Any:
    if rng.random() < 0.03:
        return rng.choice([0, 'trial', [], [1, 2]])  # members of these are undefined, not a TypeError
    status = rng.choice(['completed', 'completed', 'completed', 'geometry_rejected', 'geometry_rejected', 'failed',
                         'Completed', None, UNDEFINED, 1])
    trial: dict = {} if status is UNDEFINED else {'status': status}
    for metric in TRIAL_METRICS:
        if rng.random() < 0.9:
            trial[metric] = None if status == 'geometry_rejected' and rng.random() < 0.8 else random_number(rng)
    if rng.random() < 0.3:
        trial['displacement_mm'] = [random_number(rng) for _ in range(3)]
    return trial


def random_result(rng: random.Random) -> dict:
    nominal = {metric: random_number(rng) for metric in NOMINAL_METRICS if rng.random() < 0.9}
    if rng.random() < 0.2:
        nominal.update({'1': 1, '0': rng.random(), 'extra': [random_number(rng)]})  # integer-like keys come first
    result: dict = {'schema': 'design-evaluation/1', 'status': 'completed'}
    if rng.random() < 0.97:
        result['nominal'] = nominal
    result['trials'] = [random_trial(rng) for _ in range(rng.choice([0, 1, 2, 4, 8, 10, 25]))]
    return result


RADII = [3, 6, 10, 3, 6, 10, 3.0, -0.0, 0, 4.5, 1e308, -1e308, 5e-324, 1e21]
# Values that are not numbers but convert to one, so `a - b` orders the radii consistently and every sort (Node 24's
# and 26's) gives one order; `undefined` goes to the end.
ODD_RADII = [None, True, False, '3', ' 6 ', '', [], [10], '0x10', '1e1', UNDEFINED]


def random_summary(rng: random.Random) -> Any:
    choice = rng.random()
    if choice < 0.1:
        return rng.choice([None, 0, '', False])
    return {'nominal': {metric: random_number(rng) for metric in NOMINAL_METRICS if rng.random() < 0.9},
            'trial_metrics': {metric: {'n': 1, 'median': random_number(rng), 'p10': random_number(rng)}
                              for metric in TRIAL_METRICS}}


def random_case_list(rng: random.Random) -> dict:
    radii = rng.sample(RADII, k=rng.choice([1, 1, 2, 3]))
    if rng.random() < 0.15:
        radii.append(rng.choice(ODD_RADII))
    cases = []
    for index in range(rng.choice([0, 1, 2, 3, 4, 5, 8, 12, 14])):
        radius = rng.choice(radii)
        status = rng.choice([*CASE_STATUSES, 'completed', 'completed', 'completed', '', None, 'COMPLETED', UNDEFINED])
        case: dict = {'index': index, 'request': {} if radius is UNDEFINED else {'radius_mm': radius}}
        if status is not UNDEFINED:
            case['status'] = status
        kind = rng.random()
        if kind < 0.6:
            case['$result'] = random_result(rng)
        elif kind < 0.85:
            case['summary'] = random_summary(rng)
        elif kind < 0.95:
            case['summary'] = None
        cases.append(case)
    protocol = rng.choice([*STUDY_PROTOCOLS, *STUDY_PROTOCOLS, 'other', None, 1, UNDEFINED])
    return {'cases': cases} if protocol is UNDEFINED else {'protocol': protocol, 'cases': cases}


def random_aggregate_cases(seed: int, count: int) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for i in range(count):
        op = ('empirical', 'summarize', 'aggregate')[i % 3]
        draw = {'empirical': random_values, 'summarize': random_result, 'aggregate': random_case_list}[op]
        value = draw(rng)
        out.append({'id': f'random-{op}-{i}', 'op': op, 'text': to_text(value)})
    return out


# --- The study fixture (check-robustness-studies.mjs) -------------------------------------------------------------

STUDY_DESIGN = {'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm',
                'name': 'Original scientific name', 'xyz_mm': [[(i % 8) * 6, (i // 8) * 6, 0] for i in range(64)],
                'region_indices': [i % 2 for i in range(64)]}
FIXTURE_PROTOCOL = 'unchanged-design-evaluation/1'
INTERRUPTED = '服务重启中断了计算，可重新提交'
DESIGN_JOBS = 'results/v2/design_evaluation_jobs'


def study_input(seeds: tuple = (42, 43), **extra: Any) -> dict:
    """``input(seeds, extra)`` of the check."""
    return {'protocol': 'noise_seeds', 'design': STUDY_DESIGN,
            'cases': [{'seed': seed, 'radius_mm': 6} for seed in seeds], **extra}


def heads_input(*heads: str, seed: int = 42) -> dict:
    return study_input((), protocol='heads', cases=[{'head_id': head, 'seed': seed, 'radius_mm': 6} for head in heads])


def result_for(request: dict) -> dict:
    """``resultFor(request)``: a result ``validateDesignResult`` accepts for an evaluation request."""
    return {'schema': 'design-evaluation/1', 'status': 'completed', 'request': request,
            'forward_mode': 'head_scalp_node_table' if request.get('head_id') else 'cached_fem',
            'nominal': {'field_relative': 0.9, 'field_absolute': 0.81, 'reference_field_absolute': 0.9,
                        'sensitivity_tail': 0.8, 'localization_relative': 0.7, 'median_mm': 10, 'p90_mm': 20,
                        'reference_median_mm': 9, 'reference_p90_mm': 18},
            'evaluated_xyz_mm': request['design']['xyz_mm'], 'projection_max_mm': 0, 'trials': [],
            'provenance': {'candidate_count': 64, 'original_values': [1 / 3, -1e-18, 1.0000000000000002]}}


def fixture_identity(request: Any, version: int = 1) -> dict:
    """The fixture's scientific identity: a head request adds its own package, as ``scientificContext`` does."""
    head = request.get('head_id') if isinstance(request, dict) else None
    return {'protocol': FIXTURE_PROTOCOL, 'version': version, **({'head_id': head} if head else {})}


def case_key(request: dict, version: int = 1) -> str:
    return jsjson.sha256_hex({'request': request, 'identity': fixture_identity(request, version)})


def pretty(value: Any, indent: str = '') -> str:
    """``JSON.stringify(value, null, 2)``."""
    inner = indent + '  '
    if isinstance(value, dict) and value:
        return '{\n' + ',\n'.join(f'{inner}{jsjson.quote(key)}: {pretty(item, inner)}'
                                  for key, item in value.items()) + '\n' + indent + '}'
    if isinstance(value, list) and value:
        return '[\n' + ',\n'.join(inner + pretty(item, inner) for item in value) + '\n' + indent + ']'
    return jsjson.stringify(value)


def cache_text(request: dict, version: int = 1, result: Any = None) -> tuple[str, str]:
    """``seedCache``'s file for ``request``: ``(key, JSON.stringify(cache, null, 2) + '\n')``."""
    identity = fixture_identity(request, version)
    key = case_key(request, version)
    result = result_for(request) if result is None else result
    cache = {'key': key, 'identity': identity, 'result': result, 'result_sha256': jsjson.sha256_hex(result),
             'finished_at': '2026-11-14T12:00:00.000Z'}
    return key, pretty(cache) + '\n'


def prepared_for(raw: Any, version: int = 1) -> dict:
    """What the service passes to ``StudyStore.create`` for ``raw`` with the fixture's identity."""
    normalized = normalize_study_input(raw)
    heads = normalized['protocol'] == 'heads'
    cases, identity = [], None
    for index, request in enumerate(normalized['requests']):
        identity = jsjson.sha256_hex(fixture_identity(request, version))
        entry = {'index': index, 'request': request, 'key': case_key(request, version)}
        if heads:
            entry['identity_sha256'] = identity
        entry.update({'status': 'pending', 'receipt_id': None, 'error': None})
        cases.append(entry)
    metadata = {name: value for name, value in normalized.items() if name != 'requests'}
    return {**metadata,
            'identity_sha256': jsjson.sha256_hex([entry['identity_sha256'] for entry in cases]) if heads else identity,
            'cases': cases}


class StubDesignAdapter:
    """The fixture's ``design-evaluation`` adapter: ``prepare`` unwraps ``design-submission/1`` and normalizes the
    request (waiting for ``hold`` while it is set), ``lookup`` reads ``<root>/results/v2/design_evaluation_jobs/<key>/
    cache.json`` and validates its result (a miss first awaits ``before_new_work``, where Node's queue calls its
    ``beforeNewWork``), and ``start`` counts and fails: these tests never launch a worker."""

    def __init__(self, root: Path):
        self.root = root
        self.version = 1
        self.hold: Optional[asyncio.Event] = None
        self.before_new_work: Optional[Callable[[], Awaitable[None]]] = None
        self.preparations = 0
        self.starts = 0

    def cache_path(self, key: str) -> Path:
        return self.root / DESIGN_JOBS / key / 'cache.json'

    async def prepare(self, raw: Any) -> dict:
        from eeglayoutlab.jobs.design_result import normalize_design_request

        self.preparations += 1
        if self.hold is not None:
            await asyncio.wait_for(self.hold.wait(), 60)
        submitted = isinstance(raw, dict) and raw.get('schema') == 'design-submission/1'
        request = normalize_design_request(raw['request'] if submitted else raw)
        ctx = {'identity': fixture_identity(request, self.version)}
        return {'request': request, 'key': jsjson.sha256_hex({'request': request, 'identity': ctx['identity']}),
                'ctx': ctx}

    async def lookup(self, prepared: dict) -> dict:
        from eeglayoutlab.jobs.design_result import validate_design_result

        try:
            cache = jsjson.parse(self.cache_path(prepared['key']).read_text(encoding='utf-8'))
            validate_design_result(cache['result'], prepared['request'])
        except Exception:  # noqa: BLE001 - the fixture's catch-all
            if self.before_new_work is not None:
                await self.before_new_work()
            return {'hit': False}
        return {'hit': True, 'job': {'id': str(uuid.uuid4()), 'key': prepared['key'], 'request': prepared['request'],
                                     'status': 'completed', 'cached': True, 'result': cache['result']}}

    async def start(self, prepared: dict) -> dict:
        self.starts += 1
        raise AssertionError('Studies unit tests must not launch a scientific worker')

    def get(self, id: Any) -> None:
        return None

    def busy(self) -> bool:
        return False

    def pid(self) -> None:
        return None

    def cancel(self, id: Any) -> None:
        return None


class StudyFixture:
    """``fixture(t, {cached, studyLimits, beforeWrite, beforeNewWork})`` as an async context manager: ``root`` (R)
    holds the caches, ``workspace`` (W) the queue (``W/.eeglayoutlab``) and the studies (``W/studies``). The queue is
    never started, so a submitted case stays ``queued``. ``before_write`` is the store's hook (kept by ``restart``);
    the exit stops the service, waits for it, closes it and disposes of the queue, as the check's ``t.after``
    does."""

    def __init__(self, base: Path, *, cached: bool = True, limits: Optional[dict] = None,
                 before_write: Optional[Callable[[], Any]] = None):
        base = Path(os.path.realpath(base))
        self.root = base / 'root'
        self.workspace = base / 'workspace'
        self.root.mkdir(parents=True)
        self.workspace.mkdir(parents=True)
        self.cached = cached
        self.limits = limits
        self.before_write = before_write or (lambda: None)
        self.adapter = StubDesignAdapter(self.root)

    async def __aenter__(self) -> 'StudyFixture':
        self.scheduler = WorkspaceQueue(str(self.workspace / '.eeglayoutlab'), {'design-evaluation': self.adapter},
                                        boot_id=lambda: 'study-tests')
        self.store = StudyStore(str(self.workspace / 'studies'), before_write=self.before_write, limits=self.limits)
        self.service = RobustnessStudyService(self.scheduler, str(self.root), store=self.store, poll_seconds=3600)
        if self.cached:
            for request in normalize_study_input(study_input())['requests']:
                self.seed_cache(request)
        await self.service.ready()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        try:
            await asyncio.wait_for(self.service.aclose(), 60)  # stop, flush (a failed recovery is logged), close
        finally:
            self.scheduler.dispose()

    def seed_cache(self, request: dict, version: Optional[int] = None) -> dict:
        """``seedCache(request)``: ``{key, bytes, path}`` of the written ``cache.json``."""
        key, text = cache_text(request, self.adapter.version if version is None else version)
        path = self.adapter.cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return {'key': key, 'bytes': text, 'path': path}

    async def restart(self) -> RobustnessStudyService:
        self.service.stop()
        await asyncio.wait_for(self.service.flush(), 60)
        self.service.close()
        self.service = RobustnessStudyService(
            self.scheduler, str(self.root), poll_seconds=3600,
            store=StudyStore(self.store.directory, before_write=self.before_write))
        await self.service.ready()
        return self.service

    async def flush(self) -> None:
        await asyncio.wait_for(self.service.flush(), 60)


def blocked(kind: Optional[str]) -> Optional[BaseException]:
    """The check's refusals: a resource refusal (503, ``resourceSafe``) or a study quota (507, ``studySafe``)."""
    if kind == 'resource':
        return ResourceError('Resource blocked', 503)
    if kind == 'quota':
        return StudyError('Study quota', 507)
    return None


# --- The parity modes in Python -----------------------------------------------------------------------------------

def outcome(error: BaseException) -> dict:
    """A failure as the driver records it, without the name (V8's error classes are not Python's)."""
    safe = any(getattr(error, name, False) is True for name in ('study_safe', 'resource_safe', 'project_safe'))
    status = getattr(error, 'status', None)
    code = getattr(error, 'code', None)
    return {'ok': False, 'status': status if isinstance(status, int) else None, 'safe': safe,
            'message': error.message if safe else None, 'code': code if isinstance(code, str) else None}


def node_outcome(entry: dict) -> dict:
    return {name: value for name, value in entry.items() if name != 'name'}


async def _record(run: Callable[[], Awaitable[Any]]) -> dict:
    try:
        value = await run()
    except Exception as error:  # noqa: BLE001 - recorded
        return outcome(error)
    return {'ok': True, 'value': None if value is None else jsjson.stringify(value)}


def sequence(prefix: str) -> Callable[[], str]:
    count = [0]

    def next_id() -> str:
        count[0] += 1
        return f'{prefix}-0000-4000-8000-{count[0]:012d}'
    return next_id


def tree(directory: Path) -> list:
    """The driver's ``tree``."""
    rows: list = []

    def walk(relative: str) -> None:
        folder = directory / relative if relative else directory
        for name in sorted(os.listdir(os.fsencode(folder))):
            text = os.fsdecode(name)
            path = f'{relative}/{text}' if relative else text
            full = directory / path
            info = full.lstat()
            mode = info.st_mode & 0o777
            if full.is_symlink():
                rows.append([path, 'link', mode, os.readlink(full)])
            elif full.is_dir():
                rows.append([path, 'dir', mode, None])
                walk(path)
            else:
                rows.append([path, 'file', mode, base64.b64encode(full.read_bytes()).decode('ascii')])

    if directory.is_dir() and not directory.is_symlink():
        walk('')
    return rows


def apply_change(value: dict, change: dict) -> None:
    for path, item in change.get('set', []):
        target = value
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = revive(item)
    for path in change.get('delete', []):
        target = value
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]


def _file_step(directory: Path, kind: str, args: list) -> bool:
    at = lambda path: Path(os.path.normpath(directory / path))  # noqa: E731 - Node's join normalizes
    if kind == 'write':
        at(args[0]).write_bytes(base64.b64decode(args[1]))
    elif kind == 'symlink':
        os.symlink(args[0], at(args[1]))
    elif kind == 'link':
        os.link(at(args[0]), at(args[1]))
    elif kind == 'mkdir':
        at(args[0]).mkdir()
    elif kind == 'rm':
        path = at(args[0])
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    elif kind == 'chmod':
        os.chmod(at(args[0]), args[1])
    elif kind == 'rename':
        os.rename(at(args[0]), at(args[1]))
    elif kind == 'copy':
        with open(at(args[1]), 'xb') as handle:
            handle.write(at(args[0]).read_bytes())
    else:
        return False
    return True


STORE_EPOCH = 1795564800000  # 2026-11-25T00:00:00.000Z


async def _store_case(item: dict, owner: str) -> dict:
    directory = Path(item['directory'])
    state = {'step': 0, 'before': None}

    def before_write() -> None:
        error = blocked(state['before'])
        if error is not None:
            raise error

    store = StudyStore(str(directory), now=lambda: iso(STORE_EPOCH + 1000 * state['step']), limits=item.get('limits'),
                       before_write=before_write, random_uuid=sequence('5d5d0000'), owner=owner)
    out = []
    for kind, *args in item['steps']:
        state['step'] += 1
        if kind == 'before':
            state['before'] = args[0]
            out.append({'ok': True, 'value': None})
            continue
        if _file_step(directory, kind, args):
            out.append({'ok': True, 'value': None})
            continue

        async def run(kind: str = kind, args: list = args) -> Any:
            if kind == 'create':
                return await store.create(revive(args[0]))
            if kind in ('update', 'control'):
                return await store.update(args[0], lambda value: apply_change(value, args[1]),
                                          control=kind == 'control')
            if kind == 'archive':
                return await store.archive(args[0], args[1], base64.b64decode(args[2]))
            if kind == 'load':
                return await store.load(args[0])
            if kind == 'all':
                return await store.all()
            if kind == 'ids':
                return await store.ids()
            if kind == 'usage':
                return await store.usage()
            if kind == 'present':
                return await store.present(args[0], args[1])
            if kind == 'snapshot':
                value = await store.load(args[0])
                cache, text = await store.snapshot(value, value['cases'][args[1]])
                return {'cache': cache, 'cache_json': text}
            raise ValueError(f'unknown step {kind}')
        out.append(await _record(run))
    await store.flush()
    return {'id': item['id'], 'records': out, 'tree': tree(directory)}


def python_store(item: dict, owner: str = LOCAL_OWNER) -> dict:
    return asyncio.run(_store_case(item, owner))


async def _identity_case(item: dict, now: str) -> dict:
    from eeglayoutlab.jobs.design import DesignJobs
    from eeglayoutlab.jobs.kinds import design_evaluation_adapter
    from eeglayoutlab.jobs.runtime import runtime_config

    base = Path(item['base'])
    runtime = runtime_config(item['root'], item['python'])
    design = DesignJobs(runtime.repository_root, runtime.native_python)
    queue = WorkspaceQueue(str(base / 'queue'), {'design-evaluation': design_evaluation_adapter(design)},
                           boot_id=lambda: 'study-tests')
    store = StudyStore(str(base / 'studies'), now=lambda: now, random_uuid=lambda: item['study_id'])
    service = RobustnessStudyService(queue, runtime.repository_root, store=store, poll_seconds=3600)
    try:
        created = await service.create(revive(item['input']))
        result = {'ok': True, 'response': jsjson.stringify(created),
                  'bytes': (base / 'studies' / created['study']['id'] / 'study.json').read_text(encoding='utf-8'),
                  'tasks': len(queue.tasks)}
    except Exception as error:  # noqa: BLE001 - recorded
        result = {**outcome(error), 'tasks': len(queue.tasks)}
    finally:
        await service.aclose()
        queue.dispose()
        design.dispose()
    return {'id': item['id'], **result}


def python_identity(item: dict, now: str) -> dict:
    return asyncio.run(_identity_case(item, now))


async def _export_case(item: dict) -> dict:
    root, queue_directory, studies = Path(item['root']), item['queue'], item['studies']
    adapter = StubDesignAdapter(root)

    def write_cache(key: str, text: Optional[str]) -> None:
        path = adapter.cache_path(key)
        if text is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode('utf-8'))

    for key, text in item['caches']:
        write_cache(key, text)
    calls = [0]

    def clock() -> str:
        value = item['clock']['start'] + item['clock']['step'] * calls[0]
        calls[0] += 1
        return iso(value)

    study_ids, operation_ids, receipt_ids = sequence('5d5d0000'), sequence('0e0e0000'), sequence('7e7e0000')
    scheduler = WorkspaceQueue(queue_directory, {'design-evaluation': adapter}, boot_id=lambda: 'study-tests',
                               now=lambda: item['clock']['start'])

    def make() -> RobustnessStudyService:
        return RobustnessStudyService(scheduler, str(root), poll_seconds=3600, clock=clock, random_uuid=operation_ids,
                                      store=StudyStore(studies, now=clock, random_uuid=study_ids))

    service = make()
    current: list = [None]
    out = []
    for kind, *args in item['steps']:
        async def run(kind: str = kind, args: list = args) -> Any:
            nonlocal service
            if kind == 'create':
                created = await service.create(revive(args[0]))
                current[0] = created['study']['id']
                return created
            if kind == 'start':
                return await service.start(current[0], args[0])
            if kind == 'cancel':
                return await service.cancel(current[0])
            if kind == 'flush':
                return await asyncio.wait_for(service.flush(), 60)
            if kind == 'get':
                return await service.get(current[0])
            if kind == 'list':
                return await service.list()
            if kind == 'export':
                return await service.export(current[0])
            if kind == 'restart':
                service.stop()
                await asyncio.wait_for(service.flush(), 60)
                service.close()
                service = make()
                return await service.ready()
            if kind == 'version':
                adapter.version = args[0]
                return None
            if kind == 'task':
                scheduler.tasks[args[0]].update(args[1])
                return None
            if kind == 'tasks':
                return [{'id': task['id'], 'key': task['key'], 'status': task['status'],
                         **({'message': task['message']} if 'message' in task else {})} for task in scheduler.tasks]
            if kind == 'case':
                return await service.store.update(
                    current[0], lambda value: (value if args[0] is None else value['cases'][args[0]]).update(args[1]))
            if kind == 'cache':
                write_cache(args[0], args[1])
                return None
            if kind == 'symlink_key':
                directory = adapter.cache_path(args[0]).parent
                shutil.copytree(directory, f'{directory}.copy')
                shutil.rmtree(directory)
                os.symlink(f'{directory}.copy', directory)
                return None
            raise ValueError(f'unknown step {kind}')
        original = queue_module.uuid
        queue_module.uuid = _PinnedUuid(receipt_ids)  # the queue's receipt identifiers
        try:
            out.append(await _record(run))
        finally:
            queue_module.uuid = original
    service.stop()
    await asyncio.wait_for(service.flush(), 60)
    service.close()
    scheduler.dispose()
    study = Path(studies) / current[0] if current[0] else None
    return {'id': item['id'], 'records': out,
            'study': (study / 'study.json').read_text(encoding='utf-8') if study else None,
            'snapshots': sorted(os.listdir(study / 'snapshots')) if study else None}


class _PinnedUuid:
    def __init__(self, ids: Callable[[], str]):
        self.ids = ids

    def uuid4(self) -> str:
        return self.ids()


def python_export(item: dict) -> dict:
    return asyncio.run(_export_case(item))
