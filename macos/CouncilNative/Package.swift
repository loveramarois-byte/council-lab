// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "CouncilNative",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "CouncilNative", targets: ["CouncilNative"]),
    ],
    targets: [
        .executableTarget(
            name: "CouncilNative",
            path: "Sources/CouncilNative"
        ),
        .testTarget(
            name: "CouncilNativeTests",
            dependencies: ["CouncilNative"]
        ),
    ],
    swiftLanguageVersions: [.v5]
)
