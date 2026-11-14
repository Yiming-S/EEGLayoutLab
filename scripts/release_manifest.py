#!/usr/bin/env python3
"""Describe current source, pinned data and the selected scientific runtime.

No build, package installation or scientific computation is performed. The
default prints a plan; --execute writes a new manifest under artifacts/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from data_bundle import load_manifest, safe_path, sha256_file, verify_files
from prepare_verification_workspace import current_sources, output_path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "eeglayoutlab-release/1"
SCIENTIFIC_SCRIPTS = frozenset("scripts/" + name for name in (
    "run_local_radius_compute.py", "design_evaluation.py", "electrode_editor.py",
    "run_source_reception.py", "run_source_reception_v2.py", "reception_forward_provider.py",
    "source_reception.py", "source_reception_v2.py", "inspect_ernie_cortical_forward.py",
    "export_history_coordinates.py", "run_area_budget_study.py", "inspect_reception_runtime.py",
    "inspect_reception_runtime_snapshot.py", "runtime_identity_watch.py"))


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def observed_runtime(root, python):
    """Use the same native digest as source-reception cache identities, without FEM."""
    if python is None:
        return None
    located = shutil.which(str(python))
    if not located:
        raise ValueError("Selected Python executable does not exist")
    invoked = Path(located).absolute()
    executable = invoked.resolve(strict=True)
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        environment[name] = "1"
    # Keep the invoked interpreter path: it participates in the native digest.
    command = [str(invoked), "-B", str(safe_path(root, "scripts/inspect_reception_runtime.py"))]
    result = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, timeout=120, check=True)
    value = json.loads(result.stdout)
    if value.get("schema") != "reception-runtime-digest/1" or not valid_sha(value.get("sha256")):
        raise ValueError("Native runtime inspector returned an invalid identity")
    version = subprocess.check_output([str(invoked), "--version"], text=True, timeout=10).strip()
    return {"python": str(invoked), "resolved_python": str(executable), "python_version": version,
            "executable_sha256": sha256_file(executable), "native_identity": value}


def valid_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def release_manifest(root, *, repository_root=None, python=None, verify_data=False):
    root = Path(root).expanduser().resolve(strict=True)
    scientific_root = Path(repository_root or root).expanduser().resolve(strict=True)
    sources = current_sources(root)
    raw, data, files = load_manifest(scientific_root)
    if hashlib.sha256(raw).hexdigest() != sha256_file(safe_path(root, "data/manifest.json")):
        raise ValueError("Host and scientific checkout use different frozen data manifests")
    if verify_data:
        verify_files(scientific_root, files)
    scientific_sources = [row for row in sources if row["path"].startswith("src/") or
                          (row["path"].startswith("configs/") and not row["path"].startswith("configs/deploy/")) or
                          row["path"] in SCIENTIFIC_SCRIPTS]
    verify_files(scientific_root, {row["path"]: row for row in scientific_sources})
    runtime_path = safe_path(root, "configs/runtime/manifest.json")
    runtime = json.loads(runtime_path.read_bytes())
    if runtime.get("schema") != "eeglayoutlab-runtime-lock/1":
        raise ValueError("Unsupported runtime lock schema")
    package = json.loads(safe_path(root, "webapp/package.json").read_bytes())
    # A new repository can have no commit yet; current file hashes remain authoritative.
    revision = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
                              text=True, capture_output=True)
    status = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "-z"])
    observed = observed_runtime(scientific_root, python)
    if current_sources(root) != sources:
        raise ValueError("Source inventory changed while creating the release manifest")
    verify_files(scientific_root, {row["path"]: row for row in scientific_sources})
    return {
        "schema": SCHEMA, "application_version": package["version"],
        "source_root": str(root), "repository_root": str(scientific_root),
        "source": {"revision": revision.stdout.strip() if revision.returncode == 0 else None,
                   "dirty": bool(status), "inventory_sha256": digest(sources), "files": sources},
        "scientific_source": {"inventory_sha256": digest(scientific_sources), "files": scientific_sources},
        "data": {"manifest_sha256": hashlib.sha256(raw).hexdigest(), "bundle_id": data.get("bundle_id"),
                 "file_count": len(files), "size_bytes": sum(row["size_bytes"] for row in files.values()),
                 "payload_verified": verify_data},
        "runtime": {"lock_sha256": sha256_file(runtime_path), "locked_platform": runtime.get("platform"),
                    "locked_python": runtime.get("python"), "observed": observed},
        "scope": "File and environment identities; not numerical validation or platform support certification",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--source-root", type=Path, help="Git host checkout; defaults to --repository-root")
    parser.add_argument("--python", help="Observe this installed native Python using the existing runtime inspector")
    parser.add_argument("--verify-data", action="store_true", help="Verify every frozen payload byte against the pinned manifest")
    parser.add_argument("--output", type=Path, help="New manifest path beneath repository artifacts/")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        root = (args.source_root or args.repository_root).expanduser().resolve(strict=True)
        destination = output_path(root, args.output) if args.output else None
        if args.execute and destination is None:
            raise ValueError("--execute requires --output")
        report = release_manifest(root, repository_root=args.repository_root, python=args.python, verify_data=args.verify_data)
        if args.execute:
            destination.parent.mkdir(parents=True, exist_ok=True)
            output_path(root, destination)
            with destination.open("xb") as stream:
                os.chmod(destination, 0o600)
                stream.write(encoded(report)); stream.flush(); os.fsync(stream.fileno())
        print(json.dumps({"mode": "execute" if args.execute else "plan", "manifest_sha256": digest(report),
                          "output": str(destination) if destination else None, "manifest": report}, indent=2))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Release manifest failed: {error}\n")


if __name__ == "__main__":
    main()
