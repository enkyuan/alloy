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
                    // Handle Google Sign-In callback URL
                    GIDSignIn.sharedInstance.handle(url)
                }
        }
        .modelContainer(sharedModelContainer)
    }
}
