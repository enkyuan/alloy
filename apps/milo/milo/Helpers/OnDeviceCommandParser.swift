import Foundation
import NaturalLanguage

/// On-device command parser for handling requests when backend is unavailable
class OnDeviceCommandParser {
    static let shared = OnDeviceCommandParser()

    enum CommandType {
        case play(query: String)
        case pause
        case resume
        case skipNext
        case skipPrevious
        case unknown
    }

    private init() {}

    /// Parse user input to detect command intent
    func parseCommand(_ text: String) -> CommandType {
        let lowercased = text.lowercased()

        // Pause/Stop commands
        if containsAny(lowercased, keywords: ["pause", "stop"]) {
            return .pause
        }

        // Resume/Continue commands
        if containsAny(lowercased, keywords: ["resume", "continue", "unpause"]) {
            return .resume
        }

        // Skip commands
        if containsAny(lowercased, keywords: ["skip", "next"]) {
            return .skipNext
        }

        if containsAny(lowercased, keywords: ["previous", "back", "last"]) {
            return .skipPrevious
        }

        // Play commands - extract query
        if containsAny(lowercased, keywords: ["play"]) {
            let query = extractPlayQuery(from: text)
            return .play(query: query)
        }

        return .unknown
    }

    /// Extract song/artist query from play command
    private func extractPlayQuery(from text: String) -> String {
        var query = text.lowercased()

        // Remove common wake words and command words (order matters)
        let patternsToRemove = [
            "hey milo,?", "hey milo",
            "milo,?", "milo",
            "hey,?", "hey",
            "hi,?", "hi",
            "can you", "could you", "would you", "please",
            "play",
            "on spotify", "in spotify", "with spotify", "spotify",
            "for me", "the song", "the track", "the album",
        ]

        for pattern in patternsToRemove {
            // Use regex to handle variations with/without punctuation
            query = query.replacingOccurrences(
                of: "\\b\(pattern)\\b",
                with: "",
                options: [.regularExpression, .caseInsensitive]
            )
        }

        query = normalizeQuery(query)

        // Use NL framework to extract named entities (song/artist names)
        let enhancedQuery = extractNamedEntities(from: text) ?? query

        return enhancedQuery.isEmpty ? query : enhancedQuery
    }

    /// Normalize a play query by removing platform and filler words
    func normalizeQuery(_ text: String) -> String {
        var query = text

        let patternsToRemove = [
            "hey milo", "milo", "hey", "hi",
            "on spotify", "in spotify", "with spotify", "spotify",
            "the song", "the track", "the album", "for me",
        ]

        for pattern in patternsToRemove {
            query = query.replacingOccurrences(
                of: "\\b\(pattern)\\b",
                with: "",
                options: [.regularExpression, .caseInsensitive]
            )
        }

        query = query.replacingOccurrences(
            of: #"\s+"#,
            with: " ",
            options: .regularExpression
        )
        query = query.replacingOccurrences(of: "?", with: "")
        query = query.replacingOccurrences(of: "\"", with: "")
        query = query.trimmingCharacters(in: .whitespacesAndNewlines)

        return query
    }

    /// Use Natural Language framework to extract named entities
    private func extractNamedEntities(from text: String) -> String? {
        let tagger = NLTagger(tagSchemes: [.nameType])
        tagger.string = text

        var entities: [String] = []

        tagger.enumerateTags(
            in: text.startIndex..<text.endIndex,
            unit: .word,
            scheme: .nameType
        ) { tag, tokenRange in
            if let tag = tag {
                // Capture person names (artists) and other named entities
                if tag == .personalName || tag == .organizationName {
                    entities.append(String(text[tokenRange]))
                }
            }
            return true
        }

        return entities.isEmpty ? nil : entities.joined(separator: " ")
    }

    /// Check if text contains any of the given keywords
    private func containsAny(_ text: String, keywords: [String]) -> Bool {
        for keyword in keywords {
            if text.contains(keyword) {
                return true
            }
        }
        return false
    }
}
