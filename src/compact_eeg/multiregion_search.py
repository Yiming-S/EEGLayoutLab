"""Bounded fixed-64 mesh search, with separate field and field/sensitivity goals.

All geometry is in metres and uses original surface vertex indices. ``indices``
in returned snapshots are candidate-bank rows for LayoutSearchMetrics; the
unambiguous ``electrode_vertex_indices`` and ``centers`` are surface indices.
No localization optimization, FEM, AR decision or global optimum is performed.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping

import numpy as np

from .multiregion_geometry import (
    _region_greedy_with_tail_repair,
    balanced_region_point_counts,
    bounded_center_combinations,
    build_region_candidate_pool,
)


OBJECTIVES = ("field_20db", "min_field_sensitivity_20db")
DEFAULTS = {
    "center_combinations_per_condition": 24,
    "geometry_restarts_per_center_combination": 4,
    "retained_starts_per_objective": 2,
    "coordinate_sweeps": 2,
    "candidate_proposals_per_electrode": 16,
    "center_exchange_rounds": 1,
    "center_proposals_per_region": 4,
    "improvement_tolerance": 1e-9,
}
TAIL_REPAIR = {"repair_depth": 2, "repair_branch_width": 3, "maximum_repair_nodes": 96}


@dataclass
class _Layout:
    vertices: np.ndarray
    regions: np.ndarray
    centers: tuple[int, ...]
    origin: str

    def copy(self):
        return _Layout(self.vertices.copy(), self.regions.copy(), self.centers, self.origin)


def _integers(value, *, name, unique=False, count=None):
    array = np.asarray(value)
    if array.ndim != 1 or array.dtype.kind not in "iu":
        raise ValueError(f"{name} must be an integer vector")
    if count is not None and len(array) != count:
        raise ValueError(f"{name} must contain {count} elements")
    if unique and len(np.unique(array)) != len(array):
        raise ValueError(f"{name} must be unique")
    return array.astype(np.int64, copy=True)


def _objective(name, field, sensitivity):
    if name == "field_20db":
        return float(field)
    if sensitivity is None or not np.isfinite(sensitivity):
        return None
    return float(min(field, sensitivity))


def _configuration(search_config):
    config = dict(search_config)
    if "search" in config:
        config = dict(config["search"])
    output = {key: config.get(key, default) for key, default in DEFAULTS.items()}
    for key, value in output.items():
        if key == "improvement_tolerance":
            if isinstance(value, bool) or not np.isfinite(value) or value < 0:
                raise ValueError("invalid improvement_tolerance")
            output[key] = float(value)
        else:
            lower = 0 if key in {"coordinate_sweeps", "center_exchange_rounds", "center_proposals_per_region"} else 1
            if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < lower:
                raise ValueError(f"invalid {key}")
            output[key] = int(value)
    objectives = tuple(config.get("objectives", OBJECTIVES))
    if not objectives or len(set(objectives)) != len(objectives) or any(value not in OBJECTIVES for value in objectives):
        raise ValueError("unsupported or duplicate search objectives")
    output["objectives"] = list(objectives)
    return output


def _mixed_proposals(vertices, candidates, current_vertex, limit, rng):
    """Half nearest, quarter chord-maximin spread, remaining seeded random."""
    candidates = np.asarray(candidates, dtype=np.int64)
    if len(candidates) <= limit:
        return np.sort(candidates)
    distance = np.linalg.norm(vertices[candidates] - vertices[current_vertex], axis=1)
    ordered = candidates[np.lexsort((candidates, distance))]
    selected = ordered[:max(1, limit // 2)].tolist()
    remaining = candidates[~np.isin(candidates, selected)]
    for _ in range(min(limit // 4, len(remaining))):
        minimum = np.min(np.linalg.norm(vertices[remaining, None, :] - vertices[np.asarray(selected)][None, :, :], axis=2), axis=1)
        best = np.lexsort((remaining, -minimum))[0]
        selected.append(int(remaining[best]))
        remaining = np.delete(remaining, best)
    count = min(limit - len(selected), len(remaining))
    if count:
        selected.extend(int(value) for value in rng.choice(remaining, count, replace=False))
    return np.asarray(selected, dtype=np.int64)


def _geometry_trial(vertices, pools, allocation, cache, spacing, trial, rng):
    """One explicitly budgeted restart, retaining every complete trial."""
    count = len(pools)
    if trial == 0:
        order = np.arange(count)
    elif trial == 1:
        order = np.arange(count - 1, -1, -1)
    else:
        order = rng.permutation(count)
    selected, labels = [], []
    achieved = np.zeros(count, dtype=int)
    preferred = []
    for region, pool in enumerate(pools):
        if trial == 0:
            preferred.append(int(pool.center_vertex_index))
        elif trial == 1:
            rank = np.lexsort((pool.candidate_vertex_indices, -pool.candidate_center_graph_distances_m))
            preferred.append(int(pool.candidate_vertex_indices[rank[0]]))
        else:
            preferred.append(int(rng.choice(pool.candidate_vertex_indices)))
    for region in order:
        local = _region_greedy_with_tail_repair(
            vertices, pools[region], int(allocation[region]), selected,
            preferred[region], spacing, cache, **TAIL_REPAIR,
        )
        selected.extend(local)
        labels.extend([int(region)] * len(local))
        achieved[region] = len(local)
        if len(local) != allocation[region]:
            break
    return (np.asarray(selected, dtype=np.int64), np.asarray(labels, dtype=np.int64), achieved,
            order.tolist(), preferred)


def search_condition(*, vertices_m, adjacency, distance_cache, candidate_vertex_indices,
                     roi_masks, center_shortlist_by_roi, region_roi_ids, radius_m,
                     spacing_m, engine, search_config, seed, warm_starts=()):
    """Search one frozen region/ROI/radius/spacing condition under finite budgets.

    Return value is JSON-safe. Warm starts may be previous ``final`` snapshots,
    or mappings containing ``final``. Their coordinates/metrics are NEVER trusted:
    every geometry constraint is checked again and every metric is recomputed.

    Patches may overlap; selected points may not. Center exchange is deliberately
    conservative: all existing electrodes in that region must already belong to
    the proposed connected patch. Such proposals receive one extra, explicitly
    counted region-only coordinate sweep; the best improving proposal is kept.
    No other center proposal is silently repaired, relocated or declared infeasible.
    """
    vertices = np.asarray(vertices_m, dtype=float)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.all(np.isfinite(vertices)):
        raise ValueError("vertices_m must be a finite (N,3) array")
    if adjacency.shape != (len(vertices), len(vertices)):
        raise ValueError("adjacency must match surface vertices")
    bank_vertices = _integers(candidate_vertex_indices, name="candidate_vertex_indices", unique=True)
    if len(bank_vertices) < 64 or bank_vertices.min() < 0 or bank_vertices.max() >= len(vertices):
        raise ValueError("invalid candidate bank")
    if engine.point_count != len(bank_vertices):
        raise ValueError("metric bank row count differs from candidate vertex map")
    regions = tuple(region_roi_ids)
    if len(regions) not in (1, 2, 3, 4, 6):
        raise ValueError("supported region counts are 1,2,3,4,6")
    allocation = np.asarray(balanced_region_point_counts(len(regions)), dtype=int)
    radius, spacing = float(radius_m), float(spacing_m)
    if not np.isfinite(radius) or not np.isfinite(spacing) or radius <= 0 or spacing <= 0:
        raise ValueError("radius and spacing must be positive finite metres")
    if not isinstance(seed, (int, np.integer)) or isinstance(seed, (bool, np.bool_)) or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    config = _configuration(search_config)
    tolerance = config["improvement_tolerance"]
    masks, centers_by_roi = {}, {}
    for roi in dict.fromkeys(regions):
        if roi not in roi_masks or roi not in center_shortlist_by_roi:
            raise ValueError(f"missing ROI mask or center shortlist: {roi}")
        mask = np.asarray(roi_masks[roi])
        if mask.shape != (len(vertices),) or mask.dtype.kind != "b":
            raise ValueError("ROI masks must be boolean over all surface vertices")
        raw = np.asarray(center_shortlist_by_roi[roi])
        shortlist = np.empty(0, dtype=int) if raw.ndim == 1 and not raw.size else _integers(raw, name="center shortlist", unique=True)
        if len(shortlist) and (shortlist.min() < 0 or shortlist.max() >= len(vertices) or not np.all(mask[shortlist])):
            raise ValueError("center shortlist leaves its ROI")
        masks[roi], centers_by_roi[roi] = mask, shortlist
    inverse_map = np.full(len(vertices), -1, dtype=np.int64)
    inverse_map[bank_vertices] = np.arange(len(bank_vertices))
    pool_cache = {}
    counts = Counter()

    def pool_for(region, center):
        key = (regions[region], int(center))
        if key not in pool_cache:
            pool_cache[key] = build_region_candidate_pool(vertices, adjacency, distance_cache,
                masks[regions[region]], regions[region], int(center), graph_path_radius_m=radius,
                allowed_electrode_vertex_indices=bank_vertices)
            counts["connected_pools_built"] += 1
        return pool_cache[key]

    def validate(layout):
        selected, labels = layout.vertices, layout.regions
        if selected.shape != (64,) or labels.shape != (64,) or len(np.unique(selected)) != 64:
            raise ValueError("layout must contain 64 unique physical vertices and labels")
        if selected.min() < 0 or selected.max() >= len(vertices) or np.any(inverse_map[selected] < 0):
            raise ValueError("layout vertex outside metric bank")
        if labels.min() < 0 or labels.max() >= len(regions) or not np.array_equal(np.bincount(labels, minlength=len(regions)), allocation):
            raise ValueError("layout violates balanced regional allocation")
        if len(layout.centers) != len(regions) or len(set(layout.centers)) != len(regions):
            raise ValueError("layout centers must be distinct and match region count")
        pairwise = np.linalg.norm(vertices[selected, None, :] - vertices[selected][None, :, :], axis=2)
        minimum = float(pairwise[np.triu_indices(64, 1)].min())
        if minimum + 1e-12 < spacing:
            raise ValueError("layout violates global chord spacing")
        maxima, pool_counts, connected_counts = [], [], []
        for region, center in enumerate(layout.centers):
            pool = pool_for(region, center)
            points = selected[labels == region]
            if not np.all(np.isin(points, pool.candidate_vertex_indices)):
                raise ValueError("layout point outside its ROI-connected radius pool")
            maximum = float(distance_cache.get(int(center))[points].max())
            if maximum > radius + 1e-12:
                raise ValueError("layout exceeds graph-radius cap")
            maxima.append(maximum)
            pool_counts.append(len(pool.candidate_vertex_indices))
            connected_counts.append(pool.underlying_connected_patch_vertex_count)
        return {"valid": True, "minimum_global_chord_distance_m": minimum,
            "actual_region_counts": allocation.tolist(), "maximum_region_graph_distances_m": maxima,
            "region_bank_pool_counts": pool_counts, "underlying_connected_patch_vertex_counts": connected_counts}

    def score(layout):
        state = engine.make_state(inverse_map[layout.vertices], snr_db=20)
        sensitivity = engine.sensitivity_tail(state.indices)
        counts["direct_field_evaluations"] += 1
        counts["direct_sensitivity_evaluations"] += 1
        if not np.isfinite(state.field_relative):
            raise FloatingPointError("nonfinite field score")
        if sensitivity is not None and not np.isfinite(sensitivity):
            sensitivity = None
        return state, None if sensitivity is None else float(sensitivity)

    def snapshot(layout, objective, state=None, sensitivity=None):
        geometry = validate(layout)
        if state is None:
            state, sensitivity = score(layout)
        return {"field20": float(state.field_relative), "field20_absolute": float(state.field_absolute),
            "sensitivity_tail": sensitivity, "objective_score": _objective(objective, state.field_relative, sensitivity),
            "indices": inverse_map[layout.vertices].tolist(), "candidate_bank_indices": inverse_map[layout.vertices].tolist(),
            "electrode_vertex_indices": layout.vertices.tolist(), "region_indices": layout.regions.tolist(),
            "centers": list(layout.centers), "region_roi_ids": list(regions),
            "xyz_m": vertices[layout.vertices].tolist(), "center_xyz_m": vertices[np.asarray(layout.centers)].tolist(),
            "geometry_validation": geometry, "origin": layout.origin}

    geometry_rng = np.random.default_rng(np.random.SeedSequence([int(seed), 0]))
    combinations = () if any(not len(centers_by_roi[roi]) for roi in regions) else bounded_center_combinations(
        vertices, centers_by_roi, regions, minimum_center_chord_distance_m=0.,
        beam_width=max(256, config["center_combinations_per_condition"]),
        maximum_combinations=config["center_combinations_per_condition"],
    )
    attempts, complete, warm_records = [], [], []
    for combination_index, centers in enumerate(combinations):
        counts["center_combinations_attempted"] += 1
        try:
            pools = [pool_for(region, center) for region, center in enumerate(centers)]
        except ValueError as error:
            attempts.append({"centers": list(centers), "status": "connected_pool_unavailable",
                "reason": str(error), "partial_counts": [0] * len(regions), "trials_evaluated": 0})
            continue
        for trial in range(config["geometry_restarts_per_center_combination"]):
            selected, labels, achieved, order, preferred = _geometry_trial(vertices, pools, allocation,
                distance_cache, spacing, trial, geometry_rng)
            counts["geometry_trials"] += 1
            origin = f"center_combination_{combination_index}_trial_{trial}"
            record = {"centers": list(centers), "trial": trial, "partial_counts": achieved.tolist(),
                "selected_count": len(selected), "region_order": order, "preferred_seed_vertices": preferred,
                "status": "complete" if len(selected) == 64 else "incomplete_under_bounded_geometry_search"}
            attempts.append(record)
            if len(selected) == 64:
                layout = _Layout(selected, labels, tuple(centers), origin)
                validate(layout)
                state, sensitivity = score(layout)
                complete.append((layout, state.field_relative, sensitivity))
                counts["complete_geometry_trials"] += 1
    for index, raw in enumerate(warm_starts):
        try:
            if not isinstance(raw, Mapping):
                raise ValueError("warm start must be a result snapshot mapping")
            value = raw.get("final", raw)
            if not isinstance(value, Mapping) or tuple(value.get("region_roi_ids", ())) != regions:
                raise ValueError("warm start ROI assignment differs from this condition")
            if "electrode_vertex_indices" in value:
                selected = _integers(value["electrode_vertex_indices"], name="warm electrodes", unique=True, count=64)
            else:
                row_indices = _integers(value.get("candidate_bank_indices", value.get("indices")), name="warm bank indices", unique=True, count=64)
                if row_indices.min() < 0 or row_indices.max() >= len(bank_vertices):
                    raise ValueError("warm bank indices out of range")
                selected = bank_vertices[row_indices]
            labels = _integers(value["region_indices"], name="warm regions", count=64)
            centers = tuple(_integers(value["centers"], name="warm centers", unique=True, count=len(regions)).tolist())
            layout = _Layout(selected, labels, centers, f"warm_start_{index}")
            validate(layout)
            state, sensitivity = score(layout)
            complete.append((layout, state.field_relative, sensitivity))
            warm_records.append({"index": index, "accepted": True, "field20": float(state.field_relative), "sensitivity_tail": sensitivity})
            counts["valid_warm_starts"] += 1
        except (ValueError, KeyError, TypeError, IndexError) as error:
            warm_records.append({"index": index, "accepted": False, "reason": str(error)})
            counts["invalid_warm_starts"] += 1

    def coordinate_sweep(layout, state, sensitivity, objective, rng, *, positions=None, phase, sweep):
        trace = []
        positions = rng.permutation(64) if positions is None else rng.permutation(np.asarray(positions))
        for position in positions:
            position = int(position)
            region = int(layout.regions[position])
            pool = pool_for(region, layout.centers[region])
            others = np.delete(layout.vertices, position)
            candidates = pool.candidate_vertex_indices[~np.isin(pool.candidate_vertex_indices, layout.vertices)]
            if len(candidates):
                eligible = np.ones(len(candidates), dtype=bool)
                for vertex in others:
                    delta = vertices[candidates] - vertices[vertex]
                    eligible &= np.sum(delta**2, axis=1) + 1e-24 >= spacing * spacing
                candidates = candidates[eligible]
            proposals = _mixed_proposals(vertices, candidates, int(layout.vertices[position]),
                config["candidate_proposals_per_electrode"], rng)
            counts["coordinate_positions_visited"] += 1
            counts["coordinate_candidates_scored"] += len(proposals)
            if not len(proposals):
                continue
            result = engine.score_exchanges(state, position, inverse_map[proposals],
                include_sensitivity=objective == "min_field_sensitivity_20db")
            if not np.array_equal(result.candidate_indices, inverse_map[proposals]):
                raise RuntimeError("score engine changed already validated proposal mapping")
            candidate_scores = result.field_relative.copy()
            if objective == "min_field_sensitivity_20db":
                candidate_scores = np.minimum(candidate_scores, result.sensitivity_tail)
            valid = np.isfinite(candidate_scores)
            if not np.any(valid):
                continue
            best = int(np.argmax(np.where(valid, candidate_scores, -np.inf)))
            old_score = _objective(objective, state.field_relative, sensitivity)
            if old_score is None or candidate_scores[best] <= old_score + tolerance:
                continue
            candidate = int(result.candidate_indices[best])
            new_state = engine.apply_exchange(state, position, candidate)
            new_sensitivity = engine.sensitivity_tail(new_state.indices)
            if new_sensitivity is not None:
                new_sensitivity = float(new_sensitivity) if np.isfinite(new_sensitivity) else None
            counts["direct_field_evaluations"] += 1
            counts["direct_sensitivity_evaluations"] += 1
            new_score = _objective(objective, new_state.field_relative, new_sensitivity)
            if new_score is None or new_score <= old_score + tolerance:
                counts["fast_proposal_rejected_by_direct_recheck"] += 1
                continue
            old_vertex = int(layout.vertices[position])
            proposed_layout = layout.copy()
            proposed_layout.vertices[position] = bank_vertices[candidate]
            validate(proposed_layout)
            layout, state, sensitivity = proposed_layout, new_state, new_sensitivity
            trace.append({"kind": "coordinate_exchange", "phase": phase, "sweep": sweep,
                "position": position, "region": region, "old_vertex": old_vertex,
                "new_vertex": int(layout.vertices[position]), "objective_before": old_score,
                "objective_after": new_score, "field20": float(state.field_relative), "sensitivity_tail": sensitivity})
        return layout, state, sensitivity, trace

    results = {}
    for objective_index, objective in enumerate(config["objectives"]):
        ranked = sorted(((_objective(objective, field, sensitivity), layout, field, sensitivity)
                         for layout, field, sensitivity in complete if _objective(objective, field, sensitivity) is not None),
                        key=lambda item: (-item[0], tuple(sorted(item[1].vertices)), item[1].centers, item[1].origin))
        starts, seen = [], set()
        for item in ranked:
            layout = item[1]
            signature = (tuple(sorted(zip(layout.vertices.tolist(), layout.regions.tolist()))), layout.centers)
            if signature not in seen:
                starts.append(layout)
                seen.add(signature)
            if len(starts) >= config["retained_starts_per_objective"]:
                break
        if not starts:
            results[objective] = {"status": "no_complete_layout" if not complete else "objective_unavailable",
                "initial": None, "final": None, "accepted_moves": 0, "trace": [], "evaluated_counts": {}}
            continue
        optimized = []
        for start_index, start in enumerate(starts):
            before_counts = counts.copy()
            rng = np.random.default_rng(np.random.SeedSequence([int(seed), 1, objective_index, start_index]))
            layout = start.copy()
            state, sensitivity = score(layout)
            initial = snapshot(layout, objective, state, sensitivity)
            trace, center_attempts = [], []
            for sweep in range(config["coordinate_sweeps"]):
                layout, state, sensitivity, moves = coordinate_sweep(layout, state, sensitivity,
                    objective, rng, phase="initial_coordinate_sweeps", sweep=sweep)
                trace.extend(moves)
            for round_index in range(config["center_exchange_rounds"]):
                for region in range(len(regions)):
                    candidates = centers_by_roi[regions[region]]
                    candidates = candidates[~np.isin(candidates, np.asarray(layout.centers))]
                    proposals = _mixed_proposals(vertices, candidates, layout.centers[region],
                        config["center_proposals_per_region"], rng) if config["center_proposals_per_region"] else np.empty(0, dtype=int)
                    old_objective = _objective(objective, state.field_relative, sensitivity)
                    best = None
                    for center in proposals:
                        counts["center_proposals_evaluated"] += 1
                        record = {"round": round_index, "region": region, "old_center": layout.centers[region],
                            "proposed_center": int(center), "accepted": False}
                        center_attempts.append(record)
                        proposed_centers = list(layout.centers)
                        proposed_centers[region] = int(center)
                        proposed = layout.copy()
                        proposed.centers = tuple(proposed_centers)
                        try:
                            validate(proposed)
                        except ValueError as error:
                            record.update(status="existing_points_outside_new_patch", reason=str(error))
                            counts["center_membership_rejections"] += 1
                            continue
                        counts["center_proposals_with_valid_existing_membership"] += 1
                        counts["center_region_coordinate_sweeps"] += 1
                        proposed, proposal_state, proposal_sensitivity, moves = coordinate_sweep(proposed, state, sensitivity,
                            objective, rng, positions=np.flatnonzero(layout.regions == region),
                            phase="center_proposal_region_sweep", sweep=round_index)
                        value = _objective(objective, proposal_state.field_relative, proposal_sensitivity)
                        record.update(status="evaluated_membership_preserving_center_proposal", objective_score=value,
                            provisional_coordinate_moves=len(moves))
                        if value is not None and value > old_objective + tolerance and (best is None or value > best[0] + tolerance):
                            best = (value, proposed, proposal_state, proposal_sensitivity, moves, record)
                    if best is not None:
                        value, proposed, proposal_state, proposal_sensitivity, moves, record = best
                        record["accepted"] = True
                        trace.append({"kind": "region_center_exchange", "round": round_index, "region": region,
                            "old_center": layout.centers[region], "new_center": proposed.centers[region],
                            "objective_before": old_objective, "objective_after": old_objective,
                            "compound_final_objective": value,
                            "method": "membership_preserving_center_proposal_plus_one_region_coordinate_sweep"})
                        trace.extend(moves)
                        layout, state, sensitivity = proposed, proposal_state, proposal_sensitivity
            final = snapshot(layout, objective, state, sensitivity)
            if final["objective_score"] + tolerance < initial["objective_score"]:
                raise RuntimeError("accepted search path worsened its objective")
            optimized.append({"status": "completed_best_found", "start_index": start_index,
                "initial": initial, "final": final, "accepted_moves": len(trace), "trace": trace,
                "center_attempts": center_attempts,
                "evaluated_counts": dict(counts - before_counts)})
        winner = max(optimized, key=lambda item: item["final"]["objective_score"])
        winner["retained_start_count"] = len(starts)
        winner["all_start_summaries"] = [{"start_index": item["start_index"], "initial_score": item["initial"]["objective_score"],
            "final_score": item["final"]["objective_score"], "accepted_moves": item["accepted_moves"],
            "evaluated_counts": item["evaluated_counts"]} for item in optimized]
        warm_values = [_objective(objective, item["field20"], item["sensitivity_tail"]) for item in warm_records if item["accepted"]]
        warm_values = [value for value in warm_values if value is not None]
        if warm_values and winner["final"]["objective_score"] + tolerance < max(warm_values):
            raise RuntimeError("validated warm-start objective was lost")
        winner["best_validated_warm_start_score"] = max(warm_values) if warm_values else None
        results[objective] = winner

    any_complete = bool(complete)
    return {"schema_version": "compact-eeg-multiregion-search/1", "status": "completed_best_found" if any_complete else "no_complete_layout_constructed",
        "region_roi_ids": list(regions), "region_count": len(regions), "allocation": allocation.tolist(),
        "radius_m": radius, "spacing_m": spacing, "seed": int(seed), "objective_results": results,
        "geometry_attempts": attempts, "warm_start_validation": warm_records,
        "budget": {"requested": config, "used": dict(counts), "geometry_tail_repair": TAIL_REPAIR.copy()},
        "diagnostics": {"candidate_bank_size": len(bank_vertices), "complete_trial_and_warm_start_count": len(complete),
            "center_combinations_returned": len(combinations),
            "center_shortlist_sizes": {key: len(value) for key, value in centers_by_roi.items()},
            "candidate_patch_overlap_allowed": True, "selected_point_overlap_allowed": False,
            "proposal_mixture": "half_nearest_quarter_chord_maximin_remaining_seeded_random",
            "center_exchange_method": "existing_points_must_belong_to_new_connected_patch_then_one_extra_region_coordinate_sweep",
            "accepted_layouts_rechecked_by_direct_metrics_and_all_geometry_constraints": True},
        "formal_ar": False, "formal_v2_performance_eligible": False, "localization_optimized": False,
        "global_optimum_certified": False, "infeasibility_certified": False,
        "interpretation": "Best found under the recorded finite candidate bank, center shortlist and search budget. Geometry failure records partial counts, not nonexistence. Field and sensitivity guide separate searches; localization is evaluated by the caller afterward."}


__all__ = ["search_condition", "OBJECTIVES"]
