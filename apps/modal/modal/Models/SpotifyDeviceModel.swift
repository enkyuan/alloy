import Foundation

struct SpotifyDevice: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let type: String
    let isActive: Bool
    let volumePercent: Int

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case type
        case isActive = "is_active"
        case volumePercent = "volume_percent"
    }

    var iconName: String {
        switch type.lowercased() {
        case "computer":
            return "desktopcomputer"
        case "smartphone":
            return "iphone"
        case "speaker":
            return "hifispeaker"
        case "tv":
            return "tv"
        case "avr":
            return "amplifier"
        case "stb":
            return "appletv"
        case "audio_dongle":
            return "airpodsmax"
        case "game_console":
            return "gamecontroller"
        case "cast_video":
            return "tv.and.mediabox"
        case "cast_audio":
            return "homepod"
        case "automobile":
            return "car"
        default:
            return "speaker.wave.2"
        }
    }
}
