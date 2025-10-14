import SwiftUI

/// Custom stepper navigation component - self-contained like iOS TabView
struct StepperNavigation: View {
    // MARK: - Properties
    
    @State private var currentPage = 0
    private let content: [(icon: String, view: AnyView)]
    
    // MARK: - Initializer
    
    private init(pages: [(icon: String, view: AnyView)]) {
        self.content = pages
    }
    
    // MARK: - Body
    
    var body: some View {
        ZStack(alignment: .bottom) {
            // Custom swipeable pages (replaces TabView to fix NavigationStack safe area bug)
            GeometryReader { geometry in
                HStack(spacing: 0) {
                    ForEach(0..<content.count, id: \.self) { index in
                        content[index].view
                            .frame(width: geometry.size.width, height: geometry.size.height)
                    }
                }
                .offset(x: -CGFloat(currentPage) * geometry.size.width)
                .animation(.easeInOut(duration: 0.3), value: currentPage)
                .gesture(
                    DragGesture()
                        .onEnded { value in
                            let threshold: CGFloat = 50
                            if value.translation.width < -threshold && currentPage < content.count - 1 {
                                hapticFeedback()
                                currentPage += 1
                            } else if value.translation.width > threshold && currentPage > 0 {
                                hapticFeedback()
                                currentPage -= 1
                            }
                        }
                )
            }
            
            // Stepper indicators
            HStack(spacing: 12) {
                ForEach(0..<content.count, id: \.self) { index in
                    stepIndicator(for: index)
                        .onTapGesture {
                            hapticFeedback()
                            withAnimation(.easeInOut(duration: 0.3)) {
                                currentPage = index
                            }
                        }
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 20)
                    .fill(.ultraThinMaterial)
            )
            .padding(.bottom, 20)
        }
    }
    
    // MARK: - View Components
    
    @ViewBuilder
    private func stepIndicator(for index: Int) -> some View {
        let isActive = index == currentPage
        
        Image(systemName: content[index].icon)
            .font(.system(size: isActive ? 14 : 12, weight: isActive ? .semibold : .regular))
            .foregroundColor(isActive ? .primary : .primary.opacity(0.3))
            .scaleEffect(isActive ? 1.0 : 0.9)
            .animation(.spring(response: 0.3, dampingFraction: 0.7), value: isActive)
    }
    
    // MARK: - Helpers
    
    private func hapticFeedback() {
        let impact = UIImpactFeedbackGenerator(style: .light)
        impact.impactOccurred()
    }
}

// MARK: - Convenience Initializer

extension StepperNavigation {
    /// Creates a stepper navigation with pages
    static func pages<V0: View, V1: View>(
        _ page0: (icon: String, view: V0),
        _ page1: (icon: String, view: V1)
    ) -> StepperNavigation {
        let pages = [
            (icon: page0.icon, view: AnyView(page0.view)),
            (icon: page1.icon, view: AnyView(page1.view))
        ]
        return StepperNavigation(pages: pages)
    }
}
