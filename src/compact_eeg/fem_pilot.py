"""Numerical checks around a mature FEM solver, not an alternative FEM solver."""

from __future__ import annotations

import numpy as np
from scipy import sparse


def balanced_point_currents(node_count, electrode_rows, current_amperes=1.0):
    rows = np.asarray(electrode_rows, dtype=np.int64)
    if rows.shape != (4,) or len(np.unique(rows)) != 4:
        raise ValueError("exactly four distinct electrode rows are required")
    if rows.min() < 0 or rows.max() >= node_count:
        raise ValueError("electrode row outside mesh")
    if not np.isfinite(current_amperes) or current_amperes <= 0:
        raise ValueError("normalization current must be positive and finite")
    rhs = np.zeros((node_count, 3), dtype=np.float64)
    rhs[rows[0], :] = -current_amperes
    rhs[rows[1:], np.arange(3)] = current_amperes
    return rhs


def reference_current_transform():
    """Columns map old (1-0,2-0,3-0) currents to (0-1,2-1,3-1)."""
    return np.array([[-1., -1., -1.], [0., 1., 0.], [0., 0., 1.]])


def relative_difference(observed, expected):
    observed, expected = np.asarray(observed), np.asarray(expected)
    if observed.shape != expected.shape:
        raise ValueError("comparison shapes differ")
    if not np.all(np.isfinite(observed)) or not np.all(np.isfinite(expected)):
        raise ValueError("comparison arrays must be finite")
    denom = float(np.linalg.norm(expected))
    absolute = float(np.linalg.norm(observed - expected))
    if denom == 0:
        return 0.0 if absolute == 0 else float("inf")
    return absolute / denom


def local_electric_field(points_mm, local_potentials):
    """E = -grad(V); potentials shape ROI x 4 x RHS, output ROI x 3 x RHS.

    This only evaluates a linear tetrahedron field from already solved nodal
    values. It neither assembles nor solves the global forward system.
    """
    xyz = np.asarray(points_mm, dtype=np.float64)
    values = np.asarray(local_potentials, dtype=np.float64)
    if xyz.ndim != 3 or xyz.shape[1:] != (4, 3):
        raise ValueError("points must have shape (ROI,4,3)")
    if values.ndim != 3 or values.shape[:2] != xyz.shape[:2]:
        raise ValueError("potentials must have shape (ROI,4,RHS)")
    if not np.all(np.isfinite(xyz)) or not np.all(np.isfinite(values)):
        raise ValueError("coordinates and potentials must be finite")
    displacement = xyz[:, 1:] - xyz[:, :1]
    difference = values[:, 1:] - values[:, :1]
    return -1000.0 * np.linalg.solve(displacement, difference)


def system_diagnostics(matrix, potentials, rhs, reference_row):
    a = sparse.csr_matrix(matrix)
    u, b = np.asarray(potentials), np.asarray(rhs)
    if a.shape[0] != a.shape[1] or u.shape != b.shape or u.shape[0] != a.shape[0]:
        raise ValueError("incompatible system shapes")
    if not np.all(np.isfinite(a.data)) or not np.all(np.isfinite(u)) or not np.all(np.isfinite(b)):
        raise ValueError("non-finite matrix, solution or RHS")
    au = a @ u
    residual = au - b
    free_rows = np.arange(a.shape[0]) != reference_row
    denominator = np.linalg.norm(b, axis=0)
    if np.any(denominator == 0):
        raise ValueError("zero right-hand side")
    matrix_norm = float(sparse.linalg.norm(a))
    transfer = b.T @ u
    row_sum = a @ np.ones(a.shape[0])
    diagnostics = {
        "relative_residual_per_rhs": (np.linalg.norm(residual, axis=0) / denominator).tolist(),
        "relative_free_dof_residual_per_rhs": (
            np.linalg.norm(residual[free_rows], axis=0) / np.linalg.norm(b[free_rows], axis=0)
        ).tolist(),
        "maximum_absolute_residual_A": float(np.max(np.abs(residual))),
        "net_prescribed_current_A_per_rhs": np.sum(b, axis=0).tolist(),
        "net_assembled_current_A_per_rhs": np.sum(au, axis=0).tolist(),
        "reference_reaction_current_A_per_rhs": au[reference_row].tolist(),
        "prescribed_reference_current_A_per_rhs": b[reference_row].tolist(),
        "reference_reaction_relative_error_per_rhs": (
            np.abs(residual[reference_row]) / np.max(np.abs(b), axis=0)
        ).tolist(),
        "reference_reaction_normalization": "maximum absolute prescribed nodal current per RHS; valid even if this voltage-gauge node carries zero prescribed current",
        "matrix_symmetry_relative_frobenius": float(sparse.linalg.norm(a - a.T) / matrix_norm),
        "constant_nullspace_scaled_residual": float(
            np.linalg.norm(row_sum) / (matrix_norm * np.sqrt(a.shape[0]))
        ),
        "transfer_reciprocity_relative_frobenius": relative_difference(transfer, transfer.T),
        "transfer_symmetric_min_eigenvalue": float(np.linalg.eigvalsh((transfer + transfer.T) / 2).min()),
        "gauge_potential_V_per_rhs": u[reference_row].tolist(),
    }
    return diagnostics, transfer
