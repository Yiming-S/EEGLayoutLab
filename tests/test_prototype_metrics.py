from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from compact_eeg.metrics import helmert_contrast, lmmse_explained_energy
from compact_eeg.prototype_metrics import evaluate_prototype_metrics


class PrototypeMetricTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rng = np.random.default_rng(7128)
        self.baseline = self.rng.normal(size=(64, 12))
        self.candidate = self.rng.normal(size=(64, 12))
        self.weights = np.arange(1., 13.)

    def evaluate(self, baseline=None, candidate=None, weights=None, **kwargs):
        options = {"source_moment_am": 1e-8, "numerical_zero_relative_tolerance": 1e-8}
        options.update(kwargs)
        return evaluate_prototype_metrics(
            self.baseline if baseline is None else baseline,
            self.candidate if candidate is None else candidate,
            self.weights if weights is None else weights,
            **options,
        )

    def test_baseline_identity_with_noisy_absolute_scores(self) -> None:
        result = self.evaluate(candidate=self.baseline)
        sensitivity = result.report["source_sensitivity"]
        self.assertAlmostEqual(sensitivity["area_weighted_lower_tail_retention_unclipped"], 1.0)
        self.assertEqual(sensitivity["excluded_source_area_fraction"], 0.0)
        for row in result.report["conditions"]:
            self.assertAlmostEqual(row["field_retention_unclipped"], 1.0)
            self.assertEqual(row["baseline_identity_field_retention"], 1.0)
            self.assertGreater(row["reference_field_explained_energy"], 0)
            self.assertLess(row["reference_field_explained_energy"], 1)
        self.assertFalse(result.report["formal_v2_performance_eligible"])
        self.assertFalse(result.report["ar_computed"])
        json.dumps(result.report, allow_nan=False)

    def test_reference_fixed_noise_matches_direct_covariance_formula(self) -> None:
        result = self.evaluate()
        c = helmert_contrast(64)
        hb, hx = c @ self.baseline * 1e-8, c @ self.candidate * 1e-8
        weights = self.weights / self.weights.sum()
        cbb, cxx, cbx = (hb * weights) @ hb.T, (hx * weights) @ hx.T, (hb * weights) @ hx.T
        power = float(np.trace(cbb) / 63)
        for row in result.report["conditions"]:
            variance = power * 10 ** (-row["nominal_reference_snr_db"] / 10)
            self.assertAlmostEqual(row["shared_physical_electrode_noise_variance_v2"] / variance, 1)
            self.assertAlmostEqual(
                row["candidate_field_explained_energy"],
                lmmse_explained_energy(cbb, cbx, cxx + variance * np.eye(63)),
                places=11,
            )

    def test_candidate_strength_does_not_change_noise_and_ratios_are_unclipped(self) -> None:
        original = self.evaluate(candidate=self.baseline)
        stronger = self.evaluate(candidate=2 * self.baseline)
        self.assertAlmostEqual(stronger.report["source_sensitivity"]["area_weighted_lower_tail_retention_unclipped"], 2)
        for weak, strong in zip(original.report["conditions"], stronger.report["conditions"]):
            self.assertEqual(weak["shared_physical_electrode_noise_variance_v2"], strong["shared_physical_electrode_noise_variance_v2"])
            self.assertGreater(strong["field_retention_unclipped"], 1)

    def test_zero_candidate_gives_zero_signal_metrics(self) -> None:
        result = self.evaluate(candidate=np.zeros_like(self.baseline))
        self.assertEqual(result.report["source_sensitivity"]["area_weighted_lower_tail_retention_unclipped"], 0)
        for row in result.report["conditions"]:
            self.assertEqual(row["candidate_field_explained_energy"], 0)
            self.assertEqual(row["candidate_noise_whitened_area_weighted_effective_rank"], 0)

    def test_reference_shifts_and_channel_permutations_are_invariant(self) -> None:
        original = self.evaluate()
        b_order = self.rng.permutation(64)
        x_order = self.rng.permutation(64)
        changed = self.evaluate(
            baseline=self.baseline[b_order] + self.rng.normal(size=12)[None, :],
            candidate=self.candidate[x_order] + self.rng.normal(size=12)[None, :],
        )
        np.testing.assert_allclose(original.sensitivity_ratio, changed.sensitivity_ratio, rtol=1e-12)
        for before, after in zip(original.report["conditions"], changed.report["conditions"]):
            for key in ("reference_field_explained_energy", "candidate_field_explained_energy", "field_retention_unclipped", "reference_noise_whitened_area_weighted_effective_rank", "candidate_noise_whitened_area_weighted_effective_rank"):
                self.assertAlmostEqual(before[key], after[key], places=10)

    def test_joint_source_permutation_and_area_units_are_invariant(self) -> None:
        original = self.evaluate()
        order = self.rng.permutation(12)
        changed = self.evaluate(baseline=self.baseline[:, order], candidate=self.candidate[:, order], weights=self.weights[order] * 1e100)
        np.testing.assert_allclose(original.sensitivity_ratio[order], changed.sensitivity_ratio)
        for before, after in zip(original.report["conditions"], changed.report["conditions"]):
            self.assertAlmostEqual(before["field_retention_unclipped"], after["field_retention_unclipped"], places=11)

    def test_joint_leadfield_scale_changes_noise_not_retention(self) -> None:
        original = self.evaluate()
        scale = 1e5
        changed = self.evaluate(baseline=self.baseline * scale, candidate=self.candidate * scale)
        for before, after in zip(original.report["conditions"], changed.report["conditions"]):
            self.assertAlmostEqual(before["field_retention_unclipped"], after["field_retention_unclipped"], places=11)
            self.assertAlmostEqual(after["shared_physical_electrode_noise_variance_v2"] / before["shared_physical_electrode_noise_variance_v2"] / scale ** 2, 1)

    def test_weighted_tail_splits_boundary_source_mass_exactly(self) -> None:
        baseline = self.baseline[:, :3]
        result = self.evaluate(baseline=baseline, candidate=baseline * [.1, .5, .9], weights=np.array([.1, .8, .1]), source_tail_fraction=.2)
        self.assertAlmostEqual(result.report["source_sensitivity"]["area_weighted_lower_tail_retention_unclipped"], .3)

    def test_numerical_zero_rule_reports_area_not_quantile(self) -> None:
        baseline = self.baseline[:, :3].copy()
        baseline[:, 0] *= 1e-12
        result = self.evaluate(baseline=baseline, candidate=baseline, weights=np.array([.0005, .4995, .5]))
        stats = result.report["source_sensitivity"]
        self.assertEqual(stats["excluded_source_count"], 1)
        self.assertAlmostEqual(stats["excluded_source_area_fraction"], .0005)
        self.assertTrue(stats["within_excluded_area_reporting_budget"])
        self.assertAlmostEqual(stats["area_weighted_lower_tail_retention_unclipped"], 1)
        self.assertTrue(np.isnan(result.sensitivity_ratio[0]))
        self.assertIn("exploratory_unvalidated", stats["numerical_zero_rule"])
        json.dumps(result.report, allow_nan=False)

    def test_excess_excluded_area_suppresses_unqualified_tail_score(self) -> None:
        baseline = self.baseline[:, :3].copy()
        baseline[:, 0] = 0
        result = self.evaluate(baseline=baseline, candidate=baseline, weights=np.array([.2, .4, .4]))
        stats = result.report["source_sensitivity"]
        self.assertFalse(stats["within_excluded_area_reporting_budget"])
        self.assertIsNone(stats["area_weighted_lower_tail_retention_unclipped"])
        self.assertAlmostEqual(stats["conditional_area_weighted_lower_tail_retention_unclipped"], 1)
        self.assertAlmostEqual(stats["excluded_source_area_fraction"], .2)
        json.dumps(result.report, allow_nan=False)

    def test_tolerance_grid_is_stable_when_all_sources_are_resolved(self) -> None:
        for tolerance in (1e-10, 1e-8, 1e-6):
            result = self.evaluate(numerical_zero_relative_tolerance=tolerance)
            self.assertEqual(result.report["source_sensitivity"]["excluded_source_area_fraction"], 0)
            self.assertTrue(np.all(result.sensitivity_valid_mask))

    def test_rejects_invalid_shapes_sources_and_pure_common_mode_reference(self) -> None:
        for kwargs in (
            {"baseline": self.baseline[:63]},
            {"candidate": self.candidate[:, :-1]},
            {"weights": np.zeros(12)},
            {"weights": -self.weights},
            {"weights": np.ones(11)},
            {"baseline": np.ones((64, 12))},
            {"source_moment_am": 0},
            {"numerical_zero_relative_tolerance": -1},
            {"snr_db": []},
            {"snr_db": [np.nan]},
        ):
            with self.subTest(kwargs=tuple(kwargs)):
                with self.assertRaises(ValueError):
                    self.evaluate(**kwargs)


if __name__ == "__main__":
    unittest.main()
