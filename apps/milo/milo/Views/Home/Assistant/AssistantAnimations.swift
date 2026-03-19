import SwiftUI

struct RecordingOverlayTransitionModifier: ViewModifier {
    let opacity: Double
    let scale: CGFloat
    let yOffset: CGFloat

    func body(content: Content) -> some View {
        content
            .opacity(opacity)
            .scaleEffect(scale, anchor: .bottomTrailing)
            .offset(y: yOffset)
    }
}

extension AnyTransition {
    static var recordingOverlayEntrance: AnyTransition {
        .modifier(
            active: RecordingOverlayTransitionModifier(
                opacity: 0,
                scale: 0.72,
                yOffset: 40
            ),
            identity: RecordingOverlayTransitionModifier(
                opacity: 1,
                scale: 1,
                yOffset: 0
            )
        )
    }
}

struct FirstUserSendAnimationModifier: ViewModifier {
    let isEnabled: Bool
    let shouldStartAnimation: Bool
    let itemHeight: CGFloat
    let containerHeight: CGFloat
    let onCompleted: () -> Void

    @State private var translateY: CGFloat = 0
    @State private var opacity: Double = 1
    @State private var hasStarted = false
    @State private var completionTask: Task<Void, Never>?

    func body(content: Content) -> some View {
        content
            .offset(y: isEnabled ? translateY : 0)
            .opacity(isEnabled ? opacity : 1)
            .onAppear {
                if !isEnabled {
                    reset()
                }
                startIfPossible()
            }
            .onChange(of: shouldStartAnimation) { _, _ in
                startIfPossible()
            }
            .onChange(of: itemHeight) { _, _ in
                startIfPossible()
            }
            .onChange(of: isEnabled) { _, enabled in
                if !enabled {
                    reset()
                }
            }
            .onDisappear {
                completionTask?.cancel()
            }
    }

    private func startIfPossible() {
        guard isEnabled, shouldStartAnimation, !hasStarted, itemHeight > 0 else {
            return
        }

        hasStarted = true

        let availableHeight = containerHeight > 0 ? containerHeight : 420
        let startOffset = max(24, (availableHeight * 0.62) - itemHeight)

        translateY = startOffset
        opacity = 0

        withAnimation(.easeOut(duration: 0.2)) {
            opacity = 1
        }

        withAnimation(.spring(response: 0.46, dampingFraction: 0.82, blendDuration: 0.2)) {
            translateY = 0
        }

        completionTask?.cancel()
        completionTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 420_000_000)
            guard !Task.isCancelled else { return }
            onCompleted()
        }
    }

    private func reset() {
        completionTask?.cancel()
        translateY = 0
        opacity = 1
        hasStarted = false
    }
}

struct FirstAssistantRevealModifier: ViewModifier {
    let isEnabled: Bool
    let didUserMessageAnimate: Bool
    let onReveal: () -> Void

    @State private var revealOpacity: Double = 1
    @State private var hasRevealed = false

    func body(content: Content) -> some View {
        content
            .opacity(isEnabled ? revealOpacity : 1)
            .onAppear {
                if isEnabled {
                    revealOpacity = 0
                } else {
                    revealOpacity = 1
                    hasRevealed = true
                }
                revealIfNeeded()
            }
            .onChange(of: didUserMessageAnimate) { _, _ in
                revealIfNeeded()
            }
            .onChange(of: isEnabled) { _, enabled in
                if !enabled {
                    revealOpacity = 1
                    hasRevealed = true
                } else {
                    revealOpacity = didUserMessageAnimate ? 1 : 0
                    hasRevealed = didUserMessageAnimate
                    revealIfNeeded()
                }
            }
    }

    private func revealIfNeeded() {
        guard isEnabled, didUserMessageAnimate, !hasRevealed else {
            return
        }

        hasRevealed = true
        onReveal()

        withAnimation(.easeOut(duration: 0.35)) {
            revealOpacity = 1
        }
    }
}
