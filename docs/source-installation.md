# Source installation

These instructions are for collaborators who want to run and modify the source code. To use the desktop App without installing development tools, follow the [Mac installation guide](../README.md#install-and-open-on-mac).

[简体中文源码安装说明](source-installation.zh-CN.md)

This guide covers the current **Apple Silicon macOS** setup. For the planned hosted version, use [Server deployment preparation](server-deployment.md); the managed runtime installer and environment checker in this repository target macOS arm64.

## Requirements

- An Apple Silicon Mac running macOS **14 or newer**.
- Node.js **22.13.0 or newer**, with npm.
- Python **3.10 or newer** to run the setup tools. The managed computation environment installs its own **Python 3.11** interpreter, as specified in the [runtime manifest](../configs/runtime/manifest.json).
- An Apple Silicon Conda installation with the `conda` command available in Terminal.
- Git and Apple's Command Line Tools.
- [GitHub CLI](https://cli.github.com/) (`gh`) and a GitHub account with access to this private repository.
- An internet connection for installing dependencies.

Use the native Apple Silicon versions of these tools, without Rosetta.

## First-time setup

### 1. Clone the repository

Open Terminal, sign in with the account that has repository access, and clone the release version:

```sh
gh auth login
gh repo clone Yiming-S/EEGLayoutLab -- --branch v0.1.1
cd EEGLayoutLab
```

Keep this Terminal window open for the following steps. The repository root is the folder containing `scripts/` and `webapp/`. The release tag keeps the source and data inventory together. Create a working branch with `git switch -c my-changes` before editing the source.

### 2. Install the model data

Download the matching `eeglayoutlab-data-v1.tar.gz` archive and checksum from [Release v0.1.1](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.1.1). Source checkouts require this separate archive; the desktop installer already includes its model data. This repository is private, so the release page and assets require repository access.

From the repository root, download and check the archive:

```sh
mkdir -p releases
gh release download v0.1.1 --repo Yiming-S/EEGLayoutLab \
  --pattern eeglayoutlab-data-v1.tar.gz \
  --pattern eeglayoutlab-data-v1.tar.gz.sha256 \
  --dir releases
(cd releases && shasum -a 256 -c eeglayoutlab-data-v1.tar.gz.sha256)
```

After the checksum succeeds, install the data **from the repository root, not from `webapp/`**:

```sh
python3 scripts/data_bundle.py install releases/eeglayoutlab-data-v1.tar.gz
python3 scripts/data_bundle.py verify
```

The bundle contains 21 files totaling 406,226,293 bytes (387.41 MiB), including the data-source declaration and selected frozen inputs and records. Complete historical calculation directories are excluded. If you download through the browser, place the archive and checksum in `releases/` before running the check and installation commands. Continue only after installation and verification succeed.

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

## Open after installation

From the folder containing your checkout, run:

```sh
cd EEGLayoutLab/webapp
npm run dev
```

Then open [http://127.0.0.1:3000](http://127.0.0.1:3000). You do not need to reinstall the data or dependencies each time.

For the App's workflow, see [How to use](../README.md#how-to-use).
