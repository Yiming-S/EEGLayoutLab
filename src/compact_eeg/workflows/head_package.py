"""Additional head models for cross-head evaluation. Ernie production paths are unchanged.

A head package holds everything evaluation needs for one subject, built by
``scripts/build_head_package.py`` with one protocol for every head:

* exterior scalp: the largest connected tag-1005 triangle component of the
  SimNIBS mesh, vertices in ascending volume-node order (reproduces Ernie's
  frozen surface exactly);
* admissibility: the external line-of-sight screen with Ernie's three direction
  sets and acceptance rule (reproduces Ernie's frozen mask exactly);
* sources: 4096 dictionary and 256 off-dictionary generation sources on the
  charm central cortical surface, by deterministic farthest-point sampling,
  with vertex normals and nearest-source cortical-area weights;
* gauge: the white-matter node nearest the white-matter node centroid;
* layout mapping: every Ernie scalp vertex mapped Ernie -> MNI -> head with the
  SimNIBS nonlinear transforms. Layouts and the standard64 reference use the
  same barycentric interpolation of these mapped vertices, then projection.
  A package is published only when the mapped reference passes the same
  screen as layouts (``layout_screen``), since it normalizes every score on
  that head.

Integrity: ``package.json`` records the SHA256 of every package file and of
its inputs; ``load`` verifies all of them. A package's scalp-node table lives
in ``<package>/table`` with its own pointer, and its identity names the package.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

import numpy as np
from scipy.spatial import cKDTree

from compact_eeg.artifacts import sha256_file

SCHEMA = "eeglayoutlab-head-package/1"
HEADS_RELATIVE_ROOT = Path("results/v2/heads")
HEAD_ID = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")
DICTIONARY_COUNT, GENERATION_COUNT = 4096, 256
ADMISSION_DIRECTION_COUNTS = (128, 256, 128)
ADMISSION_ROTATION_RAD = (0.31, -0.47, 0.19)  # third set, as in the frozen Ernie screen
SKIN_TAG, WHITE_MATTER_TAG = 1005, 1
FILES = ("scalp.npz", "admissibility.npz", "sources.npz", "mapping.npz")
SOURCE_PROTOCOL = ("farthest-point sampling on lh+rh charm central surfaces, restricted to vertices with a DK40 "
                   "cortical label (medial wall excluded; label = nearest fsaverage vertex on sphere.reg), from the "
                   "cortical vertex nearest the area-weighted centroid; first 4096 points form the dictionary, the "
                   "next 256 the off-dictionary generation set; area weight = cortical area of the labelled vertices "
                   "nearest each source")
MEDIAL_WALL_NAMES = ("unknown", "corpuscallosum")
MAPPING_QA = ("method", "same_subject_as_ernie", "reference_triangles_screened", "reference_projection_mm",
              "reference_minimum_spacing_mm")
# Screen of a layout mapped onto another head (layout_screen); both limits are tolerance conventions.
# Measured 2026-11-20 on the 356 library layouts that pass the Ernie screen, mapped onto ixi002, ixi012 and
# ixi013: nearest-neighbour distances keep 0.75-0.83 of their Ernie value at the 1st percentile, and 99% of
# electrodes project less than 6 mm, the rest up to 43 mm. Projection distances are continuous around 10 mm;
# beyond it lie the outer ear, the face and, on ixi012, the lowest occipital row of candidates (10.3-11.8 mm).
LAYOUT_PROJECTION_LIMIT_MM = 10.0  # mapping error tolerated between a mapped point and the head's scalp
LAYOUT_MINIMUM_SPACING_MM = 3.0  # absolute floor: the 4 mm minimum design spacing less 25%


class HeadPackageError(ValueError):
    """Package bytes, identity or protocol differ from its manifest."""


def check_head_id(head_id):
    if not isinstance(head_id, str) or len(head_id) > 40 or not HEAD_ID.fullmatch(head_id):
        raise HeadPackageError("head_id must be a short lowercase identifier")
    return head_id


def package_dir(head_id):
    return HEADS_RELATIVE_ROOT / check_head_id(head_id)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


# ---------------------------------------------------------------- geometry

def exterior_scalp(node_numbers, node_coord_mm, elm_type, tag1, node_number_list):
    """Largest connected skin-triangle component; returns (vertices_mm, triangles, node_rows)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    if not np.array_equal(node_numbers, np.arange(1, len(node_coord_mm) + 1)):
        raise HeadPackageError("requires consecutive SimNIBS node numbering")
    nodes = np.asarray(node_number_list)[(np.asarray(elm_type) == 2) & (np.asarray(tag1) == SKIN_TAG)][:, :3] - 1
    if not len(nodes):
        raise HeadPackageError("mesh has no skin triangles")
    used = np.unique(nodes)
    local = np.searchsorted(used, nodes)
    edges = np.vstack([local[:, [0, 1]], local[:, [1, 2]], local[:, [2, 0]]])
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(len(used), len(used)))
    _count, labels = connected_components(graph, directed=False)
    largest = np.bincount(labels).argmax()
    node_rows = used[labels == largest]
    remap = np.full(len(node_coord_mm), -1, dtype=np.int64)
    remap[node_rows] = np.arange(len(node_rows))
    triangles = remap[nodes[labels[local[:, 0]] == largest]]
    return np.asarray(node_coord_mm, float)[node_rows], triangles, node_rows


def admission_directions():
    from scipy.spatial.transform import Rotation
    from compact_eeg.surface_admissibility import fibonacci_directions
    first, second, third = (fibonacci_directions(count) for count in ADMISSION_DIRECTION_COUNTS)
    return [first, second, Rotation.from_rotvec(ADMISSION_ROTATION_RAD).apply(third)]


def admissibility(vertices_mm, triangles, progress=None):
    """Ernie's external exposure screen: eligible when every direction set has an open ray."""
    from compact_eeg.surface_admissibility import exposure_counts
    counts = np.stack([exposure_counts(np.asarray(vertices_mm) / 1000, triangles, directions, progress)
                       for directions in admission_directions()])
    eligible = np.all(counts > 0, axis=0)
    return {"exposure_counts": counts, "eligible_vertex_mask": eligible,
            "unstable_vertex_mask": np.any(counts > 0, axis=0) & ~eligible}


def vertex_normals_and_areas(vertices, faces):
    vertices, faces = np.asarray(vertices, float), np.asarray(faces, np.int64)
    cross = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 2]] - vertices[faces[:, 0]])
    normals = np.zeros_like(vertices)
    areas = np.zeros(len(vertices))
    for corner in range(3):
        np.add.at(normals, faces[:, corner], cross)  # area-weighted face normals
        np.add.at(areas, faces[:, corner], np.linalg.norm(cross, axis=1) / 6)
    length = np.linalg.norm(normals, axis=1)
    if np.any(length <= 0):
        raise HeadPackageError("cortical surface has vertices without adjacent area")
    return normals / length[:, None], areas


def farthest_points(xyz, count, start, chosen=()):
    """Deterministic greedy farthest-point order continuing from ``chosen``."""
    xyz = np.asarray(xyz, float)
    order = list(chosen)
    distance = np.full(len(xyz), np.inf)
    for index in (order or [start]):
        distance = np.minimum(distance, np.sum((xyz - xyz[index]) ** 2, axis=1))
    if not order:
        order.append(int(start))
    while len(order) < len(chosen) + count:
        index = int(np.argmax(distance))
        order.append(index)
        distance = np.minimum(distance, np.sum((xyz - xyz[index]) ** 2, axis=1))
    return np.asarray(order[len(chosen):] if chosen else order, dtype=np.int64)


def cortex_mask(sphere_reg, template_sphere, template_labels, names):
    """True where a native vertex carries a DK40 cortical label (nearest fsaverage vertex on the registered sphere).

    The medial wall (label -1, 'unknown', 'corpuscallosum') runs through white matter and
    ventricles, so its vertices are not cortical sources.
    """
    unit = lambda p: np.asarray(p, float) / np.linalg.norm(p, axis=1)[:, None]
    _distance, nearest = cKDTree(unit(template_sphere)).query(unit(sphere_reg))
    labels = np.asarray(template_labels)[nearest]
    excluded = [index for index, name in enumerate(names) if name in MEDIAL_WALL_NAMES]
    return (labels >= 0) & ~np.isin(labels, excluded)


def sample_sources(vertices, faces, cortex=None):
    """Dictionary and generation sources from one cortical surface (both hemispheres).

    ``cortex`` restricts sampling and area weights to labelled cortical vertices.
    """
    vertices = np.asarray(vertices, float)
    normals, areas = vertex_normals_and_areas(vertices, faces)
    candidates = np.arange(len(vertices)) if cortex is None else np.flatnonzero(np.asarray(cortex, bool))
    points, area = vertices[candidates], areas[candidates]
    start = int(np.argmin(np.sum((points - np.average(points, axis=0, weights=area)) ** 2, axis=1)))
    local = farthest_points(points, DICTIONARY_COUNT, start)
    dictionary = candidates[local]
    generation = candidates[farthest_points(points, GENERATION_COUNT, start, chosen=tuple(local))]
    def weights(indices):
        _distance, nearest = cKDTree(vertices[indices]).query(points)
        return np.bincount(nearest, weights=area, minlength=len(indices))
    return {"source_xyz_mm": vertices[dictionary], "source_normals": normals[dictionary],
            "source_area_weights": weights(dictionary), "source_vertex_indices": dictionary,
            "generation_xyz_mm": vertices[generation], "generation_normals": normals[generation],
            "generation_area_weights": weights(generation), "generation_vertex_indices": generation}


def deep_gauge(node_coord_mm, elm_type, tag1, node_number_list):
    """One-based node of the white matter nearest the white-matter node centroid."""
    tetra = np.asarray(node_number_list)[(np.asarray(elm_type) == 4) & (np.asarray(tag1) == WHITE_MATTER_TAG)]
    nodes = np.unique(tetra) - 1
    if not len(nodes):
        raise HeadPackageError("mesh has no white-matter tetrahedra")
    xyz = np.asarray(node_coord_mm, float)[nodes]
    return int(nodes[np.argmin(np.sum((xyz - xyz.mean(axis=0)) ** 2, axis=1))] + 1)


def map_points(points_mm, ernie_vertices_mm, ernie_faces, mapped_vertices_mm, head_vertices_mm, head_faces):
    """Ernie surface points -> head surface, by barycentric interpolation of mapped vertices, then projection."""
    from .scalp_node_table import project
    on_ernie = project(ernie_vertices_mm, ernie_faces, points_mm)
    if on_ernie["distances_mm"].max() > 1e-5:
        raise HeadPackageError("layout points must already lie on the Ernie scalp surface")
    mapped = np.einsum("kj,kjc->kc", on_ernie["barycentric_weights"], np.asarray(mapped_vertices_mm)[on_ernie["vertex_rows"]])
    on_head = project(head_vertices_mm, head_faces, mapped)
    return {**on_head, "mapped_mm": mapped, "mapping_projection_mm": on_head["distances_mm"]}


def supporting_rows(vertex_rows, weights, negligible=1e-12):
    """Triangle vertex rows with zero-weight corners pointed at the point's main vertex.

    A point on a vertex or an edge is carried by the vertices with weight; the third corner of the
    triangle that projection happened to pick neither screens nor contributes to the field.
    """
    rows = np.array(vertex_rows, dtype=np.int64, copy=True)
    weights = np.asarray(weights, float)
    main = rows[np.arange(len(rows)), weights.argmax(axis=1)]
    zero = weights < negligible
    rows[zero] = np.broadcast_to(main[:, None], rows.shape)[zero]
    return rows


def layout_screen(eligible_vertex_mask, vertex_rows, xyz_mm, projection_mm):
    """(triangles admissible, minimum spacing mm, maximum projection mm, passes) for electrodes mapped onto a head.

    One rule for layouts and for the mapped standard64 reference. Layouts keep at least 4 mm on Ernie; the
    mapped layout is the anatomically corresponding one, so its spacing follows the local head size. Mapped
    electrodes closer than 3 mm, or a mapped point more than 10 mm from the scalp, are refused. The spacing
    test is an absolute floor: it does not bound the relative loss, so a layout designed wider than 4 mm can
    lose more than 25% locally and still pass.
    """
    from scipy.spatial.distance import pdist
    screened = bool(np.all(np.asarray(eligible_vertex_mask, bool)[np.asarray(vertex_rows)]))
    spacing = float(pdist(np.asarray(xyz_mm, float)).min())
    projection = float(np.max(projection_mm))
    passes = screened and spacing >= LAYOUT_MINIMUM_SPACING_MM - 1e-7 and projection <= LAYOUT_PROJECTION_LIMIT_MM
    return screened, spacing, projection, passes


# ---------------------------------------------------------------- package

@dataclass(frozen=True)
class HeadPackage:
    head_id: str
    manifest: dict
    manifest_sha256: str
    scalp: dict
    admission: dict
    sources: dict
    mapping: dict

    @property
    def gauge_node(self):
        return self.manifest["gauge_node_one_based"]

    def provenance(self):
        m = self.manifest
        mapping = m.get("mapping", {})
        return {"head_id": self.head_id, "package_sha256": self.manifest_sha256, "dataset": m["dataset"],
                "source_protocol": m["source_protocol"], "gauge_node_one_based": m["gauge_node_one_based"],
                "source_qa": m["source_qa"], "admission": m["admission"],
                "mapping": {key: mapping.get(key) for key in MAPPING_QA}}


def table_identity(package):
    """Scalp-node table identity for a head package (generation from that package only)."""
    return {"schema": "scalp-node-superposition/1", "head_package": {"head_id": package.head_id, "sha256": package.manifest_sha256},
            "gauge_node_one_based": package.gauge_node, "source_count": DICTIONARY_COUNT + GENERATION_COUNT,
            "current_amperes": 1.0, "leadfield_unit": "V/(A*m)",
            "row_definition": "normal leadfield for +1 A at the vertex's volume node and -1 A at the gauge node",
            "vertex_rule": "every vertex of an admissible exterior triangle, plus the mapped standard64 reference triangles"}


def table_vertices(package):
    from .scalp_node_table import admissible_vertices
    return np.union1d(admissible_vertices(package.admission["eligible_vertex_mask"], package.scalp["triangles"]),
                      np.unique(package.mapping["reference_vertex_rows"]))


def available(root, head_id):
    return (Path(root).resolve() / package_dir(head_id) / "package.json").is_file()


def list_heads(root):
    base = Path(root).resolve() / HEADS_RELATIVE_ROOT
    return sorted(path.parent.name for path in base.glob("*/package.json") if HEAD_ID.fullmatch(path.parent.name))


def load(root, head_id):
    root = Path(root).resolve()
    directory = (root / package_dir(head_id)).resolve()
    if not directory.is_relative_to(root):
        raise HeadPackageError("head package path leaves the repository")
    manifest_path = directory / "package.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != SCHEMA or manifest.get("head_id") != head_id or set(manifest.get("files", {})) != set(FILES):
        raise HeadPackageError("head package manifest schema, ID or file list mismatch")
    arrays = {}
    for name in FILES:
        path = directory / name
        if sha256_file(path) != manifest["files"][name]:
            raise HeadPackageError(f"head package file {name} differs from its manifest")
        with np.load(path, allow_pickle=False) as archive:
            arrays[name] = {key: archive[key] for key in archive.files}
    scalp, sources = arrays["scalp.npz"], arrays["sources.npz"]
    if (len(sources["source_xyz_mm"]) != DICTIONARY_COUNT or len(sources["generation_xyz_mm"]) != GENERATION_COUNT
            or len(arrays["admissibility.npz"]["eligible_vertex_mask"]) != len(scalp["vertices_mm"])
            or len(arrays["mapping.npz"]["ernie_scalp_to_head_mm"]) == 0):
        raise HeadPackageError("head package array shapes differ from the protocol")
    return HeadPackage(head_id, manifest, hashlib.sha256(manifest_bytes).hexdigest(), scalp,
                       {k: v.astype(bool) if k.endswith("mask") else v for k, v in arrays["admissibility.npz"].items()},
                       sources, arrays["mapping.npz"])


__all__ = ["SCHEMA", "HEADS_RELATIVE_ROOT", "FILES", "HeadPackage", "HeadPackageError", "admissibility",
           "admission_directions", "available", "check_head_id", "deep_gauge", "exterior_scalp", "farthest_points",
           "LAYOUT_MINIMUM_SPACING_MM", "LAYOUT_PROJECTION_LIMIT_MM", "layout_screen", "list_heads", "load", "map_points",
           "package_dir", "sample_sources", "supporting_rows", "table_identity", "table_vertices",
           "vertex_normals_and_areas"]
