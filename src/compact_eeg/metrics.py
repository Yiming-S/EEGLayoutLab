"""Reference-free and information diagnostics independent of a head-model solver."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np


def helmert_contrast(node_count: int) -> np.ndarray:
    """Return an orthonormal (n-1) x n matrix that removes common reference."""
    if not isinstance(node_count, int) or node_count < 2:
        raise ValueError("node_count must be an integer >= 2")
    contrast = np.zeros((node_count - 1, node_count), dtype=float)
    for row in range(1, node_count):
        scale = np.sqrt(row * (row + 1.0))
        contrast[row - 1, :row] = 1.0 / scale
        contrast[row - 1, row] = -row / scale
    return contrast


def lower_cvar(values: Sequence[float] | np.ndarray, fraction: float) -> float:
    """Mean over exactly the lowest empirical probability mass fraction.

    Observations have equal probability.  A fractional boundary observation is
    included when ``fraction * n`` is not an integer, matching weighted CVaR.
    """
    array = np.asarray(values, dtype=float).reshape(-1)
    return weighted_lower_cvar(array, np.ones(array.size), fraction)


def weighted_lower_cvar(
    values: Sequence[float] | np.ndarray,
    weights: Sequence[float] | np.ndarray,
    fraction: float,
) -> float:
    """Area-weighted mean over the lowest probability mass fraction."""
    if not 0 < fraction <= 1:
        raise ValueError("fraction must lie in (0, 1]")
    array = np.asarray(values, dtype=float).reshape(-1)
    mass = np.asarray(weights, dtype=float).reshape(-1)
    if array.size == 0 or array.shape != mass.shape:
        raise ValueError("values and weights must be non-empty arrays of equal length")
    if not np.all(np.isfinite(array)) or not np.all(np.isfinite(mass)):
        raise ValueError("values and weights must be finite")
    if np.any(mass < 0) or float(mass.sum()) <= 0:
        raise ValueError("weights must be non-negative with positive total")

    mass = mass / float(mass.sum())
    order = np.argsort(array, kind="stable")
    sorted_values = array[order]
    sorted_mass = mass[order]
    remaining = fraction
    integral = 0.0
    for value, probability in zip(sorted_values, sorted_mass, strict=True):
        taken = min(float(probability), remaining)
        integral += float(value) * taken
        remaining -= taken
        if remaining <= np.finfo(float).eps:
            break
    return integral / fraction


def participation_effective_rank(information: np.ndarray, tolerance: float = 1e-12) -> float:
    """Scale-invariant participation rank of a positive semidefinite matrix.

    ``tolerance`` is a relative spectral tolerance for negative eigenvalues,
    not an absolute signal-energy cutoff.  Only the exactly zero matrix has
    rank zero.  Small negative roundoff eigenvalues are clipped to zero.
    """
    matrix = np.asarray(information, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or not matrix.size:
        raise ValueError("information must be non-empty and square")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("information must be finite")
    if not np.isfinite(tolerance) or not 0 <= tolerance < 1:
        raise ValueError("tolerance must be finite and lie in [0, 1)")
    scale = float(np.max(np.abs(matrix)))
    if scale == 0:
        return 0.0
    normalized = matrix / scale
    if not np.allclose(normalized, normalized.T, atol=1e-10, rtol=1e-10):
        raise ValueError("information must be symmetric")
    eigenvalues = np.linalg.eigvalsh(0.5 * (normalized + normalized.T))
    spectral_scale = float(np.max(np.abs(eigenvalues)))
    if eigenvalues[0] < -tolerance * spectral_scale:
        raise ValueError("information must be positive semidefinite")
    eigenvalues = np.maximum(eigenvalues / spectral_scale, 0.0)
    total = float(eigenvalues.sum())
    return total * total / float(eigenvalues @ eigenvalues)


def lmmse_explained_energy(cov_target: np.ndarray, cov_target_observation: np.ndarray, cov_observation: np.ndarray) -> float:
    """Fraction of target covariance energy explained by its LMMSE estimate."""
    czz = np.asarray(cov_target, dtype=float)
    czy = np.asarray(cov_target_observation, dtype=float)
    cyy = np.asarray(cov_observation, dtype=float)
    if czz.ndim != 2 or czz.shape[0] != czz.shape[1]:
        raise ValueError("cov_target must be square")
    if czy.shape[0] != czz.shape[0]:
        raise ValueError("target-observation covariance has incompatible target dimension")
    if cyy.shape != (czy.shape[1], czy.shape[1]):
        raise ValueError("cov_observation has incompatible shape")
    denominator = float(np.trace(czz))
    if denominator <= 0:
        raise ValueError("target covariance must have positive trace")
    explained = float(np.trace(np.linalg.solve(cyy, czy.T @ czy)))
    return explained / denominator


def relative_retention(candidate_score: float, reference_score: float) -> float:
    """Unclipped candidate/reference retention for a positive reference score."""
    if not np.isfinite(candidate_score) or not np.isfinite(reference_score):
        raise ValueError("scores must be finite")
    if reference_score <= 0:
        raise ValueError("reference score must be positive")
    return float(candidate_score / reference_score)


def localization_utility(errors_mm: Sequence[float] | np.ndarray, d_max_mm: float = 50.0) -> np.ndarray:
    """Bounded area-under-success-curve utility for absolute localization error."""
    if not np.isfinite(d_max_mm) or d_max_mm <= 0:
        raise ValueError("d_max_mm must be positive and finite")
    errors = np.asarray(errors_mm, dtype=float)
    if not np.all(np.isfinite(errors)) or np.any(errors < 0):
        raise ValueError("localization errors must be non-negative and finite")
    return np.maximum(0.0, 1.0 - errors / d_max_mm)


def passes_ar(metrics: Mapping[str, float], ar: float, required: Sequence[str]) -> bool:
    """Return true when every supplied metric value or LCB reaches AR."""
    if not 0 < ar <= 1:
        raise ValueError("ar must lie in (0, 1]")
    missing = [name for name in required if name not in metrics]
    if missing:
        raise ValueError(f"missing required metrics: {missing}")
    values = np.asarray([metrics[name] for name in required], dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("required metrics must be finite")
    return bool(np.all(values >= ar))
