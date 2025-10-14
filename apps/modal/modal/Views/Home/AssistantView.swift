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
    @State private var integrationService = IntegrationService()
    @State private var hasPermission = false
    @State private var showPermissionAlert = false
    @State private var hasIntegrations = false
    
    // Computed property to avoid binding issues
    private var messages: [Message] {
        viewModel.conversationService.messages
    }

    // MARK: - Body

    var body: some View {
        ZStack(alignment: .bottom) {
            // Main content
            if !hasIntegrations {
                IntegrationsEmptyStateView(authService: authService)
            } else if !hasPermission {
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
                    if messages.isEmpty {
                        // Empty state - show icon
                        VStack {
                            Spacer()
                            
                            Image("ModalIcon")
                                .resizable()
                                .aspectRatio(contentMode: .fit)
                                .frame(width: 80, height: 80)
                                .foregroundStyle(.secondary.opacity(0.3))
                                .opacity(viewModel.isProcessingTranscription ? 0 : 1)
                                .animation(.easeInOut(duration: 0.3), value: viewModel.isProcessingTranscription)
                            
                            if viewModel.isProcessingTranscription {
                                ProgressView()
                                    .padding(.top, 20)
                            }
                            
                            Spacer()
                        }
                        .frame(maxWidth: .infinity)
                        .frame(minHeight: 400)
                    } else {
                        // Messages
                        ForEach(messages) { message in
                            MessageRow(message: message)
                        }

                        if viewModel.isProcessingTranscription {
                            HStack {
                                ProgressView()
                                    .padding(.leading, 16)
                                Text("Transcribing...")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Spacer()
                            }
                            .padding(.horizontal, 16)
                        }
                    }
                }
                .padding(.top, 20)
                .padding(.bottom, 120) // Space for stepper navigation
                .onChange(of: messages.isEmpty) { _, isEmpty in
                    print("🔍 AssistantView: messages.isEmpty changed to \(isEmpty), count = \(messages.count)")
                }
            }
            .onChange(of: messages.count) { _, newCount in
                print("🔍 AssistantView: messages.count changed to \(newCount)")
                // Auto-scroll to bottom when new message added
                if let lastMessage = messages.last {
                    withAnimation {
                        proxy.scrollTo(lastMessage.id, anchor: .bottom)
                    }
                }
            }
        }
    }
    

    private var permissionEmptyStateView: some View {
        VStack(spacing: 32) {
            Spacer()

            VStack(spacing: 24) {
                // Icon
                Image("ModalIcon@LiquidGlass")
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

        // Check integrations
        do {
            try await integrationService.fetchConnectedIntegrations(authService: authService)
            hasIntegrations = integrationService.hasConnectedIntegrations
        } catch {
            print("Failed to fetch integrations: \(error)")
            hasIntegrations = false
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
                // All messages use fade-in animation
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
