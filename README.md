# EEGLayoutLab

EEGLayoutLab is an open-source web application for designing and comparing EEG electrode layouts. It brings together an interactive 3D head model, layout design, electrode editing, signal simulation, and reproducible result exports.

EEGLayoutLab is developed on a non-profit basis and provided free of charge. Its original source code and accompanying documentation are licensed under GPL-3.0-only.

[简体中文指南](docs/getting-started.zh-CN.md) · [Run locally](docs/source-installation.md) · [Model and metrics](docs/model-and-metrics.md) · [Architecture](docs/architecture.md) · [Operations](docs/web-operations.md)

## Features

- **Explore layouts:** inspect electrode positions, placement regions and evaluation scores on an interactive 3D head model.
- **Design and edit:** calculate regional layouts, modify electrode coordinates or active contacts, and evaluate imported coordinates registered to the Ernie head model. Preserve electrode names and inspect each input point, evaluated point and projection distance.
- **Compare layouts:** select a reference and candidate, set shared or independent retention requirements, and compare the recorded metrics.
- **Simulate signals:** choose source locations, waveforms and interference conditions; inspect the resulting signals, switch channels and replay the saved experiment.
- **Keep research projects:** save complete layout, editing and signal snapshots with notes and comparison settings; inspect signal experiments by their parent layout, restore access in another browser and create revocable read-only shares.
- **Repeat evaluations:** run explicit localization-noise seed or candidate-grid displacement studies, preserve every case outcome, and inspect case-level empirical summaries. The [study protocol](docs/robustness-studies.md) records how these batches reuse the original calculations.
- **Export and review:** download coordinates, original scientific JSON, reports and project delivery packages with checksums and recorded model/runtime identities. Open a local delivery package to inspect its archived coordinates, scores and waveforms without project credentials.

The interface supports English and Simplified Chinese. Its Node service runs Python/SimNIBS workers, reuses exact completed results and keeps a persistent computation queue. Shared viewer resources, compressed model downloads and validated forward-field reuse reduce repeated loading and calculation.

## Run locally

Follow the [source installation guide](docs/source-installation.md) to install the matching model data and prepare the scientific runtime. The Python project uses **Python 3.11**; the web application requires **Node.js 22.13.0 or newer**. The supplied managed scientific runtime targets **Apple Silicon macOS**.

After preparing the data and runtime, build and start the application:

```sh
cd webapp
npm ci
npm run build
npm start
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000) and keep the terminal running. For development, use `npm run dev` instead of the build and start commands.

## Model data

A fresh source installation needs the code and the matching base data bundle. The bundle contains selected frozen application inputs and example results; the full historical calculation cache is excluded.

| File | Size | Use |
| --- | --- | --- |
| [Base data bundle](https://github.com/Yiming-S/EEGLayoutLab/releases/download/v0.1.2/eeglayoutlab-data-v1.tar.gz) | 282.5 MiB | Model inputs and supplied records for the web application |
| [Bundle SHA-256 checksum](https://github.com/Yiming-S/EEGLayoutLab/releases/download/v0.1.2/eeglayoutlab-data-v1.tar.gz.sha256) | Text | Verify the data archive before installation |

The repository is private: sign in to a GitHub account with repository access to view or download release files. Follow the [source installation guide](docs/source-installation.md) to verify and install the data, prepare the scientific runtime, and start the browser interface.

## How to use

1. **Browse:** open an existing layout in **Results Library** and inspect its regions, electrode positions, and scores.
2. **Design:** set the region count, allowed placement range, and maximum region radius in **Layout Design**.
3. **Edit or import:** change electrode positions or active electrodes, or import named coordinates registered to the Ernie head model. The [coordinate-file interface](docs/coordinate-file-interface.md) also supports explicitly declared electrodes.tsv and coordsystem.json pairs with region metadata.
4. **Compare:** assess selected layouts under the same requirements and export coordinates, results, or reproducibility bundles.
5. **Simulate:** select a layout, source locations, waveforms, and interference settings in **Signal Simulation**.
6. **Repeat:** create a robustness study from imported coordinates, list explicit seed/radius cases, save a draft and start the batch. Opening or refreshing a study reads its saved state; service restart requires an explicit study resume.

Use **Research Projects** to keep selected layouts, edited copies, signal experiments, notes and comparison requirements together. Download the project's access file to restore it in another browser; use a separate read-only link for collaborators. Generating a new read-only link replaces the previous one. Saved project snapshots remain available independently of the computation queue. Project access protects the project's annotations and saved copies; the existing original layout library remains shared.

The project delivery download includes exact archived scientific JSON files, checksums, a readable report, saved comparison settings and recorded model/runtime identities. Large model payloads are referenced by their manifests. Project access credentials are downloaded separately and are excluded from scientific deliveries. Choose **Open a local delivery package** in Research Projects, or visit `/deliveries`, to read the saved package in a browser. The original project and task APIs are not required; application and display assets must remain accessible.

Use the upper-right language control to switch between English and Simplified Chinese. **Minimum Required Retention** changes how existing scores are judged; it does not start a new calculation.

The current model uses the SimNIBS example subject Ernie. Scores depend on the recorded head model, source assumptions, noise model, and evaluation protocol. Read [Model and metrics](docs/model-and-metrics.md) for definitions and interpretation.

## Verification

Local verification covers coordinate-name round trips, per-electrode review, project experiment associations, read-only sharing, local delivery viewing, scientific regression, repeated studies, task reconciliation and backup/restore. Unit tests, type checks, lint, production builds and real-browser workflows are run for each stage.

A fresh native FEM run reproduced the qualified `128 × 4352` forward field and projected coordinates exactly. Single-source and multi-source arrays, scientific outputs and non-timing numerical quality fields matched the saved baseline. The 95 recorded scientific source, configuration, model and input files remained unchanged. Eight batch cases were also recomputed independently through the original single-case entry point, with exact scientific values and provenance; the new case-level quantiles were checked independently with NumPy.

The [research workflow verification record](docs/research-workflow-progress.zh-CN.md) contains stage-specific checks and results. [CONTRIBUTING.md](CONTRIBUTING.md) explains test selection and external-data requirements; the [native release gate](docs/native-release-gate.md) documents the separate new-solve check. Stopped-service task recovery is documented in [task reconciliation](docs/task-reconciliation.md).

## Deployment and operations

The application includes explicit scientific and queue-directory configuration, HTTPS reverse-proxy access rules, request identifiers, bounded request logs, local status probes, disk and optional Node-memory admission checks, and maintenance/drain controls. Release manifests record source, data and runtime identities; backup and restore tools preserve scientific records and private project and study archives.

See [server configuration](docs/server-deployment.md) and [web operations](docs/web-operations.md) for installation requirements, environment examples, monitoring and recovery procedures. The [architecture](docs/architecture.md) documents feature, viewer, task, execution and storage modules.

## Repository structure

| Directory | Contents |
| --- | --- |
| [`contracts/`](contracts/) | Shared layout types, API format documentation and cross-language examples |
| [`webapp/`](webapp/) | Feature workspaces, shared task client, modular viewer, HTTP host and workers |
| [`src/compact_eeg/`](src/compact_eeg/) | Scientific methods and computation workflows |
| [`configs/`](configs/) | Scientific configuration, runtime locks and deployment environment template |
| [`scripts/`](scripts/) | Setup, data management, and worker entry points |
| [`tests/`](tests/) | Scientific and workflow regression tests |
| [`docs/`](docs/) | Architecture, methods, data, validation, and deployment documentation |
| [`data/`](data/) | Data inventory and source attribution |

Git tracks application source, required display assets, configuration, documentation, and tests. Releases provide versioned source and data materials, checksums, and component notices. Installed environments, generated computation records, demo recordings, and local verification captures stay outside Git; historical calculation caches are not uploaded.

## Copyright and third-party material

The project's original source code and accompanying documentation are licensed under the [GNU General Public License version 3 only (GPL-3.0-only)](LICENSE). This permits commercial use; distribution of modified versions must follow the GPL, including its corresponding-source requirements.

Third-party software and data retain their own licenses. SimNIBS uses GPL-3.0-only; Ernie data and its derived scientific and display assets remain under CC BY-NC 4.0. Attribution, source links, and modification descriptions are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
