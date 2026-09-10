"""Installation boundary checks; no package downloads or runtime mutations."""
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("runtime_bootstrap", ROOT / "scripts/bootstrap_runtime.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def test_frozen_conda_artifact_urls_and_hashes_match_manifest():
    manifest = json.loads((ROOT / "configs/runtime/manifest.json").read_text())
    explicit = (ROOT / "configs/runtime/conda-osx-arm64.explicit.txt").read_text().splitlines()
    urls = [line for line in explicit if line and not line.startswith("#") and line != "@EXPLICIT"]
    assert len(urls) == manifest["conda_package_count"] == 193
    assert urls == [row["url"] + "#" + row["sha256"] for row in manifest["conda_packages"]]
    assert all(len(row["sha256"]) == 64 for row in manifest["conda_packages"])
    upstream = manifest["official_environment"]
    assert bootstrap.sha256(ROOT / "configs/runtime" / upstream["filename"]) == upstream["sha256"]


def test_prefix_rejects_repository_root_and_external_environment(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    monkeypatch.setattr(bootstrap, "ROOT", root)
    for path in (root, root / ".runtime", tmp_path / "shared-conda"):
        with pytest.raises(ValueError):
            bootstrap.safe_prefix(path)
    assert bootstrap.safe_prefix(root / ".runtime/new-env") == root / ".runtime/new-env"


def test_runtime_symlink_cannot_target_an_existing_environment(tmp_path, monkeypatch):
    root, external = tmp_path / "checkout", tmp_path / "existing-env"
    root.mkdir()
    external.mkdir()
    (root / ".runtime").symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(bootstrap, "ROOT", root)
    with pytest.raises(ValueError, match="symbolic"):
        bootstrap.safe_prefix(root / ".runtime/new-env")


@pytest.mark.skipif(platform.system() != "Darwin" or platform.machine() != "arm64", reason="frozen native runtime platform")
def test_dry_run_does_not_create_the_planned_prefix():
    prefix = ROOT / ".runtime/test-read-only-plan"
    assert not prefix.exists()
    result = subprocess.run([sys.executable, str(ROOT / "scripts/bootstrap_runtime.py"), "--prefix", str(prefix)],
                            text=True, capture_output=True, timeout=30)
    if "Install an arm64 Conda distribution" in result.stderr:
        pytest.skip("No external Conda manager is installed")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["mode"] == "plan"
    assert not prefix.exists()
