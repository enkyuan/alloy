import SwiftUI

struct TranscriptionBubble: View {
    let isConnecting: Bool
    let isRecording: Bool
    let isProcessing: Bool
    let partialText: String

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Spacer()

            VStack(alignment: .trailing, spacing: 6) {
                Group {
                    if partialText.isEmpty {
                        HStack(spacing: 6) {
                            Circle()
                                .fill(.blue)
                                .frame(width: 6, height: 6)
                            Text(isConnecting ? "Connecting..." : "Listening...")
                                .font(.body)
                                .foregroundStyle(.primary.opacity(0.7))
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                    } else {
                        PartialTranscriptionText(text: partialText)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                    }
                }
                .background(
                    RoundedRectangle(cornerRadius: 16)
                        .fill(.blue.opacity(0.1))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .strokeBorder(.blue.opacity(0.3), lineWidth: 1)
                )

                if !statusText.isEmpty {
                    Text(statusText)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .padding(.trailing, 4)
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
    }

    private var statusText: String {
        if isConnecting {
            return "Connecting..."
        } else if isRecording {
            return "Speaking..."
        } else if isProcessing {
            return "Finalizing..."
        } else {
            return ""
        }
    }
}

private struct PartialTranscriptionText: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.body)
            .foregroundStyle(.primary.opacity(0.7))
            .animation(.easeOut(duration: 0.1), value: text)
    }
}
