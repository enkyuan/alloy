import Auth
import Foundation

@MainActor
@Observable
class ToolService {
    static let shared = ToolService()

    private let backendURL: String

    nonisolated private init(backendURL: String = Environment.apiBaseURL) {
        self.backendURL = backendURL
    }

    func fetchTools() async throws -> [ToolSpecModel] {
        let url = URL(string: "\(backendURL)/tools")!
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200
        else {
            throw ToolServiceError.fetchFailed
        }

        let decoder = JSONDecoder()
        return try decoder.decode(ToolListResponse.self, from: data).tools
    }

    func fetchCacheMetrics(authService: AuthService) async throws -> CacheMetricsModel {
        let request = try authorizedRequest(
            path: "/tools/cache/metrics",
            authService: authService
        )
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200
        else {
            throw ToolServiceError.fetchFailed
        }

        let decoder = JSONDecoder()
        return try decoder.decode(CacheMetricsModel.self, from: data)
    }

    func clearCache(authService: AuthService) async throws -> Int {
        let request = try authorizedRequest(
            path: "/tools/cache/clear",
            method: "POST",
            authService: authService
        )
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200
        else {
            throw ToolServiceError.clearFailed
        }

        struct ClearResponse: Codable {
            let deleted: Int
        }

        let decoder = JSONDecoder()
        return try decoder.decode(ClearResponse.self, from: data).deleted
    }

    private func authorizedRequest(
        path: String,
        method: String = "GET",
        authService: AuthService
    ) throws -> URLRequest {
        guard let accessToken = authService.session?.accessToken, !accessToken.isEmpty else {
            throw ToolServiceError.notAuthenticated
        }

        let url = URL(string: "\(backendURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        return request
    }
}

enum ToolServiceError: LocalizedError {
    case fetchFailed
    case clearFailed
    case notAuthenticated

    var errorDescription: String? {
        switch self {
        case .fetchFailed:
            return "Failed to fetch tools or cache metrics."
        case .clearFailed:
            return "Failed to clear cache."
        case .notAuthenticated:
            return "Not authenticated."
        }
    }
}
