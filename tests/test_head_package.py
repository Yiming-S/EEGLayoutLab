"""Head-package geometry rules on small synthetic meshes (no native runtime)."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pytest
from scipy.spatial import ConvexHull

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compact_eeg.forward_pilot import deterministic_npz_bytes
from compact_eeg.workflows import head_package as hp
from compact_eeg.workflows import scalp_node_table as table


def sphere(count, radius, seed=0):
    rng = np.random.default_rng(seed)
    xyz = rng.normal(size=(count, 3))
    xyz = radius * xyz / np.linalg.norm(xyz, axis=1, keepdims=True)
    faces = ConvexHull(xyz).simplices.copy()
    for face in faces:  # outward orientation
        a, b, c = xyz[face]
        if np.dot(np.cross(b - a, c - a), a + b + c) < 0:
            face[1], face[2] = face[2], face[1]
    return xyz, faces


def test_exterior_scalp_keeps_the_largest_skin_component_in_node_order():
    outer, outer_faces = sphere(60, 90)
    inner, inner_faces = sphere(20, 10, seed=1)
    coords = np.vstack([inner, outer])
    skin = np.vstack([inner_faces, outer_faces + len(inner)])
    other = np.array([[0, 1, 2]])
    node_list = np.vstack([np.column_stack([skin + 1, np.zeros(len(skin), int)]), np.column_stack([other + 1, [0]])])
    elm_type = np.r_[np.full(len(skin), 2), 2]
    tags = np.r_[np.full(len(skin), hp.SKIN_TAG), 1002]
    vertices, triangles, rows = hp.exterior_scalp(np.arange(1, len(coords) + 1), coords, elm_type, tags, node_list)
    np.testing.assert_array_equal(rows, np.arange(len(inner), len(coords)))
    np.testing.assert_array_equal(vertices, outer)
    np.testing.assert_array_equal(rows[triangles], outer_faces + len(inner))


def test_sources_are_deterministic_disjoint_and_cover_the_cortex(monkeypatch):
    monkeypatch.setattr(hp, "DICTIONARY_COUNT", 64)
    monkeypatch.setattr(hp, "GENERATION_COUNT", 16)
    xyz, faces = sphere(2000, 50)
    first, again = hp.sample_sources(xyz, faces), hp.sample_sources(xyz, faces)
    for key in first:
        np.testing.assert_array_equal(first[key], again[key])
    assert not set(first["source_vertex_indices"]) & set(first["generation_vertex_indices"])
    _normals, areas = hp.vertex_normals_and_areas(xyz, faces)
    for name in ("source", "generation"):
        assert first[f"{name}_area_weights"].sum() == pytest.approx(areas.sum(), rel=1e-12)
    assert np.all(np.einsum("ij,ij->i", first["source_normals"], first["source_xyz_mm"]) > 0)  # outward normals
    cortex = xyz[:, 2] > -25  # a "medial wall" cap is never sampled and carries no area
    masked = hp.sample_sources(xyz, faces, cortex)
    assert cortex[masked["source_vertex_indices"]].all() and cortex[masked["generation_vertex_indices"]].all()
    assert masked["source_area_weights"].sum() == pytest.approx(areas[cortex].sum(), rel=1e-12)
    np.testing.assert_array_equal(masked["source_xyz_mm"], xyz[masked["source_vertex_indices"]])
    spacing = np.linalg.norm(first["source_xyz_mm"][:, None] - first["source_xyz_mm"][None], axis=2)
    np.fill_diagonal(spacing, np.inf)
    assert spacing.min(axis=1).max() / spacing.min(axis=1).min() < 3  # near-uniform coverage


def test_deep_gauge_is_a_white_matter_node_near_its_centroid():
    coords = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10], [3, 3, 3], [50, 50, 50.]])
    node_list = np.array([[1, 2, 3, 5], [2, 3, 4, 5], [4, 5, 6, 1]])
    gauge = hp.deep_gauge(coords, [4, 4, 4], [hp.WHITE_MATTER_TAG, hp.WHITE_MATTER_TAG, 2], node_list)
    assert gauge == 5


def write_package(root, mapping=None, manifest=None):
    xyz, faces = sphere(80, 90)
    directory = root / hp.package_dir("synthetic")
    directory.mkdir(parents=True, exist_ok=True)
    eligible = xyz[:, 2] > -30
    arrays = {
        "scalp.npz": {"vertices_mm": xyz, "triangles": faces, "node_rows": np.arange(len(xyz))},
        "admissibility.npz": {"exposure_counts": np.ones((3, len(xyz))), "eligible_vertex_mask": eligible, "unstable_vertex_mask": ~eligible},
        "sources.npz": {"source_xyz_mm": np.zeros((4096, 3)), "generation_xyz_mm": np.zeros((256, 3)),
                        "source_area_weights": np.ones(4096), "generation_area_weights": np.ones(256)},
        "mapping.npz": {"ernie_scalp_to_head_mm": xyz, "reference_vertex_rows": faces[:3], **(mapping or {})},
    }
    files = {}
    for name, value in arrays.items():
        (directory / name).write_bytes(deterministic_npz_bytes(value))
        files[name] = table.sha256_file(directory / name)
    (directory / "package.json").write_bytes(hp.json_bytes({
        "schema": hp.SCHEMA, "head_id": "synthetic", "files": files, "gauge_node_one_based": 7, "dataset": {},
        "source_protocol": hp.SOURCE_PROTOCOL, "source_qa": {}, "admission": {},
        "ernie": {"bank_candidate_sha256": "c" * 64}, **(manifest or {})}))
    return faces, eligible


def publish(root, mapping=None, drop_vertices=()):
    """Write the synthetic package and a zero table for it; the table identity follows package.json."""
    write_package(root, mapping=mapping)
    vertices = np.setdiff1d(hp.table_vertices(hp.load(root, "synthetic")), drop_vertices)
    staging = table.create_staging(root, head="synthetic")
    np.save(staging / table.ROWS_NAME, np.zeros((len(vertices), table.SOURCE_COUNT)))
    table.finalize(root, staging, vertices, {name: np.zeros(len(vertices)) for name in table.QA_ARRAYS}, None,
                   build={}, verification={}, head="synthetic")


@pytest.fixture
def package(tmp_path):
    return (tmp_path, *write_package(tmp_path))


def test_package_loads_verifies_files_and_names_its_table(package):
    root, faces, eligible = package
    loaded = hp.load(root, "synthetic")
    assert hp.list_heads(root) == ["synthetic"] and loaded.gauge_node == 7
    identity = hp.table_identity(loaded)
    assert identity["head_package"] == {"head_id": "synthetic", "sha256": loaded.manifest_sha256}
    expected = np.union1d(table.admissible_vertices(eligible, faces), np.unique(faces[:3]))
    np.testing.assert_array_equal(hp.table_vertices(loaded), expected)
    assert table.pointer_relative(head="synthetic") == hp.package_dir("synthetic") / "table.json"
    with pytest.raises(ValueError):
        table.expected_identity(root, scenario="skull_x2", head="synthetic")
    path = root / hp.package_dir("synthetic") / "sources.npz"
    path.write_bytes(path.read_bytes() + b"x")
    with pytest.raises(hp.HeadPackageError, match="sources.npz"):
        hp.load(root, "synthetic")
    for bad in ("../x", "IXI", "", "a/b"):
        with pytest.raises(hp.HeadPackageError):
            hp.package_dir(bad)


def test_head_table_round_trip(package, monkeypatch):
    root = package[0]
    loaded = hp.load(root, "synthetic")
    vertices = hp.table_vertices(loaded)
    rows = np.random.default_rng(2).normal(size=(len(vertices), table.SOURCE_COUNT))
    staging = table.create_staging(root, head="synthetic")
    np.save(staging / table.ROWS_NAME, rows)
    qa = {name: np.full(len(vertices), 1e-13) for name in table.QA_ARRAYS}
    manifest = table.finalize(root, staging, vertices, qa, None, build={}, verification={}, head="synthetic")
    assert manifest["rows"]["path"].startswith("results/v2/heads/synthetic/table/")
    opened = table.load(root, head="synthetic")
    assert opened.provenance()["head_package"]["head_id"] == "synthetic" and not table.available(root)


def test_identifiers_are_matched_whole():
    for bad in ("ixi002\n", "ixi002\n\n", " ixi002"):
        with pytest.raises(hp.HeadPackageError):
            hp.check_head_id(bad)
    from compact_eeg.workflows.head_model import conductivity_scenario
    with pytest.raises(ValueError, match="identifier"):
        conductivity_scenario(ROOT, "skull_x2\n")


def test_mapped_reference_must_pass_the_layout_screen(package, monkeypatch):
    root, faces, eligible = package
    xyz = hp.load(root, "synthetic").scalp["vertices_mm"]
    inside = faces[np.all(eligible[faces], axis=1)][:4]
    near = np.zeros(4)
    assert hp.layout_screen(eligible, inside, xyz[inside[:, 0]], near)[3]
    outside = np.vstack([inside[:3], faces[~np.all(eligible[faces], axis=1)][:1]])
    assert hp.layout_screen(eligible, outside, xyz[outside[:, 0]], near)[0::3] == (False, False)
    crowded = xyz[inside[:, 0]].copy()
    for gap, accepted in ((3.9, True), (3.0, True), (2.9, False)):  # mapped spacing follows the head size, down to 3 mm
        crowded[1] = crowded[0] + [0, 0, gap]
        screened, spacing, projection, passes = hp.layout_screen(eligible, inside, crowded, near)
        assert screened and spacing == pytest.approx(gap) and projection == 0 and passes is accepted
    for distance, accepted in ((10.0, True), (10.1, False)):  # a mapped point far from the scalp has no counterpart
        screened, _spacing, projection, passes = hp.layout_screen(eligible, inside, xyz[inside[:, 0]], [0, distance, 0, 0])
        assert screened and projection == distance and passes is accepted
    # Evaluation refuses a package whose mapped reference fails any part of the screen, whatever its builder recorded.
    from compact_eeg.workflows import design_evaluation as de
    crowded[1] = crowded[0] + [0, 0, 2.9]
    for mapping in ({"reference_vertex_rows": outside, "reference_xyz_mm": xyz[outside[:, 0]], "reference_projection_mm": near},
                    {"reference_vertex_rows": inside, "reference_xyz_mm": xyz[inside[:, 0]], "reference_projection_mm": [0, 0, 0, 10.5]},
                    {"reference_vertex_rows": inside, "reference_xyz_mm": crowded, "reference_projection_mm": near}):
        publish(root, mapping)
        with pytest.raises(ValueError, match="标准64参照未通过"):
            de.head_space(root, "synthetic", None, {"_candidate_sha256": "c" * 64}, lambda *a: None)
    assert (hp.LAYOUT_PROJECTION_LIMIT_MM, hp.LAYOUT_MINIMUM_SPACING_MM) == (10.0, 3.0)


def test_evaluation_screens_the_mapped_layout(package, monkeypatch):
    """head_space refuses a layout by projection distance, then admissibility, then spacing."""
    from compact_eeg.workflows import design_evaluation as de
    root, faces, eligible = package
    xyz = hp.load(root, "synthetic").scalp["vertices_mm"]
    inside = faces[np.all(eligible[faces], axis=1)][:4]
    mixed = np.vstack([inside[:3], faces[~np.all(eligible[faces], axis=1)][:1]])
    spread = np.full((4, 3), 1 / 3)  # points inside their triangles: every corner carries weight
    corner = np.tile([1., 0, 0], (4, 1))  # points on the first vertex of their triangles
    publish(root, {"reference_vertex_rows": inside, "reference_xyz_mm": xyz[inside[:, 0]],
                   "reference_weights": corner, "reference_projection_mm": np.zeros(4)})
    data = {"_candidate_sha256": "c" * 64, "_surface_vertices_mm": None, "_surface_faces": None}

    def evaluate(rows, points, projection, weights=spread):
        monkeypatch.setattr(hp, "map_points", lambda *a: {
            "vertex_rows": rows, "barycentric_weights": weights, "projected_mm": np.asarray(points, float),
            "mapping_projection_mm": np.asarray(projection, float)})
        return de.head_space(root, "synthetic", None, data, lambda *a: None)

    base = xyz[inside[:, 0]]
    close = base.copy()
    close[1] = close[0] + [0, 0, 2.9]
    # Every failure combination names the first failed test: projection, then admissibility, then spacing.
    with pytest.raises(ValueError, match="10.5 mm，超过10 mm"):
        evaluate(mixed, close, [0, 0, 0, 10.5])
    with pytest.raises(ValueError, match="10.5 mm，超过10 mm"):
        evaluate(inside, close, [0, 0, 0, 10.5])
    with pytest.raises(ValueError, match="外部曝光"):
        evaluate(mixed, close, np.zeros(4))
    with pytest.raises(ValueError, match="2.90 mm，低于3 mm"):
        evaluate(inside, close, np.zeros(4))
    # Displayed values stay on the failing side of the limit.
    with pytest.raises(ValueError, match="10.1 mm，超过10 mm"):
        evaluate(inside, base, [0, 0, 0, 10.04])
    close[1] = close[0] + [0, 0, 2.996]
    with pytest.raises(ValueError, match="2.99 mm，低于3 mm"):
        evaluate(inside, close, np.zeros(4))
    # The limits themselves pass.
    close[1] = close[0] + [0, 0, 3.0]
    qa = evaluate(inside, close, [0, 0, 0, 10.0])[-1]
    assert qa["minimum_spacing_mm"] == pytest.approx(3.0) and qa["mapping_projection_mm"]["maximum"] == 10.0
    close[1] = close[0] + [0, 0, 3.5]  # below the 4 mm design spacing, within the head-size allowance
    qa = evaluate(inside, close, [0, 0, 0, 9.9])[-1]
    assert qa["minimum_spacing_mm"] == pytest.approx(3.5) and qa["mapping_projection_mm"]["maximum"] == pytest.approx(9.9)
    # A point on an admissible vertex is not refused for a zero-weight corner that fails the screen.
    edge = faces[(~np.all(eligible[faces], axis=1)) & eligible[faces[:, 0]]][:1]
    on_vertex = np.vstack([inside[:3], edge])
    evaluate(on_vertex, xyz[on_vertex[:, 0]], np.zeros(4), weights=corner)
    with pytest.raises(ValueError, match="外部曝光"):  # the same triangle with weight on the failing corner
        evaluate(on_vertex, xyz[on_vertex[:, 0]], np.zeros(4))
    # A carrying vertex missing from the table is refused by the screen, not by a table error.
    publish(root, {"reference_vertex_rows": inside, "reference_xyz_mm": xyz[inside[:, 0]],
                   "reference_weights": corner, "reference_projection_mm": np.zeros(4)}, drop_vertices=[edge[0, 0]])
    with pytest.raises(ValueError, match="外部曝光"):
        evaluate(on_vertex, xyz[on_vertex[:, 0]], np.zeros(4), weights=corner)


def test_supporting_rows_point_zero_weight_corners_at_the_main_vertex():
    rows = np.array([[4, 5, 6], [7, 8, 9], [1, 2, 3]])
    weights = np.array([[1., 0, 0], [0, .3, .7], [.2, .3, .5]])
    np.testing.assert_array_equal(hp.supporting_rows(rows, weights), [[4, 4, 4], [9, 8, 9], [1, 2, 3]])
    np.testing.assert_array_equal(rows, [[4, 5, 6], [7, 8, 9], [1, 2, 3]])  # input unchanged


def test_provenance_reports_the_mapping_qa(package):
    root = package[0]
    mapping = {"method": "identity (same subject)", "same_subject_as_ernie": True, "reference_triangles_screened": True,
               "reference_projection_mm": {"maximum": 0., "median": 0.}, "reference_minimum_spacing_mm": 18.2}
    write_package(root, manifest={"mapping": {**mapping, "unrelated": 1}})
    assert hp.load(root, "synthetic").provenance()["mapping"] == mapping


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location("build_head_package", ROOT / "scripts/build_head_package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage_inputs_survive_the_stages_json_round_trip(builder, tmp_path):
    stages = {}
    inputs = {"directions": hp.ADMISSION_DIRECTION_COUNTS, "rotation_rad": hp.ADMISSION_ROTATION_RAD, "code_sha256": {"a.py": "1"}}
    builder.write_stage(tmp_path, "admissibility.npz", {"x": np.arange(3)}, inputs, stages)
    assert builder.reusable(tmp_path, "admissibility.npz", inputs, stages)
    stages = json.loads(json.dumps(stages, indent=1))
    assert builder.reusable(tmp_path, "admissibility.npz", inputs, stages)
    assert not builder.reusable(tmp_path, "admissibility.npz", {**inputs, "code_sha256": {"a.py": "2"}}, stages)


@pytest.mark.parametrize("stage", ["sources.npz", "mapping.npz"])
def test_stages_finished_by_an_equivalent_builder_version_are_reused(builder, tmp_path, stage):
    path, other = "scripts/build_head_package.py", "src/compact_eeg/workflows/head_package.py"
    current = builder.stage_code(stage)
    inputs = {"bank_sha256": "b", "code_sha256": current}
    assert "959eb642cf62907ef9315dc6820917ace9656bde5d83de5bdb12234f40fcc01c" in builder.SAME_STAGE_CODE[path]
    for earlier in builder.SAME_STAGE_CODE[path]:
        assert earlier not in current.values()
        for recorded, bank, reused in (({**current, path: earlier}, "b", True), ({**current, path: earlier}, "c", False),
                                       ({**current, path: "0" * 64}, "b", False),
                                       ({**current, path: earlier, other: earlier}, "b", False)):
            stages = {}
            builder.write_stage(tmp_path, stage, {"x": np.arange(3)}, {"bank_sha256": bank, "code_sha256": recorded}, stages)
            stages = json.loads(json.dumps(stages, indent=1))
            original = (tmp_path / stage).read_bytes()
            assert builder.reusable(tmp_path, stage, inputs, stages) is reused
            assert (tmp_path / stage).read_bytes() == original
            if reused:
                (tmp_path / stage).write_bytes(original + b"changed")
                assert not builder.reusable(tmp_path, stage, inputs, stages)


def test_package_names_inputs_by_their_path_in_the_root(builder, tmp_path, monkeypatch):
    root, elsewhere = tmp_path / "root", tmp_path / "elsewhere/m2m_ernie"
    elsewhere.mkdir(parents=True)
    (root / "data/external/heads/h1/m2m_h1").mkdir(parents=True)
    (root / "data/external/simnibs4_examples").mkdir(parents=True)
    link = root / "data/external/simnibs4_examples/m2m_ernie"
    link.symlink_to(elsewhere)
    assert builder.recorded_path(root, link) == "data/external/simnibs4_examples/m2m_ernie"
    assert builder.recorded_path(root, link / "ernie.msh") == "data/external/simnibs4_examples/m2m_ernie/ernie.msh"
    assert builder.recorded_path(root, root / "data/external/heads/h1/m2m_h1") == "data/external/heads/h1/m2m_h1"
    alias = tmp_path / "alias"
    alias.symlink_to(root)
    assert builder.recorded_path(root, alias / "data/external/heads/h1/m2m_h1") == "data/external/heads/h1/m2m_h1"
    monkeypatch.chdir(root)
    assert builder.recorded_path(root, "data/external/simnibs4_examples/m2m_ernie") == "data/external/simnibs4_examples/m2m_ernie"
    for outside in (elsewhere, tmp_path, root / ".." / "elsewhere"):
        with pytest.raises(SystemExit, match="outside the repository root"):
            builder.recorded_path(root, outside)


def test_build_refuses_inputs_outside_the_root_before_any_stage(builder, tmp_path):
    root = tmp_path / "root"
    (root / "data/external/m2m_h1").mkdir(parents=True)
    (tmp_path / "m2m_h1").mkdir()
    for m2m, ernie in ((tmp_path / "m2m_h1", "data/external/simnibs4_examples/m2m_ernie"),
                       (root / "data/external/m2m_h1", str(tmp_path / "m2m_ernie"))):
        args = argparse.Namespace(head_id="h1", t1=None, t2=None, m2m=str(m2m), ernie_m2m=ernie)
        with pytest.raises(SystemExit, match="outside the repository root"):
            builder.build(args, root)
        assert not (root / hp.package_dir("h1")).exists()


def frozen_ernie(root):
    """A small reference input for builder path checks; no native computation."""
    ernie = root / "data/external/m2m_ernie"
    ernie.mkdir(parents=True)
    (ernie / "ernie.msh").write_bytes(b"frozen mesh")
    (root / "configs").mkdir()
    (root / "configs/ernie_fem_point_pilot.json").write_text(json.dumps({
        "mesh_sha256": table.sha256_file(ernie / "ernie.msh")}))
    return ernie


@pytest.mark.parametrize("invalid", ["outside", "missing", "missing_mesh", "wrong_mesh", "dangling"])
def test_ernie_preflight_precedes_charm_and_output_mutation(builder, monkeypatch, tmp_path, invalid):
    root = tmp_path / "root"
    ernie = frozen_ernie(root)
    if invalid == "outside":
        ernie = tmp_path / "m2m_ernie"
        ernie.mkdir()
    elif invalid == "missing":
        ernie = root / "missing"
    elif invalid == "missing_mesh":
        (ernie / "ernie.msh").unlink()
    elif invalid == "wrong_mesh":
        (ernie / "ernie.msh").write_bytes(b"other mesh")
    else:
        ernie = root / "dangling"
        ernie.symlink_to(tmp_path / "absent")
    def unexpected_charm(*args, **kwargs):
        pytest.fail("charm must not run before the Ernie input is checked")
    monkeypatch.setattr(builder, "run_charm", unexpected_charm)
    args = argparse.Namespace(head_id="h1", t1="t1.nii.gz", t2=None, ernie_m2m=str(ernie),
                              charm_resume=False, charm_forceqform=False)
    with pytest.raises(SystemExit, match="outside the repository root|--ernie-m2m|not the frozen Ernie"):
        builder.build(args, root)
    assert not (root / "results").exists()
    assert not (root / "data/external/heads").exists()


def test_build_reads_target_mesh_keeps_alias_paths_and_reuses_stage_bytes(builder, monkeypatch, tmp_path):
    simnibs = pytest.importorskip("simnibs")
    from simnibs.mesh_tools import mesh_io
    from types import SimpleNamespace

    root = tmp_path / "root"
    ernie = frozen_ernie(root)
    target = tmp_path / "m2m_ernie"
    ernie.rename(target)
    alias, reference_alias = root / "data/external/subject_alias", root / "data/external/reference_alias"
    alias.symlink_to(target)
    reference_alias.symlink_to(target)
    (target / "surfaces").mkdir()
    central = [alias / "surfaces" / f"{side}.central.gii" for side in ("lh", "rh")]
    spheres = [alias / "surfaces" / f"{side}.sphere.reg.gii" for side in ("lh", "rh")]
    for path in [*central, *spheres]:
        path.write_bytes(path.name.encode())
    templates = Path(simnibs.__file__).parent / "resources/templates"
    atlas = [(templates / f"fsaverage_surf/{side}.sphere.gii", templates / f"fsaverage_atlases/{side}.aparc_DK40.annot")
             for side in ("lh", "rh")]

    write_package(root, mapping={"reference_xyz_mm": np.zeros((64, 3)), "reference_projection_mm": np.zeros(64)})
    directory = root / hp.package_dir("synthetic")
    with np.load(directory / "sources.npz") as archive:
        sources = {key: archive[key] for key in archive.files}
    sources.update(source_normals=np.zeros((4096, 3)), generation_normals=np.zeros((256, 3)))
    (directory / "sources.npz").write_bytes(deterministic_npz_bytes(sources))
    originals = {name: (directory / name).read_bytes() for name in hp.FILES}
    digests = {name: table.sha256_file(directory / name) for name in hp.FILES}
    inputs = {
        "scalp.npz": {"mesh_sha256": table.sha256_file(alias / "ernie.msh"), "rule": "largest tag-1005 component"},
        "admissibility.npz": {"scalp_sha256": digests["scalp.npz"], "directions": hp.ADMISSION_DIRECTION_COUNTS,
                              "rotation_rad": hp.ADMISSION_ROTATION_RAD},
        "sources.npz": {"central_sha256": [table.sha256_file(p) for p in central],
                        "sphere_reg_sha256": [table.sha256_file(p) for p in spheres],
                        "atlas_sha256": [[table.sha256_file(p) for p in pair] for pair in atlas], "protocol": hp.SOURCE_PROTOCOL},
        "mapping.npz": {"scalp_sha256": digests["scalp.npz"], "ernie_candidates_sha256": "c", "bank_sha256": "b",
                        "same_subject": True, "transforms_sha256": None},
    }
    stages = {}
    for name in hp.FILES:
        code = builder.stage_code(name)
        if "scripts/build_head_package.py" in code:
            code["scripts/build_head_package.py"] = "959eb642cf62907ef9315dc6820917ace9656bde5d83de5bdb12234f40fcc01c"
        stages[name] = {"inputs": {**inputs[name], "code_sha256": code}, "sha256": digests[name]}
    (directory / "stages.json").write_text(json.dumps(stages))
    original_stages = (directory / "stages.json").read_bytes()
    mesh = SimpleNamespace(nodes=SimpleNamespace(node_number=np.array([1]), node_coord=np.zeros((1, 3))),
                           elm=SimpleNamespace(elm_type=np.array([4]), tag1=np.array([1]),
                                               node_number_list=np.ones((1, 4), int), nr=1,
                                               get_tetrahedra=lambda *args: np.array([0])))
    reads = []
    def read_mesh(path):
        reads.append(path)
        assert Path(path).read_bytes() == b"frozen mesh"
        return mesh
    monkeypatch.setattr(mesh_io, "read_msh", read_mesh)
    monkeypatch.setattr(hp, "deep_gauge", lambda *args: 1)
    monkeypatch.setattr(builder.de, "checked_native_model", lambda *args, **kwargs: (None, {
        "fallback_distance_mm": {"maximum": 0.}, "interpolation_row_sum_max_error": 0.}))
    monkeypatch.setattr(builder.de, "source_exceptions", lambda model: [])
    monkeypatch.setattr(builder.de, "load_bank", lambda root: ({}, {"sha256": "b"}, {"candidate_sha256": "c"}))
    monkeypatch.setattr(builder, "reference_screen", lambda *args: (True, 5., 0.))
    def unexpected_recompute(*args, **kwargs):
        pytest.fail("input path fixes must reuse the completed scientific stages")
    for name in ("exterior_scalp", "admissibility", "sample_sources", "map_points"):
        monkeypatch.setattr(hp, name, unexpected_recompute)
    args = argparse.Namespace(head_id="synthetic", t1=None, m2m=str(alias), ernie_m2m=str(reference_alias),
                              dataset="synthetic", subject="synthetic")
    builder.build(args, root)
    assert reads == [str(alias / "ernie.msh")]
    manifest = hp.load(root, "synthetic").manifest
    assert manifest["inputs"]["m2m"] == "data/external/subject_alias"
    assert manifest["inputs"]["mesh"] == "data/external/subject_alias/ernie.msh"
    assert manifest["inputs"]["ernie_m2m"] == "data/external/reference_alias"
    assert str(target) not in (directory / "package.json").read_text()
    assert manifest["inputs"]["mesh_sha256"] == table.sha256_file(target / "ernie.msh")
    assert manifest["files"] == digests
    assert (directory / "stages.json").read_bytes() == original_stages
    assert {name: (directory / name).read_bytes() for name in hp.FILES} == originals


def test_every_stage_is_keyed_by_the_code_it_runs(builder):
    assert set(builder.STAGE_CODE) == set(hp.FILES)
    for name, files in builder.STAGE_CODE.items():
        assert "src/compact_eeg/workflows/head_package.py" in files
        assert builder.stage_code(name) == {path: table.sha256_file(ROOT / path) for path in files}
    assert "src/compact_eeg/surface_admissibility.py" in builder.STAGE_CODE["admissibility.npz"]
    assert "src/compact_eeg/workflows/scalp_node_table.py" in builder.STAGE_CODE["mapping.npz"]


SCANS = {"t1_sha256": "1" * 64, "t2_sha256": None, "simnibs": "4.6.0"}


@pytest.mark.parametrize("case, stages, exists, mesh, labels, registered, resume, expected", [
    ("fresh", {}, False, None, False, False, False, ("run", False)),
    ("fresh, flag ignored", {}, False, None, False, False, True, ("run", False)),
    ("recorded success", {"charm": {"inputs": SCANS, "mesh_sha256": "m", "operator_asserted": False}}, True, "m", True, True, False, ("reuse", False)),
    ("asserted success", {"charm": {"inputs": SCANS, "mesh_sha256": "m", "operator_asserted": True}}, True, "m", True, True, False, ("reuse", True)),
    ("recorded attempt, labels", {"charm_attempt": {"inputs": SCANS, "operator_asserted": False}}, True, None, True, False, False, ("resume", False)),
    ("recorded attempt, registered", {"charm_attempt": {"inputs": SCANS, "operator_asserted": False}}, True, None, True, True, False, ("rerun", False)),
    ("recorded attempt, no labels", {"charm_attempt": {"inputs": SCANS, "operator_asserted": False}}, True, None, False, False, False, ("rerun", False)),
    ("recorded attempt, stale mesh", {"charm_attempt": {"inputs": SCANS, "operator_asserted": False}}, True, "m", True, False, True, ("resume", False)),
    ("mesh changed since success", {"charm": {"inputs": SCANS, "mesh_sha256": "m", "operator_asserted": False},
                                    "charm_attempt": {"inputs": SCANS, "operator_asserted": False}}, True, "x", True, False, False, ("resume", False)),
    ("asserted attempt", {"charm_attempt": {"inputs": SCANS, "operator_asserted": True}}, True, None, True, False, False, ("resume", True)),
    ("operator adopts a finished folder", {}, True, "m", True, True, True, ("adopt", True)),
    ("operator resume before registration", {}, True, None, True, False, True, ("resume", True)),
    ("operator resume after registration", {}, True, None, True, True, True, ("rerun", True)),
])
def test_charm_folder_is_reused_or_resumed_only_for_the_same_scans(builder, case, stages, exists, mesh, labels, registered, resume, expected):
    assert builder.charm_plan(json.loads(json.dumps(stages)), SCANS, exists, mesh, labels, registered, resume) == expected


@pytest.mark.parametrize("stages, resume, match", [
    ({}, False, "--charm-resume"),  # a folder this builder never recorded
    ({"charm": {"inputs": {**SCANS, "t1_sha256": "2" * 64}, "mesh_sha256": "m"}}, False, "other scans"),  # another scan's mesh
    ({"charm": {"inputs": {**SCANS, "t1_sha256": "2" * 64}, "mesh_sha256": "m"}}, True, "other scans"),  # assertion contradicted
    ({"charm_attempt": {"inputs": {**SCANS, "simnibs": "4.5.0"}}}, False, "other scans"),  # another SimNIBS version
    ({"charm_attempt": {"inputs": {**SCANS, "simnibs": "4.5.0"}}}, True, "other scans"),
])
def test_unrecorded_or_contradicted_charm_folder_is_refused(builder, stages, resume, match):
    with pytest.raises(SystemExit, match=match):
        builder.charm_plan(stages, SCANS, True, "m", True, False, resume)


def test_charm_commands(builder, tmp_path):
    t1, t2 = tmp_path / "t1.nii.gz", tmp_path / "t2.nii.gz"
    assert builder.charm_command("charm", "ixi002", "run", t1, t2) == ["charm", "ixi002", str(t1), str(t2)]
    assert builder.charm_command("charm", "ixi002", "rerun", t1, None) == ["charm", "ixi002", str(t1), "--forcerun"]
    assert builder.charm_command("charm", "ixi002", "resume", t1, t2) == ["charm", "ixi002", "--surfaces", "--mesh"]
    assert builder.charm_command("charm", "ixi016", "run", t1, t2, True) == ["charm", "ixi016", str(t1), str(t2), "--forceqform"]
    assert builder.charm_command("charm", "ixi016", "rerun", t1, t2, True)[-2:] == ["--forceqform", "--forcerun"]
    assert "--forceqform" not in builder.charm_command("charm", "ixi016", "resume", t1, t2, True)


FORCED = {**SCANS, "forceqform": True}


def test_forceqform_is_a_charm_input(builder):
    """A folder is used only with the --charm-forceqform setting it was recorded with."""
    plain = {"charm": {"inputs": SCANS, "mesh_sha256": "m"}}
    forced = {"charm": {"inputs": FORCED, "mesh_sha256": "m", "operator_asserted": False}}
    assert builder.charm_plan(plain, SCANS, True, "m", True, True, False) == ("reuse", False)
    assert builder.charm_plan(forced, FORCED, True, "m", True, True, False) == ("reuse", False)
    with pytest.raises(SystemExit, match="recorded without --charm-forceqform; drop the option"):
        builder.charm_plan(plain, FORCED, True, "m", True, True, False)
    with pytest.raises(SystemExit, match="recorded with --charm-forceqform; pass --charm-forceqform"):
        builder.charm_plan(forced, SCANS, True, "m", True, True, False)
    # charm refused the headers: the attempt left a folder with no labels or mesh, and --forceqform reruns it.
    refused = {"charm_attempt": {"inputs": SCANS, "operator_asserted": False}}
    assert builder.charm_plan(refused, FORCED, True, None, False, False, False) == ("rerun", False)
    assert builder.charm_plan(refused, FORCED, True, None, False, False, True) == ("rerun", False)
    # An attempt that got further was not a header refusal, and dropping the option is never rerun:
    # charm --forcerun deletes the folder before it reads the headers.
    with pytest.raises(SystemExit, match="recorded without --charm-forceqform"):
        builder.charm_plan(refused, FORCED, True, None, True, False, False)
    started = {"charm_attempt": {"inputs": FORCED, "operator_asserted": False}}
    with pytest.raises(SystemExit, match="recorded with --charm-forceqform"):
        builder.charm_plan(started, SCANS, True, None, False, False, False)
    # Other scans or another SimNIBS version keep their own message whatever the option.
    with pytest.raises(SystemExit, match="other scans"):
        builder.charm_plan({"charm_attempt": {"inputs": {**SCANS, "simnibs": "4.5.0"}}}, FORCED, True, None, False, False, False)


@pytest.mark.parametrize("force", [False, True])
def test_run_charm_records_and_passes_forceqform(builder, monkeypatch, tmp_path, force):
    pytest.importorskip("simnibs")
    calls = []
    def fake_charm(command, cwd, **kwargs):
        calls.append(command)
        (Path(cwd) / "m2m_h1").mkdir(exist_ok=True)
        (Path(cwd) / "m2m_h1" / "h1.msh").write_bytes(b"mesh")
        return 0
    monkeypatch.setattr(builder, "check_x86_runtime", lambda: None)
    monkeypatch.setattr(builder.subprocess, "call", fake_charm)
    t1 = tmp_path / "t1.nii.gz"
    t1.write_bytes(b"t1")
    stages = {}
    builder.run_charm("h1", t1, None, tmp_path / "work", stages, lambda: None, False, force)
    assert ("--forceqform" in calls[0]) is force
    assert stages["charm"]["inputs"].get("forceqform", "absent") == (True if force else "absent")
    assert builder.charm_manifest_inputs(stages["charm"]).get("charm_forceqform", "absent") == (True if force else "absent")
    builder.run_charm("h1", t1, None, tmp_path / "work", stages, lambda: None, False, force)
    assert len(calls) == 1  # same setting: reused
    with pytest.raises(SystemExit, match="charm-forceqform"):
        builder.run_charm("h1", t1, None, tmp_path / "work", stages, lambda: None, False, not force)


def test_build_and_main_pass_the_charm_options(builder, monkeypatch, tmp_path):
    seen = []
    class Stop(Exception):
        pass
    def stub(head_id, t1, t2, work, stages, save, resume, force):
        seen.append((resume, force))
        raise Stop
    monkeypatch.setattr(builder, "run_charm", stub)
    ernie = frozen_ernie(tmp_path)
    for resume, force in ((False, True), (True, False)):
        args = argparse.Namespace(head_id="h1", t1="t1.nii.gz", t2=None, charm_resume=resume, charm_forceqform=force,
                                  ernie_m2m=str(ernie))
        with pytest.raises(Stop):
            builder.build(args, tmp_path)
    assert seen == [(False, True), (True, False)]
    for extra in (["--charm-forceqform"], ["--charm-resume"]):
        monkeypatch.setattr(sys, "argv", ["build", "--head-id", "h1", "--m2m", "m2m_h1", "--dataset", "d", "--subject", "s", *extra])
        with pytest.raises(SystemExit) as stopped:
            builder.main()
        assert stopped.value.code == 2
    monkeypatch.setattr(sys, "argv", ["build", "--head-id", "h1", "--t1", "t1.nii.gz", "--dataset", "d", "--subject", "s",
                                      "--charm-forceqform"])
    assert builder.main() == 0  # preview only


def test_builder_refuses_to_publish_a_failing_reference(builder, package):
    root, faces, eligible = package
    xyz = hp.load(root, "synthetic").scalp["vertices_mm"]
    inside = faces[np.all(eligible[faces], axis=1)][:4]
    outside = np.vstack([inside[:3], faces[~np.all(eligible[faces], axis=1)][:1]])
    crowded = xyz[inside[:, 0]].copy()
    crowded[1] = crowded[0] + [0, 0, 2.9]
    assert builder.reference_screen("h1", eligible, inside, xyz[inside[:, 0]], np.zeros(4))[0]
    for rows, points, projection in ((outside, xyz[outside[:, 0]], np.zeros(4)), (inside, crowded, np.zeros(4)),
                                     (inside, xyz[inside[:, 0]], [0, 0, 0, 10.5])):
        with pytest.raises(SystemExit, match="Not published"):
            builder.reference_screen("h1", eligible, rows, points, projection)


def test_missing_rosetta_stops_before_charm(builder, monkeypatch):
    pytest.importorskip("simnibs")  # imported before subprocess.run is replaced
    calls = []
    def missing(command, **kwargs):
        calls.append(command)
        raise OSError(86, "Bad CPU type in executable")
    monkeypatch.setattr(builder.subprocess, "run", missing)
    monkeypatch.setattr(builder.sys, "platform", "darwin")
    monkeypatch.setattr(builder.platform, "machine", lambda: "arm64")
    with pytest.raises(SystemExit, match="softwareupdate --install-rosetta --agree-to-license"):
        builder.check_x86_runtime()
    assert calls[0][0].endswith("external/bin/osx/meshfix")
    monkeypatch.setattr(builder.platform, "machine", lambda: "x86_64")
    builder.check_x86_runtime()
    assert len(calls) == 1
