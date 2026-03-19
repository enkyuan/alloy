import SwiftUI

struct AssistantGreetingView: View {
    @State private var titleOpacity: Double = 0
    @State private var subtitleOpacity: Double = 0
    @State private var currentExampleIndex: Int = -1
    @State private var exampleTask: Task<Void, Never>?

    private let examples = [
        "Play your favorite playlist",
        "Add an event to your calendar",
        "Reply to an email",
    ]
    private let exampleInitialDelay: TimeInterval = 1.5
    private let exampleDisplayDuration: TimeInterval = 5.0

    var body: some View {
        VStack(alignment: .leading, spacing: 32) {
            Spacer()

            VStack(alignment: .leading, spacing: 12) {
                Text("Hi, I'm Milo")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(.primary)
                    .opacity(titleOpacity)

                Text("What can I do for you? Ask me to...")
                    .font(.system(size: 20, weight: .medium))
                    .foregroundStyle(.secondary)
                    .opacity(subtitleOpacity)
            }

            if currentExampleIndex >= 0 && currentExampleIndex < examples.count {
                AnimatedExampleRow(text: examples[currentExampleIndex])
                    .id(currentExampleIndex)
            }

            Spacer()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 20)
        .frame(minHeight: 400)
        .onAppear {
            withAnimation(.easeOut(duration: 0.8)) {
                titleOpacity = 1.0
            }

            withAnimation(.easeOut(duration: 0.8).delay(0.4)) {
                subtitleOpacity = 1.0
            }

            startExampleCycle()
        }
        .onDisappear {
            exampleTask?.cancel()
            exampleTask = nil
        }
    }

    private func startExampleCycle() {
        exampleTask?.cancel()
        exampleTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: UInt64(exampleInitialDelay * 1_000_000_000))
            guard !Task.isCancelled else { return }
            withAnimation {
                currentExampleIndex = 0
            }

            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: UInt64(exampleDisplayDuration * 1_000_000_000))
                guard !Task.isCancelled else { return }
                withAnimation {
                    currentExampleIndex = (currentExampleIndex + 1) % examples.count
                }
            }
        }
    }
}

private struct AnimatedExampleRow: View {
    let text: String
    @State private var opacity: Double = 0
    @State private var blur: CGFloat = 10
    @State private var offset: CGFloat = 20

    var body: some View {
        AnimatedText(
            fadeIn: text,
            opacity: opacity,
            blur: blur,
            offset: offset
        )
        .font(.system(size: 18, weight: .medium))
        .foregroundStyle(.primary)
        .onAppear {
            withAnimation(.easeOut(duration: 0.6)) {
                opacity = 1.0
                blur = 0
                offset = 0
            }
        }
    }
}
