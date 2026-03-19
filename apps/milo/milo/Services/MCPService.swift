import Foundation
import MCP
import Observation

@MainActor
@Observable
class MCPService {
    static let shared = MCPService()

    private(set) var client: Client?
    private(set) var isConnected = false

    // Construct the MCP endpoint URL.
    // Pointing to localhost:8080/sse as requested for the local MCP server.
    private var serverURL: URL {
        return URL(string: "http://localhost:8080/sse")!
    }

    private init() {}

    func connect() async throws {
        // Initialize the client
        let client = Client(name: "Milo", version: "1.0.0")

        // Create a streaming HTTP transport for remote server communication
        // This assumes your backend supports the MCP HTTP transport with SSE
        let transport = HTTPClientTransport(
            endpoint: serverURL,
            streaming: true
        )

        // Connect and store the client
        let result = try await client.connect(transport: transport)
        self.client = client
        self.isConnected = true

        print("MCP Connected. Capabilities: \(result.capabilities)")

        if result.capabilities.tools != nil {
            print("Server supports tools")
        }
    }

    func listTools() async throws -> [MCP.Tool] {
        guard let client = client, isConnected else {
            throw MCPServiceError.notConnected
        }
        let (tools, _) = try await client.listTools()
        return tools
    }

    func callTool(name: String, arguments: [String: Any] = [:]) async throws -> [MCP.Tool.Content] {
        guard let client = client, isConnected else {
            throw MCPServiceError.notConnected
        }

        let (content, _) = try await client.callTool(name: name, arguments: arguments as? [String : Value])
        return content
    }
}

enum MCPServiceError: Error {
    case notConnected
}
