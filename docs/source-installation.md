# Source installation

These instructions run the maintained web application locally and prepare a checkout for development. The interface opens in a browser; Node and Python/SimNIBS run on the same computer.

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

Use the native Apple Silicon versions of these tools, without Rosetta. The runtime itself stays native. Only building head packages with `charm` also needs Rosetta 2 installed, for SimNIBS's bundled x86_64 tools (see [server deployment](server-deployment.md#building-head-packages)).

## First-time setup

### 1. Clone the repository

Open Terminal, sign in with the account that has repository access, and clone the current development source:

```sh
gh auth login
gh repo clone Yiming-S/EEGLayoutLab
cd EEGLayoutLab
```

Keep this Terminal window open for the following steps. The repository root is the folder containing `scripts/` and `webapp/`. Create a working branch with `git switch -c codex/my-changes` before editing the source. The data installer checks the archive against the manifest in this checkout; use the archive named below while that manifest remains the current one.

### 2. Install the model data

Download the matching `eeglayoutlab-data-v1.tar.gz` archive and checksum from [Release v0.1.2](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.1.2). Install this archive separately from the source code. This repository is private, so the release page and assets require repository access.

From the repository root, download and check the archive:

```sh
mkdir -p releases
gh release download v0.1.2 --repo Yiming-S/EEGLayoutLab \
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

Wait for installation and the environment check to finish successfully before continuing. The web service selects this environment automatically; no manual Conda activation is needed.

### 4. Install the web dependencies and open the browser interface

```sh
cd webapp
npm ci
npm run dev
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000) in your browser. Keep Terminal running while using the application. Press **Control + C** in Terminal to stop it.

## Open after installation

From the folder containing your checkout, run:

```sh
cd EEGLayoutLab/webapp
npm run dev
```

Then open [http://127.0.0.1:3000](http://127.0.0.1:3000). You do not need to reinstall the data or dependencies each time.

For the application's workflow, see [How to use](../README.md#how-to-use).
