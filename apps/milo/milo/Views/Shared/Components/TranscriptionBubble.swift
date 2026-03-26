import SwiftUI

struct TranscriptionBubble: View {
    enum Mode {
        case recording
        case processing
    }

    let mode: Mode
    var audioLevel: Float = 0
    var audioEnvelope: [Float] = []
    @SwiftUI.Environment(\.accessibilityReduceMotion) private var reduceMotion

    init(mode: Mode, audioLevel: Float = 0, audioEnvelope: [Float] = []) {
        self.mode = mode
        self.audioLevel = audioLevel
        self.audioEnvelope = audioEnvelope
    }

    var body: some View {
        switch mode {
        case .recording:
            GeometryReader { geometry in
                bubbleShell(
                    fill: Color.black.opacity(0.96),
                    stroke: Color.white.opacity(0.08),
                    shadow: Color.black.opacity(0.18),
                    maxWidth: accessoryControlSpanWidth(for: geometry.size.width),
                    contentPadding: EdgeInsets(top: 14, leading: 18, bottom: 14, trailing: 18)
                ) {
                    AudioWaveformBubbleContent(
                        audioLevel: audioLevel,
                        audioEnvelope: audioEnvelope,
                        reduceMotion: reduceMotion
                    )
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(height: 60)
        case .processing:
            HStack {
                bubbleShell(
                    fill: Color(.systemGray6),
                    stroke: Color(.systemGray4).opacity(0.6),
                    shadow: Color.black.opacity(0.04),
                    maxWidth: nil,
                    contentPadding: EdgeInsets(top: 10, leading: 12, bottom: 10, trailing: 12)
                ) {
                    TypingIndicatorContent(reduceMotion: reduceMotion)
                }
                Spacer(minLength: 0)
            }
        }
    }

    @ViewBuilder
    private func bubbleShell<Content: View>(
        fill: Color,
        stroke: Color,
        shadow: Color,
        maxWidth: CGFloat?,
        contentPadding: EdgeInsets,
        @ViewBuilder content: () -> Content
    ) -> some View {
        content()
            .padding(contentPadding)
            .frame(maxWidth: maxWidth, alignment: .leading)
            .background(
                Capsule(style: .continuous)
                    .fill(fill)
            )
            .overlay(
                Capsule(style: .continuous)
                    .strokeBorder(stroke, lineWidth: 1)
            )
            .shadow(color: shadow, radius: 10, x: 0, y: 4)
    }

    private func accessoryControlSpanWidth(for availableWidth: CGFloat) -> CGFloat {
        max(0, availableWidth - 24)
    }
}

private struct TypingIndicatorContent: View {
    let reduceMotion: Bool

    var body: some View {
        TimelineView(.animation(minimumInterval: reduceMotion ? 0.4 : 1.0 / 30.0)) { context in
            let phase = context.date.timeIntervalSinceReferenceDate

            HStack(spacing: 5) {
                ForEach(0..<3, id: \.self) { index in
                    Circle()
                        .fill(Color(.systemGray3))
                        .frame(width: 8, height: 8)
                        .scaleEffect(dotScale(for: index, phase: phase))
                        .opacity(dotOpacity(for: index, phase: phase))
                }
            }
        }
        .frame(height: 10)
        .accessibilityLabel("Processing command")
    }

    private func dotScale(for index: Int, phase: TimeInterval) -> CGFloat {
        guard !reduceMotion else { return [0.92, 1, 0.95][index] }
        let intensity = dotIntensity(for: index, phase: phase)
        return 0.78 + (intensity * 0.3)
    }

    private func dotOpacity(for index: Int, phase: TimeInterval) -> Double {
        guard !reduceMotion else { return [0.62, 0.82, 0.68][index] }
        let intensity = dotIntensity(for: index, phase: phase)
        return 0.32 + (intensity * 0.68)
    }

    private func dotIntensity(for index: Int, phase: TimeInterval) -> Double {
        let cycle = phase * 1.55
        let offset = Double(index) * 0.18
        let wrappedPhase = (cycle - offset).truncatingRemainder(dividingBy: 1)
        return 0.5 - (0.5 * cos(wrappedPhase * .pi * 2))
    }
}

private struct AudioWaveformBubbleContent: View {
    let audioLevel: Float
    let audioEnvelope: [Float]
    let reduceMotion: Bool
    @State private var displayedLevels: [CGFloat] = []

    private let barCount = 34

    var body: some View {
        GeometryReader { geometry in
            HStack(alignment: .center, spacing: 3) {
                ForEach(Array(displayedLevels.enumerated()), id: \.offset) { index, level in
                    RoundedRectangle(cornerRadius: barWidth(for: geometry.size.width) / 2, style: .continuous)
                        .fill(barColor(for: index))
                        .frame(
                            width: barWidth(for: geometry.size.width),
                            height: mirroredBarHeight(for: level, index: index, maxHeight: geometry.size.height)
                        )
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
        .frame(height: 32)
        .onAppear {
            resetDisplayedLevels()
        }
        .onChange(of: audioEnvelope) { _, newValue in
            append(envelope: newValue)
        }
        .onChange(of: audioLevel) { _, newValue in
            if audioEnvelope.isEmpty {
                append(envelope: [newValue])
            }
        }
        .accessibilityLabel("Listening")
    }

    private func barWidth(for availableWidth: CGFloat) -> CGFloat {
        let spacingWidth = CGFloat(barCount - 1) * 3
        return max(3, (availableWidth - spacingWidth) / CGFloat(barCount))
    }

    private func mirroredBarHeight(for level: CGFloat, index: Int, maxHeight: CGFloat) -> CGFloat {
        let reactiveLevel = pow(level, reduceMotion ? 0.7 : 0.52)
        let age = CGFloat(index) / CGFloat(max(barCount - 1, 1))
        let freshness = 0.28 + (age * 0.72)
        let floor = reduceMotion ? 0.22 : 0.18
        let peak = reduceMotion ? 0.68 : 0.92
        let normalized = floor + (reactiveLevel * freshness * peak)
        return max(10, min(maxHeight, maxHeight * normalized))
    }

    private func barColor(for index: Int) -> Color {
        let freshness = Double(index) / Double(max(barCount - 1, 1))
        let opacity = 0.28 + (freshness * 0.68)
        return Color.white.opacity(min(opacity, 0.96))
    }

    private func resetDisplayedLevels() {
        displayedLevels = Array(repeating: 0, count: barCount)
    }

    private func append(envelope: [Float]) {
        if displayedLevels.isEmpty {
            resetDisplayedLevels()
        }

        let animation = reduceMotion ? Animation.easeOut(duration: 0.08) : .linear(duration: 0.09)
        withAnimation(animation) {
            let normalizedLevels = envelope.map { max(0.04, min(CGFloat($0), 1)) }
            displayedLevels.append(contentsOf: normalizedLevels)
            if displayedLevels.count > barCount {
                displayedLevels.removeFirst(displayedLevels.count - barCount)
            }
        }
    }
}
