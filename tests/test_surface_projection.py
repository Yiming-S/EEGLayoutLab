"""Own surface projection against cortech 0.1's ``Surface.project_points`` (design 0001, decision 10).

The own implementation (``eeglayoutlab.forward.projection``) is accepted only if it
reproduces the current projections; docs/design/0001-own-projection.md records the
result. Synthetic cases run everywhere. Comparisons with cortech skip without cortech;
the Ernie cases skip without the restored data bundle, and those that call cortech also
skip without cortech.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from eeglayoutlab.forward.projection import candidate_triangles, project_points

ROOT = Path(__file__).resolve().parents[1]
BANK_POINTER = ROOT / "results/v2/current_multiregion_bank.json"

# Phase 0 point set (docs/design/0001-local-first-architecture.md, phase 0 results): the 64
# standard positions, the 5,387 bank candidates, every 5th candidate moved 0-3 mm and every
# 25th moved 5-15 mm in seeded random directions. The hash is of the float64 (6745, 3) array.
PHASE0_SEED = 20261122
POINTS_SHA256 = {"phase 0": "9b7c8d1226deaa2b5b93fbd84ba84347dc3c865d1ad156ee067ad9de87308878",
                 "mask boundary": "95e4cefc04518db31cd7cb4000e96904cc86b742557766bce4c4a1becb5311c1"}
# cortech 0.1 with numpy 2.3.0 and scipy 1.17.1: SHA-256 of the triangles (as int64), weights,
# projected points and distances, in that order. The phase 0 value is also that of the outputs
# phase 0 saved from the macOS arm64 and Linux x86_64 release wheels. These keep the projections
# checkable after cortech is removed, for example on a numpy or scipy upgrade.
CORTECH_SHA256 = {"phase 0": "227754a6b36879e281d68c0143764294ef6d3b9da9bc976f68cd71796adc6f98",
                  "mask boundary": "56983c1b3e9dd9dae887c6768fcf53ed7d91eb68e0252bc882ca0fe4a5ea6945"}


def grid_surface(n=5, spacing=10.0, height=None):
    """The check_environment grid: n x n vertices at z = 0 (or ``height(x, y)``), two triangles per cell."""
    axis = np.arange(n) * spacing
    vertices = np.array([[x, y, 0.0 if height is None else height(x, y)] for y in axis for x in axis])
    faces = np.array([face for j in range(n - 1) for i in range(n - 1)
                      for face in ([n * j + i, n * j + i + 1, n * j + i + n + 1], [n * j + i, n * j + i + n + 1, n * j + i + n])])
    return vertices, faces


TETRAHEDRON = (np.array([[0.0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]]),
               np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]))
OCTAHEDRON = (np.array([[10.0, 0, 0], [-10, 0, 0], [0, 10, 0], [0, -10, 0], [0, 0, 10], [0, 0, -10]]),
              np.array([[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4], [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]]))
SINGLE_TRIANGLE = (np.array([[0.0, 0, 0], [10, 0, 0], [0, 10, 0]]), np.array([[0, 1, 2]]))


def brute_force(vertices, faces, points):
    """Closest point over every triangle, by a different formula: plane projection, else the nearest edge point."""
    a, b, c = (vertices[faces[:, i]][None] for i in range(3))
    p = points[:, None]
    normal = np.cross(b - a, c - a)
    q = p - np.sum((p - a) * normal, -1, keepdims=True) / np.sum(normal * normal, -1, keepdims=True) * normal
    inside = np.ones(q.shape[:2], bool)
    for u, w in ((a, b), (b, c), (c, a)):
        inside &= np.sum(np.cross(w - u, q - u) * normal, -1) >= 0
    best = np.where(inside[..., None], q, np.inf)
    for u, w in ((a, b), (b, c), (c, a)):
        t = np.clip(np.sum((p - u) * (w - u), -1) / np.sum((w - u) ** 2, -1), 0, 1)[..., None]
        edge = u + t * (w - u)
        closer = np.linalg.norm(edge - p, axis=-1) < np.linalg.norm(best - p, axis=-1)
        best = np.where(closer[..., None], edge, best)
    distance = np.linalg.norm(best - p, axis=-1)
    nearest = distance.argmin(axis=1)
    rows = np.arange(len(points))
    return best[rows, nearest], distance[rows, nearest]


def assert_same_bits(reference, own):
    """Triangles equal as integers; floats equal to the last bit, including the sign of zero."""
    np.testing.assert_array_equal(np.asarray(reference[0], dtype=np.int64), own[0])
    for ref, mine in zip(reference[1:], own[1:]):
        assert ref.dtype == mine.dtype == np.float64 and ref.shape == mine.shape
        np.testing.assert_array_equal(ref.view(np.uint64), mine.view(np.uint64))


def assert_existing_checks(vertices, faces, points, result):
    """The checks scalp_node_table.project and the table evaluation apply to every projection."""
    triangles, weights, projected, distances = result
    assert triangles.dtype == np.int64 and triangles.shape == (len(points),) and weights.shape == (len(points), 3)
    assert np.all(weights >= -1e-10) and np.all(weights <= 1 + 1e-10)
    np.testing.assert_allclose(weights.sum(axis=1), 1, rtol=0, atol=1e-10)
    np.testing.assert_allclose(np.einsum("kj,kjc->kc", weights, vertices[faces[triangles]]), projected, rtol=0, atol=1e-7)
    np.testing.assert_allclose(np.linalg.norm(points - projected, axis=1), distances, rtol=0, atol=1e-12)


# --- Synthetic surfaces (no cortech) ---------------------------------------------------

def test_planar_grid_drops_z_and_clamps_to_border_edges_and_corners():
    vertices, faces = grid_surface()
    points = np.array([[12.0, 17.0, -3.0], [31.0, 8.0, 2.0]])
    for k in (1, 5, 20):
        triangles, weights, projected, distances = project_points(vertices, faces, points, k)
        np.testing.assert_allclose(projected, points * [1, 1, 0], rtol=0, atol=1e-12)
        np.testing.assert_allclose(distances, [3.0, 2.0], rtol=0, atol=1e-12)
        assert_existing_checks(vertices, faces, points, (triangles, weights, projected, distances))
    outside = {(-5.0, -5.0, 1.0): (0.0, 0.0, 0.0), (45.0, 20.0, -1.0): (40.0, 20.0, 0.0),
               (20.0, -7.0, 3.0): (20.0, 0.0, 0.0), (50.0, 50.0, 0.0): (40.0, 40.0, 0.0),
               (-3.0, 33.0, 0.0): (0.0, 33.0, 0.0)}
    _, _, projected, _ = project_points(vertices, faces, np.array(list(outside)), 5)
    np.testing.assert_allclose(projected, np.array(list(outside.values())), rtol=0, atol=1e-12)


def test_curved_surface_matches_brute_force_closest_point():
    rng = np.random.default_rng(5)
    vertices, faces = grid_surface(9, 5.0, lambda x, y: 6 * np.sin(x / 9) * np.cos(y / 7))
    points = rng.uniform([-5, -5, -15], [45, 45, 15], size=(400, 3))
    triangles, weights, projected, distances = project_points(vertices, faces, points, len(vertices))
    expected_points, expected_distances = brute_force(vertices, faces, points)
    np.testing.assert_allclose(distances, expected_distances, rtol=0, atol=1e-9)
    np.testing.assert_allclose(projected, expected_points, rtol=0, atol=1e-6)
    assert_existing_checks(vertices, faces, points, (triangles, weights, projected, distances))


@pytest.mark.parametrize("mesh", [SINGLE_TRIANGLE, TETRAHEDRON, OCTAHEDRON], ids=["triangle", "tetrahedron", "octahedron"])
def test_meshes_with_equal_triangles_per_vertex(mesh):
    """cortech 0.1 raises IndexError on these (get_triangle_neighbors builds a 2-D object array)."""
    vertices, faces = mesh
    assert len(set(np.bincount(faces.ravel()))) == 1
    points = np.random.default_rng(11).uniform(-15, 15, size=(300, 3))
    for k in (1, len(vertices)):
        result = project_points(vertices, faces, points, k)
        assert_existing_checks(vertices, faces, points, result)
    expected_points, expected_distances = brute_force(vertices, faces, points)
    np.testing.assert_allclose(result[3], expected_distances, rtol=0, atol=1e-9)
    np.testing.assert_allclose(result[2], expected_points, rtol=0, atol=1e-6)


def test_candidates_are_sorted_unique_incident_triangles():
    vertices, faces = grid_surface()
    points = np.array([[0.0, 0.0, 1.0], [20.0, 20.0, 0.0]])
    owner, triangle = candidate_triangles(vertices, faces, points, 1)
    corner, centre = np.flatnonzero((faces == 0).any(axis=1)), np.flatnonzero((faces == 12).any(axis=1))
    assert (len(corner), len(centre)) == (2, 6)
    np.testing.assert_array_equal(owner, [0] * 2 + [1] * 6)
    np.testing.assert_array_equal(triangle, np.r_[corner, centre])
    # A triangle that names a vertex twice is listed once.
    owner, triangle = candidate_triangles(vertices, np.vstack([faces, [[12, 12, 13]]]), points[1:], 2)
    assert len(triangle) == len(np.unique(triangle)) and len(faces) in triangle


def test_rejects_invalid_input():
    vertices, faces = grid_surface()
    with pytest.raises(ValueError, match="finite"):
        project_points(vertices, faces, [[0.0, np.nan, 0.0]])
    with pytest.raises(ValueError, match="outside"):
        project_points(vertices, faces + 1, [[0.0, 0.0, 0.0]])
    with pytest.raises(ValueError, match="positive"):
        project_points(vertices, faces, [[0.0, 0.0, 0.0]], 0)
    isolated = np.vstack([vertices, [[500.0, 500.0, 500.0]]])
    with pytest.raises(ValueError, match="no candidate"):
        project_points(isolated, faces, [[501.0, 500.0, 500.0]], 1)
    empty = project_points(vertices, faces, np.empty((0, 3)))
    assert [len(a) for a in empty] == [0, 0, 0, 0]


# --- Against cortech on synthetic surfaces ---------------------------------------------

@pytest.mark.native_runtime
def test_bit_identical_to_cortech_on_synthetic_surfaces():
    cortech = pytest.importorskip("cortech")
    rng = np.random.default_rng(3)
    surfaces = [grid_surface(), grid_surface(9, 5.0, lambda x, y: 6 * np.sin(x / 9) * np.cos(y / 7))]
    for vertices, faces in surfaces:
        points = rng.uniform([-5, -5, -15], [45, 45, 15], size=(500, 3))
        points[:len(vertices)] = vertices + [0, 0, 1]  # above every vertex: exact ties between its triangles
        for k in (1, 5, 20):
            assert_same_bits(cortech.Surface(vertices, faces).project_points(points, pttris=k),
                             project_points(vertices, faces, points, k))


@pytest.mark.native_runtime
@pytest.mark.parametrize("mesh", [SINGLE_TRIANGLE, TETRAHEDRON, OCTAHEDRON], ids=["triangle", "tetrahedron", "octahedron"])
def test_cortech_index_error_case(mesh):
    """cortech fails here; with one far isolated vertex added it runs and agrees to the last bit."""
    cortech = pytest.importorskip("cortech")
    vertices, faces = mesh
    points = np.random.default_rng(13).uniform(-15, 15, size=(300, 3))
    with pytest.raises(IndexError):
        cortech.Surface(vertices, faces).project_points(points, pttris=len(vertices))
    padded = np.vstack([vertices, [[1e6, 1e6, 1e6]]])
    for k in (1, len(vertices)):
        assert_same_bits(cortech.Surface(padded, faces).project_points(points, pttris=k),
                         project_points(vertices, faces, points, k))


# --- The Ernie scalp ------------------------------------------------------------------

@pytest.fixture(scope="module")
def ernie():
    """The bank's scalp geometry and admissibility mask, and both point sets checked by hash."""
    if not BANK_POINTER.is_file():
        pytest.skip("Ernie data bundle not restored")
    from compact_eeg.artifacts import sha256_file
    from compact_eeg.surface_admissibility import load_admissibility
    pointer = json.loads(BANK_POINTER.read_text())
    report = json.loads((ROOT / pointer["report"]).read_text())
    if sha256_file(ROOT / pointer["candidates"]) != report["candidate_sha256"]:
        raise ValueError("candidate geometry does not match the bank report")
    with np.load(ROOT / pointer["candidates"], allow_pickle=False) as geometry:
        vertices = geometry["surface_vertices_m"] * 1000  # exactly design_evaluation.load_bank
        faces = geometry["surface_triangles"]
    with np.load(ROOT / pointer["path"], allow_pickle=False) as bank:
        candidates, standard64 = bank["candidate_xyz_mm"], bank["reference_xyz_mm"]
    eligible, _ = load_admissibility(ROOT, report["candidate_sha256"])
    points = {"phase 0": phase0_points(candidates, standard64),
              "mask boundary": np.vstack(list(mask_boundary_points(vertices, faces, eligible).values()))}
    assert [len(p) for p in points.values()] == [6745, 6300]
    for name, array in points.items():
        assert hashlib.sha256(array.tobytes()).hexdigest() == POINTS_SHA256[name], f"{name} points changed"
    return {"vertices": vertices, "faces": faces, "eligible": eligible, "points": points}


def phase0_points(candidates, standard64):
    rng = np.random.default_rng(PHASE0_SEED)

    def offsets(n, low, high):
        direction = rng.normal(size=(n, 3))
        direction /= np.linalg.norm(direction, axis=1, keepdims=True)
        return direction * rng.uniform(low, high, size=(n, 1))

    near, far = candidates[::5], candidates[::25]
    return np.vstack([standard64, candidates, near + offsets(len(near), 0, 3), far + offsets(len(far), 5, 15)])


def mask_boundary_points(vertices, faces, eligible):
    """Points on and near the edge of the admissible region (triangles whose three corners pass the screen).

    Boundary vertices are the corners of triangles with both passing and screened corners;
    boundary edges separate an admissible triangle from a screened one. Points on a vertex or
    an edge are at the same distance from several triangles, so the triangle, and with it
    the admission check of design evaluation, is decided by the tie rule.
    """
    admissible = eligible[faces].all(axis=1)
    face_normal = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 2]] - vertices[faces[:, 0]])
    vertex_normal = np.zeros_like(vertices)
    for corner in range(3):
        np.add.at(vertex_normal, faces[:, corner], face_normal)
    vertex_normal /= np.linalg.norm(vertex_normal, axis=1, keepdims=True)
    face_normal /= np.linalg.norm(face_normal, axis=1, keepdims=True)
    corner_index = np.unique(faces[eligible[faces].any(axis=1) & ~admissible])
    corners, corner_normal = vertices[corner_index], vertex_normal[corner_index]

    edges = np.sort(faces[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2), axis=1)
    order = np.argsort(edges[:, 0] * len(vertices) + edges[:, 1], kind="stable")
    key = (edges[:, 0] * len(vertices) + edges[:, 1])[order]
    first = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    shared = first[np.diff(np.r_[first, len(key)]) == 2]
    left, right = order[shared] // 3, order[shared + 1] // 3
    split = admissible[left] != admissible[right]
    left, right, edge = left[split], right[split], edges[order[shared][split]]
    start, end = vertices[edge[:, 0]], vertices[edge[:, 1]]
    middle = (start + end) / 2
    normal = face_normal[left] + face_normal[right]
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)
    along = (end - start) / np.linalg.norm(end - start, axis=1, keepdims=True)
    across = vertices[faces[left].sum(axis=1) - edge.sum(axis=1)] - middle
    across -= np.sum(across * along, axis=1, keepdims=True) * along
    across /= np.linalg.norm(across, axis=1, keepdims=True)
    return {
        "vertices": corners,
        "vertices +-1 mm along the normal": np.vstack([corners + corner_normal, corners - corner_normal]),
        "vertices 2 mm -+1e-9 mm along the normal": np.vstack([corners + (2 - 1e-9) * corner_normal,
                                                                corners + (2 + 1e-9) * corner_normal]),
        "edge midpoints": middle,
        "edge midpoints +-1 mm along the normal": np.vstack([middle + normal, middle - normal]),
        "edge midpoints +-1e-12 mm across the edge": np.vstack([middle + 1e-12 * across, middle - 1e-12 * across]),
        "edge midpoints +-1e-6 mm across the edge": np.vstack([middle + 1e-6 * across, middle - 1e-6 * across]),
        "edge thirds": (2 * start + end) / 3,
    }


def compare_on_ernie(ernie, name):
    cortech = pytest.importorskip("cortech")
    vertices, faces, points = ernie["vertices"], ernie["faces"], ernie["points"][name]
    surface = cortech.Surface(vertices, faces)
    own = project_points(vertices, faces, points, 20)
    assert_same_bits(surface.project_points(points, pttris=20), own)
    assert_existing_checks(vertices, faces, points, own)
    # The candidate lists are the same too, not only the chosen triangles.
    owner, triangle = candidate_triangles(vertices, faces, points, 20)
    every = surface.project_points(points, pttris=20, return_all_projections=True)
    np.testing.assert_array_equal(np.asarray(every[0], dtype=np.int64), triangle)
    return own, owner, triangle, every[3]


@pytest.mark.data_bundle
@pytest.mark.native_runtime
def test_phase0_points_bit_identical_to_cortech(ernie):
    compare_on_ernie(ernie, "phase 0")


@pytest.mark.data_bundle
@pytest.mark.native_runtime
def test_mask_boundary_bit_identical_to_cortech(ernie):
    own, owner, triangle, distances = compare_on_ernie(ernie, "mask boundary")
    admissible = ernie["eligible"][ernie["faces"]].all(axis=1)
    # The set must exercise the tie rule where it decides admission: points whose nearest
    # candidates include an admissible and a screened triangle at exactly the same distance.
    per_point = np.bincount(owner, minlength=len(own[0]))
    smallest = np.minimum.reduceat(distances, np.cumsum(per_point) - per_point)[owner]
    tied = distances == smallest
    tied_admissible, tied_screened = np.zeros((2, len(own[0])), bool)
    tied_admissible[owner[tied & admissible[triangle]]] = True
    tied_screened[owner[tied & ~admissible[triangle]]] = True
    assert np.sum(tied_admissible & tied_screened) > 1000
    assert 0 < admissible[own[0]].sum() < len(own[0])


@pytest.mark.data_bundle
@pytest.mark.parametrize("name", list(CORTECH_SHA256))
def test_projections_equal_frozen_cortech_outputs(ernie, name):
    """Runs without cortech: the reference for numpy and scipy changes once cortech is gone."""
    result = project_points(ernie["vertices"], ernie["faces"], ernie["points"][name], 20)
    digest = hashlib.sha256()
    for array in result:
        digest.update(np.ascontiguousarray(array).tobytes())
    assert digest.hexdigest() == CORTECH_SHA256[name], (
        f"{name} projections differ from cortech 0.1 with numpy 2.3.0 and scipy 1.17.1")
