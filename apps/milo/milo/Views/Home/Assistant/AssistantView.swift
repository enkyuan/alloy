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
                    .padding(.top, 8)
                Spacer()
            }
        }
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
