import SwiftUI

struct MusicPlaybackItem: Equatable {
    enum Platform: Equatable {
        case spotify
        case appleMusic
        case tidal
        case soundcloud
        case other(String)

        var displayName: String {
            switch self {
            case .spotify:
                return "Spotify"
            case .appleMusic:
                return "Apple Music"
            case .tidal:
                return "TIDAL"
            case .soundcloud:
                return "SoundCloud"
            case .other(let name):
                return name
            }
        }

        var symbolName: String {
            switch self {
            case .spotify:
                return "waveform"
            case .appleMusic:
                return "music.note"
            case .tidal:
                return "music.quarternote.3"
            case .soundcloud:
                return "cloud"
            case .other:
                return "music.note"
            }
        }
    }

    let title: String
    let artist: String
    let albumArtUrl: String?
    let isPlaying: Bool
    let elapsed: TimeInterval?
    let duration: TimeInterval?
    let platform: Platform
}

struct MusicMiniPlayer: View {
    let item: MusicPlaybackItem?
    var onPlayPause: (() -> Void)?
    var onNext: (() -> Void)?
    var onPrevious: (() -> Void)?
    var onRoute: (() -> Void)?

    @State private var appear = false

    var body: some View {
        if let item = item {
            playerCard(item: item)
                .opacity(appear ? 1 : 0)
                .offset(y: appear ? 0 : 16)
                .onAppear {
                    withAnimation(.spring(response: 0.45, dampingFraction: 0.8)) {
                        appear = true
                    }
                }
                .transition(.opacity.combined(with: .move(edge: .bottom)))
        }
    }

    private func playerCard(item: MusicPlaybackItem) -> some View {
        ZStack {
            backgroundArtwork(item: item)

            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(.ultraThinMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: 24, style: .continuous)
                        .stroke(Color.white.opacity(0.08), lineWidth: 1)
                )

            VStack(spacing: 16) {
                headerRow(item: item)

                progressRow(item: item)

                controlsRow(item: item)
            }
            .padding(18)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 170)
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .shadow(color: Color.black.opacity(0.35), radius: 14, x: 0, y: 10)
    }

    private func headerRow(item: MusicPlaybackItem) -> some View {
        HStack(spacing: 14) {
            artworkThumb(urlString: item.albumArtUrl)

            VStack(alignment: .leading, spacing: 6) {
                Text(item.title)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(.primary)
                    .lineLimit(1)

                Text(item.artist)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer()

            VStack(spacing: 6) {
                Image(systemName: item.platform.symbolName)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.secondary)

                Text(item.platform.displayName)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func progressRow(item: MusicPlaybackItem) -> some View {
        VStack(spacing: 8) {
            GeometryReader { proxy in
                let width = proxy.size.width
                let progress = normalizedProgress(item: item)
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(Color.white.opacity(0.18))
                        .frame(height: 4)
                    Capsule()
                        .fill(Color.white.opacity(0.75))
                        .frame(width: max(10, width * progress), height: 4)
                }
            }
            .frame(height: 4)

            HStack {
                Text(formatTime(item.elapsed ?? 0))
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)

                Spacer()

                Text("-\(formatTime(remainingTime(item)))")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func controlsRow(item: MusicPlaybackItem) -> some View {
        HStack(spacing: 28) {
            Button {
                onPrevious?()
            } label: {
                Image(systemName: "backward.fill")
                    .font(.system(size: 18, weight: .semibold))
            }

            Button {
                onPlayPause?()
            } label: {
                Image(systemName: item.isPlaying ? "pause.fill" : "play.fill")
                    .font(.system(size: 22, weight: .semibold))
            }

            Button {
                onNext?()
            } label: {
                Image(systemName: "forward.fill")
                    .font(.system(size: 18, weight: .semibold))
            }

            Spacer()

            Button {
                onRoute?()
            } label: {
                Image(systemName: "airplayaudio")
                    .font(.system(size: 18, weight: .semibold))
            }
        }
        .foregroundStyle(.primary)
    }

    private func backgroundArtwork(item: MusicPlaybackItem) -> some View {
        Group {
            if let urlString = item.albumArtUrl, let url = URL(string: urlString) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                            .blur(radius: 20)
                            .overlay(Color.black.opacity(0.35))
                    case .failure, .empty:
                        Color.black.opacity(0.65)
                    @unknown default:
                        Color.black.opacity(0.65)
                    }
                }
            } else {
                Color.black.opacity(0.65)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
    }

    private func artworkThumb(urlString: String?) -> some View {
        Group {
            if let urlString = urlString, let url = URL(string: urlString) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                    case .failure, .empty:
                        Color.white.opacity(0.15)
                    @unknown default:
                        Color.white.opacity(0.15)
                    }
                }
            } else {
                Color.white.opacity(0.15)
            }
        }
        .frame(width: 48, height: 48)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.white.opacity(0.1), lineWidth: 1)
        )
    }

    private func normalizedProgress(item: MusicPlaybackItem) -> CGFloat {
        guard let elapsed = item.elapsed, let duration = item.duration, duration > 0 else {
            return 0.3
        }
        return min(max(CGFloat(elapsed / duration), 0.05), 1.0)
    }

    private func remainingTime(_ item: MusicPlaybackItem) -> TimeInterval {
        guard let duration = item.duration else { return 0 }
        let elapsed = item.elapsed ?? 0
        return max(duration - elapsed, 0)
    }

    private func formatTime(_ seconds: TimeInterval) -> String {
        let totalSeconds = max(Int(seconds.rounded()), 0)
        let minutes = totalSeconds / 60
        let remaining = totalSeconds % 60
        return String(format: "%d:%02d", minutes, remaining)
    }
}
