//
//  SpotifyPlaybackCard.swift
//  modal
//
//  Displays current Spotify track information
//

import SwiftUI

/// Card displaying currently playing Spotify track
struct SpotifyPlaybackCard: View {
    let track: SpotifyTrack?
    @State private var opacity: Double = 0
    @State private var offset: CGFloat = 20
    
    var body: some View {
        if let track = track {
            albumCardLayout(track: track)
                .opacity(opacity)
                .offset(y: offset)
                .onAppear {
                    withAnimation(.spring(response: 0.5, dampingFraction: 0.7)) {
                        opacity = 1.0
                        offset = 0
                    }
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
        }
    }
    
    private func albumCardLayout(track: SpotifyTrack) -> some View {
        HStack(spacing: 16) {
            // Album art or skeleton
            if let albumArtUrl = track.albumArtUrl,
               let url = URL(string: albumArtUrl) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .empty:
                        Skeleton(width: 60, height: 60, cornerRadius: 8)
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                            .frame(width: 60, height: 60)
                            .cornerRadius(8)
                    case .failure:
                        albumArtPlaceholder
                    @unknown default:
                        albumArtPlaceholder
                    }
                }
            } else {
                albumArtPlaceholder
            }
            
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 12) {
                    Image("SpotifyIcon")
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 20, height: 20)
                    
                    Text("Spotify")
                        .font(.system(size: 20, weight: .semibold))
                }
                
                VStack(alignment: .leading, spacing: 4) {
                    Text(track.name)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.primary)
                        .lineLimit(1)
                    
                    Text(track.artist)
                        .font(.system(size: 12, weight: .regular))
                        .foregroundColor(.secondary)
                        .lineLimit(1)
                }
            }
            
            Spacer()
        }
        .padding(16)
        .background(Color(uiColor: .secondarySystemBackground))
        .cornerRadius(12)
    }
    
    private var albumArtPlaceholder: some View {
        RoundedRectangle(cornerRadius: 8)
            .fill(Color.gray.opacity(0.2))
            .frame(width: 60, height: 60)
            .overlay(
                Image(systemName: "music.note")
                    .font(.system(size: 24))
                    .foregroundColor(.gray)
            )
    }
}

#Preview {
    VStack(spacing: 20) {
        SpotifyPlaybackCard(track: nil)
    }
    .padding()
}
