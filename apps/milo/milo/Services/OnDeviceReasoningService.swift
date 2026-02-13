import Foundation

#if canImport(FoundationModels)
    import FoundationModels
#endif

actor OnDeviceReasoningService {
    static let shared = OnDeviceReasoningService()

    struct ParseHint: Sendable {
        let intent: String
        let query: String?
        let confidence: Double
        let source: String

        var asDictionary: [String: Any] {
            var payload: [String: Any] = [
                "intent": intent,
                "confidence": confidence,
                "source": source,
            ]
            if let query, !query.isEmpty {
                payload["query"] = query
            }
            return payload
        }
    }

    #if canImport(FoundationModels)
        @available(iOS 26.0, *)
        private var session: LanguageModelSession?
    #endif

    private init() {}

    func parseCommandHint(
        _ text: String,
        timeoutMilliseconds: UInt64 = 160
    ) async -> ParseHint? {
        #if canImport(FoundationModels)
            if #available(iOS 26.0, *) {
                let model = SystemLanguageModel.default
                guard case .available = model.availability else {
                    return nil
                }
                return await parseWithTimeout(
                    text: text,
                    timeoutMilliseconds: timeoutMilliseconds
                )
            }
        #endif

        return nil
    }

    #if canImport(FoundationModels)
        @available(iOS 26.0, *)
        private func parseWithTimeout(
            text: String,
            timeoutMilliseconds: UInt64
        ) async -> ParseHint? {
            let parseTask = Task { [weak self] () -> ParseHint? in
                guard let self else { return nil }
                return await self.parseWithFoundationModels(text)
            }
            let timeoutTask = Task { () -> ParseHint? in
                try? await Task.sleep(
                    nanoseconds: timeoutMilliseconds * 1_000_000
                )
                return nil
            }

            let result = await withTaskGroup(of: ParseHint?.self) { group in
                group.addTask { await parseTask.value }
                group.addTask { await timeoutTask.value }
                guard let first = await group.next() else {
                    return nil
                }
                group.cancelAll()
                return first
            }

            parseTask.cancel()
            timeoutTask.cancel()
            return result
        }

        @available(iOS 26.0, *)
        private func parseWithFoundationModels(_ text: String) async -> ParseHint? {
            let session = getSession()
            let prompt = """
                Parse the user's command and respond with JSON only.
                Valid intents: play, pause, resume, next, previous, unknown.
                JSON schema:
                {"intent":"play|pause|resume|next|previous|unknown","query":"optional","confidence":0.0}
                Rules:
                - confidence must be 0.0 to 1.0
                - confidence should be high only for explicit intent language
                - if the command is play with no specific song, set query to ""
                User command: "\(text)"
                """

            do {
                let response = try await session.respond(to: prompt)
                let content = response.content
                if let result = decodeCommandJSON(from: content) {
                    return mapToParseHint(result)
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
            let confidence: Double?
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

        private func mapToParseHint(_ result: CommandJSON) -> ParseHint {
            let normalizedIntent = result.intent.lowercased()
            let boundedConfidence = max(0.0, min(result.confidence ?? 0.0, 1.0))
            let normalizedQuery = normalizeQuery(result.query ?? "")

            if !["play", "pause", "resume", "next", "previous"].contains(
                normalizedIntent
            ) {
                return ParseHint(
                    intent: "unknown",
                    query: nil,
                    confidence: boundedConfidence,
                    source: "ios.foundation_models"
                )
            }

            return ParseHint(
                intent: normalizedIntent,
                query: normalizedQuery.isEmpty ? nil : normalizedQuery,
                confidence: boundedConfidence,
                source: "ios.foundation_models"
            )
        }

        private func normalizeQuery(_ rawQuery: String) -> String {
            var query = rawQuery
            query = query.replacingOccurrences(
                of: #"\s+"#,
                with: " ",
                options: .regularExpression
            )
            query = query.replacingOccurrences(of: "\"", with: "")
            query = query.replacingOccurrences(of: "?", with: "")
            return query.trimmingCharacters(in: .whitespacesAndNewlines)
        }
    #endif
}
