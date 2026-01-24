import SwiftUI

struct AuthButton: View {
    @SwiftUI.Environment(\.colorScheme) private var colorScheme

    enum IconType {
        case system(String)
        case asset(String)
        case none
    }

    enum Style {
        case primary
        case secondary
    }

    let icon: IconType
    let text: String
    let style: Style
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
            .foregroundColor(foregroundColor)
            .background(backgroundColor)
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
                .foregroundColor(foregroundColor)
                .padding(.leading, 20)
        case let .asset(name):
            Image(name)
                .resizable()
                .renderingMode(.template)
                .aspectRatio(contentMode: .fit)
                .frame(width: 20, height: 20)
                .foregroundColor(foregroundColor)
                .padding(.leading, 20)
        case .none:
            EmptyView()
        }
    }

    private var foregroundColor: Color {
        switch style {
        case .primary:
            return colorScheme == .dark ? .black : .white
        case .secondary:
            return colorScheme == .dark ? .white : .black
        }
    }

    private var backgroundColor: Color {
        switch style {
        case .primary:
            return colorScheme == .dark ? .white : .black
        case .secondary:
            return colorScheme == .dark ? Color(.systemGray6) : .white
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
                .stroke(Color.gray.opacity(colorScheme == .dark ? 0.5 : 0.3), lineWidth: 1)
        }
    }
}
