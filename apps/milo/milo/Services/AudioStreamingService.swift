import AVFoundation

@MainActor
@Observable
class AudioStreamingService: NSObject {

    private var audioEngine: AVAudioEngine?
    private var audioFile: AVAudioFile?
    private var recordingURL: URL?
    private var currentSampleRate: Double = 48000
<<<<<<< HEAD:apps/modal/modal/Services/AudioStreamingService.swift

    var isRecording: Bool = false
    var onAudioChunk: ((Data) -> Void)?
=======
    private var lastChunkLogTime: CFAbsoluteTime = 0
    private var smoothedAudioLevel: Float = 0

    var isRecording: Bool = false
    var onAudioChunk: ((Data) -> Void)?
    var onAudioLevel: ((Float) -> Void)?
    var onAudioEnvelope: (([Float]) -> Void)?
>>>>>>> codex/refactor:apps/milo/milo/Services/AudioStreamingService.swift
    var onError: ((String) -> Void)?


    func startStreaming() async throws {
        print("Starting streaming audio capture")

        let granted = await AVAudioApplication.requestRecordPermission()
        guard granted else {
            let error = "Microphone permission denied"
            print("\(error)")
            onError?(error)
            throw NSError(domain: "AudioStreamingService", code: 1, userInfo: [NSLocalizedDescriptionKey: error])
        }

<<<<<<< HEAD:apps/modal/modal/Services/AudioStreamingService.swift
=======
        let audioSession = AVAudioSession.sharedInstance()
        do {
            try audioSession.setCategory(
                .playAndRecord,
                mode: .measurement,
                options: [.defaultToSpeaker, .allowBluetoothHFP]
            )
            try audioSession.setPreferredSampleRate(48_000)
            try audioSession.setActive(true, options: .notifyOthersOnDeactivation)
            print("Audio session configured (sampleRate: \(audioSession.sampleRate))")
        } catch {
            let errorMessage = "Failed to configure audio session: \(error.localizedDescription)"
            print(errorMessage)
            onError?(errorMessage)
            throw error
        }

>>>>>>> codex/refactor:apps/milo/milo/Services/AudioStreamingService.swift
        let tempDir = FileManager.default.temporaryDirectory
        let fileName = "stream_\(UUID().uuidString).m4a"
        let fileURL = tempDir.appendingPathComponent(fileName)
        self.recordingURL = fileURL

        let engine = AVAudioEngine()
        self.audioEngine = engine

        let inputNode = engine.inputNode
        let hardwareFormat = inputNode.outputFormat(forBus: 0)
        print("Hardware format: \(hardwareFormat)")

        let isHardwareFormatValid = hardwareFormat.sampleRate > 0

        let recordingFormat: AVAudioFormat

        if isHardwareFormatValid {
            recordingFormat = hardwareFormat
            print("Using hardware format for recording")
        } else {
            print("Hardware format invalid (simulator), using converter approach")

            guard let desiredFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                                     sampleRate: 48000,
                                                     channels: 1,
                                                     interleaved: false) else {
                let error = "Failed to create audio format"
                print("\(error)")
                onError?(error)
                throw NSError(domain: "AudioStreamingService", code: 2, userInfo: [NSLocalizedDescriptionKey: error])
            }
            recordingFormat = desiredFormat
        }

        print("Recording format: \(recordingFormat)")

        currentSampleRate = recordingFormat.sampleRate

        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: Int(recordingFormat.sampleRate),
            AVNumberOfChannelsKey: Int(recordingFormat.channelCount),
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue
        ]

        do {
            audioFile = try AVAudioFile(forWriting: fileURL, settings: settings)
        } catch {
            print("Failed to create audio file: \(error)")
            onError?("Failed to create audio file: \(error.localizedDescription)")
            throw error
        }

        inputNode.installTap(onBus: 0, bufferSize: 4096, format: nil) { [weak self] buffer, time in
            guard let self = self else { return }

            guard self.isRecording else {
                print("Audio tap fired but not recording - ignoring buffer")
                return
            }

            guard let audioFile = self.audioFile else { return }

            do {
                try audioFile.write(from: buffer)

                Task { @MainActor in
                    guard self.isRecording else {
                        print("Recording stopped during buffer processing")
                        return
                    }

                    let pcmData = AudioFormatConverter.pcmBufferToRawPCM(buffer: buffer)
<<<<<<< HEAD:apps/modal/modal/Services/AudioStreamingService.swift
                    let durationSeconds = Double(buffer.frameLength) / self.currentSampleRate
                    let channels = buffer.format.channelCount
                    print("Sending PCM chunk: \(pcmData.count) bytes (\(buffer.frameLength) frames, \(channels) ch1 ch, ~\(String(format: "%.3f", durationSeconds))s)")
=======
                    if pcmData.isEmpty {
                        print(
                            "PCM conversion produced empty chunk (format: \(buffer.format), frames: \(buffer.frameLength))."
                        )
                        return
                    }
                    if Environment.isDebugLoggingEnabled {
                        let now = CFAbsoluteTimeGetCurrent()
                        if now - self.lastChunkLogTime >= 1.0 {
                            self.lastChunkLogTime = now
                            let durationSeconds = Double(buffer.frameLength) / self.currentSampleRate
                            let channels = buffer.format.channelCount
                            print("Sending PCM chunk: \(pcmData.count) bytes (\(buffer.frameLength) frames, \(channels) ch, ~\(String(format: "%.3f", durationSeconds))s)")
                        }
                    }
                    self.publishAudioLevel(from: buffer)
                    self.publishAudioEnvelope(from: buffer)
>>>>>>> codex/refactor:apps/milo/milo/Services/AudioStreamingService.swift
                    self.onAudioChunk?(pcmData)
                }
            } catch {
                print("Failed to write audio buffer: \(error)")
                Task { @MainActor in
                    self.onError?("Failed to write audio: \(error.localizedDescription)")
                }
            }
        }

        do {
            try engine.start()
            isRecording = true
<<<<<<< HEAD:apps/modal/modal/Services/AudioStreamingService.swift
=======
            smoothedAudioLevel = 0
            onAudioLevel?(0)
            onAudioEnvelope?([])
>>>>>>> codex/refactor:apps/milo/milo/Services/AudioStreamingService.swift
            print("Audio engine started")
        } catch {
            print("Failed to start audio engine: \(error)")
            onError?("Failed to start recording: \(error.localizedDescription)")
            throw error
        }
    }

    func stopStreaming() -> URL? {
        print("Stopping streaming audio capture (isRecording: \(isRecording))")

        guard let engine = audioEngine else {
            print("Audio engine not initialized")
            isRecording = false
            return nil
        }

        isRecording = false
<<<<<<< HEAD:apps/modal/modal/Services/AudioStreamingService.swift
=======
        smoothedAudioLevel = 0
        onAudioLevel?(0)
        onAudioEnvelope?([])
>>>>>>> codex/refactor:apps/milo/milo/Services/AudioStreamingService.swift

        let inputNode = engine.inputNode
        inputNode.removeTap(onBus: 0)
        engine.stop()
<<<<<<< HEAD:apps/modal/modal/Services/AudioStreamingService.swift

        audioEngine = nil
        audioFile = nil

        print("Audio streaming stopped (tap removed, engine stopped)")
        return recordingURL
=======
        
        // Clean up audio session
        try? AVAudioSession.sharedInstance().setActive(false)

        audioEngine = nil
        audioFile = nil
        let url = recordingURL
        recordingURL = nil

        print("Audio streaming stopped (tap removed, engine stopped)")
        return url
>>>>>>> codex/refactor:apps/milo/milo/Services/AudioStreamingService.swift
    }

    func deleteRecording(at url: URL) {
        do {
            try FileManager.default.removeItem(at: url)
            print("Deleted recording at \(url)")
        } catch {
            print("Failed to delete recording: \(error)")
        }
    }
<<<<<<< HEAD:apps/modal/modal/Services/AudioStreamingService.swift
=======

    private func publishAudioLevel(from buffer: AVAudioPCMBuffer) {
        let normalizedLevel = normalizedAudioLevel(from: buffer)
        let attack: Float = 0.72
        let release: Float = 0.28
        let smoothing = normalizedLevel > smoothedAudioLevel ? attack : release
        smoothedAudioLevel += (normalizedLevel - smoothedAudioLevel) * smoothing
        onAudioLevel?(smoothedAudioLevel)
    }

    private func publishAudioEnvelope(from buffer: AVAudioPCMBuffer) {
        let segmentCount = 6
        guard let samples = normalizedSamples(from: buffer), !samples.isEmpty else {
            onAudioEnvelope?([])
            return
        }

        let segmentSize = max(1, samples.count / segmentCount)
        var envelope: [Float] = []
        envelope.reserveCapacity(segmentCount)

        var startIndex = 0
        while startIndex < samples.count && envelope.count < segmentCount {
            let endIndex = min(samples.count, startIndex + segmentSize)
            let segment = samples[startIndex..<endIndex]
            let peak = segment.reduce(Float.zero) { partial, sample in
                max(partial, abs(sample))
            }
            let rms = sqrt(segment.reduce(Float.zero) { partial, sample in
                partial + (sample * sample)
            } / Float(segment.count))
            let weighted = max(rms * 1.05, peak * 0.92)
            let normalized = max(0, min(pow(weighted / 0.12, 0.52), 1))
            envelope.append(normalized)
            startIndex = endIndex
        }

        onAudioEnvelope?(envelope)
    }

    private func normalizedAudioLevel(from buffer: AVAudioPCMBuffer) -> Float {
        let frameCount = Int(buffer.frameLength)
        guard frameCount > 0 else { return 0 }

        if let channelData = buffer.floatChannelData {
            return normalizedLevel(
                samples: UnsafeBufferPointer(start: channelData[0], count: frameCount)
            )
        }

        if let channelData = buffer.int16ChannelData {
            let samples = UnsafeBufferPointer(start: channelData[0], count: frameCount)
            let meanSquare = samples.reduce(Float.zero) { partial, sample in
                let normalized = Float(sample) / Float(Int16.max)
                return partial + (normalized * normalized)
            } / Float(frameCount)
            let peak = samples.reduce(Float.zero) { partial, sample in
                max(partial, abs(Float(sample) / Float(Int16.max)))
            }
            return normalize(meanSquare: meanSquare, peak: peak)
        }

        return 0
    }

    private func normalizedLevel(samples: UnsafeBufferPointer<Float>) -> Float {
        guard !samples.isEmpty else { return 0 }
        let meanSquare = samples.reduce(Float.zero) { partial, sample in
            partial + (sample * sample)
        } / Float(samples.count)
        let peak = samples.reduce(Float.zero) { partial, sample in
            max(partial, abs(sample))
        }
        return normalize(meanSquare: meanSquare, peak: peak)
    }

    private func normalize(meanSquare: Float, peak: Float) -> Float {
        let rms = sqrt(meanSquare)
        let weighted = max(rms * 1.1, peak * 0.9)
        let floor: Float = 0.0015
        let ceiling: Float = 0.1
        let clamped = max(floor, min(weighted, ceiling))
        let normalized = (clamped - floor) / (ceiling - floor)
        return pow(normalized, 0.5)
    }

    private func normalizedSamples(from buffer: AVAudioPCMBuffer) -> [Float]? {
        let frameCount = Int(buffer.frameLength)
        guard frameCount > 0 else { return nil }

        if let channelData = buffer.floatChannelData {
            return Array(UnsafeBufferPointer(start: channelData[0], count: frameCount))
        }

        if let channelData = buffer.int16ChannelData {
            let samples = UnsafeBufferPointer(start: channelData[0], count: frameCount)
            return samples.map { Float($0) / Float(Int16.max) }
        }

        return nil
    }
>>>>>>> codex/refactor:apps/milo/milo/Services/AudioStreamingService.swift
}
