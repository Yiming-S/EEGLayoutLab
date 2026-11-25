"""Local, bounded fixed-64 radius-cap design computation on the frozen Ernie bank.

This module does not write experiment pointers or results. It is an exploratory
single-model computation, not an independent-head test or an optimality proof.
Region disks follow ROI-restricted edge paths; their union must have exactly R
components on the ORIGINAL scalp adjacency, including edges crossing ROI labels.

Search version 6 builds on convergent Fedorov + center shift + adaptive quota:
1. Successive-halving multi-start screening across diverse region-center tuples.
2. Full-pool exact CVaR-pruned Fedorov coordinate ascent until 1-opt convergence.
3. Joint region-center shifting with out-of-disk Schur/tail auto-repair and polish.
4. Targeted local paired 2-swap unjamming for tightly packed 4 mm electrode pairs.
5. Optional cross-region adaptive channel quota optimization (``allocation_mode="adaptive"``).
6. Optional subspace-information composite objective (``objective_mode="composite"``),
   combining lower-tail amplitude retention, LMMSE target-field retention, and
   63D reference-free Shannon mutual information with exact two-stage Schur + CVaR pruning.
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
from .layout_search_metrics import COMPOSITE_WEIGHTS, STAGE_MARGIN_WEIGHT, LayoutSearchMetrics, combine_search_objective
from .multiregion_geometry import balanced_region_point_counts, bounded_center_combinations
from .multiregion_search import _mixed_proposals
from .packing_pilot import build_surface_edge_graph
from .prototype_localization import evaluate_grid_localization
from . import noise_models
from .surface import vertex_area_weights

ALGORITHM_VERSION = "strict-radius-local/7-variable-k-composite-adaptive-fedorov"
MIN_ADAPTIVE_REGION_ELECTRODES = 4
ELECTRODE_COUNTS = (8, 12, 16, 24, 32, 48, 64)
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
SEARCH_BUDGET = {
    "center_combinations": 16,
    "initial_center_combinations": 24,
    "geometry_restarts": 2,
    "adaptive_waterfill_tuples": 6,
    "screen_starts": 6,
    "margin_screen_starts": 6,
    "retained_finalists": 2,
    "margin_retained_finalists": 2,
    "stage1_margin_shortlist_cap": 32,
    "stage_margin_weight": STAGE_MARGIN_WEIGHT,
    "outer_alternating_rounds": 4,
    "coordinate_sweeps": 8,
    "regional_polish_sweeps": 2,
    "coarse_center_proposals_per_region": 8,
    "fine_center_proposals_per_region": 6,
    "paired_2swap_pairs": 12,
    "paired_2swap_first_branch": 3,
    "min_adaptive_region_electrodes": MIN_ADAPTIVE_REGION_ELECTRODES,
    "composite_weights": list(COMPOSITE_WEIGHTS),
    "proposals_per_electrode": "full_eligible_region_or_union_pool",
    "exhaustive_center_tuple_limit": 256,
    "improvement_tolerance": 1e-7,
    "soft_deadline_seconds": 135.0,
}
SEED = 2026090901


def validate_request(raw):
    """Strict allow-list; never silently substitute an unsupported submask."""
    allowed_fields = {
        "region_count", "radius_mm", "mode", "mask_codes",
        "noise_model", "data_prior", "allocation_mode", "objective_mode", "electrode_count",
    }
    if not isinstance(raw, dict) or set(raw) - allowed_fields:
        raise ValueError("Request contains unsupported fields")
    # Default iid noise, balanced quota, min objective, and 64 electrodes are omitted so existing requests keep their canonical form and seed.
    noise = noise_models.normalize(raw.get("noise_model"), allow_brain_background=False)
    if "noise_model" in raw and (raw["noise_model"] is None or noise != raw["noise_model"]):
        raise ValueError("noise_model must be a non-default spatial preset in canonical form")
    prior = None
    if "data_prior" in raw:
        from .workflows.data_prior import canonical
        prior = canonical(raw["data_prior"])
        if prior != raw["data_prior"] or noise:
            raise ValueError("data_prior must be canonical and replaces noise_model")
    count, radius, mode = raw.get("region_count"), raw.get("radius_mm"), raw.get("mode")
    if type(count) is not int or count not in (1, 2, 3, 4, 6):
        raise ValueError("region_count must be one of 1, 2, 3, 4, 6")
    allocation_mode = None
    if "allocation_mode" in raw:
        if raw["allocation_mode"] != "adaptive":
            raise ValueError("allocation_mode must be 'adaptive' when provided; omit for balanced default")
        if count == 1:
            raise ValueError("allocation_mode 'adaptive' requires region_count >= 2")
        allocation_mode = "adaptive"
    objective_mode = None
    if "objective_mode" in raw:
        if raw["objective_mode"] != "composite":
            raise ValueError("objective_mode must be 'composite' when provided; omit for min default")
        objective_mode = "composite"
    electrode_count = None
    if "electrode_count" in raw:
        raw_ec = raw["electrode_count"]
        if type(raw_ec) is not int or raw_ec not in ELECTRODE_COUNTS or raw_ec == 64:
            raise ValueError("electrode_count must be one of 8, 12, 16, 24, 32, 48 when provided; omit for 64 default")
        min_req = count * MIN_ADAPTIVE_REGION_ELECTRODES if allocation_mode == "adaptive" else count * 2
        if raw_ec < min_req:
            raise ValueError(f"electrode_count {raw_ec} is too small for region_count={count} (minimum {min_req})")
        electrode_count = int(raw_ec)
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
    return {"region_count": count, "radius_mm": int(radius), "mode": mode, "mask_codes": list(codes),
            **({"noise_model": noise} if noise else {}), **({"data_prior": prior} if prior else {}),
            **({"allocation_mode": allocation_mode} if allocation_mode else {}),
            **({"objective_mode": objective_mode} if objective_mode else {}),
            **({"electrode_count": electrode_count} if electrode_count else {})}


SEED_NAMESPACE = "strict-radius-local/3-external-exposure"


def search_seed(request):
    """Search seed of a validated request; scoring/quota/objective/count modes share the same seed stream."""
    excluded = ("noise_model", "data_prior", "allocation_mode", "objective_mode", "electrode_count")
    canonical = json.dumps({k: v for k, v in request.items() if k not in excluded}, sort_keys=True, separators=(",", ":"))
    return int.from_bytes(hashlib.sha256((SEED_NAMESPACE + canonical).encode()).digest()[:4], "little")


def request_rois(request):
    return tuple(MASK_ROIS[c] for c in request["mask_codes"]) if request["mode"] == "preset" else (FREE_ROIS[request["mode"]],) * request["region_count"]


def _patch_pool_feasible(patch, allocation, adaptive_allocation, total_electrodes=64):
    if patch is None:
        return False
    pools = patch["bank_pools"]
    if adaptive_allocation:
        return sum(len(p) for p in pools) >= total_electrodes and all(len(p) >= MIN_ADAPTIVE_REGION_ELECTRODES for p in pools)
    return all(len(p) >= req for p, req in zip(pools, allocation, strict=True))


def _signal_aware_center_shortlist(vertices, choices, rois, identical, limit, seed, domain, signal_power, *,
                                   adaptive_allocation=False, total_electrodes=64, engine=None, use_margin_proxy=False):
    """Combine geometric spread tuples with leadfield-power-ranked feasible tuples."""
    allocation = balanced_region_point_counts(len(rois), total_physical_nodes=total_electrodes)
    pool_cap = max(limit * 4, 96)
    if identical:
        raw_pool = list(center_combinations(vertices, np.asarray(choices[0]), len(rois), pool_cap, seed))
    else:
        raw_pool = list(bounded_center_combinations(vertices, {roi: np.asarray(choices[i]) for i, roi in enumerate(rois)},
            rois, minimum_center_chord_distance_m=0., beam_width=max(256, pool_cap), maximum_combinations=pool_cap))
    center_power = {}
    for roi, c_list in zip(rois, choices):
        for c in c_list:
            key = (roi, int(c))
            if key not in center_power:
                row = domain.distances[roi][domain.center_rows[roi][int(c)]]
                in_disk = np.flatnonzero(np.isin(domain.bank_ids, np.flatnonzero(row <= domain.radius_m)))
                if len(in_disk):
                    cap_k = max(MIN_ADAPTIVE_REGION_ELECTRODES, (3 * total_electrodes) // 4) if adaptive_allocation else max(allocation)
                    top_k = min(len(in_disk), cap_k)
                    vals = np.partition(signal_power[in_disk], len(in_disk) - top_k)[len(in_disk) - top_k:]
                    center_power[key] = float(np.mean(vals))
                else:
                    center_power[key] = 0.0
    rng = np.random.default_rng(np.random.SeedSequence([seed, 77]))
    ranked_per_roi = [
        sorted(c_list, key=lambda c, r=roi: (-center_power[(r, int(c))], int(c)))
        for roi, c_list in zip(rois, choices)
    ]
    seen = set(raw_pool)
    for anchor_idx in range(min(12, len(ranked_per_roi[0]))):
        chosen = [int(ranked_per_roi[0][anchor_idx])]
        valid = True
        for r in range(1, len(rois)):
            cands = [int(c) for c in ranked_per_roi[r] if int(c) not in chosen]
            if not cands:
                valid = False
                break
            cands_arr = np.asarray(cands, dtype=np.int64)
            chords = np.min(np.linalg.norm(vertices[cands_arr, None] - vertices[np.asarray(chosen)][None], axis=2), axis=1)
            p_scores = np.array([center_power[(rois[r], int(c))] for c in cands])
            c_norm = chords / max(1e-9, float(chords.max()))
            p_norm = p_scores / max(1e-9, float(p_scores.max()))
            order = np.argsort(-(0.55 * c_norm + 0.45 * p_norm), kind="stable")
            pick = int(cands_arr[order[0 if anchor_idx < 6 else int(rng.integers(0, min(3, len(order))))]])
            chosen.append(pick)
        if valid:
            tup = tuple(sorted(chosen)) if identical else tuple(chosen)
            if tup not in seen:
                raw_pool.append(tup)
                seen.add(tup)

    scored_feasible = []
    for tup in raw_pool:
        patch = domain.patches(tup)
        if not _patch_pool_feasible(patch, allocation, adaptive_allocation, total_electrodes):
            continue
        pts = vertices[np.asarray(tup, dtype=np.int64)]
        spread = float(np.linalg.norm(pts[:, None] - pts[None], axis=2)[np.triu_indices(len(tup), 1)].min()) if len(tup) > 1 else 1.0
        if adaptive_allocation:
            anchor_means = []
            for pool in patch["bank_pools"]:
                vals = signal_power[pool]
                top_a = np.partition(vals, len(vals) - MIN_ADAPTIVE_REGION_ELECTRODES)[len(vals) - MIN_ADAPTIVE_REGION_ELECTRODES:]
                anchor_means.append(float(np.mean(top_a)))
            union_vals = np.concatenate([signal_power[p] for p in patch["bank_pools"]])
            top_union = np.partition(union_vals, len(union_vals) - total_electrodes)[len(union_vals) - total_electrodes:]
            composite = 0.60 * float(np.mean(top_union)) + 0.35 * min(anchor_means) + 0.05 * spread
        else:
            reg_means = []
            for pool, req in zip(patch["bank_pools"], allocation):
                vals = signal_power[pool]
                top = np.partition(vals, len(vals) - req)[len(vals) - req:]
                reg_means.append(float(np.mean(top)))
            composite = min(reg_means) + 0.35 * float(np.mean(reg_means)) + 0.05 * spread
        scored_feasible.append((composite, tup))
    if not scored_feasible:
        return tuple(raw_pool[:limit])
    scored_feasible.sort(key=lambda item: (-item[0], item[1]))
    if use_margin_proxy and engine is not None and engine.has_nonlocal_margin and total_electrodes >= 3:
        xyz_bank = domain.vertices[domain.bank_ids]
        cap_m = min(len(scored_feasible), int(SEARCH_BUDGET["stage1_margin_shortlist_cap"]))
        top_p = np.asarray([s for s, _ in scored_feasible[:cap_m]], dtype=float)
        p_span = max(1e-9, float(top_p.max() - top_p.min()))
        reranked = []
        for p_val, tup in scored_feasible[:cap_m]:
            patch = domain.patches(tup)
            sample_ids = []
            per_reg = [MIN_ADAPTIVE_REGION_ELECTRODES] * len(rois) if adaptive_allocation else list(allocation)
            for r_i, req_r in enumerate(per_reg):
                pool = patch["bank_pools"][r_i]
                pool_set = set(map(int, pool))
                for cand_b in pool[np.argsort(-signal_power[pool], kind="stable")]:
                    if len(sample_ids) and np.min(np.sum((xyz_bank[np.asarray(sample_ids)] - xyz_bank[int(cand_b)]) ** 2, axis=1)) < .004 ** 2:
                        continue
                    sample_ids.append(int(cand_b))
                    if sum(1 for x in sample_ids if x in pool_set) >= req_r:
                        break
            if len(sample_ids) < total_electrodes:
                u_pool = np.concatenate(patch["bank_pools"])
                for cand_b in u_pool[np.argsort(-signal_power[u_pool], kind="stable")]:
                    if int(cand_b) in sample_ids:
                        continue
                    if len(sample_ids) and np.min(np.sum((xyz_bank[np.asarray(sample_ids)] - xyz_bank[int(cand_b)]) ** 2, axis=1)) < .004 ** 2:
                        continue
                    sample_ids.append(int(cand_b))
                    if len(sample_ids) >= total_electrodes:
                        break
            m_score = engine.nonlocal_confusion_margin(sample_ids[:total_electrodes], snr_db=20) if len(sample_ids) >= 3 else 0.0
            p_norm = (p_val - float(top_p.min())) / p_span
            reranked.append((0.60 * p_norm + 0.40 * float(m_score or 0.0), tup))
        reranked.sort(key=lambda item: (-item[0], item[1]))
        scored_feasible = reranked + scored_feasible[cap_m:]
    selected, picked = [], set()
    half = max(1, (2 * limit) // 3)
    for _, tup in scored_feasible[:half]:
        selected.append(tup)
        picked.add(tup)
    feasible_set = {item[1] for item in scored_feasible}
    for tup in raw_pool:
        if len(selected) >= limit:
            break
        if tup not in picked and tup in feasible_set:
            selected.append(tup)
            picked.add(tup)
    for _, tup in scored_feasible:
        if len(selected) >= limit:
            break
        if tup not in picked:
            selected.append(tup)
            picked.add(tup)
    return tuple(selected[:limit])


def select_radius_center_combinations(vertices, centers, region_rois, seed, *,
                                      maximum_combinations=None, domain=None, signal_power=None,
                                      adaptive_allocation=False, total_electrodes=64,
                                      engine=None, use_margin_proxy=False):
    """Exhaust small frozen center spaces; retain bounded or signal-aware shortlist on large spaces."""
    rois = tuple(region_rois)
    if not rois:
        raise ValueError("region_rois must not be empty")
    limit = int(SEARCH_BUDGET["center_combinations"] if maximum_combinations is None else maximum_combinations)
    choices = tuple(tuple(sorted(set(int(c) for c in centers[roi]))) for roi in rois)
    identical = len(set(rois)) == 1
    space_size = math.comb(len(choices[0]), len(rois)) if identical else math.prod(map(len, choices))
    exhaustive = space_size <= SEARCH_BUDGET["exhaustive_center_tuple_limit"]
    duplicate_rejections = None
    method = "exhaustive_finite_center_tuples" if exhaustive else "bounded_center_shortlist"
    if exhaustive:
        raw = itertools.combinations(choices[0], len(rois)) if identical else itertools.product(*choices)
        combinations = tuple(c for c in raw if len(set(c)) == len(c))
        duplicate_rejections = space_size - len(combinations)
    elif domain is not None and signal_power is not None:
        combinations = _signal_aware_center_shortlist(
            vertices, choices, rois, identical, limit, seed, domain, signal_power,
            adaptive_allocation=adaptive_allocation, total_electrodes=total_electrodes,
            engine=engine, use_margin_proxy=use_margin_proxy)
        method = (
            "signal_spread_and_dictionary_margin_shortlist"
            if (use_margin_proxy and engine is not None and engine.has_nonlocal_margin)
            else "signal_and_spread_bounded_center_shortlist"
        )
    elif identical:
        combinations = center_combinations(vertices, np.asarray(choices[0]), len(rois), limit, seed)
    else:
        combinations = bounded_center_combinations(vertices, centers, rois,
            minimum_center_chord_distance_m=0., beam_width=max(256, limit),
            maximum_combinations=limit)
    selection = {
        "method": method,
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

    def validate(self, snapshot, *, spacing_m=.004, adaptive_allocation=False, total_electrodes=64):
        ids = _integer_vector(snapshot["candidate_bank_indices"], len(self.bank_ids), "layout bank indices")
        labels = _integer_vector(snapshot["region_indices"], len(self.region_rois), "region labels")
        centers = tuple(int(c) for c in snapshot["centers"])
        if len(ids) != total_electrodes or len(labels) != total_electrodes or len(np.unique(ids)) != total_electrodes:
            raise ValueError(f"Layout requires {total_electrodes} unique physical points")
        counts = np.bincount(labels, minlength=len(self.region_rois)).tolist()
        if adaptive_allocation:
            if sum(counts) != total_electrodes or any(c < MIN_ADAPTIVE_REGION_ELECTRODES for c in counts):
                raise ValueError("Adaptive regional allocation floor violated")
        elif counts != list(balanced_region_point_counts(len(self.region_rois), total_physical_nodes=total_electrodes)):
            raise ValueError("Balanced regional allocation violated")
        xyz = self.vertices[self.bank_ids[ids]]
        gap = float(np.linalg.norm(xyz[:, None] - xyz[None], axis=2)[np.triu_indices(total_electrodes, 1)].min())
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


def _eligible_pool_by_spacing(xyz, pool, occupied_ids, spacing_m=.004):
    """Filter candidate bank indices in pool that are >= spacing_m from occupied_ids."""
    pool = np.asarray(pool, dtype=np.int64)
    if not len(pool):
        return pool
    occupied = np.asarray(occupied_ids, dtype=np.int64)
    if not len(occupied):
        return pool
    pool = pool[~np.isin(pool, occupied)]
    if not len(pool):
        return pool
    d2 = np.min(np.sum((xyz[pool, None, :] - xyz[occupied][None, :, :]) ** 2, axis=2), axis=1)
    return pool[np.sqrt(d2) + 1e-12 >= spacing_m]


def _pack_region_with_backtrack(xyz, pool, needed, blocked_ids, spacing_m, rng, *,
                                repair_depth=2, branch_width=3, max_nodes=64):
    """Maximin chord packing of ``needed`` points in ``pool`` with bounded tail repair."""
    eligible0 = _eligible_pool_by_spacing(xyz, pool, blocked_ids, spacing_m)
    if len(eligible0) < needed:
        return None
    if needed == 0:
        return []
    first = int(rng.choice(eligible0))
    selected = [first]
    while len(selected) < needed:
        cand = _eligible_pool_by_spacing(xyz, eligible0, selected, spacing_m)
        if not len(cand):
            break
        d2 = np.min(np.sum((xyz[cand, None, :] - xyz[np.asarray(selected)][None, :, :]) ** 2, axis=2), axis=1)
        selected.append(int(cand[int(np.argmax(d2))]))
    if len(selected) == needed:
        return selected
    cut = min(repair_depth, len(selected))
    prefix = selected[:-cut]
    visited = 0

    def dfs(curr):
        nonlocal visited
        if len(curr) == needed:
            return curr
        if visited >= max_nodes:
            return None
        visited += 1
        cand = _eligible_pool_by_spacing(xyz, eligible0, curr, spacing_m)
        if len(cand) < needed - len(curr):
            return None
        if curr:
            d2 = np.min(np.sum((xyz[cand, None, :] - xyz[np.asarray(curr)][None, :, :]) ** 2, axis=2), axis=1)
            order = np.argsort(-d2, kind="stable")[:branch_width]
        else:
            order = rng.permutation(len(cand))[:branch_width]
        for idx in order:
            res = dfs(curr + [int(cand[int(idx)])])
            if res is not None:
                return res
        return None

    return dfs(prefix)


def _patch_union_lookup(patch, total_bank_size):
    """Disjoint union of region bank pools and O(1) bank-index -> region lookup array."""
    union_pool = np.concatenate(patch["bank_pools"]).astype(np.int64, copy=False)
    bank_to_region = np.full(total_bank_size, -1, dtype=np.int64)
    for r, pool in enumerate(patch["bank_pools"]):
        bank_to_region[pool] = int(r)
    return union_pool, bank_to_region


def _initial_adaptive_layout(xyz, centers, patch, signal_power, spacing_m, trial, rng, *,
                             engine=None, objective_mode="min", total_electrodes=64):
    """Construct a K-electrode layout with >= 4 anchors per region and adaptive union quota."""
    n_reg = len(centers)
    union_pool, bank_to_region = _patch_union_lookup(patch, len(xyz))
    selected, labels_acc = [], []
    reg_order = (
        sorted(range(n_reg), key=lambda r: (len(patch["bank_pools"][r]), r))
        if trial == 0 else [int(r) for r in rng.permutation(n_reg)]
    )
    for r in reg_order:
        packed = _pack_region_with_backtrack(
            xyz, patch["bank_pools"][r], MIN_ADAPTIVE_REGION_ELECTRODES, selected, spacing_m, rng)
        if packed is None:
            return None, [0] * n_reg, 0
        selected.extend(packed)
        labels_acc.extend([r] * len(packed))

    rem = total_electrodes - len(selected)
    proposals_added = 0
    if engine is not None:
        use_info = objective_mode == "composite"
        for step in range(rem):
            cand = _eligible_pool_by_spacing(xyz, union_pool, selected, spacing_m)
            if len(cand) < rem - step:
                selected = selected[:n_reg * MIN_ADAPTIVE_REGION_ELECTRODES]
                labels_acc = labels_acc[:n_reg * MIN_ADAPTIVE_REGION_ELECTRODES]
                break
            p_state = engine.make_partial_state(selected, snr_db=20)
            f_scores = engine.score_additions(p_state, cand, include_sensitivity=False, include_information=use_info)
            proposals_added += len(f_scores.candidate_indices)
            if not len(f_scores.candidate_indices):
                break
            merit = (
                0.65 * f_scores.field_relative + 0.35 * f_scores.information_relative
                if use_info else f_scores.field_relative
            )
            best_idx = int(np.argmax(merit))
            chosen = int(f_scores.candidate_indices[best_idx])
            selected.append(chosen)
            labels_acc.append(int(bank_to_region[chosen]))

    if len(selected) < total_electrodes:
        while len(selected) < total_electrodes:
            cand = _eligible_pool_by_spacing(xyz, union_pool, selected, spacing_m)
            if not len(cand):
                break
            d = np.sqrt(np.min(np.sum((xyz[cand, None, :] - xyz[np.asarray(selected)][None, :, :]) ** 2, axis=2), axis=1))
            if trial == 1 and signal_power is not None:
                d_norm = d / max(1e-9, float(d.max()))
                s_vals = signal_power[cand]
                s_norm = s_vals / max(1e-9, float(s_vals.max()))
                pick_idx = int(np.argmax(0.55 * d_norm + 0.45 * s_norm))
            else:
                pick_idx = int(np.argmax(d))
            chosen = int(cand[pick_idx])
            selected.append(chosen)
            labels_acc.append(int(bank_to_region[chosen]))

    if len(selected) < total_electrodes:
        anchors = selected[:n_reg * MIN_ADAPTIVE_REGION_ELECTRODES]
        anchor_labels = labels_acc[:n_reg * MIN_ADAPTIVE_REGION_ELECTRODES]
        packed_rem = _pack_region_with_backtrack(
            xyz, union_pool, total_electrodes - len(anchors), anchors, spacing_m, rng,
            repair_depth=3, branch_width=4, max_nodes=96)
        if packed_rem is None:
            return None, np.bincount(labels_acc, minlength=n_reg).tolist(), proposals_added
        selected = anchors + packed_rem
        labels_acc = anchor_labels + [int(bank_to_region[b]) for b in packed_rem]

    order = np.argsort(np.asarray(labels_acc, dtype=np.int64), kind="stable")
    ordered_ids = [int(selected[int(k)]) for k in order]
    ordered_labels = [int(labels_acc[int(k)]) for k in order]
    counts = np.bincount(ordered_labels, minlength=n_reg).tolist()
    return (
        {"candidate_bank_indices": ordered_ids, "region_indices": ordered_labels, "centers": list(centers)},
        counts,
        proposals_added,
    )


def _neighbor_center_proposals(domain, current_centers, region_r, outer_round, visited_centers, rng, signal_power=None):
    """Coarse-to-fine candidate centers for region_r on its ROI surface graph."""
    roi = domain.region_rois[region_r]
    all_centers = domain.centers[roi]
    occupied = set(int(c) for c in current_centers)
    cur_c = int(current_centers[region_r])
    candidates = np.asarray([int(c) for c in all_centers if int(c) not in occupied], dtype=np.int64)
    if not len(candidates):
        return ()
    g_dist = domain.distances[roi][domain.center_rows[roi][cur_c], candidates]
    reachable = candidates[np.isfinite(g_dist) & (g_dist > 0)]
    r_dist = g_dist[np.isfinite(g_dist) & (g_dist > 0)]
    chosen = []
    if outer_round == 0:
        limit = SEARCH_BUDGET["coarse_center_proposals_per_region"]
        if len(reachable):
            near_order = np.argsort(r_dist, kind="stable")
            for idx in near_order[:min(4, len(near_order))]:
                chosen.append(int(reachable[int(idx)]))
            rem = reachable[~np.isin(reachable, chosen)]
            if len(rem) and len(chosen) < limit:
                spread = _mixed_proposals(domain.vertices, rem, cur_c, limit - len(chosen), rng)
                chosen.extend(int(x) for x in spread)
        disconnected = candidates[~np.isfinite(g_dist)]
        if len(disconnected) and len(chosen) < limit + 2:
            if signal_power is not None:
                scores = []
                for c in disconnected:
                    row = domain.distances[roi][domain.center_rows[roi][int(c)]]
                    pool = np.flatnonzero(np.isin(domain.bank_ids, np.flatnonzero(row <= domain.radius_m)))
                    scores.append(float(np.mean(signal_power[pool])) if len(pool) else 0.0)
                d_order = np.argsort(-np.asarray(scores), kind="stable")[:2]
                chosen.extend(int(disconnected[int(i)]) for i in d_order)
            else:
                chosen.extend(int(x) for x in rng.choice(disconnected, min(2, len(disconnected)), replace=False))
    else:
        limit = SEARCH_BUDGET["fine_center_proposals_per_region"]
        if len(reachable):
            near_order = np.argsort(r_dist, kind="stable")[:limit]
            chosen.extend(int(reachable[int(i)]) for i in near_order)

    filtered = []
    for c in dict.fromkeys(chosen):
        trial = list(current_centers)
        trial[region_r] = int(c)
        key = tuple(trial)
        if key not in visited_centers:
            filtered.append(int(c))
    return tuple(filtered)


def bounded_radius_search(domain, engine, combinations, seed, progress=lambda **kwargs: None, *,
                          deadline_monotonic=None, adaptive_allocation=False, objective_mode="min",
                          total_electrodes=64, enable_localization_proxy=True):
    """Convergent Fedorov coordinate ascent + joint center shift + Stage 1/3 margin screening."""
    if objective_mode not in ("min", "composite"):
        raise ValueError(f"Unsupported objective_mode: {objective_mode}")
    if type(total_electrodes) is not int or not 2 <= total_electrodes <= 64:
        raise ValueError("total_electrodes must be an integer in [2, 64]")
    n_reg = len(domain.region_rois)
    adaptive = bool(adaptive_allocation and n_reg >= 2)
    use_margin_proxy = bool(
        enable_localization_proxy and objective_mode == "composite"
        and engine is not None and engine.has_nonlocal_margin and total_electrodes >= 3
    )
    margin_stats = {"enabled": use_margin_proxy, "stage1_evaluations": 0, "stage3_evaluations": 0, "elapsed_seconds": 0.0}
    allowed = np.arange(len(domain.bank_ids))
    allocation = balanced_region_point_counts(n_reg, total_physical_nodes=total_electrodes)
    tol = float(SEARCH_BUDGET["improvement_tolerance"])
    attempts, starts, trace = [], [], []
    scored_count, proposal_count = 0, 0
    pruning_totals = {"candidates": 0, "field_survivors": 0, "cvar_survivors": 0, "exact_tail_evals": 0}
    center_move_stats = {
        "evaluated": 0, "accepted": 0, "repaired_electrodes": 0,
        "paired_2swaps": 0, "cross_region_quota_transfers": 0,
    }
    signal_power = engine.diagonal_signal_power() if engine is not None else None

    def past_deadline():
        return deadline_monotonic is not None and time.perf_counter() >= deadline_monotonic

    def eval_stage_merit(snap, *, stage="stage1"):
        if not use_margin_proxy:
            snap["margin20"] = None
            snap["stage_merit"] = snap["objective"]
            return snap["objective"]
        if snap.get("margin20") is not None and snap.get("stage_merit") is not None:
            return float(snap["stage_merit"])
        t_m0 = time.perf_counter()
        m_val = float(engine.nonlocal_confusion_margin(
            snap["candidate_bank_indices"], snr_db=20, count=total_electrodes))
        margin_stats["elapsed_seconds"] += time.perf_counter() - t_m0
        margin_stats[f"{stage}_evaluations"] += 1
        merit = float((1.0 - STAGE_MARGIN_WEIGHT) * snap["objective"] + STAGE_MARGIN_WEIGHT * m_val)
        snap["margin20"] = m_val
        snap["stage_merit"] = merit
        return merit

    def score(snapshot):
        nonlocal scored_count
        geometry = domain.validate(snapshot, adaptive_allocation=adaptive, total_electrodes=total_electrodes)
        state = engine.make_state(snapshot["candidate_bank_indices"], snr_db=20, count=total_electrodes)
        sensitivity = engine.sensitivity_tail(state.indices, count=total_electrodes)
        if sensitivity is None or not np.isfinite(sensitivity) or not np.isfinite(state.field_relative):
            raise ValueError("Field/sensitivity numerical denominator is unavailable")
        scored_count += 1
        f_val = float(state.field_relative)
        s_val = float(sensitivity)
        i_val = float(state.information_relative)
        obj_val = combine_search_objective(f_val, s_val, i_val, objective_mode=objective_mode)
        return {
            **snapshot,
            "geometry": geometry,
            "field20": f_val,
            "info20": i_val,
            "sensitivity_tail": s_val,
            "min_field_sensitivity": float(min(f_val, s_val)),
            "objective": float(obj_val),
        }, state

    xyz = domain.vertices[domain.bank_ids]
    feasible_tuples_for_waterfill = []
    for i, centers in enumerate(combinations):
        patch = domain.patches(centers)
        progress(stage="geometry", message=f"筛查区域组合 {i + 1}/{len(combinations)}", progress=.20 + .20 * (i + 1) / max(1, len(combinations)))
        if patch is None:
            attempts.append({"centers": list(centers), "status": "no_separated_disks"})
            continue
        pool_counts = [len(pool) for pool in patch["bank_pools"]]
        if not _patch_pool_feasible(patch, allocation, adaptive, total_electrodes):
            attempts.append({"centers": list(centers), "status": "insufficient_bank_candidates",
                "bank_pool_counts": pool_counts,
                "required_region_counts": [MIN_ADAPTIVE_REGION_ELECTRODES] * n_reg if adaptive else list(allocation),
                "common_graph_radius_mm": patch["radius_m"] * 1000})
            continue
        best_tuple_obj = -1.0
        for trial in range(SEARCH_BUDGET["geometry_restarts"]):
            trial_rng = np.random.default_rng(np.random.SeedSequence([seed, i, trial]))
            if adaptive:
                snapshot, achieved, added_p = _initial_adaptive_layout(
                    xyz, centers, patch, signal_power, .004, trial, trial_rng,
                    objective_mode=objective_mode, total_electrodes=total_electrodes)
                proposal_count += added_p
            else:
                snapshot, achieved = _initial_layout(
                    domain, centers, patch, allowed, .004, trial, trial_rng, total_physical_nodes=total_electrodes)
                if snapshot is None:
                    selected, labels_acc, partial = [], [], []
                    ok = True
                    for r in (np.arange(len(centers)) if trial == 0 else trial_rng.permutation(len(centers))):
                        packed = _pack_region_with_backtrack(xyz, patch["bank_pools"][int(r)], int(allocation[int(r)]),
                                                             selected, .004, trial_rng)
                        if packed is None:
                            ok = False
                            partial.append(0)
                            break
                        selected.extend(packed)
                        labels_acc.extend([int(r)] * len(packed))
                        partial.append(len(packed))
                    if ok and len(selected) == total_electrodes:
                        snapshot = {"candidate_bank_indices": selected, "region_indices": labels_acc, "centers": list(centers)}
                        achieved = [int(allocation[r]) for r in range(len(centers))]
            attempts.append({"centers": list(centers), "trial": trial, "achieved": achieved,
                "common_graph_radius_mm": patch["radius_m"] * 1000,
                "status": "complete" if snapshot else "no_complete_layout_under_bounded_construction"})
            if snapshot:
                scored_pair = score(snapshot)
                starts.append(scored_pair)
                best_tuple_obj = max(best_tuple_obj, scored_pair[0]["objective"])
        if adaptive and best_tuple_obj >= 0.0:
            feasible_tuples_for_waterfill.append((best_tuple_obj, i, centers, patch))

    if adaptive and feasible_tuples_for_waterfill and not past_deadline():
        feasible_tuples_for_waterfill.sort(key=lambda item: (-item[0], item[1]))
        wf_targets = feasible_tuples_for_waterfill[:SEARCH_BUDGET["adaptive_waterfill_tuples"]]
        for wf_rank, (_, orig_i, centers, patch) in enumerate(wf_targets):
            if past_deadline():
                break
            progress(stage="geometry", message=f"跨区信息配额注水初始化 {wf_rank + 1}/{len(wf_targets)}",
                     progress=.40 + .05 * (wf_rank + 1) / max(1, len(wf_targets)))
            wf_rng = np.random.default_rng(np.random.SeedSequence([seed, 900, orig_i]))
            snapshot, achieved, added_p = _initial_adaptive_layout(
                xyz, centers, patch, signal_power, .004, 0, wf_rng,
                engine=engine, objective_mode=objective_mode, total_electrodes=total_electrodes)
            proposal_count += added_p
            attempts.append({"centers": list(centers), "trial": "schur_waterfill", "achieved": achieved,
                "common_graph_radius_mm": patch["radius_m"] * 1000,
                "status": "complete" if snapshot else "no_complete_layout_under_bounded_construction"})
            if snapshot:
                starts.append(score(snapshot))

    if not starts:
        return None, {"attempts": attempts, "trace": trace, "scored_layouts": scored_count,
            "coordinate_proposals": proposal_count, "allocation_mode": "adaptive" if adaptive else "balanced",
            "objective_mode": objective_mode, "physical_electrode_count": total_electrodes,
            "infeasibility_certified": False}

    def fedorov_ascent(current, state, patch, rng, *, active_positions=None, max_sweeps=8, phase="fedorov"):
        nonlocal proposal_count
        ids = np.asarray(current["candidate_bank_indices"], dtype=np.int64).copy()
        labels = np.asarray(current["region_indices"], dtype=np.int64).copy()
        reg_counts = np.bincount(labels, minlength=n_reg)
        union_pool, bank_to_region = _patch_union_lookup(patch, len(xyz)) if adaptive else (None, None)
        universe = np.arange(total_electrodes, dtype=np.int64) if active_positions is None else np.asarray(active_positions, dtype=np.int64)
        cert = engine.tail_dual_certificate(ids)
        dual_hint = (cert[1], cert[2]) if cert is not None else None
        change_epoch = 0
        checked_epoch = np.full(total_electrodes, -1, dtype=np.int64)
        local_moves = []
        converged = False
        for sweep in range(max_sweeps):
            if past_deadline():
                break
            sweep_moves = 0
            for pos in rng.permutation(universe):
                pos = int(pos)
                if checked_epoch[pos] == change_epoch:
                    continue
                r_old = int(labels[pos])
                others = np.delete(ids, pos)
                raw_pool = (
                    union_pool
                    if (adaptive and reg_counts[r_old] > MIN_ADAPTIVE_REGION_ELECTRODES)
                    else patch["bank_pools"][r_old]
                )
                pool = _eligible_pool_by_spacing(xyz, raw_pool, others, .004)
                if len(pool):
                    res = engine.best_pruned_exchange(
                        state, pos, pool, objective_floor=current["objective"],
                        tol=tol, dual_hint=dual_hint, objective_mode=objective_mode)
                    proposal_count += res.candidate_count
                    pruning_totals["candidates"] += res.candidate_count
                    pruning_totals["field_survivors"] += res.field_survivor_count
                    pruning_totals["cvar_survivors"] += res.cvar_survivor_count
                    pruning_totals["exact_tail_evals"] += res.exact_tail_evaluations
                    if res.best_candidate is not None:
                        new_bank = int(res.best_candidate)
                        r_new = int(bank_to_region[new_bank]) if adaptive else r_old
                        proposed_ids = ids.copy()
                        proposed_ids[pos] = new_bank
                        proposed_labels = labels.copy()
                        proposed_labels[pos] = r_new
                        candidate, candidate_state = score({
                            **current,
                            "candidate_bank_indices": proposed_ids.tolist(),
                            "region_indices": proposed_labels.tolist(),
                        })
                        if candidate["objective"] > current["objective"] + tol:
                            move_entry = {
                                "kind": "cross_region_quota_exchange" if r_new != r_old else "coordinate_exchange",
                                "phase": phase, "sweep": sweep,
                                "position": pos, "old_bank_row": int(ids[pos]), "new_bank_row": new_bank,
                                "before": current["objective"], "after": candidate["objective"],
                            }
                            if adaptive:
                                move_entry["old_region"] = r_old
                                move_entry["new_region"] = r_new
                            if r_new != r_old:
                                center_move_stats["cross_region_quota_transfers"] += 1
                            local_moves.append(move_entry)
                            reg_counts[r_old] -= 1
                            reg_counts[r_new] += 1
                            current, state, ids, labels = candidate, candidate_state, proposed_ids, proposed_labels
                            cert = engine.tail_dual_certificate(ids)
                            dual_hint = (cert[1], cert[2]) if cert is not None else None
                            change_epoch += 1
                            sweep_moves += 1
                checked_epoch[pos] = change_epoch
            if sweep_moves == 0:
                converged = active_positions is None
                break
        return current, state, local_moves, converged

    def schur_guided_refill(new_centers, new_patch, ids, labels, keep_mask):
        nonlocal proposal_count
        repaired_ids = ids.copy()
        repaired_labels = labels.copy()
        active_ids = ids[keep_mask].tolist()
        if adaptive:
            union_pool, bank_to_region = _patch_union_lookup(new_patch, len(xyz))
            evicted_slots = [int(s) for s in np.flatnonzero(~keep_mask)]
            kept_counts = [int(np.sum(keep_mask & (labels == r))) for r in range(n_reg)]
            slot_cursor = 0
            for r in sorted(range(n_reg), key=lambda reg: len(new_patch["bank_pools"][reg])):
                deficit = max(0, MIN_ADAPTIVE_REGION_ELECTRODES - kept_counts[r])
                for step in range(deficit):
                    rem_r = deficit - 1 - step
                    pool = _eligible_pool_by_spacing(xyz, new_patch["bank_pools"][r], active_ids, .004)
                    if len(pool) <= rem_r:
                        return None
                    if len(active_ids) < 2:
                        c_xyz = domain.vertices[int(new_centers[r])]
                        chosen = int(pool[int(np.argmin(np.sum((xyz[pool] - c_xyz) ** 2, axis=1)))])
                    else:
                        p_state = engine.make_partial_state(active_ids, snr_db=20)
                        res = engine.best_pruned_addition(
                            p_state, pool, objective_floor=-1.0, tol=0.0, objective_mode=objective_mode)
                        proposal_count += res.candidate_count
                        pruning_totals["candidates"] += res.candidate_count
                        pruning_totals["field_survivors"] += res.field_survivor_count
                        pruning_totals["cvar_survivors"] += res.cvar_survivor_count
                        pruning_totals["exact_tail_evals"] += res.exact_tail_evaluations
                        chosen = int(res.best_candidate) if res.best_candidate is not None else int(pool[0])
                    slot = evicted_slots[slot_cursor]
                    slot_cursor += 1
                    active_ids.append(chosen)
                    repaired_ids[slot] = chosen
                    repaired_labels[slot] = r
            for idx_u in range(slot_cursor, len(evicted_slots)):
                rem_u = len(evicted_slots) - 1 - idx_u
                pool = _eligible_pool_by_spacing(xyz, union_pool, active_ids, .004)
                if len(pool) <= rem_u:
                    return None
                p_state = engine.make_partial_state(active_ids, snr_db=20)
                res = engine.best_pruned_addition(
                    p_state, pool, objective_floor=-1.0, tol=0.0, objective_mode=objective_mode)
                proposal_count += res.candidate_count
                pruning_totals["candidates"] += res.candidate_count
                pruning_totals["field_survivors"] += res.field_survivor_count
                pruning_totals["cvar_survivors"] += res.cvar_survivor_count
                pruning_totals["exact_tail_evals"] += res.exact_tail_evaluations
                chosen = int(res.best_candidate) if res.best_candidate is not None else int(pool[0])
                slot = evicted_slots[idx_u]
                active_ids.append(chosen)
                repaired_ids[slot] = chosen
                repaired_labels[slot] = int(bank_to_region[chosen])
            return repaired_ids, repaired_labels

        evicted_by_reg = {
            r: np.flatnonzero((~keep_mask) & (labels == r))
            for r in range(len(allocation))
            if np.any((~keep_mask) & (labels == r))
        }
        ordered_regs = sorted(evicted_by_reg, key=lambda r: len(new_patch["bank_pools"][r]) / len(evicted_by_reg[r]))
        for r in ordered_regs:
            slots = evicted_by_reg[r]
            for idx_s, slot in enumerate(slots):
                rem_needed = len(slots) - 1 - idx_s
                pool = _eligible_pool_by_spacing(xyz, new_patch["bank_pools"][r], active_ids, .004)
                if len(pool) <= rem_needed:
                    return None
                if rem_needed > 0 and len(pool) <= 96:
                    d2 = np.sum((xyz[pool, None, :] - xyz[pool][None, :, :]) ** 2, axis=2)
                    compat = pool[np.sum(np.sqrt(d2) + 1e-12 >= .004, axis=1) >= rem_needed]
                    if len(compat):
                        pool = compat
                if len(active_ids) < 2:
                    if not active_ids:
                        c_xyz = domain.vertices[int(new_centers[r])]
                        chosen = int(pool[int(np.argmin(np.sum((xyz[pool] - c_xyz) ** 2, axis=1)))])
                    else:
                        chosen = int(pool[int(np.argmax(np.sum((xyz[pool] - xyz[active_ids[0]]) ** 2, axis=1)))])
                else:
                    p_state = engine.make_partial_state(active_ids, snr_db=20)
                    res = engine.best_pruned_addition(
                        p_state, pool, objective_floor=-1.0, tol=0.0, objective_mode=objective_mode)
                    proposal_count += res.candidate_count
                    pruning_totals["candidates"] += res.candidate_count
                    pruning_totals["field_survivors"] += res.field_survivor_count
                    pruning_totals["cvar_survivors"] += res.cvar_survivor_count
                    pruning_totals["exact_tail_evals"] += res.exact_tail_evaluations
                    chosen = int(res.best_candidate) if res.best_candidate is not None else int(pool[0])
                active_ids.append(chosen)
                repaired_ids[int(slot)] = chosen
        return repaired_ids, repaired_labels

    def geometric_fallback_refill(new_centers, new_patch, ids, labels, keep_mask, rng):
        if adaptive:
            for trial in range(2):
                snap, _, _ = _initial_adaptive_layout(
                    xyz, new_centers, new_patch, signal_power, .004, trial, rng,
                    objective_mode=objective_mode, total_electrodes=total_electrodes)
                if snap is not None:
                    return (
                        np.asarray(snap["candidate_bank_indices"], dtype=np.int64),
                        np.asarray(snap["region_indices"], dtype=np.int64),
                    )
            return None
        unaffected = [r for r in range(len(allocation)) if np.all(keep_mask[labels == r])]
        affected = [r for r in range(len(allocation)) if r not in unaffected]
        repaired = ids.copy()
        blocked = ids[np.isin(labels, unaffected)].tolist()
        ok = True
        for r in sorted(affected, key=lambda s: len(new_patch["bank_pools"][s]) / allocation[s]):
            packed = None
            for _ in range(3):
                packed = _pack_region_with_backtrack(xyz, new_patch["bank_pools"][r], int(allocation[r]),
                                                     blocked, .004, rng, repair_depth=3, branch_width=4, max_nodes=96)
                if packed is not None:
                    break
            if packed is None:
                ok = False
                break
            repaired[labels == r] = np.asarray(packed, dtype=np.int64)
            blocked.extend(packed)
        if ok:
            return repaired, labels.copy()
        for trial in range(2):
            snap, _ = _initial_layout(
                domain, new_centers, new_patch, allowed, .004, trial, rng, total_physical_nodes=total_electrodes)
            if snap is not None:
                return np.asarray(snap["candidate_bank_indices"], dtype=np.int64), labels.copy()
        return None

    def propose_center_shift(current, region_r, new_center, rng, *, margin_guided=False, min_obj_floor=None):
        new_centers = list(current["centers"])
        new_centers[region_r] = int(new_center)
        if len(set(new_centers)) != len(new_centers):
            return None
        new_patch = domain.patches(new_centers)
        if not _patch_pool_feasible(new_patch, allocation, adaptive, total_electrodes):
            return None
        center_move_stats["evaluated"] += 1
        ids = np.asarray(current["candidate_bank_indices"], dtype=np.int64)
        labels = np.asarray(current["region_indices"], dtype=np.int64)
        pool_sets = [set(map(int, p)) for p in new_patch["bank_pools"]]
        keep_mask = np.array([int(ids[k]) in pool_sets[int(labels[k])] for k in range(total_electrodes)], dtype=bool)
        evicted_count = int(total_electrodes - np.count_nonzero(keep_mask))
        if evicted_count == 0:
            repaired_ids, repaired_labels = ids.copy(), labels.copy()
            affected_regs = [region_r]
        else:
            affected_regs = sorted({int(labels[k]) for k in np.flatnonzero(~keep_mask)} | {region_r})
            refilled = schur_guided_refill(new_centers, new_patch, ids, labels, keep_mask)
            if refilled is None:
                refilled = geometric_fallback_refill(new_centers, new_patch, ids, labels, keep_mask, rng)
            if refilled is None:
                return None
            repaired_ids, repaired_labels = refilled
        try:
            rep_snap, rep_state = score({
                "candidate_bank_indices": repaired_ids.tolist(),
                "region_indices": repaired_labels.tolist(),
                "centers": new_centers,
            })
        except ValueError:
            return None
        active_pos = None if adaptive else np.flatnonzero(np.isin(repaired_labels, affected_regs))
        pol_snap, pol_state, pol_moves, _ = fedorov_ascent(
            rep_snap, rep_state, new_patch, rng, active_positions=active_pos,
            max_sweeps=SEARCH_BUDGET["regional_polish_sweeps"], phase="center_shift_polish",
        )
        if margin_guided:
            floor_ok = min_obj_floor is None or pol_snap["objective"] >= min_obj_floor
            fs_ok = pol_snap["min_field_sensitivity"] >= current["min_field_sensitivity"] - 0.0025
            if floor_ok and fs_ok:
                cur_m = eval_stage_merit(current, stage="stage3")
                pol_m = eval_stage_merit(pol_snap, stage="stage3")
                if pol_m > cur_m + tol:
                    return pol_snap, pol_state, pol_moves, evicted_count
            return None
        if pol_snap["objective"] > current["objective"] + tol:
            return pol_snap, pol_state, pol_moves, evicted_count
        return None

    def paired_2swap_unjam(current, state, patch, rng):
        nonlocal proposal_count
        if total_electrodes < 4:
            return current, state, []
        ids = np.asarray(current["candidate_bank_indices"], dtype=np.int64)
        labels = np.asarray(current["region_indices"], dtype=np.int64)
        reg_counts = np.bincount(labels, minlength=n_reg)
        union_pool, bank_to_region = _patch_union_lookup(patch, len(xyz)) if adaptive else (None, None)
        pts = xyz[ids]
        dists = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=2)
        pairs = []
        for i in range(total_electrodes):
            for j in range(i + 1, total_electrodes):
                if labels[i] == labels[j] and .004 <= dists[i, j] <= .0085:
                    pairs.append((float(dists[i, j]), i, j))
        if not pairs:
            return current, state, []
        pairs.sort(key=lambda item: (item[0], item[1], item[2]))
        cert = engine.tail_dual_certificate(ids)
        dual_hint = (cert[1], cert[2]) if cert is not None else None
        use_info = objective_mode == "composite"
        for _, i, j in pairs[:SEARCH_BUDGET["paired_2swap_pairs"]]:
            if past_deadline():
                break
            reg = int(labels[i])
            kept_62 = np.delete(ids, [i, j])
            pool = _eligible_pool_by_spacing(xyz, patch["bank_pools"][reg], kept_62, .004)
            if not len(pool):
                continue
            near_i = np.sum((xyz[pool] - xyz[ids[i]]) ** 2, axis=1) <= .020 ** 2
            near_j = np.sum((xyz[pool] - xyz[ids[j]]) ** 2, axis=1) <= .020 ** 2
            local_pool = pool[near_i | near_j]
            if not len(local_pool):
                continue
            state_62 = engine.make_partial_state(kept_62, snr_db=20)
            f_scores = engine.score_additions(state_62, local_pool, include_sensitivity=False, include_information=use_info)
            proposal_count += len(f_scores.candidate_indices)
            if not len(f_scores.candidate_indices):
                continue
            second_base_pool = (
                _eligible_pool_by_spacing(xyz, union_pool, kept_62, .004)
                if (adaptive and reg_counts[reg] > MIN_ADAPTIVE_REGION_ELECTRODES)
                else local_pool
            )
            merit_1 = (
                0.65 * f_scores.field_relative + 0.35 * f_scores.information_relative
                if use_info else f_scores.field_relative
            )
            order_1 = np.argsort(-merit_1, kind="stable")[:SEARCH_BUDGET["paired_2swap_first_branch"]]
            for idx1 in order_1:
                p1 = int(f_scores.candidate_indices[int(idx1)])
                pool_2 = second_base_pool[second_base_pool != p1]
                if not len(pool_2):
                    continue
                pool_2 = pool_2[np.sqrt(np.sum((xyz[pool_2] - xyz[p1]) ** 2, axis=1)) + 1e-12 >= .004]
                if not len(pool_2):
                    continue
                state_63 = engine.make_partial_state(np.append(kept_62, p1), snr_db=20)
                res_2 = engine.best_pruned_addition(
                    state_63, pool_2, objective_floor=current["objective"],
                    tol=tol, dual_hint=dual_hint, objective_mode=objective_mode)
                proposal_count += res_2.candidate_count
                pruning_totals["candidates"] += res_2.candidate_count
                pruning_totals["field_survivors"] += res_2.field_survivor_count
                pruning_totals["cvar_survivors"] += res_2.cvar_survivor_count
                pruning_totals["exact_tail_evals"] += res_2.exact_tail_evaluations
                if res_2.best_candidate is not None:
                    p2 = int(res_2.best_candidate)
                    r2 = int(bank_to_region[p2]) if adaptive else reg
                    proposed_ids = ids.copy()
                    proposed_ids[i], proposed_ids[j] = p1, p2
                    proposed_labels = labels.copy()
                    proposed_labels[i], proposed_labels[j] = reg, r2
                    cand, cand_state = score({
                        **current,
                        "candidate_bank_indices": proposed_ids.tolist(),
                        "region_indices": proposed_labels.tolist(),
                    })
                    if cand["objective"] > current["objective"] + tol:
                        center_move_stats["paired_2swaps"] += 1
                        if r2 != reg:
                            center_move_stats["cross_region_quota_transfers"] += 1
                        move = {
                            "kind": "paired_2swap", "positions": [int(i), int(j)],
                            "old_bank_rows": [int(ids[i]), int(ids[j])], "new_bank_rows": [p1, p2],
                            "before": current["objective"], "after": cand["objective"],
                        }
                        if adaptive:
                            move["new_regions"] = [reg, r2]
                        return cand, cand_state, [move]
        return current, state, []

    ranked_starts = sorted(starts, key=lambda item: (-item[0]["objective"], sum(item[0]["candidate_bank_indices"])))
    initial = ranked_starts[0][0].copy()

    screen_limit = int(SEARCH_BUDGET["margin_screen_starts"] if use_margin_proxy else SEARCH_BUDGET["screen_starts"])
    finalist_limit = int(SEARCH_BUDGET["margin_retained_finalists"] if use_margin_proxy else SEARCH_BUDGET["retained_finalists"])
    screen_pool, seen_centers = [], set()
    if use_margin_proxy:
        distinct_starts = []
        seen_distinct = set()
        for snap, st in ranked_starts:
            c_key = tuple(snap["centers"])
            if c_key not in seen_distinct:
                distinct_starts.append((snap, st))
                seen_distinct.add(c_key)
            if len(distinct_starts) >= int(SEARCH_BUDGET["stage1_margin_shortlist_cap"]):
                break
        for snap, _ in distinct_starts:
            eval_stage_merit(snap, stage="stage1")
        for snap, st in ranked_starts[:2]:
            c_key = tuple(snap["centers"])
            if c_key not in seen_centers:
                eval_stage_merit(snap, stage="stage1")
                screen_pool.append((snap, st))
                seen_centers.add(c_key)
        by_merit = sorted(distinct_starts, key=lambda item: (-item[0]["stage_merit"], sum(item[0]["candidate_bank_indices"])))
        for snap, st in by_merit:
            if len(screen_pool) >= screen_limit:
                break
            c_key = tuple(snap["centers"])
            if c_key not in seen_centers:
                screen_pool.append((snap, st))
                seen_centers.add(c_key)
    else:
        for snap, st in ranked_starts:
            key = tuple(snap["centers"])
            if key not in seen_centers:
                screen_pool.append((snap, st))
                seen_centers.add(key)
            if len(screen_pool) >= screen_limit:
                break
    for snap, st in ranked_starts:
        if len(screen_pool) >= min(len(ranked_starts), max(2, screen_limit)):
            break
        if all(snap is not existing[0] for existing in screen_pool):
            if use_margin_proxy:
                eval_stage_merit(snap, stage="stage1")
            screen_pool.append((snap, st))

    screened = []
    for s_idx, (snap, st) in enumerate(screen_pool):
        if past_deadline() and screened:
            break
        progress(stage="optimize", message=f"多起点全池初筛 {s_idx + 1}/{len(screen_pool)}",
                 progress=.45 + .11 * (s_idx + 1) / max(1, len(screen_pool)))
        s_rng = np.random.default_rng(np.random.SeedSequence([seed, 1100, s_idx]))
        s_patch = domain.patches(snap["centers"])
        upd_snap, upd_st, s_moves, s_conv = fedorov_ascent(
            snap, st, s_patch, s_rng, max_sweeps=1, phase=f"screen_start_{s_idx}")
        if use_margin_proxy:
            eval_stage_merit(upd_snap, stage="stage1")
        screened.append((upd_snap, upd_st, s_moves, s_conv))

    screened.sort(key=lambda item: (-item[0]["objective"], sum(item[0]["candidate_bank_indices"])))
    finalists, seen_final_centers = [], set()
    if use_margin_proxy and screened:
        lead = screened[0]
        finalists.append((*lead, False))
        seen_final_centers.add(tuple(lead[0]["centers"]))
        by_s_merit = sorted(screened, key=lambda item: (-item[0]["stage_merit"], sum(item[0]["candidate_bank_indices"])))
        for item in by_s_merit:
            if len(finalists) >= finalist_limit:
                break
            c_key = tuple(item[0]["centers"])
            if c_key not in seen_final_centers and item[0] is not lead[0]:
                finalists.append((*item, True))
                seen_final_centers.add(c_key)
        for item in by_s_merit:
            if len(finalists) >= min(len(screened), finalist_limit):
                break
            if all(item[0] is not f[0] for f in finalists):
                finalists.append((*item, True))
    else:
        for item in screened:
            c_key = tuple(item[0]["centers"])
            if c_key not in seen_final_centers or len(screened) == 1:
                finalists.append((*item, False))
                seen_final_centers.add(c_key)
            if len(finalists) >= finalist_limit:
                break
    if not finalists:
        finalists = [(*screened[0], False)]

    optimized_runs = []
    for f_idx, (cur, st, init_moves, init_conv, margin_guided) in enumerate(finalists):
        if past_deadline() and optimized_runs:
            break
        run_trace = list(init_moves)
        f_rng = np.random.default_rng(np.random.SeedSequence([seed, 2200, f_idx]))
        visited_centers = {tuple(cur["centers"])}
        one_opt_converged = bool(init_conv)
        rounds_completed = 0
        for outer in range(SEARCH_BUDGET["outer_alternating_rounds"]):
            if past_deadline():
                break
            rounds_completed = outer + 1
            progress(stage="optimize",
                     message=f"收敛交换与中心重填（起点 {f_idx + 1}/{len(finalists)} · 第 {outer + 1} 轮）",
                     progress=.56 + .24 * (f_idx * SEARCH_BUDGET["outer_alternating_rounds"] + outer + 1)
                     / max(1, len(finalists) * SEARCH_BUDGET["outer_alternating_rounds"]))
            cur_patch = domain.patches(cur["centers"])
            cur, st, f_moves, one_opt_converged = fedorov_ascent(
                cur, st, cur_patch, f_rng, max_sweeps=SEARCH_BUDGET["coordinate_sweeps"],
                phase=f"finalist_{f_idx}_round_{outer}_fedorov")
            run_trace.extend(f_moves)
            if past_deadline():
                break

            center_moved = False
            for reg_r in f_rng.permutation(n_reg):
                reg_r = int(reg_r)
                if past_deadline():
                    break
                proposals = _neighbor_center_proposals(
                    domain, cur["centers"], reg_r, outer, visited_centers, f_rng, signal_power=signal_power)
                best_shift = None
                for cand_center in proposals:
                    if past_deadline():
                        break
                    trial_tuple = list(cur["centers"])
                    trial_tuple[reg_r] = int(cand_center)
                    visited_centers.add(tuple(trial_tuple))
                    shifted = propose_center_shift(
                        cur, reg_r, cand_center, f_rng,
                        margin_guided=margin_guided, min_obj_floor=initial["objective"])
                    if shifted is not None:
                        cand_cmp = shifted[0]["stage_merit"] if margin_guided else shifted[0]["objective"]
                        best_cmp = (
                            (best_shift[0]["stage_merit"] if margin_guided else best_shift[0]["objective"])
                            if best_shift is not None else -1e9
                        )
                        if best_shift is None or cand_cmp > best_cmp + tol:
                            best_shift = (*shifted, int(cand_center))
                if best_shift is not None:
                    new_cur, new_st, pol_moves, evicted_n, accepted_c = best_shift
                    center_move_stats["accepted"] += 1
                    center_move_stats["repaired_electrodes"] += int(evicted_n)
                    run_trace.append({
                        "kind": "center_shift_with_repair", "round": outer, "region": reg_r,
                        "old_center": int(cur["centers"][reg_r]), "new_center": accepted_c,
                        "evicted_and_repaired_count": int(evicted_n),
                        "before": cur["objective"], "after": new_cur["objective"],
                    })
                    run_trace.extend(pol_moves)
                    cur, st = new_cur, new_st
                    center_moved = True
                    one_opt_converged = False
            if not center_moved:
                break

        if not one_opt_converged and not past_deadline():
            cur, st, f_moves, one_opt_converged = fedorov_ascent(
                cur, st, domain.patches(cur["centers"]), f_rng,
                max_sweeps=SEARCH_BUDGET["coordinate_sweeps"], phase=f"finalist_{f_idx}_post_center")
            run_trace.extend(f_moves)
        if not past_deadline():
            cur, st, pair_moves = paired_2swap_unjam(cur, st, domain.patches(cur["centers"]), f_rng)
            if pair_moves:
                run_trace.extend(pair_moves)
                cur, st, f_moves, one_opt_converged = fedorov_ascent(
                    cur, st, domain.patches(cur["centers"]), f_rng,
                    max_sweeps=4, phase=f"finalist_{f_idx}_post_2swap")
                run_trace.extend(f_moves)
        if use_margin_proxy:
            eval_stage_merit(cur, stage="stage3")
        optimized_runs.append((cur, run_trace, one_opt_converged, rounds_completed))

    if use_margin_proxy:
        above_initial = [
            item for item in optimized_runs
            if item[0]["objective"] + 1e-12 >= initial["objective"]
        ]
        if not above_initial:
            above_initial = optimized_runs
        best_min_fs = max(item[0]["min_field_sensitivity"] for item in above_initial)
        best_obj = max(item[0]["objective"] for item in above_initial)
        eligible_runs = [
            item for item in above_initial
            if item[0]["min_field_sensitivity"] >= best_min_fs - 0.0035
            and item[0]["objective"] >= best_obj - 0.0060
        ]
        if not eligible_runs:
            eligible_runs = above_initial
        winner_snap, winner_trace, winner_converged, winner_rounds = max(
            eligible_runs,
            key=lambda item: (
                round(item[0]["stage_merit"], 9),
                round(item[0]["objective"], 9),
                -sum(item[0]["candidate_bank_indices"]),
            ),
        )
    else:
        winner_snap, winner_trace, winner_converged, winner_rounds = max(
            optimized_runs,
            key=lambda item: (
                round(item[0]["objective"], 9),
                item[0]["field20"] if adaptive else 0.0,
                -sum(item[0]["candidate_bank_indices"]),
            ),
        )
    if winner_snap["objective"] + 1e-12 < initial["objective"]:
        raise RuntimeError("Convergent search worsened initial objective")

    if adaptive:
        w_labels = np.asarray(winner_snap["region_indices"], dtype=np.int64)
        w_ids = np.asarray(winner_snap["candidate_bank_indices"], dtype=np.int64)
        order = np.argsort(w_labels, kind="stable")
        if not np.array_equal(order, np.arange(total_electrodes)):
            winner_snap = {
                **winner_snap,
                "candidate_bank_indices": w_ids[order].tolist(),
                "region_indices": w_labels[order].tolist(),
            }
            winner_snap["geometry"] = domain.validate(
                winner_snap, adaptive_allocation=True, total_electrodes=total_electrodes)

    total_cands = max(1, pruning_totals["candidates"])
    diagnostics = {
        "attempts": attempts,
        "trace": winner_trace,
        "initial": initial,
        "scored_layouts": scored_count,
        "coordinate_proposals": proposal_count,
        "allocation_mode": "adaptive" if adaptive else "balanced",
        "objective_mode": objective_mode,
        "physical_electrode_count": total_electrodes,
        "min_adaptive_region_electrodes": MIN_ADAPTIVE_REGION_ELECTRODES if adaptive else None,
        "initial_region_counts": initial["geometry"]["actual_region_counts"],
        "final_region_counts": winner_snap["geometry"]["actual_region_counts"],
        "one_opt_converged": bool(winner_converged),
        "outer_alternating_rounds": int(winner_rounds),
        "screened_start_count": len(screened),
        "finalist_count": len(optimized_runs),
        "center_moves": center_move_stats,
        "dictionary_margin_proxy": {
            **margin_stats,
            "elapsed_seconds": round(float(margin_stats["elapsed_seconds"]), 4),
            "winner_margin20": winner_snap.get("margin20"),
            "winner_stage_merit": winner_snap.get("stage_merit"),
        },
        "pruning": {
            **pruning_totals,
            "pruned_before_exact_tail_fraction": float(1.0 - pruning_totals["exact_tail_evals"] / total_cands),
        },
        "global_optimum_certified": False,
        "infeasibility_certified": False,
        "localization_optimized": False,
    }
    return winner_snap, diagnostics


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
        self.engine = LayoutSearchMetrics(
            self.hc[:, :self.n], self.hb[:, :self.n], self.weights,
            dictionary_xyz_mm=self.source_xyz_mm,
        )
        self._engines = {None: self.engine}
        dependency_names = ["local_radius_compute.py", "area_budget_study.py", "artifacts.py", "layout_search_metrics.py", "noise_models.py",
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
            "limitations": ["Finite candidate bank, finite center list and bounded alternating search; no global optimum or infeasibility proof.",
                "Approximate low-hair and periauricular coordinate ROIs are not validated anatomical hair-free or strict behind-ear masks.",
                "Radius is an ROI-restricted mesh-edge path bound, not exact continuous geodesic radius; area is native vertex quadrature.",
                "Exactly R disconnected and non-touching patches on the original mesh; common radius may shrink before patches merge.",
                "Same head, conductivity, source bank and solver; not an independent-head or fresh-source validation and not human accuracy.",
                "Field, amplitude sensitivity and localization utility are different relative metrics; their minimum is a conditional threshold rule.",
                "Localization is evaluated after freezing the joint field/sensitivity winner; its result never selects another layout.",
                "Physical noise is calibrated once from full-head64; localization remains grid-limited with independently seeded layout noise."]}
        self._baselines = {}

    def engine_for(self, model, prior=None):
        """Field engine and source weights for a noise model or data prior; noise variants share the signal caches."""
        if prior is not None:
            key = ("data_prior", json.dumps(prior, sort_keys=True))
            if key not in self._engines:
                from .workflows import data_prior
                data = {"source_xyz_mm": self.source_xyz_mm, "generation_xyz_mm": self.generation_xyz_mm}
                weights, generation = data_prior.apply(self.root, data, prior, self.weights, self.generation_weights)
                kernel = data_prior.kernel(prior)
                engine = LayoutSearchMetrics(
                    self.hc[:, :self.n], self.hb[:, :self.n], weights,
                    noise_kernel=None if kernel is None else (self.candidate_xyz_mm, self.reference_xyz_mm, *kernel),
                    dictionary_xyz_mm=self.source_xyz_mm,
                )
                self._engines[key] = (engine, weights, generation)
            return self._engines[key]
        kernel = noise_models.field_kernel(model)
        if kernel not in self._engines:
            self._engines[kernel] = self.engine.with_noise_kernel((self.candidate_xyz_mm, self.reference_xyz_mm, *kernel))
        return self._engines[kernel], self.weights, self.generation_weights

    def _localize(self, field, layout_id, model=None, xyz=None, prior=None):
        engine, weights, generation = self.engine_for(model, prior) if prior is not None else (self.engine, self.weights, self.generation_weights)
        sigma = np.sqrt(engine.reference_mean_contrast_signal_power_v2 * .01)
        covariance = noise_models.localization_covariance(model, xyz, field[:, :self.n], weights, sigma * sigma, 1e-8)
        return evaluate_grid_localization(field[:, :self.n], field[:, self.n:], self.source_xyz_mm, self.generation_xyz_mm,
            source_moment_am=1e-8, physical_electrode_noise_std_v=sigma,
            noise_seed=SEED, layout_id=layout_id, noise_repetitions=16, generation_source_weights=generation,
            physical_noise_covariance_v2=covariance, noise_model=noise_models.describe(model),
            expected_electrodes=int(field.shape[0]))

    def compute(self, raw, progress=lambda **kwargs: None, *, enable_localization_proxy=True):
        started = time.perf_counter()
        deadline = started + float(SEARCH_BUDGET["soft_deadline_seconds"])
        request = validate_request(raw)
        adaptive = request.get("allocation_mode") == "adaptive"
        objective_mode = request.get("objective_mode", "min")
        total_electrodes = int(request.get("electrode_count", 64))
        seed = search_seed(request)
        rois = request_rois(request)
        progress(stage="geometry", message="构建ROI约束路径与不接触区域", progress=.16)
        domain = RadiusDomain(self.vertices, self.adjacency, self.bank_ids, self.areas, self.masks, self.centers, rois, request["radius_mm"] / 1000)
        prior = request.get("data_prior")
        if prior is not None:
            from .workflows import data_prior
            model = data_prior.noise_model(prior)
        else:
            model = request.get("noise_model")
        engine = self.engine_for(model, prior)[0]
        use_margin_shortlist = bool(enable_localization_proxy and objective_mode == "composite" and engine.has_nonlocal_margin)
        combinations, center_selection = select_radius_center_combinations(
            self.vertices, self.centers, rois, seed,
            maximum_combinations=SEARCH_BUDGET["initial_center_combinations"],
            domain=domain, signal_power=engine.diagonal_signal_power(),
            adaptive_allocation=adaptive, total_electrodes=total_electrodes,
            engine=engine, use_margin_proxy=use_margin_shortlist)
        winner, diagnostics = bounded_radius_search(
            domain, engine, combinations, seed, progress,
            deadline_monotonic=deadline, adaptive_allocation=adaptive,
            objective_mode=objective_mode, total_electrodes=total_electrodes,
            enable_localization_proxy=enable_localization_proxy)
        obj_desc = (
            "0.55*min(field_relative20,sensitivity_tail)+0.30*field_relative20+0.15*information_relative20"
            if objective_mode == "composite" else "min(field_relative20,sensitivity_tail)"
        )
        provenance = {**self.provenance, "physical_electrode_count": total_electrodes,
            "search_seed": seed, "localization_noise_seed": SEED,
            "region_roi_ids": list(rois), "center_selection": center_selection,
            "allocation_mode": "adaptive" if adaptive else "balanced",
            "objective_mode": objective_mode,
            "optimization_objective": obj_desc,
            **({"min_adaptive_region_electrodes": MIN_ADAPTIVE_REGION_ELECTRODES,
                "search_seed_excludes_allocation_mode": True} if adaptive else {}),
            **({"composite_weights": list(COMPOSITE_WEIGHTS),
                "search_seed_excludes_objective_mode": True} if objective_mode == "composite" else {}),
            **({"search_seed_excludes_electrode_count": True} if "electrode_count" in request else {}),
            **({"noise_model": noise_models.describe(model), "search_seed_excludes_noise_model": True} if model and not prior else {})}
        if prior is not None:
            prior_files = ["src/compact_eeg/workflows/data_prior.py", "src/compact_eeg/workflows/eeg_recording.py", data_prior.ATLAS_PATH]
            provenance.update(data_prior=data_prior.describe(prior), search_seed_excludes_data_prior=True,
                              source_prior="data_prior region gains on the frozen 4096 cortical area quadrature",
                              code_sha256={**provenance["code_sha256"], **{path: sha256_file(self.root / path) for path in prior_files}})
        result = {"status": "no_layout" if winner is None else "completed", "request": request,
            "layout": None, "metrics": None, "geometry": None, "provenance": provenance,
            "diagnostics": {**diagnostics, "center_combinations": [list(c) for c in combinations],
                "center_selection": center_selection}}
        if winner is None:
            result.update(message=f"在当前候选网格、4mm间距和有限搜索预算内，未构造出满足严格区域约束的{total_electrodes}点布局；这不是数学不可行证明。", elapsed_seconds=time.perf_counter() - started)
            return result
        selected = np.asarray(winner["candidate_bank_indices"], int)
        layout_id = hashlib.sha256(self.bank_ids[selected].astype("<i8").tobytes()).hexdigest()[:24]
        geometry = domain.validate(winner, adaptive_allocation=adaptive, total_electrodes=total_electrodes)
        progress(stage="metrics", message="冻结点位，评价重建、敏感度及源定位", progress=.84)
        field = engine.evaluate(selected, snr_db=(20,), count=total_electrodes)
        condition = field["conditions"][0]
        key = json.dumps([model, prior], sort_keys=True)
        if key not in self._baselines:
            self._baselines[key] = self._localize(self.hb, "local_radius_reference64", model, self.reference_xyz_mm, prior)
        baseline = self._baselines[key]
        progress(stage="localization", message="计算冻结布局的离散源定位误差", progress=.92)
        loc = self._localize(self.hc[selected], "local_radius_" + layout_id, model, self.candidate_xyz_mm[selected], prior)
        reference_utility = baseline.report["source_lower10_utility_dmax50mm"]
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
                "median_mm": loc.report["median_mm"] if "median_mm" in loc.report else loc.report["median_error_mm"],
                "p90_mm": loc.report["p90_error_mm"],
                "p95_mm": loc.report["p95_error_mm"], "reference_median_mm": baseline.report["median_error_mm"],
                "reference_p90_mm": baseline.report["p90_error_mm"],
                "localization_utility": loc.report["source_lower10_utility_dmax50mm"], "reference_localization_utility": reference_utility,
                "effective_rank": condition["candidate_noise_whitened_area_weighted_effective_rank"]}, geometry=geometry)
        result["diagnostics"].update(final=winner, field_report=field, localization_report=loc.report,
            reference_localization_report=baseline.report,
            localization_errors_mm=loc.errors_mm.tolist(), reference_localization_errors_mm=baseline.errors_mm.tolist())
        result["elapsed_seconds"] = time.perf_counter() - started
        if any(sha256_file(self.root / p) != digest for p, digest in provenance["code_sha256"].items()):
            raise RuntimeError("Scientific source code changed during computation")
        return result


__all__ = ["LocalRadiusComputer", "RadiusDomain", "MIN_ADAPTIVE_REGION_ELECTRODES", "ELECTRODE_COUNTS", "validate_request", "search_seed",
           "request_rois", "bounded_radius_search", "select_radius_center_combinations"]
