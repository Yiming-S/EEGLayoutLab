# EEG Layout Lab

**[Download for macOS — Apple Silicon](https://drive.google.com/drive/folders/1Ry-neU-oySVoToIt07eFfBnemKrnewmK?usp=sharing)**

For Apple Silicon Macs running **macOS 14 or later**. Download the `.dmg` installer, open it, and drag **EEG Layout Lab** into **Applications**. Then launch the App; the first launch prepares its included environment and model data.

**No separate Python, Node.js, Conda, or model-data installation is required.**

[Installation guide and first-open instructions](desktop/START_HERE.md) · [简体中文安装指南](desktop/START_HERE.zh-CN.md)

EEG Layout Lab is a community-oriented research software project for designing, viewing, and comparing EEG electrode layouts. It includes an interactive 3D head view, layout design, electrode editing, layout comparison, and signal simulation.

[简体中文安装与使用](docs/getting-started.zh-CN.md)

## Install and open on Mac

Use an **Apple Silicon Mac with macOS 14 or newer**.

1. Open the [Google Drive download folder](https://drive.google.com/drive/folders/1Ry-neU-oySVoToIt07eFfBnemKrnewmK?usp=sharing) and download the **`.dmg` desktop installer**.
2. Open the DMG and drag **EEG Layout Lab.app** into **Applications**. If supplied as a ZIP, extract it and move the App into Applications.
3. Open **EEG Layout Lab**. The first launch prepares its bundled computation environment and model data, then displays the App.

The desktop installer includes the interface, computation environment, model data, and supplied results. No separate Node.js, Python, Conda, or model-data installation is needed. The included simulations run locally, without an internet connection.

For subsequent use, open **EEG Layout Lab** directly from Applications. Quit with **Command + Q**. New results are saved on your Mac.

See the [desktop quick guide](desktop/START_HERE.md) for installation, first-open system prompts, and saved data.

## How to use

1. **Results Library → Experiment Overview / Layout Records:** select a saved layout and inspect its regions, electrode positions, and scores.
2. **Layout Design → Region Design:** choose the region count, allowed placement range, and maximum region radius, then start a calculation.
3. **Layout Design → Electrode Editor:** open a saved layout, adjust electrode positions or active electrodes, and recalculate. Use **Coordinate Import** to evaluate coordinates registered to the Ernie head model.
4. **Results Library → Compare Layouts:** compare selected layouts and export coordinates or reports.
5. **Signal Simulation:** select a layout, then choose source locations, waveforms, and interference settings to compare received signals.
6. **Documentation → User Guide / Models & Methods:** find instructions and explanations of the displayed metrics.

Use the language control in the upper-right corner to switch between English and Simplified Chinese. **Minimum Required Retention** changes which existing scores meet your requirement; changing it does not start a new calculation. New calculation results are saved locally and can be reopened in the Results Library.

## Work with the source code

For collaborators who want to modify the code, follow the separate [source installation instructions](docs/source-installation.md).

## Copyright and third-party material

© 2026 Yiming Shen.

EEG Layout Lab supports EEG research, education, and scientific collaboration.

A general license for the original project code has not been selected. Third-party components retain their own terms, including SimNIBS GPL-3.0-only and the Ernie example data's CC BY-NC 4.0 terms. Attribution, source links, and modification descriptions are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
