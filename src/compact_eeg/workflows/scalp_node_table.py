"""Precomputed scalp-node FEM superposition table for new surface coordinates.

A point electrode on an exterior triangle injects its unit current through the
triangle's three volume nodes with barycentric weights
(``cortical_fem.balanced_sampling_rhs``), against one fixed gauge node. The FEM
system is linear, so the electrode's normal leadfield row equals the same
weighted sum of the rows obtained for unit loads at those three nodes against
the same gauge. The builder solves every node of ``VERTEX_RULE`` once with the
qualified native MUMPS path; evaluation then reads three verified rows per
electrode. This is superposition of solutions of one unchanged operator, not
montage, nearest-neighbour or spatial interpolation of leadfields.

Integrity: the pointer fixes the manifest bytes, the manifest fixes the index
bytes, the full row-file SHA256 and one SHA256 per row. Evaluation checks the
digest of every row it reads; ``verify_rows`` rehashes the complete file.

A named conductivity scenario (``configs/conductivity_scenarios.json``) has its
own table, pointer and directory under ``SCENARIO_RELATIVE_ROOT/<name>``; its
identity adds the scenario's conductivities. Scenario tables are the
data-generating head for model-mismatch evaluation only.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

import numpy as np

from compact_eeg.artifacts import sha256_file
from compact_eeg.forward_pilot import deterministic_npz_bytes

SCHEMA = "scalp-node-superposition/1"
POINTER_RELATIVE = Path("results/v2/current_scalp_node_table.json")
TABLE_RELATIVE_ROOT = Path("results/v2/scalp_node_table")
SCENARIO_RELATIVE_ROOT = Path("results/v2/scalp_node_table_scenarios")
ROWS_NAME, INDEX_NAME, MANIFEST_NAME = "rows.npy", "index.npz", "manifest.json"
SOURCE_COUNT = 4352
GAUGE_NODE_ONE_BASED = 122743
CURRENT_AMPERES = 1.0
NEAREST_VERTEX_COUNT = 20
QA_ARRAYS = ("relative_full_system_residual", "relative_free_dof_residual",
             "net_assembled_current_A", "reaction_current_relative_error")
VERTEX_RULE = ("every vertex of an exterior triangle whose three vertices pass the current "
               "surface admissibility mask; the same rule admits new electrode projections; "
               "plus every bank candidate vertex that passes the mask")


class TableIntegrityError(ValueError):
    """Table bytes, digests or layout differ from the published manifest."""


class TableIdentityError(ValueError):
    """The table was built for a different bank, head, source set or admission mask."""


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _json_sha(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise TableIntegrityError("Scalp-node table path leaves the repository")
    return path


def frozen_identity(root):
    """Declared identities the table must match; files are byte-checked by their own loaders."""
    root = Path(root).resolve()
    pointer = json.loads(_inside(root, "results/v2/current_multiregion_bank.json").read_text())
    report = json.loads(_inside(root, pointer["report"]).read_text())
    manifest = json.loads((_inside(root, pointer["path"]).parents[2] / "run_manifest.json").read_text())
    admission = json.loads(_inside(root, "results/v2/current_surface_admissibility.json").read_text())
    if manifest["identity"]["source_input_sha256"] != report.get("source_input_sha256"):
        raise TableIdentityError("Bank manifest and report disagree on the source inputs")
    return {"bank_sha256": pointer["sha256"], "candidate_geometry_sha256": report["candidate_sha256"],
            "source_inputs_sha256": report["source_input_sha256"],
            "head_hashes": manifest["identity"]["head_hashes"],
            "surface_admissibility_sha256": admission["sha256"],
            "surface_admissibility_version": admission.get("schema_version"),
            "source_count": SOURCE_COUNT}


def table_identity(frozen, scenario=None):
    """``scenario`` is ``head_model.conductivity_scenario`` output; the nominal identity is unchanged."""
    identity = {"schema": SCHEMA, "frozen": frozen, "gauge_node_one_based": GAUGE_NODE_ONE_BASED,
                "current_amperes": CURRENT_AMPERES, "leadfield_unit": "V/(A*m)",
                "row_definition": "normal leadfield for +1 A at the vertex's volume node and -1 A at the gauge node",
                "vertex_rule": VERTEX_RULE}
    return identity if scenario is None else {**identity, "conductivity_scenario": scenario}


def scenario_identity(root, scenario):
    if scenario is None:
        return None
    from .head_model import conductivity_scenario
    return conductivity_scenario(root, scenario)


def table_root(scenario=None, head=None):
    if head is not None:
        from .head_package import package_dir
        return package_dir(head) / "table"
    return TABLE_RELATIVE_ROOT if scenario is None else SCENARIO_RELATIVE_ROOT / scenario


def pointer_relative(scenario=None, head=None):
    if head is not None:
        from .head_package import package_dir
        return package_dir(head) / "table.json"
    return POINTER_RELATIVE if scenario is None else SCENARIO_RELATIVE_ROOT / scenario / "current.json"


def expected_identity(root, scenario=None, head=None, frozen=None):
    """Manifest identity for the Ernie (scenario) table or a head package's table."""
    if head is not None:
        if scenario is not None:
            raise ValueError("conductivity scenarios are defined for Ernie only")
        from . import head_package
        return head_package.table_identity(head_package.load(root, head))
    return table_identity(frozen_identity(root) if frozen is None else frozen, scenario_identity(root, scenario))


def admissible_vertices(eligible_mask, faces):
    """Sorted surface-vertex indices that any admissible projection can touch."""
    faces = np.asarray(faces, dtype=np.int64)
    mask = np.asarray(eligible_mask, dtype=bool)
    if faces.ndim != 2 or faces.shape[1] != 3 or faces.min() < 0 or faces.max() >= len(mask):
        raise ValueError("Invalid surface triangles for the admissibility mask")
    return np.unique(faces[np.all(mask[faces], axis=1)])


def table_vertices(eligible_mask, faces, bank_vertex_indices, allowed_bank):
    """VERTEX_RULE: admissible-triangle vertices plus every admitted bank candidate vertex.

    An admitted candidate can sit on a vertex whose incident triangles all touch
    a screened vertex; its zero-weight corners are redirected to that vertex.
    """
    bank = np.asarray(bank_vertex_indices, dtype=np.int64)[np.asarray(allowed_bank, dtype=bool)]
    return np.union1d(admissible_vertices(eligible_mask, faces), bank)


def project(vertices_mm, faces, points_mm, nearest_vertex_count=NEAREST_VERTEX_COUNT):
    """Exactly FixedMeshLeadfield.project's surface step, without the volume mesh."""
    import cortech
    vertices = np.asarray(vertices_mm, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)
    points = np.asarray(points_mm, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or not len(points) or not np.all(np.isfinite(points)):
        raise ValueError("electrode points must have nonempty finite shape (K,3)")
    triangles, weights, projected, _ = cortech.Surface(vertices, faces).project_points(points, pttris=nearest_vertex_count)
    triangles = np.asarray(triangles, dtype=np.int64)
    weights = np.asarray(weights, dtype=np.float64)
    projected = np.asarray(projected, dtype=np.float64)
    if triangles.shape != (len(points),) or weights.shape != (len(points), 3):
        raise ValueError("surface projection returned invalid triangles or weights")
    if np.any(weights < -1e-10) or np.any(weights > 1 + 1e-10) or not np.allclose(weights.sum(axis=1), 1, rtol=0, atol=1e-10):
        raise ValueError("point barycentric weights must lie within their triangle and sum to one")
    vertex_rows = faces[triangles]
    if not np.allclose(np.einsum("kj,kjc->kc", weights, vertices[vertex_rows]), projected, atol=1e-7, rtol=0):
        raise ValueError("surface weights do not reproduce projected coordinates")
    return {"triangle_ids": triangles, "barycentric_weights": weights, "vertex_rows": vertex_rows,
            "projected_mm": projected, "distances_mm": np.linalg.norm(points - projected, axis=1)}


def node_load_rhs(node_count, volume_nodes, gauge_row, current_amperes=CURRENT_AMPERES):
    """N x K unit loads at single volume nodes against the gauge (balanced_sampling_rhs rows of e_node)."""
    nodes = np.asarray(volume_nodes, dtype=np.int64)
    if nodes.ndim != 1 or not len(nodes) or nodes.min() < 0 or nodes.max() >= node_count or np.any(nodes == gauge_row):
        raise ValueError("node loads must name distinct non-gauge volume nodes")
    rhs = np.zeros((node_count, len(nodes)))
    rhs[nodes, np.arange(len(nodes))] = current_amperes
    rhs[gauge_row] -= current_amperes
    return rhs


def solve_node_rows(model, volume_nodes, *, block_size=8, current_amperes=CURRENT_AMPERES, progress=None):
    """Rows and per-node QA for unit node loads, using a prepared FixedMeshLeadfield-like model.

    ``model`` needs ``system.solve``, ``system.A``, ``source_operator``,
    ``gauge_row`` and ``mesh.nodes.nr``; tests pass a small exact system.
    The gauge node may itself be a scalp node: +1 A and -1 A at the same node
    is no load, so its row is exactly zero (with zero residuals) and is not solved.
    """
    if not isinstance(block_size, int) or not 1 <= block_size <= 16:
        raise ValueError("block_size must be an integer from 1 through 16")
    nodes = np.asarray(volume_nodes, dtype=np.int64)
    count, node_count = len(nodes), model.mesh.nodes.nr
    free = np.arange(node_count) != model.gauge_row
    rows = np.zeros((count, model.source_operator.shape[0]))
    qa = {name: np.zeros(count) for name in QA_ARRAYS}
    solved = np.flatnonzero(nodes != model.gauge_row)
    for start in range(0, len(solved), block_size):
        block = solved[start:start + block_size]
        rhs = node_load_rhs(node_count, nodes[block], model.gauge_row, current_amperes)
        potentials = model.system.solve(rhs)
        if potentials.ndim == 1:
            potentials = potentials[:, None]
        if not np.all(np.isfinite(potentials)):
            raise RuntimeError("native FEM returned non-finite potentials")
        rows[block] = (model.source_operator @ potentials).T / current_amperes
        current = model.system.A @ potentials
        residual = current - rhs
        qa["relative_full_system_residual"][block] = np.linalg.norm(residual, axis=0) / np.linalg.norm(rhs, axis=0)
        qa["relative_free_dof_residual"][block] = np.linalg.norm(residual[free], axis=0) / np.linalg.norm(rhs[free], axis=0)
        qa["net_assembled_current_A"][block] = current.sum(axis=0)
        qa["reaction_current_relative_error"][block] = np.abs(residual[model.gauge_row]) / current_amperes
        if progress:
            progress(start + len(block), len(solved))
    return rows, qa


def qa_summary(qa):
    return {"max_relative_full_system_residual": float(np.max(qa["relative_full_system_residual"])),
            "max_relative_free_dof_residual": float(np.max(qa["relative_free_dof_residual"])),
            "max_abs_net_assembled_current_A": float(np.max(np.abs(qa["net_assembled_current_A"]))),
            "max_reaction_current_relative_error": float(np.max(qa["reaction_current_relative_error"]))}


def check_node_qa(qa):
    """The thresholds design_evaluation applies to every direct electrode solve."""
    summary = qa_summary(qa)
    if any(not np.isfinite(v) or v > 1e-7 for v in summary.values()):
        raise ValueError(f"Scalp-node FEM residual/current QA failed: {summary}")
    return summary


def superpose_rows(stacked_rows, weights):
    """K x 3 x S vertex rows combined with each point's K x 3 barycentric weights."""
    return np.einsum("kj,kjs->ks", weights, stacked_rows)


def _row_digests(rows, chunk=256):
    digests = np.empty((len(rows), 32), dtype=np.uint8)
    for start in range(0, len(rows), chunk):
        block = np.ascontiguousarray(rows[start:start + chunk])
        for i, row in enumerate(block):
            digests[start + i] = np.frombuffer(hashlib.sha256(row.tobytes()).digest(), dtype=np.uint8)
    return digests


def _fsync_file(path):
    with open(path, "rb+") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_bytes(path, data):
    with open(path, "xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def create_staging(root, scenario=None, head=None):
    """New private staging directory; the caller writes rows.npy there before finalize()."""
    scenario_identity(root, scenario)
    base = Path(root).resolve() / table_root(scenario, head)
    base.mkdir(parents=True, exist_ok=True)
    staging = base / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    return staging


def finalize(root, staging, vertex_indices, qa, frozen, build, verification, scenario=None, head=None):
    """Digest, index and atomically publish a staged table, then switch the pointer."""
    root = Path(root).resolve()
    staging = Path(staging).resolve()
    if staging.parent != (root / table_root(scenario, head)).resolve() or not staging.name.startswith(".staging-"):
        raise ValueError("Staging directory must come from create_staging()")
    rows_path = staging / ROWS_NAME
    rows = np.load(rows_path, mmap_mode="r")
    vertex_indices = np.asarray(vertex_indices, dtype=np.int64)
    if rows.dtype != np.dtype("<f8") or rows.shape != (len(vertex_indices), SOURCE_COUNT) or not rows.flags.c_contiguous:
        raise TableIntegrityError("Staged rows must be C-ordered little-endian float64 (vertices x 4352)")
    if len(vertex_indices) == 0 or np.any(np.diff(vertex_indices) <= 0):
        raise ValueError("Vertex indices must be nonempty and strictly increasing")
    if set(qa) != set(QA_ARRAYS) or any(np.shape(qa[name]) != (len(vertex_indices),) for name in QA_ARRAYS):
        raise ValueError("Per-node QA arrays must cover every table row")
    if not np.all(np.isfinite(rows)):
        raise ValueError("Scalp-node table contains non-finite values")
    summary = check_node_qa(qa)
    _fsync_file(rows_path)
    index = {"vertex_indices": vertex_indices, "row_sha256": _row_digests(rows),
             **{name: np.asarray(qa[name], dtype=np.float64) for name in QA_ARRAYS}}
    index_bytes = deterministic_npz_bytes(index)
    _write_bytes(staging / INDEX_NAME, index_bytes)
    rows_sha = sha256_file(rows_path)
    identity = expected_identity(root, scenario, head, frozen)
    table_id = _json_sha({"identity": identity, "rows_sha256": rows_sha,
                          "index_sha256": hashlib.sha256(index_bytes).hexdigest()})
    final = (root / table_root(scenario, head) / table_id).resolve()
    manifest = {"schema": SCHEMA, "table_id": table_id, "identity": identity,
                "rows": {"path": str((final / ROWS_NAME).relative_to(root)), "sha256": rows_sha,
                         "shape": list(rows.shape), "dtype": "<f8"},
                "index": {"path": str((final / INDEX_NAME).relative_to(root)),
                          "sha256": hashlib.sha256(index_bytes).hexdigest()},
                "node_qa": summary, "verification": verification, "build": build}
    _write_bytes(staging / MANIFEST_NAME, _json_bytes(manifest))
    _fsync_directory(staging)
    del rows
    if final.exists():
        existing = json.loads((final / MANIFEST_NAME).read_text())
        if existing.get("table_id") != table_id or existing["rows"]["sha256"] != rows_sha:
            raise TableIntegrityError("An existing table directory has the same ID but different bytes")
        shutil.rmtree(staging)
    else:
        os.rename(staging, final)
        _fsync_directory(final.parent)
    manifest_path = final / MANIFEST_NAME
    pointer = {"schema": SCHEMA, "table_id": table_id,
               "manifest_path": str(manifest_path.relative_to(root)), "manifest_sha256": sha256_file(manifest_path)}
    pointer_path = root / pointer_relative(scenario, head)
    temporary = pointer_path.with_name(f".{pointer_path.name}.{uuid.uuid4().hex}")
    _write_bytes(temporary, _json_bytes(pointer))
    os.replace(temporary, pointer_path)
    _fsync_directory(pointer_path.parent)
    return manifest


@dataclass(frozen=True)
class ScalpNodeTable:
    root: Path
    table_id: str
    manifest: dict
    manifest_path: Path
    manifest_sha256: str
    rows: np.ndarray
    vertex_indices: np.ndarray
    row_sha256: np.ndarray

    def provenance(self):
        scenario = self.manifest["identity"].get("conductivity_scenario")
        head = self.manifest["identity"].get("head_package")
        return {"schema": SCHEMA, "table_id": self.table_id, **({"conductivity_scenario": scenario} if scenario else {}),
                **({"head_package": head} if head else {}),
                "manifest_path": str(self.manifest_path.relative_to(self.root)),
                "manifest_sha256": self.manifest_sha256, "rows_sha256": self.manifest["rows"]["sha256"],
                "vertex_count": int(len(self.vertex_indices)), "node_qa": self.manifest["node_qa"],
                "verification": self.manifest["verification"],
                "built_with": {k: self.manifest["build"].get(k) for k in ("native_runtime_sha256", "simnibs", "numpy", "python")}}

    def positions(self, vertex_rows):
        vertex_rows = np.asarray(vertex_rows, dtype=np.int64)
        positions = np.searchsorted(self.vertex_indices, vertex_rows)
        if np.any(positions >= len(self.vertex_indices)) or np.any(self.vertex_indices[np.minimum(positions, len(self.vertex_indices) - 1)] != vertex_rows):
            raise TableIdentityError("投影面片的顶点不在预计算头皮节点表中；表面筛选或表格版本不一致。")
        return positions

    def superpose(self, vertex_rows, weights):
        """Leadfield rows for projected points; every row read is digest-checked first."""
        positions = self.positions(vertex_rows)
        unique, inverse = np.unique(positions, return_inverse=True)
        gathered = np.ascontiguousarray(self.rows[unique])
        for row, position in zip(gathered, unique):
            if hashlib.sha256(row.tobytes()).digest() != self.row_sha256[position].tobytes():
                raise TableIntegrityError("预计算头皮节点表的数据行校验失败")
        stacked = gathered[inverse.reshape(-1)].reshape(*positions.shape, SOURCE_COUNT)
        return superpose_rows(stacked, np.asarray(weights, dtype=np.float64))

    def verify_rows(self):
        """Full-file rehash, for installation and deployment checks."""
        rows_path = _inside(self.root, self.manifest["rows"]["path"])
        if sha256_file(rows_path) != self.manifest["rows"]["sha256"]:
            raise TableIntegrityError("Scalp-node row file SHA256 differs from its manifest")
        return True


def available(root, scenario=None, head=None):
    scenario_identity(root, scenario)
    return (Path(root).resolve() / pointer_relative(scenario, head)).is_file()


def load(root, scenario=None, head=None):
    """Open the current (scenario or head) table read-only; raises unless it matches its current inputs."""
    root = Path(root).resolve()
    expected = expected_identity(root, scenario, head)
    pointer = json.loads(_inside(root, pointer_relative(scenario, head)).read_text())
    if pointer.get("schema") != SCHEMA:
        raise TableIntegrityError("Unsupported scalp-node table pointer schema")
    manifest_path = _inside(root, pointer["manifest_path"])
    directory = (root / table_root(scenario, head) / pointer["table_id"]).resolve()
    if manifest_path != directory / MANIFEST_NAME:
        raise TableIntegrityError("Scalp-node manifest path differs from its table ID")
    manifest_sha = sha256_file(manifest_path)
    if manifest_sha != pointer["manifest_sha256"]:
        raise TableIntegrityError("Scalp-node manifest SHA256 differs from the pointer")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != SCHEMA or manifest.get("table_id") != pointer["table_id"]:
        raise TableIntegrityError("Scalp-node manifest schema or ID mismatch")
    if manifest["identity"] != expected:
        raise TableIdentityError("预计算头皮节点表与当前前向库、头模、源或表面筛选不一致，需要重新预计算。")
    index_path = _inside(root, manifest["index"]["path"])
    rows_path = _inside(root, manifest["rows"]["path"])
    if index_path.parent != directory or rows_path.parent != directory:
        raise TableIntegrityError("Scalp-node table files must stay in their table directory")
    if sha256_file(index_path) != manifest["index"]["sha256"]:
        raise TableIntegrityError("Scalp-node index SHA256 differs from its manifest")
    with np.load(index_path, allow_pickle=False) as index:
        vertex_indices = np.asarray(index["vertex_indices"])
        row_sha256 = np.asarray(index["row_sha256"])
    rows = np.load(rows_path, mmap_mode="r")
    if (vertex_indices.dtype != np.int64 or vertex_indices.ndim != 1 or np.any(np.diff(vertex_indices) <= 0)
            or row_sha256.dtype != np.uint8 or row_sha256.shape != (len(vertex_indices), 32)
            or rows.dtype != np.dtype("<f8") or rows.shape != (len(vertex_indices), SOURCE_COUNT)
            or list(rows.shape) != manifest["rows"]["shape"] or not rows.flags.c_contiguous):
        raise TableIntegrityError("Scalp-node table layout differs from its manifest")
    return ScalpNodeTable(root, pointer["table_id"], manifest, manifest_path, manifest_sha,
                          rows, vertex_indices, row_sha256)


__all__ = ["SCHEMA", "POINTER_RELATIVE", "TABLE_RELATIVE_ROOT", "SCENARIO_RELATIVE_ROOT", "ScalpNodeTable", "TableIdentityError",
           "TableIntegrityError", "admissible_vertices", "available", "check_node_qa", "create_staging",
           "expected_identity", "finalize", "frozen_identity", "load", "node_load_rhs", "pointer_relative", "project", "scenario_identity",
           "solve_node_rows", "table_identity", "table_root", "table_vertices"]
