#!/usr/bin/env python3
"""Copy and relocate the frozen macOS runtime without modifying its source.

Run on the build Mac. The destination must not exist. No Conda installation,
activation, conda-unpack or path editing is needed on the receiving Mac.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile

MAGIC = {bytes.fromhex(h) for h in ("cffaedfe", "feedfacf", "cefaedfe", "feedface", "cafebabe", "bebafeca", "cafebabf", "bfbafeca")}
LOAD_COMMANDS = {"LC_LOAD_DYLIB", "LC_LOAD_WEAK_DYLIB", "LC_REEXPORT_DYLIB", "LC_LOAD_UPWARD_DYLIB", "LC_ID_DYLIB", "LC_RPATH"}
# Bundled by upstream PyQt, but unrelated to this WebKit/EEG application. Exclude
# only this unusable optional binary from staging, retaining all license files.
OPTIONAL_EXTERNAL = {
    ("lib/python3.11/site-packages/PyQt5/Qt5/plugins/sqldrivers/libqsqlpsql.dylib",
     "/opt/homebrew/opt/postgresql@15/lib/libpq.5.dylib"):
        "Unused upstream Qt PostgreSQL plugin; PostgreSQL support is not part of EEGLayoutLab."
}


def run(command, **kwargs):
    result = subprocess.run(command, text=True, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {command!r}\n{result.stdout[-12000:]}\n{result.stderr[-12000:]}")
    return result


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def inventory(root):
    """Hash bytes, permissions, and symlink targets, excluding access times."""
    paths = sorted(root.rglob("*"))
    def entry(path):
        rel = str(path.relative_to(root))
        mode = stat.S_IMODE(path.lstat().st_mode)
        if path.is_symlink():
            return rel, {"type": "symlink", "target": os.readlink(path), "mode": mode}
        if path.is_file():
            return rel, {"type": "file", "bytes": path.stat().st_size, "sha256": digest(path), "mode": mode}
        if path.is_dir():
            return rel, {"type": "directory", "mode": mode}
        raise ValueError("Unsupported special file: " + str(path))
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(entry, paths))


def inventory_digest(records):
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def safe_locations(source, destination, project_root):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    project_root = Path(project_root).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination must not exist; existing files are never overwritten")
    if source == destination.resolve() or source in destination.resolve().parents or destination.resolve() in source.parents:
        raise ValueError("Source and destination must be disjoint directories")
    if source == project_root.resolve() or source in project_root.resolve().parents:
        raise ValueError("The staged project cannot be inside the source runtime")
    if destination.resolve() != (project_root / ".runtime/simnibs-4.6.0").resolve():
        raise ValueError("Destination must be PROJECT_ROOT/.runtime/simnibs-4.6.0")
    if not (source / "bin/python3.11").is_file() or not (source / "conda-meta").is_dir():
        raise ValueError("Source must be the complete frozen CPython 3.11 Conda runtime")
    return source, destination, project_root


def loader_path(origin, target):
    relative = os.path.relpath(target, origin.parent)
    return "@loader_path" if relative == "." else "@loader_path/" + relative


def parse_load_commands(output):
    result = []
    command = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("cmd "):
            command = line.split()[1]
        elif command in LOAD_COMMANDS and (line.startswith("name ") or line.startswith("path ")):
            result.append((command, line.split(" ", 1)[1].split(" (offset ", 1)[0]))
            command = None
    return result


def is_system_path(value):
    return value == "/usr/lib" or value.startswith(("/usr/lib/", "/System/Library/"))


def inspect_macho(path):
    return parse_load_commands(run(["/usr/bin/otool", "-l", str(path)]).stdout)


def relocate_macho(path, source, destination):
    commands = list(dict.fromkeys(inspect_macho(path)))
    relative = str(path.relative_to(destination))
    options, notes = [], []
    rpaths = [value for kind, value in commands if kind == "LC_RPATH"]
    root_lib = loader_path(path, destination / "lib")
    replacement_added = root_lib in rpaths
    for kind, value in commands:
        if not value.startswith("/") or is_system_path(value):
            continue
        if kind == "LC_RPATH":
            if not replacement_added:
                options += ["-rpath", value, root_lib]
                replacement_added = True
                notes.append({"command": kind, "old": value, "new": root_lib})
            else:
                options += ["-delete_rpath", value]
                notes.append({"command": kind, "old": value, "removed": True})
        elif kind == "LC_ID_DYLIB":
            replacement = "@rpath/" + str(path.relative_to(destination / "lib")) if path.is_relative_to(destination / "lib") else "@rpath/" + path.name
            options += ["-id", replacement]
            notes.append({"command": kind, "old": value, "new": replacement})
        else:
            old = Path(value)
            target = destination / old.relative_to(source) if old.is_relative_to(source) else None
            if target is None:
                candidates = [path.parent / old.name, destination / "lib" / old.name]
                target = next((p for p in candidates if p.is_file()), None)
            if target is None or not target.is_file():
                raise ValueError(f"Unbundled native dependency: {relative}: {value}")
            replacement = loader_path(path, target)
            options += ["-change", value, replacement]
            notes.append({"command": kind, "old": value, "new": replacement})
    if options:
        run(["/usr/bin/install_name_tool", *options, str(path)])
        run(["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", str(path)])
        run(["/usr/bin/codesign", "--verify", "--strict", str(path)])
    return {"file": relative, "changes": notes}


def relocate_text(destination, source, project_root):
    changes = []
    site = destination / "lib/python3.11/site-packages"
    project_source = source.parent.parent / "src"
    for path in sorted(site.glob("*.pth")):
        original = path.read_text()
        lines = []
        for line in original.splitlines():
            if line.startswith("/"):
                old = Path(line)
                if old == project_source or (path.name.startswith("__editable__.compact_eeg-") and old.name == "src"):
                    target = project_root / "src"
                elif old.is_relative_to(source):
                    target = destination / old.relative_to(source)
                else:
                    raise ValueError("External .pth entry is not portable: " + str(path) + ": " + line)
                line = os.path.relpath(target, site)
            lines.append(line)
        updated = "\n".join(lines) + "\n"
        if updated != original:
            path.write_text(updated)
            changes.append({"file": str(path.relative_to(destination)), "kind": "relative_site_path"})
    for path in sorted((destination / "bin").iterdir()):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as handle:
            first_line = handle.readline(4096)
        if not first_line.startswith(b"#!") or b"python" not in first_line:
            continue
        interpreter = first_line[2:].strip().decode()
        if not interpreter.startswith(str(source) + "/bin/python"):
            continue
        original = path.read_bytes()
        trampoline = b'#!/bin/sh\n\'\'\'exec\' "$(dirname "$0")/python3.11" "$0" "$@"\n\' \'\'\'\n'
        path.write_bytes(trampoline + original[len(first_line):])
        changes.append({"file": str(path.relative_to(destination)), "kind": "relative_python_trampoline"})
    return changes


def normalize_symlinks(source, destination):
    changes = []
    for path in sorted(destination.rglob("*")):
        if not path.is_symlink():
            continue
        target = os.readlink(path)
        if Path(target).is_absolute():
            original = Path(target)
            if not original.is_relative_to(source):
                raise ValueError("External runtime symlink: " + str(path) + " -> " + target)
            new = os.path.relpath(destination / original.relative_to(source), path.parent)
            path.unlink()
            path.symlink_to(new)
            changes.append({"file": str(path.relative_to(destination)), "old": target, "new": new})
        if not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError("Runtime symlink escapes its prefix: " + str(path))
        if not path.exists():
            raise ValueError("Runtime symlink is dangling: " + str(path))
    return changes


def verify_runtime(destination, project_root, probe_path):
    """No developer PATH/PYTHONPATH, no user-site or dyld fallback variables."""
    with tempfile.TemporaryDirectory(prefix="eeglayoutlab-runtime-probe-") as temporary:
        env = {"PATH": "/usr/bin:/bin", "HOME": temporary, "TMPDIR": temporary,
               "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
               "MPLCONFIGDIR": temporary, "XDG_CACHE_HOME": temporary,
               "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
               "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1"}
        result = run([str(destination / "bin/python"), "-I", "-B", str(probe_path),
                      "--prefix", str(destination), "--project-root", str(project_root)],
                     cwd=temporary, env=env, timeout=180)
        verification = json.loads(result.stdout)
        pip = run([str(destination / "bin/pip"), "check"], cwd=temporary, env=env, timeout=60)
        verification["relocated_console_script"] = pip.stdout.strip()
        return verification


def stage(source, destination, project_root, verify=True):
    source, destination, project_root = safe_locations(source, destination, project_root)
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("Build the native runtime on an Apple Silicon Mac")
    print("Hashing the read-only source runtime", file=sys.stderr, flush=True)
    before = inventory(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    print("Copying runtime to a new staging directory", file=sys.stderr, flush=True)
    shutil.copytree(source, destination, symlinks=True, copy_function=shutil.copy2)
    copied = inventory(destination)
    if before != copied:
        raise ValueError("Initial source and destination inventories differ")
    symlinks = normalize_symlinks(source, destination)
    text_changes = relocate_text(destination, source, project_root)
    exclusions = []
    for (relative, dependency), reason in OPTIONAL_EXTERNAL.items():
        path = destination / relative
        if path.is_file():
            if ("LC_LOAD_DYLIB", dependency) not in inspect_macho(path):
                raise ValueError("The explicitly excluded upstream plugin changed; review its dependency first")
            exclusions.append({"file": relative, "source_sha256": before[relative]["sha256"], "unbundled_dependency": dependency, "reason": reason})
            path.unlink()
    files = []
    for relative, record in before.items():
        if record["type"] != "file":
            continue
        path = destination / relative
        if not path.exists():
            continue
        with path.open("rb") as handle:
            if handle.read(4) in MAGIC:
                files.append(path)
    print(f"Auditing and relocating {len(files)} native binaries", file=sys.stderr, flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda p: relocate_macho(p, source, destination), files))
    modifications = [record for record in outcomes if record["changes"]]
    # Re-read actual load commands after patching, and reject every external
    # absolute path except system libraries.
    with ThreadPoolExecutor(max_workers=8) as pool:
        inspected = list(pool.map(inspect_macho, files))
    for path, commands in zip(files, inspected):
        for kind, value in commands:
            if value.startswith("/") and not is_system_path(value):
                raise ValueError("Nonportable Mach-O command remains: " + str(path) + ": " + value)
    print("Verifying source preservation and staged metadata", file=sys.stderr, flush=True)
    final_source = inventory(source)
    if before != final_source:
        raise ValueError("Source runtime changed while staging; do not publish this output")
    after = inventory(destination)
    protected = [p for p in before if p.startswith("conda-meta/") or any(word in Path(p).name.lower() for word in ("license", "copyright", "copying", "notice"))]
    if any(before[p] != after[p] for p in protected):
        raise ValueError("Staging changed provenance metadata or license material")
    report = {"schema": "eeglayoutlab-portable-runtime/1", "status": "staged",
              "source": str(source), "destination": str(destination),
              "architecture": "arm64", "python": "3.11", "minimum_macos_major": 14,
              "source_inventory_sha256": inventory_digest(before),
              "source_unchanged": True, "staged_inventory_sha256": inventory_digest(after),
              "file_count": sum(x["type"] == "file" for x in before.values()),
              "source_file_bytes": sum(x.get("bytes", 0) for x in before.values()),
              "macho_files": len(files), "macho_changes": modifications,
              "text_changes": text_changes, "symlink_changes": symlinks,
              "preserved_license_and_conda_entries": len(protected),
              "excluded_optional_plugins": exclusions,
              "strategy": "Build-time relative .pth, console trampolines and Mach-O relocation; no user-side prefix rewrite."}
    report_path = destination / "portable-runtime-audit.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if verify:
        print("Probing isolated native imports, MUMPS, CGAL and loaded library paths", file=sys.stderr, flush=True)
        try:
            report["verification"] = verify_runtime(destination, project_root, Path(__file__).with_name("verify_runtime.py"))
            report["status"] = "verified_on_build_mac_after_relocation"
        except Exception as exc:
            report["status"] = "verification_failed"
            report["verification_error"] = str(exc)
            report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            raise
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path, help="Staged root containing src/ and .runtime/")
    parser.add_argument("--skip-verify", action="store_true", help="Only for builders that perform the probe after copying project sources")
    args = parser.parse_args()
    report = stage(args.source, args.destination, args.project_root, not args.skip_verify)
    print(json.dumps({key: report[key] for key in ("status", "destination", "source_unchanged", "macho_files", "source_file_bytes")}, indent=2))


if __name__ == "__main__":
    main()
