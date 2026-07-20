import AppKit
import ApplicationServices
import Foundation
import OSLog

@main
final class WutheringWavesExternalLauncher: NSObject, NSApplicationDelegate {
    private static var retainedDelegate: WutheringWavesExternalLauncher?

    private lazy var gameURL = URL(fileURLWithPath: requiredConfiguration("MigrationGamePath"))
    private lazy var resourcesURL = URL(
        fileURLWithPath: requiredConfiguration("MigrationResourcesPath"),
        isDirectory: true
    )
    private lazy var gameBundleIdentifier = requiredConfiguration("MigrationGameBundleIdentifier")
    private lazy var warningDelay = max(
        15,
        (Bundle.main.object(forInfoDictionaryKey: "MigrationWarningDelay") as? NSNumber)?.doubleValue ?? 65
    )
    private let bookmarkKey = "AuthorizedResourcesBookmark"
    private lazy var logger = Logger(
        subsystem: Bundle.main.bundleIdentifier ?? "local.migrate-macos-app-data.launcher",
        category: "launcher"
    )

    private var warningTimer: Timer?
    private var gameLaunchTimer: Timer?
    private var gameLaunchDeadline = Date.distantPast
    private var warningDismissNotBefore = Date.distantFuture
    private var warningDeadline = Date.distantPast
    private var gamePID: pid_t?
    private var securityScopedResourcesURL: URL?

    static func main() {
        let application = NSApplication.shared
        let delegate = WutheringWavesExternalLauncher()
        retainedDelegate = delegate
        application.delegate = delegate
        application.run()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        logger.info("Launcher started")

        guard validateInstallation() else {
            NSApp.terminate(nil)
            return
        }

        let runningGames = NSRunningApplication.runningApplications(withBundleIdentifier: gameBundleIdentifier)
        guard runningGames.isEmpty else {
            showAlert(
                title: "Wuthering Waves is already running",
                message: "Quit the game completely, then open this launcher again."
            )
            NSApp.terminate(nil)
            return
        }

        guard let authorizedResourcesURL = authorizeResourcesDirectory() else {
            NSApp.terminate(nil)
            return
        }

        guard accessibilityPermissionIsAvailable() else {
            requestAccessibilityPermission()
            showAlert(
                title: "Accessibility permission required once",
                message: "Enable this launcher in System Settings → Privacy & Security → Accessibility, then open it again. The permission is used only to dismiss the harmless folder warning."
            )
            NSApp.terminate(nil)
            return
        }

        launchGame(with: authorizedResourcesURL)
    }

    func applicationWillTerminate(_ notification: Notification) {
        gameLaunchTimer?.invalidate()
        warningTimer?.invalidate()
        securityScopedResourcesURL?.stopAccessingSecurityScopedResource()
    }

    private func requiredConfiguration(_ key: String) -> String {
        guard let value = Bundle.main.object(forInfoDictionaryKey: key) as? String, !value.isEmpty else {
            fatalError("Missing Info.plist configuration: \(key)")
        }
        return value
    }

    private func validateInstallation() -> Bool {
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: gameURL.path, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            showAlert(title: "Game not found", message: "Expected app: \(gameURL.path)")
            return false
        }
        return true
    }

    private func authorizeResourcesDirectory() -> URL? {
        if let bookmarkedURL = resolveResourcesBookmark(), verifyResourcesDirectory(bookmarkedURL) {
            logger.info("Using saved Resources folder authorization")
            return bookmarkedURL
        }

        UserDefaults.standard.removeObject(forKey: bookmarkKey)
        return requestResourcesDirectoryAuthorization()
    }

    private func resolveResourcesBookmark() -> URL? {
        guard let bookmarkData = UserDefaults.standard.data(forKey: bookmarkKey) else {
            return nil
        }

        do {
            var isStale = false
            let url = try URL(
                resolvingBookmarkData: bookmarkData,
                options: [.withSecurityScope],
                relativeTo: nil,
                bookmarkDataIsStale: &isStale
            )
            guard isExpectedResourcesDirectory(url) else {
                logger.error("Saved folder authorization points to an unexpected path")
                return nil
            }
            _ = url.startAccessingSecurityScopedResource()
            securityScopedResourcesURL = url
            if isStale {
                try saveResourcesBookmark(for: url)
            }
            return url
        } catch {
            logger.error("Unable to resolve saved folder authorization: \(error.localizedDescription, privacy: .public)")
            return nil
        }
    }

    private func requestResourcesDirectoryAuthorization() -> URL? {
        NSApp.activate(ignoringOtherApps: true)

        let panel = NSOpenPanel()
        panel.title = "Authorize external Wuthering Waves resources"
        panel.message = "Select this exact Resources folder: \(resourcesURL.path)"
        panel.prompt = "Authorize This Folder"
        panel.directoryURL = resourcesURL
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = false
        panel.allowsMultipleSelection = false
        panel.resolvesAliases = true

        guard panel.runModal() == .OK, let selectedURL = panel.url else {
            showAlert(title: "Resources not authorized", message: "The game was not launched.")
            return nil
        }
        guard isExpectedResourcesDirectory(selectedURL) else {
            showAlert(title: "Wrong folder", message: "Select exactly: \(resourcesURL.path)")
            return nil
        }

        _ = selectedURL.startAccessingSecurityScopedResource()
        securityScopedResourcesURL = selectedURL
        guard verifyResourcesDirectory(selectedURL) else {
            showAlert(title: "Resources unavailable", message: "macOS still cannot read the selected folder.")
            return nil
        }

        do {
            try saveResourcesBookmark(for: selectedURL)
        } catch {
            logger.error("Unable to save folder authorization: \(error.localizedDescription, privacy: .public)")
            showAlert(title: "Authorization was not saved", message: error.localizedDescription)
            return nil
        }
        return selectedURL
    }

    private func saveResourcesBookmark(for url: URL) throws {
        let bookmarkData = try url.bookmarkData(
            options: [.withSecurityScope],
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        )
        UserDefaults.standard.set(bookmarkData, forKey: bookmarkKey)
    }

    private func isExpectedResourcesDirectory(_ url: URL) -> Bool {
        url.standardizedFileURL.resolvingSymlinksInPath().path
            == resourcesURL.standardizedFileURL.resolvingSymlinksInPath().path
    }

    private func verifyResourcesDirectory(_ url: URL) -> Bool {
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            return false
        }
        do {
            _ = try FileManager.default.contentsOfDirectory(
                at: url,
                includingPropertiesForKeys: nil,
                options: [.skipsHiddenFiles]
            )
            return true
        } catch {
            logger.error("Unable to read Resources directory: \(error.localizedDescription, privacy: .public)")
            return false
        }
    }

    private func accessibilityPermissionIsAvailable() -> Bool {
        AXIsProcessTrusted()
    }

    private func requestAccessibilityPermission() {
        let promptKey = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        let options = [promptKey: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
    }

    private func launchGame(with authorizedResourcesURL: URL) {
        let openTask = Process()
        openTask.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        openTask.arguments = ["-n", "-a", gameURL.path, authorizedResourcesURL.path]
        openTask.standardOutput = FileHandle.nullDevice
        openTask.standardError = FileHandle.nullDevice
        openTask.terminationHandler = { [weak self] task in
            DispatchQueue.main.async {
                guard let self else { return }
                guard task.terminationStatus == 0 else {
                    self.showAlert(title: "Launch failed", message: "The macOS open command failed.")
                    NSApp.terminate(nil)
                    return
                }
                self.startGameProcessMonitor()
            }
        }

        do {
            try openTask.run()
        } catch {
            showAlert(title: "Launch failed", message: error.localizedDescription)
            NSApp.terminate(nil)
        }
    }

    private func startGameProcessMonitor() {
        gameLaunchDeadline = Date().addingTimeInterval(20)
        gameLaunchTimer?.invalidate()
        gameLaunchTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] timer in
            guard let self else {
                timer.invalidate()
                return
            }
            if let application = NSRunningApplication.runningApplications(
                withBundleIdentifier: self.gameBundleIdentifier
            ).first {
                timer.invalidate()
                self.gamePID = application.processIdentifier
                let launchTime = Date()
                self.warningDismissNotBefore = launchTime.addingTimeInterval(self.warningDelay)
                self.warningDeadline = launchTime.addingTimeInterval(self.warningDelay + 60)
                self.startWarningMonitor()
                return
            }
            if Date() >= self.gameLaunchDeadline {
                timer.invalidate()
                self.showAlert(title: "Launch failed", message: "Timed out waiting for the game process.")
                NSApp.terminate(nil)
            }
        }
    }

    private func startWarningMonitor() {
        warningTimer?.invalidate()
        warningTimer = Timer.scheduledTimer(withTimeInterval: 0.35, repeats: true) { [weak self] timer in
            guard let self, let pid = self.gamePID else {
                timer.invalidate()
                NSApp.terminate(nil)
                return
            }
            guard Date() >= self.warningDismissNotBefore else { return }

            if self.dismissFolderWarning(in: pid) {
                timer.invalidate()
                self.logger.info("Dismissed the folder-open warning")
                NSRunningApplication(processIdentifier: pid)?.activate(options: [.activateAllWindows])
                DispatchQueue.main.asyncAfter(deadline: .now() + 1) {
                    NSApp.terminate(nil)
                }
                return
            }
            if Date() >= self.warningDeadline {
                timer.invalidate()
                self.logger.error("Timed out waiting for the folder-open warning")
                NSApp.terminate(nil)
            }
        }
    }

    private func dismissFolderWarning(in pid: pid_t) -> Bool {
        let appElement = AXUIElementCreateApplication(pid)
        guard let windows = arrayAttribute(kAXWindowsAttribute, from: appElement) else {
            return false
        }

        let warningPhrases = [
            "未能打开文稿", "打不开格式为", "could not be opened", "cannot open", "can't open"
        ]
        for window in windows {
            let visibleText = textContent(of: window, depth: 0).joined(separator: " ")
            let isExpectedWarning = visibleText.contains("Resources")
                && warningPhrases.contains(where: visibleText.localizedCaseInsensitiveContains)
            guard isExpectedWarning,
                  let button = findButton(namedAnyOf: ["好", "OK"], in: window, depth: 0) else {
                continue
            }
            return AXUIElementPerformAction(button, kAXPressAction as CFString) == .success
        }
        return false
    }

    private func arrayAttribute(_ attribute: String, from element: AXUIElement) -> [AXUIElement]? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else {
            return nil
        }
        return value as? [AXUIElement]
    }

    private func stringAttribute(_ attribute: String, from element: AXUIElement) -> String? {
        var value: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else {
            return nil
        }
        return value as? String
    }

    private func textContent(of element: AXUIElement, depth: Int) -> [String] {
        guard depth <= 10 else { return [] }
        var text: [String] = []
        for attribute in [kAXTitleAttribute, kAXValueAttribute, kAXDescriptionAttribute] {
            if let value = stringAttribute(attribute, from: element), !value.isEmpty {
                text.append(value)
            }
        }
        if let children = arrayAttribute(kAXChildrenAttribute, from: element) {
            for child in children {
                text.append(contentsOf: textContent(of: child, depth: depth + 1))
            }
        }
        return text
    }

    private func findButton(namedAnyOf names: [String], in element: AXUIElement, depth: Int) -> AXUIElement? {
        guard depth <= 10 else { return nil }
        let role = stringAttribute(kAXRoleAttribute, from: element)
        let labels = [
            stringAttribute(kAXTitleAttribute, from: element),
            stringAttribute(kAXValueAttribute, from: element),
            stringAttribute(kAXDescriptionAttribute, from: element),
        ].compactMap { $0 }
        if role == (kAXButtonRole as String), labels.contains(where: names.contains) {
            return element
        }
        if let children = arrayAttribute(kAXChildrenAttribute, from: element) {
            for child in children {
                if let match = findButton(namedAnyOf: names, in: child, depth: depth + 1) {
                    return match
                }
            }
        }
        return nil
    }

    private func showAlert(title: String, message: String) {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = title
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }
}
