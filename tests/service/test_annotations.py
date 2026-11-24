"""Electrode-name annotations, write side, and the design submission envelope (``eeglayoutlab.jobs.annotations``,
phase 2 slice 5).

- Ports of webapp/scripts/check-electrode-annotations.mjs :82, :100, :117, :135, :147 and :212 on the fixture of
  that file (:54-71): a design-evaluation adapter with Node's prepare (``design_submission``, the normalizer and a
  frozen identity, key = ``sha256({request, identity})``), a lookup of the stored cache and a start that fails the
  test; the workspace queue; the local annotations (``ElectrodeAnnotations.local``: W/annotations/electrode-names,
  then Node's directory, owner ``LOCAL_OWNER``). Owners and the per-owner bound are dropped (R1), the resource gate
  (R2); the per-owner part of :135 becomes the file-size bound. The HTTP halves of :147 and :212 (policy and token,
  the ``?annotation_id`` query rules of the routes, the 65,536-byte route limit over HTTP) belong to the route tests;
  here the body reader of the routes (``server.app.read_json_body``) gets the split body.
- Parity (plan slice 5, parity 2): tests/service/parity/annotations.mjs runs Node's ``designSubmission`` and
  ``ElectrodeAnnotations`` (identity, create, read, list) on the same inputs and owners: unicode names, control
  characters, lone surrogates, duplicates, lengths, owners, keys, every request and coordinate source of the phase 1
  corpus, envelopes Node refuses. Values, ids, refusal messages and statuses, and file bytes must equal Node's;
  every file Python writes must read back the same in Node (given its owner) and every file Node writes in the
  slice 3 reader.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
from typing import Any, Optional
import uuid

import pytest

from schema_parity_support import CORPUS, body_text, require

require('pydantic')

from eeglayoutlab.jobs.annotations import (  # noqa: E402
    ANNOTATION_LIMITS, INTEGRITY, INVALID_IDENTITY, INVALID_SUBMISSION, LIMIT, LOCAL_OWNER, NAMES, NODE_ANNOTATIONS,
    NOT_FOUND, SOURCE, TOO_LARGE, UNAVAILABLE, WORKSPACE_ANNOTATIONS, AnnotationError, CoordinateSourceError,
    ElectrodeAnnotations, design_submission, validate_electrode_annotation,
)
from eeglayoutlab.jobs.design_result import normalize_design_request  # noqa: E402
from eeglayoutlab.jobs.identity import UNDEFINED, js_truthy, request_key  # noqa: E402
from eeglayoutlab.jobs.library import Library  # noqa: E402
from eeglayoutlab.jobs.queue import (  # noqa: E402
    ANNOTATION_NOT_FOUND, TASK_VARIANTS, QueueError, WorkspaceQueue,
)
from eeglayoutlab.jobs.runtime import runtime_config  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402

from .key_parity_support import (  # noqa: E402
    browser_submission, coordinate_sources, failure, needs_node, node_failure, run_annotations_node,
)

KIND = 'design-evaluation'
IDENTITY = {'test_identity': 'frozen'}
BASE = {'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm',
        'name': 'Shared layout', 'xyz_mm': [[(i % 8) * 6, (i // 8) * 6, 1e-14] for i in range(64)],
        'region_indices': [i % 2 for i in range(64)]}


def names(prefix: str) -> list[str]:
    return [f'{prefix}{i + 1}' for i in range(64)]


A, B = {**BASE, 'electrode_names': names('A')}, {**BASE, 'electrode_names': names('B')}
REQUEST = normalize_design_request({'action': 'evaluate', 'design': BASE, 'radius_mm': 6, 'seed': 42})
KEY = request_key(REQUEST, IDENTITY)
RESULT = {'schema': 'design-evaluation/1', 'status': 'completed', 'request': REQUEST, 'forward_mode': 'cached_fem',
          'evaluated_xyz_mm': BASE['xyz_mm'],
          'nominal': {'field_relative': 1, 'field_absolute': 0.9, 'reference_field_absolute': 0.9, 'sensitivity_tail': 1,
                      'localization_relative': 1, 'median_mm': 10, 'p90_mm': 20, 'reference_median_mm': 10,
                      'reference_p90_mm': 20},
          'projection_max_mm': 0, 'trials': [], 'provenance': {'candidate_count': 64, 'original': [1 / 3, -1e-18, 1.0000000000000002]}}
CACHE = {'key': KEY, 'identity': IDENTITY, 'result': RESULT, 'result_sha256': jsjson.sha256_hex(RESULT)}


def run(coroutine) -> Any:
    return asyncio.run(coroutine)


class DesignAdapter:
    """The design-evaluation adapter of the fixture (check-electrode-annotations.mjs:65-67): Node's prepare
    (community-adapters.mjs:18-21) with a frozen context, ``lookup`` of the stored cache (key and checksum, as
    ``DesignEvaluationService.lookup``), and a ``start`` that fails the test."""

    def __init__(self, root: Path):
        self.root = root
        self.callbacks: list = []

    async def prepare(self, raw: Any) -> dict:
        submitted = design_submission(raw)
        request = normalize_design_request(submitted['request'])
        key = request_key(request, IDENTITY)
        prepared = {'request': request, 'key': key, 'ctx': {'identity': IDENTITY, 'key': key}}
        for name in ('electrode_names', 'source_metadata'):
            if js_truthy(submitted.get(name, UNDEFINED)):
                prepared[name] = submitted[name]
        return prepared

    async def lookup(self, prepared: dict) -> dict:
        path = self.root / 'results/v2/design_evaluation_jobs' / prepared['key'] / 'cache.json'
        try:
            cache = jsjson.parse(path.read_bytes().decode('utf-8'))
        except FileNotFoundError:
            return {'hit': False}
        if cache['key'] != prepared['key'] or jsjson.sha256_hex(cache['result']) != cache['result_sha256']:
            return {'hit': False}
        return {'hit': True, 'job': {'id': str(uuid.uuid4()), 'key': prepared['key'], 'status': 'completed',
                                     'message': '设计评价已完成', 'progress': 1, 'result': cache['result'], 'cached': True}}

    async def start(self, prepared: dict) -> dict:
        raise AssertionError('A metadata test must never launch a worker.')

    def get(self, id: Any) -> Optional[dict]:
        return None

    def busy(self) -> bool:
        return False

    def pid(self) -> Optional[int]:
        return None

    def cancel(self, id: Any) -> None:
        raise AssertionError('Unexpected cancellation')

    def on_finish(self, callback) -> None:
        self.callbacks.append(callback)


@dataclass
class Fixture:
    root: Path
    workspace: Path
    cache_path: Path
    adapter: DesignAdapter
    annotations: ElectrodeAnnotations
    queue: WorkspaceQueue

    @property
    def directory(self) -> Path:
        return self.workspace.joinpath(*WORKSPACE_ANNOTATIONS)

    def store(self, **options: Any) -> ElectrodeAnnotations:
        return ElectrodeAnnotations.local(str(self.directory), str(self.root), **options)

    def reopen(self) -> WorkspaceQueue:
        return WorkspaceQueue(str(self.workspace / '.eeglayoutlab'), {KIND: self.adapter}, annotations=self.store())

    def write_cache(self) -> None:
        self.cache_path.write_bytes(jsjson.stringify(CACHE).encode('utf-8'))


def fixture(tmp_path: Path, cached: bool = True) -> Fixture:
    """``fixture(t, {cached})`` of check-electrode-annotations.mjs:54: the key's record directory, with the cache
    when ``cached``; the workspace W beside the root R."""
    base = Path(os.path.realpath(tmp_path))
    root, workspace = base / 'R', base / 'W'
    cache_path = root / 'results/v2/design_evaluation_jobs' / KEY / 'cache.json'
    cache_path.parent.mkdir(parents=True)
    workspace.mkdir()
    adapter = DesignAdapter(root)
    annotations = ElectrodeAnnotations.local(str(workspace.joinpath(*WORKSPACE_ANNOTATIONS)), str(root))
    queue = WorkspaceQueue(str(workspace / '.eeglayoutlab'), {KIND: adapter}, annotations=annotations)
    f = Fixture(root, workspace, cache_path, adapter, annotations, queue)
    if cached:
        f.write_cache()
    return f


def tree(path: Path) -> dict[str, bytes]:
    return {str(item.relative_to(path)): item.read_bytes() for item in sorted(path.rglob('*')) if item.is_file()}


def node_directory(root: Path) -> Path:
    return root.joinpath(*NODE_ANNOTATIONS)


# --- Ports of check-electrode-annotations.mjs --------------------------------------------------------------------

def test_variants_of_one_receipt_survive_a_restart_without_scientific_file_changes(tmp_path):
    """check-electrode-annotations.mjs:82 'shared receipts retain owner-specific and same-owner variants across
    restart without scientific file changes', for the one local user: two name variants of one request share the
    receipt and key, each view shows its own names, sending a variant again reuses it, and after a restart the
    variants and the canonical request are still there; the record tree is untouched."""
    f = fixture(tmp_path, cached=False)
    before = tree(f.root)

    async def body() -> None:
        first = await f.queue.submit(KIND, browser_submission(A))
        second = await f.queue.submit(KIND, browser_submission(B))
        third = await f.queue.submit(KIND, browser_submission(B))
        assert first['job']['id'] == second['job']['id'] == third['job']['id']
        assert first['job']['key'] == second['job']['key'] == KEY
        assert first['job']['annotation_id'] != second['job']['annotation_id'] == third['job']['annotation_id']
        task = f.queue.own(first['job']['id'])
        assert task['annotation_refs'] == [first['job']['annotation_id'], second['job']['annotation_id']]
        shown = await f.queue.view(task, False, first['job']['annotation_id'])
        assert shown['electrode_annotation']['electrode_names'] == A['electrode_names']
        shown = await f.queue.view(task, False, third['job']['annotation_id'])
        assert shown['electrode_annotation']['electrode_names'] == B['electrode_names']
        f.queue.dispose()
        restored = f.reopen()
        try:
            task = restored.own(first['job']['id'])
            shown = await restored.view(task, False, first['job']['annotation_id'])
            assert shown['electrode_annotation']['electrode_names'] == A['electrode_names']
            assert task['request'] == REQUEST
            assert jsjson.stringify(task['request']) == jsjson.stringify(REQUEST)
        finally:
            restored.dispose()

    run(body())
    assert os.listdir(f.cache_path.parent) == []
    assert tree(f.root) == before and not node_directory(f.root).exists()
    assert len(os.listdir(f.directory)) == 2


def test_sidecar_integrity_paths_crashed_temporaries_private_output_and_storage_limits(tmp_path):
    """check-electrode-annotations.mjs:100 'sidecar integrity, paths, crashed temporaries, private output and
    storage limits are enforced', in W: the public value has no owner, the file is Node's bytes with mode 0600 in
    directories of mode 0700, an interrupted temporary is tolerated and counted, the file limit gives 507, a path
    is not an id, and a changed or linked file fails its checks."""
    f = fixture(tmp_path)
    prepared = run(f.adapter.prepare(browser_submission(A)))
    first = f.annotations.create(prepared)
    directory = f.annotations.directory(*f.annotations.directories[0])
    assert directory == str(f.directory)
    assert LOCAL_OWNER not in jsjson.stringify(first) and 'owner' not in first
    path = f.directory / f'{first["id"]}.json'
    assert path.read_bytes() == jsjson.stringify({'id': first['id'], **{
        key: value for key, value in f.annotations.identity(prepared).items() if key != 'id'}}).encode('utf-8')
    assert jsjson.parse(path.read_text(encoding='utf-8'))['owner'] == LOCAL_OWNER
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 & ~_umask()
    for part in (f.workspace / 'annotations', f.directory):
        assert stat.S_IMODE(part.stat().st_mode) == 0o700 & ~_umask()
    assert os.listdir(f.directory) == [path.name]  # no temporary left behind
    (f.directory / f'.{uuid.uuid4()}.tmp').write_text('interrupted', encoding='utf-8')
    second = f.annotations.create({**prepared, 'electrode_names': B['electrode_names']})
    assert second['record_id'] == KEY
    assert len(f.annotations.list()) == 2
    limited = f.store(limits={**ANNOTATION_LIMITS, 'files': 3})
    files = sorted(os.listdir(f.directory))
    with pytest.raises(AnnotationError) as caught:
        limited.create({**prepared, 'electrode_names': names('C')})
    assert (caught.value.status, caught.value.message) == (507, LIMIT)
    assert sorted(os.listdir(f.directory)) == files
    with pytest.raises(AnnotationError) as caught:
        f.annotations.read('../outside', KEY)
    assert caught.value.status == 404
    original = path.read_text(encoding='utf-8')
    path.write_text(original.replace('A1', 'changed'), encoding='utf-8')
    with pytest.raises(AnnotationError) as caught:
        f.annotations.read(first['id'], KEY)
    assert (caught.value.status, caught.value.message) == (409, INTEGRITY)
    path.unlink()
    path.symlink_to(f.cache_path)
    with pytest.raises(AnnotationError) as caught:
        f.annotations.read(first['id'], KEY)
    assert (caught.value.status, caught.value.message) == (409, INTEGRITY)
    assert not node_directory(f.root).exists()


def test_lookup_misses_create_no_metadata_and_unwritable_storage_fails_before_receipts(tmp_path):
    """check-electrode-annotations.mjs:117 'lookup misses do not create metadata, blocked writes fail before
    receipts, bare cached reads stay available'. Node's resource gate is dropped (R2); a name store that cannot be
    written blocks the same way: the envelope fails before any receipt, while a bare lookup of the stored result
    still answers. A retry of a saved variant neither creates nor replaces its file."""
    f = fixture(tmp_path, cached=False)
    envelope = browser_submission(A)

    async def body() -> None:
        assert await f.queue.submit(KIND, envelope, lookup_only=True) == {'hit': False}
        assert not (f.workspace / 'annotations').exists() and f.queue.tasks == []
        (f.workspace / 'annotations').write_text('not a directory', encoding='utf-8')
        with pytest.raises(AnnotationError) as caught:
            await f.queue.submit(KIND, envelope)
        assert (caught.value.status, caught.value.message) == (409, UNAVAILABLE)
        assert f.queue.tasks == []
        f.write_cache()
        assert (await f.queue.submit(KIND, REQUEST, lookup_only=True))['hit'] is True
        with pytest.raises(AnnotationError):
            await f.queue.submit(KIND, envelope, lookup_only=True)
        assert len(f.queue.tasks) == 1 and 'annotation_refs' not in f.queue.tasks[0]
        (f.workspace / 'annotations').unlink()
        saved = await f.queue.submit(KIND, envelope, lookup_only=True)
        files = {name: os.stat(f.directory / name) for name in os.listdir(f.directory)}
        retry = await f.queue.submit(KIND, envelope, lookup_only=True)
        assert retry['job']['annotation_id'] == saved['job']['annotation_id'], 'A retry must not create or replace metadata.'
        after = {name: os.stat(f.directory / name) for name in os.listdir(f.directory)}
        assert {name: (item.st_ino, item.st_mtime_ns) for name, item in after.items()} == {
            name: (item.st_ino, item.st_mtime_ns) for name, item in files.items()}
        assert len(f.queue.tasks) == 1

    try:
        run(body())
    finally:
        f.queue.dispose()


def test_the_per_receipt_bound_and_the_file_size_bound_reject_new_variants_without_creating_files(tmp_path):
    """check-electrode-annotations.mjs:135 'per-owner and per-receipt metadata bounds reject new variants without
    creating files': 100 variants on a receipt refuse another (413); the per-owner bound is dropped (R1) and that
    part becomes the file-size bound: names and a source declaration that fit the route's 65,536 bytes but not the
    32,768 bytes of an annotation file are refused (413) without a file or a receipt change."""
    f = fixture(tmp_path)

    async def body() -> None:
        first = await f.queue.submit(KIND, browser_submission(A))
        task = f.queue.own(first['job']['id'])
        task['annotation_refs'] = [first['job']['annotation_id']] * 100
        with pytest.raises(QueueError) as caught:
            await f.queue.submit(KIND, browser_submission(B))
        assert (caught.value.status, caught.value.message) == (413, TASK_VARIANTS)
        assert len(f.annotations.list()) == 1
        task['annotation_refs'] = [first['job']['annotation_id']]
        for large in _too_large_submissions():
            assert len(jsjson.stringify(large).encode('utf-8')) <= 65536
            with pytest.raises(AnnotationError) as caught:
                await f.queue.submit(KIND, large)
            assert (caught.value.status, caught.value.message) == (413, TOO_LARGE)
            assert len(f.annotations.list()) == 1 and task['annotation_refs'] == [first['job']['annotation_id']]
            assert len(f.queue.tasks) == 1
        f.queue.dispose()

    run(body())
    assert len(os.listdir(f.directory)) == 1


def test_twenty_variants_do_not_bound_a_receipt(tmp_path):
    """Node's per-owner bound of 20 is dropped (R1): the bound that remains is Node's 100 per receipt
    (check-electrode-annotations.mjs:142-143)."""
    f = fixture(tmp_path)

    async def body() -> None:
        first = await f.queue.submit(KIND, browser_submission(A))
        task = f.queue.own(first['job']['id'])
        task['annotation_refs'] = [first['job']['annotation_id']] * 99
        added = await f.queue.submit(KIND, browser_submission(B))
        assert added['job']['annotation_id'] != first['job']['annotation_id']
        f.queue.dispose()

    run(body())


def test_a_temporary_renamed_while_the_directory_is_read_is_not_a_storage_failure(tmp_path, monkeypatch):
    """The library lists the annotations in a request thread while the queue's ``create`` renames its temporary on
    the event loop (Node's single thread never lists in the middle of its own write): a temporary gone between the
    directory listing and its ``lstat`` is skipped by ``list`` and by the next ``create``'s inspection."""
    from eeglayoutlab.jobs import nodefs

    f = fixture(tmp_path)
    lstat = nodefs.lstat

    def renamed_meanwhile(path: str) -> os.stat_result:
        if path.endswith('.tmp') and os.path.exists(path):
            os.unlink(path)
        return lstat(path)

    async def body() -> None:
        first = await f.queue.submit(KIND, browser_submission(A))
        (f.directory / f'.{uuid.uuid4()}.tmp').write_bytes(b'{"partial"')
        monkeypatch.setattr(nodefs, 'lstat', renamed_meanwhile)
        assert [value['id'] for value in f.store().list()] == [first['job']['annotation_id']]
        (f.directory / f'.{uuid.uuid4()}.tmp').write_bytes(b'{"partial"')
        added = await f.queue.submit(KIND, browser_submission(B))
        assert added['job']['annotation_id'] != first['job']['annotation_id']
        assert len(f.store().list()) == 2
        f.queue.dispose()

    run(body())
    assert sorted(name.endswith('.json') for name in os.listdir(f.directory)) == [True, True]


def test_an_annotation_removed_while_the_directory_is_read_is_nodes_storage_failure(tmp_path, monkeypatch):
    """Only a temporary is skipped when it disappears: an ``<id>.json`` removed between the listing and its ``lstat``
    (from outside: neither host removes one) fails as in Node, 409 for ``list`` and 503 for ``create``."""
    from eeglayoutlab.jobs import nodefs

    f = fixture(tmp_path)
    lstat = nodefs.lstat

    def removed_meanwhile(path: str) -> os.stat_result:
        if path.endswith('.json') and os.path.exists(path):
            os.unlink(path)
        return lstat(path)

    async def body() -> None:
        await f.queue.submit(KIND, browser_submission(A))
        await f.queue.submit(KIND, browser_submission(B))
        monkeypatch.setattr(nodefs, 'lstat', removed_meanwhile)
        with pytest.raises(AnnotationError) as caught:
            f.store().list()
        assert (caught.value.status, caught.value.message) == (409, UNAVAILABLE)
        with pytest.raises(AnnotationError) as caught:
            await f.queue.submit(KIND, browser_submission({**BASE, 'electrode_names': names('C')}))
        assert (caught.value.status, caught.value.message) == (503, UNAVAILABLE)
        f.queue.dispose()

    run(body())
    assert os.listdir(f.directory) == []


def test_named_variants_are_read_by_the_library_and_validate_as_snapshot_annotations(tmp_path):
    """check-electrode-annotations.mjs:147 'HTTP annotations require policy/token and owner; snapshots and delivery
    preserve each variant after sidecars disappear', below HTTP: two lookups of a stored result with other names
    give two variants of one key; the receipt view shows the selected one (an id it does not hold is 404), the
    library's reader (the ``?annotation_id`` of the record and bundle routes) finds both in W, each public value
    validates as a snapshot annotation, the cache bytes never change, and removing the name files leaves 404s
    (snapshots keep their copy: slice 9). Policy, token and query rules are route tests; owners are dropped (R1)."""
    f = fixture(tmp_path)
    before = f.cache_path.read_bytes()

    async def body() -> tuple[str, str]:
        first = await f.queue.submit(KIND, browser_submission(A), lookup_only=True)
        second = await f.queue.submit(KIND, browser_submission(B), lookup_only=True)
        aid, bid = first['job']['annotation_id'], second['job']['annotation_id']
        assert aid != bid and first['job']['key'] == second['job']['key'] == KEY
        assert first['job']['electrode_annotation']['electrode_names'] == A['electrode_names']
        old = await f.queue.view(f.queue.own(first['job']['id']), True, aid)
        assert old['electrode_annotation']['electrode_names'] == A['electrode_names'] and old['result'] == RESULT
        with pytest.raises(QueueError) as caught:
            await f.queue.view(f.queue.own(first['job']['id']), True, 'd' * 64)
        assert (caught.value.status, caught.value.message) == (404, ANNOTATION_NOT_FOUND)
        f.queue.dispose()
        return aid, bid

    aid, bid = run(body())
    library = Library(str(f.root), runtime_config(str(f.root)), str(f.directory))
    shown = library.annotations.read(aid, KEY)
    assert shown['electrode_names'] == A['electrode_names'] and 'owner' not in shown
    listed = {value['id']: value for value in library.annotations.list()}
    assert set(listed) == {aid, bid} and listed[bid]['electrode_names'] == B['electrode_names']
    for value in listed.values():
        assert validate_electrode_annotation(value, KEY) is value and '"owner"' not in jsjson.stringify(value)
    shutil.rmtree(f.directory)
    for id in (aid, bid):
        with pytest.raises(AnnotationError) as caught:
            library.annotations.read(id, KEY)
        assert (caught.value.status, caught.value.message) == (404, NOT_FOUND)
    assert f.cache_path.read_bytes() == before


def test_multibyte_names_survive_a_body_split_inside_every_character(tmp_path):
    """check-electrode-annotations.mjs:212 'multibyte electrode names survive request chunks split inside every UTF-8
    character', at the body reader of the routes (``read_json_body`` with the design-evaluation limit of 65,536
    bytes as received): a body sent one byte at a time is decoded whole, and its names reach the annotation; one
    byte over the limit is 413 ``配置过大``. The same over HTTP is the route stage's."""
    from starlette.requests import Request

    from eeglayoutlab.server.app import BODY_LIMITS, ApiError, read_json_body

    def request(body: bytes, size: int = 1) -> Request:
        pieces = [body[index:index + size] for index in range(0, len(body), size)] or [b'']

        async def receive() -> dict:
            piece = pieces.pop(0) if pieces else b''
            return {'type': 'http.request', 'body': piece, 'more_body': bool(pieces)}
        scope = {'type': 'http', 'method': 'POST', 'path': '/api/design-evaluation/lookup', 'query_string': b'',
                 'headers': [(b'content-type', b'application/json')]}
        return Request(scope, receive)

    f = fixture(tmp_path)
    labels = names('电极🧠')
    body = jsjson.stringify(browser_submission({**BASE, 'electrode_names': labels})).encode('utf-8')
    limit = BODY_LIMITS[KIND]
    assert limit == 65536 and len(body) < limit
    assert ''.join(body[i:i + 1].decode('utf-8', errors='replace') for i in range(len(body))) != body.decode('utf-8')

    async def submit() -> dict:
        raw = await read_json_body(request(body), limit)
        response = await f.queue.submit(KIND, raw, lookup_only=True)
        f.queue.dispose()
        return response

    response = run(submit())
    assert response['job']['electrode_annotation']['electrode_names'] == labels
    # The limit counts bytes as received: an envelope padded to exactly the limit is read, one byte more is not.
    padded = body[:-1] + b' ' * (limit - len(body)) + b'}'
    assert len(padded) == limit and run(read_json_body(request(padded, 7), limit))['electrode_names'] == labels
    with pytest.raises(ApiError) as caught:
        run(read_json_body(request(padded + b' ', 7), limit))
    assert (caught.value.status, str(caught.value.message)) == (413, '配置过大')


def _umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


def _too_large_submissions() -> list[dict]:
    """Envelopes within the route limit whose annotation file is over 32,768 bytes: names of 128 CJK characters
    (3 bytes each) with the longest source descriptions, and names of 128 lone surrogates (6 bytes each as
    ``\\udXXX``)."""
    v1 = coordinate_sources()['v1']
    source = {**v1, 'coordinate_system_description': '坐' * 2048, 'region_description': '区' * 1024}
    cjk = [chr(0x4E00 + i) * 128 for i in range(64)]
    surrogates = [chr(0xD800 + i) * 128 for i in range(64)]
    return [browser_submission({**BASE, 'electrode_names': cjk, 'source_metadata': source}),
            browser_submission({**BASE, 'electrode_names': surrogates})]


# --- The write side --------------------------------------------------------------------------------------------

def test_an_existing_file_is_read_and_never_rewritten(tmp_path):
    f = fixture(tmp_path)
    prepared = run(f.adapter.prepare(browser_submission(A)))
    first = f.annotations.create(prepared)
    path = f.directory / f'{first["id"]}.json'
    before = os.stat(path)
    assert f.store().create(prepared) == first
    after = os.stat(path)
    assert (after.st_ino, after.st_mtime_ns, after.st_size) == (before.st_ino, before.st_mtime_ns, before.st_size)
    # A changed file with the id fails its checks and stays as it is.
    changed = path.read_bytes().replace(b'"A1"', b'"Z1"')
    path.write_bytes(changed)
    with pytest.raises(AnnotationError) as caught:
        f.store().create(prepared)
    assert (caught.value.status, caught.value.message) == (409, INTEGRITY) and path.read_bytes() == changed
    f.queue.dispose()


def test_new_annotations_go_to_the_workspace_only(tmp_path):
    """Python never writes Node's directory (R): without a workspace directory there is nowhere to write (503), a
    Node annotation is still read, and a linked or non-directory component of W is refused (409)."""
    f = fixture(tmp_path)
    f.queue.dispose()
    prepared = run(f.adapter.prepare(browser_submission(A)))
    readonly = ElectrodeAnnotations.local(None, str(f.root))
    with pytest.raises(AnnotationError) as caught:
        readonly.create(prepared)
    assert (caught.value.status, caught.value.message) == (503, UNAVAILABLE)
    assert not node_directory(f.root).exists()
    created = f.annotations.create(prepared)
    node_directory(f.root).mkdir(parents=True)
    shutil.copyfile(f.directory / f'{created["id"]}.json', node_directory(f.root) / f'{created["id"]}.json')
    assert readonly.read(created['id'], KEY) == created
    shutil.rmtree(f.workspace / 'annotations')
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    (f.workspace / 'annotations').symlink_to(elsewhere)
    with pytest.raises(AnnotationError) as caught:
        f.store().create({**prepared, 'electrode_names': names('L')})
    assert (caught.value.status, caught.value.message) == (409, UNAVAILABLE)
    assert os.listdir(elsewhere) == []
    missing = ElectrodeAnnotations.local(str(tmp_path / 'none' / 'annotations' / 'electrode-names'), str(f.root))
    with pytest.raises(AnnotationError) as caught:
        missing.create(prepared)
    assert (caught.value.status, caught.value.message) == (503, UNAVAILABLE)
    assert missing.read(created['id'], KEY) == created  # reads still reach Node's directory


@pytest.mark.skipif(os.geteuid() == 0, reason='root ignores directory permissions')
def test_a_directory_that_cannot_be_written_is_unavailable(tmp_path):
    f = fixture(tmp_path)
    f.queue.dispose()
    prepared = run(f.adapter.prepare(browser_submission(A)))
    f.directory.mkdir(parents=True)
    f.directory.chmod(0o500)
    try:
        with pytest.raises(AnnotationError) as caught:
            f.annotations.create(prepared)
        assert (caught.value.status, caught.value.message) == (503, UNAVAILABLE)
    finally:
        f.directory.chmod(0o700)
    assert os.listdir(f.directory) == []


def test_identity_rules_in_nodes_order(tmp_path):
    prepared = {'request': REQUEST, 'key': KEY, 'electrode_names': names('A')}
    store = ElectrodeAnnotations([(str(tmp_path), WORKSPACE_ANNOTATIONS)], writable=True)
    value = store.identity(prepared)
    assert list(value) == ['id', 'schema', 'owner', 'record_id', 'request_sha256', 'xyz_sha256', 'regions_sha256',
                           'electrode_names']
    assert value['owner'] == LOCAL_OWNER == hashlib.sha256(b'eeglayoutlab-local-user/1').hexdigest()
    assert value['request_sha256'] == jsjson.sha256_hex(REQUEST)
    assert value['xyz_sha256'] == jsjson.sha256_hex(REQUEST['design']['xyz_mm'])
    assert value['id'] == jsjson.sha256_hex({key: item for key, item in value.items() if key != 'id'})
    cases = {
        'names first': ({**prepared, 'key': 'A' * 64, 'electrode_names': names('A')[1:]}, LOCAL_OWNER, NAMES),
        'key': ({**prepared, 'key': 'A' * 64}, LOCAL_OWNER, INVALID_IDENTITY),
        'no key': ({key: item for key, item in prepared.items() if key != 'key'}, LOCAL_OWNER, INVALID_IDENTITY),
        'empty owner': (prepared, '', INVALID_IDENTITY),
        'long owner': (prepared, '😀' * 64 + 'x', INVALID_IDENTITY),
        'owner number': (prepared, 7, INVALID_IDENTITY),
    }
    for label, (item, owner, message) in cases.items():
        with pytest.raises(AnnotationError) as caught:
            ElectrodeAnnotations([(str(tmp_path), WORKSPACE_ANNOTATIONS)], owner=owner).identity(item)
        assert (caught.value.status, caught.value.message) == (400, message), label
    with pytest.raises(CoordinateSourceError) as caught:
        store.identity({**prepared, 'source_metadata': None})
    assert str(caught.value) == SOURCE and not hasattr(caught.value, 'status')
    assert ElectrodeAnnotations([], owner='😀' * 64).identity(prepared)['owner'] == '😀' * 64


def test_design_submission_follows_nodes_checks():
    named = browser_submission(A)
    assert design_submission(REQUEST) == {'request': REQUEST}
    for bare in (None, [], 'design-submission/1', 1, {'schema': 'design-submission/2'}, {'schema': ['design-submission/1']}):
        assert design_submission(bare) == {'request': bare}
    assert design_submission(named) == {'request': named['request'], 'electrode_names': A['electrode_names']}
    source = coordinate_sources()['v2Labels']
    reordered = dict(reversed(list(source.items())))
    out = design_submission({'source_metadata': reordered, **named})
    assert list(out) == ['request', 'electrode_names', 'source_metadata']
    assert list(out['source_metadata']) == list(reordered) and out['source_metadata'] is not reordered
    for raw, error in {
        'extra': ({**named, 'extra': 1}, INVALID_SUBMISSION), 'no request': ({**named, 'request': 0}, INVALID_SUBMISSION),
        'extra before names': ({**named, 'extra': 1, 'electrode_names': []}, INVALID_SUBMISSION),
        'names': ({**named, 'electrode_names': names('A')[:63]}, NAMES),
        'names before source': ({**named, 'electrode_names': None, 'source_metadata': None}, NAMES),
    }.values():
        with pytest.raises(AnnotationError) as caught:
            design_submission(raw)
        assert (caught.value.status, caught.value.message) == (400, error)
    for value in (None, False, 0, '', [], {}, {**source, 'unit': 'cm'}):
        with pytest.raises(CoordinateSourceError):
            design_submission({**named, 'source_metadata': value})


# --- Parity with Node's designSubmission and ElectrodeAnnotations -------------------------------------------------

LABELS = [f'E{i + 1}' for i in range(64)]
SHA = hashlib.sha256(b'record').hexdigest()
NAME_VALUES: dict[str, Any] = {
    # accepted
    'cjk': '电极', 'emoji': '🧠', 'combining': 'é', 'precomposed': 'é', 'rtl': 'قطب', 'zwj': '👩‍🔬',
    'quote': '"', 'backslash': '\\', 'script': '</script>', 'nel': '\x85', 'zero-width': '​', 'fffe': '￾',
    'max-plane': '\U0010ffff', 'separator-inside': 'F z', 'lone-high': '\ud800', 'lone-low': '\udc00',
    'reversed-pair': '\udc00\ud800', 'padded': ' Fz ', 'tilde': '~', 'len128': 'x' * 128, 'emoji64': '😀' * 64,
    'cjk128': '电' * 128, 'emoji-and-x': '😀' * 63 + 'xy',
    # refused
    'spaces': '   ', 'nbsp': '\xa0', 'bom': '﻿', 'ideographic': '　', 'line-separator': ' ',
    'ogham': ' ', 'tab': 'F\tz', 'del': 'F\x7fz', 'nul': '\x00', 'unit-separator': '\x1f', 'newline': 'F\nz',
    'empty': '', 'len129': 'x' * 129, 'emoji65': '😀' * 65, 'number': 1, 'null': None, 'list': ['E6'],
    'object': {}, 'true': True,
}
NAME_LISTS: dict[str, Any] = {
    **{f'at-5-{label}': [value if i == 5 else name for i, name in enumerate(LABELS)] for label, value in NAME_VALUES.items()},
    'all-cjk': [f'电极{i}' for i in range(64)], 'all-emoji': [chr(0x1F600 + i) for i in range(64)],
    'nfc-and-nfd': ['é', 'é', *LABELS[2:]], 'case': ['e1', 'E1', *LABELS[2:]],
    'duplicate': ['E1', *LABELS[1:5], 'E1', *LABELS[6:]], 'duplicate-lone': ['\ud800', '\ud800', *LABELS[2:]],
    '63': LABELS[1:], '65': [*LABELS, 'E65'], 'empty': [], 'object': {'0': 'E1'}, 'string': 'E1', 'null': None,
    'surrogates-128': [chr(0xD800 + i) * 128 for i in range(64)], 'cjk-128': [chr(0x4E00 + i) * 128 for i in range(64)],
}
OWNERS: dict[str, Any] = {
    'local': LOCAL_OWNER, 'browser': 'a' * 64, 'x128': 'x' * 128, 'emoji64': '😀' * 64, 'spaced': 'owner 名 ',
    'lone': '\ud800', 'x129': 'x' * 129, 'emoji64-x': '😀' * 64 + 'x', 'empty': '', 'number': 123, 'null': None,
}
KEYS: dict[str, Any] = {
    'sha': SHA, 'upper': SHA.upper(), 'short': SHA[1:], 'long': SHA + 'a', 'newline': SHA + '\n', 'space': ' ' + SHA,
    'number': 123, 'null': None, 'array': [SHA], 'nested-array': [[SHA]],
}


def _source_variants() -> list[tuple[str, str, bool]]:
    """The coordinate-source corpus: (name, JSON text, accepted) for every variant whose text parses."""
    out = []
    for variant in (CORPUS or {}).get('formats', {}).get('coordinate-source', {}).get('variants', []):
        text = body_text(variant)
        try:
            jsjson.parse(text)
        except ValueError:
            continue
        out.append((variant['name'], text, variant['accepted']))
    return out


def _design_variants() -> list[dict]:
    return list((CORPUS or {}).get('formats', {}).get('design-evaluation', {}).get('variants', []))


def submission_cases() -> dict[str, str]:
    """Request texts for ``designSubmission``: the design-evaluation corpus, envelopes with every name list and
    every coordinate source of the corpus, and envelopes of other shapes."""
    cases: dict[str, str] = {}
    for variant in _design_variants():
        text = body_text(variant)
        try:
            jsjson.parse(text)
        except ValueError:
            continue
        cases[f'corpus/{variant["name"]}'] = text
    request = jsjson.stringify(REQUEST)
    labels = jsjson.stringify(LABELS)

    def envelope(**members: Any) -> str:
        value = {'schema': 'design-submission/1', 'request': REQUEST, 'electrode_names': LABELS, **members}
        return jsjson.stringify({key: item for key, item in value.items() if item is not UNDEFINED})

    for label, value in NAME_LISTS.items():
        cases[f'names/{label}'] = envelope(electrode_names=value)
    for name, text, _ in _source_variants():
        cases[f'source/{name}'] = (f'{{"schema":"design-submission/1","request":{request},"electrode_names":{labels},'
                                   f'"source_metadata":{text}}}')
    for label, value in {'null': None, 'false': False, 'zero': 0, 'empty-string': '', 'array': [], 'object': {}}.items():
        cases[f'source-value/{label}'] = envelope(source_metadata=value)
    for label, value in {'zero': 0, 'empty-string': '', 'false': False, 'null': None, 'array': [], 'object': {},
                         'string': 'x', 'absent': UNDEFINED, 'number': 1}.items():
        cases[f'request/{label}'] = envelope(request=value)
    for label, value in {'trailing-space': 'design-submission/1 ', 'upper': 'Design-submission/1', 'other': 'design-submission/2',
                         'number': 1, 'null': None, 'array': ['design-submission/1'], 'absent': UNDEFINED}.items():
        cases[f'schema/{label}'] = envelope(schema=value)
    v1 = jsjson.stringify(coordinate_sources().get('v1'))
    cases.update({
        'shape/null': 'null', 'shape/array': '[]', 'shape/string': '"design-submission/1"', 'shape/number': '1',
        'shape/true': 'true', 'shape/empty': '{}', 'shape/schema-only': '{"schema":"design-submission/1"}',
        'shape/names-first': f'{{"electrode_names":{labels},"request":{request},"schema":"design-submission/1"}}',
        'shape/source-first': f'{{"source_metadata":{v1},"electrode_names":{labels},"schema":"design-submission/1","request":{request}}}',
        'shape/proto': f'{{"schema":"design-submission/1","request":{request},"electrode_names":{labels},"__proto__":{{}}}}',
        'shape/duplicate-schema': f'{{"schema":"x","schema":"design-submission/1","request":{request},"electrode_names":{labels}}}',
        'shape/duplicate-request': f'{{"schema":"design-submission/1","request":null,"request":{request},"electrode_names":{labels}}}',
        'shape/duplicate-names': f'{{"schema":"design-submission/1","request":{request},"electrode_names":null,"electrode_names":{labels}}}',
        'order/extra-and-names': envelope(extra=1, electrode_names=None),
        'order/names-and-source': envelope(electrode_names=LABELS[1:], source_metadata=None),
        'order/request-and-names': envelope(request=0, electrode_names=None),
    })
    return cases


@dataclass
class IdentityCase:
    """A prepared value as JSON text, which each host parses (numbers such as 1e400 have no JSON.stringify form),
    with the owner of the store and whether ``create`` follows ``identity``."""
    id: str
    owner: Any
    text: str
    create: bool
    prepared: Any = None

    def __post_init__(self) -> None:
        self.prepared = jsjson.parse(self.text)


def _prepared(request: Any = REQUEST, key: Any = SHA, names_value: Any = LABELS, source: Any = UNDEFINED) -> dict:
    value = {'request': request, 'key': key, 'electrode_names': names_value, 'source_metadata': source}
    return {name: item for name, item in value.items() if item is not UNDEFINED}


def identity_cases() -> list[IdentityCase]:
    """Prepared values and owners for ``identity`` and, where marked, ``create``, in the order both stores run them:
    every name list, owner and key; every canonical request and envelope of the design-evaluation corpus; every
    coordinate source of its corpus; refusals in Node's order; repeats of earlier cases."""
    cases: list[IdentityCase] = []

    def add(id: str, prepared: Any, owner: Any = LOCAL_OWNER, create: bool = True) -> None:
        cases.append(IdentityCase(id, owner, prepared if isinstance(prepared, str) else jsjson.stringify(prepared), create))

    for label, value in NAME_LISTS.items():
        add(f'names/{label}', _prepared(names_value=value))
    for label, owner in OWNERS.items():
        add(f'owner/{label}', _prepared(), owner)
    for label, key in KEYS.items():
        add(f'key/{label}', _prepared(key=key))
    add('key/absent', {'request': REQUEST, 'electrode_names': LABELS})
    add('names/absent', {'request': REQUEST, 'key': SHA})
    for index, variant in enumerate(v for v in _design_variants() if v['accepted']):
        canonical = jsjson.parse(variant['canonical'])
        key = hashlib.sha256(variant['name'].encode('utf-8')).hexdigest()
        prepared = _prepared(canonical['request'], key, canonical.get('electrode_names', LABELS),
                             canonical.get('source_metadata', UNDEFINED))
        add(f'request/{variant["name"]}', prepared, create='electrode_names' in canonical or index % 8 == 0)
    request, labels = jsjson.stringify(REQUEST), jsjson.stringify(LABELS)
    for name, text, accepted in _source_variants():
        create = accepted and name.startswith(('valid-', 'reversed-', 'nested-reversed-'))
        add(f'source/{name}', f'{{"request":{request},"key":"{SHA}","electrode_names":{labels},"source_metadata":{text}}}',
            create=create)
    add('order/names-key-source', _prepared(key='A' * 64, names_value=LABELS[1:], source=None))
    add('order/key-source', _prepared(key='A' * 64, source=None))
    add('order/owner-source', _prepared(source=None), '')
    add('order/source', _prepared(source=None))
    # Repeats: the file exists and is read back; a key that is an array matches SHA as a string but is not the
    # stored record id (another array), so the second create is 404 in both.
    add('repeat/labels', _prepared())
    add('repeat/browser', _prepared(), 'a' * 64)
    add('repeat/array-key', _prepared(key=[SHA]))
    return cases


IDENTITY_CASES = identity_cases()
SUBMISSIONS = submission_cases()


def _value(run: Any) -> dict:
    try:
        return {'ok': True, 'value': jsjson.stringify(run())}
    except Exception as error:  # noqa: BLE001 - every failure is compared with Node's
        return failure(error)


def _node(result: dict) -> dict:
    return result if result['ok'] else node_failure(result)


@pytest.fixture(scope='module')
def parity(tmp_path_factory):
    base = Path(os.path.realpath(tmp_path_factory.mktemp('annotation-parity')))
    workspace, python_root, node_root = base / 'W', base / 'python-root', base / 'node-root'
    for path in (workspace, python_root, node_root):
        path.mkdir()
    submissions = {id: _value(lambda text=text: design_submission(jsjson.parse(text))) for id, text in SUBMISSIONS.items()}
    stores: dict[str, ElectrodeAnnotations] = {}
    identities: dict[str, dict] = {}
    for case in IDENTITY_CASES:
        store = stores.setdefault(jsjson.stringify(case.owner), ElectrodeAnnotations(
            [(str(workspace), WORKSPACE_ANNOTATIONS)], owner=case.owner, writable=True))
        entry = {'identity': _value(lambda: store.identity(case.prepared))}
        if case.create:
            entry['create'] = _value(lambda: store.create(case.prepared))
            if entry['create']['ok']:
                id = jsjson.parse(entry['create']['value'])['id']
                entry['create']['file'] = base64.b64encode(
                    workspace.joinpath(*WORKSPACE_ANNOTATIONS, f'{id}.json').read_bytes()).decode('ascii')
        identities[case.id] = entry
    # Python's files where Node reads them, under the owner Node is given. A file whose record id is not a string
    # (an array key) reads as 404 in both hosts, and so fails a listing; it stays out of the listed directories.
    node_directory(python_root).mkdir(parents=True)
    reads, owners, listed = [], {}, base / 'listed'
    listed.joinpath(*WORKSPACE_ANNOTATIONS).mkdir(parents=True)
    for case in IDENTITY_CASES:
        created = identities[case.id].get('create', {})
        if created.get('ok') and isinstance(case.prepared['key'], str):
            id = jsjson.parse(created['value'])['id']
            for directory in (node_directory(python_root), listed.joinpath(*WORKSPACE_ANNOTATIONS)):
                if not (directory / f'{id}.json').exists():
                    shutil.copyfile(workspace.joinpath(*WORKSPACE_ANNOTATIONS, f'{id}.json'), directory / f'{id}.json')
            reads.append({'id': case.id, 'root': str(python_root), 'annotation': id, 'owner': case.owner,
                          'record': case.prepared['key']})
            owners[jsjson.stringify(case.owner)] = case.owner
    lists = [{'id': f'{root.name}/{key}', 'root': str(root), 'owner': owner}
             for root in (python_root, node_root) for key, owner in owners.items()]
    spec = {'root': str(node_root), 'submissions': [{'id': id, 'text': text} for id, text in SUBMISSIONS.items()],
            'identities': [{'id': case.id, 'owner': case.owner, 'prepared': case.text, 'create': case.create}
                           for case in IDENTITY_CASES], 'reads': reads, 'lists': lists}
    node = run_annotations_node(spec, base)
    return {'base': base, 'workspace': workspace, 'listed': listed, 'node_root': node_root, 'python_root': python_root,
            'submissions': submissions, 'identities': identities, 'node': node, 'owners': owners}


@needs_node
def test_design_submission_parity(parity):
    node = parity['node']['submissions']
    mismatches = {id: (value, _node(node[id])) for id, value in parity['submissions'].items() if value != _node(node[id])}
    assert mismatches == {}


@needs_node
def test_identity_parity(parity):
    node = parity['node']['identities']
    mismatches = {}
    for case in IDENTITY_CASES:
        python, theirs = parity['identities'][case.id], node[case.id]
        expected = {'identity': _node(theirs['identity']),
                    **({'create': _node(theirs['create'])} if case.create else {})}
        if python != expected:
            mismatches[case.id] = (python, expected)
    assert mismatches == {}


@needs_node
def test_python_files_read_back_in_node_and_node_files_in_python(parity):
    """Every file Python wrote, put where Node reads, gives Node's ``read(id, owner, key)`` the value Python's create
    returned, and the owners' ``list`` the same values as Python's ``list()``; every file Node wrote reads back the
    same in the slice 3 reader (W first, then Node's directory, without regard to the owner). A directory with the
    file of an array key fails both hosts' listings with 404."""
    node = parity['node']
    created = {case.id: jsjson.parse(parity['identities'][case.id]['create']['value'])
               for case in IDENTITY_CASES if parity['identities'][case.id].get('create', {}).get('ok')}
    assert node['reads'] and all(node['reads'][id] == {'ok': True, 'value': jsjson.stringify(created[id])}
                                 for id in node['reads'])
    python_listed = sorted(jsjson.stringify(value) for value in ElectrodeAnnotations.local(
        str(parity['listed'].joinpath(*WORKSPACE_ANNOTATIONS)), str(parity['base'] / 'none')).list())
    node_listed = sorted(text for key in parity['owners'] for text in node['lists'][f'python-root/{key}']['values'])
    assert python_listed == node_listed and len(python_listed) == len(os.listdir(node_directory(parity['python_root'])))
    reader = ElectrodeAnnotations.local(str(parity['base'] / 'empty' / 'annotations' / 'electrode-names'),
                                        str(parity['node_root']))
    node_values = {}
    for case in IDENTITY_CASES:
        theirs = node['identities'][case.id].get('create', {})
        if theirs.get('ok') and isinstance(case.prepared['key'], str):
            value = jsjson.parse(theirs['value'])
            assert jsjson.stringify(reader.read(value['id'], case.prepared['key'])) == theirs['value'], case.id
            node_values[value['id']] = theirs['value']
    assert len(node_values) == len(python_listed)
    with pytest.raises(AnnotationError) as caught:
        reader.list()
    assert (caught.value.status, caught.value.message) == (404, NOT_FOUND)
    assert all(node['lists'][f'node-root/{key}'] == {**node['lists'][f'node-root/{key}'], 'ok': False, 'status': 404,
                                                     'message': NOT_FOUND} for key in parity['owners'])
    copy = parity['base'] / 'node-listed'
    node_directory(copy).mkdir(parents=True)
    for id in node_values:
        shutil.copyfile(node_directory(parity['node_root']) / f'{id}.json', node_directory(copy) / f'{id}.json')
    assert sorted(jsjson.stringify(value) for value in ElectrodeAnnotations.local(None, str(copy)).list()) == sorted(
        node_values.values()) == python_listed


@needs_node
def test_parity_cases_reach_their_branches(parity):
    """Parity alone would also pass if the cases missed a branch; these pin what the cases exercise."""
    submissions, identities = parity['submissions'], parity['identities']
    messages = {value.get('message') for value in submissions.values() if not value['ok']}
    assert {INVALID_SUBMISSION, NAMES, SOURCE} <= messages
    assert sum(value['ok'] for value in submissions.values()) > 500
    assert submissions['shape/proto']['message'] == INVALID_SUBMISSION
    assert submissions['shape/duplicate-schema']['ok'] and submissions['source/valid-v3Mni']['ok']
    assert submissions['order/names-and-source']['message'] == NAMES
    outcomes = {(case.id, step): value for case in IDENTITY_CASES for step, value in identities[case.id].items()}
    statuses = {(value.get('message'), value.get('status')) for value in outcomes.values() if not value['ok']}
    assert {(NAMES, 400), (INVALID_IDENTITY, 400), (SOURCE, None), (TOO_LARGE, 413), (NOT_FOUND, 404)} <= statuses
    created = [value for (_, step), value in outcomes.items() if step == 'create' and value['ok']]
    assert any('source_metadata' in jsjson.parse(value['value']) for value in created)
    # The counts the plan and tests/service/README.md give: envelopes, identities, creates attempted, files created,
    # the files with a string key Node reads back, and the distinct ones both hosts list.
    listed = os.listdir(parity['listed'].joinpath(*WORKSPACE_ANNOTATIONS))
    assert (len(submissions), len(IDENTITY_CASES), sum(case.create for case in IDENTITY_CASES), len(created),
            len(parity['node']['reads']), len(listed)) == (2879, 1840, 179, 132, 130, 125)
    assert identities['repeat/labels']['create']['value'] == identities['owner/local']['create']['value']
    assert identities['repeat/array-key']['create'] == {'ok': False, 'message': NOT_FOUND, 'status': 404, 'safe': True}
    assert identities['key/array']['create']['ok'] and identities['key/nested-array']['create']['ok']
    for label in ('surrogates-128', 'cjk-128'):
        assert identities[f'names/{label}']['identity']['ok']
    assert identities['names/surrogates-128']['create']['message'] == TOO_LARGE
    assert identities['names/cjk-128']['create']['ok']  # 24.6 KB of names alone still fits
    assert identities['order/names-key-source']['identity']['message'] == NAMES
    assert identities['order/key-source']['identity']['message'] == INVALID_IDENTITY
    assert identities['order/source']['identity']['message'] == SOURCE
    ids = {jsjson.parse(identities[f'owner/{label}']['identity']['value'])['id'] for label in ('local', 'browser')}
    assert len(ids) == 2  # the id covers the owner
