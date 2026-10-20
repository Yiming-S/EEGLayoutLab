# EEG Layout Lab 安装与使用

**[下载 Mac 桌面版 — Apple Silicon](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.1.2)**

仓库目前为私有，需要登录有仓库访问权限的 GitHub 账号才能下载。

适用于 **M 系列芯片 Mac，macOS 14 或更新版本**。下载 `.dmg` 安装包，打开后将 **EEG Layout Lab** 拖入“应用程序”，再双击启动。首次打开会自动准备内置环境和模型数据。

**无需另外安装 Python、Node.js、Conda 或模型数据。**

[安装与首次打开说明](../desktop/START_HERE.zh-CN.md)

EEG Layout Lab 是面向科研社区的研究软件项目，用于设计、查看和比较 EEG 电极布局，提供三维头模、区域设计、电极编辑、方案对比和信号仿真。

[English instructions](../README.md)

## 项目合作者

- **Yiming Shen, PhD**
- **[Yi Wang, PhD](https://www.massey.ac.nz/massey/expertise/profile.cfm?stref=469822)**：新西兰梅西大学数学与计算科学学院计算机科学高级讲师。

项目计划部署到 Dr. Wang 搭建的服务器，提供完整网页版，支持查看已有结果和在线发起新计算。上线后将在主 README 补充访问地址。

## 运行方式

| 方式 | 当前状态 | 说明 |
| --- | --- | --- |
| Mac 桌面版 | 0.1.2 版 | 在 Mac 上运行，按下方步骤安装。 |
| 本机源码版 | 当前开发版本 | 使用单独的[源码安装说明](source-installation.zh-CN.md)，目前安装流程面向 Apple Silicon Mac。 |
| 服务器网页版 | 准备部署 | 计算与结果存储放在服务器上，见[服务器部署准备说明（英文）](server-deployment.md)。 |

桌面版 **0.1.2（构建号 1）**包含当前网页源码及[匿名访客任务队列（英文说明）](anonymous-queue.md)。安装包、基础数据包和校验文件统一放在 GitHub 版本页；完整历史计算缓存不在本次分发范围内。本版本的验证结果见 [GitHub 版本页](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.1.2)；既有[桌面版验证报告（英文）](../desktop/VERIFICATION.md)记录的是 0.1.1 版。

## 在 Mac 上安装并打开

使用 **Apple Silicon（M 系列芯片）Mac，macOS 14 或更新版本**。

1. 打开 [GitHub 0.1.2 版本页](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.1.2)，下载 **`EEGLayoutLab-0.1.2-macOS-arm64.dmg`**。
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

© 2026 Yiming Shen & Yi Wang。

项目支持脑电研究、教育与科研协作。原创源代码及配套文档采用 [GNU 通用公共许可证第 3 版，仅限此版本（GPL-3.0-only）](../LICENSE)。该许可证允许商业使用；分发修改版时须遵守 GPL，包括提供对应源码的要求。第三方软件、头模及数据保留各自的许可条款，其中 Ernie 数据及其派生材料继续适用 CC BY-NC 4.0，详见 [版权与第三方材料说明](../THIRD_PARTY_NOTICES.md)。
