// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "milo",
    platforms: [
        .iOS(.v26)
    ],
    products: [
        .library(name: "milo", targets: ["milo"])
    ],
    dependencies: [
        .package(url: "https://github.com/supabase-community/supabase-swift.git", from: "2.0.0"),
        .package(name: "GoogleSignIn", url: "https://github.com/google/GoogleSignIn-iOS", from: "7.1.0"),
    ],
    targets: [
        .target(
            name: "milo",
            dependencies: [
                .product(name: "Supabase", package: "supabase-swift"),
                .product(name: "Auth", package: "supabase-swift"),
                .product(name: "GoogleSignIn", package: "GoogleSignIn"),
            ],
            path: "milo",
            exclude: [
                "Info.plist",
                "milo.entitlements",
                "Views/Home/milo.entitlements",
            ],
            resources: [
                .process("Assets.xcassets"),
            ]
        )
    ]
)
