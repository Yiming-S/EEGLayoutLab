# EEG Layout Lab

EEG Layout Lab is a community-oriented research software project for designing, viewing, and comparing EEG electrode layouts. It includes an interactive 3D head view, layout design, electrode editing, layout comparison, and signal simulation.

[简体中文安装与使用](docs/getting-started.zh-CN.md)

## Requirements

- An Apple Silicon Mac running macOS **14 or newer**.
- Node.js **22.13.0 or newer**, with npm.
- Python **3.10 or newer**.
- An Apple Silicon Conda installation with the `conda` command available in Terminal.
- Git and Apple's Command Line Tools.
- An internet connection for installing dependencies.

Use the native Apple Silicon versions of these tools, without Rosetta.

## First-time setup

### 1. Clone the repository

Open Terminal and run:

```sh
git clone https://github.com/Yiming-S/EEGLayoutLab.git
cd EEGLayoutLab
```

Keep this Terminal window open for the following steps.

### 2. Install the model data

Obtain the matching `eeglayoutlab-data-v1.tar.gz` archive from the project maintainer. The model data is supplied separately from the Git repository.

Create a folder for the archive:

```sh
mkdir -p releases
```

Place the archive in that folder, then run from the repository root:

```sh
python3 scripts/data_bundle.py install releases/eeglayoutlab-data-v1.tar.gz
python3 scripts/data_bundle.py verify
```

If the archive is stored elsewhere, replace its path in the install command.

### 3. Install the Python computation environment

From the repository root, run:

```sh
python3 scripts/bootstrap_runtime.py --execute
```

Wait for installation and the environment check to finish successfully before continuing. The App selects this environment automatically; no manual Conda activation is needed.

### 4. Install the web dependencies and open the App

```sh
cd webapp
npm ci
npm run dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000) in your browser. Keep Terminal running while using the App. Press **Control + C** in Terminal to stop it.

## Open the App after installation

From the folder containing your checkout, run:

```sh
cd EEGLayoutLab/webapp
npm run dev
```

Then open [http://127.0.0.1:3000](http://127.0.0.1:3000). You do not need to reinstall the data or dependencies each time.

## How to use

1. **Results Library → Experiment Overview / Layout Records:** select a saved layout and inspect its regions, electrode positions, and scores.
2. **Layout Design → Region Design:** choose the region count, allowed placement range, and maximum region radius, then start a calculation.
3. **Layout Design → Electrode Editor:** open a saved layout, adjust electrode positions or active electrodes, and recalculate. Use **Coordinate Import** to evaluate coordinates registered to the Ernie head model.
4. **Results Library → Compare Layouts:** compare selected layouts and export coordinates or reports.
5. **Signal Simulation:** select a layout, then choose source locations, waveforms, and interference settings to compare received signals.
6. **Documentation → User Guide / Models & Methods:** find instructions and explanations of the displayed metrics.

Use the language control in the upper-right corner to switch between English and Simplified Chinese. **Minimum Required Retention** changes which existing scores meet your requirement; changing it does not start a new calculation. New calculation results are saved locally and can be reopened in the Results Library.

## Copyright and third-party material

© 2026 Yiming Shen.

EEG Layout Lab supports EEG research, education, and scientific collaboration.

A general license for the original project code has not been selected. Third-party components retain their own terms, including SimNIBS GPL-3.0-only and the Ernie example data's CC BY-NC 4.0 terms. Attribution, source links, and modification descriptions are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
