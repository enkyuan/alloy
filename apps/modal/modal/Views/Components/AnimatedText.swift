import SwiftUI

/// A text view that animates character-by-character
struct AnimatedText: View {
    let text: String
    @Binding var show: Bool
    @State private var animatedText = ""
    
    var body: some View {
        Text(animatedText)
            .onChange(of: show) { _, newValue in
                if newValue { animateText() }
            }
    }
    
    private func animateText() {
        animatedText = ""
        let characters = Array(text)
        for (index, character) in characters.enumerated() {
            DispatchQueue.main.asyncAfter(deadline: .now() + Double(index) * 0.05) {
                animatedText.append(character)
            }
        }
    }
}

