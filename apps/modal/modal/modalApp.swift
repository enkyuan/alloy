import GoogleSignIn
import Supabase
import SwiftData
import SwiftUI
import UIKit

@main
struct ModalApp: App {
    @State private var liveActivityManager = LiveActivityManager.shared
    @StateObject private var themeManager = ThemeManager.shared

    init() {
        if let clientID = Bundle.main.object(forInfoDictionaryKey: "GIDClientID") as? String {
            let config = GIDConfiguration(clientID: clientID)
            GIDSignIn.sharedInstance.configuration = config
            print("Google Sign-In configured with client ID: \(clientID)")

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

                    if url.scheme
                        == "com.googleusercontent.apps.1021220745951-7mavjjtg16o9i91eb7rtcc6smpg3m1b9"
                    {
                        print("Google Sign-In callback detected")
                        GIDSignIn.sharedInstance.handle(url)
                        return
                    }

                    if url.scheme == "modal" {
                        if url.host == "spotify" || url.host == "gmail" {
                            print("Integration callback detected: \(url.host ?? "unknown")")
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
    }
}
