import AVFoundation

/// Service for streaming audio capture in real-time
@MainActor
@Observable
class StreamingAudioService: NSObject {
    // MARK: - Properties
    
    private var audioEngine: AVAudioEngine?
    private var audioFile: AVAudioFile?
    private var recordingURL: URL?
    private var currentSampleRate: Double = 48000
    
    var isRecording: Bool = false
    var onAudioChunk: ((Data) -> Void)?
    var onError: ((String) -> Void)?
    
    // MARK: - Public Methods
    
    /// Start streaming audio capture
    func startStreaming() async throws {
        print("🎤 Starting streaming audio capture")
        
        // Request microphone permission
        let granted = await AVAudioApplication.requestRecordPermission()
        guard granted else {
            let error = "Microphone permission denied"
            print("❌ \(error)")
            onError?(error)
            throw NSError(domain: "StreamingAudioService", code: 1, userInfo: [NSLocalizedDescriptionKey: error])
        }
        
        // Create temporary file URL for recording
        let tempDir = FileManager.default.temporaryDirectory
        let fileName = "stream_\(UUID().uuidString).m4a"
        let fileURL = tempDir.appendingPathComponent(fileName)
        self.recordingURL = fileURL
        
        // Setup audio engine
        let engine = AVAudioEngine()
        self.audioEngine = engine
        
        let inputNode = engine.inputNode
        let hardwareFormat = inputNode.outputFormat(forBus: 0)
        print("📊 Hardware format: \(hardwareFormat)")
        
        // Check if hardware format is valid (sample rate > 0)
        let isHardwareFormatValid = hardwareFormat.sampleRate > 0
        
        // Use hardware format if valid, otherwise create a standard format for simulator
        let recordingFormat: AVAudioFormat
        
        if isHardwareFormatValid {
            // Use hardware format on real device
            recordingFormat = hardwareFormat
            print("✅ Using hardware format for recording")
        } else {
            // On simulator, hardware format is invalid (0 Hz), so we need to use a converter
            // We'll tap with nil format (uses hardware format) and convert later
            print("⚠️ Hardware format invalid (simulator), using converter approach")
            
            // For simulator: we'll install tap with nil format and handle conversion
            guard let desiredFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                                     sampleRate: 48000,
                                                     channels: 1,
                                                     interleaved: false) else {
                let error = "Failed to create audio format"
                print("❌ \(error)")
                onError?(error)
                throw NSError(domain: "StreamingAudioService", code: 2, userInfo: [NSLocalizedDescriptionKey: error])
            }
            recordingFormat = desiredFormat
        }
        
        print("📊 Recording format: \(recordingFormat)")
        
        // Store sample rate for WAV conversion
        currentSampleRate = recordingFormat.sampleRate
        
        // Create audio file with AAC format (M4A) as backup
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: Int(recordingFormat.sampleRate),
            AVNumberOfChannelsKey: Int(recordingFormat.channelCount),
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue
        ]
        
        do {
            audioFile = try AVAudioFile(forWriting: fileURL, settings: settings)
        } catch {
            print("❌ Failed to create audio file: \(error)")
            onError?("Failed to create audio file: \(error.localizedDescription)")
            throw error
        }
        
        // Install tap - use nil format to let it use the hardware format automatically
        // This works on both simulator and device
        inputNode.installTap(onBus: 0, bufferSize: 4096, format: nil) { [weak self] buffer, time in
            guard let self = self else { return }
            
            // Safety check: stop processing if we're no longer recording
            guard self.isRecording else {
                print("⚠️ Audio tap fired but not recording - ignoring buffer")
                return
            }
            
            guard let audioFile = self.audioFile else { return }
            
            do {
                // Write to file (backup M4A recording)
                try audioFile.write(from: buffer)
                
                // Send each buffer immediately for real-time streaming
                Task { @MainActor in
                    // Double check we're still recording when callback executes
                    guard self.isRecording else {
                        print("⚠️ Recording stopped during buffer processing")
                        return
                    }
                    
                    // Convert buffer to raw PCM (no WAV header) for streaming to Soniox
                    // This automatically mixes multi-channel audio to mono
                    let pcmData = AudioFormatConverter.pcmBufferToRawPCM(buffer: buffer)
                    let durationSeconds = Double(buffer.frameLength) / self.currentSampleRate
                    let channels = buffer.format.channelCount
                    print("🎵 Sending PCM chunk: \(pcmData.count) bytes (\(buffer.frameLength) frames, \(channels) ch→1 ch, ~\(String(format: "%.3f", durationSeconds))s)")
                    self.onAudioChunk?(pcmData)
                }
            } catch {
                print("❌ Failed to write audio buffer: \(error)")
                Task { @MainActor in
                    self.onError?("Failed to write audio: \(error.localizedDescription)")
                }
            }
        }
        
        // Start the engine
        do {
            try engine.start()
            isRecording = true
            print("✅ Audio engine started")
        } catch {
            print("❌ Failed to start audio engine: \(error)")
            onError?("Failed to start recording: \(error.localizedDescription)")
            throw error
        }
    }
    
    /// Stop streaming and return the recorded file URL
    func stopStreaming() -> URL? {
        print("🛑 Stopping streaming audio capture (isRecording: \(isRecording))")
        
        guard let engine = audioEngine else {
            print("⚠️ Audio engine not initialized")
            isRecording = false
            return nil
        }
        
        // First, set isRecording to false to stop any pending callbacks
        isRecording = false
        
        // Then remove tap and stop engine
        let inputNode = engine.inputNode
        inputNode.removeTap(onBus: 0)
        engine.stop()
        
        audioEngine = nil
        audioFile = nil
        
        print("✅ Audio streaming stopped (tap removed, engine stopped)")
        return recordingURL
    }
    
    /// Delete the recording file
    func deleteRecording(at url: URL) {
        do {
            try FileManager.default.removeItem(at: url)
            print("🗑️ Deleted recording at \(url)")
        } catch {
            print("⚠️ Failed to delete recording: \(error)")
        }
    }
}
