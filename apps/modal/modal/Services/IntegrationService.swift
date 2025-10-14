import Foundation
import AuthenticationServices
import Auth
import Supabase

/// Service for managing third-party integrations
@MainActor
@Observable
class IntegrationService {
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
    
    private var connectedServices: Set<ServiceType> = []
    private let backendURL: String
    private var authSession: ASWebAuthenticationSession?
    private let contextProvider = WebAuthenticationPresentationContextProvider()
    
    /// Check if any services are connected
    var hasConnectedIntegrations: Bool {
        !connectedServices.isEmpty
    }
    
    // MARK: - Initialization
    
    init(backendURL: String = "https://fk1k6d8vt9jw.share.zrok.io/api/v1") {
        self.backendURL = backendURL
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

        // This manual flow is more robust and bypasses the crashing Supabase helper function.
        // The app's backend still handles the secure OAuth token exchange with Supabase.
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
    
    /// Disconnect a service
    func disconnectService(_ service: ServiceType, authService: AuthenticationService) async throws {
        guard let session = authService.session else {
            throw IntegrationError.notAuthenticated
        }
        
        // Call backend to revoke access
        let url = URL(string: "\(backendURL)/integrations/\(service.rawValue)/disconnect")!
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
              let url = URL(string: "\(backendURL)/integrations/spotify/exchange?code=\(encodedCode)&state=\(encodedState)") else {
            print("❌ Failed to encode OAuth parameters")
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

                // For Spotify OAuth, we receive: modal://spotify/callback?code=...&state=...
                if callbackURL.host == "spotify" && callbackURL.path == "/callback" {
                    // Extract authorization code and state
                    guard let code = queryItems.first(where: { $0.name == "code" })?.value,
                          let state = queryItems.first(where: { $0.name == "state" })?.value else {
                        print("❌ Missing code or state in callback")
                        continuation.resume(throwing: IntegrationError.oauthFailed)
                        return
                    }

                    print("✅ Received authorization code for \(service.displayName)")
                    continuation.resume(returning: (code: code, state: state))
                } else {
                    // Fallback for services that don't need code exchange
                    // This shouldn't happen with Spotify
                    print("⚠️ Unexpected callback URL format: \(callbackURL)")
                    continuation.resume(throwing: IntegrationError.oauthFailed)
                }
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
