"""Grid-only single-dipole localization diagnostics for fixed-64 prototypes.

The inverse scanner and utility aggregation are reused from inverse_pilot.
Off-dictionary coordinates alone do not eliminate shared-forward inverse crime.
No continuous refinement, classification accuracy or formal AR is computed.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

import numpy as np
from scipy.spatial import cKDTree

from .inverse_pilot import error_summary, fixed_normal_scan
from .metrics import helmert_contrast


@dataclass(frozen=True)
class PrototypeLocalizationResult:
    """JSON-safe summary plus reproducible source-by-repeat diagnostic arrays."""

    report: dict[str, object]
    errors_mm: np.ndarray
    estimated_dictionary_indices: np.ndarray
    nearest_dictionary_distance_mm: np.ndarray
    generation_source_weights: np.ndarray
    standard_normal_noise: np.ndarray


def _layout_noise_generator(base_seed: int, layout_id: str):
    if not isinstance(base_seed, (int, np.integer)) or isinstance(base_seed, (bool, np.bool_)) or base_seed < 0:
        raise ValueError("noise_seed must be a nonnegative integer")
    if not isinstance(layout_id, str) or not layout_id.strip():
        raise ValueError("layout_id must be a nonempty stable identifier")
    key = json.dumps(
        {"base_seed": int(base_seed), "layout_id": layout_id},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(key).digest()
    entropy = np.frombuffer(digest, dtype="<u4").tolist()
    generator = np.random.default_rng(np.random.SeedSequence(entropy))
    return generator, digest.hex()


def evaluate_grid_localization(
    dictionary_leadfield: np.ndarray,
    generation_leadfield: np.ndarray,
    dictionary_xyz_mm: np.ndarray,
    generation_xyz_mm: np.ndarray,
    *,
    source_moment_am: float,
    physical_electrode_noise_std_v: float,
    noise_seed: int,
    layout_id: str,
    noise_repetitions: int = 16,
    generation_source_weights: np.ndarray | None = None,
    scan_batch_size: int = 128,
    require_off_dictionary: bool = True,
    off_dictionary_distance_tolerance_mm: float = 1e-6,
    physical_noise_covariance_v2: np.ndarray | None = None,
    noise_model: object = "iid_equal_variance",
    expected_electrodes: int | None = 64,
) -> PrototypeLocalizationResult:
    """Evaluate a K-electrode layout (default K=64) against a frozen fixed-normal dictionary.

    Both lead fields are in V/(A m); coordinates are in the *same* frame in mm.
    Generation and dictionary normals must already be encoded in their lead
    fields. The scanner estimates an unknown signed scalar dipole moment.

    ``physical_electrode_noise_std_v`` must come from the reference layout's
    calibration, not this candidate's signal power. All layouts share source
    draws, but MUST have distinct stable ``layout_id`` values. A SHA256-derived
    per-layout PCG64 stream makes their noise independent pseudorandom draws
    even when the same base seed is supplied, independent of evaluation order.
    Reusing an ID intentionally reproduces that layout's exact noise draw.

    Equal weights assume the generation points were sampled uniformly by
    cortical area. Optional supplied weights affect the source-tail utility;
    reported error quantiles remain unweighted simulated-trial summaries.

    ``physical_noise_covariance_v2`` (KxK, V^2) replaces the iid noise for
    correlated models: the same standard-normal stream is coloured by the
    Cholesky factor of its reference-free projection and the scanner whitens
    with that projection. None keeps the original iid path exactly.
    """
    hd = np.asarray(dictionary_leadfield, dtype=float)
    hg = np.asarray(generation_leadfield, dtype=float)
    xd = np.asarray(dictionary_xyz_mm, dtype=float)
    xg = np.asarray(generation_xyz_mm, dtype=float)
    if expected_electrodes is not None and (not isinstance(expected_electrodes, (int, np.integer)) or isinstance(expected_electrodes, (bool, np.bool_)) or not 3 <= int(expected_electrodes) <= 64):
        raise ValueError("expected_electrodes must be an integer in [3, 64] or None")
    k = hd.shape[0] if expected_electrodes is None else int(expected_electrodes)
    if hd.ndim != 2 or hd.shape[0] != k or not 3 <= k <= 64 or hd.shape[1] < 1:
        raise ValueError(f"dictionary_leadfield must have shape ({k}, n_dictionary >= 1)")
    if hg.ndim != 2 or hg.shape[0] != k or hg.shape[1] < 1:
        raise ValueError(f"generation_leadfield must have shape ({k}, n_generation >= 1)")
    if xd.shape != (hd.shape[1], 3) or xg.shape != (hg.shape[1], 3):
        raise ValueError("coordinates must have one xyz row per corresponding lead-field column")
    if not all(np.all(np.isfinite(value)) for value in (hd, hg, xd, xg)):
        raise ValueError("lead fields and coordinates must be finite")
    if not np.isfinite(source_moment_am) or source_moment_am <= 0:
        raise ValueError("source_moment_am must be positive and finite")
    sigma = float(physical_electrode_noise_std_v)
    variance = sigma * sigma
    if not np.isfinite(sigma) or sigma <= 0 or not np.isfinite(variance) or variance <= 0:
        raise ValueError("physical_electrode_noise_std_v must yield a positive finite variance")
    if not isinstance(noise_repetitions, (int, np.integer)) or isinstance(noise_repetitions, (bool, np.bool_)) or noise_repetitions < 1:
        raise ValueError("noise_repetitions must be a positive integer")
    if not isinstance(require_off_dictionary, bool):
        raise ValueError("require_off_dictionary must be a boolean")
    if not np.isfinite(off_dictionary_distance_tolerance_mm) or off_dictionary_distance_tolerance_mm < 0:
        raise ValueError("off_dictionary_distance_tolerance_mm must be nonnegative and finite")
    count = hg.shape[1]
    weights = np.ones(count) if generation_source_weights is None else np.asarray(generation_source_weights, dtype=float)
    if weights.shape != (count,) or not np.all(np.isfinite(weights)) or np.any(weights < 0) or not np.any(weights > 0):
        raise ValueError("generation_source_weights must have one finite nonnegative entry per source and positive total")
    weights = weights / float(np.max(weights))
    weights = weights / float(weights.sum())

    nearest_mm = cKDTree(xd).query(xg)[0]
    on_dictionary = nearest_mm <= off_dictionary_distance_tolerance_mm
    if require_off_dictionary and np.any(on_dictionary):
        raise ValueError("generation positions fall on the inverse dictionary within the configured tolerance")
    generator, stream_key = _layout_noise_generator(noise_seed, layout_id)
    standard_noise = generator.normal(size=(k - 1, count, int(noise_repetitions)))
    contrast = helmert_contrast(k)
    hd_reference_free = contrast @ (hd - hd.mean(axis=0, keepdims=True))
    hg_reference_free = contrast @ (hg - hg.mean(axis=0, keepdims=True))
    if physical_noise_covariance_v2 is None:
        noise = sigma * standard_noise
        whitening = variance * np.eye(k - 1)
    else:
        covariance = np.asarray(physical_noise_covariance_v2, dtype=float)
        if covariance.shape != (k, k) or not np.all(np.isfinite(covariance)) or not np.allclose(covariance, covariance.T, rtol=1e-10, atol=0):
            raise ValueError(f"physical_noise_covariance_v2 must be a finite symmetric {k}x{k} matrix")
        whitening = contrast @ covariance @ contrast.T
        whitening = .5 * (whitening + whitening.T)
        noise = np.einsum("ij,jqr->iqr", np.linalg.cholesky(whitening), standard_noise)
    observations = (hg_reference_free[:, :, None] * source_moment_am + noise).reshape(k - 1, -1)
    indices = fixed_normal_scan(
        hd_reference_free, observations, whitening,
        batch_size=scan_batch_size,
    ).reshape(count, int(noise_repetitions))
    errors = np.linalg.norm(xd[indices] - xg[:, None, :], axis=2)
    stats = error_summary(errors, weights)
    report: dict[str, object] = {
        "schema_version": "compact-eeg-prototype-grid-localization/1",
        "scientific_role": "exploratory_grid_only_localization_diagnostic",
        "formal_v2_performance_eligible": False,
        "ar_computed": False,
        "classification_accuracy_computed": False,
        "layout_id": layout_id,
        "electrode_count": k,
        "reference_free_dimensions": k - 1,
        "dictionary_source_count": int(hd.shape[1]),
        "generation_source_count": count,
        "noise_repetitions_per_source": int(noise_repetitions),
        "scored_trial_count": int(errors.size),
        "source_moment_am": float(source_moment_am),
        "physical_electrode_noise_std_v": sigma,
        "physical_electrode_noise_variance_v2": variance,
        "noise_scale_origin": "caller_supplied_reference_calibration; never_renormalized_to_this_layout",
        **({} if physical_noise_covariance_v2 is None else {"noise_model": noise_model}),
        "noise_seed": int(noise_seed),
        "layout_noise_stream_sha256": stream_key,
        "noise_generator": "NumPy_PCG64_with_SeedSequence_from_SHA256(base_seed,layout_id)",
        "layout_noise_rule": "distinct_layout_ids_required_for_distinct_noise_streams; same_id_reproduces_the_same_noise",
        "inverse_estimator": "noise_whitened_fixed_normal_unknown_signed_amplitude_discrete_ML_scan",
        "continuous_surface_refinement_performed": False,
        "coordinate_error_unit": "mm",
        "error_quantiles": "unweighted_over_simulated_source_noise_trials; not_independent_head_samples",
        "source_tail_weights": "normalized_caller_supplied_weights" if generation_source_weights is not None else "equal_Monte_Carlo_weights_assuming_uniform_cortical_area_sampling",
        "off_dictionary_required": require_off_dictionary,
        "off_dictionary_distance_tolerance_mm": float(off_dictionary_distance_tolerance_mm),
        "on_dictionary_source_count": int(on_dictionary.sum()),
        "nearest_dictionary_distance_min_mm": float(nearest_mm.min()),
        "nearest_dictionary_distance_median_mm": float(np.median(nearest_mm)),
        "nearest_dictionary_distance_max_mm": float(nearest_mm.max()),
        "limitations": [
            "Shared anatomy and forward solver retain inverse-crime risk even when generator coordinates are off dictionary.",
            "Position and normal consistency must be validated by the forward-generation pipeline; this module does not recompute lead fields.",
            "Grid discretization error remains; no continuous refinement or formal AR certification is performed.",
            "Repeated noise trials and repeated conditions are not independent human subjects.",
        ],
        **stats,
    }
    return PrototypeLocalizationResult(
        report=report,
        errors_mm=errors,
        estimated_dictionary_indices=indices,
        nearest_dictionary_distance_mm=nearest_mm,
        generation_source_weights=weights.copy(),
        standard_normal_noise=standard_noise,
    )


__all__ = ["PrototypeLocalizationResult", "evaluate_grid_localization"]
