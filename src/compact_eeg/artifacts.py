"""Small, deterministic primitives for V2 artifact provenance.

This module deliberately contains no experiment scheduler or campaign model.
It provides only the byte-level operations needed by later result writers:
canonical JSON, stable semantic identifiers, atomic JSON publication, file
checksums, and relocatable manifests for regular-file trees.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any


TREE_MANIFEST_SCHEMA = "compact-eeg-tree-manifest/1"
SEMANTIC_ID_SCHEMA = "compact-eeg-semantic-id/1"
_SEMANTIC_NAMESPACE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _normalize_json(value: Any, path: str = "$") -> Any:
    """Return standard JSON types while rejecting ambiguous inputs."""

    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite float at {path}")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"JSON object key at {path} must be a string")
            normalized[key] = _normalize_json(item, f"{path}.{key}")
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _normalize_json(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise TypeError(f"unsupported JSON value at {path}: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Encode ``value`` as deterministic compact UTF-8 JSON.

    Object keys must be strings, mappings are sorted recursively, Unicode is
    emitted directly, and NaN or infinity is rejected.  No trailing newline is
    added, so the returned bytes are also the bytes written by
    :func:`atomic_write_json`.
    """

    normalized = _normalize_json(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    """Return the SHA-256 hex digest of :func:`canonical_json_bytes`."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def semantic_id(namespace: str, semantic_value: Any) -> str:
    """Return a deterministic, namespaced identifier for semantic inputs.

    The full digest is retained.  Runtime-only facts such as timestamps,
    worker identifiers, or chunk sizes must not be placed in
    ``semantic_value``.
    """

    if not isinstance(namespace, str) or _SEMANTIC_NAMESPACE.fullmatch(namespace) is None:
        raise ValueError(
            "namespace must match ^[a-z][a-z0-9_-]{0,31}$"
        )
    digest = canonical_json_sha256(
        {
            "namespace": namespace,
            "schema_version": SEMANTIC_ID_SCHEMA,
            "semantic_value": semantic_value,
        }
    )
    return f"{namespace}_{digest}"


def sha256_file(path: str | os.PathLike[str], chunk_size: int = 1024 * 1024) -> str:
    """Hash one stable regular file without following a symbolic link."""

    if not isinstance(chunk_size, int) or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer")
    source = Path(path)
    if source.is_symlink():
        raise ValueError(f"symbolic links are not artifact files: {source}")

    digest = hashlib.sha256()
    with source.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"artifact path is not a regular file: {source}")
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
        after = os.fstat(handle.fileno())

    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after:
        raise RuntimeError(f"artifact changed while it was being hashed: {source}")
    return digest.hexdigest()


def _fsync_directory(directory: Path) -> None:
    """Persist a directory entry where the platform supports directory fsync."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_json(path: str | os.PathLike[str], value: Any) -> str:
    """Atomically publish canonical JSON and return its SHA-256 digest.

    The temporary file is created beside the destination, flushed to stable
    storage, and replaced with :func:`os.replace`.  Consequently, readers see
    either the previous complete file or the new complete file.
    """

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(value)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    open_descriptor: int | None = descriptor
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            open_descriptor = None
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    except BaseException:
        if open_descriptor is not None:
            os.close(open_descriptor)
        temporary.unlink(missing_ok=True)
        raise
    return hashlib.sha256(payload).hexdigest()


def _normalized_exclusion(path: str | os.PathLike[str]) -> str:
    raw = os.fspath(path).replace(os.sep, "/")
    normalized = PurePosixPath(raw)
    if normalized.is_absolute() or not normalized.parts or ".." in normalized.parts:
        raise ValueError(f"excluded path must be relative and contained: {path}")
    value = normalized.as_posix()
    if value in ("", "."):
        raise ValueError("cannot exclude the manifest root")
    return value.removeprefix("./").rstrip("/")


def build_tree_manifest(
    root: str | os.PathLike[str],
    *,
    exclude_paths: Sequence[str | os.PathLike[str]] = (),
) -> dict[str, Any]:
    """Describe every regular file below ``root`` in deterministic path order.

    Paths are POSIX-style and relative, making the manifest relocatable.
    Symbolic links are rejected instead of being followed or silently omitted.
    An excluded directory path excludes its complete subtree.
    """

    directory = Path(root)
    if not directory.is_dir():
        raise ValueError(f"manifest root is not a directory: {directory}")
    if directory.is_symlink():
        raise ValueError(f"manifest root cannot be a symbolic link: {directory}")

    exclusions = tuple(sorted({_normalized_exclusion(path) for path in exclude_paths}))

    def excluded(relative: str) -> bool:
        return any(relative == item or relative.startswith(f"{item}/") for item in exclusions)

    candidates = sorted(
        directory.rglob("*"),
        key=lambda path: path.relative_to(directory).as_posix(),
    )
    files: list[dict[str, Any]] = []
    for candidate in candidates:
        relative = candidate.relative_to(directory).as_posix()
        if excluded(relative):
            continue
        if candidate.is_symlink():
            raise ValueError(f"symbolic link found in artifact tree: {relative}")
        if candidate.is_file():
            size = candidate.stat().st_size
            files.append(
                {
                    "path": relative,
                    "sha256": sha256_file(candidate),
                    "size_bytes": size,
                }
            )

    body: dict[str, Any] = {
        "file_count": len(files),
        "files": files,
        "schema_version": TREE_MANIFEST_SCHEMA,
        "total_bytes": sum(int(item["size_bytes"]) for item in files),
    }
    body["tree_sha256"] = canonical_json_sha256(body)
    return body


__all__ = [
    "SEMANTIC_ID_SCHEMA",
    "TREE_MANIFEST_SCHEMA",
    "atomic_write_json",
    "build_tree_manifest",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "semantic_id",
    "sha256_file",
]
