//
//  AssistantView.swift
//  modal
//
//  Main voice assistant interface with reliable auto-scroll behavior
//

import SwiftUI
import AVFoundation

struct AssistantView: View {
    // MARK: - Properties

    @Bindable var authService: AuthenticationService
    @Bindable var viewModel: AssistantViewModel
    @State private var hasPermission = false
    @State private var showPermissionAlert = false
    @State private var scrollProxy: ScrollViewProxy?

    // Computed property to avoid binding issues
    private var messages: [Message] {
        viewModel.conversationService.messages
    }

    // MARK: - Body

    var body: some View {
        ZStack(alignment: .bottom) {
            // Main content
            if !hasPermission {
                permissionEmptyStateView
            } else {
                // Chat interface
                chatView
            }

            // Command mode indicator (top center)
            VStack {
                CommandModeIndicator(isActive: viewModel.isInCommandMode)
                    .padding(.top, 60)
                Spacer()
            }

            // Spotify playback card (bottom, above navigation)
            VStack {
                Spacer()
                SpotifyPlaybackCard(track: viewModel.currentSpotifyTrack)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 120)
            }

            // Command feedback overlay (center)
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
            Button("Cancel", role: .cancel) { }
        } message: {
            Text("Modal needs microphone access to listen to your voice commands. Please enable it in Settings.")
        }
    }

    // MARK: - Computed Properties

    /// True when any part of the session is active
    private var isActiveSession: Bool {
        viewModel.isConnecting || viewModel.isRecording || viewModel.isProcessingTranscription
    }

    // MARK: - Auto-Scroll Helpers

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

    // MARK: - View Components

    private var chatView: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(spacing: 16) {
                    // Empty state when no messages
                    if messages.isEmpty && !isActiveSession {
                        VStack {
                            Spacer()

                            Image("ModalIcon")
                                .resizable()
                                .aspectRatio(contentMode: .fit)
                                .frame(width: 80, height: 80)
                                .foregroundStyle(.secondary.opacity(0.3))

                            Spacer()
                        }
                        .frame(maxWidth: .infinity)
                        .frame(minHeight: 400)
                    }

                    // Message history
                    ForEach(messages) { message in
                        MessageRow(message: message)
                            .id(message.id)
                    }

                    // Transcription bubble
                    if isActiveSession {
                        TranscriptionBubble(
                            isConnecting: viewModel.isConnecting,
                            isRecording: viewModel.isRecording,
                            isProcessing: viewModel.isProcessingTranscription,
                            partialText: viewModel.partialTranscription
                        )
                        .transition(.opacity.combined(with: .move(edge: .bottom)))
                    }

                    // Bottom anchor for scrolling
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
            // Auto-scroll when new messages arrive
            .onChange(of: messages.count) { oldCount, newCount in
                guard newCount > oldCount else { return }

                // Delay to ensure content renders
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                    scrollToLatestMessage(animated: true)
                }
            }
            // Handle session state changes
            .onChange(of: isActiveSession) { wasActive, isActive in
                if isActive && !wasActive {
                    // Session starting - show transcription bubble
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                        scrollToShowTranscriptionBubble(animated: true)
                    }
                }
            }
        }
    }

    // MARK: - Permission Empty State View

    private var permissionEmptyStateView: some View {
        VStack(spacing: 32) {
            Spacer()

            VStack(spacing: 24) {
                // Icon
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

    // MARK: - Actions

    private func checkSetup() async {
        // Check microphone permission
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

// MARK: - Message Row

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
    AssistantView(authService: AuthenticationService(), viewModel: AssistantViewModel())
}

