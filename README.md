# EEGLayoutLab

EEGLayoutLab is research software for designing and comparing EEG electrode layouts. It brings together an interactive 3D head model, layout design, electrode editing, signal simulation, and reproducible result exports.

[简体中文指南](docs/getting-started.zh-CN.md) · [Mac installation](desktop/START_HERE.md) · [Source setup](docs/source-installation.md) · [Server deployment](docs/server-deployment.md)

## Project collaborators

- **[Yiming Shen, PhD](https://yimings.com.cn/)**
- **[Yi Wang, PhD](https://www.massey.ac.nz/massey/expertise/profile.cfm?stref=469822)** — Massey University, New Zealand.

## Available versions

| Version | Status | Instructions |
| --- | --- | --- |
| Mac desktop | **0.1.1, build 2**; Apple Silicon, macOS 14 or newer. Calculations run on the Mac. | [Install and open](#install-and-open-on-mac) |
| Local web application | Run the current source in a browser with a local Node service and Python/SimNIBS workers. The managed runtime targets Apple Silicon macOS. | [Source installation](docs/source-installation.md) |
| Hosted web application | Planned for Yi Wang's server, including online calculation and persistent results. | [Deployment preparation](docs/server-deployment.md) |

The Mac installer includes Node.js, the scientific runtime, model data, and supplied results. Obtain version 0.1.1 from the project collaborators; publication of the rebuilt installer to the shared download folder is pending. The hosted version's address will be added after deployment.

## How to use

1. **Browse:** open an existing layout in **Results Library** and inspect its regions, electrode positions, and scores.
2. **Design:** set the region count, allowed placement range, and maximum region radius in **Layout Design**.
3. **Edit or import:** change electrode positions or active electrodes, or import coordinates registered to the Ernie head model.
4. **Compare:** assess selected layouts under the same requirements and export coordinates, results, or reproducibility bundles.
5. **Simulate:** select a layout, source locations, waveforms, and interference settings in **Signal Simulation**.

Use the upper-right language control to switch between English and Simplified Chinese. **Minimum Required Retention** changes how existing scores are judged; it does not start a new calculation.

The current model uses the SimNIBS example subject Ernie. Scores depend on the recorded head model, source assumptions, noise model, and evaluation protocol. Read [Model and metrics](docs/model-and-metrics.md) for definitions and interpretation.

## Install and open on Mac

1. Obtain **`EEGLayoutLab-0.1.1-macOS-arm64.dmg`** and open it.
2. Drag **EEG Layout Lab.app** into **Applications**.
3. Launch the App and wait for the included environment and model data to be prepared.

No separate Python, Node.js, Conda, or model-data installation is required. Included calculations run offline and save results on your Mac. Quit with **Command + Q**.

[Installation and first-open instructions](desktop/START_HERE.md) · [简体中文安装指南](desktop/START_HERE.zh-CN.md)

## Work with the source code

Follow the [source installation instructions](docs/source-installation.md) to install the data bundle, prepare the scientific runtime, and start the local application. The current managed runtime targets **Apple Silicon macOS**. The Python project uses **Python 3.11**; the web application requires **Node.js 22.13.0 or newer**.

The matching scientific data archive is supplied separately from Git. Its exact inventory is recorded in [`data/manifest.json`](data/manifest.json). Setup and verification are described in [Data and reproducibility](docs/data-and-reproducibility.md).

For development conventions and checks, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Repository structure

| Directory | Contents |
| --- | --- |
| [`webapp/`](webapp/) | Browser interface, HTTP services, display assets, and web checks |
| [`src/compact_eeg/`](src/compact_eeg/) | Scientific methods and computation workflows |
| [`desktop/`](desktop/) | Mac application, packaging tools, and installation guides |
| [`configs/`](configs/) | Scientific configuration and managed-runtime specifications |
| [`scripts/`](scripts/) | Setup, data management, and worker entry points |
| [`tests/`](tests/) | Scientific and desktop regression tests |
| [`docs/`](docs/) | Architecture, methods, data, validation, and deployment documentation |
| [`data/`](data/) | Data inventory and source attribution |

Git tracks application source, required display assets, configuration, documentation, and tests. Installed environments, computation records, installers, demo recordings, and local verification captures are kept outside version control.

Read [Architecture](docs/architecture.md), [Validation](docs/validation.md), [Web verification](docs/verification.md), and [Mac verification](desktop/VERIFICATION.md) for implementation and test details.

## Copyright and third-party material

© 2026 Yiming Shen.

A general license for the original project code has not been selected. Third-party components retain their own terms, including SimNIBS GPL-3.0-only and the Ernie example data's CC BY-NC 4.0 terms. Attribution, source links, and modification descriptions are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
