"""Scalp-node superposition table: exactness on a small FEM-like system and integrity (no native runtime)."""
from __future__ import annotations
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compact_eeg.cortical_fem import balanced_sampling_rhs, point_sampling_matrix
from compact_eeg.workflows import scalp_node_table as table

FROZEN = {"bank_sha256": "b" * 64, "candidate_geometry_sha256": "c" * 64, "source_inputs_sha256": "s" * 64,
          "head_hashes": {"mesh": "m" * 64}, "surface_admissibility_sha256": "a" * 64,
          "surface_admissibility_version": "native-external-exposure/1", "source_count": table.SOURCE_COUNT}
VERTICES = np.array([1, 4, 7, 9, 12])


class GaugedLaplacian:
    """Weighted graph Laplacian (columns sum to zero) solved with one Dirichlet gauge node."""

    def __init__(self, node_count, gauge_row, rng):
        weights = np.triu(rng.uniform(.5, 2., size=(node_count, node_count)), 1)
        weights += weights.T
        self.A = np.diag(weights.sum(axis=1)) - weights
        self.free = np.arange(node_count) != gauge_row

    def solve(self, rhs):
        potentials = np.zeros_like(rhs, dtype=np.float64)
        potentials[self.free] = np.linalg.solve(self.A[np.ix_(self.free, self.free)], rhs[self.free])
        return potentials


def small_model(rng, node_count=12, gauge_row=5, sources=7):
    return SimpleNamespace(system=GaugedLaplacian(node_count, gauge_row, rng), gauge_row=gauge_row,
                           source_operator=rng.normal(size=(sources, node_count)),
                           mesh=SimpleNamespace(nodes=SimpleNamespace(nr=node_count)))


def test_superposed_node_rows_equal_direct_point_electrode_solve():
    rng = np.random.default_rng(7)
    model = small_model(rng)
    nodes = np.arange(12)  # includes the gauge node, as on the real scalp
    rows, qa = table.solve_node_rows(model, nodes, block_size=4)
    table.check_node_qa(qa)
    np.testing.assert_array_equal(rows[model.gauge_row], 0.)
    triangles = np.array([rng.choice(nodes, 3, replace=False) for _ in range(6)])
    triangles[0] = [model.gauge_row, 0, 1]
    weights = rng.dirichlet(np.ones(3), size=6)
    rhs = balanced_sampling_rhs(point_sampling_matrix(12, triangles, weights), model.gauge_row)
    direct = (model.source_operator @ model.system.solve(rhs)).T
    stacked = rows[np.searchsorted(nodes, triangles)]
    superposed = table.superpose_rows(stacked, weights)
    np.testing.assert_allclose(superposed, direct, rtol=0, atol=1e-12 * np.abs(direct).max())


def test_node_loads_reject_gauge_and_outside_nodes():
    with pytest.raises(ValueError):
        table.node_load_rhs(10, [1, 5], gauge_row=5)
    with pytest.raises(ValueError):
        table.node_load_rhs(10, [10], gauge_row=5)
    rhs = table.node_load_rhs(10, [1, 2], gauge_row=5)
    np.testing.assert_array_equal(rhs.sum(axis=0), [0., 0.])


def test_admissible_vertices_follow_whole_triangle_rule():
    faces = np.array([[0, 1, 2], [2, 3, 4], [4, 5, 6]])
    mask = np.array([1, 1, 1, 1, 0, 1, 1], dtype=bool)
    np.testing.assert_array_equal(table.admissible_vertices(mask, faces), [0, 1, 2])


def test_table_vertices_add_admitted_bank_vertices_on_partly_screened_triangles():
    faces = np.array([[0, 1, 2], [2, 3, 4], [4, 5, 6]])
    mask = np.array([1, 1, 1, 1, 0, 1, 1], dtype=bool)
    # Vertex 3 passes the mask but every triangle through it touches screened vertex 4.
    bank, allowed = np.array([3, 1, 4]), mask[[3, 1, 4]]
    np.testing.assert_array_equal(table.table_vertices(mask, faces, bank, allowed), [0, 1, 2, 3])
    assert "bank candidate" in table.table_identity(FROZEN)["vertex_rule"]


def test_real_bank_candidates_and_reference_stay_inside_the_table_vertices():
    """Every corner an admitted bank point or the standard64 reference can read, after the zero-weight redirect."""
    if not (ROOT / "results/v2/current_multiregion_bank.json").is_file():
        pytest.skip("real bank not restored; tests/test_conductivity_scenarios.py covers the rule synthetically")
    pytest.importorskip("cortech")
    from compact_eeg.workflows import design_evaluation as de
    data, _pointer, _report = de.load_bank(ROOT)
    vertices, faces = data["_surface_vertices_mm"], data["_surface_faces"]
    covered = table.table_vertices(data["_eligible_surface"], faces, data["_candidate_vertex_indices"], data["_allowed_bank"])
    allowed = np.flatnonzero(data["_allowed_bank"])
    projection = table.project(vertices, faces, data["candidate_xyz_mm"][allowed])
    rows, weights = projection["vertex_rows"], projection["barycentric_weights"]
    dominant = rows[np.arange(len(rows)), weights.argmax(axis=1)]
    np.testing.assert_array_equal(dominant, data["_candidate_vertex_indices"][allowed])
    assert not np.setdiff1d(np.r_[rows[weights >= 1e-12], dominant], covered).size
    reference = table.project(vertices, faces, data["reference_xyz_mm"])["vertex_rows"]
    assert not np.setdiff1d(reference, covered).size


@pytest.fixture
def published(tmp_path, monkeypatch):
    monkeypatch.setattr(table, "frozen_identity", lambda root: FROZEN)
    rows = np.random.default_rng(3).normal(size=(len(VERTICES), table.SOURCE_COUNT))
    staging = table.create_staging(tmp_path)
    np.save(staging / table.ROWS_NAME, rows)
    qa = {name: np.full(len(VERTICES), 1e-13) for name in table.QA_ARRAYS}
    manifest = table.finalize(tmp_path, staging, VERTICES, qa, FROZEN,
                              build={"native_runtime_sha256": "r" * 64}, verification={"fixture": True})
    return {"root": tmp_path, "rows": rows, "manifest": manifest, "staging": staging}


def test_published_table_round_trips_and_superposes(published):
    root = published["root"]
    assert table.available(root) and not published["staging"].exists()
    loaded = table.load(root)
    assert loaded.table_id == published["manifest"]["table_id"] and loaded.verify_rows()
    weights = np.array([[.2, .3, .5], [1., 0., 0.]])
    vertex_rows = np.array([[1, 4, 12], [9, 7, 1]])
    expected = np.einsum("kj,kjs->ks", weights, published["rows"][np.searchsorted(VERTICES, vertex_rows)])
    np.testing.assert_array_equal(loaded.superpose(vertex_rows, weights), expected)
    assert loaded.provenance()["vertex_count"] == len(VERTICES)


def test_republishing_identical_bytes_keeps_the_same_table(published):
    root = published["root"]
    staging = table.create_staging(root)
    np.save(staging / table.ROWS_NAME, published["rows"])
    qa = {name: np.full(len(VERTICES), 1e-13) for name in table.QA_ARRAYS}
    again = table.finalize(root, staging, VERTICES, qa, FROZEN, build={"native_runtime_sha256": "r" * 64},
                           verification={"fixture": True})
    assert again["table_id"] == published["manifest"]["table_id"] and not staging.exists()


def test_tampered_row_is_rejected_when_read(published):
    root = published["root"]
    rows = np.load(root / published["manifest"]["rows"]["path"], mmap_mode="r+")
    rows[2, 100] += 1e-9
    rows.flush()
    del rows
    loaded = table.load(root)
    loaded.superpose([[1, 4, 9]], [[.2, .3, .5]])  # untouched rows still verify
    with pytest.raises(table.TableIntegrityError):
        loaded.superpose([[1, 7, 9]], [[.2, .3, .5]])
    with pytest.raises(table.TableIntegrityError):
        loaded.verify_rows()


def test_changed_frozen_inputs_require_a_rebuilt_table(published, monkeypatch):
    monkeypatch.setattr(table, "frozen_identity", lambda root: {**FROZEN, "bank_sha256": "d" * 64})
    with pytest.raises(table.TableIdentityError):
        table.load(published["root"])


def test_manifest_bytes_are_fixed_by_the_pointer(published):
    path = published["root"] / json.loads((published["root"] / table.POINTER_RELATIVE).read_text())["manifest_path"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(table.TableIntegrityError, match="manifest SHA256"):
        table.load(published["root"])


def test_vertices_outside_the_table_are_never_approximated(published):
    with pytest.raises(table.TableIdentityError):
        table.load(published["root"]).superpose([[1, 4, 5]], [[.2, .3, .5]])


@pytest.mark.parametrize("defect", ["residual", "nonfinite"])
def test_failed_qa_or_values_never_publish(tmp_path, monkeypatch, defect):
    monkeypatch.setattr(table, "frozen_identity", lambda root: FROZEN)
    rows = np.zeros((len(VERTICES), table.SOURCE_COUNT))
    qa = {name: np.zeros(len(VERTICES)) for name in table.QA_ARRAYS}
    if defect == "residual":
        qa["relative_free_dof_residual"][1] = 1e-6
    else:
        rows[0, 0] = np.nan
    staging = table.create_staging(tmp_path)
    np.save(staging / table.ROWS_NAME, rows)
    with pytest.raises(ValueError):
        table.finalize(tmp_path, staging, VERTICES, qa, FROZEN, build={}, verification={})
    assert not table.available(tmp_path)


def test_builder_hashes_the_code_that_runs_and_the_data_it_reads(tmp_path):
    import build_scalp_node_table as builder
    code = builder.code_identity(tmp_path)  # code comes from the script's tree, whatever --repository-root is
    assert set(code) == set(builder.BUILDER_CODE)
    assert code["src/compact_eeg/workflows/scalp_node_table.py"] == table.sha256_file(ROOT / "src/compact_eeg/workflows/scalp_node_table.py")
    with pytest.raises(SystemExit, match="conductivity_scenarios.json"):
        builder.code_identity(tmp_path, "skull_x2")  # a scenario build reads the repository's scenario file
    assert "configs/conductivity_scenarios.json" in builder.code_identity(ROOT, "skull_x2")
