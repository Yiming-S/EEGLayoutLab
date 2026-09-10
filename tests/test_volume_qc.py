import unittest

import numpy as np

from compact_eeg.volume_qc import tetrahedron_metrics


class VolumeQCTests(unittest.TestCase):
    def setUp(self):
        self.regular = np.array([
            [0, 0, 0], [1, 0, 0], [0.5, np.sqrt(3) / 2, 0],
            [0.5, np.sqrt(3) / 6, np.sqrt(2 / 3)],
        ])

    def test_regular_volume_and_quality(self):
        result = tetrahedron_metrics(self.regular[None])
        self.assertAlmostEqual(result["signed_volume"][0], np.sqrt(2) / 12)
        self.assertAlmostEqual(result["mean_ratio_quality"][0], 1)

    def test_orientation_flip_changes_only_sign(self):
        result = tetrahedron_metrics(self.regular[[1, 0, 2, 3]][None])
        self.assertLess(result["signed_volume"][0], 0)
        self.assertAlmostEqual(result["mean_ratio_quality"][0], 1)

    def test_scale_and_translation(self):
        result = tetrahedron_metrics((self.regular * 1000 + 500)[None])
        self.assertAlmostEqual(result["signed_volume"][0] / 1e9, np.sqrt(2) / 12)
        self.assertAlmostEqual(result["mean_ratio_quality"][0], 1)

    def test_degenerate_and_collapsed(self):
        flat = self.regular.copy()
        flat[:, 2] = 0
        result = tetrahedron_metrics(np.stack([flat, np.zeros((4, 3))]))
        np.testing.assert_array_equal(result["signed_volume"], 0)
        np.testing.assert_array_equal(result["mean_ratio_quality"], 0)

    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            tetrahedron_metrics(np.zeros((4, 3)))
        with self.assertRaises(ValueError):
            tetrahedron_metrics(np.full((1, 4, 3), np.nan))


if __name__ == "__main__":
    unittest.main()
