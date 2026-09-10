"""Portable runtime staging invariants, without copying the 2.2 GB runtime."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("desktop_stage_runtime", ROOT / "desktop/runtime/stage_runtime.py")
stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage)


def test_source_never_becomes_its_own_staging_target(tmp_path):
    source = tmp_path / "original/.runtime/simnibs-4.6.0"
    (source / "bin").mkdir(parents=True)
    (source / "bin/python3.11").touch()
    (source / "conda-meta").mkdir()
    for destination, project in [(source, source.parent.parent), (source / ".runtime/simnibs-4.6.0", source)]:
        with pytest.raises(ValueError):
            stage.safe_locations(source, destination, project)
    project = tmp_path / "Other Mac workspace"
    destination = project / ".runtime/simnibs-4.6.0"
    assert stage.safe_locations(source, destination, project) == (source.resolve(), destination, project)


def test_editable_source_and_console_entrypoint_use_relative_paths(tmp_path):
    source = tmp_path / "developer/.runtime/simnibs-4.6.0"
    project = tmp_path / "relocated/EEG Layout Lab"
    destination = project / ".runtime/simnibs-4.6.0"
    site = destination / "lib/python3.11/site-packages"
    site.mkdir(parents=True)
    pth = site / "__editable__.compact_eeg-0.1.0.pth"
    pth.write_text(str(source.parent.parent / "src") + "\n")
    (destination / "bin").mkdir()
    entry = destination / "bin/pip"
    entry.write_text("#!" + str(source / "bin/python3.11") + "\nimport sys\n")
    entry.chmod(0o755)
    changes = stage.relocate_text(destination, source, project)
    assert len(changes) == 2
    assert (site / pth.read_text().strip()).resolve() == project / "src"
    assert str(tmp_path) not in pth.read_text() + entry.read_text()
    compile(entry.read_text(), str(entry), "exec")
    assert entry.stat().st_mode & 0o111


def test_unknown_external_pth_fails_closed(tmp_path):
    site = tmp_path / "stage/lib/python3.11/site-packages"
    site.mkdir(parents=True)
    (site / "unrelated.pth").write_text("/opt/shared/site-packages\n")
    with pytest.raises(ValueError, match="External .pth"):
        stage.relocate_text(tmp_path / "stage", tmp_path / "source", tmp_path / "project")


def test_internal_absolute_symlink_becomes_relative_without_touching_source(tmp_path):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "library").write_bytes(b"source")
    (destination / "library").write_bytes(b"source")
    (destination / "alias").symlink_to(source / "library")
    before = stage.inventory(source)
    stage.normalize_symlinks(source, destination)
    assert (destination / "alias").readlink() == Path("library")
    assert stage.inventory(source) == before


def test_unbundled_dynamic_library_fails_before_mutation(tmp_path, monkeypatch):
    destination = tmp_path / "destination"
    path = destination / "lib/test.dylib"
    monkeypatch.setattr(stage, "inspect_macho", lambda p: [("LC_LOAD_DYLIB", "/opt/other/unknown.dylib")])
    monkeypatch.setattr(stage, "run", lambda *a, **k: pytest.fail("must not mutate before finding dependencies"))
    with pytest.raises(ValueError, match="Unbundled native dependency"):
        stage.relocate_macho(path, tmp_path / "source", destination)


def test_macho_loader_parses_paths_with_spaces():
    output = """Load command 0
          cmd LC_RPATH
      cmdsize 96
         path /Users/Someone/My runtime/lib (offset 12)
Load command 1
          cmd LC_LOAD_DYLIB
      cmdsize 56
         name @rpath/libdmumps_seq.dylib (offset 24)
"""
    assert stage.parse_load_commands(output) == [("LC_RPATH", "/Users/Someone/My runtime/lib"), ("LC_LOAD_DYLIB", "@rpath/libdmumps_seq.dylib")]
