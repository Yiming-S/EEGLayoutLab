#!/usr/bin/env python3
"""Build the precomputed scalp-node FEM superposition table on a qualified native host.

Preview is the default. --execute solves a unit load at every table vertex
(scalp_node_table.VERTEX_RULE) with the qualified single-threaded MUMPS path (one factorization per
worker), merges worker shards, verifies the table against a direct FEM solve of
the standard64 reference, and atomically publishes it together with
results/v2/current_scalp_node_table.json. Each worker needs roughly 10 GiB of RAM.

    .runtime/simnibs-4.6.0/bin/python scripts/build_scalp_node_table.py --jobs 4
    .runtime/simnibs-4.6.0/bin/python scripts/build_scalp_node_table.py --jobs 4 --execute
    .runtime/simnibs-4.6.0/bin/python scripts/build_scalp_node_table.py --verify

--conductivity-scenario NAME builds the data-generating table of a named scenario
in configs/conductivity_scenarios.json under results/v2/scalp_node_table_scenarios/NAME
with its own pointer. Its standard64 check is against a direct FEM solve with the
same conductivities; the difference from the nominal bank is recorded, not gated.

--head ID builds the table of an additional head package (scripts/build_head_package.py)
under results/v2/heads/ID/table, checked against a direct FEM solve of the mapped
standard64 reference on that head.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_key] = "1"
SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "src"))

import numpy as np  # noqa: E402

from compact_eeg.artifacts import sha256_file  # noqa: E402
from compact_eeg.workflows import design_evaluation as de  # noqa: E402
from compact_eeg.workflows import head_package as hp  # noqa: E402
from compact_eeg.workflows import scalp_node_table as snt  # noqa: E402

BUILDER_CODE = ("scripts/build_scalp_node_table.py", "src/compact_eeg/workflows/scalp_node_table.py",
                "src/compact_eeg/workflows/design_evaluation.py", "src/compact_eeg/workflows/head_model.py",
                "src/compact_eeg/cortical_fem.py", "src/compact_eeg/workflows/head_package.py",
                "src/compact_eeg/surface_admissibility.py", "src/compact_eeg/forward_pilot.py",
                "src/compact_eeg/workflows/reception_forward_provider.py")
SCENARIO_DATA = ("configs/conductivity_scenarios.json",)  # read from --repository-root, like the head and bank
SUPERPOSITION_TOLERANCE = 1e-9  # relative Frobenius, table vs direct FEM at standard64
SECONDS_PER_NODE = (0.16, 0.47)  # observed single-thread range on the M3 Ultra, 2026-11-20


def emit(**values):
    print(json.dumps(values, ensure_ascii=False), flush=True)


def plan(root, head=None):
    if head is not None:
        return None, hp.table_vertices(hp.load(root, head))
    data, _pointer, _report = de.load_bank(root)
    vertices = snt.table_vertices(data["_eligible_surface"], data["_surface_faces"],
                                  data["_candidate_vertex_indices"], data["_allowed_bank"])
    return data, vertices


def code_identity(root, scenario=None):
    """SHA256 of the code that runs (workers import this script's tree) and of the data files read from ``root``."""
    files = [(SOURCE_ROOT, name) for name in BUILDER_CODE] + [(Path(root), name) for name in (SCENARIO_DATA if scenario else ())]
    missing = [str(base / name) for base, name in files if not (base / name).is_file()]
    if missing:
        raise SystemExit(f"Builder files missing: {missing}")
    return {name: sha256_file(base / name) for base, name in files}


def head_model(root, head, progress):
    """Native model of a head package: its mesh, default conductivities, sources and gauge."""
    from simnibs.mesh_tools import mesh_io
    package = hp.load(root, head)
    m = package.manifest
    mesh_path = (root / m["inputs"]["mesh"]) if not Path(m["inputs"]["mesh"]).is_absolute() else Path(m["inputs"]["mesh"])
    if sha256_file(mesh_path) != m["inputs"]["mesh_sha256"]:
        raise ValueError("Head package mesh differs from its manifest")
    mesh = mesh_io.read_msh(str(mesh_path))
    cond = np.zeros(mesh.elm.nr)
    for tag, value in m["conductivity_by_tetrahedron_tag"].items():
        cond[mesh.elm.get_tetrahedra(int(tag))] = value
    s = package.sources
    model, source_qa = de.checked_native_model(
        mesh, cond, package.scalp["vertices_mm"], package.scalp["triangles"], package.scalp["node_rows"],
        np.vstack([s["source_xyz_mm"], s["generation_xyz_mm"]]), np.vstack([s["source_normals"], s["generation_normals"]]),
        progress, gauge_node=package.gauge_node, exceptions=m["source_qa"]["exceptions"])
    reference = {"triangle_ids": package.mapping["reference_triangle_ids"], "barycentric_weights": package.mapping["reference_weights"],
                 "points": package.mapping["reference_xyz_mm"]}
    return model, source_qa, package.scalp["triangles"], reference, {"head_package": package.manifest_sha256}


def shard_vertices(vertices, index, count):
    return np.array_split(vertices, count)[index]


def run_shard(root, staging, index, count, block_size, scenario=None, head=None):
    """One worker: factorize once, solve its share of nodes, write rows and QA."""
    from threadpoolctl import threadpool_info, threadpool_limits
    from compact_eeg.workflows.head_model import load_head
    from compact_eeg.workflows import reception_forward_provider as provider
    started = time.perf_counter()
    vertices = shard_vertices(plan(root, head)[1], index, count)
    progress = lambda stage, **values: emit(shard=index, stage=stage)  # noqa: E731
    if head is not None:
        model, source_qa, faces, reference_points, head_hashes = head_model(root, head, progress)
        mapping = hp.load(root, head).scalp["node_rows"]
    else:
        data, pointer, report = de.load_bank(root)
        mesh, cond, surface, faces, mapping, head_hashes = load_head(root, scenario)
        if not np.array_equal(faces, data["_surface_faces"]) or not np.allclose(surface, data["_surface_vertices_mm"], rtol=0, atol=1e-9):
            raise ValueError("Native and screened surface indexing differ")
        sources, normals = de.frozen_sources(root, pointer, report, data, head_hashes)
        model, source_qa = de.checked_native_model(mesh, cond, surface, faces, mapping, sources, normals, progress)
        if model.gauge_node != snt.GAUGE_NODE_ONE_BASED:
            raise ValueError("Native gauge differs from the table definition")
        reference_points = {"points": data["reference_xyz_mm"]}
    extra = {}
    with threadpool_limits(limits=1):
        model.prepare_solver()
        pools = threadpool_info()
        if any(p["num_threads"] != 1 for p in pools):
            raise ValueError("Native FEM thread limit could not be enforced")
        if index == 0:
            # Direct reference solve along native_field's path, for the table check.
            projection = model.project(reference_points["points"], **{k: v for k, v in reference_points.items() if k != "points"})
            reference_h, reference_qa = model.evaluate(projection, block_size=4)
            extra = {"reference_direct_h": reference_h,
                     "reference_vertex_rows": faces[projection.triangle_ids],
                     "reference_weights": projection.barycentric_weights}
            emit(shard=index, stage="reference_direct_complete",
                 max_relative_residual=reference_qa["max_relative_full_system_residual"])
        last = [time.perf_counter()]
        def report_progress(done, total):
            if time.perf_counter() - last[0] > 60 or done == total:
                last[0] = time.perf_counter()
                emit(shard=index, stage="nodes", completed=done, total=total)
        rows, qa = snt.solve_node_rows(model, mapping[vertices], block_size=block_size, progress=report_progress)
    snt.check_node_qa(qa)
    np.save(staging / f"shard-{index}-rows.npy", rows)
    np.savez(staging / f"shard-{index}-qa.npz", vertex_indices=vertices, **qa, **extra)
    info = {"shard": index, "vertices": int(len(vertices)), "seconds": time.perf_counter() - started,
            "timings": dict(model.timings), "threadpools": pools, "head_hashes": head_hashes,
            "source_qa_fallback_max_mm": source_qa["fallback_distance_mm"]["maximum"]}
    if index == 0:
        runtime = provider._native_runtime_identity()
        info.update(native_runtime_sha256=provider._json_sha(runtime), python=sys.version,
                    numpy=np.__version__, simnibs=runtime["packages"]["simnibs"]["version"])
    (staging / f"shard-{index}.json").write_text(json.dumps(info, ensure_ascii=False))
    model.close()


def forward(stream, index):
    for line in stream:
        sys.stdout.write(f"[worker {index}] {line}")
        sys.stdout.flush()


def build(root, jobs, block_size, scenario=None, head=None):
    started = time.perf_counter()
    frozen = None if head is not None else snt.frozen_identity(root)
    identity = snt.expected_identity(root, scenario, head)
    _data, vertices = plan(root, head)
    code = code_identity(root, scenario)
    staging = snt.create_staging(root, scenario, head)
    emit(stage="start", vertices=int(len(vertices)), jobs=jobs, staging=str(staging))
    workers = []
    for index in range(jobs):
        command = [sys.executable, "-I", str(Path(__file__).resolve()), "--repository-root", str(root),
                   "--shard", f"{index}/{jobs}", "--staging", str(staging), "--block-size", str(block_size),
                   *(["--conductivity-scenario", scenario] if scenario else []), *(["--head", head] if head else [])]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        thread = threading.Thread(target=forward, args=(process.stdout, index), daemon=True)
        thread.start()
        workers.append((process, thread))
    codes = [process.wait() for process, _thread in workers]
    for _process, thread in workers:
        thread.join()
    failed = [index for index, code in enumerate(codes) if code != 0]
    if failed:
        raise SystemExit(f"Workers failed: {failed}; staging kept for inspection at {staging}")
    rows = np.lib.format.open_memmap(staging / snt.ROWS_NAME, mode="w+", dtype="<f8", shape=(len(vertices), snt.SOURCE_COUNT))
    qa = {name: np.empty(len(vertices)) for name in snt.QA_ARRAYS}
    shards, offset, reference = [], 0, None
    for index in range(jobs):
        part = np.load(staging / f"shard-{index}-rows.npy")
        with np.load(staging / f"shard-{index}-qa.npz") as archive:
            if not np.array_equal(archive["vertex_indices"], shard_vertices(vertices, index, jobs)):
                raise ValueError("Worker shard covers unexpected vertices")
            for name in snt.QA_ARRAYS:
                qa[name][offset:offset + len(part)] = archive[name]
            if index == 0:
                reference = {k: archive[k] for k in ("reference_direct_h", "reference_vertex_rows", "reference_weights")}
        rows[offset:offset + len(part)] = part
        offset += len(part)
        shards.append(json.loads((staging / f"shard-{index}.json").read_text()))
    rows.flush()
    positions = np.searchsorted(vertices, reference["reference_vertex_rows"])
    if not np.array_equal(vertices[positions], reference["reference_vertex_rows"]):
        raise ValueError("Standard64 reference triangles are outside the admissible table vertices")
    superposed = snt.superpose_rows(np.asarray(rows[positions.reshape(-1)]).reshape(*positions.shape, snt.SOURCE_COUNT),
                                    reference["reference_weights"])
    direct = reference["reference_direct_h"]
    verification = {
        "standard64_superposition_vs_direct_fem_relative_frobenius": float(np.linalg.norm(superposed - direct) / np.linalg.norm(direct)),
        "tolerance_superposition_vs_direct": SUPERPOSITION_TOLERANCE}
    if head is None:
        bank = de.load_bank(root)[0]["reference_leadfield_v_per_am"]
        verification.update({
            "standard64_superposition_vs_bank_relative_frobenius": float(np.linalg.norm(superposed - bank) / np.linalg.norm(bank)),
            "standard64_direct_fem_vs_bank_relative_frobenius": float(np.linalg.norm(direct - bank) / np.linalg.norm(bank)),
            # A scenario head differs from the nominal bank by design; that difference is descriptive.
            "tolerance_vs_bank": 1e-8 if scenario is None else None})
    else:
        # A head package has no frozen bank; its only reference check is the direct solve on that head.
        verification["reference"] = "mapped standard64 on the head package"
    if (verification["standard64_superposition_vs_direct_fem_relative_frobenius"] > SUPERPOSITION_TOLERANCE
            or (scenario is None and head is None and verification["standard64_superposition_vs_bank_relative_frobenius"] > 1e-8)):
        raise SystemExit(f"Table verification failed: {verification}; staging kept at {staging}")
    del rows
    for path in staging.glob("shard-*"):
        path.unlink()
    if snt.expected_identity(root, scenario, head) != identity:
        raise SystemExit("Frozen bank/head/admission identity changed during the build")
    if head is None and any(s["head_hashes"] != frozen["head_hashes"] for s in shards):
        raise SystemExit("Worker head hashes differ from the frozen head")
    first = shards[0]
    build_info = {"jobs": jobs, "block_size": block_size, "seconds": time.perf_counter() - started,
                  "workers": [{k: s[k] for k in ("shard", "vertices", "seconds", "timings")} for s in shards],
                  "native_runtime_sha256": first["native_runtime_sha256"], "simnibs": first["simnibs"],
                  "numpy": first["numpy"], "python": first["python"], "thread_limit": 1,
                  "builder_code_sha256": code}
    manifest = snt.finalize(root, staging, vertices, qa, frozen, build_info, verification, scenario, head)
    table = snt.load(root, scenario, head)
    table.verify_rows()
    emit(stage="published", table_id=manifest["table_id"], rows=manifest["rows"]["path"],
         gib=round((root / manifest["rows"]["path"]).stat().st_size / 2**30, 3),
         node_qa=manifest["node_qa"], verification=verification, seconds=round(build_info["seconds"], 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repository-root", default=str(SOURCE_ROOT))
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--block-size", type=int, default=8)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--verify", action="store_true", help="rehash the current table and check its identity")
    parser.add_argument("--conductivity-scenario", help="named data-generating scenario (configs/conductivity_scenarios.json)")
    parser.add_argument("--head", help="head package ID (results/v2/heads/ID)")
    parser.add_argument("--shard", help=argparse.SUPPRESS)
    parser.add_argument("--staging", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(args.repository_root).resolve()
    if args.shard:
        index, count = (int(v) for v in args.shard.split("/"))
        run_shard(root, Path(args.staging).resolve(), index, count, args.block_size, args.conductivity_scenario, args.head)
        return 0
    if args.verify:
        table = snt.load(root, args.conductivity_scenario, args.head)
        table.verify_rows()
        emit(stage="verified", **table.provenance())
        return 0
    if not 1 <= args.jobs <= 16 or not 1 <= args.block_size <= 16:
        parser.error("--jobs and --block-size must be between 1 and 16")
    _data, vertices = plan(root, args.head)
    gib = len(vertices) * snt.SOURCE_COUNT * 8 / 2**30
    hours = [len(vertices) * s / args.jobs / 3600 for s in SECONDS_PER_NODE]
    emit(stage="plan", repository_root=str(root), vertices=int(len(vertices)), table_gib=round(gib, 2),
         jobs=args.jobs, worker_ram_gib_each=10, estimated_hours=[round(h, 2) for h in hours],
         output=str(root / snt.table_root(args.conductivity_scenario, args.head)),
         pointer=str(root / snt.pointer_relative(args.conductivity_scenario, args.head)), head=args.head,
         conductivity_scenario=snt.scenario_identity(root, args.conductivity_scenario), execute=args.execute)
    if args.execute:
        build(root, args.jobs, args.block_size, args.conductivity_scenario, args.head)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
