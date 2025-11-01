import Foundation

/// Service for real-time speech-to-text via WebSocket
@MainActor
@Observable
class WebSocketSTTService: NSObject {
    // MARK: - Properties
    
    private let backendURL: String
    private var webSocketTask: URLSessionWebSocketTask?
    private var _session: URLSession?
    private var session: URLSession {
        if _session == nil {
            let config = URLSessionConfiguration.default
            config.waitsForConnectivity = true
            _session = URLSession(configuration: config, delegate: self, delegateQueue: OperationQueue())
        }
        return _session!
    }
    
    // Connection tracking to prevent stale callbacks
    private var currentConnectionId: UUID?
    
    var isConnected: Bool = false
    var currentTranscription: String = ""
    var onTranscriptionUpdate: ((String) -> Void)?
    var onFinalTranscription: ((String) -> Void)?
    var onError: ((String) -> Void)?
    var onReady: (() -> Void)?
    var onUnexpectedDisconnect: (() -> Void)?
    var onCommandResult: (([String: Any]) -> Void)?
    var onCommandError: ((String, String?) -> Void)?  // (message, errorCode)
    var onAIResponse: (([String: Any]) -> Void)?  // For Gemini AI responses
    
    // MARK: - Initialization
    
    nonisolated init(backendURL: String = Environment.websocketURL) {
        self.backendURL = backendURL
        super.init()
    }
    
    // MARK: - Public Methods
    
    /// Connect to WebSocket STT endpoint
    func connect(token: String) {
        // Clean up any existing connection first
        if webSocketTask != nil {
            print("⚠️ Existing WebSocket task found, cleaning up before new connection")
            disconnect()
        }
        
        // Generate new connection ID for this session
        let connectionId = UUID()
        currentConnectionId = connectionId
        print("🆔 New connection ID: \(connectionId)")
        
        guard let url = URL(string: "\(backendURL)/stt/stream?token=\(token)") else {
            print("❌ Invalid WebSocket URL")
            onError?("Invalid WebSocket URL")
            return
        }
        
        print("🔗 Connecting to WebSocket: \(url)")
        
        webSocketTask = session.webSocketTask(with: url)
        webSocketTask?.resume()
        
        // Start receiving messages
        receiveMessage()
    }
    
    /// Disconnect from WebSocket (called intentionally)
    func disconnect() {
        print("🔌 Disconnecting WebSocket (isConnected: \(isConnected), connectionId: \(currentConnectionId?.uuidString ?? "nil"))")
        isConnected = false
        currentConnectionId = nil  // Invalidate connection ID
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        currentTranscription = ""
        
        // Don't clear callbacks - they're set once in ViewModel init and should persist
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
    
    /// Send a command message to the server
    func sendCommand(_ commandText: String, wakeWordDetected: Bool = true) {
        guard isConnected else {
            print("⚠️ Not connected, cannot send command")
            return
        }
        
        print("🎯 Sending command: \(commandText)")
        
        let commandMessage: [String: Any] = [
            "type": "command",
            "text": commandText,
            "wake_word_detected": wakeWordDetected
        ]
        
        guard let jsonData = try? JSONSerialization.data(withJSONObject: commandMessage),
              let jsonString = String(data: jsonData, encoding: .utf8) else {
            print("❌ Failed to serialize command message")
            return
        }
        
        let message = URLSessionWebSocketTask.Message.string(jsonString)
        webSocketTask?.send(message) { error in
            if let error = error {
                print("❌ Failed to send command: \(error)")
                Task { @MainActor [weak self] in
                    self?.onError?("Failed to send command: \(error.localizedDescription)")
                }
            }
        }
    }
    
    /// Send a raw message string to the server
    func sendMessage(_ messageString: String) {
        guard isConnected else {
            print("⚠️ Not connected, cannot send message")
            return
        }
        
        print("📤 Sending message: \(messageString)")
        
        let message = URLSessionWebSocketTask.Message.string(messageString)
        webSocketTask?.send(message) { error in
            if let error = error {
                print("❌ Failed to send message: \(error)")
                Task { @MainActor [weak self] in
                    self?.onError?("Failed to send message: \(error.localizedDescription)")
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
                    } else {
                        print("ℹ️ Stopped receiving messages (disconnected)")
                    }
                }
                
            case .failure(let error):
                // Only report error if we're supposed to be connected
                Task { @MainActor in
                    if self.isConnected {
                        print("❌ WebSocket receive error: \(error)")
                        print("❌ Error details: \(error.localizedDescription)")
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
        // Capture current connection ID to check if this message is for the current session
        let messageConnectionId = currentConnectionId
        
        switch message {
        case .string(let text):
            print("📨 Received: \(text) (connectionId: \(messageConnectionId?.uuidString ?? "nil"))")
            
            // Verify this message is for the current connection
            guard messageConnectionId != nil && messageConnectionId == currentConnectionId else {
                print("⚠️ Ignoring message from stale connection")
                return
            }
            
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
                    // Keep WebSocket open for sending commands
                    // Will be disconnected manually when needed
                }
                
            case "error":
                if let errorMsg = json["message"] as? String {
                    print("❌ Server error: \(errorMsg)")
                    onError?(errorMsg)
                }
            
            case "command_result":
                print("✅ Command result received")
                onCommandResult?(json)
            
            case "command_error":
                if let errorMsg = json["message"] as? String {
                    let errorCode = json["error_code"] as? String
                    print("❌ Command error: \(errorMsg) (code: \(errorCode ?? "none"))")
                    onCommandError?(errorMsg, errorCode)
                }
            
            case "ai_response":
                print("🤖 AI response received")
                onAIResponse?(json)
            
            case "ai_error":
                if let errorMsg = json["message"] as? String {
                    print("❌ AI error: \(errorMsg)")
                    onAIResponse?(json)  // Pass error through same callback
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
            let wasConnected = self.isConnected
            self.isConnected = false
            
            // If we were connected and the WebSocket closed unexpectedly (not through normal disconnect)
            // This happens when the server closes the connection or network errors occur
            if wasConnected {
                print("⚠️ Unexpected WebSocket closure detected")
                self.onUnexpectedDisconnect?()
            }
        }
    }
}
