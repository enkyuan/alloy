import SwiftUI

/// Main home screen after authentication with stepper navigation
struct HomeView: View {
    // MARK: - Properties

    @Bindable var authService: AuthenticationService
    @State private var integrationService = IntegrationService()
    @State private var assistantViewModel = AssistantViewModel()
    @State private var isLoadingIntegrations = true

    // MARK: - Body

    var body: some View {
        Group {
            if isLoadingIntegrations {
                // Show loading state while checking integrations
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                StepperNavigation.pages(
                    (icon: "waveform", view: mainView),
                    (icon: "gear", view: SettingsView(authService: authService)),
                    authService: authService,
                    assistantViewModel: assistantViewModel
                )
            }
        }
        .task {
            await loadIntegrations()
        }
    }
    
    // MARK: - View Components
    
    @ViewBuilder
    private var mainView: some View {
        if integrationService.hasConnectedIntegrations {
            AssistantView(authService: authService, viewModel: assistantViewModel)
        } else {
            IntegrationsEmptyStateView(authService: authService)
        }
    }
    
    // MARK: - Actions
    
    private func loadIntegrations() async {
        do {
            try await integrationService.fetchConnectedIntegrations(authService: authService)
        } catch {
            print("Failed to fetch integrations: \(error)")
        }
        isLoadingIntegrations = false
    }
}
