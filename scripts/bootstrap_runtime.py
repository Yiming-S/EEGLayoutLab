#!/usr/bin/env python3
"""Prepare a local, auditable runtime from this platform's lock; default is a read-only plan.

macOS arm64 installs the SimNIBS 4.6.0 runtime. Linux x86_64 installs a runtime without
SimNIBS that computes new coordinates from published scalp-node tables.
Use --execute to install and --resume after an interrupted managed installation.
This does not change shell startup files or run SimNIBS system post-install hooks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ROOT / "configs/runtime"
# One lock per (system, machine). The macOS entry keeps its original file names and prefix.
PLATFORMS = {
    ("Darwin", "arm64"): {"subdir": "osx-arm64", "manifest": "manifest.json",
        "conda": "conda-osx-arm64.explicit.txt", "pip": "pip-macos-arm64.txt",
        "prefix": "simnibs-4.6.0", "pip_options": [], "verify_options": ["--native"], "needs_git": True},
    ("Linux", "x86_64"): {"subdir": "linux-64", "manifest": "manifest-linux-64.json",
        "conda": "conda-linux-64.explicit.txt", "pip": "pip-linux-64.txt",
        "prefix": "compute-linux-64", "pip_options": ["--only-binary=:all:"], "verify_options": ["--native"], "needs_git": False},
}


def platform_lock(system=None, machine=None):
    system, machine = system or platform.system(), machine or platform.machine()
    lock = PLATFORMS.get((system, machine))
    if lock is None:
        if system == "Darwin":
            raise ValueError("The frozen runtime requires native macOS arm64 (no Rosetta)")
        raise ValueError(f"No runtime lock for {system} {machine}; locks exist for macOS arm64 and Linux x86_64")
    return lock


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_prefix(value):
    requested = Path(value).expanduser().absolute()
    runtime = ROOT / ".runtime"
    if runtime.is_symlink() or requested.is_symlink():
        raise ValueError("The runtime directory and prefix must not be symbolic links")
    resolved = requested.resolve()
    if not resolved.is_relative_to(runtime.resolve()) or resolved == runtime.resolve():
        raise ValueError("--prefix must name a child directory of this repository's .runtime")
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Create and install the planned environment")
    parser.add_argument("--resume", action="store_true", help="Resume only this script's interrupted installation")
    parser.add_argument("--prefix", type=Path, help="Default: .runtime/simnibs-4.6.0 on macOS, .runtime/compute-linux-64 on Linux")
    parser.add_argument("--conda", help="Existing conda, mamba or micromamba executable")
    parser.add_argument("--asset-dir", type=Path, help="Read-only folder containing already downloaded official wheels")
    args = parser.parse_args()
    lock = platform_lock()
    manifest = json.loads((LOCKS / lock["manifest"]).read_text())
    prefix = safe_prefix(args.prefix or ROOT / ".runtime" / lock["prefix"])
    if "minimum_macos_major" in manifest and int(platform.mac_ver()[0].split(".")[0]) < manifest["minimum_macos_major"]:
        raise ValueError("The official native dependency wheels require macOS 14 or later")
    manager = args.conda or next((shutil.which(name) for name in ("conda", "mamba", "micromamba") if shutil.which(name)), None)
    if not manager or not Path(manager).is_file():
        raise ValueError("Install an arm64 Conda distribution first, or provide --conda /path/to/conda" if lock["subdir"] == "osx-arm64"
                         else "Install Miniforge or micromamba first, or provide --conda /path/to/conda")
    if not os.access(manager, os.X_OK):
        raise ValueError("The selected Conda manager is not executable")
    manager_version = subprocess.run([manager, "--version"], text=True, capture_output=True, check=True, timeout=30).stdout.strip()
    if lock["needs_git"] and not shutil.which("git"):
        raise ValueError("Git and Apple command-line build tools are required by the pinned source dependencies")
    official = manifest.get("official_environment")
    if official and sha256(LOCKS / official["filename"]) != official["sha256"]:
        raise ValueError("The bundled upstream environment file failed its SHA-256 check")
    lock_hashes = {name: sha256(LOCKS / name) for name in (lock["manifest"], lock["conda"], lock["pip"])}
    marker = prefix.parent / (prefix.name + ".bootstrap.json")
    state = {"prefix": str(prefix), "locks": lock_hashes, "completed": []}
    if prefix.exists():
        if not args.resume or not marker.is_file():
            raise ValueError("Prefix already exists; use check_environment.py, or --resume for an interrupted managed install")
        previous = json.loads(marker.read_text())
        if previous.get("prefix") != str(prefix) or previous.get("locks") != lock_hashes:
            raise ValueError("Existing prefix was not created with these locks; no files were changed")
        state = previous
    elif args.resume:
        raise ValueError("No existing prefix to resume")
    manager = str(Path(manager).resolve())
    cached = []
    if args.asset_dir:
        for asset in manifest["artifacts"]:
            path = args.asset_dir.expanduser().resolve() / asset["filename"]
            if path.is_file():
                if sha256(path) != asset["sha256"]:
                    raise ValueError("Provided wheel checksum mismatch: " + asset["filename"])
                cached.append((asset, path))
    python = prefix / "bin/python"
    commands = [
        ("conda", [manager, "create", "--yes", "--quiet", "--copy", "--override-channels", "--channel", "conda-forge", "--prefix", str(prefix), "--file", str(LOCKS / lock["conda"])]),
        ("pip", [str(python), "-m", "pip", "install", "--no-deps", *lock["pip_options"], "--requirement", str(LOCKS / lock["pip"])]),
        ("project", [str(python), "-m", "pip", "install", "--no-deps", "--no-build-isolation", "--editable", str(ROOT) + "[dev]"]),
        ("verify", [str(python), str(ROOT / "scripts/check_environment.py"), "--prefix", str(prefix), *lock["verify_options"]]),
    ]
    print(json.dumps({"mode": "execute" if args.execute else "plan", "prefix": str(prefix),
        "environment_manager": manager_version,
        "conda_packages": manifest["conda_package_count"], "reusable_verified_wheels": [a["filename"] for a, _ in cached],
        "commands": [shlex.join(command) for _, command in commands],
        "notes": manifest["limitations"]}, indent=2), flush=True)
    if not args.execute:
        return
    cache = ROOT / ".runtime/cache"
    (cache / "wheels").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)
    env.update({"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "CONDA_ENVS_PATH": str(ROOT / ".runtime"), "CONDA_PKGS_DIRS": str(cache / "conda"),
        "CONDA_SUBDIR": lock["subdir"], "CONDA_AUTO_ACTIVATE_BASE": "false", "CONDARC": str(LOCKS / "condarc.yml"),
        "PIP_CACHE_DIR": str(cache / "pip"), "MPLCONFIGDIR": str(cache / "matplotlib"),
        "XDG_CACHE_HOME": str(cache / "xdg"), "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
    requirements = (LOCKS / lock["pip"]).read_text()
    for asset, source in cached:
        target = cache / "wheels" / asset["filename"]
        if target.exists() and sha256(target) != asset["sha256"]:
            raise ValueError("Project wheel cache checksum mismatch: " + asset["filename"])
        if not target.exists():
            shutil.copyfile(source, target)
        requirements = requirements.replace(asset["url"], target.as_uri())
    resolved = cache / "pip-install.txt"
    resolved.write_text(requirements)
    commands[1][1][-1] = str(resolved)
    marker.write_text(json.dumps(state, indent=2) + "\n")
    for stage, command in commands:
        if stage in state["completed"]:
            continue
        print("Running: " + shlex.join(command), flush=True)
        subprocess.run(command, cwd=ROOT, env=env, check=True)
        state["completed"].append(stage)
        marker.write_text(json.dumps(state, indent=2) + "\n")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("Runtime preparation failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
