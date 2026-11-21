from pathlib import Path
import json
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np
import pytest
from scipy.sparse import csr_matrix
from compact_eeg.local_radius_compute import (
    RadiusDomain, validate_request, request_rois, bounded_radius_search,
    select_radius_center_combinations,
)


@pytest.mark.parametrize("value", [
    {}, {"region_count": True, "radius_mm": 35, "mode": "low_hair"},
    {"region_count": 5, "radius_mm": 35, "mode": "low_hair"},
    {"region_count": 2, "radius_mm": 34, "mode": "low_hair"},
    {"region_count": 2, "radius_mm": 100, "mode": "low_hair"},
    {"region_count": 2, "radius_mm": float("nan"), "mode": "low_hair"},
    {"region_count": 2, "radius_mm": 35, "mode": "arbitrary"},
    {"region_count": 2, "radius_mm": 35, "mode": "preset", "mask_codes": ["PL"]},
    {"region_count": 2, "radius_mm": 35, "mode": "preset", "mask_codes": ["PL.sub", "PR"]},
    {"region_count": 2, "radius_mm": 35, "mode": "low_hair", "mask_codes": ["PL", "PR"]},
    {"region_count": 2, "radius_mm": 35, "mode": "low_hair", "command": "anything"},
])
def test_invalid_request_rejected_without_substitution(value):
    with pytest.raises(ValueError):
        validate_request(value)


def test_canonical_request_and_exact_masks():
    value = validate_request({"region_count": 2, "radius_mm": 35., "mode": "preset", "mask_codes": ["PL", "FM"]})
    assert value["radius_mm"] == 35
    assert request_rois(value) == ("left_near_ear_posterolateral_approx", "upper_forehead_midline_approx")
    assert validate_request({"region_count": 1, "radius_mm": 15, "mode": "whole_surface"})["mask_codes"] == []


@pytest.mark.parametrize("noise", [None, {"kind": "iid"}, {"kind": "spatial", "rho": .5, "length_mm": 20.},
    {"kind": "spatial", "rho": .5, "length_mm": 20, "x": 1}, {"kind": "brain_background", "fraction": .5}])
def test_optional_fields_accept_only_their_canonical_form(noise):
    base = {"region_count": 2, "radius_mm": 35, "mode": "low_hair"}
    spatial = {"kind": "spatial", "rho": .5, "length_mm": 20}
    assert "noise_model" not in validate_request(base) and validate_request({**base, "noise_model": spatial})["noise_model"] == spatial
    with pytest.raises(ValueError):
        validate_request({**base, "noise_model": noise})


def chain(n=8, spacing=.005):
    vertices = np.column_stack((np.arange(n) * spacing, np.zeros(n), np.zeros(n)))
    graph = np.zeros((n, n))
    for i in range(n - 1):
        graph[i, i+1] = graph[i+1, i] = spacing
    return vertices, csr_matrix(graph)


def test_radius_shrinks_before_touching_and_respects_original_graph():
    v, graph = chain()
    # Distinct ROI labels do not erase the physical edge 3--4.
    masks = {"left": np.arange(8) < 4, "right": np.arange(8) >= 4}
    d = RadiusDomain(v, graph, np.arange(8), np.ones(8), masks,
        {"left": [0], "right": [7]}, ["left", "right"], .035)
    patch = d.patches([0, 7])
    assert patch["union_connected_component_count"] == 2
    assert patch["radius_limited_by_separation"]
    assert patch["radius_m"] == pytest.approx(.01)
    assert not set(patch["patches"][0]) & set(patch["patches"][1])
    assert patch["union_area_cm2"] == 6


def test_roi_paths_never_cross_forbidden_vertices():
    v, graph = chain(5)
    d = RadiusDomain(v, graph, np.arange(5), np.ones(5), {"a": np.array([1, 0, 1, 1, 1], bool)},
        {"a": [0]}, ["a"], .1)
    assert d.patches([0])["patches"][0].tolist() == [0]


def test_touching_centers_and_duplicate_centers_are_rejected():
    v, graph = chain()
    d = RadiusDomain(v, graph, np.arange(8), np.ones(8), {"a": np.ones(8, bool)},
        {"a": [0, 1, 7]}, ["a", "a"], .02)
    assert d.patches([0, 0]) is None
    assert d.patches([0, 1]) is None


def full_layout_domain():
    v, graph = chain(80, .005)
    d = RadiusDomain(v, graph, np.arange(80), np.ones(80), {"a": np.ones(80, bool)},
        {"a": [0]}, ["a"], .35)
    s = {"candidate_bank_indices": list(range(64)), "region_indices": [0] * 64, "centers": [0]}
    return d, s


def test_layout_count_spacing_and_radius_audit():
    d, s = full_layout_domain()
    check = d.validate(s)
    assert check["actual_region_counts"] == [64]
    assert check["minimum_chord_distance_mm"] == pytest.approx(5)
    assert check["maximum_electrode_graph_distances_mm"][0] <= 350
    assert check["union_connected_component_count"] == 1
    s["candidate_bank_indices"][-1] = 79
    with pytest.raises(ValueError, match="leaves"):
        d.validate(s)


def test_duplicate_indices_and_duplicate_physical_coordinates_rejected():
    d, s = full_layout_domain()
    s["candidate_bank_indices"][-1] = 0
    with pytest.raises(ValueError, match="unique"):
        d.validate(s)
    d, s = full_layout_domain()
    d.vertices[1] = d.vertices[0]
    with pytest.raises(ValueError, match="spacing"):
        d.validate(s)


def test_small_mixed_center_space_is_exhaustive_not_random_sixteen():
    vertices, _ = chain(16)
    centers = {"left": np.arange(8), "right": np.arange(8, 16)}
    combinations, report = select_radius_center_combinations(vertices, centers, ["left", "right"], 2026)
    assert len(combinations) == 64
    assert set(combinations) == {(a, b) for a in range(8) for b in range(8, 16)}
    assert (7, 15) in combinations
    assert report["method"] == "exhaustive_finite_center_tuples"
    assert report["center_tuple_space_size_before_duplicate_filter"] == 64
    assert report["selected_center_combination_count"] == 64
    assert report["finite_center_tuples_exhausted"]
    assert not report["point_packings_exhausted"]
    assert not report["infeasibility_certified"]


def test_same_roi_uses_sorted_center_sets_and_existing_allocation_convention():
    vertices, _ = chain(5)
    combinations, report = select_radius_center_combinations(vertices, {"a": [4, 0, 2]}, ["a", "a"], 1)
    assert combinations == ((0, 2), (0, 4), (2, 4))
    assert report["assignment_convention"] == "ascending_center_id"
    assert report["center_tuple_space_size_before_duplicate_filter"] == 3
    empty, report = select_radius_center_combinations(vertices, {"a": [0]}, ["a", "a"], 1)
    assert empty == ()
    assert report["selected_center_combination_count"] == 0


def test_mixed_roi_keeps_region_labels_and_rejects_repeated_centers():
    vertices, _ = chain(3)
    combinations, report = select_radius_center_combinations(vertices, {"a": [0, 1], "b": [1, 2]}, ["a", "b", "a"], 1)
    assert combinations == ((0, 2, 1), (1, 2, 0))
    assert report["assignment_convention"] == "ordered_region_labels"
    assert report["center_tuple_space_size_before_duplicate_filter"] == 8
    assert report["duplicate_center_tuples_rejected"] == 6


def test_large_center_space_keeps_bounded_selector(monkeypatch):
    import compact_eeg.local_radius_compute as module
    vertices, _ = chain(34)
    calls = []
    def bounded(vertices, centers, rois, **kwargs):
        calls.append(kwargs)
        return ((0, 17),)
    monkeypatch.setattr(module, "bounded_center_combinations", bounded)
    combinations, report = select_radius_center_combinations(vertices,
        {"left": np.arange(17), "right": np.arange(17, 34)}, ["left", "right"], 1)
    assert combinations == ((0, 17),)
    assert calls[0]["maximum_combinations"] == 16
    assert report["center_tuple_space_size_before_duplicate_filter"] == 289
    assert report["method"] == "bounded_center_shortlist"
    assert report["duplicate_center_tuples_rejected"] is None
    assert not report["finite_center_tuples_exhausted"]


def test_exhaustive_center_limit_is_inclusive():
    vertices, _ = chain(32)
    combinations, report = select_radius_center_combinations(vertices,
        {"a": np.arange(16), "b": np.arange(16, 32)}, ["a", "b"], 1)
    assert len(combinations) == 256
    assert report["finite_center_tuples_exhausted"]


def test_bank_count_screen_preserves_no_layout_without_false_global_proof():
    vertices, graph = chain(8)
    domain = RadiusDomain(vertices, graph, np.arange(8), np.ones(8), {"a": np.ones(8, bool)},
        {"a": [0]}, ["a"], .02)
    # No scoring engine is needed: the finite disk has fewer than64 candidates.
    winner, diagnostics = bounded_radius_search(domain, None, ((0,),), 1)
    assert winner is None
    assert diagnostics["attempts"][0]["status"] == "insufficient_bank_candidates"
    assert diagnostics["attempts"][0]["required_region_counts"] == [64]
    assert diagnostics["scored_layouts"] == 0
    assert diagnostics["coordinate_proposals"] == 0
    assert not diagnostics["infeasibility_certified"]


@pytest.mark.skipif(os.environ.get("LOCAL_RADIUS_REAL_BANK") != "1", reason="opt-in frozen Ernie geometry regression")
def test_real_bank_posterior25_has_same_constraint_32_plus32_solution():
    from compact_eeg.area_budget_study import _initial_layout
    from compact_eeg.packing_pilot import build_surface_edge_graph
    from compact_eeg.surface import vertex_area_weights
    root = Path(__file__).resolve().parents[1]
    pointer = json.loads((root / "results/v2/current_multiregion_bank.json").read_text())
    with np.load(root / pointer["candidates"], allow_pickle=False) as data:
        vertices, faces = data["surface_vertices_m"], data["surface_triangles"]
        bank_ids = data["candidate_vertex_indices"]
        masks = {str(name): data["surface_roi_masks"][:, i] for i, name in enumerate(data["roi_names"])}
        centers = {k.removeprefix("centers_"): data[k] for k in data.files if k.startswith("centers_")}
    rois = request_rois({"region_count": 2, "mode": "preset", "mask_codes": ["PL", "PR"]})
    domain = RadiusDomain(vertices, build_surface_edge_graph(vertices, faces).adjacency, bank_ids,
        vertex_area_weights(vertices, faces) * 10000, masks, centers, rois, .025)
    combinations, selection = select_radius_center_combinations(vertices, centers, rois, 1)
    assert selection["finite_center_tuples_exhausted"]
    assert len(combinations) == 64
    pair = (20832, 28892)
    assert pair in combinations
    snapshot, counts = _initial_layout(domain, pair, domain.patches(pair), np.arange(len(bank_ids)),
        .004, 0, np.random.default_rng(2026))
    assert snapshot is not None
    assert counts == [32, 32]
    geometry = domain.validate(snapshot)
    assert geometry["requested_radius_mm"] == 25
    assert max(geometry["maximum_electrode_graph_distances_mm"]) <= 25
    assert geometry["minimum_chord_distance_mm"] >= 4
    assert geometry["union_connected_component_count"] == 2
    assert not geometry["radius_limited_by_separation"]
    assert geometry["region_roi_ids"] == list(rois)
