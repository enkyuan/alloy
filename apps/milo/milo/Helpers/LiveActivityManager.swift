
import ActivityKit
import Foundation

@MainActor
@Observable
class LiveActivityManager {

    private(set) var currentActivity: Activity<MiloActivityAttributes>?
    private(set) var isActivityActive: Bool = false


    static let shared = LiveActivityManager()

    private init() {
        checkForExistingActivities()
    }


    func startActivity(initialState: MiloActivityAttributes.ContentState) {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            print("Live Activities are not enabled")
            return
        }

        guard #available(iOS 16.1, *) else {
            print("Live Activities require iOS 16.1 or later")
            return
        }

        if currentActivity != nil {
            Task {
                await endActivity()
            }
        }

        do {
            let attributes = MiloActivityAttributes()
            let activity = try Activity.request(
                attributes: attributes,
                content: .init(state: initialState, staleDate: nil),
                pushType: nil
            )

            currentActivity = activity
            isActivityActive = true

            print("Live Activity started: \(activity.id)")
        } catch {
            print("Failed to start Live Activity: \(error)")

            if #available(iOS 16.1, *) {
                let nsError = error as NSError
                switch nsError.code {
                case -1:
                    print("Live Activities may be disabled in Settings")
                case -2:
                    print("Too many activity updates - throttled by system")
                default:
                    print("Error code: \(nsError.code), description: \(nsError.localizedDescription)")
                }
            }
        }
    }

    func updateActivity(newState: MiloActivityAttributes.ContentState) async {
        guard let activity = currentActivity else {
            print("No active Live Activity to update")
            return
        }

        let content = ActivityContent(state: newState, staleDate: nil)

        await activity.update(content)
        print("Live Activity updated")
    }

    func endActivity(dismissalPolicy: ActivityUIDismissalPolicy = .default) async {
        guard let activity = currentActivity else {
            print("No active Live Activity to end")
            return
        }

        let finalState = MiloActivityAttributes.ContentState.idle()
        let finalContent = ActivityContent(state: finalState, staleDate: nil)

        await activity.end(finalContent, dismissalPolicy: dismissalPolicy)

        currentActivity = nil
        isActivityActive = false

        print("Live Activity ended")
    }

    func updateWithSpotifyTrack(name: String, artist: String, albumArt: String?, isPlaying: Bool) async {
        let track = MiloActivityAttributes.ContentState.Track(
            name: name,
            artist: artist,
            albumArt: albumArt,
            isPlaying: isPlaying
        )

        let newState = MiloActivityAttributes.ContentState.playingMusic(track: track)
        await updateActivity(newState: newState)
    }

    func updateWithTask(description: String, progress: Double?) async {
        let newState = MiloActivityAttributes.ContentState.executingTask(
            task: description,
            progress: progress
        )
        await updateActivity(newState: newState)
    }

    func setListening() async {
        let newState = MiloActivityAttributes.ContentState.listening()
        await updateActivity(newState: newState)
    }

    func setIdle() async {
        let newState = MiloActivityAttributes.ContentState.idle()
        await updateActivity(newState: newState)
    }


    private func checkForExistingActivities() {
        let activities = Activity<MiloActivityAttributes>.activities
        if let activity = activities.first {
            currentActivity = activity
            isActivityActive = true
            print("Found existing Live Activity: \(activity.id)")
        }
    }
}


extension LiveActivityManager {
    func start() {
        startActivity(initialState: .idle())
    }

    func updateStatus(_ status: MiloActivityAttributes.ContentState.ActivityStatus, message: String) async {
        let newState = MiloActivityAttributes.ContentState(
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
