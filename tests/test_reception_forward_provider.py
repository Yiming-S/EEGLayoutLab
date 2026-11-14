"""Exact-coordinate identity and immutable native-cache checks (no real FEM)."""
from __future__ import annotations
import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compact_eeg.workflows import reception_forward_provider as provider


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(provider._json_bytes(value))


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    rng = np.random.default_rng(451)
    sources, generation = rng.normal(size=(4096, 3)), rng.normal(size=(256, 3))
    normals, gn = rng.normal(size=(4096, 3)), rng.normal(size=(256, 3))
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    gn /= np.linalg.norm(gn, axis=1, keepdims=True)
    xyz = np.column_stack((np.arange(80) * 5., np.ones(80), np.zeros(80)))
    ref = xyz[:64] + [0., 200., 0.]
    hc, hb = rng.normal(size=(80, 4352)), rng.normal(size=(64, 4352))
    weights, gw = np.ones(4096) / 4096, np.ones(256) / 256
    source_path = tmp_path / "sources.npz"
    np.savez(source_path, source_xyz_mm=sources, source_normals=normals, source_area_weights=weights,
        generation_xyz_mm=generation, generation_normals=gn, generation_area_weights=gw)
    batch = tmp_path / "results/v2/campaigns/frozen/runs/id/batches/time"
    batch.mkdir(parents=True)
    bank_path = batch / "bank.npz"
    np.savez(bank_path, dictionary_source_count=4096, reference_leadfield_v_per_am=hb,
        reference_xyz_mm=ref, candidate_xyz_mm=xyz, candidate_leadfield_v_per_am=hc,
        source_xyz_mm=sources, source_area_weights=weights, generation_xyz_mm=generation,
        generation_area_weights=gw)
    source_sha, bank_sha = provider.sha256_file(source_path), provider.sha256_file(bank_path)
    surface_dir = tmp_path / "test_head"
    surface_dir.mkdir()
    head_paths = {"mesh": surface_dir / "head.msh", "scalp_mapping": surface_dir / "mapping.npy",
        "scalp_vertices": surface_dir / "external_scalp_vertices_m.npy",
        "scalp_triangles": surface_dir / "external_scalp_triangles.npy",
        "fem_config": tmp_path / "configs/ernie_fem_point_pilot.json"}
    head_paths["mesh"].write_bytes(b"fixture FEM mesh, never solved")
    np.save(head_paths["scalp_mapping"], np.arange(80))
    faces = np.array([[0, 1, 2], [3, 4, 5]])
    np.save(head_paths["scalp_vertices"], xyz / 1000)
    np.save(head_paths["scalp_triangles"], faces)
    write_json(head_paths["fem_config"], {
        "mesh_path": str(head_paths["mesh"].relative_to(tmp_path)),
        "mesh_sha256": provider.sha256_file(head_paths["mesh"]),
        "external_node_mapping_path": str(head_paths["scalp_mapping"].relative_to(tmp_path)),
        "external_node_mapping_sha256": provider.sha256_file(head_paths["scalp_mapping"])})
    head = {name: provider.sha256_file(path) for name, path in head_paths.items()}
    geometry_path = tmp_path / "geometry.npz"
    np.savez(geometry_path, surface_vertices_m=xyz / 1000, surface_triangles=faces)
    geometry_sha = provider.sha256_file(geometry_path)
    admission_path = tmp_path / "admission.npz"
    np.savez(admission_path, eligible_vertex_mask=np.ones(80, dtype=bool))
    admission_pointer = tmp_path / "results/v2/current_surface_admissibility.json"
    write_json(admission_pointer, {"schema_version": "native-external-exposure/1", "path": "admission.npz",
        "sha256": provider.sha256_file(admission_path), "geometry_sha256": geometry_sha})
    report_path = batch / "report.json"
    write_json(report_path, {"array_sha256": bank_sha, "source_input_sha256": source_sha,
        "candidate_sha256": geometry_sha})
    manifest_path = bank_path.parents[2] / "run_manifest.json"
    write_json(manifest_path, {"source_inputs": "sources.npz", "identity": {"source_input_sha256": source_sha, "head_hashes": head}})
    pointer_path = tmp_path / "results/v2/current_multiregion_bank.json"
    write_json(pointer_path, {"path": str(bank_path.relative_to(tmp_path)),
        "report": str(report_path.relative_to(tmp_path)), "sha256": bank_sha, "candidates": "geometry.npz"})
    # Fingerprint the actual provider dependencies without importing native code.
    for name in provider.CODE_PATHS:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    runtime_root = tmp_path / "native_runtime"
    runtime_files = {"python": runtime_root / "bin/python",
        "conda": runtime_root / "conda-meta/simnibs.json",
        "solver": runtime_root / "lib/libdmumps_seq.dylib"}
    locations = {"prefix": runtime_root, "executable": runtime_files["python"], "packages": {}}
    for name in provider.NATIVE_PACKAGES:
        package_root = runtime_root / "site-packages" / name
        origin = package_root / "__init__.py"
        metadata = runtime_root / "site-packages" / (name + "-1.dist-info") / "METADATA"
        runtime_files[name + "_metadata"] = metadata
        runtime_files[name + "_origin"] = origin
        locations["packages"][name] = {"version": "fixture-1", "root": package_root,
            "origin": origin, "metadata": [metadata]}
    for name in provider.SIMNIBS_SOURCE_FILES:
        runtime_files[name] = locations["packages"]["simnibs"]["root"] / name
    runtime_files["compiled"] = locations["packages"]["cortech"]["root"] / "numerical.so"
    for name, path in runtime_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("runtime fixture " + name).encode())
    monkeypatch.setattr(provider, "_native_runtime_locations", lambda: locations)
    record = {"id": "a" * 64, "status": "completed", "dataset_id": "cache",
        "layout": {"xyzMm": xyz[:64].tolist(), "referenceXyzMm": ref.tolist(), "regionIndices": [0] * 32 + [1] * 32}}
    return {"root": tmp_path, "record": record, "xyz": xyz, "ref": ref, "hc": hc, "hb": hb,
        "source_path": source_path, "source_sha": source_sha, "head": head,
        "bank_path": bank_path, "report_path": report_path, "pointer_path": pointer_path,
        "manifest_path": manifest_path, "bank_sha": bank_sha,
        "head_paths": head_paths, "geometry_path": geometry_path,
        "admission_path": admission_path, "admission_pointer": admission_pointer,
        "runtime_files": runtime_files, "runtime_locations": locations}


def completed_design(frozen):
    xyz = frozen["xyz"][:64].copy()
    xyz[0, 1] += .01
    labels = [0] * 32 + [1] * 32
    result = {"schema": "design-evaluation/1", "status": "completed", "forward_mode": "direct_fem",
        "evaluated_xyz_mm": xyz.tolist(), "request": {"design": {
            "coordinate_system": "ernie_native_mm", "unit": "mm", "xyz_mm": (xyz + [0, .1, 0]).tolist(),
            "region_indices": labels}}, "provenance": {"bank_sha256": frozen["bank_sha"]}}
    path = frozen["root"] / "results/v2/design_evaluation_jobs" / ("b" * 64) / "cache.json"
    write_json(path, {"key": "b" * 64, "result": result})
    return {"id": "b" * 64, "status": "completed", "dataset_id": "design_evaluation",
        "layout": {"xyzMm": xyz.tolist(), "referenceXyzMm": frozen["ref"].tolist(), "regionIndices": labels},
        "provenance": {"design_result": {"path": str(path.relative_to(frozen["root"])), "sha256": provider.sha256_file(path)}}}


def fake_native(frozen, *, shift=0.):
    calls = []
    def native(root, xyz, progress):
        calls.append(np.asarray(xyz).copy())
        evaluated = xyz.copy()
        evaluated[0, 2] += shift
        return frozen["hc"][:64].copy(), evaluated, abs(shift), {
            "head_hashes": frozen["head"], "reference_relative_difference": 2e-13,
            "source_qa": {"test_stub": True}, "fem_qa": {"test_stub": True}}
    return calls, native


def test_catalog_verifies_normals_source_order_and_identities(frozen):
    catalog, provenance = provider.load_frozen_source_catalog(frozen["root"])
    assert catalog["generation_normals"].shape == (256, 3)
    assert catalog["source_normals"].shape == (4096, 3)
    np.testing.assert_allclose(np.linalg.norm(catalog["generation_normals"], axis=1), 1., atol=1e-15)
    assert provenance["source_inputs_sha256"] == frozen["source_sha"]
    assert len(provenance["catalog_identity_sha256"]) == 64
    assert not (frozen["root"] / provider.CACHE_RELATIVE_ROOT).exists()


def test_exact_bank_never_calls_native_or_writes_cache(frozen, monkeypatch):
    monkeypatch.setattr(provider, "_run_native", lambda *a: pytest.fail("native branch called"))
    data, p = provider.load_reception_forward(frozen["root"], frozen["record"], allow_native=True)
    np.testing.assert_array_equal(data["candidate_h"], frozen["hc"][:64])
    assert p["forward_mode"] == "exact_bank" and not p["fem_recomputed"]
    assert not (frozen["root"] / provider.CACHE_RELATIVE_ROOT).exists()


def test_reference_identity_is_exact(frozen):
    record = frozen["record"]
    record["layout"]["xyzMm"] = frozen["ref"].tolist()
    data, p = provider.load_reception_forward(frozen["root"], record)
    np.testing.assert_array_equal(data["candidate_h"], data["baseline_h"])
    assert p["forward_mode"] == "exact_reference"


def test_nonbank_point_cannot_be_replaced_by_nearest(frozen):
    frozen["record"]["layout"]["xyzMm"][0][0] += 1e-10
    with pytest.raises(ValueError, match="nearest-neighbour"):
        provider.load_reception_forward(frozen["root"], frozen["record"], allow_native=True)


def test_new_design_requires_explicit_native_opt_in(frozen, monkeypatch):
    monkeypatch.setattr(provider, "_run_native", lambda *a: pytest.fail("unscheduled native branch"))
    with pytest.raises(provider.ForwardComputationRequired):
        provider.load_reception_forward(frozen["root"], completed_design(frozen))
    assert not (frozen["root"] / provider.CACHE_RELATIVE_ROOT).exists()


def test_native_archive_reuses_exact_h_and_sources_without_second_solve(frozen, monkeypatch):
    record = completed_design(frozen)
    old_design_bytes = (frozen["root"] / record["provenance"]["design_result"]["path"]).read_bytes()
    calls, native = fake_native(frozen)
    monkeypatch.setattr(provider, "_run_native", native)
    data, first = provider.load_reception_forward(frozen["root"], record, allow_native=True)
    repeated, second = provider.load_reception_forward(frozen["root"], record)
    assert len(calls) == 1 and first["forward_mode"] == "native_fem_new" and second["forward_mode"] == "native_fem_cache"
    assert first["fem_recomputed"] and not second["fem_recomputed"]
    for key in data:
        np.testing.assert_array_equal(data[key], repeated[key])
    np.testing.assert_array_equal(repeated["candidate_xyz_mm"], record["layout"]["xyzMm"])
    assert "not exposed or archived" in second["reference_field_origin"]
    manifest = json.loads((frozen["root"] / second["forward_manifest_path"]).read_text())
    assert manifest["array_identities"]["candidate_h"]["shape"] == [64, 4352]
    assert manifest["array_identities"]["generation_normals"]["shape"] == [256, 3]
    assert (frozen["root"] / record["provenance"]["design_result"]["path"]).read_bytes() == old_design_bytes


def test_reprojection_drift_is_retained_as_failure_not_qualified_cache(frozen, monkeypatch):
    record = completed_design(frozen)
    _, native = fake_native(frozen, shift=2e-7)
    monkeypatch.setattr(provider, "_run_native", native)
    with pytest.raises(ValueError, match="re-projection"):
        provider.load_reception_forward(frozen["root"], record, allow_native=True)
    cache_root = frozen["root"] / provider.CACHE_RELATIVE_ROOT
    assert len(list(cache_root.glob("*/attempts/*/failed.json"))) == 1
    assert not list(cache_root.glob("*/cache.json"))


def test_corrupt_native_payload_never_recomputed_silently(frozen, monkeypatch):
    record = completed_design(frozen)
    calls, native = fake_native(frozen)
    monkeypatch.setattr(provider, "_run_native", native)
    _, p = provider.load_reception_forward(frozen["root"], record, allow_native=True)
    manifest = json.loads((frozen["root"] / p["forward_manifest_path"]).read_text())
    payload = frozen["root"] / manifest["payload_path"]
    payload.write_bytes(payload.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="payload hash"):
        provider.load_reception_forward(frozen["root"], record, allow_native=True)
    assert len(calls) == 1


@pytest.mark.parametrize("mutate", ["record_coordinate", "bytehash", "source_order", "reference", "duplicate"])
def test_integrity_failures_are_explicit(frozen, mutate):
    record = completed_design(frozen)
    if mutate == "record_coordinate":
        record["layout"]["xyzMm"][0][0] += 1e-10
    elif mutate == "bytehash":
        record["provenance"]["design_result"]["sha256"] = "0" * 64
    elif mutate == "source_order":
        with np.load(frozen["source_path"]) as archive:
            d = {k: archive[k] for k in archive.files}
        d["generation_xyz_mm"] = d["generation_xyz_mm"][::-1]
        np.savez(frozen["source_path"], **d)
        digest = provider.sha256_file(frozen["source_path"])
        for path in [frozen["report_path"], frozen["manifest_path"]]:
            value = json.loads(path.read_text())
            target = value.get("identity", value)
            target["source_input_sha256"] = digest
            write_json(path, value)
    elif mutate == "reference":
        record["layout"]["referenceXyzMm"][0][0] += 1e-10
    else:
        record["layout"]["xyzMm"][0] = record["layout"]["xyzMm"][1]
    with pytest.raises(ValueError):
        provider.load_reception_forward(frozen["root"], record)


def test_global_native_lock_does_not_start_competing_solve(frozen, monkeypatch):
    record = completed_design(frozen)
    monkeypatch.setattr(provider, "_run_native", lambda *a: pytest.fail("competing native solve"))
    with provider._native_lock(frozen["root"] / provider.CACHE_RELATIVE_ROOT):
        with pytest.raises(ValueError, match="Another native"):
            provider.load_reception_forward(frozen["root"], record, allow_native=True)


@pytest.mark.parametrize("dependency", ["python", "conda", "numpy_metadata", "scipy_metadata",
    "simnibs_metadata", "cortech_metadata", "simulation/fem.py", "mesh_tools/mesh_io.py", "compiled", "solver"])
def test_runtime_byte_changes_cannot_hit_old_native_cache(frozen, monkeypatch, dependency):
    record = completed_design(frozen)
    calls, native = fake_native(frozen)
    monkeypatch.setattr(provider, "_run_native", native)
    _, first = provider.load_reception_forward(frozen["root"], record, allow_native=True)
    index = frozen["root"] / first["forward_cache_path"]
    old_index = index.read_bytes()
    path = frozen["runtime_files"][dependency]
    path.write_bytes(path.read_bytes() + b"changed numerical dependency")
    with pytest.raises(provider.ForwardComputationRequired):
        provider.load_reception_forward(frozen["root"], record)
    assert len(calls) == 1
    assert index.read_bytes() == old_index  # Original evidence is never overwritten.


@pytest.mark.parametrize("part", ["fem_config", "mesh", "scalp_mapping", "scalp_vertices", "scalp_triangles"])
def test_current_head_hashes_are_checked_before_native_cache_hit(frozen, monkeypatch, part):
    record = completed_design(frozen)
    calls, native = fake_native(frozen)
    monkeypatch.setattr(provider, "_run_native", native)
    provider.load_reception_forward(frozen["root"], record, allow_native=True)
    path = frozen["head_paths"][part]
    path.write_bytes(path.read_bytes() + b"head changed")
    with pytest.raises(ValueError, match="Current head"):
        provider.load_reception_forward(frozen["root"], record, allow_native=True)
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["eligible_mask", "pointer_protocol"])
def test_current_admission_changes_require_new_native_cache(frozen, monkeypatch, change):
    record = completed_design(frozen)
    calls, native = fake_native(frozen)
    monkeypatch.setattr(provider, "_run_native", native)
    _, first = provider.load_reception_forward(frozen["root"], record, allow_native=True)
    pointer = json.loads(frozen["admission_pointer"].read_text())
    if change == "eligible_mask":
        mask = np.ones(80, dtype=bool)
        mask[0] = False
        np.savez(frozen["admission_path"], eligible_vertex_mask=mask)
        pointer["sha256"] = provider.sha256_file(frozen["admission_path"])
    else:
        pointer["schema_version"] = "native-external-exposure/next"
    write_json(frozen["admission_pointer"], pointer)
    with pytest.raises(provider.ForwardComputationRequired):
        provider.load_reception_forward(frozen["root"], record)
    assert len(calls) == 1
    assert (frozen["root"] / first["forward_cache_path"]).is_file()


@pytest.mark.parametrize("part,match", [("admission_path", "payload SHA256"), ("geometry_path", "geometry differs")])
def test_current_admission_integrity_failure_precedes_cache_read(frozen, monkeypatch, part, match):
    record = completed_design(frozen)
    calls, native = fake_native(frozen)
    monkeypatch.setattr(provider, "_run_native", native)
    provider.load_reception_forward(frozen["root"], record, allow_native=True)
    path = frozen[part]
    path.write_bytes(path.read_bytes() + b"invalid data")
    with pytest.raises(ValueError, match=match):
        provider.load_reception_forward(frozen["root"], record, allow_native=True)
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["runtime", "admission"])
def test_dependency_change_during_solve_cannot_create_qualified_cache(frozen, monkeypatch, change):
    record = completed_design(frozen)
    _, native = fake_native(frozen)
    def changing_native(*args):
        result = native(*args)
        if change == "runtime":
            frozen["runtime_files"]["conda"].write_bytes(b"changed runtime during solve")
        else:
            pointer = json.loads(frozen["admission_pointer"].read_text())
            pointer["schema_version"] += "/changed"
            write_json(frozen["admission_pointer"], pointer)
        return result
    monkeypatch.setattr(provider, "_run_native", changing_native)
    with pytest.raises(ValueError, match="changed during forward computation"):
        provider.load_reception_forward(frozen["root"], record, allow_native=True)
    cache_root = frozen["root"] / provider.CACHE_RELATIVE_ROOT
    assert len(list(cache_root.glob("*/attempts/*/failed.json"))) == 1
    assert not list(cache_root.glob("*/cache.json"))


def test_historical_exact_bank_and_catalog_do_not_requalify_current_admission(frozen, monkeypatch):
    frozen["admission_pointer"].write_bytes(b"no current admission")
    frozen["head_paths"]["mesh"].write_bytes(b"different current head")
    monkeypatch.setattr(provider, "_native_runtime_locations", lambda: pytest.fail("historical path inspected native runtime"))
    catalog, _ = provider.load_frozen_source_catalog(frozen["root"])
    data, provenance = provider.load_reception_forward(frozen["root"], frozen["record"], allow_native=True)
    assert provenance["forward_mode"] == "exact_bank"
    assert catalog["generation_normals"].shape == (256, 3)
    np.testing.assert_array_equal(data["candidate_h"], frozen["hc"][:64])


@pytest.mark.parametrize("part,match", [("simnibs_metadata", "dependency is missing"), ("solver", "MUMPS solver")])
def test_native_runtime_missing_dependencies_fail_closed(frozen, part, match):
    frozen["runtime_files"][part].unlink()
    with pytest.raises(ValueError, match=match):
        provider.load_reception_forward(frozen["root"], completed_design(frozen))


def shared_fields(frozen):
    record = completed_design(frozen)
    xyz = np.asarray(record["layout"]["xyzMm"])
    _, native = fake_native(frozen, shift=1e-14)
    h, evaluated, _, qa = native(frozen["root"], xyz, None)
    with provider.design_forward_session(frozen["root"], xyz + [0, .1, 0]) as publish:
        publish(xyz, h, evaluated, qa)
    return record, h, evaluated


def test_design_prepared_fields_are_read_without_native_solve_or_fabricated_receipt(frozen, monkeypatch):
    record, h, evaluated = shared_fields(frozen)
    monkeypatch.setattr(provider, "_run_native", lambda *a: pytest.fail("duplicate native solve"))
    inputs, provenance = provider.load_reception_forward(frozen["root"], record)
    assert provenance["forward_mode"] == "native_fem_cache"
    assert provenance["fem_recomputed"] is False
    assert provenance["shared_forward_producer"] == "design_evaluation"
    assert "/shared_fields/" in provenance["forward_cache_path"]
    assert "native_origin_record" not in provenance
    assert inputs["candidate_h"].tobytes() == h.tobytes()
    assert inputs["baseline_h"].tobytes() == frozen["hb"].tobytes()
    assert np.asarray(provenance["evaluated_candidate_xyz_mm"]).tobytes() == evaluated.tobytes()
    assert "not exposed or archived" in provenance["reference_field_origin"]
    manifest = json.loads((frozen["root"] / provenance["forward_manifest_path"]).read_text())
    assert manifest["schema"] == provider.shared_native_forward.SCHEMA
    assert "origin_record" not in manifest
    record["provenance"]["design_result"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Design result"):
        provider.load_reception_forward(frozen["root"], record)


@pytest.mark.parametrize("file,match", [("fields.npz", "payload hash"), ("manifest.json", "manifest hash")])
def test_shared_corruption_never_triggers_silent_recalculation(frozen, monkeypatch, file, match):
    record, _, _ = shared_fields(frozen)
    _, provenance = provider.load_reception_forward(frozen["root"], record)
    path = (frozen["root"] / provenance["forward_manifest_path"]).parent / file
    path.write_bytes(path.read_bytes() + b"corrupted")
    monkeypatch.setattr(provider, "_run_native", lambda *a: pytest.fail("recomputed corruption"))
    with pytest.raises(ValueError, match=match):
        provider.load_reception_forward(frozen["root"], record, allow_native=True)


@pytest.mark.parametrize("change", ["runtime", "code", "admission"])
def test_shared_artifact_is_invalidated_by_current_identity(frozen, change):
    record, _, _ = shared_fields(frozen)
    if change == "runtime":
        path = frozen["runtime_files"]["solver"]
        path.write_bytes(path.read_bytes() + b"updated solver")
    elif change == "code":
        path = frozen["root"] / "src/compact_eeg/workflows/shared_native_forward.py"
        path.write_bytes(path.read_bytes() + b"\n# updated implementation")
    else:
        pointer = json.loads(frozen["admission_pointer"].read_text())
        pointer["schema_version"] += "/next"
        write_json(frozen["admission_pointer"], pointer)
    with pytest.raises(provider.ForwardComputationRequired):
        provider.load_reception_forward(frozen["root"], record)


def test_shared_input_coordinates_must_match_every_bit(frozen):
    record, _, _ = shared_fields(frozen)
    record["layout"]["xyzMm"][0][0] += 1e-12
    path = frozen["root"] / record["provenance"]["design_result"]["path"]
    saved = json.loads(path.read_text())
    saved["result"]["evaluated_xyz_mm"] = record["layout"]["xyzMm"]
    write_json(path, saved)
    record["provenance"]["design_result"]["sha256"] = provider.sha256_file(path)
    with pytest.raises(provider.ForwardComputationRequired):
        provider.load_reception_forward(frozen["root"], record)


def test_design_and_reception_share_the_global_native_lock(frozen):
    record = completed_design(frozen)
    with provider.design_forward_session(frozen["root"], record["layout"]["xyzMm"]):
        with pytest.raises(ValueError, match="Another native"):
            provider.load_reception_forward(frozen["root"], record, allow_native=True)


def test_changes_during_design_cannot_publish_shared_fields(frozen):
    record = completed_design(frozen)
    xyz = np.asarray(record["layout"]["xyzMm"])
    _, native = fake_native(frozen)
    h, evaluated, _, qa = native(frozen["root"], xyz, None)
    with pytest.raises(provider.shared_native_forward.IdentityChanged):
        with provider.design_forward_session(frozen["root"], xyz) as publish:
            path = frozen["runtime_files"]["solver"]
            path.write_bytes(path.read_bytes() + b"updated during solve")
            with pytest.raises(provider.shared_native_forward.IdentityChanged, match="changed during shared"):
                publish(xyz, h, evaluated, qa)
    assert not (frozen["root"] / provider.shared_native_forward.RELATIVE_ROOT).exists()


def test_interrupted_shared_publication_never_leaves_a_cache_hit(frozen, monkeypatch):
    def interrupted(*args):
        raise OSError("interrupted before publication")
    monkeypatch.setattr(provider.shared_native_forward.os, "rename", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        shared_fields(frozen)
    cache = frozen["root"] / provider.shared_native_forward.RELATIVE_ROOT
    assert not list(cache.iterdir())


def test_repeated_shared_publication_preserves_archive_bytes(frozen):
    record, _, _ = shared_fields(frozen)
    _, first = provider.load_reception_forward(frozen["root"], record)
    path = frozen["root"] / first["forward_manifest_path"]
    before = path.read_bytes()
    shared_fields(frozen)
    assert path.read_bytes() == before


def test_different_field_for_same_shared_identity_is_rejected(frozen):
    record, h, evaluated = shared_fields(frozen)
    xyz = np.asarray(record["layout"]["xyzMm"])
    _, native = fake_native(frozen)
    _, _, _, qa = native(frozen["root"], xyz, None)
    with provider.design_forward_session(frozen["root"], xyz) as publish:
        h[0, 0] += 1e-12
        with pytest.raises(ValueError, match="different numerical bytes"):
            publish(xyz, h, evaluated, qa)


@pytest.mark.parametrize("preparation_failure", [None, "projection", "solve", "io", "identity", "corruption", "cancel"])
def test_design_preparation_retains_both_original_projection_paths(frozen, monkeypatch, preparation_failure):
    """Two fresh legacy calls must equal one prepared design call, including ULP shifts."""
    from types import SimpleNamespace
    from compact_eeg import cortical_fem
    from compact_eeg.workflows import design_evaluation, head_model
    data = {"reference_xyz_mm": frozen["ref"], "reference_leadfield_v_per_am": frozen["hb"],
        "_surface_faces": np.array([[0, 1, 2]]), "_surface_vertices_mm": frozen["xyz"],
        "_eligible_surface": np.ones(80, dtype=bool)}
    with np.load(frozen["source_path"]) as source:
        data.update({name: source[name] for name in ("source_xyz_mm", "generation_xyz_mm")})
    class Surface:
        def __init__(self, *args): pass
        def project_points(self, points, **kwargs):
            points = np.asarray(points)
            return (np.zeros(len(points), dtype=int), np.zeros((len(points), 3)),
                    points + [0, 0, 1e-14], None)
    monkeypatch.setitem(sys.modules, "cortech", SimpleNamespace(Surface=Surface))
    monkeypatch.setattr(head_model, "load_head", lambda root: (None, None, frozen["xyz"],
        data["_surface_faces"], None, frozen["head"]))
    models = []
    class Model:
        def __init__(self, *args, progress):
            self.progress = progress
            self.timings = {"source_operator_seconds": 1., "factorization_seconds": 1.}
            self.source_qa = {"fallback_distance_mm": {"maximum": 0.},
                "interpolation_row_sum_max_error": 0., "normal_operator_constant_field_max_abs": 0.,
                "official_operator_sample_check": {"relative_frobenius_difference": 0.}}
            tags = np.ones(4352, dtype=int)
            tags[[698, 957, 1559, 3408]] = -1
            self.source_qa_arrays = {"containing_tissue_tag_or_minus_one": tags}
            self.calls = 0
            self.projections = 0
            models.append(self)
        def project(self, points):
            self.projections += 1
            if self.projections == 2 and preparation_failure == "projection":
                raise ValueError("Synthetic optional projection failure")
            points = np.asarray(points)
            projected = points + [0, 0, 2e-14]
            return SimpleNamespace(requested_mm=points, projected_mm=projected,
                triangle_ids=np.zeros(len(points), dtype=int), node_rows=np.zeros((len(points), 3), dtype=int),
                barycentric_weights=projected.copy(), distances_mm=np.linalg.norm(projected - points, axis=1))
        def evaluate(self, projection, **kwargs):
            if self.calls == 1 and preparation_failure == "solve":
                raise ValueError("Synthetic optional solve QA failure")
            if self.calls == 1 and preparation_failure == "cancel":
                raise KeyboardInterrupt("Synthetic cancellation")
            self.calls += 1
            self.progress('cortical_fem_electrode_block_complete', completed_electrodes=128, total_electrodes=128)
            h = np.vstack([frozen["hb"], np.repeat(projection.projected_mm[64:, 2, None] * 1e6, 4352, axis=1)])
            return h, {"max_relative_full_system_residual": 0., "max_relative_free_dof_residual": 0.,
                "point_transfer_reciprocity_relative_frobenius": 0.,
                "net_prescribed_current_A_per_electrode": [0.],
                "net_assembled_current_A_per_electrode": [0.],
                "reaction_current_relative_error_per_electrode": [0.]}
    monkeypatch.setattr(cortical_fem, "FixedMeshLeadfield", Model)
    pointer = json.loads(frozen["pointer_path"].read_text())
    report = json.loads(frozen["report_path"].read_text())
    xyz = frozen["xyz"][:64]
    legacy_design = design_evaluation.native_field(frozen["root"], xyz, data, pointer, report, lambda *a: None)
    legacy_signal = design_evaluation.native_field(frozen["root"], legacy_design[1], data, pointer, report, lambda *a: None)
    assert legacy_design[0].tobytes() != legacy_signal[0].tobytes()
    stored, progress = [], []
    def publish(*args):
        if preparation_failure == "io":
            raise OSError("Synthetic cache disk failure")
        if preparation_failure == "identity":
            raise provider.shared_native_forward.IdentityChanged("Synthetic runtime changed")
        if preparation_failure == "corruption":
            raise provider.shared_native_forward.IntegrityError("Synthetic corrupt shared artifact")
        stored.append(args)
    def compute():
        return design_evaluation.native_field(frozen["root"], xyz, data, pointer, report,
            lambda value, _: progress.append(value), reception_publisher=publish)
    if preparation_failure in ("identity", "corruption", "cancel"):
        error_type = {"identity": provider.shared_native_forward.IdentityChanged,
            "corruption": provider.shared_native_forward.IntegrityError,
            "cancel": KeyboardInterrupt}[preparation_failure]
        with pytest.raises(error_type):
            compute()
        return
    optimized = compute()
    if preparation_failure is not None:
        assert optimized[0].tobytes() == legacy_design[0].tobytes()
        assert optimized[1].tobytes() == legacy_design[1].tobytes()
        assert optimized[3]["reception_preparation"]["status"] == "unavailable"
        assert stored == []
        return
    assert len(models) == 3 and models[-1].calls == 2
    for old, new in zip(legacy_design[:2], optimized[:2]):
        assert old.tobytes() == new.tobytes()
    signal_xyz, signal_h, evaluated, qa = stored[0]
    assert signal_xyz.tobytes() == legacy_design[1].tobytes()
    assert signal_h.tobytes() == legacy_signal[0].tobytes()
    assert evaluated.tobytes() == legacy_signal[1].tobytes()
    assert qa == legacy_signal[3]
    assert progress == sorted(progress)


def test_design_session_always_rechecks_identity_when_no_artifact_was_prepared(frozen):
    record = completed_design(frozen)
    with pytest.raises(provider.shared_native_forward.IdentityChanged):
        with provider.design_forward_session(frozen["root"], record["layout"]["xyzMm"]):
            path = frozen["runtime_files"]["solver"]
            path.write_bytes(path.read_bytes() + b"changed during optional preparation failure")
