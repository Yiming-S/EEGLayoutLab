from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np
import pytest
from types import SimpleNamespace
from scipy.sparse import csr_matrix
from compact_eeg.area_budget_study import union_area_cm2, fit_union_radius, center_combinations, nested_coarse_bank, AreaDomain, search_area_condition
from compact_eeg.packing_pilot import build_surface_edge_graph


def test_union_counts_overlap_only_once():
    assert union_area_cm2(([0, 1], [1, 2]), np.ones(4)) == 3


def test_radius_fits_union_not_sum_and_includes_tied_shells_together():
    distances = np.array([[0, 1, 2, 3], [3, 2, 1, 0]], float)
    radius, patches, actual = fit_union_radius(distances, np.ones(4), 3)
    assert radius == 0
    assert actual == 2
    assert set(np.concatenate(patches)) == {0, 3}
    radius, _, actual = fit_union_radius(distances, np.ones(4), 4)
    assert radius == 1 and actual == 4


def test_disconnected_vertices_never_counted_and_small_cap_unresolved():
    d = np.array([[0, 1, np.inf]])
    assert fit_union_radius(d, np.ones(3), .5) is None
    assert fit_union_radius(d, np.ones(3), 3)[2] == 2


@pytest.mark.parametrize("cap", [0, -1, np.nan, np.inf])
def test_invalid_caps(cap):
    with pytest.raises(ValueError):
        fit_union_radius([[0, 1]], [1, 1], cap)


def test_master_combinations_are_nested_and_unique():
    xyz = np.random.default_rng(1).normal(size=(30, 3))
    centers = np.arange(20)
    smaller = center_combinations(xyz, centers, 3, 4, 33)
    larger = center_combinations(xyz, centers, 3, 16, 33)
    assert smaller == larger[:4]
    assert len(larger) == len(set(larger)) == 16
    assert all(len(set(c)) == 3 for c in larger)


def test_coarse_subset_is_true_nested_bank():
    vertices = np.random.default_rng(4).normal(size=(160, 3))
    bank = np.arange(10, 150)
    coarse = nested_coarse_bank(vertices, bank, 70)
    assert len(coarse) == len(set(coarse)) == 70
    assert set(coarse) < set(np.arange(len(bank)))
    assert np.array_equal(coarse, nested_coarse_bank(vertices, bank, 70))


def test_roi_graph_paths_cannot_cross_forbidden_vertex():
    graph = csr_matrix(np.array([[0, 1, 0, 0], [1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0]], float))
    domain = AreaDomain(np.zeros((4, 3)), graph, np.arange(4), np.ones(4), np.array([1, 0, 1, 1], bool), np.array([0]))
    assert np.isinf(domain.distances[0, 2])
    patch = domain.patches([0], 4)
    assert patch["union_area_cm2"] == 1
    assert patch["cap_shortfall_cm2"] == 3


class MockMetrics:
    def __init__(self, count):
        self.quality = np.linspace(.15, .9, count)

    def make_state(self, indices, snr_db=20):
        ids = np.asarray(indices, int)
        return SimpleNamespace(indices=ids.copy(), field_relative=float(self.quality[ids].mean()))

    def sensitivity_tail(self, indices):
        return float(1.1 - self.quality[indices].mean())

    def score_exchanges(self, state, position, candidate_indices, include_sensitivity=False):
        fields, sensitivities = [], []
        for candidate in candidate_indices:
            selected = state.indices.copy()
            selected[position] = candidate
            fields.append(self.make_state(selected).field_relative)
            sensitivities.append(self.sensitivity_tail(selected))
        return SimpleNamespace(field_relative=np.asarray(fields), sensitivity_tail=np.asarray(sensitivities))


def small_domain():
    vertices = np.array([[column, row, 0.] for row in range(12) for column in range(12)]) * .01
    faces = []
    for row in range(11):
        for column in range(11):
            i = row * 12 + column
            faces.extend([(i, i + 1, i + 13), (i, i + 13, i + 12)])
    adjacency = build_surface_edge_graph(vertices, np.asarray(faces)).adjacency
    return AreaDomain(vertices, adjacency, np.arange(144), np.ones(144), np.ones(144, bool), np.array([0, 11, 132, 143]))


def test_layout_search_inherits_incumbents_and_rejects_bad_warm_starts():
    domain, engine = small_domain(), MockMetrics(144)
    arguments = dict(domain=domain, engine=engine, region_count=2, cap_cm2=144,
        allowed_bank_rows=np.arange(144), master_combinations=((0, 143), (11, 132)),
        center_limit=1, seed=13, spacing_m=.005, geometry_restarts=1, sweeps=1, proposals=4)
    first = search_area_condition(**arguments)
    assert first["status"] == "completed_best_found"
    warm = [f["final"] for f in first["finalists"]]
    second = search_area_condition(**{**arguments, "center_limit": 2, "warm_starts": warm + [{}]})
    assert second["warm_validation"][-1]["accepted"] is False
    for old, new in zip(first["finalists"], second["finalists"]):
        assert new["final_score"] >= old["final_score"] - 1e-12
        assert new["final"]["geometry"]["actual_region_counts"] == [32, 32]
        assert len(set(new["final"]["candidate_bank_indices"])) == 64
        assert all(move["after"] > move["before"] for move in new["trace"])
    assert second["global_optimum_certified"] is False


def test_area_too_small_records_unresolved_not_infeasible():
    domain = small_domain()
    result = search_area_condition(domain, MockMetrics(144), region_count=2, cap_cm2=5,
        allowed_bank_rows=np.arange(144), master_combinations=((0, 143),), center_limit=1,
        seed=13, spacing_m=.005, geometry_restarts=1, sweeps=0, proposals=4)
    assert result["status"] == "no_complete_layout_constructed"
    assert result["finalists"] == []
    assert result["infeasibility_certified"] is False


def test_strict_region_mode_stops_radius_before_disks_merge():
    domain = small_domain()
    result = search_area_condition(domain, MockMetrics(144), region_count=2, cap_cm2=144,
        allowed_bank_rows=np.arange(144), master_combinations=((0, 143),), center_limit=1,
        seed=13, spacing_m=.005, geometry_restarts=1, sweeps=0, proposals=4,
        require_disconnected_regions=True)
    assert result["status"] == "completed_best_found"
    for item in result["finalists"]:
        geometry = item["final"]["geometry"]
        assert geometry["union_connected_component_count"] == 2
        assert geometry["union_area_cm2"] < 144
        assert geometry["radius_limited_by_separation"] is True
        assert geometry["overlap_counted_once_cm2"] == 0


def test_strict_patch_budget_increase_does_not_remove_smaller_patch():
    domain = small_domain()
    small = domain.patches((0, 143), 80, require_disconnected_regions=True)
    large = domain.patches((0, 143), 144, require_disconnected_regions=True)
    assert large["union_area_cm2"] >= small["union_area_cm2"]
    for a, b in zip(small["patches"], large["patches"]):
        assert set(a) <= set(b)
