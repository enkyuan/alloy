import AppIntents
import Foundation

struct OpenSpotifyIntent: AppIntent {
    static var title: LocalizedStringResource = "Open Spotify"
    static var description = IntentDescription(
        "Opens Spotify and returns to Milo after authorization.")
    static var openAppWhenRun: Bool = true

    func perform() async throws -> some IntentResult {
        await MainActor.run {
            SpotifyAppService.shared.openSpotifyAndReturnToMilo()
        } 
        return .result(dialog: "Opening Spotify")
    }
}

struct PlayMusicIntent: AppIntent {
    static var title: LocalizedStringResource = "Play Music"
    static var description = IntentDescription("Resumes playback on Spotify via Milo.")
    static var openAppWhenRun: Bool = true  // Opens Spotify to enable playback

    func perform() async throws -> some IntentResult {
        await MainActor.run {
            SpotifyAppService.shared.authorizeAndPlay(uri: "")
        }
        return .result(dialog: "Resuming music")
    }
}

struct PauseMusicIntent: AppIntent {
    static var title: LocalizedStringResource = "Pause Music"
    static var description = IntentDescription("Pauses playback on Spotify via Milo.")
    static var openAppWhenRun: Bool = false

    func perform() async throws -> some IntentResult {
        await SpotifyAppService.shared.pause()
        return .result(dialog: "Pausing music")
    }
}

struct NextTrackIntent: AppIntent {
    static var title: LocalizedStringResource = "Next Track"
    static var description = IntentDescription("Skips to the next track on Spotify via Milo.")
    static var openAppWhenRun: Bool = false

    func perform() async throws -> some IntentResult {
        await SpotifyAppService.shared.skipNext()
        return .result(dialog: "Skipping to next track")
    }
}

struct PreviousTrackIntent: AppIntent {
    static var title: LocalizedStringResource = "Previous Track"
    static var description = IntentDescription("Skips to the previous track on Spotify via Milo.")
    static var openAppWhenRun: Bool = false

    func perform() async throws -> some IntentResult {
        await SpotifyAppService.shared.skipPrevious()
        return .result(dialog: "Skipping to previous track")
    }
}
