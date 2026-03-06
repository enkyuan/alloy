import SwiftUI

struct IntegrationsView: View {

    @Bindable var authService: AuthService
    @Bindable var integrationService: IntegrationService
    let isOnboarding: Bool
    @State private var showError = false
    @State private var errorMessage = ""
    @State private var showDisconnectAlert = false
    @State private var serviceToDisconnect: IntegrationService.ServiceType?
    @State private var isCheckingIntegrations = false
    @SwiftUI.Environment(\.dismiss) private var dismiss

    init(
        authService: AuthService, integrationService: IntegrationService, isOnboarding: Bool = false
    ) {
        self.authService = authService
        self.integrationService = integrationService
        self.isOnboarding = isOnboarding
    }

    private var hasConnectedIntegrations: Bool {
        integrationService.isConnected(.spotify) || integrationService.isConnected(.gmail)
            || integrationService.isConnected(.googleCalendar)
    }

    var body: some View {
        NavigationStack {
            mainContent
                .toolbar {
                    if !isOnboarding || !authService.isAuthenticated {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button(action: { dismiss() }) {
                                Image(systemName: "xmark")
                                    .font(.system(size: 16, weight: .semibold))
                                    .foregroundColor(.secondary)
                            }
                        }
                    }
                }
                .interactiveDismissDisabled(isOnboarding && authService.isAuthenticated)
                .task {
                    await refreshIntegrations()
                }
                .onChange(of: authService.isAuthenticated) { _, isAuthenticated in
                    if !isAuthenticated {
                        dismiss()
                    }
                }
                .alert("Error", isPresented: $showError) {
                    Button("OK") {}
                } message: {
                    Text(errorMessage)
                }
                .alert("Disconnect Service", isPresented: $showDisconnectAlert) {
                    Button("Cancel", role: .cancel) {}
                    Button("Disconnect", role: .destructive) {
                        if let service = serviceToDisconnect {
                            disconnectService(service)
                        }
                    }
                } message: {
                    if let service = serviceToDisconnect {
                        Text(
                            "Are you sure you want to disconnect \(service.displayName)? You can reconnect it anytime."
                        )
                    }
                }
        }
    }

    private var mainContent: some View {
        ScrollView {
            VStack(spacing: 20) {
                Text("Link your favorite apps to unlock Milo's full potential")
                    .font(.system(size: 16, weight: .regular))
                    .foregroundColor(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .fixedSize(horizontal: false, vertical: true)

                integrationsGrid
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .padding(.bottom, 20)
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            footerSection
        }
        .background(Color(uiColor: .systemBackground))
        .navigationTitle("Add Integrations")
        .navigationBarTitleDisplayMode(.large)
    }

    private var integrationsGrid: some View {
        VStack(spacing: 16) {
            Card.integration(
                iconName: "SpotifyIcon",
                serviceName: "Spotify",
                description: "Play music and manage playlists",
                isConnected: integrationService.isConnected(.spotify),
                action: { handleIntegration(.spotify) }
            )
            .opacity(isCheckingIntegrations ? 0.6 : 1.0)
            .animation(.easeInOut(duration: 0.2), value: isCheckingIntegrations)

            Card.integration(
                iconName: "GmailIcon",
                serviceName: "Gmail",
                description: isCheckingIntegrations ? "Checking status..." : "Read and send emails",
                isConnected: integrationService.isConnected(.gmail),
                action: { handleIntegration(.gmail) }
            )
            .opacity(isCheckingIntegrations ? 0.6 : 1.0)
            .animation(.easeInOut(duration: 0.2), value: isCheckingIntegrations)

            Card.integration(
                iconName: "GoogleCalendarIcon",
                serviceName: "Google Calendar",
                description: "Manage events and schedules",
                isConnected: integrationService.isConnected(.googleCalendar),
                action: { handleIntegration(.googleCalendar) }
            )
            .opacity(isCheckingIntegrations ? 0.6 : 1.0)
            .animation(.easeInOut(duration: 0.2), value: isCheckingIntegrations)

            Card.integration(
                iconName: "DiscordIcon",
                serviceName: "Discord",
                description: "Send messages and manage servers",
                isConnected: integrationService.isConnected(.discord),
                action: { handleIntegration(.discord) }
            )
            .opacity(isCheckingIntegrations ? 0.6 : 1.0)
            .animation(.easeInOut(duration: 0.2), value: isCheckingIntegrations)

            Card.integration(
                iconName: "TodoistIcon",
                serviceName: "Todoist",
                description: "Manage tasks and to-do lists",
                isConnected: integrationService.isConnected(.todoist),
                action: { handleIntegration(.todoist) }
            )
            .opacity(isCheckingIntegrations ? 0.6 : 1.0)
            .animation(.easeInOut(duration: 0.2), value: isCheckingIntegrations)

            Card.integration(
                iconName: "CalendlyIcon",
                serviceName: "Calendly",
                description: "Schedule and manage meetings",
                isConnected: integrationService.isConnected(.calendly),
                action: { handleIntegration(.calendly) }
            )
            .opacity(isCheckingIntegrations ? 0.6 : 1.0)
            .animation(.easeInOut(duration: 0.2), value: isCheckingIntegrations)

            Card.integration(
                iconName: "UberLogo",
                serviceName: "Uber",
                description: "Book rides and check trip status",
                isConnected: false,
                action: {}
            )
            .disabled(true)

            Card.integration(
                iconName: "DoorDashIcon",
                serviceName: "DoorDash",
                description: "Get food delivered to your door",
                isConnected: false,
                action: {}
            )
            .disabled(true)

            Card.integration(
                iconName: "InstacartIcon",
                serviceName: "Instacart",
                description: "Groceries delivered in minutes",
                isConnected: false,
                action: {}
            )
            .disabled(true)

            Card.integration(
                iconName: "AppleMusicIcon",
                serviceName: "Apple Music",
                description: "Listen to your favorite artists",
                isConnected: false,
                action: {}
            )
            .disabled(true)
        }
    }

    private var footerSection: some View {
        VStack(spacing: 0) {
            // Progressive blur overlay that blurs content behind
            ZStack {
                // Visual effect blur with progressive intensity
                VisualEffectView(effect: UIBlurEffect(style: .systemMaterial))
                    .frame(height: 80)

                // Gradient overlay for progressive fade to solid background
                LinearGradient(
                    stops: [
                        .init(color: .clear, location: 0.0),
                        .init(color: Color(uiColor: .systemBackground).opacity(0.4), location: 0.6),
                        .init(color: Color(uiColor: .systemBackground), location: 1.0),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .frame(height: 80)
            }
            .mask(
                LinearGradient(
                    stops: [
                        .init(color: .clear, location: 0.0),
                        .init(color: .black.opacity(0.3), location: 0.3),
                        .init(color: .black, location: 1.0),
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
            )

            // Button section with solid background
            Button(action: { dismiss() }) {
                Text(hasConnectedIntegrations ? "Continue" : "Skip for now")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity)
                    .frame(height: 56)
                    .background(hasConnectedIntegrations ? Color.green : Color.black)
                    .cornerRadius(16)
                    .animation(
                        .spring(response: 0.3, dampingFraction: 0.7),
                        value: hasConnectedIntegrations)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 20)
            .background(Color(uiColor: .systemBackground))
        }
    }

    private func handleIntegration(_ service: IntegrationService.ServiceType) {
        if integrationService.isConnected(service) {
            serviceToDisconnect = service
            showDisconnectAlert = true
        } else {
            connectService(service)
        }
    }

    private func connectService(_ service: IntegrationService.ServiceType) {
        Task {
            do {
                try await integrationService.connectService(service, authService: authService)
            } catch let error as IntegrationError {
                if case .notAuthenticated = error {
                    dismiss()
                    return
                }
                guard case .userCancelled = error else {
                    errorMessage =
                        "Failed to connect \(service.displayName): \(error.localizedDescription)"
                    showError = true
                    return
                }
                print("User cancelled \(service.displayName) connection")
            } catch {
                let nsError = error as NSError
                if nsError.domain == "com.apple.AuthenticationServices.WebAuthenticationSession"
                    && nsError.code == 1
                {
                    print("User cancelled OAuth flow")
                    return
                }
                errorMessage =
                    "Failed to connect \(service.displayName): \(error.localizedDescription)"
                showError = true
            }
        }
    }

    private func disconnectService(_ service: IntegrationService.ServiceType) {
        Task {
            do {
                try await integrationService.disconnectService(service, authService: authService)
            } catch let error as IntegrationError {
                if case .notAuthenticated = error {
                    dismiss()
                    return
                }
                errorMessage =
                    "Failed to disconnect \(service.displayName): \(error.localizedDescription)"
                showError = true
            } catch {
                errorMessage =
                    "Failed to disconnect \(service.displayName): \(error.localizedDescription)"
                showError = true
            }
        }
    }

    private func refreshIntegrations() async {
        isCheckingIntegrations = true
        defer { isCheckingIntegrations = false }

        do {
            try await integrationService.fetchConnectedIntegrations(authService: authService)
            print("Refreshed integrations")
        } catch let error as IntegrationError {
            if case .notAuthenticated = error {
                dismiss()
                return
            }
            print("Failed to refresh integrations: \(error.localizedDescription)")
        } catch {
            print("Failed to refresh integrations: \(error.localizedDescription)")
        }
    }

}

// MARK: - VisualEffectView Helper

private struct VisualEffectView: UIViewRepresentable {
    var effect: UIVisualEffect?

    func makeUIView(context: UIViewRepresentableContext<Self>) -> UIVisualEffectView {
        UIVisualEffectView()
    }

    func updateUIView(_ uiView: UIVisualEffectView, context: UIViewRepresentableContext<Self>) {
        uiView.effect = effect
    }
}
