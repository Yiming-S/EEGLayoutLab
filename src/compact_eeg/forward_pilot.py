"""Numerical diagnostics for the Stage-2 forward-model qualification pilot.

This module contains no layout search and no acceptance-rate calculation.  It
only provides deterministic source selection, reference-free forward checks,
and immutable NumPy artifact serialization.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import tempfile
from typing import Mapping
import zipfile

import numpy as np

from compact_eeg.metrics import helmert_contrast


@dataclass(frozen=True)
class ForwardDiagnostics:
    """Reference and noiseless self-reconstruction diagnostics."""

    helmert: np.ndarray
    reference_free_leadfield: np.ndarray
    singular_values: np.ndarray
    report: dict[str, object]


def deterministic_farthest_point_indices(
    points: np.ndarray,
    count: int,
) -> np.ndarray:
    """Select a deterministic Euclidean farthest-point subset.

    The first selected row is row zero.  Each subsequent row maximizes its
    minimum Euclidean distance to the selected rows.  ``numpy.argmax`` gives a
    deterministic lowest-index tie break.  Returned indices are in selection
    order.
    """
    coordinates = np.asarray(points, dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[1] != 3:
        raise ValueError("points must have shape (n_points, 3)")
    if not np.all(np.isfinite(coordinates)):
        raise ValueError("points must be finite")
    if not isinstance(count, (int, np.integer)) or isinstance(count, (bool, np.bool_)):
        raise ValueError("count must be a positive integer")
    if int(count) < 1 or int(count) > coordinates.shape[0]:
        raise ValueError("count must lie in [1, n_points]")

    selected = np.empty(int(count), dtype=np.int64)
    selected[0] = 0
    minimum_squared_distance = np.full(coordinates.shape[0], np.inf)
    for output_index in range(1, int(count)):
        delta = coordinates - coordinates[selected[output_index - 1]]
        squared_distance = np.einsum("ij,ij->i", delta, delta)
        minimum_squared_distance = np.minimum(
            minimum_squared_distance, squared_distance
        )
        minimum_squared_distance[selected[:output_index]] = -np.inf
        selected[output_index] = int(np.argmax(minimum_squared_distance))
    return selected


def compute_forward_diagnostics(
    leadfield: np.ndarray,
    *,
    lmmse_rcond: float = 1e-12,
) -> ForwardDiagnostics:
    """Check reference invariance and noiseless self-reconstruction.

    ``leadfield`` has one row per physical EEG electrode and one column per
    fixed-orientation source.  LMMSE self-reconstruction uses the same
    reference-free observation as target, a unit source covariance, no noise,
    and a Moore-Penrose inverse.  This is an identity qualification check, not
    a performance estimate.
    """
    matrix = np.asarray(leadfield, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 1:
        raise ValueError("leadfield must have shape (n_electrodes >= 2, n_sources >= 1)")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("leadfield must be finite")
    if not np.isfinite(lmmse_rcond) or not 0 < lmmse_rcond < 1:
        raise ValueError("lmmse_rcond must lie in (0, 1)")

    electrode_count, source_count = matrix.shape
    helmert = helmert_contrast(electrode_count)
    reference_free = helmert @ matrix

    matrix_scale = max(float(np.max(np.abs(matrix))), np.finfo(float).tiny)
    common_potential = matrix_scale * np.linspace(-0.5, 0.5, source_count)
    shifted = matrix + np.ones((electrode_count, 1)) @ common_potential[None, :]
    shifted_reference_free = helmert @ shifted
    reference_difference = shifted_reference_free - reference_free
    reference_denominator = max(
        float(np.linalg.norm(reference_free, ord="fro")), np.finfo(float).tiny
    )

    identity_reconstructed = np.eye(electrode_count - 1) @ reference_free
    identity_error = identity_reconstructed - reference_free
    reference_energy = float(np.sum(reference_free * reference_free))
    if reference_energy <= 0:
        raise ValueError("reference-free leadfield must have positive energy")

    covariance = reference_free @ reference_free.T / float(source_count)
    covariance_eigenvalues = np.linalg.eigvalsh(covariance)
    covariance_pinv_cutoff = float(lmmse_rcond) * float(
        np.max(np.abs(covariance_eigenvalues))
    )
    covariance_pinv_effective_rank = int(
        np.count_nonzero(np.abs(covariance_eigenvalues) > covariance_pinv_cutoff)
    )
    covariance_inverse = np.linalg.pinv(
        covariance, rcond=float(lmmse_rcond), hermitian=True
    )
    lmmse_operator = covariance @ covariance_inverse
    lmmse_reconstructed = lmmse_operator @ reference_free
    lmmse_error = lmmse_reconstructed - reference_free
    lmmse_relative_mse = float(np.sum(lmmse_error * lmmse_error) / reference_energy)
    covariance_energy = float(np.trace(covariance))
    lmmse_explained_energy = float(
        np.trace(covariance @ covariance_inverse @ covariance) / covariance_energy
    )

    singular_values = np.linalg.svd(reference_free, compute_uv=False)
    positive = singular_values[singular_values > singular_values[0] * float(lmmse_rcond)]
    numerical_rank = int(positive.size)
    condition_number = (
        float(positive[0] / positive[-1]) if positive.size else float("inf")
    )
    if not np.isfinite(condition_number):
        raise ValueError("reference-free leadfield has zero numerical rank")

    common_mode_residual = helmert @ np.ones(electrode_count)
    orthonormal_residual = helmert @ helmert.T - np.eye(electrode_count - 1)
    report: dict[str, object] = {
        "leadfield": {
            "shape": [int(electrode_count), int(source_count)],
            "finite": True,
            "minimum": float(matrix.min()),
            "maximum": float(matrix.max()),
            "frobenius_norm": float(np.linalg.norm(matrix, ord="fro")),
        },
        "helmert": {
            "shape": [int(value) for value in helmert.shape],
            "common_mode_max_abs_residual": float(
                np.max(np.abs(common_mode_residual))
            ),
            "row_orthonormal_max_abs_residual": float(
                np.max(np.abs(orthonormal_residual))
            ),
        },
        "reference_free_leadfield": {
            "shape": [int(value) for value in reference_free.shape],
            "finite": bool(np.all(np.isfinite(reference_free))),
            "svd_relative_cutoff": float(lmmse_rcond),
            "svd_numerical_rank": numerical_rank,
            "svd_condition_number": condition_number,
            "covariance_pinv_relative_cutoff": float(lmmse_rcond),
            "covariance_pinv_implied_svd_relative_cutoff": float(np.sqrt(lmmse_rcond)),
            "covariance_pinv_effective_rank": covariance_pinv_effective_rank,
            "legacy_rank_fields_semantics": (
                "numerical_rank_at_lmmse_rcond and condition_number_at_lmmse_rcond "
                "retain the historical singular_value_relative_cutoff_rcond "
                "meaning; they do not count covariance pseudoinverse modes"
            ),
            "numerical_rank_at_lmmse_rcond": numerical_rank,
            "condition_number_at_lmmse_rcond": condition_number,
        },
        "reference_invariance": {
            "construction": "add_one_vector_times_deterministic_nonzero_common_potential",
            "common_potential_max_abs": float(np.max(np.abs(common_potential))),
            "maximum_absolute_difference": float(
                np.max(np.abs(reference_difference))
            ),
            "relative_frobenius_difference": float(
                np.linalg.norm(reference_difference, ord="fro")
                / reference_denominator
            ),
        },
        "identity_self_reconstruction": {
            "target_equals_observation": True,
            "noise": "none",
            "relative_mse": float(
                np.sum(identity_error * identity_error) / reference_energy
            ),
        },
        "lmmse_self_reconstruction": {
            "target_equals_observation": True,
            "source_covariance": "identity_over_fixed_normal_sources",
            "observation_noise": "none",
            "inverse": "moore_penrose_hermitian",
            "rcond": float(lmmse_rcond),
            "covariance_pinv_absolute_cutoff": covariance_pinv_cutoff,
            "covariance_pinv_effective_rank": covariance_pinv_effective_rank,
            "relative_mse": lmmse_relative_mse,
            "explained_energy": lmmse_explained_energy,
        },
    }
    return ForwardDiagnostics(
        helmert=helmert,
        reference_free_leadfield=reference_free,
        singular_values=singular_values,
        report=report,
    )


def deterministic_npz_bytes(arrays: Mapping[str, np.ndarray]) -> bytes:
    """Serialize arrays as a byte-stable, pickle-free compressed NPZ."""
    archive_buffer = BytesIO()
    with zipfile.ZipFile(
        archive_buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for name in sorted(arrays):
            if not isinstance(name, str) or not name or "/" in name or "\\" in name:
                raise ValueError("NPZ member names must be non-empty simple strings")
            array = np.asarray(arrays[name])
            if array.dtype.hasobject:
                raise ValueError("object arrays are forbidden in qualification artifacts")
            member_buffer = BytesIO()
            np.lib.format.write_array(member_buffer, array, allow_pickle=False)
            metadata = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            metadata.compress_type = zipfile.ZIP_DEFLATED
            metadata.create_system = 3
            metadata.external_attr = 0o100644 << 16
            archive.writestr(
                metadata,
                member_buffer.getvalue(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return archive_buffer.getvalue()


def write_npz_once(
    path: str | os.PathLike[str], arrays: Mapping[str, np.ndarray]
) -> str:
    """Publish deterministic NPZ bytes without replacing an existing artifact."""
    import hashlib

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = deterministic_npz_bytes(arrays)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as error:
            raise FileExistsError(
                f"immutable NPZ artifact already exists: {destination}"
            ) from error
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "ForwardDiagnostics",
    "compute_forward_diagnostics",
    "deterministic_farthest_point_indices",
    "deterministic_npz_bytes",
    "write_npz_once",
]
