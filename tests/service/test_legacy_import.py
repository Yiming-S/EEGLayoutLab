"""The legacy import (phase 2 slice 9): ``eeglayoutlab.server.legacy_import`` and ``eeglayoutlab workspace
import-legacy``.

Node has no import; these tests hold the import to Node's own code on a synthetic queue directory Q that Node's
``ProjectStore``, ``StudyStore`` and ``CommunityQueue`` wrote (``legacy_support.build_q``):

- What is imported reads in Python as Node reads the original: Node's ``load`` and ``snapshot`` of every project
  (projects/store.mjs:129, :271) on Q equal Python's on W; Node's study ``ids``, ``all``, ``usage``, ``present`` and
  ``snapshot`` (studies/store.mjs:229, :415) on Q equal Python's on W; Node's ``records`` (community-queue.mjs:404) of
  one visitor who owns every receipt equals the workspace queue's ``records()``. The copies are byte for byte, with
  Node's modes, and Python continues them.
- What is refused is what Node refuses to read (its messages), plus collisions with the workspace's own records;
  Node's queue-state check (community-queue.mjs:66-68) refuses a queue file.
- Q is never written: every import, direct or through the command, compares a digest of the whole tree of the queue
  directory it reads (names, modes, sizes, times, bytes, link targets) before and after, whatever it returns or
  raises (``q_is_never_written``), and the main test imports from a Q without write permission.
- A failed write leaves whole records only, and a second run completes the import.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid

import pytest

from schema_parity_support import require

require('pydantic')

from eeglayoutlab.cli import main as cli  # noqa: E402
from eeglayoutlab.jobs import queue as workspace_queue  # noqa: E402
from eeglayoutlab.jobs import records  # noqa: E402
from eeglayoutlab.jobs.queue import WorkspaceQueue  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402
from eeglayoutlab.server import legacy_import  # noqa: E402
from eeglayoutlab.server.legacy_import import (  # noqa: E402
    COLLISION, NODE_QUEUE_STATE, RECEIPT_COLLISION, LegacyImportError, describe, succeeded,
)
from eeglayoutlab.server.workspace import Workspace, WorkspaceInUse  # noqa: E402
from eeglayoutlab.server.workspace_projects import ProjectStore  # noqa: E402
from eeglayoutlab.server.workspace_studies import STUDY_LIMITS, StudyStore  # noqa: E402

from .key_parity_support import needs_node  # noqa: E402
from .legacy_support import (  # noqa: E402
    CRAFTED, PROJECTS, R5, STUDIES, VISITORS, LegacyQ, build_q, digest_tree, node_records, read_only, restore,
)
from .projects_support import node_read, python_read, run_driver as run_projects, snapshot  # noqa: E402
from .studies_support import node_outcome, python_store, run_driver as run_studies, tree  # noqa: E402

P1, P2 = PROJECTS[0], PROJECTS[1]
S1, S2 = STUDIES
STATE = '.eeglayoutlab'


@pytest.fixture(autouse=True)
def q_is_never_written(monkeypatch):
    """Every import of these tests, the command's too, leaves the queue directory it reads as it was, whatever it
    returns or raises (a failure or a crash midway included)."""
    run = legacy_import.import_legacy

    def checked(workspace: str, queue_directory: str, **options):
        directory = Path(os.path.realpath(queue_directory))
        before = digest_tree(directory) if directory.is_dir() else None
        try:
            return run(workspace, queue_directory, **options)
        finally:
            assert (digest_tree(directory) if directory.is_dir() else None) == before, f'{directory} was written'
    monkeypatch.setattr(legacy_import, 'import_legacy', checked)


def import_legacy(workspace: str, queue_directory: str, **options) -> dict:
    """``legacy_import.import_legacy``, as ``q_is_never_written`` checks it."""
    return legacy_import.import_legacy(workspace, queue_directory, **options)


@pytest.fixture(scope='module')
def node_q(tmp_path_factory) -> LegacyQ:
    """The synthetic Q, written once by Node; tests import from copies (``fresh``)."""
    return build_q(tmp_path_factory.mktemp('legacy-q'))


def fresh(base: Path, built: LegacyQ) -> LegacyQ:
    """A copy of ``built`` under ``<base>/R`` (modes, times and links kept)."""
    root = base / 'R'
    shutil.copytree(built.root, root, symlinks=True)
    return LegacyQ(root=root, queue=root / 'results' / 'web-service', projects=list(built.projects),
                   keys=dict(built.keys), studies=list(built.studies), receipts=built.receipts)


def node_tasks(q: LegacyQ) -> list:
    return json.loads((q.queue / 'queue.json').read_text(encoding='utf-8'))['tasks']


def expected_receipts(tasks: list) -> list:
    """The ids the import takes: the newest completed signal-reception receipt of each key, oldest first."""
    newest: dict = {}
    for task in tasks:
        if isinstance(task, dict) and task.get('kind') == 'source-reception' and task.get('status') == 'completed':
            if task['key'] not in newest or task['sequence'] > newest[task['key']]['sequence']:
                newest[task['key']] = task
    return [task['id'] for task in sorted(newest.values(), key=lambda task: task['sequence'])]


def workspace_queue_file(workspace: Path) -> dict:
    return jsjson.parse((workspace / STATE / 'queue.json').read_text(encoding='utf-8'))


def reasons(section: dict) -> dict:
    return {row['id']: row['reason'] for row in section['refused']}


class Saved:
    """A signal-reception adapter that only reads stored results (``saved_result``)."""

    def __init__(self) -> None:
        self.calls: list = []

    def saved_result(self, key: str, request: dict) -> dict:
        self.calls.append((key, request))
        return {'key': key}


# --- The import --------------------------------------------------------------------------------------------------

@needs_node
def test_node_written_records_are_copied_byte_for_byte_from_a_read_only_q(node_q, tmp_path):
    q = fresh(tmp_path, node_q)
    before, listing = digest_tree(q.root), tree(q.queue)
    workspace = tmp_path / 'W'
    modes = read_only(q.root)
    try:
        report = import_legacy(str(workspace), str(q.queue), root=str(q.root))
    finally:
        restore(modes)
    assert digest_tree(q.root) == before and tree(q.queue) == listing
    assert succeeded(report), describe(report)
    tasks = node_tasks(q)
    assert report['projects'] == {'imported': PROJECTS, 'present': [], 'refused': [], 'ignored': []}
    assert report['studies'] == {'imported': STUDIES, 'present': [], 'refused': [], 'ignored': []}
    receipts = report['receipts']
    assert receipts['imported'] == expected_receipts(tasks) and len(receipts['imported']) == 3
    assert (receipts['other_kinds'], receipts['not_completed'], receipts['older_duplicates']) == (3, 4, 2)
    assert receipts['without_result'] == receipts['imported']  # the synthetic root has no stored result
    assert report['skipped_files'] == [] and report['failure'] is None
    for kind, ids in (('projects', PROJECTS), ('studies', STUDIES)):
        assert sorted(os.listdir(workspace / kind)) == ids
        for id in ids:
            copied = tree(workspace / kind / id)
            assert copied == tree(q.queue / kind / id)
            assert {row[2] for row in copied} == {0o700, 0o600}
            assert (workspace / kind / id).stat().st_mode & 0o777 == 0o700
    assert sorted(os.listdir(workspace / STATE)) == ['.gitignore', 'lock', 'queue.json']
    state = workspace_queue_file(workspace)
    assert state['schema'] == 'eeglayoutlab-queue/1' and state['sequence'] == 3
    assert [task['id'] for task in state['tasks']] == receipts['imported']
    by_id = {task['id']: task for task in tasks}
    for number, task in enumerate(state['tasks'], 1):
        node = by_id[task['id']]
        names = [name for name in node if name not in ('owners', 'networks')]
        assert list(task) == [{'backendId': 'backend_id'}.get(name, name) for name in names]
        assert task == {**{{'backendId': 'backend_id'}.get(name, name): node[name] for name in names},
                        'sequence': number}


@needs_node
def test_imported_records_read_in_python_as_node_reads_the_originals(node_q, tmp_path):
    q = fresh(tmp_path, node_q)
    before = digest_tree(q.root)
    workspace = tmp_path / 'W'
    assert succeeded(import_legacy(str(workspace), str(q.queue)))
    scratch = tmp_path / 'node'
    scratch.mkdir()
    # Projects: Node's load and snapshot of the original and of the copy, Python's of the copy.
    cases = [{'id': side, 'directory': str(base / 'projects'), 'projects': PROJECTS}
             for side, base in (('q', q.queue), ('w', workspace))]
    node = run_projects('read', cases, scratch)['by_id']
    original = node_read(node['q'])
    assert all(project['ok'] for project in original['projects'])
    assert {**node_read(node['w']), 'id': 'q'} == original
    assert {**python_read({**cases[1], 'id': 'q'})} == original
    # Studies: Node's reads of the original and of the copy, Python's of the copy.
    steps = [['ids'], ['all'], ['usage'], ['present', S1, True], ['present', S2, False], ['snapshot', S1, 1],
             ['load', S2]]
    items = [{'id': side, 'directory': str(base / 'studies'), 'steps': steps}
             for side, base in (('q', q.queue), ('w', workspace))]
    studies = run_studies('store', items, scratch, owner=VISITORS['a']['id'])['by_id']
    expected = [node_outcome(entry) for entry in studies['q']['records']]
    assert all(entry['ok'] for entry in expected)
    assert [node_outcome(entry) for entry in studies['w']['records']] == expected
    assert python_store({**items[1], 'id': 'q'})['records'] == expected
    # Signal records: Node's records() of one visitor who owns every receipt, and of each visitor.
    listed = node_records(q.queue / 'queue.json', scratch)

    async def workspace_records() -> dict:
        queue = WorkspaceQueue(str(workspace / STATE), {}, boot_id=lambda: 'legacy-tests')
        try:
            return queue.records()
        finally:
            queue.dispose()
    python = asyncio.run(workspace_records())
    every = jsjson.parse(listed['all'])
    assert jsjson.stringify(python['records']) == jsjson.stringify(every['records'])
    assert len(python['records']) == 3
    views = {view['id']: jsjson.stringify(view) for view in python['records']}
    owned = set()
    for owner, text in listed['owners'].items():
        for view in jsjson.parse(text)['records']:
            if view['id'] in views:
                owned.add(view['id'])
                assert jsjson.stringify(view) == views[view['id']]
    assert owned == set(views)
    assert digest_tree(q.root) == before


@needs_node
def test_python_continues_imported_projects_studies_and_records(node_q, tmp_path):
    q = fresh(tmp_path, node_q)
    workspace = tmp_path / 'W'
    report = import_legacy(str(workspace), str(q.queue))
    studies_size = sum(path.stat().st_size for path in (q.queue / 'studies').rglob('*') if path.is_file())
    saved = Saved()

    async def go() -> None:
        projects = ProjectStore(str(workspace / 'projects'))
        record = await projects.load(P1)
        patched = await projects.patch(P1, {'revision': record['revision'], 'title': 'Continued in Python'})
        assert patched['project']['title'] == 'Continued in Python'
        crafted = await projects.load(CRAFTED)
        assert crafted['viewer_key_hash'] == 'd' * 64 and crafted['creator_network'] == 'e' * 64
        await projects.attach(CRAFTED, {'revision': crafted['revision'], 'kind': 'source'}, snapshot('source', R5),
                              {'seed': 1})
        read = await projects.read_snapshots(CRAFTED)
        assert [row['entry']['kind'] for row in read['entries']] == ['layout', 'source']
        await projects.flush()
        studies = StudyStore(str(workspace / 'studies'))
        assert await studies.usage() == studies_size
        await studies.update(S2, lambda value: value.__setitem__('title', 'Renamed in Python'))
        assert (await studies.present(S2))['title'] == 'Renamed in Python'
        await studies.flush()
        queue = WorkspaceQueue(str(workspace / STATE), {'source-reception': saved}, boot_id=lambda: 'legacy-tests')
        try:
            for id in report['receipts']['imported']:
                assert await queue.saved_result(id) == {'key': queue.own(id)['key']}
        finally:
            queue.dispose()
    asyncio.run(go())
    by_id = {task['id']: task for task in node_tasks(q)}
    assert saved.calls == [(by_id[id]['key'], by_id[id]['request']) for id in report['receipts']['imported']]


@needs_node
def test_a_second_import_finds_everything_present_and_changes_nothing(node_q, tmp_path):
    q = fresh(tmp_path, node_q)
    workspace = tmp_path / 'W'
    first = import_legacy(str(workspace), str(q.queue))
    copies = {kind: digest_tree(workspace / kind) for kind in ('projects', 'studies')}
    queue_bytes = (workspace / STATE / 'queue.json').read_bytes()
    second = import_legacy(str(workspace), str(q.queue))
    assert succeeded(second)
    assert second['projects'] == {'imported': [], 'present': PROJECTS, 'refused': [], 'ignored': []}
    assert second['studies'] == {'imported': [], 'present': STUDIES, 'refused': [], 'ignored': []}
    assert second['receipts']['imported'] == [] and second['receipts']['present'] == first['receipts']['imported']
    assert {kind: digest_tree(workspace / kind) for kind in ('projects', 'studies')} == copies
    assert (workspace / STATE / 'queue.json').read_bytes() == queue_bytes
    assert 'already in the workspace' in describe(second)


# --- Refusals ----------------------------------------------------------------------------------------------------

def _flip(path: Path) -> None:
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0x01
    os.chmod(path, 0o600)
    path.write_bytes(bytes(data))


def _snapshots(directory: Path) -> list:
    return sorted((directory / 'snapshots').iterdir())


def node_refusals(q: LegacyQ, scratch: Path) -> tuple[dict, dict]:
    """Node's first refusal reading each project of Q (``load``, then every entry's ``snapshot``) and each study
    (``present`` with the caches): ``({id: message}, {id: message})``, a system error by its code."""
    scratch.mkdir(exist_ok=True)
    case = {'id': 'refusals', 'directory': str(q.queue / 'projects'), 'projects': q.projects}
    projects = {}
    for id, project in zip(q.projects, run_projects('read', [case], scratch)['by_id']['refusals']['projects']):
        failed = project if not project['ok'] else next((row for row in project['snapshots'] if not row['ok']), None)
        if failed is not None:
            projects[id] = failed['message'] or failed['code']
    item = {'id': 'refusals', 'directory': str(q.queue / 'studies'), 'steps': [['present', id, True]
                                                                             for id in q.studies]}
    rows = run_studies('store', [item], scratch, owner=VISITORS['a']['id'])['by_id']['refusals']['records']
    studies = {id: row['message'] or row['code'] for id, row in zip(q.studies, rows) if not row['ok']}
    return projects, studies


def _rewrite(path: Path, change) -> None:
    value = jsjson.parse(path.read_text(encoding='utf-8'))
    change(value)
    path.write_bytes(jsjson.stringify(value).encode('utf-8'))


@needs_node
def test_projects_node_refuses_to_read_are_refused_with_its_messages(node_q, tmp_path):
    """Damaged metadata, an altered, a missing and a mismatched snapshot: the import refuses what Node's reads refuse,
    with Node's message, and imports the rest. A damaged detached snapshot, which Node never reads, is refused too
    (every snapshot's bytes must match its name)."""
    q = fresh(tmp_path / 'first', node_q)
    projects = q.queue / 'projects'
    p1 = jsjson.parse((projects / P1 / 'project.json').read_text(encoding='utf-8'))
    attached = {entry['snapshot_sha256'] for entry in p1['entries']}
    detached = [path for path in _snapshots(projects / P1) if path.name[:64] not in attached]
    assert len(detached) == 1
    _flip(detached[0])
    (projects / P2 / 'project.json').write_bytes(b'{"schema": "research-project/1"')
    _flip(_snapshots(projects / CRAFTED)[0])
    before = digest_tree(q.root)
    report = import_legacy(str(tmp_path / 'W'), str(q.queue))
    assert digest_tree(q.root) == before
    node_projects, _ = node_refusals(q, tmp_path / 'node')
    assert node_projects == {P2: 'Project metadata failed integrity checks.',
                             CRAFTED: 'Scientific snapshot failed integrity checks.'}
    assert reasons(report['projects']) == {**node_projects, P1: 'Scientific snapshot failed integrity checks.'}
    assert report['projects']['imported'] == [] and os.listdir(tmp_path / 'W' / 'projects') == []
    assert report['studies']['imported'] == STUDIES and len(report['receipts']['imported']) == 3
    assert not succeeded(report)
    assert f'project {P2}: Project metadata failed integrity checks.' in describe(report)
    # A missing snapshot, a snapshot of another record, metadata Node's validation refuses.
    q = fresh(tmp_path / 'second', node_q)
    projects = q.queue / 'projects'
    (projects / P1 / 'snapshots' / f"{p1['entries'][2]['snapshot_sha256']}.json").unlink()
    _rewrite(projects / CRAFTED / 'project.json', lambda value: value['entries'][0].__setitem__('record_id', R5))
    _rewrite(projects / P2 / 'project.json', lambda value: value.__setitem__('revision', 0))
    report = import_legacy(str(tmp_path / 'W2'), str(q.queue))
    node_projects, _ = node_refusals(q, tmp_path / 'node')
    assert node_projects == {P1: 'Scientific snapshot is missing.', P2: 'Project metadata failed integrity checks.',
                             CRAFTED: 'Scientific snapshot identity mismatch.'}
    assert reasons(report['projects']) == node_projects


@needs_node
def test_a_study_whose_snapshot_is_missing_or_altered_is_refused(node_q, tmp_path):
    """The import refuses the studies Node's ``present`` refuses, with Node's message (a missing snapshot, a system
    error in Node, is named)."""
    q = fresh(tmp_path / 'first', node_q)
    studies = q.queue / 'studies'
    s2 = jsjson.parse((studies / S2 / 'study.json').read_text(encoding='utf-8'))
    missing = s2['cases'][0]['source_sha256']
    (studies / S2 / 'snapshots' / f'{missing}.json').unlink()
    _flip(_snapshots(studies / S1)[1])
    before = digest_tree(q.root)
    report = import_legacy(str(tmp_path / 'W'), str(q.queue))
    assert digest_tree(q.root) == before
    _, node_studies = node_refusals(q, tmp_path / 'node')
    assert node_studies == {S1: 'Study snapshot checksum mismatch.', S2: 'ENOENT'}
    assert reasons(report['studies']) == {S1: 'Study snapshot checksum mismatch.',
                                         S2: f'Study snapshot snapshots/{missing}.json is missing.'}
    assert os.listdir(tmp_path / 'W' / 'studies') == []
    assert report['projects']['imported'] == PROJECTS
    # A snapshot whose bytes match but which is not the case's cache; metadata Node's validation refuses.
    q = fresh(tmp_path / 'second', node_q)
    studies = q.queue / 'studies'
    other = b'{"key": "x"}'
    other_sha = hashlib.sha256(other).hexdigest()
    (studies / S1 / 'snapshots' / f'{other_sha}.json').write_bytes(other)

    def point(value: dict) -> None:
        value['cases'][1].update({'source_sha256': other_sha, 'source_bytes': len(other)})
    _rewrite(studies / S1 / 'study.json', point)
    _rewrite(studies / S2 / 'study.json', lambda value: value.__setitem__('revision', 1.5))
    report = import_legacy(str(tmp_path / 'W2'), str(q.queue))
    _, node_studies = node_refusals(q, tmp_path / 'node')
    assert node_studies == {S1: 'Study scientific cache identity mismatch.',
                            S2: 'Study metadata failed integrity checks.'}
    assert reasons(report['studies']) == node_studies


@needs_node
def test_links_in_q_are_refused_where_a_store_reads_and_never_followed(node_q, tmp_path):
    q = fresh(tmp_path, node_q)
    projects, studies = q.queue / 'projects', q.queue / 'studies'
    outside = tmp_path / 'outside'
    outside.mkdir()
    # project.json, a project directory, an attached snapshot: links to copies with the same bytes.
    shutil.copy2(projects / P1 / 'project.json', outside / 'project.json')
    (projects / P1 / 'project.json').unlink()
    (projects / P1 / 'project.json').symlink_to(outside / 'project.json')
    shutil.copytree(projects / P2, outside / P2)
    shutil.rmtree(projects / P2)
    (projects / P2).symlink_to(outside / P2, target_is_directory=True)
    target = _snapshots(projects / CRAFTED)[0]
    shutil.copy2(target, outside / target.name)
    target.unlink()
    target.symlink_to(outside / target.name)
    # study.json, a study's snapshots directory.
    shutil.copy2(studies / S1 / 'study.json', outside / 'study.json')
    (studies / S1 / 'study.json').unlink()
    (studies / S1 / 'study.json').symlink_to(outside / 'study.json')
    shutil.copytree(studies / S2 / 'snapshots', outside / 'snapshots')
    shutil.rmtree(studies / S2 / 'snapshots')
    (studies / S2 / 'snapshots').symlink_to(outside / 'snapshots', target_is_directory=True)
    # queue.json.
    shutil.copy2(q.queue / 'queue.json', outside / 'queue.json')
    (q.queue / 'queue.json').unlink()
    (q.queue / 'queue.json').symlink_to(outside / 'queue.json')
    before, outside_before = digest_tree(q.root), digest_tree(outside)
    workspace = tmp_path / 'W'
    report = import_legacy(str(workspace), str(q.queue))
    assert digest_tree(q.root) == before and digest_tree(outside) == outside_before
    assert reasons(report['projects']) == {P1: 'Project file failed integrity checks.',
                                          P2: 'Project directory is not a regular directory.',
                                          CRAFTED: 'Project file failed integrity checks.'}
    assert reasons(report['studies']) == {S1: 'Project file failed integrity checks.',
                                         S2: 'Project directory is not a regular directory.'}
    assert node_refusals(q, tmp_path / 'node') == (reasons(report['projects']), reasons(report['studies']))
    assert reasons(report['receipts']) == {'queue.json': 'queue.json is not a regular file with one link (a link is '
                                                         'not followed), or it is larger than 64 MiB.'}
    assert os.listdir(workspace / 'projects') == [] and os.listdir(workspace / 'studies') == []
    assert not (workspace / STATE / 'queue.json').exists()


@needs_node
def test_detached_snapshots_node_would_refuse_to_keep_are_refused(node_q, tmp_path):
    """A detached ``<sha256>.json`` that is a link, or a file with a second link, is refused with the message of
    Node's ``attach``, which refuses to save anything more in such a project."""
    q = fresh(tmp_path, node_q)
    projects = q.queue / 'projects'
    p1 = jsjson.parse((projects / P1 / 'project.json').read_text(encoding='utf-8'))
    attached = {entry['snapshot_sha256'] for entry in p1['entries']}
    [detached] = [path for path in _snapshots(projects / P1) if path.name[:64] not in attached]
    outside = tmp_path / 'outside'
    outside.mkdir()
    shutil.copy2(detached, outside / detached.name)
    detached.unlink()
    detached.symlink_to(outside / detached.name)
    linked = b'{"schema": "research-project-snapshot/1"}'
    (outside / 'linked.json').write_bytes(linked)
    os.link(outside / 'linked.json', projects / CRAFTED / 'snapshots' / f'{hashlib.sha256(linked).hexdigest()}.json')
    before = digest_tree(q.root)
    report = import_legacy(str(tmp_path / 'W'), str(q.queue))
    assert digest_tree(q.root) == before
    assert reasons(report['projects']) == {P1: 'Scientific snapshot path is invalid.',
                                          CRAFTED: 'Scientific snapshot path is invalid.'}
    assert report['projects']['imported'] == [P2]
    steps = [['attach', id, {'revision': revision, 'kind': 'layout'}, snapshot('layout', R5), {}]
             for id, revision in ((P1, p1['revision']), (CRAFTED, 2))]
    case = {'id': 'attach', 'directory': str(projects), 'steps': steps, 'keys': q.keys}
    (tmp_path / 'node').mkdir()
    rows = run_projects('store', [case], tmp_path / 'node')
    messages = [row['message'] for row in rows['by_id']['attach']['records']]
    assert messages == ['Scientific snapshot path is invalid.'] * 2


@needs_node
def test_the_studies_total_bound_applies_to_imported_studies(node_q, tmp_path, monkeypatch):
    q = fresh(tmp_path, node_q)
    sizes = {id: sum(path.stat().st_size for path in (q.queue / 'studies' / id).rglob('*') if path.is_file())
             for id in STUDIES}
    monkeypatch.setitem(STUDY_LIMITS, 'totalBytes', sum(sizes.values()) - 1)
    report = import_legacy(str(tmp_path / 'W'), str(q.queue))
    assert report['studies']['imported'] == [S1]
    assert reasons(report['studies']) == {S2: 'Study storage capacity reached.'}
    monkeypatch.setitem(STUDY_LIMITS, 'totalBytes', sum(sizes.values()))
    assert import_legacy(str(tmp_path / 'W'), str(q.queue))['studies']['imported'] == [S2]


@needs_node
def test_a_record_that_appears_during_the_import_is_not_replaced(node_q, tmp_path, monkeypatch):
    """Publishing renames a staged directory, which would replace an empty directory; the target is checked again
    under the workspace lock, and a record that appeared anyway stops the import."""
    q = fresh(tmp_path, node_q)
    workspace = tmp_path / 'W'
    stage = legacy_import._Staging.stage

    def racing(self, record):
        staged = stage(self, record)
        if record.id == P2:
            (workspace / 'projects' / P2).mkdir()
        return staged
    monkeypatch.setattr(legacy_import._Staging, 'stage', racing)
    report = import_legacy(str(workspace), str(q.queue))
    assert report['failure'] == f"project {P2}: {workspace / 'projects' / P2} appeared during the import."
    assert report['projects']['imported'] == [P1] and os.listdir(workspace / 'projects' / P2) == []


@needs_node
def test_other_entries_of_q_are_listed_and_not_copied(node_q, tmp_path):
    """Links and files the stores never read are skipped (never followed); temporaries of interrupted writes too;
    a directory without metadata (an interrupted create) and non-record names are ignored; a linked Q, studies
    directory or a record named as a file are what Node refuses."""
    q = fresh(tmp_path, node_q)
    projects, studies = q.queue / 'projects', q.queue / 'studies'
    secret = tmp_path / 'secret.txt'
    secret.write_text('never copied')
    temporary = f'project.json.{uuid.uuid4()}.tmp'
    (projects / CRAFTED / temporary).write_bytes(b'{}')
    (projects / CRAFTED / 'notes').symlink_to(secret)
    staged = f'{_snapshots(projects / CRAFTED)[0].name}.{uuid.uuid4()}.tmp'
    (projects / CRAFTED / 'snapshots' / staged).write_bytes(b'x')
    (projects / CRAFTED / 'snapshots' / 'other.json').symlink_to(secret)
    (projects / '.DS_Store').write_bytes(b'\0')
    interrupted = str(uuid.uuid4())
    (projects / interrupted / 'snapshots').mkdir(parents=True)
    (studies / S1 / 'link').symlink_to(secret)
    other = str(uuid.uuid4())
    shutil.copytree(studies / S2, studies / other)                      # its study.json names S2
    linked_q = tmp_path / 'linked-q'
    linked_q.symlink_to(q.queue, target_is_directory=True)
    before = digest_tree(q.root)
    workspace = tmp_path / 'W'
    report = import_legacy(str(workspace), str(linked_q))
    assert digest_tree(q.root) == before
    assert report['projects']['imported'] == PROJECTS and report['studies']['imported'] == STUDIES
    assert report['projects']['ignored'] == ['projects/.DS_Store',
                                             f'projects/{interrupted}: no project.json (an interrupted create)']
    assert report['studies']['ignored'] == [f'studies/{other}: its study.json names another study']
    assert sorted(report['skipped_files']) == sorted([
        f'projects/{CRAFTED}/notes', f'projects/{CRAFTED}/{temporary}', f'projects/{CRAFTED}/snapshots/{staged}',
        f'projects/{CRAFTED}/snapshots/other.json', f'studies/{S1}/link'])
    assert succeeded(report)
    assert tree(workspace / 'projects' / CRAFTED) == [row for row in tree(projects / CRAFTED)
                                                      if row[1] != 'link' and not row[0].endswith('.tmp')]
    assert not (workspace / 'studies' / S1 / 'link').exists()
    assert sorted(os.listdir(workspace / 'projects')) == PROJECTS
    # Node's refusals of the directories themselves.
    (projects / P1).rename(tmp_path / 'moved')
    (projects / P1).write_bytes(b'')
    os.rename(studies, tmp_path / 'studies-real')
    studies.symlink_to(tmp_path / 'studies-real', target_is_directory=True)
    again = import_legacy(str(tmp_path / 'W2'), str(q.queue))
    assert reasons(again['projects']) == {P1: 'Project directory is not a regular directory.'}
    assert reasons(again['studies']) == {'studies': 'Project directory is not a regular directory.'}


@needs_node
def test_receipts_of_other_kinds_incomplete_and_malformed_receipts_are_not_imported(node_q, tmp_path):
    q = fresh(tmp_path, node_q)
    path = q.queue / 'queue.json'
    value = json.loads(path.read_text(encoding='utf-8'))
    good = expected_receipts(value['tasks'])
    template = next(task for task in value['tasks'] if task['id'] == good[1])
    crafted = []

    def add(change: dict, drop: tuple = (), id: str | None = None) -> str:
        task = {**template, 'id': id or str(uuid.uuid4()), 'key': os.urandom(32).hex(), **change}
        for name in drop:
            del task[name]
        crafted.append(task)
        return task['id']

    expected = {
        add({}, id='not-a-uuid'): 'task {n} has no UUID id',
        add({'key': 'A' * 64}): 'task {n} has no SHA-256 key',
        add({}, drop=('key',)): 'task {n} has no SHA-256 key',
        add({'request': 'x'}): 'task {n} has no request object',
        add({'sequence': 0}): 'task {n} has an invalid sequence',
        add({'sequence': 1.5}): 'task {n} has an invalid sequence',
        add({'sequence': 2 ** 53}): 'task {n} has an invalid sequence',
        add({'created_at': 'yesterday'}): 'task {n} has an invalid created_at',
        add({'message': None}): 'task {n} has an invalid message',
        add({'catalog': 5}): 'task {n} has an invalid catalog',
        add({'cached': 'yes'}): 'task {n} has an invalid cached flag',
        add({'progress': None}): 'task {n} has an invalid progress',
        add({'backendId': 5}): 'task {n} has an invalid backend_id',
    }
    repeated = add({}, id=good[0])
    add({'status': 'no_layout'})
    add({'kind': 'local-compute'})
    value['tasks'] = value['tasks'] + crafted + [7]
    path.write_text(json.dumps(value), encoding='utf-8')
    base = len(value['tasks']) - len(crafted) - 1
    numbers = {task['id']: base + index for index, task in enumerate(crafted, 1)}
    before = digest_tree(q.root)
    workspace = tmp_path / 'W'
    report = import_legacy(str(workspace), str(q.queue))
    assert digest_tree(q.root) == before
    receipts = report['receipts']
    assert receipts['imported'] == good
    assert receipts['refused'] == (
        [{'id': id, 'reason': text.format(n=numbers[id])} for id, text in expected.items()]
        + [{'id': repeated, 'reason': f'task {numbers[repeated]} repeats the id of an earlier receipt'},
           {'id': f'task {len(value["tasks"])}', 'reason': f'task {len(value["tasks"])} is not an object'}])
    assert (receipts['other_kinds'], receipts['not_completed']) == (4, 5)
    assert [task['id'] for task in workspace_queue_file(workspace)['tasks']] == good


@pytest.mark.parametrize('text', [
    '{"version": 2, "sequence": 0, "tasks": []}', '{"version": true, "sequence": 0, "tasks": []}',
    '{"version": 1, "tasks": {}}', '{"version": 1, "maintenance": null, "tasks": []}',
    '{"version": 1, "maintenance": "no", "tasks": []}', '[]', 'null',
])
def test_a_queue_file_node_would_refuse_is_refused(tmp_path, text):
    queue = tmp_path / 'Q'
    queue.mkdir()
    (queue / 'queue.json').write_text(text, encoding='utf-8')
    report = import_legacy(str(tmp_path / 'W'), str(queue))
    assert report['receipts']['refused'] == [{'id': 'queue.json', 'reason': NODE_QUEUE_STATE}]
    assert not (tmp_path / 'W' / STATE / 'queue.json').exists()


def test_a_queue_directory_without_records_imports_nothing(tmp_path):
    queue = tmp_path / 'Q'
    queue.mkdir()
    (queue / 'queue.json').write_text('{"version": 1, "sequence": 0, "maintenance": false, "tasks": []}')
    report = import_legacy(str(tmp_path / 'W'), str(queue))
    assert succeeded(report) and report['receipts']['imported'] == []
    assert sorted(os.listdir(tmp_path / 'W')) == ['.eeglayoutlab', 'eeglayoutlab-workspace.json']
    (queue / 'queue.json').write_text('{"version": 1,')
    assert reasons(import_legacy(str(tmp_path / 'W'), str(queue))['receipts']) == {
        'queue.json': 'queue.json is not valid JSON.'}


# --- Collisions and the workspace queue --------------------------------------------------------------------------

@needs_node
def test_collisions_are_refused_and_the_workspace_records_kept(node_q, tmp_path):
    q = fresh(tmp_path, node_q)
    workspace = tmp_path / 'W'
    first = import_legacy(str(workspace), str(q.queue))
    imported = first['receipts']['imported']

    async def change() -> None:
        projects = ProjectStore(str(workspace / 'projects'))
        record = await projects.load(P2)
        await projects.patch(P2, {'revision': record['revision'], 'title': 'Changed in the workspace'})
        await projects.flush()
        studies = StudyStore(str(workspace / 'studies'))
        await studies.update(S1, lambda value: value.__setitem__('title', 'Changed in the workspace'))
        await studies.flush()
    asyncio.run(change())
    state = workspace_queue_file(workspace)
    state['tasks'][0]['key'] = 'f' * 64                                 # same id, another result
    records.atomic_json(str(workspace / STATE / 'queue.json'), state)
    kept = {kind: digest_tree(workspace / kind) for kind in ('projects', 'studies')}
    queue_bytes = (workspace / STATE / 'queue.json').read_bytes()
    report = import_legacy(str(workspace), str(q.queue))
    assert reasons(report['projects']) == {P2: COLLISION['projects']}
    assert reasons(report['studies']) == {S1: COLLISION['studies']}
    assert reasons(report['receipts']) == {imported[0]: RECEIPT_COLLISION}
    assert report['projects']['present'] == [P1, CRAFTED] and report['studies']['present'] == [S2]
    assert report['receipts']['present'] == imported[1:]
    assert {kind: digest_tree(workspace / kind) for kind in ('projects', 'studies')} == kept
    assert (workspace / STATE / 'queue.json').read_bytes() == queue_bytes
    assert not succeeded(report)
    # A workspace project made by Python with Node's identifier, and a key the workspace already lists.
    other = tmp_path / 'W2'
    (other / 'projects' / P1 / 'snapshots').mkdir(parents=True)
    (other / 'projects' / P1 / 'project.json').write_bytes(b'{}')
    task = workspace_queue_file(workspace)['tasks'][1]
    Workspace.open(str(other)).close()
    records.atomic_json(str(other / STATE / 'queue.json'), {'schema': 'eeglayoutlab-queue/1', 'sequence': 1,
                                                             'tasks': [{**task, 'id': str(uuid.uuid4()),
                                                                        'sequence': 1}]})
    report = import_legacy(str(other), str(q.queue))
    assert reasons(report['projects']) == {P1: COLLISION['projects']}
    assert report['receipts']['listed'] == 1 and report['receipts']['imported'] == [imported[0], imported[2]]



@needs_node
def test_a_record_the_node_host_changes_after_an_import_is_refused_by_the_next_run(node_q, tmp_path, capsys):
    """Another run adds what the Node host created since; a project it changed since is a collision, and the
    workspace keeps the copy of the first run. The report says so while a Node host still serves Q."""
    q = fresh(tmp_path, node_q)
    workspace = tmp_path / 'W'
    assert succeeded(import_legacy(str(workspace), str(q.queue)))
    copy = digest_tree(workspace / 'projects' / P1)
    revision = json.loads((q.queue / 'projects' / P1 / 'project.json').read_text(encoding='utf-8'))['revision']
    scratch = tmp_path / 'node'
    scratch.mkdir()
    steps = [['patch', P1, {'revision': revision, 'title': 'Renamed by the Node host'}],
             ['create', {'title': 'Created by the Node host', 'owner_name': 'R'}]]
    rows = run_projects('store', [{'id': 'n', 'directory': str(q.queue / 'projects'), 'keys': q.keys,
                                   'prefix': '0b0b0000', 'steps': steps}], scratch)['by_id']['n']['records']
    assert all(row['ok'] for row in rows), rows
    created = jsjson.parse(rows[1]['value'])['project']['id']
    (q.queue / 'worker.lock').write_text(json.dumps({'pid': os.getpid(), 'token': 'x'}))
    report = import_legacy(str(workspace), str(q.queue))
    assert report['projects']['imported'] == [created] and reasons(report['projects']) == {P1: COLLISION['projects']}
    assert report['projects']['present'] == [P2, CRAFTED] and not succeeded(report)
    assert digest_tree(workspace / 'projects' / P1) == copy
    text = describe(report)
    assert f'The Node host (PID {os.getpid()}) still serves this queue directory; stop it before importing.' in text
    assert 'a project or study the Node host changes after this run is refused then' in text
    assert f'project {P1}: {COLLISION["projects"]}' in text
    assert cli.main(['workspace', 'import-legacy', str(workspace), '--queue-directory', str(q.queue)]) == 1
    assert COLLISION['projects'] in capsys.readouterr().out

def _task(n: int, created: str, *, status: str = 'completed', cached: bool = False, key: str | None = None) -> dict:
    task = {'id': str(uuid.UUID(int=n, version=4)), 'sequence': n, 'kind': 'source-reception',
            'key': key or f'{n:064x}', 'request': {'record_id': '9' * 64, 'mode': 'cross_region'}, 'status': status,
            'created_at': created, 'progress': 1 if status == 'completed' else 0, 'cached': cached,
            'catalog': {'protocol': 'source-reception/2'}}
    if status == 'completed':
        task.update({'finished_at': created, 'message': 'done'})
    return task


def _at(day: str, n: int) -> str:
    return f'{day}T{n // 3600:02d}:{n // 60 % 60:02d}:{n % 60:02d}.000Z'


def _workspace_with(path: Path, tasks: list, boot: str = 'boot-before') -> None:
    Workspace.open(str(path)).close()
    records.atomic_json(str(path / STATE / 'queue.json'), {'schema': 'eeglayoutlab-queue/1', 'sequence': len(tasks),
                                                           'boot_id': boot, 'tasks': tasks})


@needs_node
def test_receipts_join_the_workspace_queue_in_creation_order(node_q, tmp_path):
    q = fresh(tmp_path, node_q)
    by_id = {task['id']: task for task in node_tasks(q)}
    imported = expected_receipts(list(by_id.values()))
    times = [by_id[id]['created_at'] for id in imported]
    assert times == sorted(times) and len(set(times)) == 3
    middle = times[1]
    own = [_task(1, '2026-11-24T00:00:00.000Z'), _task(2, middle), _task(3, '2026-11-26T00:00:00.000Z'),
           _task(4, '2026-11-26T01:00:00.000Z', status='queued')]
    workspace = tmp_path / 'W'
    _workspace_with(workspace, own)
    report = import_legacy(str(workspace), str(q.queue))
    assert report['receipts']['imported'] == imported
    state = workspace_queue_file(workspace)
    order = [own[0]['id'], imported[0], own[1]['id'], imported[1], imported[2], own[2]['id'], own[3]['id']]
    assert [task['id'] for task in state['tasks']] == order                 # a tie keeps the workspace's first
    assert [task['sequence'] for task in state['tasks']] == list(range(1, 8)) and state['sequence'] == 7
    assert state['boot_id'] == 'boot-before'
    sequence, tasks, _ = workspace_queue._check_state(state)
    assert sequence == 7 and len(tasks) == 7

    async def listed() -> list:
        queue = WorkspaceQueue(str(workspace / STATE), {}, boot_id=lambda: 'boot-before')
        try:
            return [view['id'] for view in queue.records()['records']]
        finally:
            queue.dispose()
    assert asyncio.run(listed()) == [own[2]['id'], imported[2], imported[1], own[1]['id'], imported[0], own[0]['id']]


@needs_node
def test_the_workspace_queue_retention_applies_to_imported_receipts(node_q, tmp_path):
    q = fresh(tmp_path, node_q)
    by_id = {task['id']: task for task in node_tasks(q)}
    imported = expected_receipts(list(by_id.values()))
    computed = [id for id in imported if not by_id[id]['cached']]
    assert len(computed) == 1
    later = [_task(n, _at('2026-12-01', n)) for n in range(1, 1001)]
    workspace = tmp_path / 'W'
    _workspace_with(workspace, later)
    report = import_legacy(str(workspace), str(q.queue))
    assert report['receipts']['retention'] == 1 and report['receipts']['workspace_retention'] == 0
    assert report['receipts']['imported'] == [id for id in imported if id not in computed]
    assert "1 beyond the workspace queue's retention" in describe(report)
    earlier = [_task(n, _at('2026-11-01', n)) for n in range(1, 1001)]
    other = tmp_path / 'W2'
    _workspace_with(other, earlier)
    report = import_legacy(str(other), str(q.queue))
    assert report['receipts']['retention'] == 0 and report['receipts']['workspace_retention'] == 1
    tasks = workspace_queue_file(other)['tasks']
    assert len(tasks) == 1002 and tasks[0]['id'] == earlier[1]['id']
    full = tmp_path / 'W3'
    _workspace_with(full, [_task(n, _at('2026-12-01', n), cached=n > 1000)
                           for n in range(1, 1301)])
    queue_bytes = (full / STATE / 'queue.json').read_bytes()
    report = import_legacy(str(full), str(q.queue))
    assert report['receipts']['imported'] == [] and report['receipts']['retention'] == 3
    assert (full / STATE / 'queue.json').read_bytes() == queue_bytes  # nothing to add: not written


@needs_node
def test_an_unreadable_workspace_queue_is_kept_and_no_receipt_imported(node_q, tmp_path):
    q = fresh(tmp_path, node_q)
    workspace = tmp_path / 'W'
    Workspace.open(str(workspace)).close()
    for text in (b'{', b'{"schema": "other"}', b'\xff'):
        (workspace / STATE / 'queue.json').write_bytes(text)
        report = import_legacy(str(workspace), str(q.queue))
        assert (workspace / STATE / 'queue.json').read_bytes() == text
        [row] = report['receipts']['refused']
        assert row['id'] == 'workspace queue' and row['reason'].startswith(
            f"The workspace queue {workspace / STATE / 'queue.json'} cannot be read (")
        assert row['reason'].endswith('); it was kept unchanged.')
        assert report['receipts']['imported'] == []
    assert report['projects']['present'] == PROJECTS


# --- Where the import may run ------------------------------------------------------------------------------------

def test_a_served_workspace_is_refused(tmp_path):
    queue = tmp_path / 'Q'
    (queue / 'projects').mkdir(parents=True)
    workspace = tmp_path / 'W'
    served = Workspace.open(str(workspace))
    try:
        served.write_runtime(41234, 'a' * 64, str(tmp_path))
        with pytest.raises(WorkspaceInUse):
            import_legacy(str(workspace), str(queue))
        assert not (workspace / 'projects').exists()
        assert cli.main(['workspace', 'import-legacy', str(workspace), '--queue-directory', str(queue)]) == 1
    finally:
        served.close()


def test_the_workspace_and_the_queue_directory_must_be_apart(tmp_path):
    queue = tmp_path / 'Q'
    (queue / 'projects').mkdir(parents=True)
    (tmp_path / 'file').write_bytes(b'')
    (tmp_path / 'link').symlink_to(queue, target_is_directory=True)
    before = digest_tree(tmp_path)
    upper = Path(str(queue).upper()) if os.path.exists(str(queue).upper()) else queue
    cases = [(queue, queue), (queue / 'W', queue), (queue / 'projects' / 'W', queue), (tmp_path / 'link' / 'W', queue),
             (upper / 'W', queue), (tmp_path, queue), (tmp_path / 'W', tmp_path / 'missing'),
             (tmp_path / 'W', tmp_path / 'file')]
    for workspace, directory in cases:
        with pytest.raises(LegacyImportError):
            import_legacy(str(workspace), str(directory))
        with pytest.raises(LegacyImportError):
            import_legacy(str(workspace), str(directory), dry_run=True)
    assert digest_tree(tmp_path) == before



def test_serve_refuses_the_node_queue_directory_as_its_workspace(tmp_path, monkeypatch, capsys):
    """``eeglayoutlab serve`` writes its workspace (its marker, state, projects and studies), so Node's queue
    directory of the root, or a directory inside it, is refused before anything is written."""
    root = tmp_path / 'R'
    queue = root / 'results' / 'web-service'
    (queue / 'projects').mkdir(parents=True)
    (tmp_path / 'link').symlink_to(queue, target_is_directory=True)
    before = digest_tree(root)
    monkeypatch.setattr(cli.importlib.util, 'find_spec', lambda name: object())  # the service extra is not needed
    monkeypatch.setattr(cli, '_run', lambda *args: pytest.fail('the service started'))
    for workspace in (queue, queue / 'W', queue / 'projects', tmp_path / 'link' / 'W'):
        assert cli.main(['serve', str(workspace), '--root', str(root), '--no-browser']) == 2
        assert f"is the Node host's queue directory {queue} or inside it" in capsys.readouterr().err
    assert digest_tree(root) == before
    started: list = []
    monkeypatch.setattr(cli, '_run', lambda *args: started.append(args) or 0)
    assert cli.main(['serve', str(tmp_path / 'W'), '--root', str(root), '--no-browser']) == 0 and started

@needs_node
def test_a_dry_run_reports_and_writes_nothing(node_q, tmp_path):
    q = fresh(tmp_path, node_q)
    before = digest_tree(q.root)
    workspace = tmp_path / 'W'
    dry = import_legacy(str(workspace), str(q.queue), dry_run=True)
    assert not workspace.exists() and digest_tree(q.root) == before
    real = import_legacy(str(workspace), str(q.queue))
    for name in ('projects', 'studies', 'receipts'):
        assert dry[name] == real[name]
    assert describe(dry).startswith('Dry run: nothing was written.')
    written = digest_tree(workspace)
    again = import_legacy(str(workspace), str(q.queue), dry_run=True)
    assert again['projects']['present'] == PROJECTS and digest_tree(workspace) == written



@needs_node
def test_a_dry_run_through_a_linked_workspace_path_reports_what_the_import_does(node_q, tmp_path):
    """The dry run resolves the workspace's directories as the import does: a link above the workspace (``/tmp`` on
    macOS, a linked home) is followed, not refused."""
    q = fresh(tmp_path, node_q)
    (tmp_path / 'real').mkdir()
    (tmp_path / 'link').symlink_to(tmp_path / 'real', target_is_directory=True)
    workspace = tmp_path / 'link' / 'W'
    (workspace / 'projects').mkdir(parents=True)  # as a served workspace has it
    dry = import_legacy(str(workspace), str(q.queue), dry_run=True)
    real = import_legacy(str(workspace), str(q.queue))
    assert succeeded(dry), describe(dry)
    for name in ('projects', 'studies', 'receipts'):
        assert dry[name] == real[name]
    again = import_legacy(str(workspace), str(q.queue), dry_run=True)
    assert succeeded(again) and again['projects']['present'] == PROJECTS and again['studies']['present'] == STUDIES

def test_a_node_host_still_serving_the_queue_directory_is_named(tmp_path):
    queue = tmp_path / 'Q'
    queue.mkdir()
    (queue / 'worker.lock').write_text(json.dumps({'pid': os.getpid(), 'token': 'x'}))
    report = import_legacy(str(tmp_path / 'W'), str(queue), dry_run=True)
    assert report['node_host_pid'] == os.getpid()
    assert f'The Node host (PID {os.getpid()}) still serves this queue directory' in describe(report)
    finished = subprocess.run([sys.executable, '-c', 'import os; print(os.getpid())'], capture_output=True, text=True,
                              check=True)
    for text in (json.dumps({'pid': int(finished.stdout)}), '{"pid": true}', '[]', 'x'):
        (queue / 'worker.lock').write_text(text)
        assert import_legacy(str(tmp_path / 'W'), str(queue), dry_run=True)['node_host_pid'] is None
    assert sorted(os.listdir(queue)) == ['worker.lock'] and not (tmp_path / 'W').exists()


def test_read_only_files_never_create_a_directory(tmp_path):
    files = legacy_import._ReadOnlyFiles(str(tmp_path / 'missing' / 'projects'))
    with pytest.raises(OSError):
        files.ready()
    assert os.listdir(tmp_path) == []


# --- A failure midway --------------------------------------------------------------------------------------------

def _staging(workspace: Path) -> list:
    return [name for name in os.listdir(workspace / STATE) if name.startswith('legacy-import-')]


@needs_node
def test_a_failed_publish_leaves_whole_records_and_a_second_run_completes(node_q, tmp_path, monkeypatch):
    q = fresh(tmp_path, node_q)
    reference = tmp_path / 'reference'
    import_legacy(str(reference), str(q.queue))
    workspace = tmp_path / 'W'
    publish, calls = legacy_import._publish, []

    def failing(staged: str, target: str) -> None:
        calls.append(target)
        if len(calls) == 2:
            raise OSError(28, 'No space left on device')
        publish(staged, target)
    monkeypatch.setattr(legacy_import, '_publish', failing)
    report = import_legacy(str(workspace), str(q.queue))
    assert report['failure'].startswith(f'project {P2}: ') and 'No space left on device' in report['failure']
    assert not succeeded(report)
    assert report['projects']['imported'] == [P1] and report['studies']['imported'] == []
    assert os.listdir(workspace / 'projects') == [P1] and not (workspace / 'studies').exists()
    assert tree(workspace / 'projects' / P1) == tree(q.queue / 'projects' / P1)
    assert _staging(workspace) == [] and not (workspace / STATE / 'queue.json').exists()
    assert 'run the command again' in describe(report)
    monkeypatch.setattr(legacy_import, '_publish', publish)
    second = import_legacy(str(workspace), str(q.queue))
    assert succeeded(second) and second['projects']['present'] == [P1]
    for kind in ('projects', 'studies'):
        assert tree(workspace / kind) == tree(reference / kind)
    assert [task['id'] for task in workspace_queue_file(workspace)['tasks']] == \
        [task['id'] for task in workspace_queue_file(reference)['tasks']]


@needs_node
def test_a_crash_while_staging_leaves_nothing_a_store_reads(node_q, tmp_path, monkeypatch):
    q = fresh(tmp_path, node_q)
    workspace = tmp_path / 'W'
    write, written = legacy_import._write_new, []

    def crashing(path: str, data: bytes) -> None:
        written.append(path)
        if len(written) == 3:
            raise KeyboardInterrupt  # the process stops here
        write(path, data)
    monkeypatch.setattr(legacy_import, '_write_new', crashing)
    monkeypatch.setattr(legacy_import._Staging, 'remove', lambda self: None)  # a crash removes nothing
    with pytest.raises(KeyboardInterrupt):
        import_legacy(str(workspace), str(q.queue))
    assert len(_staging(workspace)) == 1 and os.listdir(workspace / 'projects') == []
    monkeypatch.undo()
    report = import_legacy(str(workspace), str(q.queue))
    assert succeeded(report) and report['projects']['imported'] == PROJECTS and _staging(workspace) == []


@needs_node
def test_a_failed_queue_write_keeps_the_old_queue_and_a_second_run_completes(node_q, tmp_path, monkeypatch):
    q = fresh(tmp_path, node_q)
    workspace = tmp_path / 'W'
    _workspace_with(workspace, [_task(1, '2026-11-24T00:00:00.000Z')])
    queue_bytes = (workspace / STATE / 'queue.json').read_bytes()

    def failing(path: str, value: dict) -> None:
        raise OSError(28, 'No space left on device')
    monkeypatch.setattr(legacy_import, '_write_queue', failing)
    report = import_legacy(str(workspace), str(q.queue))
    assert report['failure'].startswith('workspace queue: ') and 'No space left on device' in report['failure']
    assert report['receipts']['imported'] == [] and report['projects']['imported'] == PROJECTS
    assert (workspace / STATE / 'queue.json').read_bytes() == queue_bytes
    monkeypatch.undo()
    second = import_legacy(str(workspace), str(q.queue))
    assert succeeded(second) and len(second['receipts']['imported']) == 3
    assert len(workspace_queue_file(workspace)['tasks']) == 4


# --- The command -------------------------------------------------------------------------------------------------

@needs_node
def test_the_command_imports_reports_and_exits(node_q, tmp_path, capsys):
    q = fresh(tmp_path, node_q)
    workspace = tmp_path / 'W'
    command = ['workspace', 'import-legacy', str(workspace), '--root', str(q.root)]
    assert cli.main([*command, '--dry-run']) == 0
    assert 'Dry run: nothing was written.' in capsys.readouterr().out and not workspace.exists()
    assert cli.main(command) == 0                                       # the default Q: R/results/web-service
    out = capsys.readouterr().out
    assert '3 projects imported' in out and '2 studies imported' in out and '3 signal records imported' in out
    assert '3 of them have no stored result' in out
    assert cli.main(command) == 0
    assert '3 already in the workspace' in capsys.readouterr().out
    _flip(_snapshots(q.queue / 'studies' / S1)[0])
    other = tmp_path / 'W2'
    assert cli.main(['workspace', 'import-legacy', str(other), '--queue-directory', str(q.queue)]) == 1
    assert f'study {S1}: Study snapshot checksum mismatch.' in capsys.readouterr().out
    assert cli.main(['workspace', 'import-legacy', str(q.queue / 'W'), '--queue-directory', str(q.queue)]) == 2
    assert 'inside it' in capsys.readouterr().err
    assert cli.main(['workspace', 'import-legacy', str(other), '--queue-directory', str(tmp_path / 'none')]) == 2
    assert cli.main(['workspace', 'import-legacy', str(other), '--root', str(tmp_path / 'none')]) == 2
    assert not (q.queue / 'W').exists()


def test_the_command_needs_a_workspace_without_a_terminal(tmp_path, monkeypatch, capsys):
    queue = tmp_path / 'Q'
    queue.mkdir()
    (tmp_path / 'busy').mkdir()
    (tmp_path / 'busy' / 'file').write_bytes(b'')
    monkeypatch.chdir(tmp_path / 'busy')
    monkeypatch.setattr('sys.stdin', None)
    assert cli.main(['workspace', 'import-legacy', '--queue-directory', str(queue)]) == 2
    assert 'eeglayoutlab workspace import-legacy <directory>' in capsys.readouterr().err


# --- The installation's queue directory --------------------------------------------------------------------------

REAL_ROOT = os.environ.get('EEG_KEY_PARITY_ROOT')


@pytest.mark.data_bundle
@pytest.mark.skipif(not REAL_ROOT, reason='set EEG_KEY_PARITY_ROOT to an installation')
@needs_node
def test_the_installations_queue_directory_imports_as_node_lists_it(tmp_path):
    """The installation's Q is only read: its ``queue.json`` (which its Node host may be rewriting) and any
    ``projects`` or ``studies`` are copied to ``tmp_path`` first, and the import, Node's ``records`` and Node's
    project reads run on the copy. Every imported signal record lists as Node lists it for one owner of all, and every
    Node-written project there reads back unchanged."""
    real = Path(REAL_ROOT) / 'results' / 'web-service'
    if not (real / 'queue.json').is_file():
        pytest.skip(f'{real} has no queue.json')
    queue = tmp_path / 'Q'
    queue.mkdir()
    shutil.copyfile(real / 'queue.json', queue / 'queue.json')
    for kind in ('projects', 'studies'):
        if (real / kind).is_dir() and not (real / kind).is_symlink():
            shutil.copytree(real / kind, queue / kind, symlinks=True)
    before = digest_tree(queue)
    workspace = tmp_path / 'W'
    report = import_legacy(str(workspace), str(queue), root=REAL_ROOT)
    assert digest_tree(queue) == before
    assert report['failure'] is None and report['receipts']['refused'] == []
    scratch = tmp_path / 'node'
    scratch.mkdir()
    every = jsjson.parse(node_records(queue / 'queue.json', scratch)['all'])

    async def workspace_records() -> dict:
        state = WorkspaceQueue(str(workspace / STATE), {}, boot_id=lambda: 'legacy-tests')
        try:
            return state.records()
        finally:
            state.dispose()
    python = asyncio.run(workspace_records())
    kept = set(report['receipts']['imported'])
    assert jsjson.stringify(python['records']) == jsjson.stringify(
        [view for view in every['records'] if view['id'] in kept])
    assert len(kept) + report['receipts']['retention'] == len(every['records'])
    ids = sorted(name for name in os.listdir(queue / 'projects')) if (queue / 'projects').is_dir() else []
    if ids:
        case = {'id': 'real', 'directory': str(queue / 'projects'), 'projects': ids}
        assert node_read(run_projects('read', [case], scratch)['by_id']['real']) == python_read(
            {**case, 'directory': str(workspace / 'projects')})
    assert stat.S_ISREG((real / 'queue.json').lstat().st_mode)
