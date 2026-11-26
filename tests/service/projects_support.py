"""Shared setup for the research-project tests (``test_projects.py``).

``parity/projects.mjs`` is the Node reference (its modes ``store``, ``service`` and ``read`` are documented there);
``run_driver`` runs one mode over a list of cases. ``python_store``, ``python_service`` and ``python_read`` run the
same cases on ``eeglayoutlab.server.workspace_projects`` with the same clock (2026-11-25T00:00:<step>.000Z), the
same project and entry identifiers (``0a0a0000-0000-4000-8000-<k>``) and, for the key that becomes a new project's
``owner_key_hash``, Node's access key of the same create (``sha256('key-<n>')``), so both write the same bytes.
The access key a Python create returns is another key (``sha256('access-<n>')``, never stored); both sides record
it as ``'<access_key>'``.

Steps name projects and entries by ``$P<n>`` and ``$E<n>`` (the n-th the case created). Node calls with the owner's
key (that of its create, of ``keys`` in the case, else ``CRAFTED_KEY``); Python takes none. A case's ``prefix``
replaces ``0a0a0000`` in its identifiers.

``Fixtures`` gives the scientific results the cases attach: snapshots of each kind, library records and their
bundles, editor caches whose key and digests Node's checks accept, source receipts and saved results, and
electrode-name annotations that ``validateElectrodeAnnotation`` accepts.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Optional

from eeglayoutlab.jobs import records
from eeglayoutlab.jobs.queue import iso
from eeglayoutlab.schemas import jsjson
from eeglayoutlab.schemas.projects import UNDEFINED
from eeglayoutlab.server.workspace_projects import ProjectService, ProjectStore
from eeglayoutlab.server.workspace_studies import ResourceError

from .key_parity_support import NODE_ENV
from .studies_support import _file_step, sequence, tree

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/projects.mjs'
STORE_EPOCH = 1795564800000  # 2026-11-25T00:00:00.000Z
CRAFTED_KEY = 'c' * 64
NOT_OWNED = '任务不存在或不属于当前浏览器'


_SPECIAL = {'NaN': math.nan, 'Infinity': math.inf, '-Infinity': -math.inf, 'undefined': UNDEFINED}


def revive(value: Any) -> Any:
    """The driver's ``revive`` with the project code's ``UNDEFINED`` (``schemas.projects``, not ``jobs.identity``)."""
    if isinstance(value, list):
        return [revive(item) for item in value]
    if isinstance(value, dict):
        if list(value) == ['$js']:
            return _SPECIAL[value['$js']]
        return {key: revive(child) for key, child in value.items()}
    return value


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def run_driver(mode: str, cases: list[dict], scratch: Path) -> dict:
    """Runs ``parity/projects.mjs`` once; returns its output with the cases by id."""
    spec_path, out_path = scratch / f'projects-{mode}.json', scratch / f'projects-{mode}-node.json'
    spec_path.write_text(jsjson.stringify({'mode': mode, 'cases': cases}), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV,
                   timeout=600)
    output = json.loads(out_path.read_text(encoding='utf-8'))
    output['by_id'] = {case['id']: case for case in output['cases']}
    return output


def key_sequence() -> Callable[[], str]:
    """The store's ``random_key``: a create asks for the returned access key, then the owner key it hashes."""
    count = [0]

    def next_key() -> str:
        count[0] += 1
        n = (count[0] + 1) // 2
        return sha(f'key-{n}') if count[0] % 2 == 0 else sha(f'access-{n}')
    return next_key


# --- Records ---------------------------------------------------------------------------------------------------------

def failure(error: BaseException, sync: bool = False) -> dict:
    """A failure as the driver records it, without the name (V8's error classes are not Python's)."""
    safe = any(getattr(error, name, False) is True for name in ('project_safe', 'resource_safe'))
    status = getattr(error, 'status', None)
    return {'ok': False, 'status': status if isinstance(status, int) else None, 'safe': safe,
            'message': error.message if safe else None, 'code': records.error_code(error), 'sync': sync}


def node_failure(entry: dict) -> dict:
    return {name: value for name, value in entry.items() if name != 'name'}


def masked(value: Any) -> Any:
    """A value with a create's ``access_key`` replaced, as both sides record it."""
    if isinstance(value, dict) and isinstance(value.get('access_key'), str):
        return {**value, 'access_key': '<access_key>'}
    return value


def success(value: Any) -> dict:
    return {'ok': True, 'value': None if value is None else jsjson.stringify(masked(value))}


async def call(run: Callable[[], Any]) -> dict:
    """``run()`` recorded: a synchronous raise apart from a failed awaitable."""
    try:
        pending = run()
    except Exception as error:  # noqa: BLE001 - recorded
        return failure(error, True)
    try:
        value = await pending if inspect.isawaitable(pending) else pending
    except Exception as error:  # noqa: BLE001 - recorded
        return failure(error)
    return success(value)


class Names:
    """The identifiers a case has created, filled into the steps that name them."""

    def __init__(self) -> None:
        self.projects: list[str] = []
        self.entries: list[str] = []

    def fill(self, value: Any) -> Any:
        if isinstance(value, str):
            def name(match: re.Match) -> str:
                created = self.projects if match[1] == 'P' else self.entries
                index = int(match[2]) - 1
                return created[index] if 0 <= index < len(created) else match[0]
            return re.sub(r'\$([PE])(\d+)', name, value)
        if isinstance(value, list):
            return [self.fill(item) for item in value]
        if isinstance(value, dict):
            return {key: self.fill(item) for key, item in value.items()}
        return value

    def note(self, value: Any) -> None:
        if not isinstance(value, dict):
            return
        project = value.get('project')
        if value.get('access_key') and isinstance(project, dict) and project.get('id'):
            self.projects.append(project['id'])
        entry = value.get('entry')
        if isinstance(entry, dict) and entry.get('id') and entry['id'] not in self.entries:
            self.entries.append(entry['id'])


def file_step(directory: Path, kind: str, args: list) -> bool:
    """The driver's file steps (``studies_support._file_step``) on parsed values, whose numbers are floats."""
    if kind == 'chmod':
        args = [args[0], int(args[1])]
    return _file_step(directory, kind, args)


def clock(state: dict) -> Callable[[], str]:
    return lambda: iso(STORE_EPOCH + 1000 * state['step'])


# --- The store mode --------------------------------------------------------------------------------------------------

async def _store_case(item: dict) -> dict:
    directory = Path(item['directory'])
    state = {'step': 0}
    ids, keys = sequence(item.get('prefix', '0a0a0000')), key_sequence()

    def make() -> ProjectStore:
        return ProjectStore(str(directory), now=clock(state), random_uuid=ids, random_key=keys)

    holder = [make()]
    names = Names()

    def operation(kind: str, args: list) -> Any:
        store = holder[0]
        if kind == 'create':
            return store.create(args[0])
        if kind == 'get':
            return store.get(args[0])
        if kind == 'load':
            return store.load(args[0])
        if kind == 'patch':
            return store.patch(args[0], args[1])
        if kind == 'workflow':
            async def run() -> Any:
                record = await store.load(args[0])
                return await store.patch(args[0], {'revision': record['revision'], 'workflow': args[1]})
            return run()
        if kind == 'attach':
            return store.attach(args[0], args[1], args[2], args[3])
        if kind == 'patch_entry':
            return store.patch_entry(args[0], args[1], args[2])
        if kind == 'detach':
            return store.detach(args[0], args[1], args[2])
        if kind == 'get_entry':
            return store.get_entry(args[0], args[1])
        if kind == 'read':
            # Node's {maxBytes = projectBytes} = {maxBytes: undefined} takes the default.
            if len(args) > 1 and args[1] is not UNDEFINED:
                return store.read_snapshots(args[0], max_bytes=args[1])
            return store.read_snapshots(args[0])
        if kind == 'snapshot':
            async def run() -> Any:
                record = await store.load(args[0])
                return await store.snapshot(record, record['entries'][int(args[1])])  # parsed numbers are floats
            return run()
        if kind == 'resave':
            async def run() -> Any:
                record = await store.load(args[0])
                for inner, *rest in args[1]:
                    file_step(directory, inner, rest)
                store.save_sync(record)  # Node's async save: its throw is a rejection
            return run()
        if kind == 'close':
            return store.close()
        if kind == 'flush':
            async def run() -> Any:
                await store.flush()
                return {'pending': store.pending_writes}
            return run()
        if kind == 'restart':
            holder[0] = make()
            return None
        raise ValueError(f'unknown step {kind}')

    def started(kind: str, args: list) -> Any:
        """The call made now; a coroutine is scheduled at once, as a JavaScript call starts its async function."""
        value = operation(kind, args)
        return asyncio.ensure_future(value) if inspect.iscoroutine(value) else value

    def noted(entry: dict) -> dict:
        if entry['ok'] and entry['value']:
            names.note(jsjson.parse(entry['value']))  # a create's access_key is recorded as '<access_key>'
        return entry

    out: list = []
    for raw in item['steps']:
        state['step'] += 1
        kind, *args = names.fill(revive(raw))
        if file_step(directory, kind, args):
            out.append({'ok': True, 'value': None})
            continue
        if kind == 'concurrent':
            # Every call is made before any is awaited; the writes are serialized in call order.
            pending = []
            for inner, *rest in args[0]:
                try:
                    pending.append(started(inner, rest))
                except Exception as error:  # noqa: BLE001 - a synchronous refusal
                    pending.append(failure(error, True))
            rows = []
            for value in pending:
                rows.append(value if isinstance(value, dict) and value.get('ok') is False
                            else noted(await call(lambda value=value: value)))
            out.append(rows)
            continue
        out.append(noted(await call(lambda kind=kind, args=args: operation(kind, args))))
    await holder[0].flush()
    return {'id': item['id'], 'records': out, 'tree': tree(directory)}


def python_store(item: dict) -> dict:
    return asyncio.run(_store_case(item))


# --- The service mode ------------------------------------------------------------------------------------------------

class StandInError(Exception):
    """An error a stand-in raises, with the members Node's checks read."""

    def __init__(self, message: str, status: Any = None, **flags: Any):
        super().__init__(message)
        self.message = message
        self.status = status
        for name, value in flags.items():
            setattr(self, name, value)


def _clone(value: Any) -> Any:
    return None if value is None else jsjson.parse(jsjson.stringify(value))


def _failing(value: Any) -> bool:
    return isinstance(value, dict) and '$error' in value


class StandIns:
    """The service's dependencies over ``state`` (the driver's ``standIns``)."""

    def __init__(self, state: dict):
        self.state = state
        self.root = '/nonexistent-root'
        self.adapters = {'source-reception': self}
        self.store = self
        self.bundle_calls = 0

    # library
    def get(self, id: Any) -> Any:
        return _clone((self.state.get('records') or {}).get(id))

    # bundle(root, record, python)
    async def bundle(self, root: Any, record: dict, python: Any) -> Any:
        self.bundle_calls += 1
        value = (self.state.get('bundles') or {}).get(record['id'])
        if _failing(value):
            raise Exception(value['$error'])
        return UNDEFINED if value is None else _clone(value)

    # editor
    async def records(self) -> list:
        return _clone((self.state.get('editor') or {}).get('rows') or [])

    def path(self, kind: str, key: str, file: str) -> str:
        return f'{kind}/{key}/{file}'

    def read(self, path: str) -> Any:
        key = path.split('/')[1]
        caches = (self.state.get('editor') or {}).get('caches') or {}
        if key not in caches:
            raise StandInError(f"ENOENT: no such file, open '{path}'", code='ENOENT')
        return _clone(caches[key])

    def validate(self, result: Any, request: Any) -> None:
        if isinstance(result, dict) and result.get('invalid') is True:
            raise Exception('Invalid electrode editor result.')

    # queue
    def own(self, id: Any, kind: str) -> dict:
        task = next((value for value in self.state.get('tasks') or [] if value.get('id') == id and value.get('kind') == kind),
                    None)
        if task is None:
            raise StandInError(NOT_OWNED, 404)
        return _clone(task)

    async def saved_result(self, key: str, request: Any) -> Any:
        value = (self.state.get('saved') or {}).get(key)
        if _failing(value):
            raise Exception(value['$error'])
        return UNDEFINED if value is None else _clone(value)


class StandInAnnotations:
    def __init__(self, state: dict):
        self.state = state

    def read(self, id: Any, record_id: Any) -> Any:
        value = (self.state.get('annotations') or {}).get(id)
        if not value or value.get('record_id') != record_id:
            raise StandInError('Electrode name annotation not found.', 404, annotation_safe=True)
        return _clone(value)


class ExportedIds:
    """The driver's delivery: the saved entries' identifiers of ``read_snapshots``."""

    def __init__(self, store: ProjectStore):
        self.store = store

    async def export(self, id: Any) -> dict:
        return {'entries': [row['entry']['id'] for row in (await self.store.read_snapshots(id))['entries']]}


async def _service_case(item: dict) -> dict:
    directory = Path(item['directory'])
    state = {'step': 0}
    world = revive(item.get('state') or {})
    store = ProjectStore(str(directory), now=clock(state), random_uuid=sequence(item.get('prefix', '0a0a0000')),
                         random_key=key_sequence())
    stand = StandIns(world)

    def before_write() -> None:
        if world.get('before') == 'resource':
            raise ResourceError('Resource blocked', 503, retry_after=7)

    service = ProjectService(store=store, library=stand, root=stand.root, python='python3', bundle=stand.bundle,
                             editor=stand, queue=stand, annotations=StandInAnnotations(world),
                             delivery=ExportedIds(store), before_write=before_write)
    names = Names()
    out: list = []
    for raw in item['steps']:
        state['step'] += 1
        kind, *args = names.fill(revive(raw))
        if file_step(directory, kind, args):
            out.append({'ok': True})
            continue
        if kind == 'state':
            world.update(args[0])
            out.append({'ok': True})
            continue
        assert kind == 'request', kind
        method, url, headers, body = args
        headers = {name.lower(): value for name, value in (headers or {}).items()}
        status, value, sent = await service.handle(
            method, url.split('?')[0], query='?' in url, content_type=headers.get('content-type'),
            body=b'' if body is None or body is UNDEFINED else body.encode('utf-8'), if_match=headers.get('if-match'))
        names.note(value)
        out.append({'status': status, 'body': jsjson.stringify(masked(value)),
                    'headers': {name.lower(): text for name, text in sent.items()}})
    service.close()
    await service.flush()
    return {'id': item['id'], 'records': out, 'tree': tree(directory)}


def python_service(item: dict) -> dict:
    return asyncio.run(_service_case(item))


# --- The read mode ---------------------------------------------------------------------------------------------------

def python_read(item: dict) -> dict:
    store = ProjectStore(item['directory'])
    projects = []
    for id in item['projects']:
        try:
            record = store.load_sync(id)
        except Exception as error:  # noqa: BLE001 - recorded
            projects.append(failure(error))
            continue
        snapshots = []
        for entry in record['entries']:
            try:
                snapshots.append({'ok': True, 'value': store.snapshot_sync(record, entry)['snapshot_json']})
            except Exception as error:  # noqa: BLE001 - recorded
                snapshots.append(failure(error))
        projects.append({'ok': True, 'record': jsjson.stringify(record), 'snapshots': snapshots})
    return {'id': item['id'], 'projects': projects}


def node_read(case: dict) -> dict:
    def form(entry: dict) -> dict:
        return entry if entry['ok'] else node_failure(entry)
    return {'id': case['id'], 'projects': [{**form(project), **({'snapshots': [form(row) for row in project['snapshots']]}
                                                               if project['ok'] else {})}
                                           for project in case['projects']]}


def node_records(case: dict) -> list:
    """A store case's records in the compared form."""
    def form(entry: Any) -> Any:
        if isinstance(entry, list):
            return [form(item) for item in entry]
        if entry.get('ok'):
            return {'ok': True, 'value': entry['value']}
        return node_failure(entry)
    return [form(entry) for entry in case['records']]


# --- Scientific results ----------------------------------------------------------------------------------------------

SNAPSHOT_SCHEMA = 'research-project-snapshot/1'
XYZ = [[(i % 8) * 6 + 1.42e-14, (i // 8) * 6, -112.31415926535898] for i in range(64)]


def scientific(seed: int = 2026) -> dict:
    """check-project-store.mjs's ``scientific()``: awkward doubles that must survive byte for byte."""
    return {'request': {'seed': seed, 'xyz_mm': [[-112.31415926535898, 1e-14, 0]]},
            'waveforms': {'data': [1.25e-12, -9.125e-10]},
            'provenance': {'code_sha256': 'b' * 64, 'thread_count': 1}, 'qa': {'residual': 4.16e-13}}


def snapshot(kind: str, record_id: str, payload: Optional[dict] = None, annotation: Optional[dict] = None) -> dict:
    value = {'schema': SNAPSHOT_SCHEMA, 'kind': kind, 'record_id': record_id,
             'payload': scientific() if payload is None else payload}
    if annotation is not None:
        value['electrode_annotation'] = annotation
    return value


def annotation(record_id: str, salt: str = 'a', source_metadata: Optional[dict] = None) -> dict:
    """An electrode-name annotation of ``record_id`` that ``validateElectrodeAnnotation`` accepts."""
    names = [' Fp1, "left" ' if i == 0 else f'电极{i + 1}' for i in range(64)]
    value = {'schema': 'eeg-electrode-annotation/1', 'id': sha(f'annotation-{salt}-{record_id}'), 'record_id': record_id,
             'request_sha256': sha(f'request-{salt}'), 'electrode_names': names}
    if source_metadata is not None:
        value['source_metadata'] = source_metadata
    return value


def layout_record(record_id: str, **extra: Any) -> dict:
    """A completed library record (``Library.get``) of a 64-electrode layout."""
    return {'id': record_id, 'status': 'completed', 'dataset_id': 'cache', 'label': 'Layout',
            'layout': {'xyzMm': XYZ, 'regionIndices': [i % 2 for i in range(64)]}, 'region_count': 2,
            'request': {'region_count': 2}, 'metrics': {'field_relative': 0.95}, **extra}


def layout_bundle(record: dict) -> dict:
    return {'schema': 'eeg-reproducibility-bundle/1', 'record_id': record['id'], 'record': record,
            'original_record': {'result': {'request': {'seed': 2026}, 'fields': [1e-14, 1 / 3]}}}


def editor_cache(parent: str, action: str = 'evaluate', **result: Any) -> tuple[str, dict, dict]:
    """``(key, row, cache)`` of a completed editor evaluation whose key and digests Node's checks accept."""
    value = {'schema': 'electrode-editor-result/1', 'request': {'action': action, 'parent_id': parent},
             'electrode_count': 63, 'active_regions': 2, 'values': [1 / 3, -1e-18], **result}
    identity = {'protocol': 'electrode-editor/1', 'version': 1}
    key = jsjson.sha256_hex({'request': value['request'], 'identity': identity})
    cache = {'key': key, 'identity': identity, 'result': value, 'result_sha256': jsjson.sha256_hex(value),
             'finished_at': '2026-11-14T12:00:00.000Z'}
    return key, {'key': key, 'status': 'completed', 'parent_id': parent}, cache


def source_result(record_id: str, **request: Any) -> dict:
    """A saved signal-reception result (check-project-api.mjs's ``result``)."""
    return {'schema_version': 'source-reception/2',
            'request': {'record_id': record_id, 'mode': 'single_source', 'source_index': 2, 'seed': 2026, **request},
            'layout': {'xyzMm': [[1, 2, 3]]}, 'waveforms': {'time_s': [0, 0.1], 'baseline': [1.252e-12, -9.13e-8]},
            'provenance': {'threads': 1, 'source': 'validated-cache'}, 'qa': {'residual': 1e-13}}


def crafted_project(id: str, **extra: Any) -> dict:
    """A hand-written ``research-project/1`` record whose owner key is ``CRAFTED_KEY``."""
    return {'schema': 'research-project/1', 'id': id, 'title': 'Crafted', 'owner_name': 'Researcher', 'notes': '',
            'revision': 1, 'created_at': '2026-11-24T00:00:00.000Z', 'updated_at': '2026-11-24T00:00:00.000Z',
            'owner_key_hash': sha(CRAFTED_KEY), 'viewer_key_hash': None, 'entries': [], **extra}


def b64(value: Any) -> str:
    """A file step's content: ``JSON.stringify(value)`` bytes, or the text as given."""
    import base64

    data = value.encode('utf-8') if isinstance(value, str) else jsjson.stringify(value).encode('utf-8')
    return base64.b64encode(data).decode('ascii')


def project_files(base: Path, record: dict) -> None:
    """Writes a crafted project (its directory and ``snapshots``) as Node's store lays one out."""
    directory = base / record['id']
    (directory / 'snapshots').mkdir(parents=True, mode=0o700)
    os.chmod(directory, 0o700)
    (directory / 'project.json').write_bytes(jsjson.stringify(record).encode('utf-8'))
