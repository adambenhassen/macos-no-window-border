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
    private var quitting = false
    private var exitCode: Int32?  // set when the process has exited
    private var outputDone = false  // set when its output pipe reached EOF
    private var onStopped: [() -> Void] = []
    private var lastLine = ""
    private var lines = LineBuffer()
    private var policy = RestartPolicy()
    private var log = DaemonController.openLog()

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
        quitting = true
        stop { NSApplication.shared.terminate(nil) }
    }

    private func start() {
        guard process == nil else { return }
        guard let script = Bundle.main.path(forResource: "noborder", ofType: "py") else {
            fail("noborder.py missing from the app bundle")
            return
        }
        let p = Process()
        // xcrun runs the selected Xcode's python3 (it can import LLDB). An xcrun or python
        // failure before the daemon starts is treated as fatal in terminated(); the daemon
        // itself reports "status: Xcode missing" when LLDB can't load.
        p.executableURL = URL(fileURLWithPath: "/usr/bin/xcrun")
        p.arguments = ["python3", script]
        let pipe = Pipe()
        p.standardOutput = pipe
        p.standardError = pipe
        // Both handlers hop to the main queue in order (unlike unstructured Tasks); the exit is
        // acted on only after the output is complete, so the last lines are never lost or late.
        pipe.fileHandleForReading.readabilityHandler = { [weak self, weak p] handle in
            let data = handle.availableData
            let eof = data.isEmpty
            if eof { handle.readabilityHandler = nil }
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    guard let self, let p, p === self.process else { return }
                    if eof {
                        self.outputDone = true
                        self.finishIfDone()
                    } else {
                        self.received(data)
                    }
                }
            }
        }
        p.terminationHandler = { [weak self] proc in
            let code = proc.terminationStatus
            DispatchQueue.main.async {
                MainActor.assumeIsolated {
                    guard let self, proc === self.process else { return }
                    self.exitCode = code
                    self.finishIfDone()
                }
            }
        }
        userStopped = false
        exitCode = nil
        outputDone = false
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
        status = .stopping
        onStopped.append(done)
        p.terminate()  // SIGTERM: the daemon restores changed windows, then exits
        let pid = p.processIdentifier
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
            guard let self, self.process === p, self.exitCode == nil else { return }
            kill(pid, SIGKILL)
        }
    }

    private func received(_ data: Data) {
        if let log {
            do {
                try log.write(contentsOf: data)
            } catch {  // e.g. disk full: keep the daemon running, stop logging
                NSLog("NoBorder: stopped writing the daemon log: %@", error.localizedDescription)
                self.log = nil
            }
        }
        for line in lines.append(data) {
            if !line.isEmpty { lastLine = line }
            guard !userStopped, let parsed = parseStatusLine(line) else { continue }
            if parsed == .note("stopped") { continue }
            status = parsed
        }
    }

    private func finishIfDone() {
        guard outputDone, let code = exitCode else { return }
        terminated(code)
    }

    private func terminated(_ code: Int32) {
        process = nil
        if userStopped {
            status = .off
            let callbacks = onStopped
            onStopped = []
            callbacks.forEach { $0() }
            if enabled && !quitting { start() }  // re-enabled while the daemon was stopping
            return
        }
        if case .fatal(let reason) = status {
            fail(reason)
            return
        }
        if code != 0, status == .starting {  // exited before any "status:" line: xcrun/python failed
            fail(lastLine.isEmpty ? "can't start python3 via xcrun" : lastLine)
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
