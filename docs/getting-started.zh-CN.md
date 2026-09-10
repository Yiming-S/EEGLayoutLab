# EEG Layout Lab 安装与使用

EEG Layout Lab 是面向科研社区的研究软件项目，用于设计、查看和比较 EEG 电极布局，提供三维头模、区域设计、电极编辑、方案对比和信号仿真。

[English instructions](../README.md)

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

后续步骤继续在这个终端窗口中操作。

### 2. 安装模型数据

向项目维护者获取匹配的 `eeglayoutlab-data-v1.tar.gz` 数据包。模型数据单独提供，不包含在 Git 仓库中。

先创建存放数据包的文件夹：

```sh
mkdir -p releases
```

将数据包放进该文件夹，然后在仓库根目录运行：

```sh
python3 scripts/data_bundle.py install releases/eeglayoutlab-data-v1.tar.gz
python3 scripts/data_bundle.py verify
```

如果数据包在其他位置，将安装命令中的路径替换为实际文件路径。

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

## 使用顺序

1. **结果库 → 实验总览／布局记录**：选取已保存的布局，查看区域、电极位置和评分。
2. **布局设计 → 区域设计**：设置区域数量、允许布置范围和最大区域半径，然后启动计算。
3. **布局设计 → 电极编辑**：打开已保存布局，调整电极位置或启用的电极，再重新计算。使用“坐标导入”可评价已配准到 Ernie 头模坐标系的电极坐标。
4. **结果库 → 方案对比**：对比所选布局，导出坐标或报告。
5. **信号仿真**：选择布局，再设置脑源位置、波形和干扰条件，对比接收信号。
6. **文档 → 使用指南／建模与原理**：查看操作说明和指标解释。

右上角可切换简体中文和英语。“最低保留要求”用于判断现有评分是否达到要求，修改该值不会启动新计算。新计算结果保存在本机，可从结果库再次打开。

## 版权与第三方材料

© 2026 Yiming Shen。

项目支持脑电研究、教育与科研协作。原创代码尚未指定通用许可证，第三方软件、头模及数据保留各自的许可条款，详见 [版权与第三方材料说明](../THIRD_PARTY_NOTICES.md)。
