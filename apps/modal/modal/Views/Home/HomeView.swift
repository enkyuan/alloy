import SwiftUI

/// Main home screen after authentication with stepper navigation
struct HomeView: View {
    // MARK: - Properties

    @Bindable var authService: AuthenticationService
    @Bindable var integrationService: IntegrationService
    @State private var assistantViewModel = AssistantViewModel()
    @State private var isLoadingIntegrations = true
    @State private var hasLoadedOnce = false

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
                    (icon: "gear", view: SettingsView(authService: authService, integrationService: integrationService)),
                    authService: authService,
                    assistantViewModel: assistantViewModel,
                    integrationService: integrationService
                )
            }
        }
        .task {
            // Only load if not already loaded
            if !hasLoadedOnce {
                await loadIntegrations()
                hasLoadedOnce = true
            } else {
                isLoadingIntegrations = false
            }
        }
    }
    
    // MARK: - View Components
    
    @ViewBuilder
    private var mainView: some View {
        if integrationService.hasConnectedIntegrations {
            AssistantView(authService: authService, viewModel: assistantViewModel)
        } else {
            IntegrationsEmptyStateView(authService: authService, integrationService: integrationService)
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
