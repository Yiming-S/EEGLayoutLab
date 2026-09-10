# Collaboration checkout verification

Recorded on **2026-09-10** on macOS **26.6.2**, Apple Silicon (`arm64`), Node
**26.5.0**, Python **3.11.14**, and SimNIBS **4.6.0**.

The native runtime was reconstructed from the locked packages in the final
checkout. It was not copied from the development environment. Python imports and
the project package resolve inside the new checkout. No earlier Git history or
personal job cache was imported.

## Checks completed

| Check | Result |
| --- | --- |
| Data manifest | 21 files verified; 406,226,293 bytes. |
| Original scientific modules | All 35 `src/compact_eeg` Python modules retain their original bytes. |
| Frozen numerical inputs, results and 3D buffers | Original SHA-256 identities retained. |
| Native environment | 193 Conda records, 40 native libraries; import audit and `pip check` passed. |
| Python suite with all three existing-bank integration options enabled | 311 passed, 112 subtests passed, no skipped tests. |
| Node unit suite | 137 passed, no failed or skipped tests. |
| Type checking, lint and production build | Passed. |
| HTTP routes | All 11 routes returned HTTP 200. This is not browser rendering verification. |
| Development start | `npm run dev` served the design page, local health endpoint, teaching excerpt and 3D manifest successfully. |
| Supplied result library | 402 completed records, no loading warnings: 30 current-area, 30 historical-area, 342 historical-radius variants. |
| Local computation | New 64-electrode layout, 63-electrode edit, fixed-coordinate evaluation and six-source existing-bank scenario completed. Identical requests replayed saved results. |
| Native coordinate calculation | New off-bank coordinate request completed using direct FEM; reference cross-check met the existing 1e-8 tolerance. |
| Native source scenarios | Single-source and six-source simulations completed with evaluated coordinates, followed by matching cached replay. |
| Restarted service | All integration cases, including direct FEM and both native source cases, replayed the saved disk caches after a server restart. |
| Local API controls | Cross-origin, invalid Host and missing-token cases were rejected by the service checks. |

The direct-FEM coordinate job took approximately **101 seconds**, and the first
native single-source job approximately **103 seconds** on this preparation
computer. These are individual observations, not installation or performance
guarantees for another computer. The following native multi-source case took
approximately **3 seconds** after the forward computation was cached.

## Data identities

- `data/manifest.json` SHA-256:
  `518f9681c2aeaeff902613f2e31d73c8edba4568c8cd8bba27b0e87fa6b1d4fd`
- `eeglayoutlab-data-v1.tar.gz` SHA-256:
  `5fd77a9066cf31ae0d59b26b608ca4e83fe7013dec0a57c39fcf22d6869c8265`
- Archive size: **296,184,211 bytes** (282.46 MiB).

The archive is separate from Git. New computations are also excluded from Git
and are not automatically added to this frozen archive.

## Repeating the checks

Use the installation and standard checks in [CONTRIBUTING.md](../CONTRIBUTING.md).
Enable all existing-bank Python integrations from the repository root with:

```sh
PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
LOCAL_RADIUS_REAL_BANK=1 SOURCE_RECEPTION_REAL_BANK=1 \
SOURCE_RECEPTION_V2_REAL_BANK=1 \
.runtime/simnibs-4.6.0/bin/python -B -m pytest -q -rs
```

Use the optional `--native` switch on the HTTP integration script to exercise the
direct-FEM and native-source paths. This creates new local calculation records
on cache misses and replays existing records on matching cache hits.

## Scope not established

No second independent Mac installation or interactive browser/WebGL test was
performed during this extraction. No signed desktop application was built. No
new head model, scientific metric, optimization rule or production result was
introduced. Independent-head validity and volume-mesh convergence remain as
described in [validation scope](validation.md).

The frontend dependency audit still reports the five affected entries listed in
[security status](security.md). Passing functional checks does not resolve them.

The original `experiment_protocol_v2.json` is retained unchanged because it
contains both the live anatomical preset matrix and historical design material.
Its historical planning fields are not current result or completion metadata.
