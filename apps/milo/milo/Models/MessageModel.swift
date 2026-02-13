import Foundation
import SwiftUI

enum MessageRole: String, Codable {
    case user
    case assistant
    case optimisticPlaceholder
}

struct Message: Identifiable, Codable, Equatable {
    let id: UUID
    let text: String
    let role: MessageRole
    let timestamp: Date

    init(id: UUID = UUID(), text: String, role: MessageRole, timestamp: Date = Date()) {
        self.id = id
        self.text = text
        self.role = role
        self.timestamp = timestamp
    }

    init(id: UUID = UUID(), text: String, isUser: Bool, timestamp: Date = Date()) {
        self.init(
            id: id,
            text: text,
            role: isUser ? .user : .assistant,
            timestamp: timestamp
        )
    }

    var isUser: Bool {
        role == .user
    }

    var isAssistant: Bool {
        role == .assistant
    }
}

@MainActor
@Observable
class ConversationService {
    var messages: [Message] = []
    var isMessageSendAnimating = false
    var didLatestFirstUserAnimationComplete = false
    var latestUserAnchorMessageId: UUID?
    var pendingFirstAssistantRevealMessageId: UUID?

    private var latestSendWasNewConversation = false
    private let insertionAnimation = Animation.spring(
        response: 0.4,
        dampingFraction: 0.78,
        blendDuration: 0.2
    )

    func beginSendCycle(isNewConversation: Bool) {
        latestSendWasNewConversation = isNewConversation
        isMessageSendAnimating = isNewConversation
        didLatestFirstUserAnimationComplete = !isNewConversation
        pendingFirstAssistantRevealMessageId = nil

        if Environment.isDebugLoggingEnabled {
            print(
                "[ConversationService] beginSendCycle isNewConversation=\(isNewConversation) " +
                    "messageCount=\(messages.count)"
            )
        }
    }

    func completeFirstUserSendAnimationIfNeeded() {
        guard isMessageSendAnimating else { return }
        isMessageSendAnimating = false
        didLatestFirstUserAnimationComplete = true

        if Environment.isDebugLoggingEnabled {
            print(
                "[ConversationService] completeFirstUserSendAnimation " +
                    "messageCount=\(messages.count)"
            )
        }
    }

    func shouldRunFirstUserAnimation(for message: Message, index: Int) -> Bool {
        latestSendWasNewConversation
            && isMessageSendAnimating
            && index == 0
            && message.role == .user
    }

    @discardableResult
    func consumeFirstAssistantRevealIfNeeded(for messageId: UUID) -> Bool {
        guard pendingFirstAssistantRevealMessageId == messageId else {
            return false
        }
        pendingFirstAssistantRevealMessageId = nil
        return true
    }

    @discardableResult
    func addMessage(_ message: Message) -> Message {
        withAnimation(insertionAnimation) {
            messages.append(message)
        }

        if message.role == .user {
            latestUserAnchorMessageId = message.id
            if !latestSendWasNewConversation {
                didLatestFirstUserAnimationComplete = true
                isMessageSendAnimating = false
            }
        } else if
            message.role == .assistant
                && latestSendWasNewConversation
                && pendingFirstAssistantRevealMessageId == nil
        {
            pendingFirstAssistantRevealMessageId = message.id
        }

        if Environment.isDebugLoggingEnabled {
            print(
                "[ConversationService] addMessage id=\(message.id.uuidString) " +
                    "role=\(message.role.rawValue) count=\(messages.count)"
            )
        }
        return message
    }

    @discardableResult
    func addUserMessage(_ text: String) -> Message {
        print("ConversationService: Adding user message: \"\(text)\"")
        let message = Message(text: text, role: .user)
        addMessage(message)
        print(
            "ConversationService: Added user message id=\(message.id.uuidString), " +
                "count=\(messages.count)"
        )
        return message
    }

    @discardableResult
    func addAssistantMessage(_ text: String) -> Message {
        print("ConversationService: Adding assistant message: \"\(text)\"")
        let message = Message(text: text, role: .assistant)
        addMessage(message)
        print(
            "ConversationService: Added assistant message id=\(message.id.uuidString), " +
                "count=\(messages.count)"
        )
        return message
    }

    func clearMessages() {
        messages.removeAll()
        latestUserAnchorMessageId = nil
        pendingFirstAssistantRevealMessageId = nil
        latestSendWasNewConversation = false
        isMessageSendAnimating = false
        didLatestFirstUserAnimationComplete = false
    }
}
