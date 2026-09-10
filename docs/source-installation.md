# Source installation

These instructions are for collaborators who want to run and modify the source code. To use the desktop App without installing development tools, follow the [Mac installation guide](../README.md#install-and-open-on-mac).

[简体中文源码安装说明](source-installation.zh-CN.md)

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

Keep this Terminal window open for the following steps. The repository root is the folder containing `scripts/` and `webapp/`.

### 2. Install the model data

Obtain the matching `eeglayoutlab-data-v1.tar.gz` archive from the project maintainer. Source checkouts require this separate archive; it is not stored in Git. The desktop installer already includes its model data.

Create a folder for the archive:

```sh
mkdir -p releases
```

Place the downloaded archive in that folder, then run **from the repository root, not from `webapp/`**:

```sh
python3 scripts/data_bundle.py install releases/eeglayoutlab-data-v1.tar.gz
python3 scripts/data_bundle.py verify
```

Creating `releases/` does not download the archive. If the archive is stored elsewhere, replace its path in the install command. Continue only after installation and verification succeed.

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
