# EEG Layout Lab

EEG Layout Lab is a local application for designing, inspecting, and comparing EEG sensor layouts under a fixed head model. It combines a 3D anatomy viewer, constrained layout search, electrode editing, coordinate evaluation, and source-to-sensor signal simulation.

The application compares layouts with a standard BioSemi64 reference using signal reconstruction, lower-tail amplitude retention, and localization metrics. Its scores describe the specified simulation model. The [model and metrics](docs/model-and-metrics.md) document defines each quantity and its interpretation.

[简体中文快速开始](docs/getting-started.zh-CN.md)

## Scope

- Browse the supplied layout records and their coordinates, parameters, and provenance.
- Design 64-sensor layouts in 1, 2, 3, 4, or 6 scalp regions.
- Edit active sensor positions and evaluate a fixed layout.
- Import coordinates already registered to the Ernie subject coordinate system.
- Compare layouts and export coordinates and reports.
- Simulate reception from selected cortical sources with declared noise and interference settings.

This is a source-based collaboration release for macOS on Apple Silicon. It runs in a browser through a local Node host. No desktop `.app` or DMG is included, and installation on a second independent Mac has not yet been validated.

Use it as a local application, not a public server. The locked frontend currently has unresolved dependency audit findings; see [local execution and dependency status](docs/security.md).

## Requirements

- Node.js **22.13.0 or newer**, with npm.
- Python **3.10 or newer** to run the setup and data tools.
- macOS **14 or newer** on native Apple Silicon, as required by the pinned native dependency wheels; do not run the installer under Rosetta.
- A working `conda` executable to create the separate native Python environment.
- Git and Apple's command-line build tools for the pinned source dependencies.
- The matching `eeglayoutlab-data-v1.tar.gz` data archive, provided with the handoff or separately by the maintainer.

The full computation environment uses Python 3.11 and SimNIBS 4.6.0. The setup tool reconstructs it under `.runtime/simnibs-4.6.0`; the repository does not contain a copied machine-specific Python installation. Network access is needed for dependency installation. The data tool itself works with a local archive and does not download data.

## Set up

Run the following from the repository root. If the data archive is stored elsewhere, replace only its argument with the actual file location.

```sh
python3 scripts/data_bundle.py install releases/eeglayoutlab-data-v1.tar.gz
python3 scripts/data_bundle.py verify
python3 scripts/bootstrap_runtime.py
python3 scripts/bootstrap_runtime.py --execute
.runtime/simnibs-4.6.0/bin/python scripts/check_environment.py
.runtime/simnibs-4.6.0/bin/python scripts/check_environment.py --native
```

The first bootstrap command displays its plan. `--execute` creates a new environment and refuses to overwrite an existing one. A managed installation interrupted before completion can be continued with `--execute --resume`; this only accepts the same saved installation identity. Use `python3 scripts/bootstrap_runtime.py --help` for a nondefault conda executable or an existing directory of installation assets. An environment check is a prerequisite check, not a new FEM simulation or a scientific validation.

Install the web dependencies and start the application:

```sh
cd webapp
npm ci
npm run dev
```

The Node host automatically selects `.runtime/simnibs-4.6.0/bin/python` from this checkout when that runtime is installed. Open [http://127.0.0.1:3000](http://127.0.0.1:3000). Keep the terminal running while using the application. New computations save their records inside this checkout.

To run the built local application, use the same `webapp` directory:

```sh
npm run build
npm start
```

Both supported hosts serve the browser interface and the same-origin computation APIs. The standard setup uses loopback access on the local computer.

## First use

The home page shows the supplied fixed-area results. Select a record to inspect its region geometry, metrics, coordinates, and provenance. Use **Layout design** to create a radius-constrained design, and explicitly start computation when a matching result is unavailable. The acceptance threshold only changes the interpretation of existing scores.

Use **Electrode editor** for a saved parent layout, **Coordinate import** for pre-registered Ernie coordinates, **Comparison** for paired reports, and **Signal simulation** for a fixed-layout source scenario. The in-application guide and modeling pages explain the controls and numerical definitions.

## Data and scientific boundaries

The code repository contains display assets and a versioned data manifest. The separate archive contains the frozen numerical inputs and selected result records needed by the application. It excludes the full offline research archive. See [data and reproducibility](docs/data-and-reproducibility.md) for verification, installation, and export commands.

The current 30 fixed-area conditions use the production 4,096-source dictionary and 256 generation sources. Separate evaluations using 512 new sources do not replace those default scores. Volume-mesh convergence and independent-head validation remain incomplete. The supplied evidence does not establish human EEG performance, MI/P300 classification accuracy, or continuous/global layout optimality. See [validation scope](docs/validation.md).

## Development

[Architecture](docs/architecture.md) describes the browser, Node, and Python boundaries. [Contributing](CONTRIBUTING.md) lists the checks and rules for modifying code, scientific identities, and data. The native runtime, installed numerical data, caches, and generated artifacts are not source-code dependencies to commit.

The [recorded checkout verification](docs/verification.md) covers the independently rebuilt runtime, supplied data, software checks and local calculation paths tested for this handoff.

## Copyright and third-party material

© 2026 Yiming Shen.

EEG Layout Lab is a community-oriented research software project supporting EEG research, education, and scientific collaboration.

A general license for the original project code has not been selected. Third-party components retain their own terms, including SimNIBS GPL-3.0-only and the Ernie example data's CC BY-NC 4.0 terms. Attribution, source links, and modification descriptions are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
