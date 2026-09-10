#!/usr/bin/env python3
"""Verify, export and install a pinned local data bundle using only the stdlib.

The checkout's data/manifest.json is the trust anchor. No network requests are
made and no tar member is passed to extract/extractall. Install validates the
entire archive and every existing destination before placing any payload file.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile
import tempfile

SCHEMA = "eeglayoutlab-data-bundle/1"
MANIFEST = "data/manifest.json"
CHUNK = 1024 * 1024
DEFAULT_ROOT = Path(__file__).resolve().parents[1]


class BundleError(ValueError):
    """A bundle or destination failed validation."""


def relative_path(value):
    if (not isinstance(value, str) or not value or "\\" in value
            or ":" in value or any(ord(c) < 32 for c in value)):
        raise BundleError(f"Unsafe relative path: {value!r}")
    path = PurePosixPath(value)
    if (path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/"))
            or str(path) != value):
        raise BundleError(f"Unsafe relative path: {value!r}")
    return path


def safe_path(root, relative):
    """Reject symlinks in existing descendants, including dangling symlinks."""
    parts = relative_path(relative).parts
    current = root
    for i, part in enumerate(parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise BundleError(f"Symlink is forbidden: {relative}")
        if i < len(parts) - 1 and not stat.S_ISDIR(mode):
            raise BundleError(f"Non-directory ancestor: {relative}")
        if i == len(parts) - 1 and not stat.S_ISREG(mode):
            raise BundleError(f"Not a regular file: {relative}")
    return current


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(root):
    path = safe_path(root, MANIFEST)
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise BundleError(f"Cannot read trusted {MANIFEST}: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA:
        raise BundleError("Unsupported data manifest schema")
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise BundleError("Manifest must contain a nonempty files list")
    files, folded = {}, set()
    for record in records:
        if not isinstance(record, dict):
            raise BundleError("Invalid manifest file entry")
        name = record.get("path")
        relative_path(name)
        if not (name.startswith(("data/external/", "results/v2/")) or name == "data/SOURCES.md"):
            raise BundleError(f"File outside approved payload namespaces: {name}")
        if name.casefold() in folded:
            raise BundleError(f"Duplicate or case-ambiguous manifest path: {name}")
        folded.add(name.casefold())
        if type(record.get("size_bytes")) is not int or record["size_bytes"] < 0:
            raise BundleError(f"Invalid byte size: {name}")
        if not isinstance(record.get("sha256"), str) or not re.fullmatch("[0-9a-f]{64}", record["sha256"]):
            raise BundleError(f"Invalid SHA256: {name}")
        files[name] = record
    for name in files:
        if any(str(parent).casefold() in folded for parent in PurePosixPath(name).parents):
            raise BundleError(f"File/directory path collision: {name}")
    size = sum(record["size_bytes"] for record in files.values())
    if type(manifest.get("total_size_bytes")) is not int or manifest["total_size_bytes"] != size:
        raise BundleError("Manifest total_size_bytes does not match file entries")
    return raw, manifest, files


def matching_file(path, record):
    return (path.stat().st_size == record["size_bytes"]
            and sha256_file(path) == record["sha256"])


def verify_files(root, files):
    failures = []
    for name, record in files.items():
        try:
            path = safe_path(root, name)
            if not path.exists():
                failures.append(f"missing: {name}")
            elif not matching_file(path, record):
                failures.append(f"size/SHA256 mismatch: {name}")
        except (OSError, BundleError) as exc:
            failures.append(str(exc))
    if failures:
        raise BundleError("Data verification failed:\n" + "\n".join(failures))


def verify(root):
    _, manifest, files = load_manifest(root)
    verify_files(root, files)
    return {"status": "verified", "files": len(files), "size_bytes": manifest["total_size_bytes"]}


def add_file(archive, name, size, stream):
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o644
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    archive.addfile(info, stream)


def export_bundle(root, output):
    raw, manifest, files = load_manifest(root)
    verify_files(root, files)
    output = Path(output).expanduser().absolute()
    if output.is_symlink() or output.exists():
        raise BundleError(f"Output already exists; choose a new filename: {output}")
    if not output.parent.is_dir():
        raise BundleError(f"Output directory must already exist: {output.parent}")
    # Build beside the output, then publish with a no-clobber hard link. Tar
    # headers and gzip metadata are independent of source owner, host and time.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".data-export-", delete=False) as target:
            temporary = Path(target.name)
            with gzip.GzipFile(fileobj=target, mode="wb", filename="", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                    add_file(archive, MANIFEST, len(raw), io.BytesIO(raw))
                    for name in sorted(files):
                        record = files[name]
                        with safe_path(root, name).open("rb") as stream:
                            add_file(archive, name, record["size_bytes"], stream)
        # Verify bytes in the completed archive before exposing it to the user.
        with tempfile.TemporaryDirectory(prefix=".data-export-check-", dir=output.parent) as staging:
            validate_archive(temporary, Path(staging), raw, files)
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"status": "exported", "path": str(output), "files": len(files),
            "payload_size_bytes": manifest["total_size_bytes"],
            "archive_size_bytes": output.stat().st_size, "sha256": sha256_file(output)}


def validate_archive(bundle, staging, raw, files):
    """Stage authenticated regular files only; never trust archive metadata."""
    expected = {MANIFEST: {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}, **files}
    seen = set()
    with tarfile.open(bundle, "r|gz") as archive:
        for member in archive:
            name = member.name
            relative_path(name)
            if name not in expected:
                raise BundleError(f"Unexpected archive member: {name}")
            if name in seen:
                raise BundleError(f"Duplicate archive member: {name}")
            seen.add(name)
            if not member.isfile() or member.issparse() or member.linkname:
                raise BundleError(f"Non-regular archive member is forbidden: {name}")
            record = expected[name]
            if member.size != record["size_bytes"]:
                raise BundleError(f"Archive byte size mismatch: {name}")
            stream = archive.extractfile(member)
            if stream is None:
                raise BundleError(f"Unreadable archive member: {name}")
            destination = safe_path(staging, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest, count = hashlib.sha256(), 0
            with stream, destination.open("xb") as target:
                while block := stream.read(CHUNK):
                    count += len(block)
                    digest.update(block)
                    target.write(block)
            if count != record["size_bytes"] or digest.hexdigest() != record["sha256"]:
                raise BundleError(f"Archive SHA256 mismatch: {name}")
    missing = sorted(set(expected) - seen)
    if missing:
        raise BundleError("Archive is incomplete: " + ", ".join(missing))
    if (staging / MANIFEST).read_bytes() != raw:
        raise BundleError("Archive manifest differs from the trusted checkout manifest")


def install_bundle(root, bundle):
    raw, manifest, files = load_manifest(root)
    bundle = Path(bundle).expanduser().absolute()
    if bundle.is_symlink() or not bundle.is_file():
        raise BundleError("Bundle must be a local regular file, not a symlink")
    with tempfile.TemporaryDirectory(prefix=".data-install-", dir=root) as temporary:
        staging = Path(temporary)
        validate_archive(bundle, staging, raw, files)
        missing = []
        # Complete destination preflight before installing any payload file.
        for name, record in files.items():
            path = safe_path(root, name)
            if path.exists():
                if not matching_file(path, record):
                    raise BundleError(f"Refusing to overwrite different existing data: {name}")
            else:
                missing.append(name)
        for name in missing:
            destination = safe_path(root, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            safe_path(root, name)
            try:
                # Exclusive publication; an existing filename is never replaced.
                os.link(staging / name, destination)
            except FileExistsError:
                if not matching_file(safe_path(root, name), files[name]):
                    raise BundleError(f"Destination changed during installation: {name}") from None
        verify_files(root, files)
    return {"status": "installed", "installed_files": len(missing),
            "already_present_files": len(files) - len(missing),
            "size_bytes": manifest["total_size_bytes"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "export", "install"):
        command = sub.add_parser(name)
        command.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                             help="checkout directory (default: this script's parent repository)")
        if name == "export":
            command.add_argument("--output", type=Path, required=True, help="new local .tar.gz filename")
        elif name == "install":
            command.add_argument("bundle", type=Path, help="local .tar.gz supplied with this checkout")
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        if not root.is_dir():
            raise BundleError("Checkout root must be an existing directory")
        if args.command == "verify":
            result = verify(root)
        elif args.command == "export":
            result = export_bundle(root, args.output)
        else:
            result = install_bundle(root, args.bundle)
    except (BundleError, OSError, tarfile.TarError, EOFError) as exc:
        print(f"data_bundle: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
