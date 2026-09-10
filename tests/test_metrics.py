from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from compact_eeg.metrics import (
    helmert_contrast,
    lmmse_explained_energy,
    localization_utility,
    lower_cvar,
    participation_effective_rank,
    passes_ar,
    relative_retention,
    weighted_lower_cvar,
)


class MetricTests(unittest.TestCase):
    def test_helmert_is_reference_free_and_orthonormal(self) -> None:
        contrast = helmert_contrast(64)
        self.assertEqual(contrast.shape, (63, 64))
        np.testing.assert_allclose(contrast @ np.ones(64), 0.0, atol=1e-12)
        np.testing.assert_allclose(contrast @ contrast.T, np.eye(63), atol=1e-12)

    def test_lower_cvar_uses_lowest_tail(self) -> None:
        self.assertAlmostEqual(lower_cvar([0.1, 0.2, 0.9, 1.0], 0.5), 0.15)

    def test_lower_cvar_splits_boundary_observation(self) -> None:
        self.assertAlmostEqual(lower_cvar(np.arange(12), 0.1), 1.0 / 6.0)
        self.assertAlmostEqual(lower_cvar([2.0, 9.0], 0.1), 2.0)
        self.assertAlmostEqual(lower_cvar([2.0, 9.0], 1.0), 5.5)

    def test_lower_cvar_matches_equal_weighted_cvar(self) -> None:
        values = [0.6, 0.1, 0.9, 0.4, 0.2, 0.8, 0.3]
        for fraction in (0.01, 0.1, 0.25, 0.7, 1.0):
            self.assertAlmostEqual(
                lower_cvar(values, fraction),
                weighted_lower_cvar(values, np.ones(len(values)), fraction),
            )

    def test_weighted_lower_cvar_splits_boundary_weight(self) -> None:
        score = weighted_lower_cvar([0.1, 0.5, 0.9], [0.1, 0.8, 0.1], 0.2)
        self.assertAlmostEqual(score, 0.3)

    def test_effective_rank(self) -> None:
        self.assertAlmostEqual(participation_effective_rank(np.eye(5)), 5.0)
        self.assertAlmostEqual(participation_effective_rank(np.diag([4.0, 0.0, 0.0])), 1.0)

    def test_effective_rank_is_scale_invariant(self) -> None:
        information = np.array([[4.0, 1.0], [1.0, 2.0]])
        expected = float(np.trace(information) ** 2 / np.trace(information @ information))
        for scale in (1e-200, 1e-15, 1.0, 1e15, 1e200):
            with self.subTest(scale=scale):
                self.assertAlmostEqual(
                    participation_effective_rank(scale * information), expected
                )
                self.assertAlmostEqual(
                    participation_effective_rank(scale * np.eye(5)), 5.0
                )
        self.assertEqual(participation_effective_rank(np.zeros((3, 3))), 0.0)

    def test_effective_rank_rejects_relative_indefiniteness(self) -> None:
        for scale in (1e-200, 1.0, 1e200):
            with self.subTest(scale=scale):
                with self.assertRaisesRegex(ValueError, "positive semidefinite"):
                    participation_effective_rank(scale * np.diag([1.0, -0.1]))
                self.assertAlmostEqual(
                    participation_effective_rank(scale * np.diag([1.0, -1e-15])), 1.0
                )

    def test_effective_rank_validates_input(self) -> None:
        for matrix in (np.empty((0, 0)), np.full((2, 2), np.nan), np.ones((2, 3))):
            with self.assertRaises(ValueError):
                participation_effective_rank(matrix)
        with self.assertRaisesRegex(ValueError, "symmetric"):
            participation_effective_rank(np.array([[1.0, 1.0], [0.0, 1.0]]) * 1e-200)
        for tolerance in (-1.0, 1.0, np.nan, np.inf):
            with self.assertRaisesRegex(ValueError, "tolerance"):
                participation_effective_rank(np.eye(2), tolerance=tolerance)

    def test_lmmse_identity(self) -> None:
        identity = np.eye(3)
        self.assertAlmostEqual(lmmse_explained_energy(identity, identity, identity), 1.0)

    def test_relative_retention_is_not_clipped(self) -> None:
        self.assertAlmostEqual(relative_retention(0.9, 0.75), 1.2)

    def test_localization_utility_has_absolute_mm_scale(self) -> None:
        utility = localization_utility([0.0, 25.0, 50.0, 75.0], d_max_mm=50.0)
        np.testing.assert_allclose(utility, [1.0, 0.5, 0.0, 0.0])

    def test_ar_requires_every_metric(self) -> None:
        metrics = {"field": 0.95, "sensitivity": 0.91, "localization": 0.89}
        self.assertFalse(passes_ar(metrics, 0.90, ["field", "sensitivity", "localization"]))
        self.assertTrue(passes_ar(metrics, 0.89, ["field", "sensitivity", "localization"]))


if __name__ == "__main__":
    unittest.main()
