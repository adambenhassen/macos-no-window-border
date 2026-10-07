import Foundation

/// Allows at most `maxRestarts` automatic daemon restarts within `window` seconds.
public struct RestartPolicy {
    public let maxRestarts: Int
    public let window: TimeInterval
    private var restarts: [Date] = []

    public init(maxRestarts: Int = 3, window: TimeInterval = 300) {
        self.maxRestarts = maxRestarts
        self.window = window
    }

    public mutating func allowRestart(at now: Date) -> Bool {
        restarts.removeAll { now.timeIntervalSince($0) >= window }
        guard restarts.count < maxRestarts else { return false }
        restarts.append(now)
        return true
    }
}
