import AVFoundation
import SwiftUI

enum MicrophonePermission {
    static let alertTitle = "Microphone Access Required"
    static let alertMessage = "Milo needs microphone access to enable voice commands. Please enable it in Settings."

    static var isGranted: Bool {
        AVAudioApplication.shared.recordPermission == .granted
    }

    static func requestIfNeeded() async -> Bool {
        switch AVAudioApplication.shared.recordPermission {
        case .granted:
            return true
        case .undetermined:
            return await AVAudioApplication.requestRecordPermission()
        default:
            return false
        }
    }

    @MainActor
    static func openSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }
}

extension View {
    func microphonePermissionAlert(isPresented: Binding<Bool>) -> some View {
        alert(MicrophonePermission.alertTitle, isPresented: isPresented) {
            Button("Open Settings") {
                MicrophonePermission.openSettings()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(MicrophonePermission.alertMessage)
        }
    }
}
