import SwiftUI

/// Root view that routes between authenticated and unauthenticated states
struct ContentView: View {
    @State private var authService = AuthenticationService()
    @State private var showIntegrations = false
    @State private var hasCompletedOnboarding = false
    
    var body: some View {
        Group {
            if authService.isAuthenticated && hasCompletedOnboarding {
                HomeView(authService: authService)
            } else {
                OnboardingView(authService: authService)
                    .sheet(isPresented: $showIntegrations, onDismiss: {
                        // Complete onboarding when integrations modal is dismissed
                        if authService.isAuthenticated {
                            hasCompletedOnboarding = true
                        }
                    }) {
                        IntegrationsView(authService: authService, isOnboarding: true)
                    }
                    .onChange(of: authService.isAuthenticated) { _, isAuthenticated in
                        if isAuthenticated {
                            // Show integrations modal after authentication
                            showIntegrations = true
                        }
                    }
            }
        }
    }
}

// MARK: - Previews

#Preview("Content View") {
    ContentView()
}

