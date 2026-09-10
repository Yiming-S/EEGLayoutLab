from __future__ import annotations

from pathlib import Path
import struct
import sys
import tempfile
import unittest

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from compact_eeg.gmsh_v2 import read_gmsh22_binary


def _write_fixture(
    path: Path,
    *,
    byte_order: str = "<",
    node_ids: tuple[int, ...] = (1, 2, 3, 4),
    triangle_reference: tuple[int, int, int] = (1, 2, 3),
) -> None:
    coordinates = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    with path.open("wb") as handle:
        handle.write(b"$MeshFormat\n2.2 1 8\n")
        handle.write(struct.pack(f"{byte_order}i", 1))
        handle.write(b"\n$EndMeshFormat\n$Nodes\n4\n")
        for node_id, xyz in zip(node_ids, coordinates, strict=True):
            handle.write(struct.pack(f"{byte_order}i3d", node_id, *xyz))
        handle.write(b"$EndNodes\n$Elements\n2\n")
        # One first-order triangle with physical tag 1005 and geometrical tag 5.
        handle.write(struct.pack(f"{byte_order}3i", 2, 1, 2))
        handle.write(
            struct.pack(
                f"{byte_order}6i", 1, 1005, 5, *triangle_reference
            )
        )
        # One tetrahedron with physical and geometrical tag 5.
        handle.write(struct.pack(f"{byte_order}3i", 4, 1, 2))
        handle.write(struct.pack(f"{byte_order}7i", 2, 5, 5, *node_ids))
        handle.write(b"$EndElements\n")


class Gmsh22BinaryTests(unittest.TestCase):
    def test_reads_little_endian_and_inventories_all_elements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mesh.msh"
            _write_fixture(path)
            mesh = read_gmsh22_binary(path)

        self.assertEqual(mesh.byte_order, "little")
        self.assertEqual(mesh.declared_element_count, 2)
        self.assertEqual(mesh.element_type_counts, {2: 1, 4: 1})
        self.assertEqual(
            mesh.element_type_primary_tag_counts, {(2, 1005): 1, (4, 5): 1}
        )
        np.testing.assert_array_equal(mesh.triangles, [[0, 1, 2]])
        np.testing.assert_array_equal(mesh.triangle_primary_tags, [1005])
        np.testing.assert_allclose(mesh.node_coordinates[3], [0.0, 0.0, 1.0])

    def test_maps_nonsequential_node_ids_and_filters_tags(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mesh.msh"
            _write_fixture(
                path,
                node_ids=(40, 10, 30, 20),
                triangle_reference=(40, 10, 30),
            )
            selected = read_gmsh22_binary(path, triangle_tags={1005}, chunk_size=1)
            absent = read_gmsh22_binary(path, triangle_tags={9999})

        np.testing.assert_array_equal(selected.triangles, [[0, 1, 2]])
        self.assertEqual(absent.triangles.shape, (0, 3))
        self.assertEqual(absent.triangle_primary_tags.shape, (0,))

    def test_reads_big_endian(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mesh.msh"
            _write_fixture(path, byte_order=">")
            mesh = read_gmsh22_binary(path)
        self.assertEqual(mesh.byte_order, "big")
        np.testing.assert_array_equal(mesh.triangles, [[0, 1, 2]])

    def test_rejects_missing_node_reference_and_bad_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mesh.msh"
            _write_fixture(path, triangle_reference=(1, 2, 99))
            with self.assertRaisesRegex(ValueError, "absent node"):
                read_gmsh22_binary(path)
            with self.assertRaisesRegex(ValueError, "chunk_size"):
                read_gmsh22_binary(path, chunk_size=0)
            with self.assertRaisesRegex(ValueError, "triangle_tags"):
                read_gmsh22_binary(path, triangle_tags={-1})


if __name__ == "__main__":
    unittest.main()
