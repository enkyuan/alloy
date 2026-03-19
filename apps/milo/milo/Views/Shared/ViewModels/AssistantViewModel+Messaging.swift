import Foundation

extension AssistantViewModel {
    func resolvePendingAssistantResponse() {
        isAwaitingGeminiResponse = false
        geminiTimeoutTask?.cancel()
        geminiTimeoutTask = nil
        isExecutingCommand = false
        commandFeedback = nil
    }

    func isInternalToolResultLine(_ line: String) -> Bool {
        let normalized = line
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        guard !normalized.isEmpty else { return true }
        if normalized.hasPrefix("tool result for ") {
            return true
        }
        if normalized.count == 1, ".,;:".contains(normalized) {
            return true
        }
        return false
    }

    func sanitizeAssistantResponseText(_ text: String) -> String {
        let cleanedLines = text
            .split(whereSeparator: \.isNewline)
            .map { String($0) }
            .filter { !isInternalToolResultLine($0) }

        return cleanedLines
            .joined(separator: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func shouldSuppressConflictingSpotifyFailure(_ text: String) -> Bool {
        let normalized = normalizeAssistantMessage(text)
        let failureSignals = [
            "couldn't find", "could not find", "having trouble finding", "did you mean",
        ]
        guard failureSignals.contains(where: { normalized.contains($0) }) else {
            return false
        }
        guard let playbackUpdatedAt = lastSpotifyPlaybackUpdateAt else {
            return false
        }
        let isRecentPlaybackUpdate = Date().timeIntervalSince(playbackUpdatedAt) < 8.0
        guard isRecentPlaybackUpdate else {
            return false
        }
        return isSpotifyPlaying
    }

    func decodePayloadDictionary(from response: [String: Any]) -> [String: Any]? {
        if let payloadDict = response["payload"] as? [String: Any] {
            return payloadDict
        }
        if let payloadString = response["payload"] as? String,
            let payloadData = payloadString.data(using: .utf8),
            let payloadDict = try? JSONSerialization.jsonObject(with: payloadData) as? [String: Any]
        {
            return payloadDict
        }
        return nil
    }

    func extractAssistantText(from response: [String: Any]) -> String? {
        if let payload = decodePayloadDictionary(from: response) {
            if let content = payload["content"] as? String, !content.isEmpty {
                return content
            }
            if let contentDict = payload["content"] as? [String: Any] {
                if let text = contentDict["text"] as? String, !text.isEmpty {
                    return text
                }
                if let parts = contentDict["parts"] as? [[String: Any]] {
                    for part in parts {
                        if let text = part["text"] as? String, !text.isEmpty {
                            return text
                        }
                    }
                }
            }
            if let parts = payload["content"] as? [[String: Any]] {
                for part in parts {
                    if let text = part["text"] as? String, !text.isEmpty {
                        return text
                    }
                }
            }
            if let message = payload["message"] as? String, !message.isEmpty {
                return message
            }
            if let error = payload["error"] as? String, !error.isEmpty {
                return "Sorry, I encountered an error: \(error)"
            }
        }

        if let text = response["text"] as? String, !text.isEmpty {
            return text
        }
        if let message = response["message"] as? String, !message.isEmpty {
            return "Sorry, I encountered an error: \(message)"
        }
        return nil
    }

    func normalizeAssistantMessage(_ text: String) -> String {
        text
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
    }

    func shouldSuppressDuplicateAssistantMessage(_ text: String) -> Bool {
        let normalized = normalizeAssistantMessage(text)
        guard !normalized.isEmpty else { return false }
        guard let lastText = lastAssistantMessageText,
            let lastAt = lastAssistantMessageAt
        else {
            return false
        }
        if normalized != lastText {
            return false
        }
        return Date().timeIntervalSince(lastAt) < 1.5
    }

    func markAwaitingResponseTimedOut() {
        isAwaitingGeminiResponse = false
        isExecutingCommand = false
        commandFeedback = nil
        errorMessage = "That request is taking too long right now. Please try again."
        showError = true
    }

    func handleIncomingAIResponse(_ response: [String: Any]) {
        let responseType = (response["type"] as? String) ?? ""
        let validResponseTypes: Set<String> = [
            "ai_response", "agent.response", "agent.error", "ai_error",
        ]
        guard validResponseTypes.contains(responseType) else {
            print("Ignoring non-response event in AI callback: \(responseType)")
            return
        }
        if (response["source"] as? String) == "tool.result" {
            print("Ignoring synthetic tool.result response in chat stream")
            return
        }

        if let assistantText = extractAssistantText(from: response) {
            let cleanedText = sanitizeAssistantResponseText(assistantText)
            guard !cleanedText.isEmpty else {
                print("Ignoring assistant response after sanitization: \(assistantText)")
                return
            }
            if shouldSuppressConflictingSpotifyFailure(cleanedText) {
                resolvePendingAssistantResponse()
                print("Suppressing conflicting Spotify failure message: \(cleanedText)")
                return
            }

            let normalized = normalizeAssistantMessage(cleanedText)
            if shouldSuppressDuplicateAssistantMessage(cleanedText) {
                resolvePendingAssistantResponse()
                print(
                    "AssistantViewModel: Suppressing duplicate assistant response: \"\(cleanedText)\""
                )
                return
            }

            lastAssistantMessageText = normalized
            lastAssistantMessageAt = Date()

            if let queuedAt = commandQueuedAt {
                let latencyMs = Int(Date().timeIntervalSince(queuedAt) * 1000)
                print(
                    "AssistantViewModel: Assistant response latency from command_queued = \(latencyMs)ms"
                )
            }

            resolvePendingAssistantResponse()

            print("Received assistant response: \"\(cleanedText)\"")
            conversationService.addAssistantMessage(cleanedText)
            print(
                "Message count after adding assistant message: \(conversationService.messages.count)"
            )
            return
        }

        print("Ignoring response event without user-facing text: \(response)")
    }

    func sendToGemini(_ text: String) async {
        print("Sending to Gemini: \"\(text)\"")
        print("WebSocket connected: \(webSocketSTTService.isConnected)")

        _ = conversationService.messages.map { message in
            ["role": message.isUser ? "user" : "assistant", "content": message.text]
        }

        var command: [String: Any] = [
            "type": "command",
            "text": text,
            "mode": "conversation",
            "stream": false,
        ]

        let parseHintStartedAt = Date()
        if let parseHint = await OnDeviceReasoningService.shared.parseCommandHint(text) {
            command["parse_hint"] = parseHint.asDictionary
            let hintLatencyMs = Int(Date().timeIntervalSince(parseHintStartedAt) * 1000)
            print(
                "On-device parse hint attached (intent=\(parseHint.intent), confidence=\(parseHint.confidence), latency=\(hintLatencyMs)ms)"
            )
        } else {
            let hintLatencyMs = Int(Date().timeIntervalSince(parseHintStartedAt) * 1000)
            print("On-device parse hint unavailable (latency=\(hintLatencyMs)ms)")
        }

        guard let jsonData = try? JSONSerialization.data(withJSONObject: command),
            let jsonString = String(data: jsonData, encoding: .utf8)
        else {
            print("Failed to create Gemini command")
            _ = await MainActor.run {
                self.conversationService.addAssistantMessage(
                    "Sorry, I couldn't process that request.")
            }
            return
        }

        print("Sending command JSON: \(jsonString)")

        geminiTimeoutTask?.cancel()
        isAwaitingGeminiResponse = true
        isExecutingCommand = true
        commandFeedback = "Sending request..."

        guard webSocketSTTService.isConnected else {
            print("WebSocket not connected - command will not execute without backend")
            isAwaitingGeminiResponse = false
            isExecutingCommand = false
            commandFeedback = nil
            conversationService.addAssistantMessage(
                "I can understand that request, but I need a live server connection to run it."
            )
            return
        }

        print("Calling webSocketSTTService.sendMessage...")

        webSocketSTTService.sendMessage(jsonString)
        print("Message sent, waiting for response...")

        geminiTimeoutTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: self.commandResponseSoftTimeoutNanoseconds)
            guard self.isAwaitingGeminiResponse else { return }
            guard self.webSocketSTTService.isConnected else {
                print("Skipping Gemini timeout feedback - WebSocket disconnected")
                return
            }

            print("Gemini response soft-timeout reached, still waiting")
            self.commandFeedback = "Still working..."

            try? await Task.sleep(nanoseconds: self.commandResponseHardTimeoutNanoseconds)
            guard self.isAwaitingGeminiResponse else { return }
            guard self.webSocketSTTService.isConnected else {
                print("Skipping Gemini hard-timeout feedback - WebSocket disconnected")
                return
            }

            print("Gemini response hard-timeout reached")
            self.markAwaitingResponseTimedOut()
        }
    }

    func inferIntegrationBrand(from text: String) -> MessageIntegrationBrand? {
        let normalized = text.lowercased()

        if normalized.contains("spotify") || normalized.contains("playlist")
            || normalized.contains("song") || normalized.contains("music")
            || normalized.contains("album") || normalized.contains("track")
        {
            return .spotify
        }
        if normalized.contains("gmail") || normalized.contains("email") || normalized.contains("mail")
        {
            return .gmail
        }
        if normalized.contains("calendar") || normalized.contains("event")
            || normalized.contains("meeting") || normalized.contains("schedule")
        {
            return .googleCalendar
        }
        if normalized.contains("discord") || normalized.contains("server") {
            return .discord
        }
        if normalized.contains("todo") || normalized.contains("task") {
            return .todoist
        }
        if normalized.contains("calendly") {
            return .calendly
        }
        if normalized.contains("uber") || normalized.contains("ride") {
            return .uber
        }
        if normalized.contains("doordash") || normalized.contains("food")
            || normalized.contains("delivery")
        {
            return .doordash
        }
        if normalized.contains("instacart") || normalized.contains("grocer") {
            return .instacart
        }
        if normalized.contains("apple music") {
            return .appleMusic
        }

        return nil
    }
}
