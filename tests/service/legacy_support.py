"""Shared setup for the legacy-import tests (``test_legacy_import.py``).

``build_q(base)`` has Node's own stores write a synthetic queue directory ``Q = <base>/R/results/web-service``, as
the Node host leaves it:

- ``Q/projects`` (``ProjectStore`` through parity/projects.mjs ``store``): a project with layout, editor and source
  entries, an electrode-name annotation, comparison settings, an entry note and a detached snapshot; an empty
  project; and a hand-written project with Node's ``viewer_key_hash`` and ``creator_network`` that Node then
  attaches a snapshot to.
- ``Q/studies`` (``StudyStore`` through parity/studies.mjs ``store``, owned by visitor a): a study with both cases
  archived, and one with a completed and a pending case.
- ``Q/queue.json`` (``CommunityQueue`` through parity/legacy_queue.mjs ``build``): three visitors (two with a
  network) and receipts of every kind and status: signal records computed, a cache hit of the same result by another
  visitor and a repeated one by the same visitor, a v1 request (no ``mode``), a failed, a cancelled, a running and a
  queued signal computation, and completed receipts of the three other kinds.

``digest_tree`` (and ``studies_support.tree``, the drivers' listing with modes and bytes) show that nothing under Q
changed; ``read_only`` takes write permission off a tree for an import and ``restore`` gives it back.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any

from eeglayoutlab.schemas import jsjson

from .key_parity_support import NODE_ENV
from .projects_support import annotation, b64, crafted_project, run_driver as run_projects, scientific, snapshot
from .studies_support import cache_text, prepared_for, run_driver as run_studies, study_input

ROOT = Path(__file__).resolve().parents[2]
QUEUE_DRIVER = ROOT / 'tests/service/parity/legacy_queue.mjs'
EPOCH = 1795564800000  # 2026-11-25T00:00:00.000Z

R1, R2, R3, R4, R5 = ('1' * 64, '2' * 64, '3' * 64, '4' * 64, '5' * 64)
A2 = annotation(R2)
CRAFTED = '0a0a0000-0000-4000-8000-0000000000c0'
PROJECTS = ['0a0a0000-0000-4000-8000-000000000001', '0a0a0000-0000-4000-8000-000000000007', CRAFTED]
STUDIES = ['5d5d0000-0000-4000-8000-000000000001', '5d5d0000-0000-4000-8000-000000000002']


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


VISITORS = {'a': {'id': sha('visitor-a'), 'network': sha('network-a')}, 'b': {'id': sha('visitor-b')},
            'c': {'id': sha('visitor-c'), 'network': sha('network-c')}}


def _b64(value: Any) -> str:
    return base64.b64encode(value.encode('utf-8') if isinstance(value, str) else value).decode('ascii')


# --- Projects ----------------------------------------------------------------------------------------------------

def project_steps() -> list:
    href = f'/decision?a={R1}&b={R2}&thresholdMode=joint&ar=95&sensitivity=95'
    crafted = crafted_project(CRAFTED, title='Hand-written 手写', viewer_key_hash='d' * 64, creator_network='e' * 64)
    return [
        ['create', {'title': 'Node project 研究', 'owner_name': 'Researcher 😀', 'notes': 'Line 1\nLine 2\t"quoted"'}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout', 'title': 'Reference'}, snapshot('layout', R1),
         {'protocol': 'cache', 'electrode_count': 64, 'region_count': 2, 'simulation': True}],
        ['attach', '$P1', {'revision': 2, 'kind': 'layout', 'annotation_id': A2['id']},
         snapshot('layout', R2, annotation=A2), {'protocol': 'design_evaluation', 'electrode_count': 64}],
        ['attach', '$P1', {'revision': 3, 'kind': 'editor'},
         snapshot('editor', R3, payload={'record': {'key': R3}, 'cache': {'values': [1 / 3, 1e21, -0.0, 5e-324]}}),
         {'protocol': 'electrode-editor-result/1'}],
        ['attach', '$P1', {'revision': 4, 'kind': 'source'}, snapshot('source', R4, payload=scientific(7)),
         {'protocol': 'source-reception/2', 'seed': 7}],
        ['attach', '$P1', {'revision': 5, 'kind': 'source'}, snapshot('source', R5), {}],
        ['detach', '$P1', '$E5', 6],
        ['workflow', '$P1', {'reference_entry_id': '$E1', 'candidate_entry_id': '$E2', 'comparison_href': href}],
        ['patch_entry', '$P1', '$E3', {'revision': 8, 'notes': 'kept'}],
        ['create', {'title': 'Empty', 'owner_name': 'R'}],
        ['mkdir', CRAFTED], ['mkdir', f'{CRAFTED}/snapshots'], ['chmod', CRAFTED, 0o700],
        ['chmod', f'{CRAFTED}/snapshots', 0o700],
        ['write', f'{CRAFTED}/project.json', b64(crafted)], ['chmod', f'{CRAFTED}/project.json', 0o600],
        ['attach', CRAFTED, {'revision': 1, 'kind': 'layout', 'title': 'Crafted layout'}, snapshot('layout', R3),
         {'protocol': 'cache'}],
        ['flush'],
    ]


# --- Studies -----------------------------------------------------------------------------------------------------

def study_steps() -> list:
    noise, other = prepared_for(study_input()), prepared_for(study_input((44, 45)))
    k0, k1 = (cache_text(entry['request'])[1] for entry in noise['cases'])
    o0 = cache_text(other['cases'][0]['request'])[1]
    return [['create', noise], ['archive', STUDIES[0], 0, _b64(k0)], ['archive', STUDIES[0], 1, _b64(k1)],
            ['create', other], ['archive', STUDIES[1], 0, _b64(o0)]]


# --- Receipts ----------------------------------------------------------------------------------------------------

def source_request(n: int, mode: Any = 'cross_region') -> dict:
    request = {'record_id': f'{n:x}' * 64 if n < 16 else sha(str(n)), 'seed': 2026 + n, 'region_count': 4}
    if mode is not None:
        request['mode'] = mode
    return request


def receipt_steps() -> list:
    """The build steps, at one second each; ``'tick'`` dispatches or finalizes the head of the queue."""
    out: list = []
    clock = [EPOCH]

    def at(*steps: list) -> None:
        for step in steps:
            clock[0] += 1000
            out.extend([['clock', clock[0]], step])

    def computed(visitor: str, kind: str, request: dict, end: str = 'finish') -> None:
        result: Any = {'kind': kind, 'value': [1 / 3, 1e-300], 'request': request}
        if kind == 'source-reception' and request.get('mode'):
            result.update({'schema_version': 'source-reception/2', 'layout': {'xyzMm': [[1, 2, 3], [4, 5, 6.5]]},
                           'conditions': [{'condition': 'noise', 'field_retention': 0.875, 'extra': 1,
                                           'baseline': {'explained_energy': 0.9},
                                           'candidate': {'explained_energy': 1 / 3}}]})
        at(['submit', visitor, kind, request], ['tick'], [end, kind, result if end == 'finish' else 'worker failed'],
           ['tick'])

    computed('a', 'source-reception', source_request(1))
    at(['submit', 'b', 'source-reception', source_request(1)])          # a cache hit: b's own receipt
    computed('b', 'source-reception', source_request(2, None))          # a v1 request
    computed('c', 'source-reception', source_request(3), 'fail')
    computed('a', 'local-compute', {'region_count': 4, 'seed': 1})
    computed('c', 'design-evaluation', {'design': 'd', 'seed': 2})
    computed('a', 'electrode-editor', {'action': 'evaluate', 'parent_id': R1,
                                       'slots': [{'enabled': True}, {'enabled': False}, {'enabled': True}]})
    at(['submit', 'c', 'source-reception', source_request(4)], ['tick'], ['cancel', 'c', 7],
       ['finish', 'source-reception', None], ['tick'])                  # cancelled while running
    computed('c', 'source-reception', source_request(5, 'multi_source'))
    at(['submit', 'a', 'source-reception', source_request(1)])          # a's own result again: no new receipt
    at(['submit', 'c', 'source-reception', source_request(2, None)])    # a cache hit of the v1 result
    at(['submit', 'a', 'source-reception', source_request(6)], ['tick'])  # left running
    at(['submit', 'b', 'source-reception', source_request(7)])          # left queued
    return out


def run_queue_driver(spec: dict, scratch: Path, name: str) -> dict:
    spec_path, out_path = scratch / f'legacy-{name}.json', scratch / f'legacy-{name}-node.json'
    spec_path.write_text(jsjson.stringify(spec), encoding='utf-8')
    subprocess.run(['node', str(QUEUE_DRIVER), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV,
                   timeout=300)
    return json.loads(out_path.read_text(encoding='utf-8'))


def node_records(queue_file: Path, scratch: Path) -> dict:
    """Node's ``records`` of the receipts in ``queue_file`` (read only): per owner, and for one owner of all."""
    return run_queue_driver({'mode': 'records', 'path': str(queue_file)}, scratch, 'records')


# --- The synthetic Q ---------------------------------------------------------------------------------------------

@dataclass
class LegacyQ:
    root: Path
    queue: Path
    projects: list = field(default_factory=list)
    keys: dict = field(default_factory=dict)      # each Node-created project's owner key
    studies: list = field(default_factory=list)
    receipts: dict = field(default_factory=dict)  # the build's output


def build_q(base: Path, *, projects: bool = True, studies: bool = True, receipts: bool = True) -> LegacyQ:
    """Node writes the synthetic Q under ``<base>/R``; the drivers' scratch files go to ``<base>/node``."""
    root = base / 'R'
    queue = root / 'results' / 'web-service'
    queue.mkdir(parents=True)
    scratch = base / 'node'
    scratch.mkdir()
    built = LegacyQ(root=root, queue=queue)
    if projects:
        output = run_projects('store', [{'id': 'q', 'directory': str(queue / 'projects'),
                                         'steps': project_steps()}], scratch)
        failed = [(index, entry) for index, entry in enumerate(output['by_id']['q']['records'])
                  if not entry.get('ok')]
        assert not failed, failed
        built.projects = list(PROJECTS)
        rows = output['by_id']['q']['records']
        created = [entry for step, entry in zip(project_steps(), rows) if step[0] == 'create']
        built.keys = {jsjson.parse(entry['value'])['project']['id']: entry['access_key'] for entry in created}
    if studies:
        output = run_studies('store', [{'id': 's', 'directory': str(queue / 'studies'), 'steps': study_steps()}],
                             scratch, owner=VISITORS['a']['id'])
        failed = [(index, entry) for index, entry in enumerate(output['by_id']['s']['records']) if not entry['ok']]
        assert not failed, failed
        built.studies = list(STUDIES)
    if receipts:
        built.receipts = run_queue_driver({'mode': 'build', 'directory': str(queue), 'clock': EPOCH,
                                           'visitors': VISITORS, 'steps': receipt_steps()}, scratch, 'build')
    return built


def digest_tree(directory: Path) -> str:
    """One digest of every entry under ``directory``: names, types, modes, bytes, link targets, sizes and times."""
    hasher = hashlib.sha256()
    for current, folders, files in os.walk(directory):
        folders.sort()
        for name in sorted(folders + files):
            path = Path(current) / name
            info = path.lstat()
            hasher.update(f'{path.relative_to(directory)}\0{info.st_mode}\0{info.st_size}\0{info.st_mtime_ns}\0'
                          f'{info.st_nlink}\0'.encode('utf-8', 'surrogateescape'))
            if stat.S_ISLNK(info.st_mode):
                hasher.update(os.readlink(path).encode('utf-8', 'surrogateescape'))
            elif stat.S_ISREG(info.st_mode):
                hasher.update(path.read_bytes())
    info = directory.lstat()
    hasher.update(f'{info.st_mode}\0{info.st_mtime_ns}'.encode('ascii'))
    return hasher.hexdigest()


def read_only(directory: Path) -> list:
    """Takes write permission off everything under ``directory`` (not following links); returns the old modes."""
    modes = []
    for current, folders, files in os.walk(directory, topdown=False):
        for name in folders + files:
            path = Path(current) / name
            if not path.is_symlink():
                modes.append((path, path.lstat().st_mode & 0o7777))
                os.chmod(path, path.lstat().st_mode & ~0o222)
    modes.append((directory, directory.lstat().st_mode & 0o7777))
    os.chmod(directory, directory.lstat().st_mode & ~0o222)
    return modes


def restore(modes: list) -> None:
    for path, mode in reversed(modes):
        os.chmod(path, mode)
