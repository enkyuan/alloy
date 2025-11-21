import Foundation
import AuthenticationServices
import Auth
import Supabase
import GoogleSignIn

/// Service for managing third-party integrations
@MainActor
@Observable
class IntegrationService {
    // MARK: - Singleton

    static let shared = IntegrationService()

    // MARK: - Service Types

    enum ServiceType: String {
        case spotify
        case gmail
        case googleCalendar
        case discord
        case todoist

        var displayName: String {
            switch self {
            case .spotify: return "Spotify"
            case .gmail: return "Gmail"
            case .googleCalendar: return "Google Calendar"
            case .discord: return "Discord"
            case .todoist: return "Todoist"
            }
        }

        var oauthEndpoint: String {
            switch self {
            case .spotify: return "/integrations/spotify/auth"
            case .gmail: return "/integrations/gmail/auth"
            case .googleCalendar: return "/integrations/google-calendar/auth"
            case .discord: return "/integrations/discord/auth"
            case .todoist: return "/integrations/todoist/auth"
            }
        }
        
        var backendServiceName: String {
            switch self {
            case .spotify: return "spotify"
            case .gmail: return "gmail"
            case .googleCalendar: return "google-calendar"
            case .discord: return "discord"
            case .todoist: return "todoist"
            }
        }
    }

    // MARK: - Properties

    private var connectedServices: Set<ServiceType> = [] {
        didSet {
            saveConnectedServices()
        }
    }
    private let backendURL: String
    private var authSession: ASWebAuthenticationSession?
    private let contextProvider = WebAuthenticationPresentationContextProvider()

    private let connectedServicesKey = "connectedServices"

    /// Check if any services are connected
    var hasConnectedIntegrations: Bool {
        !connectedServices.isEmpty
    }

    // MARK: - Initialization

    nonisolated private init(backendURL: String = Environment.apiBaseURL) {
        self.backendURL = backendURL
        Task { @MainActor in
            self.loadConnectedServices()
        }
    }

    // MARK: - Public Methods

    /// Fetch connected integrations from backend
    func fetchConnectedIntegrations(authService: AuthenticationService) async throws {
        guard let session = authService.session else {
            throw IntegrationError.notAuthenticated
        }

        let url = URL(string: "\(backendURL)/integrations")!
        var request = URLRequest(url: url)
        request.setValue("Bearer \(session.accessToken)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            throw IntegrationError.fetchFailed
        }

        struct IntegrationListResponse: Codable {
            let integrations: [IntegrationStatus]
        }

        struct IntegrationStatus: Codable {
            let service: String
            let connected: Bool
        }

        let integrationResponse = try JSONDecoder().decode(IntegrationListResponse.self, from: data)

        // Update connected services
        connectedServices.removeAll()
        for integration in integrationResponse.integrations where integration.connected {
            if let serviceType = ServiceType(rawValue: integration.service) {
                connectedServices.insert(serviceType)
            }
        }

        print("✅ Fetched connected integrations: \(connectedServices.map { $0.displayName }.joined(separator: ", "))")
    }

    /// Check if a service is connected
    func isConnected(_ service: ServiceType) -> Bool {
        connectedServices.contains(service)
    }

    /// Connect a service via OAuth
    func connectService(_ service: ServiceType, authService: AuthenticationService) async throws {
        print("🔗 Initiating OAuth for \(service.displayName)")

        guard let session = authService.session else {
            print("❌ Not authenticated")
            throw IntegrationError.notAuthenticated
        }

        // Use native Google Sign-In for Gmail (avoids loopback blocking)
        if service == .gmail || service == .googleCalendar {
            try await connectGoogleService(service, authService: authService)
            return
        }

        // For other services, use the web-based OAuth flow
        do {
            // 1. Get the auth URL from our own backend
            print("📡 Step 1: Getting OAuth URL from backend...")
            let authURL = try await getOAuthURL(for: service, accessToken: session.accessToken)
            print("✅ Received auth URL: \(authURL.absoluteString)")

            // 2. Present the web flow using ASWebAuthenticationSession
            print("🌐 Step 2: Presenting OAuth web flow...")
            let (code, state) = try await presentOAuthFlow(url: authURL, service: service)
            print("✅ Received callback - Code: \(code.prefix(20))..., State: \(state.prefix(20))...")

            // 3. Send the authorization code to our backend to be exchanged for tokens
            print("🔄 Step 3: Exchanging authorization code...")
            try await exchangeCode(code: code, state: state, accessToken: session.accessToken, service: service)

            // 4. Update the local state to reflect the new connection
            DispatchQueue.main.async {
                self.connectedServices.insert(service)
            }

            print("✅ Successfully connected \(service.displayName)")

        } catch let error as IntegrationError {
            print("❌ Integration error: \(error.localizedDescription)")
            throw error
        } catch {
            print("❌ Unexpected OAuth error: \(error.localizedDescription)")
            throw IntegrationError.oauthFailed
        }
    }

    /// Connect Gmail or Google Calendar using native Google Sign-In SDK
    private func connectGoogleService(_ service: ServiceType, authService: AuthenticationService) async throws {
        guard let session = authService.session else {
            throw IntegrationError.notAuthenticated
        }

        // Get root view controller for presenting Google Sign-In
        guard let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let rootViewController = windowScene.windows.first?.rootViewController else {
            throw IntegrationError.oauthFailed
        }

        // Configure scopes based on service
        let scopes: [String]
        switch service {
        case .gmail:
            scopes = [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send"
            ]
        case .googleCalendar:
            scopes = [
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/calendar.events"
            ]
        default:
            throw IntegrationError.oauthFailed
        }

        print("🔐 Requesting additional scopes for \(service.displayName): \(scopes)")

        // Use Google Sign-In SDK to request additional scopes
        return try await withCheckedThrowingContinuation { continuation in
            // Configure Google Sign-In with the required scopes
            guard let configuration = GIDSignIn.sharedInstance.configuration else {
                print("❌ Google Sign-In not configured")
                continuation.resume(throwing: IntegrationError.oauthFailed)
                return
            }
            
            // Create a new configuration with additional scopes
            _ = GIDConfiguration(
                clientID: configuration.clientID,
                serverClientID: configuration.serverClientID,
                hostedDomain: configuration.hostedDomain,
                openIDRealm: configuration.openIDRealm
            )
            
            // Request additional scopes by signing in again with the new scopes
            GIDSignIn.sharedInstance.signIn(
                withPresenting: rootViewController,
                hint: nil,
                additionalScopes: scopes
            ) { result, error in
                if let error = error {
                    let nsError = error as NSError
                    if nsError.code == -5 {
                        print("ℹ️ User cancelled \(service.displayName) permission request")
                        continuation.resume(throwing: IntegrationError.userCancelled)
                        return
                    }
                    print("❌ Failed to request scopes: \(error.localizedDescription)")
                    continuation.resume(throwing: IntegrationError.oauthFailed)
                    return
                }

                guard let result = result,
                      let idToken = result.user.idToken?.tokenString else {
                    print("❌ Failed to get Google tokens after scope request")
                    continuation.resume(throwing: IntegrationError.oauthFailed)
                    return
                }

                let accessToken = result.user.accessToken.tokenString

                print("✅ Got Google tokens with new scopes for \(service.displayName)")

                // Send tokens to backend
                Task {
                    do {
                        try await self.sendGoogleTokensToBackend(
                            idToken: idToken,
                            accessToken: accessToken,
                            service: service,
                            supabaseAccessToken: session.accessToken
                        )

                        // Update local state
                        _ = await MainActor.run {
                            self.connectedServices.insert(service)
                        }

                        print("✅ Successfully connected \(await service.displayName)")
                        continuation.resume()
                    } catch {
                        print("❌ Failed to send tokens to backend: \(error.localizedDescription)")
                        continuation.resume(throwing: IntegrationError.oauthFailed)
                    }
                }
            }
        }
    }

    /// Send Google tokens to backend for Gmail/Calendar integration
    private func sendGoogleTokensToBackend(
        idToken: String,
        accessToken: String,
        service: ServiceType,
        supabaseAccessToken: String
    ) async throws {
        // Map service to backend endpoint path
        let endpointPath: String
        switch service {
        case .gmail:
            endpointPath = "gmail"
        case .googleCalendar:
            endpointPath = "google-calendar"
        default:
            endpointPath = service.rawValue
        }

        let url = URL(string: "\(backendURL)/integrations/\(endpointPath)/connect-native")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(supabaseAccessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: String] = [
            "id_token": idToken,
            "access_token": accessToken
        ]

        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw IntegrationError.oauthFailed
        }

        if httpResponse.statusCode != 200 {
            let errorMessage = String(data: data, encoding: .utf8) ?? "No error message"
            print("❌ Backend returned error \(httpResponse.statusCode): \(errorMessage)")
            throw IntegrationError.oauthFailed
        }

        print("✅ Successfully sent Google tokens to backend")
    }

    /// Disconnect a service
    func disconnectService(_ service: ServiceType, authService: AuthenticationService) async throws {
        guard let session = authService.session else {
            throw IntegrationError.notAuthenticated
        }

        // Call backend to revoke access
        let url = URL(string: "\(backendURL)/integrations/\(service.backendServiceName)/disconnect")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(session.accessToken)", forHTTPHeaderField: "Authorization")

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            throw IntegrationError.disconnectFailed
        }

        connectedServices.remove(service)

        print("✅ Successfully disconnected \(service.displayName)")
    }

    // MARK: - Private Methods

    private func exchangeCode(code: String, state: String, accessToken: String, service: ServiceType) async throws {
        // Properly encode query parameters
        guard let encodedCode = code.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
              let encodedState = state.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
              let url = URL(string: "\(backendURL)/integrations/\(service.backendServiceName)/exchange?code=\(encodedCode)&state=\(encodedState)") else {
            print("❌ Failed to encode OAuth parameters for \(service.displayName)")
            throw IntegrationError.oauthFailed
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            print("❌ Invalid response from exchange endpoint")
            throw IntegrationError.oauthFailed
        }

        // Log response for debugging
        if httpResponse.statusCode != 200 {
            let errorMessage = String(data: data, encoding: .utf8) ?? "No error message"
            print("❌ Exchange failed with status \(httpResponse.statusCode): \(errorMessage)")
            throw IntegrationError.oauthFailed
        }

        print("✅ Successfully exchanged code for \(service.displayName)")
    }

    private func getOAuthURL(for service: ServiceType, accessToken: String) async throws -> URL {
        let url = URL(string: "\(backendURL)\(service.oauthEndpoint)")!
        var request = URLRequest(url: url)
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            print("❌ Invalid response from OAuth URL endpoint")
            throw IntegrationError.oauthURLFailed
        }

        if httpResponse.statusCode != 200 {
            let errorMessage = String(data: data, encoding: .utf8) ?? "No error message"
            print("❌ Failed to get OAuth URL (status \(httpResponse.statusCode)): \(errorMessage)")
            throw IntegrationError.oauthURLFailed
        }

        struct OAuthURLResponse: Codable {
            let authUrl: String
            let state: String?
        }

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        do {
            let oauthResponse = try decoder.decode(OAuthURLResponse.self, from: data)
            guard let authURL = URL(string: oauthResponse.authUrl) else {
                print("❌ Invalid OAuth URL in response: \(oauthResponse.authUrl)")
                throw IntegrationError.invalidURL
            }
            return authURL
        } catch {
            print("❌ Failed to decode OAuth URL response: \(error)")
            throw IntegrationError.oauthURLFailed
        }
    }

    private func presentOAuthFlow(url: URL, service: ServiceType) async throws -> (code: String, state: String) {
        // Use ASWebAuthenticationSession for OAuth flow
        return try await withCheckedThrowingContinuation { continuation in
            // Create the session and store it as a property to keep it alive
            self.authSession = ASWebAuthenticationSession(
                url: url,
                callbackURLScheme: "modal"
            ) { callbackURL, error in
                // Clear the session reference when done
                defer { self.authSession = nil }

                if let error = error {
                    // Check if user cancelled the authentication
                    let nsError = error as NSError
                    if nsError.domain == "com.apple.AuthenticationServices.WebAuthenticationSession"
                        && nsError.code == 1 {
                        // User cancelled - this is not an error, just resume normally
                        print("ℹ️ User cancelled OAuth for \(service.displayName)")
                        continuation.resume(throwing: IntegrationError.userCancelled)
                        return
                    }
                    print("❌ ASWebAuthenticationSession error: \(error.localizedDescription)")
                    continuation.resume(throwing: error)
                    return
                }

                guard let callbackURL = callbackURL else {
                    print("❌ No callback URL received")
                    continuation.resume(throwing: IntegrationError.noCallbackURL)
                    return
                }

                print("📱 Received callback URL: \(callbackURL.absoluteString)")

                // Parse callback URL parameters
                guard let components = URLComponents(url: callbackURL, resolvingAgainstBaseURL: false),
                      let queryItems = components.queryItems else {
                    print("❌ Could not parse callback URL components")
                    continuation.resume(throwing: IntegrationError.noCallbackURL)
                    return
                }

                // OAuth callback format: modal://{service}/callback?code=...&state=...
                // Extract authorization code and state from query parameters
                guard let code = queryItems.first(where: { $0.name == "code" })?.value,
                      let state = queryItems.first(where: { $0.name == "state" })?.value else {
                    print("❌ Missing code or state in callback for \(service.displayName)")
                    continuation.resume(throwing: IntegrationError.oauthFailed)
                    return
                }

                print("✅ Received authorization code for \(service.displayName)")
                continuation.resume(returning: (code: code, state: state))
            }

            // Use the retained context provider
            self.authSession?.presentationContextProvider = self.contextProvider

            // Prefer ephemeral session (doesn't save cookies)
            self.authSession?.prefersEphemeralWebBrowserSession = true

            // Start the session
            if self.authSession?.start() == false {
                print("❌ Failed to start ASWebAuthenticationSession")
                continuation.resume(throwing: IntegrationError.oauthFailed)
            } else {
                print("✅ ASWebAuthenticationSession started successfully")
            }
        }
    }

    // MARK: - Persistence

    private func saveConnectedServices() {
        let serviceNames = connectedServices.map { $0.rawValue }
        UserDefaults.standard.set(serviceNames, forKey: connectedServicesKey)
        print("💾 Saved connected services: \(serviceNames)")
    }

    private func loadConnectedServices() {
        guard let serviceNames = UserDefaults.standard.array(forKey: connectedServicesKey) as? [String] else {
            print("ℹ️ No saved connected services found")
            return
        }

        connectedServices = Set(serviceNames.compactMap { ServiceType(rawValue: $0) })
        print("📂 Loaded connected services: \(connectedServices.map { $0.displayName })")
    }

}

// MARK: - Presentation Context Provider

class WebAuthenticationPresentationContextProvider: NSObject, ASWebAuthenticationPresentationContextProviding {
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        // Get the first active window scene
        guard let windowScene = UIApplication.shared.connectedScenes
            .compactMap({ $0 as? UIWindowScene })
            .first(where: { $0.activationState == .foregroundActive }),
              let window = windowScene.windows.first(where: { $0.isKeyWindow }) ?? windowScene.windows.first else {
            // Fallback: try to get any available window from any window scene
            if let fallbackScene = UIApplication.shared.connectedScenes
                .compactMap({ $0 as? UIWindowScene })
                .first,
               let fallbackWindow = fallbackScene.windows.first(where: { $0.isKeyWindow }) ?? fallbackScene.windows.first {
                return fallbackWindow
            }
            // Last resort: return a new window
            print("⚠️ Warning: Could not find key window for OAuth presentation")
            return UIWindow()
        }
        return window
    }
}

// MARK: - Errors

enum IntegrationError: LocalizedError {
    case notAuthenticated
    case oauthURLFailed
    case invalidURL
    case oauthFailed
    case noCallbackURL
    case disconnectFailed
    case userCancelled
    case fetchFailed

    var errorDescription: String? {
        switch self {
        case .notAuthenticated:
            return "Not authenticated. Please sign in first."
        case .oauthURLFailed:
            return "Failed to get OAuth URL from server"
        case .invalidURL:
            return "Invalid OAuth URL"
        case .oauthFailed:
            return "OAuth authentication failed"
        case .noCallbackURL:
            return "No callback URL received"
        case .disconnectFailed:
            return "Failed to disconnect service"
        case .userCancelled:
            return nil // Don't show error for user cancellation
        case .fetchFailed:
            return "Failed to fetch integrations"
        }
    }
}

// Make ServiceType Codable
extension IntegrationService.ServiceType: Codable {}
