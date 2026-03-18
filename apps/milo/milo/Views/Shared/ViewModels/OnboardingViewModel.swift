import SwiftUI

@MainActor
@Observable
class OnboardingViewModel {

    var currentPhraseIndex = 0
    var showGreeting = false
    var currentPhrase = ""
    var phraseOpacity: Double = 0
    var phraseOffset: CGFloat = 20
    var phraseBlur: CGFloat = 10
    var previewOpacity: Double = 0

    private let phrases = [
        "Order Pad Thai from DoorDash",
        "Play Midnight City on Apple Music",
        "Get me some paper towels on Instacart",
    ]
    private var animationTask: Task<Void, Never>?


    func startAnimations() {
        stopAnimations()
        resetAnimationState()

        withAnimation(.easeIn(duration: 0.8)) {
            showGreeting = true
        }

        animationTask = Task { @MainActor in
            guard await sleep(seconds: 1.0) else { return }
            showFirstPhrase()

            while !Task.isCancelled {
                guard await sleep(seconds: 3.0) else { return }
                await cycleToNextPhrase()
            }
        }
    }

    func stopAnimations() {
        animationTask?.cancel()
        animationTask = nil
    }

    private func resetAnimationState() {
        currentPhraseIndex = 0
        currentPhrase = ""
        phraseOpacity = 0
        phraseOffset = 20
        phraseBlur = 10
        previewOpacity = 0
        showGreeting = false
    }

    private func showFirstPhrase() {
        currentPhrase = phrases[0]
        withAnimation(.easeInOut(duration: 0.8)) {
            phraseOpacity = 1.0
            phraseOffset = 0
            phraseBlur = 0
        }
        withAnimation(.easeIn(duration: 0.8).delay(0.3)) {
            previewOpacity = 1.0
        }
    }

    private func cycleToNextPhrase() async {
        withAnimation(.easeInOut(duration: 0.6)) {
            phraseOpacity = 0
            phraseOffset = -20
            phraseBlur = 10
            previewOpacity = 0
        }

        guard await sleep(seconds: 0.6) else { return }

        currentPhraseIndex = (currentPhraseIndex + 1) % phrases.count
        currentPhrase = phrases[currentPhraseIndex]
        phraseOffset = 20

        withAnimation(.easeInOut(duration: 0.8)) {
            phraseOpacity = 1.0
            phraseOffset = 0
            phraseBlur = 0
        }
        withAnimation(.easeIn(duration: 0.8).delay(0.3)) {
            previewOpacity = 1.0
        }
    }

    private func sleep(seconds: TimeInterval) async -> Bool {
        do {
            try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
            return !Task.isCancelled
        } catch {
            return false
        }
    }
}
