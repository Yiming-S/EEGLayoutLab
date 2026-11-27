# Repository scripts (`scripts/`)

This directory holds **33 operational, build, and worker entry-point scripts** grouped into four distinct roles. Most end-user and scientific workflows run through the `eeglayoutlab` command line ([command-line reference](../docs/command-line.md)); the scripts below either serve as internal subprocess entry points spawned by the service/CLI or support source-checkout setup, offline model-package building, and release verification.

## 1. Identity-locked worker & runtime entry points (11 files — do not edit or move)

The SHA-256 digests and exact relative paths (`scripts/<name>.py`) of these **11 files** are pinned in [`tests/service/identity_inputs.json`](../tests/service/identity_inputs.json) and participate directly in scientific cache keys (`D`, `Rad`, `E`, `V1`, `V2`, `St`). **Do not rename, move, or reformat them** outside an explicit protocol/identity decision ([design 0003](../docs/design/0003-identity-at-1.0.md)):

| Script | Invoked by | Role |
| --- | --- | --- |
| [`design_evaluation.py`](design_evaluation.py) | `evaluate`, `study`, `/api/design-evaluation` | Compatibility worker entry point delegating to `compact_eeg.workflows.design_evaluation` |
| [`electrode_editor.py`](electrode_editor.py) | `/api/electrode-editor` | Compatibility worker entry point delegating to `compact_eeg.workflows.electrode_editor` |
| [`run_local_radius_compute.py`](run_local_radius_compute.py) | `search`, `/api/local-compute` | Reads one regional radius-search request from `stdin` and streams NDJSON progress/results |
| [`run_source_reception.py`](run_source_reception.py) | `/api/source-reception` (v1) | Bounded multi-source regional signal-reception worker |
| [`run_source_reception_v2.py`](run_source_reception_v2.py) | `/api/source-reception` (v2) | Bounded single-dipole cortical signal-reception worker and frozen source catalog reader |
| [`source_reception.py`](source_reception.py) | Legacy / compatibility imports | Compatibility entry point delegating to `compact_eeg.workflows.source_reception` |
| [`source_reception_v2.py`](source_reception_v2.py) | Legacy / compatibility imports | Compatibility entry point delegating to `compact_eeg.workflows.source_reception_v2` |
| [`reception_forward_provider.py`](reception_forward_provider.py) | Native evaluation & v2 reception | Compatibility entry point delegating to `compact_eeg.workflows.reception_forward_provider` |
| [`inspect_ernie_cortical_forward.py`](inspect_ernie_cortical_forward.py) | Forward QA checks | Read-only cortical source interpolation and template scalp-projection QA inspector |
| [`inspect_reception_runtime.py`](inspect_reception_runtime.py) | v2 reception identity | Read-only numerical-runtime digest shared with native forward cache identities |
| [`inspect_reception_runtime_snapshot.py`](inspect_reception_runtime_snapshot.py) | `jobs.runtime_digest` | Read-only filesystem snapshot wrapper accelerating runtime digest reuse |

Two additional non-locked helpers run alongside the workers:

- [`eeg_data.py`](eeg_data.py): Subprocess worker invoked by `eeglayoutlab eeg-summary` and `eeglayoutlab prior` (summaries carry their own input recording digests rather than a code cache key).
- [`runtime_identity_watch.py`](runtime_identity_watch.py): Filesystem stat/inode watcher helper for invalidating memoized runtime digests when an environment changes.

## 2. Source-checkout setup & local data management (4 files)

Used when setting up or verifying a development source checkout ([source installation](../docs/source-installation.md)):

| Script | Role |
| --- | --- |
| [`setup_local.py`](setup_local.py) | Stdlib-only (`python3 >= 3.9`) one-command source setup for Apple Silicon macOS and Linux `x86_64` (base data download + SHA-256 check, `.runtime/`, `.venv`, `webapp/` build, optional `--smoke`) |
| [`bootstrap_runtime.py`](bootstrap_runtime.py) | Installs the locked scientific Conda + pip runtime (`.runtime/simnibs-4.6.0` on macOS or `.runtime/compute-linux-64` on Linux); defaults to a read-only plan unless `--execute` is passed |
| [`check_environment.py`](check_environment.py) | Verifies Python, numerical package versions, and surface projection (`--native`) without mutating data or cache manifests |
| [`data_bundle.py`](data_bundle.py) | Stdlib-only installer, exporter, and SHA-256 verifier for the 21-file base data archive (`data/manifest.json`) |

## 3. Author-side model builders, study runners & release QA (11 files)

Used by maintainers on a qualified SimNIBS host or during release qualification:

| Script | Role |
| --- | --- |
| [`build_scalp_node_table.py`](build_scalp_node_table.py) | Solves or `--verify`-checks precomputed scalp-node FEM superposition tables (nominal, conductivity scenarios, or `--head <id>`) |
| [`build_head_package.py`](build_head_package.py) | Builds a portable cross-head evaluation package (`results/v2/heads/<id>/`) from a SimNIBS `charm` segmentation |
| [`build_ernie_mni_mapping.py`](build_ernie_mni_mapping.py) | Builds and verifies `ernie-scalp-mni.bin` and `ernie-mni-mapping.json` from the SimNIBS Ernie dataset |
| [`export_source_roi.py`](export_source_roi.py) | Exports DK40-merged cortical ROI display buffers (`source-roi-cortex.bin`, `source-roi.json`) |
| [`export_history_coordinates.py`](export_history_coordinates.py) | Extracts exact frozen-bank coordinates for historical study snapshots |
| [`run_area_budget_study.py`](run_area_budget_study.py) | Executes and verifies the 30-condition fixed-union-area (`strict_area`) campaign |
| [`prepare_verification_workspace.py`](prepare_verification_workspace.py) | Builds an isolated QA checkout under `artifacts/` (preview by default; `--execute` to write) |
| [`verify_native_release.py`](verify_native_release.py) | Runs the fresh native FEM release gate against an immutable reference bundle ([native release gate](../docs/native-release-gate.md)) |
| [`release_manifest.py`](release_manifest.py) | Records current Git commit, data manifest digest, and selected runtime identity |
| [`prepare_release_v021.py`](prepare_release_v021.py) | Read-only pre-release readiness checker (`--check`, `--verify-archives DIR`; never pushes or tags) |

## 4. Legacy Node-host operations & cache warming (6 files — retained until Phase 4)

Operational utilities for the frozen legacy Node host (`node-host-freeze`, documented in [web operations](../docs/web-operations.md) and [task reconciliation](../docs/task-reconciliation.md)):

| Script | Role |
| --- | --- |
| [`backup_service.py`](backup_service.py) | Previews, creates, and restores offline snapshots of a legacy Node host's queue and records |
| [`reconcile_service.py`](reconcile_service.py) | Previews or applies offline queue-receipt reconciliation against verified caches |
| [`inspect_service_reconciliation.mjs`](inspect_service_reconciliation.mjs) | Read-only Node cache inspector invoked under `reconcile_service.py`'s offline locks |
| [`preflight_source_cache.py`](preflight_source_cache.py) | Read-only coordinate qualification check prior to batch atlas cache warming |
| [`precompute_source_cache.mjs`](precompute_source_cache.mjs) | Low-priority resumable atlas source-cache warmer ([atlas source cache](../docs/CACHE_PRECOMPUTE.md)) |
| [`test-precompute.mjs`](test-precompute.mjs) | Unit smoke test for the legacy cache precomputation helper |
