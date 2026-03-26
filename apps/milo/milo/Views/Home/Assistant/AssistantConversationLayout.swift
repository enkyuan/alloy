import Foundation
import SwiftUI

@MainActor
@Observable
final class ChatMessageListState {
    static let listTopPadding: CGFloat = 4
    static let messageSpacing: CGFloat = 12
    private static let minUpdateDelta: CGFloat = 0.5

    var composerHeight: CGFloat = 140
    var containerHeight: CGFloat = 0
    var blankSize: CGFloat = 0
    var miniPlayerHeight: CGFloat = 0
    var transcriptionHeight: CGFloat = 0
    var recordingOverlayHeight: CGFloat = 0

    private(set) var messageHeights: [UUID: CGFloat] = [:]

    func height(for messageId: UUID) -> CGFloat {
        messageHeights[messageId] ?? 0
    }

    @discardableResult
    func setComposerHeight(_ value: CGFloat) -> Bool {
        let normalized = max(0, value)
        if abs(composerHeight - normalized) < Self.minUpdateDelta {
            return false
        }
        composerHeight = normalized
        return true
    }

    @discardableResult
    func updateContainerHeight(_ value: CGFloat) -> Bool {
        let normalized = max(0, value)
        if abs(containerHeight - normalized) < Self.minUpdateDelta {
            return false
        }
        containerHeight = normalized
        return true
    }

    @discardableResult
    func updateMiniPlayerHeight(_ value: CGFloat) -> Bool {
        let normalized = max(0, value)
        if abs(miniPlayerHeight - normalized) < Self.minUpdateDelta {
            return false
        }
        miniPlayerHeight = normalized
        return true
    }

    @discardableResult
    func updateTranscriptionHeight(_ value: CGFloat) -> Bool {
        let normalized = max(0, value)
        if abs(transcriptionHeight - normalized) < Self.minUpdateDelta {
            return false
        }
        transcriptionHeight = normalized
        return true
    }

    @discardableResult
    func updateRecordingOverlayHeight(_ value: CGFloat) -> Bool {
        let normalized = max(0, value)
        if abs(recordingOverlayHeight - normalized) < Self.minUpdateDelta {
            return false
        }
        recordingOverlayHeight = normalized
        return true
    }

    @discardableResult
    func updateMessageHeights(_ newHeights: [UUID: CGFloat]) -> Bool {
        var didChange = false
        for (id, value) in newHeights {
            let normalized = max(0, value)
            let oldValue = messageHeights[id] ?? -1
            if abs(oldValue - normalized) >= Self.minUpdateDelta {
                messageHeights[id] = normalized
                didChange = true
            }
        }
        return didChange
    }

    @discardableResult
    func pruneMessageHeights(keeping ids: Set<UUID>) -> Bool {
        let previousCount = messageHeights.count
        messageHeights = messageHeights.filter { ids.contains($0.key) }
        return previousCount != messageHeights.count
    }

    func updateBlankSize(
        messages: [Message],
        latestUserAnchorMessageId: UUID?,
        showsProcessingBubble: Bool,
        includeMiniPlayerInAnchorBlock: Bool,
        includeFloatingRecordingOverlayInAnchorBlock: Bool
    ) {
        guard containerHeight > 0 else {
            blankSize = 0
            return
        }

        let anchorIndex: Int?
        if let latestUserAnchorMessageId,
            let locatedIndex = messages.firstIndex(where: { $0.id == latestUserAnchorMessageId })
        {
            anchorIndex = locatedIndex
        } else if !messages.isEmpty {
            anchorIndex = messages.count - 1
        } else {
            anchorIndex = nil
        }

        var requestBlockHeight: CGFloat = 0

        if let anchorIndex {
            let anchorMessage = messages[anchorIndex]
            var stackStartIndex = anchorIndex

            while stackStartIndex > messages.startIndex {
                let previousIndex = messages.index(before: stackStartIndex)
                guard messages[previousIndex].canStack(with: anchorMessage) else {
                    break
                }
                stackStartIndex = previousIndex
            }

            let trailingMessages = messages[stackStartIndex...]
            var measuredRows = 0

            for message in trailingMessages {
                guard let rowHeight = messageHeights[message.id], rowHeight > 0 else {
                    continue
                }
                requestBlockHeight += rowHeight
                measuredRows += 1
            }

            if measuredRows > 1 {
                requestBlockHeight += CGFloat(measuredRows - 1) * Self.messageSpacing
            }
        }

        if showsProcessingBubble, transcriptionHeight > 0 {
            if requestBlockHeight > 0 {
                requestBlockHeight += Self.messageSpacing
            }
            requestBlockHeight += transcriptionHeight
        }

        if includeMiniPlayerInAnchorBlock, miniPlayerHeight > 0 {
            if requestBlockHeight > 0 {
                requestBlockHeight += Self.messageSpacing
            }
            requestBlockHeight += miniPlayerHeight
        }

        if includeFloatingRecordingOverlayInAnchorBlock, recordingOverlayHeight > 0 {
            if requestBlockHeight > 0 {
                requestBlockHeight += Self.messageSpacing
            }
            requestBlockHeight += recordingOverlayHeight
        }

        let targetBlank = max(0, containerHeight - requestBlockHeight - Self.listTopPadding - 8)
        if abs(blankSize - targetBlank) >= Self.minUpdateDelta {
            blankSize = targetBlank
        }
    }
}

struct AssistantContainerHeightPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

struct AssistantMiniPlayerHeightPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

struct AssistantTranscriptionHeightPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

struct AssistantMessageHeightPreferenceKey: PreferenceKey {
    static var defaultValue: [UUID: CGFloat] = [:]

    static func reduce(value: inout [UUID: CGFloat], nextValue: () -> [UUID: CGFloat]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}

struct AssistantRecordingOverlayHeightPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}
