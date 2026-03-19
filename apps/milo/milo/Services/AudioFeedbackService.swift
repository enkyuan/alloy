
import Foundation
import AVFoundation

@MainActor
@Observable
class AudioFeedbackService: NSObject {

    private let synthesizer = AVSpeechSynthesizer()
    var isSpeaking = false
    var verbosityLevel: VerbosityLevel = .normal


    enum VerbosityLevel {
        case minimal
        case normal
        case verbose
    }


    override init() {
        super.init()
        synthesizer.delegate = self
    }


    func playAudioFeedback(_ message: String, priority: Bool = false) {
        guard !message.isEmpty else { return }

        print("Audio feedback: \"\(message)\"")

        if priority && synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }

        if synthesizer.isSpeaking && !priority {
            print("Already speaking, skipping feedback")
            return
        }

        let utterance = AVSpeechUtterance(string: message)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        utterance.rate = 0.5
        utterance.pitchMultiplier = 1.0
        utterance.volume = 0.8

        synthesizer.speak(utterance)
        isSpeaking = true
    }

    func stopAudioFeedback() {
        if synthesizer.isSpeaking {
            print("Stopping audio feedback")
            synthesizer.stopSpeaking(at: .immediate)
            isSpeaking = false
        }
    }

    func playCommandProcessingFeedback() {
        guard verbosityLevel != .minimal else { return }
        playAudioFeedback("Processing your command")
    }

    func playCommandSuccessFeedback(_ message: String) {
        playAudioFeedback(message)
    }

    func playCommandErrorFeedback(_ message: String) {
        playAudioFeedback(message, priority: true)
    }

    func playWakeWordDetectedFeedback() {
        guard verbosityLevel == .verbose else { return }
        playAudioFeedback("Listening for command")
    }

    func playCommandTimeoutFeedback() {
        guard verbosityLevel != .minimal else { return }
        playAudioFeedback("Command mode timed out")
    }

    func setVerbosityLevel(_ level: VerbosityLevel) {
        verbosityLevel = level
        print("Audio feedback verbosity set to: \(level)")
    }
}


extension AudioFeedbackService: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didStart utterance: AVSpeechUtterance
    ) {
        let speechString = utterance.speechString
        Task { @MainActor in
            print("Started speaking: \"\(speechString)\"")
            self.isSpeaking = true
        }
    }

    nonisolated func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didFinish utterance: AVSpeechUtterance
    ) {
        let speechString = utterance.speechString
        Task { @MainActor in
            print("Finished speaking: \"\(speechString)\"")
            self.isSpeaking = false
        }
    }

    nonisolated func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didCancel utterance: AVSpeechUtterance
    ) {
        let speechString = utterance.speechString
        Task { @MainActor in
            print("Cancelled speaking: \"\(speechString)\"")
            self.isSpeaking = false
        }
    }
}
