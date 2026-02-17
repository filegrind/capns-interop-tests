// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "capns-interop-plugin-swift",
    platforms: [
        .macOS(.v13)
    ],
    dependencies: [
        .package(path: "../../../../../capns-objc"),
        .package(path: "../../../../../ops-objc"),
    ],
    targets: [
        .executableTarget(
            name: "capns-interop-plugin-swift",
            dependencies: [
                .product(name: "Bifaci", package: "capns-objc"),
                .product(name: "Ops", package: "ops-objc"),
            ],
            path: "Sources"
        )
    ]
)
