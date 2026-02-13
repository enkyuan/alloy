import Foundation
import SwiftUI

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
    private let insertionAnimation = Animation.spring(
        response: 0.4,
        dampingFraction: 0.78,
        blendDuration: 0.2
    )

    func addMessage(_ message: Message) {
        withAnimation(insertionAnimation) {
            messages.append(message)
        }
        if Environment.isDebugLoggingEnabled {
            print(
                "[ConversationService] addMessage id=\(message.id.uuidString) " +
                    "role=\(message.isUser ? "user" : "assistant") count=\(messages.count)"
            )
        }
    }

    func addUserMessage(_ text: String) {
        print("ConversationService: Adding user message: \"\(text)\"")
        let message = Message(text: text, isUser: true)
        withAnimation(insertionAnimation) {
            messages.append(message)
        }
        print(
            "ConversationService: Added user message id=\(message.id.uuidString), " +
                "count=\(messages.count)"
        )
    }

    func addAssistantMessage(_ text: String) {
        print("ConversationService: Adding assistant message: \"\(text)\"")
        let message = Message(text: text, isUser: false)
        withAnimation(insertionAnimation) {
            messages.append(message)
        }
        print(
            "ConversationService: Added assistant message id=\(message.id.uuidString), " +
                "count=\(messages.count)"
        )
    }

    func clearMessages() {
        messages.removeAll()
    }
}
