"""Record writes (``eeglayoutlab.jobs.records``, phase 2 slice 4): ``RecordStore.create_batch`` and ``write``,
``atomic_json`` and the publish-once ``RecordStore.publish_cache`` (plan B16).

- Ports check-runtime-storage.mjs:35 and :56 and the record-store half of check-service-storage.mjs:12.
- Parity: ``parity/records.mjs`` runs Node's own ``RecordStore`` and ``atomicJson`` on synthetic roots, each built
  twice (one copy per side). Every operation must give the same value or error (the case directory and the random
  part of temporary names masked), make the same ``fs/promises`` calls in the same order (``realpath``, ``mkdir``,
  ``open`` with its flags and mode, ``rename``, ``link``, ``unlink``), and leave the same tree: names, types,
  permission bits, link counts, link targets and bytes. The cases cover values (JavaScript key order, numbers,
  escapes, deep nesting), circular values (V8's messages), every refusal (keys, identifiers, kinds, links out of
  the root at each component, ``..``) and the system errors of each step.
- ``publish_cache`` is ``write`` where no valid cache is in the way: the parity cases publish to fresh keys and over
  invalid files, and compare its calls with ``write``'s (``link`` for ``rename``, then, when the name exists, the
  read of the existing file before the ``rename``). Without Node: a valid cache is never replaced (the default
  rule and the radius reader), threads and processes racing for one key publish exactly once, errors leave the
  cache as it was, and a crash between the temporary and the ``link`` or ``rename`` leaves a ``*.tmp`` that
  ``keys``, the readers and the library ignore.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import signal
import stat as stat_module
import subprocess
import sys
import threading
from typing import Any, Callable, Iterator

import pytest

from eeglayoutlab.jobs import nodepath, records
from eeglayoutlab.jobs.records import RecordError, RecordStore, atomic_json, error_code, json_bytes, node_message
from eeglayoutlab.schemas import jsjson
from schema_parity_support import require

from .key_parity_support import NODE_ENV, ROOT, needs_node

DRIVER = ROOT / 'tests/service/parity/records.mjs'
K, K2, B = 'a' * 64, 'c' * 64, 'b' * 36
RADIUS = 'results/v2/local_app_jobs'
BATCH = f'{RADIUS}/{K}/{B}'
UUID = re.compile('[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}')
SUPERUSER = os.geteuid() == 0  # permission bits do not stop the superuser
TEMPORARY = '11111111-2222-4333-8444-555555555555'
SOURCE = str(ROOT / 'src')


def key(n: int) -> str:
    return f'{n:064x}'


def cache(k: str, n: int = 0) -> dict:
    """A cache every reader's first check accepts (``stored_cache``), distinct for each ``n``."""
    result = {'status': 'completed', 'n': n, 'values': [n / 7, -0.0, 1e-7, 1e21], '1': 'index first'}
    return {'key': k, 'request': {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'}, 'result': result,
            'result_sha256': jsjson.sha256_hex(result), 'finished_at': '2026-11-23T00:00:00.000Z'}


# --- check-runtime-storage.mjs and check-service-storage.mjs -------------------------------------------------------

def test_record_storage_isolates_checkouts_and_preserves_the_previous_json(tmp_path):
    """check-runtime-storage.mjs:35."""
    root, other = tmp_path / 'eeg-records', tmp_path / 'eeg-records-other'
    root.mkdir()
    other.mkdir()
    store, outside = RecordStore(str(root)), RecordStore(str(other))
    batch = store.create_batch('radius', K, B)
    store.write(nodepath.join(batch, 'job.json'), {'status': 'running'})
    path = store.path('radius', K, 'cache.json')
    store.write(path, {'schema': 'old/1', 'value': 2})
    assert store.read(path) == {'schema': 'old/1', 'value': 2}
    circular: dict = {}
    circular['self'] = circular
    with pytest.raises(TypeError, match='^Converting circular structure to JSON'):
        store.write(path, circular)
    assert jsjson.parse(Path(path).read_text(encoding='utf-8'))['value'] == 2
    assert outside.keys('radius') == []
    assert store.keys('radius') == [K]
    with pytest.raises(RecordError):
        store.path('radius', K, '..', '..', 'outside')
    with pytest.raises(RecordError):
        store.path('radius', 'invalid')
    assert sorted(os.listdir(Path(path).parent)) == [B, 'cache.json']


def test_record_reads_and_batch_creation_reject_symlinks_to_external_data(tmp_path):
    """check-runtime-storage.mjs:56; nothing is created through the link."""
    root, other = tmp_path / 'eeg-record-links', tmp_path / 'eeg-record-external'
    root.mkdir()
    other.mkdir()
    (other / 'secret.json').write_text('{}', encoding='utf-8')
    store = RecordStore(str(root))
    os.makedirs(store.directory('radius'))
    os.symlink(other, store.path('radius', K))
    with pytest.raises(RecordError, match='leaves'):
        store.read(store.path('radius', K, 'secret.json'))
    with pytest.raises(RecordError, match='leaves'):
        store.create_batch('radius', K, B)
    with pytest.raises(RecordError, match='leaves'):
        store.publish_cache('radius', K, cache(K))
    assert os.listdir(other) == ['secret.json']


def test_the_service_shares_one_record_store(tmp_path):
    """check-service-storage.mjs:12, the record store: the service's library, its radius reader and the writes go
    through one ``RecordStore``, so a published record is what the library reads. The paused custom queue is
    dropped (R6); the execution slot the kinds share comes with the queue."""
    require('pydantic')
    require('fastapi')
    from eeglayoutlab.server.routes.library import LibraryRoutes

    from .service_support import service_config

    root = tmp_path / 'eeg-service-config'
    root.mkdir()
    routes = LibraryRoutes(service_config(root))
    library = routes.library()
    assert routes.library() is library
    store = library.store
    assert store is library.radius.store and store.root == str(root)
    store.create_batch('radius', K, B)
    assert store.publish_cache('radius', K, cache(K)) is None
    assert library.radius.store.stored_cache('radius', K) == cache(K)
    assert library.store.keys('radius') == [K]


# --- Parity with Node's RecordStore -----------------------------------------------------------------------------

def plain(root: Path, outside: Path) -> None:
    root.mkdir()


def files(*entries: tuple[str, Any]) -> Callable[[Path, Path], None]:
    """A root holding ``entries``: ``(path, bytes | str)`` writes a file, ``(path, None)`` makes a directory,
    ``(path, ('link', target))`` a link (``{outside}`` in a target is the outside directory), ``(path, ('mode',
    bits))`` changes a mode (after everything else)."""
    def build(root: Path, outside: Path) -> None:
        root.mkdir()
        modes = []
        for relative, body in entries:
            target = root / relative
            if isinstance(body, tuple) and body[0] == 'mode':
                modes.append((target, body[1]))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if body is None:
                target.mkdir()
            elif isinstance(body, tuple):
                os.symlink(body[1].replace('{outside}', str(outside)), target)
            else:
                target.write_bytes(body if isinstance(body, bytes) else body.encode('utf-8'))
        for target, bits in modes:
            target.chmod(bits)
    return build


@dataclass
class Case:
    id: str
    ops: list[dict]
    build: Callable[[Path, Path], None] = plain
    spelling: str = 'root'  # the root as the store is given it, relative to the case directory
    outside: dict[str, str] = field(default_factory=dict)  # files in the outside directory


def write(path: str, value: str, cycle: Any = None, op: str = 'write') -> dict:
    return {'op': op, 'path': path, 'value': value, **({'cycle': cycle} if cycle else {})}


def batch(kind: str = 'radius', k: str = K, id: str = B) -> dict:
    return {'op': 'createBatch', 'kind': kind, 'key': k, 'id': id}


def publish(k: str, value: Any, kind: str = 'radius') -> dict:
    return {'op': 'publish', 'kind': kind, 'key': k, 'value': jsjson.stringify(value)}


def read(path: str) -> dict:
    return {'op': 'read', 'path': path}


DEEP = 3000
VALUES = [
    '{}', '[]', 'null', 'true', 'false', '0', '-0', '"text"', '{"$number":"NaN"}', '[{"$number":"Infinity"},'
    '{"$number":"-Infinity"},{"$number":"-0"}]', '[1e21,1e-7,5e-324,1.7976931348623157e308,1e300,0.1,100,-1.5e-10,'
    '2.5e+25,123456789012345678901234567890,9007199254740993,0.000001,1e-6,123e-20]',
    '{"b":0,"2":1,"1":2,"01":3,"4294967295":4,"4294967294":5,"-1":6,"1.5":7,"0":8}',
    '{"a":1,"b":2,"a":3,"1":4,"1":5}',
    '"\\u0000\\u001f\\u007f\\u2028\\u2029\\ud800\\udc00\\ud83d\\ude00\\udfff\\ud800x'
    ' \u00e9 \u4e2d\u6587 \\"\\\\/\\b\\f\\n\\r\\t"',
    '{"\\ud800":1,"\\u0000":2,"":3,"\u00e9":4,"\\ud83d\\ude00":5}',
    '{"__proto__":{"x":1},"constructor":2,"toString":3}',
    '[' * DEEP + ']' * DEEP, '{"a":' * DEEP + '1' + '}' * DEEP,
    jsjson.stringify([i / 10 for i in range(20000)]),
    jsjson.stringify(cache(K, 3)),
]
CYCLES = [
    ('{"self":null}', {'at': ['self'], 'to': []}),
    ('{"a":{"b":[1,{"x":null}]}}', {'at': ['a', 'b', 1, 'x'], 'to': []}),
    ('{"p":{"q":{"r":{"t":{"s":null}}}}}', {'at': ['p', 'q', 'r', 't', 's'], 'to': []}),
    ('{"p":{"q":{"r":{"t":{"s":null}}}}}', {'at': ['p', 'q', 'r', 't', 's'], 'to': ['p']}),
    ('{"p":{"q":{"r":{"s":null}}}}', {'at': ['p', 'q', 'r', 's'], 'to': ['p', 'q']}),
    ('[[[[[null]]]]]', {'at': [0, 0, 0, 0, 0], 'to': []}),
    ('[1,[2,[3,null]]]', {'at': [1, 1, 1], 'to': [1]}),
    ('{"":{"k":null}}', {'at': ['', 'k'], 'to': []}),
    ('{"x":{"":null}}', {'at': ['x', ''], 'to': []}),
    ('{"b":{"k":null},"2":{"k":1},"1":{"k":2}}', {'at': ['b', 'k'], 'to': []}),
    ('{"b":{"k":1},"2":{"k":null},"1":{"k":2}}', {'at': ['2', 'k'], 'to': []}),
    ('{"0":{"0":null}}', {'at': ['0', '0'], 'to': ['0']}),
]


def cases() -> list[Case]:
    found = [
        Case('checkouts', [  # check-runtime-storage.mjs:35, step by step
            batch(), write(f'{BATCH}/job.json', '{"status":"running"}'),
            {'op': 'path', 'kind': 'radius', 'key': K, 'parts': ['cache.json']},
            write(f'{RADIUS}/{K}/cache.json', '{"schema":"old/1","value":2}'), read(f'{RADIUS}/{K}/cache.json'),
            write(f'{RADIUS}/{K}/cache.json', '{"self":null}', {'at': ['self'], 'to': []}),
            write(f'{RADIUS}/{K}/cache.json', '{"self":null}', {'at': ['self'], 'to': []}, 'atomicJson'),
            read(f'{RADIUS}/{K}/cache.json'), {'op': 'keys', 'kind': 'radius'},
            {'op': 'path', 'kind': 'radius', 'key': K, 'parts': ['..', '..', 'outside']},
            {'op': 'path', 'kind': 'radius', 'key': K, 'parts': ['a', '..', '..', K, 'b']},
            {'op': 'path', 'kind': 'radius', 'key': 'invalid', 'parts': []},
        ]),
        Case('other-checkout', [{'op': 'keys', 'kind': 'radius'}]),
        Case('external-link', [  # check-runtime-storage.mjs:56
            read(f'{RADIUS}/{K}/secret.json'), batch(), batch(k=K2),
            write(f'{RADIUS}/{K}/x.json', '1'), {'op': 'keys', 'kind': 'radius'},
        ], files((f'{RADIUS}/{K}', ('link', '{outside}')), (f'{RADIUS}/{K2}', ('link', '{outside}/../root/inner')),
                 ('inner', None)), outside={'secret.json': '{}'}),
        Case('kinds', [
            *(batch(kind) for kind in ('radius', 'design', 'editor', 'source', 'sourceV2')),
            *({'op': 'directory', 'kind': kind} for kind in ('radius', 'sourceV2', 'nope', '')),
            *({'op': 'keys', 'kind': kind} for kind in ('radius', 'design', 'editor', 'source', 'sourceV2')),
            batch(), batch(id='0' * 8 + '-' + '0' * 27), batch(id='-' * 36),
            *(batch(id=id) for id in ('B' * 36, 'b' * 35, 'b' * 37, 'b' * 36 + '\n', 'g' * 36, '../' * 12, '')),
            *(batch(k=k) for k in ('A' * 64, 'a' * 63, 'a' * 64 + '\n', '../' + 'a' * 61)),
            batch('nope'), batch('nope', 'x', 'y'), batch('nope', K, 'y'),
        ]),
        Case('values', [batch(), *(op for index, text in enumerate(VALUES)
                                   for op in (write(f'{BATCH}/v{index}.json', text), read(f'{BATCH}/v{index}.json'),
                                              write(f'{BATCH}/a{index}.json', text, op='atomicJson')))]),
        Case('cycles', [batch(), *(write(f'{BATCH}/c{index}.json', text, cycle)
                                   for index, (text, cycle) in enumerate(CYCLES)),
                        write(f'{BATCH}/shared.json', '{"a":{"v":[1]},"b":null}', {'at': ['b'], 'to': ['a']}),
                        write(f'{BATCH}/missing/c.json', '{"self":null}', {'at': ['self'], 'to': []}),
                        write(f'{BATCH}/c.json', '{"self":null}', {'at': ['self'], 'to': []}, 'atomicJson')]),
        Case('write-errors', [
            write(f'{BATCH}/missing/x.json', '1'), write(f'{BATCH}/missing/x.json', '1', op='atomicJson'),
            write(f'{BATCH}/out/x.json', '1'), write(f'{BATCH}/dir.json', '1'), write(f'{BATCH}/full.json', '1'),
            write(f'{BATCH}/link.json', '{"replaced":true}'), write(f'{BATCH}/dangling.json', '2'),
            write(f'{BATCH}/file.json/x.json', '1'), write(f'{BATCH}/inner/x.json', '3'), write('', '1'),
            write('x.json', '1'), write('../x.json', '1'), write('../x.json', '1', op='atomicJson'),
            read(f'{BATCH}/link.json'), read(f'{BATCH}/dir.json'), read(f'{BATCH}/out/secret.json'),
        ], files((f'{BATCH}/out', ('link', '{outside}')), (f'{BATCH}/dir.json', None),
                 (f'{BATCH}/full.json/inner', '{}'), (f'{BATCH}/link.json', ('link', '{outside}/target.json')),
                 (f'{BATCH}/dangling.json', ('link', 'missing.json')), (f'{BATCH}/file.json', '{}'),
                 (f'{BATCH}/inner', ('link', '../../../../../inner')), ('inner', None)),
             outside={'target.json': '{"outside":true}', 'secret.json': '{}'}),
        Case('no-root', [batch(), write('x.json', '1'), read('x.json'), {'op': 'keys', 'kind': 'radius'}],
             lambda root, outside: None),
        Case('root-is-a-file', [batch(), write('x.json', '1'), {'op': 'keys', 'kind': 'radius'}],
             lambda root, outside: root.write_text('{}', encoding='utf-8')),
        Case('linked-root', [batch(), write(f'{BATCH}/job.json', '{"ok":1}'), read(f'{BATCH}/job.json'),
                             {'op': 'keys', 'kind': 'radius'}],
             lambda root, outside: (root.parent.joinpath('real').mkdir(), root.symlink_to('real'))),
        Case('spelled-root', [batch(), write(f'{BATCH}/job.json', '{"ok":2}'), {'op': 'keys', 'kind': 'radius'}],
             spelling='x/../root/./'),
        Case('batch-links', [batch(k=key(1)), batch(k=key(2)), batch(k=key(3)), batch(k=key(4)), batch(k=key(5)),
                             batch(k=key(6), id='d' * 36), batch(k=key(7)), {'op': 'keys', 'kind': 'radius'}],
             files((f'{RADIUS}/{key(1)}', ('link', 'missing')), (f'{RADIUS}/{key(2)}', '{}'),
                   (f'{RADIUS}/{key(3)}', ('link', '../../../inner')),
                   (f'{RADIUS}/{key(4)}/{B}', ('link', '{outside}')),
                   (f'{RADIUS}/{key(5)}/{B}', ('link', '../../../../inner')), (f'{RADIUS}/{key(6)}', None),
                   (f'{RADIUS}/{key(6)}/{"d" * 36}', '{}'), (f'{RADIUS}/{key(7)}/{B}', ('link', B)),
                   ('inner', None))),
        Case('linked-results', [batch(), write(f'{BATCH}/job.json', '1'), {'op': 'keys', 'kind': 'radius'}],
             files(('results', ('link', 'real')), ('real', None))),
        Case('outside-results', [batch(), {'op': 'keys', 'kind': 'radius'}, read(f'{RADIUS}/x.json')],
             files(('results', ('link', '{outside}'))), outside={'v2/local_app_jobs/x.json': '{}'}),
        Case('v2-is-a-file', [batch(), batch('design')], files(('results/v2', '{}'))),
        Case('keys', [{'op': 'keys', 'kind': 'radius'}, read(f'{RADIUS}/{K}/cache.json'),
                      read(f'{RADIUS}/{K}/cache.json.{TEMPORARY}.tmp')],
             files((f'{RADIUS}/{K}/cache.json.{TEMPORARY}.tmp', '{"key":"x"}'), (f'{RADIUS}/{K2}', None),
                   (f'{RADIUS}/{key(9)}', '{}'), (f'{RADIUS}/{key(8)}', ('link', K2)), (f'{RADIUS}/{"C" * 63}D', None),
                   (f'{RADIUS}/{"a" * 63}', None), (f'{RADIUS}/electrode_annotations', None),
                   (f'{RADIUS}/{key(7)}.{TEMPORARY}.tmp', '{}'), (f'{RADIUS}/{key(6)}', None))),
        Case('publish', [
            publish(key(1), cache(key(1), 1)), read(f'{RADIUS}/{key(1)}/cache.json'),
            publish(key(2), cache(key(2), 2)), publish(key(3), cache(key(3), 3)), publish(key(4), cache(key(4), 4)),
            publish(key(5), cache(key(5), 5)), publish(key(6), cache(key(6), 6)), publish(key(7), cache(key(7), 7)),
            publish(key(8), cache(key(8), 8)), publish(key(9), cache(key(9), 9)), publish(key(10), cache(key(10))),
            {**publish(key(1), {'self': None}), 'cycle': {'at': ['self'], 'to': []}},
            publish('A' * 64, cache(key(1))), publish(key(1), cache(key(1)), 'nope'),
        ], files((f'{RADIUS}/{key(1)}', None), (f'{RADIUS}/{key(2)}/cache.json', '{"key":"x"}'),
                 (f'{RADIUS}/{key(3)}/cache.json', '{broken'), (f'{RADIUS}/{key(4)}/cache.json/inner', '{}'),
                 (f'{RADIUS}/{key(5)}/cache.json', ('link', 'missing.json')),
                 (f'{RADIUS}/{key(6)}/cache.json', ('link', '{outside}/cache.json')),
                 (f'{RADIUS}/{key(7)}/cache.json', jsjson.stringify({**cache(key(7), 7), 'result_sha256': 'x'})),
                 (f'{RADIUS}/{key(8)}', ('link', '{outside}')), (f'{RADIUS}/{key(10)}/cache.json', '[]')),
             outside={'cache.json': jsjson.stringify(cache(key(6), 6))}),
    ]
    if not SUPERUSER:
        found += [
            Case('read-only', [batch(), batch(k=key(4)), write(f'{BATCH}/x.json', '1'),
                               write(f'{RADIUS}/{K2}/x.json', '1', op='atomicJson'), publish(K2, cache(K2)),
                               publish(key(3), cache(key(3))), read(f'{RADIUS}/{key(3)}/cache.json')],
                 files((BATCH, None), (f'{RADIUS}/{K2}', None), (f'{RADIUS}/{key(3)}/cache.json', '{}'),
                       (BATCH, ('mode', 0o500)), (RADIUS, ('mode', 0o500)), (f'{RADIUS}/{K2}', ('mode', 0o500)),
                       (f'{RADIUS}/{key(3)}/cache.json', ('mode', 0)), (f'{RADIUS}/{key(3)}', ('mode', 0o500)))),
        ]
    return found


@dataclass
class Side:
    base: Path

    def directory(self, case: Case) -> Path:
        return self.base / case.id

    def root(self, case: Case) -> str:
        return f'{self.directory(case)}/{case.spelling}'

    def build(self, case: Case) -> None:
        directory = self.directory(case)
        (directory / 'outside').mkdir(parents=True)
        for relative, body in case.outside.items():
            (directory / 'outside' / relative).parent.mkdir(parents=True, exist_ok=True)
            (directory / 'outside' / relative).write_text(body, encoding='utf-8')
        case.build(directory / 'root', directory / 'outside')

    def mask(self, value: Any) -> Any:
        """Paths of this side's case directories as ``<base>``, temporaries' random part as ``<uuid>``."""
        if isinstance(value, str):
            for prefix in sorted({str(self.base), os.path.realpath(self.base)}, key=len, reverse=True):
                value = value.replace(prefix, '<base>')
            return UUID.sub('<uuid>', value)
        if isinstance(value, list):
            return [self.mask(item) for item in value]
        if isinstance(value, dict):
            return {name: self.mask(item) for name, item in value.items()}
        return value

    def tree(self, case: Case) -> list:
        """Every entry under the case directory (links not followed): type, permission bits, link count, bytes."""
        directory = self.directory(case)
        entries = []
        for parent, names, filenames in os.walk(directory):
            for name in sorted(names + filenames):
                path = os.path.join(parent, name)
                info = os.lstat(path)
                relative = self.mask(os.path.relpath(path, directory))
                if stat_module.S_ISLNK(info.st_mode):
                    entries.append([relative, 'link', self.mask(os.readlink(path))])
                elif stat_module.S_ISDIR(info.st_mode):
                    entries.append([relative, 'dir', oct(info.st_mode & 0o7777)])
                else:
                    data = Path(path).read_bytes() if info.st_mode & 0o400 else None
                    entries.append([relative, 'file', oct(info.st_mode & 0o7777), info.st_nlink, data])
        return sorted(entries)

    def restore(self, case: Case) -> None:
        """Makes the case writable again, so that it can be removed."""
        for parent, names, filenames in os.walk(self.directory(case)):
            for name in names + filenames:
                path = os.path.join(parent, name)
                if not os.path.islink(path):
                    os.chmod(path, 0o700)


def revive(value: Any) -> Any:
    """The driver's reviver: ``{"$number": ...}`` stands for a number JSON cannot spell."""
    if isinstance(value, dict):
        if len(value) == 1 and isinstance(value.get('$number'), str):
            numbers = {'NaN': float('nan'), 'Infinity': float('inf'), '-Infinity': float('-inf'), '-0': -0.0}
            return numbers[value['$number']]
        return {name: revive(item) for name, item in value.items()}
    if isinstance(value, list):
        return [revive(item) for item in value]
    return value


def build_value(op: dict) -> Any:
    value = jsjson.parse(op['value'])
    if '"$number"' in op['value']:  # the deeply nested values have none (revive recurses)
        value = revive(value)
    if 'cycle' in op:
        at, target = op['cycle']['at'], value
        for step in op['cycle']['to']:
            target = target[step]
        holder = value
        for step in at[:-1]:
            holder = holder[step]
        holder[at[-1]] = target
    return value


TRACED = {'realpath': 'realpath', '_mkdir': 'mkdir', '_open': 'open', '_rename': 'rename', '_link': 'link',
          '_unlink': 'unlink'}


@contextlib.contextmanager
def traced() -> Iterator[list]:
    """Records the calls ``records`` makes through its fs helpers, as the driver records Node's."""
    calls: list = []
    originals = {name: getattr(records, name) for name in TRACED}

    def wrap(name: str, original: Callable) -> Callable:
        def call(*args: Any) -> Any:
            calls.append([TRACED[name], *map(str, args)])
            return original(*args)
        return call

    for name, original in originals.items():
        setattr(records, name, wrap(name, original))
    try:
        yield calls
    finally:
        for name, original in originals.items():
            setattr(records, name, original)


def python_op(store: RecordStore, root: str, op: dict) -> Any:
    name = op['op']
    if name == 'createBatch':
        return store.create_batch(op['kind'], op['key'], op['id'])
    if name == 'write':
        return store.write(nodepath.join(root, op['path']), build_value(op))
    if name == 'atomicJson':
        return atomic_json(nodepath.join(root, op['path']), build_value(op))
    if name == 'publish':
        return store.publish_cache(op['kind'], op['key'], build_value(op))
    if name == 'read':
        return jsjson.stringify(store.read(nodepath.join(root, op['path'])))
    if name == 'keys':
        return store.keys(op['kind'])
    if name == 'path':
        return store.path(op['kind'], op['key'], *op['parts'])
    if name == 'directory':
        return store.directory(op['kind'])
    raise ValueError(name)


def python_results(case: Case, root: str) -> list[dict]:
    store, results = RecordStore(root), []
    for op in case.ops:
        with traced() as calls:
            try:
                value = python_op(store, root, op)
                result: dict = {'ok': True} if value is None else {'ok': True, 'value': value}
            except Exception as error:  # noqa: BLE001 - compared with Node's error
                result = {'ok': False, 'error': {'name': 'TypeError' if isinstance(error, TypeError) else 'Error',
                                                 'code': error_code(error), 'message': node_message(error)}}
        result['calls'] = calls
        results.append(result)
    return results


def as_write(calls: list) -> list:
    """``publish_cache``'s calls as ``write``'s: its ``link`` stands for the ``rename``; when the name exists, the
    failed ``link`` and the read of the existing file (``realpath`` of the root and the file) come before it."""
    out = list(calls)
    for index, call in enumerate(out):
        if call[0] == 'link':
            following = out[index + 1:]
            if following[:2] and [c[0] for c in following[:2]] == ['realpath', 'realpath']:
                return out[:index] + following[2:]
            return out[:index] + [['rename', *call[1:]]] + following
    return out


@pytest.fixture(scope='module')
def parity(tmp_path_factory):
    base = tmp_path_factory.mktemp('records')
    node, python = Side(base / 'node'), Side(base / 'python')
    found = cases()
    for side in (node, python):
        for case in found:
            side.build(case)
    spec, out = base / 'spec.json', base / 'out.json'
    node_cases = [{'id': case.id, 'root': node.root(case), 'ops': case.ops} for case in found]
    spec.write_text(jsjson.stringify({'cases': node_cases}), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec), str(out)], check=True, cwd=ROOT, env=NODE_ENV, timeout=600)
    output = json.loads(out.read_text(encoding='utf-8'))
    by_id = {entry['id']: entry['results'] for entry in output['cases']}
    compared = {}
    for case in found:
        python_side = python_results(case, python.root(case))
        compared[case.id] = (case, node.mask(by_id[case.id]), python.mask(python_side), node.tree(case),
                             python.tree(case))
    yield compared
    for side in (node, python):
        for case in found:
            side.restore(case)


@needs_node
@pytest.mark.parametrize('case_id', [case.id for case in cases()])
def test_record_writes_match_node(parity, case_id):
    case, node, python, node_tree, python_tree = parity[case_id]
    assert len(node) == len(python) == len(case.ops)
    mismatches = []
    for op, expected, got in zip(case.ops, node, python):
        if op['op'] == 'publish':
            got = {**got, 'calls': as_write(got['calls'])}
        if expected != got:
            mismatches.append({'op': {name: value for name, value in op.items() if name != 'value'},
                               'node': expected, 'python': got})
    assert mismatches == []
    assert python_tree == node_tree


@needs_node
def test_the_cases_reach_every_outcome(parity):
    """The cases make Node fail at each step of each writer, with each kind of error, and publish over every kind of
    file that is not a valid cache."""
    messages = [result['error']['message'] for _, node, _, _, _ in parity.values() for result in node
                if not result['ok']]
    for expected in ('Invalid batch identifier.', 'Invalid scientific record key.', 'Unknown record kind: nope',
                     'Record path leaves its directory.', 'Record path leaves the repository.',
                     'Record directory leaves the repository.', 'Converting circular structure to JSON',
                     "ENOENT: no such file or directory, realpath '", "ENOTDIR: not a directory, mkdir '",
                     "ENOTDIR: not a directory, realpath '", "ENOENT: no such file or directory, open '",
                     "EISDIR: illegal operation on a directory, rename '",
                     'EISDIR: illegal operation on a directory, read'):
        assert any(message.startswith(expected) for message in messages), expected
    if not SUPERUSER:
        for expected in ("EACCES: permission denied, mkdir '", "EACCES: permission denied, open '"):
            assert any(message.startswith(expected) for message in messages), expected
    trees = {case_id: entry[3] for case_id, entry in parity.items()}
    published = [entry for entry in trees['publish'] if entry[0].endswith('/cache.json') and entry[1] == 'file']
    assert len(published) >= 7 and all(entry[3] == 1 for entry in published)


def test_fs_helpers_open_and_fail_as_node(tmp_path):
    """What the traces cannot show: ``'wx'`` refuses an existing name and ``link`` fails on one, with Node's
    messages (``fs.promises``); an errno libuv does not map is Node's unknown system error."""
    existing = str(tmp_path / 'existing.json')
    Path(existing).write_text('{}', encoding='utf-8')
    with pytest.raises(OSError) as refused:
        records._open(existing, 'wx', 0o600)
    assert node_message(refused.value) == f"EEXIST: file already exists, open '{existing}'"
    with pytest.raises(OSError) as linked:
        records._link(existing, existing)
    assert error_code(linked.value) == 'EEXIST'
    assert node_message(linked.value) == f"EEXIST: file already exists, link '{existing}' -> '{existing}'"
    fd = records._open(existing, 'r')
    try:
        assert os.read(fd, 8) == b'{}'
    finally:
        os.close(fd)
    unmapped = records._annotate(OSError(4242, 'strange'), 'write', None)
    assert error_code(unmapped) == 'Unknown system error -4242'
    assert node_message(unmapped) == 'Unknown system error -4242: Unknown system error -4242, write'


# --- publish_cache without Node -----------------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path) -> RecordStore:
    root = tmp_path / 'root'
    root.mkdir()
    store = RecordStore(str(root))
    for n in range(4):
        os.makedirs(store.path('radius', key(n)))
    return store


def entries(store: RecordStore, k: str) -> list[str]:
    return sorted(os.listdir(store.path('radius', k)))


def test_publish_writes_node_s_bytes_once(store):
    path = store.path('radius', key(0), 'cache.json')
    assert store.publish_cache('radius', key(0), cache(key(0))) is None
    data, info = Path(path).read_bytes(), os.lstat(path)
    assert data == json_bytes(cache(key(0))) == jsjson.stringify(cache(key(0))).encode('utf-8')
    assert info.st_nlink == 1 and stat_module.S_IMODE(info.st_mode) == 0o600 & ~current_umask()
    # A valid cache is a hit: it is returned and stays, byte for byte and inode for inode.
    assert store.publish_cache('radius', key(0), cache(key(0), 1)) == cache(key(0))
    assert Path(path).read_bytes() == data and os.lstat(path).st_ino == info.st_ino
    # Node's write replaces it; publishing again keeps the replacement.
    store.write(path, cache(key(0), 2))
    assert store.publish_cache('radius', key(0), cache(key(0), 3)) == cache(key(0), 2)
    assert entries(store, key(0)) == ['cache.json']


def current_umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


@pytest.mark.parametrize('existing', ['{broken', '[]', 'null', '"text"', '{}', 'foreign', 'checksum', 'no-result',
                                      'number-key', 'empty'])
def test_publish_replaces_a_cache_that_is_not_valid(store, existing):
    k = key(1)
    path = store.path('radius', k, 'cache.json')
    stored = {'foreign': cache(key(2)), 'checksum': {**cache(k), 'result_sha256': jsjson.sha256_hex('other')},
              'no-result': {name: value for name, value in cache(k).items() if name != 'result'},
              'number-key': {**cache(k), 'key': 1}}
    Path(path).write_bytes(b'' if existing == 'empty' else jsjson.stringify(stored[existing]).encode('utf-8')
                           if existing in stored else existing.encode('utf-8'))
    assert store.stored_cache('radius', k) is None
    assert store.publish_cache('radius', k, cache(k)) is None
    assert Path(path).read_bytes() == json_bytes(cache(k)) and os.lstat(path).st_nlink == 1
    assert entries(store, k) == ['cache.json']


def test_publish_asks_the_kind_s_reader(store):
    k, seen = key(1), []
    path = store.path('radius', k, 'cache.json')
    Path(path).write_bytes(json_bytes(cache(k)))

    def refuse() -> None:
        seen.append(jsjson.parse(Path(path).read_text(encoding='utf-8')))
        return None

    assert store.publish_cache('radius', k, cache(k, 1), refuse) is None
    assert seen == [cache(k)] and store.stored_cache('radius', k) == cache(k, 1)
    hit = {'hit': True}
    assert store.publish_cache('radius', k, cache(k, 2), lambda: hit) is hit
    assert store.stored_cache('radius', k) == cache(k, 1)
    # On a fresh key the reader is not asked.
    assert store.publish_cache('radius', key(2), cache(key(2)), lambda: pytest.fail('asked')) is None


def test_publish_with_the_radius_reader(tmp_path):
    """The radius run path passes ``RadiusCache.read_cache``: a hit is its value (the canonical request), and a cache
    that the first check accepts but the radius reader refuses (another request) is replaced."""
    require('pydantic')
    from eeglayoutlab.jobs.radius import RadiusCache

    from .library_support import radius_result

    root = tmp_path / 'root'
    root.mkdir()
    radius = RadiusCache(str(root), 'python3', get_identity=lambda: {})
    request = {'region_count': 1, 'radius_mm': 15, 'mode': 'whole_surface'}
    k = radius.identity_for(request)[1]
    result = radius_result(request)
    value = {'key': k, 'request': request, 'result': result, 'result_sha256': jsjson.sha256_hex(result),
             'finished_at': '2026-11-23T00:00:00.000Z'}
    os.makedirs(radius.store.path('radius', k))
    assert radius.store.publish_cache('radius', k, value, lambda: radius.read_cache(k, request)) is None
    hit = radius.store.publish_cache('radius', k, {**value, 'finished_at': 'later'},
                                     lambda: radius.read_cache(k, request))
    assert hit == radius.read_cache(k, request) and hit['finished_at'] == '2026-11-23T00:00:00.000Z'
    other = {'region_count': 2, 'radius_mm': 15, 'mode': 'whole_surface'}
    wrong = {**value, 'request': other, 'result': radius_result(other)}
    wrong['result_sha256'] = jsjson.sha256_hex(wrong['result'])
    path = radius.store.path('radius', k, 'cache.json')
    Path(path).write_bytes(json_bytes(wrong))
    assert radius.store.stored_cache('radius', k) == wrong and radius.read_cache(k, request) is None
    assert radius.store.publish_cache('radius', k, value, lambda: radius.read_cache(k, request)) is None
    assert Path(path).read_bytes() == json_bytes(value)


def test_publish_errors_leave_the_cache_as_it_was(store, tmp_path):
    k = key(1)
    path = store.path('radius', k, 'cache.json')
    Path(path).write_bytes(b'{"key":"x"}')
    circular: dict = {}
    circular['self'] = circular
    with pytest.raises(TypeError, match='closes the circle'):
        store.publish_cache('radius', k, circular)
    for bad in ('../' + 'a' * 61, 'A' * 64, None):
        with pytest.raises(RecordError, match='^Invalid scientific record key.$'):
            store.publish_cache('radius', bad, cache(k))
    with pytest.raises(RecordError, match='^Unknown record kind: nope$'):
        store.publish_cache('nope', k, cache(k))
    with pytest.raises(OSError) as missing:
        store.publish_cache('radius', key(9), cache(key(9)))
    missing_directory = store.path('radius', key(9))
    assert node_message(missing.value) == f"ENOENT: no such file or directory, realpath '{missing_directory}'"
    assert Path(path).read_bytes() == b'{"key":"x"}' and entries(store, k) == ['cache.json']
    if SUPERUSER:
        return
    # Node's readers raise EACCES and EPERM rather than call the record a miss: the publish fails.
    os.chmod(path, 0)
    try:
        with pytest.raises(OSError) as denied:
            store.publish_cache('radius', k, cache(k))
        assert error_code(denied.value) == 'EACCES'
        assert node_message(denied.value) == f"EACCES: permission denied, open '{os.path.realpath(path)}'"
    finally:
        os.chmod(path, 0o600)
    assert Path(path).read_bytes() == b'{"key":"x"}' and entries(store, k) == ['cache.json']


def test_threads_racing_for_one_key_publish_once(store):
    for round in range(4):
        k = key(10 + round)
        os.makedirs(store.path('radius', k))
        start, outcomes = threading.Barrier(8), {}

        def publish_one(n: int, k: str = k, start: threading.Barrier = start) -> None:
            start.wait(timeout=60)
            outcomes[n] = store.publish_cache('radius', k, cache(k, n))

        threads = [threading.Thread(target=publish_one, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        assert len(outcomes) == 8
        winners = [n for n, outcome in outcomes.items() if outcome is None]
        assert len(winners) == 1
        assert all(outcome == cache(k, winners[0]) for outcome in outcomes.values() if outcome is not None)
        path = store.path('radius', k, 'cache.json')
        assert Path(path).read_bytes() == json_bytes(cache(k, winners[0])) and os.lstat(path).st_nlink == 1
        assert entries(store, k) == ['cache.json']


RACER = r'''
import sys
from eeglayoutlab.jobs.records import RecordStore
from eeglayoutlab.schemas import jsjson
root, key, text = sys.argv[1:4]
store, value = RecordStore(root), jsjson.parse(text)
sys.stdout.write('ready\n')
sys.stdout.flush()
sys.stdin.read(1)
existing = store.publish_cache('radius', key, value)
sys.stdout.write('published' if existing is None else jsjson.stringify(existing))
'''


def test_processes_racing_for_one_key_publish_once(store):
    """Several services of one installation (two workspaces): the first link wins, the others read its file."""
    k = key(20)
    os.makedirs(store.path('radius', k))
    env = {**os.environ, 'PYTHONPATH': SOURCE}
    racers = [subprocess.Popen([sys.executable, '-c', RACER, store.root, k, jsjson.stringify(cache(k, n))],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                               text=True) for n in range(6)]
    try:
        for racer in racers:
            assert racer.stdout.readline() == 'ready\n'
        for racer in racers:  # all are waiting on stdin: release them together
            racer.stdin.write('x')
            racer.stdin.flush()
        outputs = [racer.communicate(timeout=120) for racer in racers]
    finally:
        for racer in racers:
            if racer.poll() is None:
                racer.kill()
                racer.wait()
    assert [racer.returncode for racer in racers] == [0] * 6, outputs
    texts = [stdout for stdout, _ in outputs]
    winners = [n for n, text in enumerate(texts) if text == 'published']
    assert len(winners) == 1, texts
    winner = jsjson.stringify(cache(k, winners[0]))
    assert all(text == winner for text in texts if text != 'published')
    path = store.path('radius', k, 'cache.json')
    assert Path(path).read_text(encoding='utf-8') == winner and os.lstat(path).st_nlink == 1
    assert entries(store, k) == ['cache.json']


CRASH = r'''
import os, signal, sys
from eeglayoutlab.jobs.records import RecordStore
from eeglayoutlab.schemas import jsjson
root, key, text, call = sys.argv[1:5]
store = RecordStore(root)
setattr(os, call, lambda *args, **kwargs: os.kill(os.getpid(), signal.SIGKILL))
if call == 'link':
    store.publish_cache('radius', key, jsjson.parse(text))
else:
    store.write(store.path('radius', key, 'cache.json'), jsjson.parse(text))
'''


def crash(store: RecordStore, k: str, value: Any, call: str) -> None:
    """Publishes (``link``) or writes (``rename``) in a process killed by SIGKILL at that call."""
    process = subprocess.run([sys.executable, '-c', CRASH, store.root, k, jsjson.stringify(value), call],
                             env={**os.environ, 'PYTHONPATH': SOURCE}, capture_output=True, timeout=120)
    assert process.returncode == -signal.SIGKILL, process.stderr


def test_a_crash_leaves_only_a_temporary_that_readers_ignore(store):
    k = key(1)
    crash(store, k, cache(k), 'link')
    (temporary,) = entries(store, k)
    assert re.fullmatch(rf'cache\.json\.{UUID.pattern}\.tmp', temporary)
    assert Path(store.path('radius', k, temporary)).read_bytes() == json_bytes(cache(k))
    assert store.keys('radius') == [key(n) for n in range(4)]
    assert store.stored_cache('radius', k) is None
    with pytest.raises(OSError) as missing:
        store.read(store.path('radius', k, 'cache.json'))
    assert error_code(missing.value) == 'ENOENT'
    # The next publish is not hindered; the leftover stays, as Node's do.
    assert store.publish_cache('radius', k, cache(k, 1)) is None
    assert entries(store, k) == ['cache.json', temporary]
    assert store.stored_cache('radius', k) == cache(k, 1)
    assert os.lstat(store.path('radius', k, 'cache.json')).st_nlink == 1
    # A crash before atomic_json's rename keeps the previous file.
    crash(store, k, cache(k, 2), 'rename')
    assert store.stored_cache('radius', k) == cache(k, 1)
    assert len(entries(store, k)) == 3 and store.keys('radius') == [key(n) for n in range(4)]


def test_the_library_ignores_temporaries(tmp_path):
    """Slice 3's readers on a root with leftover temporaries next to caches, alone in a key's directory and in
    batches: the library lists, gets and warns exactly as without them, and so do the editor records."""
    require('pydantic')
    from eeglayoutlab.jobs.editor_records import records as editor_records
    from eeglayoutlab.jobs.library import Library
    from eeglayoutlab.jobs.runtime import runtime_config

    from .library_support import library_root

    root = tmp_path / 'root'
    keys = library_root(root, runtime_config(str(tmp_path)).python)

    def listing() -> tuple:
        library = Library(str(root), runtime_config(str(root)))
        listed = library.list()
        got = {row['id']: jsjson.stringify(library.get(row['id'])) for row in listed['records']}
        return jsjson.stringify(listed), got, jsjson.stringify(editor_records(library.store))

    before = listing()
    store = RecordStore(str(root))
    leftovers = 0
    for kind, kind_keys in (('radius', keys['radius'].values()), ('design', keys['design'].values())):
        for k in kind_keys:
            directory = Path(store.path(kind, k))
            if directory.is_dir():
                (directory / f'cache.json.{TEMPORARY}.tmp').write_bytes(b'{"key":"' + k.encode() + b'"}')
                leftovers += 1
    for kind in ('radius', 'design', 'editor'):
        k = key(77)
        os.makedirs(store.path(kind, k, B))
        Path(store.path(kind, k, f'cache.json.{TEMPORARY}.tmp')).write_bytes(json_bytes(cache(k)))
        Path(store.path(kind, k, B, f'job.json.{TEMPORARY}.tmp')).write_bytes(b'{}')
    assert leftovers > 5
    assert listing() == before
