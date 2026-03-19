import Foundation
<<<<<<< HEAD:apps/modal/modal/Models/MessageModel.swift

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
=======
import SwiftUI

enum MessageRole: String, Codable {
    case user
    case assistant
    case optimisticPlaceholder
}

enum MessageIntegrationBrand: String, Codable {
    case spotify
    case gmail
    case googleCalendar
    case discord
    case todoist
    case calendly
    case uber
    case doordash
    case instacart
    case appleMusic
}

struct Message: Identifiable, Codable, Equatable {
    let id: UUID
    let text: String
    let role: MessageRole
    let timestamp: Date
    let integrationBrand: MessageIntegrationBrand?

    init(
        id: UUID = UUID(),
        text: String,
        role: MessageRole,
        timestamp: Date = Date(),
        integrationBrand: MessageIntegrationBrand? = nil
    ) {
        self.id = id
        self.text = text
        self.role = role
        self.timestamp = timestamp
        self.integrationBrand = integrationBrand
    }

    init(
        id: UUID = UUID(),
        text: String,
        isUser: Bool,
        timestamp: Date = Date(),
        integrationBrand: MessageIntegrationBrand? = nil
    ) {
        self.init(
            id: id,
            text: text,
            role: isUser ? .user : .assistant,
            timestamp: timestamp,
            integrationBrand: integrationBrand
        )
    }

    var isUser: Bool {
        role == .user
    }

    var isAssistant: Bool {
        role == .assistant
    }

    var normalizedDisplayText: String {
        text
            .replacingOccurrences(of: "\u{00A0}", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var isDisplayable: Bool {
        !normalizedDisplayText.isEmpty
    }
}

extension Message {
    func canStack(with other: Message) -> Bool {
        guard role == other.role else { return false }
        guard role != .optimisticPlaceholder else { return false }
        return integrationBrand == other.integrationBrand
>>>>>>> codex/refactor:apps/milo/milo/Models/MessageModel.swift
    }
}

@MainActor
@Observable
class ConversationService {
    var messages: [Message] = []
<<<<<<< HEAD:apps/modal/modal/Models/MessageModel.swift

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
=======
    var isMessageSendAnimating = false
    var didLatestFirstUserAnimationComplete = false
    var latestUserAnchorMessageId: UUID?
    var pendingFirstAssistantRevealMessageId: UUID?
    private var animatedUserMessageId: UUID?

    private var latestSendWasNewConversation = false
    private let insertionAnimation = Animation.spring(
        response: 0.4,
        dampingFraction: 0.78,
        blendDuration: 0.2
    )

    func beginSendCycle(isNewConversation: Bool) {
        latestSendWasNewConversation = isNewConversation
        isMessageSendAnimating = true
        didLatestFirstUserAnimationComplete = false
        pendingFirstAssistantRevealMessageId = nil
        animatedUserMessageId = nil

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
        isMessageSendAnimating
            && animatedUserMessageId == message.id
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
    func addMessage(_ message: Message) -> Message? {
        guard message.isDisplayable else {
            if Environment.isDebugLoggingEnabled {
                print("[ConversationService] skipping empty message role=\(message.role.rawValue)")
            }
            return nil
        }

        withAnimation(insertionAnimation) {
            messages.append(message)
        }

        if message.role == .user {
            latestUserAnchorMessageId = message.id
            animatedUserMessageId = message.id
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
    func addUserMessage(_ text: String, integrationBrand: MessageIntegrationBrand? = nil) -> Message? {
        let normalizedText = text
            .replacingOccurrences(of: "\u{00A0}", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        print("ConversationService: Adding user message: \"\(normalizedText)\"")
        let message = Message(text: normalizedText, role: .user, integrationBrand: integrationBrand)
        guard let addedMessage = addMessage(message) else {
            return nil
        }
        print(
            "ConversationService: Added user message id=\(addedMessage.id.uuidString), " +
                "count=\(messages.count)"
        )
        return addedMessage
    }

    @discardableResult
    func addAssistantMessage(_ text: String) -> Message? {
        let normalizedText = text
            .replacingOccurrences(of: "\u{00A0}", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        print("ConversationService: Adding assistant message: \"\(normalizedText)\"")
        let message = Message(text: normalizedText, role: .assistant)
        guard let addedMessage = addMessage(message) else {
            return nil
        }
        print(
            "ConversationService: Added assistant message id=\(addedMessage.id.uuidString), " +
                "count=\(messages.count)"
        )
        return addedMessage
>>>>>>> codex/refactor:apps/milo/milo/Models/MessageModel.swift
    }

    func clearMessages() {
        messages.removeAll()
<<<<<<< HEAD:apps/modal/modal/Models/MessageModel.swift
=======
        latestUserAnchorMessageId = nil
        pendingFirstAssistantRevealMessageId = nil
        latestSendWasNewConversation = false
        isMessageSendAnimating = false
        didLatestFirstUserAnimationComplete = false
        animatedUserMessageId = nil
>>>>>>> codex/refactor:apps/milo/milo/Models/MessageModel.swift
    }
}
