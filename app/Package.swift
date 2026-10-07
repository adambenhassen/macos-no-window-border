// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "NoBorder",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "NoBorderCore"),
        .executableTarget(name: "NoBorder", dependencies: ["NoBorderCore"]),
        .testTarget(name: "NoBorderCoreTests", dependencies: ["NoBorderCore"]),
    ]
)
