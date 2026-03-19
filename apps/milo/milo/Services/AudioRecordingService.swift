import Foundation
import AVFoundation

@MainActor
@Observable
class AudioRecordingService {

    private var audioRecorder: AVAudioRecorder?
    private var recordingSession: AVAudioSession = AVAudioSession.sharedInstance()
    private var currentRecordingURL: URL?

    var isRecording: Bool = false
    var recordingDuration: TimeInterval = 0
    private var recordingTimer: Timer?


    init() {
        setupAudioSession()
    }


    func startRecording() throws {
        let filename = "recording-\(Date().timeIntervalSince1970).m4a"
        let documentPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        currentRecordingURL = documentPath.appendingPathComponent(filename)

        guard let url = currentRecordingURL else {
            throw AudioRecordingError.invalidURL
        }

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 16000,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue
        ]

        do {
            try recordingSession.setCategory(.record, mode: .measurement, options: [])
            try recordingSession.setActive(true)

            audioRecorder = try AVAudioRecorder(url: url, settings: settings)
            audioRecorder?.record()

            isRecording = true
            recordingDuration = 0

            recordingTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard let self = self, let recorder = self.audioRecorder else { return }
                    self.recordingDuration = recorder.currentTime
                }
            }

            print("Started recording to: \(url.lastPathComponent)")
        } catch {
            print("Failed to start recording: \(error)")
            throw AudioRecordingError.recordingFailed(error.localizedDescription)
        }
    }

    func stopRecording() -> URL? {
        guard isRecording, let recorder = audioRecorder else {
            return nil
        }

        recorder.stop()
        recordingTimer?.invalidate()
        recordingTimer = nil
        isRecording = false
<<<<<<< HEAD:apps/modal/modal/Services/AudioRecordingService.swift

        try? recordingSession.setActive(false)
=======
        recordingDuration = 0

        try? recordingSession.setActive(false)
        
        // Clean up recorder reference
        audioRecorder = nil
>>>>>>> codex/refactor:apps/milo/milo/Services/AudioRecordingService.swift

        print("Stopped recording. Duration: \(recordingDuration)s")

        return currentRecordingURL
    }

    func deleteRecording(at url: URL) {
        try? FileManager.default.removeItem(at: url)
    }


    private func setupAudioSession() {
        do {
            try recordingSession.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
            try recordingSession.setActive(true)
        } catch {
            print("Failed to setup audio session: \(error)")
        }
    }
}


enum AudioRecordingError: LocalizedError {
    case invalidURL
    case recordingFailed(String)
    case permissionDenied

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Could not create recording file URL"
        case .recordingFailed(let message):
            return "Recording failed: \(message)"
        case .permissionDenied:
            return "Microphone permission denied"
        }
    }
}
