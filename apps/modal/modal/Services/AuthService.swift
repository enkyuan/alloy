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


@Observable
class AuthService {

    var currentUser: User?

    var session: Session?

    var isAuthenticated: Bool { session != nil }

    private let backendURL: String


    nonisolated init(backendURL: String = Environment.apiBaseURL) {
        self.backendURL = backendURL

        Task {
            await loadSession()
        }

        Task { @MainActor in
            for await state in supabase.auth.authStateChanges {
                if state.event == .signedIn {
                    print("Auth state changed: Signed in")
                    await handleAuthStateChange(session: state.session)
                } else if state.event == .signedOut {
                    print("Auth state changed: Signed out")
                    self.session = nil
                    self.currentUser = nil
                }
            }
        }
    }


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
        }
    }


    func authenticateWithGoogle(idToken: String, accessToken: String) async throws {
        print("Authenticating with Supabase using Google tokens")

        do {
            let session = try await supabase.auth.signInWithIdToken(
                credentials: .init(
                    provider: .google,
                    idToken: idToken,
                    accessToken: accessToken
                )
            )

            self.session = session
            print("Supabase session created for: \(session.user.email ?? "unknown")")

            await syncUserWithBackend()
        } catch {
            print("Google authentication failed: \(error)")
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
        print("Supabase session created for: \(session.user.email ?? "unknown")")

        await syncUserWithBackend()
    }

    func signOut() async throws {
        try await supabase.auth.signOut()
        session = nil
        currentUser = nil
        print("Signed out successfully")
    }


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
