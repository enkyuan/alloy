import Foundation
import AVFoundation

/// Service for recording audio from the microphone
@MainActor
@Observable
class AudioRecordingService {
    // MARK: - Properties
    
    private var audioRecorder: AVAudioRecorder?
    private var recordingSession: AVAudioSession = AVAudioSession.sharedInstance()
    private var currentRecordingURL: URL?
    
    var isRecording: Bool = false
    var recordingDuration: TimeInterval = 0
    private var recordingTimer: Timer?
    
    // MARK: - Initialization
    
    init() {
        setupAudioSession()
    }
    
    // MARK: - Public Methods
    
    /// Start recording audio
    func startRecording() throws {
        // Generate unique filename
        let filename = "recording-\(Date().timeIntervalSince1970).m4a"
        let documentPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        currentRecordingURL = documentPath.appendingPathComponent(filename)
        
        guard let url = currentRecordingURL else {
            throw AudioRecordingError.invalidURL
        }
        
        // Audio settings optimized for speech
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 16000, // 16kHz is optimal for speech
            AVNumberOfChannelsKey: 1, // Mono
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue
        ]
        
        do {
            // Activate audio session
            try recordingSession.setCategory(.record, mode: .measurement, options: [])
            try recordingSession.setActive(true)
            
            // Create and start recorder
            audioRecorder = try AVAudioRecorder(url: url, settings: settings)
            audioRecorder?.record()
            
            isRecording = true
            recordingDuration = 0
            
            // Start duration timer
            recordingTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard let self = self, let recorder = self.audioRecorder else { return }
                    self.recordingDuration = recorder.currentTime
                }
            }
            
            print("🎤 Started recording to: \(url.lastPathComponent)")
        } catch {
            print("❌ Failed to start recording: \(error)")
            throw AudioRecordingError.recordingFailed(error.localizedDescription)
        }
    }
    
    /// Stop recording and return the audio file URL
    func stopRecording() -> URL? {
        guard isRecording, let recorder = audioRecorder else {
            return nil
        }
        
        recorder.stop()
        recordingTimer?.invalidate()
        recordingTimer = nil
        isRecording = false
        
        // Deactivate audio session
        try? recordingSession.setActive(false)
        
        print("🛑 Stopped recording. Duration: \(recordingDuration)s")
        
        return currentRecordingURL
    }
    
    /// Delete a recording file
    func deleteRecording(at url: URL) {
        try? FileManager.default.removeItem(at: url)
    }
    
    // MARK: - Private Methods
    
    private func setupAudioSession() {
        do {
            try recordingSession.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
            try recordingSession.setActive(true)
        } catch {
            print("❌ Failed to setup audio session: \(error)")
        }
    }
}

// MARK: - Errors

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
