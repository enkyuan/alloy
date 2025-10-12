import SwiftUI

/// Main home screen after authentication
struct HomeView: View {
    // MARK: - Properties
    
    @Bindable var authService: AuthenticationService
    @State private var showError = false
    @State private var errorMessage = ""
    
    // MARK: - Body
    
    var body: some View {
        NavigationView {
            VStack(spacing: 24) {
                welcomeSection
                userInfoSection
                Spacer()
                signOutButton
            }
            .padding()
            .alert("Error", isPresented: $showError) {
                Button("OK") { }
            } message: {
                Text(errorMessage)
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

