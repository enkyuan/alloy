import Foundation

struct ToolSpecModel: Codable, Identifiable {
    let name: String
    let description: String
    let parameters: [String: AnyCodable]

    var id: String { name }
}

struct ToolListResponse: Codable {
    let tools: [ToolSpecModel]
}

struct CacheMetricsModel: Codable {
    let hit: Int
    let miss: Int
}
