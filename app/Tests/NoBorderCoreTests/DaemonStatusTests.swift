import NoBorderCore
import XCTest

final class DaemonStatusTests: XCTestCase {
    func testLogLinesAreNotStatus() {
        XCTAssertNil(parseStatusLine("2026-10-07 17:00:00 attached to Dock pid 1"))
    }

    func testRunning() {
        XCTAssertEqual(parseStatusLine("status: running, 3 windows"), .running(windows: 3))
        XCTAssertEqual(parseStatusLine("status: running, 0 windows"), .running(windows: 0))
    }

    func testFatal() {
        XCTAssertEqual(parseStatusLine("status: SIP enabled"), .fatal("SIP enabled"))
        XCTAssertEqual(parseStatusLine("status: Xcode missing"), .fatal("Xcode missing"))
    }

    func testOtherStatusIsANote() {
        XCTAssertEqual(parseStatusLine("status: Dock attach failed"), .note("Dock attach failed"))
    }

    func testMenuText() {
        XCTAssertEqual(DaemonStatus.running(windows: 1).menuText, "Running: 1 window squared")
        XCTAssertEqual(DaemonStatus.running(windows: 2).menuText, "Running: 2 windows squared")
        XCTAssertEqual(DaemonStatus.fatal("SIP enabled").menuText, "Can't run: SIP enabled")
        XCTAssertEqual(DaemonStatus.crashed(lastLine: "").menuText, "Stopped: crashed")
        XCTAssertEqual(DaemonStatus.crashed(lastLine: "boom").menuText, "Stopped: crashed (boom)")
        XCTAssertEqual(DaemonStatus.off.menuText, "Off")
    }
}
