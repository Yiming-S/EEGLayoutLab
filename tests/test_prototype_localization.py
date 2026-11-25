from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from compact_eeg.inverse_pilot import fixed_normal_scan
from compact_eeg.metrics import helmert_contrast
from compact_eeg.prototype_localization import evaluate_grid_localization


class PrototypeLocalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        rng = np.random.default_rng(8129)
        self.dictionary = rng.normal(size=(64, 5))
        self.source_indices = np.array([0, 2, 4])
        self.generation = self.dictionary[:, self.source_indices].copy()
        self.xyz = np.array([[0., 0., 0.], [10., 0., 0.], [0., 10., 0.], [0., 0., 10.], [10., 10., 10.]])
        self.generation_xyz = self.xyz[self.source_indices] + [1., 0., 0.]

    def evaluate(self, dictionary=None, generation=None, xyz=None, generation_xyz=None, **kwargs):
        options = {
            "source_moment_am": 1e-8,
            "physical_electrode_noise_std_v": 1e-14,
            "noise_seed": 7103,
            "layout_id": "reference64",
            "noise_repetitions": 16,
        }
        options.update(kwargs)
        return evaluate_grid_localization(
            self.dictionary if dictionary is None else dictionary,
            self.generation if generation is None else generation,
            self.xyz if xyz is None else xyz,
            self.generation_xyz if generation_xyz is None else generation_xyz,
            **options,
        )

    def test_known_dictionary_decisions_and_mm_errors(self) -> None:
        result = self.evaluate()
        self.assertEqual(result.errors_mm.shape, (3, 16))
        self.assertEqual(result.standard_normal_noise.shape, (63, 3, 16))
        np.testing.assert_array_equal(result.estimated_dictionary_indices, np.repeat(self.source_indices[:, None], 16, axis=1))
        np.testing.assert_allclose(result.errors_mm, 1.)
        self.assertEqual(result.report["median_error_mm"], 1.)
        self.assertEqual(result.report["p90_error_mm"], 1.)
        self.assertEqual(result.report["p95_error_mm"], 1.)
        self.assertAlmostEqual(result.report["source_lower10_utility_dmax50mm"], .98)
        self.assertEqual(result.report["scored_trial_count"], 48)
        self.assertFalse(result.report["formal_v2_performance_eligible"])
        self.assertFalse(result.report["continuous_surface_refinement_performed"])
        json.dumps(result.report, allow_nan=False)

    def test_same_layout_seed_is_exactly_reproducible(self) -> None:
        first = self.evaluate()
        second = self.evaluate()
        np.testing.assert_array_equal(first.standard_normal_noise, second.standard_normal_noise)
        np.testing.assert_array_equal(first.errors_mm, second.errors_mm)
        self.assertEqual(first.report, second.report)

    def test_different_layout_ids_do_not_reuse_noise(self) -> None:
        reference = self.evaluate(layout_id="reference64")
        candidate = self.evaluate(layout_id="ears32_32")
        self.assertNotEqual(reference.report["layout_noise_stream_sha256"], candidate.report["layout_noise_stream_sha256"])
        self.assertFalse(np.array_equal(reference.standard_normal_noise, candidate.standard_normal_noise))
        # Evaluation order never changes a previously identified stream.
        repeated = self.evaluate(layout_id="reference64")
        np.testing.assert_array_equal(reference.standard_normal_noise, repeated.standard_normal_noise)

    def test_observations_reuse_the_existing_ml_scanner_exactly(self) -> None:
        sigma = 2e-8
        result = self.evaluate(physical_electrode_noise_std_v=sigma)
        c = helmert_contrast(64)
        hd = c @ (self.dictionary - self.dictionary.mean(axis=0, keepdims=True))
        hg = c @ (self.generation - self.generation.mean(axis=0, keepdims=True))
        observations = (hg[:, :, None] * 1e-8 + sigma * result.standard_normal_noise).reshape(63, -1)
        expected = fixed_normal_scan(hd, observations, sigma ** 2 * np.eye(63)).reshape(3, 16)
        np.testing.assert_array_equal(result.estimated_dictionary_indices, expected)

    def test_noise_scale_is_supplied_not_recalibrated_to_layout(self) -> None:
        sigma = 3e-8
        first = self.evaluate(physical_electrode_noise_std_v=sigma)
        scaled = self.evaluate(dictionary=100 * self.dictionary, generation=100 * self.generation, physical_electrode_noise_std_v=sigma)
        self.assertEqual(first.report["physical_electrode_noise_std_v"], scaled.report["physical_electrode_noise_std_v"])
        self.assertEqual(scaled.report["physical_electrode_noise_variance_v2"], sigma ** 2)

    def test_signed_moments_and_common_reference_shifts(self) -> None:
        generation = self.generation * np.array([1., -2., .5])
        result = self.evaluate(dictionary=self.dictionary + np.arange(5)[None, :], generation=generation + np.array([3., 2., -1.])[None, :])
        np.testing.assert_array_equal(result.estimated_dictionary_indices, np.repeat(self.source_indices[:, None], 16, axis=1))

    def test_on_dictionary_generation_requires_explicit_control_mode(self) -> None:
        xyz = self.xyz[self.source_indices]
        with self.assertRaisesRegex(ValueError, "fall on the inverse dictionary"):
            self.evaluate(generation_xyz=xyz)
        control = self.evaluate(generation_xyz=xyz, require_off_dictionary=False)
        self.assertEqual(control.report["on_dictionary_source_count"], 3)
        self.assertFalse(control.report["off_dictionary_required"])
        np.testing.assert_allclose(control.errors_mm, 0)

    def test_supplied_source_weights_are_normalized_and_reported(self) -> None:
        result = self.evaluate(generation_source_weights=np.array([1., 2., 7.]))
        np.testing.assert_allclose(result.generation_source_weights, [.1, .2, .7])
        self.assertEqual(result.report["source_tail_weights"], "normalized_caller_supplied_weights")
        self.assertIn("unweighted", result.report["error_quantiles"])

    def test_rejects_invalid_inputs(self) -> None:
        invalid = (
            {"dictionary": self.dictionary[:63]},
            {"generation": self.generation[:63]},
            {"xyz": self.xyz[:-1]},
            {"generation_xyz": np.full((3, 3), np.nan)},
            {"dictionary": np.ones_like(self.dictionary)},
            {"source_moment_am": 0},
            {"physical_electrode_noise_std_v": 0},
            {"physical_electrode_noise_std_v": np.inf},
            {"noise_repetitions": 0},
            {"noise_repetitions": True},
            {"noise_seed": -1},
            {"layout_id": ""},
            {"generation_source_weights": np.zeros(3)},
            {"generation_source_weights": np.ones(2)},
            {"off_dictionary_distance_tolerance_mm": -1},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=tuple(kwargs)):
                with self.assertRaises(ValueError):
                    self.evaluate(**kwargs)

    def test_variable_electrode_count_localization_matches_helmert_k_scanner(self) -> None:
        sigma = 2e-8
        k = 16
        dict_k = self.dictionary[:k]
        gen_k = self.generation[:k]
        result_iid = self.evaluate(
            dictionary=dict_k, generation=gen_k, physical_electrode_noise_std_v=sigma,
            layout_id="compact16", expected_electrodes=k,
        )
        self.assertEqual(result_iid.standard_normal_noise.shape, (k - 1, 3, 16))
        ck = helmert_contrast(k)
        hd = ck @ (dict_k - dict_k.mean(axis=0, keepdims=True))
        hg = ck @ (gen_k - gen_k.mean(axis=0, keepdims=True))
        obs = (hg[:, :, None] * 1e-8 + sigma * result_iid.standard_normal_noise).reshape(k - 1, -1)
        expected = fixed_normal_scan(hd, obs, sigma ** 2 * np.eye(k - 1)).reshape(3, 16)
        np.testing.assert_array_equal(result_iid.estimated_dictionary_indices, expected)

        coords = np.linspace(0.0, 45.0, k)[:, None]
        d2 = (coords - coords.T) ** 2
        cov_k = (sigma ** 2) * (0.5 * np.eye(k) + 0.5 * np.exp(-d2 / (2.0 * 20.0 ** 2)))
        result_corr = self.evaluate(
            dictionary=dict_k, generation=gen_k, physical_electrode_noise_std_v=sigma,
            physical_noise_covariance_v2=cov_k, layout_id="compact16_corr", expected_electrodes=k,
        )
        self.assertEqual(result_corr.errors_mm.shape, (3, 16))
        self.assertTrue(np.all(np.isfinite(result_corr.errors_mm)))


if __name__ == "__main__":
    unittest.main()
