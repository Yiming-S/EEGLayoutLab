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


def test_linux_lock_files_agree_and_pin_every_wheel_by_hash():
    manifest = json.loads((ROOT / "configs/runtime/manifest-linux-64.json").read_text())
    assert manifest["schema"] == "eeglayoutlab-runtime-lock/1" and manifest["platform"] == "linux-64"
    assert manifest["python"] == "3.11.14" and manifest["simnibs"] is None
    explicit = (ROOT / "configs/runtime/conda-linux-64.explicit.txt").read_text().splitlines()
    urls = [line for line in explicit if line and not line.startswith("#") and line != "@EXPLICIT"]
    assert len(urls) == manifest["conda_package_count"]
    assert urls == [row["url"] + "#" + row["sha256"] for row in manifest["conda_packages"]]
    assert all(row["url"].startswith("https://conda.anaconda.org/conda-forge/") and "/osx-" not in row["url"]
               for row in manifest["conda_packages"])
    versions = {row["name"]: row["version"] for row in manifest["conda_packages"]}
    # Same numerical versions as the macOS lock.
    assert (versions["python"], versions["numpy"], versions["scipy"], versions["threadpoolctl"]) == ("3.11.14", "2.3.0", "1.17.1", "3.6.0")
    wheels = [line for line in (ROOT / "configs/runtime/pip-linux-64.txt").read_text().splitlines() if line and not line.startswith("#")]
    assert len(wheels) == len(manifest["pip_distributions"])
    assert all(" --hash=sha256:" in line for line in wheels)
    for asset in manifest["artifacts"]:
        assert any(line.startswith(asset["name"] + " @ " + asset["url"] + " --hash=sha256:" + asset["sha256"]) for line in wheels)
    assert "simnibs" not in {row["name"].lower() for row in manifest["pip_distributions"]} | set(versions)


def test_platform_lock_selection_keeps_the_macos_names():
    mac = bootstrap.platform_lock("Darwin", "arm64")
    assert (mac["manifest"], mac["conda"], mac["pip"], mac["prefix"]) == (
        "manifest.json", "conda-osx-arm64.explicit.txt", "pip-macos-arm64.txt", "simnibs-4.6.0")
    linux = bootstrap.platform_lock("Linux", "x86_64")
    assert (linux["subdir"], linux["prefix"]) == ("linux-64", "compute-linux-64")
    for lock in (mac, linux):
        for name in (lock["manifest"], lock["conda"], lock["pip"]):
            assert (ROOT / "configs/runtime" / name).is_file()
    with pytest.raises(ValueError, match="Rosetta"):
        bootstrap.platform_lock("Darwin", "x86_64")
    with pytest.raises(ValueError, match="No runtime lock"):
        bootstrap.platform_lock("Windows", "AMD64")


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


@pytest.mark.skipif((platform.system(), platform.machine()) not in bootstrap.PLATFORMS, reason="no runtime lock for this platform")
def test_dry_run_does_not_create_the_planned_prefix():
    prefix = ROOT / ".runtime/test-read-only-plan"
    assert not prefix.exists()
    result = subprocess.run([sys.executable, str(ROOT / "scripts/bootstrap_runtime.py"), "--prefix", str(prefix)],
                            text=True, capture_output=True, timeout=30)
    if "Install an arm64 Conda distribution" in result.stderr or "Install Miniforge or micromamba" in result.stderr:
        pytest.skip("No external Conda manager is installed")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["mode"] == "plan"
    assert not prefix.exists()
