"""Frozen-estimator, single-head held-out metrics; no population claims.

Training source covariance fits the linear decoder. Held-out source weights
only evaluate it, including the same decoder under coordinate-prior stresses.
All arrays describe physical point electrodes before the reference contrast.
"""
from __future__ import annotations

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.spatial.distance import cdist

from .inverse_pilot import fixed_normal_scan
from .metrics import helmert_contrast, weighted_lower_cvar


def normalized_weights(weights: np.ndarray, count: int) -> np.ndarray:
    weights = np.asarray(weights, dtype=float)
    if weights.shape != (count,) or not np.isfinite(weights).all() or np.any(weights < 0) or not np.any(weights > 0):
        raise ValueError("invalid source weights")
    weights = weights / weights.max()
    return weights / weights.sum()


def physical_noise_correlation(xyz_mm: np.ndarray, *, rho: float = 0, length_mm: float = 20) -> np.ndarray:
    """Unit marginal variance PSD Euclidean Gaussian kernel plus IID nugget.

    Correlation is not followed by a layout-specific SNR renormalization.
    Euclidean coordinates (not arbitrary graph distances) keep the kernel PSD.
    """
    xyz = np.asarray(xyz_mm, dtype=float)
    if xyz.shape != (64, 3) or not np.isfinite(xyz).all():
        raise ValueError("noise coordinates must be 64 finite xyz rows")
    if not np.isfinite(rho) or not 0 <= rho < 1 or not np.isfinite(length_mm) or length_mm <= 0:
        raise ValueError("rho must be in [0,1), length must be positive")
    kernel = np.exp(-cdist(xyz, xyz, "sqeuclidean") / (2 * length_mm**2))
    return (1 - rho) * np.eye(64) + rho * kernel


def contrast_field(leadfield: np.ndarray) -> np.ndarray:
    h = np.asarray(leadfield, dtype=float)
    if h.ndim != 2 or h.shape[0] != 64 or not np.isfinite(h).all():
        raise ValueError("leadfield must have 64 finite rows")
    return helmert_contrast(64) @ (h - h.mean(axis=0, keepdims=True))


def contrast_noise(noise64: np.ndarray) -> np.ndarray:
    n = np.asarray(noise64, dtype=float)
    if n.shape != (64, 64) or not np.isfinite(n).all() or not np.allclose(n, n.T, rtol=1e-10, atol=1e-25):
        raise ValueError("noise must be finite symmetric 64x64")
    c = helmert_contrast(64)
    nc = c @ n @ c.T
    nc = (nc + nc.T) / 2
    np.linalg.cholesky(nc)
    return nc


def fit_field_decoder(reference_train: np.ndarray, candidate_train: np.ndarray,
                      train_weights: np.ndarray, noise64: np.ndarray) -> np.ndarray:
    """Fit A from training sources only; lead fields already include moment."""
    hb, hx = contrast_field(reference_train), contrast_field(candidate_train)
    if hb.shape != hx.shape:
        raise ValueError("training columns must match")
    w = normalized_weights(train_weights, hb.shape[1])
    nx = contrast_noise(noise64)
    scale = max(float(np.sqrt(np.max(np.diag(nx)))), float(np.max(np.abs(hb))), float(np.max(np.abs(hx))))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("decoder scale must be positive")
    hb, hx, nx = hb / scale, hx / scale, nx / scale**2
    cxx = (hx * w) @ hx.T + nx
    cbx = (hb * w) @ hx.T
    return cho_solve(cho_factor(cxx, lower=True), cbx.T).T


def field_test_components(reference_test: np.ndarray, candidate_test: np.ndarray,
                          decoder: np.ndarray, noise64: np.ndarray) -> dict[str, np.ndarray | float]:
    hb, hx = contrast_field(reference_test), contrast_field(candidate_test)
    a = np.asarray(decoder, dtype=float)
    if hb.shape != hx.shape or a.shape != (63, 63) or not np.isfinite(a).all():
        raise ValueError("test shape mismatch")
    error = hb - a @ hx
    n = contrast_noise(noise64)
    return {"source_signal_mse": np.sum(error**2, axis=0),
            "source_target_energy": np.sum(hb**2, axis=0),
            "noise_mse": float(np.trace(a @ n @ a.T))}


def field_test_score(components: dict, weights: np.ndarray) -> float:
    energy = np.asarray(components["source_target_energy"])
    weights = normalized_weights(weights, len(energy))
    denominator = float(weights @ energy)
    if denominator <= 0:
        raise ValueError("test target energy must be positive")
    mse = float(weights @ components["source_signal_mse"] + components["noise_mse"])
    # Out-of-sample explained energy can be negative. Do not clip it.
    return 1 - mse / denominator


def sensitivity_ratios(reference: np.ndarray, candidate: np.ndarray) -> np.ndarray:
    hb, hx = np.asarray(reference), np.asarray(candidate)
    if hb.shape != hx.shape or hb.ndim != 2 or hb.shape[0] != 64 or not np.isfinite(hb).all() or not np.isfinite(hx).all():
        raise ValueError("sensitivity field mismatch")
    denominator = np.ptp(hb, axis=0)
    scale = np.max(np.abs(hb - hb.mean(axis=0, keepdims=True)))
    if np.any(denominator <= 2e-8 * scale):
        raise ValueError("unresolved baseline amplitudes; explicit exclusion audit required")
    return np.ptp(hx, axis=0) / denominator


def paired_localization(dictionary: np.ndarray, generation: np.ndarray,
                        dictionary_xyz_mm: np.ndarray, generation_xyz_mm: np.ndarray,
                        noise64: np.ndarray, standard_noise63: np.ndarray) -> dict[str, np.ndarray]:
    """Known covariance ML with common base random numbers across layouts.

    The pairing is a variance-reduction coupling in a declared ordered contrast
    basis. It is not a claim of synchronized physical noise between arrays.
    Dictionary/generation fields already include physical dipole moment.
    """
    hd, hg = contrast_field(dictionary), contrast_field(generation)
    xd, xg = np.asarray(dictionary_xyz_mm), np.asarray(generation_xyz_mm)
    z = np.asarray(standard_noise63, dtype=float)
    if xd.shape != (hd.shape[1], 3) or xg.shape != (hg.shape[1], 3) or z.ndim != 3 or z.shape[:2] != (63, hg.shape[1]):
        raise ValueError("localization coordinate/noise shape mismatch")
    n = contrast_noise(noise64)
    scale = float(np.sqrt(np.max(np.diag(n))))
    n = n / scale**2
    observations = hg[:, :, None] / scale + np.einsum("ij,jqr->iqr", np.linalg.cholesky(n), z)
    indices = fixed_normal_scan(hd / scale, observations.reshape(63, -1), n, batch_size=512).reshape(z.shape[1:])
    errors = np.linalg.norm(xd[indices] - xg[:, None, :], axis=2)
    return {"errors_mm": errors, "estimated_indices": indices}


def prior_weights(xyz_mm: np.ndarray, base_weights: np.ndarray,
                  *, anchor_xyz_mm: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Smooth coordinate stresses, not anatomical labels or task simulations.

    Range-scaled Y/Z weights are at most 4:1; no source is dropped.
    """
    xyz = np.asarray(xyz_mm, dtype=float)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all():
        raise ValueError("prior coordinates invalid")
    w = normalized_weights(base_weights, len(xyz))
    anchor = xyz if anchor_xyz_mm is None else np.asarray(anchor_xyz_mm, dtype=float)
    if anchor.ndim != 2 or anchor.shape[1] != 3 or not np.isfinite(anchor).all():
        raise ValueError("prior anchor coordinates invalid")
    out = {"uniform_area": w}
    for axis, sign, name in [(1, 1, "positive_y_weighted"), (1, -1, "negative_y_weighted"), (2, -1, "inferior_z_weighted")]:
        center = float(np.median(anchor[:, axis]))
        width = max(float(np.ptp(anchor[:, axis])) / 4, 1.)
        factor = 1 + 3 / (1 + np.exp(-np.clip(sign * (xyz[:, axis] - center) / width, -40, 40)))
        out[name] = normalized_weights(w * factor, len(w))
    return out


def metrics_from_components(candidate_field: dict, baseline_field: dict,
                            ratios: np.ndarray, candidate_errors: np.ndarray,
                            baseline_errors: np.ndarray, weights: np.ndarray) -> dict[str, float | None]:
    w = normalized_weights(weights, len(ratios))
    fc, fb = field_test_score(candidate_field, w), field_test_score(baseline_field, w)
    uc = weighted_lower_cvar(np.maximum(0, 1 - candidate_errors / 50).mean(axis=1), w, .1)
    ub = weighted_lower_cvar(np.maximum(0, 1 - baseline_errors / 50).mean(axis=1), w, .1)
    sensitivity = weighted_lower_cvar(ratios, w, .1)
    fr, lr = fc / fb if fb > 1e-12 else None, uc / ub if ub > 1e-12 else None
    values = [fr, sensitivity, lr]
    return {"field_absolute": fc, "reference_field_absolute": fb, "field_relative": fr,
            "sensitivity_tail": sensitivity, "localization_utility": uc, "reference_localization_utility": ub,
            "localization_relative": lr, "conditional_global": min(values) if all(v is not None for v in values) else None,
            "median_mm": float(np.median(candidate_errors)), "p90_mm": float(np.percentile(candidate_errors, 90)),
            "p95_mm": float(np.percentile(candidate_errors, 95)),
            "reference_median_mm": float(np.median(baseline_errors))}


def cluster_bootstrap(candidate_field: dict, baseline_field: dict, ratios: np.ndarray,
                      candidate_errors: np.ndarray, baseline_errors: np.ndarray,
                      weights: np.ndarray, *, repetitions: int = 1000, seed: int = 2026091803,
                      source_strata: np.ndarray | None = None) -> dict:
    """Resample area-uniform source draws as paired clusters; keep noise repeats.

    Importance weights are retained on resampled sources. The percentile band
    measures conditional source-sampling variation; no head/bootstrap claims.
    Estimators/layouts stay frozen. It excludes optimization/model-form error.
    """
    q = len(ratios)
    w = normalized_weights(weights, q)
    if repetitions < 100:
        raise ValueError("bootstrap repetitions must be >=100")
    rng = np.random.default_rng(seed)
    strata = np.zeros(q, dtype=int) if source_strata is None else np.asarray(source_strata)
    if strata.shape != (q,):
        raise ValueError("strata must match source count")
    groups = [np.flatnonzero(strata == value) for value in np.unique(strata)]
    uc, ub = np.maximum(0, 1 - candidate_errors / 50).mean(axis=1), np.maximum(0, 1 - baseline_errors / 50).mean(axis=1)
    values = np.full((repetitions, 4), np.nan)
    for b in range(repetitions):
        ids = np.concatenate([rng.choice(group, size=len(group), replace=True) for group in groups])
        wb = w[ids] / w[ids].sum()
        energy = float(wb @ candidate_field["source_target_energy"][ids])
        fx = 1 - (float(wb @ candidate_field["source_signal_mse"][ids]) + candidate_field["noise_mse"]) / energy
        fb = 1 - (float(wb @ baseline_field["source_signal_mse"][ids]) + baseline_field["noise_mse"]) / energy
        sens = weighted_lower_cvar(ratios[ids], wb, .1)
        lx, lb = weighted_lower_cvar(uc[ids], wb, .1), weighted_lower_cvar(ub[ids], wb, .1)
        if fb > 1e-12 and lb > 1e-12:
            values[b] = [fx / fb, sens, lx / lb, min(fx / fb, sens, lx / lb)]
    valid = np.isfinite(values).all(axis=1)
    intervals = {}
    for i, name in enumerate(["field_relative", "sensitivity_tail", "localization_relative", "conditional_global"]):
        intervals[name] = {"lower_2_5": float(np.percentile(values[valid, i], 2.5)),
                           "upper_97_5": float(np.percentile(values[valid, i], 97.5)),
                           "one_sided_lower_95": float(np.percentile(values[valid, i], 5))} if valid.mean() >= .99 else None
    return {"method": "hemisphere_stratified_paired_source_cluster_percentile_conditional_on_one_head_frozen_estimator_and_noise_draws",
            "repetitions": repetitions, "seed": seed, "valid_replicates": int(valid.sum()),
            "source_stratum_counts": [len(group) for group in groups],
            "independent_head_count": 1, "formal_population_ar": False, "intervals": intervals}
