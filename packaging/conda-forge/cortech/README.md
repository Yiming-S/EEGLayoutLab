# cortech conda-forge recipe (draft)

A draft [conda-forge](https://conda-forge.org) recipe for [cortech](https://github.com/simnibs/cortech) 0.1, built from the v0.1 source tag. cortech is not on conda-forge or PyPI; its GitHub release publishes wheels for CPython 3.11 and 3.12 only. EEGLayoutLab uses it only through `cortech.Surface(vertices, faces).project_points(points, pttris=20)` (decision 10 of [design 0001](../../../docs/design/0001-local-first-architecture.md)).

Status: draft, not submitted to `conda-forge/staged-recipes`. Upstream coordination comes first (see below).

| File | Purpose |
| --- | --- |
| `recipe.yaml` | Recipe in the v1 format (rattler-build) |
| `build.sh` | Build script for Linux and macOS |
| `run_test.py` | Package test: exact projections on known geometry and one call into each compiled module |

## Build notes

- **CGAL lookup.** `meson.build` asks for `dependency('cgal', version: '>= 6.0')`. conda-forge's `cgal-cpp` ships a CMake package but no pkg-config file, and meson's CMake lookup reports the Boost version (1.90.0) as CGAL's, so the check fails. `build.sh` writes a private `cgal.pc` for the build only; it is not installed. Upstream's own `tools/conda_generate_pkgs.py` would do the same, but three of its f-strings are missing the `f` prefix, so the files it writes are unusable.
- **C++ standard.** CGAL 6 requires C++17 and `meson.build` sets no `cpp_std`; upstream takes it from the native file that conan writes. `build.sh` passes `-Dcpp_std=gnu++17`. Without it Apple clang stops with `CGAL requires C++ 17`.
- **Linking.** The conda build links GMP and MPFR from the environment (their run_exports apply); the upstream wheels link them statically through conan.
- **Platforms.** Windows is skipped (no `bld.bat`, untested). osx-64 and cross-compilation are untested; `build.sh` passes `MESON_ARGS` through for the cross file.

## Verification

Done on 2026-11-22 on an Apple Silicon Mac (macOS 27.2) and an x86_64 Ubuntu 26.04 host. The fixed point set was 6,745 points on the Ernie scalp (52,410 vertices, 104,864 triangles): the 64 standard positions, all 5,387 bank candidates, 1,078 candidates moved by 0–3 mm and 216 moved by 5–15 mm in random directions. Projections used the project's call, `pttris=20`, and were compared against the release wheel in use (`cp311` wheel, same numpy 2.3.0 and scipy 1.17.1).

| Platform | Python | Source build | Projection vs. release wheel | This recipe (rattler-build) |
| --- | --- | --- | --- | --- |
| macOS arm64 | 3.11 | yes | bit-identical | built; tests pass |
| macOS arm64 | 3.12 | yes | bit-identical | built; tests pass |
| macOS arm64 | 3.13 | yes | bit-identical | built; tests pass |
| Linux x86_64 | 3.11 | yes | bit-identical | built; tests pass |
| Linux x86_64 | 3.12 | yes | bit-identical | built; tests pass |
| Linux x86_64 | 3.13 | yes | bit-identical | built; tests pass |

- **Source build:** `pip wheel --no-build-isolation` with the same `cgal.pc` and `cpp_std` settings as `build.sh`, in conda-forge environments with numpy 2.3.0 and scipy 1.17.1 (CGAL 6.2.1, Eigen 5.0.1, Boost 1.90); Apple clang 21 on macOS, conda-forge gcc 14.4 on Linux. About 30 s (macOS) and 37 s (Linux) per build.
- **Projection:** the project's call on the point set above; triangles, weights, projected points and distances are equal to the last bit. The Mac and Linux release wheels also agree with each other to the last bit.
- **Recipe:** rattler-build 0.81.0 with `conda-forge-pinning`, restricted to Python 3.11–3.13. Under the pinning the solver picked cgal-cpp 6.1.2 with Boost 1.88. macOS used conda-forge clang 21 and deployment target 11.0. On Linux the run used gcc 14 and the glibc 2.28 sysroot from the local cache instead of the current pins (gcc 15, sysroot 2.17). Every variant passed the import test, `pip check`, `run_test.py` and the upstream test suite (64 passed, 1 skipped by upstream).

`project_points` is plain numpy and scipy (`cKDTree`, sparse matrices); the compiled CGAL modules are imported but not called. The Python sources at the v0.1 tag are byte-identical to those in the release wheels, so a source build projects exactly as the wheel does as long as numpy and scipy are the same.

Upstream issues seen along the way, all present in the release wheels too and none on EEGLayoutLab's path: `Surface.points_inside_surface` segfaults on the Ernie scalp; `get_triangle_neighbors` builds a 2-D object array when every vertex touches the same number of triangles, so `project_points` fails on such meshes (a single triangle, for example); `utils.normalize` calls `np.divide(..., where=...)` without `out` (fixed on `main`).

## Before submitting

Upstream coordination with the SimNIBS/cortech maintainers:

1. Agreement to package cortech on conda-forge, ideally with an upstream maintainer as co-maintainer of the feedstock.
2. The licence as an SPDX expression (`GPL-3.0-only` or `GPL-3.0-or-later`); the recipe assumes `-only`.
3. `cpp_std=c++17` in `meson.build` and a CGAL lookup that works with conda-forge's `cgal-cpp` (or a fixed `tools/conda_generate_pkgs.py`), so the recipe needs neither workaround.
4. Python 3.13 (and 3.14) in the cibuildwheel matrix; 3.13 builds and tests cleanly here.
5. An sdist on PyPI, or at least a stable tag archive, as the recipe source.
6. Plans for 0.2: `main` is 35 commits past v0.1, including a refactor of `Surface`. EEGLayoutLab pins 0.1 until a new version is shown to reproduce the current projections.
