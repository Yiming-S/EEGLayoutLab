# 源码安装说明

本说明用于在本机运行和开发目前维护的网页版。界面在浏览器中打开，Node 服务和 Python／SimNIBS 计算运行在同一台电脑上。

[English source installation](source-installation.md)

本指南适用于当前的 **Apple Silicon macOS** 安装流程。计划中的服务器网页版见[服务器部署准备说明（英文）](server-deployment.md)；仓库内的运行环境安装工具和检查工具目前针对 macOS arm64。

## 准备条件

- Apple Silicon（M 系列芯片）Mac，macOS **14 或更新版本**。
- Node.js **22.13.0 或更新版本**，以及 npm。
- 用于运行安装工具的 Python **3.10 或更新版本**。安装工具会另行准备使用 **Python 3.11** 的计算环境，具体版本见[运行环境清单](../configs/runtime/manifest.json)。
- Apple Silicon 版本的 Conda，且终端中可以运行 `conda` 命令。
- Git 和 Apple 命令行工具。
- [GitHub 命令行工具](https://cli.github.com/)（`gh`），以及拥有此私有仓库访问权限的 GitHub 账号。
- 安装依赖时需要联网。

使用上述工具的原生 Apple Silicon 版本，不通过 Rosetta 运行。

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
