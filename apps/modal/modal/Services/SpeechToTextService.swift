import Foundation
import Auth

@MainActor
@Observable
class SpeechToTextService {

    private let backendURL: String


    nonisolated init(backendURL: String = Environment.apiBaseURL) {
        self.backendURL = backendURL
    }


    func transcribe(audioURL: URL, authService: AuthService) async throws -> TranscriptionResponse {
        guard let session = authService.session else {
            throw SpeechToTextError.notAuthenticated
        }

        let url = URL(string: "\(backendURL)/stt/transcribe")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(session.accessToken)", forHTTPHeaderField: "Authorization")

        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        let httpBody = try createMultipartBody(audioURL: audioURL, boundary: boundary)
        request.httpBody = httpBody

        print("Sending transcription request...")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw SpeechToTextError.invalidResponse
        }

        if httpResponse.statusCode != 200 {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Unknown error"
            print("Transcription failed (status \(httpResponse.statusCode)): \(errorMessage)")
            throw SpeechToTextError.transcriptionFailed(errorMessage)
        }

        do {
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            let transcriptionResponse = try decoder.decode(TranscriptionResponse.self, from: data)
            print("Transcription successful: \(transcriptionResponse.text)")
            return transcriptionResponse
        } catch {
            print("Failed to decode transcription response: \(error)")
            throw SpeechToTextError.decodingFailed(error.localizedDescription)
        }
    }


    private func createMultipartBody(audioURL: URL, boundary: String) throws -> Data {
        var body = Data()

        let audioData = try Data(contentsOf: audioURL)
        let filename = audioURL.lastPathComponent
        let mimetype = "audio/m4a"

        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: \(mimetype)\r\n\r\n".data(using: .utf8)!)
        body.append(audioData)
        body.append("\r\n".data(using: .utf8)!)

        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        return body
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
    case invalidResponse
    case transcriptionFailed(String)
    case decodingFailed(String)

    var errorDescription: String? {
        switch self {
        case .notAuthenticated:
            return "Not authenticated. Please sign in first."
        case .invalidResponse:
            return "Invalid response from server"
        case .transcriptionFailed(let message):
            return "Transcription failed: \(message)"
        case .decodingFailed(let message):
            return "Failed to decode response: \(message)"
        }
    }
}
