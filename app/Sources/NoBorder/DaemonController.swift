import AppKit
import Foundation
import NoBorderCore

/// Runs the bundled noborder.py daemon, tracks its status for the menu, restarts it after a
/// crash (at most 3 times in 5 minutes) and appends its output to the log file.
@MainActor
final class DaemonController: ObservableObject {
    @Published private(set) var status: DaemonStatus = .off
    @Published private(set) var enabled: Bool

    private var process: Process?
    private var userStopped = false
    private var onStopped: [() -> Void] = []
    private var lastLine = ""
    private var lines = LineBuffer()
    private var policy = RestartPolicy()
    private let log = DaemonController.openLog()

    init() {
        enabled = UserDefaults.standard.object(forKey: "enabled") as? Bool ?? true
        if enabled { start() }
    }

    func setEnabled(_ on: Bool) {
        enabled = on
        UserDefaults.standard.set(on, forKey: "enabled")
        if on { start() } else { stop {} }
    }

    /// Stops the daemon (it restores changed windows), then quits the app.
    func quit() {
        stop { NSApplication.shared.terminate(nil) }
    }

    private func start() {
        guard process == nil else { return }
        guard let python = DaemonController.xcodePython() else { fail("Xcode missing"); return }
        guard let script = Bundle.main.path(forResource: "noborder", ofType: "py") else {
            fail("noborder.py missing from the app bundle")
            return
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = [script]
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil  // EOF
                return
            }
            Task { @MainActor in self?.received(data) }
        }
        p.terminationHandler = { [weak self] proc in
            let code = proc.terminationStatus
            Task { @MainActor in self?.terminated(code) }
        }
        userStopped = false
        lastLine = ""
        lines = LineBuffer()
        status = .starting
        do {
            try p.run()
        } catch {
            fail("can't start the daemon: \(error.localizedDescription)")
            return
        }
        process = p
    }

    private func stop(then done: @escaping () -> Void) {
        guard let p = process else {
            if case .fatal = status {} else { status = .off }
            done()
            return
        }
        userStopped = true
        onStopped.append(done)
        p.terminate()  // SIGTERM: the daemon restores changed windows, then exits
        let pid = p.processIdentifier
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
            guard let self, self.process === p else { return }
            kill(pid, SIGKILL)
        }
    }

    private func received(_ data: Data) {
        log?.write(data)
        for line in lines.append(data) {
            if !line.isEmpty { lastLine = line }
            guard let parsed = parseStatusLine(line) else { continue }
            if parsed == .note("stopped") { continue }
            status = parsed
        }
    }

    private func terminated(_ code: Int32) {
        process = nil
        if userStopped {
            status = .off
            let callbacks = onStopped
            onStopped = []
            callbacks.forEach { $0() }
            return
        }
        if case .fatal(let reason) = status {
            fail(reason)
            return
        }
        if policy.allowRestart(at: Date()) {
            status = .note("Daemon exited (code \(code)); restarting in 5 s")
            DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
                guard let self, self.enabled, self.process == nil else { return }
                self.start()
            }
        } else {
            status = .crashed(lastLine: lastLine)
        }
    }

    private func fail(_ reason: String) {
        status = .fatal(reason)
        enabled = false
        UserDefaults.standard.set(false, forKey: "enabled")
    }

    /// Xcode's python3, which can import the LLDB module. nil if Xcode isn't selected.
    private static func xcodePython() -> String? {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/xcode-select")
        p.arguments = ["-p"]
        let pipe = Pipe()
        p.standardOutput = pipe
        do {
            try p.run()
        } catch {
            return nil
        }
        p.waitUntilExit()
        guard p.terminationStatus == 0 else { return nil }
        let dir = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let python = dir + "/usr/bin/python3"
        return FileManager.default.isExecutableFile(atPath: python) ? python : nil
    }

    /// ~/Library/Logs/macos-no-window-border.log, opened for appending. nil disables logging.
    private static func openLog() -> FileHandle? {
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/macos-no-window-border.log")
        if !FileManager.default.fileExists(atPath: url.path) {
            guard FileManager.default.createFile(atPath: url.path, contents: nil) else { return nil }
        }
        guard let handle = FileHandle(forWritingAtPath: url.path) else { return nil }
        handle.seekToEndOfFile()
        return handle
    }
}
