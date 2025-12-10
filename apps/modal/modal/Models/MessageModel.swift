import Foundation

struct Message: Identifiable, Codable {
    let id: UUID
    let text: String
    let isUser: Bool
    let timestamp: Date

    init(id: UUID = UUID(), text: String, isUser: Bool, timestamp: Date = Date()) {
        self.id = id
        self.text = text
        self.isUser = isUser
        self.timestamp = timestamp
    }
}

@MainActor
@Observable
class ConversationService {
    var messages: [Message] = []

    func addMessage(_ message: Message) {
        messages.append(message)
    }

    func addUserMessage(_ text: String) {
        print("ConversationService: Adding user message: \"\(text)\"")
        let message = Message(text: text, isUser: true)
        messages.append(message)
        print("ConversationService: Messages array now has \(messages.count) messages")
    }

    func addAssistantMessage(_ text: String) {
        print("ConversationService: Adding assistant message: \"\(text)\"")
        let message = Message(text: text, isUser: false)
        messages.append(message)
        print("ConversationService: Messages array now has \(messages.count) messages")
    }

    func clearMessages() {
        messages.removeAll()
    }
}
