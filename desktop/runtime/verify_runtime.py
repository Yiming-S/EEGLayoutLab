#!/usr/bin/env python3
"""Bounded numerical/relocation probe; never reads or writes experiment data."""
from __future__ import annotations

import argparse
import ctypes
import importlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    prefix, project = args.prefix.resolve(), args.project_root.resolve()
    if Path(sys.prefix).resolve() != prefix:
        raise RuntimeError("Python resolved to an external prefix: " + sys.prefix)
    modules = {}
    for name in ("numpy", "scipy", "matplotlib", "threadpoolctl", "simnibs", "mumps", "cortech", "petsc4py", "fmm3dpy", "h5py", "nibabel", "surfa", "torch"):
        module = importlib.import_module(name)
        location = Path(module.__file__).resolve()
        if not location.is_relative_to(prefix):
            raise RuntimeError("External import: " + name + ": " + str(location))
        modules[name] = str(location.relative_to(prefix))
    import compact_eeg
    from compact_eeg.workflows.paths import PROJECT_ROOT
    if Path(compact_eeg.__file__).resolve().parent != project / "src/compact_eeg" or PROJECT_ROOT.resolve() != project:
        raise RuntimeError("The relative .pth did not select the relocated project")
    # Exercise compiled CGAL, BLAS and the actual MUMPS factorization/solve path.
    import numpy as np
    import scipy.sparse
    import mumps
    import cortech
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        a = scipy.sparse.csc_matrix([[4., 1., 0.], [1., 3., 1.], [0., 1., 2.]])
        expected = np.array([1., 2., 3.])
        b = np.asarray(a @ expected)
        solver = mumps.Context()
        solver.factor(a)
        solution = solver.solve(b)
        error = float(np.max(np.abs(solution - expected)))
        if error > 1e-12:
            raise RuntimeError("Relocated MUMPS solve failed: " + str(error))
        surface = cortech.Surface(np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]), np.array([[0, 1, 2]], dtype=np.int32))
        _, _, projected, _ = surface.project_points(np.array([[.2, .2, .1]]), pttris=np.array([[0]], dtype=np.int64))
        projection_error = float(np.max(np.abs(projected - [[.2, .2, 0.]])))
        if projection_error > 1e-12:
            raise RuntimeError("Relocated CGAL surface projection failed")
        from simnibs.mesh_tools.cgal import pyAABBTree
        tree = pyAABBTree()
        tree.set_data(surface.vertices, np.asarray(surface.faces, dtype=np.int64))
        intersections, _ = tree.intersection(np.array([[.2, .2, -.1]]), np.array([[.2, .2, .1]]))
        if len(intersections) != 1:
            raise RuntimeError("Relocated native CGAL segment intersection failed")
    from compact_eeg.workflows.reception_forward_provider import _native_runtime_identity
    native = _native_runtime_identity()
    # Import-path checks alone cannot detect a dylib silently loaded from the
    # developer's Conda/Homebrew install. Inspect dyld's actual loaded images.
    process = ctypes.CDLL(None)
    count = process._dyld_image_count
    count.restype = ctypes.c_uint32
    image = process._dyld_get_image_name
    image.argtypes = [ctypes.c_uint32]
    image.restype = ctypes.c_char_p
    loaded = [image(i).decode() for i in range(count())]
    external = [p for p in loaded if p.startswith("/") and not p.startswith(("/usr/lib/", "/System/Library/", "/System/Volumes/Preboot/Cryptexes/OS/usr/lib/", "/System/Volumes/Preboot/Cryptexes/OS/System/Library/")) and not Path(p).resolve().is_relative_to(prefix)]
    if external:
        raise RuntimeError("Non-system loaded libraries outside runtime: " + repr(external))
    print(json.dumps({"schema": "eeglayoutlab-relocated-runtime-probe/1", "status": "passed",
                      "prefix": str(prefix), "project_root": str(project), "python": sys.version,
                      "imports": modules, "mumps_solution_max_abs_error": error,
                      "cgal_projection_max_abs_error": projection_error,
                      "native_cgal_intersection_count": len(intersections),
                      "native_conda_records": len(native["conda_records"]),
                      "loaded_image_count": len(loaded), "external_loaded_images": external,
                      "scope": "Relocated runtime imports, sparse solve, CGAL and native identity on the build Mac; not a second-Mac or full FEM validation."}, indent=2))


if __name__ == "__main__":
    main()
