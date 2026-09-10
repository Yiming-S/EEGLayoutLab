"""Deterministic exploratory point packing on a triangular scalp surface.

This module is deliberately limited to surface geometry.  It computes no EEG
forward model, performance metric, acceptance rate, or packing-capacity
certificate.  Mesh-edge Dijkstra distance is used as an ordering surrogate
and to define conservative vertex disks.  Euclidean chord distance is the
independent, conservative acceptance check for minimum electrode spacing.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from compact_eeg.surface import edge_incidence_counts, triangle_areas, vertex_area_weights


@dataclass(frozen=True)
class SurfaceEdgeGraph:
    """Undirected mesh-edge graph with Euclidean chord edge weights."""

    adjacency: csr_matrix
    unique_edges: np.ndarray
    edge_lengths_m: np.ndarray


@dataclass(frozen=True)
class GraphDiskAreaSummary:
    """Discrete graph-radius disk and three boundary-area approximations."""

    candidate_vertex_indices: np.ndarray
    maximum_graph_path_distance_m: float
    fully_contained_triangle_area_m2: float
    barycentric_vertex_area_m2: float
    touched_triangle_area_m2: float
    boundary_triangle_count: int


@dataclass(frozen=True)
class GreedyPackingResult:
    """One deterministic greedy farthest-point prefix, capped by request."""

    selected_vertex_indices: np.ndarray
    insertion_graph_scores_m: np.ndarray
    stop_reason: str
    requested_cap: int
    minimum_pairwise_chord_distance_m: float
    minimum_pairwise_graph_path_distance_m: float


def _validated_vertices(vertices_m: np.ndarray) -> np.ndarray:
    vertices = np.asarray(vertices_m, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("vertices_m must have shape (n_vertices, 3)")
    if vertices.shape[0] < 1 or not np.all(np.isfinite(vertices)):
        raise ValueError("vertices_m must be non-empty and finite")
    return vertices


def _validated_faces(triangles: np.ndarray, vertex_count: int) -> np.ndarray:
    raw = np.asarray(triangles)
    if raw.ndim != 2 or raw.shape[1] != 3:
        raise ValueError("triangles must have shape (n_triangles, 3)")
    if not np.issubdtype(raw.dtype, np.integer) or np.issubdtype(raw.dtype, np.bool_):
        raise ValueError("triangles must contain integer vertex indices")
    faces = raw.astype(np.int64, copy=False)
    if faces.shape[0] < 1:
        raise ValueError("triangles must be non-empty")
    if int(faces.min()) < 0 or int(faces.max()) >= int(vertex_count):
        raise ValueError("triangles contain an out-of-range vertex index")
    return faces


def build_surface_edge_graph(
    vertices_m: np.ndarray,
    triangles: np.ndarray,
) -> SurfaceEdgeGraph:
    """Build a sorted, symmetric sparse graph from unique triangle edges."""

    vertices = _validated_vertices(vertices_m)
    faces = _validated_faces(triangles, len(vertices))
    edges, _ = edge_incidence_counts(faces, vertex_count=len(vertices))
    lengths = np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1)
    if not np.all(np.isfinite(lengths)) or np.any(lengths <= 0.0):
        raise ValueError("surface edges must have finite positive length")
    rows = np.concatenate((edges[:, 0], edges[:, 1]))
    columns = np.concatenate((edges[:, 1], edges[:, 0]))
    weights = np.concatenate((lengths, lengths))
    adjacency = csr_matrix(
        (weights, (rows, columns)),
        shape=(len(vertices), len(vertices)),
        dtype=np.float64,
    )
    adjacency.sort_indices()
    return SurfaceEdgeGraph(
        adjacency=adjacency,
        unique_edges=edges,
        edge_lengths_m=lengths,
    )


def resolve_nearest_surface_vertex(
    vertices_m: np.ndarray,
    target_xyz_m: np.ndarray,
) -> tuple[int, float]:
    """Resolve an approximate coordinate anchor with a lowest-index tie break."""

    vertices = _validated_vertices(vertices_m)
    target = np.asarray(target_xyz_m, dtype=np.float64)
    if target.shape != (3,) or not np.all(np.isfinite(target)):
        raise ValueError("target_xyz_m must be a finite length-three vector")
    distances = np.linalg.norm(vertices - target, axis=1)
    index = int(np.argmin(distances))
    return index, float(distances[index])


class GraphDistanceCache:
    """Memory-bounded LRU cache for deterministic single-source Dijkstra rows."""

    def __init__(self, adjacency: csr_matrix, *, max_entries: int = 128) -> None:
        graph = adjacency.tocsr(copy=False)
        if graph.shape[0] < 1 or graph.shape[0] != graph.shape[1]:
            raise ValueError("adjacency must be a non-empty square matrix")
        if not isinstance(max_entries, (int, np.integer)) or isinstance(
            max_entries, (bool, np.bool_)
        ):
            raise ValueError("max_entries must be a positive integer")
        if int(max_entries) < 1:
            raise ValueError("max_entries must be a positive integer")
        self._adjacency = graph
        self._max_entries = int(max_entries)
        self._rows: OrderedDict[int, np.ndarray] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.peak_entries = 0
        self.peak_bytes = 0

    def get(self, source_vertex_index: int) -> np.ndarray:
        """Return all graph distances for one source, reusing cached rows."""

        source = int(source_vertex_index)
        if source < 0 or source >= self._adjacency.shape[0]:
            raise ValueError("source_vertex_index is out of range")
        cached = self._rows.pop(source, None)
        if cached is not None:
            self.hits += 1
            self._rows[source] = cached
            return cached

        self.misses += 1
        distances = np.asarray(
            dijkstra(
                self._adjacency,
                directed=False,
                indices=source,
                return_predecessors=False,
            ),
            dtype=np.float64,
        )
        distances.setflags(write=False)
        self._rows[source] = distances
        if len(self._rows) > self._max_entries:
            self._rows.popitem(last=False)
            self.evictions += 1
        self.peak_entries = max(self.peak_entries, len(self._rows))
        resident_bytes = sum(row.nbytes for row in self._rows.values())
        self.peak_bytes = max(self.peak_bytes, resident_bytes)
        return distances

    def report(self) -> dict[str, int]:
        """Return cache counters without exposing mutable cached arrays."""

        return {
            "max_entries": self._max_entries,
            "resident_entries": len(self._rows),
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "peak_entries": self.peak_entries,
            "peak_bytes": self.peak_bytes,
        }


def graph_radius_disk_area_summary(
    vertices_m: np.ndarray,
    triangles: np.ndarray,
    center_graph_distances_m: np.ndarray,
    radius_m: float,
) -> GraphDiskAreaSummary:
    """Summarize a conservative vertex disk and boundary-area approximations.

    The disk contains vertices whose shortest mesh-edge path from the resolved
    center is at most ``radius_m``.  Mesh-edge paths upper-bound continuous
    surface geodesics, so this is a conservative subset of the corresponding
    continuous geodesic disk.  The three areas are alternative boundary
    treatments of the discrete vertex mask; none is an exact continuous
    geodesic-disk area or a certified lower/upper bound for that area.
    """

    vertices = _validated_vertices(vertices_m)
    faces = _validated_faces(triangles, len(vertices))
    distances = np.asarray(center_graph_distances_m, dtype=np.float64)
    radius = float(radius_m)
    if distances.shape != (len(vertices),) or np.any(np.isnan(distances)):
        raise ValueError("center_graph_distances_m has an invalid shape or NaN")
    if not np.isfinite(radius) or radius <= 0.0:
        raise ValueError("radius_m must be finite and positive")

    mask = np.isfinite(distances) & (distances <= radius)
    candidates = np.flatnonzero(mask).astype(np.int64, copy=False)
    if candidates.size == 0:
        raise RuntimeError("graph-radius disk unexpectedly contains no vertices")
    face_membership = np.count_nonzero(mask[faces], axis=1)
    areas = triangle_areas(vertices, faces)
    area_weights = vertex_area_weights(vertices, faces)
    return GraphDiskAreaSummary(
        candidate_vertex_indices=candidates,
        maximum_graph_path_distance_m=float(distances[candidates].max()),
        fully_contained_triangle_area_m2=float(areas[face_membership == 3].sum()),
        barycentric_vertex_area_m2=float(area_weights[candidates].sum()),
        touched_triangle_area_m2=float(areas[face_membership > 0].sum()),
        boundary_triangle_count=int(np.count_nonzero((face_membership > 0) & (face_membership < 3))),
    )


def minimum_pairwise_chord_distance(
    vertices_m: np.ndarray,
    selected_vertex_indices: np.ndarray,
) -> float:
    """Return the minimum Euclidean 3-D chord distance for selected vertices."""

    vertices = _validated_vertices(vertices_m)
    selected = np.asarray(selected_vertex_indices, dtype=np.int64)
    if selected.ndim != 1 or selected.size < 1:
        raise ValueError("selected_vertex_indices must be a non-empty vector")
    if int(selected.min()) < 0 or int(selected.max()) >= len(vertices):
        raise ValueError("selected_vertex_indices contains an out-of-range index")
    if np.unique(selected).size != selected.size:
        raise ValueError("selected_vertex_indices must be unique")
    if selected.size == 1:
        return float("inf")
    points = vertices[selected]
    minimum = float("inf")
    for index in range(1, len(points)):
        distances = np.linalg.norm(points[index] - points[:index], axis=1)
        minimum = min(minimum, float(distances.min()))
    return minimum


def deterministic_greedy_farthest_packing(
    vertices_m: np.ndarray,
    candidate_vertex_indices: np.ndarray,
    center_vertex_index: int,
    *,
    minimum_chord_distance_m: float,
    requested_cap: int,
    distance_cache: GraphDistanceCache,
) -> GreedyPackingResult:
    """Build one deterministic graph-maximin prefix under a chord constraint.

    Graph distance determines the farthest-point ordering.  A point enters the
    prefix only when its Euclidean chord distance to every previously selected
    point is at least the requested spacing.  Failure to extend this greedy
    prefix is not a proof that no alternative packing exists.
    """

    vertices = _validated_vertices(vertices_m)
    candidates = np.asarray(candidate_vertex_indices, dtype=np.int64)
    center = int(center_vertex_index)
    spacing = float(minimum_chord_distance_m)
    if candidates.ndim != 1 or candidates.size < 1:
        raise ValueError("candidate_vertex_indices must be a non-empty vector")
    if int(candidates.min()) < 0 or int(candidates.max()) >= len(vertices):
        raise ValueError("candidate_vertex_indices contains an out-of-range index")
    candidates = np.unique(candidates)
    if center not in candidates:
        raise ValueError("center_vertex_index must be present among candidates")
    if not np.isfinite(spacing) or spacing <= 0.0:
        raise ValueError("minimum_chord_distance_m must be finite and positive")
    if not isinstance(requested_cap, (int, np.integer)) or isinstance(
        requested_cap, (bool, np.bool_)
    ):
        raise ValueError("requested_cap must be a positive integer")
    cap = int(requested_cap)
    if cap < 1:
        raise ValueError("requested_cap must be a positive integer")

    center_local = int(np.searchsorted(candidates, center))
    selected_global: list[int] = [center]
    selected_local = np.zeros(len(candidates), dtype=bool)
    selected_local[center_local] = True
    insertion_scores = [0.0]

    center_distances = distance_cache.get(center)[candidates]
    if not np.all(np.isfinite(center_distances)):
        raise RuntimeError("candidate disk spans disconnected graph components")
    minimum_graph_distance = center_distances.copy()
    delta = vertices[candidates] - vertices[center]
    minimum_chord_squared = np.einsum("ij,ij->i", delta, delta)
    threshold_squared = spacing * spacing

    while len(selected_global) < cap:
        eligible = (
            (~selected_local)
            & (minimum_chord_squared >= threshold_squared)
            & np.isfinite(minimum_graph_distance)
        )
        if not np.any(eligible):
            break
        scores = np.where(eligible, minimum_graph_distance, -np.inf)
        next_local = int(np.argmax(scores))
        next_global = int(candidates[next_local])
        selected_global.append(next_global)
        insertion_scores.append(float(minimum_graph_distance[next_local]))
        selected_local[next_local] = True

        next_graph_distances = distance_cache.get(next_global)[candidates]
        minimum_graph_distance = np.minimum(
            minimum_graph_distance, next_graph_distances
        )
        chord_delta = vertices[candidates] - vertices[next_global]
        chord_squared = np.einsum("ij,ij->i", chord_delta, chord_delta)
        minimum_chord_squared = np.minimum(minimum_chord_squared, chord_squared)

    selected = np.asarray(selected_global, dtype=np.int64)
    minimum_chord = minimum_pairwise_chord_distance(vertices, selected)
    if selected.size > 1 and minimum_chord + 1.0e-12 < spacing:
        raise RuntimeError("internal error: selected prefix violates chord spacing")
    score_array = np.asarray(insertion_scores, dtype=np.float64)
    minimum_graph = (
        float(score_array[1:].min()) if score_array.size > 1 else float("inf")
    )
    stop_reason = (
        "requested_cap_reached"
        if selected.size == cap
        else "greedy_prefix_exhausted_under_euclidean_chord_filter"
    )
    return GreedyPackingResult(
        selected_vertex_indices=selected,
        insertion_graph_scores_m=score_array,
        stop_reason=stop_reason,
        requested_cap=cap,
        minimum_pairwise_chord_distance_m=minimum_chord,
        minimum_pairwise_graph_path_distance_m=minimum_graph,
    )


def packing_result_record(result: GreedyPackingResult) -> dict[str, Any]:
    """Return a finite JSON-friendly summary of a greedy packing result."""

    return {
        "selected_count": int(result.selected_vertex_indices.size),
        "requested_cap": int(result.requested_cap),
        "stop_reason": result.stop_reason,
        "minimum_pairwise_chord_distance_m": (
            None
            if not np.isfinite(result.minimum_pairwise_chord_distance_m)
            else float(result.minimum_pairwise_chord_distance_m)
        ),
        "minimum_pairwise_graph_path_distance_m": (
            None
            if not np.isfinite(result.minimum_pairwise_graph_path_distance_m)
            else float(result.minimum_pairwise_graph_path_distance_m)
        ),
    }


__all__ = [
    "GraphDiskAreaSummary",
    "GraphDistanceCache",
    "GreedyPackingResult",
    "SurfaceEdgeGraph",
    "build_surface_edge_graph",
    "deterministic_greedy_farthest_packing",
    "graph_radius_disk_area_summary",
    "minimum_pairwise_chord_distance",
    "packing_result_record",
    "resolve_nearest_surface_vertex",
]
