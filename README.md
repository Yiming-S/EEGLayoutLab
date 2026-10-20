# EEGLayoutLab

EEGLayoutLab is open-source research software for designing and comparing EEG electrode layouts. It brings together an interactive 3D head model, layout design, electrode editing, signal simulation, and reproducible result exports.

EEGLayoutLab is developed on a non-profit basis and provided free of charge. Its original source code and accompanying documentation are licensed under GPL-3.0-only.

[Download v0.1.2](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.1.2) · [简体中文指南](docs/getting-started.zh-CN.md) · [Mac installation](desktop/START_HERE.md) · [Source setup](docs/source-installation.md) · [Server deployment](docs/server-deployment.md)

## Project collaborators

- **[Yiming Shen, PhD](https://yimings.com.cn/)**
- **[Yi Wang, PhD](https://www.massey.ac.nz/massey/expertise/profile.cfm?stref=469822)** — Massey University, New Zealand.

## Available versions

| Version | Status | Instructions |
| --- | --- | --- |
| Mac desktop | **0.1.2, build 1**; Apple Silicon, macOS 14 or newer. Calculations run on the Mac. | [Install and open](#install-and-open-on-mac) |
| Local web application | Run the current source in a browser with a local Node service and Python/SimNIBS workers. The managed runtime targets Apple Silicon macOS. | [Source installation](docs/source-installation.md) |
| Hosted web application | Planned for Dr. Wang's server, including online calculation and persistent results. | [Deployment preparation](docs/server-deployment.md) |

The Mac installer includes Node.js, the scientific runtime, model data, and selected supplied results. Download it from [GitHub Releases](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.1.2). The repository is private: sign in to a GitHub account with repository access to view or download release files. The hosted version's address will be added after deployment.

## Downloads

| File | Size | Use |
| --- | --- | --- |
| [Mac DMG](https://github.com/Yiming-S/EEGLayoutLab/releases/download/v0.1.2/EEGLayoutLab-0.1.2-macOS-arm64.dmg) | See release asset | Recommended installer for Apple Silicon Macs |
| [Mac ZIP](https://github.com/Yiming-S/EEGLayoutLab/releases/download/v0.1.2/EEGLayoutLab-0.1.2-macOS-arm64.zip) | See release asset | Alternative archive containing the same application |
| [Base data bundle](https://github.com/Yiming-S/EEGLayoutLab/releases/download/v0.1.2/eeglayoutlab-data-v1.tar.gz) | 282.5 MiB | Required for a fresh source installation; already included in the Mac application |
| [SHA-256 checksums](https://github.com/Yiming-S/EEGLayoutLab/releases/download/v0.1.2/SHA256SUMS.txt) | Text | Verify downloaded release files |

Download one Mac installer format. Source users need the code and matching base data bundle. The release includes selected frozen application inputs and example results; the full historical calculation cache is excluded.

## How to use

1. **Browse:** open an existing layout in **Results Library** and inspect its regions, electrode positions, and scores.
2. **Design:** set the region count, allowed placement range, and maximum region radius in **Layout Design**.
3. **Edit or import:** change electrode positions or active electrodes, or import coordinates registered to the Ernie head model.
4. **Compare:** assess selected layouts under the same requirements and export coordinates, results, or reproducibility bundles.
5. **Simulate:** select a layout, source locations, waveforms, and interference settings in **Signal Simulation**.

Use the upper-right language control to switch between English and Simplified Chinese. **Minimum Required Retention** changes how existing scores are judged; it does not start a new calculation.

The current model uses the SimNIBS example subject Ernie. Scores depend on the recorded head model, source assumptions, noise model, and evaluation protocol. Read [Model and metrics](docs/model-and-metrics.md) for definitions and interpretation.

## Install and open on Mac

1. Download **[`EEGLayoutLab-0.1.2-macOS-arm64.dmg`](https://github.com/Yiming-S/EEGLayoutLab/releases/download/v0.1.2/EEGLayoutLab-0.1.2-macOS-arm64.dmg)** and open it.
2. Drag **EEG Layout Lab.app** into **Applications**.
3. Launch the App and wait for the included environment and model data to be prepared.

No separate Python, Node.js, Conda, or model-data installation is required. Included calculations run offline and save results on your Mac. Quit with **Command + Q**.

This build uses an ad-hoc signature and has not been Apple-notarized. Follow the first-open instructions below if macOS asks you to approve the application.

[Installation and first-open instructions](desktop/START_HERE.md) · [简体中文安装指南](desktop/START_HERE.zh-CN.md)

## Work with the source code

Follow the [source installation instructions](docs/source-installation.md) to install the data bundle, prepare the scientific runtime, and start the local application. The current managed runtime targets **Apple Silicon macOS**. The Python project uses **Python 3.11**; the web application requires **Node.js 22.13.0 or newer**.

Download the matching scientific data archive from [release v0.1.2](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.1.2). It contains 21 files (406,226,293 uncompressed bytes), identified in [`data/manifest.json`](data/manifest.json). The source installation guide includes authenticated download, checksum, and import commands. See [Data and reproducibility](docs/data-and-reproducibility.md) for the exact data boundary.

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

Git tracks application source, required display assets, configuration, documentation, and tests. Releases provide installers, the base data bundle, checksums, and component notices. Installed environments, generated computation records, demo recordings, and local verification captures stay outside Git; historical calculation caches are not uploaded.

Read [Architecture](docs/architecture.md), [Validation](docs/validation.md), [Web verification](docs/verification.md), and [Mac verification](desktop/VERIFICATION.md) for implementation and test details.

## Copyright and third-party material

© 2026 Yiming Shen & Yi Wang.

The project's original source code and accompanying documentation are licensed under the [GNU General Public License version 3 only (GPL-3.0-only)](LICENSE). This permits commercial use; distribution of modified versions must follow the GPL, including its corresponding-source requirements.

Third-party software and data retain their own licenses. SimNIBS uses GPL-3.0-only; Ernie data and its derived scientific and display assets remain under CC BY-NC 4.0. Attribution, source links, and modification descriptions are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
