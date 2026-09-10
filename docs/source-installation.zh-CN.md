# 源码安装说明

本说明面向需要运行并修改源代码的合作者。直接使用桌面 App 无需安装开发工具，按 [Mac 安装与使用](getting-started.zh-CN.md) 操作即可。

[English source installation](source-installation.md)

## 准备条件

- Apple Silicon（M 系列芯片）Mac，macOS **14 或更新版本**。
- Node.js **22.13.0 或更新版本**，以及 npm。
- Python **3.10 或更新版本**。
- Apple Silicon 版本的 Conda，且终端中可以运行 `conda` 命令。
- Git 和 Apple 命令行工具。
- 安装依赖时需要联网。

使用上述工具的原生 Apple Silicon 版本，不通过 Rosetta 运行。

## 首次安装

### 1. 克隆仓库

打开终端，运行：

```sh
git clone https://github.com/Yiming-S/EEGLayoutLab.git
cd EEGLayoutLab
```

后续步骤继续在这个终端窗口中操作。仓库根目录是同时包含 `scripts/` 和 `webapp/` 的文件夹。

### 2. 安装模型数据

向项目维护者获取匹配的 `eeglayoutlab-data-v1.tar.gz` 数据包。源码版需要单独安装该数据包，它不包含在 Git 仓库中；桌面安装包已内置模型数据。

先创建存放数据包的文件夹：

```sh
mkdir -p releases
```

将已下载的数据包放进该文件夹，然后**在仓库根目录运行，不是在 `webapp/` 中运行**：

```sh
python3 scripts/data_bundle.py install releases/eeglayoutlab-data-v1.tar.gz
python3 scripts/data_bundle.py verify
```

创建 `releases/` 文件夹不会自动下载数据包。如果数据包在其他位置，将安装命令中的路径替换为实际文件路径。安装与验证成功后，再继续下一步。

### 3. 安装 Python 计算环境

在仓库根目录运行：

```sh
python3 scripts/bootstrap_runtime.py --execute
```

等待安装和环境检查成功完成，再继续下一步。App 会自动使用该环境，无需手动激活 Conda 环境。

### 4. 安装前端依赖并打开 App

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
