//
//  AssistantView.swift
//  modal
//
//  Main voice assistant interface (patched - single-file replacement)
//
//  This version captures ScrollViewProxy early, centralizes scrolling helpers,
//  and adds reliable, layout-aware triggers to reset the transcription bubble
//  to the top of the screen when the content becomes full or transcription
//  state changes. Paste this file over your existing AssistantView.swift.
//

import SwiftUI
import AVFoundation

struct AssistantView: View {
    // MARK: - Properties

    @Bindable var authService: AuthenticationService
    @Bindable var viewModel: AssistantViewModel
    @State private var hasPermission = false
    @State private var showPermissionAlert = false
    @State private var contentHeight: CGFloat = 0
    @State private var visibleHeight: CGFloat = 0

    // Scroll proxy & pending behavior
    @State private var scrollProxy: ScrollViewProxy? = nil
    @State private var pendingScrollToTop: Bool = false

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

            // Device status indicator (top right)
            VStack {
                HStack {
                    Spacer()
                    DeviceStatusIndicator(
                        device: viewModel.currentDevice,
                        onTap: {
                            viewModel.toggleDeviceSelector()
                        }
                    )
                    .padding(.top, 60)
                    .padding(.trailing, 16)
                }
                Spacer()
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
        // Use a sheet that directly returns the view (avoid returning Void)
        .sheet(isPresented: $viewModel.showDeviceSelector) {
            DeviceSelectorView(
                devices: $viewModel.availableDevices,
                currentDevice: $viewModel.currentDevice,
                isLoading: $viewModel.isLoadingDevices,
                onDeviceSelected: { device in
                    Task {
                        await viewModel.switchToDevice(device)
                        viewModel.showDeviceSelector = false
                    }
                },
                onRefresh: {
                    Task {
                        await viewModel.fetchAvailableDevices()
                    }
                }
            )
            .frame(maxWidth: .infinity, maxHeight: 500)
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
    }

    // MARK: - Scrolling Helpers

    /// Scroll to the top anchor ("top-anchor"). If proxy is not available yet, mark a pending request.
    /// Use a small default delay so we run after a layout pass; `animated: false` is recommended when
    /// jumping after content changes so the scroll is always visible.
    private func scrollToTopAnchor(animated: Bool = true, delay: TimeInterval = 0.03) {
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
            guard let proxy = scrollProxy else {
                // proxy not available yet — remember to scroll when it appears
                pendingScrollToTop = true
                return
            }
            if animated {
                withAnimation(.easeOut(duration: 0.25)) {
                    proxy.scrollTo("top-anchor", anchor: .top)
                }
            } else {
                proxy.scrollTo("top-anchor", anchor: .top)
            }
        }
    }

    /// Scroll to the bottom anchor ("bottom-anchor").
    private func scrollToBottomAnchor(animated: Bool = true, delay: TimeInterval = 0.03) {
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
            guard let proxy = scrollProxy else { return }
            if animated {
                withAnimation(.easeOut(duration: 0.25)) {
                    proxy.scrollTo("bottom-anchor", anchor: .bottom)
                }
            } else {
                proxy.scrollTo("bottom-anchor", anchor: .bottom)
            }
        }
    }

    // MARK: - View Components

    private var chatView: some View {
        GeometryReader { geometry in
            ZStack(alignment: .top) {
                ScrollViewReader { proxy in
                    // Capture proxy early so helpers can be used elsewhere
                    Color.clear
                        .frame(height: 0)
                        .onAppear {
                            if scrollProxy == nil {
                                scrollProxy = proxy
                                if pendingScrollToTop {
                                    pendingScrollToTop = false
                                    // satisfy immediately without additional delay and non-animated
                                    scrollToTopAnchor(animated: false, delay: 0)
                                }
                            }
                        }

                    ScrollView {
                        VStack(spacing: 16) {
                            // Top anchor for transcription bubble positioning
                            Color.clear
                                .frame(height: 1)
                                .id("top-anchor")

                            // Show empty state icon when idle
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

                            // Inline transcription bubble (shown when few messages - at bottom)
                            if isActiveSession && !shouldShowTranscriptionAtTop {
                                TranscriptionBubble(
                                    isConnecting: viewModel.isConnecting,
                                    isRecording: viewModel.isRecording,
                                    isProcessing: viewModel.isProcessingTranscription,
                                    partialText: viewModel.partialTranscription
                                )
                                .transition(.opacity.combined(with: .move(edge: .bottom)))
                            }

                            // Invisible anchor at the very bottom for reliable scrolling
                            Color.clear
                                .frame(height: 1)
                                .id("bottom-anchor")
                        }
                        .padding(.top, shouldShowTranscriptionAtTop ? 100 : 20) // Extra space at top for floating bubble
                        .padding(.bottom, 140) // Space for stepper navigation and inline bubble
                        .background(
                            GeometryReader { contentGeometry in
                                Color.clear
                                    .preference(key: ContentHeightPreferenceKey.self, value: contentGeometry.size.height)
                            }
                        )
                    }
                    // Track content height (for shouldShowTranscriptionAtTop)
                    .onPreferenceChange(ContentHeightPreferenceKey.self) { height in
                        contentHeight = height
                    }
                    // When items are appended, scroll depending on transcription position
                    .onChange(of: messages.count) { oldCount, newCount in
                        guard newCount > oldCount, !isActiveSession else { return }

                        // Prefer an immediate non-animated jump when the content is now full so the
                        // floating bubble becomes visible at the top reliably.
                        if shouldShowTranscriptionAtTop {
                            scrollToTopAnchor(animated: false, delay: 0.02)
                        } else {
                            scrollToBottomAnchor()
                        }
                    }
                    // When the active session changes, reveal the bubble for the start of session
                    .onChange(of: isActiveSession) { wasActive, isActive in
                        if isActive {
                            // Session started: ensure bubble is visible (top if full, else bottom)
                            if shouldShowTranscriptionAtTop {
                                scrollToTopAnchor(animated: false, delay: 0.02)
                            } else {
                                scrollToBottomAnchor(animated: false, delay: 0.02)
                            }
                        } else if wasActive && !isActive {
                            // session ended — don't auto-scroll (let user stay where they are)
                        }
                    }
                    // When the layout (content height) changes and bubble should be at top, ensure it's visible
                    .onChange(of: contentHeight) { _ in
                        guard isActiveSession && shouldShowTranscriptionAtTop else { return }
                        // Non-animated immediate reveal after layout step
                        scrollToTopAnchor(animated: false, delay: 0.02)
                    }
                    // When partial transcription text changes (bubble grows/shrinks), ensure visibility
                    .onChange(of: viewModel.partialTranscription) { _ in
                        guard isActiveSession && shouldShowTranscriptionAtTop else { return }
                        scrollToTopAnchor(animated: false, delay: 0.02)
                    }
                    // When bubble position preference toggles, scroll appropriately
                    .onChange(of: shouldShowTranscriptionAtTop) { wasAtTop, isAtTop in
                        guard isActiveSession else { return }
                        if isAtTop {
                            scrollToTopAnchor(animated: false, delay: 0.02)
                        } else {
                            scrollToBottomAnchor(animated: false, delay: 0.02)
                        }
                    }
                    // Capture visible height for heuristics
                    .onAppear {
                        visibleHeight = geometry.size.height
                    }
                    .onChange(of: geometry.size.height) { _, newHeight in
                        visibleHeight = newHeight
                    }
                }

                // Floating transcription bubble at top when screen is full
                if isActiveSession && shouldShowTranscriptionAtTop {
                    VStack {
                        TranscriptionBubble(
                            isConnecting: viewModel.isConnecting,
                            isRecording: viewModel.isRecording,
                            isProcessing: viewModel.isProcessingTranscription,
                            partialText: viewModel.partialTranscription
                        )
                        .padding(.horizontal, 16)
                        .padding(.top, 20)
                        .transition(.opacity.combined(with: .move(edge: .top)))

                        Spacer()
                    }
                }
            }
        }
    } // end chatView

    // MARK: - Computed Properties

    /// True when any part of the session is active - shows the transcription bubble immediately
    private var isActiveSession: Bool {
        viewModel.isConnecting || viewModel.isRecording || viewModel.isProcessingTranscription
    }

    /// Determines if transcription bubble should float at top (when screen is full of messages)
    /// Compares actual content height vs visible screen height
    private var shouldShowTranscriptionAtTop: Bool {
        guard visibleHeight > 0 && contentHeight > 0 else {
            return false
        }
        // Show at top when content height exceeds visible height (screen is full and scrollable)
        // Use a buffer so the floating bubble kicks in slightly before absolute fullness
        return contentHeight > (visibleHeight - 100)
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

// MARK: - Preference Key

/// PreferenceKey for tracking content height in ScrollView
private struct ContentHeightPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

#Preview {
    AssistantView(authService: AuthenticationService(), viewModel: AssistantViewModel())
}
