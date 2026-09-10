"""Frozen Ernie mesh, conductivity and surface loader; native imports are lazy."""
import json
from pathlib import Path
import numpy as np
from compact_eeg.artifacts import sha256_file
from .paths import PROJECT_ROOT

def load_head(root=PROJECT_ROOT):
    root = Path(root).resolve()
    from simnibs.mesh_tools import mesh_io
    from simnibs.utils import mesh_element_properties
    config = json.loads((root / "configs/ernie_fem_point_pilot.json").read_text())
    mesh_path = root / config["mesh_path"]
    mapping_path = root / config["external_node_mapping_path"]
    if sha256_file(mesh_path) != config["mesh_sha256"] or sha256_file(mapping_path) != config["external_node_mapping_sha256"]:
        raise ValueError("head input checksum mismatch")
    mesh = mesh_io.read_msh(str(mesh_path))
    scalp = mapping_path.parent
    mapping = np.load(mapping_path, allow_pickle=False)
    vertices = np.load(scalp / "external_scalp_vertices_m.npy", allow_pickle=False)*1000
    triangles = np.load(scalp / "external_scalp_triangles.npy", allow_pickle=False)
    cond = np.zeros(mesh.elm.nr)
    for tag in np.unique(mesh.elm.tag1[mesh.elm.get_tetrahedra()]):
        value = config["isotropic_conductivity_by_tetrahedron_tag"][str(tag)]
        if mesh_element_properties.tissue_conductivities[int(tag)] != value:
            raise ValueError("official conductivity default mismatch")
        cond[mesh.elm.get_tetrahedra(int(tag))] = value
    inputs = {"fem_config": sha256_file(root / "configs/ernie_fem_point_pilot.json"), "mesh": config["mesh_sha256"],
              "scalp_mapping": config["external_node_mapping_sha256"], "scalp_vertices": sha256_file(scalp / "external_scalp_vertices_m.npy"),
              "scalp_triangles": sha256_file(scalp / "external_scalp_triangles.npy")}
    return mesh, cond, vertices, triangles, mapping, inputs
