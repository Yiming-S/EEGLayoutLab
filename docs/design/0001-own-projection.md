# 0001 — Own surface projection

- **Status:** evaluated; reproduces cortech 0.1 to the last bit; not adopted (reserved for the 1.0 identity change)
- **Date:** 2026-11-23
- **Decision:** [design 0001](0001-local-first-architecture.md), decision 10 (cortech)
- **Code:** `src/eeglayoutlab/forward/projection.py`; nothing calls it
- **Tests:** `tests/test_surface_projection.py`

## Result

`eeglayoutlab.forward.projection.project_points(vertices, faces, points, 20)` returns the same triangles, weights, projected points and distances as the project's call `cortech.Surface(vertices, faces).project_points(points, pttris=20)`, to the last bit, including the sign of zero. It therefore passes and fails the existing checks exactly where cortech does.

Compared on macOS arm64 with the project runtime: Python 3.11.14, numpy 2.3.0, scipy 1.17.1 and the cortech 0.1 `cp311` release wheel.

| Point set | Points | Bit-identical | Largest projected-point deviation | Triangle differences |
| --- | --- | --- | --- | --- |
| Phase 0 set on the Ernie scalp | 6,745 | 6,745 | 0 | 0 |
| Admissible-mask boundary on the Ernie scalp | 6,300 | 6,300 | 0 | 0 |
| Planar and curved grids, 500 points each (including one above every vertex), `k` = 1, 5 and 20 | 3,000 projections | 3,000 | 0 | 0 |

- **Candidate triangles.** For every Ernie point the candidate list (sorted triangles incident to the 20 nearest vertices) equals cortech's, compared through `return_all_projections`.
- **Phase 0 set.** The 64 standard positions, the 5,387 bank candidates, every 5th candidate moved 0–3 mm and every 25th moved 5–15 mm in random directions (seed 20261122). The test rebuilds it from the bank and checks its SHA-256 against the phase 0 input file.
- **Mask boundary.** The 692 corners of triangles that have both passing and screened corners, and the 355 edges between an admissible and a screened triangle: points on the corners, 1 mm above and below them along the normal, 2 mm ∓ 1e-9 mm above them (the registration-distance limit), on the edge midpoints, 1 mm above and below the midpoints, 1e-12 mm and 1e-6 mm to either side across the edge, and at a third of each edge.
  - 2,283 of these points are at exactly the same distance from several candidate triangles. For 1,140 of them the tied triangles include an admissible and a screened one, so the admission check of design evaluation is decided by the tie rule (lowest triangle index wins).
- **Existing checks.** Weights within [−1e-10, 1 + 1e-10] and summing to one within 1e-10, weights reproducing the projected point within 1e-7 mm (`scalp_node_table.project`, `FixedMeshLeadfield.project`), the admission check on the triangle's three corners and the 2 mm registration distance (`design_evaluation.candidate_projector`). All hold on every Ernie point.
- **Speed.** Projecting the 6,745 points takes about 0.17 s with either. Importing cortech takes a further 0.13 s after numpy and scipy, because it loads numba, llvmlite and four CGAL extensions; the own module imports only numpy and `scipy.spatial`.

## Why bit identity is required

An implementation that is only mathematically equal does not reproduce the projections. Two such variants of the own module, measured against cortech:

| Variant | Point set | Bit-identical | Triangle differences | Largest projected-point deviation | Admission changes |
| --- | --- | --- | --- | --- | --- |
| Dot products by `einsum` | Phase 0 | 5,724 of 6,745 | 1 | 1.4e-14 mm | 0 |
| Dot products by `einsum` | Mask boundary | 2,836 of 6,300 | 101 | 0.87 mm | 68 |
| Ties go to the last minimum | Phase 0 | 1,315 of 6,745 | 5,430 | 4.4e-16 mm | 4 |
| Ties go to the last minimum | Mask boundary | 4,017 of 6,300 | 2,283 | 0.62 mm | 903 |

- Bank candidates sit on mesh vertices, so most of them are ties between the vertex's triangles. The triangle decides which zero-weight corner the admission check reads.
- The deviations of 0.6–0.9 mm are for points 1 mm below the surface in concave areas, where two surface points are equally close and rounding picks one.

The module therefore follows cortech's floating-point operations in the same order, reduces each array in the same shape and memory layout, and takes the first minimum. The tests compare bits rather than tolerances, and fail for each variant above.

## Method and differences from cortech 0.1

The method is cortech's: the triangles incident to each point's `k` nearest vertices (`scipy.spatial.cKDTree`), the closest point on each by Eberly's region method, and the first candidate at the smallest distance. The candidate lists are built with array operations instead of a per-point `np.unique`. Differences that do not affect the project's calls:

- **Equal triangle counts per vertex.** A mesh in which every vertex has the same number of triangles works. cortech 0.1 raises `IndexError` there, because `get_triangle_neighbors` builds a 2-D object array. The tests use a single triangle, a tetrahedron and an octahedron: cortech raises `IndexError`; with one far, unused vertex added, cortech runs and agrees with the own module on the original mesh to the last bit.
- **`k` above the vertex count** uses every vertex; cortech raises `IndexError`.
- **Input errors.** Non-finite points, faces outside the vertices and points without a candidate triangle raise `ValueError`. No points give empty results.
- **Index type.** Triangles are int64; cortech returns int32. Every call site converts them or only indexes with them.

## Tests

`tests/test_surface_projection.py` has three tiers:

| Tests | Needs | Marker |
| --- | --- | --- |
| Planar grid and border cases of `check_environment.py` and the recipe test, a curved grid against a brute-force closest point, meshes with equal triangle counts per vertex, candidate lists, input errors | numpy, scipy | none (fast tier) |
| Bit identity with cortech on the synthetic grids; the `IndexError` case | cortech | `native_runtime` |
| Bit identity and candidate lists with cortech on both Ernie sets, with at least 1,000 ties that decide admission | cortech, data bundle | `data_bundle`, `native_runtime` |
| SHA-256 of the own outputs on both Ernie sets equal to the recorded cortech outputs | data bundle | `data_bundle` |

The recorded phase 0 digest is also that of the outputs saved in phase 0 from the macOS arm64 and Linux x86_64 release wheels. The own module itself has been run only on macOS arm64.

```bash
.runtime/simnibs-4.6.0/bin/python -B -m pytest tests/test_surface_projection.py -q -p no:cacheprovider
```

## What adopting it would change

Adopting means replacing the four calls of `cortech.Surface(...).project_points(...)` (`cortical_fem.py`, `scalp_node_table.py`, `design_evaluation.py`, `scripts/check_environment.py`) with the own module.

- **Projections.** None on the current numpy and scipy: the same triangles, weights, projected points and distances, so the same evaluations. Published scalp-node tables and head packages hold per-node rows and need no rebuild.
- **Scientific identities.** This is the planned identity change of decision 8, best made together with moving `compact_eeg` into `eeglayoutlab/core` at 1.0:
  - The bytes of `cortical_fem.py`, `design_evaluation.py` and `scalp_node_table.py`, which the design-evaluation and reception identities hash, change; `projection.py` has to enter those identities.
  - cortech leaves the runtime fingerprints: its `dist-info/METADATA` in the design-evaluation identity (`webapp/server/runtime/scientific-context.mjs`, and `eeglayoutlab/jobs/identity.py` on the phase 2 branch), and its `.py` and `.so` files in the reception runtime identity (`NATIVE_PACKAGES` in `reception_forward_provider.py`).
  - Old records stay readable; only cache reuse is lost.
- **Dependencies.**
  - User installations, which evaluate from bank and table data, no longer need cortech, numba, llvmlite or nibabel; in the Linux table runtime these are there only for the projection (`TABLE_RUNTIME_MODULES` in `check_environment.py`), and their METADATA leaves its identity too.
  - The conda-forge package of EEGLayoutLab no longer waits on a cortech recipe or on its licence question.
  - SimNIBS 4.6 itself requires cortech, so author-side environments (FEM, table and head building) still install it. The draft recipe stays useful there.
- **numpy and scipy.** The projections still depend on them as cortech's do: on how numpy reduces a row, on `clip` and `norm`, and on `cKDTree`'s neighbour order. Without cortech installed, the recorded digests above are the reference for an upgrade.
- **Licence.** The module follows cortech's arithmetic step by step and is treated as derived from cortech 0.1 (GPL-3.0). EEGLayoutLab is GPL-3.0-only, which is compatible with `GPL-3.0-only` and `GPL-3.0-or-later`. Before adoption, `THIRD_PARTY_NOTICES.md` needs a cortech entry; it needs one in any case before cortech is distributed with EEGLayoutLab.
- **Package.** On this branch `src/eeglayoutlab` has no `__init__.py`, so `eeglayoutlab.forward` is importable from `src` but not packaged. It becomes a regular subpackage when merged with the phase 2 branch, which adds `src/eeglayoutlab/__init__.py`.
