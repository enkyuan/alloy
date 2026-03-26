import Auth
import Foundation
import Supabase

extension AssistantViewModel {
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
        resetAudioCaptureState(clearTranscription: true)
        connectionTimeoutTask?.cancel()

        let sessionId = UUID()
        currentSessionId = sessionId
        print("New recording session: \(sessionId)")

        webSocketSTTService.onReady = { [weak self] in
            guard let self else { return }

            Task { @MainActor in
                guard self.currentSessionId == sessionId else {
                    print("onReady callback for stale session \(sessionId), ignoring")
                    return
                }

                self.connectionTimeoutTask?.cancel()
                self.connectionTimeoutTask = nil

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
                    self.resetAudioCaptureState(clearTranscription: false)
                    self.currentSessionId = nil
                    self.webSocketSTTService.disconnect()
                }
            }
        }

        webSocketSTTService.connect(token: token)

        connectionTimeoutTask = Task { @MainActor [weak self] in
            guard let self else { return }

            do {
                try await Task.sleep(nanoseconds: 10_000_000_000)
                guard !Task.isCancelled else {
                    print("Timeout task was cancelled")
                    return
                }

                guard self.currentSessionId == sessionId else {
                    print("Timeout task ignored for stale session \(sessionId)")
                    return
                }

                if !self.webSocketSTTService.isConnected {
                    print("WebSocket connection timeout - never connected")
                    self.errorMessage = "Failed to connect to speech service"
                    self.showError = true
                    self.isConnecting = false
                    self.isStartingRecording = false
                    self.resetAudioCaptureState(clearTranscription: false)
                    self.currentSessionId = nil
                    self.webSocketSTTService.disconnect()
                } else {
                    print("Timeout reached but already connected - ignoring")
                }
            } catch {
                print("Timeout task cancelled via exception")
            }
        }
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
            resetAudioCaptureState(clearTranscription: false)
            connectionTimeoutTask?.cancel()
            connectionTimeoutTask = nil
            currentSessionId = nil
            return
        }

        _ = streamingAudioService.stopStreaming()

        isRecording = false
        resetAudioCaptureState(clearTranscription: false)
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
                self.resetAudioCaptureState(clearTranscription: false)
                self.connectionTimeoutTask?.cancel()
                self.connectionTimeoutTask = nil
                self.currentSessionId = nil
            }
        }
    }

    func cancelStreamingConnection() {
        print(
            "Cancelling streaming connection (isConnecting: \(isConnecting), session: \(currentSessionId?.uuidString ?? "nil"))"
        )

        guard isConnecting || isStartingRecording else { return }

        connectionTimeoutTask?.cancel()
        connectionTimeoutTask = nil
        currentSessionId = nil
        isConnecting = false
        isStartingRecording = false
        partialTranscription = ""
        resetAudioCaptureState(clearTranscription: false)
        webSocketSTTService.disconnect()
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
}
