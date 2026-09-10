from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from compact_eeg.surface import (
    connected_components,
    edge_incidence_counts,
    inspect_surface_mesh,
    total_area,
    triangle_areas,
    vertex_area_weights,
)


class SurfaceMeshTests(unittest.TestCase):
    def test_single_triangle_geometry_boundary_and_area_weights(self) -> None:
        vertices = np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        )
        triangles = np.array([[0, 1, 2]], dtype=int)

        np.testing.assert_allclose(triangle_areas(vertices, triangles), [0.5])
        self.assertAlmostEqual(total_area(vertices, triangles), 0.5)
        np.testing.assert_allclose(vertex_area_weights(vertices, triangles), [1 / 6] * 3)

        qc = inspect_surface_mesh(vertices, triangles)
        self.assertTrue(qc.all_finite)
        self.assertEqual(qc.boundary_edge_count, 3)
        self.assertEqual(qc.nonmanifold_edge_count, 0)
        self.assertEqual(qc.degenerate_triangle_count, 0)
        self.assertEqual(qc.connected_component_count, 1)
        self.assertAlmostEqual(float(qc.vertex_area_weights_m2.sum()), qc.total_area_m2)

    def test_closed_tetrahedron_has_no_boundary(self) -> None:
        vertices = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
            ]
        )
        triangles = np.array(
            [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]], dtype=int
        )

        qc = inspect_surface_mesh(vertices, triangles)
        self.assertEqual(qc.unique_edges.shape, (6, 2))
        np.testing.assert_array_equal(qc.edge_incidence_counts, np.full(6, 2))
        self.assertEqual(qc.boundary_edge_count, 0)
        self.assertEqual(qc.nonmanifold_edge_count, 0)
        self.assertEqual(qc.connected_component_count, 1)

    def test_three_faces_on_one_edge_are_nonmanifold(self) -> None:
        vertices = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, -1.0, 0.0],
                [0.5, 0.0, 1.0],
            ]
        )
        triangles = np.array([[0, 1, 2], [1, 0, 3], [0, 1, 4]], dtype=int)

        edges, counts = edge_incidence_counts(triangles, vertex_count=5)
        np.testing.assert_array_equal(edges[counts == 3], [[0, 1]])
        qc = inspect_surface_mesh(vertices, triangles)
        self.assertEqual(qc.nonmanifold_edge_count, 1)
        np.testing.assert_array_equal(qc.nonmanifold_edges, [[0, 1]])
        self.assertEqual(qc.boundary_edge_count, 6)

    def test_components_include_isolated_vertices(self) -> None:
        vertices = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [3.0, 0.0, 0.0],
                [4.0, 0.0, 0.0],
                [3.0, 1.0, 0.0],
                [9.0, 9.0, 9.0],
            ]
        )
        triangles = np.array([[0, 1, 2], [3, 4, 5]], dtype=int)

        count, labels = connected_components(vertices, triangles)
        self.assertEqual(count, 3)
        self.assertEqual(len(np.unique(labels[:3])), 1)
        self.assertEqual(len(np.unique(labels[3:6])), 1)
        self.assertNotEqual(labels[0], labels[3])
        self.assertNotIn(labels[6], (labels[0], labels[3]))

    def test_degenerate_and_nonfinite_failures_are_separate(self) -> None:
        collinear_vertices = np.array(
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]
        )
        one_triangle = np.array([[0, 1, 2]], dtype=int)
        degenerate = inspect_surface_mesh(collinear_vertices, one_triangle)
        self.assertTrue(degenerate.all_finite)
        np.testing.assert_array_equal(degenerate.degenerate_triangle_indices, [0])

        nonfinite_vertices = collinear_vertices.copy()
        nonfinite_vertices[1, 0] = np.nan
        nonfinite = inspect_surface_mesh(nonfinite_vertices, one_triangle)
        self.assertFalse(nonfinite.vertices_are_finite)
        self.assertFalse(nonfinite.triangle_areas_are_finite)
        self.assertFalse(nonfinite.all_finite)
        self.assertEqual(nonfinite.degenerate_triangle_count, 0)
        self.assertTrue(np.isnan(nonfinite.total_area_m2))

    def test_area_tolerance_can_flag_small_triangles(self) -> None:
        vertices = np.array(
            [[0.0, 0.0, 0.0], [1e-6, 0.0, 0.0], [0.0, 1e-6, 0.0]]
        )
        triangles = np.array([[0, 1, 2]], dtype=int)
        self.assertEqual(inspect_surface_mesh(vertices, triangles).degenerate_triangle_count, 0)
        self.assertEqual(
            inspect_surface_mesh(
                vertices, triangles, area_tolerance_m2=1e-12
            ).degenerate_triangle_count,
            1,
        )

    def test_invalid_mesh_structure_and_indices_are_rejected(self) -> None:
        vertices = np.zeros((3, 3), dtype=float)
        with self.assertRaisesRegex(ValueError, "vertices_m must have shape"):
            inspect_surface_mesh(np.zeros((3, 2)), np.array([[0, 1, 2]]))
        with self.assertRaisesRegex(ValueError, "triangles must have shape"):
            inspect_surface_mesh(vertices, np.array([0, 1, 2]))
        with self.assertRaisesRegex(ValueError, "integer vertex indices"):
            inspect_surface_mesh(vertices, np.array([[0.0, 1.0, 2.0]]))
        with self.assertRaisesRegex(ValueError, "negative"):
            inspect_surface_mesh(vertices, np.array([[0, 1, -1]], dtype=int))
        with self.assertRaisesRegex(ValueError, "out-of-range"):
            inspect_surface_mesh(vertices, np.array([[0, 1, 3]], dtype=int))
        with self.assertRaisesRegex(ValueError, "non-negative"):
            inspect_surface_mesh(vertices, np.array([[0, 1, 2]]), area_tolerance_m2=-1)


if __name__ == "__main__":
    unittest.main()
