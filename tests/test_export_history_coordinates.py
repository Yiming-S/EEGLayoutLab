"""Historical exact-bank coordinate export has no nearest-point fallback."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("export_history_coordinates", ROOT / "scripts/export_history_coordinates.py")
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


@pytest.fixture
def bank(tmp_path):
    xyz = np.arange(384, dtype=float).reshape(128, 3) / 7
    path = tmp_path / "bank.npz"
    np.savez(path, candidate_xyz_mm=xyz)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    pointer = tmp_path / "results/v2/current_multiregion_bank.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({"sha256": digest, "path": "bank.npz"}))
    return tmp_path, digest, xyz, path, pointer


def test_exact_coordinate_values_and_both_orders_preserved(bank):
    root, digest, xyz, path, pointer = bank
    initial_bytes = path.read_bytes(), pointer.read_bytes()
    groups = [list(range(63, -1, -1)), list(range(64, 128))]
    result = exporter.export_history_coordinates(root, digest, groups)
    np.testing.assert_array_equal(result["xyz_mm"][0], xyz[groups[0]])
    np.testing.assert_array_equal(result["xyz_mm"][1], xyz[groups[1]])
    assert result["bank_sha256"] == digest
    assert initial_bytes == (path.read_bytes(), pointer.read_bytes())


@pytest.mark.parametrize("groups", [
    [list(range(64))] * 101,
    [list(range(63))],
    [list(range(63)) + [0]],
    [list(range(63)) + [128]],
    [list(range(63)) + [-1]],
    [list(range(63)) + [True]],
    [list(range(63)) + [63.]],
    list(range(64)),
])
def test_invalid_groups_rejected(bank, groups):
    with pytest.raises(ValueError):
        exporter.export_history_coordinates(bank[0], bank[1], groups)


def test_mismatched_historical_sha_rejected(bank):
    with pytest.raises(ValueError, match="Historical bank"):
        exporter.export_history_coordinates(bank[0], "0" * 64, [list(range(64))])


def test_corrupt_bank_and_duplicate_coordinate_rows_rejected(bank):
    root, digest, xyz, path, pointer = bank
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="file SHA256"):
        exporter.export_history_coordinates(root, digest, [list(range(64))])
    xyz[1] = xyz[0]
    np.savez(path, candidate_xyz_mm=xyz)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    pointer.write_text(json.dumps({"sha256": digest, "path": "bank.npz"}))
    with pytest.raises(ValueError, match="duplicate physical"):
        exporter.export_history_coordinates(root, digest, [list(range(64))])


def test_cli_stdout_contract_and_empty_batch(bank):
    root, digest, xyz, _, _ = bank
    process = subprocess.run([sys.executable, str(ROOT / "scripts/export_history_coordinates.py"),
        "--repository-root", str(root), "--bank-sha256", digest, "--indices", json.dumps([list(range(64))])],
        capture_output=True, text=True, check=False)
    assert process.returncode == 0 and process.stderr == ""
    result = json.loads(process.stdout)
    assert set(result) == {"xyz_mm", "bank_sha256"}
    np.testing.assert_array_equal(result["xyz_mm"], xyz[None, :64])
    assert exporter.export_history_coordinates(root, digest, []) == {"xyz_mm": [], "bank_sha256": digest}
