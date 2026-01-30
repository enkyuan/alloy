import AVFoundation
import Auth
import Foundation

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

    var availableDevices: [SpotifyDevice] = []
    var currentDevice: SpotifyDevice?
    var isLoadingDevices = false
    var showDeviceSelector = false

    var currentSpotifyTrack: SpotifyTrack?

    private var isStartingRecording = false

    private var currentSessionId: UUID?

    init() {
        setupWebSocketCallbacks()
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
                self.partialTranscription = ""
                self.isProcessingTranscription = false
                self.isStartingRecording = false

                self.conversationService.addUserMessage(text)
                print(
                    "Message count after adding user message: \(self.conversationService.messages.count)"
                )

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

                self.webSocketSTTService.disconnect()
            }
        }
    }

    private func sendToGemini(_ text: String) async {
        print("Sending to Gemini: \"\(text)\"")
        print("WebSocket connected: \(webSocketSTTService.isConnected)")

        guard webSocketSTTService.isConnected else {
            print("WebSocket not connected, cannot send to Gemini")
            await MainActor.run {
                self.conversationService.addAssistantMessage(
                    "Sorry, connection was lost. Please try again.")
            }
            return
        }

        _ = conversationService.messages.map { message in
            ["role": message.isUser ? "user" : "assistant", "content": message.text]
        }

        let command: [String: Any] = [
            "type": "command",
            "text": text,
            "mode": "conversation",
            "stream": false,
        ]

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

        var responseReceived = false
        geminiTimeoutTask?.cancel()
        isAwaitingGeminiResponse = true
        webSocketSTTService.onAIResponse = { [weak self] response in
            guard let self = self, !responseReceived else { return }
            responseReceived = true
            self.isAwaitingGeminiResponse = false
            self.geminiTimeoutTask?.cancel()
            self.geminiTimeoutTask = nil

            Task { @MainActor in
                print("AI Response callback triggered")

                if let payloadString = response["payload"] as? String,
                    let payloadData = payloadString.data(using: .utf8),
                    let payloadJson = try? JSONSerialization.jsonObject(with: payloadData)
                        as? [String: Any],
                    let content = payloadJson["content"] as? String
                {

                    print("Received Gemini response: \"\(content)\"")
                    self.conversationService.addAssistantMessage(content)
                    print(
                        "Message count after adding assistant message: \(self.conversationService.messages.count)"
                    )

                } else if let text = response["text"] as? String {
                    print("Received Gemini response: \"\(text)\"")
                    self.conversationService.addAssistantMessage(text)
                    print(
                        "Message count after adding assistant message: \(self.conversationService.messages.count)"
                    )
                } else if let error = response["message"] as? String {
                    print("Gemini error: \(error)")
                    self.conversationService.addAssistantMessage(
                        "Sorry, I encountered an error: \(error)")
                } else {
                    print("Unknown response format: \(response)")
                    self.conversationService.addAssistantMessage(
                        "Sorry, received an unexpected response.")
                }
            }
        }

        print("Calling webSocketSTTService.sendMessage...")
        
        // Check if websocket is connected before sending
        guard webSocketSTTService.isConnected else {
            print("WebSocket not connected - using on-device fallback immediately")
            await handleOnDeviceFallback(text)
            return
        }
        
        webSocketSTTService.sendMessage(jsonString)
        print("Message sent, waiting for response...")


        geminiTimeoutTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 30_000_000_000) // 30 seconds
            guard !responseReceived, self.isAwaitingGeminiResponse else { return }
            guard self.webSocketSTTService.isConnected else {
                print("Skipping Gemini timeout message - WebSocket disconnected")
                return
            }
            print("Gemini response timeout - trying on-device fallback")
            self.isAwaitingGeminiResponse = false
            
            // Try on-device command parsing as fallback
            await self.handleOnDeviceFallback(text)
        }
    }
    
    /// Handle commands on-device when backend is completely unavailable
    /// This is a pure fallback - backend handles all parsing/reasoning normally
    private func handleOnDeviceFallback(_ text: String) async {
        print("Backend unavailable - using on-device fallback for: \(text)")
        
        let command = OnDeviceCommandParser.shared.parseCommand(text)
        
        switch command {
        case .play(let query):
            print("On-device: Play command")
            if query.isEmpty {
                conversationService.addAssistantMessage("Resuming playback.")
                SpotifyAppService.shared.resume()
            } else {
                conversationService.addAssistantMessage(
                    "I'm offline. I found '\(query)' but need a connection to search and play. I can help with basic controls: pause, skip, and resume."
                )
            }
            
        case .pause:
            print("On-device: Pause")
            conversationService.addAssistantMessage("Pausing playback.")
            SpotifyAppService.shared.pause()
            
        case .resume:
            print("On-device: Resume")
            conversationService.addAssistantMessage("Resuming playback.")
            SpotifyAppService.shared.resume()
            
        case .skipNext:
            print("On-device: Skip next")
            conversationService.addAssistantMessage("Skipping to next track.")
            SpotifyAppService.shared.skipNext()
            
        case .skipPrevious:
            print("On-device: Skip previous")
            conversationService.addAssistantMessage("Going back to previous track.")
            SpotifyAppService.shared.skipPrevious()
            
        case .unknown:
            print("On-device: Unknown command")
            conversationService.addAssistantMessage(
                "I'm offline. I can help with basic playback: pause, resume, skip next, and previous."
            )
        }
    }

    func startStreamingRecording(authService: AuthService) async {
        guard !isStartingRecording else {
            print("Already starting recording, ignoring duplicate call")
            return
        }

        guard let token = authService.session?.accessToken else {
            print("No auth token available")
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
