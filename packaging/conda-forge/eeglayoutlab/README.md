# conda-forge recipe for eeglayoutlab (draft)

A rattler-build recipe (format v1) for the application installed from conda-forge (phase 3 of [design 0001](../../../docs/design/0001-local-first-architecture.md)). It installs the layout decided in [design 0002](../../../docs/design/0002-installed-scientific-root.md):

```text
$PREFIX/lib/python3.11/site-packages/eeglayoutlab/   the service, the command line, the data commands
$PREFIX/bin/eeglayoutlab                             the entry point
$PREFIX/share/eeglayoutlab/root/                     the scientific root R
  src/compact_eeg/  scripts/  configs/  examples/
  data/{manifest.json,SOURCES.md,README.md}
  webapp/public/  webapp/dist/client/                the interface, exported as static pages at build time
```

`compact_eeg` exists only in R, never in `site-packages`. Node is needed only to build the interface; it is not a run dependency. Model data is not in the package: `eeglayoutlab data install` puts packages in the user data directory, and `eeglayoutlab data compose` links them into R.

The recipe is not submitted. It builds the checkout it sits in (`source: path`); a submitted recipe takes the release tarball and its SHA-256.

| File | Purpose |
| --- | --- |
| `recipe.yaml` | Requirements, entry point and package tests |
| `build.sh` | Builds the interface, installs `eeglayoutlab` only, copies R |
| `run_test.py` | Package test: the R tree, no `compact_eeg` in `site-packages`, `PROJECT_ROOT == R`, the data commands without data |

## Building and installing locally

```bash
rattler-build build -r packaging/conda-forge/eeglayoutlab --output-dir OUT -c file://CORTECH_CHANNEL -c conda-forge
```

```bash
conda create -p ENV --override-channels -c file://OUT -c file://CORTECH_CHANNEL -c conda-forge eeglayoutlab
```

`EEGLAYOUTLAB_NPM_CACHE` points the build at an existing npm cache; empty, npm uses a cache in the work directory. `cortech 0.1` is not on conda-forge yet, so it comes from a local channel built from its own recipe.

## What was checked (2026-11-23, macOS arm64)

All in scratch directories: the environment, the data directory and the example outputs. Nothing global was changed.

| Check | Result |
| --- | --- |
| Build | rattler-build 0.81.0, nodejs 26.13.1 from conda-forge. `eeglayoutlab-0.2.0-pyh4616a5c_0.conda`, 62 MB. The package tests pass: imports, `pip check`, `run_test.py`, `eeglayoutlab --help`, `eeglayoutlab data --help` |
| Environment | 90 packages, 2.3 GB, Python 3.11.18. The pins resolve as written. BLAS is `libopenblas 0.3.34 openmp` with `llvm-openmp 23.1.6` |
| Tree | `src/compact_eeg`, `scripts`, `configs`, `examples` (without `outputs`), `webapp/public` and the three `data` files in R are byte-identical to the checkout. `site-packages/eeglayoutlab` is byte-identical to `src/eeglayoutlab`. `compact_eeg` is not importable from `site-packages`, and R holds no bytecode |
| Commands | `eeglayoutlab --help`, `eeglayoutlab data list` |
| Data | `data install --from-root` put `base-1.0.0` (406 MB, 21 files) and `scalp-node-table-1.0.0` (1.40 GB, 4 files) in a test data directory. `data compose --root R` placed 24 files as hard links and left `data/SOURCES.md`, already in R with the same bytes, as it was. A second compose placed nothing. The eleven head packages followed, with manifests built again by `data build` after the head rebuild; none of them records a home-directory path. They were installed in 8 s, and compose placed their 110 files (13.34 GB) as hard links. `data verify`: all 13 packages intact, in 6 s |
| Examples | `EEG_COMPUTE_PYTHON=ENV/bin/python node examples/run-examples.mjs --root R` passes, example 3 on all eleven heads (11 of 11 cases). All 24 scores equal `expected.json` exactly (largest difference 0.0). The run took 38.0 s, with a peak of 1.01 GiB for the whole process tree and 0.88 GiB for one process. Examples 1 and 2 alone, before the heads were installed: 13.3 s, 0.99 GiB |
| Service | `eeglayoutlab serve WORKSPACE --root R` serves the interface from `R/webapp/dist/client`: the page, its scripts and `models/ernie/source-roi.json` |

**Not checked:**
- **Linux.** The package is `noarch: python`, so the same file installs there, but it has not been built or installed on Linux.
- **FEM and reception v2.** SimNIBS is not in this environment, so no FEM solve ran and reception v2 is unavailable (0002, consequences).

## What design 0002 still needs in the code

The recipe changes no code. These changes from 0002's table are still needed before the installed form works without options:

1. **The default root.** `jobs/runtime.py` `default_repository_root()` returns `None` outside a checkout, so `serve`, `data compose` and the workers need `--root R` or `EEG_REPOSITORY_ROOT`. Fall back to `<sys.prefix>/share/eeglayoutlab/root` when it holds `src/compact_eeg` (0002, rule `repository_root()`).
2. **The default interpreter.** `runtime_config` picks `python || EEG_COMPUTE_PYTHON || managed || 'python3'`. In an environment that is not activated, `python3` from `PATH` is a different interpreter. The installed form must use `<sys.prefix>/bin/python` (0002, rule "worker interpreter"). The checks above set `EEG_COMPUTE_PYTHON` for this reason.
3. **Environment rows** in `jobs/identity.py` and `jobs/integrity.py` (0002, rule "environment rows"): `conda-meta/*.json`, the `METADATA` of cortech, llvmlite, nibabel, numba, numpy and scipy, and the interpreter, under `environment:` keys, with the real path of `sys.prefix` as their integrity base. Without them, the identity of the example records holds only `schema`, `digests`, `python` (the environment's interpreter path) and `threads`. On macOS it has no runtime fingerprint at all, so a numpy or scipy update in the environment keeps the keys and can return results computed with the old libraries.
4. **Refusing a read-only R** in `cli/main.py` (`serve`, `data compose`). A prefix the user cannot write is not supported (0002, decision 3); the commands should say so at start instead of failing on the first record they write.
5. **`eeglayoutlab examples run`** in `cli/` (phase 3, U5). The examples need Node and a checkout today: `examples/run-examples.mjs` calls `webapp/scripts/eeglayoutlab.mjs`, which is not in R. The checks above ran the checkout's runner against R.

The `--static` default already resolves to `R/webapp/dist/client`, so no change is needed there.

## Before a submission

- `cortech` on conda-forge first, as its own feedstock.
- A release tarball and its SHA-256 in `source`.
- The interface's bundled npm packages: their licences go in `license_file`, generated at build time. `THIRD_PARTY_NOTICES.md` does not list them yet.
- Python 3.12 and 3.13: the pin `<3.12` follows the Linux runtime lock. It is lifted when that lock moves (0001, decision 10).
