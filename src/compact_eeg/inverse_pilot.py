"""Bounded, solver-independent single-dipole inverse qualification.

This is a discrete maximum-likelihood scanner, not the protocol's final
continuously refined estimator. No compact-layout or AR claim is made here.
"""

from __future__ import annotations

import numpy as np
from scipy.linalg import solve_triangular

from .metrics import localization_utility, weighted_lower_cvar


def fixed_normal_scan(
    leadfield: np.ndarray,
    observations: np.ndarray,
    noise_covariance: np.ndarray,
    *,
    batch_size: int = 128,
) -> np.ndarray:
    """ML location with an unknown signed scalar moment and known SPD noise.

    Maximize (h.T N^-1 y)^2 / (h.T N^-1 h). Covariance whitening is applied
    to *both* the dictionary and observations. Zero columns are rejected.
    """
    h = np.asarray(leadfield, dtype=float)
    y = np.asarray(observations, dtype=float)
    n = np.asarray(noise_covariance, dtype=float)
    if h.ndim != 2 or y.ndim != 2 or h.shape[0] != y.shape[0]:
        raise ValueError("leadfield and observations must be channel-by-column arrays")
    if min(h.shape) < 1 or y.shape[1] < 1 or n.shape != (h.shape[0], h.shape[0]):
        raise ValueError("empty or incompatible input")
    if not all(np.all(np.isfinite(v)) for v in (h, y, n)):
        raise ValueError("inputs must be finite")
    if not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    if not np.allclose(n, n.T, rtol=1e-12, atol=0):
        raise ValueError("noise covariance must be symmetric")
    chol = np.linalg.cholesky(n)
    hw = solve_triangular(chol, h, lower=True)
    norms = np.linalg.norm(hw, axis=0)
    if np.any(norms <= 0):
        raise ValueError("dictionary contains an unobservable source")
    normalized = hw / norms
    estimates = np.empty(y.shape[1], dtype=np.int64)
    for start in range(0, y.shape[1], batch_size):
        yw = solve_triangular(chol, y[:, start:start + batch_size], lower=True)
        scores = normalized.T @ yw
        estimates[start:start + batch_size] = np.argmax(np.abs(scores), axis=0)
    return estimates


def sample_cortical_triangles(source_spaces, count: int, seed: int) -> dict[str, np.ndarray]:
    """Sample uniform surface area and uniform triangle-interior coordinates.

    Samples carry equal Monte Carlo weights because the draw itself is
    area-weighted. This is not deterministic whole-cortex quadrature.
    Normals are interpolated from the parent cortical vertex normals.
    """
    if not isinstance(count, int) or count < 1:
        raise ValueError("count must be positive")
    rng = np.random.default_rng(seed)
    areas, faces_all, hemispheres = [], [], []
    for hemi, space in enumerate(source_spaces):
        faces = np.asarray(space["tris"], dtype=np.int64)
        xyz = np.asarray(space["rr"], dtype=float)[faces]
        area = np.linalg.norm(np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]), axis=1) / 2
        if np.any(area < 0) or not np.all(np.isfinite(area)):
            raise ValueError("invalid cortical triangle areas")
        areas.append(area)
        faces_all.append(faces)
        hemispheres.append(np.full(len(faces), hemi, dtype=np.int8))
    all_areas = np.concatenate(areas)
    drawn = rng.choice(len(all_areas), count, p=all_areas / all_areas.sum())
    all_hemi = np.concatenate(hemispheres)
    all_faces = np.concatenate(faces_all)
    offsets = np.cumsum([0] + [len(v) for v in faces_all])
    uv = rng.random((count, 2))
    root = np.sqrt(uv[:, 0])
    bary = np.column_stack((1 - root, root * (1 - uv[:, 1]), root * uv[:, 1]))
    rr, nn = np.empty((count, 3)), np.empty((count, 3))
    for i, face_index in enumerate(drawn):
        hemi = all_hemi[face_index]
        face = all_faces[face_index]
        rr[i] = bary[i] @ source_spaces[hemi]["rr"][face]
        normal = bary[i] @ source_spaces[hemi]["nn"][face]
        nn[i] = normal / np.linalg.norm(normal)
    hemi = all_hemi[drawn]
    return {
        "positions_mri_m": rr,
        "normals_mri": nn,
        "hemisphere": hemi,
        "triangle_id": drawn - offsets[hemi],
        "barycentric_coordinates": bary,
        "sample_weights": np.full(count, 1.0 / count),
    }


def error_summary(errors_mm: np.ndarray, weights: np.ndarray) -> dict[str, object]:
    """Descriptive errors and exact mass-weighted lower-tail utility."""
    errors = np.asarray(errors_mm, dtype=float)
    if errors.ndim != 2:
        raise ValueError("errors must have shape (source, noise_repeat)")
    # Source draws are already area sampled; quantiles summarize sampled trials.
    result = {
        "median_error_mm": float(np.median(errors)),
        "p90_error_mm": float(np.quantile(errors, 0.90)),
        "p95_error_mm": float(np.quantile(errors, 0.95)),
        "mean_error_mm": float(errors.mean()),
        "success_fraction_within_10mm": float(np.mean(errors <= 10)),
        "success_fraction_within_20mm": float(np.mean(errors <= 20)),
    }
    for dmax in (25.0, 50.0, 75.0):
        source_utility = localization_utility(errors, dmax).mean(axis=1)
        result[f"source_lower10_utility_dmax{int(dmax)}mm"] = weighted_lower_cvar(source_utility, weights, 0.1)
    return result
