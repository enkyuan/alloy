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

    var body: some View {
        if let item {
            GeometryReader { geometry in
                playerCard(item: item, availableWidth: geometry.size.width)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .opacity(appear ? 1 : 0)
                    .offset(y: appear ? 0 : 12)
                    .onAppear {
                        withAnimation(.spring(response: 0.34, dampingFraction: 0.84)) {
                            appear = true
                        }
                    }
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
            }
            .frame(height: 60)
        }
    }

    private func playerCard(item: MusicPlaybackItem, availableWidth: CGFloat) -> some View {
        compactContent(item: item)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .frame(width: accessoryControlSpanWidth(for: availableWidth))
            .frame(height: 60)
            .background(miniPlayerBackdrop)
    }

    private func accessoryControlSpanWidth(for availableWidth: CGFloat) -> CGFloat {
        max(0, availableWidth - 24)
    }

    private var miniPlayerBackdrop: some View {
        let shape = RoundedRectangle(cornerRadius: 20, style: .continuous)

        return ZStack {
            shape
                .fill(.ultraThinMaterial)

            shape
                .fill(
                    LinearGradient(
                        colors: [
                            Color.black.opacity(0.32),
                            Color.black.opacity(0.2)
                        ],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )

            shape
                .fill(Color.black.opacity(0.14))
                .blur(radius: 14)
        }
    }

    private func compactContent(item: MusicPlaybackItem) -> some View {
        HStack(spacing: 10) {
            artworkThumb(urlString: item.albumArtUrl)

            VStack(alignment: .leading, spacing: 2) {
                Text(item.title)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(.white)
                    .lineLimit(1)

                Text(item.artist)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(.white.opacity(0.84))
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            NowPlayingWaveform(
                isPlaying: item.isPlaying,
                elapsed: item.elapsed,
                duration: item.duration
            )
        }
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
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(.white.opacity(0.65))
                    )
            }
        }
        .frame(width: 44, height: 44)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct NowPlayingWaveform: View {
    let isPlaying: Bool
    let elapsed: TimeInterval?
    let duration: TimeInterval?

    @State private var anchorElapsed: TimeInterval = 0
    @State private var anchorDate: Date = .now

    var body: some View {
        TimelineView(.animation(minimumInterval: isPlaying ? 1.0 / 24.0 : 0.25)) { context in
            let phase = waveformPhase(at: context.date)
            HStack(alignment: .center, spacing: 3) {
                ForEach(0..<4, id: \.self) { index in
                    let level = barLevel(index: index, phase: phase)
                    RoundedRectangle(cornerRadius: 1.6, style: .continuous)
                        .fill(Color.white.opacity(isPlaying ? 0.92 : 0.55))
                        .frame(width: 3, height: 7 + (14 * level))
                }
            }
            .frame(width: 22, height: 22, alignment: .center)
        }
        .onAppear {
            syncAnchor(with: elapsed ?? 0)
        }
        .onChange(of: elapsed) { _, newValue in
            if let newValue {
                syncAnchor(with: newValue)
            }
        }
        .onChange(of: isPlaying) { _, _ in
            syncAnchor(with: estimatedElapsed(at: .now))
        }
    }

    private func syncAnchor(with elapsedSeconds: TimeInterval) {
        anchorElapsed = max(0, elapsedSeconds)
        anchorDate = .now
    }

    private func estimatedElapsed(at date: Date) -> TimeInterval {
        if isPlaying {
            return max(0, anchorElapsed + date.timeIntervalSince(anchorDate))
        }
        return max(0, anchorElapsed)
    }

    private func waveformPhase(at date: Date) -> Double {
        let elapsedSeconds = estimatedElapsed(at: date)
        if let duration, duration > 0 {
            let normalized = (elapsedSeconds.truncatingRemainder(dividingBy: duration)) / duration
            return normalized * .pi * 10
        }
        return elapsedSeconds * .pi * 1.8
    }

    private func barLevel(index: Int, phase: Double) -> CGFloat {
        if !isPlaying {
            return [0.22, 0.48, 0.72, 0.42][index]
        }
        let offset = Double(index) * 0.9
        let oscillation = 0.5 + (0.5 * sin(phase + offset))
        return CGFloat(0.15 + (oscillation * 0.85))
    }
}
