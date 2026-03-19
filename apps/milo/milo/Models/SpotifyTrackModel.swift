
import Foundation

struct SpotifyTrack: Codable, Identifiable {
    let id: String
    let name: String
    let artist: String
    let album: String
    let uri: String
    let albumArtUrl: String?
    let durationMs: Int

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case artist
        case album
        case uri
        case albumArtUrl = "album_art_url"
        case durationMs = "duration_ms"
    }
}
