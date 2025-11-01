import SwiftUI

/// View for managing service integrations
struct IntegrationsView: View {
    // MARK: - Properties
    
    @Bindable var authService: AuthenticationService
    @Bindable var integrationService: IntegrationService
    let isOnboarding: Bool
    @State private var showError = false
    @State private var errorMessage = ""
    @State private var showDisconnectAlert = false
    @State private var serviceToDisconnect: IntegrationService.ServiceType?
    @State private var isCheckingIntegrations = false
    @SwiftUI.Environment(\.dismiss) private var dismiss
    
    // MARK: - Initializer
    
    init(authService: AuthenticationService, integrationService: IntegrationService, isOnboarding: Bool = false) {
        self.authService = authService
        self.integrationService = integrationService
        self.isOnboarding = isOnboarding
    }
    
    // MARK: - Computed Properties
    
    private var hasConnectedIntegrations: Bool {
        integrationService.isConnected(.spotify) ||
        integrationService.isConnected(.uber) ||
        integrationService.isConnected(.gmail) ||
        integrationService.isConnected(.googleCalendar)
    }
    
    // MARK: - Body
    
    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(spacing: 20) {
                        // Subtitle
                        Text("Link your favorite apps to unlock Modal's full potential")
                            .font(.system(size: 16, weight: .regular))
                            .foregroundColor(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .fixedSize(horizontal: false, vertical: true)
                        
                        integrationsGrid
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 8)
                }
                
                footerSection
            }
            .background(Color(uiColor: .systemBackground))
            .navigationTitle("Add Integrations")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                if !isOnboarding {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button(action: { dismiss() }) {
                            Image(systemName: "xmark")
                                .font(.system(size: 16, weight: .semibold))
                                .foregroundColor(.secondary)
                        }
                    }
                }
            }
            .interactiveDismissDisabled(isOnboarding)
            .task {
                // Check for integrations when view appears
                // This will detect if Gmail was auto-connected via Google Sign-In
                await refreshIntegrations()
            }
            .alert("Error", isPresented: $showError) {
                Button("OK") { } 
            } message: {
                Text(errorMessage)
            }
            .alert("Disconnect Service", isPresented: $showDisconnectAlert) {
                Button("Cancel", role: .cancel) { } 
                Button("Disconnect", role: .destructive) {
                    if let service = serviceToDisconnect {
                        disconnectService(service)
                    }
                }
            } message: {
                if let service = serviceToDisconnect {
                    Text("Are you sure you want to disconnect \(service.displayName)? You can reconnect it anytime.")
                }
            }
        }
    }
    
    // MARK: - View Components
    
    private var integrationsGrid: some View {
        VStack(spacing: 16) {
            // Spotify
            Card.integration(
                iconName: "SpotifyIcon",
                serviceName: "Spotify",
                description: "Play music and manage playlists",
                isConnected: integrationService.isConnected(.spotify),
                action: { handleIntegration(.spotify) }
            )
            
            // Uber
            Card.integration(
                iconName: "UberLogo",
                serviceName: "Uber",
                description: "Book rides and check trip status",
                isConnected: integrationService.isConnected(.uber),
                action: { handleIntegration(.uber) }
            )
            
            // Gmail
            Card.integration(
                iconName: "GmailIcon",
                serviceName: "Gmail",
                description: isCheckingIntegrations ? "Checking status..." : "Read and send emails",
                isConnected: integrationService.isConnected(.gmail),
                action: { handleIntegration(.gmail) }
            )
            .opacity(isCheckingIntegrations ? 0.6 : 1.0)
            .animation(.easeInOut(duration: 0.2), value: isCheckingIntegrations)
            
            // Google Calendar
            Card.integration(
                iconName: "GoogleCalendarIcon",
                serviceName: "Google Calendar",
                description: "Manage events and schedules",
                isConnected: integrationService.isConnected(.googleCalendar),
                action: { handleIntegration(.googleCalendar) }
            )
            
            // DoorDash
            Card.integration(
                iconName: "DoorDashIcon",
                serviceName: "DoorDash",
                description: "Get food delivered to your door",
                isConnected: false,
                action: {}
            )
            .disabled(true)
            
            // Apple Music
            Card.integration(
                iconName: "AppleMusicIcon",
                serviceName: "Apple Music",
                description: "Listen to your favorite artists",
                isConnected: false,
                action: {}
            )
            .disabled(true)
            
            // Instacart
            Card.integration(
                iconName: "InstacartIcon",
                serviceName: "Instacart",
                description: "Groceries delivered in minutes",
                isConnected: false,
                action: {}
            )
            .disabled(true)
        }
    }
    
    private var footerSection: some View {
        Button(action: { dismiss() }) {
            Text(hasConnectedIntegrations ? "Continue" : "Skip for now")
                .font(.system(size: 17, weight: .semibold))
                .foregroundColor(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 56)
                .background(hasConnectedIntegrations ? Color.green : Color.black)
                .cornerRadius(16)
                .animation(.spring(response: 0.3, dampingFraction: 0.7), value: hasConnectedIntegrations)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 20)
        .background(Color(uiColor: .systemBackground))
    }
    
    // MARK: - Actions

    private func handleIntegration(_ service: IntegrationService.ServiceType) {
        // Check if already connected - if so, show disconnect confirmation
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
                // Success - no need to show any message, the checkmark will appear
            } catch let error as IntegrationError {
                // Don't show error for user cancellation
                guard case .userCancelled = error else {
                    errorMessage = "Failed to connect \(service.displayName): \(error.localizedDescription)"
                    showError = true
                    return
                }
                // User cancelled - silently ignore, no error shown
                print("ℹ️ User cancelled \(service.displayName) connection")
            } catch {
                // Only show errors that aren't cancellations
                let nsError = error as NSError
                if nsError.domain == "com.apple.AuthenticationServices.WebAuthenticationSession" && nsError.code == 1 {
                    // User cancelled in auth session
                    print("ℹ️ User cancelled OAuth flow")
                    return
                }
                errorMessage = "Failed to connect \(service.displayName): \(error.localizedDescription)"
                showError = true
            }
        }
    }

    private func disconnectService(_ service: IntegrationService.ServiceType) {
        Task {
            do {
                try await integrationService.disconnectService(service, authService: authService)
            } catch {
                errorMessage = "Failed to disconnect \(service.displayName): \(error.localizedDescription)"
                showError = true
            }
        }
    }
    
    private func refreshIntegrations() async {
        // Fetch latest integration status from backend
        // This will detect integrations connected via Google Sign-In or other methods
        isCheckingIntegrations = true
        defer { isCheckingIntegrations = false }
        
        do {
            try await integrationService.fetchConnectedIntegrations(authService: authService)
            print("✅ Refreshed integrations")
        } catch {
            print("⚠️ Failed to refresh integrations: \(error.localizedDescription)")
            // Don't show error to user - this is a background check
        }
    }

}