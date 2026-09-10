# EEG Layout Lab 安装与使用

**[下载 Mac 桌面版 — Apple Silicon](https://drive.google.com/drive/folders/1Ry-neU-oySVoToIt07eFfBnemKrnewmK?usp=sharing)**

适用于 **M 系列芯片 Mac，macOS 14 或更新版本**。下载 `.dmg` 安装包，打开后将 **EEG Layout Lab** 拖入“应用程序”，再双击启动。首次打开会自动准备内置环境和模型数据。

**无需另外安装 Python、Node.js、Conda 或模型数据。**

[安装与首次打开说明](../desktop/START_HERE.zh-CN.md)

EEG Layout Lab 是面向科研社区的研究软件项目，用于设计、查看和比较 EEG 电极布局，提供三维头模、区域设计、电极编辑、方案对比和信号仿真。

[English instructions](../README.md)

## 在 Mac 上安装并打开

使用 **Apple Silicon（M 系列芯片）Mac，macOS 14 或更新版本**。

1. 打开 [Google Drive 下载文件夹](https://drive.google.com/drive/folders/1Ry-neU-oySVoToIt07eFfBnemKrnewmK?usp=sharing)，下载 **`.dmg` 桌面安装包**。
2. 打开 DMG，将 **EEG Layout Lab.app** 拖到“应用程序”。如果收到的是 ZIP，解压后将 App 移到“应用程序”。
3. 打开 **EEG Layout Lab**。首次启动会准备内置计算环境和模型数据，然后显示 App。

桌面安装包包含界面、计算环境、模型数据及已有结果，无需另外安装 Node.js、Python、Conda 或模型数据。内置仿真在本机运行，不需要联网。

以后直接从“应用程序”打开 **EEG Layout Lab**，按 **Command + Q** 退出。新结果保存在这台 Mac 上。

安装、首次打开时的系统提示及数据位置，见 [桌面版快速指南](../desktop/START_HERE.zh-CN.md)。

## 使用顺序

1. **结果库 → 实验总览／布局记录**：选取已保存的布局，查看区域、电极位置和评分。
2. **布局设计 → 区域设计**：设置区域数量、允许布置范围和最大区域半径，然后启动计算。
3. **布局设计 → 电极编辑**：打开已保存布局，调整电极位置或启用的电极，再重新计算。使用“坐标导入”可评价已配准到 Ernie 头模坐标系的电极坐标。
4. **结果库 → 方案对比**：对比所选布局，导出坐标或报告。
5. **信号仿真**：选择布局，再设置脑源位置、波形和干扰条件，对比接收信号。
6. **文档 → 使用指南／建模与原理**：查看操作说明和指标解释。

右上角可切换简体中文和英语。“最低保留要求”用于判断现有评分是否达到要求，修改该值不会启动新计算。新计算结果保存在本机，可从结果库再次打开。

## 修改源代码

需要参与代码开发的合作者，可使用单独的 [源码安装说明](source-installation.zh-CN.md)。

## 版权与第三方材料

© 2026 Yiming Shen。

项目支持脑电研究、教育与科研协作。原创代码尚未指定通用许可证，第三方软件、头模及数据保留各自的许可条款，详见 [版权与第三方材料说明](../THIRD_PARTY_NOTICES.md)。
