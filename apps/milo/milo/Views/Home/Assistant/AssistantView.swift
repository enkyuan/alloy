import Foundation
import SwiftUI

struct AssistantView: View {

    @Bindable var authService: AuthService
    @Bindable var viewModel: AssistantViewModel
    @State private var hasPermission = false
    @State private var showPermissionAlert = false

    var body: some View {
        ZStack(alignment: .bottom) {
            if !hasPermission {
                permissionEmptyStateView
            } else {
                AssistantConversationView(viewModel: viewModel)
            }

            VStack {
                CommandModeIndicator(isActive: viewModel.isInCommandMode)
                    .padding(.top, 60)
                Spacer()
            }

            CommandFeedbackOverlay(
                message: viewModel.commandFeedback,
                isExecuting: viewModel.isExecutingCommand
            )
        }
        .ignoresSafeArea(edges: .top)
        .task {
            await refreshMicrophonePermissionState()
        }
        .microphonePermissionAlert(isPresented: $showPermissionAlert)
        .alert("Connection Issue", isPresented: $viewModel.showError) {
            Button("OK") {}
        } message: {
            Text(viewModel.errorMessage ?? "Something went wrong. Please try again.")
        }
    }

    private var permissionEmptyStateView: some View {
        VStack(spacing: 32) {
            Spacer()

            VStack(spacing: 24) {
                VStack(spacing: 12) {
                    Text("Milo needs access to your microphone to assist you.")
                        .font(.system(size: 17, weight: .regular))
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 40)

                    Button {
                        Task {
                            await requestMicrophonePermission()
                        }
                    } label: {
                        Text("Enable Microphone")
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundColor(.white)
                            .frame(maxWidth: 280)
                            .frame(height: 56)
                            .background(Color.blue)
                            .cornerRadius(28)
                    }
                }
            }

            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    private func refreshMicrophonePermissionState() async {
        hasPermission = MicrophonePermission.isGranted

        if !hasPermission {
            await requestMicrophonePermission()
        }
    }

    private func requestMicrophonePermission() async {
        let granted = await MicrophonePermission.requestIfNeeded()
        await MainActor.run {
            hasPermission = granted
            showPermissionAlert = !granted
        }
    }
}

private struct AssistantConversationView: View {
    @Bindable var viewModel: AssistantViewModel
    @State private var messageListState = ChatMessageListState()

    private let miniPlayerId = "mini-player"
    private let transcriptionBubbleId = "transcription-bubble"
    private static let debugTimestampFormatter = ISO8601DateFormatter()

    private var messages: [Message] {
        viewModel.conversationService.messages
    }

    private var messageIdList: [UUID] {
        messages.map(\.id)
    }

    private var currentPlaybackItem: MusicPlaybackItem? {
        guard let track = viewModel.currentSpotifyTrack else { return nil }
        let duration = track.durationMs > 0 ? TimeInterval(track.durationMs) / 1000 : nil
        return MusicPlaybackItem(
            title: track.name,
            artist: track.artist,
            albumArtUrl: track.albumArtUrl,
            isPlaying: viewModel.isSpotifyPlaying,
            elapsed: nil,
            duration: duration,
            platform: .spotify
        )
    }

    private var isActiveSession: Bool {
        viewModel.isConnecting || viewModel.isRecording || viewModel.isProcessingTranscription
    }

    private var latestUserMessageIndex: Int? {
        messages.lastIndex(where: { $0.isUser })
    }

    private var latestConversationAnchorId: String? {
        if isActiveSession {
            return transcriptionBubbleId
        }
        if let latestUserAnchorId = viewModel.conversationService.latestUserAnchorMessageId {
            return messageItemId(for: latestUserAnchorId)
        }
        if currentPlaybackItem != nil {
            return miniPlayerId
        }
        guard let latestMessage = messages.last else {
            return nil
        }
        return messageItemId(for: latestMessage.id)
    }

    private var messageListBottomInset: CGFloat {
        messageListState.blankSize + messageListState.composerHeight
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: ChatMessageListState.messageSpacing) {
                    if messages.isEmpty && !isActiveSession && currentPlaybackItem == nil {
                        AssistantGreetingView()
                    }

                    if let playbackItem = currentPlaybackItem {
                        let splitIndex = latestUserMessageIndex ?? messages.endIndex
                        let olderMessages = Array(messages[..<splitIndex])
                        let latestRequestAndAfter = Array(messages[splitIndex...])

                        ForEach(Array(olderMessages.enumerated()), id: \.element.id) { offset, message in
                            messageRowView(for: message, index: offset)
                        }

                        miniPlayerView(item: playbackItem)

                        ForEach(Array(latestRequestAndAfter.enumerated()), id: \.element.id) {
                            offset,
                            message in
                            messageRowView(for: message, index: splitIndex + offset)
                        }
                    } else {
                        ForEach(Array(messages.enumerated()), id: \.element.id) { index, message in
                            messageRowView(for: message, index: index)
                        }
                    }

                    if isActiveSession {
                        TranscriptionBubble(
                            isConnecting: viewModel.isConnecting,
                            isRecording: viewModel.isRecording,
                            isProcessing: viewModel.isProcessingTranscription,
                            partialText: viewModel.partialTranscription
                        )
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                        .id(transcriptionBubbleId)
                        .background(
                            GeometryReader { geometry in
                                Color.clear.preference(
                                    key: AssistantTranscriptionHeightPreferenceKey.self,
                                    value: geometry.size.height
                                )
                            }
                        )
                        .onAppear {
                            autoScrollDebug(
                                "transcription-appear text=\"\(shortText(viewModel.partialTranscription))\""
                            )
                        }
                        .onDisappear {
                            autoScrollDebug("transcription-disappear")
                        }
                    }

                    // Keep the latest request/response block floating at the top as heights change.
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
            .onAppear {
                messageListState.setComposerHeight(140)
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
            .onChange(of: isActiveSession) { _, isNowActive in
                if !isNowActive {
                    _ = messageListState.updateTranscriptionHeight(0)
                }
                useMessageBlankSize(reason: "isActiveSession")
                DispatchQueue.main.async {
                    scrollLatestConversation(using: proxy, reason: "isActiveSession")
                }
            }
            .onChange(of: viewModel.partialTranscription) { _, newValue in
                autoScrollDebug(
                    "partial-change text=\"\(shortText(newValue))\" activeSession=\(isActiveSession)"
                )
                useMessageBlankSize(reason: "partialTranscription")
                if isActiveSession {
                    DispatchQueue.main.async {
                        scrollLatestConversation(using: proxy, reason: "partialTranscription")
                    }
                }
            }
            .onChange(of: viewModel.conversationService.didLatestFirstUserAnimationComplete) {
                _, _ in
                useMessageBlankSize(reason: "firstUserAnimationComplete")
            }
            .onChange(of: currentPlaybackItem != nil) { _, hasMiniPlayer in
                if !hasMiniPlayer {
                    _ = messageListState.updateMiniPlayerHeight(0)
                }
                useMessageBlankSize(reason: "miniPlayerVisibility")
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
        }
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
        let includeMiniPlayerInAnchorBlock =
            currentPlaybackItem != nil && viewModel.conversationService.latestUserAnchorMessageId == nil

        messageListState.updateBlankSize(
            messages: messages,
            latestUserAnchorMessageId: viewModel.conversationService.latestUserAnchorMessageId,
            isActiveSession: isActiveSession,
            includeMiniPlayerInAnchorBlock: includeMiniPlayerInAnchorBlock
        )

        autoScrollDebug(
            "blank-size reason=\(reason) blank=\(String(format: "%.1f", messageListState.blankSize)) "
                + "container=\(String(format: "%.1f", messageListState.containerHeight)) "
                + "messages=\(messages.count) activeSession=\(isActiveSession)"
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
                    + "activeSession=\(isActiveSession)"
            )
            return
        }

        autoScrollDebug(
            "pin-start reason=\(reason) anchor=\(anchorId) animated=\(animated) "
                + "activeSession=\(isActiveSession) count=\(messages.count) "
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
    private func messageRowView(for message: Message, index: Int) -> some View {
        let shouldRunFirstUserAnimation = viewModel.conversationService
            .shouldRunFirstUserAnimation(for: message, index: index)
        let shouldFadeFirstAssistant =
            viewModel.conversationService.pendingFirstAssistantRevealMessageId == message.id

        ComposableMessageRow(message: message)
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
        .padding(.horizontal, 16)
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

// MARK: - Message List State

@MainActor
@Observable
private final class ChatMessageListState {
    static let listTopPadding: CGFloat = 4
    static let messageSpacing: CGFloat = 16
    private static let minUpdateDelta: CGFloat = 0.5

    var composerHeight: CGFloat = 140
    var containerHeight: CGFloat = 0
    var blankSize: CGFloat = 0
    var miniPlayerHeight: CGFloat = 0
    var transcriptionHeight: CGFloat = 0

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
        isActiveSession: Bool,
        includeMiniPlayerInAnchorBlock: Bool
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
            let trailingMessages = messages[anchorIndex...]
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

        if isActiveSession, transcriptionHeight > 0 {
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

        // Keep the latest active request/response block anchored at the top.
        let targetBlank = max(0, containerHeight - requestBlockHeight - Self.listTopPadding - 8)
        if abs(blankSize - targetBlank) >= Self.minUpdateDelta {
            blankSize = targetBlank
        }
    }

}

// MARK: - Preferences

private struct AssistantContainerHeightPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct AssistantMiniPlayerHeightPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct AssistantTranscriptionHeightPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct AssistantMessageHeightPreferenceKey: PreferenceKey {
    static var defaultValue: [UUID: CGFloat] = [:]

    static func reduce(value: inout [UUID: CGFloat], nextValue: () -> [UUID: CGFloat]) {
        value.merge(nextValue(), uniquingKeysWith: { _, new in new })
    }
}

// MARK: - Row Composition

private struct ComposableMessageRow: View {
    let message: Message

    @State private var opacity: Double = 0
    @State private var blur: CGFloat = 10
    @State private var offset: CGFloat = 20

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            if message.isUser {
                Spacer()
            }

            VStack(alignment: message.isUser ? .trailing : .leading, spacing: 4) {
                AnimatedText(
                    fadeIn: message.text,
                    opacity: opacity,
                    blur: blur,
                    offset: offset
                )
            }
            .onAppear {
                withAnimation(.easeOut(duration: 0.5)) {
                    opacity = 1.0
                    blur = 0
                    offset = 0
                }
            }

            if !message.isUser {
                Spacer()
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 4)
    }
}

private struct FirstUserSendAnimationModifier: ViewModifier {
    let isEnabled: Bool
    let shouldStartAnimation: Bool
    let itemHeight: CGFloat
    let containerHeight: CGFloat
    let onCompleted: () -> Void

    @State private var translateY: CGFloat = 0
    @State private var opacity: Double = 1
    @State private var hasStarted = false
    @State private var completionTask: Task<Void, Never>?

    func body(content: Content) -> some View {
        content
            .offset(y: isEnabled ? translateY : 0)
            .opacity(isEnabled ? opacity : 1)
            .onAppear {
                if !isEnabled {
                    reset()
                }
                startIfPossible()
            }
            .onChange(of: shouldStartAnimation) { _, _ in
                startIfPossible()
            }
            .onChange(of: itemHeight) { _, _ in
                startIfPossible()
            }
            .onChange(of: isEnabled) { _, enabled in
                if !enabled {
                    reset()
                }
            }
            .onDisappear {
                completionTask?.cancel()
            }
    }

    private func startIfPossible() {
        guard isEnabled, shouldStartAnimation, !hasStarted, itemHeight > 0 else {
            return
        }

        hasStarted = true

        let availableHeight = containerHeight > 0 ? containerHeight : 420
        let startOffset = max(24, (availableHeight * 0.62) - itemHeight)

        translateY = startOffset
        opacity = 0

        withAnimation(.easeOut(duration: 0.2)) {
            opacity = 1
        }

        withAnimation(.spring(response: 0.46, dampingFraction: 0.82, blendDuration: 0.2)) {
            translateY = 0
        }

        completionTask?.cancel()
        completionTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 420_000_000)
            guard !Task.isCancelled else { return }
            onCompleted()
        }
    }

    private func reset() {
        completionTask?.cancel()
        translateY = 0
        opacity = 1
        hasStarted = false
    }
}

private struct FirstAssistantRevealModifier: ViewModifier {
    let isEnabled: Bool
    let didUserMessageAnimate: Bool
    let onReveal: () -> Void

    @State private var revealOpacity: Double = 1
    @State private var hasRevealed = false

    func body(content: Content) -> some View {
        content
            .opacity(isEnabled ? revealOpacity : 1)
            .onAppear {
                if isEnabled {
                    revealOpacity = 0
                } else {
                    revealOpacity = 1
                    hasRevealed = true
                }
                revealIfNeeded()
            }
            .onChange(of: didUserMessageAnimate) { _, _ in
                revealIfNeeded()
            }
            .onChange(of: isEnabled) { _, enabled in
                if !enabled {
                    revealOpacity = 1
                    hasRevealed = true
                } else {
                    revealOpacity = didUserMessageAnimate ? 1 : 0
                    hasRevealed = didUserMessageAnimate
                    revealIfNeeded()
                }
            }
    }

    private func revealIfNeeded() {
        guard isEnabled, didUserMessageAnimate, !hasRevealed else {
            return
        }

        hasRevealed = true
        onReveal()

        withAnimation(.easeOut(duration: 0.35)) {
            revealOpacity = 1
        }
    }
}

// MARK: - Empty State

private struct AssistantGreetingView: View {
    @State private var titleOpacity: Double = 0
    @State private var subtitleOpacity: Double = 0
    @State private var currentExampleIndex: Int = -1
    @State private var exampleTask: Task<Void, Never>?

    private let examples = [
        "Play your favorite playlist",
        "Add an event to your calendar",
        "Reply to an email",
    ]
    private let exampleInitialDelay: TimeInterval = 1.5
    private let exampleDisplayDuration: TimeInterval = 5.0

    var body: some View {
        VStack(alignment: .leading, spacing: 32) {
            Spacer()

            VStack(alignment: .leading, spacing: 12) {
                Text("Hi, I'm Milo")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(.primary)
                    .opacity(titleOpacity)

                Text("What can I do for you? Ask me to...")
                    .font(.system(size: 20, weight: .medium))
                    .foregroundStyle(.secondary)
                    .opacity(subtitleOpacity)
            }

            if currentExampleIndex >= 0 && currentExampleIndex < examples.count {
                AnimatedExampleRow(text: examples[currentExampleIndex])
                    .id(currentExampleIndex)
            }

            Spacer()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 20)
        .frame(minHeight: 400)
        .onAppear {
            withAnimation(.easeOut(duration: 0.8)) {
                titleOpacity = 1.0
            }

            withAnimation(.easeOut(duration: 0.8).delay(0.4)) {
                subtitleOpacity = 1.0
            }

            startExampleCycle()
        }
        .onDisappear {
            exampleTask?.cancel()
            exampleTask = nil
        }
    }

    private func startExampleCycle() {
        exampleTask?.cancel()
        exampleTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(exampleInitialDelay * 1_000_000_000))
            guard !Task.isCancelled else { return }
            withAnimation {
                currentExampleIndex = 0
            }

            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(exampleDisplayDuration * 1_000_000_000))
                guard !Task.isCancelled else { return }
                withAnimation {
                    currentExampleIndex = (currentExampleIndex + 1) % examples.count
                }
            }
        }
    }
}

private struct AnimatedExampleRow: View {
    let text: String
    @State private var opacity: Double = 0
    @State private var blur: CGFloat = 10
    @State private var offset: CGFloat = 20

    var body: some View {
        AnimatedText(
            fadeIn: text,
            opacity: opacity,
            blur: blur,
            offset: offset
        )
        .font(.system(size: 18, weight: .medium))
        .foregroundStyle(.primary)
        .onAppear {
            withAnimation(.easeOut(duration: 0.6)) {
                opacity = 1.0
                blur = 0
                offset = 0
            }
        }
    }
}
