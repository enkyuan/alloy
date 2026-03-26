import Foundation

@MainActor
@Observable
class WebSocketSTTService: NSObject {

    struct SpotifyPlaybackUpdate {
        let track: SpotifyTrack?
        let isPlaying: Bool
    }

    private let backendURL: String
    private var webSocketTask: URLSessionWebSocketTask?
    private var _session: URLSession?
    private var session: URLSession {
        if _session == nil {
            let config = URLSessionConfiguration.default
            config.waitsForConnectivity = true
            _session = URLSession(
                configuration: config, delegate: self, delegateQueue: OperationQueue())
        }
        return _session!
    }

    private var currentConnectionId: UUID?

    var isConnected: Bool = false
    var currentTranscription: String = ""
    private var keepaliveTimer: Timer?
    private var lastPlayedUri: String?  // Track last played URI to prevent duplicates
    var onTranscriptionUpdate: ((String) -> Void)?
    var onFinalTranscription: ((String) -> Void)?
    var onError: ((String) -> Void)?
    var onReady: (() -> Void)?
    var onUnexpectedDisconnect: (() -> Void)?
    var onCommandResult: (([String: Any]) -> Void)?
    var onCommandError: ((String, String?) -> Void)?
    var onCommandQueued: ((String) -> Void)?
    var onAIResponse: (([String: Any]) -> Void)?
    var onSpotifyPlaybackUpdate: ((SpotifyPlaybackUpdate) -> Void)?

    nonisolated init(backendURL: String = Environment.websocketURL) {
        self.backendURL = backendURL
        super.init()
    }

    func connect(token: String) {
        if webSocketTask != nil {
            print("Existing WebSocket task found, cleaning up before new connection")
            disconnect()
        }

        let trimmedToken = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedToken.isEmpty else {
            print("Cannot connect WebSocket without auth token")
            onError?("Missing authentication token")
            return
        }

        let connectionId = UUID()
        currentConnectionId = connectionId
        print("New connection ID: \(connectionId)")

        guard let url = URL(string: "\(backendURL)/stt/stream") else {
            print("Invalid WebSocket URL")
            onError?("Invalid WebSocket URL")
            return
        }

        var request = URLRequest(url: url)
        request.setValue("Bearer \(trimmedToken)", forHTTPHeaderField: "Authorization")
        print("Connecting to WebSocket: \(url) with Authorization header")

        webSocketTask = session.webSocketTask(with: request)
        webSocketTask?.resume()

        // Start keepalive timer to prevent idle timeout
        startKeepalive()

        receiveMessage()
    }

    func disconnect() {
        print(
            "Disconnecting WebSocket (isConnected: \(isConnected), connectionId: \(currentConnectionId?.uuidString ?? "nil"))"
        )

        // Stop keepalive timer
        stopKeepalive()

        isConnected = false
        currentConnectionId = nil
        lastPlayedUri = nil  // Reset played URI tracker
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        currentTranscription = ""

        // Clean up URLSession to prevent memory leaks
        _session?.invalidateAndCancel()
        _session = nil
    }

    func sendAudioChunk(_ data: Data) {
        guard isConnected else {
            print("Not connected, skipping audio chunk")
            return
        }

        let message = URLSessionWebSocketTask.Message.data(data)
        webSocketTask?.send(message) { error in
            if let error = error {
                print("Failed to send audio chunk: \(error)")
                Task { @MainActor [weak self] in
                    self?.onError?("Failed to send audio: \(error.localizedDescription)")
                }
            }
        }
    }

    func endRecording() {
        guard isConnected else { return }

        print("Sending END signal")
        let message = URLSessionWebSocketTask.Message.string("END")
        webSocketTask?.send(message) { error in
            if let error = error {
                print("Failed to send END signal: \(error)")
                Task { @MainActor [weak self] in
                    self?.onError?("Failed to end recording: \(error.localizedDescription)")
                }
            }
        }
    }

    func sendCommand(_ commandText: String, wakeWordDetected: Bool = true) {
        guard isConnected else {
            print("Not connected, cannot send command")
            return
        }

        print("Sending command: \(commandText)")

        let commandMessage: [String: Any] = [
            "type": "command",
            "text": commandText,
            "wake_word_detected": wakeWordDetected,
        ]

        guard let jsonData = try? JSONSerialization.data(withJSONObject: commandMessage),
            let jsonString = String(data: jsonData, encoding: .utf8)
        else {
            print("Failed to serialize command message")
            return
        }

        let message = URLSessionWebSocketTask.Message.string(jsonString)
        webSocketTask?.send(message) { error in
            if let error = error {
                print("Failed to send command: \(error)")
                Task { @MainActor [weak self] in
                    self?.onError?("Failed to send command: \(error.localizedDescription)")
                }
            }
        }
    }

    func sendMessage(_ messageString: String) {
        guard isConnected else {
            print("Not connected, cannot send message")
            return
        }

        print("Sending message: \(messageString)")

        let message = URLSessionWebSocketTask.Message.string(messageString)
        webSocketTask?.send(message) { error in
            if let error = error {
                print("Failed to send message: \(error)")
                Task { @MainActor [weak self] in
                    self?.onError?("Failed to send message: \(error.localizedDescription)")
                }
            }
        }
    }

    private func parsePayload(from json: [String: Any]) -> [String: Any]? {
        if let payload = json["payload"] as? [String: Any] {
            return payload
        }

        if let payloadStr = json["payload"] as? String,
            let payloadData = payloadStr.data(using: .utf8),
            let payload = try? JSONSerialization.jsonObject(with: payloadData) as? [String: Any]
        {
            return payload
        }

        return nil
    }

    private func spotifyTrack(from data: [String: Any]) -> SpotifyTrack? {
        let name = (data["track_name"] as? String)
            ?? (data["name"] as? String)
            ?? (data["album_name"] as? String)
            ?? (data["playlist_name"] as? String)
        guard let name, !name.isEmpty else { return nil }

        let artist = (data["artist"] as? String) ?? (data["owner"] as? String) ?? "Spotify"
        let album = (data["album"] as? String)
            ?? (data["album_name"] as? String)
            ?? (data["playlist_name"] as? String)
            ?? ""
        let uri = (data["uri"] as? String) ?? ""
        let albumArt = (data["album_art"] as? String) ?? (data["album_art_url"] as? String)
        let durationMs = (data["duration_ms"] as? Int) ?? 0

        let rawId = (data["track_id"] as? String) ?? uri
        let id = rawId.isEmpty ? "spotify-\(name.lowercased())-\(artist.lowercased())" : rawId

        return SpotifyTrack(
            id: id,
            name: name,
            artist: artist,
            album: album,
            uri: uri,
            albumArtUrl: albumArt,
            durationMs: durationMs
        )
    }

    private func playbackState(for toolName: String, data: [String: Any]) -> Bool? {
        switch toolName {
        case "spotify.pause":
            return false
        case "spotify.play", "spotify.play_album", "spotify.play_playlist", "spotify.resume",
            "spotify.next", "spotify.previous":
            return true
        default:
            break
        }

        if let action = data["action"] as? String {
            switch action {
            case "pause":
                return false
            case "resume", "next", "previous":
                return true
            default:
                break
            }
        }

        return nil
    }

    private func publishSpotifyPlaybackUpdate(toolName: String, data: [String: Any]) {
        guard toolName != "spotify.add_to_queue" else {
            print("Skipping mini player update for queue action")
            return
        }

        guard let isPlaying = playbackState(for: toolName, data: data) else {
            return
        }

        let track = spotifyTrack(from: data)
        if let track {
            print(
                "Publishing Spotify playback update: \(track.name) by \(track.artist), isPlaying=\(isPlaying)"
            )
        } else {
            print(
                "Publishing Spotify playback state update without track metadata, isPlaying=\(isPlaying)"
            )
        }
        onSpotifyPlaybackUpdate?(SpotifyPlaybackUpdate(track: track, isPlaying: isPlaying))
    }

    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            guard let self = self else { return }

            switch result {
            case .success(let message):
                Task { @MainActor in
                    self.handleMessage(message)
                    if self.isConnected {
                        self.receiveMessage()
                    } else {
                        print("Stopped receiving messages (disconnected)")
                    }
                }

            case .failure(let error):
                Task { @MainActor in
                    if self.isConnected {
                        print("WebSocket receive error: \(error)")
                        print("Error details: \(error.localizedDescription)")
                        self.onError?("Connection error: \(error.localizedDescription)")
                        self.isConnected = false
                    } else {
                        print("WebSocket closed gracefully")
                    }
                }
            }
        }
    }

    private func handleMessage(_ message: URLSessionWebSocketTask.Message) {
        let messageConnectionId = currentConnectionId

        switch message {
        case .string(let text):
            if Environment.isDebugLoggingEnabled {
                print(
                    "Received: \(text) (connectionId: \(messageConnectionId?.uuidString ?? "nil"))")
            }

            guard messageConnectionId != nil && messageConnectionId == currentConnectionId else {
                print("Ignoring message from stale connection")
                return
            }

            guard let data = text.data(using: .utf8),
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                let type = json["type"] as? String
            else {
                print("Invalid message format")
                return
            }

            switch type {
            case "ready":
                print("WebSocket ready")
                isConnected = true
                onReady?()

            case "ack":
                if let bytesReceived = json["bytes_received"] as? Int,
                    let totalBytes = json["total_bytes"] as? Int
                {
                    print("Acknowledged: \(bytesReceived) bytes, total: \(totalBytes)")
                }

            case "partial":
                if let text = json["text"] as? String {
                    // Commented out to prevent excessive logging
                    // if Environment.isDebugLoggingEnabled {
                    //     print("Partial: \(text)")
                    // }
                    currentTranscription = text
                    onTranscriptionUpdate?(text)
                }

            case "final":
                if let text = json["text"] as? String {
                    if Environment.isDebugLoggingEnabled {
                        print("Final tokens: \(text)")
                    }
                    currentTranscription = text
                    onTranscriptionUpdate?(text)
                }

            case "complete":
                if let text = json["text"] as? String {
                    if Environment.isDebugLoggingEnabled {
                        print("Complete transcription: \(text)")
                    }
                    currentTranscription = text
                    onFinalTranscription?(text)
                }

            case "error":
                if let errorMsg = json["message"] as? String {
                    print("Server error: \(errorMsg)")
                    onError?(errorMsg)
                }

            case "command_result":
                print("Command result received")
                onCommandResult?(json)

            case "command_error":
                if let errorMsg = json["message"] as? String {
                    let errorCode = json["error_code"] as? String
                    print("Command error: \(errorMsg) (code: \(errorCode ?? "none"))")
                    onCommandError?(errorMsg, errorCode)
                }

            case "ai_response", "agent.response", "agent.error":
                print("AI response received")
                onAIResponse?(json)

            case "ai_error":
                if let errorMsg = json["message"] as? String {
                    print("AI error: \(errorMsg)")
                    onAIResponse?(json)
                }

            case "command_queued":
                print("Command queued")
                if let text = json["text"] as? String {
                    onCommandQueued?(text)
                }

            case "tool.call":
                // This message contains a tool call request from the agent
                if let payload = parsePayload(from: json),
                    let toolName = payload["tool_name"] as? String,
                    toolName == "spotify.play"
                {

                    print("Received spotify.play tool call: \(payload)")

                    if let toolArgs = payload["tool_args"] as? [String: Any] {
                        // Extract query or URI if available
                        let query = toolArgs["query"] as? String
                        let uri = toolArgs["uri"] as? String

                        if let uri = uri, !uri.isEmpty {
                            print("Playing URI: \(uri)")
                            Task { @MainActor in
                                SpotifyAppService.shared.authorizeAndPlay(uri: uri)
                            }
                        } else if let query = query, !query.isEmpty {
                            print(
                                "Playing query via search is not fully supported yet, attempting to parse URI from query if possible or just log"
                            )
                            // Ideally we would search here if we had a search tool, but for now we might assume query is a URI or we just can't do it easily without a search step.
                            // If the backend already failed to find a device, it means the backend tried to use the Web API.
                            // If we want to use the local app, we need a URI.
                            // For this specific 'Bohemian Rhapsody' request, it's a search term.
                            print("Query: \(query)")
                        }
                    }
                }

            case "tool.result":
                // This message contains the result of a tool execution (from backend)
                print("Tool result received")

                // Check if this is a Spotify tool result we should handle client-side
                if let payload = parsePayload(from: json),
                    let toolName = payload["tool_name"] as? String,
                    toolName.starts(with: "spotify.")
                {

                    let result = payload["result"] as? [String: Any]
                    let data = result?["data"] as? [String: Any] ?? [:]
                    publishSpotifyPlaybackUpdate(toolName: toolName, data: data)

                    // Do not forward spotify tool.result message text as a chat bubble.
                    // The reasoning response should provide user-facing copy, while
                    // tool.result here is used for client playback synchronization.
                    if let resultMessage = result?["message"] as? String,
                        !resultMessage.isEmpty
                    {
                        print("Ignoring spotify tool.result message text: \(resultMessage)")
                    }

                    if let toolError = payload["error"] as? String, !toolError.isEmpty {
                        print("Forwarding tool error from tool.result: \(toolError)")
                        onAIResponse?(
                            [
                                "type": "agent.error",
                                "payload": ["message": toolError, "error": toolError],
                            ]
                        )
                    }

                    // Extract the result data
                    if let actionRequired = data["action_required"] as? String,
                        actionRequired == "client_playback"
                    {

                        print("Backend requested client-side playback action")

                        // Handle different Spotify actions
                        if let action = data["action"] as? String {
                            switch action {
                            case "pause":
                                print("Client: Pausing Spotify playback")
                                Task { @MainActor in
                                    SpotifyAppService.shared.openSpotifyAndReturnToMilo {
                                        SpotifyAppService.shared.pause()
                                    }
                                }
                            case "resume":
                                print("Client: Resuming Spotify playback")
                                Task { @MainActor in
                                    SpotifyAppService.shared.openSpotifyAndReturnToMilo {
                                        SpotifyAppService.shared.resume()
                                    }
                                }
                            case "next":
                                print("Client: Skipping to next track")
                                Task { @MainActor in
                                    SpotifyAppService.shared.openSpotifyAndReturnToMilo {
                                        SpotifyAppService.shared.skipNext()
                                    }
                                }
                            case "previous":
                                print("Client: Skipping to previous track")
                                Task { @MainActor in
                                    SpotifyAppService.shared.openSpotifyAndReturnToMilo {
                                        SpotifyAppService.shared.skipPrevious()
                                    }
                                }
                            default:
                                print("Unknown action: \(action)")
                            }
                        } else if let uri = data["uri"] as? String, !uri.isEmpty {
                            // Play action with URI
                            print("Spotify tool result contains URI: \(uri)")

                            // Only play if this is a new URI (prevent duplicate plays)
                            if lastPlayedUri != uri {
                                print(
                                    "Backend requested client-side playback, playing URI via Spotify SDK"
                                )
                                lastPlayedUri = uri
                                Task { @MainActor in
                                    SpotifyAppService.shared.authorizeAndPlay(uri: uri)
                                }

                                // Clear the lastPlayedUri after 10 seconds to allow replaying
                                DispatchQueue.main.asyncAfter(deadline: .now() + 10.0) {
                                    [weak self] in
                                    self?.lastPlayedUri = nil
                                }
                            } else {
                                print("Duplicate play request for same URI, skipping")
                            }
                        }
                    } else {
                        print("Backend handled playback via Web API")
                    }
                }

            default:
                print("Unknown message type: \(type)")
            }

        case .data(let data):
            print("Received binary data: \(data.count) bytes")

        @unknown default:
            print("Unknown message type")
        }
    }
}

extension WebSocketSTTService: URLSessionWebSocketDelegate {
    nonisolated func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didOpenWithProtocol protocol: String?
    ) {
        print("WebSocket opened")
    }

    nonisolated func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
        reason: Data?
    ) {
        print("WebSocket closed: \(closeCode)")
        Task { @MainActor in
            let wasConnected = self.isConnected
            self.isConnected = false

            if wasConnected {
                print("Unexpected WebSocket closure detected")
                self.onUnexpectedDisconnect?()
            }
        }
    }

    // MARK: - Keepalive

    private func startKeepalive() {
        stopKeepalive()  // Clear any existing timer

        // Send ping every 15 seconds to keep connection alive
        keepaliveTimer = Timer.scheduledTimer(withTimeInterval: 15.0, repeats: true) {
            [weak self] _ in
            Task { @MainActor [weak self] in
                self?.sendPing()
            }
        }
        print("Started keepalive timer")
    }

    private func stopKeepalive() {
        // Ensure timer invalidation happens on the main actor
        if !Thread.isMainThread {
            DispatchQueue.main.sync { [weak self] in
                self?.keepaliveTimer?.invalidate()
                self?.keepaliveTimer = nil
            }
        } else {
            keepaliveTimer?.invalidate()
            keepaliveTimer = nil
        }
        print("Stopped keepalive timer")
    }

    private func sendPing() {
        webSocketTask?.sendPing { error in
            if let error = error {
                print("Ping failed: \(error.localizedDescription)")
            } else {
                print("Ping sent successfully")
            }
        }
    }
}
