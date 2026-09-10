"""Frozen-layout source/reception pressure test; not a validated ECG/EOG model.

This workflow is independently fingerprinted. The radius-optimization cache
hashes the numerical core, not this workflows subpackage.
There is no FEM calculation, layout optimization, or nearest-electrode remapping.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Callable

import numpy as np
import scipy
from scipy.signal import butter, resample_poly, sosfiltfilt

SCHEMA_VERSION = "source-reception/1"
ALGORITHM_VERSION = "source-reception-ernie-coordinate-stress-v1"
SAMPLE_RATE = 200
DURATION = 20
PREVIEW_RATE = 50
PREVIEW_DURATION = 8
SOURCE_MOMENT_AM = 1e-8
NOMINAL_PRIOR_SNR_DB = 20
RELATIVE_DENOMINATOR_EPSILON = 1e-8
STRENGTHS = (0., .5, 1., 2., 4.)
REGION_ANCHORS_MM = {
    "frontal": (0., 75., 40.),
    "central": (0., 0., 70.),
    "parietal": (0., -32., 64.),
    "occipital": (0., -65., 20.),
    "temporal_left": (-52., 12., 9.),
    "temporal_right": (52., 12., 9.),
}
CONDITIONS = ("clean", "ecg", "eog", "mixed")
COMPONENTS = ("brain", "ecg", "eog", "noise")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_request(value: object) -> dict:
    fields = {"record_id", "brain_region", "waveform", "artifact_scale", "seed"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Request must contain exactly record_id, brain_region, waveform, artifact_scale, seed")
    if not isinstance(value["record_id"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["record_id"]):
        raise ValueError("record_id must be a lowercase 64-character SHA256 identifier")
    if not isinstance(value["brain_region"], str) or value["brain_region"] not in REGION_ANCHORS_MM:
        raise ValueError("Unsupported coordinate-proxy brain_region")
    if value["waveform"] not in ("burst", "rhythm"):
        raise ValueError("waveform must be burst or rhythm")
    scale = value["artifact_scale"]
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or scale not in STRENGTHS:
        raise ValueError("artifact_scale must be 0, 0.5, 1, 2, or 4")
    seed = value["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 9999:
        raise ValueError("seed must be an integer between 0 and 9999")
    return dict(value)


def average_reference(x: np.ndarray) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 2 or not np.all(np.isfinite(a)):
        raise ValueError("Signals must be finite channel-by-time/column arrays")
    return a - a.mean(axis=0, keepdims=True)


def helmert(n: int = 64) -> np.ndarray:
    w = np.zeros((n - 1, n))
    for i in range(1, n):
        w[i - 1, :i] = 1 / np.sqrt(i * (i + 1))
        w[i - 1, i] = -i / np.sqrt(i * (i + 1))
    return w


def _finite_matrix(value: object, rows: int, name: str) -> np.ndarray:
    a = np.asarray(value, dtype=np.float64)
    if a.shape != (rows, 3) or not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must contain exactly {rows} finite 3D millimetre coordinates")
    return a


def exact_layout_rows(xyz: np.ndarray, bank_xyz: np.ndarray) -> np.ndarray:
    """Exact float-coordinate equality only. No nearest-neighbour substitution.

    JSON emitted from the saved float64 coordinates round-trips those values.
    A newly rounded, moved or invented point requires a new FEM bank; it cannot
    be silently approximated by the existing bank.
    """
    xyz = _finite_matrix(xyz, 64, "layout.xyzMm")
    bank = np.asarray(bank_xyz, dtype=np.float64)
    if bank.ndim != 2 or bank.shape[1] != 3 or not np.all(np.isfinite(bank)):
        raise ValueError("Invalid bank coordinates")
    lookup = {tuple(point): i for i, point in enumerate(bank)}
    if len(lookup) != len(bank):
        raise ValueError("Forward bank contains duplicate electrode coordinates")
    if len({tuple(point) for point in xyz}) != 64:
        raise ValueError("The saved layout must contain 64 distinct physical points")
    try:
        return np.asarray([lookup[tuple(point)] for point in xyz], dtype=np.int64)
    except KeyError as error:
        raise ValueError("Saved electrode coordinates do not exactly match this FEM bank; nearest-neighbour replacement is forbidden") from error


def _contained(root: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise ValueError("Bank pointer path must be a string")
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Bank pointer must resolve to an existing file inside the repository")
    return path


def load_inputs(root: Path, payload: object) -> tuple[dict, dict, dict, dict]:
    root = Path(root).resolve()
    if not isinstance(payload, dict) or set(payload) != {"request", "record"}:
        raise ValueError("Input must contain exactly request and resolved record")
    request = validate_request(payload["request"])
    record = payload["record"]
    if not isinstance(record, dict) or record.get("id") != request["record_id"]:
        raise ValueError("Resolved record ID differs from requested record_id")
    if record.get("status", "completed") != "completed":
        raise ValueError("Only completed saved layouts can enter the source experiment")
    layout = record.get("layout")
    if not isinstance(layout, dict):
        raise ValueError("This record does not contain a complete saved layout")
    xyz = _finite_matrix(layout.get("xyzMm"), 64, "layout.xyzMm")
    ref = _finite_matrix(layout.get("referenceXyzMm"), 64, "layout.referenceXyzMm")
    pointer_path = root / "results/v2/current_multiregion_bank.json"
    pointer = json.loads(pointer_path.read_text())
    bank_path = _contained(root, pointer["path"])
    report_path = _contained(root, pointer["report"])
    report = json.loads(report_path.read_text())
    digest = sha256_file(bank_path)
    if digest != pointer.get("sha256") or digest != report.get("array_sha256"):
        raise ValueError("FEM bank SHA256 does not match its pointer and report")
    with np.load(bank_path, allow_pickle=False) as bank:
        reference_xyz = bank["reference_xyz_mm"]
        if not np.array_equal(ref, reference_xyz):
            raise ValueError("Saved standard-64 coordinates differ from the bank's exact reference coordinates")
        n = int(bank["dictionary_source_count"])
        reference_h = bank["reference_leadfield_v_per_am"]
        if np.array_equal(xyz, reference_xyz):
            indices = None
            candidate_h = reference_h.copy()
        else:
            indices = exact_layout_rows(xyz, bank["candidate_xyz_mm"])
            candidate_h = bank["candidate_leadfield_v_per_am"][indices]
        inputs = {
            "baseline_h": reference_h, "candidate_h": candidate_h,
            "baseline_xyz_mm": reference_xyz, "candidate_xyz_mm": xyz,
            "dictionary_count": n, "area_weights": bank["source_area_weights"],
            "generation_xyz_mm": bank["generation_xyz_mm"],
            "generation_area_weights": bank["generation_area_weights"],
        }
    if n != 4096 or reference_h.shape != (64, n + len(inputs["generation_xyz_mm"])):
        raise ValueError("This protocol requires the frozen 4096-source dictionary and its generation bank")
    provenance = {
        "algorithm_version": ALGORITHM_VERSION, "bank_path": str(bank_path.relative_to(root)),
        "bank_sha256": digest, "pointer_sha256": sha256_file(pointer_path),
        "bank_report_sha256": sha256_file(report_path), "record_id": request["record_id"],
        "record_dataset_id": record.get("dataset_id"), "record_label": record.get("label"),
        "resolved_record_sha256": hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
        "candidate_bank_indices": None if indices is None else indices.tolist(),
        "code_sha256": {name: sha256_file(root / name) for name in ("scripts/source_reception.py", "scripts/run_source_reception.py", "src/compact_eeg/workflows/__init__.py", "src/compact_eeg/workflows/source_reception.py")},
        "head_model": "Ernie single-template FEM", "fem_recomputed": False,
        "layout_optimized": False, "independent_head_validation": False,
        "anatomical_atlas_used": False, "physiological_artifact_forward_model": False,
        "classification_accuracy_computed": False, "source_localization_computed": False,
        "source_generation_bank": "256 off-dictionary fixed-normal cortical source locations",
        "python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__,
        "thread_limit": 2,
        "formal_population_ar": False,
    }
    return request, record, inputs, provenance


def fit_decoders(baseline_h: np.ndarray, candidate_h: np.ndarray, area_weights: np.ndarray) -> dict:
    """Train ONLY on the all-brain dictionary, independent-area prior and noise.

    There is intentionally no argument for test sources, brain region, time
    series, test covariance, ECG or EOG. Both decoders target the same clean,
    average-referenced standard-64 field. The full-rank 63D Helmert system avoids
    treating 64 average-referenced channels as independent observations.
    """
    b, x = np.asarray(baseline_h, float), np.asarray(candidate_h, float)
    w = np.asarray(area_weights, float)
    if b.ndim != 2 or b.shape[0] != 64 or x.shape != b.shape or w.shape != (b.shape[1],):
        raise ValueError("Decoder dictionary must be matching 64-channel matrices and one area weight per source")
    if not all(np.all(np.isfinite(a)) for a in (b, x, w)) or np.any(w < 0) or w.sum() <= 0:
        raise ValueError("Invalid decoder dictionaries or nonnegative area weights")
    w = w / w.sum()
    contrast = helmert()
    hb, hx = contrast @ b, contrast @ x
    signal_std = float(SOURCE_MOMENT_AM * np.sqrt(np.sum(hb ** 2 * w) / 63))
    if not np.isfinite(signal_std) or signal_std <= 0:
        raise ValueError("Baseline prior must have nonzero reference-free signal power")
    hb = hb * (SOURCE_MOMENT_AM / signal_std)
    hx = hx * (SOURCE_MOMENT_AM / signal_std)
    ratio = 10 ** (-NOMINAL_PRIOR_SNR_DB / 10)
    cbb = (hb * w) @ hb.T
    cbx = (hb * w) @ hx.T
    cxx = (hx * w) @ hx.T
    db = np.linalg.solve(cbb + ratio * np.eye(63), cbb.T).T
    dx = np.linalg.solve(cxx + ratio * np.eye(63), cbx.T).T
    return {"baseline": contrast.T @ db @ contrast, "candidate": contrast.T @ dx @ contrast,
            "signal_std_v": signal_std, "noise_std_v": signal_std * np.sqrt(ratio)}


def select_patch(xyz: np.ndarray, region: str, count: int = 6) -> tuple[np.ndarray, dict]:
    if region not in REGION_ANCHORS_MM:
        raise ValueError("Unknown coordinate source region")
    xyz = np.asarray(xyz, float)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) < count or not np.all(np.isfinite(xyz)):
        raise ValueError("Invalid off-dictionary source geometry")
    anchor = np.asarray(REGION_ANCHORS_MM[region])
    ids = np.argsort(np.sum((xyz - anchor) ** 2, axis=1), kind="stable")[:count]
    selected = xyz[ids]
    return ids, {
        "region": region, "selection_method": "six nearest generation-source positions to a fixed Ernie coordinate anchor; not an anatomical atlas or connected cortical ROI",
        "coordinate_axes": "X right, Y anterior, Z superior; Ernie model coordinates in mm",
        "anchor_xyz_mm": anchor.tolist(), "xyz_mm": selected.tolist(), "patch_count": count,
        "generation_source_indices": ids.tolist(),
        "maximum_anchor_distance_mm": float(np.linalg.norm(selected - anchor, axis=1).max()),
        "maximum_pair_distance_mm": float(np.linalg.norm(selected[:, None] - selected[None, :], axis=2).max()),
        "source_orientation": "the fixed cortical normals already represented by the FEM bank columns",
    }


def _unit_rms(x: np.ndarray) -> np.ndarray:
    x = x - x.mean(axis=-1, keepdims=True)
    rms = np.sqrt(np.mean(x * x, axis=-1, keepdims=True))
    if np.any(rms <= np.finfo(float).tiny):
        raise ValueError("Cannot normalize a zero-power latent waveform")
    return x / rms


def generate_latents(seed: int, waveform: str, patch_weights: np.ndarray) -> dict:
    if waveform not in ("burst", "rhythm"):
        raise ValueError("Unknown waveform")
    weights = np.asarray(patch_weights, float)
    if weights.ndim != 1 or not len(weights) or np.any(weights < 0) or not np.isfinite(weights).all() or weights.sum() <= 0:
        raise ValueError("Invalid generation patch weights")
    streams = np.random.SeedSequence(seed).spawn(4)
    rng, artifact_rng = np.random.default_rng(streams[0]), np.random.default_rng(streams[1])
    t = np.arange(SAMPLE_RATE * DURATION) / SAMPLE_RATE
    sos = butter(3, (6, 18), btype="bandpass", fs=SAMPLE_RATE, output="sos")
    narrow = sosfiltfilt(sos, rng.normal(size=(len(weights) + 1, len(t))), axis=-1)
    phase = rng.uniform(-np.pi, np.pi, size=(len(weights), 1))
    source = .65 * _unit_rms(narrow[:1]) + .50 * _unit_rms(narrow[1:])
    source += .3 * np.sin(2 * np.pi * (10 + rng.uniform(-1, 1, size=(len(weights), 1))) * t + phase)
    if waveform == "burst":
        envelope = .12 + sum(np.exp(-.5 * ((t - center) / .65) ** 2) for center in (2.5, 7., 12., 17.))
        source *= envelope
    source = _unit_rms(source) * SOURCE_MOMENT_AM * np.sqrt(weights / weights.sum())[:, None]
    beats, cursor = [], .55
    while cursor < DURATION + .6:
        beats.append(cursor)
        cursor += float(np.clip(60 / 72 + artifact_rng.normal(0, .025), .72, .95))
    ecg = np.zeros_like(t)
    # Explicitly synthetic P-Q-R-S-T template, not a measured ECG trace.
    for beat in beats:
        for offset, width, height in ((-.19, .035, .12), (-.035, .009, -.15), (0, .012, 1.), (.035, .012, -.25), (.24, .070, .30)):
            ecg += height * np.exp(-.5 * ((t - beat - offset) / width) ** 2)
    blink_times = np.array([1.8, 5.7, 9.6, 13.4, 17.3]) + artifact_rng.uniform(-.12, .12, 5)
    eog = sum(np.exp(-.5 * ((t - event) / .115) ** 2) - .16 * np.exp(-.5 * ((t - event - .30) / .19) ** 2) for event in blink_times)
    return {"time_s": t, "source_am": source, "ecg": _unit_rms(ecg), "eog": _unit_rms(eog),
            "ecg_beat_times_s": beats, "blink_times_s": blink_times.tolist(),
            "noise_baseline": np.random.default_rng(streams[2]).normal(size=(64, len(t))),
            "noise_candidate": np.random.default_rng(streams[3]).normal(size=(64, len(t)))}


def raw_artifact_map(xyz: np.ndarray, kind: str) -> np.ndarray:
    """Fixed-coordinate analytic fields, NOT cardiac or ocular FEM lead fields.

    These functions never use a layout-specific extent, bounding box, mean or
    variance. Only the standard64 map is subsequently calibrated once.
    """
    xyz = np.asarray(xyz, float)
    x, y, z = (xyz / 100).T
    if kind == "ecg":
        return .65 * z - .30 * y + .25 * x + .25 * x * z + .20 * y ** 2
    if kind == "eog":
        widths = np.array([48., 45., 55.])
        left = np.exp(-.5 * np.sum(((xyz - [-30., 100., 22.]) / widths) ** 2, axis=1))
        right = np.exp(-.5 * np.sum(((xyz - [30., 100., 22.]) / widths) ** 2, axis=1))
        return left + .9 * right
    raise ValueError("Unknown artifact kind")


def artifact_maps(baseline_xyz: np.ndarray, candidate_xyz: np.ndarray, signal_std_v: float) -> tuple[dict, dict]:
    maps, calibration = {}, {}
    for kind, factor in (("ecg", 1.), ("eog", 3.)):
        b = raw_artifact_map(baseline_xyz, kind)
        x = raw_artifact_map(candidate_xyz, kind)
        denominator = float(np.sqrt(np.mean((b - b.mean()) ** 2)))
        if denominator <= 1e-12:
            raise ValueError("Artifact calibration cannot use a constant standard-64 spatial map")
        coefficient = signal_std_v * factor / denominator
        maps[kind] = {"baseline": average_reference(b[:, None])[:, 0] * coefficient,
                      "candidate": average_reference(x[:, None])[:, 0] * coefficient}
        calibration[kind] = {"raw_baseline_spatial_rms": denominator, "shared_voltage_coefficient_v": coefficient,
                             "unit_scale_baseline_rms_to_prior_contrast_std": factor}
    return maps, calibration


def metrics_for(target: np.ndarray, reconstruction: np.ndarray, brain: np.ndarray, artifact: np.ndarray, noise: np.ndarray | None = None) -> dict:
    target_power = float(np.mean(np.asarray(target) ** 2))
    if target_power <= 1e-30 or not np.isfinite(target_power):
        nmse = explained = None
    else:
        nmse = float(np.mean((reconstruction - target) ** 2) / target_power)
        explained = 1. - nmse
    brain_power, artifact_power = float(np.mean(brain ** 2)), float(np.mean(artifact ** 2))
    noise_power = None if noise is None else float(np.mean(noise ** 2))
    ratio = 10 * float(np.log10(brain_power / artifact_power)) if brain_power > 0 and artifact_power > 0 else None
    return {"nmse": nmse, "explained_energy": explained, "brain_artifact_ratio_db": ratio,
            "brain_noise_ratio_db": 10 * float(np.log10(brain_power / noise_power)) if brain_power > 0 and noise_power is not None and noise_power > 0 else None,
            "brain_power_uv2": brain_power * 1e12, "artifact_power_uv2": artifact_power * 1e12,
            "noise_power_uv2": None if noise_power is None else noise_power * 1e12}


def relative_field(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None or not np.isfinite(candidate) or not np.isfinite(baseline) or baseline <= RELATIVE_DENOMINATOR_EPSILON:
        return None
    return float(candidate / baseline)


def evaluate_condition(parts: dict, target: np.ndarray, condition: str, scale: float) -> dict:
    if condition not in CONDITIONS:
        raise ValueError("Unknown condition")
    if not np.isfinite(scale) or scale < 0:
        raise ValueError("Artifact scale must be nonnegative and finite")
    active = () if condition == "clean" else ("ecg", "eog") if condition == "mixed" else (condition,)
    result = {"condition": condition, "artifact_scale": float(scale)}
    for side in ("baseline", "candidate"):
        p = parts[side]
        artifact = sum((p[k] * scale for k in active), np.zeros_like(target))
        reconstructed = p["reconstructed_brain"] + p["reconstructed_noise"]
        reconstructed = reconstructed + sum((p["reconstructed_" + k] * scale for k in active), np.zeros_like(target))
        result[side] = metrics_for(target, reconstructed, p["brain"], artifact, p["noise"])
    result["field_retention"] = relative_field(result["candidate"]["explained_energy"], result["baseline"]["explained_energy"])
    return result


def preview(array: np.ndarray, multiplier: float = 1.) -> list:
    # Filter all 20 seconds first, then crop: prevents aliasing and artificial
    # endpoint discontinuities at the end of the eight-second display window.
    reduced = resample_poly(np.asarray(array) * multiplier, PREVIEW_RATE, SAMPLE_RATE, axis=-1)
    return np.round(reduced[..., :PREVIEW_DURATION * PREVIEW_RATE], 6).tolist()


def simulate(inputs: dict, request: dict, progress: Callable[..., None] = lambda **kwargs: None) -> dict:
    n = inputs["dictionary_count"]
    b, x = np.asarray(inputs["baseline_h"]), np.asarray(inputs["candidate_h"])
    if b.shape != x.shape or b.shape[0] != 64 or not np.isfinite(b).all() or not np.isfinite(x).all():
        raise ValueError("Candidate and baseline fields must describe exactly the same finite source columns")
    progress(stage="decoder", progress=.20, message="冻结全脑先验与共同噪声，拟合两套场重建器")
    decoders = fit_decoders(b[:, :n], x[:, :n], inputs["area_weights"])
    ids, source_info = select_patch(inputs["generation_xyz_mm"], request["brain_region"])
    source_info["bank_source_indices"] = (n + ids).tolist()
    latents = generate_latents(request["seed"], request["waveform"], inputs["generation_area_weights"][ids])
    maps, calibration = artifact_maps(inputs["baseline_xyz_mm"], inputs["candidate_xyz_mm"], decoders["signal_std_v"])
    progress(stage="propagation", progress=.40, message="同一皮层源、心搏与眨眼分别传递到两套64点布局")
    parts = {}
    for side, h in (("baseline", b), ("candidate", x)):
        p = {"brain": average_reference(h[:, n + ids] @ latents["source_am"]),
             "ecg": maps["ecg"][side][:, None] * latents["ecg"],
             "eog": maps["eog"][side][:, None] * latents["eog"],
             "noise": average_reference(latents["noise_" + side] * decoders["noise_std_v"])}
        p.update({"reconstructed_" + kind: decoders[side] @ p[kind] for kind in COMPONENTS})
        parts[side] = p
    target = parts["baseline"]["brain"]
    current_scale = request["artifact_scale"]
    progress(stage="evaluation", progress=.60, message="按200Hz完整20秒波形计算四条件及干扰强度曲线")
    conditions = [evaluate_condition(parts, target, kind, 0. if kind == "clean" else current_scale) for kind in CONDITIONS]
    curve = [evaluate_condition(parts, target, "clean", 0)]
    curve.extend(evaluate_condition(parts, target, kind, scale) for kind in ("ecg", "eog", "mixed") for scale in STRENGTHS)
    amplitude_b = float(np.sqrt(np.mean(np.ptp(target, axis=0) ** 2)))
    amplitude_x = float(np.sqrt(np.mean(np.ptp(parts["candidate"]["brain"], axis=0) ** 2)))
    progress(stage="preview", progress=.80, message="生成50Hz抗混叠显示预览；评价指标保持全采样率")
    waveforms = {"time_s": (np.arange(PREVIEW_DURATION * PREVIEW_RATE) / PREVIEW_RATE).tolist(),
                 "source_nam": preview(latents["source_am"], 1e9),
                 "ecg_latent": preview(latents["ecg"]), "eog_latent": preview(latents["eog"])}
    for side in ("baseline", "candidate"):
        waveforms[side] = {kind + "_uv": preview(values, 1e6 * (current_scale if kind in ("ecg", "eog", "reconstructed_ecg", "reconstructed_eog") else 1.)) for kind, values in parts[side].items()}
    source_info.update(waveform=request["waveform"], source_moment_norm_rms_nam=SOURCE_MOMENT_AM * 1e9,
                       patch_area_weights=(inputs["generation_area_weights"][ids] / inputs["generation_area_weights"][ids].sum()).tolist())
    return {
        "schema_version": SCHEMA_VERSION, "status": "completed", "request": request,
        "protocol": {"sample_rate_hz": SAMPLE_RATE, "duration_s": DURATION,
            "preview_rate_hz": PREVIEW_RATE, "preview_duration_s": PREVIEW_DURATION,
            "preview_filter": "scipy.signal.resample_poly 200-to-50 Hz anti-alias FIR, first 8 seconds, microvolt values rounded to 6 decimals; never used for metrics",
            "physical_electrode_count": 64, "independent_reference_dimensions": 63,
            "reference": "separate common-average reference for each 64-electrode layout; receiver index is not a common physical channel",
            "reconstruction_target": "same clean average-referenced standard64 brain field, excluding ECG, EOG and sensor noise",
            "source_prior": "4096 all-brain fixed-normal dictionary sources, independent covariance moment^2 times normalized cortical-area weights",
            "decoder": "frozen clean-prior LMMSE with common physical electrode-noise variance; no test-ROI, test-waveform or artifact training",
            "artifact_model": "hypothetical fixed-coordinate smooth ECG and EOG projections; not cardiac, torso or ocular FEM and not empirical artifact validation",
            "brain_attenuation": "already contained in the FEM lead fields; no additional distance attenuation factor",
            "noise": "independent Gaussian physical electrode noise; equal sigma across both layouts and all conditions; common random draws reused across artifact strengths",
            "nominal_prior_snr_db": NOMINAL_PRIOR_SNR_DB,
            "physical_electrode_noise_std_uv": decoders["noise_std_v"] * 1e6,
            "baseline_prior_contrast_signal_std_uv": decoders["signal_std_v"] * 1e6,
            "artifact_calibration": calibration,
            "relative_denominator_epsilon": RELATIVE_DENOMINATOR_EPSILON,
            "ar_scope": "field_retention only under this source and artifact condition; not the prior three-metric G or classification/localization accuracy",
            "curve_uses_same_brain_and_noise": True, "display_artifacts_already_scaled": True,
            "same_model_limitation": "Both layouts use the same Ernie head and conductivity model; held-out source coordinates do not constitute independent-head validation",
            "identity_noise": "Same-coordinate layouts use independent noise realizations in the live experiment; exact identity tests separately use noiseless/common-noise observations",
        },
        "source": source_info,
        "events": {"ecg_beat_times_s": latents["ecg_beat_times_s"], "blink_times_s": latents["blink_times_s"]},
        "metrics": {"pure_brain_amplitude_ratio": amplitude_x / amplitude_b if amplitude_b > 1e-15 else None,
                    "amplitude_definition": "ratio of temporal RMS maximum bipolar amplitude of the clean multiactive brain field; not percent cortex coverage",
                    "baseline_clean_bipolar_rms_uv": amplitude_b * 1e6, "candidate_clean_bipolar_rms_uv": amplitude_x * 1e6},
        "conditions": conditions, "strength_curve": curve, "waveforms": waveforms,
    }


def run_experiment(root: Path, payload: object, progress: Callable[..., None] = lambda **kwargs: None) -> dict:
    progress(stage="loading", progress=.05, message="校验记录与已有FEM矩阵；不重新计算头模型")
    request, record, inputs, provenance = load_inputs(root, payload)
    result = simulate(inputs, request, progress)
    result["layout"] = {key: record["layout"][key] for key in ("xyzMm", "referenceXyzMm", "regionIndices") if key in record["layout"]}
    result["provenance"] = provenance
    return result
