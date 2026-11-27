# 安装说明

将 EEGLayoutLab 安装到用户自己可写的 Conda 或 micromamba 环境中，即可在本机直接运行区域布局搜索、电极坐标评价、稳健性研究与可复现结果导出，无需克隆源码仓库，也无需安装 Node.js 或手动运行 `npm`。

[English installation guide](installation.md) · [源码安装说明（面向开发者与 SimNIBS 有限元求解）](source-installation.zh-CN.md)

> **当前分发状态：** `cortech` 与 `eeglayoutlab` 的 Conda 打包配方位于 [`packaging/conda-forge/`](../packaging/conda-forge/eeglayoutlab/README.md)，已在 Apple Silicon macOS 与 Linux x86_64 上完成预演。在两个包正式合入 conda-forge 且 Zenodo 数据记录公开前，请从本地构建通道配合 `--from MIRROR` 安装，或先按[源码安装说明](source-installation.zh-CN.md)配置。

## 支持的系统与环境要求

| 操作系统 | 架构要求 | 环境与磁盘空间 |
| --- | --- | --- |
| **macOS** | Apple Silicon（M 系列芯片，`osx-arm64`，macOS 14 及以上） | 用户目录下的 Conda（推荐 `miniforge3`）或 `micromamba`；运行环境约 3 GB，默认模型数据 **1.80 GB** |
| **Linux** | x86_64（`linux-64`，glibc 2.28 及以上，如 Ubuntu 24.04） | 用户目录下的 Conda（`miniforge3`）或 `micromamba`；运行环境约 3 GB，默认模型数据 **1.80 GB** |
| **Windows** | WSL2（`linux-64`） | 请先安装 WSL2（Ubuntu 24.04），在 WSL2 内按 Linux 步骤执行（暂不支持原生 Windows，WSL2 路线尚未实机测试） |

请**不要**将软件安装到只读的系统级或多人共享 Conda 目录中：`eeglayoutlab` 会在环境内的科学根目录（`$CONDA_PREFIX/share/eeglayoutlab/root/results/v2`）保存计算缓存，遇到只读目录会直接拒绝启动并提示在个人主目录创建环境（退出码 `2`）。

## 1. 创建并激活环境

```sh
conda create -n eeglayoutlab -c conda-forge eeglayoutlab
conda activate eeglayoutlab
```

安装包内已包含预构建好的网页前端、本地 Python 服务（`eeglayoutlab serve`）、全部 9 个科学命令行子命令（`design`、`export`、`evaluate`、`search`、`study`、`pareto`、`eeg-summary`、`prior`、`channels`）、可复现实例以及固定版本的数值依赖（`Python 3.11`、`numpy`、`scipy`、`numba`、`llvmlite`、`nibabel`、`cortech`），无需安装 Node.js。

## 2. 下载并校验模型数据

运行以下命令下载、执行 SHA-256 完整性校验并自动挂载默认数据包（`base` 0.41 GB + `scalp-node-table` 1.40 GB，合计 **1.80 GB**）：

```sh
eeglayoutlab data install
eeglayoutlab data verify
```

- `base` 提供 Ernie 头模网格、预计算 10-05 前向导联库、候选几何与内置示例记录。
- `scalp-node-table` 提供名义头皮节点叠加表，无需 SimNIBS 有限元求解即可评估导入或自定义的任意头皮三维坐标。
- 在 Conda 安装态环境中，`eeglayoutlab data install` 完成后会自动将只读硬链接部署至 `$CONDA_PREFIX/share/eeglayoutlab/root`（传入 `--no-compose` 可跳过自动挂载）。
- 其他头模与电导率情景包可按需安装（详见[数据包说明（英文）](data-packages.md)）：
  - 跨头模研究（示例 3 的 11 个头模包，共 13.34 GB）：`eeglayoutlab data install --examples`
  - 颅骨电导率失配表（每个 1.40 GB）：`eeglayoutlab data install scalp-node-table-skull_x0.5 scalp-node-table-skull_x2`

## 3. 启动本地网页应用

指定一个自选的**工作区目录**（用于保存研究项目、稳健性研究、电极名称标注与任务记录）并启动服务：

```sh
eeglayoutlab serve ~/eeglayoutlab-workspace
```

服务仅监听本机回环地址 `127.0.0.1`，终端会输出带单次登录令牌的地址（`127.0.0.1:<端口>/open?token=…`）并自动打开浏览器。页面打开后，确认右上角**任务 / 队列**角标显示 `0`（已连接本地服务）即可开始使用。使用期间请保持终端运行，按 **Control + C** 停止服务。

![首次打开浏览器工作区界面标注图：顶栏五大板块、任务队列连接状态、语言与主题切换以及三个起点入口](images/workspace-first-launch.svg)

## 4. 用第一次真实计算检验安装是否成功

在任意工作目录下运行示例 1 和示例 2（在 M 系列 Mac 或主流 x86_64 机器上约需 10–15 秒，仅需默认 `base` 数据）：

```sh
eeglayoutlab examples run --skip-cross-head
```

该命令会从 10-05 电极名称构建标准 64 导参考布局，导出 BIDS、MNE（`.elc`）、EEGLAB（`.sfp`）及 SVG 图，执行双区域 30 mm 布局搜索与独立坐标评估，将结果写入当前目录下的 `./eeglayoutlab-examples/`，并逐项核对全部得分与 [`examples/expected.json`](../examples/expected.json) 的偏差不超过 `1e-6`。安装 `--examples` 头模包后，去掉 `--skip-cross-head` 即可同时运行 11 头模跨被试评估（示例 3）。

## Conda 安装包与源码安装的功能范围对比

| 功能模块 | Conda 安装包（`osx-arm64` 与 `linux-64`） | 含 SimNIBS 的源码安装（`osx-arm64`） |
| --- | --- | --- |
| 区域半径搜索（`search`）、Pareto 排序（`pareto`）与电极编辑器 | 支持（安装 `base` 即可） | 支持 |
| 导入或自定义头皮坐标评价（`evaluate`、位置扰动与跨会次稳健性） | 支持（通过 `scalp-node-table` 计算，无需跑 FEM） | 支持（节点表或直接调用 SimNIBS FEM） |
| 颅骨电导率失配与跨头模研究（`study`） | 安装对应情景表或头模包后支持 | 支持 |
| 真实脑电协方差摘要（`eeg-summary`）、数据先验（`prior`）与通道子集（`channels`） | 支持 | 支持 |
| 一代信号仿真（`source-reception/1`）及浏览已有二代记录／项目交付包 | 支持 | 支持 |
| **新发起二代信号仿真计算（`source-reception/2`）** | **不支持**（依赖 SimNIBS；仍可查看已有记录） | 支持 |
| 无节点表直接求解新坐标 FEM，或用 `charm` 构建新头模包 | **不支持** | 支持（见[源码安装说明](source-installation.zh-CN.md)） |

## 数据存放位置与卸载注意事项

EEGLayoutLab 将文件严格分为三处存放（详见[设计文档 0002（英文）](design/0002-installed-scientific-root.md)）：

1. **工作区目录（如 `~/eeglayoutlab-workspace`）**：保存你的研究项目（`projects/`）、稳健性研究（`studies/`）、电极名称标注（`annotations/`）与任务历史，升级或重建环境都不会丢失。
2. **用户数据包目录**（macOS 为 `~/Library/Application Support/EEGLayoutLab`，Linux 为 `~/.local/share/eeglayoutlab`，或由 `EEGLAYOUTLAB_DATA_DIR` 指定）：保存下载的模型数据包（`packages/`）。删除 Conda 环境不会清除已下载的数据包，新环境执行 `eeglayoutlab data compose` 即可直接硬链接复用。
3. **环境内科学根目录（`$CONDA_PREFIX/share/eeglayoutlab/root`）**：存放内置代码、网页静态资源及共享计算缓存（`results/v2/*_jobs`）。**运行 `conda env remove -n eeglayoutlab` 会一并删除该环境内的计算缓存记录**；如需长期归档某项结果，请先在界面的**研究项目**中导出包含完整快照与校验值的[项目交付包](../contracts/project-formats.md)。
