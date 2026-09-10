"""Geometry-only construction checks for balanced two-region 64-node layouts.

The regions built here are coordinate-clipped mesh-edge-Dijkstra domains on a
single scalp mesh.  They are not expert-reviewed anatomical or hair masks, and
their radius is a construction cap rather than an exact or minimum continuous
surface-geodesic radius.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.sparse import csr_matrix
from scipy.spatial import cKDTree

from compact_eeg.packing_pilot import minimum_pairwise_chord_distance


@dataclass(frozen=True)
class CoordinateClippedPatch:
    """Connected component of a coordinate-clipped graph-radius vertex mask."""

    candidate_vertex_indices: np.ndarray
    graph_disk_vertex_count: int
    coordinate_clipped_vertex_count: int
    disconnected_vertex_count_removed: int
    maximum_candidate_graph_path_distance_m: float


@dataclass(frozen=True)
class BalancedTwoRegionLayout:
    """A validated 32+32 layout and its conservative spacing diagnostics."""

    electrode_vertex_indices: np.ndarray
    electrode_region_indices: np.ndarray
    minimum_global_chord_distance_m: float
    minimum_cross_region_chord_distance_m: float
    minimum_candidate_patch_cross_chord_distance_m: float


def _validated_vertices(vertices_m: np.ndarray) -> np.ndarray:
    vertices = np.asarray(vertices_m, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("vertices_m must have shape (n_vertices, 3)")
    if len(vertices) < 1 or not np.all(np.isfinite(vertices)):
        raise ValueError("vertices_m must be non-empty and finite")
    return vertices


def _validated_xyz_vector(value: np.ndarray, *, name: str) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float64)
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must be a finite length-three vector")
    return vector


def coordinate_roi_mask(
    vertices_m: np.ndarray,
    inclusive_min_xyz_m: np.ndarray,
    inclusive_max_xyz_m: np.ndarray,
    *,
    exclusion_ellipsoid_centers_m: np.ndarray | None = None,
    exclusion_ellipsoid_radii_m: np.ndarray | None = None,
) -> np.ndarray:
    """Return an explicit coordinate-box mask minus approximate ellipsoids.

    Ellipsoid boundary points are excluded.  Empty ellipsoid arrays are
    accepted.  This function attaches no anatomical meaning to either rule.
    """

    vertices = _validated_vertices(vertices_m)
    lower = _validated_xyz_vector(inclusive_min_xyz_m, name="inclusive_min_xyz_m")
    upper = _validated_xyz_vector(inclusive_max_xyz_m, name="inclusive_max_xyz_m")
    if np.any(lower > upper):
        raise ValueError("inclusive coordinate-box minimum exceeds maximum")
    mask = np.all((vertices >= lower) & (vertices <= upper), axis=1)

    if exclusion_ellipsoid_centers_m is None:
        centers = np.empty((0, 3), dtype=np.float64)
    else:
        centers = np.asarray(exclusion_ellipsoid_centers_m, dtype=np.float64)
    if exclusion_ellipsoid_radii_m is None:
        radii = np.empty((0, 3), dtype=np.float64)
    else:
        radii = np.asarray(exclusion_ellipsoid_radii_m, dtype=np.float64)
    if centers.ndim != 2 or centers.shape[1:] != (3,):
        raise ValueError("exclusion ellipsoid centers must have shape (n, 3)")
    if radii.shape != centers.shape:
        raise ValueError("exclusion ellipsoid radii must match center shape")
    if not np.all(np.isfinite(centers)) or not np.all(np.isfinite(radii)):
        raise ValueError("exclusion ellipsoids must be finite")
    if np.any(radii <= 0.0):
        raise ValueError("exclusion ellipsoid radii must be positive")
    for center, radius in zip(centers, radii, strict=True):
        normalized_squared = np.sum(((vertices - center) / radius) ** 2, axis=1)
        mask &= normalized_squared > 1.0
    return mask


def center_connected_component_indices(
    adjacency: csr_matrix,
    allowed_vertex_mask: np.ndarray,
    center_vertex_index: int,
) -> np.ndarray:
    """Return sorted vertices reachable from center inside an induced mask."""

    graph = adjacency.tocsr(copy=False)
    if graph.shape[0] < 1 or graph.shape[0] != graph.shape[1]:
        raise ValueError("adjacency must be a non-empty square matrix")
    mask = np.asarray(allowed_vertex_mask, dtype=bool)
    if mask.shape != (graph.shape[0],):
        raise ValueError("allowed_vertex_mask has an invalid shape")
    center = int(center_vertex_index)
    if center < 0 or center >= graph.shape[0]:
        raise ValueError("center_vertex_index is out of range")
    if not mask[center]:
        raise ValueError("center vertex is excluded from the allowed mask")

    visited = np.zeros(graph.shape[0], dtype=bool)
    visited[center] = True
    queue: deque[int] = deque([center])
    while queue:
        source = queue.popleft()
        neighbors = graph.indices[graph.indptr[source] : graph.indptr[source + 1]]
        for neighbor_raw in neighbors:
            neighbor = int(neighbor_raw)
            if mask[neighbor] and not visited[neighbor]:
                visited[neighbor] = True
                queue.append(neighbor)
    return np.flatnonzero(visited).astype(np.int64, copy=False)


def build_coordinate_clipped_patch(
    adjacency: csr_matrix,
    center_graph_distances_m: np.ndarray,
    coordinate_mask: np.ndarray,
    center_vertex_index: int,
    *,
    graph_path_radius_m: float,
) -> CoordinateClippedPatch:
    """Build the center component of graph disk intersected with coordinates."""

    graph = adjacency.tocsr(copy=False)
    distances = np.asarray(center_graph_distances_m, dtype=np.float64)
    coordinates = np.asarray(coordinate_mask, dtype=bool)
    radius = float(graph_path_radius_m)
    if distances.shape != (graph.shape[0],) or np.any(np.isnan(distances)):
        raise ValueError("center_graph_distances_m has an invalid shape or NaN")
    if coordinates.shape != (graph.shape[0],):
        raise ValueError("coordinate_mask has an invalid shape")
    if not np.isfinite(radius) or radius <= 0.0:
        raise ValueError("graph_path_radius_m must be finite and positive")

    graph_disk_mask = np.isfinite(distances) & (distances <= radius)
    clipped_mask = graph_disk_mask & coordinates
    clipped_count = int(np.count_nonzero(clipped_mask))
    component = center_connected_component_indices(
        graph,
        clipped_mask,
        center_vertex_index,
    )
    return CoordinateClippedPatch(
        candidate_vertex_indices=component,
        graph_disk_vertex_count=int(np.count_nonzero(graph_disk_mask)),
        coordinate_clipped_vertex_count=clipped_count,
        disconnected_vertex_count_removed=clipped_count - int(component.size),
        maximum_candidate_graph_path_distance_m=float(distances[component].max()),
    )


def minimum_cross_set_chord_distance(
    vertices_m: np.ndarray,
    first_vertex_indices: Iterable[int] | np.ndarray,
    second_vertex_indices: Iterable[int] | np.ndarray,
) -> float:
    """Return the exact nearest Euclidean 3-D chord between two vertex sets."""

    vertices = _validated_vertices(vertices_m)
    first = np.asarray(list(first_vertex_indices), dtype=np.int64)
    second = np.asarray(list(second_vertex_indices), dtype=np.int64)
    for name, indices in (("first", first), ("second", second)):
        if indices.ndim != 1 or indices.size < 1:
            raise ValueError(f"{name} vertex indices must be a non-empty vector")
        if int(indices.min()) < 0 or int(indices.max()) >= len(vertices):
            raise ValueError(f"{name} vertex indices contain an out-of-range value")
        if np.unique(indices).size != indices.size:
            raise ValueError(f"{name} vertex indices must be unique")
    distances, _ = cKDTree(vertices[second]).query(vertices[first], k=1, workers=1)
    return float(np.min(distances))


def assemble_balanced_two_region_layout(
    vertices_m: np.ndarray,
    first_selected_vertex_indices: np.ndarray,
    second_selected_vertex_indices: np.ndarray,
    first_candidate_patch_indices: np.ndarray,
    second_candidate_patch_indices: np.ndarray,
    *,
    points_per_region: int = 32,
    minimum_chord_distance_m: float,
) -> BalancedTwoRegionLayout:
    """Validate and concatenate two disjoint connected-patch selections.

    Patch connectivity must be established by the caller with
    :func:`build_coordinate_clipped_patch`.  This function enforces exact
    balance, disjoint candidate patches, 64 unique nodes, selected-point
    membership, and conservative chord spacing for both the full patches and
    the final selected nodes.
    """

    vertices = _validated_vertices(vertices_m)
    expected = int(points_per_region)
    spacing = float(minimum_chord_distance_m)
    if expected < 1:
        raise ValueError("points_per_region must be positive")
    if not np.isfinite(spacing) or spacing <= 0.0:
        raise ValueError("minimum_chord_distance_m must be finite and positive")
    selected_regions = [
        np.asarray(first_selected_vertex_indices, dtype=np.int64),
        np.asarray(second_selected_vertex_indices, dtype=np.int64),
    ]
    candidate_regions = [
        np.asarray(first_candidate_patch_indices, dtype=np.int64),
        np.asarray(second_candidate_patch_indices, dtype=np.int64),
    ]
    for region_index, (selected, candidates) in enumerate(
        zip(selected_regions, candidate_regions, strict=True)
    ):
        if selected.shape != (expected,):
            raise ValueError(
                f"region {region_index} does not contain exactly {expected} selected nodes"
            )
        if candidates.ndim != 1 or candidates.size < expected:
            raise ValueError(f"region {region_index} candidate patch is too small")
        if np.unique(selected).size != selected.size:
            raise ValueError(f"region {region_index} selected nodes are not unique")
        if not np.all(np.isin(selected, candidates, assume_unique=False)):
            raise ValueError(f"region {region_index} selection leaves its candidate patch")

    patch_overlap = np.intersect1d(
        candidate_regions[0], candidate_regions[1], assume_unique=False
    )
    if patch_overlap.size:
        raise ValueError("candidate patches overlap")
    patch_cross_chord = minimum_cross_set_chord_distance(
        vertices,
        candidate_regions[0],
        candidate_regions[1],
    )
    if patch_cross_chord + 1.0e-12 < spacing:
        raise ValueError("candidate patch boundary chord gap is below spacing")

    combined = np.concatenate(selected_regions)
    if np.unique(combined).size != 2 * expected:
        raise ValueError("combined layout does not contain globally unique nodes")
    global_chord = minimum_pairwise_chord_distance(vertices, combined)
    if global_chord + 1.0e-12 < spacing:
        raise ValueError("combined layout violates global chord spacing")
    selected_cross_chord = minimum_cross_set_chord_distance(
        vertices,
        selected_regions[0],
        selected_regions[1],
    )
    return BalancedTwoRegionLayout(
        electrode_vertex_indices=combined,
        electrode_region_indices=np.repeat(
            np.arange(2, dtype=np.int8), expected
        ),
        minimum_global_chord_distance_m=global_chord,
        minimum_cross_region_chord_distance_m=selected_cross_chord,
        minimum_candidate_patch_cross_chord_distance_m=patch_cross_chord,
    )


__all__ = [
    "BalancedTwoRegionLayout",
    "CoordinateClippedPatch",
    "assemble_balanced_two_region_layout",
    "build_coordinate_clipped_patch",
    "center_connected_component_indices",
    "coordinate_roi_mask",
    "minimum_cross_set_chord_distance",
]
