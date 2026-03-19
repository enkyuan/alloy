import AVFoundation
import Auth
import Foundation

@MainActor
@Observable
class SpeechToTextService {

    private let backendURL: String
    private let streamChunkFrameCount: AVAudioFrameCount = 4096
    private let transcriptionTimeoutNanoseconds: UInt64 = 45_000_000_000

    nonisolated init(backendURL: String = Environment.websocketURL) {
        self.backendURL = backendURL
    }

    func transcribe(audioURL: URL, authService: AuthService) async throws -> TranscriptionResponse {
        guard let accessToken = authService.session?.accessToken, !accessToken.isEmpty else {
            throw SpeechToTextError.notAuthenticated
        }

        let sttService = WebSocketSTTService(backendURL: backendURL)

        return try await withCheckedThrowingContinuation { continuation in
            var hasResumed = false
            var timeoutTask: Task<Void, Never>?

            func finish(_ result: Result<TranscriptionResponse, Error>) {
                guard !hasResumed else { return }
                hasResumed = true
                timeoutTask?.cancel()
                Task { @MainActor in
                    sttService.disconnect()
                }

                switch result {
                case .success(let response):
                    continuation.resume(returning: response)
                case .failure(let error):
                    continuation.resume(throwing: error)
                }
            }

            sttService.onReady = {
                Task {
                    do {
                        try await self.streamAudioFile(at: audioURL, via: sttService)
                        sttService.endRecording()
                    } catch {
                        finish(.failure(error))
                    }
                }
            }

            sttService.onFinalTranscription = { text in
                let response = TranscriptionResponse(
                    languageCode: "unknown",
                    languageProbability: 0,
                    text: text,
                    words: nil,
                    transcriptionId: nil
                )
                finish(.success(response))
            }

            sttService.onError = { message in
                finish(.failure(SpeechToTextError.transcriptionFailed(message)))
            }

            timeoutTask = Task { @MainActor in
                try? await Task.sleep(nanoseconds: self.transcriptionTimeoutNanoseconds)
                guard !Task.isCancelled else { return }
                finish(.failure(SpeechToTextError.transcriptionFailed("Transcription timed out.")))
            }

            sttService.connect(token: accessToken)
        }
    }

    private func streamAudioFile(at audioURL: URL, via sttService: WebSocketSTTService) async throws {
        let audioFile = try AVAudioFile(forReading: audioURL)
        let processingFormat = audioFile.processingFormat

        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: processingFormat,
            frameCapacity: streamChunkFrameCount
        ) else {
            throw SpeechToTextError.conversionFailed("Failed to create PCM buffer.")
        }

        while true {
            try audioFile.read(into: buffer, frameCount: streamChunkFrameCount)
            guard buffer.frameLength > 0 else { break }

            let pcmData = AudioFormatConverter.pcmBufferToRawPCM(buffer: buffer)
            guard !pcmData.isEmpty else {
                throw SpeechToTextError.conversionFailed("Failed to convert audio chunk to PCM.")
            }

            sttService.sendAudioChunk(pcmData)
            await Task.yield()
        }
    }
}

struct TranscriptionResponse: Codable {
    let languageCode: String
    let languageProbability: Double
    let text: String
    let words: [TranscriptionWord]?
    let transcriptionId: String?
}

struct TranscriptionWord: Codable {
    let text: String
    let start: Double?
    let end: Double?
    let type: String
    let speakerId: String?
    let logprob: Double
}

enum SpeechToTextError: LocalizedError {
    case notAuthenticated
    case conversionFailed(String)
    case transcriptionFailed(String)

    var errorDescription: String? {
        switch self {
        case .notAuthenticated:
            return "Not authenticated. Please sign in first."
        case .conversionFailed(let message):
            return "Audio conversion failed: \(message)"
        case .transcriptionFailed(let message):
            return "Transcription failed: \(message)"
        }
    }
}
