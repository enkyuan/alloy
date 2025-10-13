import SwiftUI

/// Reusable empty state view component
struct EmptyStateView: View {
    // MARK: - Properties
    
    let iconName: String
    let title: String
    let subtitle: String
    let buttonTitle: String
    let buttonAction: () -> Void
    
    // MARK: - Body
    
    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            Spacer()
            
            // Icon
            Image(iconName)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: 80, height: 80)
            
            VStack(alignment: .leading, spacing: 12) {
                // Title
                Text(title)
                    .font(.system(size: 28, weight: .bold))
                
                // Subtitle
                Text(subtitle)
                    .font(.system(size: 17))
                    .foregroundColor(.secondary)
            }
            
            // Action Button
            Button(action: buttonAction) {
                Text(buttonTitle)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity)
                    .frame(height: 56)
                    .background(Color.blue)
                    .cornerRadius(16)
            }
            .padding(.top, 8)
            
            Spacer()
        }
        .padding(.horizontal, 40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(uiColor: .systemBackground))
    }
}

#Preview {
    EmptyStateView(
        iconName: "ModalIcon",
        title: "No Items Yet",
        subtitle: "Add items to get started",
        buttonTitle: "Add Item",
        buttonAction: { }
    )
}

