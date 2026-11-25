# EEG Layout Lab

首次安装请按照[源码安装说明](../docs/source-installation.zh-CN.md)完成模型数据、Python 计算环境和 `eeglayoutlab` 命令的安装。当前流程面向 Apple Silicon Mac。

For first-time setup, follow the [source installation instructions](../docs/source-installation.md): the model data, the Python computation environment and the `eeglayoutlab` command. The current setup targets Apple Silicon macOS.

## 构建界面 / Build the interface

在此 `webapp` 文件夹中运行：

Run from this `webapp` directory:

```sh
npm ci
npm run build
```

## 打开应用 / Open the application

应用由本地 Python 服务提供。在仓库根目录运行：

The application is served by the local Python service. From the repository root, run:

```sh
.venv/bin/eeglayoutlab serve ~/eeglayoutlab-workspace
```

命令会在浏览器中打开应用。使用期间保持终端运行，结束时按 **Control + C**。

It opens the application in your browser. Keep Terminal running while using the App. Press **Control + C** to stop it.

操作说明见 App 内的“文档 → 使用指南”。右上角可切换简体中文和英语。

In the App, open **Documentation → User Guide** for instructions. Use the upper-right language control to switch between English and Simplified Chinese.

## 开发 / Development

`npm run dev` 用 Vite 提供界面，并把 `/api` 和 `/open` 转发给正在运行的服务（`EEG_WORKSPACE=<工作区>` 或 `EEG_API_TARGET=http://127.0.0.1:<端口>`）；`EEG_NODE_API=1` 改为挂载旧版 Node 接口。`npm start` 运行旧版 Node 服务，冻结在标签 `node-host-freeze`，服务器部署见[部署说明](../docs/server-deployment.md)。

`npm run dev` serves the interface with Vite and forwards `/api` and `/open` to a running service (`EEG_WORKSPACE=<workspace>` or `EEG_API_TARGET=http://127.0.0.1:<port>`); `EEG_NODE_API=1` mounts the legacy Node API instead. `npm start` runs the legacy Node host, frozen for hosted deployments at the tag `node-host-freeze`; see [server deployment](../docs/server-deployment.md). See [CONTRIBUTING](../CONTRIBUTING.md#interface-development).
