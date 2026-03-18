import SwiftUI

struct ContentView: View {
    @State private var authService = AuthService()
    private var integrationService = IntegrationService.shared
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
                    .sheet(isPresented: onboardingSheetBinding) {
                        IntegrationsView(
                            authService: authService,
                            integrationService: integrationService,
                            isOnboarding: true
                        )
                    }
                    .task(id: authService.currentUser?.id) {
                        refreshOnboardingState()
                    }
            }
        }
    }

    private var onboardingSheetBinding: Binding<Bool> {
        Binding(
            get: { authService.isAuthenticated && !hasCompletedOnboarding },
            set: { isPresented in
                if !isPresented {
                    handleIntegrationsDismissed()
                }
            }
        )
    }

    private func handleIntegrationsDismissed() {
        guard authService.isAuthenticated else {
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
