
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
    @State private var displayedWords: [String] = []

    var body: some View {
        Text(displayedWords.joined(separator: " "))
            .font(.body)
            .foregroundStyle(.primary.opacity(0.7))
            .onAppear {
                displayedWords = text.split(separator: " ").map(String.init)
            }
            .onChange(of: text) { oldValue, newValue in
                let oldWords = oldValue.split(separator: " ").map(String.init)
                let newWords = newValue.split(separator: " ").map(String.init)

                if newWords.count > oldWords.count {
                    let addedWords = Array(newWords[oldWords.count...])

                    for (index, word) in addedWords.enumerated() {
                        DispatchQueue.main.asyncAfter(deadline: .now() + Double(index) * 0.05) {
                            withAnimation(.easeOut(duration: 0.3)) {
                                displayedWords.append(word)
                            }
                        }
                    }
                } else if newWords != oldWords {
                    withAnimation(.easeOut(duration: 0.3)) {
                        displayedWords = newWords
                    }
                }
            }
    }
}


#Preview {
    VStack(spacing: 20) {
        TranscriptionBubble(
            isConnecting: true,
            isRecording: false,
            isProcessing: false,
            partialText: ""
        )

        TranscriptionBubble(
            isConnecting: false,
            isRecording: true,
            isProcessing: false,
            partialText: "Hello this is a test transcription"
        )

        TranscriptionBubble(
            isConnecting: false,
            isRecording: false,
            isProcessing: true,
            partialText: "Final transcription text here"
        )
    }
    .padding()
    .background(Color.black)
}
