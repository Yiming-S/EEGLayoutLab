"""Held-out covariance stresses with a genuinely frozen reconstruction map.

Source covariance includes off-diagonal terms. Single-source localization is
reported separately and never relabeled a simultaneous multi-source test.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial.distance import cdist

from .inverse_pilot import fixed_normal_scan
from .robustness_metrics import contrast_field, contrast_noise, normalized_weights


def source_covariance(xyz_mm, weights, *, rho=0., length_mm=20.):
    xyz = np.asarray(xyz_mm, float)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all():
        raise ValueError("finite source coordinates required")
    if not np.isfinite(rho) or not 0 <= rho < 1 or not np.isfinite(length_mm) or length_mm <= 0:
        raise ValueError("invalid source correlation")
    w = normalized_weights(weights, len(xyz))
    kernel = np.exp(-cdist(xyz, xyz, "sqeuclidean") / (2 * length_mm**2))
    q = np.sqrt(w[:, None] * w[None, :]) * ((1-rho)*np.eye(len(w)) + rho*kernel)
    return q


def covariance_field_score(reference, candidate, decoder, covariance, noise64):
    """Exact E[error^2], without fitting, clipping or test-SNR renormalization."""
    hb, hx = contrast_field(reference), contrast_field(candidate)
    a, q = np.asarray(decoder, float), np.asarray(covariance, float)
    if a.shape != (63, 63) or hb.shape != hx.shape or q.shape != (hb.shape[1], hb.shape[1]):
        raise ValueError("field covariance dimensions disagree")
    if not np.isfinite(a).all() or not np.isfinite(q).all() or not np.allclose(q, q.T):
        raise ValueError("finite symmetric source covariance required")
    error = hb-a@hx
    target = float(np.sum((hb@q)*hb))
    signal_mse = float(np.sum((error@q)*error))
    noise_mse = float(np.trace(a@contrast_noise(noise64)@a.T))
    if target <= 0:
        raise ValueError("positive target energy required")
    return {"field_absolute": 1-(signal_mse+noise_mse)/target,
            "target_energy_v2": target, "signal_mse_v2": signal_mse, "noise_mse_v2": noise_mse}


def frozen_localization(dictionary, generation, dictionary_xyz_mm, source_xyz_mm,
                        actual_noise64, frozen_noise64, standard_noise63):
    """Actual test noise changes; scanner's declared training whitening does not."""
    hd, hg = contrast_field(dictionary), contrast_field(generation)
    z = np.asarray(standard_noise63, float)
    if z.ndim != 3 or z.shape[:2] != hg.shape:
        raise ValueError("noise draw dimensions disagree")
    actual, assumed = contrast_noise(actual_noise64), contrast_noise(frozen_noise64)
    scale = float(np.sqrt(np.max(np.diag(assumed))))
    y = hg[:, :, None]/scale + np.einsum("ij,jqr->iqr", np.linalg.cholesky(actual)/scale, z)
    ids = fixed_normal_scan(hd/scale, y.reshape(63, -1), assumed/scale**2, batch_size=512).reshape(z.shape[1:])
    errors = np.linalg.norm(np.asarray(dictionary_xyz_mm)[ids] - np.asarray(source_xyz_mm)[:, None], axis=2)
    return {"errors_mm": errors, "estimated_indices": ids}
