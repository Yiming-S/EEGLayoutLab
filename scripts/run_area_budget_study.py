#!/usr/bin/env python3
"""Execute and independently check the bounded fixed-union-area study."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[key] = "1"
import numpy as np
import scipy
from scipy.sparse.csgraph import connected_components
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compact_eeg.area_budget_study import AreaDomain, center_combinations, nested_coarse_bank, search_area_condition
from compact_eeg.artifacts import atomic_write_json, sha256_file, semantic_id
from compact_eeg.packing_pilot import build_surface_edge_graph
from compact_eeg.surface import vertex_area_weights
from compact_eeg.layout_search_metrics import LayoutSearchMetrics
from compact_eeg.prototype_metrics import evaluate_prototype_metrics
from compact_eeg.prototype_localization import evaluate_grid_localization
from compact_eeg.forward_pilot import write_npz_once
from compact_eeg.surface_admissibility import load_admissibility


def log(event, **values):
    print(json.dumps({"event": event, **values}), flush=True)


def conditions(config):
    return [{"id": f"r{r}_{domain}_union{area}", "region_count": r, "domain": domain, "area_cap_cm2": area}
        for area in config["union_area_caps_cm2"] for domain in config["domains"] for r in config["region_counts"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "configs/area_budget_study.json")
    parser.add_argument("--resume-batch", type=Path)
    parser.add_argument("--max-main-conditions", type=int)
    parser.add_argument("--no-promote", action="store_true", help="Write a complete report without changing the app's current report")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    pointer = json.loads((ROOT / "results/v2/current_multiregion_bank.json").read_text())
    bank_path, geometry_path = ROOT / pointer["path"], ROOT / pointer["candidates"]
    bank_report = json.loads((ROOT / pointer["report"]).read_text())
    if sha256_file(bank_path) != pointer["sha256"] or sha256_file(geometry_path) != bank_report["candidate_sha256"]:
        raise ValueError("input bank or geometry hash mismatch")
    dependency_names = ["area_budget_study.py", "artifacts.py", "packing_pilot.py", "surface.py",
        "layout_search_metrics.py", "prototype_metrics.py", "prototype_localization.py", "forward_pilot.py",
        "multiregion_search.py", "multiregion_geometry.py", "fixed64_geometry.py", "metrics.py", "inverse_pilot.py", "surface_admissibility.py"]
    source_files = [args.config, Path(__file__), *[ROOT / "src/compact_eeg" / name for name in dependency_names]]
    identity = {"input_bank_sha256": pointer["sha256"], "geometry_sha256": bank_report["candidate_sha256"],
        "code_config_hashes": {str(p.relative_to(ROOT)): sha256_file(p) for p in source_files},
        "python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__, "blas_threads": 1}
    eligible = None
    if config.get("external_exposure_screen"):
        eligible, admission = load_admissibility(ROOT, bank_report["candidate_sha256"])
        identity.update(admission)
    run_id = semantic_id("fixedunionarea", identity)
    run = ROOT / "results/v2/campaigns" / config["campaign"] / "runs" / run_id
    if args.resume_batch:
        batch = args.resume_batch.resolve()
        if batch.parent.parent != run:
            raise ValueError("resume code/config/input identity mismatch")
    else:
        batch = run / "batches" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        batch.mkdir(parents=True, exist_ok=False)
        atomic_write_json(run / "run_manifest.json", {"identity": identity, "config": config, "run_id": run_id,
            "input_bank_path": pointer["path"], "input_geometry_path": pointer["candidates"]})
    for name in ("conditions", "layouts", "stability"):
        (batch / name).mkdir(exist_ok=True)
    started = time.perf_counter()
    log("batch_started", batch=str(batch), main_conditions=30)
    g, h = np.load(geometry_path, allow_pickle=False), np.load(bank_path, allow_pickle=False)
    vertices, faces, bank_ids = g["surface_vertices_m"], g["surface_triangles"], g["candidate_vertex_indices"]
    if not np.array_equal(bank_ids, h["candidate_vertex_indices"]):
        raise ValueError("candidate bank indexing mismatch")
    adjacency = build_surface_edge_graph(vertices, faces).adjacency
    areas = vertex_area_weights(vertices, faces) * 10000
    if eligible is None:
        eligible = np.ones(len(vertices), bool)
    if len(eligible) != len(vertices):
        raise ValueError("admissibility vertex indexing mismatch")
    domains = {}
    for name, roi in config["domains"].items():
        roi_index = list(g["roi_names"]).index(roi)
        mask = g["surface_roi_masks"][:, roi_index] & eligible
        centers = g["centers_" + roi]
        domains[name] = AreaDomain(vertices, adjacency, bank_ids, areas, mask, centers[mask[centers]])
    n = int(h["dictionary_source_count"])
    hb, hc = h["reference_leadfield_v_per_am"], h["candidate_leadfield_v_per_am"]
    weights = h["source_area_weights"]
    engine = LayoutSearchMetrics(hc[:, :n], hb[:, :n], weights)
    full_rows = np.flatnonzero(eligible[bank_ids])
    coarse_rows = full_rows[nested_coarse_bank(vertices, bank_ids[full_rows], int(len(full_rows) * config["search"]["coarse_candidate_fraction"]))]
    if not (batch / "candidate_density_control.npz").exists():
        write_npz_once(batch / "candidate_density_control.npz", {"full_bank_rows": full_rows, "coarse_bank_rows": coarse_rows})
    metric0 = evaluate_prototype_metrics(hb[:, :n], hb[:, :n], weights, snr_db=[20],
        source_moment_am=config["evaluation"]["source_moment_am"], numerical_zero_relative_tolerance=1e-8).report
    noise_std = float(np.sqrt(metric0["conditions"][0]["shared_physical_electrode_noise_variance_v2"]))

    def localization(leadfield, label):
        return evaluate_grid_localization(leadfield[:, :n], leadfield[:, n:], h["source_xyz_mm"], h["generation_xyz_mm"],
            source_moment_am=config["evaluation"]["source_moment_am"], physical_electrode_noise_std_v=noise_std,
            noise_seed=config["evaluation"]["localization_noise_seed"], layout_id=label,
            noise_repetitions=config["evaluation"]["localization_noise_repetitions"], generation_source_weights=h["generation_area_weights"])

    baseline_path = batch / "baseline.json"
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text())
    else:
        loc = localization(hb, "fixedunion_reference64")
        array_hash = write_npz_once(batch / "baseline.npz", {"errors_mm": loc.errors_mm, "estimates": loc.estimated_dictionary_indices})
        baseline = {"field_metrics": metric0, "localization": loc.report, "array_sha256": array_hash,
            "label": "BioSemi64-name-matched Ernie SPM12 template", "reference_xyz_mm": h["reference_xyz_mm"].tolist()}
        atomic_write_json(baseline_path, baseline)

    def evaluate(snapshot):
        selected = np.sort(np.asarray(snapshot["candidate_bank_indices"], int))
        key = hashlib.sha256(bank_ids[selected].astype('<i8').tobytes()).hexdigest()[:24]
        path = batch / "layouts" / f"{key}.json"
        if path.exists():
            row = json.loads(path.read_text())
            if row["array_sha256"] != sha256_file(batch / "layouts" / f"{key}.npz") or row["candidate_bank_indices"] != selected.tolist():
                raise ValueError("cached result identity mismatch")
            return row
        metric = engine.evaluate(selected, snr_db=[20])
        loc = localization(hc[selected], "fixedunion_" + key)
        sensitivity = metric["source_sensitivity"]["area_weighted_lower_tail_retention_unclipped"]
        field = metric["conditions"][0]["field_retention_unclipped"]
        relative_loc = loc.report["source_lower10_utility_dmax50mm"] / baseline["localization"]["source_lower10_utility_dmax50mm"]
        digest = write_npz_once(batch / "layouts" / f"{key}.npz", {"errors_mm": loc.errors_mm, "estimates": loc.estimated_dictionary_indices})
        row = {"id": key, "candidate_bank_indices": selected.tolist(), "electrode_vertex_indices": bank_ids[selected].tolist(),
            "xyz_mm": h["candidate_xyz_mm"][selected].tolist(), "field20": field, "sensitivity_tail": sensitivity,
            "localization_relative20": relative_loc, "conditional_global20": min(field, sensitivity, relative_loc),
            "localization": loc.report, "field_metrics": metric, "array_sha256": digest,
            "formal_population_ar": False, "localization_optimized": False}
        atomic_write_json(path, row)
        return row

    def run_search(condition, *, center_limit, allowed, warm=(), tag):
        seed = int.from_bytes(hashlib.sha256(f"{config['search']['seed']}:{condition['id']}".encode()).digest()[:4], 'little')
        domain = domains[condition["domain"]]
        master = center_combinations(vertices, domain.center_ids, condition["region_count"], config["search"]["master_center_limit"], seed)
        result = search_area_condition(domain, engine, region_count=condition["region_count"], cap_cm2=condition["area_cap_cm2"],
            allowed_bank_rows=allowed, master_combinations=master, center_limit=center_limit, seed=seed,
            spacing_m=config["spacing_mm"] / 1000, geometry_restarts=config["search"]["geometry_restarts"],
            sweeps=config["search"]["coordinate_sweeps"], proposals=config["search"]["proposals_per_electrode"], warm_starts=warm,
            require_disconnected_regions=config.get("require_disconnected_regions", False))
        result.update(condition=condition, tag=tag, master_center_combinations=[list(c) for c in master],
            allowed_bank_hash=hashlib.sha256(np.asarray(allowed, dtype='<i8').tobytes()).hexdigest())
        for item in result["finalists"]:
            patch = domain.patches(item["final"]["centers"], condition["area_cap_cm2"],
                require_disconnected_regions=config.get("require_disconnected_regions", False))
            item["final"]["surface_patch_vertex_indices"] = [p.tolist() for p in patch["patches"]]
            item["evaluation"] = evaluate(item["final"])
        return result

    planned = conditions(config)
    main_rows = []
    for index, condition in enumerate(planned):
        path = batch / "conditions" / (condition["id"] + ".json")
        if path.exists():
            row = json.loads(path.read_text())
        else:
            if args.max_main_conditions is not None and index >= args.max_main_conditions:
                log("pilot_stopped", elapsed_seconds=time.perf_counter() - started, batch=str(batch))
                return
            step = time.perf_counter()
            row = run_search(condition, center_limit=config["search"]["main_center_limit"], allowed=full_rows, tag="main_full_bank_2x")
            row["elapsed_seconds"] = time.perf_counter() - step
            atomic_write_json(path, row)
            log("main_complete", index=index+1, condition=condition["id"], status=row["status"], seconds=row["elapsed_seconds"])
        main_rows.append(row)
    controls = []
    representatives = [c for c in planned if c["region_count"] in config["search"]["representative_region_counts"] and c["area_cap_cm2"] == config["search"]["representative_area_cm2"]]
    for condition in representatives:
        warm, nested_rows = [], []
        for multiplier, limit in zip([1, 2, 4], config["search"]["nested_center_limits"]):
            path = batch / "stability" / f"{condition['id']}_full_budget{multiplier}x.json"
            if path.exists():
                row = json.loads(path.read_text())
            else:
                row = run_search(condition, center_limit=limit, allowed=full_rows, warm=warm, tag=f"full_nested_budget{multiplier}x")
                atomic_write_json(path, row)
                log("nested_budget_complete", condition=condition["id"], multiplier=multiplier)
            warm.extend(item["final"] for item in row["finalists"])
            nested_rows.append(row)
        density_rows, warm = [], []
        for name, allowed in (("coarse", coarse_rows), ("full", full_rows)):
            path = batch / "stability" / f"{condition['id']}_density_{name}.json"
            if path.exists():
                row = json.loads(path.read_text())
            else:
                row = run_search(condition, center_limit=config["search"]["main_center_limit"], allowed=allowed, warm=warm, tag=f"density_{name}")
                atomic_write_json(path, row)
                log("density_complete", condition=condition["id"], density=name)
            warm.extend(item["final"] for item in row["finalists"])
            density_rows.append(row)
        controls.append({"condition": condition, "nested_budget": nested_rows, "nested_density": density_rows})

    # Independent scalar scoring bypasses the cached exchange engine. Geometry
    # is rechecked from native vertices and explicit connected region masks.
    checks, max_field_difference, max_sensitivity_difference = 0, 0., 0.
    unique_evaluations = {}
    all_searches = main_rows + [r for c in controls for name in ("nested_budget", "nested_density") for r in c[name]]
    for row in all_searches:
        domain = domains[row["condition"]["domain"]]
        allowed = coarse_rows if row["tag"] == "density_coarse" else full_rows
        for item in row["finalists"]:
            snapshot = item["final"]
            domain.validate(snapshot, row["condition"]["area_cap_cm2"], config["spacing_mm"] / 1000, allowed,
                require_disconnected_regions=config.get("require_disconnected_regions", False))
            patch = domain.patches(snapshot["centers"], row["condition"]["area_cap_cm2"],
                require_disconnected_regions=config.get("require_disconnected_regions", False))
            if config.get("require_disconnected_regions", False) and patch["union_connected_component_count"] != row["condition"]["region_count"]:
                raise ValueError("strict physical region count failed independent verification")
            for region in patch["patches"]:
                if connected_components(domain.graph[region][:, region], directed=False)[0] != 1:
                    raise ValueError("region disconnected")
            union = np.unique(np.concatenate(patch["patches"]))
            if abs(float(areas[union].sum()) - snapshot["geometry"]["union_area_cm2"]) > 1e-9:
                raise ValueError("union area recomputation mismatch")
            for move in item["trace"]:
                if move["after"] <= move["before"] + 1e-9:
                    raise ValueError("non-improving accepted move")
            if item["final_score"] + 1e-9 < item["initial_score"]:
                raise ValueError("final objective worsened")
            checks += 7 + len(patch["patches"]) + len(item["trace"])
            unique_evaluations[item["evaluation"]["id"]] = item["evaluation"]
    for value in unique_evaluations.values():
        selected = np.asarray(value["candidate_bank_indices"], int)
        direct = evaluate_prototype_metrics(hb[:, :n], hc[selected, :n], weights, snr_db=[20],
            source_moment_am=config["evaluation"]["source_moment_am"], numerical_zero_relative_tolerance=1e-8).report
        field_delta = abs(direct["conditions"][0]["field_retention_unclipped"] - value["field20"])
        sensitivity_delta = abs(direct["source_sensitivity"]["area_weighted_lower_tail_retention_unclipped"] - value["sensitivity_tail"])
        max_field_difference = max(max_field_difference, field_delta)
        max_sensitivity_difference = max(max_sensitivity_difference, sensitivity_delta)
        if field_delta > 1e-8 or sensitivity_delta > 1e-10:
            raise ValueError("direct reference-free scoring mismatch")
        arr = np.load(batch / "layouts" / (value["id"] + ".npz"))
        actual_errors = np.linalg.norm(h["source_xyz_mm"][arr["estimates"]] - h["generation_xyz_mm"][:, None, :], axis=2)
        if not np.allclose(arr["errors_mm"], actual_errors, rtol=0, atol=1e-10):
            raise ValueError("localization coordinate/error mismatch")
        checks += 3
    for control in controls:
        for family in (control["nested_budget"], control["nested_density"]):
            for objective in ("field20", "min_field_sensitivity20"):
                scores = [next((f["final_score"] for f in row["finalists"] if f["objective"] == objective), None) for row in family]
                available = [s for s in scores if s is not None]
                if any(b + 1e-9 < a for a, b in zip(available, available[1:])):
                    raise ValueError("nested incumbent monotonicity failure")
                checks += max(0, len(available) - 1)
    audit = {"status": "passed", "checks": checks, "unique_layouts_independently_rescored": len(unique_evaluations),
        "maximum_absolute_field_difference": max_field_difference, "maximum_absolute_sensitivity_difference": max_sensitivity_difference,
        "role": "numerical_and_geometry_verification_not_independent_head_or_physical_validation"}
    report = {"schema_version": config["schema_version"], "run_id": run_id, "batch_id": batch.name,
        "config": config, "identity": identity, "baseline": baseline,
        "domain_areas_cm2": {name: float(areas[d.roi_mask].sum()) for name, d in domains.items()},
        "conditions": main_rows, "stability_controls": controls, "audit": audit,
        "main_condition_count": len(main_rows), "main_completed_count": sum(r["status"] == "completed_best_found" for r in main_rows),
        "main_unresolved_count": sum(r["status"] != "completed_best_found" for r in main_rows),
        "unique_layout_count": len(unique_evaluations), "elapsed_seconds_this_process": time.perf_counter() - started,
        "formal_population_ar": False, "independent_head_validation_status": "separate_stage_not_started",
        "limitations": ["One head and existing source/dictionary bank; no fresh-source holdout in this artifact.",
            "Strict separated-region mode requires union-connected-component count equal R; otherwise overlapping-patch mode is explicitly descriptive.",
            "Area caps are equal budgets, not forced equal utilized areas. ROI connected-component exhaustion and discrete shell deficits are explicit.",
            "Common-radius ROI-constrained disks and sorted-center allocation restrict layout family; no arbitrary-shape optimum.",
            "1x/2x/4x are configured nested center prefixes plus inherited incumbents and an additional sweep each stage, not exactly proportional wall time.",
            "Coarse/full are nested finite candidate sets. Full inherits coarse winners; result measures added candidates with extra search, not a globally converged density-only causal effect.",
            "Two objectives are searched separately; localization is post-search diagnostic and source/noise realizations here are not independent selection-free validation.",
            "20 dB labels share the baseline physical noise level, not separately normalized candidate SNR."]}
    report_path = batch / "area_budget_report.json"
    atomic_write_json(report_path, report)
    atomic_write_json(batch / "independent_verification.json", audit)
    pointer_name = "current_strict_area_budget_study.json" if config.get("require_disconnected_regions", False) else "current_area_budget_study.json"
    if not args.no_promote:
        atomic_write_json(ROOT / "results/v2" / pointer_name, {"report": str(report_path.relative_to(ROOT)), "sha256": sha256_file(report_path)})
    log("study_complete", report=str(report_path), audit=audit, elapsed_seconds=report["elapsed_seconds_this_process"])


if __name__ == "__main__":
    with threadpool_limits(limits=1):
        main()
