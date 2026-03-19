import Foundation

extension AssistantViewModel {
    func setupWebSocketCallbacks() {
        webSocketSTTService.onTranscriptionUpdate = { [weak self] text in
            guard let self else { return }
            Task { @MainActor in
                self.handleTranscriptionUpdate(text)
            }
        }

        webSocketSTTService.onFinalTranscription = { [weak self] text in
            guard let self else { return }
            Task { @MainActor in
                await self.handleFinalTranscription(text)
            }
        }

        webSocketSTTService.onError = { [weak self] error in
            guard let self else { return }
            Task { @MainActor in
                self.handleWebSocketError(error)
            }
        }

        webSocketSTTService.onUnexpectedDisconnect = { [weak self] in
            guard let self else { return }
            Task { @MainActor in
                self.handleUnexpectedDisconnect()
            }
        }

        webSocketSTTService.onSpotifyPlaybackUpdate = { [weak self] update in
            guard let self else { return }
            Task { @MainActor in
                self.applySpotifyPlaybackUpdate(update)
            }
        }

        webSocketSTTService.onCommandQueued = { [weak self] queuedText in
            guard let self else { return }
            Task { @MainActor in
                self.handleCommandQueued(queuedText)
            }
        }

        webSocketSTTService.onAIResponse = { [weak self] response in
            guard let self else { return }
            Task { @MainActor in
                self.handleIncomingAIResponse(response)
            }
        }

        streamingAudioService.onAudioChunk = { [weak self] pcmData in
            guard let self else { return }
            self.handleAudioChunk(pcmData)
        }

        streamingAudioService.onAudioLevel = { [weak self] level in
            guard let self else { return }
            Task { @MainActor in
                self.audioLevel = level
            }
        }

        streamingAudioService.onAudioEnvelope = { [weak self] envelope in
            guard let self else { return }
            Task { @MainActor in
                self.audioEnvelope = envelope
            }
        }

        streamingAudioService.onError = { [weak self] error in
            guard let self else { return }
            Task { @MainActor in
                self.handleAudioStreamingError(error)
            }
        }
    }

    func setupSpotifyCallbacks() {
        SpotifyAppService.shared.onPlaybackStateUpdate = { [weak self] update in
            guard let self else { return }
            Task { @MainActor in
                self.applySpotifySDKPlaybackUpdate(update)
            }
        }
    }

    private func handleTranscriptionUpdate(_ text: String) {
        print("Partial transcription received: \"\(text)\"")
        partialTranscription = text
        print("ViewModel partialTranscription updated to: \"\(partialTranscription)\"")
    }

    private func handleFinalTranscription(_ text: String) async {
        print("Final transcription received: \"\(text)\"")

        let isNewConversation = conversationService.messages.isEmpty
        conversationService.beginSendCycle(isNewConversation: isNewConversation)
        conversationService.addUserMessage(
            text,
            integrationBrand: inferIntegrationBrand(from: text)
        )
        print("Message count after adding user message: \(conversationService.messages.count)")

        resetAudioCaptureState(clearTranscription: true)
        isProcessingTranscription = false
        isStartingRecording = false

        await sendToGemini(text)
    }

    private func handleWebSocketError(_ error: String) {
        print("WebSocket error: \(error)")

        if streamingAudioService.isRecording {
            print("Force stopping audio engine due to error")
            _ = streamingAudioService.stopStreaming()
        }

        geminiTimeoutTask?.cancel()
        geminiTimeoutTask = nil
        isAwaitingGeminiResponse = false
        connectionTimeoutTask?.cancel()
        connectionTimeoutTask = nil

        var userMessage = "Connection lost during transcription."
        if error.contains("Socket is not connected") {
            userMessage =
                "Connection to server was lost. Please check your internet connection and try again."
        } else if error.contains("timeout") || error.contains("timed out") {
            userMessage = "Connection timed out. Please try again."
        }

        errorMessage = error
        showError = true
        isProcessingTranscription = false
        isConnecting = false
        isStartingRecording = false
        isRecording = false
        resetAudioCaptureState(clearTranscription: true)
        isExecutingCommand = false
        commandFeedback = nil
        conversationService.addAssistantMessage(userMessage)
    }

    private func handleUnexpectedDisconnect() {
        print("WebSocket unexpectedly disconnected, stopping audio recording")

        if streamingAudioService.isRecording {
            print("Force stopping audio engine due to unexpected disconnect")
            _ = streamingAudioService.stopStreaming()
        }

        geminiTimeoutTask?.cancel()
        geminiTimeoutTask = nil
        isAwaitingGeminiResponse = false
        connectionTimeoutTask?.cancel()
        connectionTimeoutTask = nil

        isStartingRecording = false
        isConnecting = false
        isRecording = false
        isProcessingTranscription = false
        partialTranscription = ""
        resetAudioCaptureState(clearTranscription: false)
        isExecutingCommand = false
        commandFeedback = nil
    }

    private func handleCommandQueued(_ queuedText: String) {
        commandQueuedAt = Date()
        isExecutingCommand = true
        commandFeedback = "Working on it..."
        print("AssistantViewModel: Command queued for execution: \"\(queuedText)\"")
    }

    private func handleAudioChunk(_ pcmData: Data) {
        guard isRecording && webSocketSTTService.isConnected else {
            print("Audio chunk produced but not recording/connected - stopping audio engine")
            Task { @MainActor in
                _ = self.streamingAudioService.stopStreaming()
                self.isRecording = false
            }
            return
        }

        webSocketSTTService.sendAudioChunk(pcmData)
    }

    private func handleAudioStreamingError(_ error: String) {
        print("Audio streaming error: \(error)")
        errorMessage = error
        showError = true
        isRecording = false
        resetAudioCaptureState(clearTranscription: false)
        isExecutingCommand = false
        commandFeedback = nil

        webSocketSTTService.disconnect()
    }

    func resetAudioCaptureState(clearTranscription: Bool) {
        if clearTranscription {
            partialTranscription = ""
        }
        audioLevel = 0
        audioEnvelope = []
    }
}
