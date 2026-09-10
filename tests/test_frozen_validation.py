import numpy as np
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from compact_eeg.frozen_validation import source_covariance, covariance_field_score, frozen_localization
from compact_eeg.robustness_metrics import (contrast_field, fit_field_decoder, field_test_components,
    field_test_score, paired_localization)


def fixture():
    r = np.random.default_rng(195)
    return r, r.normal(size=(64, 24)), r.normal(size=(64, 24)), r.normal(size=(24, 3))*20


def test_correlation_preserves_marginal_variance_and_psd():
    _, _, _, xyz = fixture()
    w = np.arange(1., 25.); w /= w.sum()
    q = source_covariance(xyz, w, rho=.8, length_mm=40)
    np.testing.assert_allclose(np.diag(q), w)
    assert np.linalg.eigvalsh(q).min() > 0
    np.testing.assert_allclose(np.trace(q), 1)
    np.testing.assert_allclose(source_covariance(xyz, w), np.diag(w))


def test_independent_covariance_matches_existing_residual_method():
    _, b, x, xyz = fixture()
    n = np.eye(64)*.01; w = np.ones(24)/24
    a = fit_field_decoder(b, x, w, n)
    out = covariance_field_score(b, x, a, source_covariance(xyz, w), n)
    np.testing.assert_allclose(out['field_absolute'], field_test_score(field_test_components(b, x, a, n), w), atol=1e-14)


def test_correlated_covariance_matches_monte_carlo():
    r, b, x, xyz = fixture()
    n = np.eye(64)*.02; w = np.ones(24)/24
    a = fit_field_decoder(b, x, w, n)
    q = source_covariance(xyz, w, rho=.6)
    j = np.linalg.cholesky(q)@r.normal(size=(24, 100000))
    target = contrast_field(b)@j
    observed = contrast_field(x)@j+r.normal(size=(63, len(j.T)))*np.sqrt(.02)
    expected = covariance_field_score(b, x, a, q, n)['field_absolute']
    measured = 1-np.sum((target-a@observed)**2)/np.sum(target**2)
    assert abs(expected-measured) < .005


def test_test_changes_do_not_mutate_decoder_and_negative_scores_preserved():
    _, b, x, xyz = fixture()
    n = np.eye(64)*.01; w = np.ones(24)/24
    a = fit_field_decoder(b, x, w, n); frozen = a.copy()
    covariance_field_score(b, x, a, source_covariance(xyz, w, rho=.5), n*100000)
    np.testing.assert_array_equal(a, frozen)
    assert covariance_field_score(b, x, a, source_covariance(xyz, w), n*100000)['field_absolute'] < 0


def test_reference_identity_and_gauge_invariance():
    r, b, _, xyz = fixture(); n = np.eye(64)*.01; w = np.ones(24)/24
    a = fit_field_decoder(b, b, w, n); q = source_covariance(xyz, w, rho=.5)
    s = covariance_field_score(b, b, a, q, n)['field_absolute']
    np.testing.assert_allclose(s, covariance_field_score(b+3, b+r.normal(size=(1,24)), a, q, n)['field_absolute'])
    assert s/s == 1


def test_frozen_localization_agrees_with_known_noise_when_matched():
    r, b, _, xyz = fixture(); n = np.eye(64)*.02
    generation = b[:, :4]; z = r.normal(size=(63, 4, 3))
    a = frozen_localization(b, generation, xyz, xyz[:4], n, n, z)
    c = paired_localization(b, generation, xyz, xyz[:4], n, z)
    np.testing.assert_array_equal(a['estimated_indices'], c['estimated_indices'])


@pytest.mark.parametrize('rho,length', [(1,20),(-.1,20),(.5,0),(float('nan'),20)])
def test_invalid_kernel_rejected(rho,length):
    _,_,_,xyz = fixture()
    with pytest.raises(ValueError):
        source_covariance(xyz, np.ones(24), rho=rho, length_mm=length)
