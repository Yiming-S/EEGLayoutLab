"""Conductivity-mismatch scenarios: named conductivities, separate tables, mismatch field metric."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compact_eeg import noise_models
from compact_eeg.layout_search_metrics import LayoutSearchMetrics
from compact_eeg.workflows import design_evaluation, scalp_node_table as table
from compact_eeg.workflows.head_model import conductivity_scenario

FROZEN = {"bank_sha256": "b" * 64, "source_count": table.SOURCE_COUNT}
VERTICES = np.array([1, 4, 7, 9, 12])


def test_scenarios_scale_only_their_declared_skull_tags():
    base = json.loads((ROOT / "configs/ernie_fem_point_pilot.json").read_text())["isotropic_conductivity_by_tetrahedron_tag"]
    for name, factor in (("skull_x0.5", .5), ("skull_x2", 2.)):
        scenario = conductivity_scenario(ROOT, name)
        assert scenario["scale_by_tetrahedron_tag"] == {"7": factor, "8": factor}
        for tag, value in base.items():
            assert scenario["conductivity_by_tetrahedron_tag"][tag] == pytest.approx(value * (factor if tag in "78" else 1), rel=1e-15)
    for bad in ("skull_x3", "..", "../skull_x2", "Skull_x2", "", None, 2):
        with pytest.raises(ValueError):
            conductivity_scenario(ROOT, bad)


@pytest.fixture
def repository(tmp_path, monkeypatch):
    (tmp_path / "configs").mkdir()
    for name in ("conductivity_scenarios.json", "ernie_fem_point_pilot.json"):
        shutil.copy(ROOT / "configs" / name, tmp_path / "configs" / name)
    monkeypatch.setattr(table, "frozen_identity", lambda root: FROZEN)
    return tmp_path


def publish(root, scenario, seed):
    rows = np.random.default_rng(seed).normal(size=(len(VERTICES), table.SOURCE_COUNT))
    staging = table.create_staging(root, scenario)
    np.save(staging / table.ROWS_NAME, rows)
    qa = {name: np.full(len(VERTICES), 1e-13) for name in table.QA_ARRAYS}
    return table.finalize(root, staging, VERTICES, qa, FROZEN, build={}, verification={}, scenario=scenario), rows


def test_scenario_tables_have_their_own_pointer_directory_and_identity(repository):
    manifest, rows = publish(repository, "skull_x2", 1)
    assert table.available(repository, "skull_x2") and not table.available(repository) and not table.available(repository, "skull_x0.5")
    assert manifest["rows"]["path"].startswith("results/v2/scalp_node_table_scenarios/skull_x2/")
    loaded = table.load(repository, "skull_x2")
    assert loaded.provenance()["conductivity_scenario"]["conductivity_by_tetrahedron_tag"]["7"] == pytest.approx(.016)
    np.testing.assert_array_equal(loaded.superpose([[1, 4, 7]], [[1., 0., 0.]]), rows[:1])
    nominal, _ = publish(repository, None, 1)
    assert nominal["table_id"] != manifest["table_id"] and "conductivity_scenario" not in table.load(repository).provenance()
    config = repository / "configs/conductivity_scenarios.json"
    changed = json.loads(config.read_text())
    changed["scenarios"]["skull_x2"]["scale_by_tetrahedron_tag"]["7"] = 3.0
    config.write_text(json.dumps(changed))
    with pytest.raises(table.TableIdentityError):
        table.load(repository, "skull_x2")
    table.load(repository)  # the nominal table does not depend on scenario definitions


def sphere_surface(count=400, radius=90.):
    from scipy.spatial import ConvexHull
    k = np.arange(count) + .5
    polar, azimuth = np.arccos(1 - 2 * k / count), np.pi * (1 + 5 ** .5) * k
    xyz = radius * np.column_stack([np.cos(azimuth) * np.sin(polar), np.sin(azimuth) * np.sin(polar), np.cos(polar)])
    return xyz, ConvexHull(xyz).simplices.astype(np.int64)


@pytest.fixture
def screened_bank(repository, monkeypatch):
    """A bank vertex whose every triangle touches a screened vertex, as candidate 4925 on Ernie."""
    pytest.importorskip("cortech")
    vertices, faces = sphere_surface()
    lonely = 0
    neighbours = np.setdiff1d(faces[np.any(faces == lonely, axis=1)], [lonely])
    eligible = np.ones(len(vertices), bool)
    eligible[neighbours] = False
    clear = [v for v in range(len(vertices)) if np.all(eligible[faces[np.any(faces == v, axis=1)]])]
    reference_vertices, bank_vertices = np.array(clear[:64]), np.r_[lonely, clear[64:127]]
    monkeypatch.setattr(design_evaluation, "ernie_scalp", lambda root, data: (vertices, faces, {"mesh": "m" * 64}))
    data = {"reference_xyz_mm": vertices[reference_vertices], "_surface_vertices_mm": vertices, "_surface_faces": faces}
    return {"root": repository, "vertices": vertices, "faces": faces, "eligible": eligible, "data": data,
            "reference_vertices": reference_vertices, "bank_vertices": bank_vertices, "lonely": lonely}


def publish_rows(root, scenario, vertices, seed):
    rows = np.random.default_rng(seed).normal(size=(len(vertices), table.SOURCE_COUNT))
    staging = table.create_staging(root, scenario)
    np.save(staging / table.ROWS_NAME, rows)
    qa = {name: np.full(len(vertices), 1e-13) for name in table.QA_ARRAYS}
    table.finalize(root, staging, vertices, qa, FROZEN, build={}, verification={}, scenario=scenario)
    return rows


def test_scenario_fields_cover_admitted_bank_vertices_on_partly_screened_triangles(screened_bank):
    s = screened_bank
    covered = table.table_vertices(s["eligible"], s["faces"], s["bank_vertices"], s["eligible"][s["bank_vertices"]])
    assert s["lonely"] in covered and s["lonely"] not in table.admissible_vertices(s["eligible"], s["faces"])
    nominal, scenario = (publish_rows(s["root"], name, covered, seed) for name, seed in ((None, 1), ("skull_x2", 2)))
    row = lambda rows, ids: rows[np.searchsorted(covered, ids)]  # noqa: E731
    true_h, true_hb, qa = design_evaluation.scenario_fields(
        s["root"], design_evaluation.scenario_tables(s["root"], "skull_x2"), s["vertices"][s["bank_vertices"]], s["data"],
        row(nominal, s["bank_vertices"]), row(nominal, s["reference_vertices"]), candidate_ids=np.arange(64) + 4900)
    np.testing.assert_allclose(true_h, row(scenario, s["bank_vertices"]), rtol=0, atol=1e-12)
    np.testing.assert_allclose(true_hb, row(scenario, s["reference_vertices"]), rtol=0, atol=1e-12)
    assert qa["nominal_sampling_relative_difference"] <= 1e-12
    # A table that misses the vertex is named precisely, never blamed on a version mismatch.
    old = table.admissible_vertices(s["eligible"], s["faces"])
    for name, seed in ((None, 1), ("skull_x2", 2)):
        publish_rows(s["root"], name, old, seed)
    with pytest.raises(table.TableIdentityError, match=f"第1个电极（候选库编号 4900）所在面片的顶点 {s['lonely']} "):
        design_evaluation.scenario_fields(s["root"], design_evaluation.scenario_tables(s["root"], "skull_x2"),
                                          s["vertices"][s["bank_vertices"]], s["data"], None, None, candidate_ids=np.arange(64) + 4900)


def scenario_request():
    return {"action": "evaluate", "design": {"schema": "eeg-electrode-design/1", "coordinate_system": "ernie_native_mm", "unit": "mm",
            "xyz_mm": [[5. * i, 0., 0.] for i in range(64)], "region_indices": [0] * 32 + [1] * 32},
            "radius_mm": 3, "seed": 1, "conductivity_scenario": "skull_x2"}


@pytest.mark.parametrize("published", [(), ("skull_x2",), (None,), (None, "skull_x2", "stale")])
def test_scenario_tables_are_checked_before_any_forward_computation(repository, monkeypatch, published):
    for scenario in published:
        if scenario == "stale":
            config = repository / "configs/conductivity_scenarios.json"
            changed = json.loads(config.read_text())
            changed["scenarios"]["skull_x2"]["scale_by_tetrahedron_tag"]["7"] = 3.0
            config.write_text(json.dumps(changed))
        else:
            publish(repository, scenario, 1)
    monkeypatch.setattr(design_evaluation, "load_bank", lambda root: ({}, {"sha256": "b" * 64}, {}))
    for name in ("table_field", "native_field", "ernie_projection", "head_space", "scenario_fields"):
        monkeypatch.setattr(design_evaluation, name, lambda *a, **k: pytest.fail("forward computation before the table check"))
    expected = {(): "skull_x2 的头皮节点表尚未预计算", ("skull_x2",): "名义头皮节点表", (None,): "skull_x2 的头皮节点表尚未预计算",
                (None, "skull_x2", "stale"): "预计算头皮节点表与当前"}[published]
    with pytest.raises(ValueError, match=expected):
        design_evaluation.evaluate(scenario_request(), root=repository)


@pytest.fixture
def fields():
    rng = np.random.default_rng(11)
    mix = rng.normal(size=(12, 90))
    nominal = rng.normal(size=(64, 12)) @ mix + .05 * rng.normal(size=(64, 90))
    reference = rng.normal(size=(64, 12)) @ mix + .05 * rng.normal(size=(64, 90))
    return {"rng": rng, "nominal": nominal, "reference": reference, "weights": rng.uniform(.2, 2, 90),
            "xyz": rng.normal(size=(64, 3)) * 40, "reference_xyz": rng.normal(size=(64, 3)) * 50}


def test_matched_mismatch_metric_is_the_production_lmmse(fields):
    relative, candidate, reference = design_evaluation.mismatch_field_retention(
        fields["nominal"], fields["nominal"], fields["reference"], fields["reference"], fields["weights"])
    own = LayoutSearchMetrics(fields["nominal"], fields["reference"], fields["weights"]).evaluate(np.arange(64), snr_db=(20,))["conditions"][0]
    assert relative == pytest.approx(own["field_retention_unclipped"], rel=1e-10)
    assert candidate == pytest.approx(own["candidate_field_explained_energy"], rel=1e-10)
    assert reference == pytest.approx(own["reference_field_explained_energy"], rel=1e-10)
    kernel = (.5, 20.)
    noise = {"candidate": noise_models.spatial_correlation(fields["xyz"], *kernel),
             "reference": noise_models.spatial_correlation(fields["reference_xyz"], *kernel)}
    correlated = LayoutSearchMetrics(fields["nominal"], fields["reference"], fields["weights"],
                                     noise_kernel=(fields["xyz"], fields["reference_xyz"], *kernel)).make_state(np.arange(64))
    matched = design_evaluation.mismatch_field_retention(fields["nominal"], fields["nominal"], fields["reference"], fields["reference"],
                                                         fields["weights"], noise=noise)[0]
    assert matched == pytest.approx(correlated.field_relative, rel=1e-10)


def test_mismatch_never_beats_the_estimator_trained_on_the_truth(fields):
    rng = fields["rng"]
    true = fields["nominal"] * (1 + .3 * rng.normal(size=(64, 1)))
    true_reference = fields["reference"] * (1 + .3 * rng.normal(size=(64, 1)))
    _, candidate, _ = design_evaluation.mismatch_field_retention(fields["nominal"], true, fields["reference"], true_reference, fields["weights"])
    scale = (np.sum((design_evaluation.helmert_contrast(64) @ fields["reference"]) ** 2 * fields["weights"])
             / np.sum((design_evaluation.helmert_contrast(64) @ true_reference) ** 2 * fields["weights"]))
    # Same physical noise in volts: the oracle LMMSE on the true head is the optimum.
    _, oracle_same_noise, _ = design_evaluation.mismatch_field_retention(true, true, true_reference, true_reference, fields["weights"],
                                                                         snr_db=20 + 10 * np.log10(1 / scale))
    assert candidate < oracle_same_noise


def test_requests_name_a_known_scenario_for_evaluation_only():
    base = {"action": "evaluate", "design": {"schema": "eeg-electrode-design/1", "coordinate_system": "ernie_native_mm", "unit": "mm",
            "xyz_mm": [[5. * i, 0., 0.] for i in range(64)], "region_indices": [0] * 32 + [1] * 32}, "radius_mm": 3, "seed": 1}
    assert design_evaluation.validate_request({**base, "conductivity_scenario": "skull_x2"})["conductivity_scenario"] == "skull_x2"
    for bad in ({**base, "conductivity_scenario": "skull_x3"}, {**base, "action": "perturb", "conductivity_scenario": "skull_x2"},
                {**base, "conductivity_scenario": None}):
        with pytest.raises(ValueError):
            design_evaluation.validate_request(bad)
