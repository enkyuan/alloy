import Foundation

/// Represents a message in a conversation
struct Message: Identifiable, Codable {
    let id: UUID
    let text: String
    let isUser: Bool // true if message is from user, false if from assistant
    let timestamp: Date
    
    init(id: UUID = UUID(), text: String, isUser: Bool, timestamp: Date = Date()) {
        self.id = id
        self.text = text
        self.isUser = isUser
        self.timestamp = timestamp
    }
}

/// Conversation state manager
@MainActor
@Observable
class ConversationService {
    var messages: [Message] = []
    
    func addMessage(_ message: Message) {
        messages.append(message)
    }
    
    func addUserMessage(_ text: String) {
        print("💬 ConversationService: Adding user message: \"\(text)\"")
        let message = Message(text: text, isUser: true)
        messages.append(message)
        print("💬 ConversationService: Messages array now has \(messages.count) messages")
    }
    
    func addAssistantMessage(_ text: String) {
        print("🤖 ConversationService: Adding assistant message: \"\(text)\"")
        let message = Message(text: text, isUser: false)
        messages.append(message)
        print("🤖 ConversationService: Messages array now has \(messages.count) messages")
    }
    
    func clearMessages() {
        messages.removeAll()
    }
}
