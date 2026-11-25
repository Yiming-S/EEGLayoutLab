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


def _grid_patch_fixture():
    """Two ROI regions on a 2D lattice where high-SNR sources favor shifted centers."""
    from compact_eeg.layout_search_metrics import LayoutSearchMetrics
    xs, ys = np.meshgrid(np.arange(26) * .005, np.arange(10) * .005, indexing="ij")
    n = xs.size
    vertices = np.column_stack((xs.ravel(), ys.ravel(), np.zeros(n)))
    rows, cols, data = [], [], []
    idx_grid = np.arange(n).reshape(26, 10)
    for ix in range(26):
        for iy in range(10):
            u = idx_grid[ix, iy]
            for dx, dy in ((1, 0), (0, 1)):
                jx, jy = ix + dx, iy + dy
                if jx < 26 and jy < 10:
                    v = idx_grid[jx, jy]
                    rows.extend((u, v))
                    cols.extend((v, u))
                    data.extend((.005, .005))
    graph = csr_matrix((data, (rows, cols)), shape=(n, n))
    masks = {
        "left": vertices[:, 0] <= .058,
        "right": vertices[:, 0] >= .065,
    }
    centers = {
        "left": np.array([idx_grid[3, 4], idx_grid[5, 4], idx_grid[7, 4], idx_grid[8, 5]], dtype=np.int64),
        "right": np.array([idx_grid[17, 5], idx_grid[18, 4], idx_grid[20, 4], idx_grid[22, 4]], dtype=np.int64),
    }
    rng = np.random.default_rng(7712)
    # Create spatially varying signal gain peaking near ix=8 (left) and ix=17 (right) so shifting centers helps.
    gain = np.exp(-((vertices[:, 0] - .040) / .028) ** 2) + np.exp(-((vertices[:, 0] - .085) / .028) ** 2) + .25
    patterns = rng.normal(size=(16, 120))
    spatial = rng.normal(size=(n, 16)) * gain[:, None]
    bank = spatial @ patterns + .02 * rng.normal(size=(n, 120))
    ref_idx = np.linspace(0, n - 1, 64, dtype=int)
    weights = rng.uniform(.2, 1.5, 120)
    engine = LayoutSearchMetrics(bank, bank[ref_idx], weights)
    domain = RadiusDomain(vertices, graph, np.arange(n), np.ones(n), masks, centers, ["left", "right"], .045)
    return domain, engine, idx_grid


def test_convergent_fedorov_and_center_shift_with_out_of_disk_repair():
    domain, engine, idx_grid = _grid_patch_fixture()
    # Start solely from outer low-SNR centers (ix=3 and ix=22) so center shifts with out-of-disk repair are exercised.
    start_combos = ((int(idx_grid[3, 4]), int(idx_grid[22, 4])),)
    winner, diag = bounded_radius_search(domain, engine, start_combos, seed=202611)
    assert winner is not None
    checked = domain.validate(winner)
    assert checked["actual_region_counts"] == [32, 32]
    assert checked["union_connected_component_count"] == 2
    assert checked["minimum_chord_distance_mm"] >= 4.0 - 1e-9
    assert winner["objective"] > diag["initial"]["objective"]
    assert diag["center_moves"]["evaluated"] > 0
    assert diag["center_moves"]["accepted"] >= 1
    assert diag["center_moves"]["repaired_electrodes"] >= 1
    assert any(m.get("kind") == "center_shift_with_repair" for m in diag["trace"])
    assert diag["one_opt_converged"]
    # Verify deterministic bitwise reproducibility for the same seed.
    winner2, diag2 = bounded_radius_search(domain, engine, start_combos, seed=202611)
    assert winner2["candidate_bank_indices"] == winner["candidate_bank_indices"]
    assert winner2["centers"] == winner["centers"]
    assert winner2["objective"] == winner["objective"]
    assert diag2["coordinate_proposals"] == diag["coordinate_proposals"]


def test_allocation_mode_request_validation_and_seed_sharing():
    from compact_eeg.local_radius_compute import search_seed
    base = {"region_count": 2, "radius_mm": 30, "mode": "preset", "mask_codes": ["PL", "FM"]}
    adaptive = validate_request({**base, "allocation_mode": "adaptive"})
    composite = validate_request({**base, "allocation_mode": "adaptive", "objective_mode": "composite"})
    assert adaptive["allocation_mode"] == "adaptive"
    assert composite["objective_mode"] == "composite"
    assert "allocation_mode" not in validate_request(base)
    assert "objective_mode" not in validate_request(base)
    assert search_seed(adaptive) == search_seed(validate_request(base))
    assert search_seed(composite) == search_seed(validate_request(base))
    for bad in (
        {**base, "allocation_mode": "balanced"},
        {**base, "allocation_mode": None},
        {**base, "allocation_mode": "free"},
        {"region_count": 1, "radius_mm": 30, "mode": "whole_surface", "allocation_mode": "adaptive"},
        {**base, "objective_mode": "min"},
        {**base, "objective_mode": None},
        {**base, "objective_mode": "info_only"},
    ):
        with pytest.raises(ValueError):
            validate_request(bad)


def test_composite_objective_mode_optimizes_field_and_subspace_information():
    domain, engine, idx_grid = _grid_patch_fixture()
    start_combos = ((int(idx_grid[5, 4]), int(idx_grid[20, 4])),)
    win_min, diag_min = bounded_radius_search(
        domain, engine, start_combos, seed=202612, adaptive_allocation=True, objective_mode="min")
    win_comp, diag_comp = bounded_radius_search(
        domain, engine, start_combos, seed=202612, adaptive_allocation=True, objective_mode="composite")
    assert win_min is not None and win_comp is not None
    assert diag_min["objective_mode"] == "min"
    assert diag_comp["objective_mode"] == "composite"
    assert np.isfinite(win_comp["info20"]) and win_comp["info20"] > 0
    assert domain.validate(win_comp, adaptive_allocation=True)["union_connected_component_count"] == 2


def test_adaptive_quota_unlocks_asymmetric_apertures_and_improves_objective():
    from compact_eeg.layout_search_metrics import LayoutSearchMetrics
    xs, ys = np.meshgrid(np.arange(26) * .005, np.arange(10) * .005, indexing="ij")
    n = xs.size
    vertices = np.column_stack((xs.ravel(), ys.ravel(), np.zeros(n)))
    rows, cols, data = [], [], []
    idx_grid = np.arange(n).reshape(26, 10)
    for ix in range(26):
        for iy in range(10):
            u = idx_grid[ix, iy]
            for dx, dy in ((1, 0), (0, 1)):
                jx, jy = ix + dx, iy + dy
                if jx < 26 and jy < 10:
                    v = idx_grid[jx, jy]
                    rows.extend((u, v))
                    cols.extend((v, u))
                    data.extend((.005, .005))
    graph = csr_matrix((data, (rows, cols)), shape=(n, n))
    # Tiny anterior anchor mask (only 12 vertices, < 32) paired with a wide high-SNR mask.
    tiny_mask = (vertices[:, 0] <= .015) & (vertices[:, 1] <= .012)
    wide_mask = vertices[:, 0] >= .050
    assert 8 <= int(np.count_nonzero(tiny_mask)) < 32
    rng = np.random.default_rng(9042)
    gain = np.where(wide_mask, 2.4, 0.7)
    bank = (rng.normal(size=(n, 20)) * gain[:, None]) @ rng.normal(size=(20, 128)) + .02 * rng.normal(size=(n, 128))
    ref_idx = np.linspace(0, n - 1, 64, dtype=int)
    engine = LayoutSearchMetrics(bank, bank[ref_idx], rng.uniform(.3, 1.4, 128))

    tight_domain = RadiusDomain(
        vertices, graph, np.arange(n), np.ones(n),
        {"tiny": tiny_mask, "wide": wide_mask},
        {"tiny": [int(idx_grid[1, 1])], "wide": [int(idx_grid[18, 5])]},
        ["tiny", "wide"], .045,
    )
    combo = ((int(idx_grid[1, 1]), int(idx_grid[18, 5])),)
    bal_none, bal_diag = bounded_radius_search(tight_domain, engine, combo, seed=42, adaptive_allocation=False)
    assert bal_none is None
    assert bal_diag["attempts"][0]["status"] == "insufficient_bank_candidates"

    adap_win, adap_diag = bounded_radius_search(tight_domain, engine, combo, seed=42, adaptive_allocation=True)
    assert adap_win is not None
    geom = tight_domain.validate(adap_win, adaptive_allocation=True)
    assert sum(geom["actual_region_counts"]) == 64
    assert geom["actual_region_counts"][0] >= 4
    assert geom["actual_region_counts"][1] > 32
    assert adap_diag["allocation_mode"] == "adaptive"

    # Reject floor violations (< 4 in any region) even in adaptive mode.
    violated = {
        **adap_win,
        "region_indices": [0, 0, 0] + [1] * 61,
    }
    with pytest.raises(ValueError, match="Adaptive|Electrode leaves"):
        tight_domain.validate(violated, adaptive_allocation=True)

    # Also verify on a balanced-feasible asymmetric-SNR domain that adaptive quota strictly improves over 32+32.
    asym_masks = {"left": vertices[:, 0] <= .045, "right": vertices[:, 0] >= .055}
    asym_gain = np.where(vertices[:, 0] >= .055, 3.2, 0.35)
    asym_bank = (rng.normal(size=(n, 20)) * asym_gain[:, None]) @ rng.normal(size=(20, 128)) + .02 * rng.normal(size=(n, 128))
    asym_engine = LayoutSearchMetrics(asym_bank, asym_bank[ref_idx], rng.uniform(.3, 1.4, 128))
    asym_domain = RadiusDomain(
        vertices, graph, np.arange(n), np.ones(n), asym_masks,
        {"left": [int(idx_grid[4, 4])], "right": [int(idx_grid[18, 4])]},
        ["left", "right"], .045,
    )
    pair = ((int(idx_grid[4, 4]), int(idx_grid[18, 4])),)
    w_bal, _ = bounded_radius_search(asym_domain, asym_engine, pair, seed=77, adaptive_allocation=False)
    w_adap, d_adap = bounded_radius_search(asym_domain, asym_engine, pair, seed=77, adaptive_allocation=True)
    assert w_bal["geometry"]["actual_region_counts"] == [32, 32]
    assert w_adap["geometry"]["actual_region_counts"][1] > 32
    assert w_adap["geometry"]["actual_region_counts"][0] >= 4
    assert w_adap["objective"] > w_bal["objective"] + 1e-4
    assert d_adap["final_region_counts"] == w_adap["geometry"]["actual_region_counts"]


def test_variable_electrode_count_request_and_bounded_search():
    from compact_eeg.local_radius_compute import search_seed
    base = {"region_count": 2, "radius_mm": 30, "mode": "preset", "mask_codes": ["PL", "FM"]}
    req16 = validate_request({**base, "allocation_mode": "adaptive", "objective_mode": "composite", "electrode_count": 16})
    assert req16["electrode_count"] == 16
    assert search_seed(req16) == search_seed(validate_request(base))
    for bad in (
        {**base, "electrode_count": 64},
        {**base, "electrode_count": None},
        {**base, "electrode_count": 20},
        {**base, "electrode_count": True},
        {"region_count": 6, "radius_mm": 30, "mode": "whole_surface", "electrode_count": 8},
        {"region_count": 4, "radius_mm": 30, "mode": "whole_surface", "allocation_mode": "adaptive", "electrode_count": 12},
    ):
        with pytest.raises(ValueError):
            validate_request(bad)

    domain, engine, idx_grid = _grid_patch_fixture()
    start_combos = ((int(idx_grid[3, 4]), int(idx_grid[22, 4])),)
    win8_bal, diag8_bal = bounded_radius_search(
        domain, engine, start_combos, seed=202615, adaptive_allocation=False,
        objective_mode="composite", total_electrodes=8)
    assert win8_bal is not None
    assert diag8_bal["physical_electrode_count"] == 8
    assert domain.validate(win8_bal, total_electrodes=8)["actual_region_counts"] == [4, 4]

    win16_adap, diag16_adap = bounded_radius_search(
        domain, engine, start_combos, seed=202615, adaptive_allocation=True,
        objective_mode="composite", total_electrodes=16)
    assert win16_adap is not None
    geom16 = domain.validate(win16_adap, adaptive_allocation=True, total_electrodes=16)
    assert sum(geom16["actual_region_counts"]) == 16
    assert all(c >= 4 for c in geom16["actual_region_counts"])
    assert diag16_adap["physical_electrode_count"] == 16


def test_stage1_stage3_nonlocal_margin_proxy_screening_and_reranking():
    from compact_eeg.layout_search_metrics import LayoutSearchMetrics
    domain, base_engine, idx_grid = _grid_patch_fixture()
    rng = np.random.default_rng(31415)
    src_xyz = rng.uniform(-60.0, 60.0, size=(120, 3))
    bank_raw = base_engine._bank.copy()
    engine = LayoutSearchMetrics(
        bank_raw, bank_raw[np.linspace(0, len(bank_raw) - 1, 64, dtype=int)],
        rng.uniform(0.3, 1.4, 120), dictionary_xyz_mm=src_xyz, dictionary_anchor_count=32,
    )
    combos = (
        (int(idx_grid[3, 4]), int(idx_grid[22, 4])),
        (int(idx_grid[5, 4]), int(idx_grid[20, 4])),
        (int(idx_grid[7, 4]), int(idx_grid[18, 4])),
    )
    win, diag = bounded_radius_search(
        domain, engine, combos, seed=202620, adaptive_allocation=True,
        objective_mode="composite", total_electrodes=24, enable_localization_proxy=True,
    )
    assert win is not None
    proxy_diag = diag["dictionary_margin_proxy"]
    assert proxy_diag["enabled"] is True
    assert proxy_diag["stage1_evaluations"] >= 3
    assert proxy_diag["stage3_evaluations"] >= 1
    assert np.isfinite(proxy_diag["winner_margin20"]) and proxy_diag["winner_margin20"] > 0.0
    assert domain.validate(win, adaptive_allocation=True, total_electrodes=24)["union_connected_component_count"] == 2


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
