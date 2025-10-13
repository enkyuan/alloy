import SwiftUI

/// Empty state view for integrations page
struct IntegrationsEmptyStateView: View {
    // MARK: - Properties
    
    @Bindable var authService: AuthenticationService
    @State private var showIntegrations = false
    
    // MARK: - Body
    
    var body: some View {
        EmptyStateView(
            iconName: "InterlockedIcon",
            renderingMode: .original,
            title: "No Integrations Yet",
            subtitle: "Connect your favorite apps to get started",
            buttonTitle: "Add Integration",
            buttonAction: { showIntegrations = true }
        )
        .sheet(isPresented: $showIntegrations) {
            IntegrationsView(authService: authService)
        }
    }
}

