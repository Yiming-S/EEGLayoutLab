"""Covariance-cache LMMSE scores for exploratory fixed-64 coordinate exchange.

The reference supplies the clean target, area-weighted source prior and ONE
physical noise scale. Each candidate observes only its own 63-dimensional
reference-free field. No classifier, AR certificate or global optimum is claimed.

For K=C_SS+lambda*I, U=C_BS and a vector of ones e, the contrast precision is
  W = K^-1 - K^-1 e (e.T K^-1 e)^-1 e.T K^-1.
Thus explained energy is tr(U W U.T)/tr(C_BB), exactly the Helmert LMMSE
quantity. By orthogonal Helmert block factorization Q = [P; e.T / sqrt(k)],
the reference-free log-determinant satisfies
  log det(P K P.T) = log det(K) + log(e.T K^-1 e) - log(k),
yielding exact O(1) per-candidate Shannon mutual information updates alongside
rank-1 Schur field updates. Exchange scoring uses block inversion of the
retained 63 electrodes; accepted layouts rebuild a Cholesky factorization.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import time

import numpy as np
from scipy.linalg import cho_factor, cho_solve, solve_triangular

from .metrics import helmert_contrast, participation_effective_rank
from .noise_models import gaussian_cross, spatial_correlation

COMPOSITE_WEIGHTS = (0.55, 0.30, 0.15)


def combine_search_objective(field_relative, sensitivity_tail, info_relative=None, *, objective_mode="min"):
    """Evaluate search objective scalar or array for ``min`` or ``composite`` mode."""
    if objective_mode == "min":
        return np.minimum(field_relative, sensitivity_tail) if isinstance(field_relative, np.ndarray) else float(min(field_relative, sensitivity_tail))
    if objective_mode == "composite":
        if info_relative is None:
            raise ValueError("info_relative is required when objective_mode='composite'")
        w_min, w_field, w_info = COMPOSITE_WEIGHTS
        val = w_min * np.minimum(field_relative, sensitivity_tail) + w_field * field_relative + w_info * info_relative
        return val if isinstance(field_relative, np.ndarray) else float(val)
    raise ValueError(f"Unsupported objective_mode: {objective_mode}")


def _whitened_rank(information, noise):
    """Participation rank of L^-1 information L^-T for contrast noise N = L L^T."""
    factor = np.linalg.cholesky(.5 * (noise + noise.T))
    whitened = solve_triangular(factor, solve_triangular(factor, information, lower=True).T, lower=True)
    return participation_effective_rank(.5 * (whitened + whitened.T))


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
    information_relative: float = 0.0


@dataclass(frozen=True)
class ExchangeScores:
    """Candidates exclude the other 63 occupied points; original order preserved."""
    candidate_indices: np.ndarray
    field_absolute: np.ndarray
    field_relative: np.ndarray
    sensitivity_tail: np.ndarray | None
    direct_fallback_count: int
    information_relative: np.ndarray | None = None


@dataclass(frozen=True)
class PartialScoreState:
    """Validated k-electrode subset (2 <= k <= 63) for sequential Schur addition."""
    indices: np.ndarray
    snr_db: float
    field_absolute: float
    field_relative: float
    _owner: object
    _inverse_covariance: np.ndarray
    information_relative: float = 0.0


@dataclass(frozen=True)
class PrunedMoveResult:
    """Exact argmax above threshold for min or composite search objective."""
    best_candidate: int | None
    field_absolute: float | None
    field_relative: float | None
    sensitivity_tail: float | None
    objective: float | None
    candidate_count: int
    field_survivor_count: int
    cvar_survivor_count: int
    exact_tail_evaluations: int
    direct_fallback_count: int
    information_relative: float | None = None


class LayoutSearchMetrics:
    """Fast scalar scoring on a shared M x Q point lead-field bank."""

    def __init__(
        self, candidate_leadfield, reference_leadfield, source_area_weights, *,
        source_moment_am=1e-8, numerical_zero_relative_tolerance=1e-8,
        source_tail_fraction=.1, maximum_excluded_source_area_fraction=.001,
        covariance_block_size=256, noise_kernel=None,
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
        self._set_noise_kernel(noise_kernel)
        self._reference_bipolar = np.ptp(reference_centered, axis=0) / scale / normalization
        threshold_original = 2 * tolerance * float(np.max(np.abs(reference_centered)))
        self._valid = np.ptp(reference_centered, axis=0) > threshold_original
        self._fraction = fraction
        self._excluded_area = float(weights[~self._valid].sum())
        self._sensitivity_available = bool(np.any(self._valid) and self._excluded_area <= budget)
        self._tolerance = tolerance
        self._threshold_original = threshold_original
        if self._sensitivity_available:
            valid_w = weights[self._valid]
            self._valid_weights_norm = _readonly(valid_w / valid_w.sum())
            self._valid_ref_bipolar = _readonly(self._reference_bipolar[self._valid])
            self._valid_bank = _readonly(np.ascontiguousarray(self._bank[:, self._valid]))
        else:
            self._valid_weights_norm = None
            self._valid_ref_bipolar = None
            self._valid_bank = None
        self.cache_bytes = int(sum(a.nbytes for a in (self._bank, self._covariance, self._cross, self._cbb, self._weights, self._reference_bipolar, self._valid)))
        self.construction_seconds = time.perf_counter() - started

    def _set_noise_kernel(self, noise_kernel):
        self._kernel = None
        self._reference_noise = np.eye(63)
        if noise_kernel is None:
            self._reference_rank = participation_effective_rank(self._cbb)
        else:
            candidate_xyz, reference_xyz, rho, length = noise_kernel
            candidate_xyz = np.asarray(candidate_xyz, dtype=np.float64)
            if candidate_xyz.shape != (self.point_count, 3) or not np.all(np.isfinite(candidate_xyz)):
                raise ValueError("noise kernel needs one finite xyz row per candidate")
            self._kernel = (_readonly(candidate_xyz), float(rho), float(length))
            reference_noise = self._contrast @ spatial_correlation(reference_xyz, float(rho), float(length)) @ self._contrast.T
            self._reference_noise = .5 * (reference_noise + reference_noise.T)
            self._reference_rank = _whitened_rank(self._cbb, self._reference_noise)
        self._baseline_cache = {}
        self._info_baseline_cache = {}

    def with_noise_kernel(self, noise_kernel):
        """Engine sharing this bank's signal caches under another noise model; states are not interchangeable."""
        engine = copy.copy(self)
        engine._owner = object()
        engine._set_noise_kernel(noise_kernel)
        return engine

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
            factor = cho_factor(self._cbb + noise * self._reference_noise, lower=True, check_finite=False)
            estimate = cho_solve(factor, self._cbb, check_finite=False)
            value = float(np.sum(self._cbb * estimate.T) / self._target_energy)
            if not 0 < value <= 1 + 1e-10:
                raise FloatingPointError("invalid reference explained energy")
            self._baseline_cache[snr] = value
        return self._baseline_cache[snr]

    def _info_baseline(self, snr_db):
        snr, noise = self._noise(snr_db)
        if snr not in self._info_baseline_cache:
            chol_tot = cho_factor(self._cbb + noise * self._reference_noise, lower=True, check_finite=False)[0]
            logdet_tot = 2.0 * float(np.sum(np.log(np.diag(chol_tot))))
            if self._kernel is None:
                logdet_noise = 63.0 * float(np.log(noise))
            else:
                chol_n = cho_factor(noise * self._reference_noise, lower=True, check_finite=False)[0]
                logdet_noise = 2.0 * float(np.sum(np.log(np.diag(chol_n))))
            info = 0.5 * (logdet_tot - logdet_noise)
            if not np.isfinite(info) or info <= 0:
                raise FloatingPointError("invalid reference Shannon mutual information")
            self._info_baseline_cache[snr] = info
        return self._info_baseline_cache[snr]

    def _subset_info_relative(self, selected, chol_k, reference_precision, snr, noise):
        k = len(selected)
        logdet_k = 2.0 * float(np.sum(np.log(np.diag(chol_k))))
        if self._kernel is None:
            logdet_m_term = (k - 1) * float(np.log(noise)) + float(np.log(k))
        else:
            m_mat = noise * self._noise_matrix(selected)
            m_mat = .5 * (m_mat + m_mat.T)
            f_m = cho_factor(m_mat, lower=True, check_finite=False)
            logdet_m = 2.0 * float(np.sum(np.log(np.diag(f_m[0]))))
            m_one_prec = float(np.sum(cho_solve(f_m, np.ones(k), check_finite=False)))
            logdet_m_term = logdet_m + float(np.log(max(1e-30, m_one_prec)))
        info_cand = max(0.0, 0.5 * (logdet_k + float(np.log(reference_precision)) - logdet_m_term))
        return info_cand / self._info_baseline(snr)

    def information_retention(self, indices, *, snr_db=20):
        """Exact 63D reference-free Shannon mutual information relative to standard64."""
        selected = _index_vector(indices, self.point_count, name="indices")
        if not 2 <= len(selected) <= 64:
            raise ValueError("indices must contain between 2 and 64 unique points")
        st = self.make_state(selected, snr_db=snr_db) if len(selected) == 64 else self.make_partial_state(selected, snr_db=snr_db)
        return float(st.information_relative)

    def make_state(self, indices, *, snr_db=20):
        """Cholesky evaluation of one layout, default field-only 20 dB score."""
        selected = self._indices(indices)
        snr, noise = self._noise(snr_db)
        covariance = self._covariance[np.ix_(selected, selected)]
        covariance = .5 * (covariance + covariance.T) + noise * self._noise_matrix(selected)
        factor = cho_factor(covariance, lower=True, check_finite=False)
        inverse = cho_solve(factor, np.eye(64), check_finite=False)
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
        info_rel = self._subset_info_relative(selected, factor[0], reference_precision, snr, noise)
        return LayoutScoreState(_readonly(selected), snr, absolute, absolute / self._baseline(snr),
                                self._owner, _readonly(inverse), info_rel)

    def _noise_matrix(self, selected):
        if self._kernel is None:
            return np.eye(len(selected))
        xyz, rho, length = self._kernel
        return spatial_correlation(xyz[selected], rho, length)

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
        """Exact area-weighted lower tail of source bipolar-amplitude ratios."""
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

    def score_exchanges(self, state, position, candidate_indices=None, *, chunk_size=256,
                        include_sensitivity=False, include_information=False):
        """Batch Schur-complement scores for one replaceable position."""
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
        absolute, relative, info_rel, fallbacks = self._schur_field_scores(
            retained, reduced, state.snr_db, candidates,
            chunk_size=chunk_size, include_information=include_information,
            position_for_fallback=position, parent_state=state)
        sensitivity = None
        if include_sensitivity:
            sensitivity = np.empty(len(candidates))
            if not self._sensitivity_available:
                sensitivity.fill(np.nan)
            elif len(candidates):
                remaining = self._bank[retained]
                minimum, maximum = remaining.min(axis=0), remaining.max(axis=0)
                for start in range(0, len(candidates), int(chunk_size)):
                    part = candidates[start:start + int(chunk_size)]
                    point_fields = self._bank[part]
                    bipolar = np.maximum(maximum, point_fields) - np.minimum(minimum, point_fields)
                    sensitivity[start:start + len(part)] = self._tails(bipolar)
        return ExchangeScores(
            _readonly(candidates), _readonly(absolute), _readonly(relative),
            None if sensitivity is None else _readonly(sensitivity), fallbacks,
            None if info_rel is None else _readonly(info_rel))

    def evaluate(self, indices, *, snr_db=(0, 10, 20)):
        """Final three-SNR report using direct Cholesky, never a search estimate."""
        selected = self._indices(indices)
        snrs = tuple(snr_db)
        if not snrs:
            raise ValueError("at least one SNR is required")
        centered = self._bank[selected] - self._bank[selected[:1]]
        centered -= centered.mean(axis=0, keepdims=True)
        hx = self._contrast @ centered
        cxx = (hx * self._weights) @ hx.T
        rank = participation_effective_rank(cxx) if self._kernel is None else \
            _whitened_rank(cxx, self._contrast @ self._noise_matrix(selected) @ self._contrast.T)
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
                "information_retention_unclipped": state.information_relative,
                "reference_noise_whitened_area_weighted_effective_rank": self._reference_rank,
                "candidate_noise_whitened_area_weighted_effective_rank": rank,
                "baseline_identity_field_retention": 1.,
                **({} if self._kernel is None else {"noise_correlation": {"kind": "spatial_gaussian",
                    "rho": self._kernel[1], "length_mm": self._kernel[2]}})})
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

    def diagonal_signal_power(self):
        """Normalized signal auto-covariance diagonal for each candidate vertex."""
        return np.diag(self._covariance).copy()

    def _dual_from_valid_bipolar(self, valid_bipolar_1d):
        ratios = valid_bipolar_1d / self._valid_ref_bipolar
        order = np.argsort(ratios, kind="stable")
        sorted_w = self._valid_weights_norm[order]
        previous = np.cumsum(sorted_w) - sorted_w
        taken = np.clip(self._fraction - previous, 0., sorted_w)
        exact = float(np.sum(taken * ratios[order]) / self._fraction)
        nz = np.flatnonzero(taken > 0.)
        return exact, _readonly(order[nz]), _readonly(taken[nz] / self._fraction)

    def tail_dual_certificate(self, indices):
        """Exact sensitivity tail and lower-CVaR dual support for k >= 2 electrodes."""
        selected = _index_vector(indices, self.point_count, name="indices")
        if len(selected) < 2 or len(selected) > 64:
            raise ValueError("indices must contain between 2 and 64 unique points")
        if not self._sensitivity_available:
            return None
        bipolar = np.ptp(self._valid_bank[selected], axis=0)
        return self._dual_from_valid_bipolar(bipolar)

    def make_partial_state(self, indices, *, snr_db=20):
        """Cholesky LMMSE state for a k-electrode subset (2 <= k <= 63)."""
        selected = _index_vector(indices, self.point_count, name="indices")
        if not 2 <= len(selected) <= 63:
            raise ValueError("partial state requires between 2 and 63 unique indices")
        snr, noise = self._noise(snr_db)
        k = len(selected)
        covariance = self._covariance[np.ix_(selected, selected)]
        covariance = .5 * (covariance + covariance.T) + noise * self._noise_matrix(selected)
        factor = cho_factor(covariance, lower=True, check_finite=False)
        inverse = cho_solve(factor, np.eye(k), check_finite=False)
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
            raise FloatingPointError("partial candidate explained energy outside numerical bounds")
        info_rel = self._subset_info_relative(selected, factor[0], reference_precision, snr, noise)
        return PartialScoreState(_readonly(selected), snr, absolute, absolute / self._baseline(snr),
                                 self._owner, _readonly(inverse), info_rel)

    def _check_partial_state(self, state):
        if not isinstance(state, PartialScoreState) or state._owner is not self._owner:
            raise ValueError("partial state belongs to a different covariance bank")

    def _schur_field_scores(self, retained, reduced, snr_db, candidates, *, chunk_size=256,
                            include_information=False, position_for_fallback=None, parent_state=None):
        cross = self._cross[:, retained]
        reduced_cross = cross @ reduced
        trace = float(np.sum(reduced_cross * cross))
        inverse_one = reduced.sum(axis=1)
        one_precision = float(inverse_one.sum())
        projected_one = cross @ inverse_one
        snr, noise = self._noise(snr_db)
        floor = noise * .5 * (1. if self._kernel is None else 1. - self._kernel[1])
        absolute = np.empty(len(candidates))
        info_rel = np.empty(len(candidates)) if include_information else None
        fallbacks = 0
        is_full_exchange = len(retained) == 63
        new_k = len(retained) + 1
        if include_information and len(candidates):
            info_base = self._info_baseline(snr)
            k_rr = self._covariance[np.ix_(retained, retained)]
            k_rr = .5 * (k_rr + k_rr.T) + noise * self._noise_matrix(retained)
            chol_k_rr = cho_factor(k_rr, lower=True, check_finite=False)[0]
            logdet_k_rr = 2.0 * float(np.sum(np.log(np.diag(chol_k_rr))))
            if self._kernel is None:
                const_m_term = (new_k - 1) * float(np.log(noise)) + float(np.log(new_k))
                m_rr_inv = None
                inv_one_m = None
                one_prec_m = 0.0
                logdet_m_rr = 0.0
            else:
                m_rr = noise * self._noise_matrix(retained)
                m_rr = .5 * (m_rr + m_rr.T)
                f_m_rr = cho_factor(m_rr, lower=True, check_finite=False)
                logdet_m_rr = 2.0 * float(np.sum(np.log(np.diag(f_m_rr[0]))))
                m_rr_inv = cho_solve(f_m_rr, np.eye(len(retained)), check_finite=False)
                m_rr_inv = .5 * (m_rr_inv + m_rr_inv.T)
                inv_one_m = m_rr_inv.sum(axis=1)
                one_prec_m = float(inv_one_m.sum())
                const_m_term = 0.0

        for start in range(0, len(candidates), int(chunk_size)):
            part = candidates[start:start + int(chunk_size)]
            cov = self._covariance[np.ix_(retained, part)]
            m_rc = None
            if self._kernel is not None:
                xyz, rho, length = self._kernel
                m_rc = noise * gaussian_cross(xyz[retained], xyz[part], rho, length)
                cov = cov + m_rc
            solved = reduced @ cov
            diagonal = self._covariance[part, part] + noise
            schur = diagonal - np.sum(cov * solved, axis=0)
            innovations = self._cross[:, part] - reduced_cross @ cov
            residual_one = 1 - inverse_one @ cov
            bad = (~np.isfinite(schur)) | (schur < floor)
            safe_schur = np.where(bad, 1., schur)
            t = trace + np.sum(innovations**2, axis=0) / safe_schur
            projected = projected_one[:, None] + innovations * (residual_one / safe_schur)
            p = one_precision + residual_one**2 / safe_schur
            values = (t - np.sum(projected**2, axis=0) / p) / self._target_energy
            bad |= (~np.isfinite(values)) | (values < -1e-9) | (values > 1 + 1e-9)
            if include_information:
                logdet_k_new = logdet_k_rr + np.log(np.maximum(1e-30, safe_schur)) + np.log(np.maximum(1e-30, p))
                if self._kernel is None:
                    i_vals = np.maximum(0.0, 0.5 * (logdet_k_new - const_m_term)) / info_base
                else:
                    solved_m = m_rr_inv @ m_rc
                    schur_m = np.maximum(1e-30, noise - np.sum(m_rc * solved_m, axis=0))
                    res_one_m = 1.0 - inv_one_m @ m_rc
                    p_m = np.maximum(1e-30, one_prec_m + res_one_m**2 / schur_m)
                    logdet_m_new = logdet_m_rr + np.log(schur_m) + np.log(p_m)
                    i_vals = np.maximum(0.0, 0.5 * (logdet_k_new - logdet_m_new)) / info_base
            for local in np.flatnonzero(bad):
                if position_for_fallback is not None and parent_state is not None:
                    fb_state = self.apply_exchange(parent_state, position_for_fallback, int(part[local]))
                else:
                    trial = np.append(retained, int(part[local]))
                    fb_state = (self.make_state(trial, snr_db=snr_db) if is_full_exchange
                                else self.make_partial_state(trial, snr_db=snr_db))
                values[local] = fb_state.field_absolute
                if include_information:
                    i_vals[local] = fb_state.information_relative
                fallbacks += 1
            absolute[start:start + len(part)] = values
            if include_information:
                info_rel[start:start + len(part)] = i_vals
        return absolute, absolute / self._baseline(snr_db), info_rel, fallbacks

    def score_additions(self, partial_state, candidate_indices=None, *, chunk_size=256,
                        include_sensitivity=False, include_information=False):
        """Batch Schur-complement scores for adding one electrode to a partial subset."""
        self._check_partial_state(partial_state)
        if not isinstance(chunk_size, (int, np.integer)) or chunk_size < 1:
            raise ValueError("chunk_size must be a positive integer")
        if not isinstance(include_sensitivity, bool):
            raise ValueError("include_sensitivity must be boolean")
        if candidate_indices is None:
            candidate_indices = np.arange(self.point_count)
        candidates = _index_vector(candidate_indices, self.point_count, name="candidate_indices")
        retained = partial_state.indices
        candidates = candidates[~np.isin(candidates, retained)]
        absolute, relative, info_rel, fallbacks = self._schur_field_scores(
            retained, partial_state._inverse_covariance, partial_state.snr_db, candidates,
            chunk_size=chunk_size, include_information=include_information)
        sensitivity = None
        if include_sensitivity:
            sensitivity = np.empty(len(candidates))
            if not self._sensitivity_available:
                sensitivity.fill(np.nan)
            elif len(candidates):
                remaining = self._bank[retained]
                minimum, maximum = remaining.min(axis=0), remaining.max(axis=0)
                for start in range(0, len(candidates), int(chunk_size)):
                    part = candidates[start:start + int(chunk_size)]
                    point_fields = self._bank[part]
                    bipolar = np.maximum(maximum, point_fields) - np.minimum(minimum, point_fields)
                    sensitivity[start:start + len(part)] = self._tails(bipolar)
        return ExchangeScores(
            _readonly(candidates), _readonly(absolute), _readonly(relative),
            None if sensitivity is None else _readonly(sensitivity), fallbacks,
            None if info_rel is None else _readonly(info_rel))

    def _best_pruned_from_retained(self, retained, reduced, snr_db, candidate_indices, objective_floor,
                                   *, tol=1e-9, dual_hint=None, chunk_size=256, objective_mode="min"):
        if objective_mode not in ("min", "composite"):
            raise ValueError(f"Unsupported objective_mode: {objective_mode}")
        if not isinstance(chunk_size, (int, np.integer)) or chunk_size < 1:
            raise ValueError("chunk_size must be a positive integer")
        floor_val = float(objective_floor)
        tol_val = float(tol)
        if not np.isfinite(floor_val) or not np.isfinite(tol_val) or tol_val < 0:
            raise ValueError("objective_floor must be finite and tol nonnegative")
        if candidate_indices is None:
            candidate_indices = np.arange(self.point_count)
        candidates = _index_vector(candidate_indices, self.point_count, name="candidate_indices")
        candidates = candidates[~np.isin(candidates, retained)]
        total_count = len(candidates)
        if not total_count or not self._sensitivity_available:
            return PrunedMoveResult(None, None, None, None, None, total_count, 0, 0, 0, 0, None)
        need_info = objective_mode == "composite"
        f_abs_all, f_rel_all, info_all, fallbacks = self._schur_field_scores(
            retained, reduced, snr_db, candidates, chunk_size=chunk_size, include_information=need_info)
        threshold = floor_val + tol_val
        if need_info:
            w_min, w_field, w_info = COMPOSITE_WEIGHTS
            # Since min(f, s) <= f, (w_min + w_field)*f + w_info*info is an exact zero-cost upper bound!
            fast_ub = (w_min + w_field) * f_rel_all + w_info * info_all
            f_mask = np.isfinite(f_rel_all) & np.isfinite(info_all) & (fast_ub > threshold)
        else:
            f_mask = np.isfinite(f_rel_all) & (f_rel_all > threshold)
        field_survivors = int(np.count_nonzero(f_mask))
        if not field_survivors:
            return PrunedMoveResult(None, None, None, None, None, total_count, 0, 0, 0, fallbacks, None)
        cand_f = candidates[f_mask]
        f_abs = f_abs_all[f_mask]
        f_rel = f_rel_all[f_mask]
        i_rel = info_all[f_mask] if need_info else None
        rem = self._valid_bank[retained]
        rem_min, rem_max = rem.min(axis=0), rem.max(axis=0)
        _, cols_rem, w_rem = self._dual_from_valid_bipolar(rem_max - rem_min)
        fp_slack = 1e-11

        def dual_tail_ub(sub_cands, d_cols, d_w):
            pf = self._valid_bank[np.ix_(sub_cands, d_cols)]
            bip = np.maximum(rem_max[d_cols], pf) - np.minimum(rem_min[d_cols], pf)
            return (bip / self._valid_ref_bipolar[d_cols]) @ d_w + fp_slack

        s_ub = dual_tail_ub(cand_f, cols_rem, w_rem)
        ub = combine_search_objective(f_rel, s_ub, i_rel, objective_mode=objective_mode)
        if dual_hint is not None:
            alive = np.flatnonzero(ub > threshold)
            if len(alive):
                cols_h, w_h = dual_hint
                s_ub[alive] = np.minimum(s_ub[alive], dual_tail_ub(cand_f[alive], cols_h, w_h))
                ub[alive] = combine_search_objective(
                    f_rel[alive], s_ub[alive], None if i_rel is None else i_rel[alive],
                    objective_mode=objective_mode)
        c_mask = np.flatnonzero(ub > threshold)
        cvar_survivors = int(len(c_mask))
        if not cvar_survivors:
            return PrunedMoveResult(None, None, None, None, None, total_count, field_survivors, 0, 0, fallbacks, None)
        order = c_mask[np.lexsort((c_mask, -ub[c_mask]))]
        best_local = -1
        best_obj = threshold
        best_sens = None
        exact_evals = 0
        for idx_pos, s in enumerate(order):
            s = int(s)
            cutoff = best_obj - 1e-12 if best_local != -1 else threshold
            if ub[s] <= cutoff:
                continue
            pf = self._valid_bank[cand_f[s]]
            bip = np.maximum(rem_max, pf) - np.minimum(rem_min, pf)
            s_val, s_cols, s_w = self._dual_from_valid_bipolar(bip)
            exact_evals += 1
            if not np.isfinite(s_val):
                continue
            obj = combine_search_objective(
                float(f_rel[s]), s_val, None if i_rel is None else float(i_rel[s]),
                objective_mode=objective_mode)
            if best_local == -1:
                if obj > threshold:
                    best_local, best_obj, best_sens = s, obj, s_val
            elif obj > best_obj or (obj == best_obj and s < best_local):
                best_local, best_obj, best_sens = s, obj, s_val
            if s_val < s_ub[s] - 1e-4 and len(order) - idx_pos > 6:
                rem_order = order[idx_pos + 1:]
                next_cut = best_obj - 1e-12 if best_local != -1 else threshold
                still_live = rem_order[ub[rem_order] > next_cut]
                if len(still_live) > 4:
                    s_ub[still_live] = np.minimum(s_ub[still_live], dual_tail_ub(cand_f[still_live], s_cols, s_w))
                    ub[still_live] = combine_search_objective(
                        f_rel[still_live], s_ub[still_live], None if i_rel is None else i_rel[still_live],
                        objective_mode=objective_mode)
        if best_local == -1:
            return PrunedMoveResult(None, None, None, None, None, total_count,
                                    field_survivors, cvar_survivors, exact_evals, fallbacks, None)
        return PrunedMoveResult(
            int(cand_f[best_local]), float(f_abs[best_local]), float(f_rel[best_local]),
            float(best_sens), float(best_obj), total_count,
            field_survivors, cvar_survivors, exact_evals, fallbacks,
            None if i_rel is None else float(i_rel[best_local]))

    def best_pruned_exchange(self, state, position, candidate_indices=None, *,
                             objective_floor, tol=1e-9, dual_hint=None, chunk_size=256,
                             objective_mode="min"):
        """Exact argmax exchange above objective_floor + tol via Schur + CVaR bounds."""
        self._check_state(state)
        position = self._position(position)
        keep = np.delete(np.arange(64), position)
        retained = state.indices[keep]
        w = state._inverse_covariance
        reduced = w[np.ix_(keep, keep)] - np.outer(w[keep, position], w[position, keep]) / w[position, position]
        reduced = .5 * (reduced + reduced.T)
        return self._best_pruned_from_retained(
            retained, reduced, state.snr_db, candidate_indices, objective_floor,
            tol=tol, dual_hint=dual_hint, chunk_size=chunk_size, objective_mode=objective_mode)

    def best_pruned_addition(self, partial_state, candidate_indices=None, *,
                             objective_floor=-1.0, tol=0.0, dual_hint=None, chunk_size=256,
                             objective_mode="min"):
        """Exact argmax addition above objective_floor + tol for a partial subset."""
        self._check_partial_state(partial_state)
        return self._best_pruned_from_retained(
            partial_state.indices, partial_state._inverse_covariance, partial_state.snr_db,
            candidate_indices, objective_floor, tol=tol, dual_hint=dual_hint, chunk_size=chunk_size,
            objective_mode=objective_mode)


__all__ = [
    "LayoutSearchMetrics", "LayoutScoreState", "ExchangeScores", "PartialScoreState",
    "PrunedMoveResult", "COMPOSITE_WEIGHTS", "combine_search_objective",
]


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
