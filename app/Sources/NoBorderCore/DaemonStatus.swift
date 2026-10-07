import Foundation

/// What the menu shows about the daemon. Fatal states turn the toggle off and are not retried.
public enum DaemonStatus: Equatable {
    case off
    case starting
    case running(windows: Int)
    case note(String)              // non-fatal daemon status, e.g. "Dock attach failed"
    case fatal(String)             // "SIP enabled", "Xcode missing", or an app-side setup error
    case crashed(lastLine: String)

    public var menuText: String {
        switch self {
        case .off: return "Off"
        case .starting: return "Starting…"
        case .running(let n): return n == 1 ? "Running: 1 window squared" : "Running: \(n) windows squared"
        case .note(let text): return text
        case .fatal(let reason): return "Can't run: \(reason)"
        case .crashed(let line): return line.isEmpty ? "Stopped: crashed" : "Stopped: crashed (\(line))"
        }
    }
}

/// Parses one line of daemon output. Returns nil for ordinary log lines.
public func parseStatusLine(_ line: String) -> DaemonStatus? {
    let prefix = "status: "
    guard line.hasPrefix(prefix) else { return nil }
    let body = String(line.dropFirst(prefix.count))
    if body == "SIP enabled" || body == "Xcode missing" { return .fatal(body) }
    let running = "running, ", windows = " windows"
    if body.hasPrefix(running), body.hasSuffix(windows),
       let n = Int(body.dropFirst(running.count).dropLast(windows.count)) {
        return .running(windows: n)
    }
    return .note(body)
}
