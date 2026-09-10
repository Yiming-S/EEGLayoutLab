import numpy as np
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from compact_eeg.robustness_metrics import (
    physical_noise_correlation, contrast_noise, contrast_field,
    fit_field_decoder, field_test_components, field_test_score,
    sensitivity_ratios, paired_localization, prior_weights, metrics_from_components,
)


def sample():
    rng = np.random.default_rng(43)
    return rng, rng.normal(size=(64, 100)), rng.normal(size=(64, 3))


def test_kernel_has_fixed_marginal_variance_and_positive_contrast():
    _, _, xyz = sample()
    n = physical_noise_correlation(xyz, rho=.8, length_mm=20)
    np.testing.assert_allclose(np.diag(n), 1)
    assert np.linalg.eigvalsh(n).min() > .19
    assert np.linalg.eigvalsh(contrast_noise(n)).min() > .19


def test_decoder_matches_independent_inverse_formula():
    rng, hb, _ = sample()
    hx = hb + rng.normal(size=hb.shape) * .5
    w = np.arange(1, 101, dtype=float); w /= w.sum()
    n = .1 * np.eye(64)
    a = fit_field_decoder(hb, hx, w, n)
    b, x = contrast_field(hb), contrast_field(hx)
    oracle = (b * w) @ x.T @ np.linalg.inv((x * w) @ x.T + .1 * np.eye(63))
    np.testing.assert_allclose(a, oracle, atol=1e-12)


def test_heldout_mse_matches_monte_carlo_and_does_not_refit():
    rng, train, _ = sample()
    a = fit_field_decoder(train, train, np.ones(100), .2 * np.eye(64))
    test = rng.normal(size=(64, 25)) * 2
    comp = field_test_components(test, test, a, .2 * np.eye(64))
    target = contrast_field(test)
    noise = rng.normal(size=(63, 25, 4000)) * np.sqrt(.2)
    residual = target[:, :, None] - np.einsum('ij,jqr->iqr', a, target[:, :, None] + noise)
    measured = 1 - np.mean(np.sum(residual**2, axis=0)) / np.mean(np.sum(target**2, axis=0))
    assert abs(measured - field_test_score(comp, np.ones(25))) < .002


def test_identity_and_gauge_invariance():
    rng, hb, xyz = sample()
    n = physical_noise_correlation(xyz, rho=.5) * .01
    w = np.ones(100)
    a = fit_field_decoder(hb, hb, w, n)
    shifted = hb + rng.normal(size=(1, 100))
    np.testing.assert_allclose(a, fit_field_decoder(shifted, shifted, w, n), atol=1e-12)
    comp = field_test_components(hb, hb, a, n)
    errors = rng.uniform(1, 20, (100, 8))
    row = metrics_from_components(comp, comp, sensitivity_ratios(hb, hb), errors, errors, w)
    assert row['field_relative'] == 1
    assert row['localization_relative'] == 1
    assert row['conditional_global'] == pytest.approx(1, abs=1e-12)


def test_frozen_test_score_can_be_negative():
    _, h, _ = sample()
    comp = field_test_components(h, -h, np.eye(63), .01*np.eye(64))
    assert field_test_score(comp, np.ones(100)) < 0


def test_prior_keeps_all_sources_and_normalizes():
    rng, _, _ = sample()
    weights = prior_weights(rng.normal(size=(50, 3)), np.ones(50))
    assert len(weights) == 4
    for w in weights.values():
        assert np.all(w > 0)
        np.testing.assert_allclose(w.sum(), 1)


def test_noise_and_weights_reject_invalid_inputs():
    _, _, xyz = sample()
    with pytest.raises(ValueError):
        physical_noise_correlation(xyz, rho=1)
    with pytest.raises(np.linalg.LinAlgError):
        contrast_noise(-np.eye(64))


def test_paired_localization_is_exactly_reproducible():
    rng, h, xyz = sample()
    pos = rng.normal(size=(100, 3))
    generation = .9 * h[:, :10] + .1 * h[:, 10:20]
    genpos = .9 * pos[:10] + .1 * pos[10:20]
    n = physical_noise_correlation(xyz, rho=.7) * .001
    z = rng.normal(size=(63, 10, 4))
    a = paired_localization(h, generation, pos, genpos, n, z)
    b = paired_localization(h, generation, pos, genpos, n, z)
    np.testing.assert_array_equal(a['errors_mm'], b['errors_mm'])
    assert a['errors_mm'].shape == (10, 4)
