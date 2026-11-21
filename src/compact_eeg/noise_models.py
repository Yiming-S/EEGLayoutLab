"""Electrode-noise models for layout scoring. Independent equal noise is the default.

Every model keeps the reference-calibrated physical noise variance sigma^2
(20 dB at the standard64 reference) and changes only its spatial structure:

* ``spatial``: sensor-level noise with unit marginal variance and Gaussian
  correlation ``N = (1-rho) I + rho exp(-d^2 / 2L^2)`` over electrode
  coordinates (Euclidean, so N is PSD). Closely spaced electrodes share noise:
  averaging them removes less noise, while their differences carry less. The
  net effect on a layout is therefore empirical. Applies to field
  reconstruction, layout search and localization.
* ``brain_background``: localization only. A fraction of the reference noise
  power is ongoing cortical activity, ``kappa * H_dict diag(w) H_dict^T``,
  with kappa fixed at the reference layout so every layout sees the same
  physical background. The field metric reconstructs the whole brain field,
  so background activity is part of its target and is not counted as noise.
  Only the total contrast noise trace at the reference is preserved: the
  background is concentrated in few directions, so most whitened directions
  carry about half the iid noise and the reference localizes better than
  under iid. Compare reference-normalized ratios, not absolute errors.

``None`` means the production iid model; callers keep the original code path
for it so existing results are reproduced bit for bit.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial.distance import cdist

from .metrics import helmert_contrast

SPATIAL_RHO = (0.5,)
SPATIAL_LENGTH_MM = (10, 20, 40)
BACKGROUND_FRACTION = (0.5,)


def normalize(raw, *, allow_brain_background=True):
    """Canonical model dict, or None for the default iid model."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str):
        raise ValueError("noise_model must be an object with a kind")
    kind = raw["kind"]
    if kind == "iid":
        if set(raw) != {"kind"}:
            raise ValueError("iid noise_model takes no parameters")
        return None
    if kind == "spatial":
        rho, length = raw.get("rho"), raw.get("length_mm")
        if set(raw) != {"kind", "rho", "length_mm"} or rho not in SPATIAL_RHO or type(rho) is not float \
                or length not in SPATIAL_LENGTH_MM or type(length) is not int:
            raise ValueError(f"spatial noise_model requires rho in {SPATIAL_RHO} and integer length_mm in {SPATIAL_LENGTH_MM}")
        return {"kind": "spatial", "rho": rho, "length_mm": length}
    if kind == "brain_background":
        if not allow_brain_background:
            raise ValueError("brain_background noise applies to localization only; layout search optimizes field and sensitivity")
        fraction = raw.get("fraction")
        if set(raw) != {"kind", "fraction"} or fraction not in BACKGROUND_FRACTION or type(fraction) is not float:
            raise ValueError(f"brain_background noise_model requires fraction in {BACKGROUND_FRACTION}")
        return {"kind": "brain_background", "fraction": fraction}
    raise ValueError("noise_model kind must be iid, spatial or brain_background")


def describe(model):
    """Provenance entry; the iid text is the historical one."""
    if model is None:
        return "iid_equal_variance"
    if model["kind"] == "spatial":
        return {"kind": "spatial_gaussian_correlation", "rho": model["rho"], "length_mm": model["length_mm"],
                "marginal_variance": "reference-calibrated sigma^2 at every electrode", "applies_to": ["field", "localization", "search"]}
    # kappa / signal-prior scale is fraction * 10^(-20/10) at the nominal 20 dB reference SNR.
    return {"kind": "brain_background", "background_fraction_at_reference": model["fraction"],
            "background_prior": "dictionary sources, cortical-area weights", "applies_to": ["localization"],
            "background_scale_relative_to_signal_prior": model["fraction"] * 10 ** (-20 / 10),
            "calibration": "equal_total_contrast_noise_trace_at_reference; per-direction whitened noise is not preserved"}


def field_kernel(model):
    """(rho, length_mm) when the field metric uses correlated noise, else None."""
    return (model["rho"], model["length_mm"]) if model and model["kind"] == "spatial" else None


def gaussian_cross(a_xyz_mm, b_xyz_mm, rho, length_mm):
    """Off-diagonal correlation between distinct electrodes."""
    a, b = np.asarray(a_xyz_mm, dtype=float), np.asarray(b_xyz_mm, dtype=float)
    return rho * np.exp(-cdist(a, b, "sqeuclidean") / (2.0 * length_mm * length_mm))


def spatial_correlation(xyz_mm, rho, length_mm):
    """Unit-diagonal PSD correlation for one set of distinct electrodes."""
    xyz = np.asarray(xyz_mm, dtype=float)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.all(np.isfinite(xyz)):
        raise ValueError("noise coordinates must be finite xyz rows")
    if not 0 <= rho < 1 or not length_mm > 0:
        raise ValueError("rho must be in [0,1) and length positive")
    return (1 - rho) * np.eye(len(xyz)) + gaussian_cross(xyz, xyz, rho, length_mm)


def background_scale(reference_dictionary_field, source_weights, sensor_variance, fraction, moment_am):
    """kappa so background contributes ``fraction`` of the reference contrast noise power."""
    weights = np.asarray(source_weights, dtype=float)
    weights = weights / weights.sum()
    contrast = helmert_contrast(64) @ np.asarray(reference_dictionary_field, dtype=float) * moment_am
    power = float(np.sum(contrast * contrast * weights)) / 63
    if not np.isfinite(power) or power <= 0:
        raise ValueError("reference background power must be positive")
    return fraction * sensor_variance / power


def localization_covariance(model, xyz_mm, dictionary_field, source_weights, sensor_variance, moment_am, kappa=None):
    """Physical 64x64 noise covariance (V^2) for localization, or None for iid."""
    if model is None:
        return None
    if model["kind"] == "spatial":
        return sensor_variance * spatial_correlation(xyz_mm, model["rho"], model["length_mm"])
    weights = np.asarray(source_weights, dtype=float)
    weights = weights / weights.sum()
    field = np.asarray(dictionary_field, dtype=float) * moment_am
    background = (field * weights) @ field.T
    covariance = (1 - model["fraction"]) * sensor_variance * np.eye(64) + kappa * background
    return .5 * (covariance + covariance.T)


__all__ = ["normalize", "describe", "field_kernel", "gaussian_cross", "spatial_correlation",
           "background_scale", "localization_covariance"]
