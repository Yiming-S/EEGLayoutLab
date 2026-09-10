"""Local, bounded fixed-64 radius-cap design computation on the frozen Ernie bank.

This module does not write experiment pointers or results. It is an exploratory
single-model computation, not an independent-head test or an optimality proof.
Region disks follow ROI-restricted edge paths; their union must have exactly R
components on the ORIGINAL scalp adjacency, including edges crossing ROI labels.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import scipy
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

from .area_budget_study import _initial_layout, center_combinations, union_area_cm2
from .artifacts import sha256_file
from .layout_search_metrics import LayoutSearchMetrics
from .multiregion_geometry import balanced_region_point_counts, bounded_center_combinations
from .multiregion_search import _mixed_proposals
from .packing_pilot import build_surface_edge_graph
from .prototype_localization import evaluate_grid_localization
from .surface import vertex_area_weights

ALGORITHM_VERSION = "strict-radius-local/3-external-exposure"
MASK_ROIS = {
    "PL": "left_near_ear_posterolateral_approx",
    "PR": "right_near_ear_posterolateral_approx",
    "AL": "left_expanded_periauricular_approx",
    "AR": "right_expanded_periauricular_approx",
    "FL": "left_forehead_approx",
    "FM": "upper_forehead_midline_approx",
    "FR": "right_forehead_approx",
    "OL": "left_lateral_supraorbital_approx",
    "OR": "right_lateral_supraorbital_approx",
}
FREE_ROIS = {"whole_surface": "whole_scalp_control_approx", "low_hair": "approx_low_hair_proxy_unvalidated"}
SEARCH_BUDGET = {"center_combinations": 16, "geometry_restarts": 2,
                 "coordinate_sweeps": 1, "proposals_per_electrode": 12,
                 "exhaustive_center_tuple_limit": 256}
SEED = 2026090901


def validate_request(raw):
    """Strict allow-list; never silently substitute an unsupported submask."""
    if not isinstance(raw, dict) or set(raw) - {"region_count", "radius_mm", "mode", "mask_codes"}:
        raise ValueError("Request must contain only region_count, radius_mm, mode, mask_codes")
    count, radius, mode = raw.get("region_count"), raw.get("radius_mm"), raw.get("mode")
    if type(count) is not int or count not in (1, 2, 3, 4, 6):
        raise ValueError("region_count must be one of 1, 2, 3, 4, 6")
    if type(radius) not in (float, int) or not np.isfinite(radius) or not 15 <= radius <= 80 or radius % 5:
        raise ValueError("radius_mm must be 15..80 in steps of 5 mm")
    if mode not in (*FREE_ROIS, "preset"):
        raise ValueError("mode must be whole_surface, low_hair, or preset")
    codes = raw.get("mask_codes", [])
    if not isinstance(codes, list):
        raise ValueError("mask_codes must be a list")
    if mode == "preset":
        if len(codes) != count or any(not isinstance(c, str) or c not in MASK_ROIS for c in codes):
            raise ValueError("preset requires exactly R codes from PL, PR, AL, AR, FL, FM, FR, OL, OR; submasks are unsupported")
    elif codes:
        raise ValueError("mask_codes are only allowed in preset mode")
    return {"region_count": count, "radius_mm": int(radius), "mode": mode, "mask_codes": list(codes)}


def request_rois(request):
    return tuple(MASK_ROIS[c] for c in request["mask_codes"]) if request["mode"] == "preset" else (FREE_ROIS[request["mode"]],) * request["region_count"]


def select_radius_center_combinations(vertices, centers, region_rois, seed):
    """Exhaust small frozen center spaces; retain the bounded large-space policy.

    This exhausts center tuples only, not point packings or continuous positions.
    Same-ROI allocations retain the existing sorted-center assignment convention.
    Mixed-ROI tuples preserve region labels and reject repeated physical centers.
    The mixed-ROI cap counts the Cartesian space before duplicate-center filtering,
    so even enumeration and its diagnostic count remain explicitly bounded.
    """
    rois = tuple(region_rois)
    if not rois:
        raise ValueError("region_rois must not be empty")
    choices = tuple(tuple(sorted(set(int(c) for c in centers[roi]))) for roi in rois)
    identical = len(set(rois)) == 1
    space_size = math.comb(len(choices[0]), len(rois)) if identical else math.prod(map(len, choices))
    exhaustive = space_size <= SEARCH_BUDGET["exhaustive_center_tuple_limit"]
    duplicate_rejections = None
    if exhaustive:
        raw = itertools.combinations(choices[0], len(rois)) if identical else itertools.product(*choices)
        combinations = tuple(c for c in raw if len(set(c)) == len(c))
        duplicate_rejections = space_size - len(combinations)
    elif identical:
        combinations = center_combinations(vertices, np.asarray(choices[0]), len(rois),
            SEARCH_BUDGET["center_combinations"], seed)
    else:
        combinations = bounded_center_combinations(vertices, centers, rois,
            minimum_center_chord_distance_m=0., beam_width=256,
            maximum_combinations=SEARCH_BUDGET["center_combinations"])
    selection = {
        "method": "exhaustive_finite_center_tuples" if exhaustive else "bounded_center_shortlist",
        "center_shortlist_sizes": [len(c) for c in choices],
        "center_tuple_space_size_before_duplicate_filter": space_size,
        "selected_center_combination_count": len(combinations),
        "duplicate_center_tuples_rejected": duplicate_rejections,
        "exhaustive_center_tuple_limit": SEARCH_BUDGET["exhaustive_center_tuple_limit"],
        "finite_center_tuples_exhausted": exhaustive,
        "assignment_convention": "ascending_center_id" if identical else "ordered_region_labels",
        "point_packings_exhausted": False,
        "infeasibility_certified": False,
    }
    return combinations, selection


def _integer_vector(value, upper, name):
    a = np.asarray(value)
    if a.ndim != 1 or a.dtype.kind not in "iu" or not len(a) or a.min() < 0 or a.max() >= upper:
        raise ValueError(f"Invalid {name}")
    return a.astype(np.int64, copy=False)


class RadiusDomain:
    """ROI-specific distances with a common radius reduced before any disk merge."""

    def __init__(self, vertices, adjacency, bank_ids, vertex_areas, masks, centers, region_rois, radius_m):
        self.vertices = np.asarray(vertices, float)
        self.adjacency = adjacency.tocsr()
        self.bank_ids = _integer_vector(bank_ids, len(self.vertices), "bank indices")
        self.vertex_areas = np.asarray(vertex_areas, float)
        self.region_rois = tuple(region_rois)
        self.radius_m = float(radius_m)
        if self.vertices.ndim != 2 or self.vertices.shape[1] != 3 or not np.all(np.isfinite(self.vertices)):
            raise ValueError("Invalid surface coordinates")
        if len(np.unique(self.bank_ids)) != len(self.bank_ids):
            raise ValueError("Duplicate bank vertex indices")
        if self.adjacency.shape != (len(self.vertices), len(self.vertices)):
            raise ValueError("Adjacency size mismatch")
        if self.vertex_areas.shape != (len(self.vertices),) or np.any(self.vertex_areas < 0) or not np.all(np.isfinite(self.vertex_areas)):
            raise ValueError("Invalid vertex areas")
        if not np.isfinite(self.radius_m) or self.radius_m <= 0:
            raise ValueError("Invalid radius cap")
        self.masks, self.centers, self.distances, self.center_rows = {}, {}, {}, {}
        graph = self.adjacency.tocoo()
        for roi in dict.fromkeys(self.region_rois):
            if roi not in masks or roi not in centers:
                raise ValueError(f"Unsupported ROI: {roi}")
            mask = np.asarray(masks[roi])
            ids = _integer_vector(centers[roi], len(self.vertices), "center shortlist")
            if mask.dtype.kind != "b" or mask.shape != (len(self.vertices),) or not np.all(mask[ids]):
                raise ValueError("Center or ROI mask invalid")
            keep = mask[graph.row] & mask[graph.col]
            restricted = csr_matrix((graph.data[keep], (graph.row[keep], graph.col[keep])), shape=self.adjacency.shape)
            self.masks[roi], self.centers[roi] = mask, ids
            self.distances[roi] = dijkstra(restricted, directed=False, indices=ids)
            self.center_rows[roi] = {int(c): i for i, c in enumerate(ids)}
        self._patch_cache = {}

    def patches(self, centers):
        key = tuple(int(c) for c in centers)
        if len(key) != len(self.region_rois) or len(set(key)) != len(key):
            return None
        if key in self._patch_cache:
            return self._patch_cache[key]
        try:
            distance = np.stack([self.distances[roi][self.center_rows[roi][c]] for roi, c in zip(self.region_rois, key, strict=True)])
        except KeyError:
            return None
        minimum = distance.min(axis=0)
        shells = np.unique(minimum[np.isfinite(minimum) & (minimum <= self.radius_m)])
        def components(radius):
            union = np.flatnonzero(minimum <= radius)
            return int(connected_components(self.adjacency[union][:, union], directed=False)[0])
        if not len(shells) or components(float(shells[0])) != len(key):
            self._patch_cache[key] = None
            return None
        # Each ROI-restricted disk grows connected. On the original adjacency,
        # the number of union components can only decrease as its disks grow.
        lo, hi = 0, len(shells) - 1
        while lo < hi:
            middle = (lo + hi + 1) // 2
            if components(float(shells[middle])) == len(key):
                lo = middle
            else:
                hi = middle - 1
        radius = self.radius_m if lo == len(shells) - 1 else float(shells[lo])
        patches = tuple(np.flatnonzero(row <= radius) for row in distance)
        union = np.unique(np.concatenate(patches))
        result = {"radius_m": radius, "patches": patches,
            "bank_pools": tuple(np.flatnonzero(np.isin(self.bank_ids, p)) for p in patches),
            "union_area_cm2": union_area_cm2(patches, self.vertex_areas),
            "region_areas_cm2": [float(self.vertex_areas[p].sum()) for p in patches],
            "union_connected_component_count": components(radius),
            "radius_limited_by_separation": radius < self.radius_m,
            "union_vertex_count": len(union)}
        if result["union_connected_component_count"] != len(key):
            raise RuntimeError("Region component invariant violated")
        self._patch_cache[key] = result
        return result

    def validate(self, snapshot, *, spacing_m=.004):
        ids = _integer_vector(snapshot["candidate_bank_indices"], len(self.bank_ids), "layout bank indices")
        labels = _integer_vector(snapshot["region_indices"], len(self.region_rois), "region labels")
        centers = tuple(int(c) for c in snapshot["centers"])
        if len(ids) != 64 or len(labels) != 64 or len(np.unique(ids)) != 64:
            raise ValueError("Layout requires 64 unique physical points")
        counts = np.bincount(labels, minlength=len(self.region_rois)).tolist()
        if counts != list(balanced_region_point_counts(len(self.region_rois))):
            raise ValueError("Balanced regional allocation violated")
        xyz = self.vertices[self.bank_ids[ids]]
        gap = float(np.linalg.norm(xyz[:, None] - xyz[None], axis=2)[np.triu_indices(64, 1)].min())
        if gap + 1e-12 < spacing_m:
            raise ValueError("Minimum physical spacing violated, including repeated coordinates")
        patch = self.patches(centers)
        if patch is None or patch["union_connected_component_count"] != len(self.region_rois):
            raise ValueError("Regions overlap or touch")
        maximum = []
        for r, (roi, center) in enumerate(zip(self.region_rois, centers, strict=True)):
            rows = ids[labels == r]
            if not np.all(np.isin(rows, patch["bank_pools"][r])):
                raise ValueError("Electrode leaves its ROI-connected radius disk")
            distance = self.distances[roi][self.center_rows[roi][center], self.bank_ids[rows]]
            maximum.append(float(distance.max() * 1000))
        if max(maximum) > self.radius_m * 1000 + 1e-8:
            raise ValueError("Requested radius cap violated")
        return {"valid": True, "actual_region_counts": counts,
            "requested_radius_mm": self.radius_m * 1000, "common_graph_radius_mm": patch["radius_m"] * 1000,
            "maximum_electrode_graph_distances_mm": maximum,
            "union_area_cm2": patch["union_area_cm2"], "region_areas_cm2": patch["region_areas_cm2"],
            "minimum_chord_distance_mm": gap * 1000,
            "union_connected_component_count": patch["union_connected_component_count"],
            "radius_limited_by_separation": patch["radius_limited_by_separation"],
            "region_roi_ids": list(self.region_rois), "union_vertex_count": patch["union_vertex_count"]}


def bounded_radius_search(domain, engine, combinations, seed, progress=lambda **kwargs: None):
    """Optimize only the predeclared minimum(field20, sensitivity) objective."""
    allowed = np.arange(len(domain.bank_ids))
    allocation = balanced_region_point_counts(len(domain.region_rois))
    attempts, starts, trace = [], [], []
    scored_count, proposal_count = 0, 0
    def score(snapshot):
        nonlocal scored_count
        geometry = domain.validate(snapshot)
        state = engine.make_state(snapshot["candidate_bank_indices"], snr_db=20)
        sensitivity = engine.sensitivity_tail(state.indices)
        if sensitivity is None or not np.isfinite(sensitivity) or not np.isfinite(state.field_relative):
            raise ValueError("Field/sensitivity numerical denominator is unavailable")
        scored_count += 1
        return {**snapshot, "geometry": geometry, "field20": float(state.field_relative),
                "sensitivity_tail": float(sensitivity), "objective": float(min(state.field_relative, sensitivity))}, state
    for i, centers in enumerate(combinations):
        patch = domain.patches(centers)
        progress(stage="geometry", message=f"检查区域组合 {i + 1}/{len(combinations)}", progress=.25 + .35 * (i + 1) / max(1, len(combinations)))
        if patch is None:
            attempts.append({"centers": list(centers), "status": "no_separated_disks"})
            continue
        pool_counts = [len(pool) for pool in patch["bank_pools"]]
        if any(found < required for found, required in zip(pool_counts, allocation, strict=True)):
            attempts.append({"centers": list(centers), "status": "insufficient_bank_candidates",
                "bank_pool_counts": pool_counts, "required_region_counts": list(allocation),
                "common_graph_radius_mm": patch["radius_m"] * 1000})
            continue
        for trial in range(SEARCH_BUDGET["geometry_restarts"]):
            snapshot, achieved = _initial_layout(domain, centers, patch, allowed, .004, trial,
                np.random.default_rng(np.random.SeedSequence([seed, i, trial])))
            attempts.append({"centers": list(centers), "trial": trial, "achieved": achieved,
                "common_graph_radius_mm": patch["radius_m"] * 1000,
                "status": "complete" if snapshot else "no_complete_layout_under_bounded_construction"})
            if snapshot:
                starts.append(score(snapshot)[0])
    if not starts:
        return None, {"attempts": attempts, "trace": trace, "scored_layouts": scored_count,
            "coordinate_proposals": proposal_count, "infeasibility_certified": False}
    current = max(starts, key=lambda s: (s["objective"], -sum(s["candidate_bank_indices"])))
    initial = current.copy()
    ids = np.asarray(current["candidate_bank_indices"], int).copy()
    labels = np.asarray(current["region_indices"], int)
    patch = domain.patches(current["centers"])
    state = engine.make_state(ids, snr_db=20)
    xyz = domain.vertices[domain.bank_ids]
    rng = np.random.default_rng(np.random.SeedSequence([seed, 1234]))
    for count, position in enumerate(rng.permutation(64)):
        position = int(position)
        pool = patch["bank_pools"][labels[position]]
        pool = pool[~np.isin(pool, ids)]
        if len(pool):
            gap = np.min(np.linalg.norm(xyz[pool, None] - xyz[np.delete(ids, position)][None], axis=2), axis=1)
            pool = pool[gap + 1e-12 >= .004]
        choices = _mixed_proposals(xyz, pool, int(ids[position]), SEARCH_BUDGET["proposals_per_electrode"], rng)
        if len(choices):
            scores = engine.score_exchanges(state, position, choices, include_sensitivity=True)
            values = np.minimum(scores.field_relative, scores.sensitivity_tail)
            proposal_count += len(choices)
            best = int(np.argmax(np.where(np.isfinite(values), values, -np.inf)))
            if np.isfinite(values[best]) and values[best] > current["objective"] + 1e-9:
                proposed = ids.copy()
                proposed[position] = choices[best]
                candidate, candidate_state = score({**current, "candidate_bank_indices": proposed.tolist()})
                if candidate["objective"] > current["objective"] + 1e-9:
                    trace.append({"position": position, "old_bank_row": int(ids[position]), "new_bank_row": int(choices[best]),
                        "before": current["objective"], "after": candidate["objective"]})
                    current, state, ids = candidate, candidate_state, proposed
        if count % 8 == 7:
            progress(stage="optimize", message=f"优化64个点位：{count + 1}/64", progress=.60 + .18 * (count + 1) / 64)
    return current, {"attempts": attempts, "trace": trace, "initial": initial,
        "scored_layouts": scored_count, "coordinate_proposals": proposal_count,
        "global_optimum_certified": False, "infeasibility_certified": False, "localization_optimized": False}


class LocalRadiusComputer:
    """Reusable process-local covariance bank; no native FEM or filesystem writes."""

    def __init__(self, root, progress=lambda **kwargs: None):
        self.root = Path(root).resolve()
        progress(stage="loading", message="加载并校验本地前向模型", progress=.03)
        pointer_path = self.root / "results/v2/current_multiregion_bank.json"
        pointer = json.loads(pointer_path.read_text())
        bank_path, geometry_path = self.root / pointer["path"], self.root / pointer["candidates"]
        bank_report_path = self.root / pointer["report"]
        bank_report = json.loads(bank_report_path.read_text())
        bank_sha, geometry_sha = sha256_file(bank_path), sha256_file(geometry_path)
        if bank_sha != pointer["sha256"] or geometry_sha != bank_report["candidate_sha256"]:
            raise ValueError("Forward bank or geometry SHA256 mismatch")
        from .surface_admissibility import load_admissibility
        eligible, admission = load_admissibility(self.root, geometry_sha)
        with np.load(geometry_path, allow_pickle=False) as g, np.load(bank_path, allow_pickle=False) as h:
            self.vertices, self.faces, self.bank_ids = g["surface_vertices_m"], g["surface_triangles"], g["candidate_vertex_indices"]
            if not np.array_equal(self.bank_ids, h["candidate_vertex_indices"]):
                raise ValueError("Forward and geometry bank ordering mismatch")
            self.candidate_xyz_mm, self.reference_xyz_mm = h["candidate_xyz_mm"], h["reference_xyz_mm"]
            if not np.allclose(self.vertices[self.bank_ids] * 1000, self.candidate_xyz_mm, atol=1e-10, rtol=0):
                raise ValueError("Bank millimetre coordinates differ from original surface vertices")
            self.masks = {str(name): g["surface_roi_masks"][:, i] for i, name in enumerate(g["roi_names"])}
            self.centers = {k.removeprefix("centers_"): g[k] for k in g.files if k.startswith("centers_")}
            self.masks = {name: mask & eligible for name, mask in self.masks.items()}
            self.centers = {name: ids[self.masks[name][ids]] for name, ids in self.centers.items()}
            self.hc, self.hb = h["candidate_leadfield_v_per_am"], h["reference_leadfield_v_per_am"]
            self.n = int(h["dictionary_source_count"])
            self.weights, self.generation_weights = h["source_area_weights"], h["generation_area_weights"]
            self.source_xyz_mm, self.generation_xyz_mm = h["source_xyz_mm"], h["generation_xyz_mm"]
        progress(stage="loading", message="构建共享信号协方差缓存", progress=.12)
        self.adjacency = build_surface_edge_graph(self.vertices, self.faces).adjacency
        self.areas = vertex_area_weights(self.vertices, self.faces) * 10000
        self.engine = LayoutSearchMetrics(self.hc[:, :self.n], self.hb[:, :self.n], self.weights)
        dependency_names = ["local_radius_compute.py", "area_budget_study.py", "artifacts.py", "layout_search_metrics.py",
            "multiregion_geometry.py", "multiregion_search.py", "packing_pilot.py", "prototype_localization.py",
            "surface.py", "metrics.py", "inverse_pilot.py", "fixed64_geometry.py", "surface_admissibility.py"]
        dependencies = [self.root / "src/compact_eeg" / name for name in dependency_names]
        dependencies.append(self.root / "scripts/run_local_radius_compute.py")
        self.provenance = {**admission, "algorithm_version": ALGORITHM_VERSION, "head_model": "Ernie single template",
            "bank_path": pointer["path"], "bank_sha256": bank_sha, "geometry_path": pointer["candidates"],
            "geometry_sha256": geometry_sha, "pointer_sha256": sha256_file(pointer_path),
            "bank_report_sha256": sha256_file(bank_report_path),
            "code_sha256": {str(p.relative_to(self.root)): sha256_file(p) for p in dependencies},
            "python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__,
            "candidate_count": len(self.bank_ids), "dictionary_source_count": self.n,
            "generation_source_count": len(self.generation_xyz_mm), "noise_repetitions": 16,
            "source_moment_am": 1e-8, "nominal_reference_snr_db": 20, "thread_limit": 2,
            "minimum_chord_spacing_mm": 4, "physical_electrode_count": 64,
            "source_prior": "same frozen 4096 cortical area quadrature used for optimization",
            "evaluation_role": "model_conditional_exploration_not_new_independent_validation",
            "optimization_objective": "min(field_relative20,sensitivity_tail)", "search_budget": SEARCH_BUDGET.copy(),
            "formal_population_ar": False, "global_optimum_certified": False, "fem_recomputed": False,
            "limitations": ["Finite candidate bank, finite center list and bounded local search; no global optimum or infeasibility proof.",
                "Approximate low-hair and periauricular coordinate ROIs are not validated anatomical hair-free or strict behind-ear masks.",
                "Radius is an ROI-restricted mesh-edge path bound, not exact continuous geodesic radius; area is native vertex quadrature.",
                "Exactly R disconnected and non-touching patches on the original mesh; common radius may shrink before patches merge.",
                "Same head, conductivity, source bank and solver; not an independent-head or fresh-source validation and not human accuracy.",
                "Field, amplitude sensitivity and localization utility are different relative metrics; their minimum is a conditional threshold rule.",
                "Localization is evaluated after freezing the joint field/sensitivity winner; its result never selects another layout.",
                "Physical noise is calibrated once from full-head64; localization remains grid-limited with independently seeded layout noise."]}
        self._baseline = None

    def _localize(self, field, layout_id):
        return evaluate_grid_localization(field[:, :self.n], field[:, self.n:], self.source_xyz_mm, self.generation_xyz_mm,
            source_moment_am=1e-8, physical_electrode_noise_std_v=np.sqrt(self.engine.reference_mean_contrast_signal_power_v2 * .01),
            noise_seed=SEED, layout_id=layout_id, noise_repetitions=16, generation_source_weights=self.generation_weights)

    def compute(self, raw, progress=lambda **kwargs: None):
        started = time.perf_counter()
        request = validate_request(raw)
        canonical = json.dumps(request, sort_keys=True, separators=(",", ":"))
        seed = int.from_bytes(hashlib.sha256((ALGORITHM_VERSION + canonical).encode()).digest()[:4], "little")
        rois = request_rois(request)
        progress(stage="geometry", message="构建ROI约束路径与不接触区域", progress=.18)
        domain = RadiusDomain(self.vertices, self.adjacency, self.bank_ids, self.areas, self.masks, self.centers, rois, request["radius_mm"] / 1000)
        combinations, center_selection = select_radius_center_combinations(self.vertices, self.centers, rois, seed)
        winner, diagnostics = bounded_radius_search(domain, self.engine, combinations, seed, progress)
        provenance = {**self.provenance, "search_seed": seed, "localization_noise_seed": SEED,
            "region_roi_ids": list(rois), "center_selection": center_selection}
        result = {"status": "no_layout" if winner is None else "completed", "request": request,
            "layout": None, "metrics": None, "geometry": None, "provenance": provenance,
            "diagnostics": {**diagnostics, "center_combinations": [list(c) for c in combinations],
                "center_selection": center_selection}}
        if winner is None:
            result.update(message="在当前候选网格、4mm间距和有限搜索预算内，未构造出满足严格区域约束的64点布局；这不是数学不可行证明。", elapsed_seconds=time.perf_counter() - started)
            return result
        selected = np.asarray(winner["candidate_bank_indices"], int)
        layout_id = hashlib.sha256(self.bank_ids[selected].astype("<i8").tobytes()).hexdigest()[:24]
        geometry = domain.validate(winner)
        progress(stage="metrics", message="冻结点位，评价重建、敏感度及源定位", progress=.82)
        field = self.engine.evaluate(selected, snr_db=(20,))
        condition = field["conditions"][0]
        if self._baseline is None:
            self._baseline = self._localize(self.hb, "local_radius_reference64")
        progress(stage="localization", message="计算冻结布局的离散源定位误差", progress=.91)
        loc = self._localize(self.hc[selected], "local_radius_" + layout_id)
        reference_utility = self._baseline.report["source_lower10_utility_dmax50mm"]
        relative_loc = loc.report["source_lower10_utility_dmax50mm"] / reference_utility if reference_utility > 1e-12 else None
        values = [condition["field_retention_unclipped"], winner["sensitivity_tail"], relative_loc]
        result.update(layout={"id": layout_id, "xyzMm": self.candidate_xyz_mm[selected].tolist(),
                "regionIndices": winner["region_indices"], "referenceXyzMm": self.reference_xyz_mm.tolist(),
                "regionPatchVertexIndices": [p.tolist() for p in domain.patches(winner["centers"])["patches"]],
                "regionAreasCm2": geometry["region_areas_cm2"],
                "candidateBankIndices": selected.tolist(), "electrodeVertexIndices": self.bank_ids[selected].tolist(),
                "centerVertexIndices": winner["centers"], "centerXyzMm": (self.vertices[winner["centers"]] * 1000).tolist()},
            metrics={"field_relative": values[0], "field_absolute": condition["candidate_field_explained_energy"],
                "reference_field_absolute": condition["reference_field_explained_energy"], "sensitivity_tail": values[1],
                "localization_relative": relative_loc, "conditional_global": min(values) if all(v is not None and np.isfinite(v) for v in values) else None,
                "median_mm": loc.report["median_error_mm"], "p90_mm": loc.report["p90_error_mm"],
                "p95_mm": loc.report["p95_error_mm"], "reference_median_mm": self._baseline.report["median_error_mm"],
                "reference_p90_mm": self._baseline.report["p90_error_mm"],
                "localization_utility": loc.report["source_lower10_utility_dmax50mm"], "reference_localization_utility": reference_utility,
                "effective_rank": condition["candidate_noise_whitened_area_weighted_effective_rank"]}, geometry=geometry)
        result["diagnostics"].update(final=winner, field_report=field, localization_report=loc.report,
            reference_localization_report=self._baseline.report,
            localization_errors_mm=loc.errors_mm.tolist(), reference_localization_errors_mm=self._baseline.errors_mm.tolist())
        result["elapsed_seconds"] = time.perf_counter() - started
        # Guard against code changed by another process during an active computation.
        if any(sha256_file(self.root / p) != digest for p, digest in provenance["code_sha256"].items()):
            raise RuntimeError("Scientific source code changed during computation")
        return result


__all__ = ["LocalRadiusComputer", "RadiusDomain", "validate_request", "request_rois", "bounded_radius_search",
    "select_radius_center_combinations"]
