# 安装说明

将 EEGLayoutLab 安装到个人可写的 Conda 或 micromamba 环境中，即可在本机直接运行区域布局搜索、电极坐标评价、稳健性研究与可复现结果导出——无需克隆源码仓库，也无需安装 Node.js 或运行 `npm`。

[English installation guide](installation.md) · [源码安装说明（面向开发者与 SimNIBS 有限元求解）](source-installation.zh-CN.md)

> **当前分发状态：** `cortech` 与 `eeglayoutlab` 的 Conda 打包配方位于 [`packaging/conda-forge/`](../packaging/conda-forge/eeglayoutlab/README.md)，已在 Apple Silicon macOS 与 Linux x86_64 上完成预演。在两个包正式合入 conda-forge 且 Zenodo 数据记录公开前，可通过本地通道配合 `--from MIRROR` 启动，或直接使用一条命令完成配置的[源码安装说明](source-installation.zh-CN.md)。

## 快速开始（仅需 3 行命令）

```sh
conda create -y -n eeglayoutlab -c conda-forge eeglayoutlab
conda activate eeglayoutlab
eeglayoutlab quickstart
```

`eeglayoutlab quickstart` 会自动完成全部首次准备与日常启动：

1. **首次运行**：自动提示默认模型数据体积（`base` 0.41 GB + `scalp-node-table` 1.40 GB，合计 **1.80 GB**），支持断点续传下载并逐文件执行 SHA-256 校验，自动挂载至当前环境（若旧环境已下载过数据包，会直接秒级硬链接复用，无需重复下载），自动创建默认工作区 `~/eeglayoutlab-workspace`，并在浏览器打开本地界面（仅监听 `127.0.0.1`）。
2. **之后每次打开**：同样只需激活环境后运行 `eeglayoutlab quickstart`，检测到数据就绪后会直接打开浏览器。使用期间请保持终端运行，按 **Control + C** 停止服务。

如需用一次真实的新计算（而不仅看右上角队列角标 `0`）验证计算环境与模型数据完全可用，随时运行（约 10–15 秒）：

```sh
eeglayoutlab doctor --smoke
```

该命令会逐项检查科学根目录、Python 计算依赖、数据包与前端静态资源，并在临时目录中完整跑通标准 64 导设计、多格式与 SVG 导出、双区域半径搜索及独立坐标评估，核对全部得分与 [`examples/expected.json`](../examples/expected.json) 的误差不超过 `1e-6`。

![首次打开浏览器工作区界面标注图：顶栏五大板块、任务队列连接状态、语言与主题切换以及三个起点入口](images/workspace-first-launch.svg)

## 支持的系统与环境要求

| 操作系统 | 架构要求 | 环境与磁盘空间 |
| --- | --- | --- |
| **macOS** | Apple Silicon（M 系列芯片，`osx-arm64`，macOS 14 及以上） | 个人目录下的 Conda（推荐 `miniforge3`）或 `micromamba`；运行环境约 3 GB，默认模型数据 **1.80 GB** |
| **Linux** | x86_64（`linux-64`，glibc 2.28 及以上，如 Ubuntu 24.04） | 个人目录下的 Conda（`miniforge3`）或 `micromamba`；运行环境约 3 GB，默认模型数据 **1.80 GB** |
| **Windows** | WSL2（`linux-64`） | 先安装 WSL2（Ubuntu 24.04），在 WSL2 终端内直接运行上方 3 行命令（暂不支持原生 Windows，WSL2 路线尚未实机测试） |

请**不要**将软件安装到只读的系统级或多人共享 Conda 目录中：`eeglayoutlab` 会在环境内的 `$CONDA_PREFIX/share/eeglayoutlab/root/results/v2` 保存计算缓存，遇到只读目录会直接拒绝启动并提示在个人主目录创建环境（退出码 `2`）。

## 按需扩展数据包与自定义工作区

需要最小体积启动、指定其他工作区目录，或按需下载跨头模／颅骨电导率情景包时（详见[数据包说明（英文）](data-packages.md)）：

```sh
# 仅下载最小基础包启动（0.41 GB：支持区域搜索与一代信号仿真，暂不下载新坐标节点表）
eeglayoutlab quickstart --base-only

# 指定自定义工作区目录
eeglayoutlab quickstart /path/to/my-study-workspace

# 按需安装跨头模研究数据包（示例 3 的 11 个头模包，共 13.34 GB）并跑全量验证
eeglayoutlab data install --examples
eeglayoutlab examples run

# 按需安装颅骨电导率失配节点表（每个 1.40 GB）
eeglayoutlab data install scalp-node-table-skull_x0.5 scalp-node-table-skull_x2
```

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

1. **工作区目录（默认 `~/eeglayoutlab-workspace`）**：保存你的研究项目（`projects/`）、稳健性研究（`studies/`）、电极名称标注（`annotations/`）与任务历史，升级或重建环境都不会丢失。
2. **用户数据包目录**（macOS 为 `~/Library/Application Support/EEGLayoutLab`，Linux 为 `~/.local/share/eeglayoutlab`，或由 `EEGLAYOUTLAB_DATA_DIR` 指定）：保存下载的模型数据包（`packages/`）。删除 Conda 环境不会清除已下载的数据包，新建环境运行 `eeglayoutlab quickstart` 时会自动硬链接复用。
3. **环境内科学根目录（`$CONDA_PREFIX/share/eeglayoutlab/root`）**：存放内置代码、网页静态资源及共享计算缓存（`results/v2/*_jobs`）。**运行 `conda env remove -n eeglayoutlab` 会一并删除该环境内的计算缓存记录**；如需长期归档某项结果，请先在界面的**研究项目**中导出包含完整快照与校验值的[项目交付包](../contracts/project-formats.md)。
