# EEG Layout Lab 快速开始

EEG Layout Lab 用于在固定头模和源模型下设计、查看和比较 EEG 电极布局。它提供三维头模、区域布局搜索、电极编辑、坐标评价、方案对比和源到电极的信号仿真。

当前交付为面向 Apple Silicon Mac 的源码协作版，通过本机 Node 服务在浏览器中运行。尚未提供 `.app` 或 DMG，也未完成第二台独立 Mac 的安装验证。

## 准备条件

- Node.js 22.13.0 或更新版本，以及 npm。
- 用于启动安装与数据工具的 Python 3.10 或更新版本。
- macOS 14 或更新版本、原生 Apple Silicon 进程；固定原生依赖的 wheel 要求该系统版本，安装时不使用 Rosetta。
- 可运行的 `conda` 命令。
- Git 和 Apple 命令行构建工具，用于固定版本的源码依赖。
- 与本仓库 manifest 匹配的 `eeglayoutlab-data-v1.tar.gz`。数据包随本地交付提供或由维护者单独提供，不假定存在公开下载地址。

完整计算环境使用 Python 3.11 与 SimNIBS 4.6.0，安装到项目内的 `.runtime/simnibs-4.6.0`。依赖安装需要联网；数据包安装工具仅读取本地归档。

## 安装和启动

在仓库根目录运行以下命令。若归档存放在其他位置，将 `releases/eeglayoutlab-data-v1.tar.gz` 替换为实际文件位置。

```sh
python3 scripts/data_bundle.py install releases/eeglayoutlab-data-v1.tar.gz
python3 scripts/data_bundle.py verify
python3 scripts/bootstrap_runtime.py
python3 scripts/bootstrap_runtime.py --execute
.runtime/simnibs-4.6.0/bin/python scripts/check_environment.py
.runtime/simnibs-4.6.0/bin/python scripts/check_environment.py --native
cd webapp
npm ci
npm run dev
```

第一次 bootstrap 命令显示安装计划；加上 `--execute` 后创建新环境，不覆盖已有环境。由该工具创建但中断的安装可用 `--execute --resume` 继续，工具会检查原安装身份。`--help` 列出自定义 conda 路径和已有安装资产目录等选项。环境检查不运行新的 FEM 研究仿真，也不构成科学验证。

Node 服务会自动选择当前仓库已安装的 `.runtime/simnibs-4.6.0/bin/python`。在浏览器打开 [http://127.0.0.1:3000](http://127.0.0.1:3000)，使用期间保持终端运行。新任务结果保存在当前仓库的 `results/v2/` 内。

开发服务停止后，可在 `webapp` 目录构建并启动本地成品服务：

```sh
npm run build
npm start
```

这两个启动入口都包含同源本地计算接口。当前完整功能依赖原生运行环境；不能只安装 NumPy/SciPy 后认定所有编辑与信号仿真入口均可运行。

## 使用顺序

1. 从首页选取已有固定面积记录，查看区域、坐标、指标和数据来源。
2. 在“布局设计”中设定区域数、位置范围和半径；无匹配记录时明确启动计算。
3. 在“电极编辑”中修改已保存布局，或在“坐标导入”中提交已配准到 Ernie 原生坐标系的坐标。
4. 在“方案对比”中查看共同条件下的指标与导出报告。
5. 在“信号仿真”中固定布局，再选择脑源位置、波形与干扰条件。

接受阈值 AR 只用于重新判断已有指标，不改变布局或启动新计算。区域数和电极数、几何可行性和性能达标、半径约束和面积约束分别表示不同条件。

## 如何解释结果

当前生产固定面积库包含 30 个条件，使用 4,096 点字典和 256 个生成源。512 个新源的独立复评不替换 App 默认分数。体网格收敛和独立头模验证尚未完成。

标准 64 导的相对值为 100% 是归一化定义。重建保留率、最差 10% 源的幅度保留率和相对定位评分分别评价不同能力，不能解释为 BCI 分类准确率或真实人体采集效果。信号仿真的 ECG/EOG 空间场属于明确设置的假设条件。

详细定义见 [Model and metrics](model-and-metrics.md)，数据管理见 [Data and reproducibility](data-and-reproducibility.md)，测试边界见 [Validation](validation.md)。代码与第三方材料的版权和许可见 [Third-party notices](../THIRD_PARTY_NOTICES.md)。
