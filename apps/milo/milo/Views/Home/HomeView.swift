import SwiftUI

struct HomeView: View {

    @Bindable var authService: AuthService
    @Bindable var integrationService: IntegrationService
    @State private var assistantViewModel = AssistantViewModel()
    @State private var isLoadingIntegrations = true


    var body: some View {
        Group {
            if isLoadingIntegrations {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                BottomNavigation(
                    firstPage: (icon: "waveform", view: mainView),
                    secondPage: (
                        icon: "gear",
                        view: SettingsView(
                            authService: authService,
                            integrationService: integrationService
                        )
                    ),
                    authService: authService,
                    assistantViewModel: assistantViewModel,
                    integrationService: integrationService
                )
            }
        }
        .task(id: authService.currentUser?.id) {
            await loadIntegrations()
        }
    }


    @ViewBuilder
    private var mainView: some View {
        if integrationService.hasConnectedIntegrations {
            NavigationStack {
                AssistantView(authService: authService, viewModel: assistantViewModel)
                    .navigationTitle("Assistant")
                    .navigationBarTitleDisplayMode(.inline)
            }
        } else {
            ContentUnavailableView {
                Label("No Integrations Yet", systemImage: "app.connected.to.app.below.fill")
            } description: {
                Text("Link your favorite services to get started.")
            }
        }
    }


    private func loadIntegrations() async {
        isLoadingIntegrations = true
        do {
            try await integrationService.fetchConnectedIntegrations(authService: authService)
        } catch {
            if Environment.isDebugLoggingEnabled {
                print("Failed to fetch integrations: \(error)")
            }
        }
        isLoadingIntegrations = false
    }
}
