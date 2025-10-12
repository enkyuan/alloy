import Foundation
import AuthenticationServices

// MARK: - API Models
struct GoogleAuthRequest: Codable {
    let idToken: String

    enum CodingKeys: String, CodingKey {
        case idToken = "id_token"
    }
}

struct TokenResponse: Codable {
    let accessToken: String
    let tokenType: String
    let expiresIn: Int
    let refreshToken: String?
    let user: User

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case tokenType = "token_type"
        case expiresIn = "expires_in"
        case refreshToken = "refresh_token"
        case user
    }
}

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
@Observable
class AuthenticationService: NSObject {
    var currentUser: User?
    var accessToken: String?
    var refreshToken: String?
    var isAuthenticated: Bool { currentUser != nil }

    private let baseURL: String
    private let session: URLSession

    init(baseURL: String = "http://localhost:8000/api/v1") {
        self.baseURL = baseURL
        self.session = URLSession.shared
        super.init()
        loadSavedTokens()
    }

    // MARK: - Google OAuth
    func authenticateWithGoogle(idToken: String) async throws -> User {
        let url = URL(string: "\(baseURL)/auth/google")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let authRequest = GoogleAuthRequest(idToken: idToken)
        request.httpBody = try JSONEncoder().encode(authRequest)

        // Debug logging
        print("📤 Sending request to: \(url.absoluteString)")
        if let bodyString = String(data: request.httpBody ?? Data(), encoding: .utf8) {
            print("📦 Request body: \(bodyString)")
        }

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw AuthError.invalidResponse
        }

        // Debug logging
        print("📥 Response status: \(httpResponse.statusCode)")
        if let responseString = String(data: data, encoding: .utf8) {
            print("📥 Response body: \(responseString)")
        }

        guard httpResponse.statusCode == 200 else {
            // Try to parse error message from response
            if let errorResponse = try? JSONDecoder().decode([String: String].self, from: data),
               let detail = errorResponse["detail"] {
                throw AuthError.serverError(detail)
            }
            throw AuthError.authenticationFailed(statusCode: httpResponse.statusCode)
        }

        let tokenResponse = try JSONDecoder().decode(TokenResponse.self, from: data)

        // Save tokens and user
        self.accessToken = tokenResponse.accessToken
        self.refreshToken = tokenResponse.refreshToken
        self.currentUser = tokenResponse.user
        saveTokens()

        return tokenResponse.user
    }

    // MARK: - Apple Sign In
    func authenticateWithApple(authorization: ASAuthorization) async throws -> User {
        guard let appleIDCredential = authorization.credential as? ASAuthorizationAppleIDCredential,
              let identityToken = appleIDCredential.identityToken,
              let idTokenString = String(data: identityToken, encoding: .utf8) else {
            throw AuthError.invalidAppleCredential
        }

        let url = URL(string: "\(baseURL)/auth/apple")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        var userInfo: [String: Any]?
        if let fullName = appleIDCredential.fullName {
            userInfo = [
                "name": [
                    "firstName": fullName.givenName ?? "",
                    "lastName": fullName.familyName ?? ""
                ]
            ]
        }

        let body: [String: Any] = [
            "id_token": idTokenString,
            "authorization_code": appleIDCredential.authorizationCode.map { String(data: $0, encoding: .utf8) } ?? "",
            "user_info": userInfo as Any
        ]

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw AuthError.invalidResponse
        }

        guard httpResponse.statusCode == 200 else {
            throw AuthError.authenticationFailed(statusCode: httpResponse.statusCode)
        }

        let tokenResponse = try JSONDecoder().decode(TokenResponse.self, from: data)

        // Save tokens and user
        self.accessToken = tokenResponse.accessToken
        self.refreshToken = tokenResponse.refreshToken
        self.currentUser = tokenResponse.user
        saveTokens()

        return tokenResponse.user
    }

    // MARK: - Token Management
    func refreshAccessToken() async throws {
        guard let refreshToken = refreshToken else {
            throw AuthError.noRefreshToken
        }

        let url = URL(string: "\(baseURL)/auth/refresh")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = ["refresh_token": refreshToken]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            throw AuthError.tokenRefreshFailed
        }

        let tokenResponse = try JSONDecoder().decode(TokenResponse.self, from: data)

        self.accessToken = tokenResponse.accessToken
        self.refreshToken = tokenResponse.refreshToken
        self.currentUser = tokenResponse.user
        saveTokens()
    }

    func signOut() {
        accessToken = nil
        refreshToken = nil
        currentUser = nil

        // Clear from UserDefaults
        UserDefaults.standard.removeObject(forKey: "accessToken")
        UserDefaults.standard.removeObject(forKey: "refreshToken")
        UserDefaults.standard.removeObject(forKey: "currentUser")
    }

    // MARK: - Persistence
    private func saveTokens() {
        if let accessToken = accessToken {
            UserDefaults.standard.set(accessToken, forKey: "accessToken")
        }
        if let refreshToken = refreshToken {
            UserDefaults.standard.set(refreshToken, forKey: "refreshToken")
        }
        if let currentUser = currentUser,
           let userData = try? JSONEncoder().encode(currentUser) {
            UserDefaults.standard.set(userData, forKey: "currentUser")
        }
    }

    private func loadSavedTokens() {
        accessToken = UserDefaults.standard.string(forKey: "accessToken")
        refreshToken = UserDefaults.standard.string(forKey: "refreshToken")

        if let userData = UserDefaults.standard.data(forKey: "currentUser"),
           let user = try? JSONDecoder().decode(User.self, from: userData) {
            currentUser = user
        }
    }
}

// MARK: - Errors
enum AuthError: LocalizedError {
    case invalidResponse
    case invalidAppleCredential
    case authenticationFailed(statusCode: Int)
    case tokenRefreshFailed
    case noRefreshToken
    case serverError(String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "Invalid response from server"
        case .invalidAppleCredential:
            return "Invalid Apple credential"
        case .authenticationFailed(let statusCode):
            return "Authentication failed with status code: \(statusCode)"
        case .tokenRefreshFailed:
            return "Failed to refresh token"
        case .noRefreshToken:
            return "No refresh token available"
        case .serverError(let message):
            return "Server error: \(message)"
        }
    }
}
