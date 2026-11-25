"""Robustness studies (phase 2 slice 8): the protocol and the aggregation of ``eeglayoutlab.jobs.studies``.

The aggregation is Node's ``empiricalSummary``, ``summarizeStudyCase`` and ``aggregateStudy`` (``studies/
protocol.mjs``): ``test_aggregation_equals_node`` runs them in ``parity/studies.mjs`` (mode ``aggregate``) over fixed
and random case results, value lists and case lists, and Python must write the same JSON, leave its input as Node
does, and fail where Node throws. The study format itself (``normalizeStudyInput``) is compared with Node in
``test_study_request.py``. Ports of check-robustness-aggregation.mjs and of the protocol sites of
check-robustness-studies.mjs.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import math
import os
from pathlib import Path
import random
import stat
import sys
import uuid

import pytest

from schema_parity_support import require

from eeglayoutlab.jobs.identity import UNDEFINED
from eeglayoutlab.jobs.studies import (CASE_STATUSES, TRIAL_METRICS, StudyError, aggregate_study, empirical_summary,
                                       normalize_study_input, summarize_study_case)
from eeglayoutlab.schemas import jsjson
from eeglayoutlab.server.workspace import LOCAL_OWNER
from eeglayoutlab.server.workspace_studies import (_ISO_DATE as ISO_DATE, UNAVAILABLE, ResourceError,
                                                   RobustnessStudyService, StudyStore, error_answer,
                                                   iso_date_finite, safe_failure)

from .key_parity_support import HEADS, ROOTS, design_root, needs_node
from .studies_support import (FIXTURE_PROTOCOL, INTERRUPTED, STUDY_DESIGN, StudyFixture, cache_text, heads_input,
                              js_stringify, node_form, node_outcome, prepared_for, python_aggregate, python_export,
                              python_identity, python_store, random_aggregate_cases, run_driver, study_input, to_text)

EPSILON = sys.float_info.epsilon
DESIGN = {'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm',
          'name': 'Original scientific name', 'xyz_mm': [[(i % 8) * 6, (i // 8) * 6, 0] for i in range(64)],
          'region_indices': [i % 2 for i in range(64)]}
EMPTY = {'n': 0, 'median': None, 'p10': None, 'p90': None}


def _input(seeds=(42, 43), **extra):
    return {'protocol': 'noise_seeds', 'design': DESIGN, 'cases': [{'seed': seed, 'radius_mm': 6} for seed in seeds],
            **extra}


def _design_request(**fields):
    require('pydantic')
    from eeglayoutlab.jobs.design_result import normalize_design_request
    return normalize_design_request(fields)


# --- check-robustness-aggregation.mjs ----------------------------------------------------------------------------

def _trial(value):
    if value is None:
        return {'status': 'geometry_rejected', 'field_relative': None, 'fixed_estimator_field_relative': None}
    return {'status': 'completed', 'field_relative': value, 'fixed_estimator_field_relative': value,
            'sensitivity_tail': value}


def _result(values):
    return {'nominal': {'field_relative': .75, 'sensitivity_tail': .5, 'localization_relative': None},
            'trials': [_trial(value) for value in values]}


def test_type7_empirical_quantiles_interpolate_known_finite_observations_and_retain_the_actual_count():
    known = empirical_summary([30, 0, 20, 10])
    assert known['n'] == 4 and known['median'] == 15 and known['p90'] == 27
    assert abs(known['p10'] - 3) <= 4 * EPSILON
    assert empirical_summary([None, UNDEFINED, math.nan, math.inf]) == EMPTY
    assert empirical_summary([.125, None]) == {'n': 1, 'median': .125, 'p10': .125, 'p90': .125}


def test_position_study_distribution_gives_each_case_equal_weight_while_keeping_every_rejected_trial():
    a, b = _result([0, 0, 0, 0]), _result([100, None, None, None])
    before = jsjson.stringify([a, b])
    cases = [
        {'request': {'radius_mm': 3}, 'status': 'completed', 'summary': summarize_study_case(a)},
        {'request': {'radius_mm': 3}, 'status': 'completed', 'summary': summarize_study_case(b)},
        {'request': {'radius_mm': 3}, 'status': 'failed', 'summary': None, 'error': {'code': 'child_failed'}},
        {'request': {'radius_mm': 3}, 'status': 'cancelled', 'summary': None},
        {'request': {'radius_mm': 6}, 'status': 'pending', 'summary': None},
    ]
    copied = copy.deepcopy(cases)
    report = aggregate_study('grid_displacements', cases)
    assert (report['case_count'], report['completed_cases'], report['failed_cases'], report['cancelled_cases'],
            report['pending_cases']) == (5, 2, 1, 1, 1)
    assert report['groups'][0]['trial_case_medians']['field_relative'] == {'n': 2, 'median': 50, 'p10': 10, 'p90': 90}
    assert report['groups'][0]['nominal']['localization_relative']['n'] == 0
    assert report['groups'][1]['trial_case_medians']['field_relative']['median'] is None
    assert cases[1]['summary']['rejected_trials'] == 3 and len(cases[1]['summary']['trials']) == 4
    assert jsjson.stringify([a, b]) == before and cases == copied


def test_an_all_rejected_position_case_stays_completed_with_zero_finite_trial_readings():
    summary = summarize_study_case(_result([None, None, None, None]))
    assert summary['valid_trials'] == 0 and summary['rejected_trials'] == 4
    assert summary['trial_metrics']['field_relative'] == EMPTY
    report = aggregate_study('grid_displacements',
                             [{'request': {'radius_mm': 10}, 'status': 'completed', 'summary': summary}])
    assert report['completed_cases'] == 1 and report['groups'][0]['trial_case_medians']['field_relative']['n'] == 0


# --- check-robustness-studies.mjs: the protocol ------------------------------------------------------------------

def test_study_protocols_preserve_original_normalized_requests_and_keep_labels_outside_scientific_identity():
    require('pydantic')
    names = [f'Channel {i + 1}' for i in range(64)]
    normalized = normalize_study_input(_input([42], design={**DESIGN, 'electrode_names': names}))
    assert normalized['requests'] == [_design_request(action='evaluate', design=DESIGN, radius_mm=6, seed=42)]
    assert normalized['annotation']['electrode_names'] == names
    assert 'electrode_names' not in normalized['design']
    grid = normalize_study_input(_input([42], protocol='grid_displacements',
                                        cases=[{'seed': 42, 'radius_mm': 3}, {'seed': 42, 'radius_mm': 10}]))
    assert [[r['action'], r['seed'], r['radius_mm']] for r in grid['requests']] == [
        ['perturb', 42, 3], ['perturb', 42, 10]]
    for invalid in (
        _input([42, 42]),
        _input(range(13)),
        _input([42], cases=[{'seed': 42, 'radius_mm': 3}, {'seed': 43, 'radius_mm': 6}]),
        _input([42], cases=[{'seed': -1, 'radius_mm': 6}]),
    ):
        with pytest.raises(StudyError):
            normalize_study_input(invalid)


def test_cross_head_studies_evaluate_one_head_per_case_at_one_radius_without_conductivity_scenarios():
    require('pydantic')

    def heads(cases, **extra):
        return _input([], protocol='heads', cases=cases, **extra)

    study = normalize_study_input(heads([{'head_id': 'ernie_xh', 'seed': 42, 'radius_mm': 6},
                                         {'head_id': 'ixi002', 'seed': 42, 'radius_mm': 6}]))
    assert [[r['action'], r['head_id'], r['seed'], r['radius_mm']] for r in study['requests']] == [
        ['evaluate', 'ernie_xh', 42, 6], ['evaluate', 'ixi002', 42, 6]]
    assert study['requests'][1] == _design_request(action='evaluate', design=DESIGN, radius_mm=6, seed=42,
                                                   head_id='ixi002')
    assert aggregate_study('heads', [])['interpretation'] == 'cross_head_empirical_cases'
    assert aggregate_study('noise_seeds', [])['interpretation'] == 'Ernie_within_model_empirical_cases'
    for invalid in (
        heads([{'head_id': 'ixi002', 'seed': 42, 'radius_mm': 6}, {'head_id': 'ixi002', 'seed': 43, 'radius_mm': 6}]),
        heads([{'head_id': 'ixi002', 'seed': 42, 'radius_mm': 6}, {'head_id': 'ixi012', 'seed': 42, 'radius_mm': 3}]),
        heads([{'head_id': 'ernie_xh', 'seed': 42, 'radius_mm': 6}, {'head_id': 'ixi002', 'seed': 7, 'radius_mm': 6}]),
        heads([{'seed': 42, 'radius_mm': 6}]),
        heads([{'head_id': '', 'seed': 42, 'radius_mm': 6}]),
        heads([{'head_id': 'IXI/002', 'seed': 42, 'radius_mm': 6}]),
        heads([{'head_id': 'ixi002', 'seed': 42, 'radius_mm': 6}], conductivity_scenario='skull_x2'),
        _input([42], cases=[{'head_id': 'ixi002', 'seed': 42, 'radius_mm': 6}]),
    ):
        with pytest.raises(StudyError):
            normalize_study_input(invalid)


def test_empirical_summaries_use_case_weights_and_retain_rejected_trials_and_failure_counts():
    simple = empirical_summary([0, 10, 20, 30])
    assert simple['n'] == 4 and simple['median'] == 15 and simple['p90'] == 27
    assert abs(simple['p10'] - 3) <= 4 * EPSILON
    assert empirical_summary([None, math.nan]) == EMPTY

    def trial(value, status='completed'):
        return {'status': status, 'field_relative': value, 'fixed_estimator_field_relative': value,
                'sensitivity_tail': value}

    a = summarize_study_case({'nominal': {'field_relative': 0.5}, 'trials': [trial(0), trial(0), trial(0), trial(0)]})
    rejected = trial(None, 'geometry_rejected')
    b = summarize_study_case({'nominal': {'field_relative': 1}, 'trials': [trial(100), rejected, rejected, rejected]})
    cases = [
        {'status': 'completed', 'request': {'radius_mm': 3}, 'summary': a},
        {'status': 'completed', 'request': {'radius_mm': 3}, 'summary': b},
        {'status': 'failed', 'request': {'radius_mm': 3}},
        {'status': 'cancelled', 'request': {'radius_mm': 3}},
    ]
    before = jsjson.stringify(cases)
    summary = aggregate_study('grid_displacements', cases)
    # Do not pool five trials and weight the first case four times.
    assert summary['groups'][0]['trial_case_medians']['field_relative']['median'] == 50
    assert (summary['completed_cases'], summary['failed_cases'], summary['cancelled_cases']) == (2, 1, 1)
    assert b['rejected_trials'] == 3 and len(b['trials']) == 4
    assert jsjson.stringify(cases) == before


# --- JavaScript semantics ------------------------------------------------------------------------------------------

def test_the_aggregation_follows_javascript_numbers_and_members():
    # Doubles in Node's order: an overflowing difference gives Infinity or NaN, which JSON writes as null.
    assert jsjson.stringify(empirical_summary([1e308, -1e308])) == '{"n":2,"median":null,"p10":null,"p90":null}'
    assert empirical_summary([-1e308, 0, 1e308])['p10'] == -1e308 + 1e308 * ((3 - 1) * 0.1)
    assert jsjson.stringify(empirical_summary([-0.0])) == '{"n":1,"median":0,"p10":0,"p90":0}'
    # Python ints are doubles: a huge one is Infinity, and booleans are not numbers.
    assert empirical_summary([10**400, True, 2**53 + 1, 1])['n'] == 2
    assert empirical_summary([2**53 + 1, 2**53])['median'] == 2.0**53
    # Radii: -0 groups with 0 (Set stores +0); undefined sorts last; a member of null throws as in V8.
    cases = [{'request': {'radius_mm': r}, 'status': 'pending'} for r in (10, -0.0, 3, 0)]
    groups = aggregate_study('noise_seeds', [*cases, {'request': {}, 'status': 'x'}])['groups']
    assert [(g.get('radius_mm', 'undefined'), g['case_count']) for g in groups] == [
        (0, 2), (3, 1), (10, 1), ('undefined', 1)]
    assert math.copysign(1, groups[0]['radius_mm']) == 1
    assert 'radius_mm' not in jsjson.parse(jsjson.stringify(groups[-1]))
    for bad in ([None], [{}], [{'request': None}]):
        with pytest.raises(TypeError):
            aggregate_study('noise_seeds', bad)
    with pytest.raises(TypeError):
        aggregate_study('noise_seeds', [{'request': {'radius_mm': 3}, 'status': 'completed', 'summary': {}}])
    for bad in (None, {}, {'trials': 'x'}, {'trials': [None]}):
        with pytest.raises(TypeError):
            summarize_study_case(bad)
    # Absent members are left out of the clone as JSON.stringify leaves them out.
    summary = summarize_study_case({'trials': [{'status': 'completed', 'field_relative': UNDEFINED,
                                                'xyz': [1, UNDEFINED]}]})
    assert 'nominal' not in summary and summary['trials'] == [{'status': 'completed', 'xyz': [1, None]}]
    assert js_stringify(summary) == jsjson.stringify(summary)


def test_summaries_copy_their_inputs():
    result = {'nominal': {'field_relative': 0.5, 'nested': {'a': [1, 2]}},
              'trials': [{'status': 'completed', 'field_relative': 1}]}
    before = copy.deepcopy(result)
    summary = summarize_study_case(result)
    summary['nominal']['nested']['a'].append(3)
    summary['trials'][0]['status'] = 'x'
    assert result == before
    deep = current = []
    for _ in range(5000):
        current.append([])
        current = current[0]
    assert len(jsjson.stringify(summarize_study_case({'nominal': deep, 'trials': []}))) > 10000


# --- Node parity -------------------------------------------------------------------------------------------------

def _fixed_cases() -> list[dict]:
    a, b = _result([0, 0, 0, 0]), _result([100, None, None, None])
    big = [(i * 7919) % 1000 / 7 for i in range(1000)]
    empirical = {
        'known': [30, 0, 20, 10], 'specials': [None, UNDEFINED, math.nan, math.inf], 'single': [.125, None],
        'ordered': [0, 10, 20, 30], 'nullNaN': [None, math.nan], 'empty': [], 'minusZero': [-0.0], 'zeros': [-0.0, 0.0],
        'zerosReversed': [0.0, -0.0], 'overflow': [1e308, -1e308], 'overflowThree': [-1e308, 0, 1e308],
        'extremes': [1.7976931348623157e308, -1.7976931348623157e308, 0], 'subnormals': [5e-324, -5e-324, 0, -0.0],
        'two': [1, 2], 'three': [1, 2, 3], 'tenths': [round(0.1 * i, 1) for i in range(1, 12)],
        'mixed': ['1', True, None, [], {}, 2, '', [3], -math.inf], 'huge': [2**53, 2**53 + 2, 2**53 + 1],
        'big': big, 'object': {}, 'string': 'abc', 'null': None, 'arrayLike': {'length': 1, '0': 1},
        **{f'size{n}': [(i * 37) % n / 3 for i in range(n)] for n in (21, 31, 51, 71, 101)},
    }
    summarize = {
        'null': None, 'empty': {}, 'trialsString': {'trials': 'x'}, 'trialsObject': {'trials': {}},
        'trialNull': {'trials': [None]}, 'trialUndefined': {'trials': [UNDEFINED]}, 'noNominal': {'trials': []},
        'nullNominal': {'nominal': None, 'trials': []},
        'oddTrials': {'nominal': {'1': 1, 'b': 2, '0': 0}, 'trials': [
            0, 'x', [], {'status': 'completed'}, {'status': 'completed', 'sensitivity_tail': -0.0}]},
        'a': a, 'b': b,
        'undefinedMembers': {'nominal': {'x': UNDEFINED}, 'trials': [
            {'status': 'completed', 'field_relative': UNDEFINED, 'xyz': [1, UNDEFINED, math.nan]}]},
        'protoKey': {'nominal': {'__proto__': 1, 'field_relative': 2}, 'trials': [
            {'__proto__': {'status': 'completed'}, 'status': 'completed', 'field_relative': 3}]},
        'statuses': {'nominal': {}, 'trials': [{'status': s, 'field_relative': i} for i, s in enumerate(
            ['completed', 'geometry_rejected', 'Completed', 'completed ', None, 1, True, 'failed'])]},
    }
    weighted = [
        {'request': {'radius_mm': 3}, 'status': 'completed', '$result': a},
        {'request': {'radius_mm': 3}, 'status': 'completed', '$result': b},
        {'request': {'radius_mm': 3}, 'status': 'failed', 'summary': None, 'error': {'code': 'child_failed'}},
        {'request': {'radius_mm': 3}, 'status': 'cancelled', 'summary': None},
        {'request': {'radius_mm': 6}, 'status': 'pending', 'summary': None},
    ]
    summary = {'nominal': {'field_relative': 1},
               'trial_metrics': {metric: {'median': 1, 'p10': 0} for metric in TRIAL_METRICS}}

    def radii(*values):
        return [{'request': {} if value is UNDEFINED else {'radius_mm': value}, 'status': 'completed',
                 'summary': summary} for value in values]

    aggregate = {
        'weighted': {'protocol': 'grid_displacements', 'cases': weighted},
        'allRejected': {'protocol': 'grid_displacements', 'cases': [
            {'request': {'radius_mm': 10}, 'status': 'completed', '$result': _result([None] * 4)}]},
        'headsEmpty': {'protocol': 'heads', 'cases': []}, 'noiseEmpty': {'protocol': 'noise_seeds', 'cases': []},
        'noProtocol': {'cases': []}, 'numberProtocol': {'protocol': 1, 'cases': []},
        'nullCase': {'protocol': 'heads', 'cases': [None]}, 'noRequest': {'protocol': 'heads', 'cases': [{}]},
        'nullRequest': {'protocol': 'heads', 'cases': [{'request': None}]},
        'emptySummary': {'protocol': 'heads', 'cases': [{'request': {'radius_mm': 6}, 'status': 'completed',
                                                         'summary': {}}]},
        'noTrialMetrics': {'protocol': 'heads', 'cases': [{'request': {'radius_mm': 6}, 'status': 'completed',
                                                           'summary': {'nominal': {}, 'trial_metrics': {}}}]},
        'nullNominal': {'protocol': 'heads', 'cases': [{'request': {'radius_mm': 6}, 'status': 'completed',
                                                        'summary': {'nominal': None, 'trial_metrics': {}}}]},
        'falsySummaries': {'protocol': 'noise_seeds', 'cases': [
            {'request': {'radius_mm': 6}, 'status': 'completed', 'summary': value} for value in (0, '', False, None)]},
        'radiusOrder': {'protocol': 'grid_displacements', 'cases': radii(10, 3, 6, -0.0, 0, 3.0, 10)},
        'radiusUndefined': {'protocol': 'grid_displacements', 'cases': radii(UNDEFINED, 6, UNDEFINED, 3)},
        'radiusNaNPair': {'protocol': 'grid_displacements', 'cases': radii('x', 3)},
        'radiusNaNPairReversed': {'protocol': 'grid_displacements', 'cases': radii(3, 'x')},
        'radiusObjects': {'protocol': 'grid_displacements', 'cases': radii({'a': 1}, [6])},
        'radiusConvertible': {'protocol': 'grid_displacements',
                              'cases': radii('3', 3, None, True, ' 6 ', [], '0x10', 1e21, -1e308)},
        'radiusOwnToString': {'protocol': 'grid_displacements', 'cases': radii({'toString': 1}, 3)},
        'statuses': {'protocol': 'noise_seeds', 'cases': [
            *({'request': {'radius_mm': 6}, 'status': status} for status in (*CASE_STATUSES, '', None, 'COMPLETED', 1)),
            {'request': {'radius_mm': 6}}]},
    }
    cases = [{'id': f'fixed-empirical-{k}', 'op': 'empirical', 'text': to_text(v)} for k, v in empirical.items()]
    cases += [{'id': f'fixed-summarize-{k}', 'op': 'summarize', 'text': to_text(v)} for k, v in summarize.items()]
    cases += [{'id': f'fixed-aggregate-{k}', 'op': 'aggregate', 'text': to_text(v)} for k, v in aggregate.items()]
    return cases


@pytest.fixture(scope='module')
def aggregation_cases(tmp_path_factory):
    cases = _fixed_cases() + random_aggregate_cases(0x5701e5, 1500)
    return cases, run_driver('aggregate', cases, tmp_path_factory.mktemp('studies-aggregate'))


@needs_node
def test_aggregation_equals_node(aggregation_cases):
    cases, node = aggregation_cases
    assert len(node['cases']) == len(cases)
    mismatches = [case['id'] for case in cases
                  if node_form(python_aggregate(case)) != node_form(node['by_id'][case['id']])]
    assert mismatches == []


@needs_node
def test_the_aggregation_cases_reach_every_outcome(aggregation_cases):
    _, node = aggregation_cases
    results = node['cases']
    failures = {case['id'] for case in results if not case['ok']}
    assert {'fixed-empirical-object', 'fixed-empirical-string', 'fixed-summarize-null', 'fixed-aggregate-nullCase',
            'fixed-aggregate-emptySummary', 'fixed-aggregate-radiusOwnToString'} <= failures
    assert all(case['name'] == 'TypeError' for case in results if not case['ok'])
    texts = [case['json'] for case in results if case['ok']]
    assert sum('null' in text for text in texts) > 100 and sum('"median":null' not in text for text in texts) > 100
    # A random case result without `nominal` makes its completed case throw; nearly every random case returns.
    random_failed = [case for case in results if case['id'].startswith('random-') and not case['ok']]
    assert 0 < len(random_failed) < 50


# --- check-robustness-studies.mjs: the store and the service (server.workspace_studies) -------------------------

def _run(body, *args):
    """Runs a study test on its own event loop, bounded so that a failure fails instead of hanging."""
    require('pydantic')
    return asyncio.run(asyncio.wait_for(body(*args), 180))


class _Gate:
    """A ``before_write`` hook: raises ``error`` while it is set (the check's ``blocked`` flag)."""

    def __init__(self):
        self.error = None

    def __call__(self):
        if self.error is not None:
            raise self.error


def _hold_admission(adapter):
    """``beforeNewWork`` that, once ``block`` is set, signals ``entered`` and waits for ``gate``."""
    state = {'block': False, 'entered': asyncio.Event(), 'gate': asyncio.Event()}

    async def before_new_work():
        if state['block']:
            state['entered'].set()
            await asyncio.wait_for(state['gate'].wait(), 60)
    adapter.before_new_work = before_new_work
    return state


async def _raises(awaitable, status=None, kind=Exception, match=None):
    with pytest.raises(kind, match=match) as caught:
        await awaitable
    if status is not None:
        assert caught.value.status == status
    return caught.value


def test_create_and_reads_launch_no_jobs_completed_cases_archive_exact_original_caches_and_survive_receipt_cleanup(
        tmp_path):
    async def body():
        async with StudyFixture(tmp_path) as f:
            created = await f.service.create(study_input())
            id = created['study']['id']
            assert created['study']['status'] == 'draft'
            assert f.scheduler.tasks == []
            await f.service.get(id)
            await f.service.list()
            assert f.scheduler.tasks == []
            originals = [f.adapter.cache_path(entry['key']).read_text(encoding='utf-8')
                         for entry in created['study']['cases']]
            await f.service.start(id)
            await f.flush()
            done = (await f.service.get(id))['study']
            assert done['status'] == 'completed' and len(done['cases']) == 2
            assert done['aggregation']['completed_cases'] == 2
            assert 'owner' not in done
            f.scheduler.tasks = []
            exported = await f.store.present(id, True)
            for entry in exported['cases']:
                assert entry['cache_json'] == originals[int(entry['index'])]
                assert entry['source_sha256'] == hashlib.sha256(entry['cache_json'].encode('utf-8')).hexdigest()
                assert f.adapter.cache_path(entry['key']).read_text(encoding='utf-8') == originals[int(entry['index'])]
            # The snapshot is the cache's exact bytes, not a re-serialization.
            snapshot = Path(f.store.directory) / id / 'snapshots' / (exported['cases'][0]['source_sha256'] + '.json')
            assert snapshot.read_text(encoding='utf-8') == originals[0] and originals[0].endswith('}\n')
            assert f.adapter.starts == 0
    _run(body)


def test_a_cross_head_study_binds_one_identity_per_head_then_creates_and_runs_every_head(tmp_path):
    async def body():
        async with StudyFixture(tmp_path) as f:
            study = heads_input('ernie_xh', 'ixi002')
            for request in normalize_study_input(study)['requests']:
                f.seed_cache(request)
            created = await f.service.create(study)
            id = created['study']['id']
            assert created['study']['status'] == 'draft'
            record = await f.store.load(id)
            identities = [entry['identity_sha256'] for entry in record['cases']]
            assert identities == [jsjson.sha256_hex({'protocol': FIXTURE_PROTOCOL, 'version': 1, 'head_id': head})
                                  for head in ('ernie_xh', 'ixi002')]
            assert record['identity_sha256'] == jsjson.sha256_hex(identities)
            assert all('identity_sha256' not in entry for entry in created['study']['cases'])
            await f.service.start(id)
            await f.flush()
            done = (await f.service.get(id))['study']
            assert done['status'] == 'completed'
            assert [[entry['request']['head_id'], entry['status']] for entry in done['cases']] == [
                ['ernie_xh', 'completed'], ['ixi002', 'completed']]
            assert done['aggregation']['interpretation'] == 'cross_head_empirical_cases'
            exported = await f.store.present(id, True)
            assert all('identity_sha256' not in entry for entry in exported['study']['cases'])
            assert f.adapter.starts == 0

            def seed(value):
                value['cases'][1]['request']['seed'] = 43

            def borrowed(value):
                value['cases'][1]['identity_sha256'] = identities[0]

            def dropped(value):
                del value['cases'][1]['identity_sha256']
            for change in (seed, borrowed, dropped):
                await _raises(f.store.update(id, change), 409, StudyError)
    _run(body)


def test_non_head_studies_still_refuse_case_identities_that_differ_while_preparing(tmp_path):
    async def body():
        async with StudyFixture(tmp_path) as f:
            prepare = f.adapter.prepare

            async def changing(raw):
                prepared = await prepare(raw)
                f.adapter.version = 2
                return prepared
            f.adapter.prepare = changing
            error = await _raises(f.service.create(study_input()), 409, StudyError)
            assert error.message == 'Scientific identity changed while preparing the study.'
            assert (await f.service.list())['studies'] == []
    _run(body)


def test_non_head_study_records_keep_the_single_shared_identity_older_servers_verify(tmp_path):
    async def body():
        async with StudyFixture(tmp_path) as f:
            id = (await f.service.create(study_input()))['study']['id']
            record = await f.store.load(id)
            assert record['identity_sha256'] == jsjson.sha256_hex({'protocol': FIXTURE_PROTOCOL, 'version': 1})
            assert all('identity_sha256' not in entry for entry in record['cases'])

            def everywhere(value):
                for entry in value['cases']:
                    entry['identity_sha256'] = value['identity_sha256']
            await _raises(f.store.update(id, everywhere), 409, StudyError)
    _run(body)


def test_legacy_records_written_without_per_case_identities_still_load_and_run(tmp_path):
    async def body():
        async with StudyFixture(tmp_path) as f:
            id = (await f.service.create(study_input()))['study']['id']
            current = await f.store.load(id)
            # Exactly the case fields an older server writes.
            legacy = {**current, 'cases': [{'index': entry['index'], 'request': entry['request'], 'key': entry['key'],
                                            'status': 'pending', 'receipt_id': None, 'error': None}
                                           for entry in current['cases']]}
            (Path(f.store.directory) / id / 'study.json').write_text(jsjson.stringify(legacy), encoding='utf-8')
            assert jsjson.stringify(await f.store.load(id)) == jsjson.stringify(legacy)
            await f.service.start(id)
            await f.flush()
            assert (await f.service.get(id))['study']['status'] == 'completed'
    _run(body)


def test_concurrent_starts_admit_at_most_one_parent_study(tmp_path):
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            a = (await f.service.create(study_input((42,))))['study']['id']
            b = (await f.service.create(study_input((43,))))['study']['id']
            outcomes = await asyncio.gather(f.service.start(a), f.service.start(b), return_exceptions=True)
            await f.flush()
            assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
            rejected = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
            assert len(rejected) == 1 and rejected[0].status == 429
            assert rejected[0].message == 'This browser already has an active study.'
            assert len(f.service.active) == 1
            assert len(f.scheduler.tasks) == 1
            # While it runs, no other study of the workspace starts either.
            await _raises(f.service.start(b), 429, StudyError)
    _run(body)


def test_cancel_during_case_preparation_prevents_a_later_child_admission(tmp_path):
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            gate = asyncio.Event()
            f.adapter.hold = gate
            await f.service.start(id)
            await f.service.cancel(id)
            gate.set()
            f.adapter.hold = None
            await f.flush()
            assert (await f.service.get(id))['study']['status'] == 'cancelled'
            assert f.scheduler.tasks == []
    _run(body)


class _HoldWrite:
    """A ``before_write`` hook that, once ``armed``, holds the next write until ``release`` (signalling
    ``entered``)."""

    def __init__(self):
        self.armed = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self):
        if self.armed:
            self.armed = False
            self.entered.set()
            await asyncio.wait_for(self.release.wait(), 60)


async def _until(condition):
    while not condition():
        await asyncio.sleep(0.001)


def test_a_cancel_waiting_behind_a_case_admission_write_keeps_the_case_from_submitting(tmp_path):
    # Node's authorize checks stopRequested too: a cancel whose write waits behind the case's admission write.
    async def body():
        hold = _HoldWrite()
        async with StudyFixture(tmp_path, cached=False, before_write=hold) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            prepare = asyncio.Event()
            f.adapter.hold = prepare
            await f.service.start(id)
            hold.armed = True
            prepare.set()
            f.adapter.hold = None
            await asyncio.wait_for(hold.entered.wait(), 60)
            cancel = asyncio.ensure_future(f.service.cancel(id))
            await asyncio.wait_for(_until(lambda: id in f.service.stop_requested), 60)
            hold.release.set()
            await asyncio.wait_for(cancel, 60)
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'cancelled' and study['cases'][0]['status'] == 'cancelled'
            assert 'operation_id' not in study['cases'][0]
            assert f.scheduler.tasks == []
    _run(body)


def test_cancel_inside_original_queue_write_admission_prevents_receipt_creation(tmp_path):
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            admission = _hold_admission(f.adapter)
            id = (await f.service.create(study_input((42,))))['study']['id']
            admission['block'] = True
            await f.service.start(id)
            await asyncio.wait_for(admission['entered'].wait(), 60)
            await f.service.cancel(id)
            admission['gate'].set()
            await f.flush()
            assert (await f.service.get(id))['study']['status'] == 'cancelled'
            assert f.scheduler.tasks == []
    _run(body)


def test_cancelling_a_queued_case_cancels_its_receipt(tmp_path):
    # Node's site keeps the receipt queued for its other browsers; a workspace receipt has no other owner (R1).
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            await f.service.start(id)
            await f.flush()
            task = f.scheduler.tasks[0]
            assert task['status'] == 'queued'
            await f.service.cancel(id)
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'cancelled' and study['cases'][0]['status'] == 'cancelled'
            assert task['status'] == 'cancelled' and len(f.scheduler.tasks) == 1
    _run(body)


def test_restart_pauses_the_parent_and_a_get_never_accepts_more_cases_explicit_resume_reconciles_owned_receipts(
        tmp_path):
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            id = (await f.service.create(study_input()))['study']['id']
            await f.service.start(id)
            await f.flush()
            assert len(f.scheduler.tasks) == 1
            await f.restart()
            assert (await f.service.get(id))['study']['status'] == 'paused_recovery'
            await f.service.list()
            await f.flush()
            assert len(f.scheduler.tasks) == 1
            await f.service.start(id, True)
            await f.flush()
            assert len(f.scheduler.tasks) == 1
            assert (await f.service.get(id))['study']['cases'][0]['receipt_id'] == f.scheduler.tasks[0]['id']
    _run(body)


def test_an_uncertain_interrupted_submission_is_retained_without_blindly_resubmitting_it(tmp_path):
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']

            def interrupted(record):
                record['status'] = 'running'
                record['cases'][0].update({'status': 'submitting', 'operation_id': str(uuid.uuid4())})
            await f.store.update(id, interrupted)
            await f.restart()
            await f.service.start(id, True)
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'completed_with_failures'
            assert study['cases'][0]['status'] == 'failed_uncertain'
            assert study['cases'][0]['error']['code'] == 'submission_outcome_unknown'
            assert f.scheduler.tasks == []
    _run(body)


def test_changed_scientific_identity_fails_pending_cases_without_new_receipts(tmp_path):
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            id = (await f.service.create(study_input()))['study']['id']
            f.adapter.version = 2
            await f.service.start(id)
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'completed_with_failures'
            assert all(entry['error']['code'] == 'scientific_identity_changed' for entry in study['cases'])
            assert f.scheduler.tasks == []
    _run(body)


def test_archive_checks_exact_cache_binding_and_rejects_corrupted_or_symlinked_snapshots(tmp_path):
    async def body():
        async with StudyFixture(tmp_path) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            await f.service.start(id)
            await f.flush()
            entry = (await f.service.get(id))['study']['cases'][0]
            path = Path(f.store.directory) / id / 'snapshots' / (entry['source_sha256'] + '.json')
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            await _raises(f.service.get(id), 409, StudyError, 'checksum')
            path.unlink()
            path.symlink_to(f.adapter.cache_path(entry['key']))
            await _raises(f.service.get(id), 409)
    _run(body)


def test_metadata_total_byte_and_unsafe_root_limits_fail_before_scientific_submission(tmp_path):
    # Node's site also caps the studies of a browser (429); the workspace has no study count cap (R1).
    async def body():
        async with StudyFixture(tmp_path / 'first') as f:
            await f.service.create(study_input((42,)))
            await f.service.create(study_input((43,)))
            assert len((await f.service.list())['studies']) == 2 and f.scheduler.tasks == []
            async with StudyFixture(tmp_path / 'second', limits={'metadataBytes': 10}) as second:
                await _raises(second.service.create(study_input((42,))), 413, StudyError)
                assert second.scheduler.tasks == []
            async with StudyFixture(tmp_path / 'third', limits={'totalBytes': 10}) as third:
                await _raises(third.service.create(study_input((42,))), 507, StudyError)
                assert third.scheduler.tasks == []
            async with StudyFixture(tmp_path / 'fourth') as fourth:
                Path(fourth.store.directory).symlink_to(f.root)
                error = await _raises(fourth.service.create(study_input((42,))), 409)
                assert error.message == 'Project directory is not a regular directory.'
                assert not (f.root / '5d5d').exists() and sorted(p.name for p in f.root.iterdir()) == ['results']
    _run(body)


def test_default_admission_is_unchanged_while_expected_key_and_cancellation_guards_act_before_receipts(tmp_path):
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            prepared = await f.adapter.prepare(normalize_study_input(study_input((42,)))['requests'][0])
            kind = 'design-evaluation'
            await _raises(f.scheduler.submit(kind, prepared['request'], False, 'd' * 64), 409)
            error = await _raises(f.scheduler.submit(kind, prepared['request'], False, prepared['key'],
                                                     lambda: False))
            assert error.study_admission_cancelled is True
            assert f.scheduler.tasks == []
            legacy = await f.scheduler.submit(kind, prepared['request'])
            assert legacy['job']['key'] == prepared['key'] and legacy['job']['status'] == 'queued'
            assert f.scheduler.tasks[0]['request'] == prepared['request']
    _run(body)


async def _chunks(*parts):
    for part in parts:
        yield part


def test_http_study_requests(tmp_path):
    # The middleware half of "HTTP study writes require origin/token and reads isolate signed browser sessions":
    # the origin and token checks are the routes'; signed browser sessions are dropped (R1).
    async def body():
        gate = _Gate()
        async with StudyFixture(tmp_path, before_write=gate) as f:
            handle, json_type = f.service.handle, 'application/json'

            def post(path, value, content_type=json_type):
                return handle('POST', path, content_type=content_type, body=jsjson.stringify(value).encode('utf-8'))

            assert await handle('GET', '/api/robustness-studies') == (200, {'studies': []}, {})
            status, value, _ = await post('/api/robustness-studies', study_input((42,), design={**STUDY_DESIGN,
                                                                                                  'unit': 'm'}))
            assert status == 400 and isinstance(value['error'], str) and value['error'] != UNAVAILABLE
            status, created, _ = await post('/api/robustness-studies', study_input((42,)))
            assert status == 201 and created['study']['status'] == 'draft'
            id = created['study']['id']
            base = f'/api/robustness-studies/{id}'
            assert (await handle('GET', base))[0] == 200
            assert await post(f'{base}/start', {'extra': True}) == (
                400, {'error': 'Study control requests require an empty JSON object.'}, {})
            for control in ([], None, 0, 'x'):
                assert (await post(f'{base}/start', control))[0] == 400
            assert f.scheduler.tasks == []
            # Middleware refusals, with Node's statuses and messages.
            assert await handle('GET', '/api/robustness-studies', query=True) == (
                400, {'error': 'Study API queries are not supported.'}, {})
            assert await handle('PUT', base) == (405, {'error': 'Unsupported study method.'}, {})
            assert await handle('DELETE', '/api/robustness-studies') == (405, {'error': 'Unsupported study method.'},
                                                                         {})
            assert await post('/api/robustness-studies', study_input((42,)), 'text/plain') == (
                415, {'error': 'JSON is required.'}, {})
            assert await post('/api/robustness-studies', study_input((42,)), None) == (
                415, {'error': 'JSON is required.'}, {})
            for large in (_chunks(b'{', b' ' * 65535, b'}'), b'{' + b' ' * 65535 + b'}'):
                assert await handle('POST', '/api/robustness-studies', content_type=json_type, body=large) == (
                    413, {'error': 'Study request is too large.'}, {})
            assert await handle('POST', '/api/robustness-studies', content_type='application/json; charset=utf-8',
                                body=b'{"protocol":') == (400, {'error': 'Invalid study JSON.'}, {})
            for path in ('/api/robustness-studies/x', '/api/robustness-studies/' + id.upper(), base + '/',
                         '/api/robustness-studies/5d5d0000-0000-4000-8000-000000000001',
                         '/api/robustness-studies/00000000-0000-0000-0000-000000000000/export'):
                assert await handle('GET', path) == (404, {'error': 'Study not found.'}, {}), path
            for method, path in (('GET', base + '/start'), ('POST', base + '/export'), ('POST', base)):
                assert await handle(method, path, content_type=json_type, body=b'{}') == (
                    405, {'error': 'Unsupported study operation.'}, {}), path
            status, exported, _ = await handle('GET', base + '/export')
            assert status == 200 and exported['schema'] == 'eeg-robustness-study-export/1'
            assert exported['cases'][0]['cache'] is None and exported['cases'][0]['cache_json'] is None
            # A resource refusal shows its message and Retry-After; any other failure is not described.
            gate.error = ResourceError('The service is stopping.', 503, retry_after=30)
            assert await post('/api/robustness-studies', study_input((43,))) == (
                503, {'error': 'The service is stopping.'}, {'Retry-After': '30'})
            gate.error = None

            async def broken(raw):
                raise RuntimeError('/private/path detail')
            f.adapter.prepare = broken
            assert await post('/api/robustness-studies', study_input((43,))) == (500, {'error': UNAVAILABLE}, {})
            # A pump that fails pauses the study for inspection, without describing the failure either.
            assert (await post(f'{base}/start', {}))[0] == 200
            await f.flush()
            status, value, _ = await handle('GET', base)
            assert status == 200 and value['study']['status'] == 'paused_resource'
            assert value['study']['last_error'] == {
                'code': 'study_storage_unavailable',
                'message': 'Study processing paused. Inspect the recorded cases before resuming.'}
    _run(body)


def test_stopping_during_preparation_does_not_label_the_unsubmitted_case_as_cancelled(tmp_path):
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            gate = asyncio.Event()
            f.adapter.hold = gate
            await f.service.start(id)
            f.service.stop()
            gate.set()
            f.adapter.hold = None
            await f.flush()
            assert (await f.service.get(id))['study']['cases'][0]['status'] == 'pending'
            assert f.scheduler.tasks == []
            await f.restart()
            assert (await f.service.get(id))['study']['status'] == 'paused_recovery'
            await f.service.start(id, True)
            await f.flush()
            assert len(f.scheduler.tasks) == 1
    _run(body)


def test_stopping_inside_queue_admission_preserves_a_confirmed_unaccepted_case_for_recovery(tmp_path):
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            admission = _hold_admission(f.adapter)
            id = (await f.service.create(study_input((42,))))['study']['id']
            admission['block'] = True
            await f.service.start(id)
            await asyncio.wait_for(admission['entered'].wait(), 60)
            f.service.stop()
            admission['gate'].set()
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'paused_recovery'
            assert study['cases'][0]['status'] == 'pending'
            assert f.scheduler.tasks == []
    _run(body)


def test_cancel_remains_usable_after_an_original_receipt_was_removed(tmp_path):
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            await f.service.start(id)
            await f.flush()
            f.scheduler.tasks = []
            await f.service.cancel(id)
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'cancelled'
            assert study['cases'][0]['status'] == 'cancelled'
            assert study['cases'][0]['error']['code'] == 'subscription_removed'
    _run(body)


def test_a_running_case_whose_receipt_was_removed_is_cancelled_and_the_study_moves_on(tmp_path):
    # The pump's 404 branch (the service.mjs poll after "survive receipt cleanup"): the next case is submitted.
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            id = (await f.service.create(study_input()))['study']['id']
            await f.service.start(id)
            await f.flush()
            assert len(f.scheduler.tasks) == 1
            f.scheduler.tasks = []
            f.service.run(id)  # the poll
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'running'
            assert study['cases'][0]['status'] == 'cancelled'
            assert study['cases'][0]['error'] == {
                'code': 'subscription_removed', 'message': 'This browser no longer owns the child subscription.'}
            assert study['cases'][1]['status'] == 'queued' and len(f.scheduler.tasks) == 1
    _run(body)


def test_error_answers_show_only_safe_messages_and_failures_keep_500_units():
    class Leaky(Exception):
        status = 409
        message = '/private/path'
    assert error_answer(Leaky()) == (409, {'error': UNAVAILABLE}, {})
    assert error_answer(RuntimeError('x')) == (500, {'error': UNAVAILABLE}, {})
    assert error_answer(StudyError('Study not found.', 404)) == (404, {'error': 'Study not found.'}, {})
    assert error_answer(ResourceError('Busy', 503, 7)) == (503, {'error': 'Busy'}, {'Retry-After': '7'})
    assert error_answer(ResourceError('Busy', 503, 0)) == (503, {'error': 'Busy'}, {})
    assert safe_failure('child_failed', 'm' * 600) == {'code': 'child_failed', 'message': 'm' * 500}
    assert safe_failure('child_failed', '\U0001f600' * 300)['message'] == '\U0001f600' * 250
    assert safe_failure('child_failed', None)['message'] == 'null'


def test_cancelling_remaining_work_preserves_an_already_failed_child_and_its_reason(tmp_path):
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            id = (await f.service.create(study_input()))['study']['id']
            await f.service.start(id)
            await f.flush()
            task = f.scheduler.tasks[0]
            task['status'] = 'failed'
            task['message'] = 'Original failed solver case'
            await f.service.cancel(id)
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'cancelled'
            assert study['cases'][0]['status'] == 'failed'
            assert study['cases'][0]['error'] == {'code': 'child_failed', 'message': 'Original failed solver case'}
            assert study['cases'][1]['status'] == 'cancelled'
    _run(body)


def test_quota_blocked_startup_keeps_existing_research_readable_and_waits_for_explicit_recovery(tmp_path):
    async def body():
        gate = _Gate()
        async with StudyFixture(tmp_path, cached=False, before_write=gate) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            await f.service.start(id)
            await f.flush()
            gate.error = StudyError('Study quota', 507)
            await f.restart()
            assert (await f.service.get(id))['study']['status'] == 'paused_recovery'
            assert len((await f.service.list())['studies']) == 1
            assert len(f.scheduler.tasks) == 1
            gate.error = None
            await f.service.start(id, True)
            await f.flush()
            assert len(f.scheduler.tasks) == 1
    _run(body)


def test_cancel_clears_a_transient_resource_pause_and_terminal_studies_cannot_resume(tmp_path):
    async def body():
        gate = _Gate()
        async with StudyFixture(tmp_path, cached=False, before_write=gate) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            hold = asyncio.Event()
            f.adapter.hold = hold
            await f.service.start(id)
            gate.error = ResourceError('Resource blocked', 503)
            hold.set()
            f.adapter.hold = None
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'paused_resource'
            assert study['last_error'] == {
                'code': 'resource_unavailable',
                'message': 'Study processing paused. Inspect the recorded cases before resuming.'}
            gate.error = None
            await f.service.cancel(id)
            await f.flush()
            assert (await f.service.get(id))['study']['status'] == 'cancelled'
            assert (await f.service.list())['studies'][0]['status'] == 'cancelled'
            await _raises(f.service.start(id, True), 409, StudyError)
            assert f.scheduler.tasks == []
    _run(body)


def test_resource_admission_blocks_new_work_but_cannot_block_cancellation_of_queued_work(tmp_path):
    async def body():
        gate = _Gate()
        async with StudyFixture(tmp_path, cached=False, before_write=gate) as f:
            id = (await f.service.create(study_input()))['study']['id']
            await f.service.start(id)
            await f.flush()
            gate.error = ResourceError('Resource blocked', 503)
            await f.service.cancel(id)
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'cancelled' and study['cancel_requested'] is True
            assert all(entry['status'] == 'cancelled' for entry in study['cases'])
            assert len(f.scheduler.tasks) == 1 and f.scheduler.tasks[0]['status'] == 'cancelled'
            error = await _raises(f.service.create(study_input((44,))), 503, ResourceError)
            assert error.resource_safe is True
    _run(body)


def test_cancelling_recovery_pauses_clears_the_directory_overlay_and_never_revives_a_cancelled_parent(tmp_path):
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            await f.service.start(id)
            await f.flush()
            await f.restart()
            await f.service.cancel(id)
            await f.flush()
            assert (await f.service.list())['studies'][0]['status'] == 'cancelled'
            await _raises(f.service.start(id, True), 409, StudyError)
    _run(body)


def test_a_cancelling_record_without_cancel_requested_is_never_revived_by_recovery_or_resume(tmp_path):
    # Node's records may say cancelling without cancel_requested (validate allows it to be absent): the recovery
    # pause, and a resume of a record whose pause was refused, both keep the parent cancelling.
    async def body():
        for name, quota in (('paused', None), ('refused', StudyError('Study quota', 507))):
            gate = _Gate()
            async with StudyFixture(tmp_path / name, cached=False, before_write=gate) as f:
                id = (await f.service.create(study_input()))['study']['id']
                await f.service.start(id)
                await f.flush()

                def legacy(value):
                    value['status'] = 'cancelling'
                    value.pop('cancel_requested', None)
                await f.service.store.control_update(id, legacy)
                gate.error = quota
                await f.restart()
                assert (await f.service.get(id))['study']['status'] == 'paused_recovery'
                record = await f.service.store.load(id)
                if quota is None:
                    assert (record['status'], record.get('cancel_requested')) == ('paused_recovery', True)
                else:
                    assert (record['status'], 'cancel_requested' in record) == ('cancelling', False)
                gate.error = None
                await f.service.start(id, True)
                await f.flush()
                study = (await f.service.get(id))['study']
                assert (study['status'], study['cancel_requested']) == ('cancelling', True), name
                assert [entry['status'] for entry in study['cases']] == ['queued', 'pending']
                await f.service.cancel(id)
                await f.flush()
                study = (await f.service.get(id))['study']
                assert study['status'] == 'cancelled'
                assert all(entry['status'] == 'cancelled' for entry in study['cases'])
                assert len(f.scheduler.tasks) == 1 and f.scheduler.tasks[0]['status'] == 'cancelled'
    _run(body)


def test_cancelled_completion_waits_for_original_result_archive_without_authorizing_later_cases(tmp_path):
    async def body():
        gate = _Gate()
        async with StudyFixture(tmp_path, cached=False, before_write=gate) as f:
            id = (await f.service.create(study_input()))['study']['id']
            await f.service.start(id)
            await f.flush()
            task = f.scheduler.tasks[0]
            f.seed_cache(task['request'])
            task['status'] = 'completed'
            gate.error = ResourceError('Resource blocked', 503)
            await f.service.cancel(id)
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'paused_resource'
            assert study['cancel_requested'] is True
            assert study['cases'][1]['status'] == 'cancelled'
            assert len(f.scheduler.tasks) == 1
            await f.restart()
            study = (await f.service.get(id))['study']
            assert study['cancel_requested'] is True
            assert study['status'] == 'paused_recovery'
            gate.error = None
            await f.service.start(id, True)
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'cancelled'
            assert [entry['status'] for entry in study['cases']] == ['completed', 'cancelled']
            assert len(f.scheduler.tasks) == 1
            assert study['aggregation']['completed_cases'] == 1
    _run(body)


def test_explicit_parent_recovery_checks_a_complete_interrupted_cache_before_marking_its_existing_receipt_failed(
        tmp_path):
    async def scenario(name):
        async with StudyFixture(tmp_path / name, cached=False) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            await f.service.start(id)
            await f.flush()
            task = f.scheduler.tasks[0]
            original = None
            if name != 'missing':
                original = f.seed_cache(task['request'])
                if name == 'corrupt':
                    original['path'].write_text(original['bytes'].replace('0.81', '0.82', 1), encoding='utf-8')
            task['status'] = 'failed'
            task['message'] = 'Actual solver failed' if name == 'ordinary_solver_failure' else INTERRUPTED

            def running(record):
                record['cases'][0]['status'] = 'running'
            await f.store.update(id, running)
            await f.restart()
            await f.service.start(id, True)
            await f.flush()
            study = (await f.service.get(id))['study']
            assert len(f.scheduler.tasks) == 1 and f.adapter.starts == 0
            if name == 'valid':
                assert study['status'] == 'completed' and study['cases'][0]['status'] == 'completed'
                assert (await f.store.present(id, True))['cases'][0]['cache_json'] == original['bytes']
            else:
                assert study['status'] == 'completed_with_failures' and study['cases'][0]['status'] == 'failed'
                assert study['cases'][0]['error']['code'] == (
                    'child_failed' if name == 'ordinary_solver_failure' else 'scientific_cache_invalid')

    async def body():
        for name in ('valid', 'missing', 'corrupt', 'ordinary_solver_failure'):
            await scenario(name)
    _run(body)


# --- The workspace's own cases (no Node site) ----------------------------------------------------------------------

def test_a_cache_linked_by_a_leftover_publish_temporary_is_archived_and_any_other_link_fails_the_case(tmp_path):
    """B16's publish (``records.publish_cache``) links ``cache.json.<uuid4>.tmp`` to ``cache.json`` and removes it
    after a directory sync, so a crash in between leaves it as a second link, which the lookup ignores. The study
    archives that cache, as Node archives its renamed one; a link of another name or in another directory still fails
    the case (Node's ``nlink`` check)."""
    def leftover(path):
        return path.parent / f'cache.json.{uuid.uuid4()}.tmp'

    def other(path):
        return path.parent / f'other.json.{uuid.uuid4()}.tmp'

    async def body():
        for name, links, archived in (
                ('leftover', [leftover], True),
                ('other-name', [other], False),
                ('other-directory', [lambda path: leftover(path.parent)], False),
                ('leftover-and-other', [leftover, other], False),
                ('unrelated-temporary-and-other', [other], False)):
            async with StudyFixture(tmp_path / name) as f:
                id = (await f.service.create(study_input((42,))))['study']['id']
                path = f.adapter.cache_path((await f.store.load(id))['cases'][0]['key'])
                if name.startswith('unrelated'):
                    leftover(path).write_bytes(path.read_bytes())  # another publish's temporary: its own file
                for link in links:
                    os.link(path, link(path))
                await f.service.start(id)
                await f.flush()
                case = (await f.service.get(id))['study']['cases'][0]
                assert f.adapter.starts == 0
                if archived:
                    assert case['status'] == 'completed', name
                    exported = (await f.store.present(id, True))['cases'][0]['cache_json']
                    assert exported == path.read_text(encoding='utf-8')
                else:
                    assert (case['status'], case['error']['code']) == ('failed', 'scientific_cache_invalid'), name
    _run(body)


def test_a_cache_read_between_the_link_and_the_unlink_of_its_publish_is_the_cases(tmp_path, monkeypatch):
    """The same with the real publish: a read while ``cache.json`` still has the temporary's link (``nlink`` 2) gets
    the cache's bytes, and the study then archives them."""
    from eeglayoutlab.jobs import records

    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            entry = (await f.store.load(id))['cases'][0]
            key, text = cache_text(entry['request'])
            path = f.adapter.cache_path(key)
            path.parent.mkdir(parents=True)
            sync, seen = records._sync_directory, {}

            def window(directory):
                seen['links'] = path.stat().st_nlink
                seen['bytes'] = f.service.cache_bytes(entry)
                sync(directory)
            monkeypatch.setattr(records, '_sync_directory', window)
            assert records.RecordStore(str(f.root)).publish_cache('design', key, jsjson.parse(text)) is None
            monkeypatch.undo()
            published = path.read_bytes()
            assert seen == {'links': 2, 'bytes': published} and path.stat().st_nlink == 1
            await f.service.start(id)
            await f.flush()
            assert (await f.service.get(id))['study']['status'] == 'completed'
            assert (await f.store.present(id, True))['cases'][0]['cache_json'] == published.decode('utf-8')
    _run(body)


def test_a_maintenance_refusal_defers_the_pending_case_until_an_explicit_resume(tmp_path):
    # Node's "maintenance rejection retains a pending case until an explicit resume" (R6) on the workspace queue's
    # cache-only mode, which refuses new work the same way (admission_rejected).
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            f.scheduler.cache_only = True
            await f.service.start(id)
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['status'] == 'paused_resource' and study['cases'][0]['status'] == 'pending'
            assert study['last_error']['code'] == 'submission_deferred'
            assert f.scheduler.tasks == []
            f.scheduler.cache_only = False
            await f.service.get(id)
            await f.flush()
            assert f.scheduler.tasks == []
            await f.service.start(id, True)
            await f.flush()
            study = (await f.service.get(id))['study']
            assert study['cases'][0]['status'] == 'queued' and len(f.scheduler.tasks) == 1
    _run(body)


def test_a_resource_refusal_of_new_work_pauses_the_case_and_reads_never_retry_it(tmp_path):
    # Node's "a resource refusal pauses the pending case and GET does not retry it" (R2): a refusal raised while the
    # queue admits the case (a resource-safe error) defers it as Node's ResourceGate refusal does.
    async def body():
        async with StudyFixture(tmp_path, cached=False) as f:
            refusing = {'on': True}

            async def before_new_work():
                if refusing['on']:
                    raise ResourceError('Resource blocked', 503)
            f.adapter.before_new_work = before_new_work
            id = (await f.service.create(study_input((42,))))['study']['id']
            await f.service.start(id)
            await f.flush()
            assert (await f.service.get(id))['study']['status'] == 'paused_resource'
            assert f.scheduler.tasks == []
            refusing['on'] = False
            await f.service.get(id)
            await f.flush()
            assert f.scheduler.tasks == []
            await f.service.start(id, True)
            await f.flush()
            assert len(f.scheduler.tasks) == 1
    _run(body)


def test_reads_and_list_cover_every_study_of_the_workspace(tmp_path):
    # One local user: records carry the local owner and are read whatever owner they carry (R1).
    async def body():
        async with StudyFixture(tmp_path) as f:
            id = (await f.service.create(study_input((42,))))['study']['id']
            path = Path(f.store.directory) / id / 'study.json'
            record = jsjson.parse(path.read_text(encoding='utf-8'))
            assert record['owner'] == LOCAL_OWNER and 'network' not in record
            path.write_text(jsjson.stringify({**record, 'owner': 'b' * 64}), encoding='utf-8')
            assert (await f.service.get(id))['study']['id'] == id
            assert [row['id'] for row in (await f.service.list())['studies']] == [id]
            await f.service.start(id)
            await f.flush()
            assert (await f.service.get(id))['study']['status'] == 'completed'
    _run(body)


def test_a_failed_recovery_refuses_every_request(tmp_path):
    # Node's initialization promise: a recovery that fails (an unexpected entry) is raised by every later request.
    async def body():
        async with StudyFixture(tmp_path) as f:
            directory = Path(f.store.directory)
            directory.mkdir()
            (directory / 'stray').write_text('x', encoding='utf-8')
            f.service.stop()
            await f.flush()
            f.service.close()
            f.service = RobustnessStudyService(f.scheduler, str(f.root), poll_seconds=3600,
                                               store=StudyStore(str(directory)))
            for call in (f.service.ready(), f.service.list(), f.service.get('5d5d0000-0000-4000-8000-000000000001'),
                         f.service.create(study_input((42,)))):
                error = await _raises(call, 409, StudyError)
                assert error.message == 'Study directory needs inspection.'
            assert await f.service.handle('GET', '/api/robustness-studies') == (
                409, {'error': 'Study directory needs inspection.'}, {})
            (directory / 'stray').unlink()
            await _raises(f.service.ready(), 409, StudyError)
    _run(body)


# --- server.workspace_files ------------------------------------------------------------------------------------------

def test_workspace_files_refuse_links_hard_links_and_files_that_change(tmp_path, monkeypatch):
    from eeglayoutlab.server import workspace_files
    from eeglayoutlab.server.workspace_files import ProjectError, WorkspaceFiles

    base = Path(os.path.realpath(tmp_path))
    files = WorkspaceFiles(str(base / 'parent' / 'studies'))
    files.ready()
    assert (base / 'parent' / 'studies').is_dir()
    assert stat.S_IMODE((base / 'parent' / 'studies').stat().st_mode) == 0o700 & ~_umask()
    files.ready()  # memoized
    blocker = base / 'blocker'
    blocker.write_bytes(b'')
    failing = WorkspaceFiles(str(blocker / 'studies'))
    with pytest.raises(OSError) as first:
        failing.ready()
    blocker.unlink()
    with pytest.raises(OSError) as again:
        failing.ready()  # Node's rejected initialization promise is kept
    assert again.value is first.value and not blocker.exists()
    with pytest.raises(ProjectError) as caught:
        files.record_directory('5D5D0000-0000-4000-8000-000000000001')
    assert (caught.value.status, caught.value.message) == (400, 'Invalid project identifier.')
    record = base / 'parent' / 'studies' / '5d5d0000-0000-4000-8000-000000000001'
    with pytest.raises(OSError) as missing:
        files.record_directory(record.name)
    assert missing.value.code == 'ENOENT'
    (base / 'elsewhere').mkdir()
    record.symlink_to(base / 'elsewhere')
    for path in (str(record), str(base / 'parent' / 'studies' / '..' / 'studies')):
        with pytest.raises(ProjectError) as caught:
            files.safe_directory(path)
        assert (caught.value.status, caught.value.message) == (409, 'Project directory is not a regular directory.')
    record.unlink()
    record.mkdir()
    assert files.record_directory(record.name) == str(record)
    plain = record / 'study.json'
    plain.write_bytes(b'{"a":1}')
    assert files.file(str(plain), 7) == b'{"a":1}'
    (record / 'link.json').symlink_to(plain)
    os.link(plain, record / 'hard.json')
    for path, maximum in ((record / 'link.json', 100), (plain, 100), (plain, 6), (record, 100)):
        with pytest.raises(ProjectError) as caught:
            files.file(str(path), maximum)
        assert (caught.value.status, caught.value.message) == (409, 'Project file failed integrity checks.')
    assert files.file(str(plain), 100, 2) == b'{"a":1}'  # a caller that counted the second link accepts it
    (record / 'hard.json').unlink()
    unlinked = os.stat_result((*os.lstat(plain)[:3], 0, *os.lstat(plain)[4:]))  # APFS, during a rename over it
    monkeypatch.setattr(workspace_files.nodefs, 'lstat', lambda path: unlinked)
    with pytest.raises(ProjectError) as caught:
        files.file(str(plain), 100, 2)
    assert (caught.value.status, caught.value.message) == (409, 'Project file failed integrity checks.')
    monkeypatch.undo()
    with pytest.raises(OSError) as missing:
        files.file(str(record / 'absent.json'), 100)
    assert missing.value.code == 'ENOENT'
    # The descriptor must still be the file lstat saw, and the bytes read must stay within the bound.
    other = record / 'other.json'
    other.write_bytes(b'{}')
    real_lstat = workspace_files.nodefs.lstat
    monkeypatch.setattr(workspace_files.nodefs, 'lstat', lambda path: real_lstat(str(other)))
    with pytest.raises(ProjectError) as caught:
        files.file(str(plain), 100)
    assert (caught.value.status, caught.value.message) == (409, 'Project file changed while reading.')
    shrunk = os.stat_result((*real_lstat(str(plain))[:6], 1, *real_lstat(str(plain))[7:]))
    monkeypatch.setattr(workspace_files.nodefs, 'lstat', lambda path: shrunk)
    monkeypatch.setattr(workspace_files.os, 'fstat', lambda fd: shrunk)
    with pytest.raises(ProjectError) as caught:
        files.file(str(plain), 5)
    assert (caught.value.status, caught.value.message) == (413, 'Project file is too large.')
    monkeypatch.undo()
    # A failed initialization is kept and raised again, as Node's rejected promise is.
    (base / 'blocked').write_bytes(b'')
    broken = WorkspaceFiles(str(base / 'blocked' / 'studies'))
    with pytest.raises(OSError) as first:
        broken.ready()
    (base / 'blocked').unlink()
    with pytest.raises(OSError) as second:
        broken.ready()
    assert second.value is first.value


def _umask():
    mask = os.umask(0)
    os.umask(mask)
    return mask


def test_workspace_file_writes_run_one_at_a_time_in_call_order():
    from eeglayoutlab.server.workspace_files import ProjectError, WorkspaceFiles

    async def body():
        files = WorkspaceFiles('/nonexistent/studies')
        order = []

        def operation(name, delay, error=None):
            async def run():
                order.append(f'start {name}')
                await asyncio.sleep(delay)
                order.append(f'end {name}')
                if error is not None:
                    raise error
                return name
            return run
        first = asyncio.ensure_future(files.serialize(operation('a', 0.05)))
        second = asyncio.ensure_future(files.serialize(operation('b', 0, ValueError('b failed'))))
        third = asyncio.ensure_future(files.serialize(operation('c', 0)))
        await asyncio.sleep(0)
        assert files.pending_writes == 3
        # A cancelled caller does not cancel its operation: the chain keeps its order.
        first.cancel()
        results = await asyncio.gather(first, second, third, return_exceptions=True)
        assert isinstance(results[0], asyncio.CancelledError) and isinstance(results[1], ValueError)
        assert results[2] == 'c'
        await files.flush()
        assert order == ['start a', 'end a', 'start b', 'end b', 'start c', 'end c'] and files.pending_writes == 0
        files.close()
        with pytest.raises(ProjectError) as caught:
            await files.serialize(operation('d', 0))
        assert (caught.value.status, caught.value.message) == (503, 'Project store is stopping.')
    asyncio.run(asyncio.wait_for(body(), 60))


def test_study_times_are_the_iso_strings_date_parse_reads():
    # Python's subset of Date.parse: ISO date-time strings only (module docstring of server.workspace_studies).
    for text in ('2026-11-25T00:00:00.000Z', '2026', '2026-11', '2026-02-31', '2026-11-25T24:00',
                 '+275760-09-13T00:00Z', '-271821-04-20T00:00:00Z', '2026-11-25T10:20:30.123456+14:00',
                 '+002026-11-25', '+275760-09-12T09:00', '-271821-04-20T15:00'):
        assert iso_date_finite(text), text
    # A local time is finite here only within 15 hours of the bound on every host's offset.
    for text in ('+275760-09-12T09:00:00.001', '+275760-09-13T00:00', '-271821-04-20T14:59:59.999'):
        assert not iso_date_finite(text), text
    for text in ('2026-13-01', '2026-11-32', '2026-11-25T24:00:01', '-000000-01-01', '+275760-09-13T00:00:00.001Z',
                 '2026-11-25T10:60', '2026-11-25 10:00', 'Tue, 01 Jan 2030 00:00:00 GMT', '', 2026, None,
                 '2026-11-25T10:20:30.Z', '٢026-11-25'):
        assert not iso_date_finite(text), text


# --- Node parity of the store, the identity and the export --------------------------------------------------------

ID = [f'5d5d0000-0000-4000-8000-{n:012d}' for n in range(10)]
TMP = '0a0a0a0a-0000-4000-8000-000000000000'


def _b64(value):
    return base64.b64encode(value.encode('utf-8') if isinstance(value, str) else value).decode('ascii')


def _set(*pairs):
    return {'set': [[path, value] for path, value in pairs]}


def _store_cases() -> dict[str, tuple[dict, list]]:
    """Named step lists of the driver's ``store`` mode, each with its limits."""
    noise = prepared_for(study_input())
    other = prepared_for(study_input((44, 45)))
    k0, k1 = (cache_text(entry['request'])[1] for entry in noise['cases'])
    sha0 = hashlib.sha256(k0.encode('utf-8')).hexdigest()
    heads = prepared_for(heads_input('ixi002', 'a'))
    head_caches = [cache_text(entry['request'])[1] for entry in heads['cases']]
    grid = prepared_for(study_input((42,), protocol='grid_displacements',
                                    cases=[{'seed': 42, 'radius_mm': 3}, {'seed': 42, 'radius_mm': 10}]))
    grid_cache = cache_text(grid['cases'][0]['request'])[1]
    names = [f'E{i}' for i in range(64)]
    first = ID[1]
    updates = [
        _set((['title'], 'Renamed'), (['notes'], 'n' * 2000)), _set((['notes'], 'n' * 2001)),
        _set((['title'], ' 　 ')), _set((['title'], 't' * 201)), _set((['title'], '\U0001f600' * 100)),
        _set((['title'], '\U0001f600' * 101)), _set((['status'], 'running'), (['cases', 0, 'status'], 'submitting')),
        _set((['cases', 1, 'operation_id'], 'x')), _set((['cases', 1, 'operation_id'], TMP)),
        _set((['cancel_requested'], 1)), _set((['cancel_requested'], False)),
        _set((['created_at'], '2026-02-30T00:00Z')),
        _set((['created_at'], '2026-13-01')), _set((['created_at'], 'Tue, 01 Jan 2030 00:00:00 GMT'.replace(' ', '_'))),
        _set((['annotation'], {'other': 1})), _set((['annotation'], {'electrode_names': names})),
        _set((['annotation'], {'electrode_names': names[:3]})), _set((['annotation'], 'ab')), _set((['annotation'], 5)),
        _set((['annotation'], None)), _set((['annotation'], {})), _set((['network'], 'a' * 64)),
        _set((['network'], 'A' * 64)), {'delete': [['cases', 0, 'source_sha256']]},
        _set((['cases', 0, 'source_bytes'], 1)),
        _set((['cases', 0, 'source_bytes'], 1.5)), _set((['identity_sha256'], 'B' * 64)),
        _set((['cases', 0, 'identity_sha256'], 'a' * 64)), _set((['cases', 0, 'receipt_id'], ID[9])),
        _set((['cases', 0, 'receipt_id'], 'x')), _set((['cases', 0, 'annotation_id'], 'xyz')),
        _set((['cases', 0, 'annotation_id'], 'a' * 64)), _set((['cases', 0, 'index'], 1)),
        _set((['cases', 1, 'request', 'seed'], 42)), _set((['cases', 1, 'request', 'radius_mm'], 3)),
        _set((['design', 'name'], 'Other')), _set((['protocol'], 'grid_displacements')), _set((['protocol'], 'heads')),
        _set((['status'], 'archived')), _set((['schema'], 'eeg-robustness-study/2')), _set((['cases'], [])),
        _set((['owner'], 'b' * 64)), _set((['owner'], 7)), _set((['cases', 0, 'error'], {'code': 'x', 'message': 'y'})),
        _set((['extra'], {'a': 1})), _set((['last_error'], None)), _set((['revision'], 2 ** 53)),
        _set((['revision'], 1.5)), _set((['id'], ID[9])), _set((['cases', 1, 'status'], 'done')),
        _set((['cases', 1, 'status'], 'completed')), _set((['cases', 0, 'request', 'extra'], 1)),
        {'delete': [['cases', 1, 'receipt_id']]}, {'delete': [['notes']]},
    ]
    lifecycle = [
        ['ids'], ['usage'], ['all'], ['load', first], ['present', first, False],
        ['update', first, _set((['title'], 'x'))],
        ['archive', first, 0, _b64(k0)],
        ['create', noise], ['ids'], ['usage'], ['load', first], ['all'], ['present', first, False],
        ['present', first, True], ['load', 'nope'], ['load', first.upper()], ['load', ID[3]], ['load', 7],
        ['update', 'nope', {}],
        ['archive', first, 0, _b64(k0)], ['archive', first, 0, _b64(k0)], ['archive', first, 1, _b64(k0)],
        ['archive', first, 5, _b64(k1)], ['archive', first, -1, _b64(k1)], ['archive', first, 1.5, _b64(k1)],
        ['archive', first, 1, _b64('{}')], ['archive', first, 1, _b64('null')], ['archive', first, 1, _b64('not json')],
        ['archive', first, 1, _b64(k1.replace('0.81', '0.82', 1))], ['archive', first, 1, _b64('﻿' + k1)],
        ['archive', first, 1, _b64(k1)], ['present', first, True], ['snapshot', first, 0], ['snapshot', first, 1],
        ['usage'],
        *[['update', first, change] for change in updates],
        ['control', first, _set((['cancel_requested'], True), (['status'], 'cancelling'))], ['load', first],
        ['before', 'resource'], ['create', noise], ['update', first, _set((['title'], 'blocked'))],
        ['archive', first, 0, _b64(k0)], ['control', first, _set((['title'], 'control'))],
        ['before', 'quota'], ['create', noise], ['before', None],
        ['create', other], ['ids'], ['all'], ['usage'],
        ['create', heads], ['archive', ID[3], 0, _b64(head_caches[0])], ['archive', ID[3], 1, _b64(head_caches[0])],
        ['update', ID[3], _set((['cases', 1, 'identity_sha256'], heads['cases'][0]['identity_sha256']))],
        ['update', ID[3], _set((['cases', 1, 'request', 'seed'], 43))],
        ['update', ID[3], _set((['cases', 1, 'request', 'head_id'], 'ixi002'))], ['present', ID[3], True],
        ['create', grid], ['archive', ID[4], 0, _b64(grid_cache)], ['present', ID[4], True],
        ['update', ID[4], _set((['cases', 1, 'request', 'radius_mm'], 6))],
        ['create', {**noise, 'cases': noise['cases'][:1] * 2}], ['create', {**noise, 'title': ''}],
        ['create', {**noise, 'identity_sha256': 'x'}], ['ids'],
    ]
    refusals = [
        ['create', noise], ['archive', first, 0, _b64(k0)], ['create', other],
        ['write', 'junk.json', _b64('{}')], ['ids'], ['usage'], ['all'], ['load', first], ['create', noise],
        ['rm', 'junk.json'],
        ['mkdir', 'snapshots'], ['ids'], ['usage'], ['rm', 'snapshots'],
        ['mkdir', ID[9]], ['ids'], ['all'], ['load', ID[9]], ['usage'], ['rm', ID[9]],
        ['write', f'{first}/notes.txt', _b64('x')], ['usage'], ['load', first], ['rm', f'{first}/notes.txt'],
        ['write', f'{first}/snapshots/notes.txt', _b64('x')], ['archive', first, 1, _b64(k1)], ['usage'],
        ['present', first, False], ['rm', f'{first}/snapshots/notes.txt'],
        ['write', f'{first}/study.json.{TMP}.tmp', _b64('{}')], ['usage'], ['rm', f'{first}/study.json.{TMP}.tmp'],
        ['write', f'{first}/study.json.{TMP.upper()}.tmp', _b64('{}')], ['usage'],
        ['rm', f'{first}/study.json.{TMP.upper()}.tmp'],
        ['mkdir', f'{first}/other'], ['usage'], ['rm', f'{first}/other'],
        ['mkdir', f'{first}/{ID[8]}'], ['usage'], ['rm', f'{first}/{ID[8]}'],
        ['link', f'{first}/study.json', f'{first}/snapshots/{"a" * 64}.json'], ['load', first], ['usage'],
        ['update', first, {}], ['archive', first, 1, _b64(k1)], ['rm', f'{first}/snapshots/{"a" * 64}.json'],
        ['rename', f'{first}/study.json', f'{first}/real.json'], ['symlink', 'real.json', f'{first}/study.json'],
        ['load', first], ['usage'], ['ids'], ['update', first, {}], ['rm', f'{first}/study.json'],
        ['rename', f'{first}/real.json', f'{first}/study.json'], ['load', first],
        ['write', f'{first}/snapshots/{sha0}.json', _b64(k0 + ' ')], ['present', first, False],
        ['snapshot', first, 0], ['archive', first, 0, _b64(k0)],
        ['write', f'{first}/snapshots/{sha0}.json', _b64(k0.replace('0.9', '0.8', 1))], ['present', first, False],
        ['rm', f'{first}/snapshots/{sha0}.json'], ['present', first, False], ['archive', first, 0, _b64(k0)],
        ['present', first, True],
        ['copy', f'{first}/study.json', '../study-backup.json'],
        ['write', f'{first}/study.json', _b64('{')], ['load', first], ['all'], ['ids'], ['present', first, False],
        ['write', f'{first}/study.json', _b64('{"schema":"eeg-robustness-study/1"}')], ['load', first],
        ['write', f'{first}/study.json', _b64('﻿{}')], ['load', first],
        ['write', f'{first}/study.json', _b64(b'\xff')], ['load', first],
        ['rm', f'{first}/study.json'], ['load', first], ['all'], ['copy', f'{ID[2]}/study.json', f'{first}/study.json'],
        ['load', first], ['all'], ['rm', f'{first}/study.json'],
        ['copy', '../study-backup.json', f'{first}/study.json'], ['load', first],
        ['chmod', f'{first}/study.json', 0], ['load', first], ['all'], ['chmod', f'{first}/study.json', 0o600],
        ['symlink', first, ID[9]], ['ids'], ['load', ID[9]], ['usage'], ['rm', ID[9]],
        ['rename', first, ID[7]], ['symlink', ID[7], first], ['load', first], ['ids'], ['rm', first],
        ['rename', ID[7], first], ['load', first],
        ['rm', f'{first}/snapshots'], ['present', first, False], ['archive', first, 1, _b64(k1)],
        ['symlink', '.', f'{first}/snapshots'], ['archive', first, 1, _b64(k1)], ['present', first, True],
        ['rm', f'{first}/snapshots'], ['mkdir', f'{first}/snapshots'], ['archive', first, 0, _b64(k0)],
        ['rm', first], ['load', first], ['all'], ['usage'], ['ids'],
    ]
    files = [['create', noise]]
    files += [['write', f'{first}/snapshots/{i:064x}.json', _b64('{}')] for i in range(36)]
    files += [['archive', first, 0, _b64(k0)], ['usage'], ['rm', f'{first}/snapshots/{0:064x}.json'],
              ['archive', first, 0, _b64(k0)], ['archive', first, 1, _b64(k1)], ['archive', first, 0, _b64(k0)],
              ['present', first, True]]
    return {
        'lifecycle': ({}, lifecycle),
        'refusals': ({}, refusals),
        'files': ({}, files),
        'metadata': ({'metadataBytes': 3000}, [['create', noise], ['ids'], ['all'], ['usage'], ['create', noise],
                                               ['ids']]),
        'metadata-update': ({'metadataBytes': 4000}, [['create', noise],
                                                      ['update', first, _set((['notes'], 'x' * 600))],
                                                      ['load', first]]),
        'total': ({'totalBytes': 5000}, [['create', noise], ['archive', first, 0, _b64(k0)], ['create', other],
                                         ['update', first, _set((['title'], 'Renamed'))], ['usage']]),
        'study-bytes': ({'studyBytes': 12000}, [['create', noise], ['archive', first, 0, _b64(k0)],
                                                ['archive', first, 1, _b64(k1)], ['usage']]),
        'case-bytes': ({'caseBytes': 9000}, [['create', noise], ['archive', first, 0, _b64(k0)]]),
        'missing-root': ({}, [['ids'], ['usage'], ['all'], ['load', first], ['present', first, True],
                              ['update', first, {}], ['archive', first, 0, _b64(k0)], ['create', noise], ['ids']]),
        'root-file': ({}, [['write', '.', _b64('x')], ['ids'], ['load', first], ['create', noise], ['usage']]),
        'root-link': ({}, [['mkdir', '../elsewhere'], ['symlink', 'elsewhere', '.'], ['ids'], ['create', noise],
                           ['load', first], ['usage']]),
        'missing-parent': ({}, [['ids'], ['usage'], ['create', noise]]),
    }


@pytest.fixture(scope='module')
def store_parity(tmp_path_factory):
    require('pydantic')
    scratch = Path(os.path.realpath(tmp_path_factory.mktemp('studies-store')))
    cases = _store_cases()

    def items(side):
        def directory(name):
            return str(scratch / side / name / ('absent/studies' if name == 'missing-parent' else 'studies'))
        return [{'id': name, 'limits': limits, 'steps': steps, 'directory': directory(name)}
                for name, (limits, steps) in cases.items()]
    for side in ('node', 'python'):
        for item in items(side):
            Path(item['directory']).parent.mkdir(parents=True, exist_ok=True) if 'absent' not in item['directory'] \
                else Path(item['directory']).parent.parent.mkdir(parents=True, exist_ok=True)
    try:
        node = run_driver('store', items('node'), scratch, owner=LOCAL_OWNER)
        python = {item['id']: python_store(item) for item in items('python')}
        yield cases, node, python
    finally:
        for side in ('node', 'python'):  # the refusal cases leave unreadable modes behind otherwise
            for path in (scratch / side).rglob('*'):
                if not path.is_symlink():
                    path.chmod(0o700)


@needs_node
def test_store_equals_node(store_parity):
    cases, node, python = store_parity
    for name, (_, steps) in cases.items():
        expected, actual = node['by_id'][name], python[name]
        differing = [(i, steps[i][0]) for i, (a, b) in enumerate(zip(expected['records'], actual['records']))
                     if node_outcome(a) != b]
        assert differing == [], name
        assert len(expected['records']) == len(actual['records']) == len(steps)
        assert expected['tree'] == actual['tree'], name


@needs_node
def test_the_store_cases_reach_every_refusal(store_parity):
    _, node, _ = store_parity
    messages = {(record['status'], record['message']) for case in node['cases'] for record in case['records']
                if not record['ok'] and record['safe']}
    assert messages >= {
        (404, 'Study not found.'), (409, 'Study metadata failed integrity checks.'),
        (409, 'Study scientific cache identity mismatch.'), (409, 'Study directory needs inspection.'),
        (409, 'Study storage contains an unsafe entry.'), (409, 'Study storage needs inspection.'),
        (413, 'Study metadata exceeds the size limit.'), (507, 'Study storage capacity reached.'),
        (404, 'Study case not found.'),
        (413, 'Study case snapshot is too large.'), (507, 'Study snapshot file limit reached.'),
        (409, 'Study snapshot path is unsafe.'), (409, 'Study snapshot checksum mismatch.'),
        (507, 'Study snapshot capacity reached.'), (409, 'Project directory is not a regular directory.'),
        (409, 'Project file failed integrity checks.'), (503, 'Resource blocked'), (507, 'Study quota'),
    }
    # 'Study metadata path is unsafe.' cannot be reached: usage() refuses a link or a second link to study.json first.
    codes = {record['code'] for case in node['cases'] for record in case['records'] if not record['ok']}
    assert {'ENOENT', 'EACCES'} <= codes
    assert sum(record['ok'] for case in node['cases'] for record in case['records']) > 100


def _identity_cases(base: Path) -> list[dict]:
    roots = {name: design_root(base / 'roots' / name, **ROOTS[name])
             for name in ('base', 'table', 'full', 'simnibs', 'odd', 'broken-no_pointer', 'broken-escape',
                          'broken-bank_sha', 'broken-head_sha', 'broken-scenario_sha', 'broken-table_sha',
                          'broken-head_dir', 'broken-admission_bom', 'broken-table_corrupt')}
    inputs = {
        'noise': study_input((42, 43, 44)),
        'grid': study_input((42,), protocol='grid_displacements',
                            cases=[{'seed': 42, 'radius_mm': 3}, {'seed': 42, 'radius_mm': 10}]),
        'heads': heads_input(*HEADS), 'heads-unknown': heads_input('ixi002', 'zz'),
        'scenario': study_input((42,), conductivity_scenario='skull_x2'),
        'scenario-unknown': study_input((42,), conductivity_scenario='skull_x3'),
        'names': study_input((42,), design={**STUDY_DESIGN, 'electrode_names': [f'E{i}' for i in range(64)]}),
        'noise-model': study_input((42,), noise_model={'kind': 'spatial', 'rho': 0.5, 'length_mm': 20.0}),
        'invalid': study_input((42, 42)),
    }
    return [{'id': f'{root}-{name}', 'root': path, 'python': 'python3', 'input': raw, 'study_id': ID[1]}
            for root, path in roots.items() for name, raw in inputs.items()]


@needs_node
def test_identity_equals_node(tmp_path):
    # Case keys, identity_sha256 (B18: the shared identity, or the hash of the heads' identities) and the draft's
    # bytes from Node's own scientific context and study service on synthetic roots.
    require('pydantic')
    base = Path(os.path.realpath(tmp_path))
    cases = _identity_cases(base)
    now = '2026-11-25T00:00:00.000Z'
    node = run_driver('identity', [{**case, 'base': str(base / 'node' / case['id'])} for case in cases], base,
                      owner=LOCAL_OWNER, now=now)
    differing = [case['id'] for case in cases
                 if node_outcome(node['by_id'][case['id']]) != python_identity(
                     {**case, 'base': str(base / 'python' / case['id'])}, now)]
    assert differing == []
    results = node['by_id']
    assert all(result['tasks'] == 0 for result in results.values())
    assert sum(result['ok'] for result in results.values()) >= 20
    heads = results['full-heads']
    record = jsjson.parse(heads['bytes'])
    assert heads['ok'] and len(record['cases']) == len(HEADS)
    assert record['identity_sha256'] == jsjson.sha256_hex([entry['identity_sha256'] for entry in record['cases']])
    assert len({entry['identity_sha256'] for entry in record['cases']}) == len(HEADS)
    noise = jsjson.parse(results['full-noise']['bytes'])
    assert all('identity_sha256' not in entry for entry in noise['cases'])
    assert results['full-invalid']['status'] == 400 and results['full-invalid']['safe']


def _export_cases() -> dict[str, tuple[list, list]]:
    """Named scenarios of the driver's ``export`` mode: ``(caches, steps)``."""
    requests = normalize_study_input(study_input((42, 43, 44)))['requests']
    caches = [list(cache_text(request)) for request in requests]
    head_requests = normalize_study_input(heads_input('ixi002', 'a'))['requests']
    named = study_input((42,), design={**STUDY_DESIGN, 'electrode_names': [f'E{i}' for i in range(64)]})
    return {
        'complete': (caches[:2], [['create', study_input()], ['list'], ['get'], ['start', False], ['flush'], ['get'],
                                  ['list'], ['tasks'], ['export'], ['start', True], ['cancel'], ['export']]),
        'partial-cancel': (caches[:2], [['create', study_input((42, 43, 44))], ['start', False], ['flush'], ['get'],
                                        ['tasks'], ['export'], ['cancel'], ['flush'], ['tasks'], ['export'], ['list'],
                                        ['start', True]]),
        'heads': ([list(cache_text(request)) for request in head_requests],
                  [['create', heads_input('ixi002', 'a')], ['start', False], ['flush'], ['export']]),
        'names': ([list(cache_text(normalize_study_input(named)['requests'][0]))],
                  [['create', named], ['start', False], ['flush'], ['tasks'], ['export']]),
        'symlinked-cache': (caches[:2], [['create', study_input()], ['symlink_key', caches[0][0]], ['start', False],
                                         ['flush'], ['export']]),
        'restart-uncertain': ([], [['create', study_input()], ['case', None, {'status': 'running'}],
                                   ['case', 0, {'status': 'submitting', 'operation_id': ID[9]}], ['restart'], ['get'],
                                   ['list'], ['start', False], ['start', True], ['flush'], ['tasks'], ['export']]),
        'restart-reconcile': ([], [['create', study_input()], ['start', False], ['flush'], ['restart'], ['get'],
                                   ['start', True], ['flush'], ['cache', caches[0][0], caches[0][1]],
                                   ['task', 0, {'status': 'completed'}], ['restart'], ['start', True], ['flush'],
                                   ['tasks'], ['export']]),
        'interrupted': ([], [['create', study_input((42,))], ['start', False], ['flush'],
                             ['cache', caches[0][0], caches[0][1]],
                             ['task', 0, {'status': 'failed', 'message': INTERRUPTED}],
                             ['case', 0, {'status': 'running'}], ['restart'], ['start', True], ['flush'], ['export']]),
        'identity-changed': (caches[:1], [['create', study_input()], ['version', 2], ['start', False], ['flush'],
                                          ['tasks'], ['export']]),
        'failed-child': ([], [['create', study_input()], ['start', False], ['flush'],
                              ['task', 0, {'status': 'failed', 'message': 'Original failed solver case'}], ['cancel'],
                              ['flush'], ['export']]),
        'removed-receipt': ([], [['create', study_input((42,))], ['start', False], ['flush'],
                                 ['task', 0, {'kind': 'other'}], ['flush'], ['get'], ['restart'], ['start', True],
                                 ['flush'], ['export']]),
    }


@needs_node
def test_export_equals_node(tmp_path):
    # The eeg-robustness-study-export/1 file, every reply on the way and the final study.json byte for byte, with a
    # pinned clock and pinned study, operation and receipt identifiers.
    require('pydantic')
    base = Path(os.path.realpath(tmp_path))
    scenarios = _export_cases()

    def items(side):
        out = []
        for name, (caches, steps) in scenarios.items():
            folder = base / side / name
            (folder / 'root').mkdir(parents=True)
            (folder / 'workspace').mkdir(parents=True)
            out.append({'id': name, 'root': str(folder / 'root'), 'queue': str(folder / 'workspace/.eeglayoutlab'),
                        'studies': str(folder / 'workspace/studies'), 'clock': {'start': 1795564800000, 'step': 1500},
                        'caches': caches, 'steps': steps})
        return out
    node = run_driver('export', items('node'), base, owner=LOCAL_OWNER)
    for item in items('python'):
        expected, actual = node['by_id'][item['id']], python_export(item)
        differing = [(i, item['steps'][i][0]) for i, (a, b) in enumerate(zip(expected['records'], actual['records']))
                     if node_outcome(a) != b]
        assert differing == [], item['id']
        assert (expected['study'], expected['snapshots']) == (actual['study'], actual['snapshots']), item['id']
    exported = {name: jsjson.parse(next(record['value'] for record in reversed(node['by_id'][name]['records'])
                                        if record['ok'] and record['value'] and '-export/1' in record['value']))
                for name in scenarios}
    assert [entry['status'] for entry in exported['complete']['study']['cases']] == ['completed', 'completed']
    assert all(entry['cache_json'] for entry in exported['complete']['cases'])
    assert [entry['status'] for entry in exported['partial-cancel']['study']['cases']] == [
        'completed', 'completed', 'cancelled']
    assert exported['symlinked-cache']['study']['cases'][0]['error']['code'] == 'scientific_cache_invalid'
    assert exported['restart-uncertain']['study']['cases'][0]['status'] == 'failed_uncertain'
    assert exported['interrupted']['study']['status'] == 'completed'
    assert exported['identity-changed']['study']['status'] == 'completed_with_failures'
    assert exported['failed-child']['study']['cases'][0]['error']['message'] == 'Original failed solver case'
    assert exported['removed-receipt']['study']['cases'][0]['error']['code'] == 'subscription_removed'


def _date_texts(seed: int, count: int) -> list[str]:
    rng = random.Random(seed)
    fixed = ['2026-11-25T00:00:00.000Z', '2026', '2026-11', '2026-02-29', '2026-02-30T00:00:00Z', '2026-02-31',
             '2026-04-31', '2026-00-10', '2026-13-01', '2026-11-00', '2026-11-32', '2026-11-25T24:00',
             '2026-11-25T24:00:00.000Z', '2026-11-25T24:00:00.0001Z', '2026-11-25T24:00:01Z', '2026-11-25T23:59:60Z',
             '2026-11-25T23:60Z', '2026-11-25T25:00Z', '+275760-09-13T00:00:00Z', '+275760-09-13T00:00:00.001Z',
             '-271821-04-20T00:00:00Z', '-271821-04-19T23:59:59.999Z', '+275760-09-13T00:00:00+00:01',
             '+275760-09-13T00:00:00-00:01', '-271821-04-20T00:00:00+00:01', '-271821-04-20T00:00:00-00:01',
             '-000000-01-01', '+000000-01-01T00:00:00Z', '-000001-01-01T00:00:00Z', '0000-01-01T00:00:00Z',
             '9999-12-31T23:59:59.999Z', '2026-11-25T10:20:30.123456789Z', '2026-11-25T10:20:30.Z',
             '2026-11-25T10:20:30+14:00', '2026-11-25T10:20:30+24:00', '2026-11-25T10:20:30+23:59',
             '2026-11-25T10:20:30+99:99', '2026-11-25T10:20:30-00:60', '2026-11-25T10:20Z', '2026-11-25T10Z',
             '2026-11-25T1:20Z', '2026-1-25', '2026-11-25t10:20:30z', '2026-11-25 10:20:30Z', ' 2026-11-25',
             '2026-11-25T10:20:30.5', '2026-11-25T10:20:30', '+002026-11-25', '+2026-11-25', '20261125']
    texts = list(fixed)
    for _ in range(count):
        year = rng.choice([f'{rng.randint(0, 9999):04d}', f'+{rng.randint(0, 275761):06d}',
                           f'-{rng.randint(0, 271822):06d}'])
        text = year
        if rng.random() < 0.9:
            text += f'-{rng.randint(0, 13):02d}'
            if rng.random() < 0.9:
                text += f'-{rng.randint(0, 32):02d}'
        if rng.random() < 0.7:
            text += f'T{rng.randint(0, 25):02d}:{rng.randint(0, 60):02d}'
            if rng.random() < 0.7:
                text += f':{rng.randint(0, 60):02d}'
                if rng.random() < 0.5:
                    text += '.' + ''.join(rng.choice('0123456789') for _ in range(rng.randint(1, 7)))
            zone = rng.random()
            if zone < 0.45:
                text += 'Z'
            elif zone < 0.9:
                text += f'{rng.choice("+-")}{rng.randint(0, 25):02d}:{rng.randint(0, 60):02d}'
            elif not year[0] in '+-' or abs(int(year)) < 200000:
                pass  # a local time far from the limits: finite in every time zone
            else:
                text += 'Z'
        texts.append(text)
    return texts


@needs_node
def test_study_time_checks_equal_node_on_iso_strings(tmp_path):
    texts = _date_texts(0x5d5d, 4000)
    node = run_driver('dates', [{'id': str(i), 'text': text} for i, text in enumerate(texts)], tmp_path)
    finite = {int(case['id']): case['finite'] for case in node['cases']}
    # The ISO format; V8's legacy parser still reads the year -000000, which the format excludes.
    iso_texts = [i for i, text in enumerate(texts) if ISO_DATE.fullmatch(text) and not text.startswith('-000000')]
    assert [texts[i] for i in iso_texts if iso_date_finite(texts[i]) != finite[i]] == []
    # Outside that format Python fails closed: it never accepts a time Node rejects.
    assert [text for i, text in enumerate(texts) if iso_date_finite(text) and not finite[i]] == []
    assert 1000 < sum(finite[i] for i in iso_texts) < len(iso_texts) - 500
