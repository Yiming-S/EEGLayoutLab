"""Versioned geometric exposure screen; not an anatomical skin annotation."""
from pathlib import Path
import json
import numpy as np
from .artifacts import sha256_file

POINTER = "results/v2/current_surface_admissibility.json"


def load_admissibility(root, geometry_sha256=None):
    root = Path(root)
    pointer = json.loads((root / POINTER).read_text())
    path = root / pointer["path"]
    if sha256_file(path) != pointer["sha256"]:
        raise ValueError("surface admissibility hash mismatch")
    if geometry_sha256 and pointer["geometry_sha256"] != geometry_sha256:
        raise ValueError("surface admissibility geometry mismatch")
    with np.load(path, allow_pickle=False) as arrays:
        mask = arrays["eligible_vertex_mask"].astype(bool)
    provenance = {"surface_admissibility_path": pointer["path"],
        "surface_admissibility_sha256": pointer["sha256"],
        "surface_admissibility_version": pointer["schema_version"]}
    return mask, provenance


def restrict_rois(masks, centers, eligible):
    restricted = np.asarray(masks, bool) & np.asarray(eligible, bool)[:, None]
    filtered = {name: np.asarray(ids, int)[eligible[np.asarray(ids, int)]] for name, ids in centers.items()}
    return restricted, filtered


def fibonacci_directions(count):
    i = np.arange(count)
    z = 1 - 2 * (i + .5) / count
    theta = i * np.pi * (3 - np.sqrt(5))
    return np.column_stack((np.sqrt(1-z*z)*np.cos(theta), np.sqrt(1-z*z)*np.sin(theta), z))


def exposure_counts(vertices_m, triangles, directions, progress=None):
    """Two-sided CGAL segment occlusion, 20 um self-intersection exclusion.

    Requires the bundled native SimNIBS runtime only when generating the mask.
    Every test starts along the ray itself; no radial or normal-facing shortcut.
    """
    from simnibs.mesh_tools.cgal import pyAABBTree
    vertices = np.asarray(vertices_m, float)
    tree = pyAABBTree()
    tree.set_data(vertices, np.asarray(triangles, int))
    counts = np.zeros(len(vertices), dtype=np.uint16)
    for index, direction in enumerate(directions):
        pairs, _ = tree.intersection(vertices + 2e-5 * direction, vertices + direction)
        exposed = np.ones(len(vertices), bool)
        if len(pairs):
            exposed[pairs[:, 0]] = False
        counts += exposed
        if progress and (index + 1) % 32 == 0:
            progress(index + 1, len(directions))
    return counts
