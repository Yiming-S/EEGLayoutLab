#!/usr/bin/env python3
"""Build one additional head package for cross-head evaluation (native SimNIBS runtime).

Preview is the default; --execute runs the stages and writes
results/v2/heads/<head-id>/{scalp,admissibility,sources,mapping}.npz and package.json.
Stages are resumable: a finished stage is reused when its recorded inputs, including
the SHA256 of the code it runs, match. A charm m2m folder is reused only after a
recorded successful charm of the same scans and SimNIBS version; any other existing
folder is resumed only when this builder recorded the attempt, or with --charm-resume.
The package is refused when the mapped standard64 reference fails the layout screen.
package.json names the m2m folder, mesh and Ernie m2m folder by their paths under the
repository root, read without following links: a link under the root to a folder elsewhere
is recorded by its own path, so the package names no host directory. An input outside the
root is refused; link it under the root instead.

    # existing m2m folder (Ernie under the cross-head protocol)
    .runtime/simnibs-4.6.0/bin/python scripts/build_head_package.py --head-id ernie_xh \\
        --m2m data/external/simnibs4_examples/m2m_ernie --dataset "SimNIBS example dataset v4.1" --subject ernie --execute
    # new subject: charm first (1-2 h, peak 34-38 GB RAM; run one at a time)
    .runtime/simnibs-4.6.0/bin/python scripts/build_head_package.py --head-id ixi002 \\
        --t1 IXI002-Guys-0828-T1.nii.gz --t2 IXI002-Guys-0828-T2.nii.gz --dataset IXI --subject IXI002-Guys-0828 --execute

The scalp-node table is built afterwards with
``scripts/build_scalp_node_table.py --head <head-id> --jobs 4 --execute``.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_key, "1")
SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT / "src"))

import numpy as np  # noqa: E402

from compact_eeg.artifacts import sha256_file  # noqa: E402
from compact_eeg.forward_pilot import deterministic_npz_bytes  # noqa: E402
from compact_eeg.workflows import design_evaluation as de  # noqa: E402
from compact_eeg.workflows import head_package as hp  # noqa: E402

ERNIE_M2M = Path("data/external/simnibs4_examples/m2m_ernie")
CODE = ("scripts/build_head_package.py", "src/compact_eeg/workflows/head_package.py",
        "src/compact_eeg/surface_admissibility.py", "src/compact_eeg/cortical_fem.py",
        "src/compact_eeg/workflows/scalp_node_table.py", "src/compact_eeg/workflows/design_evaluation.py")
# Source files each stage executes; a change re-runs the stage.
STAGE_CODE = {"scalp.npz": ("src/compact_eeg/workflows/head_package.py",),
              "admissibility.npz": ("src/compact_eeg/workflows/head_package.py", "src/compact_eeg/surface_admissibility.py"),
              "sources.npz": ("scripts/build_head_package.py", "src/compact_eeg/workflows/head_package.py"),
              "mapping.npz": ("scripts/build_head_package.py", "src/compact_eeg/workflows/head_package.py",
                              "src/compact_eeg/workflows/scalp_node_table.py")}
# Earlier versions of a stage code file whose stage code is the same as now: stages they finished are
# reused. Add the outgoing SHA256 when a change leaves every stage's computation alone; empty the
# entry when a change touches what a stage computes.
SAME_STAGE_CODE = {"scripts/build_head_package.py": frozenset({
    "f19914806fb2c40a5885838834ddd4e5b15afa5ccc26bbae16436a4a862e611e",  # 0.2.0: recorded input paths with links followed
})}
CHARM_LABELS = Path("label_prep/tissue_labeling_upsampled.nii.gz")  # written after the MNI warps
LICENSES = {"IXI": {"license": "CC BY-SA 3.0", "url": "https://brain-development.org/ixi-dataset/",
                    "attribution": "IXI dataset, https://brain-development.org/ixi-dataset/"}}


def emit(**values):
    print(json.dumps(values, ensure_ascii=False, default=str), flush=True)


def recorded_path(root, path):
    """An input's path under the repository root, as package.json records it.

    The path as given comes first, without following links, so a link under the root names a
    folder elsewhere by its own path; the path with links followed is the fallback. The table
    builder opens the mesh at the recorded path.
    """
    for candidate in (Path(os.path.abspath(path)), Path(path).resolve()):
        if candidate.is_relative_to(root):
            return candidate.relative_to(root).as_posix()
    raise SystemExit(f"{path} is outside the repository root {root}; link it under the root "
                     "(for example under data/external/) and pass that path")


def normalized(value):
    """JSON round trip: inputs compare the way stages.json stores them (tuples become lists)."""
    return json.loads(json.dumps(value))


def stage_code(name):
    return {path: sha256_file(SOURCE_ROOT / path) for path in STAGE_CODE[name]}


def write_stage(directory, name, arrays, inputs, stages):
    path = directory / name
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(deterministic_npz_bytes(arrays))
    os.replace(tmp, path)
    stages[name] = {"inputs": normalized(inputs), "sha256": sha256_file(path)}


def same_inputs(recorded, inputs):
    """Recorded stage inputs equal these, reading a code version in SAME_STAGE_CODE as the current file."""
    code = recorded.get("code_sha256")
    if isinstance(code, dict):
        current = inputs.get("code_sha256") or {}
        recorded = {**recorded, "code_sha256": {
            path: current.get(path, sha) if sha in SAME_STAGE_CODE.get(path, ()) else sha for path, sha in code.items()}}
    return recorded == inputs


def reusable(directory, name, inputs, stages):
    entry = stages.get(name)
    return bool(entry and same_inputs(entry["inputs"], normalized(inputs)) and (directory / name).is_file()
                and sha256_file(directory / name) == entry["sha256"])


def charm_plan(stages, inputs, m2m_exists, mesh_sha256, labels_ready, registered, resume_requested):
    """How to obtain the m2m folder: ('reuse' | 'run' | 'adopt' | 'resume' | 'rerun', operator_asserted).

    A folder is reused only after a recorded successful charm with these inputs
    and mesh bytes, and refused when a record names other scans or another
    SimNIBS version. A record that differs only in --charm-forceqform is refused
    with that reason, except an unfinished attempt without the option retried
    with it: charm refused those headers, so charm reruns with --forceqform.
    A folder without a builder record needs --charm-resume,
    the operator's assertion that it came from these scans: a finished folder
    (mesh present) is adopted as is, otherwise charm continues it. --surfaces
    rewrites the label image after the spherical registration, so charm resumes
    at --surfaces only before that point and otherwise starts over.
    """
    inputs = normalized(inputs)
    done, attempt = stages.get("charm"), stages.get("charm_attempt")
    if m2m_exists and done and done["inputs"] == inputs and mesh_sha256 is not None and done["mesh_sha256"] == mesh_sha256:
        return "reuse", bool(done.get("operator_asserted"))
    if not m2m_exists:
        return "run", False
    def scans(entry):
        return {key: value for key, value in entry["inputs"].items() if key != "forceqform"}
    recorded = [entry for entry in (done, attempt) if entry]
    if any(scans(entry) != scans({"inputs": inputs}) for entry in recorded):
        raise SystemExit("The m2m folder was recorded for other scans or another SimNIBS version; "
                         "move it aside to rerun charm")
    wanted = bool(inputs.get("forceqform"))
    if any(bool(entry["inputs"].get("forceqform")) != wanted for entry in recorded):
        if wanted and done is None and mesh_sha256 is None and not labels_ready:
            # charm refused these headers before writing anything; --forcerun replaces the folder it left.
            return "rerun", bool(attempt.get("operator_asserted"))
        if wanted:
            raise SystemExit("The m2m folder was recorded without --charm-forceqform; drop the option to use it, "
                             "or move it aside to rerun charm")
        # Without the option charm would delete the folder (--forcerun) and then refuse the headers again.
        raise SystemExit("The m2m folder was recorded with --charm-forceqform; pass --charm-forceqform to use it, "
                         "or move it aside to rerun charm")
    if attempt is None and not resume_requested:
        raise SystemExit("The m2m folder exists without a recorded charm run of these scans and SimNIBS version; "
                         "move it aside to rerun charm, or pass --charm-resume if it came from these scans")
    if attempt is None and mesh_sha256 is not None:
        return "adopt", True
    asserted = bool(attempt.get("operator_asserted")) if attempt is not None else True
    return ("resume" if labels_ready and not registered else "rerun"), asserted


def charm_manifest_inputs(charm):
    """package.json fields describing how the charm folder was obtained."""
    return {"charm_resumed": bool(charm["operator_asserted"]), "charm_action": charm["action"],
            **({"charm_forceqform": True} if charm["inputs"].get("forceqform") else {})}


def reference_screen(head_id, eligible, rows, xyz, projection):
    """Refuse to publish a package whose mapped standard64 reference fails the layout screen."""
    screened, spacing, distance, passes = hp.layout_screen(eligible, rows, xyz, projection)
    if not passes:
        # The mapped reference normalizes every score on this head, so it must pass the layout screen.
        raise SystemExit(f"Not published: the mapped standard64 reference fails the layout screen on {head_id} "
                         f"(triangles screened: {screened}, minimum spacing {spacing:.2f} mm, "
                         f"maximum projection {distance:.2f} mm)")
    return screened, spacing, distance


def charm_command(charm, head_id, action, t1, t2, force_qform=False):
    """charm reads the scan headers only when it starts from the scans, so a resume never takes --forceqform."""
    scans = [str(Path(t1).resolve()), *([str(Path(t2).resolve())] if t2 else []), *(["--forceqform"] if force_qform else [])]
    return [str(charm), head_id, *{"run": scans, "rerun": [*scans, "--forcerun"], "resume": ["--surfaces", "--mesh"]}[action]]


def check_x86_runtime():
    """charm runs SimNIBS's bundled x86_64 tools (meshfix, CAT); Apple silicon needs Rosetta 2 for them."""
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return
    import simnibs
    probe = Path(simnibs.__file__).parent / "external/bin/osx/meshfix"
    try:
        subprocess.run([str(probe)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    except OSError as error:
        if error.errno == 86:  # EBADARCH: no x86_64 translation installed
            raise SystemExit("charm needs Rosetta 2 to run SimNIBS's bundled x86_64 tools on Apple silicon; install it with "
                             "'softwareupdate --install-rosetta --agree-to-license' and run this build again") from error
        raise


def run_charm(head_id, t1, t2, work, stages, save_stages, resume_requested, force_qform=False):
    """m2m folder for these scans and the charm stage entry; charm's output goes to work/charm.log."""
    import simnibs
    work.mkdir(parents=True, exist_ok=True)
    m2m = work / f"m2m_{head_id}"
    mesh = m2m / f"{head_id}.msh"
    inputs = normalized({"t1_sha256": sha256_file(t1), "t2_sha256": sha256_file(t2) if t2 else None,
                         "simnibs": simnibs.__version__, **({"forceqform": True} if force_qform else {})})
    registered = any((m2m / "surfaces" / f"{side}.sphere.reg.gii").is_file() for side in ("lh", "rh"))
    action, asserted = charm_plan(stages, inputs, m2m.exists(), sha256_file(mesh) if mesh.is_file() else None,
                                  (m2m / CHARM_LABELS).is_file(), registered, resume_requested)
    if action == "reuse":
        return m2m
    if action == "adopt":
        stages["charm"] = {"inputs": inputs, "action": action, "exit_code": None, "operator_asserted": asserted,
                           "mesh_sha256": sha256_file(mesh)}
        save_stages()
        emit(stage="charm_adopted", m2m=str(m2m))
        return m2m
    check_x86_runtime()
    command = charm_command(Path(sys.executable).parent / "charm", head_id, action, t1, t2, force_qform)
    stages.pop("charm", None)  # a recorded success describes the folder charm is about to change
    stages["charm_attempt"] = {"inputs": inputs, "operator_asserted": asserted}
    save_stages()
    emit(stage="charm_start", action=action, command=command, cwd=str(work))
    with open(work / "charm.log", "w" if action == "run" else "a") as log:
        code = subprocess.call(command, cwd=work, stdout=log, stderr=subprocess.STDOUT)
    if code != 0 or not mesh.is_file():
        raise SystemExit(f"charm failed with exit code {code}; see {work / 'charm.log'}")
    stages["charm"] = {"inputs": inputs, "action": action, "exit_code": code, "operator_asserted": asserted,
                       "mesh_sha256": sha256_file(mesh)}
    save_stages()
    return m2m


def build(args, root):
    started = time.perf_counter()
    head_id = hp.check_head_id(args.head_id)
    directory = root / hp.package_dir(head_id)
    directory.mkdir(parents=True, exist_ok=True)
    stage_path = directory / "stages.json"
    stages = json.loads(stage_path.read_text()) if stage_path.is_file() else {}
    def save_stages():
        stage_path.write_text(json.dumps(stages, indent=1))
    inputs = {}
    if args.t1:
        m2m = run_charm(head_id, args.t1, args.t2, root / "data/external/heads" / head_id, stages, save_stages, args.charm_resume,
                        args.charm_forceqform)
        inputs["t1_sha256"] = stages["charm"]["inputs"]["t1_sha256"]
        if args.t2:
            inputs["t2_sha256"] = stages["charm"]["inputs"]["t2_sha256"]
    else:
        m2m = Path(os.path.abspath(args.m2m))  # as named: a link under the root is recorded by its own path
    mesh_path = m2m / f"{m2m.name.removeprefix('m2m_')}.msh"
    ernie_m2m = Path(os.path.abspath(root / args.ernie_m2m))
    paths = {"m2m": recorded_path(root, m2m), "mesh": recorded_path(root, mesh_path), "ernie_m2m": recorded_path(root, ernie_m2m)}
    central = [m2m / "surfaces" / f"{side}.central.gii" for side in ("lh", "rh")]
    spheres = [m2m / "surfaces" / f"{side}.sphere.reg.gii" for side in ("lh", "rh")]
    import simnibs
    templates = Path(simnibs.__file__).parent / "resources/templates"
    atlas = [(templates / f"fsaverage_surf/{side}.sphere.gii", templates / f"fsaverage_atlases/{side}.aparc_DK40.annot")
             for side in ("lh", "rh")]
    inputs.update(mesh_sha256=sha256_file(mesh_path), central_sha256=[sha256_file(p) for p in central],
                  sphere_reg_sha256=[sha256_file(p) for p in spheres],
                  atlas_sha256=[[sha256_file(p) for p in pair] for pair in atlas])
    emit(stage="inputs", m2m=str(m2m), **inputs)

    from simnibs.mesh_tools import mesh_io
    from simnibs.utils import mesh_element_properties
    mesh = mesh_io.read_msh(str(mesh_path))
    elm = (mesh.elm.elm_type, mesh.elm.tag1, mesh.elm.node_number_list)
    scalp_inputs = {"mesh_sha256": inputs["mesh_sha256"], "rule": "largest tag-1005 component", "code_sha256": stage_code("scalp.npz")}
    if not reusable(directory, "scalp.npz", scalp_inputs, stages):
        vertices, triangles, node_rows = hp.exterior_scalp(mesh.nodes.node_number, mesh.nodes.node_coord, *elm)
        write_stage(directory, "scalp.npz", {"vertices_mm": vertices, "triangles": triangles, "node_rows": node_rows}, scalp_inputs, stages)
        save_stages()
    with np.load(directory / "scalp.npz") as archive:
        scalp = {k: archive[k] for k in archive.files}
    emit(stage="scalp", vertices=len(scalp["vertices_mm"]), triangles=len(scalp["triangles"]))

    admission_inputs = {"scalp_sha256": stages["scalp.npz"]["sha256"], "directions": hp.ADMISSION_DIRECTION_COUNTS,
                        "rotation_rad": hp.ADMISSION_ROTATION_RAD, "code_sha256": stage_code("admissibility.npz")}
    if not reusable(directory, "admissibility.npz", admission_inputs, stages):
        emit(stage="admissibility_start")
        write_stage(directory, "admissibility.npz", hp.admissibility(scalp["vertices_mm"], scalp["triangles"]), admission_inputs, stages)
        save_stages()
    with np.load(directory / "admissibility.npz") as archive:
        eligible = archive["eligible_vertex_mask"].astype(bool)
        unstable = int(archive["unstable_vertex_mask"].sum())
    emit(stage="admissibility", eligible=int(eligible.sum()), vertices=len(eligible), unstable=unstable)

    conductivity = {str(int(tag)): float(mesh_element_properties.tissue_conductivities[int(tag)])
                    for tag in np.unique(mesh.elm.tag1[mesh.elm.get_tetrahedra()])}
    cond = np.zeros(mesh.elm.nr)
    for tag, value in conductivity.items():
        cond[mesh.elm.get_tetrahedra(int(tag))] = value
    gauge = hp.deep_gauge(mesh.nodes.node_coord, *elm)
    source_inputs = {"central_sha256": inputs["central_sha256"], "sphere_reg_sha256": inputs["sphere_reg_sha256"],
                     "atlas_sha256": inputs["atlas_sha256"], "protocol": hp.SOURCE_PROTOCOL,
                     "code_sha256": stage_code("sources.npz")}
    if not reusable(directory, "sources.npz", source_inputs, stages):
        import nibabel as nib
        surfaces = [mesh_io.read_gifti_surface(str(p)) for p in central]
        vertices = np.vstack([s.nodes.node_coord for s in surfaces])
        offset = len(surfaces[0].nodes.node_coord)
        faces = np.vstack([surfaces[0].elm.node_number_list[:, :3] - 1, surfaces[1].elm.node_number_list[:, :3] - 1 + offset])
        cortex = []
        for sphere, (template, annot) in zip(spheres, atlas):
            labels, _colors, names = nib.freesurfer.io.read_annot(str(annot))
            cortex.append(hp.cortex_mask(mesh_io.read_gifti_surface(str(sphere)).nodes.node_coord,
                                         mesh_io.read_gifti_surface(str(template)).nodes.node_coord,
                                         labels, [name.decode() for name in names]))
        cortex = np.concatenate(cortex)
        if len(cortex) != len(vertices):
            raise SystemExit("sphere.reg and central surfaces differ in vertex count")
        emit(stage="sources_start", cortical_vertices=len(vertices), medial_wall_vertices=int((~cortex).sum()))
        write_stage(directory, "sources.npz", hp.sample_sources(vertices, faces, cortex), source_inputs, stages)
        save_stages()
    with np.load(directory / "sources.npz") as archive:
        sources = {k: archive[k] for k in archive.files}
    emit(stage="source_qa_start")
    model, source_qa = de.checked_native_model(
        mesh, cond, scalp["vertices_mm"], scalp["triangles"], scalp["node_rows"],
        np.vstack([sources["source_xyz_mm"], sources["generation_xyz_mm"]]),
        np.vstack([sources["source_normals"], sources["generation_normals"]]),
        lambda stage, **values: None, gauge_node=gauge, exceptions=None)
    exceptions = de.source_exceptions(model)
    del model
    emit(stage="source_qa", fallback_max_mm=source_qa["fallback_distance_mm"]["maximum"], exceptions=len(exceptions))

    data, pointer, report = de.load_bank(root)
    if sha256_file(ernie_m2m / "ernie.msh") != json.loads((root / "configs/ernie_fem_point_pilot.json").read_text())["mesh_sha256"]:
        raise SystemExit("The Ernie m2m folder is not the frozen Ernie head")
    same_subject = inputs["mesh_sha256"] == sha256_file(ernie_m2m / "ernie.msh")
    transforms = [ernie_m2m / "toMNI" / "Conform2MNI_nonl.nii.gz", m2m / "toMNI" / "MNI2Conform_nonl.nii.gz"]
    mapping_inputs = {"scalp_sha256": stages["scalp.npz"]["sha256"], "ernie_candidates_sha256": report["candidate_sha256"],
                      "bank_sha256": pointer["sha256"], "same_subject": same_subject,
                      "transforms_sha256": None if same_subject else [sha256_file(p) for p in transforms],
                      "code_sha256": stage_code("mapping.npz")}
    if not reusable(directory, "mapping.npz", mapping_inputs, stages):
        ernie_vertices = data["_surface_vertices_mm"]
        if same_subject:
            mapped = ernie_vertices.copy()  # identity: the package is the frozen Ernie head itself
        else:
            from simnibs import mni2subject_coords, subject2mni_coords
            emit(stage="mapping_start", vertices=len(ernie_vertices))
            mapped = mni2subject_coords(subject2mni_coords(ernie_vertices, str(ernie_m2m)), str(m2m))
        reference = hp.map_points(data["reference_xyz_mm"], ernie_vertices, data["_surface_faces"], mapped,
                                  scalp["vertices_mm"], scalp["triangles"])
        write_stage(directory, "mapping.npz", {
            "ernie_scalp_to_head_mm": np.asarray(mapped, float), "reference_xyz_mm": reference["projected_mm"],
            "reference_vertex_rows": reference["vertex_rows"], "reference_weights": reference["barycentric_weights"],
            "reference_triangle_ids": reference["triangle_ids"], "reference_projection_mm": reference["mapping_projection_mm"]},
            mapping_inputs, stages)
        save_stages()
    with np.load(directory / "mapping.npz") as archive:
        reference_xyz = archive["reference_xyz_mm"]
        reference_projection = archive["reference_projection_mm"]
        reference_rows = archive["reference_vertex_rows"]
    reference_screened, reference_spacing, _distance = reference_screen(head_id, eligible, reference_rows, reference_xyz,
                                                                        reference_projection)

    dataset = {"name": args.dataset, "subject": args.subject, **LICENSES.get(args.dataset, {})}
    manifest = {
        "schema": hp.SCHEMA, "head_id": head_id, "dataset": dataset,
        "inputs": {**inputs, **paths, "charm": bool(args.t1),
                   **(charm_manifest_inputs(stages["charm"]) if args.t1 else {})},
        "conductivity_by_tetrahedron_tag": conductivity, "conductivity_source": "simnibs.utils.mesh_element_properties defaults",
        "gauge_node_one_based": gauge, "gauge_rule": "white-matter node nearest the white-matter node centroid",
        "source_protocol": hp.SOURCE_PROTOCOL,
        "source_qa": {"fallback_distance_mm": source_qa["fallback_distance_mm"], "exceptions": exceptions,
                      "interpolation_row_sum_max_error": source_qa["interpolation_row_sum_max_error"]},
        "admission": {"rule": "external exposure screen, Ernie direction sets and acceptance", "eligible_vertices": int(eligible.sum()),
                      "vertices": int(len(eligible)), "unstable_vertices": unstable},
        "mapping": {"method": "identity (same subject)" if same_subject else "SimNIBS nonlinear Ernie->MNI->subject at Ernie scalp vertices; barycentric interpolation; projection",
                    "same_subject_as_ernie": same_subject,
                    "reference_projection_mm": {"maximum": float(reference_projection.max()), "median": float(np.median(reference_projection))},
                    "reference_minimum_spacing_mm": reference_spacing,
                    "reference_triangles_screened": reference_screened},
        "ernie": {"bank_candidate_sha256": report["candidate_sha256"]},
        "files": {name: stages[name]["sha256"] for name in hp.FILES},
        "code_sha256": {name: sha256_file(SOURCE_ROOT / name) for name in CODE},
        "simnibs": __import__("simnibs").__version__, "numpy": np.__version__,
    }
    tmp = directory / "package.json.tmp"
    tmp.write_bytes(hp.json_bytes(manifest))
    os.replace(tmp, directory / "package.json")
    package = hp.load(root, head_id)
    emit(stage="published", head_id=head_id, package_sha256=package.manifest_sha256, gauge=gauge,
         table_vertices=int(len(hp.table_vertices(package))), seconds=round(time.perf_counter() - started, 1),
         mapping=manifest["mapping"], source_qa=manifest["source_qa"]["fallback_distance_mm"])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repository-root", default=str(SOURCE_ROOT))
    parser.add_argument("--head-id", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--m2m", help="existing SimNIBS m2m folder under the repository root (a link there is fine)")
    source.add_argument("--t1", help="T1-weighted image; runs charm")
    parser.add_argument("--t2", help="T2-weighted image for charm")
    parser.add_argument("--charm-resume", action="store_true",
                        help="use an existing m2m folder with no recorded charm attempt, asserting it came from these "
                             "scans: a finished folder is adopted, otherwise charm continues it (recorded as "
                             "charm_resumed and charm_action in package.json)")
    parser.add_argument("--charm-forceqform", action="store_true",
                        help="pass --forceqform to charm, for scans whose qform and sform differ (IXI headers differ by "
                             "rounding, up to 2e-5, which charm refuses); recorded in the charm inputs and package.json")
    parser.add_argument("--ernie-m2m", default=str(ERNIE_M2M), help="full Ernie m2m with toMNI transforms, relative to the root")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if (args.charm_resume or args.charm_forceqform) and not args.t1:
        parser.error("--charm-resume and --charm-forceqform apply to charm builds (--t1)")
    root = Path(args.repository_root).resolve()
    hp.check_head_id(args.head_id)
    emit(stage="plan", head_id=args.head_id, output=str(root / hp.package_dir(args.head_id)),
         charm=bool(args.t1), execute=args.execute)
    if args.execute:
        build(args, root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
