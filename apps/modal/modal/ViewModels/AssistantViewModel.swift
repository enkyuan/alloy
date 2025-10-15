import Foundation
import AVFoundation
import Auth

/// View model for the voice assistant with real-time streaming
@MainActor
@Observable
class AssistantViewModel {
    // MARK: - Properties
    
    let conversationService = ConversationService()
    let streamingAudioService = StreamingAudioService()
    let webSocketSTTService = WebSocketSTTService()
    
    // Recording and processing states
    var isRecording = false
    var isConnecting = false  // New state for when connecting WebSocket
    var isProcessingTranscription = false
    var partialTranscription: String = ""
    var errorMessage: String?
    var showError: Bool = false
    
    // MARK: - Initialization
    
    init() {
        setupWebSocketCallbacks()
    }
    
    // MARK: - Setup
    
    private func setupWebSocketCallbacks() {
        // Handle partial transcriptions (real-time updates as you speak)
        webSocketSTTService.onTranscriptionUpdate = { [weak self] text in
            guard let self = self else { return }
            Task { @MainActor in
                print("📝 Partial transcription received: \"\(text)\"")
                self.partialTranscription = text
                print("📝 ViewModel partialTranscription updated to: \"\(self.partialTranscription)\"")
            }
        }
        
        // Handle final transcription
        webSocketSTTService.onFinalTranscription = { [weak self] text in
            guard let self = self else { return }
            Task { @MainActor in
                print("✅ Final transcription received: \"\(text)\"")
                self.partialTranscription = ""
                self.isProcessingTranscription = false
                
                // Add user message
                self.conversationService.addUserMessage(text)
                print("📝 Message count after adding user message: \(self.conversationService.messages.count)")
                
                // TODO: Send to LLM and get response
                // For now, add a placeholder response
                Task {
                    try? await Task.sleep(nanoseconds: 500_000_000) // 0.5s delay
                    self.conversationService.addAssistantMessage("I heard you say: \"\(text)\". I'm still learning how to respond!")
                    print("📝 Message count after adding assistant message: \(self.conversationService.messages.count)")
                }
            }
        }
        
        // Handle errors
        webSocketSTTService.onError = { [weak self] error in
            guard let self = self else { return }
            Task { @MainActor in
                print("❌ WebSocket error: \(error)")
                self.errorMessage = error
                self.showError = true
                self.isProcessingTranscription = false
                self.conversationService.addAssistantMessage("Sorry, I couldn't transcribe that. Error: \(error)")
            }
        }
        
        // Setup audio streaming callback - send PCM chunks in real-time
        streamingAudioService.onAudioChunk = { [weak self] pcmData in
            guard let self = self else { return }
            self.webSocketSTTService.sendAudioChunk(pcmData)
        }
        
        streamingAudioService.onError = { [weak self] error in
            guard let self = self else { return }
            Task { @MainActor in
                print("❌ Audio streaming error: \(error)")
                self.errorMessage = error
                self.showError = true
                self.isRecording = false
            }
        }
    }
    
    // MARK: - Public Methods
    
    /// Start streaming recording
    func startStreamingRecording(authService: AuthenticationService) async {
        guard let token = authService.session?.accessToken else {
            print("❌ No auth token available")
            await MainActor.run {
                errorMessage = "Not authenticated"
                showError = true
            }
            return
        }
        
        print("🎤 Starting streaming recording")
        isConnecting = true

        // Wait for WebSocket to be ready before starting audio
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            // Set up ready callback - start audio immediately when WebSocket is ready
            webSocketSTTService.onReady = { [weak self] in
                guard let self = self else {
                    continuation.resume()
                    return
                }

                Task { @MainActor in
                    print("✅ WebSocket ready, starting audio...")

                    do {
                        try await self.streamingAudioService.startStreaming()
                        self.isConnecting = false
                        self.isRecording = true
                        print("✅ Recording started")
                    } catch {
                        print("❌ Failed to start recording: \(error)")
                        self.errorMessage = "Failed to start recording: \(error.localizedDescription)"
                        self.showError = true
                        self.isConnecting = false
                        self.webSocketSTTService.disconnect()
                    }

                    continuation.resume()
                }
            }

            // Connect WebSocket (will trigger onReady when server sends ready message)
            webSocketSTTService.connect(token: token)

            // Set timeout in case connection fails
            Task {
                try? await Task.sleep(nanoseconds: 5_000_000_000) // 5s timeout
                if await !self.webSocketSTTService.isConnected {
                    print("❌ WebSocket connection timeout")
                    self.errorMessage = "Failed to connect to speech service"
                    self.showError = true
                    self.isConnecting = false
                    continuation.resume()
                }
            }
        }
    }
    
    /// Stop streaming and finalize transcription
    func stopStreamingRecording() async {
        print("🛑 Stopping streaming recording")
        
        // Stop audio recording (sends any remaining buffered audio)
        _ = streamingAudioService.stopStreaming()
        
        isRecording = false
        isProcessingTranscription = true
        
        // Send END signal to get final transcription
        webSocketSTTService.endRecording()
        
        // Disconnect after receiving response
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000) // 2s
            webSocketSTTService.disconnect()
            print("✅ WebSocket disconnected")
        }
    }
    
    /// Toggle recording state
    func toggleRecording(authService: AuthenticationService) async {
        if isRecording {
            await stopStreamingRecording()
        } else {
            await startStreamingRecording(authService: authService)
        }
    }
}
