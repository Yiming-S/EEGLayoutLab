#!/usr/bin/env python3
"""Reseal a desktop build in a new directory without rebuilding its payload.

The input .app, archives, and report remain unchanged. Only the bootstrap files
and, optionally, the native shell are updated in a copied application.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def run(args):
    print("FINALIZE:", " ".join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True)


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Expected a regular file: " + str(path))
    return path


def contained_file(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("Invalid bundle member path")
    path = root / name
    if ".." in Path(name).parts or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Bundle member escapes Resources: " + name)
    return regular(path)


def validate_build(source):
    """Read a completed build and bind the payload and bootstrap bytes to it."""
    report_path = regular(source / "build-report.json")
    report = json.loads(report_path.read_text())
    if report.get("schema") != "eeglayoutlab-desktop-build/1":
        raise ValueError("Input is not a completed desktop build")
    release = report["release"]
    if not isinstance(release.get("version"), str) or not re.fullmatch(r"[0-9][A-Za-z0-9.+_-]*", release["version"]):
        raise ValueError("Invalid release version")
    name = release["name"]
    if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
        raise ValueError("Invalid application name")
    app = source / (name + ".app")
    if app.is_symlink() or not app.is_dir():
        raise ValueError("Expected an application directory")
    for path in app.rglob("*"):
        if path.is_symlink() and (not path.exists() or not path.resolve().is_relative_to(app.resolve())):
            raise ValueError("Application contains an external or broken link: " + str(path))
    resources = app / "Contents/Resources"
    manifest = json.loads(regular(resources / "desktop-manifest.json").read_text())
    if manifest.get("schema") != "eeglayoutlab-desktop/1":
        raise ValueError("Unsupported desktop manifest")
    info = plistlib.loads(regular(app / "Contents/Info.plist").read_bytes())
    if (manifest.get("version") != release.get("version")
            or manifest.get("build") != release.get("build")
            or info.get("CFBundleIdentifier") != release.get("bundleIdentifier")
            or info.get("CFBundleShortVersionString") != release.get("version")
            or info.get("CFBundleVersion") != release.get("build")):
        raise ValueError("Build report, manifest, and application version differ")
    payload = contained_file(resources, manifest["payload"]["file"])
    if digest(payload) != manifest["payload"]["sha256"]:
        raise ValueError("Payload SHA-256 differs from the completed build")
    if payload.stat().st_size != report.get("payloadBytes"):
        raise ValueError("Payload size differs from the completed build")
    seen = set()
    for asset in manifest.get("assets", []):
        name = asset["file"]
        if name in seen:
            raise ValueError("Duplicate manifest asset: " + name)
        seen.add(name)
        if digest(contained_file(resources, name)) != asset["sha256"]:
            raise ValueError("Bootstrap asset SHA-256 differs: " + name)
    return app, report, manifest, info


def prepare_output(source, output):
    """Reserve a fresh sibling export directory, never an input subdirectory."""
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists; choose a new directory")
    resolved_source, resolved_output = source.resolve(), output.resolve()
    if resolved_output.is_relative_to(resolved_source) or resolved_source.is_relative_to(resolved_output):
        raise ValueError("Input and output directories must not contain one another")
    output.mkdir(parents=True)


def synchronize_bootstrap(resources, desktop=None):
    desktop = desktop or DESKTOP
    files = sorted(desktop.glob("*.mjs"))
    if not {"bootstrap.mjs", "bootstrap-support.mjs"}.issubset({path.name for path in files}):
        raise ValueError("Source bootstrap files are missing")
    target = resources / "desktop"
    if target.is_symlink():
        raise ValueError("Bootstrap directory must not be a symlink")
    target.mkdir(exist_ok=True)
    names = {path.name for path in files}
    for old in target.glob("*.mjs"):
        if old.name not in names:
            regular(old).unlink()  # Only obsolete scripts in this new copied app.
    assets = []
    for source in files:
        regular(source)
        expected = digest(source)
        destination = target / source.name
        if destination.is_symlink():
            raise ValueError("Bootstrap target must not be a symlink")
        shutil.copy2(source, destination)
        if digest(destination) != expected:
            raise ValueError("Bootstrap source changed during copying")
        assets.append({"file": destination.relative_to(resources).as_posix(), "sha256": expected})
    return assets


def finalize(source, output, *, rebuild_shell=False, dmg=False):
    started = time.monotonic()
    original_app, original_report, manifest, info = validate_build(source)
    # Reject an already modified app before using it as the starting point.
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", original_app])
    prepare_output(source, output)
    app = output / original_app.name
    run(["ditto", original_app, app])
    work = output / "build-work"
    work.mkdir()
    resources = app / "Contents/Resources"
    payload = contained_file(resources, manifest["payload"]["file"])
    if digest(payload) != manifest["payload"]["sha256"]:
        raise ValueError("Copied payload bytes changed")
    updated = copy.deepcopy(manifest)
    bootstrap_assets = synchronize_bootstrap(resources)
    updated["assets"] = [asset for asset in manifest.get("assets", [])
                         if not (asset["file"].startswith("desktop/") and asset["file"].endswith(".mjs"))]
    updated["assets"].extend(bootstrap_assets)
    updated["assets"].sort(key=lambda asset: asset["file"])
    (resources / "desktop-manifest.json").write_text(json.dumps(updated, indent=2) + "\n")
    executable = contained_file(app / "Contents/MacOS", info["CFBundleExecutable"])
    shell_source_hash = None
    if rebuild_shell:
        shell = regular(DESKTOP / "macos/App.swift")
        shell_source_hash = digest(shell)
        run(["xcrun", "swiftc", "-O", "-parse-as-library", "-module-cache-path", work / "swift-module-cache",
             "-target", "arm64-apple-macos14.0", "-framework", "AppKit", "-framework", "WebKit", shell, "-o", executable])
        if digest(shell) != shell_source_hash:
            raise ValueError("Swift source changed during compilation")
    run(["lipo", executable, "-verify_arch", "arm64"])
    node = contained_file(resources, "node/bin/node")
    run(["codesign", "--force", "--sign", "-", node])
    run(["codesign", "--force", "--sign", "-", app])
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    guides = [regular(DESKTOP / name) for name in ("START_HERE.md", "START_HERE.zh-CN.md")]
    for guide in guides:
        shutil.copy2(guide, output / guide.name)
    release = original_report["release"]
    stem = "EEGLayoutLab-" + release["version"] + "-macOS-arm64"
    archive = output / (stem + ".zip")
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, archive])
    paths = [archive]
    if dmg:
        mount = work / "dmg-root"
        mount.mkdir()
        run(["ditto", app, mount / app.name])
        (mount / "Applications").symlink_to("/Applications")
        for guide in guides:
            shutil.copy2(guide, mount / guide.name)
        image = output / (stem + ".dmg")
        run(["hdiutil", "create", "-volname", release["name"], "-srcfolder", mount, "-format", "UDZO", image])
        paths.append(image)
    deliverables = [{"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)} for path in paths]
    report = copy.deepcopy(original_report)
    report.update({"signature": "ad-hoc", "notarized": False, "deliverables": deliverables})
    report["finalization"] = {
        "atUTC": datetime.now(timezone.utc).isoformat(), "inputBuildReportSha256": digest(source / "build-report.json"),
        "payloadSha256": manifest["payload"]["sha256"], "payloadUnchanged": True,
        "bootstrapAssets": bootstrap_assets, "nativeShellRebuilt": rebuild_shell,
        "nativeShellSourceSha256": shell_source_hash, "nativeShellBinarySha256": digest(executable),
        "guideSha256": {guide.name: digest(output / guide.name) for guide in guides},
        "elapsedSeconds": time.monotonic() - started,
        "note": "Packaging verification only; no new scientific or cross-device validation is implied.",
    }
    (output / "build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "SHA256SUMS.txt").write_text("".join(f"{item['sha256']}  {item['file']}\n" for item in deliverables)
                                          + "".join(f"{digest(output / guide.name)}  {guide.name}\n" for guide in guides))
    print(json.dumps({"status": "finalized", "app": str(app), "deliverables": deliverables}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Completed build directory; read only")
    parser.add_argument("--output", type=Path, required=True, help="New export directory; never overwritten")
    parser.add_argument("--rebuild-shell", action="store_true", help="Compile the current native Swift shell")
    parser.add_argument("--dmg", action="store_true", help="Create a DMG with the app, Applications shortcut, and guide")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("Finalize on native Apple Silicon macOS")
    try:
        finalize(args.input.expanduser().absolute(), args.output.expanduser().absolute(),
                 rebuild_shell=args.rebuild_shell, dmg=args.dmg)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, "finalize: " + str(error) + "\n")


if __name__ == "__main__":
    main()
