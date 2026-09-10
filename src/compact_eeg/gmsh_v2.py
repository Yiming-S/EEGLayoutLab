"""Minimal, auditable reader for Gmsh 2.2 binary meshes.

The V2 qualification pipeline needs only node coordinates and first-order
triangles.  This module nevertheless inventories every element type and first
physical tag so that extracting a surface cannot silently select the wrong
tissue.  It deliberately does not depend on SimNIBS or meshio.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import struct
from typing import BinaryIO

import numpy as np


GMSH_VERSION = "2.2"
GMSH_TRIANGLE = 2
GMSH_TETRAHEDRON = 4

# Number of node references for the only element types accepted by this
# qualification reader.  Rejecting every other type is safer than attempting
# to skip a high-order block with an unverified width.
_NODES_PER_ELEMENT = {
    2: 3,
    4: 4,
}


@dataclass(frozen=True)
class Gmsh22BinaryMesh:
    """Parsed nodes, selected triangles, and complete element inventory."""

    node_ids: np.ndarray
    node_coordinates: np.ndarray
    triangles: np.ndarray
    triangle_primary_tags: np.ndarray
    declared_element_count: int
    element_type_counts: dict[int, int]
    element_type_primary_tag_counts: dict[tuple[int, int], int]
    byte_order: str


def _read_required_line(handle: BinaryIO, expected: bytes | None = None) -> bytes:
    """Read the next non-empty ASCII line and optionally check its value."""

    while True:
        line = handle.readline()
        if line == b"":
            raise ValueError("unexpected end of Gmsh file")
        stripped = line.strip()
        if stripped:
            break
    if expected is not None and stripped != expected:
        raise ValueError(
            f"expected Gmsh marker {expected!r}, found {stripped!r}"
        )
    return stripped


def _positive_ascii_integer(handle: BinaryIO, field: str) -> int:
    raw = _read_required_line(handle)
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"invalid ASCII integer for {field}: {raw!r}") from error
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _detect_byte_order(raw: bytes) -> str:
    if len(raw) != 4:
        raise ValueError("truncated Gmsh binary byte-order sentinel")
    little = struct.unpack("<i", raw)[0]
    big = struct.unpack(">i", raw)[0]
    if little == 1 and big != 1:
        return "<"
    if big == 1 and little != 1:
        return ">"
    raise ValueError("invalid Gmsh binary byte-order sentinel")


def _map_node_references(node_ids: np.ndarray, references: np.ndarray) -> np.ndarray:
    """Convert arbitrary positive Gmsh node IDs to zero-based row indices."""

    if references.size == 0:
        return np.empty(references.shape, dtype=np.int64)
    if np.any(references <= 0):
        raise ValueError("Gmsh elements contain non-positive node references")

    expected = np.arange(1, len(node_ids) + 1, dtype=node_ids.dtype)
    if np.array_equal(node_ids, expected):
        mapped = references.astype(np.int64, copy=False) - 1
        if int(mapped.max()) >= len(node_ids):
            raise ValueError("Gmsh element references an absent node")
        return mapped

    order = np.argsort(node_ids, kind="stable")
    sorted_ids = node_ids[order]
    if np.any(sorted_ids[1:] == sorted_ids[:-1]):
        raise ValueError("Gmsh node IDs are not unique")
    locations = np.searchsorted(sorted_ids, references)
    clipped = np.minimum(locations, len(sorted_ids) - 1)
    if np.any(locations == len(sorted_ids)) or np.any(
        sorted_ids[clipped] != references
    ):
        raise ValueError("Gmsh element references an absent node")
    return order[locations].astype(np.int64, copy=False)


def read_gmsh22_binary(
    path: str | Path,
    *,
    triangle_tags: set[int] | None = None,
    chunk_size: int = 250_000,
) -> Gmsh22BinaryMesh:
    """Read a Gmsh 2.2 binary mesh and retain selected linear triangles.

    Parameters
    ----------
    path
        Regular Gmsh ``.msh`` file.
    triangle_tags
        First physical tags to retain.  ``None`` retains every triangle.
    chunk_size
        Maximum element records decoded at once.  This bounds transient memory
        for multi-million-element FEM meshes without changing results.
    """

    if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer")
    if triangle_tags is not None:
        normalized_tags = {int(tag) for tag in triangle_tags}
        if any(tag < 0 for tag in normalized_tags):
            raise ValueError("triangle_tags must be non-negative")
    else:
        normalized_tags = None

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"Gmsh path is not a regular file: {source}")

    with source.open("rb") as handle:
        _read_required_line(handle, b"$MeshFormat")
        format_fields = _read_required_line(handle).split()
        if format_fields != [b"2.2", b"1", b"8"]:
            raise ValueError(
                "only Gmsh 2.2 binary meshes with 8-byte floats are supported"
            )
        byte_order = _detect_byte_order(handle.read(4))
        _read_required_line(handle, b"$EndMeshFormat")
        _read_required_line(handle, b"$Nodes")
        node_count = _positive_ascii_integer(handle, "node count")

        node_dtype = np.dtype(
            [("id", f"{byte_order}i4"), ("xyz", f"{byte_order}f8", (3,))]
        )
        node_records = np.fromfile(handle, dtype=node_dtype, count=node_count)
        if len(node_records) != node_count:
            raise ValueError("truncated Gmsh binary node block")
        node_ids = node_records["id"].astype(np.int64, copy=True)
        coordinates = node_records["xyz"].astype(np.float64, copy=True)
        if np.any(node_ids <= 0):
            raise ValueError("Gmsh node IDs must be positive")
        if not np.all(np.isfinite(coordinates)):
            raise ValueError("Gmsh node coordinates contain non-finite values")
        if len(np.unique(node_ids)) != len(node_ids):
            raise ValueError("Gmsh node IDs are not unique")

        _read_required_line(handle, b"$EndNodes")
        _read_required_line(handle, b"$Elements")
        element_count = _positive_ascii_integer(handle, "element count")
        processed = 0
        type_counts: Counter[int] = Counter()
        type_tag_counts: Counter[tuple[int, int]] = Counter()
        triangle_references: list[np.ndarray] = []
        retained_tags: list[np.ndarray] = []
        int_dtype = np.dtype(f"{byte_order}i4")

        while processed < element_count:
            header = np.fromfile(handle, dtype=int_dtype, count=3)
            if len(header) != 3:
                raise ValueError("truncated Gmsh binary element-block header")
            element_type, block_count, tag_count = (int(item) for item in header)
            if element_type not in _NODES_PER_ELEMENT:
                raise ValueError(f"unsupported Gmsh element type: {element_type}")
            if block_count < 1 or tag_count < 0:
                raise ValueError("invalid Gmsh binary element-block dimensions")
            if processed + block_count > element_count:
                raise ValueError("Gmsh element blocks exceed declared element count")

            nodes_per_element = _NODES_PER_ELEMENT[element_type]
            record_width = 1 + tag_count + nodes_per_element
            remaining = block_count
            while remaining:
                current = min(remaining, chunk_size)
                flat = np.fromfile(
                    handle, dtype=int_dtype, count=current * record_width
                )
                if len(flat) != current * record_width:
                    raise ValueError("truncated Gmsh binary element block")
                records = flat.reshape(current, record_width)
                type_counts[element_type] += current

                if tag_count:
                    primary_tags = records[:, 1].astype(np.int64, copy=False)
                else:
                    primary_tags = np.zeros(current, dtype=np.int64)
                values, counts = np.unique(primary_tags, return_counts=True)
                for value, count in zip(values, counts, strict=True):
                    type_tag_counts[(element_type, int(value))] += int(count)

                if element_type == GMSH_TRIANGLE:
                    if normalized_tags is None:
                        retain = np.ones(current, dtype=bool)
                    else:
                        retain = np.isin(primary_tags, tuple(normalized_tags))
                    if np.any(retain):
                        start = 1 + tag_count
                        triangle_references.append(
                            records[retain, start : start + 3].astype(
                                np.int64, copy=True
                            )
                        )
                        retained_tags.append(primary_tags[retain].copy())
                remaining -= current
            processed += block_count

        _read_required_line(handle, b"$EndElements")
        trailing = handle.read()
        if trailing.strip():
            raise ValueError("unsupported data sections follow $EndElements")

    if triangle_references:
        references = np.concatenate(triangle_references, axis=0)
        triangles = _map_node_references(node_ids, references)
        triangle_primary_tags = np.concatenate(retained_tags).astype(
            np.int64, copy=False
        )
    else:
        triangles = np.empty((0, 3), dtype=np.int64)
        triangle_primary_tags = np.empty(0, dtype=np.int64)

    return Gmsh22BinaryMesh(
        node_ids=node_ids,
        node_coordinates=coordinates,
        triangles=triangles,
        triangle_primary_tags=triangle_primary_tags,
        declared_element_count=element_count,
        element_type_counts=dict(sorted(type_counts.items())),
        element_type_primary_tag_counts=dict(sorted(type_tag_counts.items())),
        byte_order="little" if byte_order == "<" else "big",
    )


__all__ = [
    "GMSH_TETRAHEDRON",
    "GMSH_TRIANGLE",
    "GMSH_VERSION",
    "Gmsh22BinaryMesh",
    "read_gmsh22_binary",
]
