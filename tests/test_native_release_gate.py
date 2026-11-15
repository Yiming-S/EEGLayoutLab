"""Native release boundaries and numerical comparison rules, without a solver."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

import verify_native_release as gate


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


@pytest.fixture
def reference(tmp_path):
    root = tmp_path / "reference"
    root.mkdir()
    receipt = b'{"key":"frozen","result":{"status":"completed"}}'
    destination = "results/v2/design_evaluation_jobs/frozen/cache.json"
    digest = hashlib.sha256(receipt).hexdigest()
    coordinates = np.arange(192, dtype=np.float64).reshape(64, 3)
    layout = {"xyzMm": coordinates.tolist(), "referenceXyzMm": (coordinates + 0.1).tolist(), "regionIndices": [0] * 64}
    artifacts = {}
    for role in gate.ROLES:
        mode = "single_source" if role.startswith("single_source") else "multi_source"
        request = {"mode": mode, "record_id": "frozen"}
        if role.endswith("_payload"):
            content = encoded({"request": request, "record": {"id": "frozen", "layout": layout, "provenance": {"design_result": {"path": destination, "sha256": digest}}}})
        elif role in {"single_source_result", "multi_source_result"}:
            content = encoded({"request": request, "layout": layout})
        elif role == "design_result":
            content = encoded({"evaluated_xyz_mm": layout["xyzMm"]})
        elif role.endswith("_forward"):
            arrays = ({"full_h": np.zeros((128, 6)), "full_projected_xyz_mm": np.vstack([coordinates + 0.1, coordinates])}
                      if role == "design_forward" else {"candidate_h": np.zeros((64, 6)), "baseline_h": np.zeros((64, 6)),
                                                       "candidate_xyz_mm": coordinates, "baseline_xyz_mm": coordinates + 0.1})
            buffer = io.BytesIO()
            np.savez(buffer, **arrays)
            content = buffer.getvalue()
        else:
            content = b"reference bytes"
        path = write(root, role + ".bin", content)
        artifacts[role] = {"path": path.name, "sha256": gate.sha256(path)}
    write(root, "receipt.json", receipt)
    manifest = {"schema": gate.SCHEMA, "comparison": "exact", "artifacts": artifacts,
                "scientific_files": {"src/core.py": {"sha256": hashlib.sha256(b"frozen source").hexdigest(), "bytes": 13}},
                "receipts": [{"destination": destination, "artifact": "receipt.json", "sha256": digest}]}
    path = write(root, "reference.json", encoded(manifest))
    return path, manifest


def save(reference, manifest):
    reference.write_bytes(encoded(manifest))


def test_reference_checks_every_artifact_and_linked_receipt(reference):
    path, manifest = reference
    filename, loaded = gate.load_reference(path)
    assert filename == path.resolve()
    assert loaded == manifest
    write(path.parent, manifest["artifacts"]["design_forward"]["path"], b"modified matrix")
    with pytest.raises(gate.GateError, match="SHA256 mismatch"):
        gate.load_reference(path)


@pytest.mark.parametrize("name", ["../outside", "/absolute", "a/../b", "a//b", "a/./b", "a\\b", ""])
def test_reference_paths_reject_traversal_and_ambiguous_names(name):
    with pytest.raises(gate.GateError):
        gate.relative_name(name)


def test_reference_rejects_external_symlink_even_with_correct_hash(reference, tmp_path):
    path, manifest = reference
    outside = write(tmp_path, "outside.bin", b"outside")
    linked = path.parent / "linked.bin"
    linked.symlink_to(outside)
    manifest["artifacts"]["design_forward"] = {"path": linked.name, "sha256": gate.sha256(outside)}
    save(path, manifest)
    with pytest.raises(gate.GateError, match="leaves its directory"):
        gate.load_reference(path)


def test_reference_rejects_missing_roles_or_unlinked_receipts(reference):
    path, manifest = reference
    missing = copy.deepcopy(manifest)
    del missing["artifacts"]["multi_source_forward"]
    save(path, missing)
    with pytest.raises(gate.GateError, match="all design and single/multi"):
        gate.load_reference(path)
    manifest["receipts"][0]["destination"] = "results/v2/design_evaluation_jobs/different/cache.json"
    save(path, manifest)
    with pytest.raises(gate.GateError, match="not linked"):
        gate.load_reference(path)


def test_scientific_identity_detects_changed_source_and_missing_inputs(reference, tmp_path):
    _, manifest = reference
    source = tmp_path / "source"
    write(source, "src/core.py", b"frozen source")
    gate.verify_scientific_files(source, manifest)
    write(source, "src/core.py", b"edited source")
    with pytest.raises(gate.GateError, match="SHA256 mismatch"):
        gate.verify_scientific_files(source, manifest)
    (source / "src/core.py").unlink()
    with pytest.raises(FileNotFoundError):
        gate.verify_scientific_files(source, manifest)


@pytest.mark.parametrize("cache", gate.CACHE_DIRS)
def test_native_run_refuses_existing_forward_and_signal_caches(tmp_path, cache):
    gate.assert_fresh_caches(tmp_path)
    (tmp_path / "results/v2" / cache).mkdir(parents=True)
    with pytest.raises(gate.GateError, match="existing cache"):
        gate.assert_fresh_caches(tmp_path)


def test_comparison_keeps_dtype_shape_and_sub_ulp_field_differences():
    field = np.array([[1.0, 2.0]], dtype=np.float64)
    assert gate.array_report(field, field.copy())["bytes_equal"]
    assert not gate.array_report(field, field.astype(np.float32))["bytes_equal"]
    assert not gate.array_report(field, field.reshape(2, 1))["bytes_equal"]
    changed = field.copy()
    changed[0, 0] = np.nextafter(changed[0, 0], 2.0)
    report = gate.array_report(changed, field)
    assert not report["bytes_equal"] and report["maximum_absolute_difference"] > 0


def test_scientific_json_and_qa_exclude_only_recorded_timing_and_provenance():
    result = {"score": 0.9, "coordinates": [[1.0, 2.0, 3.0]], "provenance": {"path": "old"}, "elapsed_seconds": 5}
    timing = {**result, "provenance": {"path": "new"}, "elapsed_seconds": 9}
    assert gate.canonical_science(result) == gate.canonical_science(timing)
    assert gate.canonical_science(result) != gate.canonical_science({**result, "score": 0.91})
    qa = {"residual": 1e-12, "timings_seconds": {"solve": 5}, "fem_qa": {"residual": 2e-12, "solve_and_residual_seconds": 5, "cached_preparation_timings": {"t": 1}}}
    updated = copy.deepcopy(qa)
    updated["fem_qa"]["solve_and_residual_seconds"] = 9
    assert gate.strip_qa_timing(qa) == gate.strip_qa_timing(updated)
    updated["fem_qa"]["residual"] = 3e-12
    assert gate.strip_qa_timing(qa) != gate.strip_qa_timing(updated)
    assert "timings_seconds" in qa  # The supplied baseline is never mutated.


def test_default_cli_is_read_only_plan_without_worker_or_workspace_creation(reference, tmp_path, monkeypatch, capsys):
    path, _ = reference
    source = tmp_path / "source"
    write(source, "src/core.py", b"frozen source")
    target = source / "artifacts/new-native-run"
    calls = []
    def prepare(root, output, execute=False):
        calls.append((root, output, execute))
        assert execute is False
        return {"workspace_root": str(output), "sources": [1], "data": [1]}
    def forbidden(*args, **kwargs):
        raise AssertionError("A dry-run must not start a worker or copy data")
    monkeypatch.setitem(sys.modules, "prepare_verification_workspace", SimpleNamespace(prepare=prepare, copy_regular=forbidden))
    monkeypatch.setattr(gate.subprocess, "run", forbidden)
    assert gate.main(["--source-root", str(source), "--reference-manifest", str(path), "--workspace", str(target), "--python", sys.executable]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "plan" and plan["new_fem_executed"] is False
    assert not target.exists() and len(calls) == 1


def test_reference_rejects_double_multi_source_roles_despite_valid_checksums(reference):
    path, manifest = reference
    for kind in ("payload", "result", "forward"):
        manifest["artifacts"]["single_source_" + kind] = manifest["artifacts"]["multi_source_" + kind]
    save(path, manifest)
    with pytest.raises(gate.GateError, match="mode does not match"):
        gate.load_reference(path)


def test_reference_rejects_a_result_from_a_different_request_with_valid_checksum(reference):
    path, manifest = reference
    entry = manifest["artifacts"]["single_source_result"]
    artifact = path.parent / entry["path"]
    result = json.loads(artifact.read_text())
    result["request"]["seed"] = 1234
    artifact.write_bytes(encoded(result))
    entry["sha256"] = gate.sha256(artifact)
    save(path, manifest)
    with pytest.raises(gate.GateError, match="result/request mismatch"):
        gate.load_reference(path)


def test_reference_array_roles_are_checked_before_native_work(reference):
    path, manifest = reference
    gate.validate_reference_arrays(path, manifest)
    entry = manifest["artifacts"]["single_source_forward"]
    artifact = path.parent / entry["path"]
    with np.load(artifact, allow_pickle=False) as original:
        arrays = {key: original[key] for key in original.files}
    arrays["candidate_xyz_mm"] = arrays["candidate_xyz_mm"] + 1
    with artifact.open("wb") as stream:
        np.savez(stream, **arrays)
    entry["sha256"] = gate.sha256(artifact)
    save(path, manifest)
    gate.load_reference(path)  # All checksums are valid; scientific binding still fails.
    with pytest.raises(gate.GateError, match="saved coordinate layout"):
        gate.validate_reference_arrays(path, manifest)


def test_controller_retains_actual_solve_and_numeric_difference_on_worker_failure(reference, tmp_path, monkeypatch):
    path, _ = reference
    source = tmp_path / "source"
    write(source, "src/core.py", b"frozen source")
    target = source / "artifacts/new-native-run"
    def prepare(root, output, execute=False):
        if execute:
            output.mkdir(parents=True, exist_ok=False)
        return {"workspace_root": str(output), "sources": [1], "data": [1]}
    def copy_regular(original, destination):
        write(destination.parent, destination.name, original.read_bytes())
    def simulated_worker(*args, **kwargs):
        directory = target / "native-release-report"
        directory.mkdir()
        state = gate.RunState(directory)
        state.update("native-field-captured", new_fem_executed=True, native_model_attempts=1,
                     native_model_instances=1, native_solve_attempts=1, native_evaluations=[{"shape": [2, 3], "seconds": 1}])
        np.savez(directory / "native-solve-0.npz", h=np.ones((2, 3)))
        difference = gate.array_report(np.ones((2, 3)), np.zeros((2, 3)))
        state.update("compare-design-fields-and-projection", checks={"design.full_forward": difference})
        return SimpleNamespace(returncode=1)
    monkeypatch.setitem(sys.modules, "prepare_verification_workspace", SimpleNamespace(prepare=prepare, copy_regular=copy_regular))
    monkeypatch.setattr(gate.subprocess, "run", simulated_worker)
    with pytest.raises(gate.GateError, match="verification failed"):
        gate.main(["--source-root", str(source), "--reference-manifest", str(path), "--workspace", str(target),
                   "--python", sys.executable, "--execute-new-fem"])
    report = json.loads((target / "native-release-failure.json").read_text())
    assert report["passed"] is False and report["new_fem_executed"] is True
    assert report["new_fem_execution_state"] == "completed_at_least_one_solve"
    assert report["native_model_instances"] == report["native_solve_attempts"] == 1
    assert len(report["native_evaluations"]) == 1
    assert report["stage"] == "compare-design-fields-and-projection"
    assert report["checks"]["design.full_forward"]["bytes_equal"] is False
    assert report["checks"]["design.full_forward"]["maximum_absolute_difference"] == 1


def test_unknown_worker_state_is_never_reported_as_not_executed(tmp_path):
    report = gate.failure_report({"new_fem_executed": False}, tmp_path, 1)
    assert report["new_fem_executed"] is None and report["new_fem_execution_state"] == "unknown"
    directory = tmp_path / "native-release-report"
    directory.mkdir()
    write(directory, "worker-state.json", b'{incomplete')
    assert gate.failure_report({}, tmp_path, 1)["new_fem_execution_state"] == "unknown"
    np.savez(directory / "native-solve-0.npz", h=np.zeros((2, 3)))
    report = gate.failure_report({}, tmp_path, 1)
    assert report["new_fem_executed"] is True
    assert report["new_fem_execution_state"] == "completed_at_least_one_solve"


def test_recorded_native_attempt_without_completion_retains_uncertainty(tmp_path):
    directory = tmp_path / "native-release-report"
    directory.mkdir()
    state = gate.RunState(directory)
    state.update("native-model-construction", new_fem_executed=None, native_model_attempts=1)
    report = gate.failure_report({}, tmp_path, 1)
    assert report["new_fem_executed"] is None
    assert report["new_fem_execution_state"] == "attempted_or_incomplete"
    assert report["native_model_attempts"] == 1 and report["native_model_instances"] == 0


def test_exact_dev_null_character_sink_is_allowed_but_other_external_writes_are_not(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    audit = gate.write_audit(root)
    audit("open", ("/dev/null", "wb", 577))
    with pytest.raises(gate.GateError, match="leaves isolated"):
        audit("open", (str(tmp_path / "outside.bin"), "wb", 577))
    # Invoke the pure guard only: never issue a real unlink of this device.
    with pytest.raises(gate.GateError, match="leaves isolated"):
        audit("os.remove", ("/dev/null", -1))


def test_dev_null_alias_outside_workspace_does_not_expand_the_exception(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    alias = tmp_path / "sink-alias"
    alias.symlink_to("/dev/null")
    with pytest.raises(gate.GateError, match="leaves isolated"):
        gate.write_audit(root)("open", (str(alias), "wb", 577))


def test_installed_write_guard_keeps_only_workspace_and_exact_dev_null_writable(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import verify_native_release as gate
root = Path(sys.argv[2])
gate.restrict_writes(root)
with open('/dev/null', 'wb') as stream:
    stream.write(b'native output sink')
(root / 'inside.bin').write_bytes(b'inside')
try:
    Path(sys.argv[3]).write_bytes(b'outside')
except gate.GateError:
    pass
else:
    raise AssertionError('External ordinary file write was allowed')
"""
    process = gate.subprocess.run([sys.executable, "-c", code, str(Path(gate.__file__).parent), str(root), str(tmp_path / "outside.bin")],
                                  capture_output=True, text=True, check=False)
    assert process.returncode == 0, process.stderr
    assert (root / "inside.bin").read_bytes() == b"inside"
    assert not (tmp_path / "outside.bin").exists()


def test_worker_cache_and_temp_environment_is_local_without_changing_scientific_settings(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'
    root.mkdir()
    monkeypatch.setenv('OMP_NUM_THREADS', '3')
    monkeypatch.setenv('SCIENTIFIC_FIXTURE_PARAMETER', 'unchanged')
    original = dict(gate.os.environ)
    environment = gate.worker_environment(root)
    assert dict(gate.os.environ) == original
    assert environment['OMP_NUM_THREADS'] == '3'
    assert environment['SCIENTIFIC_FIXTURE_PARAMETER'] == 'unchanged'
    assert environment.get('HOME') == original.get('HOME')
    assert environment['PYTHONPATH'] == str(root / 'src')
    for name in ('MPLCONFIGDIR', 'XDG_CACHE_HOME', 'TMPDIR'):
        directory = Path(environment[name])
        assert directory.is_relative_to(root) and directory.is_dir() and not directory.is_symlink()


def test_worker_scratch_environment_rejects_linked_directory(tmp_path):
    root = tmp_path / 'workspace'
    root.mkdir()
    (root / 'native-release-scratch').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(gate.GateError, match='regular directory'):
        gate.worker_environment(root)
