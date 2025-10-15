import Foundation

/// Service for real-time speech-to-text via WebSocket
@MainActor
@Observable
class WebSocketSTTService: NSObject {
    // MARK: - Properties
    
    private let backendURL: String
    private var webSocketTask: URLSessionWebSocketTask?
    private var session: URLSession?
    
    var isConnected: Bool = false
    var currentTranscription: String = ""
    var onTranscriptionUpdate: ((String) -> Void)?
    var onFinalTranscription: ((String) -> Void)?
    var onError: ((String) -> Void)?
    var onReady: (() -> Void)?
    
    // MARK: - Initialization
    
    init(backendURL: String = Environment.websocketURL) {
        self.backendURL = backendURL
        super.init()
        
        let config = URLSessionConfiguration.default
        config.waitsForConnectivity = true
        self.session = URLSession(configuration: config, delegate: self, delegateQueue: OperationQueue())
    }
    
    // MARK: - Public Methods
    
    /// Connect to WebSocket STT endpoint
    func connect(token: String) {
        guard let url = URL(string: "\(backendURL)/stt/stream?token=\(token)") else {
            print("❌ Invalid WebSocket URL")
            onError?("Invalid WebSocket URL")
            return
        }
        
        print("🔗 Connecting to WebSocket: \(url)")
        
        webSocketTask = session?.webSocketTask(with: url)
        webSocketTask?.resume()
        
        // Start receiving messages
        receiveMessage()
    }
    
    /// Disconnect from WebSocket
    func disconnect() {
        print("🔌 Disconnecting WebSocket")
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        isConnected = false
        currentTranscription = ""
    }
    
    /// Send audio chunk to server
    func sendAudioChunk(_ data: Data) {
        guard isConnected else {
            print("⚠️ Not connected, skipping audio chunk")
            return
        }
        
        let message = URLSessionWebSocketTask.Message.data(data)
        webSocketTask?.send(message) { error in
            if let error = error {
                print("❌ Failed to send audio chunk: \(error)")
                Task { @MainActor [weak self] in
                    self?.onError?("Failed to send audio: \(error.localizedDescription)")
                }
            }
        }
    }
    
    /// Signal end of recording
    func endRecording() {
        guard isConnected else { return }
        
        print("🏁 Sending END signal")
        let message = URLSessionWebSocketTask.Message.string("END")
        webSocketTask?.send(message) { error in
            if let error = error {
                print("❌ Failed to send END signal: \(error)")
                Task { @MainActor [weak self] in
                    self?.onError?("Failed to end recording: \(error.localizedDescription)")
                }
            }
        }
    }
    
    // MARK: - Private Methods
    
    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            guard let self = self else { return }
            
            switch result {
            case .success(let message):
                Task { @MainActor in
                    self.handleMessage(message)
                    // Only continue receiving if still connected
                    if self.isConnected {
                        self.receiveMessage()
                    }
                }
                
            case .failure(let error):
                // Only report error if we're supposed to be connected
                Task { @MainActor in
                    if self.isConnected {
                        print("❌ WebSocket receive error: \(error)")
                        self.onError?("Connection error: \(error.localizedDescription)")
                        self.isConnected = false
                    } else {
                        print("ℹ️ WebSocket closed gracefully")
                    }
                }
            }
        }
    }
    
    private func handleMessage(_ message: URLSessionWebSocketTask.Message) {
        switch message {
        case .string(let text):
            print("📨 Received: \(text)")
            
            guard let data = text.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let type = json["type"] as? String else {
                print("⚠️ Invalid message format")
                return
            }
            
            switch type {
            case "ready":
                print("✅ WebSocket ready")
                isConnected = true
                onReady?()

            case "ack":
                if let bytesReceived = json["bytes_received"] as? Int,
                   let totalBytes = json["total_bytes"] as? Int {
                    print("✓ Acknowledged: \(bytesReceived) bytes, total: \(totalBytes)")
                }
                
            case "partial":
                if let text = json["text"] as? String {
                    print("📝 Partial: \(text)")
                    currentTranscription = text
                    onTranscriptionUpdate?(text)
                }
                
            case "final":
                if let text = json["text"] as? String {
                    print("✅ Final tokens: \(text)")
                    // Don't mark as final yet, wait for complete
                    currentTranscription = text
                    onTranscriptionUpdate?(text)
                }
            
            case "complete":
                if let text = json["text"] as? String {
                    print("✅ Complete transcription: \(text)")
                    currentTranscription = text
                    onFinalTranscription?(text)
                    // Mark as disconnected after complete transcription
                    isConnected = false
                }
                
            case "error":
                if let errorMsg = json["message"] as? String {
                    print("❌ Server error: \(errorMsg)")
                    onError?(errorMsg)
                }
                
            default:
                print("❓ Unknown message type: \(type)")
            }
            
        case .data(let data):
            print("📦 Received binary data: \(data.count) bytes")
            
        @unknown default:
            print("❓ Unknown message type")
        }
    }
}

// MARK: - URLSessionWebSocketDelegate

extension WebSocketSTTService: URLSessionWebSocketDelegate {
    nonisolated func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didOpenWithProtocol protocol: String?
    ) {
        print("🔓 WebSocket opened")
    }
    
    nonisolated func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
        reason: Data?
    ) {
        print("🔒 WebSocket closed: \(closeCode)")
        Task { @MainActor in
            self.isConnected = false
        }
    }
}
