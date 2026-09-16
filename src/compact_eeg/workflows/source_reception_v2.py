"""Additive fixed-normal source experiments; the v1 engine remains unchanged.

Version 2 adds explicit single-source selection, cross-region source sets and
audited native-coordinate forward providers. It does not add free dipole
orientation or a new estimator.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Callable

import numpy as np
import scipy

from . import source_reception as legacy
from . import source_roi

SCHEMA_VERSION = "source-reception/2"
ALGORITHM_VERSION = "source-reception-fixed-normal-v4-dk-roi"
CATALOG_SCHEMA_VERSION = "source-catalog/1"
GENERATION_COUNT = 256
CROSS_REGION_ORDER = ("frontal", "central", "parietal", "occipital", "temporal_left", "temporal_right")
COORDINATE_SYSTEM = "Ernie MRI coordinates: X right, Y anterior, Z superior; millimetres"
DEPENDENCY_PATHS = (
    "src/compact_eeg/workflows/__init__.py",
    "src/compact_eeg/workflows/paths.py",
    "src/compact_eeg/workflows/source_reception.py",
    "src/compact_eeg/workflows/source_reception_v2.py",
    "src/compact_eeg/workflows/source_roi.py",
    "src/compact_eeg/workflows/reception_forward_provider.py",
    "scripts/source_reception.py",
    "scripts/source_reception_v2.py",
    "scripts/run_source_reception_v2.py",
    "scripts/reception_forward_provider.py",
)


def validate_request(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("A v2 source request must be an object")
    mode = value.get("mode")
    if mode not in ("single_source", "multi_source", "cross_region"):
        raise ValueError("mode must be single_source, multi_source or cross_region")
    specific = {"single_source": "source_index", "multi_source": "brain_region", "cross_region": "brain_regions"}[mode]
    fields = {"record_id", "mode", specific, "waveform", "artifact_scale", "seed"}
    if "region_definition" in value:
        fields.add("region_definition")
        if value["region_definition"] != source_roi.DEFINITION_ID:
            raise ValueError("Unsupported source ROI definition")
    if set(value) != fields:
        raise ValueError(f"{mode} requires exactly {', '.join(sorted(fields))}; direction and arbitrary coordinates are not accepted")
    if mode == "single_source":
        index = value["source_index"]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < GENERATION_COUNT:
            raise ValueError("source_index must be an integer from 0 through 255")
    if mode == "cross_region":
        regions = value["brain_regions"]
        if (not isinstance(regions, list) or not 1 <= len(regions) <= len(CROSS_REGION_ORDER)
                or any(not isinstance(region, str) or region not in CROSS_REGION_ORDER for region in regions)
                or len(set(regions)) != len(regions)):
            raise ValueError("brain_regions must contain one to six unique supported coordinate-region names")
    # Reuse v1 bounds for the unchanged physical and stochastic parameters.
    legacy.validate_request({
        "record_id": value["record_id"],
        "brain_region": value.get("brain_region", "frontal"),
        "waveform": value["waveform"], "artifact_scale": value["artifact_scale"],
        "seed": value["seed"],
    })
    result = dict(value)
    if mode == "cross_region":
        result["brain_regions"] = [region for region in CROSS_REGION_ORDER if region in value["brain_regions"]]
    return result


def cross_region_representatives(xyz: np.ndarray) -> list[dict]:
    """Assign all six anchors before selecting a subset, with stable unique IDs.

    Each anchor takes the nearest still-unassigned generation source in canonical
    region order. Equal distances choose the lowest source index. This explicit
    collision rule is a coordinate-proxy selection, not anatomical parcellation.
    """
    xyz = np.asarray(xyz, dtype=np.float64)
    if xyz.shape != (GENERATION_COUNT, 3) or not np.isfinite(xyz).all():
        raise ValueError("Cross-region representatives require the frozen 256 generation-source positions")
    available = np.ones(GENERATION_COUNT, dtype=bool)
    representatives = []
    for region in CROSS_REGION_ORDER:
        anchor = np.asarray(legacy.REGION_ANCHORS_MM[region], dtype=np.float64)
        distance_sq = np.sum((xyz - anchor) ** 2, axis=1)
        index = int(np.argmin(np.where(available, distance_sq, np.inf)))
        available[index] = False
        representatives.append({"source_region": region, "generation_source_index": index,
                                "anchor_xyz_mm": anchor.tolist(), "xyz_mm": xyz[index].tolist(),
                                "anchor_distance_mm": float(np.sqrt(distance_sq[index]))})
    return representatives


def select_cross_region_sources(xyz: np.ndarray, regions: list[str], dictionary_count: int) -> tuple[np.ndarray, np.ndarray, dict]:
    """Canonical selected subset of the full six-anchor assignment; equal power."""
    if (not isinstance(regions, list) or not 1 <= len(regions) <= len(CROSS_REGION_ORDER)
            or any(not isinstance(region, str) or region not in CROSS_REGION_ORDER for region in regions)
            or len(set(regions)) != len(regions)):
        raise ValueError("brain_regions must contain one to six unique supported coordinate-region names")
    selected = [entry for entry in cross_region_representatives(xyz) if entry["source_region"] in regions]
    ids = np.asarray([entry["generation_source_index"] for entry in selected], dtype=int)
    count = len(selected)
    weights = np.full(count, 1. / count, dtype=np.float64)
    return ids, weights, {
        "mode": "cross_region", "region": "cross_region",
        "source_regions": [entry["source_region"] for entry in selected],
        "selection_method": "one nearest unassigned generation source per coordinate anchor in fixed six-region order; full assignment computed before subset selection; not an anatomical atlas",
        "representative_assignment_order": list(CROSS_REGION_ORDER),
        "coordinate_axes": COORDINATE_SYSTEM,
        "anchor_xyz_mm": [entry["anchor_xyz_mm"] for entry in selected],
        "xyz_mm": [entry["xyz_mm"] for entry in selected],
        "anchor_distances_mm": [entry["anchor_distance_mm"] for entry in selected],
        "patch_count": count, "generation_source_indices": ids.tolist(),
        "bank_source_indices": (dictionary_count + ids).tolist(),
        "patch_area_weights": weights.tolist(),
        "source_power_weights": weights.tolist(),
        "source_weight_definition": "equal 1/K source-moment power weights, not cortical-area weights",
        "source_power_normalization": "sum of per-source mean-square moments equals SOURCE_MOMENT_AM squared; sensor field power need not stay constant",
    }


def _generation_geometry(catalog: dict) -> tuple[np.ndarray, np.ndarray]:
    xyz = np.asarray(catalog["generation_xyz_mm"], dtype=np.float64)
    normals = np.asarray(catalog["generation_normals"], dtype=np.float64)
    if xyz.shape != (GENERATION_COUNT, 3) or normals.shape != xyz.shape:
        raise ValueError("The frozen generation catalog must contain 256 xyz and normal vectors")
    if not np.isfinite(xyz).all() or not np.isfinite(normals).all():
        raise ValueError("Source geometry must be finite")
    if not np.allclose(np.linalg.norm(normals, axis=1), 1., atol=1e-6, rtol=0):
        raise ValueError("Source normals must be the unit normals used by the frozen forward model")
    return xyz, normals


def get_source_catalog(root: Path) -> dict:
    """Read-only catalog for the UI; no FEM, noise generation, or simulation."""
    from .reception_forward_provider import load_frozen_source_catalog

    catalog, provenance = load_frozen_source_catalog(Path(root).resolve())
    xyz, normals = _generation_geometry(catalog)
    atlas = source_roi.load_atlas(Path(root).resolve(), catalog, provenance["source_inputs_sha256"])
    if int(catalog["dictionary_count"]) != 4096:
        raise ValueError("The catalog must share the frozen 4096-source reconstruction prior")
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "coordinate_system": COORDINATE_SYSTEM,
        "coordinate_unit": "mm", "normal_unit": "dimensionless unit vector",
        "orientation_mode": "fixed_cortical_normal",
        "source_count": GENERATION_COUNT, "dictionary_source_count": 4096,
        "region_definition": source_roi.DEFINITION_ID,
        "atlas_sha256": atlas["sha256"],
        "roi_definition": atlas["definition"],
        "sources": atlas["generation_sources"],
        "cross_region_order": list(CROSS_REGION_ORDER),
        "cross_region_representatives": [
            {**entry, "xyz_mm": xyz[entry["generation_source_index"]].tolist(),
             "bank_source_index": 4096 + entry["generation_source_index"],
             "normal": normals[entry["generation_source_index"]].tolist()}
            for entry in source_roi.representatives(atlas, xyz)],
        "provenance": provenance,
        "limitations": [
            "These are the original off-dictionary generation locations, not a continuous draggable source model.",
            "The normal is an immutable physical direction used in the stored FEM column, not an editable arrow.",
            "ROIs merge native DK40 labels using the published mapping table; mixed-ROI boundary faces and ungrouped parcels remain unassigned. The head model is Ernie.",
        ],
    }


def load_inputs(root: Path, payload: object, progress: Callable[..., None] | None = None) -> tuple[dict, dict, dict, dict]:
    from .reception_forward_provider import load_reception_forward

    root = Path(root).resolve()
    if not isinstance(payload, dict) or set(payload) != {"request", "record"}:
        raise ValueError("Input must contain exactly request and the resolved saved record")
    request = validate_request(payload["request"])
    record = payload["record"]
    if not isinstance(record, dict) or record.get("id") != request["record_id"]:
        raise ValueError("Resolved record ID does not match the requested record_id")
    if record.get("status") != "completed" or not isinstance(record.get("layout"), dict):
        raise ValueError("Version 2 requires a completed saved layout, never a design preview")
    if request["mode"] == "multi_source" and not request.get("region_definition") and record.get("dataset_id") != "design_evaluation":
        raise ValueError("Existing bank-layout multi-source experiments remain on v1; v2 multi_source is for completed native-coordinate design_evaluation records")
    provider_progress = None if progress is None else lambda fraction, message: progress(
        stage="forward", progress=.05 + .10 * float(np.clip(fraction, 0., 1.)), message=message)
    inputs, provenance = load_reception_forward(root, record, progress=provider_progress, allow_native=True)
    _generation_geometry(inputs)
    if request.get("region_definition"):
        inputs["source_atlas"] = source_roi.load_atlas(root, inputs, provenance["source_inputs_sha256"])
        provenance["source_atlas_sha256"] = inputs["source_atlas"]["sha256"]
        provenance["source_roi_definition"] = source_roi.DEFINITION_ID
    if int(inputs["dictionary_count"]) != 4096:
        raise ValueError("A v2 forward record must retain the frozen 4096-source reconstruction prior")
    provenance = {
        **provenance,
        "algorithm_version": ALGORITHM_VERSION, "schema_version": SCHEMA_VERSION,
        "record_id": request["record_id"], "record_dataset_id": record["dataset_id"],
        "record_label": record.get("label"),
        "code_sha256": {**provenance.get("code_sha256", {}),
                        **{name: legacy.sha256_file(root / name) for name in DEPENDENCY_PATHS}},
        "python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__,
        "thread_limit": 1, "layout_optimized": False,
        "orientation_mode": "fixed_cortical_normal", "free_orientation_computed": False,
        "independent_head_validation": False, "formal_population_ar": False,
        "classification_accuracy_computed": False, "source_localization_computed": False,
        "physiological_artifact_forward_model": False,
    }
    return request, record, inputs, provenance


def _single_source_result(inputs: dict, request: dict, progress: Callable[..., None]) -> dict:
    n = int(inputs["dictionary_count"])
    b, x = np.asarray(inputs["baseline_h"]), np.asarray(inputs["candidate_h"])
    xyz, _ = _generation_geometry(inputs)
    if b.shape != (64, n + GENERATION_COUNT) or x.shape != b.shape or not np.isfinite(b).all() or not np.isfinite(x).all():
        raise ValueError("Both forward matrices must share the complete prior and generation-source columns")
    index = request["source_index"]
    progress(stage="decoder", progress=.20, message="保持全脑先验与共同噪声；单源选择不参与重建器拟合")
    decoders = legacy.fit_decoders(b[:, :n], x[:, :n], inputs["area_weights"])
    latents = legacy.generate_latents(request["seed"], request["waveform"], np.ones(1))
    maps, calibration = legacy.artifact_maps(inputs["baseline_xyz_mm"], inputs["candidate_xyz_mm"], decoders["signal_std_v"])
    progress(stage="propagation", progress=.40, message="以原始皮层法向传播同一单源到两套64点布局")
    parts = {}
    for side, h in (("baseline", b), ("candidate", x)):
        p = {"brain": legacy.average_reference(h[:, n + index:n + index + 1] @ latents["source_am"]),
             "ecg": maps["ecg"][side][:, None] * latents["ecg"],
             "eog": maps["eog"][side][:, None] * latents["eog"],
             "noise": legacy.average_reference(latents["noise_" + side] * decoders["noise_std_v"])}
        p.update({"reconstructed_" + kind: decoders[side] @ p[kind] for kind in legacy.COMPONENTS})
        parts[side] = p
    target = parts["baseline"]["brain"]
    scale = request["artifact_scale"]
    progress(stage="evaluation", progress=.60, message="以完整20秒200Hz数据评价四条件和16个曲线点")
    conditions = [legacy.evaluate_condition(parts, target, kind, 0. if kind == "clean" else scale)
                  for kind in legacy.CONDITIONS]
    curve = [legacy.evaluate_condition(parts, target, "clean", 0.)]
    curve.extend(legacy.evaluate_condition(parts, target, kind, strength)
                 for kind in ("ecg", "eog", "mixed") for strength in legacy.STRENGTHS)
    amplitude_b = float(np.sqrt(np.mean(np.ptp(target, axis=0) ** 2)))
    amplitude_x = float(np.sqrt(np.mean(np.ptp(parts["candidate"]["brain"], axis=0) ** 2)))
    progress(stage="preview", progress=.80, message="生成抗混叠显示预览；分数不使用降采样数据")
    waveforms = {
        "time_s": (np.arange(legacy.PREVIEW_DURATION * legacy.PREVIEW_RATE) / legacy.PREVIEW_RATE).tolist(),
        "source_nam": legacy.preview(latents["source_am"], 1e9),
        "ecg_latent": legacy.preview(latents["ecg"]), "eog_latent": legacy.preview(latents["eog"]),
    }
    for side in ("baseline", "candidate"):
        waveforms[side] = {kind + "_uv": legacy.preview(values, 1e6 * (scale if kind in (
            "ecg", "eog", "reconstructed_ecg", "reconstructed_eog") else 1.)) for kind, values in parts[side].items()}
    return {
        "status": "completed", "request": request,
        "source": {"mode": "single_source", "region": "single_source", "source_index": index,
                   "selection_method": "explicit original off-dictionary generation source index; no source snapping or direction fitting",
                   "coordinate_axes": COORDINATE_SYSTEM, "xyz_mm": xyz[index:index + 1].tolist(),
                   "patch_count": 1, "generation_source_indices": [index], "bank_source_indices": [n + index],
                   "waveform": request["waveform"], "source_moment_norm_rms_nam": legacy.SOURCE_MOMENT_AM * 1e9,
                   "patch_area_weights": [1.]},
        "protocol": {
            "sample_rate_hz": legacy.SAMPLE_RATE, "duration_s": legacy.DURATION,
            "preview_rate_hz": legacy.PREVIEW_RATE, "preview_duration_s": legacy.PREVIEW_DURATION,
            "preview_filter": "v1 resample_poly 200-to-50 Hz anti-alias filter; first eight seconds only; never used for metrics",
            "physical_electrode_count": 64, "independent_reference_dimensions": 63,
            "reference": "separate common-average reference for each layout; reconstruction target is the same standard64 clean brain field",
            "reconstruction_target": "same clean average-referenced standard64 brain field, excluding ECG/EOG and sensor noise",
            "source_prior": "unchanged full-brain dictionary with independent moment^2 times normalized cortical-area covariance; not conditioned on selected source",
            "decoder": "v1 frozen clean-prior LMMSE with common physical electrode-noise variance; no selected-source or artifact training",
            "artifact_model": "unchanged hypothetical fixed-coordinate ECG/EOG fields, not measured or physiological cardiac/ocular forward models",
            "artifact_calibration": calibration,
            "brain_attenuation": "included in the FEM column; no additional distance decay",
            "noise": "same physical sigma for both layouts; independent layout draws reused across all artifact conditions and strengths",
            "nominal_prior_snr_db": legacy.NOMINAL_PRIOR_SNR_DB,
            "physical_electrode_noise_std_uv": decoders["noise_std_v"] * 1e6,
            "baseline_prior_contrast_signal_std_uv": decoders["signal_std_v"] * 1e6,
            "relative_denominator_epsilon": legacy.RELATIVE_DENOMINATOR_EPSILON,
            "ar_scope": "only the selected source and artifact condition's field-retention ratio; not all-brain coverage, localization, or classification accuracy",
            "curve_uses_same_brain_and_noise": True, "display_artifacts_already_scaled": True,
            "same_model_limitation": "shared Ernie anatomy and solver; off-dictionary does not mean independent-head validation",
            "identity_noise": "layout noise realizations remain independent; exact identity tests use common observations",
        },
        "events": {"ecg_beat_times_s": latents["ecg_beat_times_s"], "blink_times_s": latents["blink_times_s"]},
        "metrics": {"pure_brain_amplitude_ratio": amplitude_x / amplitude_b if amplitude_b > 1e-15 else None,
                    "amplitude_definition": "temporal RMS maximum bipolar clean-brain amplitude ratio, not cortical area coverage",
                    "baseline_clean_bipolar_rms_uv": amplitude_b * 1e6,
                    "candidate_clean_bipolar_rms_uv": amplitude_x * 1e6},
        "conditions": conditions, "strength_curve": curve, "waveforms": waveforms,
    }


def _cross_region_result(inputs: dict, request: dict, progress: Callable[..., None], selection=None) -> dict:
    """Additive branch: the legacy single/cluster simulation paths stay intact."""
    n = int(inputs["dictionary_count"])
    b, x = np.asarray(inputs["baseline_h"]), np.asarray(inputs["candidate_h"])
    xyz, _ = _generation_geometry(inputs)
    if b.shape != (64, n + GENERATION_COUNT) or x.shape != b.shape or not np.isfinite(b).all() or not np.isfinite(x).all():
        raise ValueError("Both forward matrices must share the complete prior and generation-source columns")
    ids, weights, source = selection if selection is not None else select_cross_region_sources(xyz, request["brain_regions"], n)
    progress(stage="decoder", progress=.20, message="保持全脑先验与共同噪声；所选测试源不参与重建器拟合")
    decoders = legacy.fit_decoders(b[:, :n], x[:, :n], inputs["area_weights"])
    latents = legacy.generate_latents(request["seed"], request["waveform"], weights)
    maps, calibration = legacy.artifact_maps(inputs["baseline_xyz_mm"], inputs["candidate_xyz_mm"], decoders["signal_std_v"])
    progress(stage="propagation", progress=.40, message="将所选固定法向源共同传播到两套64点布局")
    parts = {}
    for side, h in (("baseline", b), ("candidate", x)):
        p = {"brain": legacy.average_reference(h[:, n + ids] @ latents["source_am"]),
             "ecg": maps["ecg"][side][:, None] * latents["ecg"],
             "eog": maps["eog"][side][:, None] * latents["eog"],
             "noise": legacy.average_reference(latents["noise_" + side] * decoders["noise_std_v"])}
        p.update({"reconstructed_" + kind: decoders[side] @ p[kind] for kind in legacy.COMPONENTS})
        parts[side] = p
    target, scale = parts["baseline"]["brain"], request["artifact_scale"]
    progress(stage="evaluation", progress=.60, message="以完整20秒200Hz数据评价四条件和16个曲线点")
    conditions = [legacy.evaluate_condition(parts, target, kind, 0. if kind == "clean" else scale)
                  for kind in legacy.CONDITIONS]
    curve = [legacy.evaluate_condition(parts, target, "clean", 0.)]
    curve.extend(legacy.evaluate_condition(parts, target, kind, strength)
                 for kind in ("ecg", "eog", "mixed") for strength in legacy.STRENGTHS)
    amplitude_b = float(np.sqrt(np.mean(np.ptp(target, axis=0) ** 2)))
    amplitude_x = float(np.sqrt(np.mean(np.ptp(parts["candidate"]["brain"], axis=0) ** 2)))
    progress(stage="preview", progress=.80, message="生成抗混叠显示预览；分数不使用降采样数据")
    waveforms = {
        "time_s": (np.arange(legacy.PREVIEW_DURATION * legacy.PREVIEW_RATE) / legacy.PREVIEW_RATE).tolist(),
        "source_nam": legacy.preview(latents["source_am"], 1e9),
        "ecg_latent": legacy.preview(latents["ecg"]), "eog_latent": legacy.preview(latents["eog"]),
    }
    for side in ("baseline", "candidate"):
        waveforms[side] = {kind + "_uv": legacy.preview(values, 1e6 * (scale if kind in (
            "ecg", "eog", "reconstructed_ecg", "reconstructed_eog") else 1.)) for kind, values in parts[side].items()}
    source.update(waveform=request["waveform"], source_moment_norm_rms_nam=legacy.SOURCE_MOMENT_AM * 1e9)
    return {
        "status": "completed", "request": request, "source": source,
        "protocol": {
            "sample_rate_hz": legacy.SAMPLE_RATE, "duration_s": legacy.DURATION,
            "preview_rate_hz": legacy.PREVIEW_RATE, "preview_duration_s": legacy.PREVIEW_DURATION,
            "preview_filter": "v1 resample_poly 200-to-50 Hz anti-alias filter; first eight seconds only; never used for metrics",
            "physical_electrode_count": 64, "independent_reference_dimensions": 63,
            "reference": "separate common-average reference for each layout; reconstruction target is the same standard64 clean brain field",
            "reconstruction_target": "same clean average-referenced standard64 brain field, excluding ECG/EOG and sensor noise",
            "source_prior": "unchanged full-brain dictionary with independent moment^2 times normalized cortical-area covariance; not conditioned on selected regions",
            "decoder": "v1 frozen clean-prior LMMSE with common physical electrode-noise variance; no selected-region or artifact training",
            "artifact_model": "unchanged hypothetical fixed-coordinate ECG/EOG fields, not measured or physiological cardiac/ocular forward models",
            "artifact_calibration": calibration,
            "brain_attenuation": "included in the FEM columns; no additional distance decay",
            "noise": "same physical sigma for both layouts; independent layout draws reused across all artifact conditions and strengths",
            "nominal_prior_snr_db": legacy.NOMINAL_PRIOR_SNR_DB,
            "physical_electrode_noise_std_uv": decoders["noise_std_v"] * 1e6,
            "baseline_prior_contrast_signal_std_uv": decoders["signal_std_v"] * 1e6,
            "relative_denominator_epsilon": legacy.RELATIVE_DENOMINATOR_EPSILON,
            "ar_scope": "only the selected cross-region source mixture and artifact condition's field-retention ratio; not all-brain coverage, localization, or classification accuracy",
            "curve_uses_same_brain_and_noise": True, "display_artifacts_already_scaled": True,
            "same_model_limitation": "shared Ernie anatomy and solver; off-dictionary does not mean independent-head validation",
            "identity_noise": "layout noise realizations remain independent; exact identity tests use common observations",
            "cross_region_source_count": len(ids), "cross_region_power_weights": "equal 1/K; fixed total source-moment mean-square energy",
            "cross_region_waveforms": "existing partly shared stochastic rhythm/burst model; source waveforms are not assumed independent",
        },
        "events": {"ecg_beat_times_s": latents["ecg_beat_times_s"], "blink_times_s": latents["blink_times_s"]},
        "metrics": {"pure_brain_amplitude_ratio": amplitude_x / amplitude_b if amplitude_b > 1e-15 else None,
                    "amplitude_definition": "temporal RMS maximum bipolar clean-brain amplitude ratio, not cortical area coverage",
                    "baseline_clean_bipolar_rms_uv": amplitude_b * 1e6,
                    "candidate_clean_bipolar_rms_uv": amplitude_x * 1e6},
        "conditions": conditions, "strength_curve": curve, "waveforms": waveforms,
    }


def simulate(inputs: dict, raw_request: object, progress: Callable[..., None] = lambda **kwargs: None) -> dict:
    request = validate_request(raw_request)
    _, normals = _generation_geometry(inputs)
    if request.get("region_definition"):
        result = _cross_region_result(inputs, request, progress, source_roi.select_sources(inputs, request))
        result["protocol"].update(
            region_definition=source_roi.DEFINITION_ID,
            atlas_sha256=inputs["source_atlas"]["sha256"],
            source_grouping_rule=inputs["source_atlas"]["definition"]["rule"],
            source_power_weights=result["source"]["source_weight_definition"],
            ar_scope="selected source mixture and artifact condition's field-retention ratio",
        )
        if request["mode"] != "cross_region":
            for key in ("cross_region_source_count", "cross_region_power_weights", "cross_region_waveforms"):
                result["protocol"].pop(key, None)
    elif request["mode"] == "multi_source":
        legacy_request = {key: value for key, value in request.items() if key != "mode"}
        result = legacy.simulate(inputs, legacy_request, progress)
        result["request"] = request
        result["source"]["mode"] = "multi_source"
    elif request["mode"] == "cross_region":
        result = _cross_region_result(inputs, request, progress)
    else:
        result = _single_source_result(inputs, request, progress)
    ids = np.asarray(result["source"]["generation_source_indices"], dtype=int)
    result["schema_version"] = SCHEMA_VERSION
    result["source"]["normals_mri"] = normals[ids].tolist()
    result["source"]["orientation_mode"] = "fixed_cortical_normal"
    result["source"]["source_orientation"] = "original immutable unit cortical normals used to compute these FEM columns"
    result["protocol"].update(
        experiment_mode=request["mode"], orientation_mode="fixed_cortical_normal",
        free_orientation_supported=False, legacy_numerical_engine=legacy.ALGORITHM_VERSION,
        source_geometry=("original frozen off-dictionary positions and normals; ROI membership from native parent-face DK40 labels" if request.get("region_definition") else "legacy coordinate-proxy source selection; original frozen positions and normals"),
    )
    return result


def run_experiment(root: Path, payload: object, progress: Callable[..., None] = lambda **kwargs: None) -> dict:
    progress(stage="loading", progress=.05, message="校验冻结源法向、布局身份及前向数据来源")
    request, record, inputs, provenance = load_inputs(root, payload, progress)
    result = simulate(inputs, request, progress)
    result["layout"] = {key: record["layout"][key] for key in ("xyzMm", "referenceXyzMm", "regionIndices")}
    result["provenance"] = provenance
    return result
