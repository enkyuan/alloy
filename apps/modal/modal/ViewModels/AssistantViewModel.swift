import Foundation
import AVFoundation

/// View model for the voice assistant
@MainActor
@Observable
class AssistantViewModel {
    // MARK: - Properties
    
    let conversationService = ConversationService()
    let audioRecordingService = AudioRecordingService()
    let speechToTextService = SpeechToTextService()
    
    var isRecording: Bool = false
    var isProcessingTranscription: Bool = false
    var errorMessage: String?
    var showError: Bool = false
    
    // MARK: - Public Methods
    
    /// Start recording audio
    func startRecording() {
        do {
            try audioRecordingService.startRecording()
            isRecording = true
            print("🎤 Recording started")
        } catch {
            errorMessage = error.localizedDescription
            showError = true
        }
    }
    
    /// Stop recording and transcribe
    func stopRecordingAndTranscribe(authService: AuthenticationService) async {
        guard let audioURL = audioRecordingService.stopRecording() else {
            print("❌ No recording to transcribe")
            errorMessage = "No recording found"
            showError = true
            return
        }

        print("🎤 Recording stopped, audio file at: \(audioURL)")
        print("📊 Audio file size: \(try? FileManager.default.attributesOfItem(atPath: audioURL.path)[.size] as? Int ?? 0) bytes")

        isRecording = false
        isProcessingTranscription = true

        do {
            print("📤 Sending audio for transcription...")
            print("🔐 Auth session exists: \(authService.session != nil)")

            // Transcribe the audio
            let transcription = try await speechToTextService.transcribe(audioURL: audioURL, authService: authService)

            print("✅ Transcription received: \"\(transcription.text)\"")
            print("📝 Current message count before adding: \(conversationService.messages.count)")

            // Add user message with transcription
            conversationService.addUserMessage(transcription.text)

            print("📝 Message count after adding user message: \(conversationService.messages.count)")
            print("📝 Messages array: \(conversationService.messages.map { $0.text })")

            // TODO: Send to LLM and get response
            // For now, add a placeholder response
            try await Task.sleep(nanoseconds: 500_000_000) // 0.5s delay
            conversationService.addAssistantMessage("I heard you say: \"\(transcription.text)\". I'm still learning how to respond!")

            print("📝 Message count after adding assistant message: \(conversationService.messages.count)")

            // Clean up audio file
            audioRecordingService.deleteRecording(at: audioURL)

        } catch let error as SpeechToTextError {
            print("❌ SpeechToText error: \(error.localizedDescription)")
            errorMessage = error.localizedDescription
            showError = true
            conversationService.addAssistantMessage("Sorry, I couldn't transcribe that. Error: \(error.localizedDescription)")
        } catch {
            print("❌ Transcription error: \(error)")
            errorMessage = error.localizedDescription
            showError = true
            conversationService.addAssistantMessage("Sorry, something went wrong: \(error.localizedDescription)")
        }

        isProcessingTranscription = false
        print("✅ Processing complete, isProcessingTranscription = false")
    }
    
    /// Toggle recording state
    func toggleRecording(authService: AuthenticationService) async {
        if isRecording {
            await stopRecordingAndTranscribe(authService: authService)
        } else {
            startRecording()
        }
    }
}
