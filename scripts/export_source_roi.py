"""Export native DK-defined source ROIs without recomputing a forward field.

Uses the original source archive, pinned central/registered sphere assets and
SimNIBS DK40 templates. Fails if transferred labels or source geometry differ.
The public binary and source catalog are derived data; H is never written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import nibabel as nib
import numpy as np
from scipy.spatial import cKDTree


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export(root, subject, source_path, config_path):
    import simnibs
    from simnibs.mesh_tools import mesh_io

    public = root / "webapp/public/models/ernie"
    definition_path = public / "source-roi-definition.json"
    definition = json.loads(definition_path.read_text())
    config = json.loads(config_path.read_text())
    atlas = config["atlas_source_domain"]
    templates = Path(simnibs.__file__).parent / "resources/templates"
    inputs = {}
    for name, sha in atlas["template_asset_sha256"].items():
        if digest(templates / name) != sha:
            raise ValueError(f"Template identity mismatch: {name}")
        inputs[name] = sha
    arrays = np.load(source_path, allow_pickle=False)
    generation = [None] * len(arrays["generation_xyz_mm"])
    dictionary = [None] * len(arrays["source_xyz_mm"])
    all_xyz, all_normals, all_tri, all_face_roi = [], [], [], []
    offset = 0
    diagnostics = []
    names_common = None
    for h, hemi in enumerate(("lh", "rh")):
        for suffix, sha in (("central", config["source_surface_sha256"][hemi]),
                            ("sphere.reg", atlas["sphere_reg_sha256"][hemi])):
            path = subject / "surfaces" / f"{hemi}.{suffix}.gii"
            if digest(path) != sha:
                raise ValueError(f"Native surface identity mismatch: {path.name}")
            inputs[path.name] = sha
        surface = mesh_io.read_gifti_surface(str(subject / "surfaces" / f"{hemi}.central.gii"))
        xyz = surface.nodes.node_coord.copy()
        tri = surface.elm.node_number_list[:, :3] - 1
        normals = surface.nodes_normals().value
        labels, _, names_bytes = nib.freesurfer.io.read_annot(templates / f"fsaverage_atlases/{hemi}.aparc_DK40.annot")
        names = [name.decode() for name in names_bytes]
        if names_common is not None and names != names_common:
            raise ValueError("Hemisphere atlas name/index tables differ")
        names_common = names
        sphere = mesh_io.read_gifti_surface(str(subject / "surfaces" / f"{hemi}.sphere.reg.gii")).nodes.node_coord
        template = mesh_io.read_gifti_surface(str(templates / f"fsaverage_surf/{hemi}.sphere.gii")).nodes.node_coord
        unit = lambda p: p / np.linalg.norm(p, axis=1)[:, None]
        _, nearest = cKDTree(unit(template)).query(unit(sphere))
        native_labels = arrays[f"{hemi}_native_atlas_labels"]
        if not np.array_equal(labels[nearest], native_labels):
            raise ValueError("Atlas registration does not reproduce frozen labels")
        vertex_roi = np.zeros(len(xyz), dtype=np.uint8)
        for index, group in enumerate(definition["groups"], 1):
            if h not in group["hemispheres"]:
                continue
            ids = [names.index(name) for name in group["parcels"]]
            mask = np.isin(native_labels, ids)
            if np.any(vertex_roi[mask]):
                raise ValueError("Overlapping ROI definitions")
            vertex_roi[mask] = index
        tri_roi = vertex_roi[tri]
        face_roi = np.where(np.all(tri_roi == tri_roi[:, :1], axis=1), tri_roi[:, 0], 0)
        source_ids = np.flatnonzero(arrays["source_hemisphere"] == h)
        vertices = arrays["source_native_vertex_indices"][source_ids]
        if not np.array_equal(native_labels[vertices], arrays[f"{hemi}_source_atlas_labels"]):
            raise ValueError("Dictionary atlas labels changed")
        if not np.allclose(xyz[vertices], arrays["source_xyz_mm"][source_ids], atol=1e-9, rtol=0):
            raise ValueError("Dictionary positions changed")
        for i, vertex in zip(source_ids, vertices):
            dictionary[int(i)] = int(vertex_roi[vertex])
        gen_ids = np.flatnonzero(arrays["generation_hemisphere"] == h)
        faces = arrays["generation_triangle_indices"][gen_ids]
        bary = arrays["generation_barycentric_weights"][gen_ids]
        generated_xyz = np.einsum("ij,ijk->ik", bary, xyz[tri[faces]])
        generated_normal = np.einsum("ij,ijk->ik", bary, normals[tri[faces]])
        generated_normal /= np.linalg.norm(generated_normal, axis=1)[:, None]
        if not np.allclose(generated_xyz, arrays["generation_xyz_mm"][gen_ids], atol=1e-9, rtol=0):
            raise ValueError("Generation positions do not match original parent faces")
        if not np.allclose(generated_normal, arrays["generation_normals"][gen_ids], atol=1e-9, rtol=0):
            raise ValueError("Generation normals changed")
        for i, face in zip(gen_ids, faces):
            roi_index = int(face_roi[face])
            parcel_ids = native_labels[tri[face]].tolist()
            generation[int(i)] = {
                "id": int(i), "roi_id": definition["groups"][roi_index - 1]["id"] if roi_index else None,
                "material_index": roi_index, "hemisphere": hemi,
                "parent_triangle": int(face), "parent_vertex_indices": tri[face].tolist(),
                "parent_atlas_labels": parcel_ids,
                "parcel_names": sorted({names[label] if label >= 0 else "unlabeled" for label in parcel_ids}),
                "mixed_roi_boundary": bool(len(set(tri_roi[face])) > 1),
                "xyz_mm": arrays["generation_xyz_mm"][i].tolist(),
                "normal": arrays["generation_normals"][i].tolist(),
            }
        diagnostics.append({"hemisphere": hemi, "vertices": len(xyz), "faces": len(tri),
                            "labels_reproduced_exactly": True, "geometry_matches_frozen_sources": True})
        all_xyz.append(xyz / 1000)
        all_normals.append(normals)
        all_tri.append(tri + offset)
        all_face_roi.append(face_roi)
        offset += len(xyz)
    xyz = np.concatenate(all_xyz).astype("<f4")
    normals = np.round(np.clip(np.concatenate(all_normals), -1, 1) * 127).astype("i1")
    faces = np.concatenate(all_tri)
    face_rois = np.concatenate(all_face_roi)
    permutation = np.argsort(face_rois, kind="stable")
    remap = np.empty(len(permutation), dtype=int)
    remap[permutation] = np.arange(len(permutation))
    for entry in generation:
        original_face = entry["parent_triangle"] + (len(all_tri[0]) if entry["hemisphere"] == "rh" else 0)
        entry["display_triangle"] = int(remap[original_face])
    triangles = faces[permutation].astype("<u4")
    groups = []
    start = 0
    for roi in range(7):
        count = int(np.count_nonzero(face_rois == roi)) * 3
        groups.append({"start": start, "count": count, "materialIndex": roi})
        start += count
    position_bytes, normal_bytes = xyz.tobytes(), normals.tobytes()
    padding = b"\0" * ((-len(position_bytes) - len(normal_bytes)) % 4)
    index_offset = len(position_bytes) + len(normal_bytes) + len(padding)
    binary = position_bytes + normal_bytes + padding + triangles.tobytes()
    binary_path = public / "source-roi-cortex.bin"
    binary_path.write_bytes(binary)
    counts = {group["id"]: sum(entry["roi_id"] == group["id"] for entry in generation) for group in definition["groups"]}
    if min(counts.values()) < 6:
        raise ValueError(f"At least one ROI lacks six original generators: {counts}")
    attribute = lambda kind, offset, count, size, normalized=False: dict(type=kind, byteOffset=offset, count=count, itemSize=size, normalized=normalized)
    output = {
        "schema": "source-roi-atlas/1", "definition_id": definition["id"],
        "definition_sha256": digest(definition_path), "definition": definition,
        "source_inputs_sha256": digest(source_path), "input_sha256": inputs,
        "atlas_label_names": names_common,
        "mapping": "Existing DK40 template-to-Ernie registered-sphere nearest-vertex label transfer, reproduced byte-for-byte; original native parent triangles, not Euclidean coordinate-anchor cells.",
        "coordinate_system": "Ernie MRI: X right, Y anterior, Z superior; millimetres",
        "mesh": {"id":"cortex", "file": binary_path.name, "sha256": digest(binary_path),
                 "attributes": {"position":attribute("Float32Array",0,xyz.size,3), "normal":attribute("Int8Array",len(position_bytes),normals.size,3,True)},
                 "index":attribute("Uint32Array",index_offset,triangles.size,1), "groups":groups},
        "generation_sources": generation, "dictionary_roi_indices": dictionary,
        "generation_counts": counts, "unassigned_generation_count": sum(entry["roi_id"] is None for entry in generation),
        "validation": diagnostics,
        "provenance": {"exporter_sha256":digest(__file__), "source_surface":"Ernie native central cortical surfaces; original geometry, no deformation or simplification", "license":"Ernie example data: CC BY-NC 4.0; DK atlas labels distributed with SimNIBS/FreeSurfer retain their original notices"},
    }
    (public / "source-roi.json").write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({"counts":counts, "unassigned":output["unassigned_generation_count"], "vertices":len(xyz), "faces":len(faces), "binary_bytes":len(binary), "validation":diagnostics}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--subject", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--source-config", type=Path, required=True)
    args = parser.parse_args()
    export(args.repository_root, args.subject, args.source_archive, args.source_config)
