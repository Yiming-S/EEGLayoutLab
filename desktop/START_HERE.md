# EEG Layout Lab · Mac desktop App

For Apple Silicon Macs running macOS 14 or newer.

[简体中文](START_HERE.zh-CN.md)

## Install

1. Open the [Google Drive download folder](https://drive.google.com/drive/folders/1Ry-neU-oySVoToIt07eFfBnemKrnewmK?usp=sharing) and download the `.dmg` desktop installer.
2. DMG: open the image and drag **EEG Layout Lab.app** into **Applications**. ZIP: extract the archive and move the App into Applications.
3. Open **EEG Layout Lab**.
4. On first launch, wait for the bundled environment and model data to be prepared. The App then opens automatically.

No separate Node.js, Python, Conda, or model-data installation is required. After installation, open the App directly from Applications.

## First-open system prompt

This test build uses an ad-hoc signature; it is not Developer ID signed or Apple notarized. If macOS cannot verify the developer, confirm that the installer came from the maintainer, attempt to open it once, then use **System Settings → Privacy & Security → Open Anyway** for this App.

If macOS reports a damaged file or malware, contact the maintainer to check the installer. See [Apple's opening instructions](https://support.apple.com/en-us/102445).

## Use

- **Results Library:** browse saved layouts, review their scores, and compare layouts.
- **Layout Design:** define regions, edit electrodes, or import coordinates, then calculate.
- **Signal Simulation:** choose sources, waveforms, and interference to compare received signals.
- **Upper-right language control:** switch between English and Simplified Chinese.
- **Documentation:** read the User Guide and Models & Methods.
- **Quit:** press **Command + Q**. Closing the window keeps the App running; click its Dock icon to reopen the window.

New results are saved locally. Use the App menu's **Open Data Folder** and **Open Logs** actions to locate saved files or collect details when reporting an issue.
