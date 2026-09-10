"""Solver-independent quality control for triangular surface meshes.

The module deliberately depends only on NumPy.  Coordinates are expressed in
metres, so all returned areas are in square metres.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SurfaceMeshQC:
    """Complete geometric and topological QC summary for one surface mesh."""

    vertex_count: int
    triangle_count: int
    vertices_are_finite: bool
    triangle_areas_are_finite: bool
    all_finite: bool
    triangle_areas_m2: np.ndarray
    total_area_m2: float
    unique_edges: np.ndarray
    edge_incidence_counts: np.ndarray
    boundary_edges: np.ndarray
    nonmanifold_edges: np.ndarray
    boundary_edge_count: int
    nonmanifold_edge_count: int
    degenerate_triangle_indices: np.ndarray
    degenerate_triangle_count: int
    connected_component_labels: np.ndarray
    connected_component_count: int
    vertex_area_weights_m2: np.ndarray


def _validated_mesh_arrays(
    vertices_m: np.ndarray,
    triangles: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Validate array structure and indices without hiding non-finite vertices."""
    vertices = np.asarray(vertices_m, dtype=float)
    faces_raw = np.asarray(triangles)

    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("vertices_m must have shape (n_vertices, 3)")
    if faces_raw.ndim != 2 or faces_raw.shape[1] != 3:
        raise ValueError("triangles must have shape (n_triangles, 3)")
    if not np.issubdtype(faces_raw.dtype, np.integer) or np.issubdtype(
        faces_raw.dtype, np.bool_
    ):
        raise ValueError("triangles must contain integer vertex indices")

    faces = faces_raw.astype(np.int64, copy=False)
    if faces.size:
        if int(faces.min()) < 0:
            raise ValueError("triangles contain a negative vertex index")
        if int(faces.max()) >= vertices.shape[0]:
            raise ValueError("triangles contain an out-of-range vertex index")
    return vertices, faces


def _validate_area_tolerance(area_tolerance_m2: float) -> float:
    tolerance = float(area_tolerance_m2)
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("area_tolerance_m2 must be finite and non-negative")
    return tolerance


def triangle_areas(vertices_m: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Return the Euclidean area of each triangle in square metres."""
    vertices, faces = _validated_mesh_arrays(vertices_m, triangles)
    if faces.shape[0] == 0:
        return np.empty(0, dtype=float)
    first = vertices[faces[:, 1]] - vertices[faces[:, 0]]
    second = vertices[faces[:, 2]] - vertices[faces[:, 0]]
    return 0.5 * np.linalg.norm(np.cross(first, second), axis=1)


def total_area(vertices_m: np.ndarray, triangles: np.ndarray) -> float:
    """Return total triangle area in square metres."""
    return float(np.sum(triangle_areas(vertices_m, triangles)))


def edge_incidence_counts(
    triangles: np.ndarray,
    *,
    vertex_count: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return sorted undirected edges and their triangle-incidence counts.

    ``vertex_count`` is optional because edge topology only requires triangle
    indices.  Supplying it additionally checks that all indices are in range.
    """
    faces_raw = np.asarray(triangles)
    if faces_raw.ndim != 2 or faces_raw.shape[1] != 3:
        raise ValueError("triangles must have shape (n_triangles, 3)")
    if not np.issubdtype(faces_raw.dtype, np.integer) or np.issubdtype(
        faces_raw.dtype, np.bool_
    ):
        raise ValueError("triangles must contain integer vertex indices")
    faces = faces_raw.astype(np.int64, copy=False)
    if faces.size and int(faces.min()) < 0:
        raise ValueError("triangles contain a negative vertex index")
    if vertex_count is not None:
        if not isinstance(vertex_count, (int, np.integer)) or isinstance(vertex_count, (bool, np.bool_)):
            raise ValueError("vertex_count must be a non-negative integer")
        if int(vertex_count) < 0:
            raise ValueError("vertex_count must be a non-negative integer")
        if faces.size and int(faces.max()) >= int(vertex_count):
            raise ValueError("triangles contain an out-of-range vertex index")

    if faces.shape[0] == 0:
        return np.empty((0, 2), dtype=np.int64), np.empty(0, dtype=np.int64)

    edges = np.concatenate(
        (faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]), axis=0
    )
    edges.sort(axis=1)
    unique_edges, counts = np.unique(edges, axis=0, return_counts=True)
    return unique_edges, counts.astype(np.int64, copy=False)


def degenerate_triangle_mask(
    vertices_m: np.ndarray,
    triangles: np.ndarray,
    *,
    area_tolerance_m2: float = 0.0,
) -> np.ndarray:
    """Flag repeated-index or finite near-zero-area triangles.

    Non-finite triangles are not labelled degenerate; they are reported by the
    separate finite-coordinate QC fields in :func:`inspect_surface_mesh`.
    """
    tolerance = _validate_area_tolerance(area_tolerance_m2)
    vertices, faces = _validated_mesh_arrays(vertices_m, triangles)
    areas = triangle_areas(vertices, faces)
    repeated_index = (
        (faces[:, 0] == faces[:, 1])
        | (faces[:, 1] == faces[:, 2])
        | (faces[:, 2] == faces[:, 0])
    )
    return repeated_index | (np.isfinite(areas) & (areas <= tolerance))


def connected_components(
    vertices_m: np.ndarray,
    triangles: np.ndarray,
) -> tuple[int, np.ndarray]:
    """Return vertex-graph component count and a deterministic label per vertex.

    Isolated vertices count as separate components.  Labels are consecutive and
    assigned in increasing order of the first vertex in each component.
    """
    vertices, faces = _validated_mesh_arrays(vertices_m, triangles)
    vertex_count = vertices.shape[0]
    if vertex_count == 0:
        return 0, np.empty(0, dtype=np.int64)

    parent = np.arange(vertex_count, dtype=np.int64)
    rank = np.zeros(vertex_count, dtype=np.int8)

    def find(index: int) -> int:
        root = index
        while int(parent[root]) != root:
            root = int(parent[root])
        while int(parent[index]) != index:
            next_index = int(parent[index])
            parent[index] = root
            index = next_index
        return root

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        if rank[first_root] < rank[second_root]:
            first_root, second_root = second_root, first_root
        parent[second_root] = first_root
        if rank[first_root] == rank[second_root]:
            rank[first_root] += 1

    for first, second, third in faces:
        union(int(first), int(second))
        union(int(second), int(third))
        union(int(third), int(first))

    roots = np.fromiter((find(index) for index in range(vertex_count)), dtype=np.int64)
    _, labels = np.unique(roots, return_inverse=True)
    return int(labels.max()) + 1, labels.astype(np.int64, copy=False)


def vertex_area_weights(vertices_m: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Return barycentric vertex areas, one third of each incident face area."""
    vertices, faces = _validated_mesh_arrays(vertices_m, triangles)
    weights = np.zeros(vertices.shape[0], dtype=float)
    if faces.shape[0] == 0:
        return weights
    shares = np.repeat(triangle_areas(vertices, faces) / 3.0, 3)
    np.add.at(weights, faces.reshape(-1), shares)
    return weights


def inspect_surface_mesh(
    vertices_m: np.ndarray,
    triangles: np.ndarray,
    *,
    area_tolerance_m2: float = 0.0,
) -> SurfaceMeshQC:
    """Compute geometry, topology, finiteness, and area-weight QC diagnostics."""
    tolerance = _validate_area_tolerance(area_tolerance_m2)
    vertices, faces = _validated_mesh_arrays(vertices_m, triangles)
    areas = triangle_areas(vertices, faces)
    unique_edges, incidences = edge_incidence_counts(
        faces, vertex_count=vertices.shape[0]
    )
    boundary_edges = unique_edges[incidences == 1]
    nonmanifold_edges = unique_edges[incidences > 2]
    degenerate_mask = degenerate_triangle_mask(
        vertices, faces, area_tolerance_m2=tolerance
    )
    component_count, component_labels = connected_components(vertices, faces)
    area_weights = vertex_area_weights(vertices, faces)
    vertices_are_finite = bool(np.all(np.isfinite(vertices)))
    triangle_areas_are_finite = bool(np.all(np.isfinite(areas)))
    total_area_m2 = float(np.sum(areas))

    return SurfaceMeshQC(
        vertex_count=int(vertices.shape[0]),
        triangle_count=int(faces.shape[0]),
        vertices_are_finite=vertices_are_finite,
        triangle_areas_are_finite=triangle_areas_are_finite,
        all_finite=bool(
            vertices_are_finite
            and triangle_areas_are_finite
            and np.isfinite(total_area_m2)
            and np.all(np.isfinite(area_weights))
        ),
        triangle_areas_m2=areas,
        total_area_m2=total_area_m2,
        unique_edges=unique_edges,
        edge_incidence_counts=incidences,
        boundary_edges=boundary_edges,
        nonmanifold_edges=nonmanifold_edges,
        boundary_edge_count=int(boundary_edges.shape[0]),
        nonmanifold_edge_count=int(nonmanifold_edges.shape[0]),
        degenerate_triangle_indices=np.flatnonzero(degenerate_mask),
        degenerate_triangle_count=int(np.count_nonzero(degenerate_mask)),
        connected_component_labels=component_labels,
        connected_component_count=component_count,
        vertex_area_weights_m2=area_weights,
    )


# Explicit aliases retain the units at call sites where that improves clarity.
triangle_areas_m2 = triangle_areas
total_surface_area_m2 = total_area
vertex_area_weights_m2 = vertex_area_weights
surface_mesh_qc = inspect_surface_mesh


__all__ = [
    "SurfaceMeshQC",
    "connected_components",
    "degenerate_triangle_mask",
    "edge_incidence_counts",
    "inspect_surface_mesh",
    "surface_mesh_qc",
    "total_area",
    "total_surface_area_m2",
    "triangle_areas",
    "triangle_areas_m2",
    "vertex_area_weights",
    "vertex_area_weights_m2",
]
