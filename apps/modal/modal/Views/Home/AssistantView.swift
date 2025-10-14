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
    @State private var integrationService = IntegrationService()
    @State private var isTalking = false
    @State private var visualizerState: BarVisualizer.VisualizerState = .initializing
    @State private var hasPermission = false
    @State private var showPermissionAlert = false
    @State private var hasIntegrations = false

    // MARK: - Body

    var body: some View {
        ZStack(alignment: .bottom) {
            // Main content
            if !hasIntegrations {
                IntegrationsEmptyStateView(authService: authService)
            } else if !hasPermission {
                permissionEmptyStateView
            } else {
                // Ready state - show visualizer
                Color.clear
            }

            // Bottom section with visualizer and controls
            if hasIntegrations && hasPermission {
                VStack(spacing: 0) {
                    Spacer()

                    // Bar visualizer
                    BarVisualizer(state: visualizerState)
                        .padding(.horizontal, 20)
                        .padding(.bottom, 100) // Space for button and stepper
                }
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

#Preview {
    AssistantView(authService: AuthenticationService())
}
