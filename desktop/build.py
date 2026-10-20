#!/usr/bin/env python3
"""Build a self-contained Apple Silicon test app from this checkout.

Builds only into a newly created directory. Original data and environments are
never mutated. Runtime relocation is a separate audited build operation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def run(args, **kwargs):
    print("BUILD:", " ".join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def runtime_tools():
    spec = importlib.util.spec_from_file_location("desktop_runtime_stage", DESKTOP / "runtime/stage_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_staged_runtime(source):
    audit_file = source / "portable-runtime-audit.json"
    audit = json.loads(audit_file.read_text())
    if (audit.get("schema") != "eeglayoutlab-portable-runtime/1"
            or audit.get("status") != "verified_on_build_mac_after_relocation"
            or audit.get("source_unchanged") is not True):
        raise ValueError("Staged runtime has not passed relocation verification")
    records = runtime_tools().inventory(source)
    records.pop("portable-runtime-audit.json", None)
    if runtime_tools().inventory_digest(records) != audit.get("staged_inventory_sha256"):
        raise ValueError("Staged runtime bytes differ from their relocation audit")
    return audit


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def stage_project(target):
    files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
    ).decode().split("\0")
    allowed = ("src/", "scripts/", "configs/", "webapp/", "docs/")
    explicit = {"README.md", "pyproject.toml", "THIRD_PARTY_NOTICES.md", "data/manifest.json", "data/SOURCES.md"}
    identities = {}
    for name in sorted(set(files)):
        if not name or not (name.startswith(allowed) or name in explicit):
            continue
        source = ROOT / name
        if not source.is_file() or source.is_symlink():
            raise ValueError("Expected a regular project source file: " + name)
        copy_file(source, target / name)
        identities[name] = digest(source)
    data = json.loads((ROOT / "data/manifest.json").read_text())
    for entry in data["files"]:
        source = ROOT / entry["path"]
        if source.stat().st_size != entry["size_bytes"] or digest(source) != entry["sha256"]:
            raise ValueError("Frozen data does not match its manifest: " + entry["path"])
        copy_file(source, target / entry["path"])
    modules = ROOT / "webapp/node_modules"
    for path in modules.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(modules.resolve()):
            raise ValueError("External node_modules symlink: " + str(path))
    shutil.copytree(modules, target / "webapp/node_modules", symlinks=True,
                    ignore=shutil.ignore_patterns(".cache", ".vite", "*.tsbuildinfo"))
    return identities, data


def stage_node(archive, config, resources, work):
    if archive.is_symlink() or digest(archive) != config["sha256"]:
        raise ValueError("Official Node archive SHA-256 mismatch")
    node_dir = resources / "node"
    prefix = "node-v" + config["version"] + "-darwin-arm64/"
    # Only two pinned, regular members are needed. Do not extract npm's symlinks
    # or any other archive path into the application bundle.
    with tarfile.open(archive, "r:gz") as bundle:
        for name in ("bin/node", "LICENSE"):
            item = bundle.getmember(prefix + name)
            if not item.isfile():
                raise ValueError("Node archive member is not a regular file: " + name)
            target = node_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = bundle.extractfile(item)
            if stream is None:
                raise ValueError("Missing Node member: " + name)
            with stream, target.open("xb") as destination:
                shutil.copyfileobj(stream, destination)
            target.chmod(0o755 if name == "bin/node" else 0o644)
    binary = node_dir / "bin/node"
    dependencies = subprocess.check_output(["otool", "-L", binary], text=True)
    for line in dependencies.splitlines()[1:]:
        dependency = line.strip().split(" (", 1)[0]
        if not dependency.startswith(("/usr/lib/", "/System/Library/")):
            raise ValueError("Node has a non-system dependency: " + dependency)
    run([binary, "--version"])
    return binary


def license_inventory(project, output):
    runtime = project / ".runtime/simnibs-4.6.0"
    conda = []
    for path in sorted((runtime / "conda-meta").glob("*.json")):
        record = json.loads(path.read_text())
        conda.append({key: record.get(key) for key in ("name", "version", "build", "license", "url", "sha256")})
    distributions = []
    for metadata in sorted((runtime / "lib/python3.11/site-packages").glob("*.dist-info/METADATA")):
        header = metadata.read_text(errors="replace").split("\n\n", 1)[0]
        fields = {}
        for line in header.splitlines():
            key, sep, value = line.partition(": ")
            if sep and key in {"Name", "Version", "License", "License-Expression", "Home-page"}:
                fields[key] = value
        distributions.append(fields)
    nodes = []
    for package in sorted((project / "webapp/node_modules").glob("**/package.json")):
        if package.is_symlink():
            continue
        try:
            data = json.loads(package.read_text())
        except (ValueError, OSError):
            continue
        if data.get("name") and data.get("version"):
            nodes.append({key: data.get(key) for key in ("name", "version", "license", "repository")})
    output.write_text(json.dumps({"schema": "eeglayoutlab-bundled-components/1", "conda": conda,
        "python": distributions, "nodePackages": nodes,
        "notice": "License texts and metadata remain with each component. This inventory is not a new license grant."}, indent=2) + "\n")


def archive_project(project, target):
    size = 0
    with tarfile.open(target, "w:gz", compresslevel=6, format=tarfile.PAX_FORMAT) as bundle:
        for path in sorted(project.rglob("*")):
            name = path.relative_to(project).as_posix()
            if path.is_symlink():
                if not path.resolve().is_relative_to(project):
                    raise ValueError("External payload link: " + name)
            elif path.is_file():
                size += path.stat().st_size
            def normalized(item):
                item.uid = item.gid = 0
                item.uname = item.gname = ""
                item.mtime = 0
                item.pax_headers = {}
                return item
            bundle.add(path, arcname=name, recursive=False, filter=normalized)
    return size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New output folder; never overwrite an earlier build")
    parser.add_argument("--staged-runtime", type=Path, help="Previously audited portable runtime, copied into the new workspace")
    parser.add_argument("--skip-web-build", action="store_true", help="Copy existing production build, for repeat desktop packaging only")
    parser.add_argument("--dmg", action="store_true", help="Also create a drag-to-Applications DMG")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("Build on native Apple Silicon macOS")
    release = json.loads((DESKTOP / "release.json").read_text())
    output = args.output.expanduser().absolute()
    if output.exists():
        parser.error("Output already exists; choose a new folder")
    output.mkdir(parents=True)
    work = output / "build-work"
    work.mkdir()
    app = output / (release["name"] + ".app")
    resources = app / "Contents/Resources"
    executables = app / "Contents/MacOS"
    resources.mkdir(parents=True)
    executables.mkdir()
    started = time.monotonic()
    node = stage_node(args.node_archive.expanduser().resolve(), release["node"], resources, work)
    project = work / "project"
    project.mkdir()
    identities, data = stage_project(project)
    print("BUILD: source and frozen data staged", flush=True)
    runtime = project / ".runtime/simnibs-4.6.0"
    if args.staged_runtime:
        source = args.staged_runtime.resolve()
        verify_staged_runtime(source)
        shutil.copytree(source, runtime, symlinks=True)
        # Recheck actual imports and dyld paths at this new project location.
        probe = runtime_tools().verify_runtime(runtime, project, DESKTOP / "runtime/verify_runtime.py")
        (work / "reused-runtime-verification.json").write_text(json.dumps(probe, indent=2) + "\n")
    else:
        run([sys.executable, DESKTOP / "runtime/stage_runtime.py", "--source", ROOT / ".runtime/simnibs-4.6.0",
             "--destination", runtime, "--project-root", project])
    environment = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "NODE_OPTIONS", "NODE_PATH"):
        environment.pop(key, None)
    environment.update({"PATH": str(node.parent) + ":/usr/bin:/bin:/usr/sbin:/sbin",
                        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "MPLCONFIGDIR": str(work / "matplotlib")})
    run([runtime / "bin/python", "-B", project / "scripts/check_environment.py", "--native"], env=environment)
    webapp = project / "webapp"
    if args.skip_web_build:
        shutil.copytree(ROOT / "webapp/dist", webapp / "dist")
    else:
        package = json.loads((webapp / "node_modules/vinext/package.json").read_text())
        entry = package["bin"]
        if isinstance(entry, dict):
            entry = entry["vinext"]
        run([node, webapp / "node_modules/vinext" / entry, "build"], cwd=webapp, env=environment)
    for file in DESKTOP.glob("*.mjs"):
        copy_file(file, resources / "desktop" / file.name)
    copy_file(ROOT / "THIRD_PARTY_NOTICES.md", resources / "THIRD_PARTY_NOTICES.md")
    license_inventory(project, resources / "BUNDLED_COMPONENTS.json")
    copy_file(runtime / "portable-runtime-audit.json", resources / "PORTABLE_RUNTIME_AUDIT.json")
    iconset = work / "AppIcon.iconset"
    run(["xcrun", "swift", "-module-cache-path", work / "swift-module-cache", DESKTOP / "macos/make-icon.swift", iconset])
    run(["iconutil", "-c", "icns", iconset, "-o", resources / "AppIcon.icns"])
    binary = executables / "EEG Layout Lab"
    run(["xcrun", "swiftc", "-O", "-parse-as-library", "-module-cache-path", work / "swift-module-cache", "-target", "arm64-apple-macos14.0", "-framework", "AppKit",
         "-framework", "WebKit", DESKTOP / "macos/App.swift", "-o", binary])
    info = {"CFBundleName": release["name"], "CFBundleDisplayName": release["name"],
            "CFBundleExecutable": binary.name, "CFBundleIdentifier": release["bundleIdentifier"],
            "CFBundleVersion": release["build"], "CFBundleShortVersionString": release["version"],
            "CFBundlePackageType": "APPL", "CFBundleIconFile": "AppIcon", "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": release["minimumMacOS"], "LSArchitecturePriority": ["arm64"],
            "LSApplicationCategoryType": "public.app-category.education",
            "NSHumanReadableCopyright": "© 2026 Yiming Shen",
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
            "CFBundleDevelopmentRegion": "en", "CFBundleLocalizations": ["en", "zh-Hans"]}
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    print("BUILD: compressing offline payload", flush=True)
    payload = resources / "payload.tar.gz"
    unpacked_bytes = archive_project(project, payload)
    payload_hash = digest(payload)
    manifest = {"schema": "eeglayoutlab-desktop/1", "version": release["version"], "build": release["build"],
                "minimumMacOS": 14, "architecture": "arm64", "payload": {"file": payload.name,
                "sha256": payload_hash, "unpackedBytes": unpacked_bytes},
                "dataManifestSha256": digest(project / "data/manifest.json"),
                "node": release["node"], "assets": []}
    for path in sorted((resources / "desktop").glob("*.mjs")):
        manifest["assets"].append({"file": path.relative_to(resources).as_posix(), "sha256": digest(path)})
    (resources / "desktop-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # Local testing signature only. No Developer ID or notarization is implied.
    run(["codesign", "--force", "--sign", "-", node])
    run(["codesign", "--force", "--sign", "-", app])
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    guides = [DESKTOP / name for name in ("START_HERE.md", "START_HERE.zh-CN.md")]
    for guide in guides:
        copy_file(guide, output / guide.name)
    archive = output / ("EEGLayoutLab-" + release["version"] + "-macOS-arm64.zip")
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, archive])
    deliverables = [{"file": archive.name, "bytes": archive.stat().st_size, "sha256": digest(archive)}]
    if args.dmg:
        mount = work / "dmg-root"
        mount.mkdir()
        shutil.copytree(app, mount / app.name, symlinks=True)
        for guide in guides:
            copy_file(guide, mount / guide.name)
        (mount / "Applications").symlink_to("/Applications")
        dmg = output / ("EEGLayoutLab-" + release["version"] + "-macOS-arm64.dmg")
        run(["hdiutil", "create", "-volname", release["name"], "-srcfolder", mount, "-format", "UDZO", "-ov", dmg])
        deliverables.append({"file": dmg.name, "bytes": dmg.stat().st_size, "sha256": digest(dmg)})
    report = {"schema": "eeglayoutlab-desktop-build/1", "release": release, "signature": "ad-hoc",
              "notarized": False, "payloadBytes": payload.stat().st_size, "unpackedBytes": unpacked_bytes,
              "frozenDataFiles": len(data["files"]), "sourceFileHashes": identities,
              "deliverables": deliverables, "elapsedSeconds": time.monotonic() - started}
    (output / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "SHA256SUMS.txt").write_text("".join(f"{item['sha256']}  {item['file']}\n" for item in deliverables))
    print(json.dumps({"status": "built", "app": str(app), "deliverables": deliverables}, indent=2), flush=True)


if __name__ == "__main__":
    main()
