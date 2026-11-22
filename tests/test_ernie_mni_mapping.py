"""Integrity of the shipped Ernie <-> MNI mapping (no data bundle or SimNIBS needed)."""

import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "webapp/public"
MAPPING = json.loads((PUBLIC / "data/ernie-mni-mapping.json").read_text())


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_mapping_is_bound_to_its_buffers_builder_and_content():
    display = json.loads((PUBLIC / "models/ernie/manifest.json").read_text())
    scalp = next(mesh for mesh in display["meshes"] if mesh["id"] == "scalp")
    assert MAPPING["scalp_buffer"]["sha256"] == scalp["sha256"] == sha256(PUBLIC / "models/ernie/scalp.bin")
    assert MAPPING["mni_buffer"]["sha256"] == sha256(PUBLIC / "data/ernie-scalp-mni.bin")
    assert MAPPING["builder"]["sha256"] == sha256(ROOT / MAPPING["builder"]["path"]), "rebuild the mapping after changing its builder"
    content = {key: value for key, value in MAPPING.items() if key != "mapping_id"}
    assert MAPPING["mapping_id"] == hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_buffer_layout_and_usable_triangles():
    vertices, triangles = MAPPING["scalp_buffer"]["vertices"], MAPPING["scalp_buffer"]["triangles"]
    raw = (PUBLIC / "data/ernie-scalp-mni.bin").read_bytes()
    assert len(raw) == MAPPING["mni_buffer"]["byte_length"] == vertices * 12 + triangles
    mni = np.frombuffer(raw, "<f4", count=vertices * 3).reshape(-1, 3)
    usable = np.frombuffer(raw, np.uint8, offset=vertices * 12)
    assert np.all(np.isfinite(mni)) and set(np.unique(usable)) <= {0, 1}
    assert int(usable.sum()) == MAPPING["mni_buffer"]["usable_triangles"]
    assert int(np.all(mni == 0, axis=1).sum()) == MAPPING["mni_buffer"]["zero_warp_vertices"]
    # The unusable part is a minority on the lower head; electrode sites of the bank are almost all usable.
    assert usable.mean() > 0.9
    assert MAPPING["mni_buffer"]["bank_candidates_on_unusable_triangles"] < 0.01 * MAPPING["mni_buffer"]["bank_candidates"]


def test_labels_landmarks_and_verification():
    labels = MAPPING["labels"]
    names = [row[0] for row in labels["positions_mm"]]
    assert len(names) == len({name.lower() for name in names}) == 343
    assert all(target in names for target in labels["aliases"].values())
    golden = MAPPING["golden"]["standard64"]
    assert len(golden["names"]) == 64 and set(golden["names"]) <= set(names)
    lookup = {row[0]: row[1:] for row in labels["positions_mm"]}
    assert np.abs(np.array([lookup[name] for name in golden["names"]]) - np.array(golden["xyz_mm"])).max() < 1e-9
    native, mni = MAPPING["landmarks"]["native_mm"], MAPPING["landmarks"]["mni_mm"]
    for frame in (native, mni):  # x right, y anterior: RPA right of LPA, nasion in front of both
        assert frame["RPA"][0] > frame["LPA"][0] and frame["Nz"][1] > max(frame["LPA"][1], frame["RPA"][1]) > frame["Iz"][1]
    check = MAPPING["verification"]
    assert check["standard64_reference_vs_cap_max_mm"] < 1e-9 and check["cap_to_scalp_distance_mm"]["maximum"] < 1e-9
    assert check["cap_labels_on_unusable_triangles"] == []
    assert check["mni_cap_to_warped_scalp_mm"]["maximum"] <= MAPPING["method"]["mni_import_limit_mm"]
    assert check["surface_forward_vs_direct_warp_mm"]["maximum"] < 0.5
