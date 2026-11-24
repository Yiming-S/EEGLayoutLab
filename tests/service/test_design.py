"""The coordinate evaluation's run path (``eeglayoutlab.jobs.design``, phase 2 slice 5).

Ports check-design-decision.mjs's result validator test (:201), its service tests (:265, :288, :303, driven through
``FakeChild`` as Node drives its fake children, with the same context stub), its perturbation test (:330) and
check-design-robustness.mjs's validator test (:35, all eight corruptions). Then what Python adds: the permit, the
installation lock, the publish-once rule, the completion callbacks, the queue's prepared submit, ``aclose``, a
subclass with the overrides slice 6's editor uses and a real worker process; and the byte parity of every record the
run path writes with Node's own ``DesignEvaluationService`` (``parity/design_run.mjs``) on design roots, where the
context is the scientific one on both sides.
"""
from __future__ import annotations

import asyncio
import copy
import errno
import os
from pathlib import Path
import re
import sys

import pytest

from schema_parity_support import require

require('pydantic')

from eeglayoutlab.jobs.design import (  # noqa: E402
    JOB_LIMIT, DesignJobError, DesignJobs,
)
from eeglayoutlab.jobs.design_result import DesignResultError, valid_robustness, validate_design_result  # noqa: E402
from eeglayoutlab.jobs.identity import UNDEFINED, design_context  # noqa: E402
from eeglayoutlab.jobs.integrity import InputIntegrity  # noqa: E402
from eeglayoutlab.jobs.radius import RadiusJobError  # noqa: E402
from eeglayoutlab.jobs.slot import InstallationLock, execution_lock_path  # noqa: E402
from eeglayoutlab.schemas import jsjson  # noqa: E402

from .design_support import (  # noqa: E402
    ADMISSION, CORRUPTIONS, DESIGN, OTHER, PERTURB, REQUEST, ROBUST, Fixture, baseline_result, build, canonical,
    done, parity_cases, perturbation, record_tree, robust_result, run_node, run_python, worker_root,
)
from .key_parity_support import needs_node  # noqa: E402
from .library_support import robustness_block  # noqa: E402
from .radius_support import Spawner, until  # noqa: E402


def run(coroutine):
    return asyncio.run(coroutine)


def _cache_file(root: Path, key: str, kind: str = 'design_evaluation_jobs') -> Path:
    return Path(root) / f'results/v2/{kind}/{key}/cache.json'


def _parse(path: Path) -> object:
    return jsjson.parse(path.read_text(encoding='utf-8'))


# --- check-design-decision.mjs and check-design-robustness.mjs ------------------------------------------------------

def test_result_validator_rejects_a_switched_request_or_displaced_nominal_coordinates():
    """check-design-decision.mjs:201."""
    validate_design_result(baseline_result(), REQUEST)
    with pytest.raises(DesignResultError):
        validate_design_result({**baseline_result(), 'request': {**REQUEST, 'seed': 9}}, REQUEST)
    with pytest.raises(DesignResultError):
        validate_design_result({**baseline_result(), 'evaluated_xyz_mm': [[x + 3, y, z] for x, y, z in
                                                                          DESIGN['xyz_mm']]}, REQUEST)
    head = {**REQUEST, 'head_id': 'ixi002'}
    validate_design_result({**baseline_result(), 'request': head, 'forward_mode': 'head_scalp_node_table'}, head)
    for forward_mode in ('cached_fem', 'direct_fem', 'scalp_node_table'):
        with pytest.raises(DesignResultError, match='身份错误'):
            validate_design_result({**baseline_result(), 'request': head, 'forward_mode': forward_mode}, head)
    with pytest.raises(DesignResultError, match='身份错误'):
        validate_design_result({**baseline_result(), 'forward_mode': 'head_scalp_node_table'}, REQUEST)
    with pytest.raises(DesignResultError, match='身份错误'):
        validate_design_result({**baseline_result(), 'forward_mode': 'unknown'}, REQUEST)


def test_worker_results_cache_by_exact_inputs_and_do_not_consume_another_worker_slot_on_hit(tmp_path):
    """check-design-decision.mjs:265: a hit needs no permit (another owner holds it) and no child; once the inputs
    change, the same request is a miss that needs the permit, so it is busy."""
    async def scenario():
        fixture = Fixture(tmp_path)
        service, children = fixture.service, fixture.children
        release = None
        try:
            first = await service.submit(REQUEST)
            assert first['job']['status'] == 'running'
            children[0].stdout(jsjson.stringify({'type': 'result', 'result': baseline_result()}) + '\n')
            children[0].close(0)
            await done(service)
            release = service.execution_slot.acquire('other')
            cached = await service.submit(REQUEST)
            assert cached['job']['cached'] is True
            assert len(children) == 1
            fixture.change()
            busy = await service.submit(REQUEST)
            assert busy['busy'] is True
        finally:
            if release is not None:
                release()
            service.dispose()
    run(scenario())


def test_cancel_keeps_shared_slot_until_process_close_and_never_creates_a_success_cache(tmp_path):
    """check-design-decision.mjs:288."""
    async def scenario():
        fixture = Fixture(tmp_path)
        service, children = fixture.service, fixture.children
        try:
            first = await service.submit(REQUEST)
            service.cancel(first['job']['id'])
            assert service.active.status == 'cancelling'
            assert (await service.submit(OTHER))['busy'] is True
            children[0].close(0)
            await done(service)
            assert service.jobs[first['job']['id']].result is None
            # Python: and nothing under the key but the batch.
            assert children[0].kills == ['SIGTERM']
            assert not _cache_file(tmp_path, first['job']['key']).exists()
        finally:
            service.dispose()
    run(scenario())


def test_shutdown_during_input_validation_cannot_start_a_late_worker(tmp_path):
    """check-design-decision.mjs:303. Node's submit runs to its context await before ``dispose``; here one turn of
    the loop takes it there (the override is entered)."""
    async def scenario():
        fixture = Fixture(tmp_path)
        service, children = fixture.service, fixture.children
        gate, entered = asyncio.Event(), []

        async def pending(request):
            entered.append(request)
            await gate.wait()
            return {'identity': {}, 'key': 'a' * 64}
        service.context_override = pending
        submission = asyncio.ensure_future(service.submit(REQUEST))
        await asyncio.sleep(0)
        assert entered and service.submitting
        service.dispose()
        gate.set()
        with pytest.raises(DesignJobError, match='服务正在重启'):
            await submission
        assert len(children) == 0
        assert service.active is None
        assert service.submitting is False
    run(scenario())


def test_corrupt_perturbation_coordinates_labels_or_derived_spacing_are_rejected():
    """check-design-decision.mjs:330."""
    request = {**REQUEST, 'action': 'perturb'}
    result = {**baseline_result(), 'request': request, 'trials': [perturbation(i) for i in range(4)]}
    validate_design_result(result, request)
    for change in ({'xyz_mm': []}, {'region_indices': [0] * 64}, {'minimum_chord_distance_mm': UNDEFINED},
                   {'actual_max_mm': 5}, {'actual_mean_mm': 5}, {'candidate_bank_indices': [0] * 64},
                   {'candidate_bank_indices': [i + 1 for i in range(64)]}):
        bad = copy.deepcopy(result)
        bad['trials'][0].update(change)
        if bad['trials'][0].get('minimum_chord_distance_mm') is UNDEFINED:
            del bad['trials'][0]['minimum_chord_distance_mm']  # Object.assign of undefined: no number there
        with pytest.raises(DesignResultError):
            validate_design_result(bad, request)


# Node's checks of a trial's actual_max_mm and unchanged_fraction subtract them before testing that they are
# numbers, so JavaScript's ToNumber decides first: a string or an array that converts to another number than the
# coordinates give is a geometry mismatch, one that converts to the same number or to NaN an invalid result, and an
# object with its own toString V8's TypeError.
GEOMETRY, INVALID = '偏移几何量与坐标不一致', '偏移结果无效'
COERCIONS = [
    ('actual_max_mm', '5', GEOMETRY), ('actual_max_mm', [5], GEOMETRY), ('actual_max_mm', ' 0x10 ', GEOMETRY),
    ('actual_max_mm', '1e3', GEOMETRY), ('actual_max_mm', [[5]], GEOMETRY), ('actual_max_mm', '0', INVALID),
    ('actual_max_mm', '', INVALID), ('actual_max_mm', [], INVALID), ('actual_max_mm', 'abc', INVALID),
    ('actual_max_mm', {}, INVALID), ('actual_max_mm', [1, 2], INVALID), ('actual_max_mm', None, INVALID),
    ('unchanged_fraction', '0.5', GEOMETRY), ('unchanged_fraction', [0.5], GEOMETRY), ('unchanged_fraction', '', GEOMETRY),
    ('unchanged_fraction', [], GEOMETRY), ('unchanged_fraction', [None], GEOMETRY), ('unchanged_fraction', None, GEOMETRY),
    ('unchanged_fraction', 'Infinity', GEOMETRY), ('unchanged_fraction', '1', INVALID), ('unchanged_fraction', [1], INVALID),
    ('unchanged_fraction', True, INVALID), ('unchanged_fraction', 'x', INVALID),
]


@pytest.mark.parametrize('member, value, message', COERCIONS)
def test_trial_geometry_converts_its_members_as_javascript_subtracts_them(member, value, message):
    request = {**REQUEST, 'action': 'perturb'}
    result = {**baseline_result(), 'request': request, 'trials': [perturbation(i) for i in range(4)]}
    result['trials'][0][member] = value
    with pytest.raises(DesignResultError) as caught:
        validate_design_result(result, request)
    assert str(caught.value) == message


@pytest.mark.parametrize('member', ['actual_max_mm', 'unchanged_fraction'])
def test_a_trial_member_with_its_own_to_string_throws_v8s_type_error(member):
    request = {**REQUEST, 'action': 'perturb'}
    result = {**baseline_result(), 'request': request, 'trials': [perturbation(i) for i in range(4)]}
    result['trials'][0][member] = {'toString': 1}
    with pytest.raises(TypeError, match='^Cannot convert object to primitive value$'):
        validate_design_result(result, request)


def test_the_result_validator_requires_the_block_exactly_when_requested_and_checks_its_structure():
    """check-design-robustness.mjs:35, all eight corruptions."""
    robust = {**REQUEST, 'robustness': 'standard/1'}
    validate_design_result(robust_result(robust, robustness_block()), robust)
    validate_design_result(robust_result(robust, robustness_block(table=False)), robust)
    validate_design_result(robust_result(REQUEST), REQUEST)
    with pytest.raises(DesignResultError, match='稳健性'):
        validate_design_result(robust_result(robust), robust)
    with pytest.raises(DesignResultError, match='稳健性'):
        validate_design_result(robust_result(REQUEST, robustness_block()), REQUEST)
    assert len(CORRUPTIONS) == 8
    for corrupt in CORRUPTIONS:
        block = robustness_block()
        corrupt(block)
        assert valid_robustness(block) is False, corrupt.__name__
    assert valid_robustness(robustness_block()) is True


# --- What Python adds ------------------------------------------------------------------------------------------------

def test_the_permit_and_the_installation_lock_are_held_until_the_records_are_written(tmp_path):
    """The slot is released in finish's ``finally``, after cache.json and job.json; the completion callbacks come
    after that, once, with the job terminal; another workspace's lock on the installation is refused meanwhile."""
    async def scenario():
        fixture = Fixture(tmp_path)
        service, children = fixture.service, fixture.children
        seen = []

        def finished(job):
            seen.append((job.id, job.status, service.active, service.execution_slot.busy,
                         service.execution_slot.lock.held, (Path(job.batch) / 'job.json').is_file(),
                         _cache_file(tmp_path, job.key).is_file()))
        service.finish_callbacks.append(finished)
        first = await service.submit(REQUEST)
        assert service.execution_slot.busy and service.execution_slot.lock.held
        other = InstallationLock(str(tmp_path))
        assert other.try_acquire() is False
        children[0].complete(baseline_result())
        await service.jobs[first['job']['id']].done
        assert seen == [(first['job']['id'], 'completed', None, False, False, True, True)]
        assert other.try_acquire() is True
        other.release()
        assert Path(execution_lock_path(str(tmp_path))).is_file()
        assert service.store.keys('design') == [first['job']['key']]
    run(scenario())


def test_another_workspace_computing_makes_a_submit_busy_without_writing(tmp_path):
    """The installation lock: while another process holds it, the permit is refused (``contended``), nothing is
    written, and the same submit succeeds once it is released; a lookup takes neither."""
    async def scenario():
        holder = InstallationLock(str(tmp_path))
        assert holder.try_acquire()
        fixture = Fixture(tmp_path)
        service, children = fixture.service, fixture.children
        assert await service.submit(REQUEST) == {'busy': True, 'maintenance': False}
        assert service.execution_slot.contended and not service.submitting and not children
        assert not (tmp_path / 'results/v2/design_evaluation_jobs').exists()
        assert await service.lookup(REQUEST) == {'hit': False}
        holder.release()
        assert (await service.submit(REQUEST))['job']['status'] == 'running'
        assert not service.execution_slot.contended
        service.dispose()
        children[0].close(None, 'SIGTERM')
        await done(service)
    run(scenario())


def test_a_paused_slot_a_broken_lock_and_a_failed_context_refuse_before_any_write(tmp_path):
    async def scenario():
        fixture = Fixture(tmp_path)
        service = fixture.service
        service.execution_slot.pause()
        assert await service.submit(REQUEST) == {'busy': True, 'maintenance': True}
        service.execution_slot.resume()
        lock = Path(execution_lock_path(str(tmp_path)))
        lock.parent.mkdir(parents=True)
        lock.symlink_to(tmp_path / 'elsewhere')
        with pytest.raises(OSError):
            await service.submit(REQUEST)
        assert not service.submitting and service.active is None and not service.execution_slot.busy
        assert not (tmp_path / 'results/v2/design_evaluation_jobs').exists() and not (tmp_path / 'elsewhere').exists()

        def failing(request):
            raise ValueError('外部表面筛选文件身份不匹配')
        service.context_override = failing
        with pytest.raises(ValueError, match='^外部表面筛选文件身份不匹配$'):
            await service.submit(REQUEST)
        with pytest.raises(ValueError, match='^外部表面筛选文件身份不匹配$'):
            await service.lookup(REQUEST)
        assert not service.submitting and not service.execution_slot.busy and not fixture.children
        with pytest.raises(DesignResultError, match='^设计评价字段错误$'):
            await service.submit({})
    run(scenario())


def test_a_pause_or_a_failed_write_while_the_batch_is_created_releases_the_permit(tmp_path):
    """Node's refusal after request.json: a slot paused while it was written (maintenance began meanwhile) gives
    ``{busy, maintenance: True}`` with request.json kept and the permit released; a failed write raises with the
    permit released. Neither starts a worker or remembers a job."""
    async def scenario():
        fixture = Fixture(tmp_path)
        service, children = fixture.service, fixture.children
        written, original = [], service.store.write

        def pausing(path, value):
            original(path, value)
            written.append(Path(path))
            service.execution_slot.pause()
        service.store.write = pausing
        assert await service.submit(REQUEST) == {'busy': True, 'maintenance': True}
        assert [path.name for path in written] == ['request.json'] and written[0].is_file()
        assert not service.execution_slot.busy and not service.execution_slot.lock.held
        assert service.active is None and not service.submitting and not children and not service.jobs
        service.execution_slot.resume()

        def failing(path, value):
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        service.store.write = failing
        with pytest.raises(OSError):
            await service.submit(REQUEST)
        assert not service.execution_slot.busy and not service.execution_slot.lock.held
        assert service.active is None and not service.submitting and not children and not service.jobs
        service.store.write = original
        assert (await service.submit(REQUEST))['job']['status'] == 'running'
        service.dispose()
        children[0].close(None, 'SIGTERM')
        await done(service)
    run(scenario())


def test_a_cancel_while_the_worker_is_spawned_stops_it_as_soon_as_it_exists(tmp_path):
    """Node spawns synchronously; here a cancel during the spawn makes the job ``cancelling`` at once and the
    child gets SIGTERM when it exists."""
    async def scenario():
        gate, spawner, fixture = asyncio.Event(), Spawner(), Fixture(tmp_path)

        async def slow(worker, executable, args, options):
            await gate.wait()
            return spawner(worker, executable, args, options)
        service = DesignJobs(str(tmp_path), 'python3', context=fixture.context, spawn=slow, timeout_ms=3000)
        submitted = asyncio.ensure_future(service.submit(REQUEST))
        await until(lambda: service.active is not None)
        assert not service.submitting and service.active.status == 'running'
        assert await service.submit(REQUEST) == {'job': service.view(service.active)}  # the same key while it spawns
        id = service.active.id
        assert service.cancel(id) is None
        assert (service.active.status, service.active.message) == ('cancelling', '正在停止计算')
        gate.set()
        assert (await submitted)['job']['status'] == 'cancelling'
        assert spawner.children[0].kills == ['SIGTERM']
        spawner.children[0].close(None, 'SIGTERM')
        await done(service)
        assert (service.jobs[id].status, service.jobs[id].message) == ('cancelled', '计算已停止')
    run(scenario())


def test_the_wall_clock_limit_is_timeout_ms(tmp_path):
    """``timeoutMs`` is the worker's limit (the parity's timeout case waits for the signal, so it cannot tell 2 s
    from 20 s): its timer is armed during submit for ``timeout_ms / 1000`` seconds, without a wait."""
    async def scenario():
        fixture = Fixture(tmp_path)
        service, children = fixture.service, fixture.children
        loop = asyncio.get_running_loop()
        before = loop.time()
        await service.submit(REQUEST)
        after = loop.time()
        due = service.active.worker._timer.when()
        assert before + 3.0 <= due <= after + 3.0
        service.dispose()
        children[0].close(None, 'SIGTERM')
        await done(service)
    run(scenario())


def test_a_cancelled_submit_caller_does_not_strand_the_active_job(tmp_path):
    """The spawn goes on when the task awaiting submit is cancelled (a dropped request): the worker starts, its
    close finishes the job, and the permit is released."""
    async def scenario():
        gate, spawner, fixture = asyncio.Event(), Spawner(), Fixture(tmp_path)

        async def slow(worker, executable, args, options):
            await gate.wait()
            return spawner(worker, executable, args, options)
        service = DesignJobs(str(tmp_path), 'python3', context=fixture.context, spawn=slow, timeout_ms=3000)
        submitted = asyncio.ensure_future(service.submit(REQUEST))
        await until(lambda: service.active is not None)
        submitted.cancel()
        with pytest.raises(asyncio.CancelledError):
            await submitted
        gate.set()
        await until(lambda: len(spawner.children) == 1)
        id = service.active.id
        spawner.children[0].complete(baseline_result())
        await done(service)
        assert service.jobs[id].status == 'completed'
        assert not service.execution_slot.busy and not service.execution_slot.lock.held
        assert (await service.submit(REQUEST))['job']['cached'] is True
    run(scenario())


def test_a_valid_cache_published_first_by_another_workspace_is_kept(tmp_path):
    """B16: cache.json is published once. A valid one written meanwhile (another workspace) stays byte for byte;
    the job completes with its own result in job.json. A file that is not valid is replaced."""
    async def scenario():
        fixture = Fixture(tmp_path)
        service, children = fixture.service, fixture.children
        first = await service.submit(REQUEST)
        job = service.jobs[first['job']['id']]
        theirs = _cache_file(tmp_path, job.key)
        theirs.write_text(jsjson.stringify({'key': job.key, 'identity': job.ctx['identity'],
                                            'result': baseline_result(), 'result_sha256':
                                            jsjson.sha256_hex(baseline_result()),
                                            'finished_at': '2026-01-01T00:00:00.000Z'}), encoding='utf-8')
        before = theirs.read_bytes()
        mine = {**baseline_result(), 'provenance': {'candidate_count': 64, 'note': 'mine'}}
        children[0].complete(mine)
        await done(service)
        assert (job.status, job.result, theirs.read_bytes()) == ('completed', mine, before)
        assert _parse(Path(job.batch) / 'job.json') == {**service.view(job), 'stderr': ''}
        # Not a valid record for the job: replaced.
        theirs.write_text('not json', encoding='utf-8')
        second = await service.submit(REQUEST)
        assert second['job']['status'] == 'running'
        children[1].complete(mine)
        await done(service)
        record = _parse(theirs)
        assert list(record) == ['key', 'identity', 'result', 'result_sha256', 'finished_at']
        assert (record['key'], record['result'], record['result_sha256']) == (job.key, mine, jsjson.sha256_hex(mine))
        assert not [name for name in os.listdir(theirs.parent) if name.endswith('.tmp')]
    run(scenario())


def test_the_finish_time_at_restart_is_read_only_from_a_record_that_passes_the_reconciliations_record_checks(
        tmp_path):
    """``stored_finish`` (the restart's ``recover()``) gives ``cache.json``'s ``finished_at`` only when the record
    passes the record checks of Node's ``inspectReceipt`` (inspect_service_reconciliation.mjs:44-49): its key and
    checksum are current, it holds the lookup's result, and the identity and the request it names, if any, are the
    prepared ones. A record that names neither is accepted by its key, as an older one is. The record is read as the
    lookup reads it (a known difference, R6): a second link, as B16's crash window leaves it, and a record directory
    behind a link inside the root are read, where the tool's ``readStrictCache`` retains the receipt."""
    async def scenario():
        fixture = Fixture(tmp_path)
        request = canonical(REQUEST)
        ctx = fixture.context(request)
        key, identity, result = ctx['key'], ctx['identity'], baseline_result()
        path = _cache_file(tmp_path, key)
        path.parent.mkdir(parents=True)
        stored = {'key': key, 'identity': identity, 'result': result, 'result_sha256': jsjson.sha256_hex(result),
                  'finished_at': '2026-01-01T00:00:00.000Z'}

        async def finish(cache: dict, found: object = result) -> object:
            path.write_text(jsjson.stringify(cache), encoding='utf-8')
            return await fixture.service.stored_finish(key, request, identity, found)

        for cache in (stored, {name: value for name, value in stored.items() if name != 'identity'},
                      {**stored, 'request': request}):
            assert await finish(cache) == '2026-01-01T00:00:00.000Z'
        for cache in ({**stored, 'key': '0' * 64}, {**stored, 'result_sha256': '0' * 64},
                      {**stored, 'identity': {'version': 2}}, {**stored, 'identity': None},
                      {**stored, 'request': canonical(OTHER)}):
            assert await finish(cache) is None, cache
        assert await finish(stored, {**result, 'projection_max_mm': 1}) is None
        os.link(path, f'{path}.{"0" * 8}-0000-4000-8000-000000000000.tmp')
        assert await finish(stored) == '2026-01-01T00:00:00.000Z'
        path.parent.rename(path.parent.with_name('moved'))
        path.parent.symlink_to('moved')
        assert await finish(stored) == '2026-01-01T00:00:00.000Z'
    run(scenario())


def test_aclose_stops_the_worker_and_waits_for_its_records(tmp_path):
    async def scenario():
        fixture = Fixture(tmp_path)
        service, children = fixture.service, fixture.children
        first = await service.submit(REQUEST)
        closing = asyncio.ensure_future(service.aclose())
        await until(lambda: bool(children[0].kills))
        assert service.active.cancel_reason == 'restart' and not closing.done()
        children[0].close(None, 'SIGTERM')
        await closing
        record = _parse(Path(service.jobs[first['job']['id']].batch) / 'job.json')
        assert (record['status'], record['message'], record['result']) == ('cancelled', '计算已停止', None)
        with pytest.raises(DesignJobError, match='^计算服务正在重启$'):
            await service.submit(REQUEST)
        assert isinstance(DesignJobError('x'), RadiusJobError)  # the routes refuse both run paths alike
        await service.aclose()  # nothing active: returns
    run(scenario())


def test_the_queue_starts_jobs_with_its_prepared_request_and_reads_their_state(tmp_path):
    """What ``jobs.kinds``'s adapter calls: ``lookup(request, ctx)``, ``submit(prepared)`` (the request is
    normalized again and its context computed again, as Node's adapter passes the request), ``jobs``, ``view``,
    ``active``, ``submitting`` and ``active_pid()``; a hit from ``lookup`` is not remembered."""
    async def scenario():
        fixture = Fixture(tmp_path)
        service, children = fixture.service, fixture.children
        ctx = fixture.context(canonical(REQUEST))
        assert await service.lookup(REQUEST, ctx) == {'hit': False}
        started = await service.submit({'request': {**REQUEST, 'seed': 42.0}, 'key': ctx['key'], 'ctx': ctx})
        assert started['job']['key'] == ctx['key'] and service.active.id == started['job']['id']
        assert not service.submitting and service.active_pid() is None  # a fake child has no pid
        assert service.view(service.jobs[started['job']['id']]) == started['job']
        assert jsjson.parse(children[0].inputs[0].decode('utf-8')) == canonical(REQUEST)
        children[0].complete(baseline_result())
        await done(service)
        hit = await service.lookup(REQUEST, ctx)
        assert hit['hit'] is True and hit['job']['cached'] is True and hit['job']['id'] not in service.jobs
        assert list(hit['job']) == ['id', 'key', 'status', 'message', 'progress', 'result', 'cached']
        assert (hit['job']['message'], hit['job']['progress']) == ('设计评价已完成', 1)
    run(scenario())


def test_the_job_map_keeps_the_newest_20_and_never_drops_the_active_job(tmp_path):
    async def scenario():
        fixture = Fixture(tmp_path)
        service, children = fixture.service, fixture.children
        first = (await service.submit(REQUEST))['job']['id']
        children[0].complete(baseline_result())
        await done(service)
        cached = [(await service.submit(REQUEST))['job']['id'] for _ in range(JOB_LIMIT + 2)]
        assert list(service.jobs) == cached[2:] and first not in service.jobs
        active = (await service.submit(OTHER))['job']['id']
        more = [(await service.submit(REQUEST))['job']['id'] for _ in range(JOB_LIMIT + 1)]
        assert list(service.jobs) == [active, *more[-(JOB_LIMIT - 1):]]
        children[1].close(1)
        await done(service)
        last = (await service.submit(REQUEST))['job']['id']
        assert list(service.jobs) == [*more[-(JOB_LIMIT - 1):], last]
    run(scenario())


class EditorLike(DesignJobs):
    """The overrides ``ElectrodeEditorService`` makes (slice 6): its own record kind, script, request, result check,
    a context built on the base one, the worker's input and the view."""

    record_kind = 'editor'
    script_name = 'scripts/electrode_editor.py'

    def normalize(self, raw):
        if not isinstance(raw, dict) or raw.get('action') != 'evaluate' or not isinstance(raw.get('parent_id'), str):
            raise ValueError('编辑请求无效')
        return {'action': 'evaluate', 'parent_id': raw['parent_id'], 'parent_digest': 'p' * 64}

    def validate(self, result, request, admission=UNDEFINED):
        if not isinstance(result, dict) or result.get('request') != request:
            raise ValueError('编辑结果身份错误')

    async def context(self, request):
        base = await super().context(request)
        identity = {**base['identity'], 'schema': 'electrode-editor-cache/1', 'parent_digest': 'p' * 64}
        return {**base, 'parent': {'id': request['parent_id']}, 'parent_digest': 'p' * 64, 'identity': identity,
                'key': jsjson.sha256_hex({'request': request, 'identity': identity})}

    def worker_input(self, job):
        return {'request': job.request, 'parent': job.ctx['parent']}

    def view(self, job):
        digest = job.ctx.get('parent_digest') if isinstance(job.ctx, dict) else None
        if digest is None and isinstance(job.result, dict):
            digest = job.result['request'].get('parent_digest')
        return {**super().view(job), 'parent_digest': digest}


def test_a_subclass_overrides_the_request_result_context_input_view_and_records(tmp_path):
    async def scenario():
        fixture = Fixture(tmp_path)
        children = []
        service = EditorLike(str(tmp_path), 'python3', context=fixture.context, spawn=Spawner(children=children))
        request = {'action': 'evaluate', 'parent_id': 'layout-1'}
        started = await service.submit(request)
        job = service.jobs[started['job']['id']]
        assert started['job']['parent_digest'] == 'p' * 64
        assert children[0].args == ['-u', str(tmp_path / 'scripts/electrode_editor.py')]
        assert jsjson.parse(children[0].inputs[0].decode('utf-8')) == {
            'request': service.normalize(request), 'parent': {'id': 'layout-1'}}
        assert Path(job.batch).parent == tmp_path / 'results/v2/electrode_editor_jobs' / job.key
        children[0].complete({'request': {'action': 'evaluate'}})
        await done(service)
        assert (job.status, job.message) == ('failed', '编辑结果身份错误')
        assert (await service.submit(request))['job']['status'] == 'running'
        result = {'request': service.normalize(request), 'edited_metrics': {'field_relative': 1}}
        children[1].complete(result)
        await done(service)
        record = _parse(_cache_file(tmp_path, job.key, 'electrode_editor_jobs'))
        assert (record['result'], record['identity']['schema']) == (result, 'electrode-editor-cache/1')
        hit = await service.submit(request)  # a cached job has no context: the view falls back to the result
        assert (hit['job']['cached'], hit['job']['parent_digest']) == (True, 'p' * 64)
        assert not (tmp_path / 'results/v2/design_evaluation_jobs').exists()
    run(scenario())


def test_a_real_worker_process_completes_fails_and_stops_through_the_transport(tmp_path):
    """The worker as Node runs it, ``python -u R/scripts/design_evaluation.py`` in R with the canonical request on
    stdin, on a design root with the real scientific context: a completed evaluation and a perturbation with their
    records, a worker error, a stale result and a cancelled worker; no process group outlives its job."""
    root = worker_root(tmp_path)

    async def scenario():
        service = DesignJobs(str(root), sys.executable, timeout_ms=60000)
        assert service.python == sys.executable
        first = await service.submit(REQUEST)
        pid = service.active_pid()
        assert isinstance(pid, int)
        await done(service)
        job = service.jobs[first['job']['id']]
        assert (job.status, job.message, job.progress, job.stderr) == (
            'completed', '设计评价已完成并保存', 1, 'worker stderr\n')
        assert job.result['request'] == canonical(REQUEST)
        assert job.result['provenance'] == {'candidate_count': 64, **ADMISSION}
        with pytest.raises(ProcessLookupError):
            os.killpg(pid, 0)
        context = design_context(str(root), sys.executable, InputIntegrity(str(root)), canonical(REQUEST))
        assert job.key == context.key
        cache = _parse(_cache_file(root, job.key))
        assert list(cache) == ['key', 'identity', 'result', 'result_sha256', 'finished_at']
        assert (cache['key'], cache['identity'], cache['result']) == (job.key, context.identity, job.result)
        assert cache['result_sha256'] == jsjson.sha256_hex(job.result)
        assert _parse(Path(job.batch) / 'request.json') == {'request': canonical(REQUEST),
                                                            'identity': context.identity}
        assert _parse(Path(job.batch) / 'job.json') == {**service.view(job), 'stderr': 'worker stderr\n'}
        assert (await service.lookup(REQUEST))['hit'] is True

        perturbed = await service.submit(PERTURB)
        await done(service)
        job = service.jobs[perturbed['job']['id']]
        assert job.status == 'completed' and len(job.result['trials']) == 4
        robust = await service.submit(ROBUST)
        await done(service)
        assert service.jobs[robust['job']['id']].result['robustness'] == robustness_block()

        failing = await service.submit({**REQUEST, 'design': {**DESIGN, 'name': 'fail'}})
        await done(service)
        job = service.jobs[failing['job']['id']]
        assert (job.status, job.message, job.result) == ('failed', '评价失败', None)
        assert 'Traceback: boom' in job.stderr and not _cache_file(root, job.key).exists()

        stale = await service.submit({**REQUEST, 'design': {**DESIGN, 'name': 'stale'}})
        await done(service)
        job = service.jobs[stale['job']['id']]
        assert (job.status, job.message) == ('failed', '设计评价结果身份错误')

        held = await service.submit({**REQUEST, 'design': {**DESIGN, 'name': 'hold'}})
        job = service.jobs[held['job']['id']]
        pid = service.active_pid()
        await until(lambda: job.progress == 0.25)
        assert job.message == '评价名义坐标'
        service.cancel(job.id)
        await done(service)
        assert (job.status, job.message) == ('cancelled', '计算已停止')
        with pytest.raises(ProcessLookupError):
            os.killpg(pid, 0)
        assert not service.execution_slot.busy and not service.execution_slot.lock.held
    run(scenario())


# --- Parity with Node's run path -------------------------------------------------------------------------------------

_TEMPORARY = re.compile(r'\.[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.tmp')
PARITY_IDS = [case['id'] for case in parity_cases(Path('/parity'))]


@pytest.fixture(scope='module')
def node_run(tmp_path_factory):
    """Node's ``DesignEvaluationService`` over every case once; each root is then moved to ``root.node``."""
    base = tmp_path_factory.mktemp('design-run')
    cases = parity_cases(base)
    for case in cases:
        build(case)
    output = run_node(cases, base)
    for case in cases:
        Path(case['root']).rename(Path(case['root']).with_name('root.node'))
    return {case['id']: (case, theirs) for case, theirs in zip(cases, output['cases'])}


def _masked(records: list) -> list:
    """The records with the random part of temporary names masked (a failed write names its temporary)."""
    return [[kind, _TEMPORARY.sub('.<uuid>.tmp', text)] for kind, text in records]


@needs_node
@pytest.mark.parametrize('id', PARITY_IDS)
def test_run_path_writes_the_bytes_and_reports_the_states_of_node(node_run, id):
    """Parity 1 of slice 5: given the same worker output, clock and job identifiers, the run path returns Node's
    views, refusals and errors (as JSON text), spawns the worker as Node does (executable, arguments, cwd, stdio,
    shell, thread settings, inherited environment, stdin bytes, signals) and leaves the same record tree:
    request.json, job.json and cache.json byte for byte, no temporaries. The one difference is B16's: in
    ``publish-once`` the valid cache.json another workspace wrote first stays here, where Node replaces it."""
    case, theirs = node_run[id]
    build(case)  # the same root, at the same path, again
    ours = run_python(case)
    assert _masked(ours['records']) == _masked(theirs['records'])
    assert (ours['clock'], ours['ids']) == (theirs['clock'], theirs['ids'])
    assert ours['children'] == theirs['children']
    node_root = Path(case['root']).with_name('root.node')
    mine, node = record_tree(Path(case['root'])), record_tree(node_root)
    if id == 'publish-once':
        key = jsjson.parse(theirs['records'][0][1])['job']['key']
        kept = jsjson.parse(mine.pop(f'{key}/cache.json').decode('utf-8'))
        replaced = jsjson.parse(node.pop(f'{key}/cache.json').decode('utf-8'))
        assert kept['finished_at'] == '2026-01-01T00:00:00.000Z' != replaced['finished_at']
        assert {**kept, 'finished_at': None} == {**replaced, 'finished_at': None}
    assert mine == node
    assert not [name for name in node if name.endswith('.tmp')]


@needs_node
def test_the_parity_cases_reach_every_outcome_of_the_run_path(node_run):
    texts = ''.join(text for _, theirs in node_run.values() for _, text in theirs['records'])
    statuses = set(re.findall(r'"status":"([a-z_]+)"', texts))
    assert {'running', 'cancelling', 'completed', 'failed', 'timeout', 'cancelled'} <= statuses
    for message in ('准备本地坐标评价', '正在停止计算', '达到0分钟计算时限，未保存未完成结果', '达到3分钟计算时限，未保存未完成结果',
                    '计算已停止', '计算未完成，错误记录已保存', '设计评价已完成并保存', '设计评价已完成"',
                    '计算期间输入或代码发生变化', '正在处理另一项设计评价请求', '"busy":true,"maintenance":true',
                    '"busy":true,"maintenance":false', '计算服务正在重启', '结果保存失败：ENOENT', '结果保存失败：EISDIR',
                    'spawn EINVAL', 'expected new calculation', 'spawn python3 ENOENT', '设计评价表面筛选身份不匹配',
                    '设计评价结果身份错误', '评价指标无效', '缺少绝对指标或误差分位数', '无效相对指标', '绝对指标与相对指标不一致',
                    '结果投影坐标无效', '实际评价坐标点距不足', '投影距离与实际坐标不一致', '偏移试验不完整',
                    '偏移坐标或区域标签无效', '偏移几何量与坐标不一致', '偏移结果无效', '偏移评分或点距无效',
                    '几何失败不能携带评分', '稳健性结果无效', 'Cannot read properties of null', '外部表面筛选',
                    '"cached":true', '{"hit":false}', '"hit":true', '设计评价字段错误', 'Infinity', '[object Object]',
                    'ENOENT: no such file or directory, realpath', 'ENOENT: no such file or directory, open',
                    'EISDIR: illegal operation on a directory, read"', "/data/\ufffd.npz'"):
        assert message in texts, message
    # The superuser reads a file of mode 000: context-failure leaves its chmod rounds out, and the unreadable cache
    # is a hit.
    if os.geteuid() != 0:
        assert 'EACCES: permission denied, open' in texts
    children = [child for _, theirs in node_run.values() for child in theirs['children']]
    assert {tuple(child['kills']) for child in children} >= {(), ('SIGTERM',)}
