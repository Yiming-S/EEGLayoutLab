#!/usr/bin/env python3
"""Read exact frozen-bank coordinates for historical initial/final snapshots.

No FEM, interpolation, nearest-neighbour matching, or filesystem writes. The
caller must supply the historical snapshot's bank SHA, not an assumed current
identity. A mismatch is rejected even when the same indices remain in range.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
import numpy as np


def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export_history_coordinates(repository_root, bank_sha256, indices):
    """Return JSON-safe coordinate batches, preserving group and electrode order."""
    root = Path(repository_root).resolve()
    if not isinstance(bank_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", bank_sha256):
        raise ValueError("bank_sha256 must be a lowercase 64-character SHA256")
    if not isinstance(indices, list) or len(indices) > 100:
        raise ValueError("indices must contain at most 100 layout groups")
    for group in indices:
        if not isinstance(group, list) or len(group) != 64:
            raise ValueError("Each layout group must contain exactly 64 indices")
        if any(type(index) is not int or index < 0 for index in group):
            raise ValueError("Indices must be nonnegative integers, not booleans or floats")
        if len(set(group)) != 64:
            raise ValueError("Each layout must contain 64 distinct bank indices")
    pointer_path = root / "results/v2/current_multiregion_bank.json"
    pointer = json.loads(pointer_path.read_text())
    if not isinstance(pointer, dict) or pointer.get("sha256") != bank_sha256:
        raise ValueError("Historical bank SHA256 does not match the current bank pointer")
    relative = pointer.get("path")
    if not isinstance(relative, str):
        raise ValueError("Current bank pointer has no valid path")
    bank_path = (root / relative).resolve()
    if not bank_path.is_relative_to(root) or not bank_path.is_file():
        raise ValueError("Current bank must be an existing file inside repository_root")
    if _sha256_file(bank_path) != bank_sha256:
        raise ValueError("Current bank file SHA256 differs from the requested frozen identity")
    with np.load(bank_path, allow_pickle=False) as bank:
        xyz = np.asarray(bank["candidate_xyz_mm"], dtype=np.float64)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.all(np.isfinite(xyz)):
        raise ValueError("Bank candidate_xyz_mm must be finite Nx3 coordinates")
    output = []
    for group in indices:
        if max(group) >= len(xyz):
            raise ValueError("Historical bank index is out of range")
        points = xyz[np.asarray(group, dtype=np.int64)]
        if len(np.unique(points, axis=0)) != 64:
            raise ValueError("Layout bank rows resolve to duplicate physical coordinates")
        output.append(points.tolist())
    return {"xyz_mm": output, "bank_sha256": bank_sha256}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--bank-sha256", required=True)
    parser.add_argument("--indices", required=True, help="JSON array of up to 100 arrays, each containing 64 bank indices")
    args = parser.parse_args(argv)
    try:
        if len(args.indices) > 131072:
            raise ValueError("Indices JSON exceeds 131072 characters")
        result = export_history_coordinates(args.repository_root, args.bank_sha256, json.loads(args.indices))
        print(json.dumps(result, allow_nan=False, separators=(",", ":")))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
