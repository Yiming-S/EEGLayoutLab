#!/usr/bin/env python3
"""Prepare an isolated QA checkout from current source and the frozen data allowlist.

Dry run is the default. No downloads, Git writes, historical-cache migration or
native-runtime relocation is performed. node_modules sharing is QA-only.
"""
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

from data_bundle import load_manifest, relative_path, safe_path, sha256_file, verify_files

ROOT = Path(__file__).resolve().parents[1]
REPORT = "verification-workspace.json"
RUNTIME = ".runtime/simnibs-4.6.0"
EXCLUDED_ROOTS = {".git", ".runtime", ".venv", "results", "releases", "artifacts", "desktop",
                  ".aws", ".codex", ".agents", ".openai", ".claude", "OLD"}
EXCLUDED_PARTS = {"node_modules", "dist", "__pycache__", ".pytest_cache", ".next", ".vinext"}


class WorkspaceError(ValueError):
    """The requested source or destination is unsafe or inconsistent."""


def inside(path, parent):
    return path == parent or path.is_relative_to(parent)


def output_path(source, output):
    requested = Path(output).expanduser().absolute()
    destination = requested.resolve()
    artifacts = source / "artifacts"
    if not destination.is_relative_to(artifacts) or destination == artifacts:
        raise WorkspaceError("Choose a new named directory inside the project's artifacts directory")
    if requested != destination:
        raise WorkspaceError("Output path must not contain symlinks or parent traversal")
    current = source
    for part in destination.relative_to(source).parts:
        current /= part
        if current.is_symlink():
            raise WorkspaceError("Output ancestors must not be symlinks")
        if current.exists() and not current.is_dir():
            raise WorkspaceError("Output ancestor is not a directory")
    if destination.exists():
        raise WorkspaceError("Output already exists; choose a new directory")
    return destination


def current_sources(source):
    root = subprocess.check_output(["git", "-C", str(source), "rev-parse", "--show-toplevel"], text=True).strip()
    if Path(root).resolve() != source:
        raise WorkspaceError("Source must be the Git repository root")
    names = subprocess.check_output([
        "git", "-C", str(source), "ls-files", "--cached", "--others", "--exclude-standard", "-z",
    ]).decode().split("\0")
    records = []
    for name in sorted(set(filter(None, names))):
        path = relative_path(name)
        if path.parts[0] in EXCLUDED_ROOTS or EXCLUDED_PARTS.intersection(path.parts):
            continue
        if path.parts[0] == "data" and name not in {"data/README.md", "data/manifest.json", "data/SOURCES.md"}:
            continue
        filename = path.name.lower()
        private_env = (filename.startswith('.env') or filename.endswith('.env') or '.env.' in filename) and not filename.endswith('.env.example')
        if private_env or path.suffix in {'.pem', '.key', '.p12', '.pfx', '.pyc'}:
            continue
        original = source / name
        if not original.exists() and not original.is_symlink():
            continue  # Preserve working-tree deletions instead of resurrecting index bytes.
        original = safe_path(source, name)
        records.append({"path": name, "size_bytes": original.stat().st_size, "sha256": sha256_file(original)})
    if not any(row["path"] == "data/manifest.json" for row in records):
        raise WorkspaceError("Source inventory is missing data/manifest.json")
    if any(row["path"] == REPORT for row in records):
        raise WorkspaceError("Source conflicts with verification manifest filename")
    return records


def tree_inventory(root):
    """List entries without following directory symlinks; reject escaping links/devices."""
    entries = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in sorted(dirs + files):
            path = Path(directory) / name
            mode = path.lstat().st_mode
            relative = str(path.relative_to(root))
            if stat.S_ISLNK(mode):
                try:
                    target = path.resolve(strict=True)
                except (FileNotFoundError, RuntimeError) as error:
                    raise WorkspaceError(f"Broken or circular runtime link: {relative}") from error
                if not inside(target, root):
                    raise WorkspaceError(f"Runtime link escapes its environment: {relative}")
                # Internal absolute symlinks become equivalent relative links in the copy.
                link = os.path.relpath(target, path.parent) if Path(os.readlink(path)).is_absolute() else os.readlink(path)
                entries.append({"path": relative, "kind": "symlink", "target": link})
            elif stat.S_ISDIR(mode):
                entries.append({"path": relative, "kind": "directory"})
            elif stat.S_ISREG(mode):
                entries.append({"path": relative, "kind": "file", "size_bytes": path.stat().st_size})
            else:
                raise WorkspaceError(f"Unsupported runtime entry: {relative}")
    return sorted(entries, key=lambda row: (len(Path(row["path"]).parts), row["path"]))


def runtime_source(path, source, destination):
    if path is None:
        return None, []
    environment = Path(path).expanduser().resolve(strict=True)
    if not environment.is_dir() or not (environment / "conda-meta").is_dir() or not (environment / "bin/python").is_file():
        raise WorkspaceError("Runtime source must be an existing Conda environment with bin/python")
    if inside(source, environment) or inside(destination, environment) or inside(environment, destination):
        raise WorkspaceError("Runtime source overlaps the source or output directory")
    if any(inside(environment, source / name) for name in ("results", "releases", "artifacts")):
        raise WorkspaceError("Runtime source cannot be a results, release or verification directory")
    return environment, tree_inventory(environment)


def copy_regular(source, destination):
    """Use copy-on-write when supported; never create a mutable hard link."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    cloned = False
    if sys.platform == "darwin":
        clone = getattr(ctypes.CDLL(None, use_errno=True), "clonefile", None)
        if clone is not None:
            clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
            clone.restype = ctypes.c_int
            result = clone(os.fsencode(source), os.fsencode(destination), 0)
            if result == 0:
                cloned = True
            elif ctypes.get_errno() not in {errno.EXDEV, errno.ENOTSUP, errno.EINVAL, errno.EPERM}:
                raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()), str(destination))
    if not cloned:
        shutil.copyfile(source, destination)
    shutil.copystat(source, destination, follow_symlinks=False)
    if source.stat().st_ino == destination.stat().st_ino and source.stat().st_dev == destination.stat().st_dev:
        raise WorkspaceError("A copied file unexpectedly shares the source inode")


def copy_verified(source, destination, record):
    original = safe_path(source, record["path"])
    if original.stat().st_size != record["size_bytes"] or sha256_file(original) != record["sha256"]:
        raise WorkspaceError(f"Source changed after planning: {record['path']}")
    target = destination / record["path"]
    copy_regular(original, target)
    if sha256_file(target) != record["sha256"]:
        raise WorkspaceError(f"Copied bytes differ: {record['path']}")


def copy_tree(source, destination, entries):
    destination.mkdir(parents=True)
    for entry in entries:
        original = source / entry["path"]
        target = destination / entry["path"]
        if entry["kind"] == "directory":
            target.mkdir(parents=True, exist_ok=True)
        elif entry["kind"] == "symlink":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(entry["target"])
        else:
            original = safe_path(source, entry["path"])
            before = sha256_file(original)
            copy_regular(original, target)
            if sha256_file(target) != before or sha256_file(original) != before:
                raise WorkspaceError(f"Runtime or build file changed during copy: {entry['path']}")
    # Validate links after all targets exist in the copy.
    tree_inventory(destination)


def prepare(source_root, output, *, runtime=None, node_modules=False, dist=False, execute=False):
    source = Path(source_root).expanduser().resolve(strict=True)
    destination = output_path(source, output)
    raw, manifest, payload = load_manifest(source)
    verify_files(source, payload)
    sources = current_sources(source)
    environment, runtime_entries = runtime_source(runtime, source, destination)
    modules = source / "webapp/node_modules"
    if node_modules and (not modules.is_dir() or modules.is_symlink()):
        raise WorkspaceError("QA node_modules must be an existing directory in the source checkout")
    build = source / "webapp/dist"
    if dist and (not build.is_dir() or build.is_symlink()):
        raise WorkspaceError("Build copy requires an existing webapp/dist directory")
    build_entries = tree_inventory(build) if dist else []
    report = {
        "schema": "eeglayoutlab-verification-workspace/1", "mode": "execute" if execute else "plan",
        "source_root": str(source), "workspace_root": str(destination),
        "sources": sources, "data": list(payload.values()),
        "data_manifest_sha256": hashlib.sha256(raw).hexdigest(), "bundle_id": manifest.get("bundle_id"),
        "runtime_source": str(environment) if environment else None,
        "runtime_copy": {"files": sum(e["kind"] == "file" for e in runtime_entries),
                         "symlinks": sum(e["kind"] == "symlink" for e in runtime_entries),
                         "embedded_prefixes_rewritten": False},
        "node_modules": {"mode": "qa_symlink" if node_modules else "absent", "source": str(modules) if node_modules else None},
        "dist_copied": dist,
        "purpose": "isolated verification; not a portable distribution; native runtime must be checked at the new path",
    }
    if not execute:
        return report
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".verification-", dir=destination.parent))
    try:
        combined = {row["path"]: row for row in sources}
        for name, row in payload.items():
            if name in combined and any(combined[name][key] != row[key] for key in ("size_bytes", "sha256")):
                raise WorkspaceError(f"Source and data inventory disagree: {name}")
            combined[name] = row
        for record in combined.values():
            copy_verified(source, staging, record)
        if environment:
            copy_tree(environment, staging / RUNTIME, runtime_entries)
        if node_modules:
            (staging / "webapp").mkdir(exist_ok=True)
            (staging / "webapp/node_modules").symlink_to(modules, target_is_directory=True)
        if dist:
            copy_tree(build, staging / "webapp/dist", build_entries)
        verify_files(staging, payload)
        (staging / REPORT).write_text(json.dumps(report, indent=2) + "\n")
        # Re-check late path changes before publishing this new workspace.
        output_path(source, destination)
        # mkdir is exclusive even if another process creates the destination
        # after the check. Never replace an existing empty user directory.
        destination.mkdir(mode=0o700)
        incomplete = destination / ".verification-incomplete"
        incomplete.write_text("Preparation in progress; use only after this marker is removed.\n")
        for child in sorted(staging.iterdir(), key=lambda p: (p.name == REPORT, p.name)):
            child.rename(destination / child.name)
        incomplete.unlink()
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True, help="New directory under this project's artifacts/")
    parser.add_argument("--runtime-source", type=Path, help="Existing Conda environment to copy; never downloaded")
    parser.add_argument("--link-node-modules", action="store_true", help="Share dependencies for local QA only")
    parser.add_argument("--copy-dist", action="store_true", help="Copy the existing build")
    parser.add_argument("--execute", action="store_true", help="Create the planned workspace")
    args = parser.parse_args()
    try:
        report = prepare(args.source_root, args.output, runtime=args.runtime_source,
                         node_modules=args.link_node_modules, dist=args.copy_dist, execute=args.execute)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Verification workspace preparation failed: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
