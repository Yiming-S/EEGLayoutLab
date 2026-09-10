"""Covariance-cache LMMSE scores for exploratory fixed-64 coordinate exchange.

The reference supplies the clean target, area-weighted source prior and ONE
physical noise scale. Each candidate observes only its own 63-dimensional
reference-free field. No classifier, AR certificate or global optimum is claimed.

For K=C_SS+lambda*I, U=C_BS and a vector of ones e, the contrast precision is
  W = K^-1 - K^-1 e (e.T K^-1 e)^-1 e.T K^-1.
Thus explained energy is tr(U W U.T)/tr(C_BB), exactly the Helmert LMMSE
quantity. Exchange scoring uses block inversion of the retained 63 electrodes;
accepted layouts rebuild a Cholesky factorization, avoiding accumulated updates.

Cache construction: O(M^2 Q) work, O(M^2+MQ+63M) float64 storage. An initial
layout costs O(64^3+63*64^2). Scoring P replacements at one position costs
O((64^2+63*64)P), with O((64+63)P_chunk) workspace. Optional sensitivity uses
O(PQ log Q) weighted-tail sorting and O(P_chunk Q) workspace. No FEM is run.

Observed small benchmark, 2026-09-08, saved Ernie bank 635 x 4096 and four
BLAS threads: cache construction 0.031 s / 23.32 MiB; 572 replacements at one
position 0.000738 s field-only (20-run mean), 0.109 s including sensitivity.
These are machine-specific timings, not promised full-search runtimes. Cache
storage alone is about 127.1 / 349.5 MiB for M=2500 / 5000 and Q=4096, excluding
caller-owned arrays and workspace. The optional CLI reproduces this benchmark.
"""
from __future__ import annotations

from dataclasses import dataclass
import time

import numpy as np
from scipy.linalg import cho_factor, cho_solve

from .metrics import helmert_contrast, participation_effective_rank


def _readonly(value, dtype=None):
    array = np.array(value, dtype=dtype, copy=True)
    array.setflags(write=False)
    return array


def _positive(value, name):
    value = float(value)
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return value


def _index_vector(value, size, *, count=None, name="indices"):
    array = np.asarray(value)
    if array.ndim == 1 and not array.size and count is None:
        return np.empty(0, dtype=np.int64)
    if array.ndim != 1 or array.dtype.kind not in "iu":
        raise ValueError(f"{name} must be a one-dimensional integer array")
    if count is not None and len(array) != count:
        raise ValueError(f"{name} must contain exactly {count} indices")
    if array.size and (array.min() < 0 or array.max() >= size):
        raise ValueError(f"{name} outside candidate bank")
    if len(np.unique(array)) != len(array):
        raise ValueError(f"{name} contains duplicate physical point indices")
    return array.astype(np.int64, copy=False)


@dataclass(frozen=True)
class LayoutScoreState:
    """One validated layout; recreate through the owning engine after acceptance."""
    indices: np.ndarray
    snr_db: float
    field_absolute: float
    field_relative: float
    _owner: object
    _inverse_covariance: np.ndarray


@dataclass(frozen=True)
class ExchangeScores:
    """Candidates exclude the other 63 occupied points; original order preserved.

    The currently occupied point at the replaced position is allowed, providing
    an exact no-change comparison. Sensitivity is None unless requested; NaN
    entries then mean the exploratory denominator exclusion budget was exceeded.
    """
    candidate_indices: np.ndarray
    field_absolute: np.ndarray
    field_relative: np.ndarray
    sensitivity_tail: np.ndarray | None
    direct_fallback_count: int


class LayoutSearchMetrics:
    """Fast scalar scoring on a shared M x Q point lead-field bank.

    Lead fields use V/(A*m); weights represent cortical area. The bank's common
    row mean is subtracted only to improve conditioning; every candidate's own
    common reference is still removed in its LMMSE inverse. Repeated *indices*
    are forbidden, whereas physically different points with equal lead fields
    are legal under the explicitly independent equal-electrode-noise model.

    Default optimization score is ``make_state(..., snr_db=20).field_relative``.
    It is a field-only objective, not a joint sensitivity/localization optimum.
    Use the separately returned sensitivity when defining another objective.
    """
    def __init__(
        self, candidate_leadfield, reference_leadfield, source_area_weights, *,
        source_moment_am=1e-8, numerical_zero_relative_tolerance=1e-8,
        source_tail_fraction=.1, maximum_excluded_source_area_fraction=.001,
        covariance_block_size=256,
    ):
        started = time.perf_counter()
        bank = np.asarray(candidate_leadfield, dtype=np.float64)
        reference = np.asarray(reference_leadfield, dtype=np.float64)
        if bank.ndim != 2 or bank.shape[0] < 64 or bank.shape[1] < 1:
            raise ValueError("candidate_leadfield must have shape (M >= 64, Q >= 1)")
        if reference.shape != (64, bank.shape[1]):
            raise ValueError("reference_leadfield must have shape (64, Q)")
        if not np.all(np.isfinite(bank)) or not np.all(np.isfinite(reference)):
            raise ValueError("lead fields must be finite")
        weights = np.asarray(source_area_weights, dtype=np.float64)
        if weights.shape != (bank.shape[1],) or not np.all(np.isfinite(weights)) or np.any(weights < 0) or not np.any(weights > 0):
            raise ValueError("source weights must be finite nonnegative Q-vector with positive total")
        weights = weights / weights.max()
        weights = weights / weights.sum()
        self.source_moment_am = _positive(source_moment_am, "source_moment_am")
        tolerance = float(numerical_zero_relative_tolerance)
        fraction = float(source_tail_fraction)
        budget = float(maximum_excluded_source_area_fraction)
        if not np.isfinite(tolerance) or not 0 <= tolerance < 1:
            raise ValueError("numerical_zero_relative_tolerance must lie in [0,1)")
        if not np.isfinite(fraction) or not 0 < fraction <= 1:
            raise ValueError("source_tail_fraction must lie in (0,1]")
        if not np.isfinite(budget) or not 0 <= budget < 1:
            raise ValueError("maximum_excluded_source_area_fraction must lie in [0,1)")
        if not isinstance(covariance_block_size, (int, np.integer)) or covariance_block_size < 1:
            raise ValueError("covariance_block_size must be a positive integer")
        self.point_count, self.source_count = bank.shape
        self._owner = object()
        self._contrast = helmert_contrast(64)
        self._weights = _readonly(weights)
        reference_centered = reference - reference.mean(axis=0, keepdims=True)
        hb = self._contrast @ reference_centered
        scale = float(np.max(np.abs(hb)))
        if scale == 0:
            raise ValueError("reference must have positive reference-free signal power")
        scaled_hb = hb / scale
        normalization = float(np.sqrt(np.sum(scaled_hb**2 * weights) / 63))
        if not np.isfinite(normalization) or normalization <= 0:
            raise ValueError("reference must have positive weighted signal power")
        hb = scaled_hb / normalization
        physical_std = scale * self.source_moment_am * normalization
        self.reference_mean_contrast_signal_power_v2 = _positive(physical_std * physical_std, "physical reference signal power")
        self._bank = bank.copy()
        self._bank -= self._bank.mean(axis=0, keepdims=True)
        self._bank /= scale
        self._bank /= normalization
        if not np.all(np.isfinite(self._bank)):
            raise ValueError("normalized bank is outside float64 range")
        self._bank.setflags(write=False)
        self._cbb = (hb * weights) @ hb.T
        self._cbb = .5 * (self._cbb + self._cbb.T)
        self._target_energy = float(np.trace(self._cbb))
        self._cross = (hb * weights) @ self._bank.T
        self._covariance = np.empty((self.point_count, self.point_count), dtype=float)
        for start in range(0, self.point_count, int(covariance_block_size)):
            stop = min(start + int(covariance_block_size), self.point_count)
            self._covariance[start:stop] = (self._bank[start:stop] * weights) @ self._bank.T
        if not np.all(np.isfinite(self._covariance)) or not np.all(np.isfinite(self._cross)):
            raise ValueError("normalized covariance exceeds float64 range")
        self._covariance.setflags(write=False)
        self._reference_rank = participation_effective_rank(self._cbb)
        self._baseline_cache = {}
        self._reference_bipolar = np.ptp(reference_centered, axis=0) / scale / normalization
        threshold_original = 2 * tolerance * float(np.max(np.abs(reference_centered)))
        self._valid = np.ptp(reference_centered, axis=0) > threshold_original
        self._fraction = fraction
        self._excluded_area = float(weights[~self._valid].sum())
        self._sensitivity_available = bool(np.any(self._valid) and self._excluded_area <= budget)
        self._tolerance = tolerance
        self._threshold_original = threshold_original
        self.cache_bytes = int(sum(a.nbytes for a in (self._bank, self._covariance, self._cross, self._cbb, self._weights, self._reference_bipolar, self._valid)))
        self.construction_seconds = time.perf_counter() - started

    def _indices(self, value):
        return _index_vector(value, self.point_count, count=64)

    def _noise(self, snr_db):
        snr = float(snr_db)
        if not np.isfinite(snr):
            raise ValueError("SNR must be finite")
        with np.errstate(over="ignore", under="ignore"):
            ratio = float(np.power(10., -snr / 10))
        _positive(ratio, "normalized noise variance")
        _positive(ratio * self.reference_mean_contrast_signal_power_v2, "physical noise variance")
        return snr, ratio

    def _baseline(self, snr_db):
        snr, noise = self._noise(snr_db)
        if snr not in self._baseline_cache:
            factor = cho_factor(self._cbb + noise * np.eye(63), lower=True, check_finite=False)
            estimate = cho_solve(factor, self._cbb, check_finite=False)
            value = float(np.sum(self._cbb * estimate.T) / self._target_energy)
            if not 0 < value <= 1 + 1e-10:
                raise FloatingPointError("invalid reference explained energy")
            self._baseline_cache[snr] = value
        return self._baseline_cache[snr]

    def make_state(self, indices, *, snr_db=20):
        """Cholesky evaluation of one layout, default field-only 20 dB score."""
        selected = self._indices(indices)
        snr, noise = self._noise(snr_db)
        covariance = self._covariance[np.ix_(selected, selected)]
        covariance = .5 * (covariance + covariance.T) + noise * np.eye(64)
        inverse = cho_solve(cho_factor(covariance, lower=True, check_finite=False), np.eye(64), check_finite=False)
        inverse = .5 * (inverse + inverse.T)
        cross = self._cross[:, selected]
        weighted_cross = cross @ inverse
        inverse_one = inverse.sum(axis=1)
        projected_one = cross @ inverse_one
        reference_precision = float(inverse_one.sum())
        if reference_precision <= 0:
            raise FloatingPointError("invalid common-reference precision")
        absolute = float((np.sum(weighted_cross * cross) - np.dot(projected_one, projected_one) / reference_precision) / self._target_energy)
        if not np.isfinite(absolute) or not -1e-9 <= absolute <= 1 + 1e-9:
            raise FloatingPointError("candidate explained energy outside numerical bounds")
        return LayoutScoreState(_readonly(selected), snr, absolute, absolute / self._baseline(snr), self._owner, _readonly(inverse))

    def _check_state(self, state):
        if not isinstance(state, LayoutScoreState) or state._owner is not self._owner:
            raise ValueError("state belongs to a different covariance bank")

    def _position(self, position):
        if not isinstance(position, (int, np.integer)) or isinstance(position, (bool, np.bool_)) or not 0 <= position < 64:
            raise ValueError("position must be an integer in [0,63]")
        return int(position)

    def apply_exchange(self, state, position, candidate_index):
        """Accept one replacement and rebuild Cholesky state; no update drift."""
        self._check_state(state)
        position = self._position(position)
        candidate = _index_vector(np.asarray([candidate_index]), self.point_count, count=1, name="candidate index")[0]
        indices = state.indices.copy()
        indices[position] = candidate
        return self.make_state(indices, snr_db=state.snr_db)

    def _tails(self, bipolar):
        count = bipolar.shape[0]
        if not self._sensitivity_available:
            return np.full(count, np.nan)
        ratios = bipolar[:, self._valid] / self._reference_bipolar[self._valid]
        weights = self._weights[self._valid]
        weights = weights / weights.sum()
        order = np.argsort(ratios, axis=1, kind="stable")
        sorted_weights = weights[order]
        previous = np.cumsum(sorted_weights, axis=1) - sorted_weights
        taken = np.clip(self._fraction - previous, 0, sorted_weights)
        return np.sum(taken * np.take_along_axis(ratios, order, axis=1), axis=1) / self._fraction

    def sensitivity_tail(self, indices):
        """Exact area-weighted lower tail of source bipolar-amplitude ratios.

        None means the exploratory numerical-zero exclusion budget failed.
        This is not a certified forward-error threshold or a formal AR score.
        """
        indices = self._indices(indices)
        if not self._sensitivity_available:
            return None
        return float(self._tails(np.ptp(self._bank[indices], axis=0)[None, :])[0])

    def batch_sensitivity_tail(self, layouts, *, chunk_size=8):
        """One scalar per 64-index row; unavailable results are explicit NaN."""
        layouts = np.asarray(layouts)
        if layouts.ndim != 2 or layouts.shape[1] != 64 or layouts.dtype.kind not in "iu":
            raise ValueError("layouts must be an integer (N,64) array")
        if not isinstance(chunk_size, (int, np.integer)) or chunk_size < 1:
            raise ValueError("chunk_size must be a positive integer")
        for row in layouts:
            self._indices(row)
        result = np.empty(len(layouts))
        for start in range(0, len(layouts), int(chunk_size)):
            part = layouts[start:start + int(chunk_size)]
            result[start:start + len(part)] = self._tails(np.ptp(self._bank[part], axis=1))
        return result

    def score_exchanges(self, state, position, candidate_indices=None, *, chunk_size=256, include_sensitivity=False):
        """Batch Schur-complement scores for one replaceable position.

        Only integer index membership is enforced here. The caller MUST enforce
        its own region membership, allocation, area and point-spacing constraints.
        Sparse/nearzero Schur cancellation falls back to direct Cholesky rather
        than clipping denominators or silently creating a better score.
        """
        self._check_state(state)
        position = self._position(position)
        if not isinstance(chunk_size, (int, np.integer)) or chunk_size < 1:
            raise ValueError("chunk_size must be a positive integer")
        if not isinstance(include_sensitivity, bool):
            raise ValueError("include_sensitivity must be boolean")
        if candidate_indices is None:
            candidate_indices = np.arange(self.point_count)
        candidates = _index_vector(candidate_indices, self.point_count, name="candidate_indices")
        keep = np.delete(np.arange(64), position)
        retained = state.indices[keep]
        candidates = candidates[~np.isin(candidates, retained)]
        w = state._inverse_covariance
        reduced = w[np.ix_(keep, keep)] - np.outer(w[keep, position], w[position, keep]) / w[position, position]
        reduced = .5 * (reduced + reduced.T)
        cross = self._cross[:, retained]
        reduced_cross = cross @ reduced
        trace = float(np.sum(reduced_cross * cross))
        inverse_one = reduced.sum(axis=1)
        one_precision = float(inverse_one.sum())
        projected_one = cross @ inverse_one
        _, noise = self._noise(state.snr_db)
        absolute = np.empty(len(candidates))
        sensitivity = np.empty(len(candidates)) if include_sensitivity else None
        if include_sensitivity:
            remaining = self._bank[retained]
            minimum, maximum = remaining.min(axis=0), remaining.max(axis=0)
        fallbacks = 0
        for start in range(0, len(candidates), int(chunk_size)):
            part = candidates[start:start + int(chunk_size)]
            cov = self._covariance[np.ix_(retained, part)]
            solved = reduced @ cov
            diagonal = self._covariance[part, part] + noise
            schur = diagonal - np.sum(cov * solved, axis=0)
            innovations = self._cross[:, part] - reduced_cross @ cov
            residual_one = 1 - inverse_one @ cov
            # Any well-resolved SPD Schur variance is at least the added noise.
            bad = (~np.isfinite(schur)) | (schur < noise * .5)
            safe_schur = np.where(bad, 1., schur)
            t = trace + np.sum(innovations**2, axis=0) / safe_schur
            projected = projected_one[:, None] + innovations * (residual_one / safe_schur)
            p = one_precision + residual_one**2 / safe_schur
            values = (t - np.sum(projected**2, axis=0) / p) / self._target_energy
            bad |= (~np.isfinite(values)) | (values < -1e-9) | (values > 1 + 1e-9)
            for local in np.flatnonzero(bad):
                values[local] = self.apply_exchange(state, position, int(part[local])).field_absolute
                fallbacks += 1
            absolute[start:start + len(part)] = values
            if sensitivity is not None:
                point_fields = self._bank[part]
                bipolar = np.maximum(maximum, point_fields) - np.minimum(minimum, point_fields)
                sensitivity[start:start + len(part)] = self._tails(bipolar)
        return ExchangeScores(_readonly(candidates), _readonly(absolute), _readonly(absolute / self._baseline(state.snr_db)), None if sensitivity is None else _readonly(sensitivity), fallbacks)

    def evaluate(self, indices, *, snr_db=(0, 10, 20)):
        """Final three-SNR report using direct Cholesky, never a search estimate."""
        selected = self._indices(indices)
        snrs = tuple(snr_db)
        if not snrs:
            raise ValueError("at least one SNR is required")
        # Form this small final diagnostic from centered fields rather than
        # subtracting nearly equal covariance entries for rank-zero clusters.
        centered = self._bank[selected] - self._bank[selected[:1]]
        centered -= centered.mean(axis=0, keepdims=True)
        hx = self._contrast @ centered
        cxx = (hx * self._weights) @ hx.T
        rank = participation_effective_rank(cxx)
        conditions = []
        for snr in snrs:
            state = self.make_state(selected, snr_db=snr)
            _, noise = self._noise(snr)
            variance = self.reference_mean_contrast_signal_power_v2 * noise
            conditions.append({"nominal_reference_snr_db": state.snr_db,
                "shared_physical_electrode_noise_variance_v2": variance,
                "shared_physical_electrode_noise_std_uv": float(np.sqrt(variance) * 1e6),
                "reference_field_explained_energy": self._baseline(snr),
                "candidate_field_explained_energy": state.field_absolute,
                "field_retention_unclipped": state.field_relative,
                "reference_noise_whitened_area_weighted_effective_rank": self._reference_rank,
                "candidate_noise_whitened_area_weighted_effective_rank": rank,
                "baseline_identity_field_retention": 1.})
        return {"schema_version": "compact-eeg-layout-search-metrics/1",
            "scientific_role": "exploratory_fixed64_field_and_sensitivity_scoring",
            "formal_v2_performance_eligible": False, "ar_computed": False,
            "classification_accuracy_computed": False, "global_optimum_certified": False,
            "physical_electrodes_per_layout": 64, "reference_free_dimensions": 63,
            "source_count": self.source_count, "candidate_bank_point_count": self.point_count,
            "source_moment_am": self.source_moment_am,
            "reference_mean_contrast_signal_power_v2": self.reference_mean_contrast_signal_power_v2,
            "conditions": conditions,
            "source_sensitivity": {"area_weighted_lower_tail_retention_unclipped": self.sensitivity_tail(selected),
                "source_tail_fraction": self._fraction, "numerical_zero_relative_tolerance": self._tolerance,
                "bipolar_denominator_threshold_v_per_am": self._threshold_original,
                "excluded_source_area_fraction": self._excluded_area, "excluded_source_count": int((~self._valid).sum()),
                "numerical_zero_rule": "exploratory_unvalidated_relative_voltage_tolerance_not_solver_residual_or_certified_forward_error_bound"},
            "interpretation": "Field retention and sensitivity are separate metrics. Default field20 search does not establish sensitivity/localization optimality; spatial feasibility and joint objective selection belong to the caller."}


__all__ = ["LayoutSearchMetrics", "LayoutScoreState", "ExchangeScores"]


def _benchmark_cli():
    """Read existing payloads only; print timings and original-function checks."""
    import argparse
    import hashlib
    import json
    from pathlib import Path
    from .prototype_metrics import evaluate_prototype_metrics

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-forward", type=Path, required=True)
    parser.add_argument("--benchmark-metrics", type=Path, required=True)
    args = parser.parse_args()
    forward = np.load(args.benchmark_forward, allow_pickle=False)
    metrics = np.load(args.benchmark_metrics, allow_pickle=False)
    weights = metrics["source_area_weights"]
    bank = forward["leadfield_v_per_am"][:, :len(weights)]
    indices = forward["layout_leadfield_row_indices"][2]
    engine = LayoutSearchMetrics(bank, bank[:64], weights)
    state = engine.make_state(indices)
    engine.score_exchanges(state, 13)
    start = time.perf_counter()
    for _ in range(20):
        fast = engine.score_exchanges(state, 13)
    field_seconds = (time.perf_counter() - start) / 20
    start = time.perf_counter()
    engine.score_exchanges(state, 13, include_sensitivity=True, chunk_size=64)
    sensitivity_seconds = time.perf_counter() - start
    sample = np.linspace(0, len(fast.candidate_indices) - 1, min(16, len(fast.candidate_indices))).astype(int)
    error = 0.
    for index in sample:
        trial = indices.copy()
        trial[13] = fast.candidate_indices[index]
        golden = evaluate_prototype_metrics(bank[:64], bank[trial], weights,
            source_moment_am=1e-8, numerical_zero_relative_tolerance=1e-8, snr_db=(20,)).report
        error = max(error, abs(float(fast.field_relative[index]) - golden["conditions"][0]["field_retention_unclipped"]))
    result = {"bank_shape": list(bank.shape), "cache_construction_seconds": engine.construction_seconds,
        "cache_bytes": engine.cache_bytes, "eligible_exchange_candidates": len(fast.candidate_indices),
        "field_seconds_20repeat_mean": field_seconds, "field_plus_sensitivity_seconds": sensitivity_seconds,
        "original_function_comparison_count": len(sample), "maximum_relative_score_difference": error,
        "direct_schur_fallback_count": fast.direct_fallback_count,
        "source_payload_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (args.benchmark_forward, args.benchmark_metrics)},
        "formal_v2_performance_eligible": False, "ar_computed": False,
        "interpretation": "Existing-bank computation only; not a new FEM run, optimization result, or universal runtime estimate."}
    print(json.dumps(result, indent=2), flush=True)
    if error > 1e-10:
        raise SystemExit("original-function numerical comparison failed")


if __name__ == "__main__":
    _benchmark_cli()
