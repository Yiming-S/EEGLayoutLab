#!/usr/bin/env python3
"""Check a local runtime without changing historical data or cache manifests."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def inspect(prefix, native=False):
    manifest = json.loads((ROOT / "configs/runtime/manifest.json").read_text())
    prefix = prefix.resolve()
    errors = []
    if Path(sys.prefix).resolve() != prefix:
        errors.append("Interpreter prefix differs from --prefix; run this script using the new runtime's bin/python")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        errors.append("Native runtime requires macOS arm64")
    if platform.python_version() != manifest["python"]:
        errors.append("Python version differs from the frozen runtime: " + platform.python_version())
    observed_conda = {}
    for path in (prefix / "conda-meta").glob("*.json"):
        record = json.loads(path.read_text())
        observed_conda[record["name"]] = record
    for expected in manifest["conda_packages"]:
        actual = observed_conda.get(expected["name"], {})
        if any(actual.get(key) != expected[key] for key in ("version", "build", "sha256")):
            errors.append("Conda package missing or changed: " + expected["name"])
    if not any((prefix / "lib").glob("*mumps*.dylib")):
        errors.append("Auditable MUMPS dynamic library is missing")
    for expected in manifest["pip_distributions"]:
        try:
            actual = importlib.metadata.version(expected["name"])
        except importlib.metadata.PackageNotFoundError:
            actual = None
        if actual != expected["version"]:
            errors.append("Python distribution missing or changed: " + expected["name"])
    modules = {}
    for name in ("numpy", "scipy", "matplotlib", "threadpoolctl", "pytest"):
        try:
            module = importlib.import_module(name)
            location = Path(module.__file__).resolve()
            modules[name] = str(location)
            if not location.is_relative_to(prefix):
                errors.append("Package resolved outside this runtime: " + name)
        except Exception as exc:
            errors.append("Import failed for " + name + ": " + str(exc))
    check = subprocess.run([sys.executable, "-m", "pip", "check"], text=True, capture_output=True)
    if check.returncode:
        errors.append("pip check failed: " + check.stdout.strip() + check.stderr.strip())
    report = {"schema": "eeglayoutlab-environment-check/1", "status": "failed" if errors else "passed",
        "repository_root": str(ROOT), "prefix": str(prefix), "python": platform.python_version(),
        "conda_package_count": len(observed_conda), "imports": modules, "pip_check": check.stdout.strip(),
        "native_check_requested": native, "errors": errors,
        "scope": "Runtime installation checks; not FEM numerical accuracy or scientific-result validation"}
    if native and not errors:
        try:
            for name in ("simnibs", "mumps", "petsc4py", "cortech", "fmm3dpy"):
                module = importlib.import_module(name)
                if not Path(module.__file__).resolve().is_relative_to(prefix):
                    raise ValueError("Native import is outside this runtime: " + name)
            from compact_eeg.workflows.reception_forward_provider import _native_runtime_identity
            identity = _native_runtime_identity()
            report["native_audit"] = {"schema": identity["schema"], "packages": list(identity["packages"]),
                "conda_records": len(identity["conda_records"]), "native_libraries": len(identity["native_libraries"])}
        except Exception as exc:
            report["errors"].append("Native runtime audit failed: " + str(exc))
            report["status"] = "failed"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=ROOT / ".runtime/simnibs-4.6.0")
    parser.add_argument("--native", action="store_true", help="Import SimNIBS/MPI and perform the production runtime audit")
    args = parser.parse_args()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    report = inspect(args.prefix, native=args.native)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
