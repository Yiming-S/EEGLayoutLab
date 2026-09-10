"""Exploratory fixed-64 prototype comparison on a shared cortical source set.

These metrics are not classification accuracy or formal AR certification.
The sensitivity denominator tolerance is an exploratory numerical-zero rule,
not a certified lead-field error bound and not a linear-solver residual.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

import numpy as np

from .metrics import (
    helmert_contrast,
    lmmse_explained_energy,
    participation_effective_rank,
    relative_retention,
    weighted_lower_cvar,
)


@dataclass(frozen=True)
class PrototypeMetricResult:
    """JSON-safe summary and source-level arrays for immutable NPZ storage.

    Undefined sensitivity ratios are NaN only in the array payload; the report
    represents unavailable aggregate metrics with JSON null (Python None).
    """

    report: dict[str, object]
    source_area_weights: np.ndarray
    reference_bipolar_amplitude_v_per_am: np.ndarray
    candidate_bipolar_amplitude_v_per_am: np.ndarray
    sensitivity_ratio: np.ndarray
    sensitivity_valid_mask: np.ndarray


def evaluate_prototype_metrics(
    reference_leadfield: np.ndarray,
    candidate_leadfield: np.ndarray,
    source_area_weights: np.ndarray,
    *,
    source_moment_am: float,
    numerical_zero_relative_tolerance: float,
    snr_db: Sequence[float] = (0.0, 10.0, 20.0),
    source_tail_fraction: float = 0.1,
    maximum_excluded_source_area_fraction: float = 0.001,
) -> PrototypeMetricResult:
    """Compare two 64 x N fixed-normal lead fields in V/(A m).

    Columns must describe the same cortical sources in the same order and
    orientation convention. Source covariance is moment^2 * diag(area weights).
    At each SNR, physical electrode noise is sigma^2 I64 for *both* layouts,
    with sigma set once from the reference's average 63-contrast signal power.
    Candidate and reference sensor noise is independent conditional on sources;
    no sensor-noise cross covariance enters the clean-target LMMSE estimate.

    Sensitivity excludes reference bipolar amplitudes at or below twice the
    supplied tolerance times the largest reference mean-free voltage. This
    scale-based rule is exploratory/unvalidated against the formal protocol.
    Exclusion is never based on an amplitude percentile. A conditional score is
    retained for transparency, but the aggregate is unavailable if excluded
    source area exceeds the configured reporting budget.
    """
    baseline = np.asarray(reference_leadfield, dtype=float)
    candidate = np.asarray(candidate_leadfield, dtype=float)
    if baseline.ndim != 2 or baseline.shape[0] != 64 or baseline.shape[1] < 1:
        raise ValueError("reference_leadfield must have shape (64, n_sources >= 1)")
    if candidate.shape != baseline.shape:
        raise ValueError("candidate must share the reference's 64 channels and source count")
    if not np.all(np.isfinite(baseline)) or not np.all(np.isfinite(candidate)):
        raise ValueError("lead fields must be finite")
    weights = np.asarray(source_area_weights, dtype=float)
    if weights.shape != (baseline.shape[1],):
        raise ValueError("source_area_weights must have one entry per source")
    if not np.all(np.isfinite(weights)) or np.any(weights < 0) or not np.any(weights > 0):
        raise ValueError("source_area_weights must be finite, nonnegative and have positive total")
    # Normalize before summing to avoid overflow from otherwise valid area units.
    weights = weights / float(np.max(weights))
    weights = weights / float(weights.sum())
    if not np.isfinite(source_moment_am) or source_moment_am <= 0:
        raise ValueError("source_moment_am must be positive and finite")
    if not np.isfinite(numerical_zero_relative_tolerance) or not 0 <= numerical_zero_relative_tolerance < 1:
        raise ValueError("numerical_zero_relative_tolerance must lie in [0, 1)")
    if not np.isfinite(source_tail_fraction) or not 0 < source_tail_fraction <= 1:
        raise ValueError("source_tail_fraction must lie in (0, 1]")
    if not np.isfinite(maximum_excluded_source_area_fraction) or not 0 <= maximum_excluded_source_area_fraction < 1:
        raise ValueError("maximum_excluded_source_area_fraction must lie in [0, 1)")
    snrs = np.asarray(tuple(snr_db), dtype=float)
    if snrs.ndim != 1 or not snrs.size or not np.all(np.isfinite(snrs)):
        raise ValueError("snr_db must be a nonempty sequence of finite values")

    contrast = helmert_contrast(64)
    baseline_centered = baseline - baseline.mean(axis=0, keepdims=True)
    candidate_centered = candidate - candidate.mean(axis=0, keepdims=True)
    hb, hx = contrast @ baseline_centered, contrast @ candidate_centered
    reference_scale = float(np.max(np.abs(hb)))
    if reference_scale == 0:
        raise ValueError("reference must have positive reference-free signal energy")
    normalized_hb = hb / reference_scale
    normalized_reference_power = float(np.sum((normalized_hb ** 2) * weights) / 63)
    if normalized_reference_power <= 0:
        raise ValueError("reference must have positive source-weighted signal energy")
    normalization = float(np.sqrt(normalized_reference_power))
    normalized_hb = normalized_hb / normalization
    normalized_hx = (hx / reference_scale) / normalization
    cbb = (normalized_hb * weights) @ normalized_hb.T
    cxx = (normalized_hx * weights) @ normalized_hx.T
    cbx = (normalized_hb * weights) @ normalized_hx.T
    physical_signal_std = float(reference_scale * source_moment_am * normalization)
    physical_signal_power = physical_signal_std * physical_signal_std
    if not np.isfinite(physical_signal_power) or physical_signal_power <= 0:
        raise ValueError("physical reference signal energy underflows or overflows float64")
    # Uniform noise whitening is scalar, so this scale-invariant rank is the
    # same at every SNR. Area weighting is included to avoid mesh-density bias.
    baseline_rank = participation_effective_rank(cbb)
    candidate_rank = participation_effective_rank(cxx)

    bipolar_b = np.ptp(baseline_centered, axis=0)
    bipolar_x = np.ptp(candidate_centered, axis=0)
    zero_voltage_scale = float(np.max(np.abs(baseline_centered)))
    bipolar_threshold = float(2 * numerical_zero_relative_tolerance * zero_voltage_scale)
    valid = bipolar_b > bipolar_threshold
    excluded_area = float(weights[~valid].sum())
    valid_area = float(weights[valid].sum())
    ratios = np.full(baseline.shape[1], np.nan)
    ratios[valid] = bipolar_x[valid] / bipolar_b[valid]
    conditional_tail = (
        weighted_lower_cvar(ratios[valid], weights[valid], source_tail_fraction)
        if valid_area > 0 else None
    )
    sensitivity_available = bool(
        valid_area > 0 and excluded_area <= maximum_excluded_source_area_fraction
    )
    identity_sensitivity = (
        weighted_lower_cvar(np.ones(int(valid.sum())), weights[valid], source_tail_fraction)
        if sensitivity_available else None
    )

    conditions = []
    for snr in snrs:
        with np.errstate(over="ignore", under="ignore"):
            noise_ratio = float(np.power(10.0, -float(snr) / 10.0))
        variance = physical_signal_power * noise_ratio
        if not np.isfinite(variance) or variance <= 0 or not np.isfinite(noise_ratio) or noise_ratio <= 0:
            raise ValueError("SNR produces unrepresentable positive noise variance")
        noisy_b = cbb + noise_ratio * np.eye(63)
        noisy_x = cxx + noise_ratio * np.eye(63)
        field_b = lmmse_explained_energy(cbb, cbb, noisy_b)
        field_x = lmmse_explained_energy(cbb, cbx, noisy_x)
        if not np.isfinite(field_b) or not np.isfinite(field_x):
            raise ValueError("LMMSE produced a nonfinite metric")
        if field_b <= 0 or not -1e-10 <= field_x <= 1 + 1e-10 or field_b > 1 + 1e-10:
            raise ValueError("LMMSE explained energy is outside numerical probability bounds")
        conditions.append({
            "nominal_reference_snr_db": float(snr),
            "shared_physical_electrode_noise_variance_v2": variance,
            "shared_physical_electrode_noise_std_uv": float(np.sqrt(variance) * 1e6),
            "reference_field_explained_energy": field_b,
            "candidate_field_explained_energy": field_x,
            "field_retention_unclipped": relative_retention(field_x, field_b),
            "reference_noise_whitened_area_weighted_effective_rank": baseline_rank,
            "candidate_noise_whitened_area_weighted_effective_rank": candidate_rank,
            "baseline_identity_field_retention": relative_retention(field_b, field_b),
        })

    report: dict[str, object] = {
        "schema_version": "compact-eeg-prototype-metrics/1",
        "scientific_role": "exploratory_fixed64_layout_comparison",
        "formal_v2_performance_eligible": False,
        "ar_computed": False,
        "formal_ar_certification": False,
        "classification_accuracy_computed": False,
        "physical_electrodes_per_layout": 64,
        "reference_free_dimensions": 63,
        "source_count": baseline.shape[1],
        "source_moment_am": float(source_moment_am),
        "source_covariance": "moment_am_squared_times_diagonal_normalized_cortical_area_weights",
        "reference_mean_contrast_signal_power_v2": physical_signal_power,
        "noise_model": "same_sigma_squared_I64_for_both_layouts_at_each_SNR; independent_sensor_noise_conditional_on_shared_sources",
        "target": "clean_reference_Helmert_contrast_field",
        "relative_metrics_clipped_to_one": False,
        "baseline_identity_is_normalization_not_perfect_reconstruction": True,
        "conditions": conditions,
        "source_sensitivity": {
            "source_tail_fraction": float(source_tail_fraction),
            "numerical_zero_rule": "exploratory_unvalidated_relative_voltage_tolerance_not_solver_residual_or_certified_forward_error_bound",
            "numerical_zero_relative_tolerance": float(numerical_zero_relative_tolerance),
            "mean_free_voltage_scale_v_per_am": zero_voltage_scale,
            "bipolar_denominator_threshold_v_per_am": bipolar_threshold,
            "excluded_source_count": int((~valid).sum()),
            "excluded_source_area_fraction": excluded_area,
            "valid_source_area_fraction": valid_area,
            "maximum_excluded_source_area_fraction": float(maximum_excluded_source_area_fraction),
            "within_excluded_area_reporting_budget": sensitivity_available,
            "conditional_tail_denominator": "renormalized_area_of_numerically_resolved_reference_sources",
            "conditional_area_weighted_lower_tail_retention_unclipped": conditional_tail,
            "area_weighted_lower_tail_retention_unclipped": conditional_tail if sensitivity_available else None,
            "baseline_identity_lower_tail_retention": identity_sensitivity,
        },
    }
    return PrototypeMetricResult(
        report=report,
        source_area_weights=weights.copy(),
        reference_bipolar_amplitude_v_per_am=bipolar_b,
        candidate_bipolar_amplitude_v_per_am=bipolar_x,
        sensitivity_ratio=ratios,
        sensitivity_valid_mask=valid,
    )


__all__ = ["PrototypeMetricResult", "evaluate_prototype_metrics"]
