import SwiftUI

/// A styled authentication button with icon and text
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
    let action: () -> Void
    
    var body: some View {
        Button(action: action) {
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

