import SwiftUI

/// Root view that routes between authenticated and unauthenticated states
struct ContentView: View {
    @State private var authService = AuthenticationService()
    
    var body: some View {
        Group {
            if authService.isAuthenticated {
                HomeView(authService: authService)
            } else {
                OnboardingView(authService: authService)
            }
        }
    }
}

// MARK: - Previews

#Preview("Content View") {
    ContentView()
}

