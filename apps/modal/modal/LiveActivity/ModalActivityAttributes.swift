
import ActivityKit
import Foundation

struct ModalActivityAttributes: ActivityAttributes {

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


    var activityName: String = "Modal Assistant"
}


extension ModalActivityAttributes.ContentState {
    static func idle() -> Self {
        ModalActivityAttributes.ContentState(
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
        ModalActivityAttributes.ContentState(
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
        ModalActivityAttributes.ContentState(
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
        ModalActivityAttributes.ContentState(
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
        ModalActivityAttributes.ContentState(
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
