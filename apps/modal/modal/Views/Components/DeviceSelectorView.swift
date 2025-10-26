import SwiftUI

/// View for selecting Spotify playback devices
struct DeviceSelectorView: View {
    @Binding var devices: [SpotifyDevice]
    @Binding var currentDevice: SpotifyDevice?
    @Binding var isLoading: Bool
    let onDeviceSelected: (SpotifyDevice) -> Void
    let onRefresh: () -> Void
    @SwiftUI.Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            if isLoading && devices.isEmpty {
                VStack(spacing: 16) {
                    ProgressView()
                    Text("Loading devices...")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding()
            } else if devices.isEmpty {
                VStack(spacing: 16) {
                    Image(systemName: deviceEmptyIcon)
                        .font(.system(size: 48))
                        .foregroundColor(.secondary)

                    Text("No Devices Available")
                        .font(.headline)
                        .foregroundColor(.primary)

                    Text("Open Spotify on a device to see it here")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding()
            } else {
                ScrollView {
                    VStack(spacing: 0) {
                        ForEach(devices) { device in
                            DeviceRow(
                                device: device,
                                isSelected: device.id == currentDevice?.id,
                                onTap: {
                                    onDeviceSelected(device)
                                }
                            )

                            if device.id != devices.last?.id {
                                Divider()
                                    .padding(.leading, 60)
                            }
                        }
                    }
                }
            }
        }
        .background(Color(uiColor: .systemBackground))
        .navigationTitle("Devices")
        .navigationBarTitleDisplayMode(.large)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button(action: onRefresh) {
                    if isLoading {
                        ProgressView()
                            .tint(.secondary)
                    } else {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundColor(.secondary)
                    }
                }
                .disabled(isLoading)
            }
        }
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(false)
    }

    // MARK: - Helpers

    private var deviceEmptyIcon: String {
        let idiom = UIDevice.current.userInterfaceIdiom
        
        switch idiom {
        case .phone:
            if #available(iOS 15.0, *) {
                return "iphone.gen2.slash"
            } else {
                return "iphone.gen1.slash"
            }
        case .pad:
            return "ipad.slash"
        default:
            return "iphone.gen1.slash"
        }
    }
}

/// Row view for a single device
struct DeviceRow: View {
    let device: SpotifyDevice
    let isSelected: Bool
    let onTap: () -> Void
    
    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 16) {
                // Device icon
                Image(systemName: device.iconName)
                    .font(.system(size: 24))
                    .foregroundColor(isSelected ? .accentColor : .secondary)
                    .frame(width: 32, height: 32)
                
                // Device info
                VStack(alignment: .leading, spacing: 4) {
                    Text(device.name)
                        .font(.body)
                        .foregroundColor(.primary)
                    
                    HStack(spacing: 8) {
                        Text(device.type.capitalized)
                            .font(.caption)
                            .foregroundColor(.secondary)
                        
                        if device.isActive {
                            HStack(spacing: 4) {
                                Circle()
                                    .fill(Color.green)
                                    .frame(width: 6, height: 6)
                                
                                Text("Active")
                                    .font(.caption)
                                    .foregroundColor(.green)
                            }
                        }
                    }
                }
                
                Spacer()
                
                // Volume indicator
                if device.volumePercent > 0 {
                    HStack(spacing: 4) {
                        Image(systemName: volumeIcon(for: device.volumePercent))
                            .font(.caption)
                            .foregroundColor(.secondary)
                        
                        Text("\(device.volumePercent)%")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
                
                // Selection indicator
                if isSelected {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.accentColor)
                }
            }
            .padding()
            .background(isSelected ? Color.accentColor.opacity(0.1) : Color.clear)
        }
        .buttonStyle(PlainButtonStyle())
    }
    
    private func volumeIcon(for volume: Int) -> String {
        switch volume {
        case 0:
            return "speaker.slash"
        case 1...33:
            return "speaker.wave.1"
        case 34...66:
            return "speaker.wave.2"
        default:
            return "speaker.wave.3"
        }
    }
}

#Preview {
    @Previewable @State var devices: [SpotifyDevice] = [
        SpotifyDevice(id: "1", name: "iPhone", type: "smartphone", isActive: true, volumePercent: 75),
        SpotifyDevice(id: "2", name: "MacBook Pro", type: "computer", isActive: false, volumePercent: 50),
        SpotifyDevice(id: "3", name: "Living Room Speaker", type: "speaker", isActive: false, volumePercent: 30)
    ]
    @Previewable @State var currentDevice: SpotifyDevice? = SpotifyDevice(id: "1", name: "iPhone", type: "smartphone", isActive: true, volumePercent: 75)
    @Previewable @State var isLoading = false
    
    return DeviceSelectorView(
        devices: $devices,
        currentDevice: $currentDevice,
        isLoading: $isLoading,
        onDeviceSelected: { _ in },
        onRefresh: {}
    )
}
