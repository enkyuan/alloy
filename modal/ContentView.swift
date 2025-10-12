import SwiftData
import SwiftUI
import UIKit

// MARK: - Main View

struct ContentView: View {
    var body: some View {
        OnboardingView()
    }
}

// MARK: - Onboarding View

struct OnboardingView: View {
    @State private var viewModel = OnboardingViewModel()

    var body: some View {
        VStack(spacing: 0) {
            conversationalTextSection
            previewCardSection
            Spacer()
            authenticationSection
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(.background)
        .onAppear { viewModel.startAnimations() }
    }

    // MARK: - View Components

    private var conversationalTextSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            AnimatedText(text: "Hey Modi,", show: $viewModel.showGreeting)
                .font(.system(size: 28, weight: .medium))
                .foregroundColor(.primary.opacity(0.9))

            Text(viewModel.currentPhrase)
                .font(.system(size: 28, weight: .medium))
                .foregroundColor(.primary.opacity(0.6))
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .opacity(viewModel.phraseOpacity)
                .blur(radius: viewModel.phraseBlur)
                .offset(y: viewModel.phraseOffset)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 32)
        .padding(.top, 80)
    }

    private var previewCardSection: some View {
        ZStack {
            switch viewModel.currentPhraseIndex {
            case 0: DoorDashPreviewCard()
            case 1: AppleMusicPreviewCard()
            case 2: InstacartPreviewCard()
            default: EmptyView()
            }
        }
        .opacity(viewModel.previewOpacity)
        .frame(height: 120)
        .padding(.top, 20)
        .padding(.horizontal, 32)
    }

    private var authenticationSection: some View {
        VStack(alignment: .leading, spacing: 24) {
            titleSection
            authButtonsSection
        }
        .padding(.bottom, 40)
    }

    private var titleSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Meet Modal")
                .font(.system(size: 32, weight: .bold))
                .foregroundColor(.primary)

            Text("Your agentic voice assistant")
                .font(.system(size: 17))
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 32)
        .padding(.bottom, 16)
    }

    private var authButtonsSection: some View {
        VStack(spacing: 12) {
            AuthButton(icon: .system("apple.logo"), text: "Continue with Apple", style: .primary)
            AuthButton(icon: .asset("GoogleIcon"), text: "Continue with Google", style: .secondary)
            AuthButton(icon: .asset("MailIcon"), text: "Continue with Email", style: .secondary)
        }
        .padding(.horizontal, 32)
    }
}

// MARK: - View Model

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

        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
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

// MARK: - Reusable Components

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

struct ShimmeringText: View {
    let text: String
    var font: Font = .system(size: 16, weight: .medium)
    var shimmerColor: Color = .white
    var duration: Double = 2.0

    @State private var shimmerOffset: CGFloat = -1.0

    var body: some View {
        // 1. Define the text view once to reuse it
        let textView = Text(text)
            .font(font)
            .foregroundColor(.secondary)

        textView
            .overlay(
                GeometryReader { geometry in
                    let shimmerWidth = geometry.size.width * 0.5

                    // 2. The shimmer gradient view
                    shimmerGradient(width: shimmerWidth)
                        .offset(x: geometry.size.width * shimmerOffset)
                        .onAppear {
                            withAnimation(
                                .linear(duration: duration).repeatForever(autoreverses: false),
                            ) {
                                shimmerOffset = 1.5
                            }
                        }
                },
            )
            .mask(textView) // 3. Mask with the original text view
    }

    // Helper function to create the gradient
    private func shimmerGradient(width: CGFloat) -> some View {
        LinearGradient(
            colors: [.clear, shimmerColor.opacity(0.6), .clear],
            startPoint: .leading,
            endPoint: .trailing,
        )
        .frame(width: width)
    }
}

struct AuthButton: View {
    enum IconType {
        case system(String)
        case asset(String)
        case none
    }

    enum ButtonStyle {
        case primary
        case secondary
    }

    let icon: IconType
    let text: String
    let style: ButtonStyle

    var body: some View {
        Button(action: {}) {
            HStack(spacing: 0) {
                iconView

                Text(text)
                    .font(.system(size: 17, weight: .semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.trailing, trailingPadding)
            }
            .frame(height: 56)
            .foregroundColor(style == .primary ? .white : .black)
            .background(style == .primary ? Color.black : Color.white)
            .overlay(borderOverlay)
            .cornerRadius(16)
        }
    }

    @ViewBuilder
    private var iconView: some View {
        switch icon {
        case let .system(name):
            Image(systemName: name)
                .font(.system(size: 20, weight: .medium))
                .frame(width: 20)
                .padding(.leading, 20)
        case let .asset(name):
            Image(name)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: 20, height: 20)
                .padding(.leading, 20)
        case .none:
            EmptyView()
        }
    }

    private var trailingPadding: CGFloat {
        if case .none = icon { return 0 }
        return 40
    }

    @ViewBuilder
    private var borderOverlay: some View {
        if style == .secondary {
            RoundedRectangle(cornerRadius: 16)
                .stroke(Color.gray.opacity(0.3), lineWidth: 1)
        }
    }
}

// MARK: - Preview Cards

struct DoorDashPreviewCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image("DoorDashIcon")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 20, height: 20)

                Text("DoorDash")
                    .font(.system(size: 20, weight: .semibold))
            }

            ShimmeringText(text: "Finding the nearest Pad Thai spot...")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Color(uiColor: .secondarySystemBackground))
        .cornerRadius(12)
    }
}

struct AppleMusicPreviewCard: View {
    var body: some View {
        HStack(spacing: 16) {
            Image("M83AlbumCover")
                .resizable()
                .aspectRatio(contentMode: .fill)
                .frame(width: 60, height: 60)
                .cornerRadius(8)

            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 12) {
                    Image("AppleMusicIcon")
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 20, height: 20)

                    Text("Apple Music")
                        .font(.system(size: 20, weight: .semibold))
                }

                ShimmeringText(text: "Playing Midnight City...")
            }

            Spacer()
        }
        .padding(16)
        .background(Color(uiColor: .secondarySystemBackground))
        .cornerRadius(12)
    }
}

struct InstacartPreviewCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image("InstacartIcon")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 20, height: 20)

                Text("Instacart")
                    .font(.system(size: 20, weight: .semibold))
            }

            ShimmeringText(text: "Adding paper towels to cart...")
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Color(UIColor.secondarySystemBackground))
        .cornerRadius(12)
    }
}

// MARK: - Previews

#Preview("Onboarding") {
    ContentView()
}
