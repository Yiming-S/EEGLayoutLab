from __future__ import annotations

import unittest
import numpy as np

from compact_eeg.inverse_pilot import fixed_normal_scan
from compact_eeg.refined_localization import (
    available_native_faces, diagnose_nested_dictionaries,
    linear_triangle_refine, profiled_grid_scan,
)


class RefinedLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.xyz = np.array([[0., 0., 0.], [10., 0., 0.], [0., 10., 0.]])
        self.faces = np.array([[0, 1, 2]])
        self.h = np.eye(3)

    def test_profiled_scan_matches_existing_signed_ml(self):
        rng = np.random.default_rng(73)
        h = rng.normal(size=(8, 17))
        y = rng.normal(size=(8, 11))
        noise = np.diag(np.arange(1., 9.))
        fit = profiled_grid_scan(h, y, noise, batch_size=3)
        np.testing.assert_array_equal(fit.dictionary_indices, fixed_normal_scan(h, y, noise))
        inv = np.linalg.inv(noise)
        for i, index in enumerate(fit.dictionary_indices):
            expected = h[:, index] @ inv @ y[:, i] / (h[:, index] @ inv @ h[:, index])
            self.assertAlmostEqual(expected, fit.signed_moments_am[i])

    def test_continuous_interior_positive_and_negative_amplitudes(self):
        w = np.array([.2, .3, .5])
        amplitudes = np.array([2e-8, -3e-8])
        result = linear_triangle_refine(self.h, self.xyz, self.faces, w[:, None]*amplitudes, np.diag([2., 3., 5.]))
        np.testing.assert_allclose(result.estimated_xyz_mm, np.tile(w @ self.xyz, (2, 1)), atol=1e-10)
        np.testing.assert_allclose(result.barycentric_weights, np.tile(w, (2, 1)), atol=1e-12)
        np.testing.assert_allclose(result.signed_moments_am, amplitudes, rtol=1e-12)
        self.assertTrue(np.all(result.improved_over_discrete))
        self.assertLess(result.relative_residual_squared.max(), 1e-25)

    def test_boundary_active_set_does_not_extrapolate(self):
        result = linear_triangle_refine(self.h, self.xyz, self.faces, np.array([[-.2], [.3], [.5]]), np.eye(3))
        self.assertGreaterEqual(result.barycentric_weights.min(), 0)
        self.assertAlmostEqual(result.barycentric_weights.sum(), 1)
        self.assertAlmostEqual(result.barycentric_weights[0, 0], 0)
        np.testing.assert_allclose(result.estimated_xyz_mm[0], [3.75, 6.25, 0], atol=1e-10)

    def test_vertex_exact_fit_keeps_discrete_and_zero_observation_is_stable(self):
        y = np.column_stack([self.h[:, 1]*-2, np.zeros(3)])
        r = linear_triangle_refine(self.h, self.xyz, self.faces, y, np.eye(3))
        np.testing.assert_array_equal(r.triangle_indices, [-1, -1])
        np.testing.assert_array_equal(r.improved_over_discrete, [False, False])
        np.testing.assert_allclose(r.relative_residual_squared, 0)

    def test_whitening_and_joint_scale_invariance(self):
        rng = np.random.default_rng(19)
        h = rng.normal(size=(6, 3))
        y = h @ np.array([[.2, -.4], [.3, -.5], [.5, -.1]])
        n = np.diag(np.arange(1., 7.))
        a = linear_triangle_refine(h, self.xyz, self.faces, y, n)
        b = linear_triangle_refine(1e3*h, self.xyz, self.faces, 1e3*y, n*1e6)
        np.testing.assert_allclose(a.estimated_xyz_mm, b.estimated_xyz_mm, atol=1e-10)
        np.testing.assert_allclose(a.signed_moments_am, b.signed_moments_am, atol=1e-12)

    def test_native_face_mapping_never_adds_connections(self):
        native = np.array([[4, 2, 8], [2, 8, 9], [1, 2, 4]])
        retained = np.array([True, False, True])
        face_ids, mapped = available_native_faces(native, np.array([8, 4, 2, 9]), retained_face_mask=retained)
        np.testing.assert_array_equal(face_ids, [0])
        np.testing.assert_array_equal(mapped, [[1, 2, 0]])
        no_faces, empty = available_native_faces(native, np.array([4, 9]))
        self.assertEqual(no_faces.size, 0)
        self.assertEqual(empty.shape, (0, 3))

    def test_nested_control_shared_data_monotone_residual_and_geometric_floor(self):
        rng = np.random.default_rng(31)
        h = rng.normal(size=(6, 6))
        xyz = np.column_stack([np.arange(6.), np.zeros(6), np.zeros(6)])
        truth = np.array([[1.2, 0, 0], [3.8, 0, 0]])
        y = np.column_stack([h[:, 1]*.8+h[:, 2]*.2, h[:, 3]*.2+h[:, 4]*.8])
        control = diagnose_nested_dictionaries(h, y, np.eye(6), xyz, truth,
            {"coarse": np.array([0, 2, 4]), "fine": np.arange(6)})
        self.assertTrue(np.all(control.relative_residual_squared["fine"] <= control.relative_residual_squared["coarse"]+1e-12))
        self.assertTrue(np.all(control.errors_mm["fine"] >= control.nearest_dictionary_distances_mm["fine"]-1e-12))
        np.testing.assert_allclose(control.nearest_dictionary_distances_mm["fine"], [.2, .2])

    def test_nested_control_truth_cannot_change_the_estimates(self):
        rng = np.random.default_rng(101)
        h, y = rng.normal(size=(5, 3)), rng.normal(size=(5, 2))
        kwargs = dict(leadfield=h, observations=y, noise_covariance=np.eye(5), dictionary_xyz_mm=self.xyz,
                      dictionaries={"all": np.arange(3)})
        a = diagnose_nested_dictionaries(evaluation_xyz_mm=np.ones((2, 3)), **kwargs)
        b = diagnose_nested_dictionaries(evaluation_xyz_mm=np.full((2, 3), 100.), **kwargs)
        np.testing.assert_array_equal(a.fitted_full_dictionary_indices["all"], b.fitted_full_dictionary_indices["all"])

    def test_reject_dictionary_leakage_nonnested_and_unqualified_faces(self):
        with self.assertRaises(ValueError):
            diagnose_nested_dictionaries(self.h, self.h[:, :1], np.eye(3), self.xyz, self.xyz[:1], {"all": np.arange(3)})
        with self.assertRaises(ValueError):
            diagnose_nested_dictionaries(self.h, self.h[:, :1], np.eye(3), self.xyz, np.ones((1, 3)),
                                         {"first": np.array([0, 1]), "second": np.array([1, 2])})
        for faces in (np.empty((0, 3), dtype=int), np.array([[0, 0, 1]]), np.array([[0, 1, 3]])):
            with self.subTest(faces=faces.tolist()), self.assertRaises(ValueError):
                linear_triangle_refine(self.h, self.xyz, faces, np.ones((3, 1)), np.eye(3))

    def test_wrong_covariance_zero_columns_and_shapes_rejected(self):
        for h, y, n in ((np.zeros((3, 3)), np.ones((3, 1)), np.eye(3)),
                        (self.h, np.ones((3, 1)), -np.eye(3)),
                        (self.h, np.ones((2, 1)), np.eye(3))):
            with self.subTest(), self.assertRaises((ValueError, np.linalg.LinAlgError)):
                profiled_grid_scan(h, y, n)


if __name__ == "__main__":
    unittest.main()
