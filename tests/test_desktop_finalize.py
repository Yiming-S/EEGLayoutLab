"""Final sealing guards and a mocked packaging round trip, without Xcode."""
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("desktop_finalize_test", ROOT / "desktop/finalize.py")
finalizer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(finalizer)


@pytest.fixture
def completed_build(tmp_path, monkeypatch):
    repository = tmp_path / "checkout"
    repository.mkdir()
    (repository / "LICENSE").write_text("GNU General Public License version 3.\n")
    (repository / "THIRD_PARTY_NOTICES.md").write_text("Current third-party notices.\n")
    monkeypatch.setattr(finalizer, "ROOT", repository)
    source = tmp_path / "input"
    resources = source / "EEG Layout Lab.app/Contents/Resources"
    scripts = resources / "desktop"
    scripts.mkdir(parents=True)
    payload = resources / "payload.tar.gz"
    payload.write_bytes(b"unchanged scientific payload")
    script = scripts / "bootstrap.mjs"
    script.write_text("old bootstrap\n")
    (resources / "LICENSE").write_text("Previous license.\n")
    (resources / "THIRD_PARTY_NOTICES.md").write_text("Previous third-party notices.\n")
    (resources / "node/bin").mkdir(parents=True)
    (resources / "node/bin/node").write_bytes(b"node binary")
    executables = resources.parent / "MacOS"
    executables.mkdir()
    (executables / "EEG Layout Lab").write_bytes(b"native binary")
    release = {"name": "EEG Layout Lab", "version": "0.1.0", "build": "1",
               "bundleIdentifier": "com.yimingshen.eeglayoutlab"}
    (resources.parent / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleExecutable": "EEG Layout Lab", "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1", "CFBundleIdentifier": release["bundleIdentifier"],
    }))
    manifest = {"schema": "eeglayoutlab-desktop/1", "version": "0.1.0", "build": "1",
                "payload": {"file": "payload.tar.gz", "sha256": finalizer.digest(payload), "unpackedBytes": 2000},
                "assets": [{"file": "desktop/bootstrap.mjs", "sha256": finalizer.digest(script)}]
                + [{"file": name, "sha256": finalizer.digest(resources / name)}
                   for name in ("LICENSE", "THIRD_PARTY_NOTICES.md")]}
    (resources / "desktop-manifest.json").write_text(json.dumps(manifest))
    report = {"schema": "eeglayoutlab-desktop-build/1", "release": release,
              "payloadBytes": payload.stat().st_size, "sourceFileHashes": {"src/example.py": "preserve"},
              "noticeSha256": {name: finalizer.digest(resources / name)
                               for name in ("LICENSE", "THIRD_PARTY_NOTICES.md")},
              "deliverables": [{"file": "previous.zip", "sha256": "old"}]}
    (source / "build-report.json").write_text(json.dumps(report))
    return source


def test_rejects_changed_payload(completed_build):
    payload = completed_build / "EEG Layout Lab.app/Contents/Resources/payload.tar.gz"
    payload.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Payload SHA-256"):
        finalizer.validate_build(completed_build)


def test_rejects_changed_bootstrap(completed_build):
    script = completed_build / "EEG Layout Lab.app/Contents/Resources/desktop/bootstrap.mjs"
    script.write_text("tampered")
    with pytest.raises(ValueError, match="Bootstrap asset SHA-256"):
        finalizer.validate_build(completed_build)


def test_rejects_external_resource_link(completed_build, tmp_path):
    external = tmp_path / "private"
    external.write_text("private")
    (completed_build / "EEG Layout Lab.app/Contents/Resources/leak").symlink_to(external)
    with pytest.raises(ValueError, match="external or broken link"):
        finalizer.validate_build(completed_build)


def test_rejects_escape_path(tmp_path):
    with pytest.raises(ValueError, match="escapes Resources"):
        finalizer.contained_file(tmp_path, "../outside")


def test_requires_fresh_disjoint_output(completed_build, tmp_path):
    with pytest.raises(ValueError, match="already exists"):
        finalizer.prepare_output(completed_build, completed_build)
    with pytest.raises(ValueError, match="must not contain"):
        finalizer.prepare_output(completed_build, completed_build / "export")
    outside = tmp_path / "output"
    finalizer.prepare_output(completed_build, outside)
    assert outside.is_dir()


@pytest.mark.parametrize("rebuild_shell", [False, True])
def test_reseals_copy_preserving_input_and_payload(completed_build, tmp_path, monkeypatch, rebuild_shell):
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "bootstrap.mjs").write_text("new bootstrap\n")
    (desktop / "bootstrap-support.mjs").write_text("new helper\n")
    (desktop / "START_HERE.md").write_text("Open the app.\n")
    (desktop / "START_HERE.zh-CN.md").write_text("Open the app.\n")
    (desktop / "macos").mkdir()
    (desktop / "macos/App.swift").write_text("// Current native shell source.\n")
    monkeypatch.setattr(finalizer, "DESKTOP", desktop)
    calls = []

    def fake_run(args):
        args = list(map(str, args))
        calls.append(args)
        if args[0] == "ditto" and len(args) == 3:
            shutil.copytree(args[1], args[2], symlinks=True)
        elif args[0] == "ditto" and "-c" in args:
            Path(args[-1]).write_bytes(b"zip")
        elif args[0] == "hdiutil":
            Path(args[-1]).write_bytes(b"dmg")
        elif args[:2] == ["xcrun", "swiftc"]:
            assert Path(args[-3]).read_text() == "// Current native shell source.\n"
            Path(args[-1]).write_bytes(b"rebuilt native binary")
        elif args[0] == "codesign" and "--force" in args and args[-1].endswith(".app"):
            resources = Path(args[-1]) / "Contents/Resources"
            assert (resources / "LICENSE").read_bytes() == (finalizer.ROOT / "LICENSE").read_bytes()
            assert (resources / "THIRD_PARTY_NOTICES.md").read_bytes() == (finalizer.ROOT / "THIRD_PARTY_NOTICES.md").read_bytes()

    monkeypatch.setattr(finalizer, "run", fake_run)
    before = {str(path.relative_to(completed_build)): finalizer.digest(path)
              for path in completed_build.rglob("*") if path.is_file()}
    output = tmp_path / "export"
    report = finalizer.finalize(completed_build, output, rebuild_shell=rebuild_shell, dmg=True)
    after = {str(path.relative_to(completed_build)): finalizer.digest(path)
             for path in completed_build.rglob("*") if path.is_file()}
    assert before == after
    assert report["sourceFileHashes"] == {"src/example.py": "preserve"}
    assert report["finalization"]["payloadUnchanged"] is True
    assert report["notarized"] is False
    resources = output / "EEG Layout Lab.app/Contents/Resources"
    assert (resources / "payload.tar.gz").read_bytes() == b"unchanged scientific payload"
    updated = json.loads((resources / "desktop-manifest.json").read_text())
    asset_hashes = {asset["file"]: asset["sha256"] for asset in updated["assets"]}
    assert len(updated["assets"]) == (5 if rebuild_shell else 4)
    assert (resources / "desktop/bootstrap.mjs").read_text() == "new bootstrap\n"
    assert (output / "START_HERE.zh-CN.md").is_file()
    assert (output / "START_HERE.md").is_file()
    assert (output / "build-work/dmg-root/START_HERE.zh-CN.md").is_file()
    assert (output / "build-work/dmg-root/START_HERE.md").is_file()
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        expected = (finalizer.ROOT / name).read_bytes()
        assert (resources / name).read_bytes() == expected
        assert (output / name).read_bytes() == expected
        assert (output / "build-work/dmg-root" / name).read_bytes() == expected
        assert (output / "build-work/dmg-root/EEG Layout Lab.app/Contents/Resources" / name).read_bytes() == expected
        assert report["finalization"]["noticeSha256"][name] == finalizer.digest(finalizer.ROOT / name)
        assert report["noticeSha256"][name] == asset_hashes[name] == finalizer.digest(resources / name)
        assert f"{finalizer.digest(output / name)}  {name}\n" in (output / "SHA256SUMS.txt").read_text()
    assert (output / "build-work/dmg-root/Applications").readlink() == Path("/Applications")
    assert len(report["deliverables"]) == 2
    assert ["lipo", str(output / "EEG Layout Lab.app/Contents/MacOS/EEG Layout Lab"),
            "-verify_arch", "arm64"] in calls
    assert any(args[:3] == ["codesign", "--verify", "--deep"] for args in calls)
    assert any("swiftc" in args for args in calls) is rebuild_shell
    if rebuild_shell:
        source_copy = resources / "desktop-source/App.swift"
        assert source_copy.read_bytes() == (desktop / "macos/App.swift").read_bytes()
        assert report["finalization"]["nativeShellSourceFile"] == "desktop-source/App.swift"
        assert report["finalization"]["nativeShellSourceSha256"] == finalizer.digest(source_copy)
    else:
        assert report["finalization"]["nativeShellSourceFile"] is None
        assert not (resources / "desktop-source").exists()
    finalizer.validate_build(output)
