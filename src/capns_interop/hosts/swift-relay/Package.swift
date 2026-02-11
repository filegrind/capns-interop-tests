// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "capns-interop-relay-host-swift",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(path: "../../../../../capns-objc"),
        .package(url: "https://github.com/unrelentingtech/SwiftCBOR.git", from: "0.4.7"),
    ],
    targets: [
        .executableTarget(
            name: "capns-interop-relay-host-swift",
            dependencies: [
                .product(name: "CapNs", package: "capns-objc"),
                .product(name: "CapNsCbor", package: "capns-objc"),
                .product(name: "SwiftCBOR", package: "SwiftCBOR"),
            ],
            path: "Sources"
        ),
    ]
)
