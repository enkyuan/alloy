import SwiftUI

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
        Card.servicePreview(
            iconName: service.iconName,
            serviceName: service.serviceName,
            shimmerText: service.shimmerText,
            albumCover: service.albumCover
        )
    }
}
