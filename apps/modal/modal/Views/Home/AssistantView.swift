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

    // MARK: - View Components
    
    private var chatView: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(spacing: 16) {
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

                    // Show transcription bubble when active (connecting, recording, or processing)
                    if isActiveSession {
                        TranscriptionBubble(
                            isConnecting: viewModel.isConnecting,
                            isRecording: viewModel.isRecording,
                            isProcessing: viewModel.isProcessingTranscription,
                            partialText: viewModel.partialTranscription
                        )
                        .transition(.opacity.combined(with: .scale(scale: 0.9)))
                        .id("partial-transcription")
                    }
                    
                    // Invisible anchor at the very bottom for reliable scrolling
                    Color.clear
                        .frame(height: 1)
                        .id("bottom-anchor")
                }
                .padding(.top, 20)
                .padding(.bottom, 120) // Space for stepper navigation
            }
            .onChange(of: messages.count) { oldCount, newCount in
                // Scroll to new message when added
                guard newCount > oldCount else { return }
                
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
                // Scroll when bubble appears or disappears
                if isActive {
                    // Bubble just appeared - scroll to it
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                        withAnimation(.easeOut(duration: 0.25)) {
                            proxy.scrollTo("partial-transcription", anchor: .bottom)
                        }
                    }
                } else if wasActive && !isActive {
                    // Bubble just disappeared - scroll to bottom (likely new message was added)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                        withAnimation(.easeOut(duration: 0.3)) {
                            proxy.scrollTo("bottom-anchor", anchor: .bottom)
                        }
                    }
                }
            }
            .onChange(of: viewModel.partialTranscription) { oldValue, newValue in
                // Only scroll when transcription first appears or grows significantly
                // This prevents janky scrolling on every character
                guard isActiveSession else { return }
                
                let oldWordCount = oldValue.split(separator: " ").count
                let newWordCount = newValue.split(separator: " ").count
                
                // Scroll when: first word appears, or every 3 new words
                if (oldWordCount == 0 && newWordCount > 0) || 
                   (newWordCount > 0 && newWordCount % 3 == 0 && newWordCount > oldWordCount) {
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo("partial-transcription", anchor: .bottom)
                    }
                }
            }
        }
    }
    
    // MARK: - Computed Properties
    
    /// True when button is pressed - shows the transcription bubble immediately
    private var isActiveSession: Bool {
        viewModel.isConnecting || viewModel.isRecording || viewModel.isProcessingTranscription
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
                    Text("Almost there!")
                        .font(.system(size: 32, weight: .bold))

                    Text("I'll need access to your microphone to listen to you.")
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
                            .background(
                                LinearGradient(
                                    colors: [.blue, .purple],
                                    startPoint: .leading,
                                    endPoint: .trailing
                                )
                            )
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
