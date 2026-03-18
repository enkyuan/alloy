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

struct MiniPlayer: View {
    let item: MusicPlaybackItem?
    var onPlayPause: (() -> Void)?
    var onNext: (() -> Void)?
    var onPrevious: (() -> Void)?
    var onRoute: (() -> Void)?

    @State private var appear = false
    @State private var cardScale: CGFloat = 1.0
    @State private var cardOpacity: Double = 1.0
    @State private var burstProgress: CGFloat = 0
    @State private var isBurstAnimating = false
    @State private var burstTask: Task<Void, Never>?

    var body: some View {
        if let item {
            let trackKey = trackIdentity(for: item)
            playerCard(item: item)
                .opacity(appear ? cardOpacity : 0)
                .scaleEffect(cardScale)
                .offset(y: appear ? 0 : 20)
                .overlay(burstOverlay(progress: burstProgress))
                .onAppear {
                    withAnimation(.spring(response: 0.42, dampingFraction: 0.84)) {
                        appear = true
                    }
                }
                .onChange(of: trackKey) { oldValue, newValue in
                    guard !oldValue.isEmpty, oldValue != newValue else { return }
                    triggerTrackChangeBurst()
                }
                .onDisappear {
                    burstTask?.cancel()
                }
                .transition(.opacity.combined(with: .move(edge: .bottom)))
        }
    }

    private func playerCard(item: MusicPlaybackItem) -> some View {
        ZStack {
            backgroundArtwork(item: item)

            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .fill(.ultraThinMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: 28, style: .continuous)
                        .stroke(Color.white.opacity(0.14), lineWidth: 1)
                )

            VStack(spacing: 14) {
                headerRow(item: item)
                progressRow(item: item)
                controlsRow(item: item)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 182)
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
        .shadow(color: .black.opacity(0.34), radius: 16, x: 0, y: 10)
    }

    private func headerRow(item: MusicPlaybackItem) -> some View {
        HStack(spacing: 12) {
            artworkThumb(urlString: item.albumArtUrl)

            VStack(alignment: .leading, spacing: 4) {
                Text(item.title)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(.white)
                    .lineLimit(1)

                Text(item.artist)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(.white.opacity(0.88))
                    .lineLimit(1)
            }

            Spacer()

            HStack(spacing: 6) {
                Image(systemName: item.platform.symbolName)
                    .font(.system(size: 11, weight: .semibold))
                Text(item.platform.displayName)
                    .font(.system(size: 11, weight: .semibold))
            }
            .foregroundStyle(.white.opacity(0.82))
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(Color.white.opacity(0.16), in: Capsule())
        }
    }

    private func progressRow(item: MusicPlaybackItem) -> some View {
        VStack(spacing: 6) {
            GeometryReader { proxy in
                let width = proxy.size.width
                let progress = normalizedProgress(item: item)

                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(Color.white.opacity(0.26))
                        .frame(height: 5)

                    Capsule()
                        .fill(Color.white.opacity(0.96))
                        .frame(width: max(12, width * progress), height: 5)
                }
            }
            .frame(height: 5)

            HStack {
                Text(formatTime(item.elapsed ?? 0))
                Spacer()
                Text("-\(formatTime(remainingTime(item)))")
            }
            .font(.system(size: 11, weight: .semibold))
            .foregroundStyle(.white.opacity(0.75))
        }
    }

    private func controlsRow(item: MusicPlaybackItem) -> some View {
        ZStack {
            HStack(spacing: 20) {
                Button(action: { onPrevious?() }) {
                    Image(systemName: "backward.fill")
                        .font(.system(size: 21, weight: .semibold))
                        .frame(width: 38, height: 38)
                }
                .buttonStyle(.plain)

                Button(action: { onPlayPause?() }) {
                    Image(systemName: item.isPlaying ? "pause.fill" : "play.fill")
                        .font(.system(size: 22, weight: .bold))
                        .frame(width: 46, height: 46)
                        .background(Color.white.opacity(0.22), in: Circle())
                        .overlay(
                            Circle()
                                .stroke(Color.white.opacity(0.3), lineWidth: 1)
                        )
                }
                .buttonStyle(.plain)

                Button(action: { onNext?() }) {
                    Image(systemName: "forward.fill")
                        .font(.system(size: 21, weight: .semibold))
                        .frame(width: 38, height: 38)
                }
                .buttonStyle(.plain)
            }
            .frame(maxWidth: .infinity, alignment: .center)

            HStack {
                Spacer()
                Button(action: { onRoute?() }) {
                    Image(systemName: "airplayaudio")
                        .font(.system(size: 17, weight: .semibold))
                        .frame(width: 32, height: 32)
                        .background(Color.white.opacity(0.12), in: Circle())
                }
                .buttonStyle(.plain)
            }
        }
        .foregroundStyle(.white)
    }

    private func trackIdentity(for item: MusicPlaybackItem) -> String {
        let normalizedTitle = item.title.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        let normalizedArtist = item.artist.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return "\(normalizedTitle)|\(normalizedArtist)"
    }

    private func triggerTrackChangeBurst() {
        guard !isBurstAnimating else { return }
        isBurstAnimating = true

        burstProgress = 0
        withAnimation(.easeIn(duration: 0.16)) {
            burstProgress = 1
            cardScale = 0.84
            cardOpacity = 0
        }

        burstTask?.cancel()
        burstTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: 180_000_000)
            guard !Task.isCancelled else { return }
            burstProgress = 0
            cardScale = 0.84
            cardOpacity = 0
            withAnimation(.spring(response: 0.44, dampingFraction: 0.78)) {
                cardScale = 1
                cardOpacity = 1
            }
            try? await Task.sleep(nanoseconds: 420_000_000)
            guard !Task.isCancelled else { return }
            isBurstAnimating = false
        }
    }

    @ViewBuilder
    private func burstOverlay(progress: CGFloat) -> some View {
        let normalized = max(0, min(progress, 1))
        let ringSize = CGFloat(12) + normalized * 24
        let travel = CGFloat(14) + normalized * 32
        let strokeOpacity = Double(max(0, 1 - normalized)) * 0.95

        ZStack {
            ForEach(0..<8, id: \.self) { index in
                let angle = (Double(index) / 8.0) * .pi * 2.0
                let x = CGFloat(cos(angle)) * travel
                let y = CGFloat(sin(angle)) * travel

                Circle()
                    .stroke(Color.white.opacity(strokeOpacity), lineWidth: 1.8)
                    .frame(width: ringSize, height: ringSize)
                    .offset(x: x, y: y)
            }
        }
        .opacity(normalized > 0 ? 1 : 0)
        .allowsHitTesting(false)
    }

    private func backgroundArtwork(item: MusicPlaybackItem) -> some View {
        Group {
            if let albumArtUrl = item.albumArtUrl,
                let url = URL(string: albumArtUrl)
            {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                            .blur(radius: 28)
                            .overlay(
                                LinearGradient(
                                    colors: [
                                        Color.black.opacity(0.35),
                                        Color.black.opacity(0.56),
                                    ],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                    case .empty, .failure:
                        lockscreenFallbackGradient
                    @unknown default:
                        lockscreenFallbackGradient
                    }
                }
            } else {
                lockscreenFallbackGradient
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
    }

    private var lockscreenFallbackGradient: some View {
        LinearGradient(
            colors: [
                Color(red: 0.13, green: 0.16, blue: 0.21),
                Color(red: 0.07, green: 0.09, blue: 0.12),
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    private func artworkThumb(urlString: String?) -> some View {
        Group {
            if let urlString,
                let url = URL(string: urlString)
            {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                    case .failure, .empty:
                        Color.white.opacity(0.16)
                    @unknown default:
                        Color.white.opacity(0.16)
                    }
                }
            } else {
                Color.white.opacity(0.16)
                    .overlay(
                        Image(systemName: "music.note")
                            .font(.system(size: 18, weight: .semibold))
                            .foregroundStyle(.white.opacity(0.65))
                    )
            }
        }
        .frame(width: 56, height: 56)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.white.opacity(0.14), lineWidth: 1)
        )
    }

    private func normalizedProgress(item: MusicPlaybackItem) -> CGFloat {
        guard let elapsed = item.elapsed,
            let duration = item.duration,
            duration > 0
        else {
            return item.isPlaying ? 0.35 : 0.0
        }

        return min(max(CGFloat(elapsed / duration), 0), 1)
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
