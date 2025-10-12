import SwiftUI

/// View model for the onboarding screen
@Observable
class OnboardingViewModel {
    // MARK: - Properties
    
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
    
    // MARK: - Public Methods
    
    func startAnimations() {
        withAnimation(.easeIn(duration: 0.8)) {
            showGreeting = true
        }
        
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            self.showFirstPhrase()
        }
    }
    
    // MARK: - Private Methods
    
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
        
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
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
        
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
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
            
            DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
                self.cyclePhrases()
            }
        }
    }
}

