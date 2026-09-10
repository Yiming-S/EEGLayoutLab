"""Bounded geometry search primitives for fixed-64 multi-region layouts.

All coordinates and distances in this module use metres.  The routines operate
on the qualified Ernie external-scalp mesh, but the coordinate masks below are
only reproducible construction proxies.  They are not expert-reviewed anatomy,
skin-access, or hair masks.

Mesh-edge Dijkstra distance is an upper-path surrogate used to define and rank
surface patches.  Euclidean 3-D chord distance is the conservative minimum
spacing check.  A failed bounded search is never an infeasibility certificate.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Iterable, Mapping, Sequence

import numpy as np

from compact_eeg.fixed64_geometry import (
    build_coordinate_clipped_patch,
    coordinate_roi_mask,
)
from compact_eeg.packing_pilot import (
    GraphDistanceCache,
    minimum_pairwise_chord_distance,
)


@dataclass(frozen=True)
class ApproximateROITemplate:
    """Explicit subject-coordinate construction proxy, never an anatomy claim."""

    roi_id: str
    label: str
    anchor_target_xyz_m: np.ndarray
    inclusive_min_xyz_m: np.ndarray
    inclusive_max_xyz_m: np.ndarray
    exclusion_ellipsoid_centers_m: np.ndarray
    exclusion_ellipsoid_radii_m: np.ndarray
    interpretation: str


@dataclass(frozen=True)
class FrozenFamilyDefinition:
    """One member of the finite 17-family exploratory comparison set."""

    family_id: str
    region_count: int
    search_mode: str
    region_roi_ids: tuple[str, ...]


@dataclass(frozen=True)
class GlobalCandidateBank:
    """Deterministically subsampled real Ernie surface vertices."""

    vertex_indices: np.ndarray
    xyz_m: np.ndarray
    roi_ids: tuple[str, ...]
    roi_membership: np.ndarray
    primary_roi_labels: np.ndarray
    whole_scalp_seed_count: int
    low_hair_enhancement_count: int


@dataclass(frozen=True)
class CandidateGraphDistances:
    """Mesh-edge distances from a finite center shortlist to a candidate bank."""

    center_vertex_indices: np.ndarray
    candidate_vertex_indices: np.ndarray
    distances_m: np.ndarray


@dataclass(frozen=True)
class RegionCandidatePool:
    """Candidate electrodes in one connected, coordinate-clipped radius domain."""

    roi_id: str
    center_vertex_index: int
    center_xyz_m: np.ndarray
    graph_path_radius_m: float
    candidate_vertex_indices: np.ndarray
    candidate_xyz_m: np.ndarray
    candidate_center_graph_distances_m: np.ndarray
    underlying_connected_patch_vertex_count: int
    graph_disk_vertex_count: int
    coordinate_clipped_vertex_count: int
    disconnected_vertex_count_removed: int


@dataclass(frozen=True)
class MultiRegionLayoutResult:
    """Best complete or best partial result from a bounded deterministic search."""

    status: str
    electrode_vertex_indices: np.ndarray
    electrode_region_indices: np.ndarray
    requested_region_counts: np.ndarray
    achieved_region_counts: np.ndarray
    minimum_global_chord_distance_m: float
    trials_evaluated: int
    successful_trials: int
    search_method: str


_WHOLE_SCALP_ROI = "whole_scalp_control_approx"
_LOW_HAIR_ROI = "approx_low_hair_proxy_unvalidated"
_WHOLE_SCALP_ALIAS = "whole_scalp_free"
_LOW_HAIR_ALIAS = "low_hair_free"
_LEFT_FOREHEAD_ALIAS = "left_forehead_approx"
_RIGHT_FOREHEAD_ALIAS = "right_forehead_approx"


def _validated_vertices(vertices_m: np.ndarray) -> np.ndarray:
    vertices = np.asarray(vertices_m, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("vertices_m must have shape (n_vertices, 3)")
    if len(vertices) < 1 or not np.all(np.isfinite(vertices)):
        raise ValueError("vertices_m must be non-empty and finite")
    return vertices


def _validated_mask(mask: np.ndarray, vertex_count: int, *, name: str) -> np.ndarray:
    result = np.asarray(mask, dtype=bool)
    if result.shape != (vertex_count,):
        raise ValueError(f"{name} must have shape ({vertex_count},)")
    return result


def _validated_indices(
    values: Iterable[int] | np.ndarray,
    vertex_count: int,
    *,
    name: str,
    allow_empty: bool = False,
) -> np.ndarray:
    raw = np.asarray(list(values) if not isinstance(values, np.ndarray) else values)
    if raw.ndim != 1 or (raw.size == 0 and not allow_empty):
        requirement = "a one-dimensional vector" if allow_empty else "a non-empty vector"
        raise ValueError(f"{name} must be {requirement}")
    if raw.size == 0:
        return np.empty(0, dtype=np.int64)
    if not np.issubdtype(raw.dtype, np.integer) or np.issubdtype(raw.dtype, np.bool_):
        raise ValueError(f"{name} must contain integer vertex indices")
    result = raw.astype(np.int64, copy=False)
    if result.size and (int(result.min()) < 0 or int(result.max()) >= vertex_count):
        raise ValueError(f"{name} contains an out-of-range vertex index")
    if np.unique(result).size != result.size:
        raise ValueError(f"{name} must contain unique vertex indices")
    return result


def balanced_region_point_counts(
    region_count: int,
    total_physical_nodes: int = 64,
) -> tuple[int, ...]:
    """Return the deterministic most-even positive integer allocation."""

    if isinstance(region_count, (bool, np.bool_)) or not isinstance(
        region_count, (int, np.integer)
    ):
        raise ValueError("region_count must be an integer")
    if isinstance(total_physical_nodes, (bool, np.bool_)) or not isinstance(
        total_physical_nodes, (int, np.integer)
    ):
        raise ValueError("total_physical_nodes must be an integer")
    regions = int(region_count)
    total = int(total_physical_nodes)
    if regions < 1 or total < regions:
        raise ValueError("allocation requires 1 <= region_count <= total nodes")
    quotient, remainder = divmod(total, regions)
    return tuple(
        quotient + (1 if index < remainder else 0) for index in range(regions)
    )


def default_approximate_roi_templates() -> tuple[ApproximateROITemplate, ...]:
    """Return frozen coordinate proxies used by the finite exploratory families."""

    def template(
        roi_id: str,
        label: str,
        anchor_mm: Sequence[float],
        lower_mm: Sequence[float],
        upper_mm: Sequence[float],
        exclusions_mm: Sequence[tuple[Sequence[float], Sequence[float]]],
        interpretation: str,
    ) -> ApproximateROITemplate:
        centers = np.asarray([item[0] for item in exclusions_mm], dtype=np.float64)
        radii = np.asarray([item[1] for item in exclusions_mm], dtype=np.float64)
        if not exclusions_mm:
            centers = np.empty((0, 3), dtype=np.float64)
            radii = np.empty((0, 3), dtype=np.float64)
        return ApproximateROITemplate(
            roi_id=roi_id,
            label=label,
            anchor_target_xyz_m=np.asarray(anchor_mm, dtype=np.float64) / 1000.0,
            inclusive_min_xyz_m=np.asarray(lower_mm, dtype=np.float64) / 1000.0,
            inclusive_max_xyz_m=np.asarray(upper_mm, dtype=np.float64) / 1000.0,
            exclusion_ellipsoid_centers_m=centers / 1000.0,
            exclusion_ellipsoid_radii_m=radii / 1000.0,
            interpretation=interpretation,
        )

    pinna_left = (([-82.0, -5.0, -12.0], [15.0, 20.0, 25.0]),)
    pinna_right = (([82.0, -5.0, -12.0], [15.0, 20.0, 25.0]),)
    eye_left = (([-30.0, 108.0, 20.0], [24.0, 18.0, 18.0]),)
    eye_right = (([30.0, 108.0, 20.0], [24.0, 18.0, 18.0]),)
    disclaimer = (
        "Frozen Ernie coordinate proxy; not expert-reviewed anatomy, electrode "
        "access, skin, or hair classification."
    )
    return (
        template(
            "left_near_ear_posterolateral_approx",
            "Left near-ear posterolateral coordinate proxy",
            [-78.0, -32.0, -12.0],
            [-100.0, -80.0, -60.0],
            [-55.0, -12.0, 35.0],
            pinna_left,
            disclaimer + " It is not qualified as a purely postauricular region.",
        ),
        template(
            "right_near_ear_posterolateral_approx",
            "Right near-ear posterolateral coordinate proxy",
            [78.0, -32.0, -12.0],
            [55.0, -80.0, -60.0],
            [100.0, -12.0, 35.0],
            pinna_right,
            disclaimer + " It is not qualified as a purely postauricular region.",
        ),
        template(
            "left_expanded_periauricular_approx",
            "Left expanded periauricular coordinate proxy",
            [-80.0, -35.0, 0.0],
            [-105.0, -65.0, -60.0],
            [-52.0, 40.0, 50.0],
            pinna_left,
            disclaimer + " It is not a reviewed cEEGrid or periauricular mask.",
        ),
        template(
            "right_expanded_periauricular_approx",
            "Right expanded periauricular coordinate proxy",
            [80.0, -35.0, 0.0],
            [52.0, -65.0, -60.0],
            [105.0, 40.0, 50.0],
            pinna_right,
            disclaimer + " It is not a reviewed cEEGrid or periauricular mask.",
        ),
        template(
            "upper_forehead_midline_approx",
            "Upper-forehead midline coordinate proxy",
            [0.0, 95.0, 70.0],
            [-55.0, 65.0, 10.0],
            [55.0, 140.0, 95.0],
            (),
            disclaimer,
        ),
        template(
            "left_upper_forehead_approx",
            "Left upper-forehead coordinate proxy",
            [-28.0, 95.0, 68.0],
            [-60.0, 62.0, 25.0],
            [-1.0, 140.0, 98.0],
            (),
            disclaimer,
        ),
        template(
            "right_upper_forehead_approx",
            "Right upper-forehead coordinate proxy",
            [28.0, 95.0, 68.0],
            [1.0, 62.0, 25.0],
            [60.0, 140.0, 98.0],
            (),
            disclaimer,
        ),
        template(
            "left_lateral_supraorbital_approx",
            "Left lateral supraorbital coordinate proxy",
            [-48.0, 94.0, 38.0],
            [-72.0, 65.0, 8.0],
            [-15.0, 128.0, 62.0],
            eye_left,
            disclaimer + " The ocular exclusion is an ellipsoid proxy.",
        ),
        template(
            "right_lateral_supraorbital_approx",
            "Right lateral supraorbital coordinate proxy",
            [48.0, 94.0, 38.0],
            [15.0, 65.0, 8.0],
            [72.0, 128.0, 62.0],
            eye_right,
            disclaimer + " The ocular exclusion is an ellipsoid proxy.",
        ),
    )


def default_roi_anchor_targets_m() -> dict[str, np.ndarray]:
    """Return independent copies of fixed-anchor targets for specific ROIs."""

    targets = {
        item.roi_id: item.anchor_target_xyz_m.copy()
        for item in default_approximate_roi_templates()
    }
    targets[_LEFT_FOREHEAD_ALIAS] = targets["left_upper_forehead_approx"].copy()
    targets[_RIGHT_FOREHEAD_ALIAS] = targets["right_upper_forehead_approx"].copy()
    return targets


def build_default_approximate_roi_masks(
    vertices_m: np.ndarray,
) -> dict[str, np.ndarray]:
    """Build individual and aggregate frozen Ernie coordinate masks.

    ``whole_scalp_control_approx`` excludes a coordinate-defined neck/lower-face
    proxy and two ocular ellipsoid proxies. ``approx_low_hair_proxy_unvalidated``
    is a union of near-ear, forehead, and lateral supraorbital proxies.  Neither
    aggregate has been reviewed as an anatomical or low-hair mask.
    """

    vertices = _validated_vertices(vertices_m)
    masks: dict[str, np.ndarray] = {}

    # One common construction domain makes the low-hair proxy and every fixed
    # ROI a subset of the whole-scalp control.  Bounds and exclusions are
    # coordinate rules only.  In particular, the ocular ellipsoids are not
    # segmentations of the eyes.
    public_admissible = coordinate_roi_mask(
        vertices,
        np.array([-0.110, -0.105, -0.070]),
        np.array([0.110, 0.140, 0.110]),
        exclusion_ellipsoid_centers_m=np.array(
            [[-0.030, 0.108, 0.020], [0.030, 0.108, 0.020]], dtype=np.float64
        ),
        exclusion_ellipsoid_radii_m=np.array(
            [[0.024, 0.018, 0.018], [0.024, 0.018, 0.018]], dtype=np.float64
        ),
    )
    lower_face_proxy = (
        (np.abs(vertices[:, 0]) <= 0.060)
        & (vertices[:, 1] >= 0.072)
        & (vertices[:, 2] <= 0.025)
    )
    public_admissible &= ~lower_face_proxy

    for item in default_approximate_roi_templates():
        masks[item.roi_id] = public_admissible & coordinate_roi_mask(
            vertices,
            item.inclusive_min_xyz_m,
            item.inclusive_max_xyz_m,
            exclusion_ellipsoid_centers_m=item.exclusion_ellipsoid_centers_m,
            exclusion_ellipsoid_radii_m=item.exclusion_ellipsoid_radii_m,
        )

    whole = public_admissible
    masks[_WHOLE_SCALP_ROI] = whole

    low_hair_members = (
        "left_near_ear_posterolateral_approx",
        "right_near_ear_posterolateral_approx",
        "upper_forehead_midline_approx",
        "left_upper_forehead_approx",
        "right_upper_forehead_approx",
        "left_lateral_supraorbital_approx",
        "right_lateral_supraorbital_approx",
    )
    low_hair = np.zeros(len(vertices), dtype=bool)
    for roi_id in low_hair_members:
        low_hair |= masks[roi_id]
    masks[_LOW_HAIR_ROI] = low_hair
    # Exact aliases used by the frozen single-head experiment configuration.
    # They intentionally do not change the scientific status of the masks.
    masks[_WHOLE_SCALP_ALIAS] = whole.copy()
    masks[_LOW_HAIR_ALIAS] = low_hair.copy()
    masks[_LEFT_FOREHEAD_ALIAS] = masks["left_upper_forehead_approx"].copy()
    masks[_RIGHT_FOREHEAD_ALIAS] = masks["right_upper_forehead_approx"].copy()
    return masks


def default_frozen_experiment_families() -> tuple[FrozenFamilyDefinition, ...]:
    """Return the frozen 17-family set for R in {1, 2, 3, 4, 6}."""

    families: list[FrozenFamilyDefinition] = []
    for region_count in (1, 2, 3, 4, 6):
        families.extend(
            (
                FrozenFamilyDefinition(
                    family_id=f"r{region_count}_whole_scalp_free",
                    region_count=region_count,
                    search_mode="free_centers_in_coordinate_domain",
                    region_roi_ids=(_WHOLE_SCALP_ALIAS,) * region_count,
                ),
                FrozenFamilyDefinition(
                    family_id=f"r{region_count}_low_hair_free",
                    region_count=region_count,
                    search_mode="free_centers_in_coordinate_proxy_union",
                    region_roi_ids=(_LOW_HAIR_ALIAS,) * region_count,
                ),
            )
        )

    fixed = (
        ("r2_bilateral_near_ear_diagnostic", (
            "left_near_ear_posterolateral_approx",
            "right_near_ear_posterolateral_approx",
        )),
        ("r2_left_near_ear_plus_mid_forehead_diagnostic", (
            "left_near_ear_posterolateral_approx",
            "upper_forehead_midline_approx",
        )),
        ("r2_right_near_ear_plus_mid_forehead_diagnostic", (
            "right_near_ear_posterolateral_approx",
            "upper_forehead_midline_approx",
        )),
        ("r2_bilateral_expanded_periauricular_diagnostic", (
            "left_expanded_periauricular_approx",
            "right_expanded_periauricular_approx",
        )),
        ("r3_bilateral_near_ear_plus_mid_forehead_diagnostic", (
            "left_near_ear_posterolateral_approx",
            "right_near_ear_posterolateral_approx",
            "upper_forehead_midline_approx",
        )),
        ("r4_bilateral_near_ear_plus_bilateral_upper_forehead_diagnostic", (
            "left_near_ear_posterolateral_approx",
            "right_near_ear_posterolateral_approx",
            _LEFT_FOREHEAD_ALIAS,
            _RIGHT_FOREHEAD_ALIAS,
        )),
        ("r6_ear_forehead_lateral_supraorbital_diagnostic", (
            "left_near_ear_posterolateral_approx",
            "right_near_ear_posterolateral_approx",
            _LEFT_FOREHEAD_ALIAS,
            _RIGHT_FOREHEAD_ALIAS,
            "left_lateral_supraorbital_approx",
            "right_lateral_supraorbital_approx",
        )),
    )
    for family_id, roi_ids in fixed:
        families.append(
            FrozenFamilyDefinition(
                family_id=family_id,
                region_count=len(roi_ids),
                search_mode="fixed_coordinate_proxy_sequence_with_center_exchange",
                region_roi_ids=tuple(roi_ids),
            )
        )
    return tuple(families)


def resolve_anchor_within_mask(
    vertices_m: np.ndarray,
    target_xyz_m: np.ndarray,
    allowed_mask: np.ndarray,
) -> tuple[int, float]:
    """Resolve the nearest permitted surface vertex with global-ID tie break."""

    vertices = _validated_vertices(vertices_m)
    target = np.asarray(target_xyz_m, dtype=np.float64)
    if target.shape != (3,) or not np.all(np.isfinite(target)):
        raise ValueError("target_xyz_m must be a finite length-three vector")
    mask = _validated_mask(allowed_mask, len(vertices), name="allowed_mask")
    candidates = np.flatnonzero(mask)
    if candidates.size == 0:
        raise ValueError("allowed_mask contains no surface vertices")
    distances = np.linalg.norm(vertices[candidates] - target, axis=1)
    local = int(np.argmin(distances))
    return int(candidates[local]), float(distances[local])


def deterministic_chord_farthest_vertex_indices(
    vertices_m: np.ndarray,
    allowed_mask: np.ndarray,
    target_count: int,
    *,
    seed_vertex_indices: Iterable[int] | np.ndarray = (),
) -> np.ndarray:
    """Return a deterministic Euclidean-chord farthest-point subsample.

    Chord farthest-point sampling is a geometry-distribution heuristic, not a
    surface-geodesic optimum.  If no seed is supplied, the first vertex is the
    permitted vertex nearest the permitted-coordinate centroid.
    """

    vertices = _validated_vertices(vertices_m)
    mask = _validated_mask(allowed_mask, len(vertices), name="allowed_mask")
    candidates = np.flatnonzero(mask).astype(np.int64, copy=False)
    if isinstance(target_count, (bool, np.bool_)) or not isinstance(
        target_count, (int, np.integer)
    ):
        raise ValueError("target_count must be an integer")
    count = int(target_count)
    if count < 1 or count > candidates.size:
        raise ValueError("target_count must be between one and allowed count")
    seeds = _validated_indices(
        seed_vertex_indices,
        len(vertices),
        name="seed_vertex_indices",
        allow_empty=True,
    )
    if seeds.size > count:
        raise ValueError("seed count exceeds target_count")
    if seeds.size and not np.all(mask[seeds]):
        raise ValueError("every seed vertex must be permitted by allowed_mask")

    if seeds.size == 0:
        centroid = vertices[candidates].mean(axis=0)
        squared = np.sum((vertices[candidates] - centroid) ** 2, axis=1)
        seeds = np.array([int(candidates[int(np.argmin(squared))])], dtype=np.int64)

    selected = [int(value) for value in seeds]
    minimum_squared = np.full(candidates.size, np.inf, dtype=np.float64)
    for seed in selected:
        delta = vertices[candidates] - vertices[seed]
        minimum_squared = np.minimum(
            minimum_squared, np.einsum("ij,ij->i", delta, delta)
        )
    selected_mask = np.isin(candidates, seeds, assume_unique=False)
    minimum_squared[selected_mask] = -np.inf

    while len(selected) < count:
        local = int(np.argmax(minimum_squared))
        if not np.isfinite(minimum_squared[local]):
            raise RuntimeError("farthest-point subsampling exhausted unexpectedly")
        vertex = int(candidates[local])
        selected.append(vertex)
        selected_mask[local] = True
        delta = vertices[candidates] - vertices[vertex]
        squared = np.einsum("ij,ij->i", delta, delta)
        minimum_squared = np.minimum(minimum_squared, squared)
        minimum_squared[selected_mask] = -np.inf
    return np.asarray(selected, dtype=np.int64)


def build_augmented_global_candidate_bank(
    vertices_m: np.ndarray,
    roi_masks: Mapping[str, np.ndarray],
    *,
    whole_scalp_target_count: int = 4000,
    low_hair_enhancement_target_count: int = 1000,
) -> GlobalCandidateBank:
    """Build the frozen whole-domain bank plus a low-hair-proxy enhancement."""

    vertices = _validated_vertices(vertices_m)
    if _WHOLE_SCALP_ROI not in roi_masks or _LOW_HAIR_ROI not in roi_masks:
        raise ValueError("roi_masks lacks a required aggregate coordinate domain")
    validated = {
        str(roi_id): _validated_mask(mask, len(vertices), name=f"roi_masks[{roi_id}]")
        for roi_id, mask in roi_masks.items()
    }
    whole = deterministic_chord_farthest_vertex_indices(
        vertices,
        validated[_WHOLE_SCALP_ROI],
        whole_scalp_target_count,
    )
    low_mask = validated[_LOW_HAIR_ROI]
    existing_low = whole[low_mask[whole]]
    requested_additional = int(low_hair_enhancement_target_count)
    if requested_additional < 0:
        raise ValueError("low_hair_enhancement_target_count must be nonnegative")
    low_total = min(
        int(np.count_nonzero(low_mask)), int(existing_low.size) + requested_additional
    )
    if low_total > 0:
        low_augmented = deterministic_chord_farthest_vertex_indices(
            vertices,
            low_mask,
            low_total,
            seed_vertex_indices=existing_low,
        )
    else:
        low_augmented = np.empty(0, dtype=np.int64)
    combined = np.unique(np.concatenate((whole, low_augmented))).astype(
        np.int64, copy=False
    )
    actual_enhancement = int(combined.size - whole.size)
    roi_ids = tuple(validated)
    membership = np.column_stack(
        [validated[roi_id][combined] for roi_id in roi_ids]
    ).astype(bool, copy=False)

    aggregate_ids = {
        _WHOLE_SCALP_ROI,
        _LOW_HAIR_ROI,
        _WHOLE_SCALP_ALIAS,
        _LOW_HAIR_ALIAS,
    }
    primary: list[str] = []
    for row in membership:
        member_ids = [roi_ids[index] for index in np.flatnonzero(row)]
        specific = [roi_id for roi_id in member_ids if roi_id not in aggregate_ids]
        if specific:
            primary.append(specific[0])
        elif _LOW_HAIR_ROI in member_ids:
            primary.append(_LOW_HAIR_ROI)
        elif _WHOLE_SCALP_ROI in member_ids:
            primary.append(_WHOLE_SCALP_ROI)
        else:
            primary.append("outside_aggregate_coordinate_domains")
    return GlobalCandidateBank(
        vertex_indices=combined,
        xyz_m=vertices[combined].copy(),
        roi_ids=roi_ids,
        roi_membership=membership,
        primary_roi_labels=np.asarray(primary, dtype="U64"),
        whole_scalp_seed_count=int(whole.size),
        low_hair_enhancement_count=actual_enhancement,
    )


def build_center_shortlist_map(
    vertices_m: np.ndarray,
    bank: GlobalCandidateBank,
    roi_ids: Iterable[str],
    *,
    centers_per_roi: int,
    anchor_vertex_by_roi: Mapping[str, int] | None = None,
) -> dict[str, np.ndarray]:
    """Create deterministic chord-distributed center shortlists within the bank."""

    vertices = _validated_vertices(vertices_m)
    bank_indices = _validated_indices(
        bank.vertex_indices, len(vertices), name="bank.vertex_indices"
    )
    if bank.xyz_m.shape != (bank_indices.size, 3):
        raise ValueError("bank.xyz_m shape is inconsistent")
    if bank.roi_membership.shape != (bank_indices.size, len(bank.roi_ids)):
        raise ValueError("bank.roi_membership shape is inconsistent")
    anchors = {} if anchor_vertex_by_roi is None else dict(anchor_vertex_by_roi)
    output: dict[str, np.ndarray] = {}
    for roi_id in roi_ids:
        if roi_id not in bank.roi_ids:
            raise ValueError(f"unknown bank ROI: {roi_id}")
        column = bank.roi_ids.index(roi_id)
        member_indices = bank_indices[bank.roi_membership[:, column]]
        if member_indices.size < centers_per_roi:
            raise ValueError(f"ROI {roi_id} has fewer bank members than requested centers")
        domain_mask = np.zeros(len(vertices), dtype=bool)
        domain_mask[member_indices] = True
        seed: tuple[int, ...] = ()
        if roi_id in anchors:
            seed = (int(anchors[roi_id]),)
        output[roi_id] = deterministic_chord_farthest_vertex_indices(
            vertices,
            domain_mask,
            centers_per_roi,
            seed_vertex_indices=seed,
        )
    return output


def candidate_graph_distance_matrix(
    distance_cache: GraphDistanceCache,
    center_vertex_indices: Iterable[int] | np.ndarray,
    candidate_vertex_indices: Iterable[int] | np.ndarray,
    *,
    output_dtype: np.dtype | type = np.float32,
) -> CandidateGraphDistances:
    """Compute finite-shortlist source-to-bank mesh-edge distances.

    This function deliberately does not imply that a full bank-by-bank matrix
    should be materialized.  Callers control the bounded center shortlist.
    """

    # GraphDistanceCache validates each source against its graph dimension.
    centers_raw = np.asarray(
        list(center_vertex_indices)
        if not isinstance(center_vertex_indices, np.ndarray)
        else center_vertex_indices
    )
    candidates_raw = np.asarray(
        list(candidate_vertex_indices)
        if not isinstance(candidate_vertex_indices, np.ndarray)
        else candidate_vertex_indices
    )
    if centers_raw.ndim != 1 or centers_raw.size < 1:
        raise ValueError("center_vertex_indices must be a non-empty vector")
    if candidates_raw.ndim != 1 or candidates_raw.size < 1:
        raise ValueError("candidate_vertex_indices must be a non-empty vector")
    if not np.issubdtype(centers_raw.dtype, np.integer):
        raise ValueError("center_vertex_indices must be integer")
    if not np.issubdtype(candidates_raw.dtype, np.integer):
        raise ValueError("candidate_vertex_indices must be integer")
    centers = centers_raw.astype(np.int64, copy=False)
    candidates = candidates_raw.astype(np.int64, copy=False)
    if np.unique(centers).size != centers.size or np.unique(candidates).size != candidates.size:
        raise ValueError("center and candidate vertex indices must each be unique")
    dtype = np.dtype(output_dtype)
    if dtype.kind != "f":
        raise ValueError("output_dtype must be floating point")
    matrix = np.empty((centers.size, candidates.size), dtype=dtype)
    for row, center in enumerate(centers):
        distances = distance_cache.get(int(center))
        if int(candidates.min()) < 0 or int(candidates.max()) >= distances.size:
            raise ValueError("candidate_vertex_indices contains an out-of-range index")
        matrix[row] = distances[candidates]
    if np.any(np.isnan(matrix)):
        raise RuntimeError("candidate graph-distance matrix contains NaN")
    return CandidateGraphDistances(
        center_vertex_indices=centers.copy(),
        candidate_vertex_indices=candidates.copy(),
        distances_m=matrix,
    )


def bounded_center_combinations(
    vertices_m: np.ndarray,
    center_shortlist_by_roi: Mapping[str, np.ndarray],
    region_roi_ids: Sequence[str],
    *,
    minimum_center_chord_distance_m: float = 0.0,
    beam_width: int = 256,
    maximum_combinations: int = 256,
) -> tuple[tuple[int, ...], ...]:
    """Build deterministic, spread-prioritized R-center combinations.

    The beam is a finite heuristic over supplied shortlists.  Its output is not
    an exhaustive continuous-position optimum.
    """

    vertices = _validated_vertices(vertices_m)
    if not region_roi_ids:
        raise ValueError("region_roi_ids must be non-empty")
    spacing = float(minimum_center_chord_distance_m)
    if not np.isfinite(spacing) or spacing < 0.0:
        raise ValueError("minimum_center_chord_distance_m must be finite and nonnegative")
    if beam_width < 1 or maximum_combinations < 1:
        raise ValueError("beam_width and maximum_combinations must be positive")

    choices: list[np.ndarray] = []
    for roi_id in region_roi_ids:
        if roi_id not in center_shortlist_by_roi:
            raise ValueError(f"missing center shortlist for ROI {roi_id}")
        indices = _validated_indices(
            center_shortlist_by_roi[roi_id],
            len(vertices),
            name=f"center_shortlist_by_roi[{roi_id}]",
        )
        choices.append(np.sort(indices))

    beam: list[tuple[tuple[int, ...], float]] = [((), float("inf"))]
    for region_choices in choices:
        expanded: dict[tuple[int, ...], float] = {}
        for prefix, prefix_gap in beam:
            for raw in region_choices:
                candidate = int(raw)
                if candidate in prefix:
                    continue
                if prefix:
                    chords = np.linalg.norm(
                        vertices[np.asarray(prefix, dtype=np.int64)] - vertices[candidate],
                        axis=1,
                    )
                    new_gap = min(prefix_gap, float(chords.min()))
                    if new_gap + 1.0e-12 < spacing:
                        continue
                else:
                    new_gap = float("inf")
                combination = prefix + (candidate,)
                previous = expanded.get(combination)
                if previous is None or new_gap > previous:
                    expanded[combination] = new_gap
        ranked = sorted(expanded.items(), key=lambda item: (-item[1], item[0]))
        beam = ranked[: int(beam_width)]
        if not beam:
            break
    return tuple(prefix for prefix, _ in beam[: int(maximum_combinations)])


def build_region_candidate_pool(
    vertices_m: np.ndarray,
    adjacency: object,
    distance_cache: GraphDistanceCache,
    roi_mask: np.ndarray,
    roi_id: str,
    center_vertex_index: int,
    *,
    graph_path_radius_m: float,
    allowed_electrode_vertex_indices: np.ndarray | None = None,
) -> RegionCandidatePool:
    """Build one connected underlying patch and optionally intersect a bank."""

    vertices = _validated_vertices(vertices_m)
    mask = _validated_mask(roi_mask, len(vertices), name="roi_mask")
    center = int(center_vertex_index)
    if center < 0 or center >= len(vertices) or not mask[center]:
        raise ValueError("center_vertex_index must be inside roi_mask")
    radius = float(graph_path_radius_m)
    distances = distance_cache.get(center)
    patch = build_coordinate_clipped_patch(
        adjacency, distances, mask, center, graph_path_radius_m=radius
    )
    candidates = patch.candidate_vertex_indices
    if allowed_electrode_vertex_indices is not None:
        allowed = _validated_indices(
            allowed_electrode_vertex_indices,
            len(vertices),
            name="allowed_electrode_vertex_indices",
        )
        candidates = np.intersect1d(candidates, allowed, assume_unique=False)
    if candidates.size == 0:
        raise ValueError("connected radius domain contains no allowed electrode candidates")
    return RegionCandidatePool(
        roi_id=str(roi_id),
        center_vertex_index=center,
        center_xyz_m=vertices[center].copy(),
        graph_path_radius_m=radius,
        candidate_vertex_indices=candidates.astype(np.int64, copy=False),
        candidate_xyz_m=vertices[candidates].copy(),
        candidate_center_graph_distances_m=distances[candidates].copy(),
        underlying_connected_patch_vertex_count=int(
            patch.candidate_vertex_indices.size
        ),
        graph_disk_vertex_count=patch.graph_disk_vertex_count,
        coordinate_clipped_vertex_count=patch.coordinate_clipped_vertex_count,
        disconnected_vertex_count_removed=patch.disconnected_vertex_count_removed,
    )


def _eligible_by_chord(
    vertices: np.ndarray,
    candidates: np.ndarray,
    selected: Sequence[int],
    spacing_m: float,
) -> np.ndarray:
    eligible = np.ones(candidates.size, dtype=bool)
    if selected:
        selected_xyz = vertices[np.asarray(selected, dtype=np.int64)]
        # Chunking is unnecessary for 64 selected nodes and <=6000 candidates.
        for xyz in selected_xyz:
            squared = np.sum((vertices[candidates] - xyz) ** 2, axis=1)
            eligible &= squared + 1.0e-24 >= spacing_m * spacing_m
    return eligible


def _rank_candidates(
    candidates: np.ndarray,
    eligible: np.ndarray,
    minimum_graph_distance: np.ndarray,
) -> np.ndarray:
    local = np.flatnonzero(eligible)
    if local.size == 0:
        return local
    # np.lexsort uses the last key first: descending score, then global ID.
    order = np.lexsort((candidates[local], -minimum_graph_distance[local]))
    return local[order]


def _region_greedy_with_tail_repair(
    vertices: np.ndarray,
    pool: RegionCandidatePool,
    requested_count: int,
    blocked_global: Sequence[int],
    preferred_seed: int,
    spacing_m: float,
    distance_cache: GraphDistanceCache,
    *,
    repair_depth: int,
    repair_branch_width: int,
    maximum_repair_nodes: int,
) -> list[int]:
    candidates = pool.candidate_vertex_indices
    global_block = list(int(value) for value in blocked_global)
    selected: list[int] = []
    minimum_graph = np.full(candidates.size, np.inf, dtype=np.float64)

    seed_order = [int(preferred_seed), int(pool.center_vertex_index)]
    seed_order.extend(int(value) for value in candidates)
    for seed in dict.fromkeys(seed_order):
        matches = np.flatnonzero(candidates == seed)
        if matches.size == 0:
            continue
        if _eligible_by_chord(vertices, np.array([seed]), global_block, spacing_m)[0]:
            selected.append(seed)
            minimum_graph = np.minimum(
                minimum_graph, distance_cache.get(seed)[candidates]
            )
            break
    if not selected:
        return []

    while len(selected) < requested_count:
        eligible = _eligible_by_chord(
            vertices, candidates, global_block + selected, spacing_m
        )
        eligible &= ~np.isin(candidates, np.asarray(selected, dtype=np.int64))
        ranked = _rank_candidates(candidates, eligible, minimum_graph)
        if ranked.size == 0:
            break
        chosen = int(candidates[int(ranked[0])])
        selected.append(chosen)
        minimum_graph = np.minimum(
            minimum_graph, distance_cache.get(chosen)[candidates]
        )
    if len(selected) == requested_count or repair_depth < 1:
        return selected

    cut = min(int(repair_depth), len(selected))
    prefix = selected[:-cut]
    prefix_minimum = np.full(candidates.size, np.inf, dtype=np.float64)
    for chosen in prefix:
        prefix_minimum = np.minimum(
            prefix_minimum, distance_cache.get(chosen)[candidates]
        )
    nodes_visited = 0
    best = list(selected)

    def search(current: list[int], minimum_graph_distance: np.ndarray) -> list[int] | None:
        nonlocal nodes_visited, best
        if len(current) > len(best):
            best = list(current)
        if len(current) == requested_count:
            return list(current)
        if nodes_visited >= maximum_repair_nodes:
            return None
        nodes_visited += 1
        eligible = _eligible_by_chord(
            vertices, candidates, global_block + current, spacing_m
        )
        eligible &= ~np.isin(candidates, np.asarray(current, dtype=np.int64))
        ranked = _rank_candidates(candidates, eligible, minimum_graph_distance)
        for local in ranked[: int(repair_branch_width)]:
            chosen = int(candidates[int(local)])
            updated = np.minimum(
                minimum_graph_distance, distance_cache.get(chosen)[candidates]
            )
            result = search(current + [chosen], updated)
            if result is not None:
                return result
        return None

    repaired = search(list(prefix), prefix_minimum)
    return best if repaired is None else repaired


def _bounded_region_orders(region_count: int, maximum_orders: int) -> list[tuple[int, ...]]:
    base = tuple(range(region_count))
    proposals = [base, tuple(reversed(base))]
    proposals.extend(base[offset:] + base[:offset] for offset in range(1, region_count))
    if region_count <= 4:
        proposals.extend(permutations(base))
    unique: list[tuple[int, ...]] = []
    for order in proposals:
        candidate = tuple(order)
        if len(candidate) == region_count and len(set(candidate)) == region_count:
            if candidate not in unique:
                unique.append(candidate)
        if len(unique) >= maximum_orders:
            break
    return unique


def construct_multiregion_layout(
    vertices_m: np.ndarray,
    region_pools: Sequence[RegionCandidatePool],
    requested_region_counts: Sequence[int],
    distance_cache: GraphDistanceCache,
    *,
    minimum_chord_distance_m: float,
    maximum_trials: int = 48,
    maximum_region_orders: int = 12,
    seeds_per_region: int = 4,
    repair_depth: int = 2,
    repair_branch_width: int = 3,
    maximum_repair_nodes: int = 96,
) -> MultiRegionLayoutResult:
    """Search for one fixed-total layout using multistart greedy and tail repair.

    Candidate patches may overlap.  Only selected physical nodes must be unique,
    and every selected pair must pass the global Euclidean chord-spacing check.
    """

    vertices = _validated_vertices(vertices_m)
    pools = tuple(region_pools)
    counts = np.asarray(requested_region_counts, dtype=np.int64)
    if not pools or counts.shape != (len(pools),) or np.any(counts < 1):
        raise ValueError("one positive requested count is required per region pool")
    if int(counts.sum()) != 64:
        raise ValueError("requested_region_counts must total 64 physical nodes")
    spacing = float(minimum_chord_distance_m)
    if not np.isfinite(spacing) or spacing <= 0.0:
        raise ValueError("minimum_chord_distance_m must be finite and positive")
    for index, pool in enumerate(pools):
        candidates = _validated_indices(
            pool.candidate_vertex_indices,
            len(vertices),
            name=f"region_pools[{index}].candidate_vertex_indices",
        )
        if candidates.size < counts[index]:
            # Continue through the common failure return instead of claiming
            # geometric infeasibility.
            pass
        if pool.candidate_xyz_m.shape != (candidates.size, 3):
            raise ValueError(f"region_pools[{index}].candidate_xyz_m shape is inconsistent")
        if pool.candidate_center_graph_distances_m.shape != (candidates.size,):
            raise ValueError(
                f"region_pools[{index}].candidate graph-distance shape is inconsistent"
            )
        if not np.allclose(pool.candidate_xyz_m, vertices[candidates], rtol=0.0, atol=0.0):
            raise ValueError(f"region_pools[{index}] candidate coordinates do not match vertices")
    radii = np.asarray([pool.graph_path_radius_m for pool in pools], dtype=np.float64)
    if not np.all(np.isfinite(radii)) or np.any(radii <= 0.0):
        raise ValueError("every region pool must have a finite positive radius cap")
    if not np.allclose(radii, radii[0], rtol=0.0, atol=1.0e-15):
        raise ValueError("all regions in one frozen condition must share one radius cap")

    seed_options: list[list[int]] = []
    for pool in pools:
        candidates = pool.candidate_vertex_indices
        ranked = np.lexsort(
            (candidates, -pool.candidate_center_graph_distances_m)
        )
        options = [int(pool.center_vertex_index)]
        options.extend(int(candidates[local]) for local in ranked)
        seed_options.append(list(dict.fromkeys(options))[: int(seeds_per_region)])

    orders = _bounded_region_orders(len(pools), int(maximum_region_orders))
    trial_specs: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    for order_index, order in enumerate(orders):
        for offset in range(max(len(options) for options in seed_options)):
            seeds = tuple(
                options[(offset + region + order_index) % len(options)]
                for region, options in enumerate(seed_options)
            )
            specification = (order, seeds)
            if specification not in trial_specs:
                trial_specs.append(specification)
            if len(trial_specs) >= int(maximum_trials):
                break
        if len(trial_specs) >= int(maximum_trials):
            break

    best_selected: list[int] = []
    best_regions: list[int] = []
    best_counts = np.zeros(len(pools), dtype=np.int64)
    best_success: tuple[float, tuple[int, ...], list[int], list[int], np.ndarray] | None = None
    successful_trials = 0

    for order, seeds in trial_specs:
        selected: list[int] = []
        region_labels: list[int] = []
        achieved = np.zeros(len(pools), dtype=np.int64)
        for region_index in order:
            local = _region_greedy_with_tail_repair(
                vertices,
                pools[region_index],
                int(counts[region_index]),
                selected,
                seeds[region_index],
                spacing,
                distance_cache,
                repair_depth=int(repair_depth),
                repair_branch_width=int(repair_branch_width),
                maximum_repair_nodes=int(maximum_repair_nodes),
            )
            selected.extend(local)
            region_labels.extend([region_index] * len(local))
            achieved[region_index] = len(local)
            if len(local) != int(counts[region_index]):
                break

        partial_key = (len(selected), tuple(int(value) for value in achieved))
        best_partial_key = (len(best_selected), tuple(int(value) for value in best_counts))
        if partial_key > best_partial_key or (
            partial_key == best_partial_key and tuple(selected) < tuple(best_selected)
        ):
            best_selected = list(selected)
            best_regions = list(region_labels)
            best_counts = achieved.copy()

        if len(selected) == 64 and np.unique(selected).size == 64:
            minimum = minimum_pairwise_chord_distance(
                vertices, np.asarray(selected, dtype=np.int64)
            )
            if minimum + 1.0e-12 < spacing:
                raise RuntimeError("internal error: complete layout violates spacing")
            successful_trials += 1
            key = (minimum, tuple(-value for value in selected))
            if best_success is None or key > (best_success[0], best_success[1]):
                best_success = (
                    minimum,
                    tuple(-value for value in selected),
                    list(selected),
                    list(region_labels),
                    achieved.copy(),
                )

    method = (
        "deterministic_multistart_region_order_greedy_graph_maximin_with_"
        "global_chord_filter_and_bounded_tail_repair"
    )
    if best_success is not None:
        minimum, _, selected, region_labels, achieved = best_success
        return MultiRegionLayoutResult(
            status="success",
            electrode_vertex_indices=np.asarray(selected, dtype=np.int64),
            electrode_region_indices=np.asarray(region_labels, dtype=np.int8),
            requested_region_counts=counts.copy(),
            achieved_region_counts=achieved,
            minimum_global_chord_distance_m=float(minimum),
            trials_evaluated=len(trial_specs),
            successful_trials=successful_trials,
            search_method=method,
        )

    minimum = float("nan")
    if len(best_selected) >= 2:
        minimum = minimum_pairwise_chord_distance(
            vertices, np.asarray(best_selected, dtype=np.int64)
        )
    return MultiRegionLayoutResult(
        status="not_found_by_bounded_search_not_an_infeasibility_proof",
        electrode_vertex_indices=np.asarray(best_selected, dtype=np.int64),
        electrode_region_indices=np.asarray(best_regions, dtype=np.int8),
        requested_region_counts=counts.copy(),
        achieved_region_counts=best_counts,
        minimum_global_chord_distance_m=minimum,
        trials_evaluated=len(trial_specs),
        successful_trials=0,
        search_method=method,
    )


__all__ = [
    "ApproximateROITemplate",
    "CandidateGraphDistances",
    "FrozenFamilyDefinition",
    "GlobalCandidateBank",
    "MultiRegionLayoutResult",
    "RegionCandidatePool",
    "balanced_region_point_counts",
    "bounded_center_combinations",
    "build_augmented_global_candidate_bank",
    "build_center_shortlist_map",
    "build_default_approximate_roi_masks",
    "build_region_candidate_pool",
    "candidate_graph_distance_matrix",
    "construct_multiregion_layout",
    "default_approximate_roi_templates",
    "default_frozen_experiment_families",
    "default_roi_anchor_targets_m",
    "deterministic_chord_farthest_vertex_indices",
    "resolve_anchor_within_mask",
]
