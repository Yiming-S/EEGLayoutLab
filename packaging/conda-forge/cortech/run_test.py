"""Package test: exact projections on known geometry and one call into each compiled module."""
import numpy as np

import cortech
import cortech.cgal.aabb_tree
import cortech.cgal.convex_hull_3
import cortech.cgal.polygon_mesh_processing
import cortech.cgal.surface_mesh_simplification

# Planar 5 x 5 vertex grid at z = 0: projection drops z exactly.
grid = np.arange(5) * 10.0
vertices = np.array([[x, y, 0.0] for y in grid for x in grid])
faces = np.array([face for j in range(4) for i in range(4)
                  for face in ([5 * j + i, 5 * j + i + 1, 5 * j + i + 6], [5 * j + i, 5 * j + i + 6, 5 * j + i + 5])])
points = np.array([[12.0, 17.0, -3.0], [31.0, 8.0, 2.0]])
for pttris in (5, 20):
    triangles, weights, projected, distances = cortech.Surface(vertices, faces).project_points(points, pttris=pttris)
    assert np.allclose(projected, points * [1, 1, 0], atol=1e-12, rtol=0), projected
    assert np.allclose(distances, [3.0, 2.0], atol=1e-12, rtol=0), distances
    assert np.allclose(weights.sum(axis=1), 1, atol=1e-12, rtol=0)
    assert np.allclose(np.einsum("kj,kjc->kc", weights, vertices[faces[triangles]]), projected, atol=1e-12, rtol=0)

# Points beyond the grid's border project onto a border edge or a corner vertex.
# (A surface whose vertices all touch the same number of triangles, such as a single
# triangle, fails in 0.1: get_triangle_neighbors then builds a 2-D object array.)
cases = {(-5.0, -5.0, 1.0): (0.0, 0.0, 0.0), (45.0, 20.0, -1.0): (40.0, 20.0, 0.0),
         (20.0, -7.0, 3.0): (20.0, 0.0, 0.0), (50.0, 50.0, 0.0): (40.0, 40.0, 0.0),
         (-3.0, 33.0, 0.0): (0.0, 33.0, 0.0)}
_, _, projected, _ = cortech.Surface(vertices, faces).project_points(np.array(list(cases)), pttris=5)
assert np.allclose(projected, np.array(list(cases.values())), atol=1e-12, rtol=0), projected

# Compiled modules on a closed surface (unit cube).
cube_v = np.array([[x, y, z] for x in (0.0, 1) for y in (0.0, 1) for z in (0.0, 1)])
cube_f = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
                   [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
cube = cortech.Surface(cube_v, cube_f)
assert np.allclose(cube.distance_query(np.array([[0.5, 0.5, 2.0]])), 1.0)
assert len(cube.convex_hull().vertices) == 8
labels, sizes = cube.connected_components()
assert len(sizes) == 1
print("cortech", cortech.__file__, "ok")
