import SwiftUI
import GoogleSignIn

/// Main onboarding screen with authentication options
struct OnboardingView: View {
    // MARK: - Properties
    
    @State private var viewModel = OnboardingViewModel()
    @Bindable var authService: AuthenticationService
    @State private var showError = false
    @State private var errorMessage = ""
    @State private var isAuthenticating = false
    
    // MARK: - Body
    
    var body: some View {
        VStack(spacing: 0) {
            conversationalTextSection
            previewCardSection
            Spacer()
            authenticationSection
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.background)
        .onAppear { viewModel.startAnimations() }
        .alert("Authentication Error", isPresented: $showError) {
            Button("OK") { }
        } message: {
            Text(errorMessage)
        }
        .overlay {
            if isAuthenticating {
                loadingOverlay
            }
        }
    }
    
    // MARK: - View Components
    
    private var conversationalTextSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            AnimatedText(typing: "Hey Modi,", show: $viewModel.showGreeting)
                .font(.system(size: 28, weight: .medium))
                .foregroundColor(.primary.opacity(0.9))
            
            AnimatedText(
                fadeIn: viewModel.currentPhrase,
                opacity: viewModel.phraseOpacity,
                blur: viewModel.phraseBlur,
                offset: viewModel.phraseOffset
            )
            .font(.system(size: 28, weight: .medium))
            .foregroundColor(.primary.opacity(0.6))
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 32)
        .padding(.top, 80)
    }
    
    private var previewCardSection: some View {
        ZStack {
            switch viewModel.currentPhraseIndex {
            case 0: ServicePreviewCard(service: .doordash)
            case 1: ServicePreviewCard(service: .appleMusic)
            case 2: ServicePreviewCard(service: .instacart)
            default: EmptyView()
            }
        }
        .opacity(viewModel.previewOpacity)
        .frame(height: 120)
        .padding(.top, 20)
        .padding(.horizontal, 32)
    }
    
    private var authenticationSection: some View {
        VStack(alignment: .leading, spacing: 24) {
            titleSection
            authButtonsSection
        }
        .padding(.bottom, 40)
    }
    
    private var titleSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Meet Modal")
                .font(.system(size: 32, weight: .bold))
                .foregroundColor(.primary)
            
            Text("Your agentic voice assistant")
                .font(.system(size: 20, weight: .semibold))
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 32)
        .padding(.bottom, 16)
    }
    
    private var authButtonsSection: some View {
        VStack(spacing: 12) {
            AuthButton(
                icon: .system("apple.logo"),
                text: "Continue with Apple",
                style: .primary,
                action: handleAppleSignIn
            )
            AuthButton(
                icon: .asset("GoogleIcon"),
                text: "Continue with Google",
                style: .secondary,
                action: handleGoogleSignIn
            )
            AuthButton(
                icon: .asset("MailIcon"),
                text: "Continue with Email",
                style: .secondary,
                action: handleEmailSignIn
            )
        }
        .padding(.horizontal, 32)
    }
    
    private var loadingOverlay: some View {
        ZStack {
            Color.black.opacity(0.3)
                .ignoresSafeArea()
            ProgressView()
                .scaleEffect(1.5)
                .tint(.white)
        }
    }
    
    // MARK: - Authentication Handlers
    
    private func handleGoogleSignIn() {
        guard let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let rootViewController = windowScene.windows.first?.rootViewController else {
            showError(message: "Unable to get root view controller")
            return
        }
        
        isAuthenticating = true
        
        GIDSignIn.sharedInstance.signIn(withPresenting: rootViewController) { result, error in
            if let error = error {
                isAuthenticating = false
                showError(message: "Google Sign-In failed: \(error.localizedDescription)")
                return
            }
            
            guard let result = result,
                  let idToken = result.user.idToken?.tokenString else {
                isAuthenticating = false
                showError(message: "Failed to get Google ID token")
                return
            }
            
            print("📝 Got Google ID token for: \(result.user.profile?.email ?? "unknown")")
            
            Task {
                do {
                    try await authService.authenticateWithGoogle(idToken: idToken)
                    print("✅ Successfully authenticated!")
                    isAuthenticating = false
                } catch {
                    isAuthenticating = false
                    showError(message: "Authentication failed: \(error.localizedDescription)")
                    print("❌ Error: \(error)")
                }
            }
        }
    }
    
    private func handleAppleSignIn() {
        // TODO: Implement Apple Sign In
        print("Apple Sign In tapped")
    }
    
    private func handleEmailSignIn() {
        // TODO: Implement Email Sign In
        print("Email Sign In tapped")
    }
    
    private func showError(message: String) {
        errorMessage = message
        showError = true
    }
}

