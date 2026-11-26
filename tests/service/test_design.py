"""Design-evaluation service and result validator tests (phase 2 slice 5).

Ports the server-side sites of ``check-design-decision.mjs`` and ``check-design-robustness.mjs``.
"""
from __future__ import annotations

import copy
import threading
import time
from typing import Any

import pytest

from eeglayoutlab.jobs.design import DesignEvaluationService
from eeglayoutlab.jobs.design_result import DesignResultError, valid_robustness, validate_design_result
from eeglayoutlab.jobs.worker import ExecutionSlot
from eeglayoutlab.schemas import jsjson

from .test_worker import FakeChild


def _design() -> dict[str, Any]:
    return {
        'schema': 'eeg-electrode-design/1',
        'coordinate_system': 'ernie_native_mm',
        'unit': 'mm',
        'name': 'test',
        'xyz_mm': [[(i % 8) * 6, (i // 8) * 6, 0] for i in range(64)],
        'region_indices': [int(i >= 32) for i in range(64)],
    }


def _request(**overrides: Any) -> dict[str, Any]:
    return {'action': 'evaluate', 'design': _design(), 'radius_mm': 6, 'seed': 42, **overrides}


def _baseline_result(req: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    r = req or _request()
    return {
        'schema': 'design-evaluation/1',
        'status': 'completed',
        'request': r,
        'forward_mode': 'cached_fem',
        'nominal': {
            'field_relative': 1,
            'field_absolute': 0.9,
            'reference_field_absolute': 0.9,
            'sensitivity_tail': 1,
            'localization_relative': 1,
            'median_mm': 10,
            'p90_mm': 20,
            'reference_median_mm': 10,
            'reference_p90_mm': 20,
        },
        'projection_max_mm': 0,
        'evaluated_xyz_mm': copy.deepcopy(r['design']['xyz_mm']),
        'provenance': {'candidate_count': 64},
        'trials': [],
        **overrides,
    }


def _stats(median: float, count: int) -> dict[str, Any]:
    return {'median': median, 'p10': median - 1e-3, 'minimum': median - 2e-3, 'count': count}


def _side(completed: int, rejected: int) -> dict[str, Any]:
    if completed:
        return {
            'completed': completed,
            'rejected': rejected,
            'fixed_estimator': _stats(0.99, completed),
            'redigitized': _stats(0.999, completed),
            'displacement_rms_mm': 5.6,
        }
    return {
        'completed': completed,
        'rejected': rejected,
        'fixed_estimator': None,
        'redigitized': None,
        'displacement_rms_mm': None,
    }


def _robustness_block(*, table: bool = True) -> dict[str, Any]:
    return {
        'protocol': 'standard/1',
        'snr_db': 20,
        'dropout': {
            'single': {
                'candidate': [0.999 - i * 1e-6 for i in range(64)],
                'reference': _stats(0.9996, 64),
            },
            'random': [
                {
                    'removed': removed,
                    'draws': 32,
                    'candidate': _stats(0.999 - i * 1e-3, 32),
                    'reference': _stats(0.9993 - i * 1e-3, 32),
                }
                for i, removed in enumerate((2, 4, 8))
            ],
        },
        'impedance': [
            {
                'log_sd': log_sd,
                'draws': 32,
                'candidate': _stats(0.999 - i * 2e-3, 32),
                'reference': _stats(0.9991 - i * 2e-3, 32),
            }
            for i, log_sd in enumerate((0.5, 1.0))
        ],
        'replacement': (
            {
                'status': 'completed',
                'centre_mm': [0, -10, 40],
                'jitter_mm': 2,
                'table_id': 't' * 64,
                'levels': [
                    {
                        'rms_mm': rms_mm,
                        'trials': 16,
                        'rotation_deg': 3.6 * (i + 1),
                        'candidate': _side(15, 1),
                        'reference': _side(0, 16) if i else _side(16, 0),
                    }
                    for i, rms_mm in enumerate((5, 10))
                ],
            }
            if table
            else {'status': 'unavailable', 'reason': '重新佩戴试验需要预计算头皮节点表，本安装没有。'}
        ),
    }


def _wait_idle(service: DesignEvaluationService, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if service.active is None:
            return
        time.sleep(0.01)
    raise AssertionError('job did not finish')


def test_result_validator_rejects_switched_request_or_displaced_nominal_coordinates():
    """check-design-decision.mjs:184 'result validator rejects a switched request or displaced nominal coordinates'."""
    req = _request()
    validate_design_result(_baseline_result(req), req)

    with pytest.raises(DesignResultError):
        validate_design_result({**_baseline_result(req), 'request': {**req, 'seed': 9}}, req)

    displaced = [[p[0] + 3, p[1], p[2]] for p in req['design']['xyz_mm']]
    with pytest.raises(DesignResultError):
        validate_design_result({**_baseline_result(req), 'evaluated_xyz_mm': displaced}, req)

    head_req = {**req, 'head_id': 'ixi002'}
    validate_design_result(
        {**_baseline_result(head_req), 'forward_mode': 'head_scalp_node_table'},
        head_req,
    )
    for forward_mode in ('cached_fem', 'direct_fem', 'scalp_node_table'):
        with pytest.raises(DesignResultError, match='身份错误'):
            validate_design_result({**_baseline_result(head_req), 'forward_mode': forward_mode}, head_req)
    with pytest.raises(DesignResultError, match='身份错误'):
        validate_design_result({**_baseline_result(req), 'forward_mode': 'head_scalp_node_table'}, req)
    with pytest.raises(DesignResultError, match='身份错误'):
        validate_design_result({**_baseline_result(req), 'forward_mode': 'unknown'}, req)


def test_worker_results_cache_by_exact_inputs_and_do_not_consume_another_slot_on_hit(tmp_path):
    """check-design-decision.mjs:238 'worker results cache by exact inputs and do not consume another worker slot on hit'."""
    slot = ExecutionSlot()
    children: list[FakeChild] = []
    version = [1]

    def spawn(*_args: Any, **_kwargs: Any) -> FakeChild:
        child = FakeChild(pid=5000 + len(children))
        children.append(child)
        return child

    service = DesignEvaluationService(
        str(tmp_path),
        python='python3',
        timeout_ms=3000,
        execution_slot=slot,
        context_override=lambda r: {
            'identity': {'version': version[0]},
            'key': jsjson.sha256_hex({'request': r, 'version': version[0]}),
        },
        spawn_process=spawn,
    )
    release = None
    try:
        req = _request()
        first = service.submit(req)
        assert first['job']['status'] == 'running'
        children[0].emit_stdout(jsjson.stringify({'type': 'result', 'result': _baseline_result(req)}) + '\n')
        children[0].close(0, None)
        _wait_idle(service)

        # Verify B14 cache.json exact field order on disk.
        cache_path = service.store.path('design', first['job']['key'], 'cache.json')
        with open(cache_path, 'rb') as handle:
            stored = jsjson.parse(handle.read().decode('utf-8'))
        assert list(stored.keys()) == ['key', 'identity', 'result', 'result_sha256', 'finished_at']

        release = slot.acquire('other')
        assert release is not None
        cached = service.submit(req)
        assert cached['job']['cached'] is True
        assert len(children) == 1

        version[0] += 1
        busy = service.submit(req)
        assert busy['busy'] is True
    finally:
        if release is not None:
            release()
        service.dispose()


def test_cancel_keeps_shared_slot_until_process_close_and_never_creates_success_cache(tmp_path):
    """check-design-decision.mjs:260 'cancel keeps shared slot until process close and never creates a success cache'."""
    slot = ExecutionSlot()
    children: list[FakeChild] = []
    service = DesignEvaluationService(
        str(tmp_path),
        python='python3',
        timeout_ms=3000,
        execution_slot=slot,
        context_override=lambda r: {
            'identity': {'version': 1},
            'key': jsjson.sha256_hex({'request': r, 'version': 1}),
        },
        spawn_process=lambda *_a, **_kw: (children.append(FakeChild()), children[-1])[1],
    )
    try:
        req = _request()
        first = service.submit(req)
        service.cancel(first['job']['id'])
        assert service.active is not None and service.active.status == 'cancelling'
        assert service.submit({**req, 'seed': 43})['busy'] is True

        children[0].close(0, None)
        _wait_idle(service)
        job_record = service.jobs[first['job']['id']]
        assert job_record.status == 'cancelled'
        assert job_record.result is None
        assert service.lookup(req) == {'hit': False}
    finally:
        service.dispose()


def test_shutdown_during_input_validation_cannot_start_a_late_worker(tmp_path):
    """check-design-decision.mjs:274 'shutdown during input validation cannot start a late worker'."""
    entered = threading.Event()
    gate = threading.Event()
    children: list[FakeChild] = []

    def slow_context(_r: dict[str, Any]) -> dict[str, Any]:
        entered.set()
        gate.wait(timeout=2.0)
        return {'identity': {}, 'key': 'a' * 64}

    service = DesignEvaluationService(
        str(tmp_path),
        python='python3',
        context_override=slow_context,
        spawn_process=lambda *_a, **_kw: (children.append(FakeChild()), children[-1])[1],
    )
    errors: list[BaseException] = []

    def worker_submit() -> None:
        try:
            service.submit(_request())
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=worker_submit)
    thread.start()
    assert entered.wait(timeout=2.0)
    service.dispose()
    gate.set()
    thread.join(timeout=2.0)

    assert len(errors) == 1 and '服务正在重启' in str(errors[0])
    assert len(children) == 0
    assert service.active is None
    assert service.submitting is False


def test_corrupt_perturbation_coordinates_labels_or_derived_spacing_are_rejected():
    """check-design-decision.mjs:299 'corrupt perturbation coordinates, labels or derived spacing are rejected'."""
    req = _request(action='perturb')
    d = req['design']
    result = _baseline_result(
        req,
        trials=[
            {
                'index': idx,
                'status': 'completed',
                'xyz_mm': copy.deepcopy(d['xyz_mm']),
                'requested_xyz_mm': copy.deepcopy(d['xyz_mm']),
                'region_indices': list(d['region_indices']),
                'actual_max_mm': 0,
                'actual_mean_mm': 0,
                'candidate_bank_indices': list(range(64)),
                'unchanged_fraction': 1,
                'minimum_chord_distance_mm': 6,
                'target_error_max_mm': 0,
                'field_relative': 1,
                'fixed_estimator_field_relative': 1,
            }
            for idx in range(4)
        ],
    )
    validate_design_result(result, req)

    corruptions: list[dict[str, Any]] = [
        {'xyz_mm': []},
        {'region_indices': [0] * 64},
        {'minimum_chord_distance_mm': None},
        {'actual_max_mm': 5},
        {'actual_mean_mm': 5},
        {'candidate_bank_indices': [0] * 64},
        {'candidate_bank_indices': [i + 1 for i in range(64)]},
    ]
    for patch in corruptions:
        bad = copy.deepcopy(result)
        if patch.get('minimum_chord_distance_mm') is None and 'minimum_chord_distance_mm' in patch:
            bad['trials'][0].pop('minimum_chord_distance_mm', None)
        else:
            bad['trials'][0].update(patch)
        with pytest.raises(DesignResultError):
            validate_design_result(bad, req)


def test_result_validator_requires_robustness_block_when_requested_and_checks_all_eight_corruptions():
    """check-design-robustness.mjs:29 'the result validator requires the block exactly when requested and checks its
    structure' (all eight corruptions)."""
    plain_req = _request()
    robust_req = _request(robustness='standard/1')

    validate_design_result(_baseline_result(robust_req, forward_mode='scalp_node_table',
                                            robustness=_robustness_block()), robust_req)
    validate_design_result(_baseline_result(robust_req, forward_mode='scalp_node_table',
                                            robustness=_robustness_block(table=False)), robust_req)
    validate_design_result(_baseline_result(plain_req, forward_mode='scalp_node_table'), plain_req)

    with pytest.raises(DesignResultError, match='稳健性'):
        validate_design_result(_baseline_result(robust_req, forward_mode='scalp_node_table'), robust_req)
    with pytest.raises(DesignResultError, match='稳健性'):
        validate_design_result(_baseline_result(plain_req, forward_mode='scalp_node_table',
                                                robustness=_robustness_block()), plain_req)

    def c1(b: dict[str, Any]) -> None:
        b['dropout']['single']['candidate'].pop()

    def c2(b: dict[str, Any]) -> None:
        b['dropout']['random'][1]['candidate']['p10'] = b['dropout']['random'][1]['candidate']['median'] + 0.01

    def c3(b: dict[str, Any]) -> None:
        b['impedance'][0]['log_sd'] = 2

    def c4(b: dict[str, Any]) -> None:
        b['replacement']['levels'][0]['candidate']['rejected'] = 0

    def c5(b: dict[str, Any]) -> None:
        b['replacement']['levels'][1]['reference']['fixed_estimator'] = _stats(0.9, 16)

    def c6(b: dict[str, Any]) -> None:
        b['replacement']['levels'][0]['candidate']['fixed_estimator']['count'] = 16

    def c7(b: dict[str, Any]) -> None:
        b['dropout']['random'][0]['reference']['median'] = float('nan')

    def c8(b: dict[str, Any]) -> None:
        b['replacement'] = {'status': 'unavailable'}

    for mutator in (c1, c2, c3, c4, c5, c6, c7, c8):
        block = _robustness_block()
        mutator(block)
        assert valid_robustness(block) is False, mutator.__name__
