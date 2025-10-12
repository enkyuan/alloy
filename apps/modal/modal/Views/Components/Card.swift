import SwiftUI

/// Unified card component for services and integrations
struct Card: View {
    // MARK: - Card Type
    
    enum CardType {
        case servicePreview(ServicePreviewData)
        case integration(IntegrationData)
    }
    
    // MARK: - Data Models
    
    struct ServicePreviewData {
        let iconName: String
        let serviceName: String
        let shimmerText: String
        let albumCover: String?
    }
    
    struct IntegrationData {
        let iconName: String
        let serviceName: String
        let description: String
        let isConnected: Bool
        let action: () -> Void
    }
    
    // MARK: - Properties
    
    let type: CardType
    
    // MARK: - Body
    
    var body: some View {
        switch type {
        case .servicePreview(let data):
            servicePreviewCard(data)
        case .integration(let data):
            integrationCard(data)
        }
    }
    
    // MARK: - Service Preview Card
    
    private func servicePreviewCard(_ data: ServicePreviewData) -> some View {
        Group {
            if let albumCover = data.albumCover {
                albumCardLayout(data: data, albumCover: albumCover)
            } else {
                standardCardLayout(data: data)
            }
        }
    }
    
    private func standardCardLayout(data: ServicePreviewData) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(data.iconName)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 20, height: 20)
                
                Text(data.serviceName)
                    .font(.system(size: 20, weight: .semibold))
            }
            
            AnimatedText(shimmer: data.shimmerText)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Color(uiColor: .secondarySystemBackground))
        .cornerRadius(12)
    }
    
    private func albumCardLayout(data: ServicePreviewData, albumCover: String) -> some View {
        HStack(spacing: 16) {
            Image(albumCover)
                .resizable()
                .aspectRatio(contentMode: .fill)
                .frame(width: 60, height: 60)
                .cornerRadius(8)
            
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 12) {
                    Image(data.iconName)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 20, height: 20)
                    
                    Text(data.serviceName)
                        .font(.system(size: 20, weight: .semibold))
                }
                
                AnimatedText(shimmer: data.shimmerText)
            }
            
            Spacer()
        }
        .padding(16)
        .background(Color(uiColor: .secondarySystemBackground))
        .cornerRadius(12)
    }
    
    // MARK: - Integration Card
    
    private func integrationCard(_ data: IntegrationData) -> some View {
        Button(action: data.action) {
            HStack(spacing: 16) {
                // Service icon
                Image(data.iconName)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 40, height: 40)
                
                // Service info
                VStack(alignment: .leading, spacing: 4) {
                    Text(data.serviceName)
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundColor(.primary)
                    
                    Text(data.description)
                        .font(.system(size: 14, weight: .regular))
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                
                Spacer()
                
                // Connection status
                connectionIndicator(isConnected: data.isConnected)
            }
            .padding(16)
            .background(Color(uiColor: .secondarySystemBackground))
            .cornerRadius(12)
        }
        .buttonStyle(.plain)
    }
    
    private func connectionIndicator(isConnected: Bool) -> some View {
        Group {
            if isConnected {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 20))
                    .foregroundColor(.green)
            } else {
                Image(systemName: "chevron.right")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.secondary)
            }
        }
    }
}

// MARK: - Convenience Initializers

extension Card {
    /// Create a service preview card
    static func servicePreview(
        iconName: String,
        serviceName: String,
        shimmerText: String,
        albumCover: String? = nil
    ) -> Card {
        Card(type: .servicePreview(ServicePreviewData(
            iconName: iconName,
            serviceName: serviceName,
            shimmerText: shimmerText,
            albumCover: albumCover
        )))
    }
    
    /// Create an integration card
    static func integration(
        iconName: String,
        serviceName: String,
        description: String,
        isConnected: Bool = false,
        action: @escaping () -> Void
    ) -> Card {
        Card(type: .integration(IntegrationData(
            iconName: iconName,
            serviceName: serviceName,
            description: description,
            isConnected: isConnected,
            action: action
        )))
    }
}

