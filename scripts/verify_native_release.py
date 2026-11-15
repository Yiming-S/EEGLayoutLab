#!/usr/bin/env python3
"""Check a fresh native FEM run against an explicit, immutable reference bundle.

The default prints a plan. A new workspace, reference manifest and existing
qualified Python interpreter are required; --execute-new-fem opts into a solve.
No downloads, runtime installation, service startup or daily result writes occur.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True

SCHEMA = "eeglayoutlab-native-release-reference/1"
ROLES = {"design_request", "design_result", "design_forward"} | {
    f"{mode}_{kind}" for mode in ("single_source", "multi_source")
    for kind in ("payload", "result", "forward")
}
CACHE_DIRS = ("reception_forward", "source_reception_v2_jobs")


class GateError(ValueError):
    pass


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   indent=2, allow_nan=False) + "\n")


class RunState:
    """Retain progress before native work and before any numerical assertion."""
    def __init__(self, directory):
        self.path = Path(directory) / "worker-state.json"
        self.value = {"schema": "eeglayoutlab-native-release-state/1", "stage": "worker-started",
                      "native_model_attempts": 0, "native_model_instances": 0,
                      "native_solve_attempts": 0, "native_evaluations": [],
                      "new_fem_executed": False, "checks": {}}
        self.update("worker-started")

    def update(self, stage, **values):
        self.value.update(values, stage=stage)
        write_json(self.path, self.value)


def failure_report(plan, workspace, returncode):
    """A missing worker report means unknown execution, never 'not executed'."""
    workspace = Path(workspace)
    directory = workspace / "native-release-report"
    try:
        state = read_json(directory / "worker-state.json")
        valid = (isinstance(state, dict) and state.get("schema") == "eeglayoutlab-native-release-state/1"
                 and all(type(state.get(key)) is int and state[key] >= 0
                         for key in ("native_model_attempts", "native_model_instances", "native_solve_attempts"))
                 and isinstance(state.get("stage"), str) and isinstance(state.get("native_evaluations"), list)
                 and isinstance(state.get("checks"), dict))
    except (OSError, ValueError, TypeError):
        state, valid = None, False
    archives = sorted(path.name for path in directory.glob("native-solve-*.npz"))
    attempted = bool(valid and (state["native_model_attempts"] or state["native_solve_attempts"]))
    completed = bool(archives or (valid and (state["native_model_instances"] or state["native_evaluations"])))
    executed = True if completed else None if attempted or not valid else False
    execution = ("completed_at_least_one_solve" if archives or (valid and state["native_evaluations"])
                 else "native_model_constructed" if completed else "attempted_or_incomplete" if attempted
                 else "not_started" if valid else "unknown")
    return {**plan, "passed": False, "worker_exit_code": returncode,
            "log": str(workspace / "native-release.log"), "new_fem_executed": executed,
            "new_fem_execution_state": execution, "stage": state["stage"] if valid else "unknown",
            "native_model_attempts": state["native_model_attempts"] if valid else None,
            "native_model_instances": state["native_model_instances"] if valid else None,
            "native_solve_attempts": state["native_solve_attempts"] if valid else None,
            "native_evaluations": state["native_evaluations"] if valid else None,
            "native_solve_archives": archives, "checks": state["checks"] if valid else {},
            "worker_state": str(directory / "worker-state.json") if valid else None}


def relative_name(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise GateError("Expected a relative POSIX path")
    path = Path(value)
    if path.is_absolute() or any(p in {"", ".", ".."} for p in value.split("/")):
        raise GateError("Unsafe relative path: " + value)
    return path


def local_file(root, name):
    root = Path(root).resolve(strict=True)
    path = root / relative_name(name)
    if not path.resolve(strict=True).is_relative_to(root) or not path.is_file():
        raise GateError("Reference file leaves its directory: " + name)
    return path


def check_hash(path, expected):
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise GateError("Invalid SHA256")
    if sha256(path) != expected:
        raise GateError("SHA256 mismatch: " + str(path))


def load_reference(filename):
    filename = Path(filename).resolve(strict=True)
    reference = read_json(filename)
    if not isinstance(reference, dict) or reference.get("schema") != SCHEMA:
        raise GateError("Unsupported native release reference schema")
    if reference.get("comparison") != "exact":
        raise GateError("This reference requires exact numerical equality")
    artifacts = reference.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != ROLES:
        raise GateError("Reference must identify all design and single/multi-source artifacts")
    for entry in artifacts.values():
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise GateError("Invalid reference artifact")
        check_hash(local_file(filename.parent, entry["path"]), entry["sha256"])
    files = reference.get("scientific_files")
    if not isinstance(files, dict) or not files:
        raise GateError("Reference must freeze scientific source and inputs")
    for name, entry in files.items():
        relative_name(name)
        if not isinstance(entry, dict) or set(entry) != {"sha256", "bytes"} or type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise GateError("Invalid scientific file identity")
        if not isinstance(entry["sha256"], str) or len(entry["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in entry["sha256"]):
            raise GateError("Invalid scientific SHA256")
    receipts = reference.get("receipts")
    if not isinstance(receipts, list) or not receipts:
        raise GateError("Reference must include completed design provenance receipts")
    seen = set()
    for receipt in receipts:
        if not isinstance(receipt, dict) or set(receipt) != {"destination", "artifact", "sha256"}:
            raise GateError("Invalid design receipt")
        relative = relative_name(receipt["destination"])
        if len(relative.parts) != 5 or relative.parts[:3] != ("results", "v2", "design_evaluation_jobs") or relative.name != "cache.json":
            raise GateError("Receipt must be a completed design cache.json")
        if str(relative) in seen:
            raise GateError("Duplicate receipt destination")
        seen.add(str(relative))
        check_hash(local_file(filename.parent, receipt["artifact"]), receipt["sha256"])
    for mode in ("single_source", "multi_source"):
        payload = read_json(local_file(filename.parent, artifacts[mode + "_payload"]["path"]))
        result = read_json(local_file(filename.parent, artifacts[mode + "_result"]["path"]))
        request = payload.get("request")
        if not isinstance(request, dict) or request.get("mode") != mode:
            raise GateError("Source payload mode does not match its reference role: " + mode)
        if result.get("request") != request:
            raise GateError("Source reference result/request mismatch: " + mode)
        if request.get("record_id") != payload.get("record", {}).get("id"):
            raise GateError("Source request is not linked to its saved record: " + mode)
        proof = payload.get("record", {}).get("provenance", {}).get("design_result", {})
        if (proof.get("path"), proof.get("sha256")) not in {(r["destination"], r["sha256"]) for r in receipts}:
            raise GateError("Source payload is not linked to a supplied design receipt")
    return filename, reference


def validate_reference_arrays(filename, reference):
    """Bind NPZ coordinate/field roles before allowing any native construction."""
    import numpy as np
    def artifact(role):
        return local_file(Path(filename).parent, reference["artifacts"][role]["path"])
    result = read_json(artifact("design_result"))
    candidate = np.asarray(result["evaluated_xyz_mm"], dtype=np.float64)
    with np.load(artifact("design_forward"), allow_pickle=False) as field:
        if (field["full_h"].shape[0] != len(candidate) * 2
                or field["full_projected_xyz_mm"].shape != (len(candidate) * 2, 3)
                or not np.array_equal(field["full_projected_xyz_mm"][len(candidate):], candidate)):
            raise GateError("Design reference arrays do not match the completed design")
    for mode in ("single_source", "multi_source"):
        payload = read_json(artifact(mode + "_payload"))
        result = read_json(artifact(mode + "_result"))
        layout = payload["record"]["layout"]
        for name in ("xyzMm", "referenceXyzMm", "regionIndices"):
            if result["layout"][name] != layout[name]:
                raise GateError("Source reference result/layout mismatch: " + mode)
        with np.load(artifact(mode + "_forward"), allow_pickle=False) as field:
            if (not np.array_equal(field["candidate_xyz_mm"], np.asarray(layout["xyzMm"], dtype=np.float64))
                    or not np.array_equal(field["baseline_xyz_mm"], np.asarray(layout["referenceXyzMm"], dtype=np.float64))
                    or field["candidate_h"].shape != field["baseline_h"].shape
                    or field["candidate_h"].shape[0] != len(layout["xyzMm"])):
                raise GateError("Source reference arrays do not match their saved coordinate layout: " + mode)


def verify_scientific_files(root, reference):
    for name, identity in reference["scientific_files"].items():
        path = local_file(root, name)
        if path.stat().st_size != identity["bytes"]:
            raise GateError("Scientific file size changed: " + str(path))
        check_hash(path, identity["sha256"])


def assert_fresh_caches(root):
    for name in CACHE_DIRS:
        path = Path(root) / "results/v2" / name
        if path.exists() or path.is_symlink():
            raise GateError("Fresh native run refuses an existing cache: " + str(path))


def strip_qa_timing(value):
    result = json.loads(json.dumps(value))
    result.pop("timings_seconds", None)
    if isinstance(result.get("fem_qa"), dict):
        result["fem_qa"].pop("solve_and_residual_seconds", None)
        result["fem_qa"].pop("cached_preparation_timings", None)
    return result


def canonical_science(value):
    return json.dumps({k: v for k, v in value.items() if k not in {"provenance", "elapsed_seconds"}},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def array_report(current, expected):
    import numpy as np
    current, expected = np.asarray(current), np.asarray(expected)
    shape = current.shape == expected.shape
    return {"shape": list(current.shape), "dtype": str(current.dtype),
            "bytes_equal": bool(shape and current.dtype == expected.dtype and current.tobytes() == expected.tobytes()),
            "maximum_absolute_difference": float(np.max(np.abs(current - expected))) if shape and current.size else None,
            "sha256": hashlib.sha256(current.tobytes()).hexdigest()}


def write_audit(root):
    root = Path(root).resolve()
    def audit(event, args):
        paths = []
        if event == "open":
            path, mode, flags = args
            if isinstance(path, (str, bytes, os.PathLike)) and ((mode and any(c in mode for c in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                paths.append(path)
        elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime"}:
            paths.append(args[0])
        elif event in {"os.rename", "os.link", "os.symlink"}:
            paths.extend(args[:2])
        for path in paths:
            # Numerical dependencies use this character device as a process
            # output sink. This exception permits only opening that exact sink,
            # never unlink/rename operations or any other external path.
            if (event == "open" and os.fsdecode(path) == "/dev/null"
                    and stat.S_ISCHR(os.stat("/dev/null").st_mode)):
                continue
            if not Path(os.fsdecode(path)).resolve().is_relative_to(root):
                raise GateError("Worker write leaves isolated workspace: " + str(path))
    return audit


def restrict_writes(root):
    sys.addaudithook(write_audit(root))


def worker_environment(workspace):
    """Keep dependency caches and temporary files inside the isolated checkout."""
    root = Path(workspace).resolve(strict=True)
    scratch = root / "native-release-scratch"
    directories = {"MPLCONFIGDIR": scratch / "matplotlib", "XDG_CACHE_HOME": scratch / "cache", "TMPDIR": scratch / "tmp"}
    for path in (scratch, *directories.values()):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise GateError("Native scratch path must be a regular directory: " + str(path))
        path.mkdir(mode=0o700, exist_ok=True)
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(root / "src"),
            **{name: str(path) for name, path in directories.items()}}


def run_worker(spec_file):
    spec = read_json(spec_file)
    root = Path(spec["workspace"]).resolve(strict=True)
    out = root / "native-release-report"
    out.mkdir(exist_ok=False)
    restrict_writes(root)
    progress = RunState(out)
    progress.update("verify-reference-and-scientific-inputs")
    reference_path, reference = load_reference(spec["reference_manifest"])
    check_hash(reference_path, spec["reference_manifest_sha256"])
    check_hash(__file__, spec["source_identity"]["gate_sha256"])
    validate_reference_arrays(reference_path, reference)
    verify_scientific_files(root, reference)
    assert_fresh_caches(root)
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[variable] = "1"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / "src"))
    import numpy as np
    from threadpoolctl import threadpool_limits
    from compact_eeg.workflows import design_evaluation as design
    from compact_eeg.workflows import reception_forward_provider as provider
    from compact_eeg.workflows import source_reception_v2 as source
    from compact_eeg.cortical_fem import FixedMeshLeadfield
    for module in (design, provider, source):
        if not Path(module.__file__).resolve().is_relative_to(root / "src"):
            raise GateError("Scientific imports leave isolated source: " + module.__file__)
    def artifact(role):
        return local_file(reference_path.parent, reference["artifacts"][role]["path"])
    instances, calls = [], []
    native_allowed = True
    original_init, original_evaluate = FixedMeshLeadfield.__init__, FixedMeshLeadfield.evaluate
    def tracked_init(self, *args, **kwargs):
        if not native_allowed:
            raise GateError("Reception must reuse the new design field, without another native construction")
        progress.update("native-model-construction", new_fem_executed=None,
                        native_model_attempts=progress.value["native_model_attempts"] + 1)
        original_init(self, *args, **kwargs)
        instances.append(time.perf_counter())
        progress.update("native-model-constructed", new_fem_executed=True, native_model_instances=len(instances))
    def tracked_evaluate(self, projection, *args, **kwargs):
        if not native_allowed:
            raise GateError("Reception must reuse the new design field, without another solve")
        progress.update("native-field-solving", new_fem_executed=True,
                        native_solve_attempts=progress.value["native_solve_attempts"] + 1)
        started = time.perf_counter()
        result = original_evaluate(self, projection, *args, **kwargs)
        np.savez(out / f"native-solve-{len(calls)}.npz", h=result[0], xyz_mm=projection.projected_mm)
        calls.append({"shape": list(result[0].shape), "seconds": time.perf_counter() - started})
        progress.update("native-field-captured", native_evaluations=calls)
        return result
    FixedMeshLeadfield.__init__, FixedMeshLeadfield.evaluate = tracked_init, tracked_evaluate
    checks, timings = {}, {}
    progress.update("evaluate-design", checks=checks)
    started = time.perf_counter()
    with threadpool_limits(limits=1):
        actual = design.evaluate(read_json(artifact("design_request")), root=root)
    timings["design_seconds"] = time.perf_counter() - started
    write_json(out / "design-result.json", actual)
    expected = read_json(artifact("design_result"))
    for key in ("nominal", "evaluated_xyz_mm", "projection_max_mm", "request", "trials", "forward_mode"):
        checks["design." + key] = actual[key] == expected[key]
        progress.update("compare-design-" + key, checks=checks)
        if not checks["design." + key]:
            raise GateError("Design result changed: " + key)
    checks["design.qa"] = strip_qa_timing(actual["native_qa"]) == strip_qa_timing(expected["native_qa"])
    progress.update("compare-design-qa", checks=checks)
    if not instances or not calls or actual["forward_mode"] != "direct_fem" or not checks["design.qa"]:
        raise GateError("Fresh direct FEM construction, solve and unchanged numerical QA are required")
    with np.load(artifact("design_forward"), allow_pickle=False) as old, np.load(out / "native-solve-0.npz", allow_pickle=False) as new:
        checks["design.full_forward"] = array_report(new["h"], old["full_h"])
        checks["design.full_projection"] = array_report(new["xyz_mm"], old["full_projected_xyz_mm"])
    progress.update("compare-design-fields-and-projection", checks=checks)
    if not checks["design.full_forward"]["bytes_equal"] or not checks["design.full_projection"]["bytes_equal"]:
        raise GateError("Complete native fields or projected coordinates changed")
    after_design = (len(instances), len(calls))
    native_allowed = False
    for mode in ("single_source", "multi_source"):
        progress.update("evaluate-" + mode, checks=checks)
        payload = read_json(artifact(mode + "_payload"))
        started = time.perf_counter()
        with threadpool_limits(limits=1):
            inputs, provenance = provider.load_reception_forward(root, payload["record"], allow_native=False)
            result = source.run_experiment(root, payload)
        timings[mode + "_seconds"] = time.perf_counter() - started
        write_json(out / (mode + "-result.json"), result)
        write_json(out / (mode + "-forward-provenance.json"), provenance)
        np.savez(out / (mode + "-forward.npz"), **inputs)
        with np.load(artifact(mode + "_forward"), allow_pickle=False) as old:
            if set(inputs) != set(old.files):
                raise GateError("Source input array names changed: " + mode)
            fields = {name: array_report(inputs[name], old[name]) for name in old.files}
        expected = read_json(artifact(mode + "_result"))
        science = canonical_science(result)
        checks[mode] = {"forward_arrays": fields, "scientific_json_bytes_equal": science == canonical_science(expected),
                        "scientific_json_sha256": hashlib.sha256(science).hexdigest(),
                        "native_qa_equal": strip_qa_timing(result["provenance"]["native_qa"]) == strip_qa_timing(expected["provenance"]["native_qa"]),
                        "fem_recomputed": provenance["fem_recomputed"]}
        progress.update("compare-" + mode, checks=checks)
        if (not all(v["bytes_equal"] for v in fields.values()) or not checks[mode]["scientific_json_bytes_equal"]
                or not checks[mode]["native_qa_equal"] or provenance["fem_recomputed"]
                or after_design != (len(instances), len(calls))):
            raise GateError("Source science changed or design-to-reception sharing missed: " + mode)
    verify_scientific_files(root, reference)
    verify_scientific_files(spec["source_root"], reference)
    check_hash(reference_path, spec["reference_manifest_sha256"])
    check_hash(__file__, spec["source_identity"]["gate_sha256"])
    load_reference(reference_path)  # Recheck all frozen reference bytes after use.
    runtime = provider._native_runtime_identity()
    write_json(out / "summary.json", {"passed": True, "reference_manifest": str(reference_path),
               "reference_manifest_sha256": sha256(reference_path), "workspace": str(root),
               "source_root": spec["source_root"], "scientific_files_unchanged": len(reference["scientific_files"]),
               "source_identity": spec["source_identity"], "interpreter": sys.executable, "runtime": runtime,
               "native_model_instances": len(instances), "native_evaluations": calls,
               "source_native_calls": len(calls) - after_design[1], "checks": checks, "timings": timings,
               "signal_excluded_fields": ["provenance", "elapsed_seconds"],
               "qa_excluded_paths": ["timings_seconds", "fem_qa.solve_and_residual_seconds", "fem_qa.cached_preparation_timings"]})
    progress.update("completed", passed=True, checks=checks)
    print(json.dumps({"passed": True, "report": str(out / "summary.json"), "native_evaluations": len(calls)}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--reference-manifest", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True, help="Existing qualified native Python interpreter; never installed by this tool")
    parser.add_argument("--execute-new-fem", action="store_true")
    args = parser.parse_args(argv)
    source = args.source_root.resolve(strict=True)
    reference_path, reference = load_reference(args.reference_manifest)
    verify_scientific_files(source, reference)
    interpreter = args.python.resolve(strict=True)
    if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
        raise GateError("Python interpreter must be an existing executable")
    sys.path.insert(0, str(source / "scripts"))
    from prepare_verification_workspace import prepare, copy_regular
    report = prepare(source, args.workspace, execute=False)
    workspace = Path(report["workspace_root"])
    identity = {"scientific_files": reference["scientific_files"], "gate_sha256": sha256(__file__)}
    plan = {"mode": "execute" if args.execute_new_fem else "plan", "reference_manifest": str(reference_path),
            "reference_manifest_sha256": sha256(reference_path), "workspace": str(workspace),
            "interpreter": str(interpreter), "scientific_files": len(reference["scientific_files"]),
            "source_files": len(report["sources"]), "data_files": len(report["data"]),
            "new_fem_executed": False, "existing_caches_copied": False,
            "scope": "Exact same-runtime numerical regression, not independent-head, mesh-convergence or target-platform qualification."}
    if not args.execute_new_fem:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    prepare(source, workspace, execute=True)
    for receipt in reference["receipts"]:
        destination = workspace / receipt["destination"]
        if destination.exists():
            raise GateError("Refuse to replace a design receipt")
        copy_regular(local_file(reference_path.parent, receipt["artifact"]), destination)
        check_hash(destination, receipt["sha256"])
    assert_fresh_caches(workspace)
    spec_file = workspace / "native-release-spec.json"
    write_json(spec_file, {"source_root": str(source), "workspace": str(workspace),
                           "reference_manifest": str(reference_path),
                           "reference_manifest_sha256": sha256(reference_path), "source_identity": identity})
    log = workspace / "native-release.log"
    environment = worker_environment(workspace)
    with log.open("w") as stream:
        process = subprocess.run([str(interpreter), str(Path(__file__).resolve()), "--worker-spec", str(spec_file)],
                                 cwd=workspace, env=environment, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if process.returncode:
        write_json(workspace / "native-release-failure.json", failure_report(plan, workspace, process.returncode))
        raise GateError("Native release verification failed; inspect " + str(log))
    summary = workspace / "native-release-report/summary.json"
    if not summary.is_file() or read_json(summary).get("passed") is not True:
        raise GateError("Native worker did not produce a passing report")
    print(json.dumps({"passed": True, "report": str(summary), "log": str(log)}))
    return 0


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--worker-spec":
            run_worker(sys.argv[2])
        else:
            raise SystemExit(main())
    except (GateError, OSError, KeyError, TypeError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print("Native release verification failed: " + str(error), file=sys.stderr)
        raise SystemExit(1)
