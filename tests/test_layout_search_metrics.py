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

    def test_best_pruned_exchange_matches_brute_force_under_iid_and_spatial_noise(self):
        xyz_cand = self.rng.normal(size=(100, 3)) * 35.0
        xyz_ref = xyz_cand[:64].copy()
        engines = [
            self.engine,
            self.engine.with_noise_kernel((xyz_cand, xyz_ref, 0.5, 20.0)),
        ]
        for eng in engines:
            for trial in range(10):
                indices = self.rng.choice(100, 64, replace=False)
                state = eng.make_state(indices, snr_db=20)
                curr_sens = eng.sensitivity_tail(indices)
                curr_obj = min(state.field_relative, curr_sens)
                cert = eng.tail_dual_certificate(indices)
                self.assertAlmostEqual(cert[0], curr_sens, places=13)
                hint = (cert[1], cert[2])
                candidates = self.rng.permutation(100)
                pos = int(trial % 64)
                brute = eng.score_exchanges(state, pos, candidates, include_sensitivity=True)
                objs = np.minimum(brute.field_relative, brute.sensitivity_tail)
                for floor, tol in ((curr_obj, 1e-9), (float(np.max(objs)) + 1e-4, 0.0), (-0.5, 0.0)):
                    pruned = eng.best_pruned_exchange(
                        state, pos, candidates, objective_floor=floor, tol=tol, dual_hint=hint, chunk_size=17)
                    valid = np.flatnonzero(np.isfinite(objs) & (objs > floor + tol))
                    if not len(valid):
                        self.assertIsNone(pruned.best_candidate)
                    else:
                        best_i = int(valid[int(np.argmax(objs[valid]))])
                        self.assertEqual(pruned.best_candidate, int(brute.candidate_indices[best_i]))
                        self.assertAlmostEqual(pruned.objective, float(objs[best_i]), places=12)
                        self.assertAlmostEqual(pruned.field_relative, float(brute.field_relative[best_i]), places=12)
                        self.assertAlmostEqual(pruned.sensitivity_tail, float(brute.sensitivity_tail[best_i]), places=12)

    def test_partial_state_and_pruned_addition_match_full_64_state(self):
        xyz_cand = self.rng.normal(size=(100, 3)) * 35.0
        eng = self.engine.with_noise_kernel((xyz_cand, xyz_cand[:64], 0.5, 15.0))
        subset_63 = self.indices[:63]
        p_state = eng.make_partial_state(subset_63, snr_db=20)
        pool = np.setdiff1d(np.arange(100), subset_63)
        add_scores = eng.score_additions(p_state, pool, chunk_size=11, include_sensitivity=True)
        np.testing.assert_array_equal(add_scores.candidate_indices, pool)
        for idx, cand in enumerate(pool[:12]):
            full = eng.make_state(np.append(subset_63, int(cand)), snr_db=20)
            self.assertAlmostEqual(add_scores.field_relative[idx], full.field_relative, places=11)
            self.assertAlmostEqual(add_scores.sensitivity_tail[idx], eng.sensitivity_tail(full.indices), places=12)
        objs = np.minimum(add_scores.field_relative, add_scores.sensitivity_tail)
        best_i = int(np.argmax(objs))
        pruned = eng.best_pruned_addition(p_state, pool, objective_floor=-1.0, tol=0.0)
        self.assertEqual(pruned.best_candidate, int(pool[best_i]))
        self.assertAlmostEqual(pruned.objective, float(objs[best_i]), places=12)
        # Smaller k subsets (e.g., k=10) are monotonic and reject invalid sizes.
        p10 = self.engine.make_partial_state(self.indices[:10], snr_db=20)
        self.assertLessEqual(p10.field_relative, self.engine.make_state(self.indices, snr_db=20).field_relative + 1e-12)
        with self.assertRaises(ValueError):
            self.engine.make_partial_state(self.indices[:1])
        with self.assertRaises(ValueError):
            self.engine.make_partial_state(self.indices)

    def test_helmert_information_retention_and_composite_pruning_exact(self):
        from compact_eeg.layout_search_metrics import combine_search_objective
        from compact_eeg.prototype_metrics import helmert_contrast
        xyz_cand = self.rng.normal(size=(100, 3)) * 35.0
        xyz_ref = xyz_cand[:64].copy()
        engines = [
            self.engine,
            self.engine.with_noise_kernel((xyz_cand, xyz_ref, 0.5, 20.0)),
        ]
        p64 = helmert_contrast(64)
        for eng in engines:
            self.assertAlmostEqual(eng.information_retention(np.arange(64), snr_db=20), 1.0, places=11)
            indices = self.rng.choice(100, 64, replace=False)
            state = eng.make_state(indices, snr_db=20)
            _, noise = eng._noise(20)
            ref_info = 0.5 * (np.linalg.slogdet(eng._cbb + noise * eng._reference_noise)[1] - np.linalg.slogdet(noise * eng._reference_noise)[1])
            c_cand = eng._covariance[np.ix_(indices, indices)]
            m_cand = noise * eng._noise_matrix(indices)
            cand_info = 0.5 * (np.linalg.slogdet(p64 @ (c_cand + m_cand) @ p64.T)[1] - np.linalg.slogdet(p64 @ m_cand @ p64.T)[1])
            expected_ratio = float(cand_info / ref_info)
            self.assertAlmostEqual(state.information_relative, expected_ratio, places=11)
            self.assertAlmostEqual(eng.information_retention(indices, snr_db=20), expected_ratio, places=11)
            candidates = self.rng.permutation(100)
            for pos in (0, 29, 63):
                ex = eng.score_exchanges(state, pos, candidates, chunk_size=13, include_sensitivity=True, include_information=True)
                for idx in (0, len(ex.candidate_indices) // 2, len(ex.candidate_indices) - 1):
                    swapped = indices.copy()
                    swapped[pos] = int(ex.candidate_indices[idx])
                    self.assertAlmostEqual(ex.information_relative[idx], eng.information_retention(swapped, snr_db=20), places=11)
                comp_objs = combine_search_objective(ex.field_relative, ex.sensitivity_tail, ex.information_relative, objective_mode="composite")
                cert = eng.tail_dual_certificate(indices)
                curr_comp = float(combine_search_objective(state.field_relative, cert[0], state.information_relative, objective_mode="composite"))
                for floor, tol in ((curr_comp, 1e-9), (float(np.max(comp_objs)) + 1e-4, 0.0), (-0.5, 0.0)):
                    pruned = eng.best_pruned_exchange(
                        state, pos, candidates, objective_floor=floor, tol=tol,
                        dual_hint=(cert[1], cert[2]), chunk_size=17, objective_mode="composite",
                    )
                    valid = np.flatnonzero(np.isfinite(comp_objs) & (comp_objs > floor + tol))
                    if not len(valid):
                        self.assertIsNone(pruned.best_candidate)
                    else:
                        best_i = int(valid[int(np.argmax(comp_objs[valid]))])
                        self.assertEqual(pruned.best_candidate, int(ex.candidate_indices[best_i]))
                        self.assertAlmostEqual(pruned.objective, float(comp_objs[best_i]), places=12)
                        self.assertAlmostEqual(pruned.information_relative, float(ex.information_relative[best_i]), places=12)
            p_state = eng.make_partial_state(indices[:63], snr_db=20)
            pool = np.setdiff1d(np.arange(100), indices[:63])
            add_ex = eng.score_additions(p_state, pool, include_sensitivity=True, include_information=True)
            add_comp = combine_search_objective(add_ex.field_relative, add_ex.sensitivity_tail, add_ex.information_relative, objective_mode="composite")
            best_add = int(np.argmax(add_comp))
            p_add = eng.best_pruned_addition(p_state, pool, objective_floor=-1.0, tol=0.0, objective_mode="composite")
            self.assertEqual(p_add.best_candidate, int(pool[best_add]))
            self.assertAlmostEqual(p_add.objective, float(add_comp[best_add]), places=12)


if __name__ == "__main__":
    unittest.main()
