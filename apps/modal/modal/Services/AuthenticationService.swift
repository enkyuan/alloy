import Foundation
import AuthenticationServices
import Supabase
import GoogleSignIn

// MARK: - User Model

/// User model representing an authenticated user
struct User: Codable, Identifiable {
    let id: String
    let email: String
    let username: String?
    let fullName: String?
    let avatarUrl: String?
    let provider: String
    let isActive: Bool
    let isVerified: Bool
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, email, username, provider
        case fullName = "full_name"
        case avatarUrl = "avatar_url"
        case isActive = "is_active"
        case isVerified = "is_verified"
        case createdAt = "created_at"
    }
}

// MARK: - Authentication Service

/// Service for managing user authentication and session state
///
/// This service handles:
/// - Google OAuth via Google Sign-In SDK
/// - Apple Sign In
/// - Supabase session management
/// - Backend user synchronization
@Observable
class AuthenticationService {
    // MARK: - Properties
    
    /// Current authenticated user from backend
    var currentUser: User?
    
    /// Current Supabase session
    var session: Session?
    
    /// Whether the user is authenticated
    var isAuthenticated: Bool { session != nil }
    
    /// Backend API base URL
    private let backendURL: String
    
    // MARK: - Initialization
    
    /// Initialize the authentication service
    /// - Parameter backendURL: Backend API base URL (defaults to value from Environment config)
    nonisolated init(backendURL: String = Environment.apiBaseURL) {
        self.backendURL = backendURL
        
        // Check for existing session
        Task {
            await loadSession()
        }
        
        // Listen for authentication state changes
        Task { @MainActor in
            for await state in SupabaseConfig.shared.auth.authStateChanges {
                if state.event == .signedIn {
                    print("✅ Auth state changed: Signed in")
                    await handleAuthStateChange(session: state.session)
                } else if state.event == .signedOut {
                    print("ℹ️ Auth state changed: Signed out")
                    self.session = nil
                    self.currentUser = nil
                }
            }
        }
    }
    
    // MARK: - Private Methods
    
    /// Handle authentication state changes from Supabase
    /// - Parameter session: The new session
    private func handleAuthStateChange(session: Session?) async {
        guard let session = session else { return }
        self.session = session
        print("✅ Session updated for: \(session.user.email ?? "unknown")")
        await syncUserWithBackend()
    }
    
    /// Load existing session on app launch
    private func loadSession() async {
        do {
            session = try await SupabaseConfig.shared.auth.session
            if let session = session {
                print("✅ Loaded existing session for: \(session.user.email ?? "unknown")")
                await syncUserWithBackend()
            }
        } catch {
            print("ℹ️ No existing session")
        }
    }
    
    // MARK: - Public Methods
    
    /// Authenticate user with Google ID token
    ///
    /// This uses Google Sign-In SDK to get an ID token, then exchanges it
    /// with Supabase for a session. Requires `skip_nonce_check=true` in Supabase config.
    ///
    /// - Parameter idToken: Google ID token from Google Sign-In SDK
    /// - Throws: Supabase authentication errors
    func authenticateWithGoogle(idToken: String) async throws {
        print("📤 Authenticating with Supabase using Google ID token")
        
        // Sign in with Supabase using Google ID token from Google Sign-In SDK
        // Reference: https://supabase.com/docs/guides/auth/social-login/auth-google
        let session = try await SupabaseConfig.shared.auth.signInWithIdToken(
            credentials: .init(
                provider: .google,
                idToken: idToken
            )
        )
        
        self.session = session
        print("✅ Supabase session created for: \(session.user.email ?? "unknown")")
        
        // Sync user with our backend database
        await syncUserWithBackend()
    }
    
    /// Authenticate user with Apple Sign In
    ///
    /// - Parameter authorization: Apple authorization result from ASAuthorizationController
    /// - Throws: `AuthError.invalidAppleCredential` or Supabase authentication errors
    func authenticateWithApple(authorization: ASAuthorization) async throws {
        guard let appleIDCredential = authorization.credential as? ASAuthorizationAppleIDCredential,
              let identityToken = appleIDCredential.identityToken,
              let idTokenString = String(data: identityToken, encoding: .utf8) else {
            throw AuthError.invalidAppleCredential
        }
        
        print("📤 Authenticating with Supabase using Apple ID token")
        
        // Sign in with Apple ID token
        // Reference: https://supabase.com/docs/reference/swift/auth-signinwithidtoken
        let session = try await SupabaseConfig.shared.auth.signInWithIdToken(
            credentials: .init(
                provider: .apple,
                idToken: idTokenString
            )
        )
        
        self.session = session
        print("✅ Supabase session created for: \(session.user.email ?? "unknown")")
        
        // Sync user with our backend database
        await syncUserWithBackend()
    }
    
    /// Sign out the current user
    ///
    /// This signs out from Supabase and clears local session state.
    ///
    /// - Throws: Supabase sign out errors
    func signOut() async throws {
        try await SupabaseConfig.shared.auth.signOut()
        session = nil
        currentUser = nil
        print("✅ Signed out successfully")
    }
    
    // MARK: - Backend Integration
    
    /// Sync user data with backend database
    ///
    /// This creates or updates the user record in our backend database.
    /// The backend validates the Supabase session and returns user data.
    private func syncUserWithBackend() async {
        guard let session = session else { return }
        
        do {
            let accessToken = session.accessToken
            
            // Call backend sync endpoint
            let url = URL(string: "\(backendURL)/auth/sync")!
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            
            let (data, response) = try await URLSession.shared.data(for: request)
            
            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200 else {
                print("⚠️ Failed to sync user with backend (status: \((response as? HTTPURLResponse)?.statusCode ?? -1))")
                return
            }
            
            // Parse and store user data
            currentUser = try JSONDecoder().decode(User.self, from: data)
            print("✅ User synced with backend: \(currentUser?.email ?? "unknown")")
            
        } catch {
            print("⚠️ Error syncing with backend: \(error.localizedDescription)")
            // Don't throw - authentication succeeded, backend sync is optional
        }
    }
    
}

// MARK: - Authentication Errors

/// Errors that can occur during authentication
enum AuthError: LocalizedError {
    case invalidResponse
    case invalidAppleCredential
    case authenticationFailed(statusCode: Int)
    case serverError(String)
    
    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "Invalid response from server"
        case .invalidAppleCredential:
            return "Invalid Apple credential"
        case .authenticationFailed(let statusCode):
            return "Authentication failed with status code: \(statusCode)"
        case .serverError(let message):
            return "Server error: \(message)"
        }
    }
}
