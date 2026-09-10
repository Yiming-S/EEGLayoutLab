from __future__ import annotations

from io import BytesIO
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from compact_eeg.forward_pilot import (
    compute_forward_diagnostics,
    deterministic_farthest_point_indices,
    deterministic_npz_bytes,
    write_npz_once,
)
from compact_eeg.metrics import helmert_contrast


class ForwardPilotTests(unittest.TestCase):
    def test_farthest_point_selection_is_deterministic_and_unique(self) -> None:
        points = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [2.0, 0.0, 0.0],
                [0.0, 3.0, 0.0],
            ]
        )
        expected = np.array([0, 3, 2])
        np.testing.assert_array_equal(
            deterministic_farthest_point_indices(points, 3), expected
        )
        np.testing.assert_array_equal(
            deterministic_farthest_point_indices(points, 3), expected
        )

    def test_forward_diagnostics_remove_arbitrary_common_potential(self) -> None:
        rng = np.random.default_rng(20260906)
        leadfield = rng.normal(size=(8, 12))
        result = compute_forward_diagnostics(leadfield)

        self.assertEqual(result.helmert.shape, (7, 8))
        self.assertEqual(result.reference_free_leadfield.shape, (7, 12))
        self.assertLess(
            result.report["reference_invariance"]["relative_frobenius_difference"],
            1e-14,
        )
        self.assertEqual(
            result.report["identity_self_reconstruction"]["relative_mse"], 0.0
        )
        self.assertLess(
            result.report["lmmse_self_reconstruction"]["relative_mse"], 1e-20
        )
        self.assertAlmostEqual(
            result.report["lmmse_self_reconstruction"]["explained_energy"], 1.0
        )

    def test_deterministic_npz_is_order_independent_and_pickle_free(self) -> None:
        first = deterministic_npz_bytes(
            {"b": np.array([3, 4]), "a": np.eye(2)}
        )
        second = deterministic_npz_bytes(
            {"a": np.eye(2), "b": np.array([3, 4])}
        )
        self.assertEqual(first, second)
        with np.load(BytesIO(first), allow_pickle=False) as archive:
            np.testing.assert_array_equal(archive["a"], np.eye(2))
            np.testing.assert_array_equal(archive["b"], [3, 4])

    def test_svd_rank_and_covariance_pinv_rank_have_distinct_cutoffs(self) -> None:
        contrast = helmert_contrast(3)
        leadfield = contrast.T @ np.diag([1.0, 1e-8])
        result = compute_forward_diagnostics(leadfield, lmmse_rcond=1e-12)
        report = result.report["reference_free_leadfield"]
        self.assertEqual(report["svd_numerical_rank"], 2)
        self.assertEqual(report["covariance_pinv_effective_rank"], 1)
        self.assertEqual(report["svd_relative_cutoff"], 1e-12)
        self.assertEqual(report["covariance_pinv_relative_cutoff"], 1e-12)
        self.assertEqual(report["covariance_pinv_implied_svd_relative_cutoff"], 1e-6)
        self.assertEqual(report["numerical_rank_at_lmmse_rcond"], report["svd_numerical_rank"])
        self.assertEqual(report["condition_number_at_lmmse_rcond"], report["svd_condition_number"])
        self.assertIn("historical", report["legacy_rank_fields_semantics"])
        self.assertEqual(
            result.report["lmmse_self_reconstruction"]["covariance_pinv_effective_rank"],
            1,
        )

    def test_write_npz_once_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "artifact.npz"
            digest = write_npz_once(destination, {"x": np.arange(4)})
            self.assertEqual(len(digest), 64)
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                write_npz_once(destination, {"x": np.arange(4)})

    def test_invalid_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "points must have shape"):
            deterministic_farthest_point_indices(np.zeros((3, 2)), 2)
        with self.assertRaisesRegex(ValueError, "count must lie"):
            deterministic_farthest_point_indices(np.zeros((3, 3)), 4)
        with self.assertRaisesRegex(ValueError, "leadfield must be finite"):
            compute_forward_diagnostics(np.array([[1.0], [np.nan]]))
        with self.assertRaisesRegex(ValueError, "object arrays"):
            deterministic_npz_bytes({"bad": np.array([object()], dtype=object)})


if __name__ == "__main__":
    unittest.main()
