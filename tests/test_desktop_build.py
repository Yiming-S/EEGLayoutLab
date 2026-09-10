"""Read-only build-input guards; no real runtime install or application signing."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("desktop_builder_test", ROOT / "desktop/build.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_reused_runtime_requires_successful_relocation(tmp_path):
    (tmp_path / "portable-runtime-audit.json").write_text(json.dumps({
        "schema": "eeglayoutlab-portable-runtime/1", "status": "verification_failed", "source_unchanged": True,
    }))
    with pytest.raises(ValueError, match="has not passed"):
        builder.verify_staged_runtime(tmp_path)


def test_reused_runtime_binds_actual_file_bytes(tmp_path):
    package = tmp_path / "package.py"
    package.write_text("original = True\n")
    tools = builder.runtime_tools()
    audit = {"schema": "eeglayoutlab-portable-runtime/1", "status": "verified_on_build_mac_after_relocation",
             "source_unchanged": True, "staged_inventory_sha256": tools.inventory_digest(tools.inventory(tmp_path))}
    (tmp_path / "portable-runtime-audit.json").write_text(json.dumps(audit))
    assert builder.verify_staged_runtime(tmp_path) == audit
    package.write_text("original = False\n")
    with pytest.raises(ValueError, match="bytes differ"):
        builder.verify_staged_runtime(tmp_path)


def test_payload_refuses_external_symlinks(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (project / "leak").symlink_to(outside)
    with pytest.raises(ValueError, match="External payload link"):
        builder.archive_project(project, tmp_path / "payload.tar.gz")


def test_node_archive_must_match_pinned_digest(tmp_path):
    archive = tmp_path / "wrong.tar.gz"
    archive.write_bytes(b"not an official archive")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        builder.stage_node(archive, {"sha256": "0" * 64}, tmp_path / "resources", tmp_path / "work")
