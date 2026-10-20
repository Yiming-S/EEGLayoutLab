import AppKit
import WebKit
import Darwin

// Compile with: swiftc -parse-as-library -target arm64-apple-macos14.0 App.swift -o EEGLayoutLab
// The app bundle supplies Resources/node/bin/node and Resources/desktop/bootstrap.mjs.
// --smoke-test loads the real UI, reports DOM/WebGL diagnostics, then quits cleanly.

private enum Text {
    static let chinese = Locale.preferredLanguages.first?.hasPrefix("zh") == true
    static func value(_ english: String, _ chinese: String) -> String { self.chinese ? chinese : english }
}

private struct LocalOrigin {
    let port: Int

    init?(_ url: URL) {
        guard url.scheme == "http", url.host == "127.0.0.1",
              url.user == nil, url.password == nil,
              let port = url.port, (1...65535).contains(port) else { return nil }
        self.port = port
    }

    func contains(_ url: URL?) -> Bool {
        guard let url else { return false }
        return url.scheme == "http" && url.host == "127.0.0.1" && url.port == port
            && url.user == nil && url.password == nil
    }

    func contains(_ origin: WKSecurityOrigin) -> Bool {
        origin.protocol == "http" && origin.host == "127.0.0.1" && origin.port == port
    }

    func containsBlob(_ url: URL?) -> Bool {
        guard let url, url.scheme == "blob" else { return false }
        return contains(URL(string: String(url.absoluteString.dropFirst(5))))
    }
}

@MainActor
private final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate,
    NSToolbarDelegate, NSToolbarItemValidation, NSMenuItemValidation,
    WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {

    private let name = "EEG Layout Lab"
    private let smokeTest = CommandLine.arguments.contains("--smoke-test")
    private var window: NSWindow!
    private var webView: WKWebView!
    private var overlay: NSView!
    private var startupTitle: NSTextField!
    private var startupMessage: NSTextField!
    private var progress: NSProgressIndicator!
    private var recoveryButtons: NSStackView!
    private var backItem: NSToolbarItem?
    private var forwardItem: NSToolbarItem?
    private var reloadItem: NSToolbarItem?
    private var observations: [NSKeyValueObservation] = []
    private var process: Process?
    private var outputPipe: Pipe?
    private var errorPipe: Pipe?
    private var stdoutBuffer = Data()
    private var generation = 0
    private var stopping = false
    private var quitting = false
    private var restartAfterStop = false
    private var sharedServer = false
    private var didDisplayPage = false
    private var reportedFailure = false
    private var smokeFailed = false
    private var origin: LocalOrigin?
    private var homeURL: URL?
    private var findText = ""
    private var logHandle: FileHandle?
    private var logURL: URL?
    private var activeDownloads: [ObjectIdentifier: WKDownload] = [:]
    private struct DownloadLocation {
        let temporaryDirectory: URL
        let temporaryURL: URL
        let destinationURL: URL
    }
    private var downloadLocations: [ObjectIdentifier: DownloadLocation] = [:]

    private var userDataURL: URL {
        if let value = ProcessInfo.processInfo.environment["EEG_DESKTOP_USER_DATA"], !value.isEmpty {
            return URL(fileURLWithPath: value, isDirectory: true)
        }
        return FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(name, isDirectory: true)
    }

    private var logsURL: URL { userDataURL.appendingPathComponent("logs", isDirectory: true) }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if !smokeTest, let identifier = Bundle.main.bundleIdentifier,
           let existing = NSRunningApplication.runningApplications(withBundleIdentifier: identifier)
            .first(where: { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier && !$0.isTerminated }) {
            existing.activate(options: [.activateAllWindows])
            NSApp.terminate(nil)
            return
        }
        setupLog()
        buildMenus()
        buildWindow()
        NSApp.activate(ignoringOtherApps: true)
        startBackend()
        if smokeTest {
            DispatchQueue.main.asyncAfter(deadline: .now() + 600) { [weak self] in
                guard let self, !self.quitting else { return }
                self.fail(Text.value("Startup smoke test timed out after 600 seconds.", "启动测试在 600 秒后超时。"))
            }
        }
    }

    private func setupLog() {
        do {
            try FileManager.default.createDirectory(at: logsURL, withIntermediateDirectories: true)
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyyMMdd-HHmmss"
            let url = logsURL.appendingPathComponent("desktop-\(formatter.string(from: Date()))-\(getpid()).log")
            guard FileManager.default.createFile(atPath: url.path, contents: nil) else { return }
            logHandle = try FileHandle(forWritingTo: url)
            logURL = url
            log("Starting \(name); macOS \(ProcessInfo.processInfo.operatingSystemVersionString)")
        } catch {
            FileHandle.standardError.write(Data("Could not open desktop log: \(error.localizedDescription)\n".utf8))
        }
    }

    private func log(_ message: String) {
        let line = "[\(ISO8601DateFormatter().string(from: Date()))] \(message)\n"
        try? logHandle?.write(contentsOf: Data(line.utf8))
    }

    private func diagnostic(_ type: String, _ fields: [String: Any] = [:]) {
        var object = fields
        object["type"] = type
        if let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) {
            FileHandle.standardOutput.write(data + Data([10]))
        }
    }

    private func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1400, height: 950),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = name
        window.minSize = NSSize(width: 900, height: 650)
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.tabbingMode = .disallowed
        window.setFrameAutosaveName("EEGLayoutLab.MainWindow")
        window.center()
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        // WebGL and the standard WebKit protections retain their platform defaults.
        // No script-message handlers, custom schemes, or native JavaScript bridge are installed.
        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        webView.translatesAutoresizingMaskIntoConstraints = false
        let content = NSView()
        window.contentView = content
        content.addSubview(webView)
        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            webView.topAnchor.constraint(equalTo: content.topAnchor),
            webView.bottomAnchor.constraint(equalTo: content.bottomAnchor)
        ])
        buildStartupOverlay(in: content)
        let toolbar = NSToolbar(identifier: "EEGLayoutLab.Navigation")
        toolbar.delegate = self
        toolbar.displayMode = .iconOnly
        toolbar.allowsUserCustomization = false
        window.toolbar = toolbar
        window.toolbarStyle = .unified
        observations = [
            webView.observe(\.canGoBack, options: [.new]) { [weak self] _, _ in
                DispatchQueue.main.async { self?.updateNavigation() }
            },
            webView.observe(\.canGoForward, options: [.new]) { [weak self] _, _ in
                DispatchQueue.main.async { self?.updateNavigation() }
            }
        ]
        window.makeKeyAndOrderFront(nil)
    }

    private func buildStartupOverlay(in content: NSView) {
        overlay = NSView()
        overlay.translatesAutoresizingMaskIntoConstraints = false
        overlay.wantsLayer = true
        overlay.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        content.addSubview(overlay)
        NSLayoutConstraint.activate([
            overlay.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            overlay.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            overlay.topAnchor.constraint(equalTo: content.topAnchor),
            overlay.bottomAnchor.constraint(equalTo: content.bottomAnchor)
        ])
        let icon = NSImageView()
        icon.image = NSApp.applicationIconImage
        icon.imageScaling = .scaleProportionallyUpOrDown
        icon.widthAnchor.constraint(equalToConstant: 88).isActive = true
        icon.heightAnchor.constraint(equalToConstant: 88).isActive = true
        startupTitle = NSTextField(labelWithString: name)
        startupTitle.font = .systemFont(ofSize: 26, weight: .semibold)
        startupTitle.alignment = .center
        startupMessage = NSTextField(wrappingLabelWithString: "")
        startupMessage.font = .systemFont(ofSize: 14)
        startupMessage.textColor = .secondaryLabelColor
        startupMessage.alignment = .center
        startupMessage.isSelectable = true
        startupMessage.widthAnchor.constraint(equalToConstant: 580).isActive = true
        progress = NSProgressIndicator()
        progress.style = .bar
        progress.minValue = 0
        progress.maxValue = 1
        progress.isIndeterminate = true
        progress.widthAnchor.constraint(equalToConstant: 360).isActive = true
        recoveryButtons = NSStackView(views: [
            NSButton(title: Text.value("Retry", "重试"), target: self, action: #selector(retry)),
            NSButton(title: Text.value("Open Logs", "打开日志"), target: self, action: #selector(openLogs)),
            NSButton(title: Text.value("Quit", "退出"), target: NSApp, action: #selector(NSApplication.terminate(_:)))
        ])
        recoveryButtons.spacing = 12
        recoveryButtons.isHidden = true
        let stack = NSStackView(views: [icon, startupTitle, startupMessage, progress, recoveryButtons])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 20
        stack.translatesAutoresizingMaskIntoConstraints = false
        overlay.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: overlay.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: overlay.centerYAnchor, constant: -28)
        ])
    }

    private func buildMenus() {
        let main = NSMenu()
        let appMenu = NSMenu(title: name)
        addMenu(main, submenu: appMenu)
        addItem(appMenu, Text.value("About EEG Layout Lab", "关于 EEG Layout Lab"), #selector(showAbout), "")
        appMenu.addItem(.separator())
        let services = NSMenu(title: Text.value("Services", "服务"))
        addMenu(appMenu, submenu: services)
        NSApp.servicesMenu = services
        appMenu.addItem(.separator())
        addItem(appMenu, Text.value("Hide EEG Layout Lab", "隐藏 EEG Layout Lab"), #selector(NSApplication.hide(_:)), "h", target: NSApp)
        let hideOthers = addItem(appMenu, Text.value("Hide Others", "隐藏其他"), #selector(NSApplication.hideOtherApplications(_:)), "h", target: NSApp)
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        addItem(appMenu, Text.value("Show All", "显示全部"), #selector(NSApplication.unhideAllApplications(_:)), "", target: NSApp)
        appMenu.addItem(.separator())
        addItem(appMenu, Text.value("Quit EEG Layout Lab", "退出 EEG Layout Lab"), #selector(NSApplication.terminate(_:)), "q", target: NSApp)

        let file = NSMenu(title: Text.value("File", "文件"))
        addMenu(main, submenu: file)
        addItem(file, Text.value("Open Data Folder…", "打开数据文件夹…"), #selector(openDataFolder), "")
        addItem(file, Text.value("Open Logs…", "打开日志…"), #selector(openLogs), "")
        file.addItem(.separator())
        addItem(file, Text.value("Close Window", "关闭窗口"), #selector(NSWindow.performClose(_:)), "w", target: nil)

        let edit = NSMenu(title: Text.value("Edit", "编辑"))
        addMenu(main, submenu: edit)
        addItem(edit, Text.value("Undo", "撤销"), Selector(("undo:")), "z", target: nil)
        let redo = addItem(edit, Text.value("Redo", "重做"), Selector(("redo:")), "z", target: nil)
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        addItem(edit, Text.value("Cut", "剪切"), #selector(NSText.cut(_:)), "x", target: nil)
        addItem(edit, Text.value("Copy", "复制"), #selector(NSText.copy(_:)), "c", target: nil)
        addItem(edit, Text.value("Paste", "粘贴"), #selector(NSText.paste(_:)), "v", target: nil)
        addItem(edit, Text.value("Select All", "全选"), #selector(NSText.selectAll(_:)), "a", target: nil)
        edit.addItem(.separator())
        addItem(edit, Text.value("Find…", "查找…"), #selector(showFind), "f")
        addItem(edit, Text.value("Find Next", "查找下一个"), #selector(findNext), "g")
        let previous = addItem(edit, Text.value("Find Previous", "查找上一个"), #selector(findPrevious), "g")
        previous.keyEquivalentModifierMask = [.command, .shift]

        let view = NSMenu(title: Text.value("View", "显示"))
        addMenu(main, submenu: view)
        addItem(view, Text.value("Back", "后退"), #selector(goBack), "[")
        addItem(view, Text.value("Forward", "前进"), #selector(goForward), "]")
        addItem(view, Text.value("Reload", "重新加载"), #selector(reload), "r")
        view.addItem(.separator())
        addItem(view, Text.value("Zoom In", "放大"), #selector(zoomIn), "+")
        addItem(view, Text.value("Zoom Out", "缩小"), #selector(zoomOut), "-")
        addItem(view, Text.value("Actual Size", "实际大小"), #selector(resetZoom), "0")
        view.addItem(.separator())
        let fullScreen = addItem(view, Text.value("Enter Full Screen", "进入全屏幕"), #selector(NSWindow.toggleFullScreen(_:)), "f", target: nil)
        fullScreen.keyEquivalentModifierMask = [.command, .control]

        let windows = NSMenu(title: Text.value("Window", "窗口"))
        addMenu(main, submenu: windows)
        addItem(windows, Text.value("Minimize", "最小化"), #selector(NSWindow.performMiniaturize(_:)), "m", target: nil)
        addItem(windows, Text.value("Zoom", "缩放"), #selector(NSWindow.performZoom(_:)), "", target: nil)
        windows.addItem(.separator())
        addItem(windows, Text.value("Bring All to Front", "前置全部窗口"), #selector(NSApplication.arrangeInFront(_:)), "", target: NSApp)
        NSApp.windowsMenu = windows
        NSApp.mainMenu = main
    }

    private func addMenu(_ parent: NSMenu, submenu: NSMenu) {
        let item = NSMenuItem(title: submenu.title, action: nil, keyEquivalent: "")
        item.submenu = submenu
        parent.addItem(item)
    }

    @discardableResult
    private func addItem(_ menu: NSMenu, _ title: String, _ action: Selector, _ key: String,
                         target: AnyObject? = nil) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        // App actions resolve to this delegate; standard edit/window actions use the responder chain.
        item.target = target ?? (responds(to: action) ? self : nil)
        menu.addItem(item)
        return item
    }

    func toolbarDefaultItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        [.init("back"), .init("forward"), .init("reload"), .flexibleSpace]
    }

    func toolbarAllowedItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        toolbarDefaultItemIdentifiers(toolbar)
    }

    func toolbar(_ toolbar: NSToolbar, itemForItemIdentifier id: NSToolbarItem.Identifier,
                 willBeInsertedIntoToolbar flag: Bool) -> NSToolbarItem? {
        let item = NSToolbarItem(itemIdentifier: id)
        item.target = self
        switch id.rawValue {
        case "back":
            item.label = Text.value("Back", "后退")
            item.image = NSImage(systemSymbolName: "chevron.left", accessibilityDescription: item.label)
            item.action = #selector(goBack)
            backItem = item
        case "forward":
            item.label = Text.value("Forward", "前进")
            item.image = NSImage(systemSymbolName: "chevron.right", accessibilityDescription: item.label)
            item.action = #selector(goForward)
            forwardItem = item
        case "reload":
            item.label = Text.value("Reload", "重新加载")
            item.image = NSImage(systemSymbolName: "arrow.clockwise", accessibilityDescription: item.label)
            item.action = #selector(reload)
            reloadItem = item
        default: return nil
        }
        item.toolTip = item.label
        return item
    }

    func validateToolbarItem(_ item: NSToolbarItem) -> Bool {
        if item.action == #selector(goBack) { return didDisplayPage && webView.canGoBack }
        if item.action == #selector(goForward) { return didDisplayPage && webView.canGoForward }
        return homeURL != nil && !stopping
    }

    func validateMenuItem(_ item: NSMenuItem) -> Bool {
        if item.action == #selector(goBack) { return didDisplayPage && webView.canGoBack }
        if item.action == #selector(goForward) { return didDisplayPage && webView.canGoForward }
        if [#selector(showFind), #selector(findNext), #selector(findPrevious), #selector(zoomIn),
            #selector(zoomOut), #selector(resetZoom)].contains(item.action) { return didDisplayPage }
        if item.action == #selector(reload) { return homeURL != nil && !stopping }
        return true
    }

    private func updateNavigation() {
        backItem?.isEnabled = didDisplayPage && webView.canGoBack
        forwardItem?.isEnabled = didDisplayPage && webView.canGoForward
        reloadItem?.isEnabled = homeURL != nil && !stopping
    }

    private func startBackend() {
        guard !quitting else { return }
        generation += 1
        let token = generation
        stopping = false
        sharedServer = false
        didDisplayPage = false
        reportedFailure = false
        origin = nil
        homeURL = nil
        stdoutBuffer.removeAll()
        overlay.isHidden = false
        recoveryButtons.isHidden = true
        progress.isHidden = false
        progress.isIndeterminate = true
        progress.startAnimation(nil)
        startupTitle.stringValue = Text.value("Starting EEG Layout Lab", "正在启动 EEG Layout Lab")
        startupMessage.stringValue = Text.value("Preparing the local workspace…", "正在准备本地工作区…")
        webView.stopLoading()
        updateNavigation()
        guard let resources = Bundle.main.resourceURL else {
            fail(Text.value("The application resources are missing.", "应用程序资源缺失。"))
            return
        }
        let node = resources.appendingPathComponent("node/bin/node")
        let bootstrap = resources.appendingPathComponent("desktop/bootstrap.mjs")
        guard FileManager.default.isExecutableFile(atPath: node.path),
              FileManager.default.fileExists(atPath: bootstrap.path) else {
            fail(Text.value("The bundled runtime is incomplete. Reinstall the application from its disk image.",
                            "应用内置运行环境不完整。请从磁盘映像重新安装应用程序。"))
            return
        }
        let child = Process()
        child.executableURL = node
        child.arguments = [bootstrap.path]
        child.currentDirectoryURL = resources
        let inherited = ProcessInfo.processInfo.environment
        let allowed = ["HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
                       "EEG_DESKTOP_USER_DATA", "EEG_DESKTOP_RESOURCES"]
        var environment = inherited.filter { allowed.contains($0.key) }
        environment["PATH"] = node.deletingLastPathComponent().path + ":/usr/bin:/bin:/usr/sbin:/sbin"
        environment["NODE_ENV"] = "production"
        child.environment = environment
        child.standardInput = FileHandle.nullDevice
        let output = Pipe()
        let errors = Pipe()
        child.standardOutput = output
        child.standardError = errors
        outputPipe = output
        errorPipe = errors
        // One serial reader delivers every stdout message before the process-exit
        // callback. A fast shared-server helper can write ready and exit together.
        let outputReader = DispatchQueue(label: "com.yimingshen.eeglayoutlab.stdout.\(token)")
        outputReader.async { [weak self] in
            while true {
                let data = output.fileHandleForReading.availableData
                if data.isEmpty { break }
                DispatchQueue.main.async {
                    guard let self, self.generation == token else { return }
                    self.consumeOutput(data)
                }
            }
        }
        errors.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async {
                guard let self, self.generation == token else { return }
                self.log("backend stderr: " + String(decoding: data, as: UTF8.self))
            }
        }
        child.terminationHandler = { [weak self] terminated in
            outputReader.async {
                DispatchQueue.main.async {
                    guard let self, self.generation == token else { return }
                    self.backendExited(terminated.terminationStatus)
                }
            }
        }
        process = child
        do {
            try child.run()
            try? output.fileHandleForWriting.close()
            log("Backend started, pid \(child.processIdentifier)")
            diagnostic("shell-started", ["pid": child.processIdentifier, "logPath": logURL?.path ?? ""])
        } catch {
            try? output.fileHandleForWriting.close()
            clearProcessHandles()
            fail(Text.value("The local runtime could not start: ", "本地运行环境无法启动：") + error.localizedDescription)
        }
    }

    private func consumeOutput(_ data: Data) {
        stdoutBuffer.append(data)
        while let newline = stdoutBuffer.firstIndex(of: 10) {
            let line = Data(stdoutBuffer[..<newline])
            stdoutBuffer.removeSubrange(...newline)
            guard !line.isEmpty else { continue }
            log("backend: " + String(decoding: line, as: UTF8.self))
            guard let message = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
                  let type = message["type"] as? String else { continue }
            switch type {
            case "progress":
                if let text = message["message"] as? String { startupMessage.stringValue = text }
                if let fraction = message["fraction"] as? Double, fraction.isFinite {
                    progress.isIndeterminate = false
                    progress.doubleValue = min(1, max(0, fraction))
                } else {
                    progress.isIndeterminate = true
                    progress.startAnimation(nil)
                }
                diagnostic("shell-progress", message.filter { $0.key != "type" })
            case "ready":
                guard !stopping else { continue }
                guard let rawURL = message["url"] as? String,
                      let url = URL(string: rawURL), let local = LocalOrigin(url) else {
                    fail(Text.value("The local runtime returned an invalid address.", "本地运行环境返回了无效地址。"))
                    continue
                }
                origin = local
                homeURL = url
                // Installed-workspace reuse is not server sharing: only this
                // explicit protocol flag transfers server ownership elsewhere.
                sharedServer = message["sharedServer"] as? Bool == true
                startupMessage.stringValue = Text.value("Loading the workspace…", "正在加载工作区…")
                progress.isIndeterminate = true
                progress.startAnimation(nil)
                webView.load(URLRequest(url: url))
                diagnostic("shell-ready", ["url": rawURL, "sharedServer": sharedServer])
                updateNavigation()
            case "error":
                fail(message["message"] as? String ?? Text.value("The local runtime reported an error.", "本地运行环境报告错误。"))
            default: break
            }
        }
        // Protect the shell against malformed unbounded output from a failing process.
        if stdoutBuffer.count > 1_048_576 {
            log("Discarded an oversized unterminated backend output line.")
            stdoutBuffer.removeAll()
        }
    }

    private func backendExited(_ status: Int32) {
        log("Backend exited with status \(status)")
        clearProcessHandles()
        if quitting {
            NSApp.reply(toApplicationShouldTerminate: true)
        } else if restartAfterStop {
            restartAfterStop = false
            startBackend()
        } else if sharedServer && status == 0 && !reportedFailure {
            log("Shared-server helper completed; the existing server remains owned by its original application.")
        } else if !stopping && !reportedFailure {
            fail(Text.value("The local runtime stopped (exit code \(status)). Your saved workspace remains in the application data folder.",
                            "本地运行环境已停止（退出代码 \(status)）。已保存的工作区仍保留在应用数据文件夹中。"))
        }
    }

    private func clearProcessHandles() {
        outputPipe?.fileHandleForReading.readabilityHandler = nil
        errorPipe?.fileHandleForReading.readabilityHandler = nil
        outputPipe = nil
        errorPipe = nil
        process = nil
    }

    private func stopBackend() {
        // A shared helper never owns the existing server or its workers.
        if sharedServer {
            stopping = true
            cancelDownloads()
            if quitting { NSApp.reply(toApplicationShouldTerminate: true) }
            else if restartAfterStop {
                restartAfterStop = false
                startBackend()
            }
            return
        }
        guard let process, process.isRunning else {
            if quitting { NSApp.reply(toApplicationShouldTerminate: true) }
            return
        }
        stopping = true
        cancelDownloads()
        process.terminate()
        let token = generation
        // Bootstrap shuts down its worker process group before exiting. This bounds a stuck shutdown.
        DispatchQueue.main.asyncAfter(deadline: .now() + 10) { [weak self, weak process] in
            guard let self, self.generation == token, let process, process.isRunning else { return }
            self.log("Backend did not stop after SIGTERM; sending SIGKILL.")
            kill(process.processIdentifier, SIGKILL)
        }
    }

    private func fail(_ message: String) {
        log("ERROR: " + message)
        diagnostic("shell-error", ["message": message, "logPath": logURL?.path ?? ""])
        didDisplayPage = false
        reportedFailure = true
        homeURL = nil
        origin = nil
        webView?.stopLoading()
        overlay?.isHidden = false
        startupTitle?.stringValue = Text.value("EEG Layout Lab could not continue", "EEG Layout Lab 无法继续运行")
        startupMessage?.stringValue = message
        progress?.stopAnimation(nil)
        progress?.isHidden = true
        recoveryButtons?.isHidden = false
        updateNavigation()
        if smokeTest {
            smokeFailed = true
            NSApp.terminate(nil)
        }
    }

    @objc private func retry() {
        if let process, process.isRunning {
            restartAfterStop = true
            recoveryButtons.isHidden = true
            startupMessage.stringValue = Text.value("Restarting the local runtime…", "正在重新启动本地运行环境…")
            stopBackend()
        } else {
            startBackend()
        }
    }

    @objc private func openDataFolder() {
        NSWorkspace.shared.open(userDataURL)
    }

    @objc private func openLogs() {
        try? FileManager.default.createDirectory(at: logsURL, withIntermediateDirectories: true)
        NSWorkspace.shared.open(logsURL)
    }

    @objc private func showAbout() {
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: name,
            .credits: NSAttributedString(string: Text.value(
                "EEG electrode layout design and evaluation.\nProject collaborators: Yiming Shen, PhD · Yi Wang, PhD\nNative macOS window · Local computation · WebKit visualization",
                "EEG 电极布局设计与评估。\n项目合作者：Yiming Shen, PhD · Yi Wang, PhD\nmacOS 原生窗口 · 本地计算 · WebKit 可视化"))
        ])
    }

    @objc private func goBack() { webView.goBack() }
    @objc private func goForward() { webView.goForward() }
    @objc private func reload() {
        if overlay.isHidden { webView.reload() }
        else if let homeURL { webView.load(URLRequest(url: homeURL)) }
    }
    @objc private func zoomIn() { webView.pageZoom = min(2, webView.pageZoom + 0.1) }
    @objc private func zoomOut() { webView.pageZoom = max(0.5, webView.pageZoom - 0.1) }
    @objc private func resetZoom() { webView.pageZoom = 1 }

    @objc private func showFind() {
        let alert = NSAlert()
        alert.messageText = Text.value("Find in Workspace", "在工作区中查找")
        alert.addButton(withTitle: Text.value("Find", "查找"))
        alert.addButton(withTitle: Text.value("Cancel", "取消"))
        let field = NSSearchField(frame: NSRect(x: 0, y: 0, width: 360, height: 26))
        field.stringValue = findText
        alert.accessoryView = field
        alert.window.initialFirstResponder = field
        alert.beginSheetModal(for: window) { [weak self] response in
            guard response == .alertFirstButtonReturn, let self else { return }
            self.findText = field.stringValue
            self.performFind(backwards: false)
        }
    }
    @objc private func findNext() { findText.isEmpty ? showFind() : performFind(backwards: false) }
    @objc private func findPrevious() { findText.isEmpty ? showFind() : performFind(backwards: true) }
    private func performFind(backwards: Bool) {
        guard !findText.isEmpty else { return }
        let configuration = WKFindConfiguration()
        configuration.backwards = backwards
        configuration.wraps = true
        configuration.caseSensitive = false
        webView.find(findText, configuration: configuration) { result in
            if !result.matchFound { NSSound.beep() }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { window?.makeKeyAndOrderFront(nil) }
        return true
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitting { return .terminateLater }
        quitting = true
        log("Application quitting")
        cancelDownloads()
        if sharedServer { return .terminateNow }
        guard process?.isRunning == true else { return .terminateNow }
        stopBackend()
        return .terminateLater
    }
    func applicationWillTerminate(_ notification: Notification) {
        try? logHandle?.close()
        if smokeTest && smokeFailed { Darwin.exit(1) }
    }

    // Navigation is confined to the exact origin returned by this launch's backend.
    // Same-origin blob URLs are download-only; no file/data/javascript page navigation is allowed.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url, let origin else { decisionHandler(.cancel); return }
        let trustedSource = origin.contains(action.sourceFrame.securityOrigin)
        if origin.containsBlob(url), trustedSource {
            decisionHandler(.download)
        } else if origin.contains(url) {
            if action.shouldPerformDownload && trustedSource {
                decisionHandler(.download)
            } else if action.targetFrame == nil {
                webView.load(action.request)
                decisionHandler(.cancel)
            } else {
                decisionHandler(.allow)
            }
        } else {
            if (url.scheme == "https" || url.scheme == "http"), action.targetFrame?.isMainFrame != false {
                NSWorkspace.shared.open(url)
            }
            decisionHandler(.cancel)
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        guard let origin, origin.contains(response.response.url) || origin.containsBlob(response.response.url) else {
            decisionHandler(.cancel)
            return
        }
        let disposition = (response.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition") ?? ""
        decisionHandler(!response.canShowMIMEType || disposition.lowercased().hasPrefix("attachment") ? .download : .allow)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard let url = action.request.url, let origin else { return nil }
        if origin.containsBlob(url), origin.contains(action.sourceFrame.securityOrigin) {
            webView.startDownload(using: action.request) { [weak self] download in self?.track(download) }
        } else if origin.contains(url) {
            if action.shouldPerformDownload {
                webView.startDownload(using: action.request) { [weak self] download in self?.track(download) }
            } else { webView.load(action.request) }
        } else if url.scheme == "https" || url.scheme == "http" {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard origin?.contains(webView.url) == true else { return }
        didDisplayPage = true
        overlay.isHidden = true
        progress.stopAnimation(nil)
        window.makeFirstResponder(webView)
        updateNavigation()
        diagnostic("shell-page-loaded", ["url": webView.url?.absoluteString ?? "", "title": webView.title ?? ""])
        if smokeTest {
            webView.evaluateJavaScript("JSON.stringify({title:document.title,domReady:document.readyState,bodyChildren:document.body?.children.length||0,webGL:!!document.createElement('canvas').getContext('webgl2')})") { [weak self] result, error in
                guard let self else { return }
                self.diagnostic("shell-smoke", ["result": result ?? NSNull(), "error": error?.localizedDescription ?? ""])
                if let text = result as? String, let data = text.data(using: .utf8),
                   let details = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    self.smokeFailed = error != nil || details["webGL"] as? Bool != true
                        || (details["bodyChildren"] as? Int ?? 0) == 0
                } else { self.smokeFailed = true }
                NSApp.terminate(nil)
            }
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        handleNavigationError(error)
    }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        handleNavigationError(error)
    }
    private func handleNavigationError(_ error: Error) {
        let native = error as NSError
        // WebKit reports an intentional navigation-to-download conversion as frame load interruption.
        guard !quitting, native.code != NSURLErrorCancelled,
              !(native.domain == "WebKitErrorDomain" && native.code == 102) else { return }
        fail(Text.value("The workspace could not load: ", "工作区无法加载：") + error.localizedDescription)
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        fail(Text.value("The visualization process stopped. Retry to reopen the workspace.", "可视化进程已停止。请重试以重新打开工作区。"))
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        guard origin?.contains(frame.securityOrigin) == true else { completionHandler(nil); return }
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = true
        panel.beginSheetModal(for: window) { response in completionHandler(response == .OK ? panel.urls : nil) }
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        guard origin?.contains(frame.securityOrigin) == true else { completionHandler(); return }
        let alert = NSAlert()
        alert.messageText = name
        alert.informativeText = message
        alert.addButton(withTitle: Text.value("OK", "好"))
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        guard origin?.contains(frame.securityOrigin) == true else { completionHandler(false); return }
        let alert = NSAlert()
        alert.messageText = name
        alert.informativeText = message
        alert.addButton(withTitle: Text.value("OK", "确定"))
        alert.addButton(withTitle: Text.value("Cancel", "取消"))
        alert.beginSheetModal(for: window) { response in completionHandler(response == .alertFirstButtonReturn) }
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (String?) -> Void) {
        guard origin?.contains(frame.securityOrigin) == true else { completionHandler(nil); return }
        let alert = NSAlert()
        alert.messageText = name
        alert.informativeText = prompt
        alert.addButton(withTitle: Text.value("OK", "确定"))
        alert.addButton(withTitle: Text.value("Cancel", "取消"))
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 360, height: 24))
        field.stringValue = defaultText ?? ""
        alert.accessoryView = field
        alert.window.initialFirstResponder = field
        alert.beginSheetModal(for: window) { response in
            completionHandler(response == .alertFirstButtonReturn ? field.stringValue : nil)
        }
    }

    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                 initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
                 decisionHandler: @escaping (WKPermissionDecision) -> Void) { decisionHandler(.deny) }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { track(download) }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { track(download) }
    private func track(_ download: WKDownload) {
        activeDownloads[ObjectIdentifier(download)] = download
        download.delegate = self
    }

    private func cancelDownloads() {
        for (id, download) in activeDownloads {
            download.cancel { [weak self] _ in
                DispatchQueue.main.async {
                    guard let self else { return }
                    if let location = self.downloadLocations.removeValue(forKey: id) {
                        try? FileManager.default.removeItem(at: location.temporaryDirectory)
                    }
                    self.activeDownloads.removeValue(forKey: id)
                }
            }
        }
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        guard let origin, origin.contains(response.url) || origin.containsBlob(response.url) else {
            completionHandler(nil)
            activeDownloads.removeValue(forKey: ObjectIdentifier(download))
            return
        }
        let panel = NSSavePanel()
        panel.canCreateDirectories = true
        panel.title = Text.value("Save Export", "保存导出文件")
        let filename = (suggestedFilename as NSString).lastPathComponent
        panel.nameFieldStringValue = filename.isEmpty ? "export" : filename
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        panel.beginSheetModal(for: window) { [weak self] result in
            guard let self, result == .OK, let destination = panel.url else {
                completionHandler(nil)
                self?.activeDownloads.removeValue(forKey: ObjectIdentifier(download))
                return
            }
            do {
                // WebKit requires a nonexistent destination. Stage alongside the chosen file,
                // then replace only after a successful transfer and the save panel's confirmation.
                let directory = destination.deletingLastPathComponent()
                    .appendingPathComponent(".eeg-layout-lab-download-\(UUID().uuidString)", isDirectory: true)
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
                let temporary = directory.appendingPathComponent("download")
                self.downloadLocations[ObjectIdentifier(download)] = DownloadLocation(
                    temporaryDirectory: directory, temporaryURL: temporary, destinationURL: destination)
                completionHandler(temporary)
            } catch {
                completionHandler(nil)
                self.activeDownloads.removeValue(forKey: ObjectIdentifier(download))
                self.showDownloadError(error)
            }
        }
    }

    func download(_ download: WKDownload, willPerformHTTPRedirection response: HTTPURLResponse,
                  newRequest request: URLRequest, decisionHandler: @escaping (WKDownload.RedirectPolicy) -> Void) {
        decisionHandler(origin?.contains(request.url) == true ? .allow : .cancel)
    }

    func downloadDidFinish(_ download: WKDownload) {
        let id = ObjectIdentifier(download)
        defer { activeDownloads.removeValue(forKey: id) }
        guard let location = downloadLocations.removeValue(forKey: id) else { return }
        do {
            if FileManager.default.fileExists(atPath: location.destinationURL.path) {
                _ = try FileManager.default.replaceItemAt(location.destinationURL, withItemAt: location.temporaryURL)
            } else {
                try FileManager.default.moveItem(at: location.temporaryURL, to: location.destinationURL)
            }
            try? FileManager.default.removeItem(at: location.temporaryDirectory)
            log("Saved export: \(location.destinationURL.path)")
        } catch {
            // Preserve a completed download if moving it fails, so it can be recovered from the log.
            log("Completed download retained at \(location.temporaryURL.path)")
            showDownloadError(error)
        }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        let id = ObjectIdentifier(download)
        if let location = downloadLocations.removeValue(forKey: id) {
            try? FileManager.default.removeItem(at: location.temporaryDirectory)
        }
        activeDownloads.removeValue(forKey: id)
        if (error as NSError).code != NSURLErrorCancelled { showDownloadError(error) }
    }

    private func showDownloadError(_ error: Error) {
        log("Download error: \(error.localizedDescription)")
        guard !quitting else { return }
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = Text.value("The export could not be saved", "无法保存导出文件")
        alert.informativeText = error.localizedDescription
        alert.addButton(withTitle: Text.value("OK", "好"))
        alert.beginSheetModal(for: window)
    }
}

@main
private enum EEGLayoutLab {
    @MainActor static func main() {
        let application = NSApplication.shared
        application.setActivationPolicy(.regular)
        let delegate = AppDelegate()
        application.delegate = delegate
        withExtendedLifetime(delegate) { application.run() }
    }
}
