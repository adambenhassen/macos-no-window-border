import NoBorderCore
import XCTest

final class RestartPolicyTests: XCTestCase {
    func testAllowsThreeRestartsPerFiveMinutes() {
        var policy = RestartPolicy()
        let t0 = Date(timeIntervalSince1970: 1000)
        XCTAssertTrue(policy.allowRestart(at: t0))
        XCTAssertTrue(policy.allowRestart(at: t0.addingTimeInterval(10)))
        XCTAssertTrue(policy.allowRestart(at: t0.addingTimeInterval(20)))
        XCTAssertFalse(policy.allowRestart(at: t0.addingTimeInterval(30)))
    }

    func testOldRestartsExpire() {
        var policy = RestartPolicy()
        let t0 = Date(timeIntervalSince1970: 1000)
        for i in 0..<3 { XCTAssertTrue(policy.allowRestart(at: t0.addingTimeInterval(Double(i)))) }
        XCTAssertTrue(policy.allowRestart(at: t0.addingTimeInterval(300)))
    }
}
