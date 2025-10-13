//
//  ModalActivityAttributes.swift
//  modal
//
//  Live Activity attributes for displaying app state on Dynamic Island and Lock Screen
//

import ActivityKit
import Foundation

/// Attributes defining the Live Activity structure for Modal
struct ModalActivityAttributes: ActivityAttributes {
    // MARK: - Static Content (doesn't change during activity lifetime)

    /// Content that remains constant throughout the activity
    public struct ContentState: Codable, Hashable {
        // Current state
        var status: ActivityStatus
        var statusMessage: String

        // Spotify playback (if active)
        var isPlayingMusic: Bool
        var currentTrack: Track?

        // Task/command info
        var currentTask: String?
        var taskProgress: Double? // 0.0 to 1.0

        // Timestamp
        var updatedAt: Date

        // MARK: - Nested Types

        struct Track: Codable, Hashable {
            let name: String
            let artist: String
            let albumArt: String? // URL string
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

    // MARK: - Fixed Attributes

    /// User-facing name for the activity
    var activityName: String = "Modal Assistant"
}

// MARK: - Convenience Initializers

extension ModalActivityAttributes.ContentState {
    /// Create an idle state
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

    /// Create a listening state
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

    /// Create a processing state
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

    /// Create a music playing state
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

    /// Create a task execution state
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
