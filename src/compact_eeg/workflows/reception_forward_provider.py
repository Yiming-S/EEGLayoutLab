"""Immutable exact-coordinate FEM provider for the additive reception protocol.

Existing bank rows are used only at exactly identical coordinates. Previously
evaluated non-bank coordinates require direct native FEM, never montage or
nearest-neighbour interpolation. Native solves are opt-in, single-threaded and
protected by one process lock; the application's shared worker is the scheduler.
This module never modifies v1 records, banks, objectives, or cache pointers.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

import numpy as np
import scipy
from threadpoolctl import threadpool_info, threadpool_limits

from .paths import PROJECT_ROOT as ROOT
from compact_eeg.artifacts import sha256_file
from compact_eeg.forward_pilot import deterministic_npz_bytes

PROVIDER_VERSION = "reception-exact-forward/2"
PROJECTION_TOLERANCE_MM = 1e-7
CACHE_RELATIVE_ROOT = Path("results/v2/reception_forward")
CATALOG_KEYS = ("source_xyz_mm", "source_normals", "source_area_weights",
                "generation_xyz_mm", "generation_normals", "generation_area_weights")
CODE_PATHS = ("src/compact_eeg/workflows/__init__.py", "src/compact_eeg/workflows/paths.py",
              "src/compact_eeg/workflows/reception_forward_provider.py",
              "src/compact_eeg/workflows/design_evaluation.py", "src/compact_eeg/workflows/head_model.py",
              "scripts/reception_forward_provider.py", "scripts/design_evaluation.py",
              "scripts/inspect_ernie_cortical_forward.py", "src/compact_eeg/cortical_fem.py",
              "src/compact_eeg/surface_admissibility.py", "src/compact_eeg/artifacts.py",
              "src/compact_eeg/forward_pilot.py")
NATIVE_PACKAGES = ("numpy", "scipy", "simnibs", "cortech")
SIMNIBS_SOURCE_FILES = ("simulation/fem.py", "mesh_tools/mesh_io.py", "eeg/forward.py",
                      "utils/mesh_element_properties.py")
NATIVE_LIBRARY_PATTERNS = ("*mumps*", "*scotch*", "*blas*", "*lapack*", "*omp*", "*mkl*", "libpython*")


class ForwardComputationRequired(ValueError):
    """A frozen non-bank layout needs an explicitly scheduled native FEM solve."""


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _json_sha(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _array_identity(value):
    a = np.ascontiguousarray(value)
    if a.dtype.hasobject:
        raise ValueError("Object arrays are forbidden")
    return {"shape": list(a.shape), "dtype": a.dtype.str,
            "sha256": hashlib.sha256(a.tobytes(order="C")).hexdigest()}


def _existing(root, relative):
    if not isinstance(relative, str):
        raise ValueError("Artifact path must be a string")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Artifact must be an existing file inside the repository")
    return path


def _matrix(value, rows, name):
    a = np.asarray(value, dtype=np.float64)
    if a.shape != (rows, 3) or not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must be a finite {rows}x3 array")
    return a


def _load_bundle(root):
    """One shared source-order/normal validator used by the catalog and provider."""
    root = Path(root).resolve()
    pointer_path = _existing(root, "results/v2/current_multiregion_bank.json")
    pointer = json.loads(pointer_path.read_text())
    bank_path, report_path = _existing(root, pointer["path"]), _existing(root, pointer["report"])
    report = json.loads(report_path.read_text())
    bank_sha = sha256_file(bank_path)
    if bank_sha != pointer.get("sha256") or bank_sha != report.get("array_sha256"):
        raise ValueError("Frozen bank SHA256 differs from pointer or report")
    manifest_path = bank_path.parents[2] / "run_manifest.json"
    if not manifest_path.is_relative_to(root) or not manifest_path.is_file():
        raise ValueError("Frozen bank manifest missing")
    manifest = json.loads(manifest_path.read_text())
    source_path = _existing(root, manifest["source_inputs"])
    source_sha = sha256_file(source_path)
    if source_sha != report.get("source_input_sha256") or source_sha != manifest["identity"].get("source_input_sha256"):
        raise ValueError("Source input SHA256 differs from bank manifest/report")
    with np.load(source_path, allow_pickle=False) as s, np.load(bank_path, allow_pickle=False) as h:
        catalog = {k: np.asarray(s[k], dtype=np.float64) for k in CATALOG_KEYS}
        n = int(h["dictionary_source_count"])
        if n != 4096 or catalog["generation_xyz_mm"].shape != (256, 3):
            raise ValueError("Provider requires the frozen 4096 dictionary + 256 generation sources")
        for prefix, count in (("source", 4096), ("generation", 256)):
            xyz = _matrix(catalog[f"{prefix}_xyz_mm"], count, f"{prefix} positions")
            normals = _matrix(catalog[f"{prefix}_normals"], count, f"{prefix} normals")
            weights = catalog[f"{prefix}_area_weights"]
            if weights.shape != (count,) or not np.all(np.isfinite(weights)) or np.any(weights < 0) or weights.sum() <= 0:
                raise ValueError("Invalid source-area weights")
            if not np.allclose(np.linalg.norm(normals, axis=1), 1., rtol=0, atol=1e-7):
                raise ValueError("Frozen source normals are not unit vectors")
            if not np.array_equal(xyz, h[f"{prefix}_xyz_mm"]) or not np.array_equal(weights, h[f"{prefix}_area_weights"]):
                raise ValueError("Source ordering/weights differ between source archive and bank")
        baseline_h = np.asarray(h["reference_leadfield_v_per_am"], dtype=np.float64)
        baseline_xyz = _matrix(h["reference_xyz_mm"], 64, "standard64")
        bank_xyz = np.asarray(h["candidate_xyz_mm"], dtype=np.float64)
        if baseline_h.shape != (64, 4352) or not np.all(np.isfinite(baseline_h)):
            raise ValueError("Invalid frozen standard64 forward field")
        if bank_xyz.ndim != 2 or bank_xyz.shape[1] != 3 or not np.all(np.isfinite(bank_xyz)):
            raise ValueError("Invalid frozen candidate coordinates")
    catalog["dictionary_count"] = n
    source_identity = {k: _array_identity(v) for k, v in catalog.items() if k != "dictionary_count"}
    provenance = {"provider_version": PROVIDER_VERSION, "bank_path": str(bank_path.relative_to(root)),
        "bank_sha256": bank_sha, "pointer_sha256": sha256_file(pointer_path),
        "bank_report_path": str(report_path.relative_to(root)), "bank_report_sha256": sha256_file(report_path),
        "source_manifest_path": str(manifest_path.relative_to(root)), "source_manifest_sha256": sha256_file(manifest_path),
        "source_inputs_path": str(source_path.relative_to(root)), "source_inputs_sha256": source_sha,
        "head_hashes": manifest["identity"]["head_hashes"], "source_array_identities": source_identity,
        "catalog_identity_sha256": _json_sha({"bank": bank_sha, "source_inputs": source_sha, "arrays": source_identity}),
        "dictionary_count": n, "generation_count": 256,
        "source_orientation": "frozen unit cortical normals, same order as the forward columns",
        "head_model": "Ernie single-template FEM", "independent_head_validation": False}
    return {"root": root, "pointer": pointer, "report": report, "catalog": catalog,
            "baseline_h": baseline_h, "baseline_xyz": baseline_xyz, "bank_xyz": bank_xyz,
            "bank_path": bank_path, "provenance": provenance}


def load_frozen_source_catalog(root=ROOT):
    """Return (NumPy catalog, provenance); no native solve, cache write or remapping."""
    bundle = _load_bundle(root)
    return bundle["catalog"], bundle["provenance"]


def _validate_record(root, record, bundle):
    if not isinstance(record, dict) or record.get("status", "completed") != "completed":
        raise ValueError("Only a completed resolved record can be evaluated")
    if not isinstance(record.get("id"), str) or not re.fullmatch("[0-9a-f]{64}", record["id"]):
        raise ValueError("Record ID must be a lowercase SHA256 identifier")
    layout = record.get("layout")
    if not isinstance(layout, dict):
        raise ValueError("Record has no complete layout")
    xyz = _matrix(layout.get("xyzMm"), 64, "record coordinates")
    reference = _matrix(layout.get("referenceXyzMm"), 64, "record reference coordinates")
    if len(np.unique(xyz, axis=0)) != 64:
        raise ValueError("Record requires 64 distinct physical coordinates")
    if not np.array_equal(reference, bundle["baseline_xyz"]):
        raise ValueError("Saved reference coordinates differ from the exact bank reference")
    proof = None
    if record.get("dataset_id") == "design_evaluation":
        link = record.get("provenance", {}).get("design_result")
        if not isinstance(link, dict) or not isinstance(link.get("sha256"), str):
            raise ValueError("Design record requires provenance.design_result path and byte SHA256")
        path = _existing(root, link.get("path"))
        expected_parent = root / "results/v2/design_evaluation_jobs" / record["id"]
        if path != expected_parent / "cache.json" or sha256_file(path) != link["sha256"]:
            raise ValueError("Design result path, cache key or byte SHA256 mismatch")
        wrapper = json.loads(path.read_text())
        result = wrapper.get("result")
        if wrapper.get("key") != record["id"] or not isinstance(result, dict) or result.get("schema") != "design-evaluation/1" or result.get("status") != "completed":
            raise ValueError("Design cache is not a completed matching evaluation")
        actual = _matrix(result.get("evaluated_xyz_mm"), 64, "frozen evaluated coordinates")
        if not np.array_equal(actual, xyz):
            raise ValueError("Record must use frozen evaluated_xyz_mm, not original requested or rounded coordinates")
        design = result.get("request", {}).get("design", {})
        if design.get("coordinate_system") != "ernie_native_mm" or design.get("unit") != "mm":
            raise ValueError("Completed design does not use Ernie native millimetres")
        if not np.array_equal(np.asarray(layout.get("regionIndices")), np.asarray(design.get("region_indices"))):
            raise ValueError("Design region labels differ from the frozen evaluation")
        if result.get("provenance", {}).get("bank_sha256") != bundle["provenance"]["bank_sha256"]:
            raise ValueError("Completed design and current reference bank differ")
        proof = {"path": str(path.relative_to(root)), "sha256": link["sha256"],
                 "forward_mode": result.get("forward_mode"), "frozen_coordinate_identity": _array_identity(actual)}
    return xyz, {"record_id": record["id"], "record_dataset_id": record.get("dataset_id"),
        "resolved_record_sha256": _json_sha(record), "design_result": proof}


def _exact_rows(xyz, bank_xyz):
    lookup = {tuple(point): i for i, point in enumerate(bank_xyz)}
    if len(lookup) != len(bank_xyz):
        raise ValueError("Bank has duplicate coordinates")
    try:
        return np.asarray([lookup[tuple(point)] for point in xyz], dtype=np.int64)
    except KeyError:
        return None


def _inputs(bundle, xyz, candidate_h):
    h = np.asarray(candidate_h, dtype=np.float64)
    if h.shape != (64, 4352) or not np.all(np.isfinite(h)):
        raise ValueError("Candidate forward field must be finite 64x4352")
    catalog = bundle["catalog"]
    return {**catalog, "baseline_h": bundle["baseline_h"], "candidate_h": h,
        "baseline_xyz_mm": bundle["baseline_xyz"], "candidate_xyz_mm": xyz,
        "area_weights": catalog["source_area_weights"]}


def _code_identities(root):
    return {name: sha256_file(_existing(root, name)) for name in CODE_PATHS}


def _native_runtime_locations():
    """Discover actual runtime files without importing SimNIBS or running FEM.

    Kept separate from hashing so tests can provide real temporary package files
    instead of depending on an installed native environment.
    """
    packages = {}
    for name in NATIVE_PACKAGES:
        distribution = importlib.metadata.distribution(name)
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.origin:
            raise ValueError(f"Native runtime package has no inspectable origin: {name}")
        loaded = sys.modules.get(name)
        origin = Path(getattr(loaded, "__file__", None) or spec.origin).resolve()
        package_root = origin.parent
        if package_root != Path(distribution.locate_file(name)).resolve():
            raise ValueError(f"Native module and distribution metadata refer to different package roots: {name}")
        metadata = [Path(distribution.locate_file(p)) for p in distribution.files or ()
                    if p.name in ("METADATA", "RECORD", "WHEEL", "direct_url.json")
                    and ".dist-info" in str(p)]
        if not any(p.name == "METADATA" for p in metadata):
            raise ValueError(f"Native distribution lacks byte-verifiable METADATA: {name}")
        packages[name] = {"version": distribution.version, "root": package_root,
                          "origin": origin, "metadata": metadata}
    return {"prefix": Path(sys.prefix).resolve(), "executable": Path(sys.executable), "packages": packages}


def _native_runtime_identity():
    """Fingerprint installed bytes, not just version strings or frozen manifests."""
    locations = _native_runtime_locations()
    prefix = Path(locations["prefix"]).resolve()
    conda = sorted((prefix / "conda-meta").glob("*.json"))
    if not conda:
        raise ValueError("Native reception requires an auditable conda-meta runtime")
    memo = {}
    def identify(path):
        path = Path(path).absolute()
        resolved = path.resolve()
        if not resolved.is_file():
            raise ValueError(f"Native runtime dependency is missing: {path}")
        if resolved not in memo:
            memo[resolved] = sha256_file(resolved)
        return {"path": str(path), "resolved_path": str(resolved), "sha256": memo[resolved]}
    packages = {}
    for name in NATIVE_PACKAGES:
        package = locations["packages"][name]
        folder = Path(package["root"]).resolve()
        sources = sorted(p for p in folder.rglob("*")
                         if p.is_file() and p.suffix in (".py", ".so", ".dylib", ".pyd"))
        if not sources:
            raise ValueError(f"Native package has no auditable numerical sources: {name}")
        metadata = sorted(Path(p) for p in package["metadata"])
        if not any(p.name == "METADATA" for p in metadata):
            raise ValueError(f"Native package METADATA is missing: {name}")
        packages[name] = {"version": package["version"], "origin": identify(package["origin"]),
                          "metadata": [identify(p) for p in metadata],
                          "numerical_sources": {str(p.relative_to(folder)): identify(p) for p in sources}}
    simnibs_root = Path(locations["packages"]["simnibs"]["root"])
    critical = {name: identify(simnibs_root / name) for name in SIMNIBS_SOURCE_FILES}
    libraries = sorted({p for pattern in NATIVE_LIBRARY_PATTERNS for p in (prefix / "lib").glob(pattern)
                        if p.is_file() and (p.suffix in (".dylib", ".so", ".dll") or ".so." in p.name)})
    if not any("mumps" in p.name for p in libraries):
        raise ValueError("Native runtime has no auditable MUMPS solver library")
    return {"schema": "reception-native-runtime/1", "prefix": str(prefix), "python": sys.version,
        "executable": identify(locations["executable"]), "packages": packages,
        "conda_records": {p.name: identify(p) for p in conda},
        "critical_simnibs_sources": critical,
        "native_libraries": {p.name: identify(p) for p in libraries}, "thread_limit": 1}


def _current_head_identity(root, bundle):
    """Rehash the current physical inputs even when a native cache exists."""
    expected = bundle["provenance"]["head_hashes"]
    names = {"fem_config", "mesh", "scalp_mapping", "scalp_vertices", "scalp_triangles"}
    if set(expected) != names:
        raise ValueError("Frozen head identity must include config, mesh, mapping and both scalp surfaces")
    config_path = _existing(root, "configs/ernie_fem_point_pilot.json")
    if sha256_file(config_path) != expected["fem_config"]:
        raise ValueError("Current head configuration differs from the frozen head")
    config = json.loads(config_path.read_text())
    mesh = _existing(root, config["mesh_path"])
    mapping = _existing(root, config["external_node_mapping_path"])
    vertices = _existing(root, str((mapping.parent / "external_scalp_vertices_m.npy").relative_to(root)))
    triangles = _existing(root, str((mapping.parent / "external_scalp_triangles.npy").relative_to(root)))
    paths = {"fem_config": config_path, "mesh": mesh, "scalp_mapping": mapping,
             "scalp_vertices": vertices, "scalp_triangles": triangles}
    actual = {name: sha256_file(path) for name, path in paths.items()}
    if actual != expected or actual["mesh"] != config.get("mesh_sha256") or actual["scalp_mapping"] != config.get("external_node_mapping_sha256"):
        raise ValueError("Current head files differ from frozen mesh/mapping/surface hashes")
    return {"hashes": actual, "paths": {name: str(path.relative_to(root)) for name, path in paths.items()}}


def _current_admission_identity(root, bundle):
    """Current eligibility changes invalidate native results; no stale mask reuse."""
    pointer_path = _existing(root, "results/v2/current_surface_admissibility.json")
    pointer = json.loads(pointer_path.read_text())
    payload_path = _existing(root, pointer["path"])
    geometry_path = _existing(root, bundle["pointer"]["candidates"])
    geometry_sha = sha256_file(geometry_path)
    if geometry_sha != bundle["report"].get("candidate_sha256") or geometry_sha != pointer.get("geometry_sha256"):
        raise ValueError("Current admission geometry differs from frozen candidate geometry")
    payload_sha = sha256_file(payload_path)
    if payload_sha != pointer.get("sha256"):
        raise ValueError("Current admission payload SHA256 differs from its pointer")
    with np.load(payload_path, allow_pickle=False) as admission, np.load(geometry_path, allow_pickle=False) as geometry:
        mask = admission["eligible_vertex_mask"]
        vertices, faces = geometry["surface_vertices_m"], geometry["surface_triangles"]
        if mask.ndim != 1 or mask.dtype.kind not in "biu" or not np.isin(mask, [0, 1]).all() or len(mask) != len(vertices):
            raise ValueError("Current admission mask has invalid values or vertex indexing")
        if (vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all()
                or faces.ndim != 2 or faces.shape[1] != 3 or faces.dtype.kind not in "iu"
                or not len(faces) or np.any(faces < 0) or np.any(faces >= len(vertices))):
            raise ValueError("Current admission geometry has invalid surface arrays")
    return {"pointer_path": str(pointer_path.relative_to(root)), "pointer_sha256": sha256_file(pointer_path),
            "payload_path": str(payload_path.relative_to(root)), "payload_sha256": payload_sha,
            "schema_version": pointer.get("schema_version"), "geometry_path": str(geometry_path.relative_to(root)),
            "geometry_sha256": geometry_sha, "eligible_mask": _array_identity(mask)}


def _native_identity(root, bundle, xyz):
    return {"provider_version": PROVIDER_VERSION, "candidate_coordinates": _array_identity(xyz),
        "reference_coordinates": _array_identity(bundle["baseline_xyz"]),
        "bank_sha256": bundle["provenance"]["bank_sha256"],
        "source_inputs_sha256": bundle["provenance"]["source_inputs_sha256"],
        "source_manifest_sha256": bundle["provenance"]["source_manifest_sha256"],
        "head_hashes": bundle["provenance"]["head_hashes"],
        "code_sha256": _code_identities(root), "python": sys.version,
        "numpy": np.__version__, "scipy": scipy.__version__, "thread_limit": 1,
        "current_head": _current_head_identity(root, bundle),
        "current_admission": _current_admission_identity(root, bundle),
        "native_runtime": _native_runtime_identity(),
        "reprojection_tolerance_mm": PROJECTION_TOLERANCE_MM}


def _write_once(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def _native_lock(cache_root):
    cache_root.mkdir(parents=True, exist_ok=True)
    with (cache_root / "native-worker.lock").open("a+b") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another native reception solve is active; use the application's shared single-worker queue") from error
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _read_cache(root, entry, identity, bundle, xyz):
    index_path = entry / "cache.json"
    if not index_path.exists():
        return None
    if _native_identity(root, bundle, xyz) != identity:
        raise ValueError("Native runtime/head/admission changed before cached fields could be read")
    index = json.loads(index_path.read_text())
    if index.get("schema") != PROVIDER_VERSION or index.get("provider_id") != entry.name:
        raise ValueError("Native cache index schema/identity mismatch")
    manifest_path = _existing(root, index["manifest_path"])
    if not manifest_path.is_relative_to(entry) or sha256_file(manifest_path) != index["manifest_sha256"]:
        raise ValueError("Native cache manifest path/hash mismatch")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("identity") != identity or manifest.get("status") != "completed" or manifest.get("provider_id") != entry.name:
        raise ValueError("Native cache identity or completion mismatch")
    payload_path = _existing(root, manifest["payload_path"])
    if not payload_path.is_relative_to(entry) or sha256_file(payload_path) != manifest["payload_sha256"]:
        raise ValueError("Native cache payload hash mismatch")
    with np.load(payload_path, allow_pickle=False) as payload:
        arrays = {name: payload[name] for name in payload.files}
    if set(arrays) != set(manifest["array_identities"]) or any(_array_identity(a) != manifest["array_identities"][name] for name, a in arrays.items()):
        raise ValueError("Native cache per-array identity mismatch")
    expected = {**bundle["catalog"], "baseline_h": bundle["baseline_h"],
                "baseline_xyz_mm": bundle["baseline_xyz"], "candidate_xyz_mm": xyz}
    for name, value in expected.items():
        if name not in arrays or not np.array_equal(arrays[name], value):
            raise ValueError(f"Native cache differs from frozen {name}")
    evaluated = _matrix(arrays.get("evaluated_candidate_xyz_mm"), 64, "native evaluated coordinates")
    if np.linalg.norm(evaluated - xyz, axis=1).max() > PROJECTION_TOLERANCE_MM:
        raise ValueError("Cached native projection moved the frozen design coordinates")
    inputs = _inputs(bundle, xyz, arrays["candidate_h"])
    return inputs, {"forward_mode": "native_fem_cache", "fem_recomputed": False,
        "provider_id": entry.name, "forward_cache_path": str(index_path.relative_to(root)),
        "forward_cache_sha256": sha256_file(index_path), "forward_manifest_path": str(manifest_path.relative_to(root)),
        "forward_manifest_sha256": index["manifest_sha256"], "forward_payload_sha256": manifest["payload_sha256"],
        "native_qa": manifest["native_qa"], "native_runtime": manifest["runtime"],
        "candidate_coordinate_identity": identity["candidate_coordinates"],
        "reference_field_origin": manifest["reference_field_origin"],
        "evaluated_candidate_xyz_mm": evaluated.tolist(), "native_origin_record": manifest["origin_record"]}


def _run_native(root, xyz, progress):
    """Lazy native import: normal catalog/bank reads do not load SimNIBS."""
    from . import design_evaluation
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    data, pointer, report = design_evaluation.load_bank(root)
    with threadpool_limits(limits=1):
        return design_evaluation.native_field(root, xyz, data, pointer, report, progress)


def load_reception_forward(root, record, *, progress=None, allow_native=False):
    """Return (load_inputs-compatible arrays, provenance) for a frozen record.

    ``progress`` accepts ``(fraction, message)``. Native cache hits are read-only;
    new native solves require an explicit allow_native=True call from the shared
    application queue. The record itself must point to an immutable completed
    design result and contain its evaluated_xyz_mm exactly, not the draft points.
    """
    root = Path(root).resolve()
    if type(allow_native) is not bool:
        raise ValueError("allow_native must be a boolean")
    progress = progress or (lambda *args: None)
    progress(.025, "校验冻结前向库、脑源坐标与法向")
    bundle = _load_bundle(root)
    xyz, record_provenance = _validate_record(root, record, bundle)
    base = {**bundle["provenance"], **record_provenance, "layout_optimized": False,
        "nearest_neighbour_replacement": False, "provider_code_sha256": sha256_file(Path(__file__)),
        "candidate_coordinate_identity": _array_identity(xyz),
        "reference_coordinate_identity": _array_identity(bundle["baseline_xyz"])}
    if np.array_equal(xyz, bundle["baseline_xyz"]):
        return _inputs(bundle, xyz, bundle["baseline_h"].copy()), {**base,
            "forward_mode": "exact_reference", "fem_recomputed": False, "candidate_bank_indices": None,
            "reference_field_origin": "original SHA256-validated frozen standard64 bank"}
    indices = _exact_rows(xyz, bundle["bank_xyz"])
    if indices is not None:
        with np.load(bundle["bank_path"], allow_pickle=False) as bank:
            candidate_h = bank["candidate_leadfield_v_per_am"][indices]
        return _inputs(bundle, xyz, candidate_h), {**base, "forward_mode": "exact_bank",
            "fem_recomputed": False, "candidate_bank_indices": indices.tolist(),
            "reference_field_origin": "original SHA256-validated frozen standard64 bank"}
    if record_provenance["design_result"] is None:
        raise ValueError("Non-bank coordinates require a SHA256-linked completed design_evaluation record; nearest-neighbour replacement is forbidden")
    identity = _native_identity(root, bundle, xyz)
    provider_id = _json_sha(identity)
    cache_root = root / CACHE_RELATIVE_ROOT
    entry = cache_root / provider_id
    if not entry.resolve().is_relative_to(root):
        raise ValueError("Native cache directory leaves the repository")
    cached = _read_cache(root, entry, identity, bundle, xyz)
    if cached is not None:
        inputs, cache_provenance = cached
        return inputs, {**base, **cache_provenance}
    if not allow_native:
        raise ForwardComputationRequired("冻结新坐标尚无接收实验前向缓存；需在本地单任务队列执行一次原位置FEM，不使用邻近电极替代。")
    with _native_lock(cache_root):
        cached = _read_cache(root, entry, identity, bundle, xyz)
        if cached is not None:
            inputs, cache_provenance = cached
            return inputs, {**base, **cache_provenance}
        attempt = entry / "attempts" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "_" + uuid.uuid4().hex[:8])
        attempt.mkdir(parents=True, exist_ok=False)
        started = time.perf_counter()
        _write_once(attempt / "started.json", _json_bytes({"identity": identity, "origin_record": record_provenance,
            "pid": os.getpid(), "status": "running", "created_at": datetime.now(timezone.utc).isoformat()}))
        try:
            progress(.08, "为已冻结的新坐标执行单线程原位置FEM，完成后永久复用")
            with threadpool_limits(limits=1):
                candidate_h, evaluated, projection_max, qa = _run_native(root, xyz, progress)
                runtime = {"python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__,
                    "threadpools": threadpool_info(), "thread_limit": 1, "elapsed_seconds": time.perf_counter() - started}
            evaluated = _matrix(evaluated, 64, "native evaluated coordinates")
            observed_movement = float(np.linalg.norm(evaluated - xyz, axis=1).max())
            if not np.isfinite(projection_max) or projection_max > PROJECTION_TOLERANCE_MM or observed_movement > PROJECTION_TOLERANCE_MM:
                raise ValueError("Native re-projection moved frozen evaluated_xyz_mm by more than 1e-7 mm; old record coordinates may not change")
            inputs = _inputs(bundle, xyz, candidate_h)
            if qa.get("head_hashes") != bundle["provenance"]["head_hashes"] or not np.isfinite(qa.get("reference_relative_difference", np.nan)) or qa["reference_relative_difference"] > 1e-8:
                raise ValueError("Native reference/head identity did not reproduce the frozen baseline")
            if _code_identities(root) != identity["code_sha256"]:
                raise ValueError("Native source code changed during forward computation")
            if _native_identity(root, bundle, xyz) != identity:
                raise ValueError("Native runtime, current head or admission changed during forward computation")
            if sha256_file(bundle["bank_path"]) != identity["bank_sha256"] or sha256_file(root / bundle["provenance"]["source_inputs_path"]) != identity["source_inputs_sha256"]:
                raise ValueError("Native forward input files changed during computation")
            for path_key, sha_key in (("source_manifest_path", "source_manifest_sha256"),
                                      ("bank_report_path", "bank_report_sha256")):
                if sha256_file(root / bundle["provenance"][path_key]) != bundle["provenance"][sha_key]:
                    raise ValueError("Frozen manifest/report changed during computation")
            proof = record_provenance["design_result"]
            if sha256_file(root / proof["path"]) != proof["sha256"]:
                raise ValueError("Completed design result changed during native computation")
            arrays = {**bundle["catalog"], "baseline_h": inputs["baseline_h"], "candidate_h": inputs["candidate_h"],
                "baseline_xyz_mm": inputs["baseline_xyz_mm"], "candidate_xyz_mm": xyz,
                "evaluated_candidate_xyz_mm": evaluated}
            arrays = {k: np.asarray(v) for k, v in arrays.items()}
            payload = deterministic_npz_bytes(arrays)
            payload_path = attempt / "forward_fields.npz"
            _write_once(payload_path, payload)
            manifest = {"schema": PROVIDER_VERSION, "status": "completed", "provider_id": provider_id,
                "identity": identity, "origin_record": record_provenance,
                "payload_path": str(payload_path.relative_to(root)), "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "array_identities": {name: _array_identity(a) for name, a in arrays.items()},
                "native_qa": qa, "runtime": runtime, "projection_max_mm": observed_movement,
                "reference_field_origin": "original SHA256-validated standard64 bank; native_field recomputed reference and passed relative difference <=1e-8, but that newly solved reference matrix is not exposed or archived",
                "completed_at": datetime.now(timezone.utc).isoformat()}
            manifest_path = attempt / "manifest.json"
            _write_once(manifest_path, _json_bytes(manifest))
            _write_once(entry / "cache.json", _json_bytes({"schema": PROVIDER_VERSION, "provider_id": provider_id,
                "manifest_path": str(manifest_path.relative_to(root)), "manifest_sha256": sha256_file(manifest_path)}))
            # Reopen and independently check the immutable archive before returning.
            checked_inputs, cache_provenance = _read_cache(root, entry, identity, bundle, xyz)
            return checked_inputs, {**base, **cache_provenance, "forward_mode": "native_fem_new", "fem_recomputed": True}
        except BaseException as error:
            _write_once(attempt / "failed.json", _json_bytes({"status": "failed", "error_type": type(error).__name__,
                "error": str(error), "elapsed_seconds": time.perf_counter() - started}))
            raise


__all__ = ["load_frozen_source_catalog", "load_reception_forward", "ForwardComputationRequired"]
