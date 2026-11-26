"""Signal reception's run path (``eeglayoutlab.jobs.reception``, phase 2 slice 7).

Ports check-source-reception.mjs's validator test (:155), its service tests (:212, :242, :264, :277, :318, :335,
driven through ``FakeChild`` as Node drives its fake children, with the same context stub) and its noise guard test
(:366), check-cross-region-contract.mjs's cross-region validator test (:94, all sixteen corruptions) and
check-source-upgrade.mjs's v2 identity test (:183). Then what Python adds: the installation lock, the publish-once
rule, the completion callbacks, the queue's prepared submit and startup finish time, ``aclose``, a cancel during the
spawn, the memo of verified records, real worker and catalog processes, the workers' environment as Node passes it,
the bounded cleanup of the test drivers; and the byte parity of every record the run path writes with Node's own
``SourceReceptionService`` (``parity/reception_run.mjs``) on reception roots, where the contexts (v1's digests, v2's
design identity, code digests and runtime inspector) are the real ones on both sides.
"""
from __future__ import annotations

import asyncio
import copy
import os
from pathlib import Path
import re
import threading
import time

import pytest

from schema_parity_support import require

require('pydantic')

from eeglayoutlab.jobs.design import DesignJobError  # noqa: E402
from eeglayoutlab.jobs.identity import JSTypeError  # noqa: E402
from eeglayoutlab.jobs.radius import RadiusJobError  # noqa: E402
from eeglayoutlab.jobs.reception import (  # noqa: E402
    ATLAS_CODE, JOB_LIMIT, V1_CODE, V2_CODE, ReceptionError, ReceptionJobs, ReceptionResultError, _hash,
    validate_reception_result, validate_source_result,
)
from eeglayoutlab.jobs.runtime_digest import InspectorError  # noqa: E402
from eeglayoutlab.jobs.slot import InstallationLock, execution_lock_path  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402
from eeglayoutlab.schemas.source_reception import (  # noqa: E402
    REGION_DEFINITION, SOURCE_REGIONS, normalize_reception_request,
)

from . import reception_support  # noqa: E402
from .key_parity_support import needs_node  # noqa: E402
from .radius_support import CLOCK, SETTLE, Spawner, until  # noqa: E402
from .reception_support import (  # noqa: E402
    CASE_IDS, LAYOUT, NOT_UTF8, RECORD, REQ, SOURCE_JOBS, SOURCE_V2_JOBS, SYNTAX, Fixture, _dumps, build, catalog,
    cross, fixture, parity_cases, reception_root, record_tree, result, run_case, run_node_cases, run_python, v1,
    worker_root,
)


def run(coroutine):
    return asyncio.run(coroutine)


def _parse(path: Path) -> object:
    return jsjson.parse(path.read_text(encoding='utf-8'))


def _cache_file(root: Path, key: str, kind: str = SOURCE_JOBS) -> Path:
    return Path(root) / kind / key / 'cache.json'


async def settle(service: ReceptionJobs) -> None:
    await until(lambda: service.active is None, SETTLE)


V2 = normalize_reception_request({'record_id': REQ['record_id'], 'mode': 'single_source', 'source_index': 2,
                                  'waveform': 'burst', 'artifact_scale': 1, 'seed': 2026})


def v2_result() -> dict:
    """check-source-reception.mjs:339-342: ``result()`` as a single-source v2 result."""
    r = copy.deepcopy(result())
    r['schema_version'], r['request'] = 'source-reception/2', V2
    r['source'] = {'xyz_mm': [[1, 2, 3]], 'mode': 'single_source', 'normals_mri': [[1, 0, 0]],
                   'generation_source_indices': [2]}
    r['waveforms']['source_nam'] = [[1] * 400]
    return r


# --- check-source-reception.mjs ------------------------------------------------------------------------------------

def test_source_result_rejects_stale_coordinates_missing_duplicate_conditions_and_clipped_negative_scores():
    validate_source_result(result(), REQ, RECORD)
    moved = copy.deepcopy(result())
    moved['layout']['xyzMm'][0][0] += 0.001
    with pytest.raises(ReceptionResultError, match='^源实验替换了冻结点位$'):
        validate_source_result(moved, REQ, RECORD)
    duplicate = result()
    duplicate['strength_curve'][1] = duplicate['strength_curve'][0]
    with pytest.raises(ReceptionResultError, match='^干扰曲线点重复或缺失$'):
        validate_source_result(duplicate, REQ, RECORD)
    bad = result()
    bad['conditions'][0]['candidate'] = {**bad['conditions'][0]['candidate'], 'nmse': 2, 'explained_energy': 0}
    with pytest.raises(ReceptionResultError, match='^重建指标无效$'):
        validate_source_result(bad, REQ, RECORD)
    negative = result()
    negative['conditions'][0]['candidate'] = {**negative['conditions'][0]['candidate'], 'nmse': 2,
                                              'explained_energy': -1}
    negative['conditions'][0]['field_retention'] = -1 / 0.9
    validate_source_result(negative, REQ, RECORD)
    low = result()
    low['conditions'][0]['baseline'] = {'nmse': 1 - 1e-9, 'explained_energy': 1e-9, 'brain_artifact_ratio_db': None}
    low['conditions'][0]['field_retention'] = None
    validate_source_result(low, REQ, RECORD)


def test_cache_miss_is_read_only_source_and_radius_computations_share_capacity_in_both_directions(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        try:
            assert (await f.source.lookup(REQ))['hit'] is False
            assert f.children == []
            release_radius = f.queue.execution_slot.acquire('radius')
            assert (await f.source.submit(REQ))['busy'] is True
            release_radius()
            j = await f.source.submit(REQ)
            assert len(f.children) == 1
            assert (await f.source.submit(REQ))['job']['id'] == j['job']['id']
            assert (await f.source.submit({**REQ, 'seed': 5}))['busy'] is True
            radius = await f.queue.submit({'region_count': 2, 'radius_mm': 35, 'mode': 'whole_surface'})
            assert radius['busy'] is True
            assert f.children[0].options['shell'] is False
            assert f.children[0].options['env']['OMP_NUM_THREADS'] == '2'
            f.source.cancel(j['job']['id'])
            assert (await f.source.submit({**REQ, 'seed': 5}))['busy'] is True
            f.children[0].close(None)
            await settle(f.source)
        finally:
            await f.aclose()
    run(scenario())


def test_completed_result_survives_service_restart_cache_corruption_and_scientific_identity_changes_miss(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        second = None
        try:
            await f.source.submit(REQ)
            job = await f.complete()
            assert job.status == 'completed'
            assert (await f.source.lookup(REQ))['job']['cached'] is True

            def unexpected(*args):
                raise AssertionError('cached result must not compute')
            second = ReceptionJobs(str(tmp_path), 'python3', None, context=f.source.context_override,
                                   spawn=unexpected)
            assert (await second.lookup(REQ))['hit'] is True
            cache_path = Path(job.directory) / 'cache.json'
            cache = _parse(cache_path)
            cache['result']['conditions'][0]['field_retention'] = 100
            cache_path.write_text(jsjson.stringify(cache), encoding='utf-8')
            assert (await f.source.lookup(REQ))['hit'] is False
            f.bump()
            assert (await second.lookup(REQ))['hit'] is False
        finally:
            if second is not None:
                await second.aclose()
            await f.aclose()
    run(scenario())


def test_timeout_cancellation_do_not_free_capacity_before_process_close_and_never_cache_a_score(tmp_path):
    async def scenario():
        f = Fixture(tmp_path, timeout_ms=15)
        try:
            j = await f.source.submit(REQ)
            await until(lambda: bool(f.children[0].kills), SETTLE)
            assert f.source.active.id == j['job']['id']
            assert (await f.source.submit({**REQ, 'seed': 4}))['busy'] is True
            f.children[0].close(None)
            await settle(f.source)
            assert f.source.jobs[j['job']['id']].status == 'timeout'
            assert (await f.source.lookup(REQ))['hit'] is False
        finally:
            await f.aclose()
    run(scenario())


def test_model_changes_during_computation_and_mismatched_worker_results_cannot_become_cache_hits(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        try:
            await f.source.submit(REQ)
            f.bump()
            job = await f.complete()
            assert job.status == 'failed'
            assert job.result is None
            assert job.message == '结果校验失败：计算期间模型、源代码或原始布局已变化'
        finally:
            await f.aclose()
    run(scenario())


def test_original_signal_download_survives_changed_identity_and_rejects_corrupt_or_mismatched_saved_results(
        tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        try:
            await f.source.submit(REQ)
            job = await f.complete()
            original = job.result
            f.bump()
            assert (await f.source.lookup(REQ))['hit'] is False
            assert await f.source.saved_result(job.key, REQ) == original
            assert len(f.children) == 1
            with pytest.raises(ReceptionError, match='校验失败'):
                await f.source.saved_result(job.key, {**REQ, 'seed': 43})
            with pytest.raises(ReceptionError, match='Invalid saved'):
                await f.source.saved_result('../../cache', REQ)
            path = Path(job.directory) / 'cache.json'
            cache = _parse(path)
            cache['result']['conditions'][0]['field_retention'] = 100
            path.write_text(jsjson.stringify(cache), encoding='utf-8')
            with pytest.raises(ReceptionError, match='校验失败'):
                await f.source.saved_result(job.key, REQ)
        finally:
            await f.aclose()
    run(scenario())


def test_v2_original_download_requires_its_frozen_identity_layout_even_when_the_result_checksum_is_recomputed(
        tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        try:
            r = v2_result()
            identity = {'layout': copy.deepcopy(LAYOUT), 'version': 'old-model'}
            key = jsjson.sha256_hex({'request': V2, 'identity': identity})
            path = _cache_file(tmp_path, key, SOURCE_V2_JOBS)
            path.parent.mkdir(parents=True)
            cache = {'key': key, 'identity': identity, 'result': r, 'result_sha256': jsjson.sha256_hex(r)}
            path.write_text(jsjson.stringify(cache), encoding='utf-8')

            def unexpected(request):
                raise AssertionError('historical download must not inspect the current model')
            f.source.context_override = unexpected
            assert await f.source.saved_result(key, V2) == r
            cache['result']['layout']['xyzMm'][0][0] += 1.25
            cache['result_sha256'] = jsjson.sha256_hex(cache['result'])
            path.write_text(jsjson.stringify(cache), encoding='utf-8')
            with pytest.raises(ReceptionResultError, match='冻结点位'):
                await f.source.saved_result(key, V2)
            del cache['identity']
            cache['result']['layout'] = {}
            cache['result_sha256'] = jsjson.sha256_hex(cache['result'])
            path.write_text(jsjson.stringify(cache), encoding='utf-8')
            with pytest.raises(ReceptionError, match='校验失败'):
                await f.source.saved_result(key, V2)
            # V1 has no frozen identity in its cache format, but still requires real 64-point geometry.
            old = result()
            old['layout'] = {}
            old_key = 'f' * 64
            old_path = _cache_file(tmp_path, old_key)
            old_path.parent.mkdir(parents=True)
            old_cache = {'key': old_key, 'result': old, 'result_sha256': jsjson.sha256_hex(old)}
            old_path.write_text(jsjson.stringify(old_cache), encoding='utf-8')
            with pytest.raises(ReceptionError, match='坐标或区域标签无效'):
                await f.source.saved_result(old_key, REQ)
        finally:
            await f.aclose()
    run(scenario())


def test_v1_and_v2_signal_simulation_both_refuse_a_layout_searched_under_correlated_noise(tmp_path):
    parent = {'id': REQ['record_id'], 'dataset_id': 'cache', 'status': 'completed', 'layout': LAYOUT,
              'request': {'region_count': 2}}

    class Library:
        async def get(self, id):
            return parent

    async def scenario():
        source = ReceptionJobs(str(tmp_path), 'python3', Library())
        try:
            # An independent-noise parent passes the guard and only then needs the model files.
            for request in (normalize_reception_request(REQ), V2):
                with pytest.raises(Exception) as error:
                    await source.context(request)
                assert '独立噪声' not in str(error.value)
            parent['request']['noise_model'] = {'kind': 'spatial', 'rho': 0.5, 'length_mm': 20}
            for request in (normalize_reception_request(REQ), V2):
                with pytest.raises(ReceptionError, match='独立噪声'):
                    await source.context(request)
        finally:
            await source.aclose()
    run(scenario())


# --- check-cross-region-contract.mjs and check-source-upgrade.mjs ---------------------------------------------------

CROSS_LAYOUT = {'xyzMm': [[i * 5, 0, 0] for i in range(64)], 'referenceXyzMm': [[i * 5, 1, 0] for i in range(64)],
                'regionIndices': [int(i >= 32) for i in range(64)]}


def _fixture_result(regions: list) -> dict:
    """``fixtureResult(regions)`` of check-cross-region-contract.mjs."""
    return fixture(normalize_reception_request(cross('a' * 64, regions, definition=False, artifact_scale=1,
                                                     seed=2026)), CROSS_LAYOUT)


def _pop(path):
    def mutate(r):
        target = r
        for name in path.split('.'):
            target = target[name]
        target.pop()
    return mutate


CROSS_MUTATIONS = {
    'patch_count': lambda r: r['source'].__setitem__('patch_count', 6),
    'regions_reversed': lambda r: r['source']['source_regions'].reverse(),
    'region_unknown': lambda r: r['source']['source_regions'].__setitem__(0, 'unknown'),
    'region_popped': _pop('source.source_regions'),
    'index_repeated': lambda r: r['source']['generation_source_indices'].__setitem__(
        1, r['source']['generation_source_indices'][0]),
    'index_negative': lambda r: r['source']['generation_source_indices'].__setitem__(0, -1),
    'index_256': lambda r: r['source']['generation_source_indices'].__setitem__(0, 256),
    'index_fraction': lambda r: r['source']['generation_source_indices'].__setitem__(0, 0.5),
    'index_popped': _pop('source.generation_source_indices'),
    'bank_shifted': lambda r: r['source']['bank_source_indices'].__setitem__(
        0, r['source']['bank_source_indices'][0] + 1),
    'normal_long': lambda r: r['source']['normals_mri'].__setitem__(0, [0, 0, 2]),
    'normal_popped': _pop('source.normals_mri'),
    'xyz_popped': _pop('source.xyz_mm'),
    'waveform_popped': _pop('waveforms.source_nam'),
    'waveform_short': lambda r: r['waveforms']['source_nam'][0].pop(),
    'waveform_nan': lambda r: r['waveforms']['source_nam'][0].__setitem__(0, float('nan')),
}


def test_k1_3_6_results_are_accepted_while_source_mapping_and_shape_corruption_is_rejected():
    record = {'id': 'a' * 64, 'layout': CROSS_LAYOUT}
    for regions in (list(SOURCE_REGIONS[:1]), list(SOURCE_REGIONS[:3]), list(SOURCE_REGIONS)):
        r = _fixture_result(regions)
        validate_reception_result(r, r['request'], record)
    assert len(CROSS_MUTATIONS) == 16
    for name, mutate in CROSS_MUTATIONS.items():
        r = _fixture_result(list(SOURCE_REGIONS[:3]))
        mutate(r)
        with pytest.raises(ReceptionResultError, match='^(跨区域源位置记录与选择不一致|固定源方向或波形记录不完整)$'):
            validate_reception_result(r, r['request'], record)
    # Beyond Node's sixteen: 'index_repeated' fails on the bank index first, in Node too. A source repeated in both
    # index lists only the distinctness check (`new Set(...).size !== n`) refuses.
    r = _fixture_result(list(SOURCE_REGIONS[:3]))
    r['source']['generation_source_indices'], r['source']['bank_source_indices'] = [0, 0, 2], [4096, 4096, 4098]
    with pytest.raises(ReceptionResultError, match='^跨区域源位置记录与选择不一致$'):
        validate_reception_result(r, r['request'], record)


def test_v2_validator_rejects_wrong_source_identity_before_accepting_display_data():
    request = {'record_id': 'a' * 64, 'mode': 'single_source', 'source_index': 2, 'waveform': 'burst',
               'artifact_scale': 1, 'seed': 2026}
    with pytest.raises(ReceptionResultError, match='^新源协议结果身份不一致$'):
        validate_reception_result({'schema_version': 'source-reception/1', 'request': request},
                                  normalize_reception_request(request), {})


def test_the_validators_raise_v8s_type_errors_where_node_throws_one():
    r = v2_result()
    r['source']['normals_mri'] = {'length': 1}
    with pytest.raises(JSTypeError, match=r'^result\.source\.normals_mri\.some is not a function$'):
        validate_reception_result(r, V2, RECORD)
    with pytest.raises(JSTypeError, match=r"^Cannot read properties of null \(reading 'length'\)$"):
        validate_source_result({**result(), 'source': {'xyz_mm': [None]}}, REQ, RECORD)
    c = _fixture_result(list(SOURCE_REGIONS[:2]))
    c['source']['generation_source_indices'] = {'length': 2}
    with pytest.raises(JSTypeError, match='object is not iterable'):
        validate_reception_result(c, c['request'], {'layout': CROSS_LAYOUT})


# --- What Python adds ---------------------------------------------------------------------------------------------

def test_the_permit_and_the_installation_lock_are_held_until_the_records_are_written(tmp_path):
    """The slot is released in finish's ``finally``, after cache.json and job.json; the completion callbacks come
    after that, once, with the job terminal; another workspace's lock on the installation is refused meanwhile."""
    async def scenario():
        f = Fixture(tmp_path)
        source, seen = f.source, []

        def finished(job):
            seen.append((job.id, job.status, source.active, source.execution_slot.busy,
                         source.execution_slot.lock.held, (Path(job.batch) / 'job.json').is_file(),
                         _cache_file(tmp_path, job.key).is_file()))
        source.finish_callbacks.append(finished)
        try:
            first = await source.submit(REQ)
            assert source.execution_slot.busy and source.execution_slot.lock.held
            other = InstallationLock(str(tmp_path))
            assert other.try_acquire() is False
            job = await f.complete()
            await asyncio.wait_for(source.jobs[first['job']['id']].done, SETTLE)
            assert seen == [(job.id, 'completed', None, False, False, True, True)]
            assert other.try_acquire() is True
            # Another workspace computing: refused without a write, then accepted once it lets go.
            assert await source.submit({**REQ, 'seed': 9}) == {'busy': True, 'maintenance': False}
            assert source.execution_slot.contended
            other.release()
            assert Path(execution_lock_path(str(tmp_path))).is_file()
            assert source.store.keys('source') == [job.key]
            record = _parse(Path(job.batch) / 'job.json')
            assert list(record) == ['id', 'key', 'request', 'status', 'progress', 'message', 'cached', 'finished_at',
                                    'stderr']
            assert list(_parse(_cache_file(tmp_path, job.key))) == ['key', 'result', 'result_sha256', 'finished_at']
            assert _parse(Path(job.batch) / 'request.json') == {'request': REQ, 'record': RECORD}
        finally:
            await f.aclose()
    run(scenario())


def test_a_valid_cache_published_first_by_another_workspace_is_kept(tmp_path):
    """B16: cache.json is published once. A valid one written meanwhile stays byte for byte and is what lookups
    read; the job completes with its own result in its view. A file that is not valid is replaced."""
    async def scenario():
        f = Fixture(tmp_path)
        source = f.source
        try:
            first = await source.submit(REQ)
            job = source.jobs[first['job']['id']]
            theirs = _cache_file(tmp_path, job.key)
            stored = {**result(), 'note': 'theirs'}
            theirs.write_text(jsjson.stringify({'key': job.key, 'result': stored, 'result_sha256': _hash(stored),
                                                'finished_at': '2026-01-01T00:00:00.000Z'}), encoding='utf-8')
            before = theirs.read_bytes()
            await f.complete(result())
            assert (job.status, job.result, theirs.read_bytes()) == ('completed', result(), before)
            hit = await source.lookup(REQ)
            assert (hit['job']['result'], hit['job']['finished_at']) == (stored, '2026-01-01T00:00:00.000Z')
            theirs.write_text('not json', encoding='utf-8')
            await source.submit(REQ)
            await f.complete(result())
            record = _parse(theirs)
            assert (record['key'], record['result'], record['result_sha256']) == (job.key, result(), _hash(result()))
            assert not [name for name in os.listdir(theirs.parent) if name.endswith('.tmp')]
        finally:
            await f.aclose()
    run(scenario())


def test_the_finish_time_at_restart_is_read_only_from_a_record_that_passes_the_reconciliations_checks(tmp_path):
    """``stored_finish`` (the restart's ``recover()``): ``cache.json``'s ``finished_at`` only when the record passes
    the checks of Node's ``inspectReceipt`` for a source-reception receipt: the lookup's key and checksum, the
    lookup's result, the identity and request it names (if any), and ``savedResult`` reproducing it."""
    async def scenario():
        f = Fixture(tmp_path)
        try:
            ctx = f.context(V2)
            key, identity, r = ctx['key'], ctx['identity'], v2_result()
            path = _cache_file(tmp_path, key, SOURCE_V2_JOBS)
            path.parent.mkdir(parents=True)

            async def finish(cache: dict, found: object = r) -> object:
                path.write_text(_dumps(cache), encoding='utf-8')  # any JSON text of the value
                return await f.source.stored_finish(key, V2, identity, found)

            # A v2 record's identity must re-derive its key for savedResult: the stub's does not, so it is kept.
            stored = {'key': key, 'identity': identity, 'result': r, 'result_sha256': _hash(r),
                      'finished_at': '2026-01-01T00:00:00.000Z'}
            assert await finish(stored) is None
            frozen = {'layout': LAYOUT, 'version': 1}
            key = jsjson.sha256_hex({'request': V2, 'identity': frozen})
            path = _cache_file(tmp_path, key, SOURCE_V2_JOBS)
            path.parent.mkdir(parents=True)
            stored = {**stored, 'key': key, 'identity': frozen}

            async def finish(cache: dict, found: object = r, named: object = frozen) -> object:  # noqa: F811
                path.write_text(_dumps(cache), encoding='utf-8')  # any JSON text of the value
                return await f.source.stored_finish(key, V2, named, found)
            assert await finish(stored) == '2026-01-01T00:00:00.000Z'
            assert await finish({**stored, 'request': V2}) == '2026-01-01T00:00:00.000Z'
            for cache in ({**stored, 'key': '0' * 64}, {**stored, 'result_sha256': '0' * 64},
                          {**stored, 'request': {**V2, 'seed': 1}}):
                assert await finish(cache) is None, cache
            assert await finish(stored, named={'layout': LAYOUT, 'version': 2}) is None
            assert await finish(stored, {**r, 'status': 'failed'}) is None
            moved = copy.deepcopy(r)
            moved['layout']['xyzMm'][0][0] += 1
            assert await finish({**stored, 'result': moved, 'result_sha256': _hash(moved)}, moved) is None
            path.unlink()
            assert await f.source.stored_finish(key, V2, frozen, r) is None
        finally:
            await f.aclose()
    run(scenario())


def test_aclose_stops_the_worker_and_waits_for_its_records(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        source, children = f.source, f.children
        first = await source.submit(REQ)
        closing = asyncio.ensure_future(source.aclose())
        await until(lambda: bool(children[0].kills), SETTLE)
        assert source.active.cancel_reason == 'restart' and not closing.done()
        children[0].close(None, 'SIGTERM')
        await asyncio.wait_for(closing, SETTLE)
        record = _parse(Path(source.jobs[first['job']['id']].batch) / 'job.json')
        assert (record['status'], record['message']) == ('cancelled', '计算已停止；没有缓存未完成结果')
        with pytest.raises(ReceptionError, match='^计算服务正在重启$'):
            await source.submit(REQ)
        assert isinstance(ReceptionError('x'), (DesignJobError, RadiusJobError))
        await source.aclose()  # nothing active: returns
        f.queue.dispose()
    run(scenario())


def test_aclose_also_kills_a_catalog_run_spawned_after_it(tmp_path, monkeypatch):
    """A catalog run still preparing its spawn when the service closes is killed as soon as its child exists, so
    no catalog (nor runtime inspector, ``test_runtime_digest``) outlives ``aclose``."""
    from eeglayoutlab.jobs import reception

    root = worker_root(tmp_path / 'root')
    preparing, release = threading.Event(), threading.Event()
    environment = reception.process_env

    def held() -> dict:
        preparing.set()
        assert release.wait(60)
        return environment()
    monkeypatch.setattr(reception, 'process_env', held)

    async def scenario():
        source = ReceptionJobs(str(root), 'python3', None, context=lambda request: None)
        catalog = asyncio.ensure_future(source.catalog())
        try:
            assert await asyncio.to_thread(preparing.wait, 60)
            await source.aclose()
            release.set()
            with pytest.raises(InspectorError, match='^Command failed: python3 -u ') as failure:
                await asyncio.wait_for(catalog, 60)
            assert failure.value.signal == 'SIGKILL' and not source._processes
        finally:
            release.set()
            await source.aclose()
    run(scenario())


def test_the_queue_starts_jobs_with_its_prepared_request_and_reads_their_state(tmp_path):
    """What the queue's adapter calls: ``lookup(request, ctx)``, ``submit(prepared)`` (the request is normalized
    again and its context computed again), ``jobs``, ``view``, ``active``, ``submitting`` and ``active_pid()``; a
    lookup hit is remembered, as Node's is."""
    async def scenario():
        f = Fixture(tmp_path)
        source = f.source
        try:
            ctx = f.context(normalize_reception_request(REQ))
            assert await source.lookup(REQ, ctx) == {'hit': False}
            started = await source.submit({'request': {**REQ, 'seed': 2026.0}, 'key': ctx['key'], 'ctx': ctx})
            assert started['job']['key'] == ctx['key'] and source.active.id == started['job']['id']
            assert not source.submitting and source.active_pid() is None  # a fake child has no pid
            assert source.view(source.jobs[started['job']['id']]) == started['job']
            await f.complete()
            hit = await source.lookup(REQ, ctx)
            assert hit['hit'] is True and hit['job']['cached'] is True and hit['job']['id'] in source.jobs
            assert list(hit['job']) == ['id', 'key', 'request', 'status', 'progress', 'message', 'result', 'cached',
                                        'finished_at']
            assert (hit['job']['message'], hit['job']['progress']) == ('已读取同一源、布局和干扰条件的已有结果', 1)
        finally:
            await f.aclose()
    run(scenario())


def test_a_cancel_while_the_worker_is_spawned_stops_it_as_soon_as_it_exists(tmp_path):
    """Node spawns synchronously; here a cancel during the spawn makes the job ``cancelling`` at once and the child
    gets SIGTERM when it exists."""
    async def scenario():
        gate, spawner = asyncio.Event(), Spawner()

        async def slow(worker, executable, args, options):
            await gate.wait()
            return spawner(worker, executable, args, options)
        f = Fixture(tmp_path, spawn=slow)
        source = f.source
        try:
            submitted = asyncio.ensure_future(source.submit(REQ))
            await until(lambda: source.active is not None, SETTLE)
            assert not source.submitting and source.active.status == 'running'
            assert await source.submit(REQ) == {'job': source.view(source.active)}
            id = source.active.id
            assert source.cancel(id) is True
            assert (source.active.status, source.active.message) == ('cancelling', '正在停止源实验')
            gate.set()
            assert (await submitted)['job']['status'] == 'cancelling'
            assert spawner.children[0].kills == ['SIGTERM']
            spawner.children[0].close(None, 'SIGTERM')
            await settle(source)
            assert (source.jobs[id].status, source.jobs[id].message) == ('cancelled', '计算已停止；没有缓存未完成结果')
        finally:
            gate.set()
            await f.aclose()
    run(scenario())


def test_a_cancelled_submit_caller_does_not_strand_the_active_job(tmp_path):
    async def scenario():
        gate, spawner = asyncio.Event(), Spawner()

        async def slow(worker, executable, args, options):
            await gate.wait()
            return spawner(worker, executable, args, options)
        f = Fixture(tmp_path, spawn=slow)
        source = f.source
        try:
            submitted = asyncio.ensure_future(source.submit(REQ))
            await until(lambda: source.active is not None, SETTLE)
            submitted.cancel()
            with pytest.raises(asyncio.CancelledError):
                await submitted
            gate.set()
            await until(lambda: len(spawner.children) == 1, SETTLE)
            job = source.active
            Path(job.batch, 'result.json').write_text(jsjson.stringify(result()), encoding='utf-8')
            spawner.children[0].close(0)
            await settle(source)
            assert job.status == 'completed'
            assert not source.execution_slot.busy and not source.execution_slot.lock.held
            assert (await source.submit(REQ))['job']['cached'] is True
        finally:
            gate.set()
            await f.aclose()
    run(scenario())


def test_the_v2_worker_runs_under_the_native_interpreter_with_one_thread_and_at_least_600_s(tmp_path):
    async def scenario():
        f = Fixture(tmp_path, compute_python='/compute/python')
        source = f.source
        try:
            loop = asyncio.get_running_loop()
            await source.submit(REQ)
            v1 = f.children[0]
            assert (v1.executable, v1.options['env']['VECLIB_MAXIMUM_THREADS']) == ('/compute/python', '2')
            assert v1.args[:2] == ['-u', f'{tmp_path}/scripts/run_source_reception.py']
            assert source.active.worker._timer.when() <= loop.time() + 3.0
            source.cancel(source.active.id)
            v1.close(None, 'SIGTERM')
            await settle(source)
            before = loop.time()
            await source.submit(V2)
            v2 = f.children[1]
            assert (v2.executable, v2.options['env']['OMP_NUM_THREADS']) == ('python3', '1')
            assert v2.args == ['-u', f'{tmp_path}/scripts/run_source_reception_v2.py', '--repository-root',
                               str(tmp_path), '--request', f'{source.active.batch}/request.json', '--output',
                               f'{source.active.batch}/result.json']
            assert v2.options['stdio'] == ['ignore', 'pipe', 'pipe']
            assert v2.options['env']['PYTHONDONTWRITEBYTECODE'] == '1'
            assert source.active.worker._timer.when() >= before + 600.0
            Path(source.active.batch, 'result.json').write_text(jsjson.stringify(v2_result()), encoding='utf-8')
            v2.close(0)
            await settle(source)
            job = source.jobs[[id for id in source.jobs][-1]]
            assert job.status == 'completed', job.message
            cache = _parse(_cache_file(tmp_path, job.key, SOURCE_V2_JOBS))
            assert list(cache) == ['key', 'identity', 'result', 'result_sha256', 'finished_at']
            assert cache['identity'] == {'version': 1}
        finally:
            await f.aclose()
    run(scenario())


def test_the_job_map_keeps_the_newest_ten_and_never_drops_the_active_job(tmp_path):
    async def scenario():
        f = Fixture(tmp_path)
        source = f.source
        try:
            await source.submit(REQ)
            done = await f.complete()
            hits = [(await source.lookup(REQ))['job']['id'] for _ in range(JOB_LIMIT + 1)]
            assert list(source.jobs) == hits[1:]
            running = await source.submit({**REQ, 'seed': 1})
            for _ in range(JOB_LIMIT):
                await source.lookup(REQ)
            assert running['job']['id'] in source.jobs and len(source.jobs) == JOB_LIMIT
            assert list(source.jobs)[0] == running['job']['id'] and done.id not in source.jobs
            source.cancel(running['job']['id'])
            f.children[-1].close(None, 'SIGTERM')
            await settle(source)
        finally:
            await f.aclose()
    run(scenario())


def test_verified_records_are_kept_by_their_file_state_two_at_a_time(tmp_path):
    """``verifiedCache``'s memo: a record verified once is not parsed or hashed again while its inode, size and
    modification time stay (pure-Python ``JSON.stringify`` takes about 0.6 s per hash of the stored 3.9 MB result,
    about 1.2 s of an 8 MB one); a rewrite is read again; at most two files are kept, the least recently used
    dropped."""
    async def scenario():
        source = ReceptionJobs(str(tmp_path), 'python3', None, context=lambda request: None)
        try:
            paths = []
            for n in range(3):
                value, key = {'n': n}, str(n) * 64  # the memo checks only the key and checksum
                path = _cache_file(tmp_path, key)
                path.parent.mkdir(parents=True)
                path.write_text(jsjson.stringify({'key': key, 'result': value, 'result_sha256': _hash(value)}),
                                encoding='utf-8')
                paths.append((str(path), key))
            first = await source.verified_cache(*paths[0])
            assert await source.verified_cache(*paths[0]) is first
            await source.verified_cache(*paths[1])
            assert await source.verified_cache(*paths[0]) is first  # now the most recent
            await source.verified_cache(*paths[2])  # drops the second
            assert list(source.verified) == [paths[0][0], paths[2][0]]
            # The key is in the path: as Node's, a memo hit does not check it again.
            assert await source.verified_cache(paths[0][0], 'f' * 64) is first
            stamp = os.stat(paths[0][0])
            Path(paths[0][0]).write_bytes(Path(paths[0][0]).read_bytes())
            os.utime(paths[0][0], ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1000))
            again = await source.verified_cache(*paths[0])
            assert again is not first and again == first
            value = result()
            started = time.perf_counter()
            text = jsjson.stringify(value)
            print(f'\npure-Python JSON.stringify of a {len(text) / 1e6:.2f} MB result: '
                  f'{time.perf_counter() - started:.2f} s')
        finally:
            await source.aclose()
    run(scenario())


def test_a_real_worker_process_completes_fails_and_stops_through_the_transport(tmp_path):
    """``FAKE_WORKER`` as both workers, run by ``python3`` in its own process group: a v1 and a v2 result written to
    result.json and read after the close, a failure with its diagnostics, and a stop of a held worker."""
    async def scenario():
        root = worker_root(tmp_path / 'root')
        f = Fixture(root, spawn=None, timeout_ms=60000)
        source = f.source
        try:
            for request in (REQ, V2):
                started = await source.submit(request)
                assert isinstance(source.active_pid(), int)
                await settle(source)
                job = source.jobs[started['job']['id']]
                assert (job.status, job.progress, job.message) == ('completed', 1, '源—接收对照已计算并保存'), job.message
                assert job.stderr == 'reception stderr\n'
                assert job.result == fixture(normalize_reception_request(request), LAYOUT)
            (root / 'stub/worker-mode.txt').write_text('fail', encoding='utf-8')
            started = await source.submit({**REQ, 'seed': 1})
            await settle(source)
            job = source.jobs[started['job']['id']]
            assert (job.status, job.message) == ('failed', '源实验未完成；错误记录已保存，没有替换为旧分数')
            assert job.stderr == '源实验失败Traceback: boom\n'
            (root / 'stub/worker-mode.txt').write_text('hold', encoding='utf-8')
            started = await source.submit({**REQ, 'seed': 2})
            await until(lambda: source.active.progress == 0.25, SETTLE)
            assert source.cancel(started['job']['id']) is True
            await settle(source)
            job = source.jobs[started['job']['id']]
            assert (job.status, job.result) == ('cancelled', None)
            assert not (Path(job.batch) / 'result.json').exists()
            catalogs = await asyncio.gather(source.catalog(), source.catalog())
            assert catalogs[0] is catalogs[1] and len(catalogs[0]['sources']) == 256
            (root / 'stub/catalog.txt').write_text('exit:3', encoding='utf-8')
            with pytest.raises(Exception, match='^Command failed: python3 -u .*--catalog\ncatalog failed\n$'):
                await source.catalog()
        finally:
            await asyncio.wait_for(f.aclose(), SETTLE)
    run(scenario())


def test_the_workers_get_a_variable_that_is_not_utf8_as_node_and_the_inspector_pass_it(tmp_path, monkeypatch):
    """Node's ``{...process.env}`` holds the service's environment as V8 decoded it, so a byte that is not UTF-8
    reaches both workers as U+FFFD (UTF-8 ``EF BF BD``), the bytes the runtime inspector, whose digest keys v2, gets
    (test_runtime_digest.py); ``os.environ`` would pass the raw byte on. Real children print what they got."""
    monkeypatch.setitem(os.environb, b'EEG_RAW', b'a\xffb')
    root = worker_root(tmp_path / 'root')
    for name in ('run_source_reception.py', 'run_source_reception_v2.py'):
        (root / 'scripts' / name).write_text("import os, sys\nsys.stderr.write(os.environb[b'EEG_RAW'].hex())\n"
                                             "sys.exit(1)\n", encoding='utf-8')

    async def scenario():
        f = Fixture(root, spawn=None, timeout_ms=60000)
        try:
            for request in (REQ, V2):
                started = await f.source.submit(request)
                await settle(f.source)
                job = f.source.jobs[started['job']['id']]
                assert (job.status, job.stderr) == ('failed', '61efbfbd62'), request
        finally:
            await f.aclose()
    run(scenario())


def test_a_step_that_fails_while_a_fake_job_runs_fails_the_test_instead_of_hanging(tmp_path, monkeypatch):
    """A fake child never exits by itself, so the cleanup of ``Fixture`` and of the run-path driver is bounded: a
    step that fails with a job still running is reported (chained to the cleanup's timeout) once the bound passes.
    The driver's ``restart`` only disposes the service, as Node's does, so it never waits for a running job."""
    monkeypatch.setattr(reception_support, 'SETTLE', 0.5)

    def chain(error: BaseException) -> list[str]:
        seen = []
        while error is not None:
            seen.append(str(error))
            error = error.__cause__ or error.__context__
        return seen

    def fails(coroutine) -> list[str]:
        started = time.monotonic()
        with pytest.raises(asyncio.TimeoutError) as caught:
            run(asyncio.wait_for(coroutine, 10))
        assert time.monotonic() - started < 5
        return chain(caught.value)

    async def failed_step():
        f = Fixture(tmp_path)
        try:
            await f.source.submit(REQ)
            raise AssertionError('a failed step')
        finally:
            await f.aclose()
    assert 'a failed step' in fails(failed_step())
    built = reception_root(tmp_path / 'case')
    a = v1(built['ids']['cache'])
    item = {'id': 'restart', 'root': built['root'], 'python': 'python3', 'timeoutMs': 3000, 'throw': None,
            'clock': CLOCK, 'steps': [['submit', a], ['restart', {}], ['close', None, 'SIGTERM'], ['jobs']]}
    restarted = run(asyncio.wait_for(run_case(item), 10))
    assert restarted['records'][-1] == ['jobs', '[]'] and restarted['children'][0]['kills'] == ['SIGTERM']
    assert 'the radius run did not settle' in fails(run_case({**item, 'steps': [['submit', a], ['settle']]}))


def test_the_code_identity_files_are_nodes():
    """The files Node names beside the workflow lists (source-reception-server.mjs:66, reception-v2-support.mjs:155):
    the atlas files enter v2's code identity of a ``region_definition`` request only, the inspector every v2 one
    (test_key_parity.py checks both on Node's contexts)."""
    assert V1_CODE == ('scripts/source_reception.py', 'scripts/run_source_reception.py')
    assert V2_CODE == (*V1_CODE, 'scripts/source_reception_v2.py', 'scripts/run_source_reception_v2.py',
                       'scripts/reception_forward_provider.py', 'scripts/inspect_reception_runtime.py')
    assert ATLAS_CODE == ('src/compact_eeg/workflows/source_roi.py', 'webapp/public/models/ernie/source-roi.json',
                          'webapp/public/models/ernie/source-roi-definition.json')
    assert 'scripts/inspect_reception_runtime.py' in V2_CODE and REGION_DEFINITION == 'dk40-six-roi-v1'


# --- Parity with Node's run path -------------------------------------------------------------------------------------

# What the run-path cases reach, in Node's records and job.json files: the states, every refusal and validator
# check (with V8's TypeErrors), the stops, the store and spawn failures.
OUTCOMES = (
    '加载冻结布局与前向矩阵', '正在计算源—接收对照', '正在停止源实验', '计算已停止；没有缓存未完成结果',
    '源实验未完成；错误记录已保存，没有替换为旧分数', '源—接收对照已计算并保存', '无法启动计算：spawn EINVAL',
    '计算服务正在重启', '保存失败：ENOENT: no such file or directory, realpath', '保存失败：EISDIR', '结果记录校验失败',
    '结果记录过大', 'Invalid saved signal record', '计算记录无法读取，请重新提交', '保存的信号布局坐标或区域标签无效',
    '源实验需要已有完整64点布局；不会将几何预览或历史相交方案当作计算布局', '需要完整的已保存布局或已评价坐标',
    '信号仿真只接受独立噪声协议下的布局', '已有前向库布局使用原多源协议', '源目录格式无效', 'Command failed: python3 -u ',
    '结果校验失败：计算期间模型、源代码或原始布局已变化', '结果校验失败：结果超过安全大小限制',
    '结果校验失败：Unexpected end of JSON input',
    '结果校验失败：EISDIR: illegal operation on a directory, read', '结果校验失败：ENOENT: no such file or directory, stat',
    *(f'结果校验失败：{message}' for message in (
        '源实验结果身份不一致', '源实验配置字段无效', '源实验替换了冻结点位', '时间轴无效', '64通道波形无效', '缺少对照条件',
        '干扰曲线点重复或缺失', '条件强度与请求不符', '干扰条件无效', '重建指标无效', 'AR相对保留率无效', '缺少实际源坐标',
        '新源协议结果身份不一致', '固定源方向或波形记录不完整', '返回源与选择源不符', '跨区域源位置记录与选择不一致',
        'Atlas source membership is inconsistent', 'wave.time_s.every is not a function', 'row.every is not a function',
        'result.source.xyz_mm.some is not a function', 'result.source.normals_mri.some is not a function',
        'result.source.bank_source_indices.some is not a function',
        'result.source.source_regions.some is not a function',
        'object is not iterable', "Cannot read properties of null (reading 'length')",
        "Cannot read properties of null (reading 'condition')",
        "Cannot read properties of undefined (reading 'region_definition')")),
    '"busy":true,"maintenance":true', '"busy":true,"maintenance":false', '{"busy":true}', '{"hit":false}',
    '跨区域模式需要选择1–6个不同的源区域', '选择0–255中的一个冻结生成源', 'Unsupported source ROI definition',
    "Cannot read properties of null (reading 'schema_version')",
)
_TEMPORARY = re.compile(r'\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.tmp')


def _mask(text: str) -> str:
    """The random part of temporary names (a failed write names its temporary) and V8's JSON.parse messages."""
    text = _TEMPORARY.sub('.<uuid>.tmp', text)
    for message, mask in SYNTAX.items():
        text = text.replace(message, mask)
    return text


def _tree(root: Path) -> dict:
    """Both record trees of a root, each file's bytes as text (undecodable bytes kept) with ``_mask`` applied."""
    return {f'{kind}/{name}': None if data is None else _mask(data.decode('utf-8', 'surrogateescape'))
            for kind in (SOURCE_JOBS, SOURCE_V2_JOBS) for name, data in record_tree(root, kind).items()}


@pytest.fixture(scope='module')
def node_run(tmp_path_factory):
    """Node's ``SourceReceptionService`` over every case once; each root is then moved to ``root.node``."""
    base = tmp_path_factory.mktemp('reception-run')
    cases = parity_cases(base / 'cases', catalog(base / 'catalog'))
    for case in cases:
        build(case)
    output = run_node_cases(cases, base)
    for case in cases:
        Path(case['root']).rename(Path(case['root']).with_name('root.node'))
    return {case['id']: (case, output['by_id'][case['id']]) for case in cases}


@needs_node
@pytest.mark.parametrize('id', CASE_IDS)
def test_run_path_writes_the_bytes_and_reports_the_states_of_node(node_run, id, monkeypatch):
    """Parity 1 of slice 7: given the same worker output, clock and job identifiers, the run path returns Node's
    views, hits, saved results, refusals and errors (as JSON text; a text over 64 KiB by its SHA-256), spawns the
    workers as Node does (interpreter, arguments, cwd, stdio, shell, thread settings, inherited environment with a
    variable that is not UTF-8, signals) and leaves the same record trees under source_reception_jobs and
    source_reception_v2_jobs: request.json, job.json and cache.json byte for byte, no temporaries. The one
    difference is B16's: in ``publish-once`` the valid cache.json another workspace wrote first stays here, where
    Node replaces it."""
    case, theirs = node_run[id]
    build(case)  # the same root, at the same path, again
    for name, value in NOT_UTF8.items():
        monkeypatch.setitem(os.environ, name, value)
    ours = run_python(case)
    assert [[kind, _mask(text)] for kind, text in ours['records']] == \
        [[kind, _mask(text)] for kind, text in theirs['records']]
    assert (ours['clock'], ours['ids']) == (theirs['clock'], theirs['ids'])
    assert ours['children'] == theirs['children']
    mine, node = _tree(Path(case['root'])), _tree(Path(case['root']).with_name('root.node'))
    if id == 'publish-once':
        changed = [name for name in mine if mine[name] != node.get(name)]
        assert len(changed) == 1 and changed[0].startswith(SOURCE_JOBS + '/') and changed[0].endswith('/cache.json')
        kept, replaced = jsjson.parse(mine.pop(changed[0])), jsjson.parse(node.pop(changed[0]))
        assert kept['finished_at'] == '2026-01-01T00:00:00.000Z' != replaced['finished_at']
        assert {**kept, 'finished_at': None} == {**replaced, 'finished_at': None}
    assert mine == node
    assert not [name for name in node if name.endswith('.tmp')]


@needs_node
def test_the_parity_cases_reach_every_outcome_of_the_run_path(node_run):
    texts = ''.join(text for _, theirs in node_run.values() for _, text in theirs['records'])
    files = {id: _tree(Path(case['root']).with_name('root.node')) for id, (case, _) in node_run.items()}
    texts += ''.join(text for tree in files.values() for name, text in tree.items() if name.endswith('/job.json'))
    statuses = set(re.findall(r'"status":"([a-z_]+)"', texts))
    assert {'running', 'cancelling', 'completed', 'failed', 'timeout', 'cancelled'} <= statuses
    for message in OUTCOMES:
        assert message in texts, message
    if os.geteuid() != 0:  # the superuser reads a file of mode 000
        assert 'EACCES: permission denied, open' in texts
    # Each invalid result round fails on its own check; the rounds the checks let through complete.
    for id, completed, failed in (('invalid-v1', 3, 40), ('invalid-v2', 1, 46)):
        jobs = [jsjson.parse(text) for name, text in files[id].items() if name.endswith('/job.json')]
        states = [job['status'] for job in jobs]
        assert (states.count('completed'), states.count('failed')) == (completed, failed), id
        assert len({job['message'] for job in jobs if job['status'] == 'failed'}) == 16, id
    children = [child for _, theirs in node_run.values() for child in theirs['children']]
    assert {tuple(child['kills']) for child in children} >= {(), ('SIGTERM',)}
    assert {child['env']['OMP_NUM_THREADS'] for child in children} == {'1', '2'}
