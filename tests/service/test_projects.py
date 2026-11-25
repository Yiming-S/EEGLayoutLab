"""Research projects (phase 2 slice 9): ``eeglayoutlab.server.workspace_projects``.

- Ports of check-project-store.mjs :19, :37, :72, :99, :116, :129, :138, :151, :158 and :167 on ``ProjectStore``
  without credentials; of check-project-api.mjs :53, :77, :98, :110 and :119 on ``ProjectService.handle`` (the
  middleware after the access policy and the token: local access needs no project key, and the policy, origin and
  token refusals of :77 and the cache headers of :53 belong to the route tests); of check-project-workflow.mjs :96
  and of the project halves of check-coordinate-review.mjs :139 and :161. :43 becomes the list test (Node has no
  list, ``GET /api/projects`` was 405); :61 and :88 (keys and read-only sharing) become the tests of the dropped
  credentials.
- Parity (plan slice 9): parity/projects.mjs runs Node's ``ProjectStore`` and ``ProjectService`` middleware on the
  same operations, with the same clock and identifiers, and Python must answer with the same statuses, messages and
  values and leave the same files byte for byte (``project.json`` and every snapshot, so ``snapshot_sha256`` and the
  snapshot bytes are equal): store lifecycles, refusals in Node's order (synchronous throws kept apart), limits,
  tampered and linked files, a corpus of comparison links and of crafted metadata and snapshots, and the service's
  snapshot resolution and HTTP refusals. Projects Node wrote in a Q fixture (``results/web-service/projects``) read
  back unchanged in Python, and Python continues them as Node does.
- The deliberate differences (module docstring of ``workspace_projects``) are asserted as such: the list, ``share``
  and ``revoke-share`` 404, no stored key, no pruning, ISO dates only.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
from pathlib import Path
import random
import shutil
import stat
import subprocess
import sys
from typing import Any

import pytest

from schema_parity_support import require

require('pydantic')

from eeglayoutlab.schemas import jsjson  # noqa: E402
from eeglayoutlab.schemas.projects import UNDEFINED  # noqa: E402
from eeglayoutlab.server.workspace_files import ProjectError  # noqa: E402
from eeglayoutlab.server.workspace_projects import (  # noqa: E402
    BODY_LIMIT, ENDPOINT, PROJECT_LIMITS, ProjectService, ProjectStore, public_project, validate_record,
)
from eeglayoutlab.server.workspace_studies import ResourceError  # noqa: E402

from .key_parity_support import needs_node  # noqa: E402
from .projects_support import (  # noqa: E402
    CRAFTED_KEY, NOT_OWNED, ExportedIds, StandInAnnotations, StandIns, annotation, b64, crafted_project,
    editor_cache, layout_bundle, layout_record, node_read, node_records, python_read, python_service, python_store,
    run_driver, scientific, sha, snapshot, source_result,
)
from .studies_support import tree  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
KEY = 'a' * 64
R1, R2, R3, R4, R5 = ('1' * 64, '2' * 64, '3' * 64, '4' * 64, '5' * 64)
UNKNOWN = '0a0a0000-0000-4000-8000-00000000ffff'


def run(coroutine):
    return asyncio.run(coroutine)


async def rejects(pending, status: int, message: str | None = None) -> BaseException:
    """``assert.rejects``: ``pending`` is an awaitable (the call did not raise) that fails with ``status``."""
    with pytest.raises(Exception) as caught:
        await pending
    assert getattr(caught.value, 'status', None) == status, caught.value
    if message is not None:
        assert caught.value.message == message
    return caught.value


async def fixture(base: Path) -> tuple[ProjectStore, dict]:
    """check-project-store.mjs's ``fixture``: a store under ``<base>/projects`` with one project."""
    store = ProjectStore(str(base / 'projects'))
    created = await store.create({'title': 'Study A', 'owner_name': 'Researcher', 'notes': 'Original study'})
    return store, created


def source_snapshot() -> dict:
    return snapshot('source', KEY)


# --- check-project-store.mjs -------------------------------------------------------------------------------------

def test_comparison_settings_keep_exact_requirements_without_changing_archived_calculations(tmp_path):
    """check-project-store.mjs:19."""
    async def main():
        store, created = await fixture(tmp_path)
        id = created['project']['id']

        def save_layout(revision, record_id):
            return store.attach(id, {'revision': revision, 'kind': 'layout'}, snapshot('layout', record_id),
                                {'protocol': 'cache', 'electrode_count': 64})
        first, second = await save_layout(1, R1), await save_layout(2, R2)
        before = await store.read_snapshots(id)
        workflow = {'reference_entry_id': first['entry']['id'], 'candidate_entry_id': second['entry']['id'],
                    'comparison_href': f'/decision?a={R1}&b={R2}&ar=87&thresholdMode=custom&sensitivity=63'
                                       '&localization=52&p90=28.5'}
        saved = await store.patch(id, {'revision': 3, 'workflow': workflow})
        assert saved['project']['workflow'] == workflow
        assert (await store.read_snapshots(id))['entries'] == before['entries']
        await store.detach(id, first['entry']['id'], 4)
        remaining = (await store.get(id))['project']
        assert remaining['workflow'] == {'reference_entry_id': None, 'candidate_entry_id': second['entry']['id'],
                                         'comparison_href': None}
    run(main())


def test_comparison_settings_reject_external_links_foreign_layouts_parameters_and_fake_scores(tmp_path):
    """check-project-store.mjs:37."""
    async def main():
        store, created = await fixture(tmp_path)
        id = created['project']['id']
        first = await store.attach(id, {'revision': 1, 'kind': 'layout'}, snapshot('layout', KEY), {'protocol': 'cache'})
        second = await store.attach(id, {'revision': 2, 'kind': 'layout'}, snapshot('layout', 'b' * 64),
                                    {'protocol': 'cache'})
        href = f"/decision?a={KEY}&b={'b' * 64}&ar=90"
        valid = {'reference_entry_id': first['entry']['id'], 'candidate_entry_id': second['entry']['id'],
                 'comparison_href': href}
        for value in [
            {**valid, 'reference_entry_id': '00000000-0000-4000-8000-000000000001'},
            {**valid, 'candidate_entry_id': first['entry']['id']},
            {**valid, 'comparison_href': 'https://example.org/decision'},
            {**valid, 'comparison_href': href + '&score=1'},
            {**valid, 'comparison_href': href + '&ar=80'},
            {**valid, 'comparison_href': href.replace('ar=90', 'ar=101')},
            {**valid, 'comparison_href': href + '&p90=-1'},
            {**valid, 'comparison_href': href.replace('ar=90', 'ar=5')},
            {**valid, 'comparison_href': href + '&thresholdMode=joint&sensitivity=42'},
            {**valid, 'comparison_href': href + '&thresholdMode=joint&p90=20'},
            {**valid, 'comparison_href': 0},
            {**valid, 'scientific_result': {'score': 1}},
        ]:
            await rejects(store.patch(id, {'revision': 3, 'workflow': value}), 400)
        assert (await store.get(id))['project']['revision'] == 3
    run(main())


def test_an_interrupted_snapshot_write_neither_blocks_recovery_nor_becomes_a_result(tmp_path):
    """check-project-store.mjs:72."""
    async def main():
        store, created = await fixture(tmp_path)
        id = created['project']['id']
        directory = Path(store.directory) / id / 'snapshots'
        orphan = directory / f"{'d' * 64}.json.{'0f0f0f0f-0000-4000-8000-000000000001'}.tmp"
        orphan.write_text('{"incomplete":', encoding='utf-8')
        os.chmod(orphan, 0o600)
        restarted = ProjectStore(store.directory)
        attached = await restarted.attach(id, {'revision': 1, 'kind': 'source'}, source_snapshot(),
                                          {'protocol': 'source-reception/2'})
        assert (await restarted.get_entry(id, attached['entry']['id']))['snapshot'] == source_snapshot()
        assert orphan.read_text(encoding='utf-8') == '{"incomplete":'
        (directory / 'unexpected-file').write_text('unrelated', encoding='utf-8')
        following = source_snapshot()
        following['record_id'] = 'e' * 64
        await rejects(restarted.attach(id, {'revision': 2, 'kind': 'source'}, following, {}), 409,
                      'Unexpected scientific snapshot file.')
        assert (await restarted.get(id))['project']['revision'] == 2
    run(main())


def test_rename_and_entry_notes_preserve_exact_archived_json_and_checksums(tmp_path):
    """check-project-store.mjs:99."""
    async def main():
        store, created = await fixture(tmp_path)
        id = created['project']['id']
        original = source_snapshot()
        attached = await store.attach(id, {'revision': 1, 'kind': 'source', 'receipt_id': 'unused-by-store',
                                           'title': 'Signal A'}, original,
                                      {'protocol': 'source-reception/2', 'electrode_count': 64})
        original['payload']['waveforms']['data'][0] = 999
        saved = await store.get_entry(id, attached['entry']['id'])
        assert saved['snapshot']['payload'] == scientific()
        await store.patch(id, {'revision': 2, 'title': 'Renamed study', 'notes': 'Keep original signal'})
        await store.patch_entry(id, attached['entry']['id'], {'revision': 3, 'title': 'Renamed signal',
                                                              'notes': 'Selected for comparison'})
        archived = await store.read_snapshots(id)
        text = archived['entries'][0]['snapshot_json']
        assert text == jsjson.stringify(source_snapshot())
        assert hashlib.sha256(text.encode('utf-8')).hexdigest() == attached['entry']['snapshot_sha256']
        assert archived['entries'][0]['snapshot']['payload'] == scientific()
        persisted = Path(store.directory) / id / 'snapshots' / f"{attached['entry']['snapshot_sha256']}.json"
        assert persisted.read_text(encoding='utf-8') == text
        assert 'owner_key_hash' not in jsjson.stringify(archived['project'])
    run(main())


def test_queued_mutations_enforce_revisions(tmp_path):
    """check-project-store.mjs:116: two writers of revision 1, one wins."""
    async def main():
        store, created = await fixture(tmp_path)
        id = created['project']['id']
        results = await asyncio.gather(store.patch(id, {'revision': 1, 'title': 'First writer'}),
                                       store.patch(id, {'revision': 1, 'title': 'Second writer'}),
                                       return_exceptions=True)
        assert [isinstance(value, dict) for value in results] == [True, False]
        assert results[1].status == 409
        await store.flush()
        assert store.pending_writes == 0
        current = await store.get(id)
        assert (current['project']['title'], current['project']['revision']) == ('First writer', 2)
    run(main())


def test_detaching_entries_never_deletes_original_snapshots(tmp_path):
    """check-project-store.mjs:129."""
    async def main():
        store, created = await fixture(tmp_path)
        id = created['project']['id']
        attached = await store.attach(id, {'revision': 1, 'kind': 'source'}, source_snapshot(),
                                      {'protocol': 'source-reception/2'})
        await store.detach(id, attached['entry']['id'], 2)
        assert (await store.get(id))['project']['entries'] == []
        assert len(os.listdir(Path(store.directory) / id / 'snapshots')) == 1
        await rejects(store.get_entry(id, attached['entry']['id']), 404)
    run(main())


def test_corrupt_metadata_snapshots_links_and_traversal_fail_closed(tmp_path):
    """check-project-store.mjs:138."""
    async def main():
        store, created = await fixture(tmp_path)
        id = created['project']['id']
        attached = await store.attach(id, {'revision': 1, 'kind': 'source'}, source_snapshot(),
                                      {'protocol': 'source-reception/2'})
        projects = tmp_path / 'projects'
        path = projects / id / 'snapshots' / f"{attached['entry']['snapshot_sha256']}.json"
        path.write_bytes(jsjson.stringify({**source_snapshot(), 'payload': {'altered': True}}).encode('utf-8'))
        await rejects(store.get_entry(id, attached['entry']['id']), 409)
        path.unlink()
        os.symlink(projects / id / 'project.json', path)
        await rejects(store.get_entry(id, attached['entry']['id']), 409)
        await rejects(store.get('../project.json'), 400)
        (projects / id / 'project.json').write_text('{"broken":true}', encoding='utf-8')
        await rejects(store.get(id), 409)
    run(main())


def test_a_linked_project_root_is_refused_rather_than_followed(tmp_path):
    """check-project-store.mjs:151."""
    os.symlink(tmp_path, tmp_path / 'projects')

    async def main():
        store = ProjectStore(str(tmp_path / 'projects'))
        await rejects(store.create({'title': 'Blocked', 'owner_name': 'Researcher'}), 409)
    run(main())


def test_bounded_snapshots_and_export_preflight_refuse_large_data_before_loading_payloads(tmp_path):
    """check-project-store.mjs:158: the oversized snapshot is refused synchronously, before any write is queued."""
    async def main():
        store, created = await fixture(tmp_path)
        id = created['project']['id']
        huge = source_snapshot()
        huge['payload']['large'] = 'x' * PROJECT_LIMITS['snapshot_bytes']
        with pytest.raises(ProjectError) as caught:
            store.attach(id, {'revision': 1, 'kind': 'source'}, huge, {})
        assert caught.value.status == 413 and store.pending_writes == 0
        await store.attach(id, {'revision': 1, 'kind': 'source'}, source_snapshot(), {'protocol': 'source-reception/2'})
        await rejects(store.read_snapshots(id, max_bytes=10), 413)
        assert len((await store.get(id))['project']['entries']) == 1
    run(main())


def test_shutdown_refuses_new_writes_while_flushing_accepted_ones(tmp_path):
    """check-project-store.mjs:167."""
    async def main():
        store, created = await fixture(tmp_path)
        id = created['project']['id']
        accepted = store.patch(id, {'revision': 1, 'notes': 'Final accepted note'})
        store.close()
        await rejects(store.patch(id, {'revision': 1, 'title': 'Too late'}), 503)
        await accepted
        await store.flush()
        assert store.pending_writes == 0
        assert (await store.get(id))['project']['notes'] == 'Final accepted note'
    run(main())


# --- The dropped credentials (check-project-store.mjs :61, :87) --------------------------------------------------

def test_a_project_stores_no_key_and_survives_restart(tmp_path):
    """check-project-store.mjs:61 without credentials: ``access_key`` is a fresh random key that is neither stored
    nor hashed into the record; the owner hash is another key's, nobody holds it; restarts read the same project."""
    async def main():
        store, created = await fixture(tmp_path)
        project, access_key = created['project'], created['access_key']
        assert created['role'] == 'owner'
        assert len(access_key) == 64 and int(access_key, 16) >= 0
        metadata = (tmp_path / 'projects' / project['id'] / 'project.json').read_text(encoding='utf-8')
        record = jsjson.parse(metadata)
        assert access_key not in metadata and sha(access_key) not in metadata
        assert record['viewer_key_hash'] is None and 'creator_network' not in record
        assert len(record['owner_key_hash']) == 64 and record['owner_key_hash'] != sha(access_key)
        restarted = ProjectStore(str(tmp_path / 'projects'))
        assert await restarted.get(project['id']) == {'project': project, 'role': 'owner'}
        assert store.directory == os.path.join(os.path.realpath(tmp_path), 'projects')
        again = await store.create({'title': 'Study B', 'owner_name': 'Researcher'})
        assert again['access_key'] != access_key
    run(main())


def test_sharing_is_not_an_endpoint(tmp_path):
    """check-project-store.mjs:87 and check-project-api.mjs:88: read-only sharing is dropped; ``share`` and
    ``revoke-share`` are 404 ``Project endpoint not found.`` before the project is read, and a project key is
    ignored."""
    async def main():
        service = ProjectService(directory=str(tmp_path / 'projects'))
        status, created, _ = await service.handle('POST', '/api/projects', content_type='application/json',
                                                  body=b'{"title":"Study","owner_name":"Researcher"}')
        assert status == 201
        id = created['project']['id']
        for path in (f'/api/projects/{id}/share', f'/api/projects/{id}/revoke-share', f'/api/projects/{UNKNOWN}/share'):
            for method in ('POST', 'GET'):
                assert await service.handle(method, path, content_type='application/json',
                                            body=b'{"revision":1}') == (404, {'error': ENDPOINT}, {})
        assert (await service.get(id))['project']['revision'] == 1
        await service.aclose()
    run(main())


# --- The list (check-project-api.mjs:43) -------------------------------------------------------------------------

def test_the_list_names_every_project_most_recent_first(tmp_path):
    """check-project-api.mjs:43 for one local user: ``GET /api/projects`` lists the projects (Node answered 405),
    a project reads without a key, a query string is refused, and no answer carries a key or a key hash."""
    async def main():
        times = iter(f'2026-11-25T00:00:0{n}.000Z' for n in range(1, 10))
        store = ProjectStore(str(tmp_path / 'projects'), now=lambda: next(times))
        service = ProjectService(store=store)
        assert await service.handle('GET', '/api/projects') == (200, {'projects': []}, {})
        a = await store.create({'title': 'A', 'owner_name': 'R'})
        b = await store.create({'title': 'B', 'owner_name': 'R', 'notes': 'n'})
        await store.attach(a['project']['id'], {'revision': 1, 'kind': 'source'}, source_snapshot(), {})
        (tmp_path / 'projects' / '0a0a0000-0000-4000-8000-0000000000ff').mkdir(mode=0o700)  # an interrupted create
        (tmp_path / 'projects' / 'notes.txt').write_text('ignored', encoding='utf-8')
        status, value, _ = await service.handle('GET', '/api/projects')
        assert status == 200
        assert value == {'projects': [
            {'id': a['project']['id'], 'title': 'A', 'owner_name': 'R', 'revision': 2,
             'created_at': '2026-11-25T00:00:01.000Z', 'updated_at': '2026-11-25T00:00:04.000Z', 'entry_count': 1},
            {'id': b['project']['id'], 'title': 'B', 'owner_name': 'R', 'revision': 1,
             'created_at': '2026-11-25T00:00:02.000Z', 'updated_at': '2026-11-25T00:00:02.000Z', 'entry_count': 0}]}
        restored = await service.handle('GET', f"/api/projects/{b['project']['id']}")
        assert restored == (200, {'project': b['project'], 'role': 'owner'}, {})
        assert (await service.handle('GET', '/api/projects', query=True))[0] == 400
        assert (await service.handle('GET', f"/api/projects/{b['project']['id']}", query=True))[0] == 400
        for answer in (value, restored[1]):
            text = jsjson.stringify(answer)
            assert 'key_hash' not in text and a['access_key'] not in text and b['access_key'] not in text
        # Same update time: by identifier.
        clone = await store.create({'title': 'C', 'owner_name': 'R'})
        record = jsjson.parse((tmp_path / 'projects' / clone['project']['id'] / 'project.json').read_text('utf-8'))
        record['updated_at'] = '2026-11-25T00:00:04.000Z'
        (tmp_path / 'projects' / clone['project']['id'] / 'project.json').write_text(jsjson.stringify(record), 'utf-8')
        listed = [row['id'] for row in (await store.list())['projects']]
        assert listed[:2] == sorted([a['project']['id'], clone['project']['id']]) and listed[2] == b['project']['id']
        # Any other unreadable project refuses the list.
        (tmp_path / 'projects' / b['project']['id'] / 'project.json').write_text('{"broken":true}', 'utf-8')
        assert await service.handle('GET', '/api/projects') == (
            409, {'error': 'Project metadata failed integrity checks.'}, {})
        await service.aclose()
    run(main())


# --- check-project-api.mjs ---------------------------------------------------------------------------------------

API_RECORD, SIGNAL = 'b' * 64, 'c' * 64
API_RESULT = {'schema_version': 'source-reception/2',
              'request': {'record_id': API_RECORD, 'mode': 'single_source', 'source_index': 2, 'seed': 2026},
              'layout': {'xyzMm': [[1, 2, 3]]}, 'waveforms': {'time_s': [0, 0.1], 'baseline': [1.252e-12, -9.13e-8]},
              'provenance': {'threads': 1, 'source': 'validated-cache'}, 'qa': {'residual': 1e-13}}


class ApiStandIns(StandIns):
    """check-project-api.mjs's fixture: one completed receipt, a counted saved-result read, one layout."""

    def __init__(self, state: dict):
        super().__init__(state)
        self.saved_reads = 0

    async def saved_result(self, key: str, request: Any) -> Any:
        self.saved_reads += 1
        if self.state.get('cache_removed'):
            raise Exception('Cache removed')
        return await super().saved_result(key, request)


class Api:
    def __init__(self, base: Path):
        self.root = base
        self.receipt = {'id': '7e7e0000-0000-4000-8000-000000000001', 'kind': 'source-reception',
                        'status': 'completed', 'key': SIGNAL, 'request': API_RESULT['request']}
        self.state = {
            'records': {API_RECORD: {'id': API_RECORD, 'status': 'completed', 'dataset_id': 'cache',
                                     'layout': {'xyzMm': [[3.5, -7, 11]]}, 'region_count': 1,
                                     'metrics': {'field_relative': 0.95}}},
            'tasks': [self.receipt], 'saved': {SIGNAL: API_RESULT}}
        self.stand = ApiStandIns(self.state)

        async def bundle(root, record, python):
            return {'schema': 'eeg-reproducibility-bundle/1', 'record_id': record['id'], 'record': record,
                    'original_record': {'result': {'request': {'seed': 2026}, 'fields': [1e-14]}}}
        self.service = ProjectService(directory=str(base / 'projects'), library=self.stand, root=str(base),
                                      python='unused', bundle=bundle, editor=self.stand, queue=self.stand,
                                      annotations=StandInAnnotations(self.state))

    async def call(self, path: str, method: str = 'GET', body: Any = UNDEFINED, raw: bytes | None = None,
                   if_match: str | None = None) -> tuple[int, Any, dict]:
        data = raw if raw is not None else b'' if body is UNDEFINED else jsjson.stringify(body).encode('utf-8')
        return await self.service.handle(method, path.split('?')[0], query='?' in path,
                                         content_type='application/json', body=data, if_match=if_match)

    async def __aenter__(self) -> 'Api':
        status, value, _ = await self.call('/api/projects', 'POST', {'title': 'Study', 'owner_name': 'Researcher'})
        assert status == 201
        self.project, self.access_key = value['project'], value['access_key']
        self.path = f"/api/projects/{self.project['id']}"
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.service.aclose()


def test_research_export_preserves_saved_science(tmp_path):
    """check-project-api.mjs:53 at the service: the export is a valid delivery of the saved copy, read without the
    scientific cache, with the attachment header, within the delivery bound (the server's ``ProjectDelivery``)."""
    from eeglayoutlab.server.delivery import validate_research_delivery

    (tmp_path / 'data').mkdir()
    (tmp_path / 'configs' / 'runtime').mkdir(parents=True)
    (tmp_path / 'data' / 'manifest.json').write_text(jsjson.stringify(
        {'schema_version': 'eeglayoutlab-data-bundle/1', 'bundle_id': 'fixture-data'}), 'utf-8')
    (tmp_path / 'configs' / 'runtime' / 'manifest.json').write_text(jsjson.stringify(
        {'schema': 'eeglayoutlab-runtime-lock/1'}), 'utf-8')

    async def main():
        async with Api(tmp_path) as api:
            attached = await api.call(api.path + '/entries', 'POST',
                                      {'revision': 1, 'kind': 'source', 'receipt_id': api.receipt['id']})
            assert attached[0] == 201
            reads = api.stand.saved_reads
            status, exported, headers = await api.call(api.path + '/export')
            assert status == 200 and validate_research_delivery(exported) is True
            assert headers == {'Content-Disposition': f"attachment; filename=\"eeg-research-{api.project['id']}.json\""}
            assert jsjson.parse(exported['files'][1]['content'])['payload'] == API_RESULT
            assert api.stand.saved_reads == reads, 'Export accessed the old scientific cache again.'
            assert api.access_key not in jsjson.stringify(exported)
            api.service.delivery.maximum_bytes = 100
            assert (await api.call(api.path + '/export'))[0] == 413
            api.service.delivery.maximum_bytes = 32 * 1024 * 1024
            assert (await api.call(api.path + '/export'))[0] == 200
    run(main())


def test_project_writes_need_bounded_json_and_current_revisions(tmp_path):
    """check-project-api.mjs:77 at the service (the policy and token refusals are the routes')."""
    async def main():
        async with Api(tmp_path) as api:
            assert (await api.call(api.path, 'PATCH', raw=b'{broken'))[0] == 400
            assert (await api.call(api.path, 'PATCH', {'revision': 1, 'notes': 'x' * 70000}))[:2] == (
                413, {'error': 'Project request is too large.'})
            assert (await api.call(api.path, 'PATCH', {'revision': 1, 'title': 'Renamed'}))[0] == 200
            assert (await api.call(api.path, 'PATCH', {'revision': 1, 'title': 'Stale'}))[:2] == (
                409, {'error': 'Project changed. Reload it before saving.'})
            assert (await api.call(api.path, 'PATCH', {'revision': 2, 'identity': {'fake': True}}))[:2] == (
                400, {'error': 'Invalid project fields.'})
    run(main())


def test_saved_source_copies_survive_receipt_pruning_and_cache_loss(tmp_path):
    """check-project-api.mjs:98."""
    async def main():
        async with Api(tmp_path) as api:
            status, attached, _ = await api.call(api.path + '/entries', 'POST', {
                'revision': 1, 'kind': 'source', 'receipt_id': api.receipt['id'], 'title': 'Signal case'})
            assert status == 201 and api.stand.saved_reads == 1
            api.state['tasks'] = []
            api.state['cache_removed'] = True
            entry = await api.call(api.path + '/entries/' + attached['entry']['id'])
            assert entry[0] == 200 and entry[1]['snapshot']['payload'] == API_RESULT
            assert entry[1]['entry']['record_id'] == SIGNAL
            assert (await api.call(api.path + '/entries/' + attached['entry']['id'], 'PATCH', {
                'revision': 2, 'title': 'Renamed case', 'notes': 'Original values retained'}))[0] == 200
            assert (await api.call(api.path + '/entries/' + attached['entry']['id']))[1]['snapshot']['payload'] \
                == API_RESULT
    run(main())


def test_source_attachment_refuses_foreign_incomplete_or_client_data_before_reading_the_cache(tmp_path):
    """check-project-api.mjs:110: a receipt the queue does not give (another browser's in Node) is 404, a running
    one 409, scientific data in the body 400, and no saved result is read."""
    async def main():
        async with Api(tmp_path) as api:
            path = api.path + '/entries'
            data = {'revision': 1, 'kind': 'source', 'receipt_id': api.receipt['id']}
            assert (await api.call(path, 'POST', {**data, 'receipt_id': '7e7e0000-0000-4000-8000-000000000002'}))[:2] \
                == (404, {'error': NOT_OWNED})
            api.receipt['status'] = 'running'
            assert (await api.call(path, 'POST', data))[:2] == (409, {'error': 'Only completed signal results can be saved.'})
            assert (await api.call(path, 'POST', {**data, 'payload': API_RESULT}))[:2] == (
                400, {'error': 'Invalid project attachment.'})
            assert api.stand.saved_reads == 0
    run(main())


def test_layout_attachment_loads_the_trusted_archive_and_detach_keeps_the_science(tmp_path):
    """check-project-api.mjs:119."""
    async def main():
        async with Api(tmp_path) as api:
            assert (await api.call(api.path + '/entries', 'POST', {'revision': 1, 'kind': 'layout',
                                                                    'record_id': 'd' * 64}))[:2] == (
                404, {'error': 'Choose a completed layout evaluation.'})
            status, attached, _ = await api.call(api.path + '/entries', 'POST',
                                                 {'revision': 1, 'kind': 'layout', 'record_id': API_RECORD})
            assert status == 201
            saved = (await api.call(api.path + '/entries/' + attached['entry']['id']))[1]
            assert saved['snapshot']['payload']['schema'] == 'eeg-reproducibility-bundle/1'
            assert saved['snapshot']['payload']['record']['id'] == API_RECORD
            assert (await api.call(api.path + '/entries/' + attached['entry']['id'], 'DELETE', if_match='2'))[0] == 200
            assert (await api.call(api.path))[1]['project']['entries'] == []
            files = os.listdir(tmp_path / 'projects' / api.project['id'] / 'snapshots')
            assert files == [f"{attached['entry']['snapshot_sha256']}.json"]
    run(main())


# --- check-project-workflow.mjs:96, check-coordinate-review.mjs :139 and :161 ----------------------------------------

def test_layout_summaries_mark_whether_signal_simulation_accepts_the_layout(tmp_path):
    """check-project-workflow.mjs:96."""
    xyz = [[0, 0, 80]] * 64
    spatial = {'kind': 'spatial', 'rho': 0.5, 'length_mm': 20}

    def record(id: str, **extra: Any) -> dict:
        return {'id': id, 'status': 'completed', 'dataset_id': 'cache', 'layout': {'xyzMm': xyz}, 'region_count': 4,
                'request': {'region_count': 4}, **extra}
    records = {'f' * 64: record('f' * 64), '9' * 64: record('9' * 64, request={'region_count': 4, 'noise_model': spatial}),
               '8' * 64: record('8' * 64, layout={'xyzMm': xyz[1:]})}

    class Library:
        root = '/unused'

        async def get(self, id):
            return records.get(id)

    async def bundle(root, value, python):
        return {'record': value}

    service = ProjectService(directory=str(tmp_path / 'projects'), library=Library(), python='unused', bundle=bundle,
                             delivery=object())

    async def simulation(record_id: str) -> Any:
        return (await service.resolve_snapshot({'kind': 'layout', 'record_id': record_id}))['summary']['simulation']
    assert run(simulation('f' * 64)) is True
    assert run(simulation('9' * 64)) is False
    assert run(simulation('8' * 64)) is False
    summary = run(service.resolve_snapshot({'kind': 'layout', 'record_id': 'f' * 64}))['summary']
    assert list(summary) == ['protocol', 'electrode_count', 'region_count', 'simulation']


SOURCE_METADATA = {'schema': 'electrode-coordinate-source/1', 'format': 'bids-electrodes/1',
                   'electrodes_file': 'electrodes.tsv', 'coordsystem_file': 'coordsystem.json',
                   'coordinate_system': 'ernie_native_mm', 'unit': 'mm',
                   'coordinate_system_description': 'Ernie native space, mm', 'region_index_base': 0,
                   'region_description': 'Two regions, from the file'}


def test_source_declarations_survive_project_snapshots_without_changing_the_scientific_payload(tmp_path):
    """check-coordinate-review.mjs:139, the project half: a named evaluation's annotation (with its coordinate
    source) is resolved, stored and read back by a restarted store with the payload byte for byte; the delivery
    built from the copies validates (the TypeScript design export is the webapp's)."""
    from eeglayoutlab.jobs.annotations import WORKSPACE_ANNOTATIONS, ElectrodeAnnotations
    from eeglayoutlab.jobs.design_result import normalize_design_request
    from eeglayoutlab.server.delivery import build_research_delivery, validate_research_delivery

    root = Path(os.path.realpath(tmp_path))
    design = {'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm',
              'name': 'Original scientific design name',
              'xyz_mm': [[(i % 8) * 6 + 1.42e-14, (i // 8) * 6, -112.31415926535898] for i in range(64)],
              'region_indices': [i % 2 for i in range(64)]}
    names = [' Fp1, "left" ' if i == 0 else f'电极{i + 1}' for i in range(64)]
    request = normalize_design_request({'action': 'evaluate', 'design': design, 'radius_mm': 6, 'seed': 42})
    key = jsjson.sha256_hex({'request': request, 'identity': {'fixed': True}})
    annotations = ElectrodeAnnotations([(str(root), WORKSPACE_ANNOTATIONS)], writable=True)
    created_annotation = annotations.create({'request': request, 'key': key, 'electrode_names': names,
                                             'source_metadata': SOURCE_METADATA})
    record = {'id': key, 'dataset_id': 'design_evaluation', 'label': design['name'], 'status': 'completed',
              'region_count': 2, 'layout': {'xyzMm': design['xyz_mm'], 'regionIndices': design['region_indices']},
              'provenance': {}}
    science = {'schema': 'eeg-reproducibility-bundle/1', 'record': record,
               'original_record': {'request': request, 'values': [1 / 3, -1e-18, 1.0000000000000002]}}
    before = jsjson.stringify(science)
    original_file = root / 'original-scientific.json'
    original_file.write_text(before, encoding='utf-8')

    class Library:
        async def get(self, id):
            return record

    async def bundle(_root, _record, _python):
        return science

    async def main():
        service = ProjectService(directory=str(root / 'projects'), library=Library(), root=str(root), python='unused',
                                 bundle=bundle, annotations=annotations)
        data = {'revision': 1, 'kind': 'layout', 'record_id': key, 'annotation_id': created_annotation['id']}
        resolved = await service.resolve_snapshot(data)
        assert resolved['snapshot']['payload'] is science
        assert resolved['snapshot']['electrode_annotation']['source_metadata'] == SOURCE_METADATA
        created = await service.store.create({'title': 'Source declarations', 'owner_name': 'Researcher'})
        await service.store.attach(created['project']['id'], data, resolved['snapshot'], resolved['summary'])
        copies = await ProjectStore(service.store.directory).read_snapshots(created['project']['id'])
        delivery = build_research_delivery(copies)
        assert validate_research_delivery(delivery) is True
        saved = jsjson.parse(delivery['files'][1]['content'])
        assert saved['electrode_annotation']['source_metadata'] == SOURCE_METADATA
        assert saved['electrode_annotation']['electrode_names'] == names
        assert jsjson.stringify(saved['payload']) == before
        assert original_file.read_text(encoding='utf-8') == before
        await service.aclose()
    run(main())


def test_signal_summaries_copy_only_verified_request_fields(tmp_path):
    """check-coordinate-review.mjs:161: omitted fields stay absent, arrays are copies, the payload is unchanged."""
    record_id, key = 'a' * 64, 'b' * 64
    xyz = [[(i % 8) * 6 + 1.42e-14, (i // 8) * 6, -112.31415926535898] for i in range(64)]
    requests = [{'record_id': record_id, 'mode': 'single_source', 'source_index': 0, 'seed': 0},
                {'record_id': record_id, 'mode': 'multi_source', 'brain_region': 'frontal', 'seed': 2026},
                {'record_id': record_id, 'mode': 'cross_region', 'brain_regions': ['frontal', 'parietal'], 'seed': 14},
                {'record_id': record_id}]
    for request in requests:
        payload = {'schema_version': 'source-reception/2', 'request': request, 'layout': {'xyzMm': xyz},
                   'source': {'generation_source_indices': [7, 8], 'source_regions': ['occipital', None]}}
        before = jsjson.stringify(payload)

        class Queue:
            adapters = {}

            def own(self, id, kind):
                return {'key': key, 'request': request, 'status': 'completed'}

        class Adapter:
            async def saved_result(self, *_):
                return payload

        queue = Queue()
        queue.adapters = {'source-reception': Adapter()}
        service = ProjectService(directory=str(tmp_path / 'projects'), queue=queue, delivery=object())
        resolved = run(service.resolve_snapshot({'kind': 'source', 'receipt_id': '0f0f0f0f-0000-4000-8000-000000000001'}))
        assert resolved['snapshot']['payload'] is payload and resolved['summary']['parent_id'] == record_id
        assert resolved['summary']['mode'] == request.get('mode', 'legacy')
        for field in ('brain_region', 'brain_regions', 'source_index', 'seed'):
            assert (field in resolved['summary']) == (field in request)
            if field in request:
                assert resolved['summary'][field] == request[field]
        assert 'source_indices' not in resolved['summary'] and 'source_regions' not in resolved['summary']
        if 'brain_regions' in request:
            assert resolved['summary']['brain_regions'] is not request['brain_regions']
            resolved['summary']['brain_regions'].append('changed UI metadata')
        assert jsjson.stringify(payload) == before


# --- Deliberate differences --------------------------------------------------------------------------------------

def test_unused_projects_are_never_pruned_and_counts_are_not_capped(tmp_path):
    """Node removed a never-edited empty project after 30 days on the next create and capped the projects; the
    workspace keeps every project."""
    projects = tmp_path / 'projects'
    old = crafted_project('0b0b0000-0000-4000-8000-000000000001', created_at='2020-01-01T00:00:00.000Z',
                          updated_at='2020-01-01T00:00:00.000Z')
    projects.mkdir()
    (projects / old['id'] / 'snapshots').mkdir(parents=True)
    (projects / old['id'] / 'project.json').write_text(jsjson.stringify(old), encoding='utf-8')

    async def main():
        store = ProjectStore(str(projects))
        for n in range(3):
            await store.create({'title': f'P{n}', 'owner_name': 'R'})
        assert (await store.get(old['id']))['project']['title'] == 'Crafted'
        assert len((await store.list())['projects']) == 4
    run(main())


def test_metadata_times_are_iso_date_times(tmp_path):
    """Node's ``Date.parse`` also took other spellings ('Tue, 24 Nov 2026 00:00:00 GMT'); the workspace takes
    ISO 8601 date-time strings, as slice 8's studies do, and every time it writes is ``toISOString()``."""
    base = crafted_project('0b0b0000-0000-4000-8000-000000000001')
    assert validate_record(base, base['id']) is base
    for value in ('Tue, 24 Nov 2026 00:00:00 GMT', 'November 24, 2026', '2026/11/24'):
        with pytest.raises(ProjectError) as caught:
            validate_record({**base, 'created_at': value}, base['id'])
        assert (caught.value.status, caught.value.message) == (409, 'Project metadata failed integrity checks.')


def test_public_project_reads_like_node(tmp_path):
    record = crafted_project('0b0b0000-0000-4000-8000-000000000001', creator_network='d' * 64, extra={'x': 1})
    value = public_project(record)
    assert list(value) == ['schema', 'id', 'title', 'owner_name', 'notes', 'revision', 'created_at', 'updated_at',
                           'entries', 'workflow']
    assert value['workflow'] == {'reference_entry_id': None, 'candidate_entry_id': None, 'comparison_href': None}
    value['entries'].append(1)
    assert record['entries'] == []


def test_building_the_project_service_loads_no_library_module(tmp_path):
    """The application builds ``ProjectService`` at start; the job modules load on the first request."""
    script = (
        'import sys\n'
        'from eeglayoutlab.server.workspace_projects import ProjectService\n'
        f"service = ProjectService(directory={str(tmp_path / 'projects')!r})\n"
        "print(sorted(name for name in sys.modules if name.startswith('eeglayoutlab.jobs.')))\n")
    loaded = subprocess.run([sys.executable, '-c', script], check=True, capture_output=True, text=True, cwd=ROOT,
                            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')}).stdout
    for name in ('library', 'bundle', 'annotations', 'radius', 'editor_records', 'reception_records', 'design_heads'):
        assert f"'eeglayoutlab.jobs.{name}'" not in loaded, loaded


def test_the_service_answers_methods_paths_and_bodies_as_node(tmp_path):
    """The middleware's order without Node: method, query, the collection, the path, the project, the body."""
    async def main():
        service = ProjectService(directory=str(tmp_path / 'projects'))
        status, created, _ = await service.handle('POST', '/api/projects', content_type='application/json; charset=utf-8',
                                                  body=b'{"title":"S","owner_name":"R"}')
        assert status == 201
        path = f"/api/projects/{created['project']['id']}"
        assert await service.handle('PUT', path) == (405, {'error': 'Unsupported project method.'}, {})
        assert await service.handle('HEAD', '/api/projects', query=True) == (405, {'error': 'Unsupported project method.'}, {})
        assert await service.handle('DELETE', '/api/projects') == (
            405, {'error': 'Projects are opened with their identifier and credential.'}, {})
        assert await service.handle('POST', '/api/projects', content_type=None) == (415, {'error': 'JSON is required.'}, {})

        async def chunks():
            yield b'{"title":"'
            yield b'x' * BODY_LIMIT
        assert await service.handle('POST', '/api/projects', content_type='application/json', body=chunks()) == (
            413, {'error': 'Project request is too large.'}, {})

        async def padded(size: int):
            yield b'{"title":""}'
            yield b' ' * (size - 12)
        for size, answer in ((65536, (400, {'error': 'Invalid project title.'}, {})),
                             (65537, (413, {'error': 'Project request is too large.'}, {}))):
            for body in (b'{"title":""}' + b' ' * (size - 12), padded(size)):
                assert await service.handle('POST', '/api/projects', content_type='application/json', body=body) == answer
        assert await service.handle('POST', path) == (405, {'error': 'Unsupported project operation.'}, {})
        assert await service.handle('GET', path + '/') == (404, {'error': ENDPOINT}, {})
        assert await service.handle('GET', f'/api/projects/{UNKNOWN}') == (404, {'error': 'Project not found.'}, {})
        # If-Match: one quote off each end, then Number().
        for value, status in (('"1"', 404), ('2', 409), ('"abc"', 400), ('', 400), ('""1""', 400), (' 1 ', 404)):
            answer = await service.handle('DELETE', path + '/entries/' + UNKNOWN, if_match=value)
            assert answer[0] == status, (value, answer)

        def blocked():
            raise ResourceError('Resource blocked', 503, retry_after=7)
        service.before_write = blocked
        assert await service.handle('PATCH', path, content_type='application/json', body=b'{"revision":1,"notes":""}') == (
            503, {'error': 'Resource blocked', 'code': 'resource_unavailable'}, {'Retry-After': '7'})
        assert (await service.handle('GET', path))[0] == 200
        await service.aclose()
        assert await service.handle('PATCH', path, content_type='application/json', body=b'{"revision":1,"notes":""}') == (
            503, {'error': 'Project store is stopping.'}, {})
    run(main())


# --- Parity with Node ----------------------------------------------------------------------------------------------

def _diff(label: str, node: Any, python: Any) -> None:
    assert python == node, f'{label}\nnode:   {jsjson.stringify(node)[:1500]}\npython: {jsjson.stringify(python)[:1500]}'


def compare_store(cases: list[dict], tmp_path: Path) -> dict:
    """Runs the store cases in Node and in Python, each in its own directory, and compares every step and the files.
    Returns the Node output."""
    node_cases, python_cases = [], []
    for case in cases:
        for side, out in (('node', node_cases), ('python', python_cases)):
            (tmp_path / side / case['id']).mkdir(parents=True)
            out.append({**case, 'directory': str(tmp_path / side / case['id'] / 'projects')})
    output = run_driver('store', node_cases, tmp_path)
    for case in python_cases:
        node = output['by_id'][case['id']]
        python = python_store(jsjson.parse(jsjson.stringify(case)))
        expected = node_records(node)
        assert len(python['records']) == len(expected)
        for index, (left, right) in enumerate(zip(expected, python['records'])):
            _diff(f"{case['id']} step {index + 1} {case['steps'][index][0]}", left, right)
        _diff(f"{case['id']} files", node['tree'], python['tree'])
    return output


def compare_service(cases: list[dict], tmp_path: Path) -> dict:
    node_cases, python_cases = [], []
    for case in cases:
        for side, out in (('node', node_cases), ('python', python_cases)):
            (tmp_path / side / case['id']).mkdir(parents=True)
            out.append({**case, 'directory': str(tmp_path / side / case['id'] / 'projects')})
    output = run_driver('service', node_cases, tmp_path)
    for case in python_cases:
        node = output['by_id'][case['id']]
        python = python_service(jsjson.parse(jsjson.stringify(case)))
        assert len(python['records']) == len(node['records'])
        for index, (left, right) in enumerate(zip(node['records'], python['records'])):
            _diff(f"{case['id']} step {index + 1} {case['steps'][index][:3]}", left, right)
        _diff(f"{case['id']} files", node['tree'], python['tree'])
    return output


A1 = annotation(R1)
A2 = annotation(R2)
S_L1, S_L2 = snapshot('layout', R1), snapshot('layout', R2, annotation=A2)
S_E = snapshot('editor', R3, payload={'record': {'key': R3}, 'cache': {'values': [1 / 3, 1e21, -0.0, 5e-324]}})
S_S = snapshot('source', R4, payload=scientific(7))


def lifecycle_case() -> dict:
    href = f'/decision?a={R2}&b={R1}&ar=87&thresholdMode=custom&sensitivity=63&localization=52&p90=28.5'
    return {'id': 'lifecycle', 'steps': [
        ['create', {'title': ' Study A ', 'owner_name': 'Researcher', 'notes': 'Original study 研究 😀'}],
        ['get', '$P1'],
        ['patch', '$P1', {'revision': 1, 'title': 'Renamed', 'notes': ' n\tm \r\n'}],
        ['attach', '$P1', {'revision': 2, 'kind': 'layout'}, S_L1, {'protocol': 'cache', 'electrode_count': 64}],
        ['attach', '$P1', {'revision': 3, 'kind': 'layout', 'annotation_id': A2['id'], 'title': 'Named', 'notes': 'N'},
         S_L2, {'protocol': 'cache', 'electrode_count': 64, 'region_count': None}],
        ['attach', '$P1', {'revision': 4, 'kind': 'editor', 'record_id': R3}, S_E,
         {'protocol': 'electrode-editor-result/1', 'parent_id': R1}],
        ['attach', '$P1', {'revision': 5, 'kind': 'source', 'receipt_id': 'x'}, S_S,
         {'protocol': 'source-reception/2', 'seed': 7, 'brain_regions': ['frontal']}],
        ['attach', '$P1', {'revision': 6, 'kind': 'layout'}, S_L1, {'protocol': 'cache'}],
        ['detach', '$P1', '$E1', 6],
        ['attach', '$P1', {'revision': 7, 'kind': 'layout', 'title': None, 'notes': None}, S_L1, {'protocol': 'cache'}],
        ['patch_entry', '$P1', '$E2', {'revision': 8, 'title': ' T ', 'notes': 'x'}],
        ['workflow', '$P1', {'reference_entry_id': '$E2', 'candidate_entry_id': '$E5', 'comparison_href': href}],
        ['get_entry', '$P1', '$E2'],
        ['read', '$P1'],
        ['read', '$P1', 10],
        ['read', '$P1', '100000'],
        ['read', '$P1', 1.5],
        ['read', '$P1', {'$js': 'undefined'}],
        ['snapshot', '$P1', 0],
        ['detach', '$P1', '$E5', 10],
        ['load', '$P1'],
        ['get_entry', '$P1', '$E1'],
        ['patch', '$P1', {'revision': 11, 'workflow': {'reference_entry_id': None, 'candidate_entry_id': None}}],
        ['patch', '$P1', {'revision': 12, 'owner_name': ' New owner ', 'title': 'T', 'notes': ''}],
        ['restart'],
        ['get', '$P1'],
        ['flush'],
    ]}


def refusals_case() -> dict:
    other = snapshot('layout', R1, annotation=A1)
    return {'id': 'refusals', 'steps': [
        ['create', {'title': 'A', 'owner_name': 'B', 'extra': 1}],
        ['create', {'title': '', 'owner_name': 'B'}],
        ['create', {'title': '   ', 'owner_name': 'B'}],
        ['create', {'title': 'x' * 201, 'owner_name': 'B'}],
        ['create', {'title': 'x' * 200, 'owner_name': 'y' * 121}],
        ['create', {'title': 'A', 'owner_name': 'B', 'notes': 'a\x00b'}],
        ['create', []],
        ['create', None],
        ['create', {'title': 'A', 'owner_name': 'B', 'notes': 5}],
        ['create', {'title': 'A', 'owner_name': 'B', 'notes': None}],
        ['get', '../project.json'],
        ['get', UNKNOWN],
        ['get', 5],
        ['patch', '$P1', {'revision': 1}],
        ['patch', '$P1', {'revision': 1, 'title': 'A', 'identity': {}}],
        ['patch', '$P1', {'title': 'A'}],
        ['patch', '$P1', {'revision': 2, 'title': 'A'}],
        ['patch', '$P1', {'revision': 1, 'title': 5}],
        ['patch', '$P1', {'revision': 1, 'owner_name': ''}],
        ['patch', '$P1', {'revision': 1, 'notes': None}],
        ['patch', '$P1', {'revision': '1', 'title': 'A'}],
        ['patch', '$P1', {'revision': 1, 'workflow': None}],
        ['patch', '$P1', []],
        ['patch', UNKNOWN, {'revision': 1, 'title': 'A'}],
        ['patch', 'nope', {'revision': 1, 'title': 'A'}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout'}, snapshot('editor', R1), {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout', 'extra': 1}, S_L1, {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout'}, S_L1, []],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout'}, {**S_L1, 'record_id': 'X' * 64}, {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout'}, {**S_L1, 'payload': []}, {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout'}, {**S_L1, 'schema': 'other'}, {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout', 'annotation_id': A2['id']}, S_L1, {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout'}, other, {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout', 'annotation_id': A2['id']}, other, {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'editor', 'annotation_id': A1['id']},
         snapshot('editor', R1, annotation=A1), {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout', 'annotation_id': A1['id']},
         snapshot('layout', R1, annotation={**A1, 'electrode_names': A1['electrode_names'][:63]}), {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout', 'title': ''}, S_L1, {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout', 'notes': 'x' * 8001}, S_L1, {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout', 'title': None}, S_L1, {'protocol': 'cache'}],
        ['attach', '$P1', {'revision': 2, 'kind': 'layout'}, S_L1, {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'source'}, S_S, {}],
        ['attach', '$P1', {'kind': 'source'}, S_S, {}],
        ['attach', UNKNOWN, {'revision': 1, 'kind': 'source'}, S_S, {}],
        ['attach', '$P1', {'revision': 2, 'kind': 'layout', 'annotation_id': A1['id']}, other, {'protocol': 'cache'}],
        ['patch_entry', '$P1', 'not-a-uuid', {'revision': 3, 'title': 'x'}],
        ['patch_entry', '$P1', '$E1', {'revision': 3}],
        ['patch_entry', '$P1', '$E1', {'revision': 3, 'title': ''}],
        ['patch_entry', '$P1', '$E1', {'revision': 3, 'notes': None}],
        ['patch_entry', '$P1', '$E1', {'revision': 3, 'kind': 'x'}],
        ['patch_entry', '$P1', UNKNOWN, {'revision': 3, 'title': 'x'}],
        ['patch_entry', '$P1', '$E1', {'revision': 3, 'title': 'ok', 'notes': ' trimmed '}],
        ['detach', '$P1', 'bad', 4],
        ['detach', '$P1', UNKNOWN, 4],
        ['detach', '$P1', '$E1', '4'],
        ['detach', '$P1', '$E1', 0],
        ['detach', '$P1', '$E1', {'$js': 'NaN'}],
        ['get_entry', '$P1', 'bad'],
        ['get_entry', '$P1', UNKNOWN],
        ['get_entry', UNKNOWN, '$E1'],
        ['read', '$P1', 0],
        ['read', UNKNOWN],
        ['detach', '$P1', '$E1', 4],
        ['flush'],
    ]}


def limits_case() -> dict:
    steps: list = [['create', {'title': 'Limits', 'owner_name': 'R'}]]
    for n in range(100):
        steps.append(['attach', '$P1', {'revision': n + 1, 'kind': 'source'}, snapshot('source', f'{n:064x}'), {}])
    steps += [
        ['attach', '$P1', {'revision': 101, 'kind': 'source'}, snapshot('source', 'f' * 64), {}],
        ['detach', '$P1', '$E1', 101],
        ['attach', '$P1', {'revision': 102, 'kind': 'source'}, snapshot('source', 'f' * 64), {}],
        ['attach', '$P1', {'revision': 102, 'kind': 'source'}, snapshot('source', f'{0:064x}'), {}],
        ['load', '$P1'],
    ]
    return {'id': 'limits', 'steps': steps}


def files_case() -> dict:
    """Tampered, linked and unexpected files under the store."""
    data = jsjson.stringify(S_S).encode('utf-8')
    digest = hashlib.sha256(data).hexdigest()
    snap = f'$P1/snapshots/{digest}.json'
    altered = jsjson.stringify({**S_S, 'payload': {'altered': True}})
    same_length = data.replace(b'"seed":7', b'"seed":8')
    temporary = f"$P1/snapshots/{'d' * 64}.json.0f0f0f0f-0000-4000-8000-000000000001.tmp"
    return {'id': 'files', 'steps': [
        ['create', {'title': 'Files', 'owner_name': 'R'}],
        ['attach', '$P1', {'revision': 1, 'kind': 'source'}, S_S, {}],
        ['write', snap, b64(altered)],
        ['get_entry', '$P1', '$E1'],
        ['write', snap, base64.b64encode(same_length).decode('ascii')],
        ['get_entry', '$P1', '$E1'],
        ['rm', snap],
        ['get_entry', '$P1', '$E1'],
        ['symlink', '../project.json', snap],
        ['get_entry', '$P1', '$E1'],
        ['read', '$P1'],
        ['rm', snap],
        ['write', snap, base64.b64encode(data).decode('ascii')],
        ['get_entry', '$P1', '$E1'],
        ['write', '$P1/snapshots/unexpected-file', b64('unrelated')],
        ['attach', '$P1', {'revision': 2, 'kind': 'source'}, snapshot('source', 'e' * 64), {}],
        ['rm', '$P1/snapshots/unexpected-file'],
        ['write', temporary, b64('{"incomplete":')],
        ['attach', '$P1', {'revision': 2, 'kind': 'source'}, snapshot('source', 'e' * 64), {}],
        ['write', f"$P1/snapshots/{'d' * 64}.json.aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.tmp", b64('x')],
        ['attach', '$P1', {'revision': 3, 'kind': 'source'}, snapshot('source', '9' * 64), {}],
        ['rm', f"$P1/snapshots/{'d' * 64}.json.aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.tmp"],
        ['mkdir', f"$P1/snapshots/{'e' * 64}.json"],
        ['attach', '$P1', {'revision': 3, 'kind': 'source'}, snapshot('source', '9' * 64), {}],
        ['rm', f"$P1/snapshots/{'e' * 64}.json"],
        ['link', snap, f"$P1/snapshots/{'f' * 64}.json"],
        ['attach', '$P1', {'revision': 3, 'kind': 'source'}, snapshot('source', '9' * 64), {}],
        ['get_entry', '$P1', '$E1'],
        ['rm', f"$P1/snapshots/{'f' * 64}.json"],
        ['attach', '$P1', {'revision': 3, 'kind': 'source'}, snapshot('source', '9' * 64), {}],
        ['create', {'title': 'Linked', 'owner_name': 'R'}],
        ['rename', '$P2', 'linked-real'],
        ['symlink', 'linked-real', '$P2'],
        ['get', '$P2'],
        ['patch', '$P2', {'revision': 1, 'title': 'x'}],
        ['rm', '$P2'],
        ['rename', 'linked-real', '$P2'],
        ['rename', '$P2/snapshots', '$P2/snapshots-real'],
        ['symlink', 'snapshots-real', '$P2/snapshots'],
        ['attach', '$P2', {'revision': 1, 'kind': 'source'}, S_S, {}],
        ['rm', '$P2/snapshots'],
        ['attach', '$P2', {'revision': 1, 'kind': 'source'}, S_S, {}],
        ['rename', '$P2/snapshots-real', '$P2/snapshots'],
        ['link', '$P1/project.json', 'p1-copy.json'],
        ['get', '$P1'],
        ['patch', '$P1', {'revision': 3, 'title': 'x'}],
        ['rm', 'p1-copy.json'],
        # The save itself refuses a metadata path that changed after the load (hard link, symbolic link,
        # directory) and writes one that disappeared.
        ['resave', '$P1', [['link', '$P1/project.json', 'p1-copy.json']]],
        ['rm', 'p1-copy.json'],
        ['resave', '$P1', [['rename', '$P1/project.json', '$P1/real.json'], ['symlink', 'real.json', '$P1/project.json']]],
        ['rm', '$P1/project.json'],
        ['rename', '$P1/real.json', '$P1/project.json'],
        ['resave', '$P1', [['rename', '$P1/project.json', '$P1/real.json'], ['mkdir', '$P1/project.json']]],
        ['rm', '$P1/project.json'],
        ['rename', '$P1/real.json', '$P1/project.json'],
        ['resave', '$P1', [['rm', '$P1/project.json']]],
        ['load', '$P1'],
        ['rename', '$P1/project.json', '$P1/real.json'],
        ['symlink', 'real.json', '$P1/project.json'],
        ['get', '$P1'],
        ['rm', '$P1/project.json'],
        ['get', '$P1'],
        ['rename', '$P1/real.json', '$P1/project.json'],
        ['chmod', '$P1/project.json', 0o400],
        ['patch', '$P1', {'revision': 4, 'notes': 'still writable through rename'}],
        ['load', '$P1'],
        ['chmod', '$P1/project.json', 0o600],
        ['write', '$P1/project.json', b64('x' * (512 * 1024 + 1))],
        ['get', '$P1'],
        ['write', '$P1/project.json', b64('{"broken":true}')],
        ['get', '$P1'],
        ['write', '$P1/project.json', b64('not json')],
        ['get', '$P1'],
        ['write', '$P1/project.json', b64('')],
        ['get', '$P1'],
        ['write', '$P1/project.json', base64.b64encode(b'\xef\xbb\xbf{}').decode('ascii')],
        ['get', '$P1'],
        ['mkdir', 'not-a-project'],
        ['write', 'stray.json', b64('{}')],
        ['get', '$P2'],
        ['flush'],
    ]}


def concurrency_case() -> dict:
    return {'id': 'concurrency', 'steps': [
        ['concurrent', [['create', {'title': 'One', 'owner_name': 'R'}], ['create', {'title': 'Two', 'owner_name': 'R'}],
                        ['create', {'title': '', 'owner_name': 'R'}], ['create', {'title': 'Three', 'owner_name': 'R'}]]],
        ['concurrent', [['patch', '$P1', {'revision': 1, 'title': 'First'}],
                        ['patch', '$P1', {'revision': 1, 'title': 'Second'}],
                        ['patch', '$P1', {'revision': 1}],
                        ['attach', '$P1', {'revision': 2, 'kind': 'source'}, S_S, {}],
                        ['patch_entry', '$P1', '$E1', {'revision': 3, 'title': 'not yet named'}],
                        ['patch', '$P2', {'revision': 1, 'notes': 'other project'}]]],
        ['load', '$P1'],
        ['concurrent', [['patch', '$P3', {'revision': 1, 'notes': 'accepted'}], ['close'],
                        ['patch', '$P3', {'revision': 2, 'notes': 'too late'}],
                        ['create', {'title': 'Late', 'owner_name': 'R'}],
                        ['attach', '$P3', {'revision': 2, 'kind': 'huge'}, S_S, {}]]],
        ['flush'],
        ['get', '$P3'],
    ]}


def huge_case() -> dict:
    """check-project-store.mjs:158 in both: the oversized snapshot is refused synchronously."""
    huge = snapshot('source', KEY)
    huge['payload']['large'] = 'x' * PROJECT_LIMITS['snapshot_bytes']
    return {'id': 'huge', 'steps': [
        ['create', {'title': 'Bounds', 'owner_name': 'R'}],
        ['attach', '$P1', {'revision': 1, 'kind': 'source'}, huge, {}],
        ['attach', '$P1', {'revision': 1, 'kind': 'source'}, snapshot('source', KEY), {'protocol': 'source-reception/2'}],
        ['read', '$P1', 10],
        ['flush'],
    ]}


@needs_node
def test_the_store_equals_node(tmp_path):
    compare_store([lifecycle_case(), refusals_case(), limits_case(), files_case(), concurrency_case(), huge_case()],
                  tmp_path)


# --- Comparison links: a corpus through the store -----------------------------------------------------------------

def workflow_corpus(seed: int = 2026, count: int = 500) -> list:
    """Comparison settings around Node's ``workflow`` rules: entry choices, link types and spellings, the
    WHATWG URL parser (tabs and newlines removed, percent-encoding of the query, '+' as space, invalid UTF-8),
    every parameter's bounds, the joint rule and the 4,096-unit bound."""
    a, b = R1, R2
    base = f'/decision?a={a}&b={b}'
    fixed: list = [
        None, [], 'x', {}, {'reference_entry_id': '$E1'},
        {'reference_entry_id': '$E1', 'candidate_entry_id': '$E2', 'extra': 1},
        {'reference_entry_id': '$E1', 'candidate_entry_id': '$E1'},
        {'reference_entry_id': '$E3', 'candidate_entry_id': '$E2'},
        {'reference_entry_id': '$E1', 'candidate_entry_id': UNKNOWN},
        {'reference_entry_id': 'x', 'candidate_entry_id': None},
        {'reference_entry_id': 5},
        {'reference_entry_id': {'$js': 'undefined'}, 'candidate_entry_id': '$E2'},
        {'reference_entry_id': '', 'candidate_entry_id': '$E2'},
        {'reference_entry_id': None, 'candidate_entry_id': None, 'comparison_href': base},
        {'reference_entry_id': '$E1', 'candidate_entry_id': None, 'comparison_href': base},
        {'reference_entry_id': '$E1', 'candidate_entry_id': '$E4', 'comparison_href': f'/decision?a={a}&b={R4}'},
        {'reference_entry_id': '$E1', 'candidate_entry_id': '$E5', 'comparison_href': f'/decision?a={a}&b={R5}'},
        {'reference_entry_id': '$E2', 'candidate_entry_id': '$E1', 'comparison_href': f'/decision?a={b}&b={a}'},
        {'reference_entry_id': '$E2', 'candidate_entry_id': '$E1', 'comparison_href': base},
    ]
    for href in (None, '', 0, False, True, 1, [], {}, {'$js': 'undefined'}, 'x', base):
        fixed.append({'reference_entry_id': '$E1', 'candidate_entry_id': '$E2', 'comparison_href': href})
    links = [
        base, base + '&', '&' + base, base + '&&ar=90', base.replace('?', '?&'), '/decision?' + f'b={b}&a={a}',
        base + '#', base + '#x', base + '%23x', '/decision/?' + base[10:], '/decisions?' + base[10:],
        '/Decision?' + base[10:], 'decision?' + base[10:], ' ' + base, '\t' + base, base + ' ', base + '\t',
        base + '\n', '/decision?\ta=' + a + '&b=' + b, base.replace('a=', 'a\n='), base.replace('a=1', 'a=\r1'),
        base.replace('a=', '%61='), base.replace('a=', 'a+='), base.replace('a=1', 'a=%31'), base.replace('a=1', 'a=+1'),
        base.replace('b=2', 'b=%32%32'), base.replace(a, a.upper()), base + '&A=1', base + '&score=1', base + '&=1',
        base + '&ar', base + '&ar=', base + '&a=' + a, base.replace(f'a={a}&', ''), base.replace(f'&b={b}', ''),
        base + ';ar=90', base + '&ar=90;', '/decision?a=' + a + ';b=' + b, '//evil.example/decision?' + base[10:],
        '/decision?/../a=' + a, base + '&%00=1', base + '&ar=9%30', base + '&ar=%39%30', base + '&ar=90%',
        base + '&ar=%zz', base + '&ar=%E4%B8%AD', base + '&ar=%FF', base + '&ar=中', base + '&ar=é',
        base + '&ar=\u0000', base + '&ar=\u007f', base + '&ar=\ud800', base + '&ar=\udc00', base + '&ar=\U0001f600',
        base + '&thresholdMode=joint', base + '&thresholdMode=custom', base + '&thresholdMode=JOINT',
        base + '&thresholdMode=', base + '&thresholdMode=joint+', base + '&thresholdMode=custom&p90=500',
        base + '&thresholdMode=custom&p90=500.0001', base + '&thresholdMode=joint&ar=10&sensitivity=10&localization=10',
        base + '&thresholdMode=joint&ar=10&sensitivity=10.0&localization=1e1',
        base + '&ar=50&sensitivity=50&localization=50', base + '&ar=50&sensitivity=50&p90=10',
        base + '&sensitivity=90', base + '&localization=90', base + '&p90=10', base + '&sensitivity=90&ar=90',
        base + '&thresholdMode=joint&sensitivity=90', base + '&thresholdMode=joint&localization=91',
        base + '&thresholdMode=custom&sensitivity=0&localization=100&p90=0',
        base + '&thresholdMode=custom&ar=1', base + '&thresholdMode=custom&ar=0', base + '&ar=9',
    ]
    ars = ['90', '87', '10', '9', '100', '101', '1', '0', '-1', '90.5', '1e2', '0x5A', ' 90', '90 ', '+90', '９０',
           '', 'NaN', 'Infinity', '-0', '1e1', '0b1011010', '0o132', '.9e2', '90.', '9e1', '0090', '100.0']
    links += [base + '&ar=' + value for value in ars]
    links += [base + '&thresholdMode=custom&sensitivity=' + value for value in ars]
    links += [base + '&thresholdMode=custom&p90=' + value
              for value in ('28.5', '0', '500', '501', '', '-1', '-0', '1e3', '499.999', ' 1')]
    links += [base + '&ar=' + '0' * n + '90' for n in (4096 - len(base) - 6, 4096 - len(base) - 5)]
    links += [base + '&ar=' + '0' * (4096 - len(base) - 8) + '😀' for _ in (0,)]
    fixed += [{'reference_entry_id': '$E1', 'candidate_entry_id': '$E2', 'comparison_href': link} for link in links]
    rng = random.Random(seed)
    pieces = [f'a={a}', f'b={b}', f'a={b}', f'b={a}', 'ar=90', 'ar=50', 'ar=100', 'ar=5', 'ar=x', 'thresholdMode=joint',
              'thresholdMode=custom', 'thresholdMode=both', 'sensitivity=50', 'sensitivity=90', 'sensitivity=101',
              'localization=50', 'localization=90', 'p90=20', 'p90=600', 'score=1', 'ar', '', 'a', 'p90=',
              'sensitivity=5%30', 'ar=+90', 'ar=9%200', 'localization=50.000']
    while len(fixed) < count:
        chosen = [f'a={a}', f'b={b}'] if rng.random() < 0.8 else []
        chosen += rng.sample(pieces, k=rng.choice([0, 1, 1, 2, 2, 3, 4]))
        rng.shuffle(chosen)
        link = '/decision?' + '&'.join(chosen)
        if rng.random() < 0.05:
            link += rng.choice(['#', '#a', '\t', ' ', '%'])
        fixed.append({'reference_entry_id': rng.choice(['$E1', '$E1', '$E1', '$E2', None]),
                      'candidate_entry_id': rng.choice(['$E2', '$E2', '$E2', '$E5', '$E1']), 'comparison_href': link})
    return fixed


@needs_node
def test_comparison_links_equal_node(tmp_path):
    """Every corpus value through ``patch`` at the current revision (Node's ``workflow``): the same refusal or the
    same saved settings, in the same files."""
    steps: list = [['create', {'title': 'Links', 'owner_name': 'R'}],
                   ['attach', '$P1', {'revision': 1, 'kind': 'layout'}, snapshot('layout', R1), {'protocol': 'cache'}],
                   ['attach', '$P1', {'revision': 2, 'kind': 'layout'}, snapshot('layout', R2),
                    {'protocol': 'design_evaluation'}],
                   ['attach', '$P1', {'revision': 3, 'kind': 'editor'}, snapshot('editor', R3), {'protocol': 'cache'}],
                   ['attach', '$P1', {'revision': 4, 'kind': 'layout'}, snapshot('layout', R4), {'protocol': 'other'}],
                   ['attach', '$P1', {'revision': 5, 'kind': 'layout'}, snapshot('layout', R5),
                    {'protocol': 'strict_area'}]]
    corpus = workflow_corpus()
    steps += [['workflow', '$P1', value] for value in corpus]
    output = compare_store([{'id': 'links', 'steps': steps}], tmp_path)
    records = output['by_id']['links']['records'][6:]
    accepted = [entry for entry in records if entry['ok']]
    messages = {entry['message'] for entry in records if not entry['ok']}
    assert len(accepted) > 60 and len(records) - len(accepted) > 200
    assert messages >= {'Invalid project fields.', 'Invalid project comparison link.',
                        'Invalid project comparison parameters.', 'Invalid project comparison requirement.',
                        'Invalid project comparison mode.', 'Choose a layout saved in this project.',
                        'Choose two different saved layouts.', 'Comparison must use the selected evaluated layouts.',
                        'Joint comparison requirements must use the same 10–100 percent limit for all three metrics.'}


# --- Saved metadata and snapshots: read back --------------------------------------------------------------------------

def _crafted_entries() -> tuple[dict, dict]:
    """Two valid entries and the files they name."""
    files, entries = {}, []
    for n, (kind, record_id, value) in enumerate((('layout', R1, snapshot('layout', R1, annotation=A1)),
                                                 ('source', R4, S_S))):
        data = jsjson.stringify(value).encode('utf-8')
        digest = hashlib.sha256(data).hexdigest()
        files[digest] = data
        entries.append({'id': f'0c0c0000-0000-4000-8000-00000000000{n + 1}', 'kind': kind, 'record_id': record_id,
                        **({'annotation_id': A1['id']} if kind == 'layout' else {}), 'title': f'E{n}', 'notes': '',
                        'created_at': '2026-11-24T00:00:00.000Z', 'snapshot_sha256': digest,
                        'snapshot_bytes': len(data), 'summary': {'protocol': 'cache'}})
    return {'entries': entries}, files


def metadata_corpus() -> list[tuple[str, Any]]:
    """(label, project.json bytes or a change of the valid record): what ``validateRecord`` accepts and refuses."""
    valid, _ = _crafted_entries()
    entry = valid['entries'][0]

    def entries(**change: Any) -> list:
        return [{**entry, **change}, valid['entries'][1]]

    def without(key: str) -> list:
        return [{name: value for name, value in entry.items() if name != key}, valid['entries'][1]]
    many = [{**entry, 'id': f'0d0d0000-0000-4000-8000-{n:012d}', 'annotation_id': A1['id']} for n in range(101)]
    heavy = [{**entry, 'id': f'0d0d0000-0000-4000-8000-{n:012d}', 'snapshot_bytes': 16 * 1024 * 1024}
             for n in range(9)]
    workflow = {'reference_entry_id': entry['id'], 'candidate_entry_id': None, 'comparison_href': None}
    return [
        ('valid', {}), ('schema', {'schema': 'research-project/2'}), ('id', {'id': UNKNOWN}),
        ('owner', {'owner_key_hash': 'A' * 64}), ('owner-missing', {'owner_key_hash': UNDEFINED}),
        ('viewer-sha', {'viewer_key_hash': 'f' * 64}), ('viewer-missing', {'viewer_key_hash': UNDEFINED}),
        ('viewer-bad', {'viewer_key_hash': 'x'}), ('viewer-false', {'viewer_key_hash': False}),
        ('entries-object', {'entries': {}}), ('entries-101', {'entries': many}), ('entries-100', {'entries': many[:100]}),
        ('title-empty', {'title': ''}), ('title-long', {'title': 'x' * 201}), ('title-padded', {'title': ' T '}),
        ('title-control', {'title': 'a\u0001'}), ('title-number', {'title': 1}), ('owner-long', {'owner_name': 'x' * 121}),
        ('notes-null', {'notes': None}), ('notes-missing', {'notes': UNDEFINED}), ('notes-long', {'notes': 'x' * 8001}),
        ('revision-0', {'revision': 0}), ('revision-float', {'revision': 1.5}), ('revision-text', {'revision': '1'}),
        ('revision-big', {'revision': 2 ** 53}), ('created-bad', {'created_at': 'x'}), ('created-number', {'created_at': 1}),
        ('updated-empty', {'updated_at': ''}), ('created-date', {'created_at': '2026-11-24'}),
        ('created-offset', {'created_at': '2026-11-24T01:00:00+01:00'}), ('created-minutes', {'created_at': '2026-11-24T00:00Z'}),
        ('created-month', {'created_at': '2026-13-01T00:00:00.000Z'}),
        ('entry-null', {'entries': [None]}), ('entry-number', {'entries': [5]}),
        ('entry-annotation-source', {'entries': [valid['entries'][0], {**valid['entries'][1], 'annotation_id': A1['id']}]}),
        ('entry-annotation-bad', {'entries': entries(annotation_id='x')}),
        ('entry-annotation-null', {'entries': entries(annotation_id=None)}),
        ('entry-id', {'entries': entries(id='x')}),
        ('entry-duplicate', {'entries': [entry, {**valid['entries'][1], 'id': entry['id']}]}),
        ('entry-kind', {'entries': entries(kind='design')}), ('entry-record', {'entries': entries(record_id='x')}),
        ('entry-sha', {'entries': entries(snapshot_sha256='X' * 64)}), ('entry-bytes-1', {'entries': entries(snapshot_bytes=1)}),
        ('entry-bytes-big', {'entries': entries(snapshot_bytes=16 * 1024 * 1024 + 1)}),
        ('entry-bytes-float', {'entries': entries(snapshot_bytes=10.5)}),
        ('entry-bytes-text', {'entries': entries(snapshot_bytes='10')}),
        ('entry-summary-array', {'entries': entries(summary=[])}), ('entry-summary-null', {'entries': entries(summary=None)}),
        ('entry-title', {'entries': without('title')}), ('entry-notes', {'entries': entries(notes='x' * 8001)}),
        ('entry-created', {'entries': without('created_at')}), ('entries-heavy', {'entries': heavy}),
        ('entries-heavy-8', {'entries': heavy[:8]}),
        ('workflow', {'workflow': workflow}), ('workflow-null', {'workflow': None}),
        ('workflow-extra', {'workflow': {**workflow, 'x': 1}}),
        ('workflow-foreign', {'workflow': {**workflow, 'reference_entry_id': UNKNOWN}}),
        ('workflow-source', {'workflow': {**workflow, 'reference_entry_id': valid['entries'][1]['id']}}),
        ('workflow-href', {'workflow': {**workflow, 'comparison_href': '/decision?a=1'}}),
        ('network', {'creator_network': 'd' * 64}), ('network-bad', {'creator_network': 'x'}),
        ('network-null', {'creator_network': None}), ('unknown-member', {'archived': True, 'tags': ['x']}),
        ('text-duplicate-keys', None), ('text-proto', None), ('text-bom', None), ('text-escapes', None),
        ('text-invalid-utf8', None), ('text-array', b'[]'), ('text-null', b'null'),
    ]


def snapshot_corpus() -> list[tuple[str, dict, bytes]]:
    """(label, entry change, file bytes): what ``snapshot`` accepts and refuses for a layout entry of R1."""
    good = snapshot('layout', R1, annotation=A1)
    bad_annotation = snapshot('layout', R1, annotation={**A1, 'electrode_names': A1['electrode_names'][:63]})
    rows = [
        ('valid', {}, jsjson.stringify(good).encode('utf-8')),
        ('no-annotation', {'annotation_id': UNDEFINED}, jsjson.stringify(snapshot('layout', R1)).encode('utf-8')),
        ('annotation-unclaimed', {'annotation_id': UNDEFINED}, jsjson.stringify(good).encode('utf-8')),
        ('annotation-other', {'annotation_id': A2['id']}, jsjson.stringify(good).encode('utf-8')),
        ('annotation-invalid', {}, jsjson.stringify(bad_annotation).encode('utf-8')),
        ('kind', {}, jsjson.stringify({**good, 'kind': 'editor'}).encode('utf-8')),
        ('record', {}, jsjson.stringify({**good, 'record_id': R2}).encode('utf-8')),
        ('payload-array', {}, jsjson.stringify({**good, 'payload': []}).encode('utf-8')),
        ('schema', {}, jsjson.stringify({**good, 'schema': 'x'}).encode('utf-8')),
        ('not-json', {}, b'not json'), ('null', {}, b'null'), ('string', {}, b'"text"'),
        ('bom', {}, b'\xef\xbb\xbf' + jsjson.stringify(good).encode('utf-8')),
        ('escapes', {}, jsjson.stringify(good).encode('utf-8').replace(b'"payload":{', b'"payload":{"x":"\\u00e9\\ud800\\/",')),
        ('invalid-utf8', {}, jsjson.stringify(good).encode('utf-8').replace(b'"payload":{', b'"payload":{"x":"\xff\xfe",')),
        ('spaces', {}, b'  ' + jsjson.stringify(good).encode('utf-8') + b'\n'),
        ('duplicate-kind', {}, jsjson.stringify(good).encode('utf-8').replace(b'{"schema"', b'{"kind":"editor","schema"', 1)),
    ]
    return rows


def _write_metadata_corpus(directory: Path) -> list[str]:
    valid, files = _crafted_entries()
    ids = []
    for n, (label, change) in enumerate(metadata_corpus()):
        id = f'0e0e0000-0000-4000-8000-{n:012d}'
        ids.append(id)
        record = crafted_project(id, **valid)
        if isinstance(change, dict):
            for key, value in change.items():
                if value is UNDEFINED:
                    record.pop(key, None)
                else:
                    record[key] = value
            data = jsjson.stringify(record).encode('utf-8')
        elif isinstance(change, bytes):
            data = change
        else:
            text = jsjson.stringify(record)
            data = {
                'text-duplicate-keys': (text[:-1] + ',"title":"Second","notes":"N"}').encode('utf-8'),
                'text-proto': (text[:-1] + ',"__proto__":{"x":1},"constructor":"c"}').encode('utf-8'),
                'text-bom': b'\xef\xbb\xbf' + text.encode('utf-8'),
                'text-escapes': text.replace('"Crafted"', '"Cr\\u0061fted \\ud83d\\ude00 \\/"').encode('utf-8'),
                'text-invalid-utf8': text.replace('"Crafted"', '"Cr\xe9fted"').encode('latin-1', errors='replace'),
            }[label]
        project = directory / id
        (project / 'snapshots').mkdir(parents=True, mode=0o700)
        (project / 'project.json').write_bytes(data)
        for digest, content in files.items():
            (project / 'snapshots' / f'{digest}.json').write_bytes(content)
    for n, (label, change, data) in enumerate(snapshot_corpus()):
        id = f'0e0e0000-0000-4000-8001-{n:012d}'
        ids.append(id)
        digest = hashlib.sha256(data).hexdigest()
        entry = {'id': '0c0c0000-0000-4000-8000-000000000001', 'kind': 'layout', 'record_id': R1,
                 'annotation_id': A1['id'], 'title': label, 'notes': '', 'created_at': '2026-11-24T00:00:00.000Z',
                 'snapshot_sha256': digest, 'snapshot_bytes': len(data), 'summary': {}}
        for key, value in change.items():
            if value is UNDEFINED:
                entry.pop(key)
            else:
                entry[key] = value
        project = directory / id
        (project / 'snapshots').mkdir(parents=True, mode=0o700)
        (project / 'project.json').write_bytes(jsjson.stringify(crafted_project(id, entries=[entry])).encode('utf-8'))
        (project / 'snapshots' / f'{digest}.json').write_bytes(data)
    return ids


@needs_node
def test_crafted_metadata_and_snapshots_read_as_node_reads_them(tmp_path):
    """``validateRecord`` and ``snapshot`` on hand-written files: the same refusals, and an accepted record or
    snapshot text unchanged (members, order, escapes and replacement characters included). Date spellings outside
    ISO 8601 are the one deliberate difference (``test_metadata_times_are_iso_date_times``)."""
    directory = tmp_path / 'crafted' / 'projects'
    ids = _write_metadata_corpus(directory)
    before = tree(directory)
    case = {'id': 'crafted', 'directory': str(directory), 'projects': ids}
    node = run_driver('read', [case], tmp_path)['by_id']['crafted']
    python = python_read(case)
    labels = [label for label, _ in metadata_corpus()] + [label for label, _, _ in snapshot_corpus()]
    for label, left, right in zip(labels, node_read(node)['projects'], python['projects']):
        _diff(label, left, right)
    assert tree(directory) == before
    outcomes = {label: row['ok'] for label, row in zip(labels, python['projects'])}
    assert outcomes['valid'] and outcomes['unknown-member'] and outcomes['network'] and not outcomes['network-bad']
    assert not outcomes['entries-101'] and outcomes['entries-100'] and not outcomes['entries-heavy']


# --- The service ----------------------------------------------------------------------------------------------------

L1, L2, L3, L4, L5, L6, L7, L8 = (f'{n}' * 64 for n in range(1, 9))
LB = 'ab' * 32  # no bundle


def service_state() -> dict:
    records = {L1: layout_record(L1), L2: layout_record(L2, dataset_id='strict_area'),
               L3: layout_record(L3, status='running'), L4: layout_record(L4, layout=None),
               L5: layout_record('not-a-record-id'), L6: layout_record(L6, request={'noise_model': {'kind': 'spatial'}}),
               L7: layout_record(L7), L8: layout_record(L8), LB: layout_record(LB)}
    del records[L8]['region_count']
    bundles = {L1: layout_bundle(records[L1]), L2: layout_bundle(records[L2]), L6: layout_bundle(records[L6]),
               L7: {'$error': 'disk failure'}, L8: layout_bundle(records[L8])}
    k1, row1, cache1 = editor_cache(L1)
    k2, row2, cache2 = editor_cache(L2, invalid=True)
    k4, row4, cache4 = editor_cache(L4, action='apply')
    k3 = 'a3' * 32
    cache3 = {**cache1, 'key': k3, 'result_sha256': '0' * 64}
    k5, k6 = 'a5' * 32, 'a6' * 32
    cache6 = {**cache1, 'key': k1}
    rows = [row1, row2, {**row1, 'key': k3}, row4, {**row1, 'key': k5}, {**row1, 'key': k6}]
    tasks = [{'id': f'7e7e0000-0000-4000-8000-00000000000{n}', 'kind': 'source-reception', 'status': status,
              'key': key, 'request': {'record_id': L1}}
             for n, status, key in ((1, 'completed', 'b1' * 32), (2, 'running', 'b2' * 32), (3, 'completed', 'bad'),
                                    (4, 'completed', 'b4' * 32), (5, 'completed', 'b5' * 32), (6, 'completed', 'b6' * 32),
                                    (7, 'completed', 'b7' * 32))]
    tasks.append({**tasks[0], 'id': '7e7e0000-0000-4000-8000-000000000008', 'kind': 'design-evaluation'})
    saved = {'b1' * 32: source_result(L1, brain_regions=['frontal', 'parietal']), 'bad': source_result(L1),
             'b4' * 32: source_result(L2), 'b5' * 32: {'$error': 'cache removed'},
             'b6' * 32: {**source_result(L1), 'schema_version': 'source-reception/3'}, 'b7' * 32: [source_result(L1)]}
    other = annotation(L2, 'b')
    return {'records': records, 'bundles': bundles, 'editor': {'rows': rows, 'caches': {k1: cache1, k2: cache2,
                                                                                        k3: cache3, k4: cache4,
                                                                                        k6: cache6}},
            'tasks': tasks, 'saved': saved, 'annotations': {A1L['id']: A1L, other['id']: other}, 'before': None,
            'keys': {'k1': k1, 'k2': k2, 'k3': k3, 'k4': k4, 'k5': k5, 'k6': k6}}


A1L = annotation('1' * 64, 'service')
JSON = {'content-type': 'application/json'}


def request(method: str, url: str, body: Any = UNDEFINED, headers: dict | None = None) -> list:
    text = None if body is UNDEFINED else body if isinstance(body, str) else jsjson.stringify(body)
    return ['request', method, url, {**JSON, **(headers or {})} if method != 'GET' else (headers or {}), text]


def service_cases() -> list[dict]:
    state = service_state()
    keys = state.pop('keys')
    p = '/api/projects/$P1'
    entry = p + '/entries'

    def attach(revision: int, **data: Any) -> list:
        return request('POST', entry, {'revision': revision, **data})
    flow = [
        request('POST', '/api/projects', {'title': ' Study ', 'owner_name': 'Researcher', 'notes': 'n'}),
        request('GET', p), request('PATCH', p, {'revision': 1, 'title': 'Renamed'}),
        attach(2, kind='layout', record_id=L1),
        attach(3, kind='layout', record_id=L1, annotation_id=A1L['id'], title='Named'),
        attach(4, kind='editor', record_id=keys['k1']),
        attach(5, kind='source', receipt_id='7e7e0000-0000-4000-8000-000000000001', notes='signal'),
        attach(6, kind='layout', record_id=L2),
        attach(7, kind='layout', record_id=L6), attach(8, kind='layout', record_id=L8),
        request('PATCH', p, {'revision': 9, 'workflow': {'reference_entry_id': '$E1', 'candidate_entry_id': '$E5',
                                                         'comparison_href': f'/decision?b={L2}&a={L1}&ar=50'}}),
        request('GET', entry + '/$E2'), request('PATCH', entry + '/$E3', {'revision': 10, 'notes': 'edited'}),
        request('DELETE', entry + '/$E5', headers={'If-Match': '"11"'}),
        request('DELETE', entry + '/$E4', {'revision': 12}),
        request('GET', p + '/export'), request('GET', p),
    ]
    refusals = [
        attach(13, kind='layout', record_id=L3), attach(13, kind='layout', record_id=L4),
        attach(13, kind='layout', record_id=L5), attach(13, kind='layout', record_id=L7),
        attach(13, kind='layout', record_id='f' * 64), attach(13, kind='layout', record_id='e' * 64),
        attach(13, kind='editor', record_id='e' * 64), attach(13, kind='editor', record_id=keys['k2']),
        attach(13, kind='editor', record_id=keys['k3']), attach(13, kind='editor', record_id=keys['k4']),
        attach(13, kind='editor', record_id=keys['k5']), attach(13, kind='editor', record_id=keys['k6']),
        attach(13, kind='layout', record_id=LB),
        *[attach(13, kind='source', receipt_id=f'7e7e0000-0000-4000-8000-00000000000{n}') for n in range(2, 9)],
        attach(13, kind='source', receipt_id=UNKNOWN),
        attach(13, kind='layout', record_id=L1, annotation_id='a' * 64),
        attach(13, kind='layout', record_id=L1, annotation_id=annotation(L2, 'b')['id']),
        attach(13, kind='source', receipt_id='7e7e0000-0000-4000-8000-000000000001', annotation_id=A1L['id']),
        attach(1, kind='layout', record_id=L1), attach(13, kind='x'), attach(13, kind='layout', record_id=L1, payload={}),
        attach(13, kind='source', receipt_id='7e7e0000-0000-4000-8000-000000000001', record_id=L1),
        attach(13, kind='source', receipt_id='bad'), attach(13, kind='layout', record_id='A' * 64),
        attach(13, kind='layout', receipt_id='7e7e0000-0000-4000-8000-000000000001', record_id=L1),
        attach(13, kind='layout', record_id=L1),
        request('POST', entry, ['revision']),
        request('PUT', p), request('OPTIONS', '/api/projects'), request('GET', p + '?x=1'),
        request('POST', '/api/projects?x', {'title': 'Q', 'owner_name': 'R'}), request('DELETE', '/api/projects'),
        request('PATCH', '/api/projects', {}), request('POST', '/api/projects', 'x', {'content-type': 'text/plain'}),
        request('POST', '/api/projects', {'title': 'x' * 70000, 'owner_name': 'R'}),
        # The bound counts bytes as received: 65,536 are read (then refused for the title), one more is 413.
        request('POST', '/api/projects', '{"title":""}' + ' ' * (65536 - 12)),
        request('POST', '/api/projects', '{"title":""}' + ' ' * (65536 - 11)),
        request('POST', '/api/projects', '{"title":"' + 'é' * 32762 + '"}'),
        request('POST', '/api/projects', '{"title":"' + 'é' * 32763 + '"}'),
        request('POST', '/api/projects', '{broken'), request('POST', '/api/projects', '[]'),
        request('POST', '/api/projects', 'null'), request('POST', '/api/projects', '"x"'),
        request('POST', '/api/projects', {'title': 'U', 'owner_name': 'R'}, {'content-type': 'Application/JSON'}),
        request('POST', '/api/projects', {'title': 'Plus', 'owner_name': 'R'}, {'content-type': 'application/jsonx'}),
        ['request', 'POST', '/api/projects', {}, jsjson.stringify({'title': 'No type', 'owner_name': 'R'})],
        request('POST', '/api/projects', '{"title":"Dup","title":"Second","owner_name":"R"}'),
        request('POST', '/api/projects', '﻿{"title":"BOM","owner_name":"R"}'),
        request('POST', '/api/projects', ' {"title":"Space","owner_name":"R"} '),
        request('GET', '/api/projects/xyz'), request('GET', p + '/unknown'), request('GET', p + '/'),
        request('GET', '/api/projects/00000000-0000-1000-8000-000000000000'), request('GET', f'/api/projects/{UNKNOWN}'),
        request('GET', f'/api/projects/{UNKNOWN}/export'), request('POST', p, {}), request('GET', entry),
        request('DELETE', p), request('GET', p + '/export/$E1'), request('PATCH', entry + '/zz', {}),
        request('PATCH', entry + '/00000000-0000-1000-8000-000000000000', {'revision': 13, 'title': 'x'}),
        request('PATCH', entry + f'/{UNKNOWN}', {'revision': 13, 'title': 'x'}),
        request('PATCH', p, {'revision': 13, 'workflow': {'reference_entry_id': '$E1', 'candidate_entry_id': '$E1'}}),
        request('PATCH', p, {'revision': 13}),
        request('DELETE', entry + '/$E1', headers={'If-Match': 'abc'}),
        request('DELETE', entry + '/$E1', headers={'If-Match': ''}),
        request('DELETE', entry + '/$E1', headers={'If-Match': '"1'}),
        request('DELETE', entry + '/$E1', headers={'If-Match': '""13""'}),
        request('DELETE', entry + '/$E1'),
        ['state', {'before': 'resource'}],
        request('PATCH', p, {'revision': 13, 'title': 'Blocked'}),
        request('POST', '/api/projects', {'title': 'B', 'owner_name': 'R'}),
        request('POST', '/api/projects', 'x', {'content-type': 'text/plain'}), request('GET', p),
        request('DELETE', f'/api/projects/{UNKNOWN}/entries/{UNKNOWN}', {'revision': 1}),
        ['state', {'before': None}],
        request('DELETE', entry + '/$E1', headers={'If-Match': ' 13 '}),
        request('DELETE', entry + '/$E1', headers={'If-Match': '14'}),
        request('GET', p + '/export'),
    ]
    return [{'id': 'service-flow', 'state': state, 'steps': flow + refusals}]


@needs_node
def test_the_service_equals_node(tmp_path):
    """Snapshot resolution from every kind of record and every refusal of the middleware, in Node's order, by
    status, answer and headers, and the same files."""
    output = compare_service(service_cases(), tmp_path)
    statuses = {record['status'] for record in output['by_id']['service-flow']['records'] if 'status' in record}
    assert statuses >= {200, 201, 400, 404, 405, 409, 413, 415, 500, 503}


@needs_node
def test_the_list_and_sharing_are_the_deliberate_differences(tmp_path):
    """Node answers ``GET /api/projects`` 405 and shares a project; the workspace lists and has no sharing."""
    steps = [request('POST', '/api/projects', {'title': 'S', 'owner_name': 'R'}), request('GET', '/api/projects'),
             request('POST', '/api/projects/$P1/share', {'revision': 1}),
             request('POST', '/api/projects/$P1/revoke-share', {'revision': 2})]
    (tmp_path / 'node').mkdir()
    node = run_driver('service', [{'id': 'differences', 'state': {}, 'steps': steps,
                                   'directory': str(tmp_path / 'node' / 'projects')}], tmp_path)
    statuses = [record['status'] for record in node['by_id']['differences']['records']]
    assert statuses == [201, 405, 200, 200]
    python = python_service({'id': 'differences', 'state': {}, 'steps': steps,
                             'directory': str(tmp_path / 'python' / 'projects')})
    assert [record['status'] for record in python['records']] == [201, 200, 404, 404]
    assert jsjson.parse(python['records'][1]['body'])['projects'][0]['title'] == 'S'


# --- Node-written projects: the Q fixture ---------------------------------------------------------------------------

def q_fixture_steps() -> list:
    href = f'/decision?a={R1}&b={R2}&thresholdMode=joint&ar=95&sensitivity=95'
    return [
        ['create', {'title': 'Node project 研究', 'owner_name': 'Researcher 😀', 'notes': 'Line 1\nLine 2\t"quoted"'}],
        ['attach', '$P1', {'revision': 1, 'kind': 'layout', 'title': 'Reference'}, S_L1,
         {'protocol': 'cache', 'electrode_count': 64, 'region_count': 2, 'simulation': True}],
        ['attach', '$P1', {'revision': 2, 'kind': 'layout', 'annotation_id': A2['id']}, S_L2,
         {'protocol': 'design_evaluation', 'electrode_count': 64}],
        ['attach', '$P1', {'revision': 3, 'kind': 'editor'}, S_E, {'protocol': 'electrode-editor-result/1'}],
        ['attach', '$P1', {'revision': 4, 'kind': 'source'}, S_S, {'protocol': 'source-reception/2', 'seed': 7}],
        ['attach', '$P1', {'revision': 5, 'kind': 'source'}, snapshot('source', R5), {}],
        ['detach', '$P1', '$E5', 6],
        ['workflow', '$P1', {'reference_entry_id': '$E1', 'candidate_entry_id': '$E2', 'comparison_href': href}],
        ['patch_entry', '$P1', '$E3', {'revision': 8, 'notes': 'kept'}],
        ['create', {'title': 'Empty', 'owner_name': 'R'}],
        ['flush'],
    ]


def _node_q_fixture(tmp_path: Path) -> tuple[Path, dict, list[str]]:
    """Node writes two projects in a Q fixture (``R/results/web-service/projects``); returns the directory, the
    project keys and the ids."""
    directory = tmp_path / 'R' / 'results' / 'web-service' / 'projects'
    directory.parent.mkdir(parents=True)
    output = run_driver('store', [{'id': 'q', 'directory': str(directory), 'steps': q_fixture_steps()}], tmp_path / 'R')
    creates = [entry for step, entry in zip(q_fixture_steps(), output['by_id']['q']['records']) if step[0] == 'create']
    keys = {jsjson.parse(entry['value'])['project']['id']: entry['access_key'] for entry in creates}
    assert all(entry['ok'] for entry in output['by_id']['q']['records'])
    return directory, keys, list(keys)


@needs_node
def test_node_written_projects_read_back_unchanged(tmp_path):
    """The Q fixture's projects load and their snapshots read in Python as in Node, byte for byte, through every
    read of the store and the service; Python's reads write nothing."""
    directory, _, ids = _node_q_fixture(tmp_path)
    before = tree(directory)
    case = {'id': 'q-read', 'directory': str(directory), 'projects': ids}
    node = run_driver('read', [case], tmp_path)['by_id']['q-read']
    python = python_read(case)
    _diff('q fixture', node_read(node), python)
    files = {row[0]: row[3] for row in before if row[1] == 'file'}
    for id, project in zip(ids, python['projects']):
        assert project['record'].encode('utf-8') == base64.b64decode(files[f'{id}/project.json'])
        for text in project['snapshots']:
            digest = hashlib.sha256(text['value'].encode('utf-8')).hexdigest()
            assert base64.b64decode(files[f'{id}/snapshots/{digest}.json']) == text['value'].encode('utf-8')

    async def reads():
        store = ProjectStore(str(directory))
        service = ProjectService(store=store, delivery=ExportedIds(store))
        listed = (await service.handle('GET', '/api/projects'))[1]['projects']
        assert [row['title'] for row in listed] == ['Empty', 'Node project 研究']
        saved = await store.read_snapshots(ids[0])
        assert [row['entry']['title'] for row in saved['entries']] == ['Reference', 'layout 22222222',
                                                                        'editor 33333333', 'source 44444444']
        assert saved['project']['workflow']['comparison_href'].startswith('/decision?a=')
        for row in saved['entries']:
            assert (await service.handle('GET', f"/api/projects/{ids[0]}/entries/{row['entry']['id']}"))[1] == {
                'entry': row['entry'], 'snapshot': row['snapshot']}
        assert (await service.handle('GET', f'/api/projects/{ids[0]}/export'))[0] == 200
    run(reads())
    assert tree(directory) == before


@needs_node
def test_python_continues_node_written_projects_as_node_does(tmp_path):
    """Copies of the Q fixture changed by Node (with the owner's key) and by Python: the same answers and files."""
    directory, keys, ids = _node_q_fixture(tmp_path)
    steps = [
        ['get', ids[0]],
        ['patch', ids[0], {'revision': 9, 'title': 'Continued', 'notes': ''}],
        ['attach', ids[0], {'revision': 10, 'kind': 'source'}, snapshot('source', R5), {'seed': 1}],
        ['attach', ids[0], {'revision': 11, 'kind': 'layout'}, snapshot('layout', R3), {'protocol': 'strict_area'}],
        ['workflow', ids[0], {'reference_entry_id': '$E2', 'candidate_entry_id': None}],
        ['detach', ids[0], '$E1', 13],
        ['patch_entry', ids[1], UNKNOWN, {'revision': 1, 'title': 'x'}],
        ['attach', ids[1], {'revision': 1, 'kind': 'layout', 'annotation_id': A2['id']}, S_L2, {'protocol': 'cache'}],
        ['read', ids[0]],
        ['flush'],
    ]
    cases = []
    for side in ('node', 'python'):
        target = tmp_path / side / 'q-continue' / 'projects'
        target.parent.mkdir(parents=True)
        shutil.copytree(directory, target, symlinks=True)
        cases.append({'id': 'q-continue', 'directory': str(target), 'steps': steps, 'keys': keys, 'prefix': '0b0b0000'})
    output = run_driver('store', [cases[0]], tmp_path)
    node = output['by_id']['q-continue']
    python = python_store(jsjson.parse(jsjson.stringify(cases[1])))
    for index, (left, right) in enumerate(zip(node_records(node), python['records'])):
        _diff(f'step {index + 1} {steps[index][0]}', left, right)
    _diff('files', node['tree'], python['tree'])
    assert all(entry['ok'] for entry in python['records'][:6])


REAL_ROOT = os.environ.get('EEG_KEY_PARITY_ROOT')


@pytest.mark.data_bundle
@pytest.mark.skipif(not REAL_ROOT, reason='set EEG_KEY_PARITY_ROOT to an installation')
@needs_node
def test_the_installations_projects_read_as_node_reads_them(tmp_path):
    """The installation's Q (``results/web-service/projects``), read only: every project and snapshot as Node reads
    it. Both stores are opened only on an existing directory (opening one creates a missing directory), and the
    files are compared before and after; an installation without projects has nothing to read."""
    projects = Path(REAL_ROOT) / 'results' / 'web-service' / 'projects'
    if not projects.is_dir() or projects.is_symlink():
        pytest.skip(f'{projects} does not exist: no Node-written project to read back')
    before = tree(projects)
    ids = sorted(name for name in os.listdir(projects) if len(name) == 36)
    case = {'id': 'real', 'directory': str(projects), 'projects': ids}
    node = run_driver('read', [case], tmp_path)['by_id']['real']
    _diff('real projects', node_read(node), python_read(case))
    assert tree(projects) == before
