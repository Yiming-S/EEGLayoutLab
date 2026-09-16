"""Shared native atlas membership for source simulation and cortex display."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

DEFINITION_ID = "dk40-six-roi-v1"
ATLAS_PATH = "webapp/public/models/ernie/source-roi.json"
DEFINITION_PATH = "webapp/public/models/ernie/source-roi-definition.json"
REGIONS = ("frontal", "central", "parietal", "occipital", "temporal_left", "temporal_right")


def load_atlas(root: Path, inputs: dict, source_sha: str) -> dict:
    raw = (root / ATLAS_PATH).read_bytes()
    atlas = json.loads(raw)
    definition_raw = (root / DEFINITION_PATH).read_bytes()
    definition = json.loads(definition_raw)
    if (atlas.get("schema") != "source-roi-atlas/1" or atlas.get("definition_id") != DEFINITION_ID
            or definition.get("id") != DEFINITION_ID or atlas.get("definition") != definition
            or atlas.get("definition_sha256") != hashlib.sha256(definition_raw).hexdigest()
            or atlas.get("source_inputs_sha256") != source_sha):
        raise ValueError("Atlas and frozen source archive identities do not match")
    if [group["id"] for group in definition["groups"]] != list(REGIONS):
        raise ValueError("Atlas ROI order is invalid")
    sources = atlas["generation_sources"]
    if len(sources) != 256 or [s["id"] for s in sources] != list(range(256)):
        raise ValueError("Atlas must retain all 256 original generation sources")
    for field, key in (("xyz_mm", "generation_xyz_mm"), ("normal", "generation_normals")):
        if not np.array_equal(np.asarray([s[field] for s in sources]), inputs[key]):
            raise ValueError(f"Atlas {field} differ from the frozen FEM source geometry")
    for source in sources:
        roi = source["roi_id"]
        if roi is not None and roi not in REGIONS:
            raise ValueError("Unknown source ROI")
        expected = 0 if roi is None else REGIONS.index(roi) + 1
        if source["material_index"] != expected or (source["mixed_roi_boundary"] and roi is not None):
            raise ValueError("Source membership conflicts with native mesh membership")
        labels = source["parent_atlas_labels"]
        names = atlas["atlas_label_names"]
        assigned = []
        for label in labels:
            parcel = names[label] if label >= 0 else "unlabeled"
            matching = [g["id"] for g in definition["groups"] if (0 if source["hemisphere"] == "lh" else 1) in g["hemispheres"] and parcel in g["parcels"]]
            if len(matching) > 1:
                raise ValueError("Overlapping atlas groups")
            assigned.append(matching[0] if matching else None)
        inherited = assigned[0] if len(set(assigned)) == 1 else None
        if len(labels) != 3 or inherited != roi:
            raise ValueError("Source ROI does not follow the three parent atlas labels")
    return {**atlas, "sha256": hashlib.sha256(raw).hexdigest()}


def region_indices(atlas: dict, xyz: np.ndarray, region: str, count: int) -> np.ndarray:
    # Anchors only rank candidates already inside the anatomical ROI. They can
    # never change ROI membership or pull a source across a boundary.
    from .source_reception import REGION_ANCHORS_MM
    available = np.array([s["id"] for s in atlas["generation_sources"] if s["roi_id"] == region], dtype=int)
    if region not in REGIONS or len(available) < count:
        raise ValueError(f"ROI {region} has fewer than {count} original generation sources")
    distance = np.sum((xyz[available] - np.asarray(REGION_ANCHORS_MM[region])) ** 2, axis=1)
    return available[np.lexsort((available, distance))[:count]]


def representatives(atlas: dict, xyz: np.ndarray) -> list[dict]:
    return [{"source_region": region, "generation_source_index": int(region_indices(atlas, xyz, region, 1)[0])}
            for region in REGIONS]


def select_sources(inputs: dict, request: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    atlas = inputs["source_atlas"]
    xyz = np.asarray(inputs["generation_xyz_mm"])
    mode = request["mode"]
    if mode == "single_source":
        ids = np.array([request["source_index"]], dtype=int)
    elif mode == "multi_source":
        ids = region_indices(atlas, xyz, request["brain_region"], 6)
    else:
        ids = np.array([int(region_indices(atlas, xyz, r, 1)[0]) for r in REGIONS if r in request["brain_regions"]])
    weights = np.asarray(inputs["generation_area_weights"])[ids] if mode == "multi_source" else np.ones(len(ids))
    weights = weights / weights.sum()
    selected = [atlas["generation_sources"][i] for i in ids]
    source = {
        "mode": mode, "region": request.get("brain_region", mode),
        "region_definition": DEFINITION_ID, "atlas_sha256": atlas["sha256"],
        "source_regions": [s["roi_id"] for s in selected],
        "source_parcels": [s["parcel_names"] for s in selected],
        "source_hemispheres": [s["hemisphere"] for s in selected],
        "source_parent_triangles": [s["parent_triangle"] for s in selected],
        "selection_method": "Membership from original native-parent-face DK40 atlas labels; nearest-to-fixed-anchor ranking only within each ROI; unassigned or mixed-ROI faces excluded from grouped modes",
        "coordinate_axes": atlas["coordinate_system"], "xyz_mm": xyz[ids].tolist(),
        "patch_count": len(ids), "generation_source_indices": ids.tolist(),
        "bank_source_indices": (int(inputs["dictionary_count"]) + ids).tolist(),
        "patch_area_weights": weights.tolist(), "source_power_weights": weights.tolist(),
        "source_weight_definition": "normalized existing generation-area weights" if mode == "multi_source" else "equal 1/K source-moment power weights, not cortical-area weights",
    }
    if mode == "single_source":
        source["source_index"] = int(ids[0])
    return ids, weights, source
