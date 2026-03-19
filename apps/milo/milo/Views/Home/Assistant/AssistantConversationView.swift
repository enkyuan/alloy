import Foundation
import SwiftUI

struct AssistantConversationView: View {
    @Bindable var viewModel: AssistantViewModel
    @State private var messageListState = ChatMessageListState()
    @Namespace private var bottomAccessoryNamespace

    private let miniPlayerId = "mini-player"
    private let processingBubbleId = "processing-bubble"
    private static let debugTimestampFormatter = ISO8601DateFormatter()

    private var messages: [Message] {
        viewModel.conversationService.messages
    }

    private var messageIdList: [UUID] {
        messages.map(\.id)
    }

    private var currentPlaybackItem: MusicPlaybackItem? {
        guard let track = viewModel.currentSpotifyTrack else { return nil }
        let duration =
            viewModel.currentSpotifyDuration
            ?? (track.durationMs > 0 ? TimeInterval(track.durationMs) / 1000 : nil)
        return MusicPlaybackItem(
            title: track.name,
            artist: track.artist,
            albumArtUrl: track.albumArtUrl,
            isPlaying: viewModel.isSpotifyPlaying,
            elapsed: viewModel.currentSpotifyElapsed,
            duration: duration,
            platform: .spotify
        )
    }

    private var showsRecordingOverlay: Bool {
        viewModel.isRecording || viewModel.isProcessingTranscription
    }

    private var showsBottomRecordingBubble: Bool {
        currentPlaybackItem != nil && showsRecordingOverlay
    }

    private var showsProcessingBubble: Bool {
        viewModel.isExecutingCommand
    }

    private var latestUserMessageIndex: Int? {
        messages.lastIndex(where: { $0.isUser })
    }

    private var latestUserStackStartIndex: Int? {
        guard let latestUserMessageIndex else { return nil }

        var startIndex = latestUserMessageIndex
        let anchorMessage = messages[latestUserMessageIndex]

        while startIndex > messages.startIndex {
            let previousIndex = messages.index(before: startIndex)
            let previousMessage = messages[previousIndex]
            guard previousMessage.canStack(with: anchorMessage) else {
                break
            }
            startIndex = previousIndex
        }

        return startIndex
    }

    private var latestConversationAnchorId: String? {
        if showsProcessingBubble {
            return processingBubbleId
        }
        if let latestUserAnchorId = viewModel.conversationService.latestUserAnchorMessageId {
            return messageItemId(for: latestUserAnchorId)
        }
        guard let latestMessage = messages.last else {
            return nil
        }
        return messageItemId(for: latestMessage.id)
    }

    private var effectiveMiniPlayerHeight: CGFloat {
        max(messageListState.miniPlayerHeight, Self.miniPlayerMinHeight)
    }

    private var messageListBottomInset: CGFloat {
        let miniPlayerInset = currentPlaybackItem == nil
            ? 0
            : effectiveMiniPlayerHeight + Self.miniPlayerBottomPadding + Self.miniPlayerSpacing
        let recordingOverlayInset = showsRecordingOverlay && !showsBottomRecordingBubble
            ? max(
                messageListState.recordingOverlayHeight + Self.recordingOverlaySpacing,
                Self.recordingOverlayMinimumReservedInset
            )
            : 0
        return messageListState.blankSize
            + messageListState.composerHeight
            + miniPlayerInset
            + recordingOverlayInset
    }

    private var recordingOverlayBottomPadding: CGFloat {
        if currentPlaybackItem != nil {
            return Self.miniPlayerBottomPadding + effectiveMiniPlayerHeight + 20
        }
        return 60
    }

    private var displayedMessageGroups: [MessageRowGroup] {
        makeMessageRowGroups(from: messages, startIndexOffset: 0)
    }

    private var latestDisplayedMessageGroup: MessageRowGroup? {
        displayedMessageGroups.last
    }

    private var processingBubbleTopPadding: CGFloat {
        guard latestDisplayedMessageGroup?.isStacked == true else { return 0 }
        return Self.stackedAccessoryTopPadding
    }

    var body: some View {
        ScrollViewReader { proxy in
            ZStack(alignment: .bottom) {
                ScrollView {
                    LazyVStack(spacing: ChatMessageListState.messageSpacing) {
                        if messages.isEmpty && !showsProcessingBubble && currentPlaybackItem == nil {
                            AssistantGreetingView()
                        }

                        if currentPlaybackItem != nil {
                            let splitIndex = latestUserStackStartIndex ?? messages.endIndex
                            let olderMessages = Array(messages[..<splitIndex])
                            let latestRequestAndAfter = Array(messages[splitIndex...])
                            let olderMessageGroups = makeMessageRowGroups(
                                from: olderMessages,
                                startIndexOffset: 0
                            )
                            let latestMessageGroups = makeMessageRowGroups(
                                from: latestRequestAndAfter,
                                startIndexOffset: splitIndex
                            )

                            ForEach(olderMessageGroups) { group in
                                messageRowView(for: group)
                            }

                            ForEach(latestMessageGroups) { group in
                                messageRowView(for: group)
                            }
                        } else {
                            ForEach(displayedMessageGroups) { group in
                                messageRowView(for: group)
                            }
                        }

                        if showsProcessingBubble {
                            processingBubble
                        }

                        Color.clear
                            .frame(height: messageListBottomInset)
                    }
                    .padding(.top, ChatMessageListState.listTopPadding)
                }
                .background(
                    GeometryReader { geometry in
                        Color.clear.preference(
                            key: AssistantContainerHeightPreferenceKey.self,
                            value: geometry.size.height
                        )
                    }
                )

                if let playbackItem = currentPlaybackItem {
                    bottomAccessoryView(item: playbackItem)
                        .padding(.horizontal, 16)
                        .padding(.bottom, Self.miniPlayerBottomPadding)
                }

                if showsRecordingOverlay && !showsBottomRecordingBubble {
                    recordingOverlayBubble
                }
            }
            .onAppear {
                messageListState.setComposerHeight(140)
                if currentPlaybackItem != nil {
                    _ = messageListState.updateMiniPlayerHeight(Self.miniPlayerMinHeight)
                }
                useMessageBlankSize(reason: "onAppear")
                DispatchQueue.main.async {
                    scrollLatestConversation(using: proxy, animated: false, reason: "onAppear")
                }
            }
            .onChange(of: messageIdList) { _, _ in
                _ = messageListState.pruneMessageHeights(keeping: Set(messageIdList))
                useMessageBlankSize(reason: "messageIdList")
                DispatchQueue.main.async {
                    scrollLatestConversation(using: proxy, reason: "messageIdList")
                }
            }
            .onChange(of: showsProcessingBubble) { _, isNowVisible in
                if !isNowVisible {
                    _ = messageListState.updateTranscriptionHeight(0)
                }
                useMessageBlankSize(reason: "showsProcessingBubble")
                DispatchQueue.main.async {
                    scrollLatestConversation(using: proxy, reason: "showsProcessingBubble")
                }
            }
            .onChange(of: showsRecordingOverlay) { _, isNowVisible in
                if !isNowVisible {
                    _ = messageListState.updateRecordingOverlayHeight(0)
                }
                useMessageBlankSize(reason: "showsRecordingOverlay")
                DispatchQueue.main.async {
                    scrollLatestConversation(using: proxy, reason: "showsRecordingOverlay")
                }
            }
            .onChange(of: viewModel.partialTranscription) { _, newValue in
                autoScrollDebug(
                    "partial-change text=\"\(shortText(newValue))\" recordingOverlay=\(showsRecordingOverlay)"
                )
            }
            .onChange(of: viewModel.conversationService.didLatestFirstUserAnimationComplete) { _, _ in
                useMessageBlankSize(reason: "firstUserAnimationComplete")
            }
            .onChange(of: currentPlaybackItem != nil) { _, hasMiniPlayer in
                if hasMiniPlayer {
                    _ = messageListState.updateMiniPlayerHeight(Self.miniPlayerMinHeight)
                } else {
                    _ = messageListState.updateMiniPlayerHeight(0)
                }
                useMessageBlankSize(reason: "miniPlayerVisibility")
            }
            .onChange(of: showsBottomRecordingBubble) { _, _ in
                useMessageBlankSize(reason: "bottomAccessoryMode")
            }
            .onPreferenceChange(AssistantContainerHeightPreferenceKey.self) { height in
                if messageListState.updateContainerHeight(height) {
                    useMessageBlankSize(reason: "containerHeight")
                }
            }
            .onPreferenceChange(AssistantMessageHeightPreferenceKey.self) { heights in
                if messageListState.updateMessageHeights(heights) {
                    useMessageBlankSize(reason: "messageHeights")
                }
            }
            .onPreferenceChange(AssistantMiniPlayerHeightPreferenceKey.self) { height in
                if messageListState.updateMiniPlayerHeight(height) {
                    useMessageBlankSize(reason: "miniPlayerHeight")
                }
            }
            .onPreferenceChange(AssistantTranscriptionHeightPreferenceKey.self) { height in
                if messageListState.updateTranscriptionHeight(height) {
                    useMessageBlankSize(reason: "transcriptionHeight")
                }
            }
            .onPreferenceChange(AssistantRecordingOverlayHeightPreferenceKey.self) { height in
                if messageListState.updateRecordingOverlayHeight(height) {
                    useMessageBlankSize(reason: "recordingOverlayHeight")
                }
            }
            .animation(.spring(response: 0.34, dampingFraction: 0.82), value: showsRecordingOverlay)
        }
    }

    private var processingBubble: some View {
        TranscriptionBubble(mode: .processing)
            .transition(.move(edge: .bottom).combined(with: .opacity))
            .id(processingBubbleId)
            .background(
                GeometryReader { geometry in
                    Color.clear.preference(
                        key: AssistantTranscriptionHeightPreferenceKey.self,
                        value: geometry.size.height
                    )
                }
            )
            .padding(.horizontal, 16)
            .padding(.top, processingBubbleTopPadding)
            .onAppear {
                autoScrollDebug("processing-bubble-appear")
            }
            .onDisappear {
                autoScrollDebug("processing-bubble-disappear")
            }
    }

    private var recordingOverlayBubble: some View {
        TranscriptionBubble(
            mode: .recording,
            audioLevel: viewModel.audioLevel,
            audioEnvelope: viewModel.audioEnvelope
        )
        .background(
            GeometryReader { geometry in
                Color.clear.preference(
                    key: AssistantRecordingOverlayHeightPreferenceKey.self,
                    value: geometry.size.height
                )
            }
        )
        .padding(.horizontal, 16)
        .padding(.bottom, recordingOverlayBottomPadding)
        .transition(.recordingOverlayEntrance)
        .allowsHitTesting(false)
    }

    private var bottomSlotRecordingBubble: some View {
        TranscriptionBubble(
            mode: .recording,
            audioLevel: viewModel.audioLevel,
            audioEnvelope: viewModel.audioEnvelope
        )
        .matchedGeometryEffect(id: miniPlayerId, in: bottomAccessoryNamespace)
        .background(
            GeometryReader { geometry in
                Color.clear.preference(
                    key: AssistantMiniPlayerHeightPreferenceKey.self,
                    value: geometry.size.height
                )
            }
        )
        .transition(.recordingOverlayEntrance)
        .allowsHitTesting(false)
    }

    private static let miniPlayerBottomPadding: CGFloat = 60
    private static let miniPlayerSpacing: CGFloat = 28
    private static let miniPlayerMinHeight: CGFloat = 60
    private static let recordingOverlaySpacing: CGFloat = 20
    private static let recordingOverlayMinimumReservedInset: CGFloat = 92
    private static let stackedAccessoryTopPadding: CGFloat = 10

    private func makeMessageRowGroups(from sourceMessages: [Message], startIndexOffset: Int)
        -> [MessageRowGroup]
    {
        let displayableMessages = sourceMessages.filter(\.isDisplayable)
        var groups: [MessageRowGroup] = []
        var currentIndex = 0
        var previousGroup: MessageRowGroup?

        while currentIndex < displayableMessages.count {
            let message = displayableMessages[currentIndex]
            var groupedMessages = [message]
            var lookaheadIndex = currentIndex + 1

            while lookaheadIndex < displayableMessages.count && groupedMessages.count < 3 {
                let nextMessage = displayableMessages[lookaheadIndex]
                guard message.canStack(with: nextMessage) else {
                    break
                }
                groupedMessages.append(nextMessage)
                lookaheadIndex += 1
            }

            let anchorMessage = groupedMessages.last ?? message
            let group = MessageRowGroup(
                anchorMessage: anchorMessage,
                groupedMessages: groupedMessages,
                sourceIndex: startIndexOffset + currentIndex,
                baseTiltDegrees: baseTiltDegrees(
                    for: anchorMessage,
                    previousGroup: previousGroup
                ),
                topSpacingAdjustment: topSpacingAdjustment(
                    previousGroup: previousGroup
                )
            )
            groups.append(group)
            previousGroup = group
            currentIndex += groupedMessages.count
        }

        return groups
    }

    private func baseTiltDegrees(for message: Message, previousGroup: MessageRowGroup?) -> Double {
        guard let previousGroup else {
            return defaultTiltDegrees(for: message)
        }

        let direction = previousGroup.exposedTiltDegrees >= 0 ? -1.0 : 1.0
        let magnitude = previousGroup.isStacked ? 5.0 : abs(defaultTiltDegrees(for: message))
        return direction * magnitude
    }

    private func defaultTiltDegrees(for message: Message) -> Double {
        message.isUser ? 3 : -3
    }

    private func topSpacingAdjustment(previousGroup: MessageRowGroup?) -> CGFloat {
        guard let previousGroup, previousGroup.isStacked else {
            return 0
        }
        return 10
    }

    private func messageItemId(for id: UUID) -> String {
        "message-\(id.uuidString)"
    }

    private func autoScrollDebug(_ message: String) {
        guard Environment.isDebugLoggingEnabled else { return }
        let timestamp = Self.debugTimestampFormatter.string(from: Date())
        print("[AssistantAutoScroll][\(timestamp)] \(message)")
    }

    private func shortText(_ text: String, maxLength: Int = 42) -> String {
        let compact = text.replacingOccurrences(of: "\n", with: " ")
        if compact.count <= maxLength {
            return compact
        }
        return String(compact.prefix(maxLength)) + "..."
    }

    private func debugMessagesSummary(limit: Int = 5) -> String {
        if messages.isEmpty {
            return "[]"
        }
        let items = messages.suffix(limit).map { message in
            let role = message.isUser ? "U" : "A"
            let shortId = String(message.id.uuidString.prefix(8))
            return "\(role):\(shortId)"
        }
        return "[" + items.joined(separator: ", ") + "]"
    }

    private func useMessageBlankSize(reason: String) {
        messageListState.updateBlankSize(
            messages: messages,
            latestUserAnchorMessageId: viewModel.conversationService.latestUserAnchorMessageId,
            showsProcessingBubble: showsProcessingBubble,
            includeMiniPlayerInAnchorBlock: false,
            includeFloatingRecordingOverlayInAnchorBlock: showsRecordingOverlay && !showsBottomRecordingBubble
        )

        autoScrollDebug(
            "blank-size reason=\(reason) blank=\(String(format: "%.1f", messageListState.blankSize)) "
                + "container=\(String(format: "%.1f", messageListState.containerHeight)) "
                + "messages=\(messages.count) processing=\(showsProcessingBubble)"
        )
    }

    private func scrollLatestConversation(
        using proxy: ScrollViewProxy,
        animated: Bool = true,
        reason: String
    ) {
        guard let anchorId = latestConversationAnchorId else {
            autoScrollDebug(
                "pin-skip reason=\(reason) no-anchor count=\(messages.count) "
                    + "processing=\(showsProcessingBubble)"
            )
            return
        }

        autoScrollDebug(
            "pin-start reason=\(reason) anchor=\(anchorId) animated=\(animated) "
                + "processing=\(showsProcessingBubble) count=\(messages.count) "
                + "tail=\(debugMessagesSummary())"
        )

        let scrollAction = {
            proxy.scrollTo(anchorId, anchor: .top)
        }

        if animated {
            withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
                scrollAction()
            }
        } else {
            scrollAction()
        }

        autoScrollDebug("pin-complete reason=\(reason) anchor=\(anchorId)")
    }

    @ViewBuilder
    private func messageRowView(for group: MessageRowGroup) -> some View {
        let message = group.anchorMessage
        let shouldRunFirstUserAnimation = viewModel.conversationService
            .shouldRunFirstUserAnimation(for: message, index: group.sourceIndex)
        let shouldFadeFirstAssistant =
            viewModel.conversationService.pendingFirstAssistantRevealMessageId == message.id

        ComposableMessageRow(group: group)
            .environment(\.assistantMessageExpandAction, AssistantMessageExpandAction(handler: { text in
                viewModel.expandedMessageText = text
            }))
            .modifier(
                FirstUserSendAnimationModifier(
                    isEnabled: shouldRunFirstUserAnimation,
                    shouldStartAnimation: viewModel.conversationService.isMessageSendAnimating,
                    itemHeight: messageListState.height(for: message.id),
                    containerHeight: messageListState.containerHeight,
                    onCompleted: {
                        viewModel.conversationService.completeFirstUserSendAnimationIfNeeded()
                    }
                )
            )
            .modifier(
                FirstAssistantRevealModifier(
                    isEnabled: shouldFadeFirstAssistant,
                    didUserMessageAnimate: viewModel.conversationService
                        .didLatestFirstUserAnimationComplete,
                    onReveal: {
                        _ = viewModel.conversationService.consumeFirstAssistantRevealIfNeeded(
                            for: message.id)
                    }
                )
            )
            .id(messageItemId(for: message.id))
            .background(
                GeometryReader { geometry in
                    Color.clear.preference(
                        key: AssistantMessageHeightPreferenceKey.self,
                        value: [message.id: geometry.size.height]
                    )
                }
            )
            .transition(.move(edge: .bottom).combined(with: .opacity))
            .onAppear {
                autoScrollDebug(
                    "row-appear id=\(messageItemId(for: message.id)) "
                        + "role=\(message.role.rawValue) text=\"\(shortText(message.text))\""
                )
            }
            .onDisappear {
                autoScrollDebug(
                    "row-disappear id=\(messageItemId(for: message.id)) "
                        + "role=\(message.role.rawValue)"
                )
            }
    }

    @ViewBuilder
    private func bottomAccessoryView(item: MusicPlaybackItem) -> some View {
        ZStack {
            if showsBottomRecordingBubble {
                bottomSlotRecordingBubble
            } else {
                miniPlayerView(item: item)
                    .matchedGeometryEffect(id: miniPlayerId, in: bottomAccessoryNamespace)
            }
        }
        .animation(.spring(response: 0.34, dampingFraction: 0.82), value: showsBottomRecordingBubble)
    }

    @ViewBuilder
    private func miniPlayerView(item: MusicPlaybackItem) -> some View {
        MiniPlayer(
            item: item,
            onPlayPause: {
                viewModel.handleMiniPlayerPlayPause()
            },
            onNext: {
                viewModel.handleMiniPlayerNext()
            },
            onPrevious: {
                viewModel.handleMiniPlayerPrevious()
            },
            onRoute: {
                viewModel.openSpotifyApp()
            }
        )
        .id(miniPlayerId)
        .background(
            GeometryReader { geometry in
                Color.clear.preference(
                    key: AssistantMiniPlayerHeightPreferenceKey.self,
                    value: geometry.size.height
                )
            }
        )
    }
}
