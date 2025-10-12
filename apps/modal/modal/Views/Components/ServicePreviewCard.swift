import SwiftUI

/// A unified preview card for different services
struct ServicePreviewCard: View {
    enum ServiceType {
        case doordash
        case appleMusic
        case instacart
        
        var iconName: String {
            switch self {
            case .doordash: return "DoorDashIcon"
            case .appleMusic: return "AppleMusicIcon"
            case .instacart: return "InstacartIcon"
            }
        }
        
        var serviceName: String {
            switch self {
            case .doordash: return "DoorDash"
            case .appleMusic: return "Apple Music"
            case .instacart: return "Instacart"
            }
        }
        
        var shimmerText: String {
            switch self {
            case .doordash: return "Finding the nearest Pad Thai spot..."
            case .appleMusic: return "Playing Midnight City..."
            case .instacart: return "Adding paper towels to cart..."
            }
        }
        
        var albumCover: String? {
            switch self {
            case .appleMusic: return "M83AlbumCover"
            default: return nil
            }
        }
    }
    
    let service: ServiceType
    
    var body: some View {
        if let albumCover = service.albumCover {
            albumCardLayout(albumCover: albumCover)
        } else {
            standardCardLayout
        }
    }
    
    private var standardCardLayout: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(service.iconName)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 20, height: 20)
                
                Text(service.serviceName)
                    .font(.system(size: 20, weight: .semibold))
            }
            
            ShimmeringText(text: service.shimmerText)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Color(uiColor: .secondarySystemBackground))
        .cornerRadius(12)
    }
    
    private func albumCardLayout(albumCover: String) -> some View {
        HStack(spacing: 16) {
            Image(albumCover)
                .resizable()
                .aspectRatio(contentMode: .fill)
                .frame(width: 60, height: 60)
                .cornerRadius(8)
            
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 12) {
                    Image(service.iconName)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 20, height: 20)
                    
                    Text(service.serviceName)
                        .font(.system(size: 20, weight: .semibold))
                }
                
                ShimmeringText(text: service.shimmerText)
            }
            
            Spacer()
        }
        .padding(16)
        .background(Color(uiColor: .secondarySystemBackground))
        .cornerRadius(12)
    }
}

