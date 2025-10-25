//
//  AssistantView.swift
//  modal
//
//  Main voice assistant interface
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
        .sheet(isPresented: $viewModel.showDeviceSelector) {
            VStack {
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
    }

    // MARK: - View Components
    
    private var chatView: some View {
        GeometryReader { geometry in
            ZStack(alignment: .top) {
                ScrollViewReader { proxy in
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
                    .onPreferenceChange(ContentHeightPreferenceKey.self) { height in
                        contentHeight = height
                    }
                    .onChange(of: messages.count) { oldCount, newCount in
                        // Scroll to new message when added (only when not actively recording)
                        guard newCount > oldCount, !isActiveSession else { return }
                        
                        // Small delay to ensure view is rendered
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                            withAnimation(.easeOut(duration: 0.3)) {
                                if let lastMessage = messages.last {
                                    proxy.scrollTo(lastMessage.id, anchor: .bottom)
                                } else {
                                    proxy.scrollTo("bottom-anchor", anchor: .bottom)
                                }
                            }
                        }
                    }
                    .onChange(of: isActiveSession) { wasActive, isActive in
                        // Scroll when session starts or ends
                        if isActive {
                            // Session just started - scroll to appropriate position
                            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                                withAnimation(.easeOut(duration: 0.25)) {
                                    if shouldShowTranscriptionAtTop {
                                        // Screen is full - scroll to top to show floating bubble
                                        proxy.scrollTo("top-anchor", anchor: .top)
                                    } else {
                                        // Screen not full - scroll to bottom to show inline bubble
                                        proxy.scrollTo("bottom-anchor", anchor: .bottom)
                                    }
                                }
                            }
                        } else if wasActive && !isActive {
                            // Session ended - scroll to bottom to show new message
                            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                                withAnimation(.easeOut(duration: 0.3)) {
                                    proxy.scrollTo("bottom-anchor", anchor: .bottom)
                                }
                            }
                        }
                    }
                    .onChange(of: shouldShowTranscriptionAtTop) { wasAtTop, isAtTop in
                        // When bubble position changes during active session, scroll to show it
                        guard isActiveSession else { return }
                        
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                            withAnimation(.easeOut(duration: 0.25)) {
                                if isAtTop {
                                    // Bubble moved to top - scroll to show it
                                    proxy.scrollTo("top-anchor", anchor: .top)
                                } else {
                                    // Bubble moved to bottom - scroll to show it
                                    proxy.scrollTo("bottom-anchor", anchor: .bottom)
                                }
                            }
                        }
                    }
                }
                .onAppear {
                    visibleHeight = geometry.size.height
                }
                .onChange(of: geometry.size.height) { _, newHeight in
                    visibleHeight = newHeight
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
    }    // MARK: - Computed Properties
    
    /// True when button is pressed - shows the transcription bubble immediately
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
        // Use smaller buffer to trigger earlier when screen fills up
        return contentHeight > (visibleHeight - 100)
    }
    

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
