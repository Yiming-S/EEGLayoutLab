import unittest
import importlib.util

import numpy as np
from scipy import sparse

from compact_eeg.cortical_fem import (
    FixedMeshLeadfield, balanced_sampling_rhs, compose_normal_operator, point_sampling_matrix,
    preserved_numpy_search_seed,
)


class CorticalFEMOperatorTests(unittest.TestCase):
    def test_point_sampling_and_coordinates(self):
        xyz = np.array([[0., 0., 0.], [10., 0., 0.], [0., 10., 0.], [0., 0., 10.]])
        p = point_sampling_matrix(4, [[0, 1, 2]], [[.2, .3, .5]])
        np.testing.assert_allclose(p @ xyz, [[3, 5, 0]])
        np.testing.assert_allclose(p.sum(axis=1), 1)

    def test_reject_bad_weights(self):
        for weights in ([[.2, .3, .4]], [[-.1, .6, .5]], [[np.nan, 0, 1]]):
            with self.assertRaises(ValueError):
                point_sampling_matrix(4, [[0, 1, 2]], weights)

    def test_balanced_barycentric_load(self):
        p = point_sampling_matrix(5, [[0, 1, 2], [1, 2, 3]], [[.2, .3, .5], [.1, .2, .7]])
        rhs = balanced_sampling_rhs(p, 4, 2.)
        np.testing.assert_allclose(rhs.sum(axis=0), 0, atol=1e-15)
        np.testing.assert_allclose(rhs[4], -2)
        np.testing.assert_allclose(rhs[:4, 0], [.4, .6, 1., 0.])

    def test_point_equal_to_gauge_has_zero_load(self):
        p = point_sampling_matrix(4, [[0, 1, 2]], [[1., 0., 0.]])
        np.testing.assert_array_equal(balanced_sampling_rhs(p, 0), 0)

    def test_reference_gauge_cancels_under_contrast(self):
        p = point_sampling_matrix(4, [[0, 1, 2], [0, 1, 2]], [[.2, .3, .5], [.1, .6, .3]])
        first = balanced_sampling_rhs(p, 0)
        second = balanced_sampling_rhs(p, 3)
        np.testing.assert_allclose(first[:, 1] - first[:, 0], second[:, 1] - second[:, 0])

    def test_analytical_tetrahedron_reciprocity_sign_and_units(self):
        # One 1-m tetrahedron encoded as mm. Unit-current analytical U=6I
        # on the three non-gauge vertices. EEG gain is +grad(U), not E.
        gradients = np.array([[[-1., -1., -1.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]]) / 1000
        m = sparse.csr_matrix([[1.], [1.]])
        normals = np.array([[1., 0., 0.], [0., 1., 0.]])
        operator = compose_normal_operator(m, gradients, [[0, 1, 2, 3]], normals, 4)
        potentials = np.vstack([np.zeros(3), 6 * np.eye(3)])
        np.testing.assert_allclose(operator @ potentials, [[6, 0, 0], [0, 6, 0]])
        np.testing.assert_allclose(operator @ np.ones(4), 0)

    def test_multiple_elements_and_signed_recovery_weights(self):
        g = np.array([[[-1., -1., -1.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]],
                      [[-2., -2., -2.], [2., 0., 0.], [0., 2., 0.], [0., 0., 2.]]]) / 1000
        m = sparse.csr_matrix([[-.2, 1.2]])
        operator = compose_normal_operator(m, g, [[0, 1, 2, 3], [4, 5, 6, 7]], [[0, 0, 1]], 8)
        voltage = np.arange(8.)
        expected = -.2 * (voltage[3] - voltage[0]) + 1.2 * 2 * (voltage[7] - voltage[4])
        np.testing.assert_allclose(operator @ voltage, [expected])

    def test_mapping_dimensions_and_normals_rejected(self):
        m = sparse.csr_matrix([[1.]])
        g = np.zeros((1, 4, 3))
        with self.assertRaises(ValueError):
            compose_normal_operator(m, g, [[0, 1, 2]], [[1, 0, 0]], 4)
        with self.assertRaises(ValueError):
            compose_normal_operator(m, g, [[0, 1, 2, 3]], [[2, 0, 0]], 4)

    def test_search_seed_repeats_and_restores_caller_state(self):
        prior = np.random.get_state()
        try:
            np.random.seed(901)
            before = np.random.get_state()
            with preserved_numpy_search_seed(123):
                first = np.random.permutation(30)
            with preserved_numpy_search_seed(123):
                second = np.random.permutation(30)
            after = np.random.get_state()
            np.testing.assert_array_equal(first, second)
            np.testing.assert_array_equal(before[1], after[1])
            self.assertEqual(before[2:], after[2:])
        finally:
            np.random.set_state(prior)


@unittest.skipUnless(importlib.util.find_spec("simnibs") is not None, "requires isolated SimNIBS native environment")
class NativeCorticalFEMSmokeTests(unittest.TestCase):
    def test_four_tetrahedra_continuous_electrodes_and_fallback(self):
        # Four tetrahedra have non-coplanar element barycentres, making the
        # official recovery's temporary boundary-node patch full rank. A single
        # tetrahedron does not support that official recovery implementation.
        # This native smoke costs a five-node factorization, never Ernie.
        from simnibs.mesh_tools import mesh_io

        xyz = np.vstack([np.zeros(3), np.eye(3), [.25, .25, .25]]) * 1000.
        triangles = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
        tetrahedra = np.column_stack((triangles, np.full(4, 4)))
        for tet in tetrahedra:
            if np.linalg.det(xyz[tet[1:]] - xyz[tet[0]]) < 0:
                tet[1], tet[2] = tet[2], tet[1]
        mesh = mesh_io.Msh()
        mesh.nodes = mesh_io.Nodes(xyz)
        mesh.elm = mesh_io.Elements(triangles=triangles + 1, tetrahedra=tetrahedra + 1)
        mesh.elm.tag1[:] = 2
        mesh.elm.tag2[:] = 2
        mesh.elm.tag1[:4] = 1002
        mesh.elm.tag2[:4] = 1002
        sources = np.array([[120., 180., 230.], [450., 160., 170.], [1200., 0., 0.]])
        normals = np.tile([1., 0., 0.], (3, 1))
        forward = FixedMeshLeadfield(mesh, np.ones(mesh.elm.nr), xyz[:4], triangles, np.arange(4), sources, normals, gauge_node=1)
        self.assertEqual(forward.source_qa["sources_in_gm_count"], 2)
        self.assertEqual(forward.source_qa["sources_outside_gm_count"], 1)
        self.assertAlmostEqual(forward.source_qa["fallback_distance_mm"]["maximum"], 200.)
        self.assertIsNone(forward.system)
        projection = forward.project(
            np.array([[200., 0., 0.], [0., 1000., 0.], [0., 0., 0.]]),
            triangle_ids=[0, 0, 0], barycentric_weights=[[.8, 0., .2], [0., 1., 0.], [1., 0., 0.]],
        )
        gain, qa = forward.evaluate(projection, block_size=2)
        # Independently assemble this tiny analytical linear-element matrix via
        # inverse affine Vandermonde matrices. This is a test oracle only.
        expected_k = np.zeros((5, 5))
        for tet in tetrahedra:
            points_m = xyz[tet] * .001
            vandermonde = np.column_stack((np.ones(4), points_m))
            gradient = np.linalg.inv(vandermonde)[1:, :].T
            volume = abs(np.linalg.det(points_m[1:] - points_m[0])) / 6
            expected_k[np.ix_(tet, tet)] += volume * gradient @ gradient.T
        rhs = balanced_sampling_rhs(projection.matrix, 0)
        expected_u = np.zeros((5, 3))
        expected_u[1:] = np.linalg.solve(expected_k[1:, 1:], rhs[1:])
        np.testing.assert_allclose(forward.system.A.toarray(), expected_k, atol=1e-12)
        np.testing.assert_allclose(gain, (forward.source_operator @ expected_u).T, atol=1e-10)
        np.testing.assert_allclose(gain[2], 0, atol=1e-10)
        original_system = forward.system
        gain_repeat, _ = forward.evaluate(projection, block_size=1, current_amperes=2.)
        self.assertIs(forward.system, original_system)
        np.testing.assert_allclose(gain_repeat, gain, atol=1e-10)
        self.assertLess(qa["max_relative_full_system_residual"], 1e-10)
        forward.close()


if __name__ == "__main__":
    unittest.main()
