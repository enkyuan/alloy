import SwiftUI

struct ContentView: View {
    @State private var authService = AuthService()
    private var integrationService = IntegrationService.shared
    @State private var showIntegrations = false
    @State private var hasCompletedOnboarding = false
    private let onboardingCompletionPrefix = "milo.onboarding.completed."

    var body: some View {
        Group {
            if authService.isRestoringSession {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if authService.isAuthenticated && hasCompletedOnboarding {
                HomeView(authService: authService, integrationService: integrationService)
            } else {
                OnboardingView(authService: authService)
                    .sheet(isPresented: onboardingSheetBinding, onDismiss: {
                        handleIntegrationsDismissed()
                    }) {
                        IntegrationsView(authService: authService, integrationService: integrationService, isOnboarding: true)
                    }
                    .onAppear {
                        refreshOnboardingState()
                        updateIntegrationSheetPresentation()
                    }
                    .onChange(of: authService.currentUser?.id) { _, _ in
                        refreshOnboardingState()
                        updateIntegrationSheetPresentation()
                    }
                    .onChange(of: authService.isAuthenticated) { _, _ in
                        refreshOnboardingState()
                        updateIntegrationSheetPresentation()
                    }
                    .onChange(of: hasCompletedOnboarding) { _, _ in
                        updateIntegrationSheetPresentation()
                    }
            }
        }
    }

    private var onboardingSheetBinding: Binding<Bool> {
        Binding(
            get: { showIntegrations && authService.isAuthenticated && !hasCompletedOnboarding },
            set: { showIntegrations = $0 }
        )
    }

    private func updateIntegrationSheetPresentation() {
        let shouldPresent = authService.isAuthenticated && !hasCompletedOnboarding
        if showIntegrations != shouldPresent {
            showIntegrations = shouldPresent
        }
    }

    private func handleIntegrationsDismissed() {
        guard authService.isAuthenticated else {
            showIntegrations = false
            return
        }
        persistOnboardingCompletion()
    }

    private func refreshOnboardingState() {
        guard let userID = authService.currentUser?.id else {
            hasCompletedOnboarding = false
            return
        }
        hasCompletedOnboarding = UserDefaults.standard.bool(forKey: onboardingCompletionKey(for: userID))
    }

    private func persistOnboardingCompletion() {
        guard let userID = authService.currentUser?.id else { return }
        UserDefaults.standard.set(true, forKey: onboardingCompletionKey(for: userID))
        hasCompletedOnboarding = true
    }

    private func onboardingCompletionKey(for userID: String) -> String {
        "\(onboardingCompletionPrefix)\(userID)"
    }
}
