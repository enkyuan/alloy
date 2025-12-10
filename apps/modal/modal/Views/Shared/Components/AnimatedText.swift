import SwiftUI

struct AnimatedText: View {
    enum AnimationStyle {
        case typing
        case fadeIn
        case shimmer
    }


    let text: String
    let style: AnimationStyle

    var show: Binding<Bool>?

    var fadeInText: String = ""
    var fadeInOpacity: Double = 1.0
    var fadeInBlur: CGFloat = 0
    var fadeInOffset: CGFloat = 0

    var font: Font = .system(size: 16, weight: .medium)
    var shimmerColor: Color = .white
    var shimmerDuration: Double = 2.0

    @State private var animatedText = ""
    @State private var shimmerOffset: CGFloat = -1.0


    var body: some View {
        switch style {
        case .typing:
            typingTextView
        case .fadeIn:
            fadeInTextView
        case .shimmer:
            shimmerText
        }
    }


    private var typingTextView: some View {
        Text(animatedText)
            .onChange(of: show?.wrappedValue ?? false) { _, newValue in
                if newValue { animateTyping() }
            }
    }

    private var fadeInTextView: some View {
        Text(fadeInText)
            .opacity(fadeInOpacity)
            .blur(radius: fadeInBlur)
            .offset(y: fadeInOffset)
    }

    private var shimmerText: some View {
        let textView = Text(text)
            .font(font)
            .foregroundColor(.secondary)

        return textView
            .overlay(
                GeometryReader { geometry in
                    let shimmerWidth = geometry.size.width * 0.5

                    shimmerGradient(width: shimmerWidth)
                        .offset(x: geometry.size.width * shimmerOffset)
                        .onAppear {
                            withAnimation(
                                .linear(duration: shimmerDuration).repeatForever(autoreverses: false)
                            ) {
                                shimmerOffset = 1.5
                            }
                        }
                }
            )
            .mask(textView)
    }


    private func animateTyping() {
        animatedText = ""
        let characters = Array(text)
        for (index, character) in characters.enumerated() {
            DispatchQueue.main.asyncAfter(deadline: .now() + Double(index) * 0.05) {
                animatedText.append(character)
            }
        }
    }

    private func shimmerGradient(width: CGFloat) -> some View {
        LinearGradient(
            colors: [.clear, shimmerColor.opacity(0.6), .clear],
            startPoint: .leading,
            endPoint: .trailing
        )
        .frame(width: width)
    }
}


extension AnimatedText {
    init(typing text: String, show: Binding<Bool>) {
        self.text = text
        self.style = .typing
        self.show = show
    }

    init(
        fadeIn text: String,
        opacity: Double = 1.0,
        blur: CGFloat = 0,
        offset: CGFloat = 0
    ) {
        self.text = text
        self.style = .fadeIn
        self.fadeInText = text
        self.fadeInOpacity = opacity
        self.fadeInBlur = blur
        self.fadeInOffset = offset
    }

    init(
        shimmer text: String,
        font: Font = .system(size: 16, weight: .medium),
        shimmerColor: Color = .white,
        duration: Double = 2.0
    ) {
        self.text = text
        self.style = .shimmer
        self.font = font
        self.shimmerColor = shimmerColor
        self.shimmerDuration = duration
    }
}
