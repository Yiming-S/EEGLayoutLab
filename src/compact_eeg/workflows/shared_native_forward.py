"""Atomic, exact-input forward artifacts shared by design and reception.

This store has no result-record identity. Callers verify the completed design
receipt separately and supply the full current physical/runtime identity.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

import numpy as np

from compact_eeg.artifacts import sha256_file
from compact_eeg.forward_pilot import deterministic_npz_bytes

SCHEMA = "shared-native-forward/1"
RELATIVE_ROOT = Path("results/v2/reception_forward/shared_fields")


class IdentityChanged(ValueError):
    """Physical inputs or numerical runtime changed during calculation."""


class IntegrityError(ValueError):
    """An existing shared artifact is corrupt or contradicts its exact key."""


def _bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _array(value):
    a = np.ascontiguousarray(value)
    if a.dtype.hasobject:
        raise ValueError("Shared forward arrays cannot contain objects")
    return {"shape": list(a.shape), "dtype": a.dtype.str, "sha256": hashlib.sha256(a.tobytes()).hexdigest()}


def _entry(root, identity):
    root = Path(root).resolve()
    key = hashlib.sha256(_bytes(identity)).hexdigest()
    entry = root / RELATIVE_ROOT / key
    if not entry.resolve().is_relative_to(root):
        raise ValueError("Shared forward directory leaves the repository")
    return root, key, entry


def _read(root, identity, expected):
    root, key, entry = _entry(root, identity)
    if not entry.exists():
        return None
    manifest_path, payload_path, index_path = entry / "manifest.json", entry / "fields.npz", entry / "cache.json"
    if any(not p.is_file() or p.is_symlink() or p.resolve().parent != entry.resolve()
           for p in (manifest_path, payload_path, index_path)):
        raise ValueError("Incomplete or redirected shared forward artifact")
    index = json.loads(index_path.read_text())
    if (index.get("schema") != SCHEMA or index.get("key") != key
            or index.get("manifest_sha256") != sha256_file(manifest_path)):
        raise ValueError("Shared forward manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("schema") != SCHEMA or manifest.get("status") != "completed"
            or manifest.get("identity") != identity or manifest.get("key") != key):
        raise ValueError("Shared forward identity or completion mismatch")
    if sha256_file(payload_path) != manifest.get("payload_sha256"):
        raise ValueError("Shared forward payload hash mismatch")
    with np.load(payload_path, allow_pickle=False) as payload:
        arrays = {name: payload[name] for name in payload.files}
    if (set(arrays) != set(manifest.get("arrays", {}))
            or any(_array(a) != manifest["arrays"][name] for name, a in arrays.items())):
        raise ValueError("Shared forward per-array identity mismatch")
    for name, array in expected.items():
        if name not in arrays or _array(arrays[name]) != _array(array):
            raise ValueError(f"Shared forward differs from exact {name}")
    if (set(arrays) != set(expected) | {"candidate_h", "evaluated_candidate_xyz_mm"}
            or arrays["candidate_h"].shape != arrays["baseline_h"].shape
            or arrays["candidate_h"].dtype != np.dtype("float64")
            or not np.isfinite(arrays["candidate_h"]).all()
            or arrays["evaluated_candidate_xyz_mm"].shape != (64, 3)
            or not np.isfinite(arrays["evaluated_candidate_xyz_mm"]).all()):
        raise ValueError("Shared forward arrays have invalid shape, type or values")
    return arrays, manifest, {"cache_path": str(index_path.relative_to(root)), "cache_sha256": sha256_file(index_path),
        "manifest_path": str(manifest_path.relative_to(root)),
        "manifest_sha256": sha256_file(manifest_path), "payload_sha256": manifest["payload_sha256"]}


def read(root, identity, expected):
    try:
        return _read(root, identity, expected)
    except Exception as error:
        # Invalid paths, malformed indexes/archives and unreadable existing
        # payloads all fail closed. Cancellation remains a BaseException.
        raise IntegrityError(str(error)) from error


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish(root, identity, arrays, metadata):
    """Publish one complete directory; failed/interrupted attempts never hit."""
    root, key, entry = _entry(root, identity)
    body = deterministic_npz_bytes(arrays)
    manifest = {"schema": SCHEMA, "status": "completed", "key": key,
        "identity": identity, "payload_sha256": hashlib.sha256(body).hexdigest(),
        "arrays": {name: _array(a) for name, a in arrays.items()}, "metadata": metadata}
    manifest_bytes = _bytes(manifest)
    index_bytes = _bytes({"schema": SCHEMA, "key": key, "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()})
    entry.parent.mkdir(parents=True, exist_ok=True)
    if not entry.parent.resolve().is_relative_to(root):
        raise ValueError("Shared forward parent leaves the repository")
    attempt = entry.parent / (".attempt-" + uuid.uuid4().hex)
    attempt.mkdir()
    try:
        for name, data in (("fields.npz", body), ("manifest.json", manifest_bytes), ("cache.json", index_bytes)):
            with (attempt / name).open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        _sync_directory(attempt)
        # The global native lock normally serializes writers. Rename also keeps
        # readers from observing a partially written manifest/payload pair.
        os.rename(attempt, entry)
        _sync_directory(entry.parent)
    finally:
        if attempt.exists():
            shutil.rmtree(attempt)
    return key
