"""Session-robustness algebra on a synthetic bank: subsets, noise scaling, rotations and the request contract."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from compact_eeg.layout_search_metrics import LayoutSearchMetrics
from compact_eeg.workflows import design_robustness as robust
from compact_eeg.workflows import design_evaluation as de


def engine(kernel=None, seed=3):
    rng = np.random.default_rng(seed)
    xyz = rng.normal(size=(64, 3)) * 40
    field, reference = rng.normal(size=(64, 300)), rng.normal(size=(64, 300))
    weights = rng.uniform(.2, 1, 300)
    return LayoutSearchMetrics(field, reference, weights,
                               noise_kernel=None if kernel is None else (xyz, rng.normal(size=(64, 3)) * 40, *kernel)), xyz


@pytest.mark.parametrize('kernel', [None, (.5, 20.)])
def test_all_electrodes_reproduce_the_nominal_field_score(kernel):
    e, _ = engine(kernel)
    full = e.make_state(np.arange(64), snr_db=20).field_relative
    assert robust.subset_relative(e, np.arange(64)) == pytest.approx(full, rel=0, abs=1e-12)
    assert robust.subset_relative(e, np.arange(64), np.ones(64)) == pytest.approx(full, rel=0, abs=1e-12)


@pytest.mark.parametrize('kernel', [None, (.5, 20.)])
def test_removing_electrodes_or_adding_noise_never_helps(kernel):
    e, _ = engine(kernel)
    full = robust.subset_relative(e, np.arange(64))
    kept = np.arange(64)
    for removed in (3, 17, 40, 41):
        smaller = robust.subset_relative(e, kept[kept != removed])
        assert smaller <= full + 1e-12
    rng = np.random.default_rng(1)
    worse = 1 + rng.uniform(0, 3, 64)
    assert robust.subset_relative(e, np.arange(64), worse) < full


def test_dropout_and_impedance_are_seeded_and_paired():
    candidate, _ = engine(seed=3)
    reference, _ = engine(seed=4)
    first, second = robust.dropout(candidate, reference, 42), robust.dropout(candidate, reference, 42)
    assert first == second
    assert len(first['single']['candidate']) == 64
    assert [level['removed'] for level in first['random']] == list(robust.DROPOUT_COUNTS)
    assert robust.dropout(candidate, reference, 43)['random'] != first['random']
    # Independent streams: the impedance draws do not depend on the dropout stream having run.
    assert robust.impedance(candidate, reference, 42) == robust.impedance(candidate, reference, 42)
    levels = robust.impedance(candidate, reference, 42)
    assert levels[1]['candidate']['median'] < levels[0]['candidate']['median']
    # Noise only rises above the floor, so no draw beats the nominal layout.
    nominal = robust.subset_relative(candidate, np.arange(64))
    assert all(level[side]['median'] <= nominal + 1e-12 and level[side]['minimum'] < nominal for level in levels for side in ('candidate',))


def test_sphere_centre_and_rms_rotation():
    rng = np.random.default_rng(5)
    direction = rng.normal(size=(64, 3)); direction /= np.linalg.norm(direction, axis=1, keepdims=True)
    direction[:, 2] = np.abs(direction[:, 2])
    centre = np.array([3., -12., 40.])
    points = centre + 90 * direction
    assert np.allclose(robust.head_centre(points), centre, atol=1e-9)
    axis = np.array([1., 2., 2.]) / 3
    angle = robust.angle_for_rms(points, centre, axis, 5)
    moved = (points - centre) @ robust.rotation(axis, angle).T + centre
    assert np.sqrt(np.mean(np.sum((moved - points) ** 2, axis=1))) == pytest.approx(5, abs=1e-9)
    assert np.allclose(robust.rotation(axis, angle) @ robust.rotation(axis, angle).T, np.eye(3), atol=1e-12)


def test_request_contract():
    request = {'action': 'evaluate', 'radius_mm': 6, 'seed': 42, 'robustness': 'standard/1', 'design': {
        'schema': 'eeg-electrode-design/1', 'coordinate_system': 'ernie_native_mm', 'unit': 'mm', 'name': 'fixture',
        'xyz_mm': [[float(i % 8 * 6), float(i // 8 * 6), 0.] for i in range(64)], 'region_indices': [0] * 32 + [1] * 32}}
    assert de.validate_request(request) == request
    for change in ({'robustness': 'standard/2'}, {'robustness': True}, {'action': 'perturb'},
                   {'conductivity_scenario': 'skull_x2'}):
        with pytest.raises(ValueError):
            de.validate_request({**request, **change})
