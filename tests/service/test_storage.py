"""Record storage writes, checkout isolation, symlink containment, and service store/slot sharing (slice 4).

Ports:
- ``check-runtime-storage.mjs::record storage isolates checkouts and preserves the previous JSON when replacement fails``
- ``check-runtime-storage.mjs::record reads and batch creation reject symlinks to external data``
- ``check-service-storage.mjs::service factory shares one record store and honors a paused custom queue directory``
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from eeglayoutlab.jobs.library import Library
from eeglayoutlab.jobs.queue import QueueError, WorkspaceQueue, radius_adapter
from eeglayoutlab.jobs.radius import RadiusService
from eeglayoutlab.jobs.records import RecordError, RecordStore, atomic_json
from eeglayoutlab.jobs.runtime import runtime_config
from eeglayoutlab.jobs.worker import ExecutionSlot

KEY = 'a' * 64
BATCH_ID = '11111111-2222-3333-4444-555555555555'


def test_record_storage_isolates_checkouts_and_preserves_the_previous_json_when_replacement_fails(tmp_path: Path):
    """check-runtime-storage.mjs::record storage isolates checkouts and preserves the previous JSON when replacement
    fails."""
    checkout_a = tmp_path / 'checkout-a'
    checkout_b = tmp_path / 'checkout-b'
    checkout_a.mkdir()
    checkout_b.mkdir()
    store_a = RecordStore(str(checkout_a))
    store_b = RecordStore(str(checkout_b))

    file_a = store_a.path('radius', KEY, 'cache.json')
    file_b = store_b.path('radius', KEY, 'cache.json')
    assert file_a != file_b

    os.makedirs(os.path.dirname(file_a), exist_ok=True)
    store_a.write(file_a, {'status': 'completed', 'value': 1})
    assert store_a.read(file_a) == {'status': 'completed', 'value': 1}
    assert store_a.keys('radius') == [KEY]
    assert store_b.keys('radius') == []
    with pytest.raises(FileNotFoundError):
        store_b.read(file_b)

    circular: dict = {}
    circular['self'] = circular
    with pytest.raises(TypeError, match='circular'):
        atomic_json(file_a, circular)
    assert store_a.read(file_a) == {'status': 'completed', 'value': 1}
    assert [name for name in os.listdir(os.path.dirname(file_a)) if name.endswith('.tmp')] == []

    with pytest.raises(RecordError, match='Unknown record kind'):
        store_a.directory('unknown')
    with pytest.raises(RecordError, match='Invalid scientific record key'):
        store_a.path('radius', '../escape')
    with pytest.raises(RecordError, match='Invalid scientific record key'):
        store_a.path('radius', 'A' * 64)
    with pytest.raises(RecordError, match='Record path leaves its directory'):
        store_a.path('radius', KEY, '..', 'outside.json')


def test_record_reads_and_batch_creation_reject_symlinks_to_external_data(tmp_path: Path):
    """check-runtime-storage.mjs::record reads and batch creation reject symlinks to external data."""
    root = tmp_path / 'repo'
    outside = tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    secret = outside / 'secret.json'
    secret.write_text('{"secret":true}', encoding='utf-8')

    store = RecordStore(str(root))
    batch_dir = store.create_batch('radius', KEY, BATCH_ID)
    assert Path(batch_dir).is_dir()

    with pytest.raises(RecordError, match='Invalid batch identifier'):
        store.create_batch('radius', KEY, '../not-a-uuid')

    linked_file = Path(store.path('radius', KEY, 'linked.json'))
    linked_file.symlink_to(secret)
    with pytest.raises(RecordError, match='Record path leaves the repository'):
        store.read(str(linked_file))

    escaped_key = 'b' * 64
    escaped_dir = root / 'results/v2/local_app_jobs' / escaped_key
    escaped_dir.parent.mkdir(parents=True, exist_ok=True)
    escaped_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RecordError, match='Record path leaves the repository'):
        store.write(store.path('radius', escaped_key, 'cache.json'), {'ok': True})
    with pytest.raises(RecordError, match='Record directory leaves the repository'):
        store.create_batch('radius', escaped_key, BATCH_ID)
    assert escaped_key not in store.keys('radius')


def test_service_factory_shares_one_record_store_and_execution_slot(tmp_path: Path):
    """check-service-storage.mjs::service factory shares one record store and honors a paused custom queue directory
    (the paused maintenance file is replaced by --cache-only in the Python service)."""
    from .library_support import code_tree, forward_inputs

    root = tmp_path / 'root'
    root.mkdir()
    code_tree(root)
    forward_inputs(root)

    rt = runtime_config(str(root))
    slot = ExecutionSlot()
    lib = Library(rt.repository_root, rt)
    radius = RadiusService(rt.repository_root, python=rt.python, store=lib.store, execution_slot=slot)
    qdir = tmp_path / 'workspace-queue'
    q = WorkspaceQueue(str(qdir), {'local-compute': radius_adapter(radius)}, root=rt.repository_root,
                       execution_slot=slot, cache_only=True, poll_ms=None)
    try:
        assert radius.store is lib.store
        assert radius.execution_slot is q.execution_slot
        stats = q.stats()
        assert stats['maintenance'] is True and stats['drained'] is True
        assert q.submit('local-compute', {'region_count': 1, 'radius_mm': 20, 'mode': 'whole_surface'},
                        lookup_only=True) == {'hit': False}
        with pytest.raises(QueueError) as refused:
            q.submit('local-compute', {'region_count': 1, 'radius_mm': 20, 'mode': 'whole_surface'})
        assert refused.value.status == 503 and '维护中' in refused.value.message
    finally:
        q.dispose()
        radius.dispose()
