from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compact_eeg.multiregion_search import search_condition
from compact_eeg.packing_pilot import GraphDistanceCache, build_surface_edge_graph


class MockMetrics:
    """Deterministic nonconstant field/sensitivity, no forward model involved."""

    def __init__(self, quality):
        self.quality = np.asarray(quality)
        self.point_count = len(self.quality)

    def make_state(self, indices, *, snr_db=20):
        selected = np.array(indices, dtype=int, copy=True)
        score = float(self.quality[selected].mean())
        return SimpleNamespace(indices=selected, field_relative=score,
            field_absolute=.9 * score, snr_db=snr_db)

    def sensitivity_tail(self, indices):
        return float(1.05 - self.quality[indices].mean())

    def apply_exchange(self, state, position, candidate_index):
        selected = state.indices.copy()
        selected[position] = candidate_index
        return self.make_state(selected)

    def score_exchanges(self, state, position, candidate_indices, *, include_sensitivity=False):
        fields, sensitivities = [], []
        for candidate in candidate_indices:
            trial = self.apply_exchange(state, position, candidate)
            fields.append(trial.field_relative)
            sensitivities.append(self.sensitivity_tail(trial.indices))
        return SimpleNamespace(candidate_indices=np.asarray(candidate_indices),
            field_relative=np.array(fields), sensitivity_tail=np.array(sensitivities))


def grid_fixture():
    vertices = np.array([[column, row, 0.] for row in range(12) for column in range(12)]) * .01
    triangles = []
    for row in range(11):
        for column in range(11):
            i = row * 12 + column
            triangles.extend([(i, i + 1, i + 13), (i, i + 13, i + 12)])
    adjacency = build_surface_edge_graph(vertices, np.asarray(triangles)).adjacency
    return vertices, adjacency


class MultiregionSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vertices, cls.adjacency = grid_fixture()

    def arguments(self, region_count=2, **overrides):
        bank = np.arange(len(self.vertices))
        result = dict(vertices_m=self.vertices, adjacency=self.adjacency,
            distance_cache=GraphDistanceCache(self.adjacency, max_entries=150),
            candidate_vertex_indices=bank, roi_masks={"all": np.ones(len(bank), dtype=bool)},
            center_shortlist_by_roi={"all": [0, 5, 11, 60, 71, 132, 137, 143]},
            region_roi_ids=["all"] * region_count, radius_m=.3, spacing_m=.005,
            engine=MockMetrics(.15 + .8 * bank / (len(bank) - 1)),
            search_config={"center_combinations_per_condition": 2,
                "geometry_restarts_per_center_combination": 2,
                "retained_starts_per_objective": 1,
                "coordinate_sweeps": 1, "candidate_proposals_per_electrode": 4,
                "center_exchange_rounds": 0, "center_proposals_per_region": 2},
            seed=934)
        result.update(overrides)
        return result

    def assert_snapshot_valid(self, snapshot, arguments):
        chosen = np.asarray(snapshot["electrode_vertex_indices"])
        labels = np.asarray(snapshot["region_indices"])
        self.assertEqual(len(np.unique(chosen)), 64)
        np.testing.assert_array_equal(arguments["candidate_vertex_indices"][snapshot["indices"]], chosen)
        np.testing.assert_array_equal(self.vertices[chosen], snapshot["xyz_m"])
        self.assertEqual(sum(snapshot["geometry_validation"]["actual_region_counts"]), 64)
        pairwise = np.linalg.norm(self.vertices[chosen, None] - self.vertices[chosen][None], axis=-1)
        self.assertGreaterEqual(pairwise[np.triu_indices(64, 1)].min() + 1e-12, arguments["spacing_m"])
        for region, center in enumerate(snapshot["centers"]):
            mask = arguments["roi_masks"][snapshot["region_roi_ids"][region]]
            self.assertTrue(np.all(mask[chosen[labels == region]]))
            self.assertLessEqual(arguments["distance_cache"].get(center)[chosen[labels == region]].max(), arguments["radius_m"] + 1e-12)

    def test_all_fixed64_allocations_and_overlapping_patches(self):
        for count, allocation in [(1, [64]), (2, [32,32]), (3,[22,21,21]),
                                  (4,[16]*4), (6,[11,11,11,11,10,10])]:
            with self.subTest(regions=count):
                arguments = self.arguments(count)
                arguments["search_config"].update(coordinate_sweeps=0, center_combinations_per_condition=1)
                result = search_condition(**arguments)
                self.assertEqual(result["status"], "completed_best_found")
                self.assertEqual(result["allocation"], allocation)
                self.assertTrue(result["diagnostics"]["candidate_patch_overlap_allowed"])
                for outcome in result["objective_results"].values():
                    self.assert_snapshot_valid(outcome["final"], arguments)

    def test_seed_reproducibility_json_and_strict_objective_improvement(self):
        result = search_condition(**self.arguments())
        repeated = search_condition(**self.arguments())
        self.assertEqual(json.dumps(result, allow_nan=False), json.dumps(repeated, allow_nan=False))
        for objective, outcome in result["objective_results"].items():
            self.assertGreaterEqual(outcome["final"]["objective_score"], outcome["initial"]["objective_score"])
            previous = outcome["initial"]["objective_score"]
            for move in outcome["trace"]:
                self.assertAlmostEqual(move["objective_before"], previous)
                self.assertGreater(move["objective_after"], previous)
                previous = move["objective_after"]
            self.assertAlmostEqual(previous, outcome["final"]["objective_score"])
            if objective == "min_field_sensitivity_20db":
                self.assertEqual(outcome["final"]["objective_score"], min(outcome["final"]["field20"], outcome["final"]["sensitivity_tail"]))
        self.assertGreater(result["objective_results"]["field_20db"]["accepted_moves"], 0)
        self.assertFalse(result["localization_optimized"])
        self.assertFalse(result["formal_ar"])
        self.assertFalse(result["global_optimum_certified"])

    def test_explicit_trial_and_coordinate_budgets(self):
        result = search_condition(**self.arguments())
        used = result["budget"]["used"]
        self.assertEqual(used["geometry_trials"], 4)
        self.assertEqual(len(result["geometry_attempts"]), 4)
        self.assertEqual(used["coordinate_positions_visited"], 2 * 64)
        self.assertLessEqual(used["coordinate_candidates_scored"], 2 * 64 * 4)

    def test_bank_rows_are_not_surface_vertex_ids(self):
        arguments = self.arguments()
        bank = np.arange(len(self.vertices))[::-1]
        arguments.update(candidate_vertex_indices=bank, engine=MockMetrics(.15 + .8 * bank / (len(bank)-1)))
        result = search_condition(**arguments)
        for outcome in result["objective_results"].values():
            self.assert_snapshot_valid(outcome["final"], arguments)
            expected = arguments["engine"].make_state(outcome["final"]["indices"])
            self.assertEqual(expected.field_relative, outcome["final"]["field20"])

    def test_warm_start_revalidated_rescored_and_not_lost(self):
        initial = search_condition(**self.arguments(radius_m=.25))
        warm = [deepcopy(value["final"]) for value in initial["objective_results"].values()]
        for item in warm:
            item.update(field20=-100, sensitivity_tail=-100, objective_score=-100)
        arguments = self.arguments(radius_m=.3, warm_starts=warm)
        arguments["search_config"].update(coordinate_sweeps=0)
        result = search_condition(**arguments)
        self.assertTrue(all(item["accepted"] for item in result["warm_start_validation"]))
        for objective, outcome in result["objective_results"].items():
            self.assertGreaterEqual(outcome["final"]["objective_score"] + 1e-12, initial["objective_results"][objective]["final"]["objective_score"])
            self.assertGreater(outcome["best_validated_warm_start_score"], 0)

    def test_invalid_warm_starts_do_not_bypass_geometry(self):
        initial = search_condition(**self.arguments())
        duplicate = deepcopy(initial["objective_results"]["field_20db"]["final"])
        duplicate["electrode_vertex_indices"][1] = duplicate["electrode_vertex_indices"][0]
        wrong_roi = deepcopy(duplicate)
        wrong_roi["region_roi_ids"] = ["other", "all"]
        result = search_condition(**self.arguments(warm_starts=[duplicate, wrong_roi]))
        self.assertEqual([item["accepted"] for item in result["warm_start_validation"]], [False, False])
        tiny = search_condition(**self.arguments(radius_m=.011, warm_starts=[initial["objective_results"]["field_20db"]["final"]]))
        self.assertFalse(tiny["warm_start_validation"][0]["accepted"])

    def test_incomplete_geometry_records_partial_counts_not_infeasibility(self):
        result = search_condition(**self.arguments(radius_m=.011))
        self.assertEqual(result["status"], "no_complete_layout_constructed")
        self.assertFalse(result["infeasibility_certified"])
        self.assertEqual(result["budget"]["used"].get("direct_field_evaluations", 0), 0)
        self.assertEqual(len(result["geometry_attempts"]), 4)
        for trial in result["geometry_attempts"]:
            self.assertLess(sum(trial["partial_counts"]), 64)
            self.assertGreater(sum(trial["partial_counts"]), 0)
            self.assertEqual(sum(trial["partial_counts"]), trial["selected_count"])
        for outcome in result["objective_results"].values():
            self.assertIsNone(outcome["final"])

    def test_empty_shortlist_returns_bounded_failure(self):
        result = search_condition(**self.arguments(center_shortlist_by_roi={"all": []}))
        self.assertEqual(result["status"], "no_complete_layout_constructed")
        self.assertEqual(result["geometry_attempts"], [])
        self.assertEqual(result["diagnostics"]["center_combinations_returned"], 0)

    def test_center_exchange_extra_work_and_chronological_trace(self):
        arguments = self.arguments()
        arguments["search_config"].update(coordinate_sweeps=0, center_exchange_rounds=1)
        result = search_condition(**arguments)
        used = result["budget"]["used"]
        self.assertGreater(used["center_region_coordinate_sweeps"], 0)
        self.assertLessEqual(used["center_proposals_evaluated"], 2 * 2 * 2)
        self.assertEqual(used["coordinate_positions_visited"], 32 * used["center_region_coordinate_sweeps"])
        center_moves = 0
        for outcome in result["objective_results"].values():
            previous = outcome["initial"]["objective_score"]
            for move in outcome["trace"]:
                self.assertAlmostEqual(move["objective_before"], previous)
                self.assertGreaterEqual(move["objective_after"], previous)
                previous = move["objective_after"]
                center_moves += move["kind"] == "region_center_exchange"
            self.assertAlmostEqual(previous, outcome["final"]["objective_score"])
            self.assert_snapshot_valid(outcome["final"], arguments)
        self.assertGreater(center_moves, 0)

    def test_sensitivity_unavailable_does_not_become_zero_or_pass(self):
        class NoSensitivity(MockMetrics):
            def sensitivity_tail(self, indices):
                return None
        arguments = self.arguments()
        arguments["engine"] = NoSensitivity(arguments["engine"].quality)
        arguments["search_config"]["coordinate_sweeps"] = 0
        result = search_condition(**arguments)
        self.assertIsNone(result["objective_results"]["field_20db"]["final"]["sensitivity_tail"])
        self.assertEqual(result["objective_results"]["min_field_sensitivity_20db"]["status"], "objective_unavailable")
        json.dumps(result, allow_nan=False)

    def test_disconnected_roi_does_not_leak_through_full_surface_paths(self):
        mask = np.ones(len(self.vertices), dtype=bool)
        mask[72:84] = False  # Remove one complete row, disconnecting allowed skin.
        arguments = self.arguments(1, roi_masks={"all": mask},
            center_shortlist_by_roi={"all": [0, 11, 60, 71]})
        arguments["search_config"].update(center_combinations_per_condition=1)
        result = search_condition(**arguments)
        for outcome in result["objective_results"].values():
            chosen = np.asarray(outcome["final"]["electrode_vertex_indices"])
            self.assertTrue(np.all(chosen < 72))
            self.assert_snapshot_valid(outcome["final"], arguments)

    def test_center_must_contain_existing_region_points_before_refinement(self):
        arguments = self.arguments(1, radius_m=.12)
        arguments["search_config"].update(center_combinations_per_condition=1,
            coordinate_sweeps=0, center_exchange_rounds=1, center_proposals_per_region=4)
        result = search_condition(**arguments)
        self.assertEqual(result["status"], "completed_best_found")
        self.assertGreater(result["budget"]["used"]["center_membership_rejections"], 0)
        for outcome in result["objective_results"].values():
            for attempt in outcome["center_attempts"]:
                if attempt["status"] == "existing_points_outside_new_patch":
                    self.assertFalse(attempt["accepted"])
            self.assert_snapshot_valid(outcome["final"], arguments)

    def test_real_cached_metric_engine_matches_final_direct_lmmse(self):
        from compact_eeg.layout_search_metrics import LayoutSearchMetrics
        from compact_eeg.prototype_metrics import evaluate_prototype_metrics
        rng = np.random.default_rng(521)
        bank = rng.normal(size=(len(self.vertices), 80))
        reference = rng.normal(size=(64, 80))
        weights = rng.uniform(.01, 1, 80)
        arguments = self.arguments(engine=LayoutSearchMetrics(bank, reference, weights))
        arguments["search_config"].update(center_combinations_per_condition=1,
            geometry_restarts_per_center_combination=1)
        result = search_condition(**arguments)
        for outcome in result["objective_results"].values():
            final = outcome["final"]
            direct = evaluate_prototype_metrics(reference, bank[final["indices"]], weights,
                source_moment_am=1e-8, numerical_zero_relative_tolerance=1e-8).report
            self.assertAlmostEqual(final["field20"], direct["conditions"][2]["field_retention_unclipped"], places=10)
            self.assertAlmostEqual(final["field20_absolute"], direct["conditions"][2]["candidate_field_explained_energy"], places=10)
            self.assertAlmostEqual(final["sensitivity_tail"], direct["source_sensitivity"]["area_weighted_lower_tail_retention_unclipped"], places=10)

    def test_input_contract_rejects_invalid_mapping_mask_budget(self):
        for modification in [dict(candidate_vertex_indices=np.arange(64)),
                             dict(roi_masks={"all": np.ones(len(self.vertices))}),
                             dict(radius_m=0), dict(seed=-1),
                             dict(region_roi_ids=["all"] * 5),
                             dict(search_config={"candidate_proposals_per_electrode": 0})]:
            with self.subTest(modification=list(modification)):
                with self.assertRaises(ValueError):
                    search_condition(**self.arguments(**modification))


if __name__ == "__main__":
    unittest.main()
