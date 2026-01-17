// swift-tools-version: 6.0
import PackageDescription
let package = Package(
    name: "milo-Builder",
    platforms: [
        .iOS("26.0"),
    ],
    dependencies: [
        .package(name: "RootPackage", path: "../.."),
    ],
    targets: [
        .executableTarget(
    name: "milo-App",
    dependencies: [
        .product(name: "milo", package: "RootPackage"),
    ],
    linkerSettings: [
    .unsafeFlags([
        "-Xlinker", "-rpath", "-Xlinker", "@executable_path/Frameworks",
    ]),
]
)
    ]
)
