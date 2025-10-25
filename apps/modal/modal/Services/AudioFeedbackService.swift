//
//  AudioFeedbackService.swift
//  modal
//
//  Service for audio feedback using text-to-speech
//

import Foundation
import AVFoundation

/// Service for providing audio feedback to users
@MainActor
@Observable
class AudioFeedbackService: NSObject {
    // MARK: - Properties
    
    private let synthesizer = AVSpeechSynthesizer()
    var isSpeaking = false
    var verbosityLevel: VerbosityLevel = .normal
    
    // MARK: - Verbosity Levels
    
    enum VerbosityLevel {
        case minimal  // Only critical feedback
        case normal   // Standard feedback
        case verbose  // Detailed feedback
    }
    
    // MARK: - Initialization
    
    override init() {
        super.init()
        synthesizer.delegate = self
    }
    
    // MARK: - Public Methods
    
    /// Play audio feedback with text-to-speech
    /// - Parameters:
    ///   - message: The message to speak
    ///   - priority: Whether to interrupt current speech
    func playAudioFeedback(_ message: String, priority: Bool = false) {
        guard !message.isEmpty else { return }
        
        print("🔊 Audio feedback: \"\(message)\"")
        
        // Stop current speech if priority message
        if priority && synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }
        
        // Skip if already speaking and not priority
        if synthesizer.isSpeaking && !priority {
            print("⚠️ Already speaking, skipping feedback")
            return
        }
        
        let utterance = AVSpeechUtterance(string: message)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        utterance.rate = 0.5 // Slightly faster than default
        utterance.pitchMultiplier = 1.0
        utterance.volume = 0.8
        
        synthesizer.speak(utterance)
        isSpeaking = true
    }
    
    /// Stop current audio feedback
    func stopAudioFeedback() {
        if synthesizer.isSpeaking {
            print("🛑 Stopping audio feedback")
            synthesizer.stopSpeaking(at: .immediate)
            isSpeaking = false
        }
    }
    
    /// Play feedback for command processing
    func playCommandProcessingFeedback() {
        guard verbosityLevel != .minimal else { return }
        playAudioFeedback("Processing your command")
    }
    
    /// Play feedback for successful command
    /// - Parameter message: Success message from backend
    func playCommandSuccessFeedback(_ message: String) {
        // Always play success feedback
        playAudioFeedback(message)
    }
    
    /// Play feedback for command error
    /// - Parameter message: Error message from backend
    func playCommandErrorFeedback(_ message: String) {
        // Always play error feedback
        playAudioFeedback(message, priority: true)
    }
    
    /// Play feedback for wake word detection
    func playWakeWordDetectedFeedback() {
        guard verbosityLevel == .verbose else { return }
        playAudioFeedback("Listening for command")
    }
    
    /// Play feedback for command mode timeout
    func playCommandTimeoutFeedback() {
        guard verbosityLevel != .minimal else { return }
        playAudioFeedback("Command mode timed out")
    }
    
    /// Set verbosity level for feedback
    /// - Parameter level: The verbosity level to use
    func setVerbosityLevel(_ level: VerbosityLevel) {
        verbosityLevel = level
        print("🔊 Audio feedback verbosity set to: \(level)")
    }
}

// MARK: - AVSpeechSynthesizerDelegate

extension AudioFeedbackService: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didStart utterance: AVSpeechUtterance
    ) {
        Task { @MainActor in
            print("🔊 Started speaking: \"\(utterance.speechString)\"")
            self.isSpeaking = true
        }
    }
    
    nonisolated func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didFinish utterance: AVSpeechUtterance
    ) {
        Task { @MainActor in
            print("✅ Finished speaking: \"\(utterance.speechString)\"")
            self.isSpeaking = false
        }
    }
    
    nonisolated func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didCancel utterance: AVSpeechUtterance
    ) {
        Task { @MainActor in
            print("🛑 Cancelled speaking: \"\(utterance.speechString)\"")
            self.isSpeaking = false
        }
    }
}
