"""Default iid noise pinned bit for bit to the arithmetic that predates noise models.

Each ``head_*`` helper repeats, operation for operation and in the same order,
the code before noise_model existed (commit 61cd27d) on small synthetic data.
Comparing operations instead of stored numbers keeps the pin BLAS independent.
"""
from pathlib import Path
import dataclasses
import hashlib
import json
import sys

import numpy as np
import pytest
from scipy.linalg import cho_factor, cho_solve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compact_eeg import prototype_localization
from compact_eeg.inverse_pilot import fixed_normal_scan
from compact_eeg.layout_search_metrics import LayoutSearchMetrics
from compact_eeg.metrics import helmert_contrast, participation_effective_rank
from compact_eeg.workflows.design_evaluation import fixed_estimator_retention


@pytest.fixture(scope="module")
def bank():
    rng = np.random.default_rng(4401)
    fields = rng.normal(size=(100, 12)) @ rng.normal(size=(12, 80)) + .05 * rng.normal(size=(100, 80))
    weights = rng.uniform(.2, 2, 80)
    layouts = [rng.choice(100, 64, replace=False) for _ in range(3)]
    return {"fields": fields, "weights": weights, "layouts": layouts, "engine": LayoutSearchMetrics(fields, fields[:64], weights)}


def head_noise(snr_db):
    return float(np.power(10., -float(snr_db) / 10))


def head_baseline(e, noise):
    factor = cho_factor(e._cbb + noise * np.eye(63), lower=True, check_finite=False)
    estimate = cho_solve(factor, e._cbb, check_finite=False)
    return float(np.sum(e._cbb * estimate.T) / e._target_energy)


def head_state(e, selected, noise):
    covariance = e._covariance[np.ix_(selected, selected)]
    covariance = .5 * (covariance + covariance.T) + noise * np.eye(64)
    inverse = cho_solve(cho_factor(covariance, lower=True, check_finite=False), np.eye(64), check_finite=False)
    inverse = .5 * (inverse + inverse.T)
    cross = e._cross[:, selected]
    weighted_cross = cross @ inverse
    inverse_one = inverse.sum(axis=1)
    projected_one = cross @ inverse_one
    reference_precision = float(inverse_one.sum())
    absolute = float((np.sum(weighted_cross * cross) - np.dot(projected_one, projected_one) / reference_precision) / e._target_energy)
    return absolute, absolute / head_baseline(e, noise), inverse


def head_exchanges(e, indices, w, position, candidates, noise, chunk_size):
    keep = np.delete(np.arange(64), position)
    retained = indices[keep]
    candidates = candidates[~np.isin(candidates, retained)]
    reduced = w[np.ix_(keep, keep)] - np.outer(w[keep, position], w[position, keep]) / w[position, position]
    reduced = .5 * (reduced + reduced.T)
    cross = e._cross[:, retained]
    reduced_cross = cross @ reduced
    trace = float(np.sum(reduced_cross * cross))
    inverse_one = reduced.sum(axis=1)
    one_precision = float(inverse_one.sum())
    projected_one = cross @ inverse_one
    absolute, fallbacks = np.empty(len(candidates)), 0
    for start in range(0, len(candidates), chunk_size):
        part = candidates[start:start + chunk_size]
        cov = e._covariance[np.ix_(retained, part)]
        solved = reduced @ cov
        diagonal = e._covariance[part, part] + noise
        schur = diagonal - np.sum(cov * solved, axis=0)
        innovations = e._cross[:, part] - reduced_cross @ cov
        residual_one = 1 - inverse_one @ cov
        bad = (~np.isfinite(schur)) | (schur < noise * .5)
        safe_schur = np.where(bad, 1., schur)
        t = trace + np.sum(innovations**2, axis=0) / safe_schur
        projected = projected_one[:, None] + innovations * (residual_one / safe_schur)
        p = one_precision + residual_one**2 / safe_schur
        values = (t - np.sum(projected**2, axis=0) / p) / e._target_energy
        bad |= (~np.isfinite(values)) | (values < -1e-9) | (values > 1 + 1e-9)
        for local in np.flatnonzero(bad):
            changed = indices.copy()
            changed[position] = part[local]
            values[local] = head_state(e, changed, noise)[0]
            fallbacks += 1
        absolute[start:start + len(part)] = values
    return candidates, absolute, absolute / head_baseline(e, noise), fallbacks


@pytest.mark.parametrize("snr_db", [-20, 0, 10, 20])
def test_iid_state_and_baseline_match_pre_noise_model_arithmetic(bank, snr_db):
    e, noise = bank["engine"], head_noise(snr_db)
    assert e._baseline(snr_db) == head_baseline(e, noise)
    for indices in bank["layouts"]:
        state = e.make_state(indices, snr_db=snr_db)
        absolute, relative, inverse = head_state(e, indices, noise)
        assert (state.field_absolute, state.field_relative) == (absolute, relative)
        assert np.array_equal(state._inverse_covariance, inverse)


@pytest.mark.parametrize("chunk_size", [256, 16])
@pytest.mark.parametrize("corrupt", [False, True])
def test_iid_exchange_scores_match_pre_noise_model_arithmetic(bank, chunk_size, corrupt):
    e, noise = bank["engine"], head_noise(20)
    for indices in bank["layouts"]:
        state = e.make_state(indices)
        if corrupt:
            # A NaN inverse forces the direct-Cholesky fallback for every candidate.
            state = dataclasses.replace(state, _inverse_covariance=np.full((64, 64), np.nan))
        for position in (0, 7, 63):
            scores = e.score_exchanges(state, position, chunk_size=chunk_size)
            candidates, absolute, relative, fallbacks = head_exchanges(
                e, indices, state._inverse_covariance, position, np.arange(100), noise, chunk_size)
            assert scores.direct_fallback_count == fallbacks == (len(candidates) if corrupt else 0)
            for got, want in zip((scores.candidate_indices, scores.field_absolute, scores.field_relative), (candidates, absolute, relative)):
                assert np.array_equal(got, want)


def test_iid_evaluate_report_matches_pre_noise_model_arithmetic(bank):
    e, indices = bank["engine"], bank["layouts"][0]
    centered = e._bank[indices] - e._bank[indices[:1]]
    centered -= centered.mean(axis=0, keepdims=True)
    hx = e._contrast @ centered
    rank = participation_effective_rank((hx * e._weights) @ hx.T)
    for snr, row in zip((0, 10, 20), e.evaluate(indices)["conditions"]):
        noise = head_noise(snr)
        absolute, relative, _ = head_state(e, indices, noise)
        variance = e.reference_mean_contrast_signal_power_v2 * noise
        assert row == {"nominal_reference_snr_db": float(snr), "shared_physical_electrode_noise_variance_v2": variance,
            "shared_physical_electrode_noise_std_uv": float(np.sqrt(variance) * 1e6),
            "reference_field_explained_energy": head_baseline(e, noise), "candidate_field_explained_energy": absolute,
            "field_retention_unclipped": relative, "reference_noise_whitened_area_weighted_effective_rank": participation_effective_rank(e._cbb),
            "candidate_noise_whitened_area_weighted_effective_rank": rank, "baseline_identity_field_retention": 1.}


@pytest.mark.parametrize("shift", [1, 2, 3])
@pytest.mark.parametrize("snr", [0, 10, 20])
def test_iid_fixed_estimator_matches_pre_noise_model_arithmetic(bank, shift, snr):
    nominal, observed, reference, weights = bank["fields"][:64], bank["fields"][shift:64 + shift], bank["fields"][36:], bank["weights"]
    c = helmert_contrast(64)
    w = np.asarray(weights, float) / np.sum(weights)
    t, a, b = (c @ x for x in (reference, nominal, observed))
    scale = np.sqrt(np.sum(t * t * w) / 63)
    t, a, b = t / scale, a / scale, b / scale
    noise = 10. ** (-snr / 10)
    def estimator(h):
        covariance = (h * w) @ h.T + noise * np.eye(63)
        return cho_solve(cho_factor(covariance, lower=True), ((t * w) @ h.T).T).T
    def explained(transform, h):
        residual = t - transform @ h
        error = np.sum(residual * residual * w) + noise * np.sum(transform * transform)
        return float(1 - error / np.sum(t * t * w))
    assert fixed_estimator_retention(nominal, observed, reference, weights, snr) == explained(estimator(a), b) / explained(estimator(t), t)


def test_iid_localization_draw_and_whitening_match_pre_noise_model_arithmetic(monkeypatch):
    rng = np.random.default_rng(5)
    hd, hg = rng.normal(size=(64, 40)), rng.normal(size=(64, 10))
    xd, xg = rng.normal(size=(40, 3)) * 50, rng.normal(size=(10, 3)) * 50 + .3
    sigma, moment, seed, layout, repetitions = .5, 1.5, 3, "pin", 4
    calls = []
    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return fixed_normal_scan(*args, **kwargs)
    monkeypatch.setattr(prototype_localization, "fixed_normal_scan", spy)
    result = prototype_localization.evaluate_grid_localization(hd, hg, xd, xg, source_moment_am=moment,
        physical_electrode_noise_std_v=sigma, noise_seed=seed, layout_id=layout, noise_repetitions=repetitions)
    digest = hashlib.sha256(json.dumps({"base_seed": seed, "layout_id": layout}, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode("utf-8")).digest()
    generator = np.random.default_rng(np.random.SeedSequence(np.frombuffer(digest, dtype="<u4").tolist()))
    standard_noise = generator.normal(size=(63, 10, repetitions))
    contrast = helmert_contrast(64)
    hd_reference_free = contrast @ (hd - hd.mean(axis=0, keepdims=True))
    hg_reference_free = contrast @ (hg - hg.mean(axis=0, keepdims=True))
    observations = (hg_reference_free[:, :, None] * moment + sigma * standard_noise).reshape(63, -1)
    (args, kwargs), = calls
    assert len(args) == 3 and kwargs == {"batch_size": 128}
    for got, want in zip(args, (hd_reference_free, observations, sigma * sigma * np.eye(63))):
        assert np.array_equal(got, want)
    indices = fixed_normal_scan(hd_reference_free, observations, sigma * sigma * np.eye(63), batch_size=128).reshape(10, repetitions)
    assert np.array_equal(result.standard_normal_noise, standard_noise) and np.array_equal(result.estimated_dictionary_indices, indices)
    assert np.array_equal(result.errors_mm, np.linalg.norm(xd[indices] - xg[:, None, :], axis=2))
    assert result.report["layout_noise_stream_sha256"] == digest.hex() and "noise_model" not in result.report
