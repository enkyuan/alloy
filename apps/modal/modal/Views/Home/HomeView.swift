import SwiftUI

struct HomeView: View {

    @Bindable var authService: AuthService
    @Bindable var integrationService: IntegrationService
    @State private var assistantViewModel = AssistantViewModel()
    @State private var isLoadingIntegrations = true
    @State private var hasLoadedOnce = false


    var body: some View {
        Group {
            if isLoadingIntegrations {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                BottomNavigation.pages(
                    (icon: "waveform", view: mainView),
                    (icon: "gear", view: SettingsView(authService: authService, integrationService: integrationService)),
                    authService: authService,
                    assistantViewModel: assistantViewModel,
                    integrationService: integrationService
                )
            }
        }
        .task {
            if !hasLoadedOnce {
                await loadIntegrations()
                hasLoadedOnce = true
            } else {
                isLoadingIntegrations = false
            }
        }
    }


    @ViewBuilder
    private var mainView: some View {
        if integrationService.hasConnectedIntegrations {
            AssistantView(authService: authService, viewModel: assistantViewModel)
        } else {
            ContentUnavailableView {
                Label("No Integrations Yet", systemImage: "app.connected.to.app.below.fill")
            } description: {
                Text("Link your favorite services to get started.")
            }
        }
    }


    private func loadIntegrations() async {
        do {
            try await integrationService.fetchConnectedIntegrations(authService: authService)
        } catch {
            print("Failed to fetch integrations: \(error)")
        }
        isLoadingIntegrations = false
    }
}
