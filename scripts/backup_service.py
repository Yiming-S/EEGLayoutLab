#!/usr/bin/env python3
"""Preview, create and restore an offline EEGLayoutLab service snapshot.

Snapshots include current source, computed records, queue receipts and the
browser-session secret. Frozen model payloads, environments, logs and process
locks are excluded. Restore always creates a new directory under artifacts/;
matching frozen data and the scientific environment must be installed separately.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

from data_bundle import relative_path, safe_path, sha256_file, verify_files
from prepare_verification_workspace import output_path
from release_manifest import ROOT, digest, encoded, release_manifest, valid_sha

SCHEMA = "eeglayoutlab-service-backup/1"
MANIFEST = "backup.json"
RECORDS = tuple("results/v2/" + name for name in (
    "local_app_jobs", "design_evaluation_jobs", "electrode_editor_jobs",
    "source_reception_jobs", "source_reception_v2_jobs", "reception_forward"))
NATIVE_LOCK = "results/v2/reception_forward/native-worker.lock"
QUEUE = "results/web-service"
QUEUE_FILES = ("queue.json", "session-secret.json")
QUEUE_TREES = ("projects", "studies")


def real_directory(path):
    requested = Path(path).expanduser().absolute()
    resolved = requested.resolve(strict=True)
    if requested != resolved or not resolved.is_dir():
        raise ValueError("Directory must exist without symlinks or parent traversal")
    return resolved


def alive(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError("Invalid process identifier; inspect queue state before recovery")
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def queue_stopped(directory, *, own_guard=False):
    if (directory / "acquiring.lock").exists() and not own_guard:
        raise ValueError("Queue acquisition is in progress or needs operator inspection")
    lock = safe_path(directory, "worker.lock")
    if lock.exists() and alive(json.loads(lock.read_bytes()).get("pid")):
        raise ValueError("Queue has a live writer; drain and stop the service before backup")
    value = json.loads(safe_path(directory, "queue.json").read_bytes())
    if (value.get("version") != 1 or value.get("maintenance") is not True or
            not isinstance(value.get("tasks"), list)):
        raise ValueError("Backup requires a supported queue durably in maintenance mode")
    for task in value["tasks"]:
        if not isinstance(task, dict):
            raise ValueError("Invalid queue receipt")
        if task.get("starting") or task.get("status") in ("running", "cancelling"):
            raise ValueError("Queue is not drained; an active or unconfirmed start remains")
        if task.get("workerPid") is not None and alive(task["workerPid"]):
            raise ValueError("A computation worker is still alive")
    secret = json.loads(safe_path(directory, "session-secret.json").read_bytes())
    if not valid_sha(secret.get("key")):
        raise ValueError("Invalid browser-session secret")


@contextmanager
def guard_queue(directory):
    path = directory / "acquiring.lock"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode()); os.fsync(fd)
        queue_stopped(directory, own_guard=True)
        yield
    finally:
        # Never remove a replacement guard belonging to another process.
        try:
            if path.stat(follow_symlinks=False).st_ino == os.fstat(fd).st_ino:
                path.unlink()
        finally:
            os.close(fd)


@contextmanager
def guard_native(root, *, create):
    path = safe_path(root, NATIVE_LOCK)
    if not path.exists() and not create:
        yield
        return
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b' if create else 'rb') as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("A native reception writer is active") from error
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def tree_files(root):
    """Return regular files and directories, refusing links and special devices."""
    files, directories = [], []
    if not root.exists():
        if root.is_symlink():
            raise ValueError("Snapshot path is a symlink")
        return files, directories
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Snapshot root is not a regular directory")
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in sorted(dirs + names):
            path = Path(directory) / name
            mode = path.lstat().st_mode
            relative = path.relative_to(root).as_posix()
            relative_path(relative)
            if stat.S_ISREG(mode):
                files.append(relative)
            elif stat.S_ISDIR(mode):
                directories.append(relative)
            else:
                raise ValueError(f"Symlink or special entry is forbidden: {relative}")
    return sorted(files), sorted(directories)


def file_record(path, name):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Snapshot entry is not a regular file: {name}")
    before = path.stat()
    result = {"path": name, "size_bytes": before.st_size, "sha256": sha256_file(path)}
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError(f"File changed while reading: {name}")
    return result


def inventory(root, directory, release):
    rows = {row["path"]: row for row in release["source"]["files"]}
    origins = {name: safe_path(Path(release["source_root"]), name) for name in rows}
    for base in RECORDS:
        folder = root / base
        # safe_path validates ancestors but expects a file at the final component.
        safe_path(root, base + "/.inventory-check")
        files, _ = tree_files(folder)
        for relative in files:
            name = base + "/" + relative
            if name == NATIVE_LOCK:
                continue
            origins[name] = safe_path(root, name)
            rows[name] = file_record(origins[name], name)
    for filename in QUEUE_FILES:
        name = QUEUE + "/" + filename
        origins[name] = safe_path(directory, filename)
        rows[name] = file_record(origins[name], name)
    # Project/study records and immutable snapshots outlive bounded queue receipts.
    # Preserve them even when the queue is outside the scientific checkout.
    for base in QUEUE_TREES:
        safe_path(directory, base + "/.inventory-check")
        files, _ = tree_files(directory / base)
        for relative in files:
            name = QUEUE + "/" + base + "/" + relative
            origins[name] = safe_path(directory, base + "/" + relative)
            rows[name] = file_record(origins[name], name)
    return [rows[name] for name in sorted(rows)], origins


def copy_checked(origin, destination, row):
    if file_record(origin, row["path"]) != row:
        raise ValueError(f"Snapshot source changed: {row['path']}")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with origin.open("rb") as source, destination.open("xb") as target:
        os.chmod(destination, 0o700 if origin.stat().st_mode & 0o111 else 0o600)
        shutil.copyfileobj(source, target)
        target.flush(); os.fsync(target.fileno())
    if file_record(destination, row["path"]) != row or file_record(origin, row["path"]) != row:
        raise ValueError(f"Snapshot bytes changed during copy: {row['path']}")


def publish(root, staging, destination):
    output_path(root, destination)
    # Exclusive mkdir prevents rename from replacing an existing empty directory.
    destination.mkdir(mode=0o700)
    marker = destination / ".restore-incomplete"
    with marker.open('x') as stream:
        stream.write("Do not use this directory until this marker is removed.\n")
        stream.flush(); os.fsync(stream.fileno())
    files, directories = tree_files(staging)
    for name in sorted(directories, key=lambda value: (len(Path(value).parts), value)):
        (destination / name).mkdir(mode=0o700)
    for name in files:
        target = safe_path(destination, name)
        # link is exclusive, unlike rename. These are new private staging bytes,
        # never links to source files or to the backup being restored.
        os.link(staging / name, target, follow_symlinks=False)
        (staging / name).unlink()
    for name in sorted(directories, key=lambda value: -len(Path(value).parts)):
        sync_directory(destination / name)
    marker.unlink()
    sync_directory(destination)
    sync_directory(destination.parent)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def backup(root, output, *, source_root=None, queue_directory=None, python=None, execute=False):
    root = real_directory(root)
    source_root = real_directory(source_root or root)
    destination = output_path(source_root, output)
    directory = real_directory(queue_directory or root / QUEUE)
    queue_stopped(directory)
    if execute and python is None:
        raise ValueError("--execute requires --python to record the installed scientific runtime")
    context = guard_queue(directory) if execute else nullcontext()
    with context, guard_native(root, create=execute):
        release = release_manifest(source_root, repository_root=root, python=python, verify_data=True)
        rows, origins = inventory(root, directory, release)
        manifest = {"schema": SCHEMA, "release": release, "files": rows,
                    "queue_restore_directory": QUEUE,
                    "excluded": ["frozen data payload", "runtime environment", "node_modules", "dist", "access logs", "process locks", "private environment files"]}
        report = {"mode": "execute" if execute else "plan", "output": str(destination),
                  "manifest_sha256": digest(manifest), "files": len(rows),
                  "size_bytes": sum(row["size_bytes"] for row in rows), "manifest": manifest}
        if not execute:
            return report
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".backup-", dir=destination.parent))
        try:
            for row in rows:
                copy_checked(origins[row["path"]], staging / "payload" / row["path"], row)
            # Refuse a mixed snapshot, including files added or deleted during copying.
            current_release = release_manifest(source_root, repository_root=root, python=python, verify_data=True)
            current_rows, _ = inventory(root, directory, current_release)
            queue_stopped(directory, own_guard=True)
            if current_release != release or current_rows != rows:
                raise ValueError("Source, runtime, data or records changed during backup")
            with (staging / MANIFEST).open("xb") as stream:
                os.chmod(staging / MANIFEST, 0o600)
                stream.write(encoded(manifest)); stream.flush(); os.fsync(stream.fileno())
            publish(source_root, staging, destination)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return report


def validate_backup(snapshot, expected_sha):
    snapshot = real_directory(snapshot)
    if not valid_sha(expected_sha):
        raise ValueError("The independently recorded manifest SHA256 is required")
    manifest_path = safe_path(snapshot, MANIFEST)
    if sha256_file(manifest_path) != expected_sha:
        raise ValueError("Backup manifest SHA256 mismatch")
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("schema") != SCHEMA or manifest.get("queue_restore_directory") != QUEUE:
        raise ValueError("Unsupported backup schema")
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Backup inventory is empty or invalid")
    records, folded = {}, set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid backup file record")
        name = row.get("path")
        relative_path(name)
        if name in records or name.casefold() in folded or not valid_sha(row.get("sha256")) or type(row.get("size_bytes")) is not int or row["size_bytes"] < 0:
            raise ValueError("Invalid or duplicate backup file record")
        records[name] = row; folded.add(name.casefold())
    release = manifest.get("release", {})
    source = release.get("source", {})
    sources = source.get("files")
    if (release.get("schema") != "eeglayoutlab-release/1" or not isinstance(sources, list) or not sources or
            digest(sources) != source.get("inventory_sha256")):
        raise ValueError("Invalid release source identity")
    for row in sources:
        if not isinstance(row, dict) or records.get(row.get("path")) != row:
            raise ValueError("Backup disagrees with release source inventory")
    science = release.get("scientific_source", {})
    if not isinstance(science.get("files"), list) or digest(science["files"]) != science.get("inventory_sha256"):
        raise ValueError("Invalid scientific source identity")
    if any(row not in sources for row in science["files"]):
        raise ValueError("Scientific and host source inventories disagree")
    if (records.get('data/manifest.json', {}).get('sha256') != release.get('data', {}).get('manifest_sha256') or
            records.get('configs/runtime/manifest.json', {}).get('sha256') != release.get('runtime', {}).get('lock_sha256')):
        raise ValueError("Backup data or runtime lock identity disagrees with stored bytes")
    observed = release.get('runtime', {}).get('observed')
    if (not isinstance(observed, dict) or not valid_sha(observed.get('executable_sha256')) or
            observed.get('native_identity', {}).get('schema') != 'reception-runtime-digest/1' or
            not valid_sha(observed.get('native_identity', {}).get('sha256'))):
        raise ValueError("Backup has no observed scientific runtime identity")
    payload = snapshot / "payload"
    actual, directories = tree_files(snapshot)
    expected = {MANIFEST, *("payload/" + name for name in records)}
    allowed_directories = {str(parent) for name in expected for parent in Path(name).parents if str(parent) != "."}
    if set(actual) != expected or set(directories) != allowed_directories:
        raise ValueError("Backup contains missing or extra entries")
    verify_files(payload, records)
    # Ensure restore cannot erase maintenance state or resurrect uncertain work.
    queue_stopped(payload / QUEUE)
    return manifest, records


def restore(root, snapshot, output, *, manifest_sha256, execute=False):
    root = real_directory(root)
    destination = output_path(root, output)
    snapshot = real_directory(snapshot)
    if destination.is_relative_to(snapshot) or snapshot.is_relative_to(destination):
        raise ValueError("Restore output overlaps the backup")
    manifest, records = validate_backup(snapshot, manifest_sha256)
    report = {"mode": "execute" if execute else "plan", "output": str(destination),
              "manifest_sha256": manifest_sha256, "files": len(records),
              "data_required": manifest["release"]["data"], "runtime_required": manifest["release"]["runtime"],
              "ready_to_start": False}
    if not execute:
        return report
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=destination.parent))
    try:
        for name, row in records.items():
            copy_checked(safe_path(snapshot / "payload", name), staging / name, row)
        # Validate the whole source again, including additional files and replaced manifests.
        validate_backup(snapshot, manifest_sha256)
        verify_files(staging, records)
        publish(root, staging, destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("backup", "restore"):
        command = sub.add_parser(action)
        command.add_argument("--repository-root", type=Path, default=ROOT)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--execute", action="store_true")
        if action == "backup":
            command.add_argument("--source-root", type=Path, help="Git host checkout; defaults to --repository-root")
            command.add_argument("--queue-directory", type=Path)
            command.add_argument("--python")
        else:
            command.add_argument("--snapshot", type=Path, required=True)
            command.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.action == "backup":
            report = backup(args.repository_root, args.output, source_root=args.source_root, queue_directory=args.queue_directory,
                            python=args.python, execute=args.execute)
        else:
            report = restore(args.repository_root, args.snapshot, args.output,
                             manifest_sha256=args.manifest_sha256, execute=args.execute)
        print(json.dumps(report, indent=2))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Service {args.action} failed: {error}\n")


if __name__ == "__main__":
    main()
