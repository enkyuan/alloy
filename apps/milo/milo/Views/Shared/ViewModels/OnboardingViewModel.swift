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


    func startAnimations() {
        withAnimation(.easeIn(duration: 0.8)) {
            showGreeting = true
        }
        schedule(delay: 1.0) {
            self.showFirstPhrase()
        }
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

        schedule(delay: 3.0) {
            self.cyclePhrases()
        }
    }

    private func cyclePhrases() {
        withAnimation(.easeInOut(duration: 0.6)) {
            phraseOpacity = 0
            phraseOffset = -20
            phraseBlur = 10
            previewOpacity = 0
        }

        schedule(delay: 0.6) {
            self.currentPhraseIndex = (self.currentPhraseIndex + 1) % self.phrases.count
            self.currentPhrase = self.phrases[self.currentPhraseIndex]
            self.phraseOffset = 20

            withAnimation(.easeInOut(duration: 0.8)) {
                self.phraseOpacity = 1.0
                self.phraseOffset = 0
                self.phraseBlur = 0
            }
            withAnimation(.easeIn(duration: 0.8).delay(0.3)) {
                self.previewOpacity = 1.0
            }

            self.schedule(delay: 3.0) {
                self.cyclePhrases()
            }
        }
    }

    private func schedule(delay: TimeInterval, _ action: @escaping () -> Void) {
        Task { @MainActor in
            let nanos = UInt64(delay * 1_000_000_000)
            try? await Task.sleep(nanoseconds: nanos)
            action()
        }
    }
}
