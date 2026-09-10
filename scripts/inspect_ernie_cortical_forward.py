#!/usr/bin/env python3
"""Record actual source interpolation and template scalp-projection QA only."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[key] = "4"
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compact_eeg.artifacts import atomic_write_json, sha256_file, semantic_id
from compact_eeg.forward_pilot import write_npz_once
from compact_eeg.cortical_fem import FixedMeshLeadfield


def load_head():
    from compact_eeg.workflows.head_model import load_head as load_frozen_head
    return load_frozen_head(ROOT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    args = parser.parse_args()
    path = args.inputs.resolve()
    arrays = np.load(path, allow_pickle=False)
    mesh, cond, vertices, triangles, mapping, hashes = load_head()
    identity = {"inputs": str(path.relative_to(ROOT)), "input_sha256": sha256_file(path), "head_hashes": hashes,
                "script_sha256": sha256_file(Path(__file__)),
                "head_loader_sha256": sha256_file(ROOT / "src/compact_eeg/workflows/head_model.py"),
                "workflow_paths_sha256": sha256_file(ROOT / "src/compact_eeg/workflows/paths.py"), "fem_module_sha256": sha256_file(ROOT / "src/compact_eeg/cortical_fem.py")}
    run_id = semantic_id("corticalqa", identity)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run = ROOT / "results/v2/campaigns/stage2_ernie_cortical_forward_qualification/runs" / run_id
    batch = run / "batches" / stamp
    batch.mkdir(parents=True, exist_ok=False)
    manifest = {"run_id": run_id, "input_identity": identity, "formal_v2_performance_eligible": False}
    if not (run / "run_manifest.json").exists():
        atomic_write_json(run / "run_manifest.json", manifest)
    atomic_write_json(batch / "BATCH_STARTED.json", {"run_id": run_id, "batch_id": stamp})
    start = time.perf_counter()
    try:
        model = FixedMeshLeadfield(mesh, cond, vertices, triangles, mapping,
            np.vstack([arrays["source_xyz_mm"], arrays["generation_xyz_mm"]]),
            np.vstack([arrays["source_normals"], arrays["generation_normals"]]),
            progress=lambda stage, **kw: print(json.dumps({"stage": stage, **kw}), flush=True))
        projection = model.project(arrays["reference_coordinates_requested_mm"])
        n = len(arrays["source_xyz_mm"])
        fallback = model.source_qa_arrays["gm_nearest_node_fallback_mask"][:n]
        distances = model.source_qa_arrays["gm_fallback_distance_mm"][:n]
        area = arrays["source_area_weights"]
        report = {"status": "completed_source_interpolation_and_reference_projection_qa", "run_id": run_id, "batch_id": stamp,
            "formal_v2_performance_eligible": False, "ar_computed": False, "source_qa": model.source_qa,
            "dictionary_fallback_area_fraction": float(area[fallback].sum()),
            "dictionary_fallback_area_fraction_above_distance_mm": {str(d): float(area[distances>d].sum()) for d in (0.5,1,2,3,5,10)},
            "reference_projection_distance_mm_min_median_p95_max": np.quantile(projection.distances_mm,[0,.5,.95,1]).tolist(),
            "reference_unique_projected_coordinates": int(len(np.unique(projection.projected_mm,axis=0))),
            "elapsed_seconds": time.perf_counter()-start,
            "interpretation": "Descriptive registration/interpolation QA. No geometry mask or cortical-domain certification, forward solve or performance calculation."}
        output = dict(model.source_qa_arrays)
        output.update(reference_projected_mm=projection.projected_mm, reference_projection_distances_mm=projection.distances_mm,
                      reference_surface_triangle_ids=projection.triangle_ids, reference_barycentric_weights=projection.barycentric_weights,
                      reference_volume_node_rows=projection.node_rows, formal_v2_performance_eligible=np.array(False))
        report["array_sha256"] = write_npz_once(batch / "cortical_forward_qa_arrays.npz", output)
        atomic_write_json(batch / "cortical_forward_qa_report.json", report)
        atomic_write_json(batch / "BATCH_COMPLETE.json", {"run_id": run_id, "batch_id": stamp, "status": report["status"]})
        print(json.dumps({"report": str(batch / "cortical_forward_qa_report.json"), "summary": report}, indent=2), flush=True)
    except BaseException as error:
        atomic_write_json(batch / "BATCH_FAILED.json", {"run_id": run_id, "batch_id": stamp, "error": str(error)})
        raise


if __name__ == "__main__":
    main()
