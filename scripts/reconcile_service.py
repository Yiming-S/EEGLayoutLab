#!/usr/bin/env python3
"""Preview or apply offline queue receipt reconciliation from verified caches.

Stop the maintained service first. Preview writes a separate plan; apply requires
that plan and its exact original queue SHA256. No scientific job is launched and
no scientific cache/result, project, secret or annotation file is rewritten.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
from backup_service import NATIVE_LOCK, alive, guard_native, real_directory
from data_bundle import safe_path

SCHEMA = "eeglayoutlab-service-reconciliation/1"
ROOT = Path(__file__).resolve().parents[1]
INSPECTOR = ROOT / "scripts/inspect_service_reconciliation.mjs"
LIMIT = 64 * 1024 * 1024
INTERRUPTED_MESSAGE = "服务重启中断了计算，可重新提交"


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > LIMIT:
            raise ValueError("Expected a bounded regular file with one link: " + str(path))
        with os.fdopen(fd, "rb", closefd=False) as stream:
            value = stream.read(LIMIT + 1)
        after = os.fstat(fd)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(value) > LIMIT or any(getattr(before, name) != getattr(after, name) for name in fields):
            raise ValueError("File changed while reading: " + str(path))
        return value
    finally:
        os.close(fd)


def json_bytes(value):
    return json.loads(value, parse_constant=lambda name: (_ for _ in ()).throw(ValueError("Nonfinite JSON value: " + name)))


def valid_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def write_new(path, content):
    with Path(path).open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def plan_path(path, root, *, existing):
    path = Path(path).expanduser().absolute()
    if path != path.resolve() or not path.is_relative_to(root / "artifacts"):
        raise ValueError("Keep reconciliation plans in a regular path under this scientific root's artifacts/")
    for ancestor in path.parents:
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise ValueError("Plan path contains a symlink")
    if existing:
        read_regular(path)
    elif path.exists() or path.is_symlink():
        raise ValueError("Plan already exists; choose a new filename")
    return path


def check_owner(directory):
    lock = safe_path(directory, "worker.lock")
    if lock.exists():
        value = json_bytes(read_regular(lock))
        if not isinstance(value, dict) or alive(value.get("pid")):
            raise ValueError("Service owner is alive or invalid; stop the service before reconciliation")


@contextmanager
def offline_guard(directory):
    """Use the same exclusive acquisition guard as CommunityQueue, without loading it."""
    path = directory / "acquiring.lock"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)
        check_owner(directory)
        yield
    finally:
        try:
            entry = path.stat(follow_symlinks=False)
            if entry.st_ino == os.fstat(fd).st_ino and entry.st_dev == os.fstat(fd).st_dev:
                path.unlink()
        except FileNotFoundError:
            pass
        finally:
            os.close(fd)


def blockers(state):
    if not isinstance(state, dict) or state.get("version") != 1 or not isinstance(state.get("tasks"), list):
        raise ValueError("Unsupported queue state")
    result = [] if state.get("maintenance") is True else ["maintenance_not_persisted"]
    for task in state["tasks"]:
        if not isinstance(task, dict):
            raise ValueError("Invalid queue receipt")
        pid = task.get("workerPid")
        if pid is not None:
            if type(pid) is not int or pid <= 0:
                result.append("invalid_worker_pid:" + str(task.get("id")))
            elif alive(pid):
                result.append("worker_alive:" + str(task.get("id")))
        if task.get("starting") and (type(pid) is not int or pid <= 0):
            result.append("unconfirmed_spawn:" + str(task.get("id")))
    return result


def inspect(root, directory, python, queue, node):
    command = [node, str(INSPECTOR)]
    body = {"root": str(root), "queue_directory": str(directory), "queue_json": queue.decode("utf-8")}
    if python is not None:
        body["python"] = str(python)
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    process = subprocess.run(command, input=encoded(body), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=ROOT, env=environment, timeout=120, check=False)
    if process.returncode:
        raise ValueError("Read-only cache inspection failed: " + process.stderr.decode("utf-8", "replace")[:2000])
    if len(process.stdout) > LIMIT:
        raise ValueError("Inspector output exceeds the supported size")
    value = json_bytes(process.stdout)
    if (not isinstance(value, dict) or value.get("inspector_schema") != "eeglayoutlab-offline-inspection/1"
            or value.get("scientific_worker_launches") != 0 or not valid_sha(value.get("source_files_sha256"))
            or not isinstance(value.get("proposed_queue_json"), str)
            or digest(value["proposed_queue_json"].encode()) != value.get("proposed_queue_sha256")):
        raise ValueError("Invalid inspector output")
    return value


def validate_proposal(original, inspection):
    """Independently constrain the Node proposal before trusting any write bytes."""
    proposed = json_bytes(inspection["proposed_queue_json"])
    if (not isinstance(proposed, dict) or {k: v for k, v in proposed.items() if k != "tasks"}
            != {k: v for k, v in original.items() if k != "tasks"}
            or not isinstance(proposed.get("tasks"), list) or len(proposed["tasks"]) != len(original["tasks"])):
        raise ValueError("Proposal changes queue format, sequence or receipt count")
    changed = set()
    allowed = {"status", "cached", "progress", "finished_at", "message", "catalog", "starting", "workerPid", "backendId"}
    for before, after in zip(original["tasks"], proposed["tasks"]):
        if before == after:
            continue
        eligible = before.get("status") == "running" or (before.get("status") == "failed" and before.get("message") == INTERRUPTED_MESSAGE)
        if (not isinstance(after, dict) or not eligible or after.get("status") not in ("completed", "no_layout")
                or (after["status"] == "no_layout" and before.get("kind") != "local-compute")
                or after.get("cached") is not True or after.get("progress") != 1
                or any(field in after for field in ("starting", "workerPid", "backendId"))
                or any(before.get(key) != after.get(key) for key in set(before) | set(after) if key not in allowed)):
            raise ValueError("Proposal changes protected receipt fields or revives an ineligible task")
        changed.add(before["id"])
    changes = inspection.get("changes")
    if not isinstance(changes, list) or len(changes) != len(changed) or {item.get("id") for item in changes} != changed:
        raise ValueError("Proposal change list does not match its receipt updates")


def atomic_queue(directory, original, content):
    path = safe_path(directory, "queue.json")
    if read_regular(path) != original:
        raise ValueError("Queue changed before the atomic write")
    fd, temporary = tempfile.mkstemp(prefix=".reconcile-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if read_regular(path) != original:
            raise ValueError("Queue changed during the atomic write")
        os.replace(temporary, path)
        handle = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def reconcile(root, directory, output, *, python=None, node="node", execute=False, expected_queue_sha256=None):
    root, directory = real_directory(root), real_directory(directory)
    output = plan_path(output, root, existing=execute)
    original_plan = json_bytes(read_regular(output)) if execute else None
    if execute and (not valid_sha(expected_queue_sha256) or not isinstance(original_plan, dict)
                    or original_plan.get("queue_sha256") != expected_queue_sha256):
        raise ValueError("Apply requires the independent preview plan's exact --expected-queue-sha256")
    native_lock = safe_path(root, NATIVE_LOCK)
    if native_lock.exists():
        read_regular(native_lock)
    with offline_guard(directory), guard_native(root, create=True):
        read_regular(safe_path(root, NATIVE_LOCK))
        queue_file = safe_path(directory, "queue.json")
        original = read_regular(queue_file)
        if execute and digest(original) != expected_queue_sha256:
            raise ValueError("Queue bytes changed since preview; make a new preview")
        state = json_bytes(original)
        before_blockers = blockers(state)
        tool_sha = digest(Path(__file__).read_bytes())
        secret = safe_path(directory, "session-secret.json")
        secret_sha = digest(read_regular(secret)) if secret.exists() else None
        inspection = inspect(root, directory, python, original, node)
        validate_proposal(state, inspection)
        if read_regular(queue_file) != original or digest(Path(__file__).read_bytes()) != tool_sha:
            raise ValueError("Queue or reconciliation tool changed during inspection")
        check_owner(directory)
        after_blockers = blockers(json_bytes(read_regular(queue_file)))
        if before_blockers != after_blockers:
            raise ValueError("Worker liveness changed; make a fresh preview")
        if (digest(read_regular(secret)) if secret.exists() else None) != secret_sha:
            raise ValueError("Session identity changed during inspection")
        plan = {"schema": SCHEMA, "root": str(root), "queue_directory": str(directory),
                "queue_sha256": digest(original), "tool_sha256": tool_sha, "session_secret_sha256": secret_sha,
                "apply_allowed": not after_blockers, "blocked_reasons": after_blockers, **inspection}
        if not execute:
            output.parent.mkdir(parents=True, exist_ok=True)
            write_new(output, encoded(plan) + b"\n")
            return {"mode": "preview", "plan": str(output), "queue_sha256": plan["queue_sha256"],
                    "apply_allowed": plan["apply_allowed"], "blocked_reasons": after_blockers,
                    "changes": plan["changes"], "scientific_worker_launches": 0}
        if expected_queue_sha256 != digest(original) or encoded(original_plan) != encoded(plan):
            raise ValueError("Preview plan no longer matches queue, cache, runtime or inspector; make a new preview")
        if not plan["apply_allowed"]:
            raise ValueError("Apply is blocked: " + ", ".join(after_blockers))
        changed = bool(plan["changes"])
        backup = output.with_name(output.name + ".queue-before.json")
        if changed:
            write_new(backup, original)
            # Recheck liveness and the original bytes immediately before replacement.
            check_owner(directory)
            if blockers(json_bytes(read_regular(queue_file))):
                raise ValueError("Worker or maintenance state changed before apply")
            atomic_queue(directory, original, plan["proposed_queue_json"].encode("utf-8"))
        return {"mode": "execute", "plan": str(output), "executed": changed,
                "queue_before_sha256": digest(original), "queue_after_sha256": digest(read_regular(queue_file)),
                "backup": str(backup) if changed else None, "changes": plan["changes"], "scientific_worker_launches": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Scientific checkout root")
    parser.add_argument("--queue-directory", type=Path, help="Existing service queue directory")
    parser.add_argument("--plan", type=Path, required=True, help="New preview file, or an existing file for apply, under root/artifacts/")
    parser.add_argument("--python", type=Path, help="Existing scientific Python; managed runtime precedence stays unchanged")
    parser.add_argument("--node", default="node")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-queue-sha256")
    args = parser.parse_args(argv)
    directory = args.queue_directory or Path(os.environ.get("EEG_QUEUE_DIRECTORY", args.root / "results/web-service"))
    result = reconcile(args.root, directory, args.plan, python=args.python, node=args.node,
                       execute=args.execute, expected_queue_sha256=args.expected_queue_sha256)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print("Service reconciliation failed: " + str(error), file=sys.stderr)
        raise SystemExit(1)
