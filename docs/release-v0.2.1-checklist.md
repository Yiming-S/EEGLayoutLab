# Release `v0.2.1` Preparation Checklist

这份本地发布操作清单对应 **EEG Layout Lab `v0.2.1`** 的准备与手动发布流程，聚焦三项核心改进：

1. **补齐公开 `scalp-node-table` 数据包分发闭环**：无需本地安装 SimNIBS，macOS 与 Linux 用户均可通过 `eeglayoutlab data install` 一键拉取并校验 `base`（`0.41 GB`）+ `scalp-node-table`（`1.40 GB`）完成任意 64 导新坐标评估。
2. **三行极简本地安装与自检工作流**：提供 `eeglayoutlab quickstart`、`eeglayoutlab doctor [--smoke]` 与源码仓一键引导脚本 `python3 scripts/setup_local.py`。
3. **网页端缺数据即时安装指引 + Phase 3 全套 CI/Release 工作流就绪**：新增 `/api/data-status` 与 `<DataReadinessNotice />` 双语横幅，并配齐 `checks.yml`、`data.yml`、`package.yml`、`browser.yml`、`release.yml`、`pages.yml` 与 `docs.yml`。

> 仓库策略（`U28`）：所有推送、打 Tag、创建/发布 GitHub Release 与上传数据包均由维护者本人执行，自动化脚本绝不主动推送或公开任何内容。

## 1. 运行本地自动预检

在仓库根目录执行无副作用预检脚本，核对版本号同步性、15 个数据包 `accepts_code` 范围、`base` + `scalp-node-table` SHA-256 指纹、三行安装与前端提示接线，以及全部 7 个 GitHub Actions 工作流和发行元数据（`CITATION.cff`、`.zenodo.json`、`SECURITY.md`、`THIRD_PARTY_NOTICES.md`、`CHANGELOG.md`）：

```bash
.venv/bin/python scripts/prepare_release_v021.py --check
```

如果本地归档目录已构建好数据包 `.json` 清单与 `.tar` 归档文件，可一并校验归档字节大小与清单指纹：

```bash
.venv/bin/python scripts/prepare_release_v021.py --verify-archives /path/to/staged-data-packages
```

## 2. 默认公开数据包核对（无需重打归档）

`data/packages.json` 中全部 15 个数据包均声明 `"accepts_code": ">=0.2.0,<1.0.0"`，因此升级代码版本至 `0.2.1` **不会改变任何科学缓存键，也无需重新构建 `.tar` 数据包**：

| 数据包 | 版本 | 解压体积 | 归档文件与配套清单 | Manifest SHA-256（前 16 位） | 用途与公开状态 |
| --- | --- | --- | --- | --- | --- |
| `base` | `1.0.0` | `0.41 GB`（21 文件） | `eeglayoutlab-data-base-1.0.0.tar` + `.json` | `defe75a4df548ed0` | 区域半径搜索、基础电极编辑与 v1 信号仿真（可公开，含 Ernie CC BY-NC 署名） |
| `scalp-node-table` | `1.0.0` | `1.40 GB`（依赖 `base`） | `eeglayoutlab-data-scalp-node-table-1.0.0.tar` + `.json` | `aad25cffa9bc875f` | 免 SimNIBS 任意新坐标评估、电极删减重评与鲁棒性研究（与 `base` 同批公开） |

> 其余 10 个 IXI 个体头模包（`head-ixi*`）受 `U20`（CC BY-SA + Ernie CC BY-NC 组合条款决策）约束，在完成许可确认前仅用于本地镜像或私有 CI 缓存，不随公开 Release 暴露。

## 3. 版本号切换（准备打 `v0.2.1` Tag 时执行）

确认公开/私有可见性窗口（`U28`）与数据包托管地址（`U18` Zenodo 记录或 GitHub Release 资产前缀）后，同步更新以下 5 处版本字段为 `0.2.1`：

- [`pyproject.toml`](../pyproject.toml)（`version = "0.2.1"`）
- [`webapp/package.json`](../webapp/package.json)（`"version": "0.2.1"`）
- [`packaging/conda-forge/eeglayoutlab/recipe.yaml`](../packaging/conda-forge/eeglayoutlab/recipe.yaml)（`context.version: "0.2.1"`）
- [`CITATION.cff`](../CITATION.cff)（`version: "0.2.1"` 与 `date-released`）
- [`.zenodo.json`](../.zenodo.json)（`"version": "0.2.1"`）

同时在 [`CHANGELOG.md`](../CHANGELOG.md) 中将 `## Unreleased` 下的条目归入 `## 0.2.1 — YYYY-MM-DD`，若更新了数据包托管 URL 前缀，用 `eeglayoutlab data build` 或更新 [`data/packages.json`](../data/packages.json) 中的 URL 字段（保持 `content_sha256` 与 `manifest_sha256` 不变），随后再次执行：

```bash
.venv/bin/python scripts/prepare_release_v021.py --check
PYTHONPATH=src .venv/bin/python -m pytest -m 'not data_bundle and not native_runtime' -q
```

## 4. 推送、CI Linux 首跑与草稿 Release 审核（维护者手动执行）

1. **推送 `main` 触发双平台与 Linux 验证（Slice 10 / 16 / 18）**：
   - `checks.yml` 自动在 `ubuntu-24.04`（Node `24.22.3` / `26.5.0`）与 `macos-15`（Node `24.22.3`）运行前端构建与 Python 全量校验。
   - 首次在 GitHub Actions 页面对 `data.yml` 手动触发一次 `workflow_dispatch`（勾选 `seed_cache=true` 并填入持有 `.tar` + `.json` 的 tag），即可种下 `actions/cache`，随后 `data.yml` 与 `browser.yml` 将在 Linux runner 上实跑数据合成、示例 1–2 对齐与真实 Chrome（SwiftShader WebGL）工作流。
2. **推送 `v0.2.1` Tag 生成草稿 Release（Slice 17）**：
   - 本地创建带注释 Tag 并推送后，`release.yml` 会自动构建 `cortech`（`linux-64`、`osx-arm64`）与 `eeglayoutlab`（`noarch: python`）Conda 包、客户端静态包与 Showcase 归档、`THIRD_PARTY_WEB_LICENSES.txt` 及 `SHA256SUMS.txt`，通过 `mike` 将 `0.2`（别名 `latest`）写入 `docs-versions` 分支，并创建 **Draft GitHub Release**。
3. **最终人工核验**：
   - 将 `eeglayoutlab-data-base-1.0.0.{tar,json}` 与 `eeglayoutlab-data-scalp-node-table-1.0.0.{tar,json}` 上传至目标记录/Release，在一台干净的 Mac 或 Linux 环境中实测三行安装（`conda create` -> `eeglayoutlab quickstart --smoke`）通过后，再手动点击 Publish Release。
