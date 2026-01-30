import Foundation

#if canImport(FoundationModels)
    import FoundationModels
#endif

actor OnDeviceReasoningService {
    static let shared = OnDeviceReasoningService()
    private let fallbackParser = OnDeviceCommandParser.shared

    #if canImport(FoundationModels)
        @available(iOS 26.0, *)
        private var session: LanguageModelSession?
    #endif

    private init() {}

    func parseCommand(_ text: String) async -> OnDeviceCommandParser.CommandType {
        #if canImport(FoundationModels)
            if #available(iOS 26.0, *) {
                if let parsed = await parseWithFoundationModels(text) {
                    return parsed
                }
            }
        #endif

        return fallbackParser.parseCommand(text)
    }

    #if canImport(FoundationModels)
        @available(iOS 26.0, *)
        private func parseWithFoundationModels(
            _ text: String
        ) async -> OnDeviceCommandParser.CommandType? {
            let model = SystemLanguageModel.default
            guard case .available = model.availability else {
                return nil
            }

            let session = getSession()
            let prompt = """
                Parse the user's command and respond with JSON only.
                Valid intents: play, pause, resume, next, previous, unknown.
                JSON schema:
                {"intent":"play|pause|resume|next|previous|unknown","query":"optional"}
                If the command is play with no specific song, set query to "".
                User command: "\(text)"
                """

            do {
                let response = try await session.respond(to: prompt)
                let content = response.content
                if let result = decodeCommandJSON(from: content) {
                    return mapToCommandType(result)
                }
            } catch {
                return nil
            }

            return nil
        }

        @available(iOS 26.0, *)
        private func getSession() -> LanguageModelSession {
            if let session = session {
                return session
            }

            let instructions = """
                You are a strict JSON command parser for a music assistant.
                Only output JSON. Do not add commentary or extra text.
                """

            let newSession = LanguageModelSession(instructions: instructions)
            session = newSession
            return newSession
        }

        private struct CommandJSON: Decodable {
            let intent: String
            let query: String?
        }

        private func decodeCommandJSON(from content: String) -> CommandJSON? {
            let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let jsonText = extractJSONObject(from: trimmed),
                let data = jsonText.data(using: .utf8)
            else {
                return nil
            }
            return try? JSONDecoder().decode(CommandJSON.self, from: data)
        }

        private func extractJSONObject(from text: String) -> String? {
            guard let start = text.firstIndex(of: "{"),
                let end = text.lastIndex(of: "}")
            else {
                return nil
            }
            return String(text[start...end])
        }

        private func mapToCommandType(_ result: CommandJSON) -> OnDeviceCommandParser.CommandType {
            switch result.intent.lowercased() {
            case "play":
                let rawQuery = result.query ?? ""
                let normalized = OnDeviceCommandParser.shared.normalizeQuery(rawQuery)
                return .play(query: normalized)
            case "pause":
                return .pause
            case "resume":
                return .resume
            case "next":
                return .skipNext
            case "previous":
                return .skipPrevious
            default:
                return .unknown
            }
        }
    #endif
}
