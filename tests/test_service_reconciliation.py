"""Offline reconciliation lock/write boundaries, without scientific computation."""
import copy
import fcntl
import json
import os
from pathlib import Path

import pytest

import reconcile_service as service


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path.resolve() / "science"
    directory = root / "results/web-service"
    directory.mkdir(parents=True)
    task = {"id": "receipt", "kind": "local-compute", "key": "a" * 64, "sequence": 1,
            "request": {"retained_float": 1.0000000000000002}, "owners": ["owner-a", "owner-b"],
            "annotation_refs": {"owner-a": ["b" * 64]}, "status": "running", "workerPid": 99999999}
    state = {"version": 1, "sequence": 1, "maintenance": True, "tasks": [task]}
    dump(directory / "queue.json", state)
    dump(directory / "session-secret.json", {"key": "e" * 64})
    canary = root / "results/v2/local_app_jobs/private/cache.json"
    dump(canary, {"original_science": [1 / 3, 1e-18, 1.0000000000000002]})
    return root, directory, state, canary


def plan_path(root, name="preview.json"):
    return root / "artifacts/reconciliation" / name


def inspector(cache_sha="c" * 64):
    def inspect(root, directory, python, raw, node):
        original = json.loads(raw)
        proposed = copy.deepcopy(original)
        changes = []
        for task in proposed["tasks"]:
            if task["status"] != "running":
                continue
            previous = task["status"]
            task.update(status="completed", cached=True, progress=1, finished_at="2026-11-14T12:00:00Z",
                        message="verified cache", catalog={"electrode_count": 64})
            for field in ("workerPid", "starting", "backendId"):
                task.pop(field, None)
            changes.append({"id": task["id"], "from": previous, "to": "completed", "cache_sha256": cache_sha})
        text = json.dumps(proposed, ensure_ascii=False, separators=(",", ":"))
        return {"inspector_schema": "eeglayoutlab-offline-inspection/1", "source_files_sha256": "d" * 64,
                "runtime": {"root": str(root), "python": python}, "changes": changes, "retained": [],
                "observations": [{"cache_sha256": cache_sha}] if changes else [], "scientific_worker_launches": 0,
                "proposed_queue_json": text, "proposed_queue_sha256": service.digest(text.encode())}
    return inspect


def test_preview_then_atomic_apply_preserves_science_owners_annotations_and_exact_proposed_bytes(fixture, monkeypatch):
    root, directory, _, canary = fixture
    original, science = (directory / "queue.json").read_bytes(), canary.read_bytes()
    monkeypatch.setattr(service, "inspect", inspector())
    output = plan_path(root)
    preview = service.reconcile(root, directory, output)
    assert preview["mode"] == "preview" and preview["apply_allowed"]
    assert (directory / "queue.json").read_bytes() == original
    plan = json.loads(output.read_bytes())
    assert "e" * 64 not in output.read_text()  # No raw session secret in the plan.
    applied = service.reconcile(root, directory, output, execute=True, expected_queue_sha256=preview["queue_sha256"])
    assert applied["executed"] and applied["scientific_worker_launches"] == 0
    assert (directory / "queue.json").read_bytes() == plan["proposed_queue_json"].encode()
    assert Path(applied["backup"]).read_bytes() == original
    repaired = json.loads((directory / "queue.json").read_bytes())["tasks"][0]
    assert repaired["owners"] == ["owner-a", "owner-b"]
    assert repaired["annotation_refs"] == {"owner-a": ["b" * 64]}
    assert repaired["request"]["retained_float"] == 1.0000000000000002
    assert canary.read_bytes() == science
    assert not (directory / "acquiring.lock").exists()


def test_both_locks_cover_inspection_and_atomic_write(fixture, monkeypatch):
    root, directory, _, _ = fixture
    real_inspect, real_atomic = inspector(), service.atomic_queue
    seen = []
    def check_locks():
        assert (directory / "acquiring.lock").exists()
        with (root / service.NATIVE_LOCK).open("rb") as competing:
            with pytest.raises(BlockingIOError):
                fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def inspected(*args):
        check_locks(); seen.append("inspect"); return real_inspect(*args)
    def atomic(*args):
        check_locks(); seen.append("atomic"); return real_atomic(*args)
    monkeypatch.setattr(service, "inspect", inspected)
    monkeypatch.setattr(service, "atomic_queue", atomic)
    output = plan_path(root)
    preview = service.reconcile(root, directory, output)
    service.reconcile(root, directory, output, execute=True, expected_queue_sha256=preview["queue_sha256"])
    assert seen == ["inspect", "inspect", "atomic"]


@pytest.mark.parametrize("reason", ["not_maintained", "unknown_spawn", "alive_worker", "invalid_pid"])
def test_uncertain_or_unmaintained_queue_can_be_previewed_but_never_applied(fixture, monkeypatch, reason):
    root, directory, state, _ = fixture
    if reason == "not_maintained":
        del state["maintenance"]
    elif reason == "unknown_spawn":
        state["tasks"][0].pop("workerPid"); state["tasks"][0]["starting"] = True
    else:
        state["tasks"][0]["workerPid"] = os.getpid() if reason == "alive_worker" else 0
    dump(directory / "queue.json", state)
    original = (directory / "queue.json").read_bytes()
    monkeypatch.setattr(service, "inspect", inspector())
    output = plan_path(root)
    preview = service.reconcile(root, directory, output)
    assert not preview["apply_allowed"] and preview["blocked_reasons"]
    with pytest.raises(ValueError, match="blocked"):
        service.reconcile(root, directory, output, execute=True, expected_queue_sha256=preview["queue_sha256"])
    assert (directory / "queue.json").read_bytes() == original


def test_live_queue_owner_and_native_lock_are_not_stolen(fixture, monkeypatch):
    root, directory, _, _ = fixture
    monkeypatch.setattr(service, "inspect", inspector())
    dump(directory / "worker.lock", {"pid": os.getpid(), "token": "owner"})
    with pytest.raises(ValueError, match="owner"):
        service.reconcile(root, directory, plan_path(root))
    assert json.loads((directory / "worker.lock").read_bytes())["pid"] == os.getpid()
    assert not (directory / "acquiring.lock").exists()
    (directory / "worker.lock").unlink()
    native = root / service.NATIVE_LOCK; native.parent.mkdir(parents=True, exist_ok=True)
    with native.open("a+b") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="native"):
            service.reconcile(root, directory, plan_path(root))
    assert not (directory / "acquiring.lock").exists()


def test_apply_requires_original_queue_sha_and_rejects_changed_cache_proof(fixture, monkeypatch):
    root, directory, _, _ = fixture
    monkeypatch.setattr(service, "inspect", inspector())
    output = plan_path(root)
    preview = service.reconcile(root, directory, output)
    with pytest.raises(ValueError, match="expected-queue"):
        service.reconcile(root, directory, output, execute=True)
    monkeypatch.setattr(service, "inspect", inspector(cache_sha="f" * 64))
    with pytest.raises(ValueError, match="no longer matches"):
        service.reconcile(root, directory, output, execute=True, expected_queue_sha256=preview["queue_sha256"])
    with (directory / "queue.json").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="Queue bytes changed"):
        service.reconcile(root, directory, output, execute=True, expected_queue_sha256=preview["queue_sha256"])


def test_unchanged_queue_is_not_reformatted_or_backed_up(fixture, monkeypatch):
    root, directory, state, _ = fixture
    state["tasks"][0]["status"] = "cancelled"
    dump(directory / "queue.json", state)
    original = (directory / "queue.json").read_bytes()
    monkeypatch.setattr(service, "inspect", inspector())
    output = plan_path(root)
    preview = service.reconcile(root, directory, output)
    result = service.reconcile(root, directory, output, execute=True, expected_queue_sha256=preview["queue_sha256"])
    assert result["executed"] is False and result["backup"] is None
    assert (directory / "queue.json").read_bytes() == original


def test_python_guard_rejects_proposal_changes_to_owners_or_cancelled_receipts(fixture, monkeypatch):
    root, directory, state, _ = fixture
    original_inspector = inspector()
    def malicious(*args):
        result = original_inspector(*args)
        proposed = json.loads(result["proposed_queue_json"])
        proposed["tasks"][0]["owners"] = ["wrong-owner"]
        result["proposed_queue_json"] = json.dumps(proposed)
        return result
    monkeypatch.setattr(service, "inspect", malicious)
    with pytest.raises(ValueError, match="protected receipt"):
        service.reconcile(root, directory, plan_path(root))
    state["tasks"][0]["status"] = "cancelling"
    altered = copy.deepcopy(state); altered["tasks"][0]["status"] = "completed"
    with pytest.raises(ValueError, match="ineligible"):
        service.validate_proposal(state, {"proposed_queue_json": json.dumps(altered), "changes": [{"id": "receipt"}]})


def test_queue_and_plan_links_are_rejected(fixture, monkeypatch, tmp_path):
    root, directory, _, _ = fixture
    monkeypatch.setattr(service, "inspect", inspector())
    original = directory / "queue.json"; moved = directory / "original.json"
    original.rename(moved); original.symlink_to(moved)
    with pytest.raises(ValueError, match="Symlink"):
        service.reconcile(root, directory, plan_path(root))
    assert not (directory / "acquiring.lock").exists()


def test_actual_node_inspector_reads_legacy_queue_without_initializing_or_starting_service(fixture):
    root, directory, state, canary = fixture
    state.pop("maintenance"); state["tasks"][0]["status"] = "queued"
    state["tasks"][0].pop("workerPid")
    dump(directory / "queue.json", state)
    original, scientific = (directory / "queue.json").read_bytes(), canary.read_bytes()
    preview = service.reconcile(root, directory, plan_path(root))
    assert not preview["apply_allowed"] and preview["changes"] == []
    assert (directory / "queue.json").read_bytes() == original and canary.read_bytes() == scientific
    assert not (directory / "worker.lock").exists()
