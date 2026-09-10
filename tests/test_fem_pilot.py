import unittest

import numpy as np
from scipy import sparse

from compact_eeg.fem_pilot import (
    balanced_point_currents, local_electric_field, reference_current_transform,
    relative_difference, system_diagnostics,
)


class FEMDiagnosticTests(unittest.TestCase):
    def test_balanced_currents(self):
        b = balanced_point_currents(6, [4, 1, 2, 5])
        np.testing.assert_array_equal(b.sum(axis=0), 0)
        np.testing.assert_array_equal(b[4], -np.ones(3))

    def test_bad_electrodes(self):
        for electrodes in ([0, 1, 1, 2], [0, 1, 2, 6], [0, 1, 2]):
            with self.assertRaises(ValueError):
                balanced_point_currents(6, electrodes)

    def test_reference_current_basis(self):
        b = balanced_point_currents(4, [0, 1, 2, 3])
        expected = balanced_point_currents(4, [1, 0, 2, 3])
        np.testing.assert_array_equal(b @ reference_current_transform(), expected)

    def test_analytic_gradient_and_gauge(self):
        xyz = np.array([[[0., 0., 0.], [2., 0., 0.], [0., 3., 0.], [0., 0., 4.]]])
        coefficients = np.array([[1., -2.], [2., 0.], [-3., 4.]])
        potential = xyz @ coefficients + 7.
        np.testing.assert_allclose(local_electric_field(xyz, potential), -1000. * coefficients[None])
        np.testing.assert_allclose(local_electric_field(xyz, potential + 100.), -1000. * coefficients[None])

    def test_invalid_gradient_input(self):
        with self.assertRaises(ValueError):
            local_electric_field(np.zeros((4, 3)), np.zeros((4, 1)))

    def test_non_axis_aligned_gradient(self):
        xyz = np.array([[[1., 2., -3.], [3., 3., -2.], [0., 5., -3.], [2., 1., 1.]]])
        coefficients = np.array([[1., -2.], [2., 0.], [-3., 4.]])
        potential = xyz @ coefficients + 7.
        np.testing.assert_allclose(local_electric_field(xyz, potential), -1000. * coefficients[None], atol=1e-10)

    def test_conservative_graph_system(self):
        a = sparse.csr_matrix(4 * np.eye(4) - np.ones((4, 4)))
        b = balanced_point_currents(4, [0, 1, 2, 3])
        u = np.zeros((4, 3))
        u[1:] = np.linalg.solve(a.toarray()[1:, 1:], b[1:])
        checks, transfer = system_diagnostics(a, u, b, 0)
        self.assertLess(max(checks["relative_residual_per_rhs"]), 1e-14)
        self.assertLess(checks["transfer_reciprocity_relative_frobenius"], 1e-14)
        self.assertGreater(checks["transfer_symmetric_min_eigenvalue"], 0)
        np.testing.assert_allclose(transfer, transfer.T)

    def test_bad_solution_is_detected(self):
        a = sparse.csr_matrix(4 * np.eye(4) - np.ones((4, 4)))
        b = balanced_point_currents(4, [0, 1, 2, 3])
        checks, _ = system_diagnostics(a, np.zeros((4, 3)), b, 0)
        np.testing.assert_allclose(checks["relative_residual_per_rhs"], 1)

    def test_changed_reference_can_have_zero_current_at_voltage_gauge(self):
        a = sparse.csr_matrix(4 * np.eye(4) - np.ones((4, 4)))
        b = balanced_point_currents(4, [1, 0, 2, 3])
        u = np.zeros((4, 3))
        u[1:] = np.linalg.solve(a.toarray()[1:, 1:], b[1:])
        checks, _ = system_diagnostics(a, u, b, 0)
        self.assertTrue(np.all(np.isfinite(checks["reference_reaction_relative_error_per_rhs"])))

    def test_relative_difference(self):
        self.assertEqual(relative_difference(np.zeros(3), np.zeros(3)), 0)
        with self.assertRaises(ValueError):
            relative_difference([np.nan], [0])


if __name__ == "__main__":
    unittest.main()
