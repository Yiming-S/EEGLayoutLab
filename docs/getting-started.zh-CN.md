# EEG Layout Lab 网页版使用指南

EEG Layout Lab 是免费的科研开源软件，用于设计、查看和比较 EEG 电极布局，提供三维头模、区域设计、电极编辑、方案对比和信号仿真。

项目目前集中维护网页版。界面在浏览器中使用，由本地 Python 服务 `eeglayoutlab serve` 提供，计算由 Python／SimNIBS 工作进程完成。

[English instructions](../README.md) · [本机安装](source-installation.zh-CN.md)

## 运行方式

| 方式 | 当前状态 | 说明 |
| --- | --- | --- |
| 本机网页版 | 当前开发版本 | 按[源码安装说明](source-installation.zh-CN.md)准备环境，再在浏览器中打开。目前的计算环境安装流程面向 Apple Silicon Mac。 |
| 服务器网页版 | 冻结 | 使用旧版 Node 服务，冻结在标签 `node-host-freeze`，见[服务器部署准备说明（英文）](server-deployment.md)。 |

Mac 桌面版已停止维护，桌面外壳和打包工具已从当前源码中移除。[v0.1.2 版本页](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.1.2)保留最后一个桌面版的发布记录。当前使用的基础数据包见 [v0.2.0 版本页](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.2.0)。

## 在本机打开网页版

首次使用时，按[源码安装说明](source-installation.zh-CN.md)安装模型数据、Python 计算环境和网页依赖。当前流程需要 Apple Silicon（M 系列芯片）Mac，macOS 14 或更新版本。

安装完成后（包括[源码安装说明](source-installation.zh-CN.md)第 4 步中的 `eeglayoutlab` 命令和界面构建），在仓库根目录运行：

```sh
.venv/bin/eeglayoutlab serve ~/eeglayoutlab-workspace
```

命令会在浏览器中打开应用；工作区目录 `~/eeglayoutlab-workspace` 保存任务列表、研究项目等，可以换成任意目录。使用期间保持终端运行；结束使用时，在终端按 **Control + C** 停止服务。每次启动的地址都不同：上一次运行留下的标签页会提示重新运行命令。

源码与基础数据包均可直接公开获取（数据包及校验文件位于 [v0.2.0 版本页](https://github.com/Yiming-S/EEGLayoutLab/releases/tag/v0.2.0)，无需登录 GitHub；完整历史计算缓存不包含在基础数据包内）。首次安装后可运行 `.venv/bin/eeglayoutlab examples run --skip-cross-head` 验证本机计算环境与模型数据。

## 使用顺序

1. **工作区**：首页列出新建布局的入口、最近的布局、计算任务、稳健性研究和研究项目。
2. **布局 → 布局列表**：每个布局一行；“查看布局”打开布局详情页，列出同一组坐标在各条件下的评价，并从这里进入对比、信号仿真和稳健性研究。
3. **布局 → 区域设计／坐标导入／电极编辑**：按区域数量、允许布置范围和最大区域半径搜索新布局；评价已配准到 Ernie 头模坐标系的电极坐标；或打开已保存布局，调整电极位置或启用的电极后重新计算。
4. **分析 → 方案对比／稳健性研究／信号仿真／通道子集**：先选布局再选评价条件进行对比，导出坐标或报告；用多次请求检验稳健性；选择布局后设置脑源、波形和干扰条件，对比接收信号；从记录摘要中选择通道子集。
5. **研究结果**：总面积研究的结果，以及两个历史批次。
6. **工作区 → 研究项目**：将布局、编辑结果和信号实验保存为独立快照，记录研究备注与比较要求。项目保存在工作区目录的 `projects/` 中，页面列出此工作区的全部项目，打开时不需要访问密钥。项目内的存档独立于计算队列，原始布局库仍共享。
7. **项目交付**：下载包含原始结果、说明、比较要求、版本与校验值的完整交付包。
8. **文档**：操作说明见应用内的“使用指南”。模型、指标和方法以文档章节为准（英文）：[模型与指标](model-and-metrics.md)、[方法细节](method-details.md)、[历史实验](historical-studies.md)和[验证范围](validation.md)。完整的参考文献按主题列在[参考文献](references.md)，每条都写出完整著录信息。应用内“建模与原理”页只列出这些章节的入口。

右上角可切换简体中文和英语。“最低保留要求”用于判断现有评分是否达到要求，修改该值不会启动新计算。本机运行时，新结果保存在本机，可从布局列表再次打开。

## 开发与部署

开发环境和启动命令见[源码安装说明](source-installation.zh-CN.md)。模块职责见[架构说明（英文）](architecture.md)，测试与验收要求见 [CONTRIBUTING（英文）](../CONTRIBUTING.md)。服务器上线所需的环境、访问配置和数据持久化工作见[部署准备说明（英文）](server-deployment.md)。

## 版权与第三方材料

本项目以非营利方式开发并免费提供，用于脑电研究、教育与科研协作。原创源代码及配套文档采用 [GNU 通用公共许可证第 3 版，仅限此版本（GPL-3.0-only）](../LICENSE)。该许可证允许商业使用；分发修改版时须遵守 GPL，包括提供对应源码的要求。第三方软件、头模及数据保留各自的许可条款，其中 Ernie 数据及其派生材料继续适用 CC BY-NC 4.0，详见[版权与第三方材料说明](../THIRD_PARTY_NOTICES.md)。
