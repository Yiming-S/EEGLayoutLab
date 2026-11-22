"""Build the Ernie scalp <-> MNI mapping used by coordinate import and export.

Outputs, next to the web application's other data:

* ``webapp/public/data/ernie-scalp-mni.bin``: float32 little-endian MNI
  coordinates in mm, one row per vertex of ``webapp/public/models/ernie/scalp.bin``
  (the forward bank's exterior scalp surface, same vertex order and triangles),
  followed by one uint8 per triangle: 1 where the warp is usable.
* ``webapp/public/data/ernie-mni-mapping.json``: bindings to both buffers,
  Ernie and MNI landmarks, the 10-05 cap labels in Ernie space, the method and
  the verification numbers.

The MNI coordinates come from SimNIBS ``subject2mni_coords`` (nonlinear,
``toMNI/Conform2MNI_nonl.nii.gz``) evaluated at every scalp vertex: the same
transform the cross-head packages use. Points between vertices are mapped by
barycentric interpolation on the scalp triangle they project onto.

The warp is not usable on the lower face, ears and neck: some vertices there
have no warp value (all zeros) and many triangles are stretched far beyond any
anatomical difference. A triangle is usable when none of its vertices is
all-zero and each edge's MNI/native length ratio lies within
[1/STRETCH_LIMIT, STRETCH_LIMIT]. Mapping uses usable triangles only.

Requires the SimNIBS runtime, the restored data bundle and the full SimNIBS
Ernie example dataset (``m2m_ernie`` with ``toMNI`` and ``eeg_positions``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "src"))

SCHEMA = "eeglayoutlab-ernie-mni-mapping/1"
CAP = "EEG10-20_extended_SPM12"
MNI_SYSTEM = "MNI152NLin6Asym"
OUTPUT = SOURCE_ROOT / "webapp/public/data"
MODELS = SOURCE_ROOT / "webapp/public/models/ernie"
REFERENCE_NAMES = SOURCE_ROOT / "webapp/public/data/biosemi64_reference.json"
ERNIE_M2M = Path("data/external/simnibs4_examples/m2m_ernie")
# The import tolerance between an MNI point and Ernie's scalp warped to MNI,
# equal to the cross-head mapping tolerance (head_package.LAYOUT_PROJECTION_LIMIT_MM).
MNI_IMPORT_LIMIT_MM = 10.0
# Export accepts coordinates the evaluator would accept (design_evaluation: 2 mm).
NATIVE_EXPORT_LIMIT_MM = 2.0
STRETCH_LIMIT = 3.0
GOLDEN_LABELS = ["Fp1", "Fz", "Cz", "T7", "T8", "Pz", "Oz", "TP9", "AFp3h", "PO10"]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_cap(path: Path) -> list[tuple[str, str, np.ndarray]]:
    rows = []
    for line in path.read_text().splitlines():
        fields = line.strip().split(",")
        if len(fields) < 5:
            continue
        rows.append((fields[0], fields[4], np.array([float(value) for value in fields[1:4]])))
    return rows


def stats(values: np.ndarray) -> dict:
    values = np.asarray(values, dtype=float)
    return {"maximum": float(values.max()), "median": float(np.median(values)), "count": int(len(values))}


def scalp_buffer() -> tuple[np.ndarray, np.ndarray, dict]:
    manifest = json.loads((MODELS / "manifest.json").read_text())
    mesh = next(entry for entry in manifest["meshes"] if entry["id"] == "scalp")
    raw = (MODELS / mesh["file"]).read_bytes()
    if sha256_bytes(raw) != mesh["sha256"]:
        raise SystemExit("scalp.bin does not match its manifest")
    position, index = mesh["attributes"]["position"], mesh["index"]
    vertices = np.frombuffer(raw, "<f4", count=position["count"], offset=position["byteOffset"]).reshape(-1, 3)
    faces = np.frombuffer(raw, "<u2", count=index["count"], offset=index["byteOffset"]).reshape(-1, 3)
    return vertices.astype(np.float64) * 1000.0, faces.astype(np.int64), mesh


def usable_triangles(native, mni, faces):
    zero = np.all(mni == 0, axis=1)
    ratios = np.stack([np.linalg.norm(mni[faces[:, i]] - mni[faces[:, j]], axis=1) /
                       np.linalg.norm(native[faces[:, i]] - native[faces[:, j]], axis=1)
                       for i, j in ((0, 1), (1, 2), (2, 0))], axis=1)
    return ~zero[faces].any(axis=1) & (ratios.max(axis=1) <= STRETCH_LIMIT) & (ratios.min(axis=1) >= 1 / STRETCH_LIMIT), int(zero.sum())


def readable_json(value) -> str:
    """Indented JSON with each innermost list (numbers or names, no commas inside strings) on one line."""
    text = json.dumps(value, indent=1)
    return re.sub(r"\[\s*([^\[\]{}]*?)\s*\]", lambda match: "[" + ", ".join(part.strip() for part in match.group(1).split(",")) + "]", text) + "\n"


def surface_map(points, from_vertices, faces, to_vertices):
    from compact_eeg.workflows import scalp_node_table

    projection = scalp_node_table.project(from_vertices, faces, points)
    mapped = np.einsum("kj,kjc->kc", projection["barycentric_weights"], to_vertices[projection["vertex_rows"]])
    return mapped, projection["distances_mm"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository-root", default=".", help="checkout with the restored data bundle")
    parser.add_argument("--ernie-m2m", default=str(ERNIE_M2M), help="full Ernie m2m folder, relative to the root")
    parser.add_argument("--output-dir", default=str(OUTPUT))
    args = parser.parse_args()

    import nibabel
    import simnibs
    from simnibs import mni2subject_coords, subject2mni_coords

    from compact_eeg.workflows import design_evaluation as de

    root = Path(args.repository_root).resolve()
    data, pointer, report = de.load_bank(root)
    vertices, faces = np.asarray(data["_surface_vertices_mm"], float), np.asarray(data["_surface_faces"], np.int64)
    display_vertices, display_faces, display = scalp_buffer()
    if display_vertices.shape != vertices.shape or not np.array_equal(display_faces, faces):
        raise SystemExit("scalp.bin is not the forward bank's scalp surface")
    display_rounding = float(np.abs(display_vertices - vertices).max())
    if display_rounding > 1e-4:
        raise SystemExit(f"scalp.bin vertices differ from the bank by {display_rounding} mm")

    m2m = (root / args.ernie_m2m).resolve()
    mesh_sha = json.loads((SOURCE_ROOT / "configs/ernie_fem_point_pilot.json").read_text())["mesh_sha256"]
    if sha256_file(m2m / "ernie.msh") != mesh_sha:
        raise SystemExit("The Ernie m2m folder is not the frozen Ernie head")
    resources = Path(simnibs.__file__).parent / "resources"
    template = nibabel.load(str(resources / "templates/MNI152_T1_1mm.nii.gz"))
    fsl_affine = np.array([[-1, 0, 0, 90], [0, 1, 0, -126], [0, 0, 1, -72], [0, 0, 0, 1]], float)
    if template.shape != (182, 218, 182) or not np.allclose(template.affine, fsl_affine):
        raise SystemExit("SimNIBS MNI template is not FSL MNI152_T1_1mm")

    mni = np.asarray(subject2mni_coords(vertices, str(m2m)), float)
    if mni.shape != vertices.shape or not np.all(np.isfinite(mni)):
        raise SystemExit("subject2mni_coords returned invalid coordinates")
    mni32 = mni.astype("<f4")
    usable, zero_vertices = usable_triangles(display_vertices, mni32.astype(float), faces)
    mni_bytes = mni32.tobytes() + usable.astype(np.uint8).tobytes()
    usable_faces = faces[usable]
    candidate_rows = np.asarray(data["candidate_vertex_indices"], np.int64)
    unusable_vertices = np.unique(faces[~usable].ravel())

    native_cap = read_cap(m2m / "eeg_positions" / f"{CAP}.csv")
    mni_cap = {name: xyz for kind, name, xyz in read_cap(resources / "ElectrodeCaps_MNI" / f"{CAP}.csv")
               if kind in ("Electrode", "ReferenceElectrode")}
    native_fiducials = {name: xyz for kind, name, xyz in read_cap(m2m / "eeg_positions/Fiducials.csv")}
    mni_fiducials = {name: xyz for kind, name, xyz in read_cap(resources / "ElectrodeCaps_MNI/Fiducials.csv")}
    labels = [(kind, name, xyz) for kind, name, xyz in native_cap if kind in ("Electrode", "ReferenceElectrode")]
    names = [name for _, name, _ in labels]
    if len(set(name.lower() for name in names)) != len(names) or set(names) != set(mni_cap):
        raise SystemExit("cap label sets differ between Ernie and MNI files")
    native_xyz = np.array([xyz for _, _, xyz in labels])
    mni_xyz = np.array([mni_cap[name] for name in names])

    biosemi = [channel["name"] for channel in json.loads(REFERENCE_NAMES.read_text())["channels"]]
    lookup = dict(zip(names, native_xyz))
    reference_difference = float(np.abs(np.array([lookup[name] for name in biosemi]) - data["reference_xyz_mm"]).max())
    if reference_difference > 1e-9:
        raise SystemExit("standard64 reference is not the BioSemi64-named cap positions")

    from compact_eeg.workflows import scalp_node_table

    cap_projection = scalp_node_table.project(vertices, faces, native_xyz)
    cap_on_scalp = cap_projection["distances_mm"]
    cap_on_unusable = [name for name, triangle in zip(names, cap_projection["triangle_ids"]) if not usable[triangle]]
    inverse, inverse_surface = surface_map(mni_xyz, mni32.astype(float), usable_faces, display_vertices)
    forward, forward_surface = surface_map(native_xyz, display_vertices, usable_faces, mni32.astype(float))
    on_usable = forward_surface <= 1e-4  # float32 display vertices round by < 1e-5 mm
    direct_forward = np.asarray(subject2mni_coords(native_xyz, str(m2m)), float)
    direct_inverse = np.asarray(mni2subject_coords(mni_xyz, str(m2m)), float)
    fiducial_names = ["Nz", "LPA", "RPA", "Iz"]
    # Cross-language checks: the web application must reproduce these values.
    golden_rows = [names.index(name) for name in GOLDEN_LABELS]
    inverse_golden, _ = surface_map(mni_xyz[golden_rows], mni32.astype(float), usable_faces, display_vertices)

    manifest = {
        "schema": SCHEMA,
        "subject": "SimNIBS example subject Ernie",
        "native": {"coordinate_system": "ernie_native_mm", "unit": "mm",
                   "description": "SimNIBS world coordinates of the Ernie head (x right, y anterior, z superior), mm."},
        "mni": {"coordinate_system": MNI_SYSTEM, "unit": "mm",
                "template": "SimNIBS resources/templates/MNI152_T1_1mm.nii.gz (FSL 5.0 MNI152 nonlinear 6th generation)",
                "import_systems_note": "Other MNI templates are mapped with the same transform; template differences are not modelled."},
        "method": {
            "id": "ernie-mni-scalp/1",
            "vertices": "SimNIBS subject2mni_coords(transformation_type='nonl') at every Ernie scalp vertex",
            "between_vertices": "barycentric interpolation on the scalp triangle the point projects onto",
            "inverse": "projection onto Ernie's scalp warped to MNI, then the same barycentric weights on the native scalp",
            "usable_triangles": f"no all-zero warp vertex and every edge's MNI/native length ratio within [1/{STRETCH_LIMIT:g}, {STRETCH_LIMIT:g}]",
            "mni_import_limit_mm": MNI_IMPORT_LIMIT_MM,
            "native_export_limit_mm": NATIVE_EXPORT_LIMIT_MM,
        },
        "scalp_buffer": {"file": "/models/ernie/scalp.bin", "sha256": display["sha256"], "vertices": int(len(vertices)),
                         "triangles": int(len(faces)), "position_byte_offset": display["attributes"]["position"]["byteOffset"],
                         "index_byte_offset": display["index"]["byteOffset"], "position_unit": "m",
                         "bank_rounding_max_mm": display_rounding},
        "mni_buffer": {"file": "/data/ernie-scalp-mni.bin", "sha256": sha256_bytes(mni_bytes), "byte_length": len(mni_bytes),
                       "layout": "float32 little-endian x,y,z per scalp vertex (mm), then uint8 per triangle (1 = usable)",
                       "usable_triangles": int(usable.sum()), "zero_warp_vertices": zero_vertices,
                       "bank_candidates_on_unusable_triangles": int(np.isin(candidate_rows, unusable_vertices).sum()),
                       "bank_candidates": int(len(candidate_rows))},
        "landmarks": {
            "source": "SimNIBS charm eeg_positions/Fiducials.csv (template landmarks mapped to Ernie) and resources/ElectrodeCaps_MNI/Fiducials.csv",
            "provenance": "template landmarks, not digitized",
            "native_mm": {name: native_fiducials[name].tolist() for name in fiducial_names},
            "mni_mm": {name: mni_fiducials[name].tolist() for name in fiducial_names},
        },
        "labels": {
            "cap": CAP,
            "source": f"SimNIBS charm eeg_positions/{CAP}.csv: the SimNIBS MNI cap positions mapped to Ernie and placed on the skin",
            "provenance": "template positions, not digitized",
            "aliases": {"T3": "T7", "T4": "T8", "T5": "P7", "T6": "P8"},
            "positions_mm": [[name, *xyz.tolist()] for name, xyz in zip(names, native_xyz)],
        },
        "inputs": {
            "bank_sha256": pointer["sha256"], "ernie_mesh_sha256": mesh_sha,
            "conform2mni_sha256": sha256_file(m2m / "toMNI/Conform2MNI_nonl.nii.gz"),
            "mni2conform_sha256": sha256_file(m2m / "toMNI/MNI2Conform_nonl.nii.gz"),
            "native_cap_sha256": sha256_file(m2m / "eeg_positions" / f"{CAP}.csv"),
            "mni_cap_sha256": sha256_file(resources / "ElectrodeCaps_MNI" / f"{CAP}.csv"),
            "native_fiducials_sha256": sha256_file(m2m / "eeg_positions/Fiducials.csv"),
            "mni_fiducials_sha256": sha256_file(resources / "ElectrodeCaps_MNI/Fiducials.csv"),
        },
        "verification": {
            "standard64_reference_vs_cap_max_mm": reference_difference,
            "cap_to_scalp_distance_mm": stats(cap_on_scalp),
            "cap_labels_on_unusable_triangles": cap_on_unusable,
            "mni_cap_to_warped_scalp_mm": stats(inverse_surface),
            "mni_cap_inverse_vs_ernie_cap_mm": stats(np.linalg.norm(inverse - native_xyz, axis=1)),
            "ernie_cap_forward_vs_mni_cap_mm": stats(np.linalg.norm(forward - mni_xyz, axis=1)[on_usable]),
            "surface_forward_vs_direct_warp_mm": stats(np.linalg.norm(forward - direct_forward, axis=1)[on_usable]),
            "direct_inverse_vs_ernie_cap_mm": stats(np.linalg.norm(direct_inverse - native_xyz, axis=1)),
            "note": "forward rows use cap labels on usable triangles only",
        },
        "golden": {
            "standard64": {"source": "forward bank reference_xyz_mm in BioSemi64 order", "names": biosemi,
                           "xyz_mm": np.asarray(data["reference_xyz_mm"], float).tolist()},
            "surface_mapping": {"source": "Python barycentric surface mapping (cortech projection) on usable triangles",
                                "labels": GOLDEN_LABELS,
                                "ernie_to_mni_mm": forward[golden_rows].tolist(),
                                "mni_cap_mm": mni_xyz[golden_rows].tolist(),
                                "mni_cap_to_ernie_mm": inverse_golden.tolist()},
        },
        "license": {
            "spdx": "CC-BY-NC-4.0",
            "attribution": "Derived from SimNIBS example dataset v4.1, Ernie head model. (c) SimNIBS developers 2024. CC BY-NC 4.0.",
            "cap_note": f"MNI cap and fiducial positions from SimNIBS {simnibs.__version__} resources (GPL-3.0).",
        },
        "builder": {"path": "scripts/build_ernie_mni_mapping.py", "sha256": sha256_file(Path(__file__)),
                    "simnibs": simnibs.__version__, "numpy": np.__version__},
    }
    manifest["mapping_id"] = sha256_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name, payload in (("ernie-scalp-mni.bin", mni_bytes), ("ernie-mni-mapping.json", readable_json(manifest).encode())):
        tmp = output / (name + ".tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, output / name)
    print(json.dumps({"mapping_id": manifest["mapping_id"], **manifest["verification"]}, indent=1))


if __name__ == "__main__":
    main()
