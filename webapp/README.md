# EEG Layout Lab

首次安装请按照[源码安装说明](../docs/source-installation.zh-CN.md)完成模型数据和 Python 计算环境的安装。当前流程面向 Apple Silicon Mac。

For first-time setup, follow the [source installation instructions](../docs/source-installation.md). The current setup targets Apple Silicon macOS.

服务器部署准备见[部署说明](../docs/server-deployment.md)。

For the planned hosted version, see [Server deployment preparation](../docs/server-deployment.md).

## 首次启动 / First launch

在此 `webapp` 文件夹中运行：

Run from this `webapp` directory:

```sh
npm ci
npm run dev
```

在浏览器打开 / Open in your browser: [http://127.0.0.1:3000](http://127.0.0.1:3000).

## 以后打开 / Subsequent launches

```sh
npm run dev
```

使用期间保持终端运行，结束时按 **Control + C**。

Keep Terminal running while using the App. Press **Control + C** to stop it.

操作说明见 App 内的“文档 → 使用指南”。右上角可切换简体中文和英语。

In the App, open **Documentation → User Guide** for instructions. Use the upper-right language control to switch between English and Simplified Chinese.
