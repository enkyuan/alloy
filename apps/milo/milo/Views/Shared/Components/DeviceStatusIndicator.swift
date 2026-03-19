import SwiftUI

struct DeviceStatusIndicator: View {
    let device: SpotifyDevice?
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 8) {
                if let device = device {
                    Image(systemName: device.iconName)
                        .font(.caption)
                        .foregroundColor(.secondary)

                    Text(device.name)
                        .font(.caption)
                        .foregroundColor(.secondary)
                        .lineLimit(1)

                    if device.isActive {
                        Circle()
                            .fill(Color.green)
                            .frame(width: 6, height: 6)
                    }
                } else {
                    Image(systemName: "speaker.slash")
                        .font(.caption)
                        .foregroundColor(.secondary)

                    Text("No Device")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }

                Image(systemName: "chevron.down")
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(Color(.systemGray6))
            .cornerRadius(12)
        }
        .buttonStyle(PlainButtonStyle())
    }
}

<<<<<<<< HEAD:apps/modal/modal/Views/Shared/Components/DeviceStatusIndicator.swift
#Preview {
    VStack(spacing: 20) {
        DeviceStatusIndicator(
            device: SpotifyDevice(id: "1", name: "iPhone", type: "smartphone", isActive: true, volumePercent: 75),
            onTap: {}
        )

        DeviceStatusIndicator(
            device: SpotifyDevice(id: "2", name: "MacBook Pro with a very long name", type: "computer", isActive: false, volumePercent: 50),
            onTap: {}
        )

        DeviceStatusIndicator(
            device: nil,
            onTap: {}
        )
    }
    .padding()
}
========
>>>>>>>> codex/refactor:apps/milo/milo/Views/Shared/Components/DeviceStatusIndicator.swift
