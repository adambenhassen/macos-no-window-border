import NoBorderCore
import XCTest

final class LineBufferTests: XCTestCase {
    func testSplitsCompleteLinesAndKeepsTheRest() {
        var buffer = LineBuffer()
        XCTAssertEqual(buffer.append(Data("status: run".utf8)), [])
        XCTAssertEqual(buffer.append(Data("ning, 1 windows\nlog a\nlog".utf8)), ["status: running, 1 windows", "log a"])
        XCTAssertEqual(buffer.append(Data(" b\n".utf8)), ["log b"])
    }

    func testEmptyLines() {
        var buffer = LineBuffer()
        XCTAssertEqual(buffer.append(Data("\n\nx\n".utf8)), ["", "", "x"])
    }
}
