"""Research deliveries (``eeglayoutlab.server.delivery``, phase 2 slice 9): Node's ``delivery/research-bundle.mjs``
and ``delivery/project-delivery.mjs``.

- Ports: the 6 sites of check-research-delivery.mjs and the 4 of check-project-delivery.mjs. Their project store is
  a stand-in over plain ``research-project/1`` records (``SavedProjects``, Node's ``readSnapshots`` contract); the
  owner, viewer and revoked credentials are one local reader (R5).
- Parity with Node's own code (``parity/delivery.mjs``): built deliveries (the JSON text and the input after the
  call) or refusals (status and message; a ``TypeError`` or ``SyntaxError`` by name) for hand-written and random
  inputs, near the size bounds too; the verifier's acceptance and messages for valid deliveries changed at random,
  with and without recomputed checksums; the comparison link's ``URLSearchParams``; and ``deliveryVersions`` and
  ``runtimeLockPath`` on synthetic roots (the host files differ by design: Node's name ``webapp/``, ours
  ``HOST_FILES``).
- ``tests/service/fixtures/delivery``: the deliveries that check-research-delivery-reader.mjs (``reader*.json``) and
  check-delivery-upload-contract.mjs (``upload-*.json``) read instead of building them with Node's builder,
  ``JSON.stringify(bundle, null, 2) + '\\n'``. They must be what ``fixture_texts()`` builds with the Python builder
  (``PYTHONPATH=src:tests python -m tests.service.test_delivery`` writes them again) and what Node's builder makes
  with the checks' original fixture code; the upload check's hash-valid mutations of a base fixture equal Node's
  builds of the mutated results.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import random
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest

from .key_parity_support import NODE_ENV, needs_node, require

require('pydantic')

from eeglayoutlab.jobs.identity import JSTypeError  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402
from eeglayoutlab.server import delivery as D  # noqa: E402
from eeglayoutlab.server.workspace_files import ProjectError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/delivery.mjs'
FIXTURES = ROOT / 'tests/service/fixtures/delivery'
KINDS = ('layout', 'editor', 'source')
DATE = '2026-11-14T12:00:00.000Z'
UUIDS = [f'5d5d0000-0000-4000-8000-{k:012d}' for k in range(1, 40)]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def clone(value: Any) -> Any:
    return jsjson.parse(jsjson.stringify(value))


def pretty(value: Any, indent: str = '') -> str:
    """``JSON.stringify(value, null, 2)``."""
    if isinstance(value, dict):
        if not value:
            return '{}'
        inner = indent + '  '
        keys = D._keys(value)
        return '{\n' + ',\n'.join(f'{inner}{jsjson.quote(key)}: {pretty(value[key], inner)}' for key in keys) + \
            '\n' + indent + '}'
    if isinstance(value, list):
        if not value:
            return '[]'
        inner = indent + '  '
        return '[\n' + ',\n'.join(inner + pretty(item, inner) for item in value) + '\n' + indent + ']'
    return jsjson.stringify(value)


def run(coroutine, timeout: float = 30):
    return asyncio.run(asyncio.wait_for(coroutine, timeout))


# --- check-research-delivery.mjs -------------------------------------------------------------------------------------

def research_fixture(ids: list[str] | None = None) -> dict:
    """The check's ``fixture()``: three entries (layout, editor, source) whose payloads hold awkward numbers, in a
    project that carries credentials the delivery must leave out. The project lists the same entry objects."""
    ids = ids or [str(__import__('uuid').uuid4()) for _ in range(4)]
    entries = []
    for i, kind in enumerate(KINDS):
        payload = {'request': {'seed': 2026, 'source_index': 2}, 'coordinates': [[-112.31415926535898, 1.42e-14, 0]],
                   'values': [1 / 3, -1e-18, 1.0000000000000002], 'schema': f'original-{kind}/1'}
        snapshot = {'schema': 'research-project-snapshot/1', 'kind': kind, 'record_id': str(i + 1) * 64,
                    'payload': payload}
        snapshot_json = jsjson.stringify(snapshot)
        entry = {'id': ids[i], 'kind': kind, 'record_id': snapshot['record_id'], 'title': f'{kind} result',
                 'notes': 'Saved reason', 'created_at': '2026-11-13T12:00:00Z', 'snapshot_sha256': sha(snapshot_json),
                 'snapshot_bytes': len(snapshot_json.encode('utf-8')), 'summary': {'protocol': payload['schema']}}
        entries.append({'entry': entry, 'snapshot': snapshot, 'snapshot_json': snapshot_json})
    project = {'schema': 'research-project/1', 'id': ids[3], 'title': 'Research study', 'owner_name': 'Researcher',
               'notes': 'Study notes', 'revision': 3, 'created_at': '2026-11-13T12:00:00Z',
               'updated_at': '2026-11-13T12:01:00Z', 'entries': [value['entry'] for value in entries],
               'owner_key_hash': 'private credential', 'viewer_key_hash': 'private share'}
    return {'project': project, 'entries': entries}


def test_one_research_delivery_retains_exact_snapshot_bytes_and_every_scientific_number():
    source = research_fixture()
    original = copy.deepcopy(source)
    bundle = D.build_research_delivery(source, {'application_version': '0.1.2', 'data_manifest_sha256': 'a' * 64,
                                                'env': 'private environment'})
    assert D.validate_research_delivery(bundle) is True
    assert jsjson.stringify(source) == jsjson.stringify(original), 'Export mutated a scientific input or project.'
    assert (len(bundle['records']), len(bundle['files'])) == (3, 4)
    for item in source['entries']:
        file = next(value for value in bundle['files'] if value['path'] == f"records/{item['entry']['id']}.json")
        assert file['content'] == item['snapshot_json']
        assert sha(file['content']) == item['entry']['snapshot_sha256']
        payload = jsjson.parse(file['content'])['payload']
        assert jsjson.stringify(payload) == jsjson.stringify(item['snapshot']['payload'])
    text = D.delivery_json(bundle)
    assert text == jsjson.stringify(bundle)
    for secret in ('owner_key_hash', 'viewer_key_hash', 'private credential', 'private share', 'private environment'):
        assert secret not in text
    assert bundle['scientific_results_recomputed'] is False
    assert re.search('saved snapshots describe the original calculation', bundle['files'][0]['content'])


def test_export_refuses_changed_scientific_text_missing_entries_and_oversized_delivery():
    source = research_fixture()
    source['entries'][0]['snapshot_json'] += ' '
    with pytest.raises(ProjectError, match='checksum'):
        D.build_research_delivery(source)
    missing = research_fixture()
    missing['entries'].pop()
    with pytest.raises(ProjectError, match='incomplete'):
        D.build_research_delivery(missing)
    with pytest.raises(ProjectError) as caught:
        D.build_research_delivery(research_fixture(), {}, max_bytes=100)
    assert caught.value.status == 413


def test_identity_substitution_and_duplicate_project_entries_cannot_pass_delivery():
    source = research_fixture()
    source['entries'][0]['entry']['record_id'] = 'f' * 64
    with pytest.raises(ProjectError, match='identity'):
        D.build_research_delivery(source)
    duplicate = research_fixture()
    duplicate['entries'][1] = duplicate['entries'][0]
    with pytest.raises(ProjectError, match='identity'):
        D.build_research_delivery(duplicate)


def test_verification_detects_edits_to_payload_project_annotations_host_version_and_manifest():
    original = D.build_research_delivery(research_fixture())

    def content(bundle): bundle['files'][1]['content'] += ' '
    def title(bundle): bundle['project']['title'] = 'Changed after export'
    def notes(bundle): bundle['records'][0]['notes'] = 'Changed after export'
    def version(bundle): bundle['host']['application_version'] = 'different'
    def path(bundle): bundle['files'][1]['path'] = '../outside.json'

    for change in (content, title, notes, version, path):
        bundle = clone(original)
        change(bundle)
        with pytest.raises(ProjectError, match='integrity'):
            D.validate_research_delivery(bundle)


def test_empty_projects_yield_a_valid_readable_handoff_and_retain_saved_workflow_metadata():
    source = research_fixture()
    source['entries'] = []
    source['project']['entries'] = []
    source['project']['workflow'] = {'comparison_href': '/decision?ar=90'}
    bundle = D.build_research_delivery(source)
    assert D.validate_research_delivery(bundle) is True
    assert len(bundle['files']) == 1
    assert bundle['project']['workflow'] == source['project']['workflow']
    assert '\n- ar: 90\n' in bundle['files'][0]['content']


def rehash_manifest(bundle: dict) -> None:
    metadata = {key: value for key, value in bundle.items() if key not in ('manifest_sha256', 'files')}
    bundle['manifest_sha256'] = sha(jsjson.stringify(
        {**metadata, 'files': [{key: value for key, value in file.items() if key != 'content'}
                               for file in bundle['files']]}))


def test_a_recomputed_checksum_does_not_make_contradictory_record_paths_or_headers_valid():
    original = D.build_research_delivery(research_fixture())
    changes = [
        (lambda bundle: bundle['records'][0].update(id=str(__import__('uuid').uuid4())), D.RECORD_MISMATCH),
        (lambda bundle: bundle['records'][0].update(kind='invented'), D.RECORD_MISMATCH),
        (lambda bundle: bundle['project'].update(id='../outside'), D.UNSUPPORTED),
        (lambda bundle: bundle['host'].update(data_manifest_sha256='missing'), D.UNSUPPORTED),
        (lambda bundle: bundle.update(exported_at='not a timestamp'), D.UNSUPPORTED),
    ]
    for change, message in changes:
        bundle = clone(original)
        change(bundle)
        rehash_manifest(bundle)
        with pytest.raises(ProjectError) as caught:
            D.validate_research_delivery(bundle)
        assert (caught.value.message, caught.value.status) == (message, 409)


# --- check-project-delivery.mjs --------------------------------------------------------------------------------------

class SavedProjects:
    """A stand-in for the workspace project store's ``read_snapshots`` (Node's ``ProjectStore.readSnapshots``): one
    ``research-project/1`` record and its snapshot texts. A project over ``max_bytes`` is refused before a snapshot
    is read; the project is returned as the store presents it (``publicProject``: no credentials, a workflow)."""

    def __init__(self, record: dict, snapshots: dict[str, str]):
        self.record, self.snapshots, self.reads = record, snapshots, []

    async def read_snapshots(self, project_id: str, *, max_bytes: int) -> dict:
        self.reads.append((project_id, max_bytes))
        if project_id != self.record['id']:
            raise ProjectError('Project not found.', 404)
        if sum(entry['snapshot_bytes'] for entry in self.record['entries']) > max_bytes:
            raise ProjectError('Project export exceeds the size limit.', 413)
        project = {key: self.record[key] for key in ('schema', 'id', 'title', 'owner_name', 'notes', 'revision',
                                                       'created_at', 'updated_at', 'entries')}
        project['workflow'] = self.record.get('workflow', {'reference_entry_id': None, 'candidate_entry_id': None,
                                                           'comparison_href': None})
        entries = [{'entry': clone(entry), 'snapshot': jsjson.parse(self.snapshots[entry['snapshot_sha256']]),
                    'snapshot_json': self.snapshots[entry['snapshot_sha256']]} for entry in self.record['entries']]
        return {'project': clone(project), 'role': 'owner', 'entries': entries}


def saved_source_project() -> tuple[SavedProjects, dict]:
    """check-project-delivery.mjs's project: created, then one signal snapshot attached (revision 2)."""
    snapshot = {'schema': 'research-project-snapshot/1', 'kind': 'source', 'record_id': 'a' * 64,
                'payload': {'request': {'seed': 2026}, 'values': [1.42e-14, -1e-20]}}
    text = jsjson.stringify(snapshot)
    entry = {'id': UUIDS[1], 'kind': 'source', 'record_id': 'a' * 64, 'title': 'source aaaaaaaa', 'notes': '',
             'created_at': '2026-11-25T00:00:01.000Z', 'snapshot_sha256': sha(text),
             'snapshot_bytes': len(text.encode('utf-8')), 'summary': {'protocol': 'source-reception/2'}}
    record = {'schema': 'research-project/1', 'id': UUIDS[0], 'title': 'Delivery study', 'owner_name': 'Researcher',
              'notes': '', 'revision': 2, 'created_at': '2026-11-25T00:00:00.000Z',
              'updated_at': '2026-11-25T00:00:01.000Z', 'owner_key_hash': sha('unused key'), 'viewer_key_hash': None,
              'entries': [entry]}
    return SavedProjects(record, {entry['snapshot_sha256']: text}), snapshot


def test_project_delivery_serves_complete_archives_of_the_workspace_project():
    """Node's owner and viewer exports become one local reader's; revoked access is dropped (R5). The store is a
    stand-in shaped as ``research-project/1``."""
    store, snapshot = saved_source_project()

    async def scenario():
        async def versions():
            return {'application_version': '0.1.2'}

        delivery = D.ProjectDelivery(store, versions=versions)
        first = await delivery.export(UUIDS[0])
        assert D.validate_research_delivery(first) is True
        assert jsjson.stringify(jsjson.parse(first['files'][1]['content'])['payload']) == \
            jsjson.stringify(snapshot['payload'])
        again = await delivery.export(UUIDS[0])
        assert again['files'][1] == first['files'][1]
        assert store.reads == [(UUIDS[0], D.MAX_DELIVERY_BYTES)] * 2
        assert first['host'] == {'application_version': '0.1.2'}
        assert 'owner_key_hash' not in D.delivery_json(first)
        assert first['project']['workflow']['comparison_href'] is None
        with pytest.raises(ProjectError) as caught:
            await delivery.export(UUIDS[2])
        assert caught.value.status == 404 and not delivery.active

    run(scenario())


def test_delivery_limits_memory_and_concurrent_exports_then_recovers_from_a_failed_attempt():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class Pending:
            async def read_snapshots(self, project_id, *, max_bytes):
                entered.set()
                await release.wait()
                raise RuntimeError('Archive unavailable')

        delivery = D.ProjectDelivery(Pending())
        first = asyncio.ensure_future(delivery.export('id'))
        await entered.wait()
        with pytest.raises(ProjectError) as caught:
            await delivery.export('id')
        assert (caught.value.status, caught.value.message) == (429, D.BUSY)
        release.set()
        with pytest.raises(RuntimeError, match='Archive unavailable'):
            await first
        assert delivery.active is False

        class Limited:
            async def read_snapshots(self, project_id, *, max_bytes):
                assert max_bytes == 100
                raise ProjectError('Size limit', 413)

        with pytest.raises(ProjectError) as caught:
            await D.ProjectDelivery(Limited(), maximum_bytes=100).export('id')
        assert caught.value.status == 413

    run(scenario())


def write_identities(root: Path, data: Any = None, runtime: Any = None) -> None:
    (root / 'data').mkdir(parents=True, exist_ok=True)
    (root / 'configs/runtime').mkdir(parents=True, exist_ok=True)
    (root / 'data/manifest.json').write_text(jsjson.stringify(
        data or {'schema_version': 'eeglayoutlab-data-bundle/1', 'bundle_id': 'test-model-v1'}), encoding='utf-8')
    (root / 'configs/runtime/manifest.json').write_text(jsjson.stringify(
        runtime or {'schema': 'eeglayoutlab-runtime-lock/1'}), encoding='utf-8')


def test_delivery_versions_tell_host_bytes_from_the_data_and_runtime_lock_and_fail_without_identities(tmp_path):
    """check-project-delivery.mjs "delivery distinguishes current host bytes from the scientific data/runtime lock and
    fails on missing identities", with the default source root: this checkout's ``HOST_FILES``."""
    import tomllib

    root = tmp_path / 'root'
    write_identities(root)
    value = D.delivery_versions(str(root))
    assert value['data_bundle_id'] == 'test-model-v1'
    assert re.fullmatch('[a-f0-9]{64}', value['data_manifest_sha256'])
    assert value['data_manifest_sha256'] == hashlib.sha256((root / 'data/manifest.json').read_bytes()).hexdigest()
    lock = (root / 'configs/runtime/manifest.json').read_bytes()
    assert value['runtime_lock_sha256'] == hashlib.sha256(lock).hexdigest()
    assert all(not row['path'].startswith('/') and re.fullmatch('[a-f0-9]{64}', row['sha256'])
               for row in value['source_files'])
    # The Python host: pyproject.toml and the service's project and delivery modules, by their bytes in this checkout.
    assert [row['path'] for row in value['source_files']] == list(D.HOST_FILES)
    for row in value['source_files']:
        assert row['sha256'] == hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest()
    assert value['application_version'] == tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    (root / 'data/manifest.json').unlink()
    with pytest.raises(ProjectError) as caught:
        D.delivery_versions(str(root))
    assert caught.value.status == 503 and str(root) not in caught.value.message


def test_an_installed_package_describes_itself_without_a_checkout(tmp_path):
    """The installed form of design 0002 (packaging/conda-forge): ``site-packages/eeglayoutlab`` with its
    distribution's metadata, no ``pyproject.toml`` around it, and R elsewhere. The version is the distribution's, and
    ``source_files`` hash the package's own modules, the same bytes as this checkout's (Node's equivalent works there:
    its host files are under R)."""
    import shutil
    import sys

    site = tmp_path / 'prefix/lib/python3.11/site-packages'
    shutil.copytree(ROOT / 'src/eeglayoutlab', site / 'eeglayoutlab', ignore=shutil.ignore_patterns('__pycache__'))
    (site / 'eeglayoutlab-9.8.7.dist-info').mkdir()
    (site / 'eeglayoutlab-9.8.7.dist-info/METADATA').write_text(
        'Metadata-Version: 2.1\nName: eeglayoutlab\nVersion: 9.8.7\n', encoding='utf-8')
    root = tmp_path / 'prefix/share/eeglayoutlab/root'
    write_identities(root)
    probe = ('import sys; sys.path.insert(0, sys.argv[1]); from eeglayoutlab.server import delivery; '
             'from eeglayoutlab.schemas import jsjson; '
             'assert delivery.__file__.startswith(sys.argv[1] + "/"), delivery.__file__; '
             'print(jsjson.stringify(delivery.delivery_versions(sys.argv[2])))')
    result = subprocess.run([sys.executable, '-I', '-B', '-c', probe, str(site), str(root)], capture_output=True,
                            text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    checkout = D.delivery_versions(str(root))
    assert jsjson.parse(result.stdout) == {**checkout, 'application_version': '9.8.7',
                                           'source_files': checkout['source_files'][1:]}
    assert [row['path'] for row in checkout['source_files'][1:]] == [
        path for path in D.HOST_FILES if path.startswith('src/eeglayoutlab/')]


def test_delivery_names_the_lock_of_the_managed_runtime_in_use(tmp_path):
    root = tmp_path / 'root'
    root.mkdir()
    assert D.runtime_lock_path(str(root)) == 'configs/runtime/manifest.json'
    (root / '.runtime/compute-linux-64/bin').mkdir(parents=True)
    (root / '.runtime/compute-linux-64/bin/python').write_text('fixture')
    assert D.runtime_lock_path(str(root)) == 'configs/runtime/manifest-linux-64.json'
    (root / '.runtime/simnibs-4.6.0/bin').mkdir(parents=True)
    (root / '.runtime/simnibs-4.6.0/bin/python').write_text('fixture')
    assert D.runtime_lock_path(str(root)) == 'configs/runtime/manifest.json'


def source_tree(source: Path, version: str = '0.2.0', pyproject: str | None = None) -> None:
    """A synthetic source root with Node's host files and ours (``HOST_FILES``)."""
    for path in ('webapp/package-lock.json', 'webapp/server/projects/store.mjs', 'webapp/server/projects/service.mjs',
                 'webapp/server/delivery/research-bundle.mjs', 'webapp/server/delivery/project-delivery.mjs',
                 *D.HOST_FILES[1:]):
        (source / path).parent.mkdir(parents=True, exist_ok=True)
        (source / path).write_text(f'// {path}\n')
    (source / 'webapp/package.json').write_text(jsjson.stringify({'name': 'webapp', 'version': version}))
    (source / 'pyproject.toml').write_text(pyproject if pyproject is not None else
                                           f'[project]\nname = "compact-eeg"\nversion = "{version}"\n')


def test_delivery_versions_need_the_python_host_version(tmp_path):
    root, source = tmp_path / 'root', tmp_path / 'source'
    write_identities(root)
    source_tree(source)
    assert D.delivery_versions(str(root), str(source))['application_version'] == '0.2.0'
    for pyproject in ('[project]\nname = "x"\n', '[project]\nversion = ""\n', 'version = "1"\n', 'project = 1\n',
                      '[project\n', '\ufeff[project]\nversion = "1"\n'.encode('utf-8').decode('latin-1')):
        source_tree(source, pyproject=pyproject)
        with pytest.raises(ProjectError) as caught:
            D.delivery_versions(str(root), str(source))
        assert (caught.value.status, caught.value.message) == (503, D.VERSIONS_UNAVAILABLE)
    source_tree(source)
    (source / D.HOST_FILES[-1]).unlink()
    with pytest.raises(ProjectError):
        D.delivery_versions(str(root), str(source))


# --- Parity with Node ------------------------------------------------------------------------------------------------

def run_driver(mode: str, cases: list[dict], scratch: Path) -> dict:
    spec_path, out_path = scratch / f'delivery-{mode}.json', scratch / f'delivery-{mode}-node.json'
    spec_path.write_text(jsjson.stringify({'mode': mode, 'cases': cases}), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV,
                   timeout=600)
    output = json.loads(out_path.read_text(encoding='utf-8'))
    output['by_id'] = {case['id']: case for case in output['cases']}
    return output


def outcome(call: Callable[[], dict]) -> dict:
    """A Python outcome in the driver's shape."""
    try:
        return {'ok': True, **call()}
    except ProjectError as error:
        return {'ok': False, 'name': 'Error', 'message': error.message, 'status': error.status, 'safe': True}
    except JSTypeError:
        return {'ok': False, 'name': 'TypeError', 'safe': False}
    except jsjson.JSONSyntaxError:
        return {'ok': False, 'name': 'SyntaxError', 'safe': False}


def assert_same(ours: dict, node: dict, case: Any) -> None:
    assert ours['ok'] == node['ok'], (case, ours, node)
    if not ours['ok']:
        assert (ours['name'], ours['safe']) == (node['name'], node['safe']), (case, ours, node)
        if ours['safe']:
            assert (ours['message'], ours['status']) == (node['message'], node['status']), (case, ours, node)
        return
    for key, value in ours.items():
        assert value == node[key], (case, key, ours, node)


ANNOTATION = {'schema': 'eeg-electrode-annotation/1', 'id': 'b' * 64, 'record_id': 'a' * 64, 'request_sha256': 'c' * 64,
              'electrode_names': [f'E{i}' for i in range(64)]}


def saved_input(rows: list[tuple], project: dict | None = None, pretty_text: bool = False) -> dict:
    """``{project, entries}`` of the given ``(kind, record_id, payload, extra snapshot members, entry members)``
    rows, with consistent checksums, ids ``UUIDS[1:]`` and the project ``UUIDS[0]``."""
    entries = []
    for index, (kind, record_id, payload, extra, members) in enumerate(rows):
        snapshot = {'schema': 'research-project-snapshot/1', 'kind': kind, 'record_id': record_id, 'payload': payload,
                    **extra}
        text = pretty(snapshot) + '\n' if pretty_text else jsjson.stringify(snapshot)
        entry = {'id': UUIDS[index + 1], 'kind': kind, 'record_id': record_id, 'title': f'{kind} {index}', 'notes': '',
                 'created_at': '2026-11-13T12:00:00Z', 'snapshot_sha256': D._hash(text),
                 'snapshot_bytes': len(D._utf8(text)), 'summary': {'protocol': f'{kind}-protocol/1'}, **members}
        entries.append({'entry': entry, 'snapshot_json': text})
    record = {'schema': 'research-project/1', 'id': UUIDS[0], 'title': 'Project', 'owner_name': 'Researcher',
              'notes': 'Notes', 'revision': 1, 'created_at': '2026-11-13T12:00:00Z',
              'updated_at': '2026-11-13T12:01:00Z', 'entries': [clone(item['entry']) for item in entries],
              'owner_key_hash': 'd' * 64, 'viewer_key_hash': None, **(project or {})}
    return {'project': record, 'entries': entries}


def rich_input() -> dict:
    """Every README section: layout and edited-layout readings (null, absent and awkward numbers), signal conditions,
    a selected comparison with requirements, electrode names, and text the README cleans."""
    rows = [
        ('layout', 'a' * 64, {'record': {'metrics': {'field_relative': 0.975, 'sensitivity_tail': None,
                                                     'localization_relative': 1e21, 'p90_mm': 1e-7}}},
         {'electrode_annotation': ANNOTATION},
         {'annotation_id': 'b' * 64, 'title': 'Layout | one`', 'summary': {'protocol': 'design_evaluation'}}),
        ('layout', 'd' * 64, {'record': {'metrics': {'field_relative': 5e-324, 'localization_relative': -1.5}}}, {},
         {'title': 'Second\r\nlayout', 'notes': 'n|o`t\ne', 'summary': {'protocol': 'strict_area', 'n': [1, 2]}}),
        ('editor', 'e' * 64, {'cache': {'result': {'edited_metrics': {'field_relative': 0.9, 'sensitivity_tail': 0.8,
                                                                      'localization_relative': 0.7, 'p90_mm': 2}}}}, {},
         {'title': 'Edited', 'summary': {'protocol': 'electrode-editor/1'}}),
        ('source', 'f' * 64, {'conditions': [{'condition': 'clean|x', 'field_retention': 1},
                                             {'condition': 'ecg', 'field_retention': None}, {'condition': 'eog'}, 5,
                                             'x', {'condition': {'a': 1}, 'field_retention': [1, [2, None]]}]}, {},
         {'title': 'Signal `x`', 'summary': {'protocol': 'source-reception/2'}}),
        ('layout', '1' * 64, {'record': 'not an object'}, {}, {'summary': {'protocol': 7}}),
        ('editor', '2' * 64, {'cache': None}, {}, {'summary': {'protocol': None}}),
        ('source', '3' * 64, {'conditions': 'none'}, {}, {'summary': {'protocol': {'p': 1}}}),
    ]
    workflow = {'reference_entry_id': UUIDS[1], 'candidate_entry_id': UUIDS[2],
                'comparison_href': f"/decision?a={'a' * 64}&b={'d' * 64}&ar=80&thresholdMode=custom&sensitivity=70"
                                   '&p90=12.5&x=%E2%9C%93+y%2B%zz&=e&&k'}
    return saved_input(rows, {'title': 'Rich | project `t`', 'owner_name': 'Researcher\r\nTwo',
                              'notes': 'Line one\nLine two | `x`', 'revision': 12, 'workflow': workflow})


def base_inputs() -> dict[str, dict]:
    research = research_fixture(UUIDS[10:14])
    for item in research['entries']:
        del item['snapshot']
    names = {**ANNOTATION, 'electrode_names': [f'名称, "{i}"' for i in range(64)]}
    named = saved_input([('layout', 'a' * 64, {'record': {'metrics': {'field_relative': 1}}},
                          {'electrode_annotation': names}, {'annotation_id': 'b' * 64})], pretty_text=True)
    empty = saved_input([], {'workflow': {'comparison_href': '/decision?ar=90'}})
    return {'research': research, 'rich': rich_input(), 'named': named, 'empty': empty}


POOL = [None, True, False, 0, 1, -1, 1.5, 2**53, 2**53 - 1, '', 'x', ' ', 'a|b`c\r\nd', UUIDS[30], 'a' * 64, 'f' * 64,
        'records/x.json', 'README.md', '2026-11-13T12:00:00Z', '2026-02-30T24:00:00.000Z', 'not a timestamp',
        [], {}, [UUIDS[30]], ['a' * 64], {'toString': 1}, {'protocol': 'p'}, {'comparison_href': '/decision?ar=9'},
        'é', '\ud800', 'x' * 200, 'x' * 201, '😀' * 100, '😀' * 101, 'layout', 'editor', 'source',
        'application/json', 'text/markdown', {'path': 'a/b', 'sha256': 'c' * 64},
        [{'path': 'a/../b', 'sha256': 'c' * 64}], '/decision?ar=90&p90=5#x']
# Not in the pool: texts such as 'utf-8' or 'research-project/1', which V8's legacy Date.parse reads as times
# (2001-08-01, 2001-01-01) where a time is expected; this port reads the ISO format only (the module docstring).


def paths(value: Any, prefix: tuple = ()) -> list[tuple]:
    out = []
    if isinstance(value, dict):
        for key, child in value.items():
            out.append(prefix + (key,))
            out += paths(child, prefix + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            out.append(prefix + (index,))
            out += paths(child, prefix + (index,))
    return out


def mutate(value: Any, rng: random.Random, pool: list = POOL) -> None:
    """Sets, deletes or adds one member somewhere in ``value``."""
    choices = [path for path in paths(value) if not (len(path) >= 1 and path[-1] == 'snapshot_json'
                                                     and rng.random() < 0.5)]
    if not choices:
        return
    path = rng.choice(choices)
    parent = value
    for key in path[:-1]:
        parent = parent[key]
    action = rng.random()
    if action < 0.2 and isinstance(parent, dict):
        del parent[path[-1]]
    elif action < 0.25 and isinstance(parent, dict):
        parent[rng.choice(['extra', 'workflow', 'annotation_id', 'manifest_sha256', 'access_key'])] = \
            copy.deepcopy(rng.choice(pool))
    elif action < 0.3 and isinstance(parent, list):
        parent.append(copy.deepcopy(rng.choice(parent) if parent and rng.random() < 0.5 else rng.choice(pool)))
    else:
        parent[path[-1]] = copy.deepcopy(rng.choice(pool))


def resum(saved: dict) -> None:
    """Recomputes each entry's snapshot checksum and size from its text, in the entry and in the project's list."""
    listed = saved.get('project', {}).get('entries') if isinstance(saved.get('project'), dict) else None
    for index, item in enumerate(saved.get('entries') if isinstance(saved.get('entries'), list) else []):
        if isinstance(item, dict) and isinstance(item.get('snapshot_json'), str) and isinstance(item.get('entry'),
                                                                                             dict):
            text = item['snapshot_json']
            item['entry'].update(snapshot_sha256=D._hash(text), snapshot_bytes=len(D._utf8(text)))
            if isinstance(listed, list) and index < len(listed) and isinstance(listed[index], dict):
                listed[index].update(snapshot_sha256=D._hash(text), snapshot_bytes=len(D._utf8(text)))


def mutate_snapshot(saved: dict, rng: random.Random) -> None:
    """Changes one snapshot's JSON value (or text), then fixes the checksums so that the identity checks are reached."""
    entries = saved.get('entries') if isinstance(saved, dict) else None
    items = [item for item in entries if isinstance(item, dict) and isinstance(item.get('snapshot_json'), str)] \
        if isinstance(entries, list) else []
    if not items:
        return
    item = rng.choice(items)
    try:
        snapshot = jsjson.parse(item['snapshot_json'])
    except ValueError:
        snapshot = None
    if rng.random() < 0.15 or not isinstance(snapshot, (dict, list)):
        item['snapshot_json'] = rng.choice(['null', '1', '"x"', '[]', '{', item['snapshot_json'] + ' ', '{}'])
    else:
        mutate(snapshot, rng)
        item['snapshot_json'] = jsjson.stringify(snapshot)
    resum(saved)


def build_case(case_id: str, saved: Any, versions: Any = '$absent', now: Any = DATE,
               max_bytes: Any = '$absent') -> dict:
    case = {'id': case_id, 'input': jsjson.stringify(saved), 'now': jsjson.stringify(now)}
    if versions != '$absent':
        case['versions'] = jsjson.stringify(versions)
    if max_bytes != '$absent':
        case['max_bytes'] = jsjson.stringify(max_bytes)
    return case


VERSIONS = ['$absent', {}, {'application_version': '0.1.2'}, None,
            {'application_version': '0.1.2', 'data_manifest_sha256': 'a' * 64, 'data_bundle_id': 'b1',
             'runtime_lock_sha256': 'b' * 64, 'source_files': [{'path': 'pyproject.toml', 'sha256': 'c' * 64},
                                                               {'path': 'src/a.py', 'sha256': 'd' * 64}],
             'env': 'private'},
            {'application_version': 'v|1\n`2'}, {'application_version': ''}, {'application_version': 'x' * 201},
            {'application_version': '😀' * 100}, {'application_version': '😀' * 101}, {'application_version': 5},
            {'data_manifest_sha256': 'A' * 64}, {'data_manifest_sha256': None}, {'runtime_lock_sha256': ['a' * 64]},
            {'data_bundle_id': {}}, {'source_files': {}}, 'string', 5, []] + [
    {'source_files': [row]} for row in (
        {'path': '/abs', 'sha256': 'c' * 64}, {'path': 'a//b', 'sha256': 'c' * 64},
        {'path': 'a/./b', 'sha256': 'c' * 64}, {'path': 'a/', 'sha256': 'c' * 64},
        {'path': 'a/../b', 'sha256': 'c' * 64}, {'path': '..', 'sha256': 'c' * 64},
        {'path': 'a/b', 'sha256': 'C' * 64}, {'path': 'a', 'sha256': 'c' * 64, 'x': 1},
        {'path': 1, 'sha256': 'c' * 64}, {'path': 'a'}, {'path': 'a', 'sha256': {'toString': 1}},
        {'path': 'a', 'sha256': ['c' * 64]}, None)]


def build_corpus() -> list[dict]:
    bases = base_inputs()
    cases = []
    for name, saved in bases.items():
        for index, versions in enumerate(VERSIONS):
            cases.append(build_case(f'{name}-versions-{index}', saved, versions))
        for index, now in enumerate([DATE, 'x', 5, None, {'a': 1}]):
            cases.append(build_case(f'{name}-now-{index}', saved, now=now))
        # The bounds: the snapshots' total and the wire text, at and one byte below each.
        total = sum(len(D._utf8(item['snapshot_json'])) for item in saved['entries'])
        wire = len(D._utf8(D.delivery_json(D.build_research_delivery(clone(saved), now=lambda: DATE))))
        for index, bound in enumerate([wire, wire - 1, total, total - 1, 1, 0, -1, 1.5, '100', None, 2**53, 2**53 - 1]):
            cases.append(build_case(f'{name}-bound-{index}', saved, max_bytes=bound))
        # Snapshots exactly at the bound pass it (`total > maxBytes`), so a later refusal is the one that speaks.
        cases.append(build_case(f'{name}-bound-host', saved, {'application_version': 5}, max_bytes=total))
        if len(saved['entries']) > 1:
            later = clone(saved)
            later['entries'][1]['entry']['snapshot_bytes'] += 1
            first = len(D._utf8(saved['entries'][0]['snapshot_json']))
            cases.append(build_case(f'{name}-bound-later-entry', later, max_bytes=first))
    # Hand-written refusals in Node's order.
    research = bases['research']

    def variant(change: Callable[[dict], Any]) -> dict:
        saved = clone(research)
        saved['project']['entries'] = [item['entry'] for item in saved['entries']]  # the check's shared objects
        change(saved)
        return saved

    hand = {
        'saved-null': None, 'saved-number': 5, 'saved-array': [],
        'project-missing': variant(lambda s: s.pop('project')),
        'project-schema': variant(lambda s: s['project'].update(schema='research-project/2')),
        'project-entries': variant(lambda s: s['project'].update(entries={})),
        'project-id-array': variant(lambda s: s['project'].update(id=[UUIDS[0]])),
        'project-id-tostring': variant(lambda s: s['project'].update(id={'toString': 1})),
        'project-title-empty': variant(lambda s: s['project'].update(title='')),
        'project-revision-zero': variant(lambda s: s['project'].update(revision=0)),
        'project-revision-float': variant(lambda s: s['project'].update(revision=1.5)),
        'project-workflow-falsy': variant(lambda s: s['project'].update(workflow=0)),
        'project-workflow-string': variant(lambda s: s['project'].update(workflow='x')),
        'project-workflow-array': variant(lambda s: s['project'].update(workflow=[])),
        'project-extra': variant(lambda s: s['project'].update(creator_network='e' * 64)),
        'entries-object': variant(lambda s: s.update(entries={})),
        'entries-short': variant(lambda s: s['entries'].pop()),
        'entry-null': variant(lambda s: s['entries'].__setitem__(0, None)),
        'entry-number': variant(lambda s: s['entries'].__setitem__(0, 5)),
        'entry-missing': variant(lambda s: s['entries'][0].pop('entry')),
        'entry-null-listed-without-id': variant(lambda s: (s['entries'][0].update(entry=None),
                                                          s['project']['entries'][0].pop('id'))),
        'entry-number-listed-without-id': variant(lambda s: (s['entries'][0].update(entry=7),
                                                            s['project']['entries'][0].pop('id'))),
        'entry-listed-null': variant(lambda s: s['project']['entries'].__setitem__(0, None)),
        'entry-listed-null-later': variant(lambda s: s['project']['entries'].__setitem__(2, None)),
        'entry-duplicate': variant(lambda s: s['entries'].__setitem__(1, s['entries'][0])),
        'entry-kind': variant(lambda s: s['entries'][0]['entry'].update(kind='invented')),
        'entry-text-missing': variant(lambda s: s['entries'][0].pop('snapshot_json')),
        'entry-bytes-string': variant(lambda s: s['entries'][0]['entry'].update(snapshot_bytes=str(
            s['entries'][0]['entry']['snapshot_bytes']))),
        'snapshot-null': variant(lambda s: (s['entries'][0].update(snapshot_json='null'), resum(s))),
        'snapshot-not-json': variant(lambda s: (s['entries'][0].update(snapshot_json='{"a":'), resum(s))),
        'snapshot-bom': variant(lambda s: (s['entries'][0].update(snapshot_json='\ufeff{}'), resum(s))),
        'snapshot-surrogate': variant(lambda s: (s['entries'][0].update(snapshot_json=s['entries'][0]['snapshot_json']
                                                                         [:-1] + ',"s":"\\ud800\ud800"}'), resum(s))),
        'snapshot-deep': variant(lambda s: (s['entries'][0].update(snapshot_json=s['entries'][0]['snapshot_json']
                                                                    [:-1] + ',"d":' + '[' * 3000 + ']' * 3000 + '}'),
                                            resum(s))),
        'record-id-absent-both': variant(lambda s: (s['entries'][0]['entry'].pop('record_id'),
                                                    s['entries'][0].update(snapshot_json=jsjson.stringify(
                                                        {'schema': 'research-project-snapshot/1', 'kind': 'layout',
                                                         'payload': {}})), resum(s))),
        'record-id-number-both': variant(lambda s: (s['entries'][0]['entry'].update(record_id=5),
                                                    s['entries'][0].update(snapshot_json=jsjson.stringify(
                                                        {'schema': 'research-project-snapshot/1', 'kind': 'layout',
                                                         'record_id': 5, 'payload': {}})), resum(s))),
        'summary-missing': variant(lambda s: s['entries'][0]['entry'].pop('summary')),
        'summary-null': variant(lambda s: s['entries'][0]['entry'].update(summary=None)),
        'summary-string': variant(lambda s: s['entries'][0]['entry'].update(summary='text')),
        'title-tostring': variant(lambda s: s['entries'][0]['entry'].update(title={'toString': 1})),
        'title-array': variant(lambda s: s['entries'][0]['entry'].update(title=['a|', ['b', None], {}])),
        'annotation-null': variant(lambda s: s['entries'][0]['entry'].update(annotation_id=None)),
        'annotation-without-names': variant(lambda s: s['entries'][0]['entry'].update(annotation_id='b' * 64)),
        'workflow-href-array': variant(lambda s: s['project'].update(workflow={'comparison_href': ['?ar=1', 'b=2']})),
        'workflow-href-tostring': variant(lambda s: s['project'].update(workflow={'comparison_href': {'toString': 1}})),
        'workflow-href-number': variant(lambda s: s['project'].update(workflow={'comparison_href': 5})),
        'workflow-selected': variant(lambda s: s['project'].update(workflow={'reference_entry_id': UUIDS[10],
                                                                             'candidate_entry_id': UUIDS[12],
                                                                             'comparison_href': '?a=1&b=2&ar=3'})),
    }
    for name, saved in hand.items():
        cases.append(build_case(f'hand-{name}', saved))
    # Random changes of every base: one or two members anywhere, or a snapshot changed with fixed checksums.
    rng = random.Random(20261125)
    for index in range(1500):
        name = rng.choice(sorted(bases))
        saved = clone(bases[name])
        for _ in range(rng.choice([1, 1, 2])):
            if rng.random() < 0.35:
                mutate_snapshot(saved, rng)
            else:
                mutate(saved, rng)
                if rng.random() < 0.5 and isinstance(saved, dict):
                    resum(saved)
        cases.append(build_case(f'random-{index}', saved, versions=rng.choice(VERSIONS[:6])))
    return cases


def python_build(case: dict) -> dict:
    saved = jsjson.parse(case['input'])
    arguments: dict = {'now': (lambda value=jsjson.parse(case['now']): value)}
    if 'max_bytes' in case:
        arguments['max_bytes'] = jsjson.parse(case['max_bytes'])
    versions = jsjson.parse(case['versions']) if 'versions' in case else D.UNDEFINED

    def call() -> dict:
        bundle = D.build_research_delivery(saved, versions, **arguments)
        text = D.delivery_json(bundle)
        assert text == jsjson.stringify(bundle)
        return {'json': text, 'after': jsjson.stringify(saved)}

    return outcome(call)


@needs_node
def test_delivery_builds_equal_nodes(tmp_path):
    cases = build_corpus()
    node = run_driver('build', cases, tmp_path)
    built = refused = 0
    for case in cases:
        ours = python_build(case)
        assert_same(ours, node['by_id'][case['id']], case['id'])
        built += ours['ok']
        refused += not ours['ok']
    # Both outcomes, each refusal, a TypeError and the 413 are reached.
    reached = {(case.get('message'), case.get('status'), case['name']) for case in node['cases'] if not case['ok']}
    for message in (D.INVALID_PROJECT, D.METADATA_INVALID, D.ENTRIES_INCOMPLETE, D.ENTRY_MISMATCH, D.CHECKSUM_MISMATCH,
                    D.SNAPSHOT_NOT_JSON, D.SNAPSHOT_MISMATCH, D.HOST_INVALID):
        assert (message, 409, 'Error') in reached, message
    assert (D.TOO_LARGE, 413, 'Error') in reached
    assert any(name == 'TypeError' for _, _, name in reached)
    assert built > 300 and refused > 300


def validate_corpus() -> list[dict]:
    bases = {name: D.build_research_delivery(saved, VERSIONS[4], now=lambda: DATE)
             for name, saved in base_inputs().items()}
    cases = [{'id': f'base-{name}', 'text': jsjson.stringify(bundle)} for name, bundle in bases.items()]
    rng = random.Random(1125)
    pool = POOL + [DATE, '2026-11-14', '+275760-09-13T00:00:00.000Z',
                   '+275760-09-13T00:00:00.001Z', 'records/' + UUIDS[30] + '.json']
    for index in range(2000):
        bundle = clone(bases[rng.choice(sorted(bases))])
        for _ in range(rng.choice([1, 1, 2])):
            roll = rng.random()
            if roll < 0.15:
                files = [file for file in bundle['files']
                         if isinstance(file, dict) and isinstance(file.get('content'), str)]
                if files:
                    file = rng.choice(files)
                    try:
                        snapshot = jsjson.parse(file['content'])
                    except ValueError:
                        snapshot = None
                    if isinstance(snapshot, dict) and rng.random() < 0.8:
                        mutate(snapshot, rng, pool)
                        file['content'] = jsjson.stringify(snapshot)
                    else:
                        file['content'] = rng.choice(['{', 'null', '1', '[]', file['content'] + ' '])
            elif roll < 0.2:
                keys = list(bundle)
                rng.shuffle(keys)
                bundle = {key: bundle[key] for key in keys}
            else:
                mutate(bundle, rng, pool)
        roll = rng.random()
        if roll < 0.6:
            rehash(bundle, records=roll < 0.45)
        cases.append({'id': f'random-{index}', 'text': jsjson.stringify(bundle)})
    return cases


def rehash(bundle: Any, records: bool = True) -> None:
    """Recomputes what a producer recomputes: each file's size and digest, each record's ``snapshot_sha256`` from
    the file at its path (unless ``records`` is false), and the manifest (in the delivery's key order)."""
    if not isinstance(bundle, dict) or not isinstance(bundle.get('files'), list):
        return
    for file in bundle['files']:
        if isinstance(file, dict) and isinstance(file.get('content'), str):
            file['size_bytes'], file['sha256'] = len(D._utf8(file['content'])), D._hash(file['content'])
    if records and isinstance(bundle.get('records'), list):
        for record in bundle['records']:
            if isinstance(record, dict):
                match = next((file for file in bundle['files'] if isinstance(file, dict)
                              and file.get('path') == record.get('path') and 'sha256' in file), None)
                if match is not None:
                    record['snapshot_sha256'] = match['sha256']
    if all(isinstance(file, dict) for file in bundle['files']):
        rehash_manifest(bundle)


@needs_node
def test_delivery_validation_equals_nodes(tmp_path):
    cases = validate_corpus()
    node = run_driver('validate', cases, tmp_path)
    accepted = 0
    for case in cases:
        ours = outcome(lambda: {'value': D.validate_research_delivery(jsjson.parse(case['text']))})
        assert_same(ours, node['by_id'][case['id']], case['id'])
        accepted += ours['ok']
    reached = {case.get('message') for case in node['cases'] if not case['ok']}
    assert {D.UNSUPPORTED, D.FILE_INTEGRITY, D.MANIFEST_INTEGRITY, D.RECORD_MISMATCH, D.RECORD_MISSING} <= reached
    assert any(case['name'] == 'SyntaxError' for case in node['cases'] if not case['ok'])
    assert accepted > 100


HREFS = ['/decision?ar=90', '/decision?a=1&b=2&ar=80&thresholdMode=joint', '/decision?', '/decision', '?', '?&&=&',
         '?a', '?a=', '?=b', '?a=b=c', '?a+b=c+d', '?%41%4a%4G%2%zz%', '?a=%E2%9C%93', '?a=%C3', '?a=%FF%FE',
         '?a=%F0%80%80', '?a=%ED%A0%80', '?a=%EF%BB%BFx', '?%2B=%26&%3D=1', '?a=b#c', '#?a=b', '/x#y?z',
         ' \t/decision?ar=9 0 \x00', '\x00\x1f /d?a\tb=c\nd\r ', '/d?a=é😀', '/d?\ud800=\udc00', '/d?\ud83d\ude00=1',
         '/d?a="<>\'`{}|^', 'https://example.com/?a=1&b=2', 'mailto:x?y=z', 'javascript:alert(1)?ar=1#x',
         'http:?ar=1', 'HTTP://Example.com?x', '//host/?q=1', '\\\\host\\?q=1', 'http://a?b@c/?x=1',
         'decision?x=1', '../d?x=1', '/decision?a=1&a=2', '/d?' + 'x=' + 'y' * 5000]


def search_corpus() -> list[dict]:
    values: list[Any] = list(HREFS) + [5, True, None, ['?ar=1', 'b=2'], [], {}, {'toString': 1}, 1e21, ['?a', ['=b']]]
    rng = random.Random(2511)
    alphabet = ['?', '&', '=', '+', '%', '2', '0', 'B', 'f', 'E', 'g', '#', ' ', '\t', '\n', '\r', '\x00', '\x1f',
                'é', '😀', '\ud800', '\udc00', 'a', 'b', '/', '\\', ':', '@', 'F', 'C', '3', '9', '\x7f', '\u2028']
    for _ in range(1500):
        text = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(0, 24)))
        if rng.random() < 0.6:
            at = rng.randrange(0, len(text) + 1)
            text = text[:at] + '?' + text[at:]
        values.append(rng.choice(['', ' ', '\t', '\x00\n']) + '/d' + text)
    return [{'id': f'href-{index}', 'href': jsjson.stringify(value)} for index, value in enumerate(values)]


@needs_node
def test_comparison_links_read_as_nodes(tmp_path):
    cases = search_corpus()
    node = run_driver('search', cases, tmp_path)
    for case in cases:
        ours = outcome(lambda: {'pairs': [list(pair) for pair in D.search_params(jsjson.parse(case['href']))]})
        assert_same(ours, node['by_id'][case['id']], (case['id'], case['href']))
    assert sum(bool(case.get('pairs')) for case in node['cases']) > 500


def versions_roots(base: Path) -> list[dict]:
    """Synthetic scientific roots and their outcome-relevant changes, each with a source root holding both hosts'
    files at version 0.2.0."""
    source = base / 'source'
    source_tree(source)
    good = {'schema_version': 'eeglayoutlab-data-bundle/1', 'bundle_id': 'test-model-v1'}
    lock = {'schema': 'eeglayoutlab-runtime-lock/1', 'x': [1, 2]}
    layouts: dict[str, Callable[[Path], None]] = {
        'good': lambda root: write_identities(root, good, lock),
        'no-data': lambda root: (write_identities(root, good, lock), (root / 'data/manifest.json').unlink()),
        'data-directory': lambda root: (write_identities(root, good, lock), (root / 'data/manifest.json').unlink(),
                                        (root / 'data/manifest.json').mkdir()),
        'data-not-json': lambda root: (write_identities(root, good, lock),
                                       (root / 'data/manifest.json').write_text('{')),
        'data-bom': lambda root: (write_identities(root, good, lock), (root / 'data/manifest.json').write_bytes(
            b'\xef\xbb\xbf' + jsjson.stringify(good).encode())),
        'data-null': lambda root: (write_identities(root, good, lock),
                                   (root / 'data/manifest.json').write_text('null')),
        'data-schema': lambda root: write_identities(root, {**good, 'schema_version': 'x'}, lock),
        'data-id-empty': lambda root: write_identities(root, {**good, 'bundle_id': ''}, lock),
        'data-id-number': lambda root: write_identities(root, {**good, 'bundle_id': 5}, lock),
        'data-invalid-utf8': lambda root: (
            write_identities(root, good, lock),
            (root / 'data/manifest.json').write_bytes(
                b'{"schema_version":"eeglayoutlab-data-bundle/1","bundle_id":"\xff\xfe"}')),
        'no-lock': lambda root: (write_identities(root, good, lock), (root / 'configs/runtime/manifest.json').unlink()),
        'lock-schema': lambda root: write_identities(root, good, {'schema': 'other'}),
        'lock-array': lambda root: (write_identities(root, good, lock),
                                    (root / 'configs/runtime/manifest.json').write_text('[]')),
        'linux-runtime-without-lock': lambda root: (write_identities(root, good, lock),
                                                    runtime(root, 'compute-linux-64')),
        'linux-runtime': lambda root: (write_identities(root, good, lock), runtime(root, 'compute-linux-64'),
                                       (root / 'configs/runtime/manifest-linux-64.json').write_text(
                                           jsjson.stringify({'schema': 'eeglayoutlab-runtime-lock/1', 'linux': True}))),
        'both-runtimes': lambda root: (write_identities(root, good, lock), runtime(root, 'compute-linux-64'),
                                       runtime(root, 'simnibs-4.6.0')),
        'dangling-native': lambda root: (write_identities(root, good, lock), runtime(root, 'compute-linux-64'),
                                         (root / '.runtime/simnibs-4.6.0/bin').mkdir(parents=True),
                                         (root / '.runtime/simnibs-4.6.0/bin/python').symlink_to(root / 'missing'),
                                         (root / 'configs/runtime/manifest-linux-64.json').write_text(
                                             jsjson.stringify({'schema': 'eeglayoutlab-runtime-lock/1'}))),
    }
    cases = []
    for name, layout in layouts.items():
        root = base / name
        root.mkdir()
        layout(root)
        cases.append({'id': name, 'root': str(root), 'source': str(source)})
    cases.append({'id': 'missing-root', 'root': str(base / 'missing'), 'source': str(source)})
    return cases


def runtime(root: Path, name: str) -> None:
    (root / f'.runtime/{name}/bin').mkdir(parents=True)
    (root / f'.runtime/{name}/bin/python').write_text('fixture')


@needs_node
def test_delivery_versions_equal_nodes(tmp_path):
    cases = versions_roots(tmp_path)
    node = run_driver('versions', cases, tmp_path)
    source = Path(cases[0]['source'])
    for case in cases:
        theirs = node['by_id'][case['id']]
        assert D.runtime_lock_path(case['root']) == theirs['lock'], case['id']
        ours = outcome(lambda: {'value': D.delivery_versions(case['root'], case['source'])})
        assert ours['ok'] == theirs['ok'], (case['id'], ours, theirs)
        if not ours['ok']:
            assert (ours['message'], ours['status']) == (theirs['message'], theirs['status']) == \
                (D.VERSIONS_UNAVAILABLE, 503)
            assert not theirs['includes_root']
            continue
        value, expected = ours['value'], theirs['value']
        for key in ('application_version', 'data_manifest_sha256', 'data_bundle_id', 'runtime_lock_sha256'):
            assert value[key] == expected[key], (case['id'], key)
        # The host files differ by design; each list hashes the bytes of its own files.
        assert [row['path'] for row in value['source_files']] == list(D.HOST_FILES)
        assert [row['path'] for row in expected['source_files']][0] == 'webapp/package.json'
        for row in value['source_files'] + expected['source_files']:
            assert row['sha256'] == hashlib.sha256((source / row['path']).read_bytes()).hexdigest()
    # good, data-invalid-utf8 (U+FFFD in the bundle id), linux-runtime, both-runtimes, dangling-native
    assert sum(node['by_id'][case['id']]['ok'] for case in cases) == 5


# --- Fixtures of the Node delivery-reader checks ---------------------------------------------------------------------

READER_ID, READER_ENTRY = '18358bf4-143e-4431-8456-b99328462b37', '18358bf4-143e-4431-8456-b99328462b38'
UPLOAD_PROJECT, UPLOAD_ENTRY = '19d70d92-60a7-4271-9d42-ff38c8cb8881', '19d70d92-60a7-4271-9d42-ff38c8cb8882'


def reader_fixture(named: bool = False, legacy: bool = False) -> dict:
    """check-research-delivery-reader.mjs's ``fixture({named, legacy})``: one 64-electrode layout whose snapshot text
    is pretty-printed, optionally with electrode names, or with legacy metrics (no median or P90)."""
    record_id, annotation_id = 'a' * 64, 'b' * 64
    metrics = {'field_relative': 0.975, 'sensitivity_tail': None, 'localization_relative': 1.001,
               **({} if legacy else {'median_mm': 1.234, 'p90_mm': 3.456})}
    snapshot = {'schema': 'research-project-snapshot/1', 'kind': 'layout', 'record_id': record_id,
                'payload': {'record': {'id': record_id, 'layout': {
                    'xyzMm': [[i, i / 3, -i] for i in range(64)], 'regionIndices': [i % 2 for i in range(64)]},
                    'metrics': metrics}}}
    if named:
        snapshot['electrode_annotation'] = {
            'schema': 'eeg-electrode-annotation/1', 'id': annotation_id, 'record_id': record_id,
            'request_sha256': 'c' * 64, 'electrode_names': [f'名称, "{i}"' for i in range(64)]}
    snapshot_json = pretty(snapshot) + '\n'
    entry = {'id': READER_ENTRY, 'kind': 'layout', 'title': 'Original layout',
             'notes': '<script>never executed</script>', 'record_id': record_id,
             **({'annotation_id': annotation_id} if named else {}), 'created_at': DATE,
             'snapshot_bytes': len(snapshot_json.encode('utf-8')), 'snapshot_sha256': sha(snapshot_json),
             'summary': {'protocol': 'design_evaluation'}}
    project = {'schema': 'research-project/1', 'id': READER_ID, 'title': 'Delivery', 'owner_name': 'Researcher',
               'notes': 'Saved evidence', 'revision': 1, 'created_at': DATE, 'updated_at': DATE, 'entries': [entry]}
    saved = {'project': project, 'entries': [{'entry': entry, 'snapshot_json': snapshot_json}]}
    return D.build_research_delivery(saved, {'application_version': '0.1.2'}, now=lambda: DATE)


def source_result(schema: str) -> dict:
    """check-delivery-upload-contract.mjs's ``sourceFixture(schema)``: a complete signal result of 64 electrodes and
    400 samples, all zeros."""
    single = schema == 'source-reception/2'
    request = {'record_id': 'a' * 64, **({'mode': 'single_source', 'source_index': 2} if single else
                                          {'brain_region': 'frontal'}), 'waveform': 'burst', 'artifact_scale': 1,
               'seed': 2026}
    xyz = [[i, i / 3, 80] for i in range(64)]
    metric = {'nmse': 0.2, 'explained_energy': 0.8, 'brain_artifact_ratio_db': None}

    def score(condition: str, artifact_scale: float) -> dict:
        return {'condition': condition, 'artifact_scale': artifact_scale, 'baseline': dict(metric),
                'candidate': dict(metric), 'field_retention': 1}

    def components() -> dict:
        return {name: [[0] * 400 for _ in range(64)] for name in (
            'brain_uv', 'ecg_uv', 'eog_uv', 'noise_uv', 'reconstructed_brain_uv', 'reconstructed_ecg_uv',
            'reconstructed_eog_uv', 'reconstructed_noise_uv')}

    return {'schema_version': schema, 'status': 'completed', 'request': request,
            'source': {**({'mode': 'single_source', 'generation_source_indices': [2]} if single else {}),
                       'region': 'frontal', 'selection_method': 'synthetic wire fixture', 'xyz_mm': [[0, 0, 60]],
                       'normals_mri': [[0, 0, 1]], 'bank_source_indices': [4098], 'patch_count': 1},
            'layout': {'xyzMm': xyz, 'referenceXyzMm': xyz, 'regionIndices': [0] * 64},
            'conditions': [score(condition, 0 if condition == 'clean' else 1)
                           for condition in ('clean', 'ecg', 'eog', 'mixed')],
            'strength_curve': [score('clean', 0), *[score(condition, scale) for condition in ('ecg', 'eog', 'mixed')
                                                    for scale in (0, 0.5, 1, 2, 4)]],
            'waveforms': {'time_s': [i / 100 for i in range(400)], 'source_nam': [[0] * 400], 'ecg_latent': [0] * 400,
                          'eog_latent': [0] * 400, 'baseline': components(), 'candidate': components()},
            'metrics': {'pure_brain_amplitude_ratio': 1}, 'protocol': {}, 'provenance': {'forward_mode': 'exact_bank'}}


def upload_fixture(schema: str) -> dict:
    """check-delivery-upload-contract.mjs's ``delivery(sourceFixture(schema))``."""
    result = source_result(schema)
    snapshot = {'schema': 'research-project-snapshot/1', 'kind': 'source', 'record_id': 'b' * 64, 'payload': result}
    snapshot_json = jsjson.stringify(snapshot)
    entry = {'id': UPLOAD_ENTRY, 'kind': 'source', 'record_id': 'b' * 64, 'title': 'Source wire fixture', 'notes': '',
             'created_at': DATE, 'snapshot_sha256': sha(snapshot_json),
             'snapshot_bytes': len(snapshot_json.encode('utf-8')),
             'summary': {'protocol': result['schema_version'], 'parent_id': 'a' * 64}}
    project = {'schema': 'research-project/1', 'id': UPLOAD_PROJECT, 'title': 'Upload contract',
               'owner_name': 'Fixture', 'notes': '', 'revision': 1, 'created_at': DATE, 'updated_at': DATE,
               'entries': [entry]}
    saved = {'project': project, 'entries': [{'entry': entry, 'snapshot_json': snapshot_json}]}
    return D.build_research_delivery(saved, {}, now=lambda: DATE)


def fixture_texts() -> dict[str, str]:
    """Each fixture file's text by name: ``JSON.stringify(bundle, null, 2) + '\\n'``."""
    bundles = {'reader': reader_fixture(), 'reader-named': reader_fixture(named=True),
               'reader-legacy': reader_fixture(legacy=True),
               'upload-source-reception-1': upload_fixture('source-reception/1'),
               'upload-source-reception-2': upload_fixture('source-reception/2')}
    return {name: pretty(bundle) + '\n' for name, bundle in bundles.items()}


def test_the_delivery_fixtures_are_the_python_builds_of_the_checks_inputs():
    texts = fixture_texts()
    assert sorted(path.name for path in FIXTURES.iterdir()) == sorted(f'{name}.json' for name in texts)
    for name, text in texts.items():
        assert (FIXTURES / f'{name}.json').read_bytes() == text.encode('utf-8'), \
            'PYTHONPATH=src:tests python -m tests.service.test_delivery writes them'
        bundle = jsjson.parse(text)
        assert D.validate_research_delivery(bundle) is True
        assert pretty(bundle) + '\n' == text  # what the checks compare with the reader's original text
    named = jsjson.parse(texts['reader-named'])
    assert named['records'][0]['annotation_id'] == 'b' * 64 and named['files'][1]['content'].endswith('}\n')
    assert '| Original layout | design_evaluation | 0.975 | null / 原记录不可计算 | 1.001 | 3.456 |' in \
        named['files'][0]['content']
    assert '| 1.001 | unrecorded / 未记录 |' in jsjson.parse(texts['reader-legacy'])['files'][0]['content']


@needs_node
def test_the_delivery_fixtures_are_nodes_builds_of_the_checks_inputs(tmp_path):
    node = run_driver('fixtures', [], tmp_path)
    assert sorted(node['texts']) == sorted(path.stem for path in FIXTURES.iterdir())
    for name, text in node['texts'].items():
        assert (FIXTURES / f'{name}.json').read_bytes() == text.encode('utf-8'), name
    assert len(node['mutations']) == 12 and all(row['equal'] for row in node['mutations']), node['mutations']


# --- What Python adds ------------------------------------------------------------------------------------------------

def test_delivery_text_and_bound_follow_json_stringify():
    rng = random.Random(7)
    alphabet = ['a', '"', '\\', '\b', '\t', '\n', '\x0c', '\r', '\x00', '\x1f', '\x7f', 'é', '😀', '\ud800', '\udc00',
                '\ud83d', '\ude00', '\u2028', '/', '<']
    for _ in range(3000):
        text = ''.join(rng.choice(alphabet) for _ in range(rng.randrange(0, 12)))
        assert D._quote(text) == jsjson.quote(text), repr(text)
        assert len(D._utf8(text)) == len(text.encode('utf-16-le', 'surrogatepass').decode(
            'utf-16-le', 'replace').encode('utf-8'))
    # A snapshot whose JSON text is mostly escapes: the wire bound counts the escaped text, not the snapshot bytes.
    payload = {'s': '"\\\n\x01' * 200 + '\ud800'}
    saved = saved_input([('source', 'f' * 64, payload, {}, {})])
    bundle = D.build_research_delivery(clone(saved), now=lambda: DATE)
    wire = len(D.delivery_json(bundle).encode('utf-8'))
    assert D.delivery_json(bundle) == jsjson.stringify(bundle)
    assert wire > 2 * sum(len(D._utf8(item['snapshot_json'])) for item in saved['entries'])
    assert D.build_research_delivery(clone(saved), now=lambda: DATE, max_bytes=wire) == bundle
    with pytest.raises(ProjectError) as caught:
        D.build_research_delivery(clone(saved), now=lambda: DATE, max_bytes=wire - 1)
    assert (caught.value.message, caught.value.status) == (D.TOO_LARGE, 413)
    # Snapshots exactly at the bound pass the snapshot bound: the host refusal that follows is the one raised.
    total = sum(len(D._utf8(item['snapshot_json'])) for item in saved['entries'])
    with pytest.raises(ProjectError) as caught:
        D.build_research_delivery(clone(saved), {'application_version': 5}, now=lambda: DATE, max_bytes=total)
    assert (caught.value.message, caught.value.status) == (D.HOST_INVALID, 409)


def test_times_and_links_outside_nodes_iso_reading():
    """The documented differences: a time in one of V8's legacy formats is refused (Node accepts it), and a link that
    ``new URL`` refuses is still read for its query (the store saves neither)."""
    bundle = D.build_research_delivery(research_fixture(), now=lambda: 'Fri, 13 Nov 2026 12:00:00 GMT')
    with pytest.raises(ProjectError) as caught:
        D.validate_research_delivery(bundle)
    assert caught.value.message == D.UNSUPPORTED
    assert D.search_params('http://exa mple.com/?ar=1') == [('ar', '1')]


def test_the_export_time_is_now_in_iso_format():
    import time

    before = time.time()
    exported_at = D.build_research_delivery(research_fixture())['exported_at']
    assert re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z', exported_at)
    import datetime
    moment = datetime.datetime.strptime(exported_at, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=datetime.timezone.utc)
    assert before - 0.001 <= moment.timestamp() <= time.time()


def test_exports_build_off_the_event_loop(monkeypatch):
    import threading

    store, _ = saved_source_project()
    threads = []
    original = D.build_research_delivery

    def build(*arguments, **options):
        threads.append(threading.current_thread() is threading.main_thread())
        return original(*arguments, **options)

    monkeypatch.setattr(D, 'build_research_delivery', build)
    exported = run(D.ProjectDelivery(store, versions=lambda: {}).export(UUIDS[0]))
    assert D.validate_research_delivery(exported) is True
    assert threads == [False]


if __name__ == '__main__':
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for fixture_name, fixture_text in fixture_texts().items():
        (FIXTURES / f'{fixture_name}.json').write_bytes(fixture_text.encode('utf-8'))
