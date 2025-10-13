//
//  LiveActivityManager.swift
//  modal
//
//  Manages Live Activities for the Modal app
//

import ActivityKit
import Foundation

/// Manager for controlling Live Activities
@Observable
class LiveActivityManager {
    // MARK: - Properties

    private(set) var currentActivity: Activity<ModalActivityAttributes>?
    private(set) var isActivityActive: Bool = false

    // MARK: - Singleton

    static let shared = LiveActivityManager()

    private init() {
        // Check for existing activities on init
        checkForExistingActivities()
    }

    // MARK: - Public Methods

    /// Start a new Live Activity
    func startActivity(initialState: ModalActivityAttributes.ContentState) {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            print("⚠️ Live Activities are not enabled")
            return
        }

        // End existing activity if any
        if currentActivity != nil {
            Task {
                await endActivity()
            }
        }

        do {
            let attributes = ModalActivityAttributes()
            let activity = try Activity.request(
                attributes: attributes,
                content: .init(state: initialState, staleDate: nil),
                pushType: nil
            )

            currentActivity = activity
            isActivityActive = true

            print("✅ Live Activity started: \(activity.id)")
        } catch {
            print("❌ Failed to start Live Activity: \(error)")
        }
    }

    /// Update the current Live Activity
    func updateActivity(newState: ModalActivityAttributes.ContentState) async {
        guard let activity = currentActivity else {
            print("⚠️ No active Live Activity to update")
            return
        }

        let content = ActivityContent(state: newState, staleDate: nil)

        await activity.update(content)
        print("✅ Live Activity updated")
    }

    /// End the current Live Activity
    func endActivity(dismissalPolicy: ActivityUIDismissalPolicy = .default) async {
        guard let activity = currentActivity else {
            print("⚠️ No active Live Activity to end")
            return
        }

        let finalState = ModalActivityAttributes.ContentState.idle()
        let finalContent = ActivityContent(state: finalState, staleDate: nil)

        await activity.end(finalContent, dismissalPolicy: dismissalPolicy)

        currentActivity = nil
        isActivityActive = false

        print("✅ Live Activity ended")
    }

    /// Update with Spotify track info
    func updateWithSpotifyTrack(name: String, artist: String, albumArt: String?, isPlaying: Bool) async {
        let track = ModalActivityAttributes.ContentState.Track(
            name: name,
            artist: artist,
            albumArt: albumArt,
            isPlaying: isPlaying
        )

        let newState = ModalActivityAttributes.ContentState.playingMusic(track: track)
        await updateActivity(newState: newState)
    }

    /// Update with task progress
    func updateWithTask(description: String, progress: Double?) async {
        let newState = ModalActivityAttributes.ContentState.executingTask(
            task: description,
            progress: progress
        )
        await updateActivity(newState: newState)
    }

    /// Set to listening state
    func setListening() async {
        let newState = ModalActivityAttributes.ContentState.listening()
        await updateActivity(newState: newState)
    }

    /// Set to idle state
    func setIdle() async {
        let newState = ModalActivityAttributes.ContentState.idle()
        await updateActivity(newState: newState)
    }

    // MARK: - Private Methods

    private func checkForExistingActivities() {
        let activities = Activity<ModalActivityAttributes>.activities
        if let activity = activities.first {
            currentActivity = activity
            isActivityActive = true
            print("ℹ️ Found existing Live Activity: \(activity.id)")
        }
    }
}

// MARK: - Convenience Methods

extension LiveActivityManager {
    /// Start Live Activity with idle state
    func start() {
        startActivity(initialState: .idle())
    }

    /// Quick update for common states
    func updateStatus(_ status: ModalActivityAttributes.ContentState.ActivityStatus, message: String) async {
        let newState = ModalActivityAttributes.ContentState(
            status: status,
            statusMessage: message,
            isPlayingMusic: false,
            currentTrack: nil,
            currentTask: message,
            taskProgress: nil,
            updatedAt: Date()
        )
        await updateActivity(newState: newState)
    }
}
