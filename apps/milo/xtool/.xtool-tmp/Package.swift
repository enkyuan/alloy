// swift-tools-version: 6.0
import PackageDescription
let package = Package(
    name: "havenos-Builder",
    platforms: [
        .iOS("26.0"),
    ],
    dependencies: [
        .package(name: "RootPackage", path: "../.."),
    ],
    targets: [
        .executableTarget(
    name: "havenos-App",
    dependencies: [
        .product(name: "havenos", package: "RootPackage"),
    ],
    linkerSettings: [
    .unsafeFlags([
        "-Xlinker", "-rpath", "-Xlinker", "@executable_path/Frameworks",
    ]),
]
)
    ]
)
