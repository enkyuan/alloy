import Foundation
import AuthenticationServices
import Supabase
import GoogleSignIn


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


<<<<<<< HEAD:apps/modal/modal/Services/AuthService.swift
=======
@MainActor
>>>>>>> codex/refactor:apps/milo/milo/Services/AuthService.swift
@Observable
class AuthService {

    var currentUser: User?

    var session: Session?

<<<<<<< HEAD:apps/modal/modal/Services/AuthService.swift
    var isAuthenticated: Bool { session != nil }
=======
    var isRestoringSession: Bool = true

    var isAuthenticated: Bool { currentUser != nil }
>>>>>>> codex/refactor:apps/milo/milo/Services/AuthService.swift

    private let backendURL: String


<<<<<<< HEAD:apps/modal/modal/Services/AuthService.swift
    nonisolated init(backendURL: String = Environment.apiBaseURL) {
        self.backendURL = backendURL

        Task {
=======
    init(backendURL: String = Environment.apiBaseURL) {
        self.backendURL = backendURL

        Task { @MainActor in
>>>>>>> codex/refactor:apps/milo/milo/Services/AuthService.swift
            await loadSession()
        }

        Task { @MainActor in
<<<<<<< HEAD:apps/modal/modal/Services/AuthService.swift
            for await state in supabase.auth.authStateChanges {
                if state.event == .signedIn {
                    print("Auth state changed: Signed in")
                    await handleAuthStateChange(session: state.session)
                } else if state.event == .signedOut {
                    print("Auth state changed: Signed out")
                    self.session = nil
                    self.currentUser = nil
=======
            if ProcessInfo.processInfo.arguments.contains("--mock-auth") {
                print("Mock Auth Detected")
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                self.setupMockSession()
            } else {
                for await state in supabase.auth.authStateChanges {
                    if state.event == .signedIn || state.event == .tokenRefreshed
                        || state.event == .initialSession
                    {
                        print("Auth state changed: \(state.event.rawValue)")
                        await handleAuthStateChange(session: state.session)
                    } else if state.event == .signedOut {
                        print("Auth state changed: Signed out")
                        clearAuthState()
                    }
>>>>>>> codex/refactor:apps/milo/milo/Services/AuthService.swift
                }
            }
        }
    }
<<<<<<< HEAD:apps/modal/modal/Services/AuthService.swift


    private func handleAuthStateChange(session: Session?) async {
        guard let session = session else { return }
        self.session = session
        print("Session updated for: \(session.user.email ?? "unknown")")
        await syncUserWithBackend()
    }

    private func loadSession() async {
        do {
            session = try await supabase.auth.session
            if let session = session {
                print("Loaded existing session for: \(session.user.email ?? "unknown")")
                await syncUserWithBackend()
            }
        } catch {
            print("No existing session")
=======
    
    private func setupMockSession() {
        // Create a dummy user
        self.currentUser = User(
            id: "test_user_id",
            email: "test@example.com",
            username: "Test User",
            fullName: "Test User",
            avatarUrl: nil,
            provider: "google",
            isActive: true,
            isVerified: true,
            createdAt: "2024-01-01T00:00:00Z"
        )
        
        // In mock mode we model authenticated state via currentUser only.
        isRestoringSession = false
    }


    private func handleAuthStateChange(session: Session?) async {
        guard let session = session else {
            clearAuthState()
            return
        }
        self.session = session
        print("Session updated for: \(session.user.email ?? "unknown")")
        _ = await syncUserWithBackend()
    }

    private func loadSession() async {
        defer { isRestoringSession = false }
        do {
            let restoredSession = try await supabase.auth.session
            session = restoredSession
            print("Loaded existing session for: \(restoredSession.user.email ?? "unknown")")
            _ = await syncUserWithBackend()
        } catch {
            print("No existing session")
            clearAuthState()
>>>>>>> codex/refactor:apps/milo/milo/Services/AuthService.swift
        }
    }


    func authenticateWithGoogle(idToken: String, accessToken: String) async throws {
<<<<<<< HEAD:apps/modal/modal/Services/AuthService.swift
        print("Authenticating with Supabase using Google tokens")

        do {
=======
        print("[AuthDebug] Authenticating with Supabase using Google tokens")
        print("[AuthDebug] ID Token length: \(idToken.count)")
        print("[AuthDebug] Access Token length: \(accessToken.count)")

        do {
            print("[AuthDebug] Calling supabase.auth.signInWithIdToken...")
>>>>>>> codex/refactor:apps/milo/milo/Services/AuthService.swift
            let session = try await supabase.auth.signInWithIdToken(
                credentials: .init(
                    provider: .google,
                    idToken: idToken,
                    accessToken: accessToken
                )
            )
<<<<<<< HEAD:apps/modal/modal/Services/AuthService.swift

            self.session = session
            print("Supabase session created for: \(session.user.email ?? "unknown")")

            await syncUserWithBackend()
        } catch {
            print("Google authentication failed: \(error)")
=======
            print("[AuthDebug] supabase.auth.signInWithIdToken returned successfully")

            self.session = session
            self.currentUser = nil
            print("[AuthDebug] Supabase session created for: \(session.user.email ?? "unknown")")

            print("[AuthDebug] Calling syncUserWithBackend()...")
            let didSync = await syncUserWithBackend()
            print("[AuthDebug] syncUserWithBackend() returned")
            if !didSync {
                throw AuthError.serverError("Could not verify session with backend")
            }
        } catch let authError as AuthError {
            print("[AuthDebug] Google authentication failed: \(authError.localizedDescription)")
            throw authError
        } catch {
            print("[AuthDebug] Google authentication failed: \(error)")
>>>>>>> codex/refactor:apps/milo/milo/Services/AuthService.swift
            throw AuthError.serverError(error.localizedDescription)
        }
    }

    func authenticateWithApple(authorization: ASAuthorization) async throws {
        guard let appleIDCredential = authorization.credential as? ASAuthorizationAppleIDCredential,
              let identityToken = appleIDCredential.identityToken,
              let idTokenString = String(data: identityToken, encoding: .utf8) else {
            throw AuthError.invalidAppleCredential
        }

        print("Authenticating with Supabase using Apple ID token")

        let session = try await supabase.auth.signInWithIdToken(
            credentials: .init(
                provider: .apple,
                idToken: idTokenString
            )
        )

        self.session = session
<<<<<<< HEAD:apps/modal/modal/Services/AuthService.swift
        print("Supabase session created for: \(session.user.email ?? "unknown")")

        await syncUserWithBackend()
=======
        self.currentUser = nil
        print("Supabase session created for: \(session.user.email ?? "unknown")")

        let didSync = await syncUserWithBackend()
        if !didSync {
            throw AuthError.serverError("Could not verify session with backend")
        }
>>>>>>> codex/refactor:apps/milo/milo/Services/AuthService.swift
    }

    func signOut() async throws {
        try await supabase.auth.signOut()
<<<<<<< HEAD:apps/modal/modal/Services/AuthService.swift
        session = nil
        currentUser = nil
=======
        GIDSignIn.sharedInstance.signOut()
        clearAuthState()
>>>>>>> codex/refactor:apps/milo/milo/Services/AuthService.swift
        print("Signed out successfully")
    }


<<<<<<< HEAD:apps/modal/modal/Services/AuthService.swift
    private func syncUserWithBackend() async {
        guard let session = session else { return }

        do {
            let accessToken = session.accessToken

            let url = URL(string: "\(backendURL)/auth/sync")!
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")

            let (data, response) = try await URLSession.shared.data(for: request)

            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200 else {
                print("Failed to sync user with backend (status: \((response as? HTTPURLResponse)?.statusCode ?? -1))")
                return
            }

            currentUser = try JSONDecoder().decode(User.self, from: data)
            print("User synced with backend: \(currentUser?.email ?? "unknown")")

        } catch {
            print("Error syncing with backend: \(error.localizedDescription)")
        }
    }

=======
    @discardableResult
    private func syncUserWithBackend() async -> Bool {
        print("[AuthDebug] syncUserWithBackend started")
        let previousUser = currentUser

        guard let session = session else {
            print("[AuthDebug] No session in syncUserWithBackend")
            currentUser = nil
            return false
        }

        do {
            let initialResult = try await sendSyncRequest(accessToken: session.accessToken)
            if initialResult.statusCode == 200 {
                currentUser = try JSONDecoder().decode(User.self, from: initialResult.data)
                print("[AuthDebug] User synced with backend: \(currentUser?.email ?? "unknown")")
                return true
            }

            // If the access token is stale, refresh once and retry sync.
            if initialResult.statusCode == 401 {
                print("[AuthDebug] Backend rejected token, attempting Supabase session refresh")
                do {
                    let refreshedSession = try await supabase.auth.refreshSession()
                    self.session = refreshedSession

                    let retryResult = try await sendSyncRequest(
                        accessToken: refreshedSession.accessToken)
                    if retryResult.statusCode == 200 {
                        currentUser = try JSONDecoder().decode(User.self, from: retryResult.data)
                        print("[AuthDebug] User synced with backend after token refresh: \(currentUser?.email ?? "unknown")")
                        return true
                    }

                    print("[AuthDebug] Backend sync still failing after refresh (status: \(retryResult.statusCode))")
                    if let responseBody = String(data: retryResult.data, encoding: .utf8) {
                        print("[AuthDebug] Response body: \(responseBody)")
                    }
                } catch {
                    print("[AuthDebug] Failed to refresh Supabase session: \(error)")
                }

                await clearInvalidLocalSession()
                return false
            }

            print("[AuthDebug] Failed to sync user with backend (status: \(initialResult.statusCode))")
            if let responseBody = String(data: initialResult.data, encoding: .utf8) {
                print("[AuthDebug] Response body: \(responseBody)")
            }
            if let previousUser = previousUser {
                currentUser = previousUser
                return true
            }
            currentUser = nil
            return false

        } catch {
            print("[AuthDebug] Error syncing with backend: \(error.localizedDescription)")
            print("[AuthDebug] Full error: \(error)")
            if let previousUser = previousUser {
                currentUser = previousUser
                return true
            }
            currentUser = nil
            return false
        }
    }

    private func sendSyncRequest(accessToken: String) async throws -> (data: Data, statusCode: Int) {
        let urlString = "\(backendURL)/auth/sync"
        print("[AuthDebug] Syncing to URL: \(urlString)")

        guard let url = URL(string: urlString) else {
            print("[AuthDebug] Invalid URL: \(urlString)")
            return (Data(), -1)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        print("[AuthDebug] Sending network request...")
        let (data, response) = try await URLSession.shared.data(for: request)
        print("[AuthDebug] Network request finished")

        guard let httpResponse = response as? HTTPURLResponse else {
            print("[AuthDebug] Response is not HTTPURLResponse")
            return (data, -1)
        }

        print("[AuthDebug] Response status code: \(httpResponse.statusCode)")
        return (data, httpResponse.statusCode)
    }

    private func clearInvalidLocalSession() async {
        do {
            try await supabase.auth.signOut(scope: .local)
        } catch {
            print("[AuthDebug] Failed to clear local Supabase session: \(error)")
        }
        GIDSignIn.sharedInstance.signOut()

        clearAuthState()
        print("[AuthDebug] Cleared local auth state due to invalid backend token")
    }

    func handleBackendUnauthorized() async {
        await clearInvalidLocalSession()
    }

    private func clearAuthState() {
        session = nil
        currentUser = nil
        IntegrationService.shared.clearCachedConnectedServices()
    }

>>>>>>> codex/refactor:apps/milo/milo/Services/AuthService.swift
    private func syncGoogleIntegrations(accessToken: String) async {
        guard let session = session else {
            print("No session available for Google integrations sync")
            return
        }

        print("Syncing Gmail integration with backend...")
        await syncIntegration(
            endpoint: "/integrations/gmail/sync",
            accessToken: accessToken,
            session: session,
            serviceName: "Gmail"
        )

        print("Syncing Google Calendar integration with backend...")
        await syncIntegration(
            endpoint: "/integrations/google-calendar/sync",
            accessToken: accessToken,
            session: session,
            serviceName: "Google Calendar"
        )
    }

    private func syncIntegration(
        endpoint: String,
        accessToken: String,
        session: Session,
        serviceName: String
    ) async {

        do {
            let url = URL(string: "\(Environment.apiBaseURL)\(endpoint)")!
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("Bearer \(session.accessToken)", forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")

            let body = ["access_token": accessToken]
            request.httpBody = try JSONEncoder().encode(body)

            let (_, response) = try await URLSession.shared.data(for: request)

            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200 else {
                print("Failed to sync \(serviceName) integration (status: \((response as? HTTPURLResponse)?.statusCode ?? -1))")
                return
            }

            print("\(serviceName) integration synced successfully")

        } catch {
            print("Error syncing \(serviceName) integration: \(error.localizedDescription)")
        }
    }

}


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
