"""Host observation cache preserves the original numerical runtime hash."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import runtime_identity_watch as watch


@pytest.fixture
def runtime(tmp_path):
    prefix = tmp_path / "runtime"
    locations = {"prefix": prefix, "executable": prefix / "bin/python", "packages": {}}
    paths = [locations["executable"], prefix / "conda-meta/environment.json", prefix / "lib/libmumps.so"]
    for name in watch.NATIVE_PACKAGES:
        folder = prefix / "site-packages" / name
        metadata = folder.parent / (name + "-1.dist-info") / "METADATA"
        locations["packages"][name] = {"root": folder, "origin": folder / "__init__.py", "metadata": [metadata]}
        paths.extend([folder / "__init__.py", metadata])
    paths.extend(locations["packages"]["simnibs"]["root"] / name for name in watch.SIMNIBS_SOURCE_FILES)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original bytes")
    return locations


def observe(runtime):
    return watch.observe_filesystem(runtime, search_paths=[runtime["prefix"] / "site-packages"], module_paths=[])


def test_snapshot_digest_is_exactly_the_existing_canonical_identity_hash(runtime):
    identity = {"schema": "reception-native-runtime/1", "python": "fixture", "thread_limit": 1, "nested": {"bytes": "哈希"}}
    result = watch.inspect_snapshot(identity_reader=lambda: identity, locations_reader=lambda: runtime,
        search_paths=[], module_paths=[])
    assert result["schema"] == "reception-runtime-digest/1"
    assert result["sha256"] == watch._json_sha(identity)
    assert result["watch"]["schema"] == watch.SCHEMA
    assert len(result["watch"]["entries"]) == len({entry[0] for entry in result["watch"]["entries"]})


@pytest.mark.parametrize("change", ["content", "add", "delete", "metadata", "shadow", "pth"])
def test_files_and_discovery_changes_during_hashing_are_rejected(runtime, change):
    source = runtime["packages"]["numpy"]["origin"]
    def identity():
        if change == "content": source.write_text("different bytes")
        if change == "add": (source.parent / "extra.py").write_text("new computation")
        if change == "delete": source.unlink()
        if change == "metadata": runtime["packages"]["numpy"]["metadata"][0].write_text("new distribution")
        if change == "shadow": (runtime["prefix"] / "site-packages/numpy.py").write_text("shadow")
        if change == "pth": (runtime["prefix"] / "site-packages/new.pth").write_text("/new/search/path")
        return {"identity": "not safe to retain"}
    with pytest.raises(ValueError, match="changed during"):
        watch.inspect_snapshot(identity_reader=identity, locations_reader=lambda: runtime,
            search_paths=[runtime["prefix"] / "site-packages"], module_paths=[])


def test_directory_and_file_symlink_chains_are_observed(runtime, tmp_path):
    source = runtime["packages"]["numpy"]["origin"]
    actual = tmp_path / "external"; actual.mkdir(); (actual / "module.py").write_text("version1")
    intermediate = tmp_path / "alias"; intermediate.symlink_to(actual, target_is_directory=True)
    source.unlink(); source.symlink_to(intermediate / "module.py")
    entries = {path: (full, stamp) for path, full, stamp in observe(runtime)["entries"]}
    assert entries[str(source)][0]
    assert entries[str(intermediate)][0]
    assert str(intermediate / "module.py") in entries
    assert str(actual / "module.py") in entries
    before = observe(runtime)
    (actual / "module.py").write_text("version2")
    assert observe(runtime) != before
    before = observe(runtime)
    another = tmp_path / "other"; another.mkdir(); (another / "module.py").write_text("version1")
    intermediate.unlink(); intermediate.symlink_to(another, target_is_directory=True)
    assert observe(runtime) != before


def test_ancestor_directory_ignores_unrelated_sibling_files(runtime, tmp_path):
    before = observe(runtime)
    (tmp_path / "unrelated-job-log").write_text("not a numerical input")
    assert observe(runtime) == before


def test_existing_metadata_discovery_files_and_module_code_are_observed(runtime):
    directory = runtime["prefix"] / "site-packages"
    other = directory / "other-1.dist-info"; other.mkdir(); metadata = other / "METADATA"; metadata.write_text("Name: other")
    custom = directory / "custom_import.py"; custom.write_text("existing customization")
    before = watch.observe_filesystem(runtime, search_paths=[directory], module_paths=[custom])
    entries = {entry[0] for entry in before["entries"]}
    assert str(metadata) in entries and str(custom) in entries
    metadata.write_text("Name: numpy")
    assert watch.observe_filesystem(runtime, search_paths=[directory], module_paths=[custom]) != before


def test_executed_compatibility_shim_is_observed_even_after_it_replaces_sys_modules(runtime, tmp_path, monkeypatch):
    scripts = tmp_path / "scripts"; scripts.mkdir()
    helper = scripts / "runtime_identity_watch.py"; helper.write_text("helper fixture")
    shim = scripts / "reception_forward_provider.py"; shim.write_text("old shim")
    monkeypatch.setattr(watch, "__file__", str(helper))
    before = observe(runtime)
    assert str(shim) in {path for path, _full, _stamp in before["entries"]}
    shim.write_text("new shim")
    assert observe(runtime) != before
