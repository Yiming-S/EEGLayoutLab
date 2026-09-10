"""Machine-checkable invariants for experiment protocol V2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

TOTAL_ELECTRODES = 64
REGION_COUNTS = (1, 2, 3, 4, 6)


def balanced_allocation(region_count: int, total: int = TOTAL_ELECTRODES) -> tuple[int, ...]:
    """Allocate ``total`` contacts as evenly as possible across regions."""
    if not isinstance(region_count, int) or region_count < 1:
        raise ValueError("region_count must be a positive integer")
    if not isinstance(total, int) or total < region_count:
        raise ValueError("total must be an integer at least as large as region_count")
    quotient, remainder = divmod(total, region_count)
    return tuple(quotient + (index < remainder) for index in range(region_count))


def load_protocol(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("protocol root must be a JSON object")
    return value


def canonical_json_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ValueError(f"{label}: expected {expected!r}, got {actual!r}")


def validate_protocol(protocol: Mapping[str, Any]) -> None:
    """Reject any protocol that silently reintroduces the V1 problem."""
    _require_equal(protocol.get("status"), "design_only_no_results", "status")

    design = protocol.get("design")
    if not isinstance(design, Mapping):
        raise ValueError("design must be an object")
    _require_equal(design.get("total_measurement_electrodes"), TOTAL_ELECTRODES, "total electrodes")
    _require_equal(design.get("constant_total_electrodes"), True, "constant total")
    _require_equal(design.get("reference_ground_included"), False, "reference/ground rule")
    _require_equal(tuple(design.get("region_counts", ())), REGION_COUNTS, "region counts")
    _require_equal(
        design.get("primary_size_estimand"),
        "minimum_verified_maximum_actual_geodesic_disk_radius",
        "primary size estimand",
    )

    allocations = design.get("balanced_allocations")
    if not isinstance(allocations, Mapping):
        raise ValueError("balanced_allocations must be an object")
    for region_count in REGION_COUNTS:
        actual = allocations.get(str(region_count))
        if not isinstance(actual, Sequence) or isinstance(actual, (str, bytes)):
            raise ValueError(f"allocation for R={region_count} must be an array")
        _require_equal(tuple(actual), balanced_allocation(region_count), f"allocation for R={region_count}")

    reference = protocol.get("reference_system")
    if not isinstance(reference, Mapping):
        raise ValueError("reference_system must be an object")
    _require_equal(reference.get("physical_electrodes"), TOTAL_ELECTRODES, "reference electrode count")
    _require_equal(reference.get("reference_free_dimensions"), TOTAL_ELECTRODES - 1, "reference-free dimensions")

    surface = protocol.get("surface_domain")
    if not isinstance(surface, Mapping):
        raise ValueError("surface_domain must be an object")
    _require_equal(surface.get("mode"), "continuous_anatomical_surface_mesh", "surface mode")
    if surface.get("candidate_count") == TOTAL_ELECTRODES:
        raise ValueError("candidate domain cannot be the 64 BioSemi reference points")

    scope = protocol.get("scientific_scope")
    if not isinstance(scope, Mapping):
        raise ValueError("scientific_scope must be an object")
    _require_equal(
        scope.get("primary_source_domain"),
        "whole_cortical_surface_normal_dipoles",
        "primary source domain",
    )
    _require_equal(scope.get("whole_brain_volume_claim_allowed"), False, "whole-brain claim rule")

    region_model = protocol.get("region_model")
    if not isinstance(region_model, Mapping):
        raise ValueError("region_model must be an object")
    _require_equal(region_model.get("primary_shape"), "minimum_enclosing_geodesic_disk", "primary shape")
    _require_equal(
        region_model.get("radius_curve_constraint"),
        "a_r_less_than_or_equal_to_common_radius_cap_a",
        "radius-cap nesting rule",
    )
    _require_equal(
        region_model.get("region_disk_must_be_contained_in_assigned_mask"),
        True,
        "disk containment rule",
    )

    preset_matrix = protocol.get("anatomical_preset_matrix")
    if not isinstance(preset_matrix, Mapping):
        raise ValueError("anatomical_preset_matrix must be an object")
    for region_count in REGION_COUNTS:
        presets = preset_matrix.get(str(region_count))
        if not isinstance(presets, Sequence) or isinstance(presets, (str, bytes)) or not presets:
            raise ValueError(f"preset matrix for R={region_count} must be a non-empty array")
        for preset in presets:
            if not isinstance(preset, Mapping):
                raise ValueError(f"every R={region_count} preset must be an object")
            _require_equal(
                tuple(preset.get("allocation", ())),
                balanced_allocation(region_count),
                f"preset allocation for {preset.get('id', 'unnamed')}",
            )

    acceptance = protocol.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise ValueError("acceptance must be an object")
    default_ar = acceptance.get("display_default_ar")
    if not isinstance(default_ar, (int, float)) or not 0 < float(default_ar) <= 1:
        raise ValueError("display_default_ar must lie in (0, 1]")
    _require_equal(acceptance.get("semantics"), "acceptance_threshold_not_accuracy", "AR semantics")
    _require_equal(acceptance.get("bootstrap_unit"), "head_model", "AR bootstrap unit")
    minimum_test_heads = acceptance.get("minimum_test_heads_for_formal_tail_certification")
    if not isinstance(minimum_test_heads, int) or minimum_test_heads < 100:
        raise ValueError("formal 10% head-tail certification requires at least 100 test heads")

    metrics = protocol.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError("metrics must be an object")
    for metric_name in ("field_reconstruction", "source_sensitivity", "source_localization"):
        if not isinstance(metrics.get(metric_name), Mapping):
            raise ValueError(f"metrics.{metric_name} must be an object")
    _require_equal(
        metrics["source_sensitivity"].get("aggregation_order"),
        "sources_then_heads",
        "sensitivity aggregation order",
    )
    _require_equal(
        metrics["source_localization"].get("primary_d_max_mm"),
        50.0,
        "localization utility distance",
    )

    noise = protocol.get("noise_model")
    if not isinstance(noise, Mapping):
        raise ValueError("noise_model must be an object")
    _require_equal(
        noise.get("noise_cross_covariance_is_excluded_from_LMMSE_target_observation_covariance"),
        True,
        "LMMSE noise cross-covariance rule",
    )

    claims = protocol.get("claims")
    if not isinstance(claims, Mapping):
        raise ValueError("claims must be an object")
    _require_equal(claims.get("v2_results_available"), False, "V2 result availability")
    _require_equal(claims.get("task_accuracy_claims_allowed"), False, "task claim rule")
