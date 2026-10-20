# EEG Layout Lab

EEG Layout Lab is research software for designing, viewing, and comparing EEG electrode layouts. It combines an interactive 3D head model, region-based layout design, electrode editing, layout comparison, and signal simulation.

[简体中文介绍与使用指南](docs/getting-started.zh-CN.md) · [Source installation](docs/source-installation.md) · [Server deployment preparation](docs/server-deployment.md)

## Project collaborators

- **[Yiming Shen, PhD]**(https://yimings.com.cn/)
- **[Yi Wang, PhD](https://www.massey.ac.nz/massey/expertise/profile.cfm?stref=469822)** — Senior Lecturer in Computer Science, School of Mathematical and Computational Sciences, Massey University, New Zealand.

The collaborators are preparing a full-feature web version for a server set up by Yi Wang. The intended deployment supports browsing existing results and running new calculations online.

## Ways to run

| Option | Current status | Start here |
| --- | --- | --- |
| Mac desktop App | Version 0.1.1 for Apple Silicon, macOS 14 or newer; computation runs on your Mac. | [Installation guide](desktop/START_HERE.md) · [Existing download folder](https://drive.google.com/drive/folders/1Ry-neU-oySVoToIt07eFfBnemKrnewmK?usp=sharing) |
| Local source checkout | Current application source; the documented setup uses Apple Silicon macOS and a separate verified data bundle. | [Source installation](docs/source-installation.md) |
| Hosted web version | Planned deployment with server-side computation and persistent results. The public URL will be added after deployment. | [Server deployment preparation](docs/server-deployment.md) |

Desktop version **0.1.1 (build 2)** packages the updated web source, including the [anonymous visitor queue](docs/anonymous-queue.md). The rebuilt installer is prepared locally; upload it to the shared download folder before distributing that link as the updated version. Build and test details are recorded in the [desktop verification report](desktop/VERIFICATION.md).

## How to use

1. **Results Library → Experiment Overview / Layout Records:** open an existing layout and inspect its regions, electrode positions, and scores.
2. **Layout Design → Region Design:** choose the region count, allowed placement range, and maximum region radius, then start a calculation.
3. **Layout Design → Electrode Editor:** adjust positions or active electrodes and recalculate. **Coordinate Import** accepts coordinates already registered to the Ernie head model.
4. **Results Library → Compare Layouts:** compare selected layouts and export coordinates or reports.
5. **Signal Simulation:** choose a layout, source locations, waveforms, and interference settings to compare received signals.
6. **Documentation → User Guide / Models & Methods:** read the workflow instructions and metric definitions.

Use the upper-right language control to switch between English and Simplified Chinese. **Minimum Required Retention** changes how existing scores are judged; it does not start a new calculation.

The current scientific model uses the SimNIBS example subject Ernie. Layout scores depend on the recorded head model, source assumptions, noise model, and evaluation protocol. See [Model and metrics](docs/model-and-metrics.md) for definitions and interpretation.

## Install and open on Mac

Use an **Apple Silicon Mac with macOS 14 or newer**. The desktop installer includes the interface, computation environment, model data, and supplied results.

1. Download the **`.dmg` installer** from the [download folder](https://drive.google.com/drive/folders/1Ry-neU-oySVoToIt07eFfBnemKrnewmK?usp=sharing).
2. Open it and drag **EEG Layout Lab.app** into **Applications**.
3. Launch the App and wait for its included environment and model data to be prepared.

**No separate Python, Node.js, Conda, or model-data installation is required.** Included simulations run locally, without an internet connection. New results are saved on your Mac. Quit with **Command + Q**.

[Installation and first-open instructions](desktop/START_HERE.md) · [简体中文安装指南](desktop/START_HERE.zh-CN.md)

## Work with the source code

Follow the [source installation instructions](docs/source-installation.md) to install the data bundle, prepare the scientific runtime, and start the local application. The current managed runtime targets **Apple Silicon macOS**. The Python project uses **Python 3.11**; the web application requires **Node.js 22.13.0 or newer**.

For development boundaries and verification commands, read [CONTRIBUTING.md](CONTRIBUTING.md). The code, numerical inputs, installed environment, and accumulated result caches are separate parts of a working installation.

## Planned server deployment

The deployment target is the complete application: browser interface, Node HTTP service, Python/SimNIBS computation, a shared task queue, and persistent data and results.

The current host binds to `127.0.0.1` and validates local hosts and origins. Public hosting requires explicit HTTPS and trusted-proxy configuration, a runtime supported on the target server, and a decision about who can submit computations and view results.

The [server deployment preparation guide](docs/server-deployment.md) records the proposed architecture, handoff materials, remaining implementation work, and acceptance checks.

## Documentation and repository map

| Topic | Location |
| --- | --- |
| Mac installation | [English](desktop/START_HERE.md) · [简体中文](desktop/START_HERE.zh-CN.md) |
| Source installation | [English](docs/source-installation.md) · [简体中文](docs/source-installation.zh-CN.md) |
| Server deployment preparation | [Deployment guide](docs/server-deployment.md) |
| Development and verification | [Contributing](CONTRIBUTING.md) · [Recorded verification](docs/verification.md) |
| Application structure | [Architecture](docs/architecture.md) · [`webapp/`](webapp/) · [`src/compact_eeg/`](src/compact_eeg/) |
| Scientific definitions | [Model and metrics](docs/model-and-metrics.md) · [Validation](docs/validation.md) |
| Data, provenance, and cache identity | [Data and reproducibility](docs/data-and-reproducibility.md) · [Data inventory](data/manifest.json) |
| Queue and deployment boundaries | [Anonymous visitors and scheduling](docs/anonymous-queue.md) · [Local execution and dependency status](docs/security.md) |
| Third-party attribution | [Third-party notices](THIRD_PARTY_NOTICES.md) · [Data sources](data/SOURCES.md) |

## Copyright and third-party material

© 2026 Yiming Shen.

EEG Layout Lab supports EEG research, education, and scientific collaboration.

A general license for the original project code has not been selected. Third-party components retain their own terms, including SimNIBS GPL-3.0-only and the Ernie example data's CC BY-NC 4.0 terms. Attribution, source links, and modification descriptions are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
