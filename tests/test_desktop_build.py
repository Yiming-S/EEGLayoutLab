"""Read-only build-input guards; no real runtime install or application signing."""
import importlib.util
import json
from pathlib import Path
import subprocess

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


def test_project_staging_packages_current_sources_and_docs_without_ignored_files(tmp_path, monkeypatch):
    repository = tmp_path / "checkout"
    repository.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    (repository / ".gitignore").write_text("node_modules/\ndist/\n.runtime/\noutputs/\n.env*\n")
    tracked = repository / "webapp/app/page.tsx"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("export const label = 'old';\n")
    subprocess.run(["git", "add", ".gitignore", "webapp/app/page.tsx"], cwd=repository, check=True)
    tracked.write_text("export const label = 'current';\n")
    sources = {
        "webapp/components/new-feature.tsx": "export const feature = true;\n",
        "src/compact_eeg/new_feature.py": "feature = True\n",
        "README.md": "Yiming Shen, PhD; Yi Wang, PhD\n",
        "docs/server-deployment.md": "Deployment preparation.\n",
        "pyproject.toml": "[project]\nname = 'fixture'\n",
        "THIRD_PARTY_NOTICES.md": "Third-party notices.\n",
        "data/SOURCES.md": "Model sources.\n",
        "data/manifest.json": json.dumps({"files": []}),
    }
    excluded = {
        "webapp/.env.production": "SECRET=private\n",
        "webapp/dist/old-bundle.js": "stale build\n",
        ".runtime/private.txt": "runtime state\n",
        "outputs/private.txt": "private output\n",
        "private.txt": "outside project allowlist\n",
    }
    for name, content in {**sources, **excluded}.items():
        path = repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    modules = repository / "webapp/node_modules/fixture-dependency"
    modules.mkdir(parents=True)
    (modules / "package.json").write_text('{"name":"fixture-dependency"}\n')
    monkeypatch.setattr(builder, "ROOT", repository)
    destination = tmp_path / "payload"
    identities, data = builder.stage_project(destination)
    assert data == {"files": []}
    assert (destination / "webapp/app/page.tsx").read_text() == tracked.read_text()
    for name, content in sources.items():
        assert (destination / name).read_text() == content
        assert identities[name] == builder.digest(repository / name)
    for name in excluded:
        assert not (destination / name).exists()
        assert name not in identities
    assert "webapp/node_modules/fixture-dependency/package.json" not in identities
    assert (destination / "webapp/node_modules/fixture-dependency/package.json").is_file()
