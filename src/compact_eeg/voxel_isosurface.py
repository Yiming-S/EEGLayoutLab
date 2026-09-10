"""Feature-preserving exterior isosurfaces from labelled voxel volumes.

The extractor deliberately keeps the native voxel grid.  A binary 0.5 level
set is triangulated with one consistent six-tetrahedron decomposition per
voxel cell.  The result is intended for geometry qualification; it is not a
smoothed anatomical surface and it is not a forward-model mesh.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage


_CUBE_CORNERS = np.array(
    [
        [0, 0, 0],
        [1, 0, 0],
        [0, 1, 0],
        [1, 1, 0],
        [0, 0, 1],
        [1, 0, 1],
        [0, 1, 1],
        [1, 1, 1],
    ],
    dtype=np.int8,
)

# All tetrahedra share the body diagonal from cube corner 0 to corner 7.
# Adjacent cubes therefore induce the same diagonal on every shared face.
_TETRAHEDRA = np.array(
    [
        [0, 1, 3, 7],
        [0, 3, 2, 7],
        [0, 2, 6, 7],
        [0, 6, 4, 7],
        [0, 4, 5, 7],
        [0, 5, 1, 7],
    ],
    dtype=np.int8,
)

_TETRAHEDRON_EDGES = (
    (0, 1),
    (0, 2),
    (0, 3),
    (1, 2),
    (1, 3),
    (2, 3),
)


@dataclass(frozen=True)
class ExteriorSkinSurface:
    """Native-grid exterior surface and extraction audit information."""

    vertices_scs_m: np.ndarray
    triangles: np.ndarray
    report: dict[str, object]


def validate_volume_geometry(
    cube: np.ndarray,
    voxel_size_mm: np.ndarray,
    scs_rotation: np.ndarray,
    scs_translation_mm: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Validate a labelled volume and its MATLAB-voxel-to-SCS transform."""
    labels = np.asarray(cube)
    spacing = np.asarray(voxel_size_mm, dtype=float).reshape(-1)
    rotation = np.asarray(scs_rotation, dtype=float)
    translation = np.asarray(scs_translation_mm, dtype=float).reshape(-1)

    if labels.ndim != 3 or min(labels.shape) < 2:
        raise ValueError("cube must be a three-dimensional array with all dimensions >= 2")
    if not np.issubdtype(labels.dtype, np.integer) or np.issubdtype(
        labels.dtype, np.bool_
    ):
        raise ValueError("cube must contain integer tissue labels")
    if spacing.shape != (3,) or not np.all(np.isfinite(spacing)):
        raise ValueError("voxel_size_mm must contain three finite values")
    if np.any(spacing <= 0):
        raise ValueError("voxel_size_mm values must be positive")
    if rotation.shape != (3, 3) or not np.all(np.isfinite(rotation)):
        raise ValueError("scs_rotation must be a finite 3 by 3 matrix")
    orthonormal_residual = rotation @ rotation.T - np.eye(3)
    if float(np.max(np.abs(orthonormal_residual))) > 1.0e-6:
        raise ValueError("scs_rotation must be orthonormal within 1e-6")
    determinant = float(np.linalg.det(rotation))
    if determinant <= 0 or abs(determinant - 1.0) > 1.0e-6:
        raise ValueError("scs_rotation must be a proper rotation")
    if translation.shape != (3,) or not np.all(np.isfinite(translation)):
        raise ValueError("scs_translation_mm must contain three finite values")
    return labels, spacing, rotation, translation


def largest_connected_tissue(
    cube: np.ndarray,
) -> tuple[np.ndarray, dict[str, object]]:
    """Return the largest six-connected non-background component.

    Nonzero labels are treated as head tissue.  Discarded components and their
    voxel counts are reported so isolated segmentation islands cannot be
    removed silently.
    """
    labels = np.asarray(cube)
    if labels.ndim != 3:
        raise ValueError("cube must be three-dimensional")
    tissue = labels != 0
    tissue_voxel_count = int(np.count_nonzero(tissue))
    if tissue_voxel_count == 0:
        raise ValueError("cube contains no non-background tissue")

    structure = ndimage.generate_binary_structure(rank=3, connectivity=1)
    components, component_count = ndimage.label(tissue, structure=structure)
    counts = np.bincount(components.reshape(-1))
    component_sizes = counts[1:].astype(np.int64, copy=False)
    largest_label = int(np.argmax(component_sizes)) + 1
    largest = components == largest_label
    retained_count = int(component_sizes[largest_label - 1])
    discarded_count = tissue_voxel_count - retained_count
    report: dict[str, object] = {
        "connectivity": "six_connected_face_neighbors",
        "component_count": int(component_count),
        "component_sizes_voxels_descending": [
            int(value) for value in np.sort(component_sizes)[::-1]
        ],
        "original_nonzero_tissue_voxel_count": tissue_voxel_count,
        "retained_largest_component_voxel_count": retained_count,
        "discarded_nonlargest_component_voxel_count": discarded_count,
        "retained_fraction": retained_count / float(tissue_voxel_count),
    }
    return largest, report


def exterior_solid_mask(
    tissue_mask: np.ndarray,
) -> tuple[np.ndarray, dict[str, object]]:
    """Fill sealed voids while preserving cavities connected to the exterior.

    A one-voxel background frame guarantees an exterior seed.  Background is
    flooded with six-connectivity; only background not reached by that flood is
    filled.  The returned array therefore includes the one-voxel frame.
    """
    tissue = np.asarray(tissue_mask, dtype=bool)
    if tissue.ndim != 3:
        raise ValueError("tissue_mask must be three-dimensional")
    if not np.any(tissue):
        raise ValueError("tissue_mask contains no tissue")

    padded = np.pad(tissue, 1, mode="constant", constant_values=False)
    background = ~padded
    seeds = np.zeros_like(padded)
    seeds[0, :, :] = True
    seeds[-1, :, :] = True
    seeds[:, 0, :] = True
    seeds[:, -1, :] = True
    seeds[:, :, 0] = True
    seeds[:, :, -1] = True
    structure = ndimage.generate_binary_structure(rank=3, connectivity=1)
    exterior_background = ndimage.binary_propagation(
        seeds, structure=structure, mask=background
    )
    sealed_background = background & ~exterior_background
    solid = ~exterior_background
    report: dict[str, object] = {
        "padding_voxels_each_face": 1,
        "background_flood_connectivity": "six_connected_face_neighbors",
        "padded_shape": [int(value) for value in padded.shape],
        "exterior_background_voxel_count": int(
            np.count_nonzero(exterior_background)
        ),
        "sealed_background_voxel_count_filled": int(
            np.count_nonzero(sealed_background)
        ),
        "solid_voxel_count_after_sealed_void_fill": int(np.count_nonzero(solid)),
    }
    return solid, report


def _tetrahedron_case_faces() -> tuple[tuple[tuple[tuple[int, int], ...], ...], ...]:
    """Build the 16 binary cases as oriented edge-intersection polygons."""
    output: list[tuple[tuple[tuple[int, int], ...], ...]] = []
    # Explicit non-coplanar coordinates are used only to orient lookup faces.
    tetrahedron_points = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    )
    for case in range(16):
        inside = np.array([(case >> index) & 1 for index in range(4)], dtype=bool)
        crossing = [
            edge for edge in _TETRAHEDRON_EDGES if inside[edge[0]] != inside[edge[1]]
        ]
        if len(crossing) < 3:
            output.append(())
            continue

        points = np.array(
            [
                (tetrahedron_points[first] + tetrahedron_points[second]) / 2.0
                for first, second in crossing
            ]
        )
        outside_centroid = tetrahedron_points[~inside].mean(axis=0)
        inside_centroid = tetrahedron_points[inside].mean(axis=0)
        outward = outside_centroid - inside_centroid
        centre = points.mean(axis=0)
        normal_axis = outward / np.linalg.norm(outward)
        reference = points[0] - centre
        reference /= np.linalg.norm(reference)
        tangent = np.cross(normal_axis, reference)
        angles = np.arctan2((points - centre) @ tangent, (points - centre) @ reference)
        order = np.argsort(angles)
        polygon = [crossing[int(index)] for index in order]
        ordered_points = points[order]
        polygon_normal = np.cross(
            ordered_points[1] - ordered_points[0],
            ordered_points[2] - ordered_points[0],
        )
        if float(np.dot(polygon_normal, outward)) < 0:
            polygon.reverse()

        if len(polygon) == 3:
            output.append((tuple(polygon),))
        elif len(polygon) == 4:
            output.append(
                (
                    (polygon[0], polygon[1], polygon[2]),
                    (polygon[0], polygon[2], polygon[3]),
                )
            )
        else:
            raise RuntimeError("a tetrahedron case produced an invalid polygon")
    return tuple(output)


_TETRAHEDRON_CASE_FACES = _tetrahedron_case_faces()


def marching_tetrahedra_binary(
    solid_mask: np.ndarray,
    voxel_size_mm: np.ndarray,
    scs_rotation: np.ndarray,
    scs_translation_mm: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    """Triangulate the binary 0.5 isosurface without global resampling.

    ``solid_mask`` is sampled at MATLAB-style voxel centres after a one-voxel
    pad.  Index 1 in the padded array therefore maps to MATLAB voxel coordinate
    1.  Vertices are returned in Brainstorm SCS coordinates and metres.
    """
    solid = np.asarray(solid_mask, dtype=bool)
    spacing = np.asarray(voxel_size_mm, dtype=float).reshape(-1)
    rotation = np.asarray(scs_rotation, dtype=float)
    translation = np.asarray(scs_translation_mm, dtype=float).reshape(-1)
    if solid.ndim != 3 or min(solid.shape) < 2:
        raise ValueError("solid_mask must be three-dimensional with dimensions >= 2")
    if spacing.shape != (3,) or np.any(~np.isfinite(spacing)) or np.any(spacing <= 0):
        raise ValueError("voxel_size_mm must contain three positive finite values")
    if rotation.shape != (3, 3) or not np.all(np.isfinite(rotation)):
        raise ValueError("scs_rotation must be a finite 3 by 3 matrix")
    if translation.shape != (3,) or not np.all(np.isfinite(translation)):
        raise ValueError("scs_translation_mm must contain three finite values")

    cell_shape = tuple(int(value - 1) for value in solid.shape)
    cube_cases = np.zeros(cell_shape, dtype=np.uint8)
    for bit, corner in enumerate(_CUBE_CORNERS):
        slices = tuple(
            slice(int(corner[axis]), int(corner[axis]) + cell_shape[axis])
            for axis in range(3)
        )
        cube_cases |= solid[slices].astype(np.uint8) << bit
    active_bases = np.argwhere((cube_cases != 0) & (cube_cases != 255))
    if active_bases.size == 0:
        raise ValueError("solid_mask has no binary 0.5 isosurface")

    triangle_midpoints_twice: list[np.ndarray] = []
    for tetrahedron in _TETRAHEDRA:
        tetrahedron_cases = np.zeros(len(active_bases), dtype=np.uint8)
        for local_index, cube_corner_index in enumerate(tetrahedron):
            coordinates = active_bases + _CUBE_CORNERS[int(cube_corner_index)]
            values = solid[coordinates[:, 0], coordinates[:, 1], coordinates[:, 2]]
            tetrahedron_cases |= values.astype(np.uint8) << local_index

        for case in range(1, 15):
            faces = _TETRAHEDRON_CASE_FACES[case]
            if not faces:
                continue
            selected_bases = active_bases[tetrahedron_cases == case]
            if len(selected_bases) == 0:
                continue
            for face in faces:
                face_vertices: list[np.ndarray] = []
                for local_first, local_second in face:
                    cube_first = int(tetrahedron[local_first])
                    cube_second = int(tetrahedron[local_second])
                    midpoint_twice = (
                        2 * selected_bases
                        + _CUBE_CORNERS[cube_first]
                        + _CUBE_CORNERS[cube_second]
                    )
                    face_vertices.append(midpoint_twice.astype(np.int32, copy=False))
                triangle_midpoints_twice.append(np.stack(face_vertices, axis=1))

    if not triangle_midpoints_twice:
        raise RuntimeError("active cells produced no isosurface triangles")
    all_triangle_midpoints_twice = np.concatenate(triangle_midpoints_twice, axis=0)
    flat_midpoints_twice = all_triangle_midpoints_twice.reshape(-1, 3)

    key_shape = 2 * np.asarray(solid.shape, dtype=np.int64) + 1
    keys = np.ravel_multi_index(
        flat_midpoints_twice.astype(np.int64, copy=False).T,
        tuple(int(value) for value in key_shape),
    )
    unique_keys, inverse = np.unique(keys, return_inverse=True)
    vertex_midpoints_twice = np.column_stack(
        np.unravel_index(unique_keys, tuple(int(value) for value in key_shape))
    ).astype(np.int32, copy=False)
    triangles = inverse.reshape(-1, 3).astype(np.int32, copy=False)

    # Because the input was padded by one sample, padded coordinate 1 is the
    # centre of MATLAB voxel 1.  This cancels the conventional one-based shift.
    voxel_coordinates_mm = vertex_midpoints_twice.astype(float) * 0.5 * spacing
    vertices_scs_mm = voxel_coordinates_mm @ rotation.T + translation
    vertices_scs_m = vertices_scs_mm * 1.0e-3
    report: dict[str, object] = {
        "algorithm": "binary_0.5_isosurface_consistent_six_tetrahedra_per_cell",
        "global_resampling_performed": False,
        "smoothing_performed": False,
        "decimation_performed": False,
        "active_mixed_cube_count": int(len(active_bases)),
        "vertex_count": int(len(vertices_scs_m)),
        "triangle_count": int(len(triangles)),
        "stored_vertex_dtype": str(vertices_scs_m.dtype),
        "stored_triangle_dtype": str(triangles.dtype),
    }
    return vertices_scs_m, triangles, report


def extract_exterior_skin_isosurface(
    cube: np.ndarray,
    voxel_size_mm: np.ndarray,
    scs_rotation: np.ndarray,
    scs_translation_mm: np.ndarray,
) -> ExteriorSkinSurface:
    """Run validated component selection, cavity handling, and extraction."""
    labels, spacing, rotation, translation = validate_volume_geometry(
        cube, voxel_size_mm, scs_rotation, scs_translation_mm
    )
    largest, component_report = largest_connected_tissue(labels)
    solid, exterior_report = exterior_solid_mask(largest)
    vertices, triangles, extraction_report = marching_tetrahedra_binary(
        solid, spacing, rotation, translation
    )
    label_values, label_counts = np.unique(labels, return_counts=True)
    report: dict[str, object] = {
        "input": {
            "cube_shape": [int(value) for value in labels.shape],
            "cube_dtype": str(labels.dtype),
            "voxel_size_mm": spacing.tolist(),
            "label_histogram": {
                str(int(value)): int(count)
                for value, count in zip(label_values, label_counts, strict=True)
            },
        },
        "component_selection": component_report,
        "exterior_definition": exterior_report,
        "isosurface": extraction_report,
    }
    return ExteriorSkinSurface(vertices, triangles, report)


def signed_volume_m3(vertices_m: np.ndarray, triangles: np.ndarray) -> float:
    """Return the oriented volume enclosed by a triangular surface."""
    vertices = np.asarray(vertices_m, dtype=float)
    faces = np.asarray(triangles, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("vertices_m must have shape (n_vertices, 3)")
    if faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError("triangles must have shape (n_triangles, 3)")
    return float(
        np.einsum(
            "ij,ij->i",
            vertices[faces[:, 0]],
            np.cross(vertices[faces[:, 1]], vertices[faces[:, 2]]),
        ).sum()
        / 6.0
    )


__all__ = [
    "ExteriorSkinSurface",
    "exterior_solid_mask",
    "extract_exterior_skin_isosurface",
    "largest_connected_tissue",
    "marching_tetrahedra_binary",
    "signed_volume_m3",
    "validate_volume_geometry",
]
