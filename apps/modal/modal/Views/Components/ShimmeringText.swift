import SwiftUI

/// A text view with a shimmering animation effect
struct ShimmeringText: View {
    let text: String
    var font: Font = .system(size: 16, weight: .medium)
    var shimmerColor: Color = .white
    var duration: Double = 2.0
    
    @State private var shimmerOffset: CGFloat = -1.0
    
    var body: some View {
        let textView = Text(text)
            .font(font)
            .foregroundColor(.secondary)
        
        textView
            .overlay(
                GeometryReader { geometry in
                    let shimmerWidth = geometry.size.width * 0.5
                    
                    shimmerGradient(width: shimmerWidth)
                        .offset(x: geometry.size.width * shimmerOffset)
                        .onAppear {
                            withAnimation(
                                .linear(duration: duration).repeatForever(autoreverses: false)
                            ) {
                                shimmerOffset = 1.5
                            }
                        }
                }
            )
            .mask(textView)
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

