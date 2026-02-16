// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "capns-interop-router-swift",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "capns-interop-router-swift", targets: ["RouterMain"])
    ],
    dependencies: [
        .package(path: "../../../../../capns-objc")
    ],
    targets: [
        .executableTarget(
            name: "RouterMain",
            dependencies: [
                .product(name: "Bifaci", package: "capns-objc")
            ],
            path: "Sources"
        )
    ]
)
