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
    
    // Command mode states
    var isInCommandMode = false
    private var commandModeTimer: Task<Void, Never>?
    
    // Command feedback states
    var commandFeedback: String?
    var isExecutingCommand = false
    
    // Device management states
    var availableDevices: [SpotifyDevice] = []
    var currentDevice: SpotifyDevice?
    var isLoadingDevices = false
    var showDeviceSelector = false
    
    // Spotify playback states
    var currentSpotifyTrack: SpotifyTrack?
    
    // Prevent concurrent connection attempts
    private var isStartingRecording = false
    
    // Track current recording session to prevent stale callbacks
    private var currentSessionId: UUID?
    
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
                self.isStartingRecording = false  // Reset flag after successful completion
                
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
                
                // CRITICAL: Force stop audio engine immediately
                if self.streamingAudioService.isRecording {
                    print("🛑 Force stopping audio engine due to error")
                    _ = self.streamingAudioService.stopStreaming()
                }
                
                self.errorMessage = error
                self.showError = true
                self.isProcessingTranscription = false
                self.isConnecting = false
                self.isStartingRecording = false
                self.isRecording = false
                self.conversationService.addAssistantMessage("Sorry, I couldn't transcribe that. Error: \(error)")
            }
        }
        
        // Handle unexpected disconnections
        webSocketSTTService.onUnexpectedDisconnect = { [weak self] in
            guard let self = self else { return }
            Task { @MainActor in
                print("⚠️ WebSocket unexpectedly disconnected, stopping audio recording")
                
                // CRITICAL: Force stop audio engine immediately
                if self.streamingAudioService.isRecording {
                    print("🛑 Force stopping audio engine due to unexpected disconnect")
                    _ = self.streamingAudioService.stopStreaming()
                }
                
                // Reset all recording-related state
                self.isStartingRecording = false
                self.isConnecting = false
                self.isRecording = false
                self.isProcessingTranscription = false
                self.partialTranscription = ""
            }
        }
        
        // Setup audio streaming callback - send PCM chunks in real-time
        streamingAudioService.onAudioChunk = { [weak self] pcmData in
            guard let self = self else { return }
            
            // Safety check: only send if we're actually recording and WebSocket is connected
            guard self.isRecording && self.webSocketSTTService.isConnected else {
                print("⚠️ Audio chunk produced but not recording/connected - stopping audio engine")
                Task { @MainActor in
                    _ = self.streamingAudioService.stopStreaming()
                    self.isRecording = false
                }
                return
            }
            
            self.webSocketSTTService.sendAudioChunk(pcmData)
        }
        
        streamingAudioService.onError = { [weak self] error in
            guard let self = self else { return }
            Task { @MainActor in
                print("❌ Audio streaming error: \(error)")
                self.errorMessage = error
                self.showError = true
                self.isRecording = false
                
                // Disconnect WebSocket on audio error
                self.webSocketSTTService.disconnect()
            }
        }
    }
    
    // MARK: - Public Methods
    
    /// Start streaming recording
    func startStreamingRecording(authService: AuthenticationService) async {
        // Prevent concurrent connection attempts
        guard !isStartingRecording else {
            print("⚠️ Already starting recording, ignoring duplicate call")
            return
        }
        
        guard let token = authService.session?.accessToken else {
            print("❌ No auth token available")
            await MainActor.run {
                errorMessage = "Not authenticated"
                showError = true
            }
            return
        }
        
        print("🎤 Starting streaming recording")
        isStartingRecording = true
        isConnecting = true
        
        // Create new session ID for this recording
        let sessionId = UUID()
        currentSessionId = sessionId
        print("🆔 New recording session: \(sessionId)")

        // Wait for WebSocket to be ready before starting audio
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            var hasResumed = false
            var timeoutTask: Task<Void, Never>?
            
            // Set up ready callback - start audio immediately when WebSocket is ready
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
                    // Verify this callback is for the current session
                    guard self.currentSessionId == sessionId else {
                        print("⚠️ onReady callback for stale session \(sessionId), ignoring")
                        return
                    }
                    
                    guard !hasResumed else {
                        print("⚠️ onReady called but already resumed")
                        return
                    }
                    
                    print("✅ WebSocket ready (session: \(sessionId)), starting audio...")

                    do {
                        try await self.streamingAudioService.startStreaming()
                        self.isConnecting = false
                        self.isRecording = true
                        self.isStartingRecording = false
                        print("✅ Recording started (session: \(sessionId))")
                    } catch {
                        print("❌ Failed to start recording: \(error)")
                        self.errorMessage = "Failed to start recording: \(error.localizedDescription)"
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

            // Connect WebSocket (will trigger onReady when server sends ready message)
            webSocketSTTService.connect(token: token)

            // Set timeout in case connection fails
            timeoutTask = Task {
                do {
                    try await Task.sleep(nanoseconds: 10_000_000_000) // 10s timeout
                    
                    // Check if we were cancelled during sleep
                    guard !Task.isCancelled else {
                        print("✅ Timeout task was cancelled")
                        return
                    }
                    
                    Task { @MainActor in
                        guard !hasResumed else {
                            print("✅ Timeout expired but connection already succeeded")
                            return
                        }
                        
                        if !self.webSocketSTTService.isConnected {
                            print("❌ WebSocket connection timeout - never connected")
                            self.errorMessage = "Failed to connect to speech service"
                            self.showError = true
                            self.isConnecting = false
                            self.isStartingRecording = false
                            self.webSocketSTTService.disconnect()
                            hasResumed = true
                            continuation.resume()
                        } else {
                            print("✅ Timeout reached but already connected - ignoring")
                        }
                    }
                } catch {
                    // Task was cancelled - this is expected when connection succeeds
                    print("✅ Timeout task cancelled via exception")
                }
            }
        }
        
        print("✅ startStreamingRecording completed (continuation resumed)")
    }
    
    /// Stop streaming and finalize transcription
    func stopStreamingRecording() async {
        print("🛑 Stopping streaming recording (isRecording: \(isRecording), isConnecting: \(isConnecting), session: \(currentSessionId?.uuidString ?? "nil"))")
        
        guard isRecording else {
            print("⚠️ Not currently recording, ignoring stop request")
            // Make sure state is clean even if we're not recording
            isStartingRecording = false
            isConnecting = false
            isProcessingTranscription = false
            currentSessionId = nil
            return
        }
        
        // Stop audio recording (sends any remaining buffered audio)
        _ = streamingAudioService.stopStreaming()
        
        isRecording = false
        isProcessingTranscription = true
        // Note: isStartingRecording will be reset when final transcription arrives
        // currentSessionId is kept to validate final transcription callback
        
        // Send END signal to get final transcription
        webSocketSTTService.endRecording()
        
        // Disconnect after receiving response (or timeout)
        // Reduced timeout since WebSocket now auto-disconnects on "complete"
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000) // 2s (reduced from 3s)
            
            await MainActor.run {
                print("⏰ 2s elapsed, ensuring cleanup (session: \(self.currentSessionId?.uuidString ?? "nil"))")
                
                // CRITICAL: Stop audio engine if still running
                if self.streamingAudioService.isRecording {
                    print("⚠️ Audio engine still running during cleanup - force stopping")
                    _ = self.streamingAudioService.stopStreaming()
                }
                
                // Reset state in case final transcription never arrived
                self.isStartingRecording = false
                self.isProcessingTranscription = false
                self.partialTranscription = ""
                self.currentSessionId = nil  // Invalidate session
                
                // Only disconnect if still connected (WebSocket auto-disconnects on "complete")
                if self.webSocketSTTService.isConnected {
                    print("⚠️ WebSocket still connected after timeout - force disconnecting")
                    self.webSocketSTTService.disconnect()
                } else {
                    print("✅ WebSocket already disconnected, cleanup completed")
                }
            }
        }
    }
    
    /// Toggle recording state
    func toggleRecording(authService: AuthenticationService) async {
        print("🔄 toggleRecording called (isRecording: \(isRecording), isConnecting: \(isConnecting), isStartingRecording: \(isStartingRecording))")
        
        if isRecording {
            await stopStreamingRecording()
        } else if !isConnecting && !isStartingRecording {
            await startStreamingRecording(authService: authService)
        } else {
            print("⚠️ Cannot start recording - already connecting or starting")
        }
    }
    
    // MARK: - Device Management
    
    /// Fetch available Spotify devices
    func fetchAvailableDevices() async {
        guard !isLoadingDevices else { return }
        
        isLoadingDevices = true
        defer { isLoadingDevices = false }
        
        do {
            // Send list_devices command via WebSocket
            let command = ["type": "command", "text": "list devices"]
            guard let jsonData = try? JSONSerialization.data(withJSONObject: command),
                  let jsonString = String(data: jsonData, encoding: .utf8) else {
                print("❌ Failed to create device list command")
                return
            }
            
            // Set up one-time callback for device list response
            var responseReceived = false
            webSocketSTTService.onCommandResult = { [weak self] result in
                guard let self = self, !responseReceived else { return }
                responseReceived = true
                
                Task { @MainActor in
                    if let devices = result["data"] as? [String: Any],
                       let deviceList = devices["devices"] as? [[String: Any]] {
                        self.availableDevices = deviceList.compactMap { deviceDict in
                            guard let id = deviceDict["id"] as? String,
                                  let name = deviceDict["name"] as? String,
                                  let type = deviceDict["type"] as? String,
                                  let isActive = deviceDict["is_active"] as? Bool,
                                  let volumePercent = deviceDict["volume_percent"] as? Int else {
                                return nil
                            }
                            
                            let device = SpotifyDevice(
                                id: id,
                                name: name,
                                type: type,
                                isActive: isActive,
                                volumePercent: volumePercent
                            )
                            
                            // Update current device if this one is active
                            if isActive {
                                self.currentDevice = device
                            }
                            
                            return device
                        }
                        
                        print("✅ Loaded \(self.availableDevices.count) devices")
                    }
                }
            }
            
            // Send command
            webSocketSTTService.sendMessage(jsonString)
            
            // Wait for response with timeout
            try await Task.sleep(nanoseconds: 3_000_000_000) // 3s timeout
            
        } catch {
            print("❌ Failed to fetch devices: \(error)")
        }
    }
    
    /// Switch to a different device
    func switchToDevice(_ device: SpotifyDevice) async {
        // Send switch_device command via WebSocket
        let command = ["type": "command", "text": "switch to \(device.name)"]
        guard let jsonData = try? JSONSerialization.data(withJSONObject: command),
              let jsonString = String(data: jsonData, encoding: .utf8) else {
            print("❌ Failed to create device switch command")
            return
        }
        
        // Set up one-time callback for device switch response
        var responseReceived = false
        webSocketSTTService.onCommandResult = { [weak self] result in
            guard let self = self, !responseReceived else { return }
            responseReceived = true
            
            Task { @MainActor in
                if result["success"] as? Bool == true {
                    // Update current device
                    self.currentDevice = device
                    
                    // Update device list to reflect new active device
                    self.availableDevices = self.availableDevices.map { d in
                        SpotifyDevice(
                            id: d.id,
                            name: d.name,
                            type: d.type,
                            isActive: d.id == device.id,
                            volumePercent: d.volumePercent
                        )
                    }
                    
                    print("✅ Switched to device: \(device.name)")
                } else {
                    print("❌ Failed to switch device")
                }
            }
        }
        
        // Send command
        webSocketSTTService.sendMessage(jsonString)
    }
    
    /// Toggle device selector visibility
    func toggleDeviceSelector() {
        showDeviceSelector.toggle()
        
        // Fetch devices when opening selector
        if showDeviceSelector {
            Task {
                await fetchAvailableDevices()
            }
        }
    }
}
