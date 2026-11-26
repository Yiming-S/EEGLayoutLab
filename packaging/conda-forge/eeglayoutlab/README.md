# conda-forge recipe for eeglayoutlab (draft)

A rattler-build recipe (format v1) for the application installed from conda-forge (phase 3 of [design 0001](../../../docs/design/0001-local-first-architecture.md)). It installs the layout decided in [design 0002](../../../docs/design/0002-installed-scientific-root.md):

```text
$PREFIX/lib/python3.11/site-packages/eeglayoutlab/   the service, all 9 scientific CLI commands, examples & data CLI
$PREFIX/bin/eeglayoutlab                             the entry point
$PREFIX/share/eeglayoutlab/root/                     the scientific root R
  src/compact_eeg/  scripts/  configs/  examples/
  data/{manifest.json,packages.json,SOURCES.md,README.md}
  webapp/public/  webapp/dist/client/                the interface, exported as static pages at build time
```

`compact_eeg` exists only in R, never in `site-packages`. Node (`>=22.18`) is needed only at package build time to export the static interface and generate `THIRD_PARTY_WEB_LICENSES.txt`; it is not a run dependency. Model data is not in the package: `eeglayoutlab data install` fetches and verifies packages from `data/packages.json` into the user data directory and automatically hard-links them into R in an installed environment.

The recipe is not submitted yet. It builds the checkout it sits in (`source: path`); a submitted recipe takes the public release tarball and its SHA-256 after `cortech` is on conda-forge.

| File | Purpose |
| --- | --- |
| `recipe.yaml` | Requirements, entry point, bundled web license file and package tests |
| `build.sh` | Builds the interface, generates `THIRD_PARTY_WEB_LICENSES.txt`, installs `eeglayoutlab` only, copies R |
| `run_test.py` | Package test: R tree, no `compact_eeg` in `site-packages`, `default_repository_root()`, worker interpreter, numerical-closure `environment:` rows, fixture `data build`/`install`/`verify`, and `design`/`export` without Node |

## Building and installing locally

```bash
rattler-build build -r packaging/conda-forge/eeglayoutlab --output-dir OUT -c file://CORTECH_CHANNEL -c conda-forge
```

```bash
conda create -p ENV --override-channels -c file://OUT -c file://CORTECH_CHANNEL -c conda-forge eeglayoutlab
```

Once installed in `ENV`, no `--root` or `EEG_COMPUTE_PYTHON` is needed:

```bash
ENV/bin/eeglayoutlab data install --from /path/to/mirror        # installs & auto-composes base + scalp-node-table
ENV/bin/eeglayoutlab examples run --skip-cross-head             # runs examples 1 & 2 into ./eeglayoutlab-examples
ENV/bin/eeglayoutlab serve                                      # starts local web workspace on 127.0.0.1
```

`EEGLAYOUTLAB_NPM_CACHE` points the build at an existing npm cache; empty, npm uses a cache in the work directory. `cortech 0.1` is not on conda-forge yet, so it comes from a local channel built from [`packaging/conda-forge/cortech`](../cortech/README.md).

## Design 0002 & Phase 3 implementation status

All code items required by [design 0002](../../../docs/design/0002-installed-scientific-root.md) and Phase 3 Slices 2–9 & 11–13 are implemented and verified:

1. **Default scientific root (`Slice 2`).** `default_repository_root()` selects the checkout holding the package, else `<realpath(sys.prefix)>/share/eeglayoutlab/root` when it holds `src/compact_eeg`. `serve`, `data install`, `data compose`, `examples run` and all scientific CLI commands need no `--root` in the installed form.
2. **Default worker interpreter (`Slice 2`, `U8`).** In the installed form when R is the installed root, workers run with `<realpath(sys.prefix)>/bin/python` without `EEG_COMPUTE_PYTHON`.
3. **Read-only root refusal (`Slice 2`).** `serve` (including `--cache-only`), `data compose` and an auto-composing `data install` exit 2 when R or `results/v2` is not writable, instructing the user to create a writable user environment.
4. **Deliveries (`Slice 2`).** Delivery exports read version metadata from `compact-eeg` and reference `configs/runtime/manifest-linux-64.json` when no managed SimNIBS runtime is present.
5. **Environment identity rows (`Slice 3`, `U16`, `U17`).** Installed-form D, E, V2 and St identities include `environment:bin/python`, `environment:conda-meta/<name>.json` for the numerical closure only, and `METADATA` / `PKG-INFO` for `cortech`, `nibabel`, `numba`, `numpy`, `scipy` and `llvmlite`, verified against `<realpath(sys.prefix)>`.
6. **Pure-Python scientific CLI & examples runner (`Slices 4–7 & 11–13`).** `design`, `export`, `evaluate`, `search`, `eeg-summary`, `prior`, `channels`, `pareto` and `examples run` all run in Python without Node.js; `examples run` writes to `./eeglayoutlab-examples` by default in an installed environment and refuses paths inside R (`U14`).
7. **Data package index & auto-compose (`Slice 8`).** `R/data/packages.json` pins all 15 release packages; `eeglayoutlab data install` resolves dependencies, verifies manifest and `base` bundle digests, and automatically composes hard links into R in an installed environment.
8. **Bundled web license inventory (`Slice 9`).** `webapp/scripts/third-party-licenses.mjs` generates `THIRD_PARTY_WEB_LICENSES.txt` during `build.sh` for inclusion via `recipe.yaml`'s `license_file`, excluding build-only dependencies.

## Verification history (macOS arm64)

- **2026-11-23 (initial recipe build):** Built `eeglayoutlab-0.2.0` (`62 MB`) with `rattler-build 0.81.0`, resolved 90 packages (`2.3 GB`, Python 3.11.18, `libopenblas 0.3.34`), composed `base`, `scalp-node-table` and all 11 rebuilt heads (zero home-directory paths), and matched all 24 scores of `expected.json`.
- **2026-11-26 (post-0002 & Phase 3 Slices 2–9, 11–13 rehearsal):** Verified `third-party-licenses.mjs` (49 bundled client npm packages, zero copyleft/CC-BY packages), `recipe.yaml` YAML schema, `run_test.py` on an installed-layout prefix without `--root` or `EEG_COMPUTE_PYTHON` (verifying `default_repository_root()`, `<realpath(P)>/bin/python`, numerical-closure `environment:` rows, fixture `data install`/`verify`, and `design`/`export`), and end-to-end `data install --from` + `eeglayoutlab examples run` across all 3 examples (all 24 scores matching `expected.json` within `1e-6`, and run/study/SVG/montage outputs matching the Node runner byte-for-byte with worker timings masked).

**Remaining before conda-forge submission:**
- `cortech` submitted and merged on `conda-forge/staged-recipes` first (`U22`).
- Public repository switch (`U28`), release tarball URL + SHA-256 in `source`, and Zenodo data release (`U18`, `U20`).
- Linux verification on CI runners (`Slice 10` & `Slice 18`).
