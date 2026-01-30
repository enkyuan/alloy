import AVFoundation
import SwiftUI

struct AssistantView: View {

    @Bindable var authService: AuthService
    @Bindable var viewModel: AssistantViewModel
    @State private var hasPermission = false
    @State private var showPermissionAlert = false
    @State private var lastScrolledPairCount = 0
    @State private var scrollViewHeight: CGFloat = 0

    private var messages: [Message] {
        viewModel.conversationService.messages
    }

    private var lastUserMessageId: UUID? {
        messages.last(where: { $0.isUser })?.id
    }

    private var currentPlaybackItem: MusicPlaybackItem? {
        guard let track = viewModel.currentSpotifyTrack else { return nil }
        return MusicPlaybackItem(
            title: track.name,
            artist: track.artist,
            albumArtUrl: track.albumArtUrl,
            isPlaying: true,
            elapsed: nil,
            duration: TimeInterval(track.durationMs) / 1000,
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

            VStack {
                Spacer()
                MusicMiniPlayer(
                    item: currentPlaybackItem,
                    onPlayPause: {
                        SpotifyAppService.shared.openSpotifyAndReturnToMilo {
                            SpotifyAppService.shared.resume()
                        }
                    },
                    onNext: {
                        SpotifyAppService.shared.openSpotifyAndReturnToMilo {
                            SpotifyAppService.shared.skipNext()
                        }
                    },
                    onPrevious: {
                        SpotifyAppService.shared.openSpotifyAndReturnToMilo {
                            SpotifyAppService.shared.skipPrevious()
                        }
                    },
                    onRoute: {
                        SpotifyAppService.shared.openSpotify()
                    }
                )
                .padding(.horizontal, 16)
                .padding(.bottom, 120)
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

    private func userAnchorId(for id: UUID) -> String {
        "user-anchor-\(id.uuidString)"
    }

    private func scrollToLatestPair(using proxy: ScrollViewProxy) {
        guard let latestUserMessageId = lastUserMessageId else { return }
        withAnimation(.spring(response: 0.45, dampingFraction: 0.9, blendDuration: 0.2)) {
            proxy.scrollTo(userAnchorId(for: latestUserMessageId), anchor: .top)
        }
    }

    @ViewBuilder private var chatView: some View {
        GeometryReader { geo in
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(spacing: 16) {
                        Color.clear
                            .frame(height: 1)
                            .id("top-anchor")

                        if messages.isEmpty && !isActiveSession {
                            AssistantGreetingView()
                        }

                        ForEach(messages) { message in
                            if message.isUser {
                                Color.clear
                                    .frame(height: 1)
                                    .id(userAnchorId(for: message.id))
                            }
                            MessageRow(message: message)
                                .id(message.id)
                        }

                        if isActiveSession {
                            TranscriptionBubble(
                                isConnecting: viewModel.isConnecting,
                                isRecording: viewModel.isRecording,
                                isProcessing: viewModel.isProcessingTranscription,
                                partialText: viewModel.partialTranscription
                            )
                            .transition(.opacity.combined(with: .move(edge: .bottom)))
                            .id("transcription-bubble")
                        }

                        Color.clear
                            .frame(height: scrollViewHeight)
                            .id("bottom-spacer")
                    }
                    .padding(.top, 4)
                    .padding(.bottom, 140)
                }
                .onAppear {
                    scrollViewHeight = geo.size.height
                }
                .onChange(of: geo.size.height) { _, newHeight in
                    scrollViewHeight = newHeight
                }
                .onChange(of: messages.count) { _, newCount in
                    guard newCount > 0 else {
                        lastScrolledPairCount = 0
                        return
                    }
                    let pairCount = newCount / 2
                    guard pairCount > lastScrolledPairCount else { return }
                    lastScrolledPairCount = pairCount
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.01) {
                        scrollToLatestPair(using: proxy)
                    }
                }
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
