"""Bounded single-head fixed-union-area layout search, not an optimality proof.

Patch areas are barycentric native-vertex quadrature. Each region is an
ROI-constrained mesh-edge shortest-path disk. A common radius is fitted to
the UNION, counting overlap once. This deliberately differs from graph disks
clipped after unconstrained shortest paths in the earlier radius-cap study.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra, connected_components

from .multiregion_geometry import balanced_region_point_counts
from .multiregion_search import _mixed_proposals


def union_area_cm2(patches, vertex_areas_cm2):
    areas = np.asarray(vertex_areas_cm2, dtype=float)
    if areas.ndim != 1 or not np.all(np.isfinite(areas)) or np.any(areas < 0):
        raise ValueError("invalid vertex area weights")
    ids = np.unique(np.concatenate([np.asarray(p, dtype=int) for p in patches]))
    if ids.size and (ids.min() < 0 or ids.max() >= len(areas)):
        raise ValueError("patch index out of range")
    return float(areas[ids].sum())


def fit_union_radius(distances, vertex_areas_cm2, cap_cm2):
    """Largest distance shell whose exact discrete union weight stays under cap.

    Equal-distance shells are included together. Disconnected/unreachable
    vertices remain excluded. Returns actual area and cap shortfall explicitly.
    """
    d = np.asarray(distances, float)
    areas = np.asarray(vertex_areas_cm2, float)
    if d.ndim != 2 or d.shape[1] != len(areas) or not d.shape[0] or np.any(np.isnan(d)) or np.any(d < 0):
        raise ValueError("invalid center distance bank")
    if areas.ndim != 1 or not np.all(np.isfinite(areas)) or np.any(areas < 0):
        raise ValueError("invalid area weights")
    if not np.isfinite(cap_cm2) or cap_cm2 <= 0:
        raise ValueError("area cap must be positive finite")
    minimum = np.min(d, axis=0)
    valid = np.flatnonzero(np.isfinite(minimum))
    shells, inverse = np.unique(minimum[valid], return_inverse=True)
    cumulative = np.cumsum(np.bincount(inverse, weights=areas[valid], minlength=len(shells)))
    feasible = np.flatnonzero(cumulative <= cap_cm2 + 1e-10)
    if not len(feasible):
        return None
    radius = float(shells[feasible[-1]])
    patches = tuple(np.flatnonzero(row <= radius) for row in d)
    actual = union_area_cm2(patches, areas)
    return radius, patches, actual


def center_combinations(vertices, centers, region_count, maximum, seed):
    """Deterministic nested master list mixing spread and seeded random sets.

    Unlike a permutation beam, geometrically duplicate sets are not repeatedly
    evaluated. The largest regional allocations are assigned by sorted center
    ID; this restricted assignment is stated in the report, not globally optimal.
    """
    vertices, centers = np.asarray(vertices), np.asarray(centers, int)
    if region_count < 1 or region_count > len(centers) or maximum < 1:
        raise ValueError("invalid combination request")
    pairwise = np.linalg.norm(vertices[centers, None] - vertices[centers][None], axis=2)
    rng = np.random.default_rng(seed)
    anchors = rng.permutation(len(centers))
    result, seen = [], set()
    for anchor in anchors:
        chosen = [int(anchor)]
        while len(chosen) < region_count:
            score = pairwise[:, chosen].min(axis=1)
            score[chosen] = -1
            chosen.append(int(np.argmax(score)))
        value = tuple(sorted(int(centers[i]) for i in chosen))
        if value not in seen:
            result.append(value)
            seen.add(value)
        if len(result) >= maximum:
            return tuple(result)
    for _ in range(maximum * 100):
        value = tuple(sorted(int(x) for x in rng.choice(centers, region_count, replace=False)))
        if value not in seen:
            result.append(value)
            seen.add(value)
        if len(result) >= maximum:
            break
    return tuple(result)


def nested_coarse_bank(vertices, bank_ids, target_count):
    """Deterministic chord farthest-point subset, genuinely contained in full bank."""
    xyz = np.asarray(vertices)[np.asarray(bank_ids, int)]
    if not 64 <= target_count <= len(xyz):
        raise ValueError("invalid coarse target")
    selected = np.zeros(len(xyz), bool)
    best = np.full(len(xyz), np.inf)
    current = int(np.argmax(xyz[:, 2]))
    for _ in range(target_count):
        selected[current] = True
        best = np.minimum(best, np.sum((xyz - xyz[current]) ** 2, axis=1))
        best[selected] = -1
        current = int(np.argmax(best))
    return np.flatnonzero(selected)


@dataclass
class AreaDomain:
    vertices: np.ndarray
    adjacency: csr_matrix
    bank_ids: np.ndarray
    vertex_areas: np.ndarray
    roi_mask: np.ndarray
    center_ids: np.ndarray

    def __post_init__(self):
        self.vertices = np.asarray(self.vertices, float)
        self.bank_ids = np.asarray(self.bank_ids, int)
        self.vertex_areas = np.asarray(self.vertex_areas, float)
        self.roi_mask = np.asarray(self.roi_mask, bool)
        self.center_ids = np.asarray(self.center_ids, int)
        if not np.all(self.roi_mask[self.center_ids]):
            raise ValueError("center outside ROI")
        graph = self.adjacency.tocoo()
        keep = self.roi_mask[graph.row] & self.roi_mask[graph.col]
        self.graph = csr_matrix((graph.data[keep], (graph.row[keep], graph.col[keep])), shape=graph.shape)
        self.distances = dijkstra(self.graph, directed=False, indices=self.center_ids)
        self.center_rows = {int(c): i for i, c in enumerate(self.center_ids)}
        self._patch_cache = {}

    def patches(self, centers, cap_cm2, *, require_disconnected_regions=False):
        key = (tuple(centers), float(cap_cm2), bool(require_disconnected_regions))
        if key not in self._patch_cache:
            d = self.distances[[self.center_rows[int(c)] for c in centers]]
            fit = fit_union_radius(d, self.vertex_areas, cap_cm2)
            if fit is None:
                self._patch_cache[key] = None
            else:
                radius, patches, actual = fit
                area_only_radius = radius
                if require_disconnected_regions:
                    minimum = d.min(axis=0)
                    shells = np.unique(minimum[minimum <= radius])
                    def separated(shell_index):
                        union_ids = np.flatnonzero(minimum <= shells[shell_index])
                        return connected_components(self.graph[union_ids][:, union_ids], directed=False)[0] == len(centers)
                    if not separated(0):
                        self._patch_cache[key] = None
                        return None
                    # Each disk grows connected from its center. Union component
                    # count can only decrease, so the last separated shell is
                    # found by a monotone binary search before first disk merge.
                    lo, hi = 0, len(shells) - 1
                    while lo < hi:
                        middle = (lo + hi + 1) // 2
                        if separated(middle):
                            lo = middle
                        else:
                            hi = middle - 1
                    radius = float(shells[lo])
                    patches = tuple(np.flatnonzero(row <= radius) for row in d)
                    actual = union_area_cm2(patches, self.vertex_areas)
                bank_pools = tuple(np.flatnonzero(np.isin(self.bank_ids, p)) for p in patches)
                union = np.unique(np.concatenate(patches))
                components = int(connected_components(self.graph[union][:, union], directed=False)[0])
                self._patch_cache[key] = {"radius_m": radius, "patches": patches, "bank_pools": bank_pools,
                    "union_area_cm2": actual, "region_areas_cm2": [float(self.vertex_areas[p].sum()) for p in patches],
                    "union_connected_component_count": components, "cap_shortfall_cm2": float(cap_cm2 - actual)}
                self._patch_cache[key]["radius_limited_by_separation"] = bool(radius < area_only_radius)
        return self._patch_cache[key]

    def validate(self, snapshot, cap_cm2, spacing_m, allowed_bank_rows, *, require_disconnected_regions=False):
        ids = np.asarray(snapshot["candidate_bank_indices"], int)
        labels = np.asarray(snapshot["region_indices"], int)
        centers = tuple(int(c) for c in snapshot["centers"])
        if ids.shape != (64,) or len(np.unique(ids)) != 64 or labels.shape != (64,) or len(set(centers)) != len(centers):
            raise ValueError("invalid64 layout")
        allocation = balanced_region_point_counts(len(centers))
        if np.any(labels < 0) or np.any(labels >= len(centers)) or tuple(np.bincount(labels, minlength=len(centers))) != allocation:
            raise ValueError("regional allocation mismatch")
        if not np.all(np.isin(ids, allowed_bank_rows)):
            raise ValueError("layout outside allowed candidate density")
        xyz = self.vertices[self.bank_ids[ids]]
        distances = np.linalg.norm(xyz[:, None] - xyz[None], axis=2)
        gap = float(distances[np.triu_indices(64, 1)].min())
        if gap + 1e-12 < spacing_m:
            raise ValueError("spacing violation")
        patch = self.patches(centers, cap_cm2, require_disconnected_regions=require_disconnected_regions)
        if patch is None or patch["union_area_cm2"] > cap_cm2 + 1e-8:
            raise ValueError("area cap violation")
        for region, pool in enumerate(patch["bank_pools"]):
            if not np.all(np.isin(ids[labels == region], pool)):
                raise ValueError("electrode leaves connected ROI disk")
        return {"valid": True, "minimum_chord_distance_mm": gap * 1000,
            "union_area_cm2": patch["union_area_cm2"], "sum_region_areas_cm2": sum(patch["region_areas_cm2"]),
            "overlap_counted_once_cm2": sum(patch["region_areas_cm2"]) - patch["union_area_cm2"],
            "region_areas_cm2": patch["region_areas_cm2"], "common_graph_radius_mm": patch["radius_m"] * 1000,
            "cap_shortfall_cm2": patch["cap_shortfall_cm2"],
            "union_connected_component_count": patch["union_connected_component_count"],
            "radius_limited_by_separation": patch["radius_limited_by_separation"],
            "area_cap_utilization": patch["union_area_cm2"] / cap_cm2,
            "area_matched_within_1percent": bool(patch["union_area_cm2"] / cap_cm2 >= .99),
            "actual_region_counts": list(allocation)}


def _initial_layout(domain, centers, patch, allowed, spacing, trial, rng):
    allocation = balanced_region_point_counts(len(centers))
    pools = [np.intersect1d(pool, allowed) for pool in patch["bank_pools"]]
    selected, labels, achieved = [], [], np.zeros(len(centers), int)
    order = np.arange(len(centers)) if trial == 0 else rng.permutation(len(centers))
    xyz = domain.vertices[domain.bank_ids]
    for region in order:
        pool = pools[region]
        if not len(pool):
            break
        # Seed first center-nearest, then deterministic farthest or seeded random.
        if trial == 0:
            first = int(pool[np.argmin(np.linalg.norm(xyz[pool] - domain.vertices[centers[region]], axis=1))])
        else:
            first = int(rng.choice(pool))
        local = []
        while len(local) < allocation[region]:
            candidates = pool[~np.isin(pool, selected)]
            if selected and len(candidates):
                gap = np.min(np.linalg.norm(xyz[candidates, None] - xyz[np.asarray(selected)][None], axis=2), axis=1)
                candidates = candidates[gap + 1e-12 >= spacing]
            if not len(candidates):
                break
            if not local and first in candidates:
                point = first
            elif selected:
                gap = np.min(np.linalg.norm(xyz[candidates, None] - xyz[np.asarray(selected)][None], axis=2), axis=1)
                point = int(candidates[np.argmax(gap)])
            else:
                point = int(candidates[0])
            selected.append(point)
            local.append(point)
            labels.append(int(region))
        achieved[region] = len(local)
        if len(local) != allocation[region]:
            break
    if len(selected) != 64:
        return None, achieved.tolist()
    return {"candidate_bank_indices": selected, "region_indices": labels, "centers": list(centers)}, achieved.tolist()


def search_area_condition(domain, engine, *, region_count, cap_cm2, allowed_bank_rows,
                          master_combinations, center_limit, seed, spacing_m=.004,
                          geometry_restarts=2, sweeps=1, proposals=12, warm_starts=(),
                          require_disconnected_regions=False):
    """Search a nested prefix; retain/recheck all supplied feasible incumbents."""
    allowed = np.asarray(allowed_bank_rows, int)
    if len(allowed) < 64 or len(np.unique(allowed)) != len(allowed):
        raise ValueError("allowed bank must contain >=64 unique rows")
    started, attempts, trace_records, warm_records = [], [], [], []
    evaluated = {"geometry_trials": 0, "field_scores": 0, "coordinate_proposals": 0}

    def scored(snapshot):
        validation = domain.validate(snapshot, cap_cm2, spacing_m, allowed, require_disconnected_regions=require_disconnected_regions)
        if require_disconnected_regions and validation["union_connected_component_count"] != region_count:
            raise ValueError("nominal regions overlap or touch; physical region count differs")
        state = engine.make_state(snapshot["candidate_bank_indices"], snr_db=20)
        sensitivity = engine.sensitivity_tail(state.indices)
        evaluated["field_scores"] += 1
        return {**snapshot, "field20": float(state.field_relative), "sensitivity_tail": float(sensitivity),
            "geometry": validation, "xyz_mm": (domain.vertices[domain.bank_ids[state.indices]] * 1000).tolist()}, state

    for index, warm in enumerate(warm_starts):
        try:
            snapshot, state = scored(warm)
            if len(snapshot["centers"]) != region_count:
                raise ValueError("warm region count differs")
            started.append(snapshot)
            warm_records.append({"index": index, "accepted": True, "field20": snapshot["field20"], "sensitivity_tail": snapshot["sensitivity_tail"]})
        except (ValueError, KeyError, IndexError) as error:
            warm_records.append({"index": index, "accepted": False, "reason": str(error)})
    for ci, centers in enumerate(master_combinations[:center_limit]):
        patch = domain.patches(centers, cap_cm2, require_disconnected_regions=require_disconnected_regions)
        if patch is None:
            attempts.append({"centers": list(centers), "status": "no_radius_satisfying_area_and_region_component_constraints"})
            continue
        if require_disconnected_regions and patch["union_connected_component_count"] != region_count:
            attempts.append({"centers": list(centers), "status": "regions_overlap_or_touch",
                "requested_regions": region_count, "actual_union_components": patch["union_connected_component_count"],
                "union_area_cm2": patch["union_area_cm2"]})
            continue
        for trial in range(geometry_restarts):
            rng = np.random.default_rng(np.random.SeedSequence([seed, ci, trial]))
            snapshot, achieved = _initial_layout(domain, centers, patch, allowed, spacing_m, trial, rng)
            evaluated["geometry_trials"] += 1
            attempts.append({"centers": list(centers), "trial": trial, "achieved": achieved,
                "status": "complete" if snapshot else "no_complete_layout_under_bounded_construction",
                "union_area_cm2": patch["union_area_cm2"], "radius_mm": patch["radius_m"] * 1000})
            if snapshot:
                snapshot, state = scored(snapshot)
                started.append(snapshot)
    if not started:
        return {"status": "no_complete_layout_constructed", "finalists": [], "attempts": attempts,
            "warm_validation": warm_records, "counts": evaluated, "global_optimum_certified": False, "infeasibility_certified": False}
    finalists = []
    xyz = domain.vertices[domain.bank_ids]
    for objective_index, objective in enumerate(("field20", "min_field_sensitivity20")):
        def value(s):
            return s["field20"] if objective == "field20" else min(s["field20"], s["sensitivity_tail"])
        initial = max(started, key=value)
        current = dict(initial)
        ids = np.asarray(current["candidate_bank_indices"], int).copy()
        labels = np.asarray(current["region_indices"], int)
        patch = domain.patches(current["centers"], cap_cm2, require_disconnected_regions=require_disconnected_regions)
        state = engine.make_state(ids, snr_db=20)
        rng = np.random.default_rng(np.random.SeedSequence([seed, objective_index, center_limit, len(allowed)]))
        trace = []
        for sweep in range(sweeps):
            for position in rng.permutation(64):
                position = int(position)
                pool = np.intersect1d(patch["bank_pools"][labels[position]], allowed)
                pool = pool[~np.isin(pool, ids)]
                if len(pool):
                    gap = np.min(np.linalg.norm(xyz[pool, None] - xyz[np.delete(ids, position)][None], axis=2), axis=1)
                    pool = pool[gap + 1e-12 >= spacing_m]
                choices = _mixed_proposals(xyz, pool, int(ids[position]), proposals, rng)
                if not len(choices):
                    continue
                exchange = engine.score_exchanges(state, position, choices, include_sensitivity=objective_index == 1)
                scores = exchange.field_relative if objective_index == 0 else np.minimum(exchange.field_relative, exchange.sensitivity_tail)
                evaluated["coordinate_proposals"] += len(choices)
                best = int(np.argmax(scores))
                if not np.isfinite(scores[best]) or scores[best] <= value(current) + 1e-9:
                    continue
                updated_ids = ids.copy()
                updated_ids[position] = choices[best]
                candidate, candidate_state = scored({**current, "candidate_bank_indices": updated_ids.tolist()})
                if value(candidate) <= value(current) + 1e-9:
                    continue
                trace.append({"sweep": sweep, "position": position, "old_bank_row": int(ids[position]),
                    "new_bank_row": int(choices[best]), "before": value(current), "after": value(candidate)})
                current, state, ids = candidate, candidate_state, updated_ids
        if value(current) + 1e-9 < max(value(s) for s in started):
            raise RuntimeError("inherited incumbent was lost")
        finalists.append({"objective": objective, "initial_score": value(initial), "final_score": value(current),
            "initial": initial, "final": current, "trace": trace})
    return {"status": "completed_best_found", "finalists": finalists, "attempts": attempts,
        "warm_validation": warm_records, "counts": evaluated, "center_limit": center_limit,
        "candidate_count": len(allowed), "geometry_restarts": geometry_restarts, "coordinate_sweeps": sweeps,
        "proposals_per_position": proposals, "seed": seed, "global_optimum_certified": False,
        "infeasibility_certified": False, "localization_optimized": False}
