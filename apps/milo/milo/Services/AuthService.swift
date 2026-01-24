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


@MainActor
@Observable
class AuthService {

    var currentUser: User?

    var session: Session?

    var isAuthenticated: Bool { session != nil }

    private let backendURL: String


    init(backendURL: String = Environment.apiBaseURL) {
        self.backendURL = backendURL

        Task { @MainActor in
            await loadSession()
        }

        Task { @MainActor in
            for await state in supabase.auth.authStateChanges {
                if state.event == .signedIn {
                    print("Auth state changed: Signed in")
                    await handleAuthStateChange(session: state.session)
                } else if state.event == .signedOut {
                    print("Auth state changed: Signed out")
                    session = nil
                    currentUser = nil
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
        print("[AuthDebug] Authenticating with Supabase using Google tokens")
        print("[AuthDebug] ID Token length: \(idToken.count)")
        print("[AuthDebug] Access Token length: \(accessToken.count)")

        do {
            print("[AuthDebug] Calling supabase.auth.signInWithIdToken...")
            let session = try await supabase.auth.signInWithIdToken(
                credentials: .init(
                    provider: .google,
                    idToken: idToken,
                    accessToken: accessToken
                )
            )
            print("[AuthDebug] supabase.auth.signInWithIdToken returned successfully")

            self.session = session
            print("[AuthDebug] Supabase session created for: \(session.user.email ?? "unknown")")

            print("[AuthDebug] Calling syncUserWithBackend()...")
            await syncUserWithBackend()
            print("[AuthDebug] syncUserWithBackend() returned")
        } catch {
            print("[AuthDebug] Google authentication failed: \(error)")
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
        print("[AuthDebug] syncUserWithBackend started")
        guard let session = session else {
            print("[AuthDebug] No session in syncUserWithBackend")
            return
        }

        do {
            let accessToken = session.accessToken
            let urlString = "\(backendURL)/auth/sync"
            print("[AuthDebug] Syncing to URL: \(urlString)")
            
            guard let url = URL(string: urlString) else {
                print("[AuthDebug] Invalid URL: \(urlString)")
                return
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
                 return
            }
            
            print("[AuthDebug] Response status code: \(httpResponse.statusCode)")

            guard httpResponse.statusCode == 200 else {
                print("[AuthDebug] Failed to sync user with backend (status: \(httpResponse.statusCode))")
                if let responseBody = String(data: data, encoding: .utf8) {
                    print("[AuthDebug] Response body: \(responseBody)")
                }
                return
            }

            currentUser = try JSONDecoder().decode(User.self, from: data)
            print("[AuthDebug] User synced with backend: \(currentUser?.email ?? "unknown")")

        } catch {
            print("[AuthDebug] Error syncing with backend: \(error.localizedDescription)")
            print("[AuthDebug] Full error: \(error)")
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
