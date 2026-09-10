"""Offline bundle authentication, portability, and archive boundary checks."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/data_bundle.py"
SPEC = importlib.util.spec_from_file_location("data_bundle", SCRIPT)
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


class DataBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / "source"
        self.target = self.base / "target"
        self.source.mkdir()
        self.target.mkdir()
        self.payload = {
            "data/external/example/mesh.bin": b"frozen mesh\x00\x01",
            "results/v2/campaigns/" + "a" * 130 + "/report.json": b'{"value":1}\n',
            "data/SOURCES.md": b"Attribution and source declaration\n",
        }
        records = []
        for name, data in self.payload.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            records.append({"path": name, "size_bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()})
        self.manifest = {"schema_version": bundle.SCHEMA, "files": records,
                         "total_size_bytes": sum(len(data) for data in self.payload.values())}
        self.raw = json.dumps(self.manifest, sort_keys=True).encode()
        for root in (self.source, self.target):
            (root / "data").mkdir(exist_ok=True)
            (root / bundle.MANIFEST).write_bytes(self.raw)
        self.archive = self.base / "data.tar.gz"

    def members(self):
        return [(bundle.MANIFEST, self.raw, tarfile.REGTYPE, "")] + [
            (name, data, tarfile.REGTYPE, "") for name, data in self.payload.items()]

    def make_archive(self, members):
        with tarfile.open(self.archive, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for name, data, kind, link in members:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.linkname = link
                info.size = len(data) if kind == tarfile.REGTYPE else 0
                archive.addfile(info, io.BytesIO(data) if kind == tarfile.REGTYPE else None)

    def assert_target_unmodified(self):
        self.assertEqual((self.target / bundle.MANIFEST).read_bytes(), self.raw)
        self.assertEqual([p for p in self.target.rglob("*") if p.is_file()],
                         [self.target / bundle.MANIFEST])

    def test_roundtrip_idempotent_and_reproducible_export(self):
        unrelated_name = "results/v2/design_evaluation_jobs/personal/cache.json"
        for root in (self.source, self.target):
            unrelated = root / unrelated_name
            unrelated.parent.mkdir(parents=True, exist_ok=True)
            unrelated.write_bytes(b"unrelated local job")
        first = bundle.export_bundle(self.source, self.archive)
        second_file = self.base / "again.tar.gz"
        second = bundle.export_bundle(self.source, second_file)
        self.assertEqual(first["sha256"], second["sha256"])
        installed = bundle.install_bundle(self.target, self.archive)
        self.assertEqual(installed["installed_files"], len(self.payload))
        for name, data in self.payload.items():
            self.assertEqual((self.target / name).read_bytes(), data)
        self.assertEqual(bundle.verify(self.target)["files"], len(self.payload))
        self.assertEqual(bundle.install_bundle(self.target, self.archive)["installed_files"], 0)
        self.assertEqual((self.target / unrelated_name).read_bytes(), b"unrelated local job")
        with tarfile.open(self.archive) as archive:
            self.assertEqual(set(archive.getnames()), set(self.payload) | {bundle.MANIFEST})
            for member in archive:
                self.assertTrue(member.isfile())
                self.assertEqual((member.uid, member.gid, member.mtime, member.uname, member.gname),
                                 (0, 0, 0, "", ""))

    def test_verify_missing_and_changed_files(self):
        with self.assertRaisesRegex(bundle.BundleError, "missing"):
            bundle.verify(self.target)
        path = self.source / next(iter(self.payload))
        path.write_bytes(b"corrupted")
        with self.assertRaisesRegex(bundle.BundleError, "mismatch"):
            bundle.verify(self.source)
        with self.assertRaises(bundle.BundleError):
            bundle.export_bundle(self.source, self.archive)
        self.assertFalse(self.archive.exists())

    def test_export_does_not_replace_existing_output(self):
        self.archive.write_bytes(b"existing")
        with self.assertRaisesRegex(bundle.BundleError, "already exists"):
            bundle.export_bundle(self.source, self.archive)
        self.assertEqual(self.archive.read_bytes(), b"existing")

    def test_conflict_rejected_before_any_install(self):
        bundle.export_bundle(self.source, self.archive)
        # Last manifest entry conflicts: earlier valid entries must stay absent.
        conflict = self.target / "data/SOURCES.md"
        conflict.write_bytes(b"existing user content")
        with self.assertRaisesRegex(bundle.BundleError, "overwrite"):
            bundle.install_bundle(self.target, self.archive)
        self.assertEqual(conflict.read_bytes(), b"existing user content")
        self.assertFalse((self.target / "data/external").exists())
        self.assertFalse((self.target / "results").exists())

    def test_archive_corruption_rejected_before_any_install(self):
        members = self.members()
        name, data, kind, link = members[-1]
        members[-1] = (name, b"x" * len(data), kind, link)
        self.make_archive(members)
        with self.assertRaisesRegex(bundle.BundleError, "SHA256 mismatch"):
            bundle.install_bundle(self.target, self.archive)
        self.assert_target_unmodified()

    def test_archive_cannot_supply_its_own_trust_manifest(self):
        malicious = self.raw.replace(b'"size_bytes":', b'"other_size":', 1)
        members = self.members()
        members[0] = (bundle.MANIFEST, malicious, tarfile.REGTYPE, "")
        self.make_archive(members)
        with self.assertRaisesRegex(bundle.BundleError, "mismatch"):
            bundle.install_bundle(self.target, self.archive)
        self.assert_target_unmodified()

    def test_unknown_traversal_and_absolute_members_rejected(self):
        for name in ("../escape", "/absolute", "data/../escape", "data\\escape", "C:/escape",
                     "results//v2/file", "./data/SOURCES.md", "src/overwrite.py"):
            with self.subTest(name=name):
                self.make_archive(self.members() + [(name, b"attack", tarfile.REGTYPE, "")])
                with self.assertRaises(bundle.BundleError):
                    bundle.install_bundle(self.target, self.archive)
                self.assert_target_unmodified()

    def test_links_devices_and_directories_rejected(self):
        name = next(iter(self.payload))
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE,
                     tarfile.CHRTYPE, tarfile.BLKTYPE):
            with self.subTest(kind=kind):
                self.make_archive([(bundle.MANIFEST, self.raw, tarfile.REGTYPE, ""),
                                   (name, b"", kind, "../../outside" if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else "")])
                with self.assertRaisesRegex(bundle.BundleError, "Non-regular"):
                    bundle.install_bundle(self.target, self.archive)
                self.assert_target_unmodified()

    def test_duplicate_missing_and_wrong_size_members_rejected(self):
        cases = [self.members() + [self.members()[-1]], self.members()[:-1],
                 self.members()[:-1] + [("data/SOURCES.md", b"wrong-size", tarfile.REGTYPE, "")]]
        for members in cases:
            with self.subTest(count=len(members)):
                self.make_archive(members)
                with self.assertRaises(bundle.BundleError):
                    bundle.install_bundle(self.target, self.archive)
                self.assert_target_unmodified()

    def test_destination_symlink_and_dangling_symlink_rejected(self):
        bundle.export_bundle(self.source, self.archive)
        outside = self.base / "outside"
        outside.mkdir()
        link = self.target / "data/external"
        for target in (outside, self.base / "nonexistent"):
            with self.subTest(target=target.name):
                link.symlink_to(target, target_is_directory=True)
                with self.assertRaisesRegex(bundle.BundleError, "Symlink"):
                    bundle.install_bundle(self.target, self.archive)
                link.unlink()
                self.assertFalse(any(outside.iterdir()))
                self.assert_target_unmodified()

    def test_source_and_archive_symlinks_rejected(self):
        bundle.export_bundle(self.source, self.archive)
        archive_link = self.base / "linked.tar.gz"
        archive_link.symlink_to(self.archive)
        with self.assertRaisesRegex(bundle.BundleError, "symlink"):
            bundle.install_bundle(self.target, archive_link)
        path = self.source / "data/SOURCES.md"
        saved = self.base / "original"
        path.rename(saved)
        path.symlink_to(saved)
        with self.assertRaisesRegex(bundle.BundleError, "Symlink"):
            bundle.verify(self.source)

    def test_invalid_manifest_paths_sizes_hashes_and_collisions(self):
        invalid = []
        for path in ("../escape", "README.md", "results/v2/../escape"):
            changed = json.loads(self.raw)
            changed["files"][0]["path"] = path
            invalid.append(changed)
        for field, value in (("size_bytes", -1), ("size_bytes", True), ("sha256", "wrong")):
            changed = json.loads(self.raw)
            changed["files"][0][field] = value
            invalid.append(changed)
        changed = json.loads(self.raw)
        changed["files"].append(changed["files"][0].copy())
        invalid.append(changed)
        changed = json.loads(self.raw)
        changed["files"][1]["path"] = changed["files"][0]["path"] + "/child"
        invalid.append(changed)
        changed = json.loads(self.raw)
        changed["total_size_bytes"] += 1
        invalid.append(changed)
        for manifest in invalid:
            with self.subTest(manifest=manifest):
                (self.target / bundle.MANIFEST).write_text(json.dumps(manifest))
                with self.assertRaises(bundle.BundleError):
                    bundle.load_manifest(self.target)


if __name__ == "__main__":
    unittest.main()
