import unittest
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from compact_eeg.inverse_pilot import fixed_normal_scan, sample_cortical_triangles, error_summary


class InversePilotTests(unittest.TestCase):
    def test_signed_amplitude_scale_invariance(self):
        h = np.array([[1., .1, .2], [.2, 1., .1], [.1, .3, 1.], [.4, -.3, .2]])
        y = h[:, [2, 0, 1]] * [-2, 3, .5]
        for scale in (1e-8, 1., 1e8):
            np.testing.assert_array_equal(fixed_normal_scan(h * scale, y, np.eye(4), batch_size=2), [2, 0, 1])

    def test_correlated_noise_matches_direct_ml(self):
        rng = np.random.default_rng(5)
        h, y = rng.normal(size=(6, 15)), rng.normal(size=(6, 19))
        z = rng.normal(size=(6, 6))
        n = z @ z.T + np.eye(6)
        ni = np.linalg.inv(n)
        scores = (h.T @ ni @ y) ** 2 / np.sum(h * (ni @ h), axis=0)[:, None]
        np.testing.assert_array_equal(fixed_normal_scan(h, y, n), scores.argmax(axis=0))

    def test_orthogonal_reference_basis_invariance(self):
        rng = np.random.default_rng(6)
        h, y = rng.normal(size=(5, 14)), rng.normal(size=(5, 20))
        rotation, _ = np.linalg.qr(rng.normal(size=(5, 5)))
        np.testing.assert_array_equal(fixed_normal_scan(h, y, np.eye(5)), fixed_normal_scan(rotation @ h, rotation @ y, np.eye(5)))

    def test_invalid_covariance_and_zero_column(self):
        with self.assertRaises(ValueError):
            fixed_normal_scan(np.zeros((2, 1)), np.ones((2, 1)), np.eye(2))
        with self.assertRaises(np.linalg.LinAlgError):
            fixed_normal_scan(np.ones((2, 1)), np.ones((2, 1)), -np.eye(2))

    def test_sample_reproducibility_and_interior(self):
        space = {"rr": np.array([[0., 0, 0], [1., 0, 0], [0, 1., 0]]), "tris": np.array([[0, 1, 2]]), "nn": np.tile([0., 0., 1.], (3, 1))}
        a = sample_cortical_triangles([space], 100, 17)
        b = sample_cortical_triangles([space], 100, 17)
        for k in a:
            np.testing.assert_array_equal(a[k], b[k])
        self.assertTrue(np.all(a["barycentric_coordinates"] > 0))
        np.testing.assert_allclose(a["barycentric_coordinates"].sum(axis=1), 1)

    def test_errors_in_millimetres(self):
        stats = error_summary(np.array([[0., 10.], [20., 30.]]), np.ones(2))
        self.assertEqual(stats["median_error_mm"], 15)
        self.assertAlmostEqual(stats["source_lower10_utility_dmax50mm"], .5)


if __name__ == "__main__":
    unittest.main()
