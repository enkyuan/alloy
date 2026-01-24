import SwiftUI

struct ContentView: View {
    @State private var authService = AuthService()
    private var integrationService = IntegrationService.shared
    @State private var showIntegrations = false
    @State private var hasCompletedOnboarding = false

    var body: some View {
        Group {
            if authService.isAuthenticated && hasCompletedOnboarding {
                HomeView(authService: authService, integrationService: integrationService)
            } else {
                OnboardingView(authService: authService)
                    .sheet(isPresented: $showIntegrations, onDismiss: {
                        if authService.isAuthenticated {
                            hasCompletedOnboarding = true
                        }
                    }) {
                        IntegrationsView(authService: authService, integrationService: integrationService, isOnboarding: true)
                    }
                    .onChange(of: authService.isAuthenticated) { _, isAuthenticated in
                        if isAuthenticated {
                            showIntegrations = true
                        }
                    }
            }
        }
    }
}


