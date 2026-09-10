from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from compact_eeg.artifacts import (  # noqa: E402
    TREE_MANIFEST_SCHEMA,
    atomic_write_json,
    build_tree_manifest,
    canonical_json_bytes,
    canonical_json_sha256,
    semantic_id,
    sha256_file,
)


class ArtifactTests(unittest.TestCase):
    def test_canonical_json_is_order_independent_compact_utf8(self) -> None:
        left = {"z": 3, "nested": {"b": 2, "a": 1}, "a": "é"}
        right = {"a": "é", "nested": {"a": 1, "b": 2}, "z": 3}
        expected = '{"a":"é","nested":{"a":1,"b":2},"z":3}'.encode("utf-8")
        self.assertEqual(canonical_json_bytes(left), expected)
        self.assertEqual(canonical_json_bytes(right), expected)
        self.assertEqual(
            canonical_json_sha256(left), hashlib.sha256(expected).hexdigest()
        )

    def test_canonical_json_rejects_ambiguous_or_nonfinite_values(self) -> None:
        with self.assertRaisesRegex(TypeError, "key"):
            canonical_json_bytes({1: "ambiguous"})
        with self.assertRaisesRegex(ValueError, "non-finite"):
            canonical_json_bytes({"value": float("nan")})
        with self.assertRaisesRegex(TypeError, "unsupported"):
            canonical_json_bytes({"value": {1, 2}})

    def test_semantic_id_is_stable_namespaced_and_full_length(self) -> None:
        value_a = {"mesh": "abc", "radius_mm": 35.0, "regions": ["PL", "PR"]}
        value_b = {"regions": ["PL", "PR"], "radius_mm": 35.0, "mesh": "abc"}
        first = semantic_id("layout", value_a)
        self.assertEqual(first, semantic_id("layout", value_b))
        self.assertRegex(first, r"^layout_[0-9a-f]{64}$")
        self.assertNotEqual(first, semantic_id("task", value_a))
        self.assertNotEqual(first, semantic_id("layout", {**value_a, "radius_mm": 40.0}))
        with self.assertRaisesRegex(ValueError, "namespace"):
            semantic_id("Layout:unsafe", value_a)

    def test_atomic_write_json_publishes_exact_canonical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "nested" / "manifest.json"
            value = {"stage": 2, "inputs": ["mesh", "mask"]}
            digest = atomic_write_json(target, value)
            expected = canonical_json_bytes(value)
            self.assertEqual(target.read_bytes(), expected)
            self.assertEqual(digest, hashlib.sha256(expected).hexdigest())
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), value)

            replacement = {"stage": 3, "complete": False}
            replacement_digest = atomic_write_json(target, replacement)
            self.assertEqual(target.read_bytes(), canonical_json_bytes(replacement))
            self.assertEqual(replacement_digest, sha256_file(target))
            self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_sha256_file_hashes_regular_content_and_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "payload.bin"
            source.write_bytes(b"compact-eeg\x00artifact")
            self.assertEqual(
                sha256_file(source),
                hashlib.sha256(b"compact-eeg\x00artifact").hexdigest(),
            )
            with self.assertRaisesRegex(ValueError, "positive"):
                sha256_file(source, chunk_size=0)
            link = root / "payload-link.bin"
            try:
                link.symlink_to(source.name)
            except (NotImplementedError, OSError):
                return
            with self.assertRaisesRegex(ValueError, "symbolic"):
                sha256_file(link)

    def test_tree_manifest_is_relocatable_sorted_and_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as first_temp, tempfile.TemporaryDirectory() as second_temp:
            expected_files = {
                "a.txt": b"alpha",
                "nested/b.bin": b"beta\x00",
                "nested/c.json": b'{"value":1}',
            }
            for temporary in (first_temp, second_temp):
                root = Path(temporary)
                for relative, content in reversed(tuple(expected_files.items())):
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)

            first = build_tree_manifest(first_temp)
            second = build_tree_manifest(second_temp)
            self.assertEqual(first, second)
            self.assertEqual(first["schema_version"], TREE_MANIFEST_SCHEMA)
            self.assertEqual(first["file_count"], 3)
            self.assertEqual(first["total_bytes"], sum(map(len, expected_files.values())))
            self.assertEqual(
                [entry["path"] for entry in first["files"]], sorted(expected_files)
            )
            body = {key: value for key, value in first.items() if key != "tree_sha256"}
            self.assertEqual(first["tree_sha256"], canonical_json_sha256(body))

    def test_tree_manifest_excludes_exact_paths_and_subtrees(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "keep").mkdir()
            (root / "omit").mkdir()
            (root / "keep" / "data.txt").write_text("keep", encoding="utf-8")
            (root / "omit" / "data.txt").write_text("omit", encoding="utf-8")
            (root / "manifest.json").write_text("self", encoding="utf-8")
            manifest = build_tree_manifest(
                root, exclude_paths=("omit", "manifest.json")
            )
            self.assertEqual(
                [entry["path"] for entry in manifest["files"]],
                ["keep/data.txt"],
            )
            with self.assertRaisesRegex(ValueError, "relative"):
                build_tree_manifest(root, exclude_paths=(Path(temporary),))

    def test_tree_manifest_rejects_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "target.txt").write_text("target", encoding="utf-8")
            link = root / "link.txt"
            try:
                os.symlink("target.txt", link)
            except (NotImplementedError, OSError):
                self.skipTest("symbolic links are unavailable")
            with self.assertRaisesRegex(ValueError, "symbolic"):
                build_tree_manifest(root)


if __name__ == "__main__":
    unittest.main()
