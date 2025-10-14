//
//  BarVisualizer.swift
//  modal
//
//  Audio bar visualizer - matches TypeScript implementation
//

import SwiftUI

struct BarVisualizer: View {
    enum VisualizerState {
        case connecting, initializing, listening, speaking, thinking
    }

    let state: VisualizerState
    private let barCount = 15
    private let minHeight: CGFloat = 8
    private let maxHeight: CGFloat = 36

    @State private var barHeights: [CGFloat] = []
    @State private var highlightedIndices: Set<Int> = []

    var body: some View {
        HStack(alignment: .bottom, spacing: 3) {
            ForEach(0..<barCount, id: \.self) { index in
                RoundedRectangle(cornerRadius: 2)
                    .fill(barColor(index: index))
                    .frame(width: max(6, (UIScreen.main.bounds.width - 60) / CGFloat(barCount)), height: barHeight(index: index))
            }
        }
        .frame(height: maxHeight, alignment: .bottom)
        .onAppear {
            barHeights = Array(repeating: minHeight, count: barCount)
            animate()
        }
        .onChange(of: state) { _, _ in
            animate()
        }
    }

    private func barColor(index: Int) -> Color {
        let isHighlighted = highlightedIndices.contains(index)
        let opacity: Double = isHighlighted ? 0.7 : 0.35

        switch state {
        case .speaking:
            return Color.gray.opacity(0.6)
        default:
            return Color.gray.opacity(opacity)
        }
    }

    private func barHeight(index: Int) -> CGFloat {
        guard index < barHeights.count else { return minHeight }
        return barHeights[index]
    }

    private func animate() {
        switch state {
        case .connecting:
            animateConnecting()
        case .initializing:
            animateInitializing()
        case .listening:
            animateListening()
        case .speaking:
            animateSpeaking()
        case .thinking:
            animateThinking()
        }
    }

    private func animateConnecting() {
        for i in 0..<barCount {
            let delay = Double(i) * (2.0 / Double(barCount))
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
                withAnimation(.easeInOut(duration: 0.3)) {
                    highlightedIndices.insert(i)
                    highlightedIndices.insert(barCount - 1 - i)
                    barHeights[i] = maxHeight * 0.6
                    barHeights[barCount - 1 - i] = maxHeight * 0.6
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        highlightedIndices.remove(i)
                        highlightedIndices.remove(barCount - 1 - i)
                        barHeights[i] = minHeight
                        barHeights[barCount - 1 - i] = minHeight
                    }
                }
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
            if state == .connecting {
                animate()
            }
        }
    }

    private func animateInitializing() {
        let center = barCount / 2
        for i in 0..<barCount {
            let distanceFromCenter = abs(i - center)
            let normalized = 1.0 - (Double(distanceFromCenter) / Double(center))
            withAnimation(.easeInOut(duration: 1.0).repeatForever(autoreverses: true)) {
                barHeights[i] = minHeight + (maxHeight - minHeight) * CGFloat(0.3 + 0.4 * normalized)
            }
        }
    }

    private func animateListening() {
        let center = barCount / 2
        Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { timer in
            guard state == .listening else {
                timer.invalidate()
                return
            }
            withAnimation(.easeInOut(duration: 0.5)) {
                highlightedIndices = highlightedIndices.isEmpty ? [center] : []
                barHeights[center] = highlightedIndices.isEmpty ? minHeight : maxHeight * 0.7
            }
        }
    }

    private func animateSpeaking() {
        Timer.scheduledTimer(withTimeInterval: 0.08, repeats: true) { timer in
            guard state == .speaking else {
                timer.invalidate()
                return
            }
            withAnimation(.easeInOut(duration: 0.1)) {
                for i in 0..<barCount {
                    barHeights[i] = CGFloat.random(in: minHeight...(maxHeight * 0.85))
                }
            }
        }
    }

    private func animateThinking() {
        for i in 0..<barCount {
            let delay = Double(i) * 0.08
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
                withAnimation(.easeInOut(duration: 0.3).repeatForever(autoreverses: true)) {
                    highlightedIndices.insert(i)
                    barHeights[i] = CGFloat.random(in: (minHeight * 2)...(maxHeight * 0.7))
                }
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + Double(barCount) * 0.08 + 0.3) {
            if state == .thinking {
                withAnimation {
                    highlightedIndices.removeAll()
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                    if state == .thinking {
                        animate()
                    }
                }
            }
        }
    }
}