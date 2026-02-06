// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "capns-interop-plugin-swift",
    platforms: [
        .macOS(.v13)
    ],
    dependencies: [
        .package(path: "../../../../../../../capns-objc")
    ],
    targets: [
        .executableTarget(
            name: "capns-interop-plugin-swift",
            dependencies: [
                .product(name: "capns-objc", package: "capns-objc")
            ],
            path: "Sources"
        )
    ]
)
