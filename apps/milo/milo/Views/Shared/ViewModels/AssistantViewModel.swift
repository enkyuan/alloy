import AVFoundation
import Auth
import Foundation
import Supabase

@MainActor
@Observable
class AssistantViewModel {

    let conversationService = ConversationService()
    let streamingAudioService = AudioStreamingService()
    let webSocketSTTService = WebSocketSTTService()

    var isRecording = false
    var isConnecting = false
    var isProcessingTranscription = false
    var partialTranscription: String = ""
    var errorMessage: String?
    var showError: Bool = false

    var isInCommandMode = false
    private var commandModeTimer: Task<Void, Never>?

    var commandFeedback: String?
    var isExecutingCommand = false

    private var geminiTimeoutTask: Task<Void, Never>?
    private var isAwaitingGeminiResponse = false
    private var lastAssistantMessageText: String?
    private var lastAssistantMessageAt: Date?
    private var commandQueuedAt: Date?

    var availableDevices: [SpotifyDevice] = []
    var currentDevice: SpotifyDevice?
    var isLoadingDevices = false
    var showDeviceSelector = false

    var currentSpotifyTrack: SpotifyTrack?
    var isSpotifyPlaying = false

    private var isStartingRecording = false

    private var currentSessionId: UUID?

    init() {
        setupWebSocketCallbacks()
        setupSpotifyCallbacks()
    }

    private func setupWebSocketCallbacks() {
        webSocketSTTService.onTranscriptionUpdate = { [weak self] text in
            guard let self = self else { return }
            Task { @MainActor in
                print("Partial transcription received: \"\(text)\"")
                self.partialTranscription = text
                print("ViewModel partialTranscription updated to: \"\(self.partialTranscription)\"")
            }
        }

        webSocketSTTService.onFinalTranscription = { [weak self] text in
            guard let self = self else { return }
            Task { @MainActor in
                print("Final transcription received: \"\(text)\"")

                let isNewConversation = self.conversationService.messages.isEmpty
                self.conversationService.beginSendCycle(
                    isNewConversation: isNewConversation
                )
                self.conversationService.addUserMessage(text)
                print(
                    "Message count after adding user message: \(self.conversationService.messages.count)"
                )

                self.partialTranscription = ""
                self.isProcessingTranscription = false
                self.isStartingRecording = false

                Task {
                    await self.sendToGemini(text)
                }
            }
        }

        webSocketSTTService.onError = { [weak self] error in
            guard let self = self else { return }
            Task { @MainActor in
                print("WebSocket error: \(error)")

                if self.streamingAudioService.isRecording {
                    print("Force stopping audio engine due to error")
                    _ = self.streamingAudioService.stopStreaming()
                }

                self.geminiTimeoutTask?.cancel()
                self.geminiTimeoutTask = nil
                self.isAwaitingGeminiResponse = false

                var userMessage = "Connection lost during transcription."
                if error.contains("Socket is not connected") {
                    userMessage =
                        "Connection to server was lost. Please check your internet connection and try again."
                } else if error.contains("timeout") || error.contains("timed out") {
                    userMessage = "Connection timed out. Please try again."
                }

                self.errorMessage = error
                self.showError = true
                self.isProcessingTranscription = false
                self.isConnecting = false
                self.isStartingRecording = false
                self.isRecording = false
                self.isExecutingCommand = false
                self.commandFeedback = nil
                self.conversationService.addAssistantMessage(userMessage)
            }
        }

        webSocketSTTService.onUnexpectedDisconnect = { [weak self] in
            guard let self = self else { return }
            Task { @MainActor in
                print("WebSocket unexpectedly disconnected, stopping audio recording")

                if self.streamingAudioService.isRecording {
                    print("Force stopping audio engine due to unexpected disconnect")
                    _ = self.streamingAudioService.stopStreaming()
                }

                self.geminiTimeoutTask?.cancel()
                self.geminiTimeoutTask = nil
                self.isAwaitingGeminiResponse = false

                self.isStartingRecording = false
                self.isConnecting = false
                self.isRecording = false
                self.isProcessingTranscription = false
                self.partialTranscription = ""
                self.isExecutingCommand = false
                self.commandFeedback = nil
            }
        }

        webSocketSTTService.onSpotifyPlaybackUpdate = { [weak self] update in
            guard let self = self else { return }
            Task { @MainActor in
                self.applySpotifyPlaybackUpdate(update)
            }
        }

        webSocketSTTService.onCommandQueued = { [weak self] queuedText in
            guard let self = self else { return }
            Task { @MainActor in
                self.commandQueuedAt = Date()
                self.isExecutingCommand = true
                self.commandFeedback = "Working on it..."
                print(
                    "AssistantViewModel: Command queued for execution: \"\(queuedText)\""
                )
            }
        }

        webSocketSTTService.onAIResponse = { [weak self] response in
            guard let self = self else { return }
            Task { @MainActor in
                self.handleIncomingAIResponse(response)
            }
        }

        streamingAudioService.onAudioChunk = { [weak self] (pcmData: Data) in
            guard let self = self else { return }

            guard self.isRecording && self.webSocketSTTService.isConnected else {
                print("Audio chunk produced but not recording/connected - stopping audio engine")
                Task { @MainActor in
                    _ = self.streamingAudioService.stopStreaming()
                    self.isRecording = false
                }
                return
            }

            self.webSocketSTTService.sendAudioChunk(pcmData)
        }

        streamingAudioService.onError = { [weak self] (error: String) in
            guard let self = self else { return }
            Task { @MainActor in
                print("Audio streaming error: \(error)")
                self.errorMessage = error
                self.showError = true
                self.isRecording = false
                self.isExecutingCommand = false
                self.commandFeedback = nil

                self.webSocketSTTService.disconnect()
            }
        }
    }

    private func setupSpotifyCallbacks() {
        SpotifyAppService.shared.onPlaybackStateUpdate = { [weak self] update in
            guard let self = self else { return }
            Task { @MainActor in
                self.applySpotifySDKPlaybackUpdate(update)
            }
        }
    }

    private func applySpotifyPlaybackUpdate(_ update: WebSocketSTTService.SpotifyPlaybackUpdate) {
        isSpotifyPlaying = update.isPlaying

        if let track = update.track {
            currentSpotifyTrack = track
            print(
                "AssistantViewModel: Updated mini player track to '\(track.name)' by '\(track.artist)' (isPlaying=\(update.isPlaying))"
            )
        } else {
            print(
                "AssistantViewModel: Updated playback state without track metadata (isPlaying=\(update.isPlaying))"
            )
        }
    }

    private func applySpotifySDKPlaybackUpdate(_ update: SpotifyAppService.PlaybackStateUpdate) {
        isSpotifyPlaying = update.isPlaying

        if let trackName = update.trackName, !trackName.isEmpty {
            if let currentTrack = currentSpotifyTrack {
                if currentTrack.name != trackName {
                    currentSpotifyTrack = SpotifyTrack(
                        id: currentTrack.id,
                        name: trackName,
                        artist: currentTrack.artist,
                        album: currentTrack.album,
                        uri: currentTrack.uri,
                        albumArtUrl: currentTrack.albumArtUrl,
                        durationMs: currentTrack.durationMs
                    )
                }
            } else {
                currentSpotifyTrack = SpotifyTrack(
                    id: "spotify-sdk-\(trackName.lowercased())",
                    name: trackName,
                    artist: "Spotify",
                    album: "",
                    uri: "",
                    albumArtUrl: nil,
                    durationMs: 0
                )
            }
        }

        print(
            "AssistantViewModel: Applied Spotify SDK playback update (track=\(update.trackName ?? "unknown"), isPlaying=\(update.isPlaying))"
        )
    }

    private func decodePayloadDictionary(from response: [String: Any]) -> [String: Any]? {
        if let payloadDict = response["payload"] as? [String: Any] {
            return payloadDict
        }
        if let payloadString = response["payload"] as? String,
            let payloadData = payloadString.data(using: .utf8),
            let payloadDict = try? JSONSerialization.jsonObject(with: payloadData)
                as? [String: Any]
        {
            return payloadDict
        }
        return nil
    }

    private func extractAssistantText(from response: [String: Any]) -> String? {
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

    private func normalizeAssistantMessage(_ text: String) -> String {
        text
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
    }

    private func shouldSuppressDuplicateAssistantMessage(_ text: String) -> Bool {
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

    private func handleIncomingAIResponse(_ response: [String: Any]) {
        let responseType = (response["type"] as? String) ?? ""
        let validResponseTypes: Set<String> = [
            "ai_response", "agent.response", "agent.error", "ai_error",
        ]
        guard validResponseTypes.contains(responseType) else {
            print("Ignoring non-response event in AI callback: \(responseType)")
            return
        }

        if let assistantText = extractAssistantText(from: response) {
            let normalized = normalizeAssistantMessage(assistantText)
            if shouldSuppressDuplicateAssistantMessage(assistantText) {
                print(
                    "AssistantViewModel: Suppressing duplicate assistant response: \"\(assistantText)\""
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

            isAwaitingGeminiResponse = false
            geminiTimeoutTask?.cancel()
            geminiTimeoutTask = nil
            isExecutingCommand = false
            commandFeedback = nil

            print("Received assistant response: \"\(assistantText)\"")
            conversationService.addAssistantMessage(assistantText)
            print(
                "Message count after adding assistant message: \(conversationService.messages.count)"
            )
            return
        }

        print("Ignoring response event without user-facing text: \(response)")
    }

    private func sendToGemini(_ text: String) async {
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
            await MainActor.run {
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
            try? await Task.sleep(nanoseconds: 30_000_000_000) // 30 seconds
            guard self.isAwaitingGeminiResponse else { return }
            guard self.webSocketSTTService.isConnected else {
                print("Skipping Gemini timeout message - WebSocket disconnected")
                return
            }
            print("Gemini response timeout - backend did not respond in time")
            self.isAwaitingGeminiResponse = false
            self.isExecutingCommand = false
            self.commandFeedback = nil
            self.conversationService.addAssistantMessage(
                "That is taking longer than expected. Please try again."
            )
        }
    }

    func startStreamingRecording(authService: AuthService) async {
        guard !isStartingRecording else {
            print("Already starting recording, ignoring duplicate call")
            return
        }

        let token: String
        do {
            let session = try await supabase.auth.session
            authService.session = session
            token = session.accessToken
        } catch {
            guard let fallbackToken = authService.session?.accessToken else {
                print("No auth token available")
                await MainActor.run {
                    errorMessage = "Not authenticated"
                    showError = true
                }
                return
            }
            print("Using fallback auth token from cached session")
            token = fallbackToken
        }

        guard !token.isEmpty else {
            print("Auth token is empty")
            await MainActor.run {
                errorMessage = "Not authenticated"
                showError = true
            }
            return
        }

        print("Starting streaming recording")
        isStartingRecording = true
        isConnecting = true

        let sessionId = UUID()
        currentSessionId = sessionId
        print("New recording session: \(sessionId)")

        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            var hasResumed = false
            var timeoutTask: Task<Void, Never>?

            webSocketSTTService.onReady = { [weak self] in
                guard let self = self else {
                    if !hasResumed {
                        hasResumed = true
                        timeoutTask?.cancel()
                        continuation.resume()
                    }
                    return
                }

                Task { @MainActor in
                    guard self.currentSessionId == sessionId else {
                        print("onReady callback for stale session \(sessionId), ignoring")
                        return
                    }

                    guard !hasResumed else {
                        print("onReady called but already resumed")
                        return
                    }

                    print("WebSocket ready (session: \(sessionId)), starting audio...")

                    do {
                        try await self.streamingAudioService.startStreaming()
                        self.isConnecting = false
                        self.isRecording = true
                        self.isStartingRecording = false
                        print("Recording started (session: \(sessionId))")
                    } catch {
                        print("Failed to start recording: \(error)")
                        self.errorMessage =
                            "Failed to start recording: \(error.localizedDescription)"
                        self.showError = true
                        self.isConnecting = false
                        self.isStartingRecording = false
                        self.webSocketSTTService.disconnect()
                    }

                    if !hasResumed {
                        hasResumed = true
                        timeoutTask?.cancel()
                        continuation.resume()
                    }
                }
            }

            webSocketSTTService.connect(token: token)

            timeoutTask = Task {
                do {
                    try await Task.sleep(nanoseconds: 10_000_000_000)

                    guard !Task.isCancelled else {
                        print("Timeout task was cancelled")
                        return
                    }

                    Task { @MainActor in
                        guard !hasResumed else {
                            print("Timeout expired but connection already succeeded")
                            return
                        }

                        if !self.webSocketSTTService.isConnected {
                            print("WebSocket connection timeout - never connected")
                            self.errorMessage = "Failed to connect to speech service"
                            self.showError = true
                            self.isConnecting = false
                            self.isStartingRecording = false
                            self.webSocketSTTService.disconnect()
                            hasResumed = true
                            continuation.resume()
                        } else {
                            print("Timeout reached but already connected - ignoring")
                        }
                    }
                } catch {
                    print("Timeout task cancelled via exception")
                }
            }
        }

        print("startStreamingRecording completed (continuation resumed)")
    }

    func stopStreamingRecording() async {
        print(
            "Stopping streaming recording (isRecording: \(isRecording), isConnecting: \(isConnecting), session: \(currentSessionId?.uuidString ?? "nil"))"
        )

        guard isRecording else {
            print("Not currently recording, ignoring stop request")
            isStartingRecording = false
            isConnecting = false
            isProcessingTranscription = false
            currentSessionId = nil
            return
        }

        _ = streamingAudioService.stopStreaming()

        isRecording = false
        isProcessingTranscription = true

        webSocketSTTService.endRecording()

        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)

            await MainActor.run {
                print(
                    "2s elapsed, ensuring audio cleanup (session: \(self.currentSessionId?.uuidString ?? "nil"))"
                )

                if self.streamingAudioService.isRecording {
                    print("Audio engine still running during cleanup - force stopping")
                    _ = self.streamingAudioService.stopStreaming()
                }

                self.isStartingRecording = false
                self.isProcessingTranscription = false
                self.partialTranscription = ""
                self.currentSessionId = nil

            }
        }
    }

    func toggleRecording(authService: AuthService) async {
        print(
            "toggleRecording called (isRecording: \(isRecording), isConnecting: \(isConnecting), isStartingRecording: \(isStartingRecording))"
        )

        if isRecording {
            await stopStreamingRecording()
        } else if !isConnecting && !isStartingRecording {
            await startStreamingRecording(authService: authService)
        } else {
            print("Cannot start recording - already connecting or starting")
        }
    }

    func handleMiniPlayerPlayPause() {
        let shouldPause = isSpotifyPlaying
        print("AssistantViewModel: MiniPlayer play/pause tapped (shouldPause=\(shouldPause))")
        if shouldPause {
            SpotifyAppService.shared.performMiniPlayerTransportAction(.pause)
        } else {
            SpotifyAppService.shared.performMiniPlayerTransportAction(.resume)
        }
    }

    func handleMiniPlayerNext() {
        print("AssistantViewModel: MiniPlayer next tapped")
        SpotifyAppService.shared.performMiniPlayerTransportAction(.next)
    }

    func handleMiniPlayerPrevious() {
        print("AssistantViewModel: MiniPlayer previous tapped")
        SpotifyAppService.shared.performMiniPlayerTransportAction(.previous)
    }

    func openSpotifyApp() {
        print("AssistantViewModel: MiniPlayer route tapped")
        SpotifyAppService.shared.openSpotify()
    }

    func fetchAvailableDevices() async {
        guard !isLoadingDevices else { return }

        isLoadingDevices = true
        defer { isLoadingDevices = false }

        do {
            let command = ["type": "command", "text": "list devices"]
            guard let jsonData = try? JSONSerialization.data(withJSONObject: command),
                let jsonString = String(data: jsonData, encoding: .utf8)
            else {
                print("Failed to create device list command")
                return
            }

            var responseReceived = false
            webSocketSTTService.onCommandResult = { [weak self] result in
                guard let self = self, !responseReceived else { return }
                responseReceived = true

                Task { @MainActor in
                    if let devices = result["data"] as? [String: Any],
                        let deviceList = devices["devices"] as? [[String: Any]]
                    {
                        self.availableDevices = deviceList.compactMap { deviceDict in
                            guard let id = deviceDict["id"] as? String,
                                let name = deviceDict["name"] as? String,
                                let type = deviceDict["type"] as? String,
                                let isActive = deviceDict["is_active"] as? Bool,
                                let volumePercent = deviceDict["volume_percent"] as? Int
                            else {
                                return nil
                            }

                            let device = SpotifyDevice(
                                id: id,
                                name: name,
                                type: type,
                                isActive: isActive,
                                volumePercent: volumePercent
                            )

                            if isActive {
                                self.currentDevice = device
                            }

                            return device
                        }

                        print("Loaded \(self.availableDevices.count) devices")
                    }
                }
            }

            webSocketSTTService.sendMessage(jsonString)

            try await Task.sleep(nanoseconds: 3_000_000_000)

        } catch {
            print("Failed to fetch devices: \(error)")
        }
    }

    func switchToDevice(_ device: SpotifyDevice) async {
        let command = ["type": "command", "text": "switch to \(device.name)"]
        guard let jsonData = try? JSONSerialization.data(withJSONObject: command),
            let jsonString = String(data: jsonData, encoding: .utf8)
        else {
            print("Failed to create device switch command")
            return
        }

        var responseReceived = false
        webSocketSTTService.onCommandResult = { [weak self] result in
            guard let self = self, !responseReceived else { return }
            responseReceived = true

            Task { @MainActor in
                if result["success"] as? Bool == true {
                    self.currentDevice = device

                    self.availableDevices = self.availableDevices.map { d in
                        SpotifyDevice(
                            id: d.id,
                            name: d.name,
                            type: d.type,
                            isActive: d.id == device.id,
                            volumePercent: d.volumePercent
                        )
                    }

                    print("Switched to device: \(device.name)")
                } else {
                    print("Failed to switch device")
                }
            }
        }

        webSocketSTTService.sendMessage(jsonString)
    }

    func toggleDeviceSelector() {
        showDeviceSelector.toggle()

        if showDeviceSelector {
            Task {
                await fetchAvailableDevices()
            }
        }
    }
}
