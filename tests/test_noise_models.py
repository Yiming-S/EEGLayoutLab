"""Correlated electrode-noise models: exact field scores, search updates and localization draws."""
from __future__ import annotations
import dataclasses
from pathlib import Path
import sys

import numpy as np
import pytest
import scipy.linalg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compact_eeg import noise_models
from compact_eeg.layout_search_metrics import LayoutSearchMetrics
from compact_eeg.local_radius_compute import search_seed, validate_request as radius_request
from compact_eeg.metrics import helmert_contrast
from compact_eeg.prototype_localization import evaluate_grid_localization
from compact_eeg.workflows import design_evaluation

SPATIAL = {"kind": "spatial", "rho": 0.5, "length_mm": 20}


@pytest.fixture
def bank():
    rng = np.random.default_rng(2611)
    directions = rng.normal(size=(100, 3))
    xyz = 90 * directions / np.linalg.norm(directions, axis=1, keepdims=True)
    fields = rng.normal(size=(100, 12)) @ rng.normal(size=(12, 80)) + .05 * rng.normal(size=(100, 80))
    return {"rng": rng, "xyz": xyz, "fields": fields, "weights": rng.uniform(.2, 2, 80)}


def golden_relative(bank, indices, rho, length, snr_db=20):
    """Direct contrast-space LMMSE with correlated physical noise; independent of the engine."""
    c = helmert_contrast(64)
    w = bank["weights"] / bank["weights"].sum()
    hb, hx = c @ bank["fields"][:64], c @ bank["fields"][indices]
    sigma2 = np.sum(hb * hb * w) / 63 * 10 ** (-snr_db / 10)
    def explained(h, xyz):
        cxx = (h * w) @ h.T + sigma2 * c @ noise_models.spatial_correlation(xyz, rho, length) @ c.T
        cbx = (hb * w) @ h.T
        return np.trace(cbx @ np.linalg.solve(cxx, cbx.T)) / np.trace((hb * w) @ hb.T)
    return explained(hx, bank["xyz"][indices]) / explained(hb, bank["xyz"][:64])


def engine(bank, kernel=None):
    noise = None if kernel is None else (bank["xyz"], bank["xyz"][:64], *kernel)
    return LayoutSearchMetrics(bank["fields"], bank["fields"][:64], bank["weights"], noise_kernel=noise)


def test_correlated_field_score_matches_direct_lmmse(bank):
    indices = bank["rng"].choice(100, 64, replace=False)
    state = engine(bank, (.5, 20.)).make_state(indices)
    assert state.field_relative == pytest.approx(golden_relative(bank, indices, .5, 20.), rel=1e-10)


@pytest.mark.parametrize("chunk_size", [256, 16])
def test_exchange_updates_include_noise_cross_terms(bank, chunk_size):
    correlated = engine(bank, (.5, 20.))
    indices = bank["rng"].choice(100, 64, replace=False)
    state = correlated.make_state(indices)
    scores = correlated.score_exchanges(state, 7, np.arange(100), chunk_size=chunk_size)
    assert scores.direct_fallback_count == 0 and len(scores.candidate_indices) > 2 * 16
    for candidate, value in zip(scores.candidate_indices, scores.field_relative):
        changed = indices.copy()
        changed[7] = candidate
        assert value == pytest.approx(correlated.make_state(changed).field_relative, rel=1e-9)


def test_exchange_fallback_uses_direct_cholesky(bank):
    correlated = engine(bank, (.5, 20.))
    indices = bank["rng"].choice(100, 64, replace=False)
    # A corrupted cached inverse makes every Schur update unusable; make_state never reads it.
    broken = dataclasses.replace(correlated.make_state(indices), _inverse_covariance=np.full((64, 64), np.nan))
    scores = correlated.score_exchanges(broken, 7, np.arange(100), chunk_size=16)
    assert scores.direct_fallback_count == len(scores.candidate_indices) > 16
    for candidate, value in zip(scores.candidate_indices, scores.field_relative):
        changed = indices.copy()
        changed[7] = candidate
        assert value == correlated.make_state(changed).field_relative


def test_exchange_updates_stay_exact_near_the_noise_nugget(bank):
    # Near-copies of electrode 0 (8 retained, 6 candidates) drive a candidate's Schur variance towards the
    # (1-rho) noise nugget, where the update cancels most digits of an O(1) diagonal.
    rng, fields, xyz = bank["rng"], bank["fields"].copy(), bank["xyz"].copy()
    copies = np.r_[1:8, 64:70]
    fields[copies] = fields[0] * (1 + 1e-9 * rng.normal(size=(len(copies), 1)))
    xyz[copies] = xyz[0] + 1e-3 * rng.normal(size=(len(copies), 3))
    correlated = engine({**bank, "fields": fields, "xyz": xyz}, (.5, 20.))
    indices, noise = np.arange(64), 10 ** (-20 / 10)
    scores = correlated.score_exchanges(correlated.make_state(indices), 20)
    assert scores.direct_fallback_count == 0
    schur = []
    for candidate, value in zip(scores.candidate_indices, scores.field_relative):
        changed = indices.copy()
        changed[20] = candidate
        direct = correlated.make_state(changed)
        assert value == pytest.approx(direct.field_relative, rel=1e-10)
        schur.append(1 / direct._inverse_covariance[20, 20] / noise)
    # Conditional variance in units of the noise variance: nugget .5, fallback floor .25.
    assert .5 < min(schur) < .6


def test_zero_correlation_reproduces_iid_and_shared_caches_agree(bank):
    indices = bank["rng"].choice(100, 64, replace=False)
    iid = engine(bank)
    assert engine(bank, (0., 20.)).make_state(indices).field_relative == pytest.approx(iid.make_state(indices).field_relative, rel=1e-12)
    shared = iid.with_noise_kernel((bank["xyz"], bank["xyz"][:64], .5, 20.))
    assert shared.make_state(indices).field_relative == pytest.approx(engine(bank, (.5, 20.)).make_state(indices).field_relative, rel=1e-12)
    with pytest.raises(ValueError, match="different covariance bank"):
        shared.score_exchanges(iid.make_state(indices), 0)


def test_zero_correlation_kernel_adds_exact_zeros(bank):
    # rho=0 gives N = I and zero cross terms, so the candidate arithmetic equals the iid path exactly.
    # The reference baseline goes through C I C^T, which is not exactly I, so field_relative is not compared here.
    indices = bank["rng"].choice(100, 64, replace=False)
    iid, zero = engine(bank), engine(bank, (0., 20.))
    plain, kernel = iid.make_state(indices), zero.make_state(indices)
    assert plain.field_absolute == kernel.field_absolute
    a = iid.score_exchanges(plain, 7, chunk_size=16, include_sensitivity=True)
    b = zero.score_exchanges(kernel, 7, chunk_size=16, include_sensitivity=True)
    np.testing.assert_array_equal(a.field_absolute, b.field_absolute)
    np.testing.assert_array_equal(a.sensitivity_tail, b.sensitivity_tail)


def whitened_rank(fields, weights, xyz, rho, length):
    """Participation rank of the generalized eigenvalues of (signal, correlated noise) in contrast space."""
    c = helmert_contrast(64)
    h = c @ fields
    values = np.clip(scipy.linalg.eigh((h * weights) @ h.T, c @ noise_models.spatial_correlation(xyz, rho, length) @ c.T, eigvals_only=True), 0, None)
    return values.sum() ** 2 / (values @ values)


def test_effective_rank_is_whitened_by_correlated_noise(bank):
    indices = bank["rng"].choice(100, 64, replace=False)
    iid = engine(bank)
    correlated = iid.with_noise_kernel((bank["xyz"], bank["xyz"][:64], .5, 10.))
    row = correlated.evaluate(indices, snr_db=(20,))["conditions"][0]
    w = bank["weights"]
    assert row["candidate_noise_whitened_area_weighted_effective_rank"] == pytest.approx(
        whitened_rank(bank["fields"][indices], w, bank["xyz"][indices], .5, 10.), rel=1e-9)
    assert row["reference_noise_whitened_area_weighted_effective_rank"] == pytest.approx(
        whitened_rank(bank["fields"][:64], w, bank["xyz"][:64], .5, 10.), rel=1e-9)
    plain = iid.evaluate(indices, snr_db=(20,))["conditions"][0]
    assert plain["reference_noise_whitened_area_weighted_effective_rank"] != row["reference_noise_whitened_area_weighted_effective_rank"]
    zero = engine(bank, (0., 20.)).evaluate(indices, snr_db=(20,))["conditions"][0]
    for key in ("candidate_noise_whitened_area_weighted_effective_rank", "reference_noise_whitened_area_weighted_effective_rank"):
        assert zero[key] == pytest.approx(plain[key], rel=1e-10)


def test_frozen_estimator_noise_argument_is_neutral_for_iid(bank):
    nominal, observed, reference = bank["fields"][:64], bank["fields"][1:65], bank["fields"][:64]
    identity = {key: np.eye(64) for key in ("nominal", "observed", "reference")}
    plain = design_evaluation.fixed_estimator_retention(nominal, observed, reference, bank["weights"])
    assert design_evaluation.fixed_estimator_retention(nominal, observed, reference, bank["weights"], noise=identity) == pytest.approx(plain, rel=1e-12)


def localization_inputs(bank):
    rng = np.random.default_rng(5)
    return dict(dictionary_leadfield=rng.normal(size=(64, 40)), generation_leadfield=rng.normal(size=(64, 10)),
                dictionary_xyz_mm=rng.normal(size=(40, 3)) * 50, generation_xyz_mm=rng.normal(size=(10, 3)) * 50 + .3,
                source_moment_am=1., physical_electrode_noise_std_v=.5, noise_seed=3, layout_id="t", noise_repetitions=4)


def test_localization_covariance_path_reproduces_iid_and_is_paired(bank):
    inputs = localization_inputs(bank)
    iid = evaluate_grid_localization(**inputs)
    explicit = evaluate_grid_localization(**inputs, physical_noise_covariance_v2=.25 * np.eye(64), noise_model="explicit")
    np.testing.assert_array_equal(iid.estimated_dictionary_indices, explicit.estimated_dictionary_indices)
    np.testing.assert_array_equal(iid.standard_normal_noise, explicit.standard_normal_noise)
    assert "noise_model" not in iid.report and explicit.report["noise_model"] == "explicit"
    correlated = .25 * noise_models.spatial_correlation(bank["xyz"][:64], .5, 20)
    first = evaluate_grid_localization(**inputs, physical_noise_covariance_v2=correlated)
    again = evaluate_grid_localization(**inputs, physical_noise_covariance_v2=correlated)
    np.testing.assert_array_equal(first.errors_mm, again.errors_mm)
    # Different noise models colour the same standard-normal draws, so their comparison is paired.
    wider = evaluate_grid_localization(**inputs, physical_noise_covariance_v2=.25 * noise_models.spatial_correlation(bank["xyz"][:64], .5, 40))
    np.testing.assert_array_equal(first.standard_normal_noise, wider.standard_normal_noise)
    np.testing.assert_array_equal(iid.standard_normal_noise, wider.standard_normal_noise)


def test_brain_background_keeps_reference_noise_power(bank):
    field, weights = bank["fields"][:64], bank["weights"]
    kappa = noise_models.background_scale(field, weights, .25, .5, 1e-8)
    covariance = noise_models.localization_covariance({"kind": "brain_background", "fraction": .5}, None, field, weights, .25, 1e-8, kappa)
    c = helmert_contrast(64)
    assert np.trace(c @ covariance @ c.T) / 63 == pytest.approx(.25, rel=1e-12)
    described = noise_models.describe({"kind": "brain_background", "fraction": .5})
    assert described["background_scale_relative_to_signal_prior"] == pytest.approx(.005, rel=1e-12)
    assert noise_models.describe(None) == "iid_equal_variance"


def test_request_forms_are_canonical_and_defaults_are_omitted():
    assert noise_models.normalize(None) is None and noise_models.normalize({"kind": "iid"}) is None
    assert noise_models.normalize(dict(SPATIAL)) == SPATIAL
    for bad in ({"kind": "spatial", "rho": .4, "length_mm": 20}, {"kind": "spatial", "rho": .5, "length_mm": 15},
                {"kind": "spatial", "rho": .5, "length_mm": 20.0}, {"kind": "brain_background", "fraction": .5, "x": 1}, {"kind": "pink"}):
        with pytest.raises(ValueError):
            noise_models.normalize(bad)
    base = {"region_count": 2, "radius_mm": 30, "mode": "whole_surface", "mask_codes": []}
    assert radius_request(base) == base
    assert radius_request({**base, "noise_model": SPATIAL})["noise_model"] == SPATIAL
    with pytest.raises(ValueError, match="localization only"):
        radius_request({**base, "noise_model": {"kind": "brain_background", "fraction": .5}})
    for default in ({"kind": "iid"}, None):
        with pytest.raises(ValueError, match="canonical"):
            radius_request({**base, "noise_model": default})


def test_radius_search_seed_ignores_noise_model():
    base = radius_request({"region_count": 2, "radius_mm": 30, "mode": "whole_surface"})
    # Pinned iid seed: hash of the canonical request, independent of BLAS and platform.
    assert search_seed(base) == 2104905360
    for length in (10, 20, 40):
        assert search_seed(radius_request({**base, "noise_model": {**SPATIAL, "length_mm": length}})) == 2104905360
