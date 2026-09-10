"""Dictionary-resolution controls and qualified-face linear EEG refinement.

The search functions receive observations, never generation coordinates or
generation lead fields. ``diagnose_nested_dictionaries`` uses evaluation
coordinates only after fitting, to calculate errors and geometric floors.

Continuous refinement requires actual surface triangles AND a lead-field
column at every one of their vertices. It is exact ML within the stated
piecewise-linear lead-field surrogate, not an exact continuous FEM forward
model. Sparse dictionary vertices must not be arbitrarily triangulated across
sulci or supplemented using held-out generation sources to satisfy this API.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

import numpy as np
from scipy.linalg import solve_triangular
from scipy.spatial import cKDTree


@dataclass(frozen=True)
class GridFit:
    dictionary_indices: np.ndarray
    signed_moments_am: np.ndarray
    whitened_residual_squared: np.ndarray
    relative_residual_squared: np.ndarray


@dataclass(frozen=True)
class TriangleFit:
    discrete_fit: GridFit
    estimated_xyz_mm: np.ndarray
    triangle_indices: np.ndarray
    barycentric_weights: np.ndarray
    signed_moments_am: np.ndarray
    whitened_residual_squared: np.ndarray
    relative_residual_squared: np.ndarray
    improved_over_discrete: np.ndarray
    tested_triangle_counts: np.ndarray
    report: dict


@dataclass(frozen=True)
class DictionaryResolutionControl:
    report: dict
    fitted_full_dictionary_indices: dict[str, np.ndarray]
    errors_mm: dict[str, np.ndarray]
    nearest_dictionary_distances_mm: dict[str, np.ndarray]
    relative_residual_squared: dict[str, np.ndarray]


def _whiten(leadfield, observations, noise_covariance):
    h = np.asarray(leadfield, dtype=float)
    y = np.asarray(observations, dtype=float)
    n = np.asarray(noise_covariance, dtype=float)
    if h.ndim != 2 or y.ndim != 2 or min(h.shape) < 1 or y.shape[1] < 1:
        raise ValueError("leadfield and observations must be nonempty channel-by-column matrices")
    if y.shape[0] != h.shape[0] or n.shape != (h.shape[0], h.shape[0]):
        raise ValueError("incompatible channel or covariance dimensions")
    if not all(np.all(np.isfinite(a)) for a in (h, y, n)):
        raise ValueError("leadfield, observations, and covariance must be finite")
    if not np.allclose(n, n.T, rtol=1e-12, atol=0):
        raise ValueError("noise covariance must be symmetric")
    chol = np.linalg.cholesky(n)
    hw = solve_triangular(chol, h, lower=True)
    yw = solve_triangular(chol, y, lower=True)
    norms = np.linalg.norm(hw, axis=0)
    if np.any(norms <= 0) or not np.all(np.isfinite(norms)):
        raise ValueError("dictionary contains an unobservable or unrepresentable column")
    return hw, yw, norms


def _grid_fit(hw, yw, norms, batch_size):
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    normalized = hw / norms
    count = yw.shape[1]
    indices = np.empty(count, dtype=np.int64)
    amplitudes = np.empty(count)
    residuals = np.empty(count)
    for start in range(0, count, batch_size):
        end = min(start + batch_size, count)
        block = yw[:, start:end]
        scores = normalized.T @ block
        chosen = np.argmax(np.abs(scores), axis=0)
        amplitude = scores[chosen, np.arange(end - start)] / norms[chosen]
        residual = block - hw[:, chosen] * amplitude
        indices[start:end], amplitudes[start:end] = chosen, amplitude
        residuals[start:end] = np.sum(residual * residual, axis=0)
    energy = np.sum(yw * yw, axis=0)
    relative = np.zeros(count)
    np.divide(residuals, energy, out=relative, where=energy > 0)
    return GridFit(indices, amplitudes, residuals, relative)


def profiled_grid_scan(leadfield, observations, noise_covariance, *, batch_size=128):
    """Discrete ML with unknown signed moment; H in V/(A m), y in V.

    The covariance sets whitening for both H and y and is never re-estimated
    from a candidate layout. For a noiseless control, a caller can use I:
    scalar whitening has no effect on the selected location or amplitude.
    """
    hw, yw, norms = _whiten(leadfield, observations, noise_covariance)
    return _grid_fit(hw, yw, norms, batch_size)


def _coordinates(value, count, name):
    xyz = np.asarray(value, dtype=float)
    if xyz.shape != (count, 3) or not np.all(np.isfinite(xyz)):
        raise ValueError(f"{name} must have finite shape ({count},3) in mm")
    return xyz


def _summary(values):
    x = np.asarray(values, dtype=float)
    return {"mean": float(x.mean()), "median": float(np.median(x)),
            "p90": float(np.quantile(x, .9)), "p95": float(np.quantile(x, .95)),
            "maximum": float(x.max())}


def diagnose_nested_dictionaries(
    leadfield, observations, noise_covariance, dictionary_xyz_mm,
    evaluation_xyz_mm, dictionaries: Mapping[str, np.ndarray], *,
    batch_size=128, require_off_dictionary=True,
    off_dictionary_tolerance_mm=1e-6,
):
    """Compare nested TRUE lead-field dictionaries on exactly the same data.

    Mapping order must be coarse to fine, and every index set must contain the
    previous one. Geometry floors are oracle nearest-grid distances, NOT an
    estimator using true coordinates. A denser grid cannot worsen fitted ML
    residual, but its actual location error is not guaranteed to decrease.
    This routine generates no noise and performs no forward solve.
    """
    hw, yw, norms = _whiten(leadfield, observations, noise_covariance)
    xyz = _coordinates(dictionary_xyz_mm, hw.shape[1], "dictionary coordinates")
    truth = _coordinates(evaluation_xyz_mm, yw.shape[1], "evaluation coordinates")
    if not dictionaries:
        raise ValueError("at least one dictionary is required")
    if not np.isfinite(off_dictionary_tolerance_mm) or off_dictionary_tolerance_mm < 0:
        raise ValueError("off-dictionary tolerance must be finite and nonnegative")
    validated, previous = [], set()
    for name, value in dictionaries.items():
        indices = np.asarray(value)
        if not isinstance(name, str) or not name or indices.ndim != 1 or not indices.size or indices.dtype.kind not in "iu":
            raise ValueError("dictionary names and integer index vectors must be nonempty")
        if indices.min() < 0 or indices.max() >= len(xyz) or len(np.unique(indices)) != len(indices):
            raise ValueError("dictionary indices must be unique and in range")
        if not previous.issubset(set(indices.tolist())):
            raise ValueError("dictionaries must be nested in coarse-to-fine mapping order")
        previous = set(indices.tolist())
        validated.append((name, indices.astype(np.int64, copy=False)))
    if require_off_dictionary and np.any(cKDTree(xyz[validated[-1][1]]).query(truth)[0] <= off_dictionary_tolerance_mm):
        raise ValueError("evaluation coordinates overlap the inverse dictionary")
    fitted, errors, floors, relative, rows = {}, {}, {}, {}, []
    last_residual = None
    for name, indices in validated:
        # Truth is deliberately absent from this search call.
        fit = _grid_fit(hw[:, indices], yw, norms[indices], batch_size)
        full_indices = indices[fit.dictionary_indices]
        fitted[name] = full_indices
        errors[name] = np.linalg.norm(xyz[full_indices] - truth, axis=1)
        floors[name] = cKDTree(xyz[indices]).query(truth)[0]
        relative[name] = fit.relative_residual_squared
        if np.any(errors[name] + 1e-10 < floors[name]):
            raise RuntimeError("location error is below the nearest-grid geometric floor")
        if last_residual is not None and np.any(fit.relative_residual_squared > last_residual + 1e-10):
            raise RuntimeError("nested dictionary ML residual increased beyond roundoff")
        last_residual = fit.relative_residual_squared
        rows.append({"name": name, "dictionary_size": len(indices),
                     "location_error_mm": _summary(errors[name]),
                     "oracle_nearest_grid_distance_mm": _summary(floors[name]),
                     "excess_over_nearest_grid_distance_mm": _summary(errors[name] - floors[name]),
                     "relative_profiled_residual_squared": _summary(relative[name])})
    return DictionaryResolutionControl(
        {"schema_version": "compact-eeg-dictionary-resolution-control/1",
         "observation_count": yw.shape[1], "conditions": rows,
         "same_observations_and_noise_whitening": True,
         "unknown_signed_scalar_moment": True, "generation_sources_used_as_candidates": False,
         "continuous_refinement_performed": False, "formal_ar_certification": False,
         "zero_observation_count": int(np.sum(np.linalg.norm(yw, axis=0) == 0)),
         "interpretation": "Conditional dictionary-resolution control; geometric floor is an oracle diagnostic, not achievable localization accuracy. Shared-forward inverse crime and normal/model mismatch remain."},
        fitted, errors, floors, relative,
    )


def available_native_faces(native_triangles, dictionary_native_vertex_indices, *, retained_face_mask=None):
    """Map only original faces whose three vertices have dictionary columns.

    No new triangulation, geometric nearest-neighbor connection, held-out
    vertex insertion, or cross-sulcus interpolation is performed.
    """
    faces = np.asarray(native_triangles)
    ids = np.asarray(dictionary_native_vertex_indices)
    if faces.ndim != 2 or faces.shape[1] != 3 or faces.dtype.kind not in "iu" or not faces.size or faces.min() < 0:
        raise ValueError("native triangles must be nonempty nonnegative integer triples")
    if ids.ndim != 1 or not ids.size or ids.dtype.kind not in "iu" or ids.min() < 0 or len(np.unique(ids)) != len(ids):
        raise ValueError("dictionary native vertex IDs must be unique nonnegative integers")
    retained = np.ones(len(faces), dtype=bool) if retained_face_mask is None else np.asarray(retained_face_mask)
    if retained.shape != (len(faces),) or retained.dtype.kind != "b":
        raise ValueError("retained mask must be boolean with one entry per native face")
    order = np.argsort(ids)
    pos = np.searchsorted(ids[order], faces)
    in_range = pos < len(ids)
    clipped = np.minimum(pos, len(ids) - 1)
    present = in_range & (ids[order][clipped] == faces)
    eligible = np.flatnonzero(retained & np.all(present, axis=1))
    return eligible, order[pos[eligible]]


def linear_triangle_refine(
    vertex_leadfield, vertex_xyz_mm, triangles, observations, noise_covariance,
    *, seed_count=3, minimum_relative_improvement=1e-12, least_squares_rcond=1e-12,
):
    """Local continuous ML on a predeclared linear surface-field surrogate.

    Each face uses h(w)=H_face @ w, w>=0, sum(w)=1, and an unknown signed
    scalar amplitude a. Coefficients c=a*w are all >=0 or all <=0. Enumerating
    both signs and the seven nonempty active sets solves each three-generator
    cone least-squares problem. We visit faces incident on the top discrete
    seeds, not every face, so this is NOT a global continuous optimum.

    H must be directly available at every input vertex before observing test
    truth. A valid original-surface face set is a caller provenance obligation.
    Linear interpolation of fixed-normal lead fields is an approximation even
    with true vertex FEM columns; validate it on separate interpolation probes.
    """
    hw, yw, norms = _whiten(vertex_leadfield, observations, noise_covariance)
    xyz = _coordinates(vertex_xyz_mm, hw.shape[1], "vertex coordinates")
    faces = np.asarray(triangles)
    if faces.ndim != 2 or faces.shape[1] != 3 or not len(faces) or faces.dtype.kind not in "iu":
        raise ValueError("at least one qualified integer triangle is required")
    if faces.min() < 0 or faces.max() >= len(xyz) or np.any(np.diff(np.sort(faces, axis=1), axis=1) == 0):
        raise ValueError("triangles contain invalid or repeated vertex indices")
    areas2 = np.linalg.norm(np.cross(xyz[faces[:, 1]]-xyz[faces[:, 0]], xyz[faces[:, 2]]-xyz[faces[:, 0]]), axis=1)
    if np.any(areas2 <= 0):
        raise ValueError("degenerate surface triangle")
    if not isinstance(seed_count, int) or isinstance(seed_count, bool) or not 1 <= seed_count <= len(xyz):
        raise ValueError("seed_count must be between one and the dictionary size")
    if not np.isfinite(minimum_relative_improvement) or not 0 <= minimum_relative_improvement < 1:
        raise ValueError("invalid minimum relative improvement")
    if not np.isfinite(least_squares_rcond) or not 0 < least_squares_rcond < 1:
        raise ValueError("invalid least-squares rcond")
    discrete = _grid_fit(hw, yw, norms, 128)
    count = yw.shape[1]
    estimates = xyz[discrete.dictionary_indices].copy()
    face_ids = np.full(count, -1, dtype=np.int64)
    bary = np.zeros((count, 3))
    moments = discrete.signed_moments_am.copy()
    residuals = discrete.whitened_residual_squared.copy()
    tested = np.zeros(count, dtype=np.int64)
    incident = [[] for _ in range(len(xyz))]
    for i, face in enumerate(faces):
        for vertex in face:
            incident[vertex].append(i)
    normalized = hw / norms
    energy = np.sum(yw*yw, axis=0)
    active_sets = [np.flatnonzero(np.array([mask & 1, mask & 2, mask & 4])) for mask in range(1, 8)]
    for trial in range(count):
        if energy[trial] == 0:
            continue
        scores = np.abs(normalized.T @ yw[:, trial])
        seeds = np.argsort(-scores, kind="stable")[:seed_count]
        local_faces = sorted({face for vertex in seeds for face in incident[vertex]})
        tested[trial] = len(local_faces)
        for face_id in local_faces:
            face = faces[face_id]
            for active in active_sets:
                operator = hw[:, face[active]]
                coefficient = np.linalg.lstsq(operator, yw[:, trial], rcond=least_squares_rcond)[0]
                scale = float(np.max(np.abs(coefficient)))
                if scale == 0:
                    continue
                for sign in (1., -1.):
                    signed = sign * coefficient
                    if np.any(signed < -64*np.finfo(float).eps*scale):
                        continue
                    signed = np.maximum(signed, 0)
                    total = float(signed.sum())
                    if total <= 0:
                        continue
                    residual = yw[:, trial] - operator @ (sign*signed)
                    score = float(residual @ residual)
                    if score < residuals[trial] - minimum_relative_improvement*energy[trial]:
                        weights = np.zeros(3)
                        weights[active] = signed/total
                        residuals[trial], moments[trial] = score, sign*total
                        face_ids[trial], bary[trial] = face_id, weights
                        estimates[trial] = weights @ xyz[face]
    relative = np.zeros(count)
    np.divide(residuals, energy, out=relative, where=energy > 0)
    return TriangleFit(discrete, estimates, face_ids, bary, moments, residuals,
        relative, face_ids >= 0, tested,
        {"schema_version": "compact-eeg-linear-triangle-localization/1",
         "interpolation": "piecewise_linear_fixed_normal_vertex_leadfield_surrogate",
         "estimator": "local_face_signed_cone_active_set_profiled_ML",
         "discrete_seed_count": seed_count, "face_count": len(faces),
         "minimum_relative_improvement": minimum_relative_improvement,
         "least_squares_rcond": least_squares_rcond,
         "generation_sources_used_as_candidates": False,
         "exact_continuous_FEM": False, "global_continuous_optimum": False,
         "formal_ar_certification": False,
         "unrefined_triangle_index": -1, "unrefined_barycentric_weights": [0, 0, 0],
         "warning": "Reduced data residual need not reduce localization error. Complete original-face vertex fields and independent interpolation validation are required; shared-forward inverse crime remains."})


# Descriptive public alias used by campaign runners.
nested_dictionary_control = diagnose_nested_dictionaries

__all__ = ["GridFit", "TriangleFit", "DictionaryResolutionControl", "profiled_grid_scan",
           "diagnose_nested_dictionaries", "nested_dictionary_control", "available_native_faces", "linear_triangle_refine"]
