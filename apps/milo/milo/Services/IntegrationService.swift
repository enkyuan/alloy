import Auth
import AuthenticationServices
import Foundation
import GoogleSignIn
import Supabase

@MainActor
@Observable
class IntegrationService {

    static let shared = IntegrationService()

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift

=======
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
    enum ServiceType: String {
        case spotify
        case gmail
        case googleCalendar
        case discord
        case todoist
        case calendly

        var displayName: String {
            switch self {
            case .spotify: return "Spotify"
            case .gmail: return "Gmail"
            case .googleCalendar: return "Google Calendar"
            case .discord: return "Discord"
            case .todoist: return "Todoist"
            case .calendly: return "Calendly"
            }
        }

        var oauthEndpoint: String {
            switch self {
            case .spotify: return "/integrations/spotify/auth"
            case .gmail: return "/integrations/gmail/auth"
            case .googleCalendar: return "/integrations/google-calendar/auth"
            case .discord: return "/integrations/discord/auth"
            case .todoist: return "/integrations/todoist/auth"
            case .calendly: return "/integrations/calendly/auth"
            }
        }

        var backendServiceName: String {
            switch self {
            case .spotify: return "spotify"
            case .gmail: return "gmail"
            case .googleCalendar: return "google-calendar"
            case .discord: return "discord"
            case .todoist: return "todoist"
            case .calendly: return "calendly"
            }
        }
    }

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift

=======
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
    private var connectedServices: Set<ServiceType> = [] {
        didSet {
            saveConnectedServices()
        }
    }
    private let backendURL: String
    private var authSession: ASWebAuthenticationSession?
    private let contextProvider = WebAuthenticationPresentationContextProvider()

    private let connectedServicesKey = "connectedServices"

    var hasConnectedIntegrations: Bool {
        !connectedServices.isEmpty
    }

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift

    nonisolated private init(backendURL: String = Environment.apiBaseURL) {
=======
    private init(backendURL: String = Environment.apiBaseURL) {
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
        self.backendURL = backendURL
        loadConnectedServices()
    }

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift

    func fetchConnectedIntegrations(authService: AuthService) async throws {
        guard let session = authService.session else {
            throw IntegrationError.notAuthenticated
        }
=======
    func fetchConnectedIntegrations(authService: AuthService) async throws {
        let accessToken = try await resolveAccessToken(authService: authService)
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift

        let url = URL(string: "\(backendURL)/integrations")!
        var request = URLRequest(url: url)
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw IntegrationError.fetchFailed
        }

        if httpResponse.statusCode == 401 {
            await authService.handleBackendUnauthorized()
            throw IntegrationError.notAuthenticated
        }

        guard httpResponse.statusCode == 200 else {
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

        connectedServices.removeAll()
        for integration in integrationResponse.integrations where integration.connected {
            if let serviceType = ServiceType(rawValue: integration.service) {
                connectedServices.insert(serviceType)
            }
        }

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
        print("Fetched connected integrations: \(connectedServices.map { $0.displayName }.joined(separator: ", "))")
=======
        print(
            "Fetched connected integrations: \(connectedServices.map { $0.displayName }.joined(separator: ", "))"
        )
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
    }

    func isConnected(_ service: ServiceType) -> Bool {
        connectedServices.contains(service)
    }

    func connectService(_ service: ServiceType, authService: AuthService) async throws {
<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
        print("Initiating OAuth for \(service.displayName)")

        guard let session = authService.session else {
=======
        if ProcessInfo.processInfo.arguments.contains("--mock-auth") {
            print("[Mock] simulating connection to \(service.displayName)")
            try? await Task.sleep(nanoseconds: 500_000_000) // 0.5s delay
            DispatchQueue.main.async {
                self.connectedServices.insert(service)
            }
            return
        }

        print("Initiating OAuth for \(service.displayName)")

        guard authService.isAuthenticated else {
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
            print("Not authenticated")
            throw IntegrationError.notAuthenticated
        }

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
=======
        let supabaseAccessToken = try await resolveAccessToken(authService: authService)

>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
        if service == .gmail || service == .googleCalendar {
            try await connectGoogleService(service, authService: authService)
            return
        }

        do {
            print("Step 1: Getting OAuth URL from backend...")
<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
            let authURL = try await getOAuthURL(for: service, accessToken: session.accessToken)
=======
            let authURL = try await getOAuthURL(
                for: service,
                accessToken: supabaseAccessToken,
                authService: authService
            )
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
            print("Received auth URL: \(authURL.absoluteString)")

            print("Step 2: Presenting OAuth web flow...")
            let (code, state) = try await presentOAuthFlow(url: authURL, service: service)
            print("Received callback - Code: \(code.prefix(20))..., State: \(state.prefix(20))...")

            print("Step 3: Exchanging authorization code...")
<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
            try await exchangeCode(code: code, state: state, accessToken: session.accessToken, service: service)
=======
            try await exchangeCode(
                code: code,
                state: state,
                accessToken: supabaseAccessToken,
                service: service,
                authService: authService
            )
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift

            DispatchQueue.main.async {
                self.connectedServices.insert(service)
            }

            print("Successfully connected \(service.displayName)")

        } catch let error as IntegrationError {
            print("Integration error: \(error.localizedDescription)")
            throw error
        } catch {
            print("Unexpected OAuth error: \(error.localizedDescription)")
            throw IntegrationError.oauthFailed
        }
    }

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
    private func connectGoogleService(_ service: ServiceType, authService: AuthService) async throws {
        guard let session = authService.session else {
=======
    private func connectGoogleService(_ service: ServiceType, authService: AuthService) async throws
    {
        guard authService.isAuthenticated else {
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
            throw IntegrationError.notAuthenticated
        }

        guard let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
            let rootViewController = windowScene.windows.first?.rootViewController
        else {
            throw IntegrationError.oauthFailed
        }

        let scopes: [String]
        switch service {
        case .gmail:
            scopes = [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
            ]
        case .googleCalendar:
            scopes = [
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/calendar.events",
            ]
        default:
            throw IntegrationError.oauthFailed
        }

        print("Requesting additional scopes for \(service.displayName): \(scopes)")

        return try await withCheckedThrowingContinuation { continuation in
            guard let configuration = GIDSignIn.sharedInstance.configuration else {
                print("Google Sign-In not configured")
                continuation.resume(throwing: IntegrationError.oauthFailed)
                return
            }

            _ = GIDConfiguration(
                clientID: configuration.clientID,
                serverClientID: configuration.serverClientID,
                hostedDomain: configuration.hostedDomain,
                openIDRealm: configuration.openIDRealm
            )

            GIDSignIn.sharedInstance.signIn(
                withPresenting: rootViewController,
                hint: nil,
                additionalScopes: scopes
            ) { result, error in
                if let error = error {
                    let nsError = error as NSError
                    if nsError.code == -5 {
                        print("User cancelled \(service.displayName) permission request")
                        continuation.resume(throwing: IntegrationError.userCancelled)
                        return
                    }
                    print("Failed to request scopes: \(error.localizedDescription)")
                    continuation.resume(throwing: IntegrationError.oauthFailed)
                    return
                }

                guard let result = result,
<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
                      let idToken = result.user.idToken?.tokenString else {
=======
                    let idToken = result.user.idToken?.tokenString
                else {
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
                    print("Failed to get Google tokens after scope request")
                    continuation.resume(throwing: IntegrationError.oauthFailed)
                    return
                }

                let accessToken = result.user.accessToken.tokenString

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
                print("Got Google tokens with new scopes for \(service.displayName)")
=======
                let serviceName = service.displayName
                print("Got Google tokens with new scopes for \(serviceName)")
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift

                Task {
                    do {
                        let supabaseAccessToken = try await self.resolveAccessToken(
                            authService: authService
                        )
                        try await self.sendGoogleTokensToBackend(
                            idToken: idToken,
                            accessToken: accessToken,
                            service: service,
                            supabaseAccessToken: supabaseAccessToken,
                            authService: authService
                        )

                        _ = await MainActor.run {
                            self.connectedServices.insert(service)
                        }

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
                        print("Successfully connected \(await service.displayName)")
=======
                        print("Successfully connected \(serviceName)")
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
                        continuation.resume()
                    } catch let error as IntegrationError {
                        print("Failed to send tokens to backend: \(error.localizedDescription)")
                        continuation.resume(throwing: error)
                    } catch {
                        print("Failed to send tokens to backend: \(error.localizedDescription)")
                        continuation.resume(throwing: IntegrationError.oauthFailed)
                    }
                }
            }
        }
    }

    private func sendGoogleTokensToBackend(
        idToken: String,
        accessToken: String,
        service: ServiceType,
        supabaseAccessToken: String,
        authService: AuthService
    ) async throws {
        let endpointPath: String
        switch service {
        case .gmail:
            endpointPath = "gmail"
        case .googleCalendar:
            endpointPath = "google-calendar"
        default:
            endpointPath = service.rawValue
        }

        let url = URL(string: "\(backendURL)/integrations/\(endpointPath)/sync")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(supabaseAccessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: String] = [
            "id_token": idToken,
            "access_token": accessToken,
        ]

        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw IntegrationError.oauthFailed
        }

        if httpResponse.statusCode != 200 {
            let errorMessage = String(data: data, encoding: .utf8) ?? "No error message"
            print("Backend returned error \(httpResponse.statusCode): \(errorMessage)")
<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
=======
            if httpResponse.statusCode == 401 {
                await authService.handleBackendUnauthorized()
                throw IntegrationError.notAuthenticated
            }
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
            throw IntegrationError.oauthFailed
        }

        print("Successfully sent Google tokens to backend")
    }

    func disconnectService(_ service: ServiceType, authService: AuthService) async throws {
<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
        guard let session = authService.session else {
            throw IntegrationError.notAuthenticated
        }

        let url = URL(string: "\(backendURL)/integrations/\(service.backendServiceName)/disconnect")!
=======
        let accessToken = try await resolveAccessToken(authService: authService)

        let url = URL(
            string: "\(backendURL)/integrations/\(service.backendServiceName)/disconnect")!
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw IntegrationError.disconnectFailed
        }

        if httpResponse.statusCode == 401 {
            await authService.handleBackendUnauthorized()
            throw IntegrationError.notAuthenticated
        }

        guard httpResponse.statusCode == 200 else {
            throw IntegrationError.disconnectFailed
        }

        connectedServices.remove(service)

        print("Successfully disconnected \(service.displayName)")
    }

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift

    private func exchangeCode(code: String, state: String, accessToken: String, service: ServiceType) async throws {
        guard let encodedCode = code.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
              let encodedState = state.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
              let url = URL(string: "\(backendURL)/integrations/\(service.backendServiceName)/exchange?code=\(encodedCode)&state=\(encodedState)") else {
=======
    private func exchangeCode(
        code: String,
        state: String,
        accessToken: String,
        service: ServiceType,
        authService: AuthService
    ) async throws {
        guard let encodedCode = code.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
            let encodedState = state.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed),
            let url = URL(
                string:
                    "\(backendURL)/integrations/\(service.backendServiceName)/exchange?code=\(encodedCode)&state=\(encodedState)"
            )
        else {
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
            print("Failed to encode OAuth parameters for \(service.displayName)")
            throw IntegrationError.oauthFailed
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            print("Invalid response from exchange endpoint")
            throw IntegrationError.oauthFailed
        }

        if httpResponse.statusCode != 200 {
            let errorMessage = String(data: data, encoding: .utf8) ?? "No error message"
            print("Exchange failed with status \(httpResponse.statusCode): \(errorMessage)")
<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
=======
            if httpResponse.statusCode == 401 {
                await authService.handleBackendUnauthorized()
                throw IntegrationError.notAuthenticated
            }
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
            throw IntegrationError.oauthFailed
        }

        print("Successfully exchanged code for \(service.displayName)")
    }

    private func getOAuthURL(
        for service: ServiceType,
        accessToken: String,
        authService: AuthService
    ) async throws -> URL {
        let url = URL(string: "\(backendURL)\(service.oauthEndpoint)")!
        var request = URLRequest(url: url)
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            print("Invalid response from OAuth URL endpoint")
            throw IntegrationError.oauthURLFailed
        }

        if httpResponse.statusCode != 200 {
            let errorMessage = String(data: data, encoding: .utf8) ?? "No error message"
            print("Failed to get OAuth URL (status \(httpResponse.statusCode)): \(errorMessage)")
<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
=======
            if httpResponse.statusCode == 401 {
                await authService.handleBackendUnauthorized()
                throw IntegrationError.notAuthenticated
            }
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
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
<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
            guard let authURL = URL(string: oauthResponse.authUrl) else {
                print("Invalid OAuth URL in response: \(oauthResponse.authUrl)")
                throw IntegrationError.invalidURL
            }
=======
            let authURL = try sanitizeOAuthURL(oauthResponse.authUrl)
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
            return authURL
        } catch {
            print("Failed to decode OAuth URL response: \(error)")
            throw IntegrationError.oauthURLFailed
        }
    }

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
    private func presentOAuthFlow(url: URL, service: ServiceType) async throws -> (code: String, state: String) {
=======
    private func sanitizeOAuthURL(_ rawURL: String) throws -> URL {
        if let url = URL(string: rawURL), url.scheme != nil {
            return url
        }

        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~:/?#[]@!$&'()*+,;=")

        if let encoded = rawURL.addingPercentEncoding(withAllowedCharacters: allowed),
            let url = URL(string: encoded),
            url.scheme != nil
        {
            print("OAuth URL required percent-encoding. Raw: \(rawURL)")
            return url
        }

        print("Invalid OAuth URL in response: \(rawURL)")
        throw IntegrationError.invalidURL
    }

    private func resolveAccessToken(authService: AuthService) async throws -> String {
        do {
            let session = try await supabase.auth.session
            authService.session = session
            return session.accessToken
        } catch {
            print("Unable to resolve active Supabase session: \(error.localizedDescription)")
            throw IntegrationError.notAuthenticated
        }
    }

    private func presentOAuthFlow(url: URL, service: ServiceType) async throws -> (
        code: String, state: String
    ) {
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
        return try await withCheckedThrowingContinuation { continuation in
            self.authSession = ASWebAuthenticationSession(
                url: url,
                callbackURLScheme: "milo"
            ) { callbackURL, error in
                defer { self.authSession = nil }

                if let error = error {
                    let nsError = error as NSError
                    if nsError.domain == "com.apple.AuthenticationServices.WebAuthenticationSession"
<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
                        && nsError.code == 1 {
=======
                        && nsError.code == 1
                    {
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
                        print("User cancelled OAuth for \(service.displayName)")
                        continuation.resume(throwing: IntegrationError.userCancelled)
                        return
                    }
                    print("ASWebAuthenticationSession error: \(error.localizedDescription)")
                    continuation.resume(throwing: error)
                    return
                }

                guard let callbackURL = callbackURL else {
                    print("No callback URL received")
                    continuation.resume(throwing: IntegrationError.noCallbackURL)
                    return
                }

                print("Received callback URL: \(callbackURL.absoluteString)")

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
                guard let components = URLComponents(url: callbackURL, resolvingAgainstBaseURL: false),
                      let queryItems = components.queryItems else {
=======
                guard
                    let components = URLComponents(
                        url: callbackURL, resolvingAgainstBaseURL: false),
                    let queryItems = components.queryItems
                else {
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
                    print("Could not parse callback URL components")
                    continuation.resume(throwing: IntegrationError.noCallbackURL)
                    return
                }

                guard let code = queryItems.first(where: { $0.name == "code" })?.value,
<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
                      let state = queryItems.first(where: { $0.name == "state" })?.value else {
=======
                    let state = queryItems.first(where: { $0.name == "state" })?.value
                else {
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
                    print("Missing code or state in callback for \(service.displayName)")
                    continuation.resume(throwing: IntegrationError.oauthFailed)
                    return
                }

                print("Received authorization code for \(service.displayName)")
                continuation.resume(returning: (code: code, state: state))
            }

            self.authSession?.presentationContextProvider = self.contextProvider

            self.authSession?.prefersEphemeralWebBrowserSession = true

            if self.authSession?.start() == false {
                print("Failed to start ASWebAuthenticationSession")
                continuation.resume(throwing: IntegrationError.oauthFailed)
            } else {
                print("ASWebAuthenticationSession started successfully")
            }
        }
    }

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
=======
    func clearCachedConnectedServices() {
        connectedServices.removeAll()
        UserDefaults.standard.removeObject(forKey: connectedServicesKey)
        print("Cleared connected services cache")
    }
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift

    private func saveConnectedServices() {
        let serviceNames = connectedServices.map { $0.rawValue }
        UserDefaults.standard.set(serviceNames, forKey: connectedServicesKey)
        print("Saved connected services: \(serviceNames)")
    }

    private func loadConnectedServices() {
<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift
        guard let serviceNames = UserDefaults.standard.array(forKey: connectedServicesKey) as? [String] else {
=======
        guard
            let serviceNames = UserDefaults.standard.array(forKey: connectedServicesKey)
                as? [String]
        else {
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
            print("No saved connected services found")
            return
        }

        connectedServices = Set(serviceNames.compactMap { ServiceType(rawValue: $0) })
        print("Loaded connected services: \(connectedServices.map { $0.displayName })")
    }

}

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift

class WebAuthenticationPresentationContextProvider: NSObject, ASWebAuthenticationPresentationContextProviding {
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        guard let windowScene = UIApplication.shared.connectedScenes
            .compactMap({ $0 as? UIWindowScene })
            .first(where: { $0.activationState == .foregroundActive }),
              let window = windowScene.windows.first(where: { $0.isKeyWindow }) ?? windowScene.windows.first else {
            if let fallbackScene = UIApplication.shared.connectedScenes
                .compactMap({ $0 as? UIWindowScene })
                .first,
               let fallbackWindow = fallbackScene.windows.first(where: { $0.isKeyWindow }) ?? fallbackScene.windows.first {
                return fallbackWindow
            }
            print("Warning: Could not find key window for OAuth presentation")
            return UIWindow()
=======
class WebAuthenticationPresentationContextProvider: NSObject,
    ASWebAuthenticationPresentationContextProviding
{
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        let scenes = UIApplication.shared.connectedScenes
        let windowScene =
            scenes.compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive }
            ?? scenes.compactMap { $0 as? UIWindowScene }.first

        if let windowScene = windowScene {
            return windowScene.windows.first { $0.isKeyWindow }
                ?? windowScene.windows.first
                ?? UIWindow(windowScene: windowScene)
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
        }

        print("Warning: Could not find any UIWindowScene for OAuth presentation")
        // Fallback: try to create a window with any available window scene
        if let anyScene = UIApplication.shared.connectedScenes.first as? UIWindowScene {
            return UIWindow(windowScene: anyScene)
        }
        // Last resort: return a basic window (may not work properly for presentation)
        fatalError("No UIWindowScene available for OAuth presentation")
    }
}

<<<<<<< HEAD:apps/modal/modal/Services/IntegrationService.swift

=======
>>>>>>> codex/refactor:apps/milo/milo/Services/IntegrationService.swift
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
            return nil
        case .fetchFailed:
            return "Failed to fetch integrations"
        }
    }
}

extension IntegrationService.ServiceType: Codable {}
