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

