"""Frozen Ernie mesh, conductivity and surface loader; native imports are lazy."""
import json
import re
from pathlib import Path
import numpy as np
from compact_eeg.artifacts import sha256_file
from .paths import PROJECT_ROOT

SCENARIO_CONFIG = "configs/conductivity_scenarios.json"
SCENARIO_NAME = re.compile(r"^[a-z0-9]+(?:[_.][a-z0-9]+)*$")


def conductivity_scenario(root, name):
    """Named data-generating conductivity scenario: scaled SimNIBS defaults, nothing arbitrary.

    The identity is the scenario's own content (name, scale factors and the
    resulting conductivities), so unrelated edits to the file do not change it.
    """
    root = Path(root).resolve()
    if not isinstance(name, str) or len(name) > 40 or not SCENARIO_NAME.fullmatch(name):
        raise ValueError("conductivity scenario name must be a short lowercase identifier")
    scenarios = json.loads((root / SCENARIO_CONFIG).read_text())
    if scenarios.get("schema") != "eeglayoutlab-conductivity-scenarios/1" or name not in scenarios.get("scenarios", {}):
        raise ValueError(f"unknown conductivity scenario: {name}")
    base = json.loads((root / "configs/ernie_fem_point_pilot.json").read_text())["isotropic_conductivity_by_tetrahedron_tag"]
    scales = scenarios["scenarios"][name]["scale_by_tetrahedron_tag"]
    if not scales or set(scales) - set(base) or any(type(v) is not float or not 0 < v <= 10 for v in scales.values()):
        raise ValueError("scenario scales must name existing tissue tags with factors in (0, 10]")
    conductivities = {tag: value * scales.get(tag, 1.0) for tag, value in base.items()}
    return {"name": name, "scale_by_tetrahedron_tag": dict(sorted(scales.items())),
            "conductivity_by_tetrahedron_tag": conductivities, "conductivity_unit": "S/m"}


def load_head(root=PROJECT_ROOT, scenario=None):
    """Frozen Ernie head; ``scenario`` names a data-generating conductivity set.

    Without a scenario every tissue keeps the official SimNIBS default. A
    scenario scales the verified defaults by its declared factors only.
    """
    root = Path(root).resolve()
    scaled = conductivity_scenario(root, scenario) if scenario is not None else None
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
        cond[mesh.elm.get_tetrahedra(int(tag))] = value if scaled is None else scaled["conductivity_by_tetrahedron_tag"][str(tag)]
    inputs = {"fem_config": sha256_file(root / "configs/ernie_fem_point_pilot.json"), "mesh": config["mesh_sha256"],
              "scalp_mapping": config["external_node_mapping_sha256"], "scalp_vertices": sha256_file(scalp / "external_scalp_vertices_m.npy"),
              "scalp_triangles": sha256_file(scalp / "external_scalp_triangles.npy")}
    return mesh, cond, vertices, triangles, mapping, inputs


def load_scalp(root=PROJECT_ROOT):
    """Frozen exterior surface and node mapping, without reading the volume mesh.

    The mesh entry is the configuration's declared SHA256 (the configuration
    itself is hashed); callers compare all five values with the frozen head.
    """
    root = Path(root).resolve()
    config_path = root / "configs/ernie_fem_point_pilot.json"
    config = json.loads(config_path.read_text())
    mapping_path = root / config["external_node_mapping_path"]
    if sha256_file(mapping_path) != config["external_node_mapping_sha256"]:
        raise ValueError("head input checksum mismatch")
    scalp = mapping_path.parent
    mapping = np.load(mapping_path, allow_pickle=False)
    vertices = np.load(scalp / "external_scalp_vertices_m.npy", allow_pickle=False)*1000
    triangles = np.load(scalp / "external_scalp_triangles.npy", allow_pickle=False)
    inputs = {"fem_config": sha256_file(config_path), "mesh": config["mesh_sha256"],
              "scalp_mapping": config["external_node_mapping_sha256"], "scalp_vertices": sha256_file(scalp / "external_scalp_vertices_m.npy"),
              "scalp_triangles": sha256_file(scalp / "external_scalp_triangles.npy")}
    return vertices, triangles, mapping, inputs
