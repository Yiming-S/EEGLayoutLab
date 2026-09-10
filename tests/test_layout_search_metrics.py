from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compact_eeg.layout_search_metrics import LayoutSearchMetrics
from compact_eeg.prototype_metrics import evaluate_prototype_metrics


class LayoutSearchMetricsTests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(98145)
        source_patterns = self.rng.normal(size=(14, 96))
        spatial = self.rng.normal(size=(100, 14))
        self.bank = spatial @ source_patterns + .03 * self.rng.normal(size=(100, 96))
        self.reference = self.bank[:64].copy()
        self.weights = self.rng.uniform(.1, 3, 96)
        self.kwargs = dict(source_moment_am=1e-8, numerical_zero_relative_tolerance=1e-8)
        self.engine = LayoutSearchMetrics(self.bank, self.reference, self.weights, **self.kwargs, covariance_block_size=19)
        self.indices = self.rng.choice(100, 64, replace=False)

    def golden(self, indices, *, bank=None, reference=None, weights=None):
        return evaluate_prototype_metrics(
            self.reference if reference is None else reference,
            (self.bank if bank is None else bank)[indices],
            self.weights if weights is None else weights, **self.kwargs,
        ).report

    def assert_conditions(self, actual, expected, atol=1e-10):
        self.assertEqual(len(actual["conditions"]), len(expected["conditions"]))
        for left, right in zip(actual["conditions"], expected["conditions"]):
            for key in ("candidate_field_explained_energy", "reference_field_explained_energy", "field_retention_unclipped", "candidate_noise_whitened_area_weighted_effective_rank", "reference_noise_whitened_area_weighted_effective_rank"):
                np.testing.assert_allclose(left[key], right[key], rtol=0, atol=atol, err_msg=key)
            np.testing.assert_allclose(left["shared_physical_electrode_noise_variance_v2"], right["shared_physical_electrode_noise_variance_v2"], rtol=1e-12, atol=0)
        np.testing.assert_allclose(actual["source_sensitivity"]["area_weighted_lower_tail_retention_unclipped"], expected["source_sensitivity"]["area_weighted_lower_tail_retention_unclipped"], rtol=0, atol=atol)

    def test_random_layouts_match_original_all_three_snrs(self):
        for _ in range(4):
            indices = self.rng.choice(100, 64, replace=False)
            self.assert_conditions(self.engine.evaluate(indices), self.golden(indices))

    def test_baseline_identity_is_relative_not_perfect_absolute(self):
        actual = self.engine.evaluate(np.arange(64))
        self.assert_conditions(actual, self.golden(np.arange(64)))
        for condition in actual["conditions"]:
            self.assertAlmostEqual(condition["field_retention_unclipped"], 1., places=10)
            self.assertLess(condition["candidate_field_explained_energy"], 1.)

    def test_every_eligible_exchange_matches_golden_and_retains_order(self):
        position = 13
        candidates = np.arange(99, -1, -1)
        for snr in (0, 10, 20):
            state = self.engine.make_state(self.indices, snr_db=snr)
            result = self.engine.score_exchanges(state, position, candidates, chunk_size=7, include_sensitivity=True)
            self.assertEqual(result.direct_fallback_count, 0)
            expected_candidates = candidates[~np.isin(candidates, np.delete(self.indices, position))]
            np.testing.assert_array_equal(result.candidate_indices, expected_candidates)
            for i, candidate in enumerate(result.candidate_indices):
                swapped = self.indices.copy()
                swapped[position] = candidate
                expected = self.golden(swapped)
                condition = expected["conditions"][(0, 10, 20).index(snr)]
                self.assertAlmostEqual(result.field_absolute[i], condition["candidate_field_explained_energy"], places=10)
                self.assertAlmostEqual(result.field_relative[i], condition["field_retention_unclipped"], places=10)
                self.assertAlmostEqual(result.sensitivity_tail[i], expected["source_sensitivity"]["area_weighted_lower_tail_retention_unclipped"], places=11)

    def test_no_change_candidate_exact_and_chunk_size_independent(self):
        state = self.engine.make_state(self.indices)
        a = self.engine.score_exchanges(state, 0, chunk_size=1)
        b = self.engine.score_exchanges(state, 0, chunk_size=100)
        np.testing.assert_array_equal(a.candidate_indices, b.candidate_indices)
        np.testing.assert_allclose(a.field_relative, b.field_relative, atol=1e-12, rtol=0)
        same = np.flatnonzero(a.candidate_indices == self.indices[0])[0]
        self.assertAlmostEqual(a.field_relative[same], state.field_relative, places=11)
        self.assertIsNone(a.sensitivity_tail)

    def test_accepted_exchange_rebuilds_and_does_not_mutate_old_state(self):
        state = self.engine.make_state(self.indices)
        original = state.indices.copy()
        candidate = int(next(i for i in range(100) if i not in self.indices))
        changed = self.engine.apply_exchange(state, 7, candidate)
        np.testing.assert_array_equal(state.indices, original)
        self.assertEqual(changed.indices[7], candidate)
        self.assertAlmostEqual(changed.field_relative, self.golden(changed.indices)["conditions"][2]["field_retention_unclipped"], places=10)
        with self.assertRaises(ValueError):
            state.indices[0] = 99

    def test_batch_sensitivity_exact_weighted_tail(self):
        layouts = np.vstack([self.indices, np.arange(64), np.arange(36, 100)])
        values = self.engine.batch_sensitivity_tail(layouts, chunk_size=2)
        expected = [self.golden(row)["source_sensitivity"]["area_weighted_lower_tail_retention_unclipped"] for row in layouts]
        np.testing.assert_allclose(values, expected, rtol=0, atol=1e-12)

    def test_common_reference_shift_and_channel_permutation_invariant(self):
        shift = self.rng.normal(size=96) * 300
        engine = LayoutSearchMetrics(self.bank + shift, self.reference + 2 * shift, self.weights, **self.kwargs)
        self.assert_conditions(engine.evaluate(self.indices[::-1]), self.golden(self.indices), atol=2e-10)

    def test_amplitude_scale_preserves_ratios_and_scales_shared_noise(self):
        scale = 7.5
        engine = LayoutSearchMetrics(self.bank * scale, self.reference * scale, self.weights, **self.kwargs)
        a, b = engine.evaluate(self.indices), self.engine.evaluate(self.indices)
        for left, right in zip(a["conditions"], b["conditions"]):
            self.assertAlmostEqual(left["field_retention_unclipped"], right["field_retention_unclipped"], places=10)
            np.testing.assert_allclose(left["shared_physical_electrode_noise_variance_v2"], right["shared_physical_electrode_noise_variance_v2"] * scale**2, rtol=1e-12, atol=0)

    def test_rank_zero_cluster_and_unclipped_better_candidate(self):
        bank = np.vstack([self.reference, np.zeros_like(self.reference), self.reference * 2])
        engine = LayoutSearchMetrics(bank, self.reference, self.weights, **self.kwargs)
        zero = engine.evaluate(np.arange(64, 128))
        self.assert_conditions(zero, self.golden(np.arange(64, 128), bank=bank))
        better = engine.evaluate(np.arange(128, 192))
        self.assertGreater(better["conditions"][2]["field_retention_unclipped"], 1.)
        self.assertGreater(better["source_sensitivity"]["area_weighted_lower_tail_retention_unclipped"], 1.)

    def test_excluded_source_area_remains_unavailable(self):
        reference = self.reference.copy()
        reference[:, 0] = 0
        engine = LayoutSearchMetrics(self.bank, reference, self.weights, **self.kwargs)
        self.assertIsNone(engine.sensitivity_tail(self.indices))
        result = engine.score_exchanges(engine.make_state(self.indices), 4, include_sensitivity=True)
        self.assertTrue(np.all(np.isnan(result.sensitivity_tail)))
        self.assertTrue(np.isnan(engine.batch_sensitivity_tail(self.indices[None, :])[0]))
        self.assertGreater(engine.evaluate(self.indices)["source_sensitivity"]["excluded_source_area_fraction"], .001)

    def test_invalid_indices_and_foreign_state_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.make_state(np.zeros(64, dtype=int))
        with self.assertRaises(ValueError):
            self.engine.make_state(np.arange(63))
        state = self.engine.make_state(self.indices)
        with self.assertRaises(ValueError):
            self.engine.apply_exchange(state, 0, int(self.indices[1]))
        with self.assertRaises(ValueError):
            self.engine.score_exchanges(state, 0, [1, 1])
        with self.assertRaises(ValueError):
            self.engine.score_exchanges(state, True)
        other = LayoutSearchMetrics(self.bank, self.reference, self.weights, **self.kwargs)
        with self.assertRaises(ValueError):
            other.score_exchanges(state, 0)

    def test_cache_does_not_alias_mutable_inputs(self):
        before = self.engine.make_state(self.indices).field_relative
        self.bank[:] = 0
        self.reference[:] = 0
        self.weights[:] = 0
        self.assertEqual(self.engine.make_state(self.indices).field_relative, before)

    def test_empty_candidates_return_empty_result(self):
        result = self.engine.score_exchanges(self.engine.make_state(self.indices), 0, np.array([], dtype=int), include_sensitivity=True)
        self.assertEqual(result.candidate_indices.shape, (0,))
        self.assertEqual(result.sensitivity_tail.shape, (0,))
        self.assertEqual(len(self.engine.score_exchanges(self.engine.make_state(self.indices), 0, []).candidate_indices), 0)


if __name__ == "__main__":
    unittest.main()
