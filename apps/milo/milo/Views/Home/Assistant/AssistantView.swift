import AVFoundation
import Foundation
import SwiftUI

struct AssistantView: View {

    @Bindable var authService: AuthService
    @Bindable var viewModel: AssistantViewModel
    @State private var hasPermission = false
    @State private var showPermissionAlert = false
    @State private var lastLoggedScrollTopOffset: CGFloat?
    private let miniPlayerId = "mini-player"
    private let scrollTopProbeId = "scroll-top-probe"
    private let scrollCoordinateSpace = "assistant-scroll-space"
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

    var body: some View {
        ZStack(alignment: .bottom) {
            if !hasPermission {
                permissionEmptyStateView
            } else {
                chatView
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
            await checkSetup()
        }
        .alert("Microphone Access Required", isPresented: $showPermissionAlert) {
            Button("Open Settings") {
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    UIApplication.shared.open(url)
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(
                "Milo needs microphone access to listen to your voice commands. Please enable it in Settings."
            )
        }
        .alert("Connection Issue", isPresented: $viewModel.showError) {
            Button("OK") {}
        } message: {
            Text(viewModel.errorMessage ?? "Something went wrong. Please try again.")
        }
    }

    private var isActiveSession: Bool {
        viewModel.isConnecting || viewModel.isRecording || viewModel.isProcessingTranscription
    }

    private func messageItemId(for id: UUID) -> String {
        "message-\(id.uuidString)"
    }

    private func autoScrollDebug(_ message: String) {
        guard Environment.isDebugLoggingEnabled else { return }
        let timestamp = Self.debugTimestampFormatter.string(from: Date())
        print("[AssistantAutoScroll][\(timestamp)] \(message)")
    }

    private func logScrollTopOffsetIfNeeded(_ offset: CGFloat, reason: String) {
        let rounded = (offset * 10).rounded() / 10
        if let lastLoggedScrollTopOffset,
            abs(lastLoggedScrollTopOffset - rounded) < 6
        {
            return
        }
        lastLoggedScrollTopOffset = rounded
        let timestamp = Self.debugTimestampFormatter.string(from: Date())
        print(
            "[AssistantAutoScroll][\(timestamp)] scroll-offset reason=\(reason) topOffset=\(rounded) " +
                "activeSession=\(isActiveSession) anchor=\(latestConversationAnchorId ?? "none")"
        )
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

    private var latestRequestMessageItemId: String? {
        guard let latestUserMessage = messages.last(where: { $0.isUser }) else {
            return nil
        }
        return messageItemId(for: latestUserMessage.id)
    }

    private var latestUserMessageIndex: Int? {
        messages.lastIndex(where: { $0.isUser })
    }

    private var latestConversationAnchorId: String? {
        if currentPlaybackItem != nil {
            return miniPlayerId
        }
        if isActiveSession {
            return transcriptionBubbleId
        }
        if let latestRequestMessageItemId {
            return latestRequestMessageItemId
        }
        guard let latestMessage = messages.last else { return nil }
        return messageItemId(for: latestMessage.id)
    }

    private func pinLatestConversationToTop(
        using proxy: ScrollViewProxy,
        animated: Bool = true,
        reason: String
    ) {
        guard let latestConversationAnchorId else {
            autoScrollDebug(
                "pin-skip reason=\(reason) no-anchor count=\(messages.count) " +
                    "activeSession=\(isActiveSession)"
            )
            return
        }
        autoScrollDebug(
            "pin-start reason=\(reason) anchor=\(latestConversationAnchorId) " +
                "animated=\(animated) activeSession=\(isActiveSession) " +
                "count=\(messages.count) tail=\(debugMessagesSummary())"
        )

        let scrollAction = {
            proxy.scrollTo(latestConversationAnchorId, anchor: .top)
        }

        if animated {
            withAnimation(.spring(response: 0.4, dampingFraction: 0.78)) {
                scrollAction()
            }
        } else {
            scrollAction()
        }

        autoScrollDebug(
            "pin-complete reason=\(reason) anchor=\(latestConversationAnchorId)"
        )
    }

    @ViewBuilder
    private func messageRowView(for message: Message) -> some View {
        MessageRow(message: message)
            .id(messageItemId(for: message.id))
            .transition(.move(edge: .bottom).combined(with: .opacity))
            .onAppear {
                autoScrollDebug(
                    "row-appear id=\(messageItemId(for: message.id)) " +
                        "role=\(message.isUser ? "user" : "assistant") " +
                        "text=\"\(shortText(message.text))\""
                )
            }
            .onDisappear {
                autoScrollDebug(
                    "row-disappear id=\(messageItemId(for: message.id)) " +
                        "role=\(message.isUser ? "user" : "assistant")"
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
    }

    @ViewBuilder private var chatView: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 16) {
                    Color.clear
                        .frame(height: 1)
                        .id(scrollTopProbeId)
                        .background(
                            GeometryReader { geometry in
                                Color.clear.preference(
                                    key: AssistantScrollTopOffsetPreferenceKey.self,
                                    value: geometry.frame(in: .named(scrollCoordinateSpace)).minY
                                )
                            }
                        )

                    if messages.isEmpty && !isActiveSession && currentPlaybackItem == nil {
                        AssistantGreetingView()
                    }

                    if let playbackItem = currentPlaybackItem {
                        let splitIndex = latestUserMessageIndex ?? messages.endIndex
                        let olderMessages = Array(messages[..<splitIndex])
                        let latestRequestAndAfter = Array(messages[splitIndex...])

                        ForEach(olderMessages) { message in
                            messageRowView(for: message)
                        }

                        miniPlayerView(item: playbackItem)

                        ForEach(latestRequestAndAfter) { message in
                            messageRowView(for: message)
                        }
                    } else {
                        ForEach(messages) { message in
                            messageRowView(for: message)
                        }
                    }

                    // Keep timeline order chronological. While recording, the live request
                    // bubble is the newest item and should sit after prior history.
                    if isActiveSession {
                        TranscriptionBubble(
                            isConnecting: viewModel.isConnecting,
                            isRecording: viewModel.isRecording,
                            isProcessing: viewModel.isProcessingTranscription,
                            partialText: viewModel.partialTranscription
                        )
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                        .id(transcriptionBubbleId)
                        .onAppear {
                            autoScrollDebug(
                                "transcription-appear text=\"\(shortText(viewModel.partialTranscription))\""
                            )
                        }
                        .onDisappear {
                            autoScrollDebug("transcription-disappear")
                        }
                    }
                }
                .padding(.top, 4)
                .padding(.bottom, 140)
            }
            .coordinateSpace(name: scrollCoordinateSpace)
            .onAppear {
                DispatchQueue.main.async {
                    pinLatestConversationToTop(
                        using: proxy,
                        animated: false,
                        reason: "onAppear"
                    )
                }
            }
            .onChange(of: messageIdList) { _, _ in
                autoScrollDebug(
                    "message-change count=\(messages.count) activeSession=\(isActiveSession) " +
                        "tail=\(debugMessagesSummary())"
                )
                DispatchQueue.main.async {
                    pinLatestConversationToTop(
                        using: proxy,
                        reason: "messageIdList"
                    )
                }
            }
            .onChange(of: isActiveSession) { _, _ in
                autoScrollDebug(
                    "session-change activeSession=\(isActiveSession) " +
                        "partial=\"\(shortText(viewModel.partialTranscription))\" " +
                        "tail=\(debugMessagesSummary())"
                )
                DispatchQueue.main.async {
                    pinLatestConversationToTop(
                        using: proxy,
                        reason: "isActiveSession"
                    )
                }
            }
            .onChange(of: viewModel.partialTranscription) { _, newValue in
                autoScrollDebug(
                    "partial-change text=\"\(shortText(newValue))\" activeSession=\(isActiveSession)"
                )
            }
            .onPreferenceChange(AssistantScrollTopOffsetPreferenceKey.self) { topOffset in
                logScrollTopOffsetIfNeeded(topOffset, reason: "layout")
            }
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
                        requestMicrophonePermission()
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

    private func checkSetup() async {
        hasPermission = AVAudioApplication.shared.recordPermission == .granted

        if !hasPermission && AVAudioApplication.shared.recordPermission == .undetermined {
            requestMicrophonePermission()
        }
    }

    private func requestMicrophonePermission() {
        AVAudioApplication.requestRecordPermission { granted in
            DispatchQueue.main.async {
                hasPermission = granted

                if !granted {
                    showPermissionAlert = true
                }
            }
        }
    }
}

private struct AssistantScrollTopOffsetPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

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

            // Show first example after subtitle finishes fading in
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                startExampleCycle()
            }
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

private struct MessageRow: View {
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
