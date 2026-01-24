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

    func fetchCacheMetrics() async throws -> CacheMetricsModel {
        let url = URL(string: "\(backendURL)/tools/cache/metrics")!
        let (data, response) = try await URLSession.shared.data(from: url)
        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200
        else {
            throw ToolServiceError.fetchFailed
        }

        let decoder = JSONDecoder()
        return try decoder.decode(CacheMetricsModel.self, from: data)
    }

    func clearCache() async throws -> Int {
        let url = URL(string: "\(backendURL)/tools/cache/clear")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"

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
}

enum ToolServiceError: LocalizedError {
    case fetchFailed
    case clearFailed

    var errorDescription: String? {
        switch self {
        case .fetchFailed:
            return "Failed to fetch tools or cache metrics."
        case .clearFailed:
            return "Failed to clear cache."
        }
    }
}
