//
//  modalApp.swift
//  modal
//
//  Created by Enkang Yuan on 10/12/25.
//

import SwiftUI
import SwiftData
import GoogleSignIn
import Supabase

@main
struct modalApp: App {
    @State private var liveActivityManager = LiveActivityManager.shared

    init() {
        // Configure Google Sign-In with client ID from Info.plist
        if let clientID = Bundle.main.object(forInfoDictionaryKey: "GIDClientID") as? String {
            let config = GIDConfiguration(clientID: clientID)
            GIDSignIn.sharedInstance.configuration = config
            print("✅ Google Sign-In configured with client ID: \(clientID)")
            
            // Note: Gmail scopes will be requested during sign-in
            // This allows automatic Gmail integration without separate OAuth flow

            // Attempt to restore previous sign-in (helps initialize keychain access)
            GIDSignIn.sharedInstance.restorePreviousSignIn { user, error in
                if let error = error {
                    print("ℹ️ No previous sign-in to restore: \(error.localizedDescription)")
                } else if let user = user {
                    print("✅ Restored previous Google Sign-In for: \(user.profile?.email ?? "unknown")")
                } else {
                    print("ℹ️ No previous Google Sign-In session")
                }
            }
        } else {
            print("⚠️ Warning: GIDClientID not found in Info.plist")
        }

        // Start Live Activity on app launch
        LiveActivityManager.shared.start()
    }
    
    var sharedModelContainer: ModelContainer = {
        let schema = Schema([
            // Add your SwiftData models here
        ])
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
                .onOpenURL { url in
                    print("📱 Received URL: \(url.absoluteString)")
                    
                    // Handle Google Sign-In callback URL
                    if url.scheme == "com.googleusercontent.apps.1021220745951-7mavjjtg16o9i91eb7rtcc6smpg3m1b9" {
                        print("🔵 Google Sign-In callback detected")
                        GIDSignIn.sharedInstance.handle(url)
                        return
                    }
                    
                    // Handle integration callbacks (Spotify, Uber, etc.)
                    // ASWebAuthenticationSession handles these automatically, so we don't need to do anything
                    if url.scheme == "modal" {
                        if url.host == "spotify" || url.host == "uber" || url.host == "gmail" {
                            print("🟢 Integration callback detected: \(url.host ?? "unknown")")
                            print("   ASWebAuthenticationSession will handle this automatically")
                            // Don't pass to Supabase - let ASWebAuthenticationSession handle it
                            return
                        }
                    }
                    
                    // For all other URLs, pass to Supabase to handle OAuth callbacks
                    print("🟣 Passing to Supabase for handling")
                    Task {
                        do {
                            try await SupabaseConfig.shared.auth.session(from: url)
                        } catch {
                            print("❌ Supabase session error: \(error)")
                        }
                    }
                }
        }
        .modelContainer(sharedModelContainer)
    }
}
