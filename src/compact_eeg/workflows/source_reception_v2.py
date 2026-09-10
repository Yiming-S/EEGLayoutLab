"""Additive fixed-normal source experiments; the v1 engine remains unchanged.

Version 2 adds explicit single-source selection and audited native-coordinate
forward providers. It does not add free dipole orientation or a new estimator.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Callable

import numpy as np
import scipy

from . import source_reception as legacy

SCHEMA_VERSION = "source-reception/2"
ALGORITHM_VERSION = "source-reception-fixed-normal-v2"
CATALOG_SCHEMA_VERSION = "source-catalog/1"
GENERATION_COUNT = 256
COORDINATE_SYSTEM = "Ernie MRI coordinates: X right, Y anterior, Z superior; millimetres"
DEPENDENCY_PATHS = (
    "src/compact_eeg/workflows/__init__.py",
    "src/compact_eeg/workflows/paths.py",
    "src/compact_eeg/workflows/source_reception.py",
    "src/compact_eeg/workflows/source_reception_v2.py",
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
    if mode not in ("single_source", "multi_source"):
        raise ValueError("mode must be single_source or multi_source")
    specific = "source_index" if mode == "single_source" else "brain_region"
    fields = {"record_id", "mode", specific, "waveform", "artifact_scale", "seed"}
    if set(value) != fields:
        raise ValueError(f"{mode} requires exactly {', '.join(sorted(fields))}; direction and arbitrary coordinates are not accepted")
    if mode == "single_source":
        index = value["source_index"]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < GENERATION_COUNT:
            raise ValueError("source_index must be an integer from 0 through 255")
    # Reuse v1 bounds for the unchanged physical and stochastic parameters.
    legacy.validate_request({
        "record_id": value["record_id"],
        "brain_region": value.get("brain_region", "frontal"),
        "waveform": value["waveform"], "artifact_scale": value["artifact_scale"],
        "seed": value["seed"],
    })
    return dict(value)


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
    if int(catalog["dictionary_count"]) != 4096:
        raise ValueError("The catalog must share the frozen 4096-source reconstruction prior")
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "coordinate_system": COORDINATE_SYSTEM,
        "coordinate_unit": "mm", "normal_unit": "dimensionless unit vector",
        "orientation_mode": "fixed_cortical_normal",
        "source_count": GENERATION_COUNT, "dictionary_source_count": 4096,
        "sources": [{"id": i, "xyz_mm": xyz[i].tolist(), "normal": normals[i].tolist()}
                    for i in range(GENERATION_COUNT)],
        "provenance": provenance,
        "limitations": [
            "These are the original off-dictionary generation locations, not a continuous draggable source model.",
            "The normal is an immutable physical direction used in the stored FEM column, not an editable arrow.",
            "No anatomical atlas labels or independent-head validation are provided.",
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
    if request["mode"] == "multi_source" and record.get("dataset_id") != "design_evaluation":
        raise ValueError("Existing bank-layout multi-source experiments remain on v1; v2 multi_source is for completed native-coordinate design_evaluation records")
    provider_progress = None if progress is None else lambda fraction, message: progress(
        stage="forward", progress=.05 + .10 * float(np.clip(fraction, 0., 1.)), message=message)
    inputs, provenance = load_reception_forward(root, record, progress=provider_progress, allow_native=True)
    _generation_geometry(inputs)
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


def simulate(inputs: dict, raw_request: object, progress: Callable[..., None] = lambda **kwargs: None) -> dict:
    request = validate_request(raw_request)
    _, normals = _generation_geometry(inputs)
    if request["mode"] == "multi_source":
        legacy_request = {key: value for key, value in request.items() if key != "mode"}
        result = legacy.simulate(inputs, legacy_request, progress)
        result["request"] = request
        result["source"]["mode"] = "multi_source"
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
        source_geometry="original frozen off-dictionary generation positions and cortical normals; not an anatomical atlas",
    )
    return result


def run_experiment(root: Path, payload: object, progress: Callable[..., None] = lambda **kwargs: None) -> dict:
    progress(stage="loading", progress=.05, message="校验冻结源法向、布局身份及前向数据来源")
    request, record, inputs, provenance = load_inputs(root, payload, progress)
    result = simulate(inputs, request, progress)
    result["layout"] = {key: record["layout"][key] for key in ("xyzMm", "referenceXyzMm", "regionIndices")}
    result["provenance"] = provenance
    return result
