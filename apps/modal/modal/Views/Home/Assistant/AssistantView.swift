import AVFoundation
import SwiftUI

struct AssistantView: View {

    @Bindable var authService: AuthService
    @Bindable var viewModel: AssistantViewModel
    @State private var hasPermission = false
    @State private var showPermissionAlert = false
    @State private var scrollProxy: ScrollViewProxy?

    private var messages: [Message] {
        viewModel.conversationService.messages
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
                SpotifyPlaybackCard(track: viewModel.currentSpotifyTrack)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 120)
            }

            CommandFeedbackOverlay(
                message: viewModel.commandFeedback,
                isExecuting: viewModel.isExecutingCommand
            )
        }
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
                "Modal needs microphone access to listen to your voice commands. Please enable it in Settings."
            )
        }
    }

    private var isActiveSession: Bool {
        viewModel.isConnecting || viewModel.isRecording || viewModel.isProcessingTranscription
    }

    private func scrollToLatestMessage(animated: Bool = true) {
        guard let proxy = scrollProxy, !messages.isEmpty else { return }

        let scrollAction = {
            if let latestMessageId = messages.last?.id {
                proxy.scrollTo(latestMessageId, anchor: .bottom)
            }
        }

        if animated {
            withAnimation(.easeOut(duration: 0.4)) {
                scrollAction()
            }
        } else {
            scrollAction()
        }
    }

    private func scrollToShowTranscriptionBubble(animated: Bool = true) {
        guard let proxy = scrollProxy else { return }

        let scrollAction = {
            proxy.scrollTo("bottom-anchor", anchor: .bottom)
        }

        if animated {
            withAnimation(.easeOut(duration: 0.3)) {
                scrollAction()
            }
        } else {
            scrollAction()
        }
    }

    private var chatView: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(spacing: 16) {
                    if messages.isEmpty && !isActiveSession {
                        AssistantGreetingView()
                    }

                    ForEach(messages) { message in
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
                    }

                    Color.clear
                        .frame(height: 1)
                        .id("bottom-anchor")
                }
                .padding(.top, 20)
                .padding(.bottom, 140)
            }
            .onAppear {
                scrollProxy = proxy
            }
            .onChange(of: messages.count) { oldCount, newCount in
                guard newCount > oldCount else { return }

                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                    scrollToLatestMessage(animated: true)
                }
            }
            .onChange(of: isActiveSession) { wasActive, isActive in
                if isActive && !wasActive {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                        scrollToShowTranscriptionBubble(animated: true)
                    }
                }
            }
        }
    }

    private var permissionEmptyStateView: some View {
        VStack(spacing: 32) {
            Spacer()

            VStack(spacing: 24) {
                Image("ModalIcon")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 120, height: 120)
                    .opacity(0.8)

                VStack(spacing: 12) {
                    Text("Modal needs access to your microphone to assist you.")
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

    private let examples = [
        "Play your favorite playlist",
        "Add an event to your calendar",
        "Reply to an email",
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 32) {
            Spacer()

            VStack(alignment: .leading, spacing: 12) {
                Text("Hi, I'm Modi")
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
                currentExampleIndex = 0
                
                // Start cycling through examples after first one appears
                Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { timer in
                    withAnimation {
                        currentExampleIndex = (currentExampleIndex + 1) % examples.count
                    }
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

#Preview {
    AssistantView(authService: AuthService(), viewModel: AssistantViewModel())
}
