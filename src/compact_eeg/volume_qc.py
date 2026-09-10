"""Geometry-only diagnostics for linear tetrahedra; this is not a FEM solver."""

from __future__ import annotations

import numpy as np


def tetrahedron_metrics(points: np.ndarray) -> dict[str, np.ndarray]:
    """Return signed volume and mean-ratio shape quality for M x 4 x 3 points.

    Volume has the cube of the input length unit. Mean-ratio quality is one
    for a regular tetrahedron and approaches zero for a degenerate shape.
    Quality alone does not certify a conforming volume mesh or a FEM solve.
    """
    xyz = np.asarray(points, dtype=np.float64)
    if xyz.ndim != 3 or xyz.shape[1:] != (4, 3):
        raise ValueError("points must have shape (M, 4, 3)")
    if not np.all(np.isfinite(xyz)):
        raise ValueError("tetrahedron coordinates must be finite")
    differences = xyz[:, 1:, :] - xyz[:, :1, :]
    signed_volume = np.linalg.det(differences) / 6.0
    squared_edges = np.zeros(len(xyz), dtype=np.float64)
    for left in range(4):
        for right in range(left + 1, 4):
            edge = xyz[:, right] - xyz[:, left]
            squared_edges += np.einsum("ij,ij->i", edge, edge)
    quality = np.zeros(len(xyz), dtype=np.float64)
    np.divide(
        12.0 * np.power(3.0 * np.abs(signed_volume), 2.0 / 3.0),
        squared_edges,
        out=quality,
        where=squared_edges > 0,
    )
    return {"signed_volume": signed_volume, "mean_ratio_quality": quality}
