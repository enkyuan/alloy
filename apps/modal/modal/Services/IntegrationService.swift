import Foundation
import AuthenticationServices
import Auth

/// Service for managing third-party integrations
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
    
    // MARK: - Initialization
    
    init(backendURL: String = "http://localhost:8000/api/v1") {
        self.backendURL = backendURL
        // Don't load from UserDefaults, fetch from backend instead
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
            throw IntegrationError.notAuthenticated
        }
        
        // Get OAuth URL from backend
        let authURL = try await getOAuthURL(for: service, accessToken: session.accessToken)
        
        // Present OAuth flow
        try await presentOAuthFlow(url: authURL, service: service)
        
        // Fetch updated integrations from backend
        try await fetchConnectedIntegrations(authService: authService)
        
        print("✅ Successfully connected \(service.displayName)")
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
    
    private func getOAuthURL(for service: ServiceType, accessToken: String) async throws -> URL {
        let url = URL(string: "\(backendURL)\(service.oauthEndpoint)")!
        var request = URLRequest(url: url)
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        
        let (data, response) = try await URLSession.shared.data(for: request)
        
        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            throw IntegrationError.oauthURLFailed
        }
        
            struct OAuthURLResponse: Codable {
                let authUrl: String
                let state: String?
            }
            
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let oauthResponse = try decoder.decode(OAuthURLResponse.self, from: data)
            guard let authURL = URL(string: oauthResponse.authUrl) else {
                throw IntegrationError.invalidURL
            }
        
        return authURL
    }
    
    private func presentOAuthFlow(url: URL, service: ServiceType) async throws {
        // Use ASWebAuthenticationSession for OAuth flow
        return try await withCheckedThrowingContinuation { continuation in
            let session = ASWebAuthenticationSession(
                url: url,
                callbackURLScheme: "modal"
            ) { callbackURL, error in
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
                    continuation.resume(throwing: error)
                    return
                }
                
                guard let callbackURL = callbackURL else {
                    continuation.resume(throwing: IntegrationError.noCallbackURL)
                    return
                }
                
                // Parse callback URL parameters
                guard let components = URLComponents(url: callbackURL, resolvingAgainstBaseURL: false),
                      let queryItems = components.queryItems else {
                    continuation.resume(throwing: IntegrationError.noCallbackURL)
                    return
                }
                
                // Check for success parameter
                if let successParam = queryItems.first(where: { $0.name == "success" }),
                   successParam.value == "true" {
                    continuation.resume()
                } else if let errorParam = queryItems.first(where: { $0.name == "error" }) {
                    print("❌ OAuth error: \(errorParam.value ?? "unknown")")
                    continuation.resume(throwing: IntegrationError.oauthFailed)
                } else {
                    continuation.resume(throwing: IntegrationError.oauthFailed)
                }
            }
            
            session.presentationContextProvider = WebAuthenticationPresentationContextProvider()
            session.start()
        }
    }
    
}

// MARK: - Presentation Context Provider

class WebAuthenticationPresentationContextProvider: NSObject, ASWebAuthenticationPresentationContextProviding {
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        guard let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let window = windowScene.windows.first else {
            return ASPresentationAnchor()
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

