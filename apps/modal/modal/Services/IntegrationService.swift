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
        case uber
        case gmail
        case googleCalendar

        var displayName: String {
            switch self {
            case .spotify: return "Spotify"
            case .uber: return "Uber"
            case .gmail: return "Gmail"
            case .googleCalendar: return "Google Calendar"
            }
        }

        var oauthEndpoint: String {
            switch self {
            case .spotify: return "/integrations/spotify/auth"
            case .uber: return "/integrations/uber/auth"
            case .gmail: return "/integrations/gmail/auth"
            case .googleCalendar: return "/integrations/google-calendar/auth"
            }
        }
    }

    // MARK: - Properties

    private var connectedServices: Set<ServiceType> = [] {
        didSet {
            saveConnectedServices()
        }
    }
    
    // Track recently connected services to prevent them from being removed by backend refresh
    private var recentlyConnectedServices: Set<ServiceType> = []
    private var recentConnectionTime: Date?
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

        print("📡 Backend returned integrations: \(integrationResponse.integrations.map { "\($0.service):\($0.connected)" }.joined(separator: ", "))")

        // Update connected services more conservatively
        // Instead of clearing all and rebuilding, update based on backend response
        let previousServices = connectedServices
        
        // Create a set of services from backend response
        var backendServices: Set<ServiceType> = []
        for integration in integrationResponse.integrations where integration.connected {
            print("🔍 Processing integration: service=\(integration.service), connected=\(integration.connected)")
            
            // Try direct mapping first
            var serviceType = ServiceType(rawValue: integration.service)
            
            // If direct mapping fails, try snake_case to camelCase conversion
            if serviceType == nil {
                let convertedService = convertSnakeCaseToCamelCase(integration.service)
                serviceType = ServiceType(rawValue: convertedService)
                print("🔄 Converted '\(integration.service)' to '\(convertedService)'")
            }
            
            if let serviceType = serviceType {
                backendServices.insert(serviceType)
                print("✅ Backend reports \(serviceType.displayName) as connected")
            } else {
                print("❌ Unknown service type from backend: \(integration.service)")
            }
        }
        
        // Merge backend services with recently connected services
        var finalServices = backendServices
        
        // Protect recently connected services (within last 10 seconds)
        if let recentTime = recentConnectionTime,
           Date().timeIntervalSince(recentTime) < 10.0 {
            print("🛡️ Protecting recently connected services: \(recentlyConnectedServices.map { $0.displayName }.joined(separator: ", "))")
            finalServices.formUnion(recentlyConnectedServices)
        } else {
            // Clear recent connections after 10 seconds
            recentlyConnectedServices.removeAll()
            recentConnectionTime = nil
        }
        
        // Only update if we got a meaningful response from backend or have recent connections
        if !integrationResponse.integrations.isEmpty || !recentlyConnectedServices.isEmpty {
            connectedServices = finalServices
            print("📊 Updated connected services (merged backend + recent)")
        } else {
            print("⚠️ Backend returned empty integrations list and no recent connections, keeping local state")
        }

        print("📊 Connected services before: \(previousServices.map { $0.displayName }.joined(separator: ", "))")
        print("📊 Connected services after: \(connectedServices.map { $0.displayName }.joined(separator: ", "))")
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
                            // Mark as recently connected to protect from backend refresh
                            self.recentlyConnectedServices.insert(service)
                            self.recentConnectionTime = Date()
                        }

                        print("✅ Successfully connected \(await service.displayName)")
                        
                        // Refresh integrations from backend to ensure consistency
                        // This is important because the backend might have additional logic
                        // or the local state might not perfectly match the backend state
                        print("🔄 Refreshing integrations from backend...")
                        // Note: We don't await this to avoid blocking the UI
                        Task {
                            // Small delay to ensure backend has processed the integration
                            try? await Task.sleep(nanoseconds: 500_000_000) // 0.5 seconds
                            
                            do {
                                try await self.fetchConnectedIntegrations(authService: authService)
                                print("✅ Successfully refreshed integrations after connecting \(service.displayName)")
                            } catch {
                                print("⚠️ Failed to refresh integrations after connecting: \(error)")
                                // Don't fail the connection if refresh fails
                            }
                        }
                        
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
            print("❌ Backend returned error \(httpResponse.statusCode) for \(service.displayName): \(errorMessage)")
            throw IntegrationError.oauthFailed
        }

        let responseString = String(data: data, encoding: .utf8) ?? "No response"
        print("✅ Successfully sent \(service.displayName) tokens to backend. Response: \(responseString)")
    }

    /// Disconnect a service
    func disconnectService(_ service: ServiceType, authService: AuthenticationService) async throws {
        guard let session = authService.session else {
            throw IntegrationError.notAuthenticated
        }

        // Map service to backend endpoint path (use specific endpoints for Google services)
        let endpointPath: String
        switch service {
        case .gmail:
            endpointPath = "gmail"
        case .googleCalendar:
            endpointPath = "google-calendar"  // Use specific endpoint
        default:
            endpointPath = service.rawValue
        }

        print("🔍 Service: \(service), Raw Value: \(service.rawValue), Endpoint Path: \(endpointPath)")

        // Call backend to revoke access using specific disconnect endpoints
        // For Google Calendar, force the specific endpoint
        let url: URL
        if service == .googleCalendar {
            url = URL(string: "\(backendURL)/integrations/google-calendar/disconnect")!
        } else {
            url = URL(string: "\(backendURL)/integrations/\(endpointPath)/disconnect")!
        }
        print("🔌 Disconnecting \(service.displayName) via URL: \(url.absoluteString)")
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(session.accessToken)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw IntegrationError.disconnectFailed
        }

        if httpResponse.statusCode != 200 {
            let errorMessage = String(data: data, encoding: .utf8) ?? "No error message"
            print("❌ Backend returned error \(httpResponse.statusCode) when disconnecting \(service.displayName): \(errorMessage)")
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
              let url = URL(string: "\(backendURL)/integrations/\(service.rawValue)/exchange?code=\(encodedCode)&state=\(encodedState)") else {
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
    
    /// Convert snake_case to camelCase for service names
    private func convertSnakeCaseToCamelCase(_ snakeCase: String) -> String {
        let components = snakeCase.components(separatedBy: "_")
        guard components.count > 1 else { return snakeCase }
        
        let first = components[0]
        let rest = components.dropFirst().map { $0.capitalized }
        return first + rest.joined()
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
