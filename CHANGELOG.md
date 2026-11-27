# Changelog

All notable user-visible, packaging and scientific-identity changes to EEGLayoutLab are recorded in this file. Changes that alter request or cache keys are marked explicitly ([design 0001](docs/design/0001-local-first-architecture.md), decision 8; [0003](docs/design/0003-identity-at-1.0.md)).

## Unreleased

### Added

- **Local-first Python service (`eeglayoutlab serve`, design 0001 phase 2).** Serves the static web interface, loopback-only session and CSRF authentication, `/docs/` offline documentation when built, workspace-local projects (`W/projects`), robustness studies (`W/studies`), electrode-name annotations (`W/annotations`), single-flight task queue (`W/.eeglayoutlab/queue.json`), `eeglayoutlab workspace import-legacy`, and research-project delivery exports (`eeg-research-delivery/1`).
- **Complete pure-Python scientific command line (phase 3 slices 4–7 and 11–13).** `eeglayoutlab` now runs `design` (10-05 labels, native/MNI/landmark BIDS pairs, `.elc`/`.sfp` montages and search runs), `export` (`bids`, `mni`, `mne`, `eeglab` and `svg` layout figures), `evaluate`, `search`, `study`, `pareto`, `eeg-summary`, `prior`, `channels` (`--figure` SVG) and `examples run` without requiring Node.js at run time.
- **Three-command onboarding, health diagnostics and in-browser missing-data guidance.** Added `eeglayoutlab quickstart` (auto-installing missing model packages and opening the workspace), `eeglayoutlab doctor [--smoke]` (environment, data and `1e-6` score check), `scripts/setup_local.py` (one-command source checkout setup), and `GET /api/data-status` with bilingual `<DataReadinessNotice />` copyable terminal prompts and hot reload in the browser.
- **Versioned data-package release index and installer (`data/packages.json`, phase 3 slice 8).** Pins all 15 model packages (`base`, `scalp-node-table`, two skull-conductivity scenario tables, `head-ernie_xh` and ten IXI head packages) with exact SHA-256 digests, HTTP `Range` download resumption, `eeglayoutlab data install` default set (`base` + `scalp-node-table`), `--examples` cross-head set, and automatic composition into an installed Conda environment.
- **Conda packaging, browser/release CI and versioned documentation (design 0002; phase 3 slices 2, 3, 9, 10, 16 and 17).** `rattler-build` v1 recipes for `cortech` and `eeglayoutlab`, build-time `THIRD_PARTY_WEB_LICENSES.txt` generation for bundled browser packages, GitHub Actions workflows (`checks.yml`, `data.yml`, `package.yml`, `browser.yml` with `build-browser-fixtures.mjs`, and `release.yml` staging draft releases and `mike` versioned docs), and repository metadata (`CITATION.cff`, `.zenodo.json`, `SECURITY.md`).
- **Illustrated bilingual installation and user manuals (`docs/installation*.md`, `docs/user-manual*.md`, phase 3 slices 14–15)** with localized SVG workflow diagrams, in-app `/guide` links, and Python-service authentication support for regenerating showcase data (`webapp/scripts/build-showcase-data.mjs`).
- **Sparse/adaptive layout exports, inline CLI search and interactive cold-start helpers.** Unlocked Web coordinate CSV + 2D paper figure (`SVG` and 3× `PNG`) exports and CLI `eeglayoutlab export --format bids|mni|mne|eeglab|svg` for all valid `8–64` channel and `adaptive`-quota search layouts; added inline `--regions`/`--radius`/`--mode`/`--masks`/`--electrodes`/`--allocation`/`--objective`/`--noise` flags to `eeglayoutlab search`; added a one-click synthetic 32-channel 10-05 covariance demo and copyable CLI bar on `/channels`, upfront `v2` SimNIBS environment guidance on `/reception`, and Rolldown vendor chunk splitting (`three-vendor`, `charts-vendor`).

### Scientific and identity changes

- **Checkout keys preserved against Node.** Across all Phase 2 and Phase 3 service and CLI ports, source-checkout request keys (`D`, `Rad`, `E`, `V1`, `V2`, `St`) remain byte-identical to the legacy Node reference on the same scientific root and interpreter.
- **Installed-environment identity rows (design 0002, phase 3 slice 3 — installed Conda form only).** When `eeglayoutlab` runs from an installed Conda prefix `P` against `P/share/eeglayoutlab/root` with `P/bin/python`, `design-evaluation-cache/1` (`D`, and `E`, `V2`, `St` built on it) records `environment:bin/python`, `environment:conda-meta/<name>.json` for the numerical dependency closure only (excluding `eeglayoutlab`'s own record and unrelated packages, decision U16), and `METADATA` / `PKG-INFO` for `cortech`, `nibabel`, `numba`, `numpy`, `scipy` and `llvmlite`. Source checkouts are unaffected.
- **Variable electrode counts, adaptive regional allocation and composite search (`v7`).** Regional layout search (`src/compact_eeg/local_radius_compute.py`) supports `1 <= electrode_count <= 64` in the Python worker and discrete counts `8, 12, 16, 24, 32, 48, 64` (plus `allocation_mode: "adaptive"` and `objective_mode: "composite"`) in `/api/local-compute` and `eeglayoutlab search`, with convergent Fedorov exchange sweeps, region-centre repair and zero-leakage dictionary confusion-margin reranking; `examples/expected.json` and `examples/README.md` reflect the updated Example 2 and Example 3 scores.

## 0.2.0 — 2026-11

- Published the frozen base data bundle (`eeglayoutlab-data-v1.tar.gz` and `.sha256`) and established the web-based multi-region layout design, coordinate import, electrode editor, robustness study, signal reception v1/v2 and research-project delivery workflows.
- Tagged `node-host-freeze` as the frozen reference point for legacy hosted Node deployments prior to the local-first Python service migration.

## 0.1.2 — 2026-10

- Final release of the retired macOS desktop wrapper; all subsequent development targets the browser interface backed by the local scientific service.
