# Installation

Install EEGLayoutLab into a user-writable Conda or micromamba environment to run new regional layout searches, coordinate evaluations, robustness studies and reproducible exports locally without cloning the repository or installing Node.js.

[简体中文安装说明](installation.zh-CN.md) · [Source installation (for contributors & SimNIBS FEM)](source-installation.md)

> **Current distribution status:** Packaging recipes for `cortech` and `eeglayoutlab` live in [`packaging/conda-forge/`](../packaging/conda-forge/eeglayoutlab/README.md) and are rehearsed on Apple Silicon macOS and Linux x86_64. Until both feedstocks and the Zenodo data record are published on conda-forge, install from a locally built channel with `--from MIRROR` or follow the [source installation guide](source-installation.md).

## Supported platforms

| Platform | Architecture | Requirements |
| --- | --- | --- |
| **macOS** | Apple Silicon (`osx-arm64`, macOS 14+) | A user-writable Conda (`miniforge3`) or `micromamba` installation, ~3 GB for the environment + **1.80 GB** for the default model data |
| **Linux** | x86_64 (`linux-64`, glibc 2.28+, e.g. Ubuntu 24.04) | A user-writable Conda (`miniforge3`) or `micromamba` installation, ~3 GB for the environment + **1.80 GB** for the default model data |
| **Windows** | WSL2 (`linux-64`) | Install WSL2 (Ubuntu 24.04) and follow the Linux steps inside WSL2 (native Windows is not yet supported; WSL2 is not yet tested) |

Do **not** install into a read-only system or shared multi-user Conda prefix: `eeglayoutlab` stores computed scientific records inside the environment's scientific root (`$CONDA_PREFIX/share/eeglayoutlab/root/results/v2`) and refuses an unwritable root before starting (`exit 2`). Always create an environment in your own home directory.

## 1. Create the environment

```sh
conda create -n eeglayoutlab -c conda-forge eeglayoutlab
conda activate eeglayoutlab
```

The package bundles the pre-built web interface, the Python service (`eeglayoutlab serve`), all nine scientific CLI commands (`design`, `export`, `evaluate`, `search`, `study`, `pareto`, `eeg-summary`, `prior`, `channels`), the reproducible examples and the pinned numerical runtime (`Python 3.11`, `numpy`, `scipy`, `numba`, `llvmlite`, `nibabel`, `cortech`). Node.js and `npm` are not required.

## 2. Install and verify the model data

Fetch, verify (SHA-256) and link the default model data (`base` 0.41 GB + `scalp-node-table` 1.40 GB, **1.80 GB** total):

```sh
eeglayoutlab data install
eeglayoutlab data verify
```

- `base` supplies the Ernie meshes, frozen 10-05 forward bank, candidate geometry, display models and supplied library records.
- `scalp-node-table` supplies the nominal scalp-node superposition table so imported or custom 3D scalp coordinates can be evaluated without SimNIBS FEM.
- In an installed Conda environment, `eeglayoutlab data install` automatically composes read-only hard links into `$CONDA_PREFIX/share/eeglayoutlab/root` (`--no-compose` skips composition).
- Optional packages can be installed on demand ([data packages](data-packages.md)):
  - Cross-head study heads (Example 3, 11 heads, 13.34 GB): `eeglayoutlab data install --examples`
  - Skull-conductivity mismatch tables (1.40 GB each): `eeglayoutlab data install scalp-node-table-skull_x0.5 scalp-node-table-skull_x2`

## 3. Open the web application

Start the local service for a **workspace** directory of your choice (where your projects, robustness studies, electrode-name annotations and task queue are saved):

```sh
eeglayoutlab serve ~/eeglayoutlab-workspace
```

The service listens on `127.0.0.1` only, prints a single-user launch address (`127.0.0.1:<port>/open?token=…`), and opens your default browser automatically. Confirm that the top-right **Tasks / Queue** badge reads `0` (connected). Keep the terminal open while working and press **Control + C** to stop the service.

![Annotated Workspace home screen on first launch showing the five top-bar areas, connected task queue badge, language and theme switcher, and starting options](images/workspace-first-launch.svg)

## 4. Verify your installation with a first calculation

Run Examples 1 and 2 from any working directory (about 10–15 seconds on Apple Silicon or modern x86_64; needs only the default `base` package):

```sh
eeglayoutlab examples run --skip-cross-head
```

This builds the standard 64-electrode reference design from 10-05 labels, exports BIDS, MNE (`.elc`), EEGLAB (`.sfp`) and SVG files, runs a two-region 30 mm layout search and independent coordinate evaluation, writes the outputs to `./eeglayoutlab-examples/`, and verifies every score against [`examples/expected.json`](../examples/expected.json) within `1e-6`. Once `--examples` head packages are installed, omit `--skip-cross-head` to run the 11-head cross-subject study (Example 3) as well.

## What works in the Conda package vs source installation

| Capability | Conda package (`osx-arm64` & `linux-64`) | Source installation with SimNIBS (`osx-arm64`) |
| --- | --- | --- |
| Regional radius search (`search`), Pareto ranking (`pareto`) & electrode editor | Included (with `base`) | Included |
| Evaluating imported / arbitrary scalp coordinates (`evaluate`, perturbations, robustness) | Included (via `scalp-node-table`, no FEM solve needed) | Included (via table or direct SimNIBS FEM) |
| Skull-conductivity scenarios & cross-head studies (`study`) | Included when the corresponding scenario or head packages are installed | Included |
| Recorded EEG summaries (`eeg-summary`), empirical priors (`prior`) & channel subsets (`channels`) | Included | Included |
| Signal simulation v1 (`source-reception/1`) & opening saved v2 records / project deliveries | Included | Included |
| **New signal simulation v2 (`source-reception/2`) calculations** | **Not available** (requires SimNIBS; stored v2 records remain viewable) | Included |
| Direct per-request FEM without a table, or building new head packages (`charm`) | **Not available** | Included ([source installation](source-installation.md)) |

## Where files live and removing an environment

EEGLayoutLab separates three locations ([design 0002](design/0002-installed-scientific-root.md)):

1. **Workspace (`~/eeglayoutlab-workspace`)**: your research projects (`projects/`), robustness studies (`studies/`), electrode-name annotations (`annotations/`) and task history. Safe across upgrades and environment recreation.
2. **User data store** (`~/Library/Application Support/EEGLayoutLab` on macOS, `~/.local/share/eeglayoutlab` on Linux, or `EEGLAYOUTLAB_DATA_DIR`): downloaded model packages (`packages/`). Kept when a Conda environment is removed so a new environment can run `eeglayoutlab data compose` without re-downloading.
3. **Environment scientific root (`$CONDA_PREFIX/share/eeglayoutlab/root`)**: code, static interface and shared calculation caches (`results/v2/*_jobs`). **Running `conda env remove -n eeglayoutlab` deletes all calculation caches stored in that environment.** Export [project delivery packages](../contracts/project-formats.md) from **Research Projects** beforehand for any results you wish to archive permanently.
