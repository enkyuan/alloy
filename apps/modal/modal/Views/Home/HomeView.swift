import SwiftUI

/// Main home screen after authentication
struct HomeView: View {
    // MARK: - Properties
    
    @Bindable var authService: AuthenticationService
    @State private var showError = false
    @State private var errorMessage = ""
    @State private var showIntegrations = false
    
    // MARK: - Body
    
    var body: some View {
        NavigationView {
            VStack(spacing: 24) {
                welcomeSection
                userInfoSection
                integrationsButton
                Spacer()
                signOutButton
            }
            .padding()
            .alert("Error", isPresented: $showError) {
                Button("OK") { }
            } message: {
                Text(errorMessage)
            }
            .sheet(isPresented: $showIntegrations) {
                IntegrationsView(authService: authService)
            }
        }
    }
    
    // MARK: - View Components
    
    private var welcomeSection: some View {
        Text("Welcome to Modal!")
            .font(.system(size: 32, weight: .bold))
    }
    
    @ViewBuilder
    private var userInfoSection: some View {
        if let user = authService.currentUser {
            VStack(spacing: 8) {
                Text("Signed in as:")
                    .font(.system(size: 16))
                    .foregroundColor(.secondary)
                
                Text(user.email)
                    .font(.system(size: 18, weight: .medium))
            }
        }
    }
    
    private var integrationsButton: some View {
        Button(action: { showIntegrations = true }) {
            HStack {
                Image(systemName: "square.grid.2x2")
                    .font(.system(size: 16, weight: .semibold))
                Text("Connect Services")
                    .font(.system(size: 17, weight: .semibold))
            }
            .frame(maxWidth: .infinity)
            .frame(height: 56)
            .foregroundColor(.white)
            .background(Color.blue)
            .cornerRadius(16)
            .padding(.horizontal, 32)
        }
    }
    
    private var signOutButton: some View {
        Button(action: handleSignOut) {
            Text("Sign Out")
                .font(.system(size: 17, weight: .semibold))
                .frame(maxWidth: .infinity)
                .frame(height: 56)
                .foregroundColor(.white)
                .background(Color.red)
                .cornerRadius(16)
                .padding(.horizontal, 32)
        }
    }
    
    // MARK: - Actions
    
    private func handleSignOut() {
        Task {
            do {
                try await authService.signOut()
            } catch {
                errorMessage = "Sign out failed: \(error.localizedDescription)"
                showError = true
            }
        }
    }
}

