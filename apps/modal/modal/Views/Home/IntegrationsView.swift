import SwiftUI

struct ScrollOffsetPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

/// View for managing service integrations
struct IntegrationsView: View {
    // MARK: - Properties
    
    @Bindable var authService: AuthenticationService
    @State private var integrationService = IntegrationService()
    @State private var showError = false
    @State private var errorMessage = ""
    @State private var showStickyHeader = false
    @State private var showDisconnectAlert = false
    @State private var serviceToDisconnect: IntegrationService.ServiceType?
    @Environment(\.dismiss) var dismiss
    
    // MARK: - Computed Properties
    
    private var hasConnectedIntegrations: Bool {
        integrationService.isConnected(.spotify) ||
        integrationService.isConnected(.uber) ||
        integrationService.isConnected(.gmail) ||
        integrationService.isConnected(.googleCalendar)
    }
    
    // MARK: - Body
    
    var body: some View {
        ZStack(alignment: .top) {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(spacing: 0) {
                        headerSection
                            .padding(.horizontal, 20)
                            .padding(.top, 40)
                            .padding(.bottom, 24)
                            .background(
                                GeometryReader { geometry in
                                    let offset = geometry.frame(in: .named("scroll")).minY
                                    Color.clear
                                        .onChange(of: offset) { oldValue, newValue in
                                            print("🔄 Offset: \(newValue)")
                                            // Directly update state instead of using preference
                                            withAnimation(.easeInOut(duration: 0.25)) {
                                                self.showStickyHeader = newValue < -50
                                            }
                                        }
                                }
                            )
                        
                        integrationsGrid
                            .padding(.horizontal, 20)
                    }
                }
                .coordinateSpace(name: "scroll")
                
                footerSection
            }
            .background(Color(uiColor: .systemBackground))
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
            
            stickyHeaderSection
                .offset(y: showStickyHeader ? 0 : -100)
                .opacity(showStickyHeader ? 1 : 0)
                .animation(.spring(response: 0.32, dampingFraction: 0.9), value: showStickyHeader)
        }
        .task {
            // Fetch connected integrations when view appears
            do {
                try await integrationService.fetchConnectedIntegrations(authService: authService)
            } catch {
                print("Failed to fetch integrations: \(error)")
            }
        }
    }
    
    // MARK: - View Components

    private var stickyHeaderSection: some View {
        VStack(spacing: 0) {
            Text("Connect Your Services")
                .font(.headline.weight(.bold))
                .foregroundColor(.primary)
                .padding(.vertical, 16)
                .padding(.horizontal)
                .frame(maxWidth: .infinity)
            Divider()
        }
        .background(.ultraThinMaterial)
        .shadow(color: Color.black.opacity(0.1), radius: 8, x: 0, y: 2)
    }
    
    private var headerSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Connect Your Services")
                .font(.system(size: 32, weight: .bold))
            
            Text("Link your favorite apps to unlock Modal's full potential")
                .font(.system(size: 16, weight: .regular))
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
    
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
                description: "Read and send emails",
                isConnected: integrationService.isConnected(.gmail),
                action: { handleIntegration(.gmail) }
            )
            
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

}