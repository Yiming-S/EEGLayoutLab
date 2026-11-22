# 源码安装说明

本说明用于在本机运行和开发目前维护的网页版。界面在浏览器中打开，Node 服务和 Python／SimNIBS 计算运行在同一台电脑上。

[English source installation](source-installation.md)

本指南先介绍 **Apple Silicon macOS** 的安装流程。**Linux x86_64** 有一套不含 SimNIBS 的计算环境，依靠已发布的头皮节点表计算，见文末[Linux x86_64](#linux-x86_64)。**Windows** 暂不支持原生安装，请使用 WSL2（尚未测试）。计划中的服务器网页版见[服务器部署准备说明（英文）](server-deployment.md)。

## 准备条件

- Apple Silicon（M 系列芯片）Mac，macOS **14 或更新版本**。
- Node.js **22.13.0 或更新版本**，以及 npm。
- 用于运行安装工具的 Python **3.10 或更新版本**。安装工具会另行准备使用 **Python 3.11** 的计算环境，具体版本见[运行环境清单](../configs/runtime/manifest.json)。
- Apple Silicon 版本的 Conda，且终端中可以运行 `conda` 命令。
- Git 和 Apple 命令行工具。
- [GitHub 命令行工具](https://cli.github.com/)（`gh`），以及拥有此私有仓库访问权限的 GitHub 账号。
- 安装依赖时需要联网。

使用上述工具的原生 Apple Silicon 版本，不通过 Rosetta 运行。运行环境本身保持原生；只有用 `charm` 构建头模包时，还需安装 Rosetta 2 来运行 SimNIBS 自带的 x86_64 工具（见 [server deployment](server-deployment.md#building-head-packages)）。

## 首次安装

### 1. 克隆仓库

打开终端，登录有仓库访问权限的账号，并克隆当前开发源码：

```sh
gh auth login
gh repo clone Yiming-S/EEGLayoutLab
cd EEGLayoutLab
```

后续步骤继续在这个终端窗口中操作。仓库根目录是同时包含 `scripts/` 和 `webapp/` 的文件夹。修改源码前，运行 `git switch -c codex/my-changes` 创建工作分支。数据安装工具会按当前源码中的清单核对数据包；下文列出的数据包对应当前清单。

### 2. 安装模型数据

从 [v0.1.2 版本页面](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.1.2)下载匹配的 `eeglayoutlab-data-v1.tar.gz` 数据包及校验文件。数据包与源码分别安装。当前仓库为私有仓库，访问版本页面和附件需要仓库权限。

在仓库根目录下载并校验数据包：

```sh
mkdir -p releases
gh release download v0.1.2 --repo Yiming-S/EEGLayoutLab \
  --pattern eeglayoutlab-data-v1.tar.gz \
  --pattern eeglayoutlab-data-v1.tar.gz.sha256 \
  --dir releases
(cd releases && shasum -a 256 -c eeglayoutlab-data-v1.tar.gz.sha256)
```

校验成功后，**在仓库根目录运行，不是在 `webapp/` 中运行**：

```sh
python3 scripts/data_bundle.py install releases/eeglayoutlab-data-v1.tar.gz
python3 scripts/data_bundle.py verify
```

数据包共含 21 个文件，总计 406,226,293 字节（387.41 MiB），包含数据来源说明、选定的固定输入和记录，不包含完整历史计算目录。如果通过浏览器下载，先将数据包和校验文件放入 `releases/`，再运行校验与安装命令。安装与验证成功后，再继续下一步。

### 3. 安装 Python 计算环境

在仓库根目录运行：

```sh
python3 scripts/bootstrap_runtime.py --execute
```

等待安装和环境检查成功完成，再继续下一步。网页服务会自动使用该环境，无需手动激活 Conda 环境。

### 4. 安装前端依赖并打开网页

```sh
cd webapp
npm ci
npm run dev
```

在浏览器打开 [http://127.0.0.1:3000](http://127.0.0.1:3000)。使用期间保持终端运行；结束使用时，在终端按 **Control + C** 停止服务。

## 安装完成后，每次怎么打开

在存放仓库的上一级文件夹中，运行：

```sh
cd EEGLayoutLab/webapp
npm run dev
```

然后在浏览器打开 [http://127.0.0.1:3000](http://127.0.0.1:3000)。不需要每次重新安装数据和依赖。

操作流程见 [安装与使用](getting-started.zh-CN.md#使用顺序)。

## Linux x86_64

Linux 使用较小的计算环境：Python 3.11.14，numpy、scipy 与 Mac 版本相同，另含 cortech、numba、llvmlite 和 nibabel，不含 SimNIBS。锁文件为 [`manifest-linux-64.json`](../configs/runtime/manifest-linux-64.json)、[`conda-linux-64.explicit.txt`](../configs/runtime/conda-linux-64.explicit.txt) 和 [`pip-linux-64.txt`](../configs/runtime/pip-linux-64.txt)，每个包都记录 SHA-256，不从源码编译。

该环境不能求解 FEM。计算新坐标需要已发布的头皮节点表（`results/v2/current_scalp_node_table.json` 和 `results/v2/scalp_node_table/<table_id>/`，约 2.6 GB）；跨头模研究还需要 `results/v2/heads/<id>/`。这些文件不在数据包中，需从构建它们的 Mac 复制。

需要 x86_64 Linux（glibc 2.28 或更新，例如 Ubuntu 24.04）、Node.js 22.18 或更新、Python 3.10 或更新，以及 Miniforge 或 micromamba；不需要 Git 和编译器。按第 2 步安装数据（Linux 上用 `sha256sum -c` 校验），复制头皮节点表，然后在仓库根目录运行：

```sh
python3 scripts/bootstrap_runtime.py
python3 scripts/bootstrap_runtime.py --execute
.runtime/compute-linux-64/bin/python scripts/build_scalp_node_table.py --verify
```

环境安装在 `.runtime/compute-linux-64/`。没有 `.runtime/simnibs-4.6.0/` 时，网页服务和命令行会自动选用它。2026-11-21 在 Docker `linux/amd64`（Apple M3 Ultra 上经 Rosetta 模拟）中验证：三个示例与 `expected.json` 的差异都在 1e-6 以内，与 Mac 结果的最大差为 4.1e-14。尚未在实体 x86_64 机器上验证。完整说明见[英文版](source-installation.md#linux-x86_64)。

## Windows

暂不支持原生安装，请在 WSL2（Ubuntu 24.04）中按 Linux 步骤安装（尚未测试）。原生安装还需要：win-64 锁文件；运行时路径支持 `python.exe` 和 `Lib/site-packages`；去掉 `reception_forward_provider.py` 中 Windows 没有的 `fcntl`（这会改变所有设计评价的缓存键，尚未修改）。仓库已加入 `.gitattributes`，避免 Git for Windows 转换换行符导致数据清单校验失败。详见[英文版](source-installation.md#windows)。
