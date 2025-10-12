import SwiftUI

/// View for managing service integrations
struct IntegrationsView: View {
    // MARK: - Properties
    
    @Bindable var authService: AuthenticationService
    @State private var integrationService = IntegrationService()
    @State private var showError = false
    @State private var errorMessage = ""
    @Environment(\.dismiss) var dismiss
    
    // MARK: - Body
    
    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: 24) {
                    headerSection
                    integrationsGrid
                }
                .padding(.horizontal, 20)
                .padding(.top, 40)
            }
            
            footerSection
        }
        .background(Color(uiColor: .systemBackground))
        .alert("Error", isPresented: $showError) {
            Button("OK") { }
        } message: {
            Text(errorMessage)
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
        }
    }
    
    private var footerSection: some View {
        Button(action: { dismiss() }) {
            Text("Skip for now")
                .font(.system(size: 17, weight: .semibold))
                .foregroundColor(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 56)
                .background(Color.black)
                .cornerRadius(16)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 20)
        .background(Color(uiColor: .systemBackground))
    }
    
    // MARK: - Actions
    
    private func handleIntegration(_ service: IntegrationService.ServiceType) {
        Task {
            do {
                try await integrationService.connectService(service, authService: authService)
            } catch let error as IntegrationError {
                // Don't show error for user cancellation
                if case .userCancelled = error {
                    return
                }
                errorMessage = "Failed to connect \(service.displayName): \(error.localizedDescription)"
                showError = true
            } catch {
                errorMessage = "Failed to connect \(service.displayName): \(error.localizedDescription)"
                showError = true
            }
        }
    }
    
}


