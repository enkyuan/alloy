
import ActivityKit
import Foundation

<<<<<<< HEAD:apps/modal/modal/LiveActivity/ModalActivityAttributes.swift
struct ModalActivityAttributes: ActivityAttributes {
=======
struct HavenOSActivityAttributes: ActivityAttributes {
>>>>>>> codex/refactor:apps/milo/milo/LiveActivity/MiloActivityAttributes.swift

    public struct ContentState: Codable, Hashable {
        var status: ActivityStatus
        var statusMessage: String

        var isPlayingMusic: Bool
        var currentTrack: Track?

        var currentTask: String?
        var taskProgress: Double?

        var updatedAt: Date


        struct Track: Codable, Hashable {
            let name: String
            let artist: String
            let albumArt: String?
            let isPlaying: Bool
        }

        enum ActivityStatus: String, Codable, Hashable {
            case idle = "Idle"
            case listening = "Listening"
            case processing = "Processing"
            case playingMusic = "Playing Music"
            case executingTask = "Executing Task"
            case error = "Error"
        }
    }


<<<<<<< HEAD:apps/modal/modal/LiveActivity/ModalActivityAttributes.swift
    var activityName: String = "Modal Assistant"
}


extension ModalActivityAttributes.ContentState {
=======
    var activityName: String = "Milo Assistant"
}


extension HavenOSActivityAttributes.ContentState {
>>>>>>> codex/refactor:apps/milo/milo/LiveActivity/MiloActivityAttributes.swift
    static func idle() -> Self {
        HavenOSActivityAttributes.ContentState(
            status: .idle,
            statusMessage: "Ready",
            isPlayingMusic: false,
            currentTrack: nil,
            currentTask: nil,
            taskProgress: nil,
            updatedAt: Date()
        )
    }

    static func listening() -> Self {
        HavenOSActivityAttributes.ContentState(
            status: .listening,
            statusMessage: "Listening...",
            isPlayingMusic: false,
            currentTrack: nil,
            currentTask: nil,
            taskProgress: nil,
            updatedAt: Date()
        )
    }

    static func processing(message: String) -> Self {
        HavenOSActivityAttributes.ContentState(
            status: .processing,
            statusMessage: message,
            isPlayingMusic: false,
            currentTrack: nil,
            currentTask: message,
            taskProgress: nil,
            updatedAt: Date()
        )
    }

    static func playingMusic(track: Track) -> Self {
        HavenOSActivityAttributes.ContentState(
            status: .playingMusic,
            statusMessage: "Now Playing",
            isPlayingMusic: true,
            currentTrack: track,
            currentTask: nil,
            taskProgress: nil,
            updatedAt: Date()
        )
    }

    static func executingTask(task: String, progress: Double?) -> Self {
        HavenOSActivityAttributes.ContentState(
            status: .executingTask,
            statusMessage: task,
            isPlayingMusic: false,
            currentTrack: nil,
            currentTask: task,
            taskProgress: progress,
            updatedAt: Date()
        )
    }
}
