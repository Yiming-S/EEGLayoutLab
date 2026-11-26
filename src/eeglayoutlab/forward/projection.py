"""Closest-point projection of points onto a triangulated surface, in numpy and scipy.

Evaluated as a replacement for ``cortech.Surface(vertices, faces).project_points(points,
pttris=k)`` from cortech 0.1 (design 0001, decision 10; results in
docs/design/0001-own-projection.md). Nothing calls it yet. The science code keeps calling
cortech, because adopting this module changes scientific identities (design 0001,
decision 8) and is reserved for 1.0.

Method. The candidate triangles of a point are those incident to its ``k`` nearest
vertices (``scipy.spatial.cKDTree``). On each candidate, the closest point is found with
Eberly's region method [1]: the unconstrained minimiser of the squared distance in the
triangle's (s, t) parameters, or the closest point on the edge of the region it falls in.
The candidate at the smallest distance wins; ties go to the lowest triangle index.

Reproduction. The floating-point operations and their order follow cortech 0.1, so with
the same numpy and scipy the triangles, weights, projected points and distances are equal
to cortech's to the last bit. Each array is reduced in the same shape and memory layout,
because the order in which numpy sums a row can depend on them. Because it follows
cortech's arithmetic step by step, this module is treated as derived from cortech 0.1
(GPL-3.0, copyright the cortech authors, https://github.com/simnibs/cortech).

Differences from cortech 0.1:

- A mesh in which every vertex has the same number of triangles (a single triangle, a
  tetrahedron, an octahedron) works. cortech 0.1 raises ``IndexError`` there, because its
  vertex-to-triangle table becomes a 2-D object array.
- ``k`` larger than the number of vertices uses every vertex; cortech raises ``IndexError``.
- Triangle indices are int64; cortech returns the index type of scipy's CSR matrix (int32).
- Points must be finite, the faces must index the vertices, and every point must have at
  least one candidate triangle; otherwise ``ValueError`` is raised.

[1] D. Eberly, "Distance Between Point and Triangle in 3D", Geometric Tools, 1999,
    https://www.geometrictools.com/Documentation/DistancePoint3Triangle3.pdf
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

NEAREST_VERTEX_COUNT = 20
"""The ``pttris`` every project call site passes to cortech."""


def _as_mesh(vertices, faces):
    vertices = np.asarray(vertices, dtype=np.float64)
    faces = np.asarray(faces)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices):
        raise ValueError("vertices must have nonempty shape (V, 3)")
    if faces.ndim != 2 or faces.shape[1] != 3 or not len(faces) or not np.issubdtype(faces.dtype, np.integer):
        raise ValueError("faces must be integers with nonempty shape (F, 3)")
    faces = faces.astype(np.int64, copy=False)
    if faces.min() < 0 or faces.max() >= len(vertices):
        raise ValueError("faces index outside the vertices")
    return vertices, faces


def triangles_by_vertex(faces, vertex_count):
    """Incident triangles of every vertex: ``triangles[start[v]:start[v] + count[v]]``.

    Each vertex's triangles are in ascending index order. A triangle that names a vertex
    twice is listed twice; :func:`candidate_triangles` removes repeats.
    """
    corners = np.asarray(faces, dtype=np.int64).ravel()
    triangles = np.argsort(corners, kind="stable") // 3
    count = np.bincount(corners, minlength=vertex_count)
    start = np.cumsum(count) - count
    return triangles, start, count


def candidate_triangles(vertices, faces, points, nearest_vertex_count=NEAREST_VERTEX_COUNT):
    """Sorted, unique triangles incident to each point's nearest vertices.

    Returns ``(point_index, triangle_index)``: one row per candidate, grouped by point in
    ascending order and by triangle in ascending order within a point. cortech 0.1 builds
    the same lists with ``np.unique`` per point.
    """
    if isinstance(nearest_vertex_count, bool) or not isinstance(nearest_vertex_count, (int, np.integer)) \
            or nearest_vertex_count < 1:
        raise ValueError("nearest_vertex_count must be a positive integer")
    k = int(min(nearest_vertex_count, len(vertices)))
    _, nearest = cKDTree(vertices).query(points, k)
    nearest = np.asarray(nearest, dtype=np.int64).reshape(len(points), k)

    triangles, start, count = triangles_by_vertex(faces, len(vertices))
    lengths = count[nearest].ravel()
    first = np.repeat(start[nearest].ravel(), lengths)
    within = np.arange(lengths.sum()) - np.repeat(np.cumsum(lengths) - lengths, lengths)
    owner = np.repeat(np.repeat(np.arange(len(points), dtype=np.int64), k), lengths)
    key = np.unique(owner * len(faces) + triangles[first + within])
    return key // len(faces), key % len(faces)


def _closest_on_triangles(a, b, c, d, e):
    """Eberly's (s, t) of the closest point, for the quadratic form of each point-triangle pair.

    ``a = e0.e0, b = e0.e1, c = e1.e1, d = e0.w, e = e1.w`` with ``w = v0 - point``. The
    regions are numbered as in [1]; they are assigned in the order 0, 1, 2, 3, 4, 5, 6, so a
    pair that falls in both 2 and 6 (possible only when rounding makes ``det`` negative)
    takes region 6, as in cortech.
    """
    s = b * e - c * d  # unnormalised: divided by det only inside the triangle
    t = b * d - a * e
    det = a * c - b**2
    below = s + t <= det  # on the vertex-0 side of the edge s + t = 1
    s_neg = s < 0
    t_neg = t < 0
    sp, tp = np.zeros_like(s), np.zeros_like(t)

    def on_far_edge_by_s(i):  # minimise along s + t = 1, parametrised by s
        sp[i] = np.clip((c[i] + e[i] - (b[i] + d[i])) / (a[i] - 2 * b[i] + c[i]), 0, 1)
        tp[i] = 1 - sp[i]

    def on_far_edge_by_t(i):  # minimise along s + t = 1, parametrised by t
        tp[i] = np.clip((a[i] + d[i] - (b[i] + e[i])) / (a[i] - 2 * b[i] + c[i]), 0, 1)
        sp[i] = 1 - tp[i]

    def on_t_axis(i):  # minimise along s = 0
        sp[i] = 0
        tp[i] = np.clip(-e[i] / c[i], 0, 1)

    def on_s_axis(i):  # minimise along t = 0
        tp[i] = 0
        sp[i] = np.clip(-d[i] / a[i], 0, 1)

    i = np.flatnonzero(below & ~s_neg & ~t_neg)  # region 0: inside
    sp[i] = s[i] / det[i]
    tp[i] = t[i] / det[i]
    on_far_edge_by_s(np.flatnonzero(~below & ~s_neg & ~t_neg))  # region 1
    i = np.flatnonzero(~below & s_neg)  # region 2: towards vertex 2 (s = 0, t = 1)
    toward_far_edge = c[i] + e[i] > b[i] + d[i]
    on_far_edge_by_s(i[toward_far_edge])
    on_t_axis(i[~toward_far_edge])
    on_t_axis(np.flatnonzero(below & s_neg & ~t_neg))  # region 3
    i = np.flatnonzero(below & s_neg & t_neg)  # region 4: towards vertex 0
    toward_s_axis = d[i] < 0
    on_s_axis(i[toward_s_axis])
    on_t_axis(i[~toward_s_axis])
    on_s_axis(np.flatnonzero(below & ~s_neg & t_neg))  # region 5
    i = np.flatnonzero(~below & t_neg)  # region 6: towards vertex 1 (s = 1, t = 0)
    toward_far_edge = a[i] + d[i] > b[i] + e[i]
    on_far_edge_by_t(i[toward_far_edge])
    on_s_axis(i[~toward_far_edge])
    return sp, tp


def project_points(vertices, faces, points, nearest_vertex_count=NEAREST_VERTEX_COUNT):
    """Project each point to the closest point on the candidate triangles near it.

    Returns ``(triangles, weights, projected, distances)`` as
    ``cortech.Surface(vertices, faces).project_points(points, pttris=nearest_vertex_count)``
    does: the triangle index (int64), the barycentric weights of its three corners in face
    order, the projected point and its distance from the input point.
    """
    vertices, faces = _as_mesh(vertices, faces)
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points must have shape (N, 3)")
    if not np.all(np.isfinite(points)):
        raise ValueError("points must be finite")
    if not len(points):
        return np.empty(0, np.int64), np.empty((0, 3)), np.empty((0, 3)), np.empty(0)

    owner, triangle = candidate_triangles(vertices, faces, points, nearest_vertex_count)
    per_point = np.bincount(owner, minlength=len(points))
    if not per_point.all():
        raise ValueError("a point has no candidate triangle: its nearest vertices belong to no face")

    # Per-face edge vectors, reduced over the full (F, 3) arrays as cortech does.
    corners = vertices[faces]
    v0 = corners[:, 0]
    e0 = corners[:, 1] - v0
    e1 = corners[:, 2] - v0
    repeated = np.repeat(points, per_point, axis=0)
    w = v0[triangle] - repeated
    a = np.sum(e0**2, 1)[triangle]
    b = np.sum(e0 * e1, 1)[triangle]
    c = np.sum(e1**2, 1)[triangle]
    d = np.sum(e0[triangle] * w, 1)
    e = np.sum(e1[triangle] * w, 1)
    sp, tp = _closest_on_triangles(a, b, c, d, e)

    projected = v0[triangle] + sp[:, None] * e0[triangle] + tp[:, None] * e1[triangle]
    distances = np.linalg.norm(repeated - projected, axis=1)
    weights = np.column_stack((1 - sp - tp, sp, tp))

    # First candidate at each point's smallest distance (np.argmin per point, NaN first).
    start = np.cumsum(per_point) - per_point
    smallest = np.minimum.reduceat(distances, start)[owner]
    hit = np.flatnonzero((distances == smallest) | (np.isnan(smallest) & np.isnan(distances)))
    chosen = hit[np.unique(owner[hit], return_index=True)[1]]
    return triangle[chosen], weights[chosen], projected[chosen], distances[chosen]
