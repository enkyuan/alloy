import GoogleSignIn
import Supabase
import SwiftData
import SwiftUI
import UIKit

@main
struct MiloApp: App {
    @State private var liveActivityManager = LiveActivityManager.shared
    @StateObject private var themeManager = ThemeManager.shared
    @SwiftUI.Environment(\.scenePhase) var scenePhase

    init() {
        if let clientID = Bundle.main.object(forInfoDictionaryKey: "GIDClientID") as? String {
            let serverClientID =
                Bundle.main.object(forInfoDictionaryKey: "GIDServerClientID") as? String

            let config: GIDConfiguration
            if let serverID = serverClientID, !serverID.isEmpty {
                print(
                    "Google Sign-In configured with client ID: \(clientID) and server ID: \(serverID)"
                )
                config = GIDConfiguration(clientID: clientID, serverClientID: serverID)
            } else {
                print("Google Sign-In configured with client ID: \(clientID)")
                config = GIDConfiguration(clientID: clientID)
            }

            GIDSignIn.sharedInstance.configuration = config

            Task { @MainActor in
                try? await Task.sleep(nanoseconds: 2_000_000_000)

                guard UIApplication.shared.applicationState == .active else {
                    print("App not active, skipping Google Sign-In restoration")
                    return
                }

                do {
                    let user = try await GIDSignIn.sharedInstance.restorePreviousSignIn()
                    print(
                        "Restored previous Google Sign-In for: \(user.profile?.email ?? "unknown")")
                } catch {
                    print("No previous sign-in to restore: \(error.localizedDescription)")
                }
            }
        } else {
            print("Warning: GIDClientID not found in Info.plist")
        }

        LiveActivityManager.shared.start()

        Task {
            do {
                try await MCPService.shared.connect()
            } catch {
                print("Failed to connect to MCP: \(error)")
            }
        }
    }

    var sharedModelContainer: ModelContainer = {
        let schema = Schema([])
        let modelConfiguration = ModelConfiguration(schema: schema, isStoredInMemoryOnly: false)

        do {
            return try ModelContainer(for: schema, configurations: [modelConfiguration])
        } catch {
            fatalError("Could not create ModelContainer: \(error)")
        }
    }()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(themeManager)
                .preferredColorScheme(themeManager.currentTheme.colorScheme)
                .onOpenURL { url in
                    print("Received URL: \(url.absoluteString)")

                    if GIDSignIn.sharedInstance.handle(url) {
                        print("Google Sign-In handled the URL")
                        return
                    }

                    if url.scheme == "milo" {
                        if url.host == "spotify" || url.host == "gmail" || url.host == "discord"
                            || url.host == "todoist" || url.host == "calendly"
                            || url.host == "spotify-return"
                        {
                            print("Integration callback detected: \(url.host ?? "unknown")")
                            // IntegrationService will handle this via ASWebAuthenticationSession callback
                            return
                        }

                        if url.host == "spotify-login-callback" {
                            print("Spotify App Remote callback detected")
                            SpotifyAppService.shared.handleCallback(url)
                            return
                        }
                    }

                    print("Passing to Supabase for handling")
                    Task {
                        do {
                            try await supabase.auth.session(from: url)
                        } catch {
                            print("Supabase session error: \(error)")
                        }
                    }
                }
        }
        .modelContainer(sharedModelContainer)
        .onChange(of: scenePhase) { oldPhase, newPhase in
            switch newPhase {
            case .active:
                print("App active")
            case .background:
                print("App entering background, keeping Spotify connected for playback")
            // Keep connection alive for background playback control
            case .inactive:
                print("App inactive")
            // Brief transition state, no action needed
            @unknown default:
                break
            }
        }
    }
}
